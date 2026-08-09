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
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from arknights_video_pipeline.core.exceptions import VideoValidationError, ImageValidationError
from arknights_video_pipeline.core.utils import (
    PROJECT_ROOT,
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

    def __init__(self, config_proxy: ConfigProxy, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config_proxy
        # 并发池：按文件索引保存正在运行的 worker
        self._workers: dict[int, PipelineWorker] = {}
        # 批次状态
        self._queue: list[str] = []          # 待处理视频路径（按用户顺序）
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

    # ── 输入校验 ──────────────────────────────────────────

    def validate_batch(self, video_paths: list[str]) -> list[str]:
        """校验批量输入是否可运行，返回错误列表（空表示通过）

        背景板图片与 MAA 路径对整批共享，仅校验一次；每个视频单独校验。
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

    # 保留单文件校验入口（向后兼容，等价于长度为 1 的批量）
    def validate_inputs(self) -> list[str]:
        video_path = self._config.video_path()
        return self.validate_batch([video_path] if video_path else [])

    # ── 运行控制 ──────────────────────────────────────────

    def is_running(self) -> bool:
        return len(self._workers) > 0

    def run_pipeline(self, video_paths: list[str]) -> bool:
        """启动批量流水线。

        Args:
            video_paths: 按用户顺序排列的视频路径列表

        Returns:
            True 表示已成功启动；False 表示因校验失败或已有任务运行而未启动。
        """
        if self.is_running():
            return False

        errors = self.validate_batch(video_paths)
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
        # 若没有任何运行中的 worker（例如取消时队列尚未派发），直接结束批次
        if not self._workers:
            self._finish_batch()

    def wait_for_shutdown(self, timeout_ms: int = 3000) -> None:
        """等待所有工作线程退出，避免 QThread 被销毁时仍在运行"""
        for worker in list(self._workers.values()):
            if worker.isRunning():
                worker.wait(timeout_ms)

    def force_terminate_workers(self, timeout_ms: int = 2000) -> None:
        """强制终止所有仍在运行的工作线程。

        wait_for_shutdown 超时后的兜底手段。worker.cancel() 仅在步骤边界
        检查 cancel_event，长步骤（MAA ~320s、track ~358s、compose ~360s）
        不会在短超时内响应。QThread.terminate() 立即终止线程，可能留下
        未释放的资源，但确保进程不会因非 daemon QThread 阻塞而无法退出。
        """
        for idx, worker in list(self._workers.items()):
            if worker.isRunning():
                self.log_emitted.emit(
                    "WARNING",
                    f"工作线程 {idx} 在超时后仍未退出，强制终止",
                )
                worker.terminate()
                worker.wait(timeout_ms)
            self._workers.pop(idx, None)

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
                    parent=self,
                )
            except Exception as exc:
                self.log_emitted.emit(
                    "ERROR",
                    f"[{idx + 1}/{len(self._queue)}] 创建工作线程失败: {exc}",
                )
                self.file_started.emit(idx, video_path)
                self.file_progress.emit(idx, 0, "处理失败")
                self.file_finished.emit(idx, False, {"error": str(exc)}, False)
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
        self._file_percents[idx] = percent
        self._contributions[idx] = percent
        self.file_progress.emit(idx, percent, message)
        self._emit_overall()

    def _on_worker_finished(self, idx: int, success: bool,
                            report_dict: dict[str, Any], cancelled: bool) -> None:
        """单个 worker 完成回调"""
        cancelled = cancelled or self._cancelled
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

        # 清理该 worker
        worker = self._workers.pop(idx, None)
        if worker is not None:
            worker.deleteLater()

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
        self._next_dispatch_index = 0
        self._workers = {}
        self._contributions = []
        self._file_percents = []
        self._cancelled = False
        self._max_concurrent = 1
