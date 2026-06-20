"""
service.pipeline_service - 流水线服务

对 GUI 暴露统一的流水线运行接口，管理后台工作线程生命周期。
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
    """流水线应用服务"""

    step_started = pyqtSignal(str, str)
    step_finished = pyqtSignal(str, bool, float, list)
    progress_updated = pyqtSignal(int, str)
    log_emitted = pyqtSignal(str, str)
    pipeline_finished = pyqtSignal(bool, dict, bool)
    validation_failed = pyqtSignal(list)

    def __init__(self, config_proxy: ConfigProxy, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config_proxy
        self._worker: PipelineWorker | None = None

    # ── 输入校验 ──────────────────────────────────────────

    def validate_inputs(self) -> list[str]:
        """校验当前配置是否可运行，返回错误列表（空表示通过）"""
        errors: list[str] = []

        video_path = self._config.video_path()
        if not video_path:
            errors.append("请选择输入视频文件")
        elif not os.path.exists(video_path):
            errors.append(f"视频文件不存在: {video_path}")
        else:
            ext = os.path.splitext(video_path)[1].lower()
            if ext not in SUPPORTED_VIDEO_EXTENSIONS:
                errors.append(f"不受支持的视频格式: {ext}")
            else:
                try:
                    validate_video_file(video_path)
                except VideoValidationError as exc:
                    errors.append(str(exc))

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
        if maa_path:
            # 宽松校验：路径存在即可，具体有效性由核心引擎处理
            if not os.path.exists(maa_path):
                errors.append(f"MAA 路径不存在: {maa_path}")

        return errors

    # ── 运行控制 ──────────────────────────────────────────

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def run_pipeline(self) -> bool:
        """启动流水线。启动前会自动校验输入。

        Returns:
            True 表示已成功启动工作线程；False 表示因校验失败或已有任务运行而未启动。
        """
        if self.is_running():
            return False

        # 启动前自动校验输入，避免调用方遗漏
        errors = self.validate_inputs()
        if errors:
            self.validation_failed.emit(errors)
            return False

        self._worker = PipelineWorker(
            video_path=self._config.video_path(),
            config_proxy=self._config,
            background_image_path=self._config.background_image(),
            skip_steps=self._config.skip_steps(),
            parent=self,
        )
        self._worker.step_started.connect(self.step_started)
        self._worker.step_finished.connect(self.step_finished)
        self._worker.progress_updated.connect(self.progress_updated)
        self._worker.log_emitted.connect(self.log_emitted)
        self._worker.pipeline_finished.connect(self._on_pipeline_finished)
        self._worker.start()
        return True

    def cancel_pipeline(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()

    def wait_for_shutdown(self, timeout_ms: int = 3000) -> None:
        """等待工作线程退出，避免 QThread 被销毁时仍在运行

        Args:
            timeout_ms: 最大等待时间（毫秒），超时后强制返回
        """
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(timeout_ms)

    def _on_pipeline_finished(self, success: bool, report_dict: dict[str, Any], cancelled: bool) -> None:
        self.pipeline_finished.emit(success, report_dict, cancelled)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
