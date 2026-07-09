"""
service.pipeline_service - 流水线应用服务（批量原生）

对 GUI 暴露统一的批量流水线运行接口，串行调度多个 ``PipelineWorker``
（一次仅运行一个，避免 MAA 资源争用），并通过带文件索引的 Qt 信号
反馈每个文件及整体进度。

单文件视为长度为 1 的批量。单文件失败标记 failed 后自动推进下一文件；
取消请求在当前文件结束后停止后续文件。
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
    file_finished = pyqtSignal(int, bool, dict)               # index, success, report
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
        self._worker: PipelineWorker | None = None
        # 批次状态
        self._queue: list[str] = []          # 待处理视频路径（按用户顺序）
        self._current_index: int = -1        # 正在处理的文件索引
        self._success_count: int = 0
        self._cancelled: bool = False
        # 每个文件对总体进度的贡献值：等待=0、运行=P、完成=100
        self._contributions: list[int] = []
        # 每个文件当前进度百分比（用于 file_progress，失败时停留）
        self._file_percents: list[int] = []

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
        return self._worker is not None and self._worker.isRunning()

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

        # 初始化批次状态
        self._queue = list(video_paths)
        self._current_index = -1
        self._success_count = 0
        self._cancelled = False
        self._contributions = [0] * len(self._queue)
        self._file_percents = [0] * len(self._queue)

        self.log_emitted.emit("INFO", f"开始批量处理：共 {len(self._queue)} 个文件")
        self._emit_overall()
        self._start_next()
        return True

    def cancel_pipeline(self) -> None:
        """请求取消：当前文件结束后停止后续文件"""
        self._cancelled = True
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        else:
            # 无运行中的 worker，直接结束批次
            self._finish_batch()

    def wait_for_shutdown(self, timeout_ms: int = 3000) -> None:
        """等待工作线程退出，避免 QThread 被销毁时仍在运行"""
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(timeout_ms)

    # ── 内部：worker 调度 ─────────────────────────────────

    def _start_next(self) -> None:
        """启动队列中下一个文件的 worker"""
        if self._cancelled:
            self._finish_batch()
            return

        self._current_index += 1
        if self._current_index >= len(self._queue):
            self._finish_batch()
            return

        idx = self._current_index
        video_path = self._queue[idx]
        self._contributions[idx] = 0
        self._file_percents[idx] = 0

        self.file_started.emit(idx, video_path)
        self.file_progress.emit(idx, 0, "处理中")
        self._emit_overall()
        self.log_emitted.emit("INFO", f"[{idx + 1}/{len(self._queue)}] 开始处理: {video_path}")

        self._worker = PipelineWorker(
            video_path=video_path,
            config_proxy=self._config,
            background_image_path=self._config.background_image(),
            skip_steps=self._config.skip_steps(),
            parent=self,
        )
        # 连接 worker 信号到带文件索引的服务信号
        self._worker.step_started.connect(
            lambda step_key, step_desc, i=idx: self._on_step_started(i, step_key, step_desc)
        )
        self._worker.step_finished.connect(
            lambda step_key, success, elapsed, warnings, i=idx:
                self.step_finished.emit(i, step_key, success, elapsed, warnings)
        )
        self._worker.progress_updated.connect(
            lambda percent, msg, i=idx: self._on_file_progress(i, percent, msg)
        )
        self._worker.log_emitted.connect(self.log_emitted)
        self._worker.pipeline_finished.connect(
            lambda success, report, cancelled, i=idx:
                self._on_worker_finished(i, success, report, cancelled)
        )
        self._worker.start()

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
        if success:
            self._success_count += 1
            self._file_percents[idx] = 100
        # 无论成功失败，已处理完毕的文件对总体进度贡献 100
        self._contributions[idx] = 100

        if success:
            self.file_progress.emit(idx, 100, "已完成")
        self.file_finished.emit(idx, success, report_dict)
        self.log_emitted.emit(
            "INFO" if success else "ERROR",
            f"[{idx + 1}/{len(self._queue)}] "
            f"{'处理完成' if success else '处理失败'}: {self._queue[idx]}",
        )
        self._emit_overall()

        # 清理当前 worker
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

        # 取消或已到队尾 → 结束批次；否则启动下一个
        if cancelled or self._cancelled:
            self._cancelled = True
            self._finish_batch()
            return
        self._start_next()

    def _emit_overall(self) -> None:
        """计算并发射总体进度"""
        n = len(self._queue)
        if n == 0:
            return
        total = sum(self._contributions)
        percent = total // n
        # 当前处理中的文件序号（1-based）
        done = sum(1 for c in self._contributions if c >= 100)
        processing = 0 if self._current_index >= n or self._contributions[self._current_index] >= 100 else 1
        current = done + processing
        message = f"Processing {current}/{n}"
        self.overall_progress.emit(percent, message)

    def _finish_batch(self) -> None:
        """批次结束：发射 batch_finished"""
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
        self._current_index = -1
        self._contributions = []
        self._file_percents = []
        self._cancelled = False
