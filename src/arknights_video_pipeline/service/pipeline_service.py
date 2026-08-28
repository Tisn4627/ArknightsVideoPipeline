"""
service.pipeline_service - 流水线应用服务（批量 + 可选并发）

对 GUI 暴露统一的批量流水线运行接口，调度多个 ``PipelineWorker``。
默认串行（``multithreading=false``，一次仅运行一个，避免 MAA 资源争用）；
启用多线程后按 ``max_concurrent`` 上限并发派发，超出部分入队等待空位。

调度模型：
- ``_queue`` 保存全部待处理视频路径（按用户顺序）；
- ``_next_dispatch_index`` 指向下一个尚未派发的文件；
- ``_workers`` 保存当前正在运行的 worker（按文件索引键）；
- 所有状态变更（派发、完成、计数）均发生在 GUI 主线程的 Qt 信号槽中，
  worker 仅通过信号回报，因此无需显式锁。

单文件视为长度为 1 的批量。单个文件失败标记 failed 后不影响其他并行
任务；取消请求会停止队列后续派发，已在运行的 worker 在当前步骤结束后退出。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from arknights_video_pipeline.core.exceptions import VideoValidationError, ImageValidationError
from arknights_video_pipeline.core.utils import (
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    validate_video_file,
    validate_image_file,
)
from arknights_video_pipeline.service.config_proxy import ConfigProxy
from arknights_video_pipeline.service.pipeline_worker import PipelineWorker


class PipelineService(QObject):
    """批量流水线应用服务"""

    # ── 单文件级信号（第一个参数始终为文件在队列中的索引） ──
    file_started = pyqtSignal(int, str)                       # index, video_path
    file_progress = pyqtSignal(int, int, str)                 # index, percent, message
    file_finished = pyqtSignal(int, bool, dict, bool)  # idx, success, report, cancelled
    step_started = pyqtSignal(int, str, str)                  # index, step_key, step_desc
    step_finished = pyqtSignal(int, str, bool, float, list)   # index, step_key, success, elapsed, warnings

    # ── 批次级信号 ──
    overall_progress = pyqtSignal(int, str)                   # percent, message
    batch_finished = pyqtSignal(int, int, bool)               # success_count, total_count, cancelled
    log_emitted = pyqtSignal(str, str)
    validation_failed = pyqtSignal(list)
    # 后台校验完成（errors 为空列表表示通过）
    validation_finished = pyqtSignal(list)

    def __init__(self, config_proxy: ConfigProxy, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config_proxy
        # 并发池：按文件索引保存正在运行的 worker
        self._workers: dict[int, PipelineWorker] = {}
        # 批次状态
        self._queue: list[str] = []          # 待处理视频路径（按用户顺序）
        self._json_map: dict[int, str | None] = {}  # 文件索引 → 自定义作业JSON（None=未绑定）
        self._next_dispatch_index: int = 0   # 下一个待派发的文件索引
        self._success_count: int = 0
        self._cancelled: bool = False
        # 每个文件对总体进度的贡献值：等待=0、运行=P、完成=100
        self._contributions: list[int] = []
        # 每个文件当前进度百分比（用于 file_progress，失败时停留）
        self._file_percents: list[int] = []
        # 并发参数（每次 run_pipeline 时从配置读取）
        self._max_concurrent: int = 1
        # 批次活跃标志：用于 _finish_batch 幂等保护，防止 worker.cancel()
        # 同步触发 finished 信号导致 _finish_batch 被重复调用
        self._batch_active: bool = False
        # 后台校验进行中标志（防止重复发起校验）
        self._validating: bool = False

    # ── 输入校验 ──────────────────────────────────────────

    def validate_batch(self, video_paths: list[str],
                       json_paths: list[str | None] | None = None) -> list[str]:
        """校验批量输入是否可运行，返回错误列表（空表示通过）

        背景板图片与 MAA 路径对整批共享，仅校验一次；每个视频单独校验。
        ``json_paths`` 与 ``video_paths`` 平行对齐，校验绑定的自定义作业 JSON。
        """
        errors: list[str] = []

        if not video_paths:
            errors.append("请至少添加一个视频文件")
            return errors

        for idx, video_path in enumerate(video_paths, start=1):
            prefix = f"[{idx}] "
            if not video_path:
                errors.append(f"{prefix}视频文件路径为空")
                continue
            if not os.path.exists(video_path):
                errors.append(f"{prefix}视频文件不存在: {video_path}")
                continue
            ext = os.path.splitext(video_path)[1].lower()
            if ext not in SUPPORTED_VIDEO_EXTENSIONS:
                errors.append(f"{prefix}不受支持的视频格式: {ext}")
                continue
            try:
                validate_video_file(video_path)
            except VideoValidationError as exc:
                errors.append(f"{prefix}{exc}")

        # 自定义作业 JSON：绑定后跳过视频识别，文件必须存在且为 .json
        if json_paths:
            # 两列表必须平行对齐（GUI 侧含 None 占位）；错位时自定义
            # 作业会静默绑定到错误的视频，必须在启动前拦截
            if len(json_paths) != len(video_paths):
                errors.append(
                    f"视频列表({len(video_paths)})与JSON列表"
                    f"({len(json_paths)})长度不一致，无法确定对应关系"
                )
            else:
                for idx, json_path in enumerate(json_paths, start=1):
                    if not json_path:
                        continue
                    prefix = f"[{idx}] "
                    if not os.path.exists(json_path):
                        errors.append(f"{prefix}自定义作业JSON文件不存在: {json_path}")
                        continue
                    ext = os.path.splitext(json_path)[1].lower()
                    if ext != ".json":
                        errors.append(f"{prefix}自定义作业JSON必须是 .json 文件: {json_path}")

        # 背景板图片：style1 必填，整批共享
        if self._config.style() == "style1":
            bg_path = self._config.background_image()
            if not bg_path:
                errors.append("style1 需要背景板图片，请选择背景板图片")
            elif not os.path.exists(bg_path):
                errors.append(f"背景板图片不存在: {bg_path}")
            else:
                ext = os.path.splitext(bg_path)[1].lower()
                if ext not in SUPPORTED_IMAGE_EXTENSIONS:
                    errors.append(f"不受支持的图片格式: {ext}")
                else:
                    try:
                        validate_image_file(bg_path)
                    except ImageValidationError as exc:
                        errors.append(str(exc))

        maa_path = self._config.maa_path()
        if maa_path and not os.path.exists(maa_path):
            errors.append(f"MAA 路径不存在: {maa_path}")

        return errors

    def validate_batch_async(self, video_paths: list[str],
                             json_paths: list[str | None] | None = None) -> bool:
        """在后台线程执行 validate_batch，完成后发射 validation_finished

        validate_video_file 内部为同步 ffprobe 子进程调用（单文件超时
        上限 60 秒），在 GUI 主线程串行校验大量文件会长时间冻结界面，
        故移至后台线程执行；结果经 Qt 排队信号投递回主线程接收方。

        Returns:
            True 表示已开始后台校验；False 表示正在校验或已有任务运行。
        """
        if self._validating or self.is_running():
            return False
        self._validating = True

        def _run_validation() -> None:
            try:
                errors = self.validate_batch(video_paths, json_paths)
            except Exception as exc:  # 兜底：异常不能吞掉导致 UI 永久等待
                errors = [f"输入校验发生异常: {exc}"]
            finally:
                self._validating = False
            # 跨线程 emit：Qt 自动以排队连接投递到主线程
            self.validation_finished.emit(errors)

        threading.Thread(
            target=_run_validation, daemon=True, name="batch-validation"
        ).start()
        return True

    # ── 运行控制 ──────────────────────────────────────────

    def is_running(self) -> bool:
        return len(self._workers) > 0

    def run_pipeline(self, video_paths: list[str],
                     json_paths: list[str | None] | None = None,
                     validate: bool = True) -> bool:
        """启动批量流水线。

        Args:
            video_paths: 按用户顺序排列的视频路径列表
            json_paths: 与 video_paths 平行对齐的自定义作业 JSON 路径列表
                （None 表示该视频未绑定，仍执行视频识别）
            validate: 是否执行输入校验。调用方刚通过 validate_batch_async
                完成校验时传 False，避免同一批次 ffprobe 重复探测

        Returns:
            True 表示已成功启动；False 表示因校验失败或已有任务运行而未启动。
        """
        if self.is_running():
            return False

        if validate:
            errors = self.validate_batch(video_paths, json_paths)
            if errors:
                self.validation_failed.emit(errors)
                return False

        # 读取并发配置：关闭或上限 <=1 时退化为完全串行（max_concurrent=1）
        if self._config.multithreading():
            self._max_concurrent = max(1, self._config.max_concurrent())
        else:
            self._max_concurrent = 1

        # 初始化批次状态
        self._queue = list(video_paths)
        self._json_map = {
            i: (json_paths[i] if json_paths and i < len(json_paths) else None)
            for i in range(len(self._queue))
        }
        self._next_dispatch_index = 0
        self._success_count = 0
        self._cancelled = False
        self._contributions = [0] * len(self._queue)
        self._file_percents = [0] * len(self._queue)
        self._batch_active = True

        mode = "并发" if self._max_concurrent > 1 else "串行"
        self.log_emitted.emit(
            "INFO",
            f"开始批量处理（{mode}，上限 {self._max_concurrent}）："
            f"共 {len(self._queue)} 个文件",
        )
        self._emit_overall()
        self._dispatch_next()
        return True

    def cancel_pipeline(self) -> None:
        """请求取消：停止队列后续派发，已在运行的 worker 在当前步骤结束后退出"""
        self._cancelled = True
        # 取消所有正在运行的 worker
        for worker in list(self._workers.values()):
            if worker.isRunning():
                worker.cancel()
        # 取消提示只发一次（worker.cancel 不再各自发，避免并发模式下刷屏）
        if self._workers:
            self.log_emitted.emit("INFO", "用户请求取消，将在当前步骤结束后停止")
        # 若没有任何运行中的 worker（例如取消时队列尚未派发），直接结束批次
        if not self._workers:
            self._finish_batch()

    def wait_for_shutdown(self, timeout_ms: int = 3000) -> None:
        """等待所有工作线程退出，避免 QThread 被销毁时仍在运行

        使用统一 deadline 分摊等待预算：串行逐个 wait(timeout) 时最坏
        阻塞主线程 N×timeout；改为共享截止时间后总等待不超过 timeout_ms。
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        for worker in list(self._workers.values()):
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            if worker.isRunning():
                worker.wait(remaining_ms)

    def force_terminate_workers(self, timeout_ms: int = 2000) -> None:
        """强制终止所有仍在运行的工作线程。

        wait_for_shutdown 超时后的兜底手段。worker.cancel() 仅在步骤边界
        检查 cancel_event，长步骤（MAA ~320s、track ~358s、compose ~360s）
        不会在短超时内响应。QThread.terminate() 立即终止线程，可能留下
        未释放的资源，但确保进程不会因非 daemon QThread 阻塞而无法退出。

        与 wait_for_shutdown 一致使用统一 deadline 分摊等待预算，
        N 个 worker 的总阻塞时间不超过 timeout_ms（而非 N×timeout_ms）。
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        for idx, worker in list(self._workers.items()):
            if worker.isRunning():
                self.log_emitted.emit(
                    "WARNING",
                    f"工作线程 {idx} 在超时后仍未退出，强制终止",
                )
                worker.terminate()
                remaining_ms = max(1, min(timeout_ms, round((deadline - time.monotonic()) * 1000)))
                worker.wait(remaining_ms)
            self._workers.pop(idx, None)
            # terminate 后线程已停止（或 wait 超时后即将被销毁），安全清理
            worker.deleteLater()

    # ── 内部：worker 调度 ─────────────────────────────────

    def _dispatch_next(self) -> None:
        """按 max_concurrent 上限派发队列中尚未启动的文件

        串行模式下 _max_concurrent=1，行为与原 _start_next 等价：
        一次仅一个 worker 在运行，待其完成后再派发下一个。
        """
        while (
            not self._cancelled
            and self._next_dispatch_index < len(self._queue)
            and len(self._workers) < self._max_concurrent
        ):
            idx = self._next_dispatch_index
            self._next_dispatch_index += 1

            video_path = self._queue[idx]
            self._contributions[idx] = 0
            self._file_percents[idx] = 0

            # 先创建 worker，成功后再发射信号；创建失败时跳过该文件，
            # 避免 worker 不入 _workers 却已通知 UI "处理中" 导致批次卡死。
            try:
                worker_config = self._config.build_worker_config()
                worker = PipelineWorker(
                    video_path=video_path,
                    config_manager=worker_config,
                    background_image_path=self._config.background_image(),
                    skip_steps=self._config.skip_steps(),
                    copilot_json_path=self._json_map.get(idx),
                    parent=self,
                )
            except Exception as exc:
                self.log_emitted.emit(
                    "ERROR",
                    f"[{idx + 1}/{len(self._queue)}] 创建工作线程失败: {exc}",
                )
                self.file_started.emit(idx, video_path)
                self.file_progress.emit(idx, 0, "处理失败")
                # 与正常路径 report.to_dict() 的结构保持一致，
                # 避免消费者需要处理两种互不兼容的 schema
                failure_report = {
                    "video_path": video_path,
                    "video_name": os.path.basename(video_path),
                    "output_dir": "",
                    "pipeline_status": "failed",
                    "total_elapsed": 0.0,
                    "timestamp": "",
                    "steps": [],
                    "output_files": {},
                    "warnings": [f"创建工作线程失败: {exc}"],
                }
                self.file_finished.emit(idx, False, failure_report, False)
                self._contributions[idx] = 100
                continue

            self._workers[idx] = worker
            self.file_started.emit(idx, video_path)
            self.file_progress.emit(idx, 0, "处理中")
            self.log_emitted.emit(
                "INFO",
                f"[{idx + 1}/{len(self._queue)}] 开始处理: {video_path}",
            )

            # 连接 worker 信号到带文件索引的服务信号
            worker.step_started.connect(
                lambda step_key, step_desc, i=idx: self._on_step_started(i, step_key, step_desc)
            )
            worker.step_finished.connect(
                lambda step_key, success, elapsed, warnings, i=idx:
                    self.step_finished.emit(i, step_key, success, elapsed, warnings)
            )
            worker.progress_updated.connect(
                lambda percent, msg, i=idx: self._on_file_progress(i, percent, msg)
            )
            worker.log_emitted.connect(self.log_emitted)
            worker.pipeline_finished.connect(
                lambda success, report, cancelled, i=idx:
                    self._on_worker_finished(i, success, report, cancelled)
            )
            worker.start()

        self._emit_overall()
        # 若所有文件均创建失败（无在途 worker 且队列已耗尽），需收尾批次
        if self._next_dispatch_index >= len(self._queue) and not self._workers:
            self._finish_batch()

    def _on_step_started(self, idx: int, step_key: str, step_desc: str) -> None:
        self.step_started.emit(idx, step_key, step_desc)

    def _on_file_progress(self, idx: int, percent: int, message: str) -> None:
        # 与 _on_worker_finished 相同的迟到信号防护（进度信号同样可能
        # 在批次收尾后到达）
        if not self._batch_active or idx >= len(self._file_percents):
            return
        self._file_percents[idx] = percent
        self._contributions[idx] = percent
        self.file_progress.emit(idx, percent, message)
        self._emit_overall()

    def _on_worker_finished(self, idx: int, success: bool,
                            report_dict: dict[str, Any], cancelled: bool) -> None:
        """单个 worker 完成回调"""
        # 迟到信号防护：force_terminate 后批次状态已被 _finish_batch 清空，
        # 但 worker 的 finally 块仍可能抢在线程死亡前发射 pipeline_finished；
        # 此时批次已结束或索引越界，直接忽略，避免 IndexError 与重复信号
        if not self._batch_active or idx >= len(self._queue):
            return
        # 注意：批次取消状态（self._cancelled）仅用于停止后续派发，
        # 不覆盖该文件自身的失败语义——worker 已失败完成的文件仍按
        # "处理失败"上报，避免丢失失败事实
        if success:
            self._success_count += 1
            self._file_percents[idx] = 100
        else:
            message = "已取消" if cancelled else "处理失败"
            self.file_progress.emit(idx, self._file_percents[idx], message)
        # 无论成功失败，已处理完毕的文件对总体进度贡献 100
        self._contributions[idx] = 100

        if success:
            self.file_progress.emit(idx, 100, "已完成")
        self.file_finished.emit(idx, success, report_dict, cancelled)
        status_text = "处理完成" if success else ("已取消" if cancelled else "处理失败")
        self.log_emitted.emit(
            "INFO" if success else "ERROR",
            f"[{idx + 1}/{len(self._queue)}] {status_text}: {self._queue[idx]}",
        )

        # 清理该 worker：调度簿记立即移除；对象销毁以 QThread.finished
        # 为锚点——pipeline_finished 在 run() 的 finally 中发射，排队
        # 抵达主线程时线程可能尚未完成内部收尾，此时 deleteLater 会
        # 销毁仍在运行的 QThread（Qt 文档警告可致崩溃）
        worker = self._workers.pop(idx, None)
        if worker is not None:
            if worker.isFinished():
                worker.deleteLater()
            else:
                worker.finished.connect(worker.deleteLater)

        # 取消请求：不再派发新任务，等待所有在途 worker 结束后收尾
        if cancelled or self._cancelled:
            self._cancelled = True
            if not self._workers:
                self._finish_batch()
            else:
                self._emit_overall()
            return

        # 继续派发队列中剩余文件（填补空出的并发槽位）
        self._dispatch_next()

        # 队列耗尽且无在途 worker → 结束批次
        if self._next_dispatch_index >= len(self._queue) and not self._workers:
            self._finish_batch()

    def _emit_overall(self) -> None:
        """计算并发射总体进度"""
        n = len(self._queue)
        if n == 0:
            return
        total = sum(self._contributions)
        percent = total // n
        # 已完成的文件数
        done = sum(1 for c in self._contributions if c >= 100)
        # 当前在途（已派发但未完成）的文件数 = 活跃 worker 数
        active = len(self._workers)
        current = done + active
        message = f"Processing {current}/{n}"
        self.overall_progress.emit(percent, message)

    def _finish_batch(self) -> None:
        """批次结束：发射 batch_finished

        幂等保护：worker.cancel() 若同步触发 pipeline_finished，会导致
        _on_worker_finished 在 cancel_pipeline 调用栈内先行收尾，随后
        cancel_pipeline 末尾的 ``if not self._workers`` 又会再次调用本方法。
        通过 _batch_active 标志确保仅第一次调用生效，避免 batch_finished
        被重复发射且用已清空的 _queue 计算出错误的 total。
        """
        if not self._batch_active:
            return
        self._batch_active = False

        total = len(self._queue)
        self.log_emitted.emit(
            "INFO",
            f"批量处理结束：成功 {self._success_count}/{total}"
            + ("（已取消）" if self._cancelled else ""),
        )
        self.overall_progress.emit(100, f"Completed {self._success_count}/{total}")
        self.batch_finished.emit(self._success_count, total, self._cancelled)
        # 重置批次状态（保留 config 不变）
        self._queue = []
        self._json_map = {}
        self._next_dispatch_index = 0
        self._workers = {}
        self._contributions = []
        self._file_percents = []
        self._cancelled = False
        self._max_concurrent = 1
