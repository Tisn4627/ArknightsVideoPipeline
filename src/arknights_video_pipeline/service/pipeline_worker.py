"""
service.pipeline_worker - 流水线后台工作线程

在 QThread 中运行 Pipeline，并通过 Qt 信号向主界面反馈状态。

注：本模块位于 service 层而非 gui 层，因为它是流水线执行的并发单元，
本质属于服务层职责。gui 层通过 PipelineService 间接使用。
"""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from arknights_video_pipeline.core.logger import setup_logger
from arknights_video_pipeline.core.pipeline import Pipeline
from arknights_video_pipeline.core.step_defs import STEPS_BY_KEY
from arknights_video_pipeline.service.config_proxy import ConfigProxy


class QtLogHandler(logging.Handler):
    """将日志记录转发为 Qt 信号的 Handler"""

    def __init__(self, signal: pyqtSignal) -> None:
        super().__init__()
        self._signal = signal

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._signal.emit(record.levelname, msg)
        except Exception:
            self.handleError(record)


class PipelineWorker(QThread):
    """流水线工作线程

    通过回调钩子（on_step_start / on_step_finish / is_cancelled）将
    Pipeline 的步骤执行进度桥接为 Qt 信号，避免 monkey-patch（修复 M17）。
    """

    step_started = pyqtSignal(str, str)
    step_finished = pyqtSignal(str, bool, float, list)
    progress_updated = pyqtSignal(int, str)
    log_emitted = pyqtSignal(str, str)
    pipeline_finished = pyqtSignal(bool, dict, bool)

    def __init__(
        self,
        video_path: str,
        config_proxy: ConfigProxy,
        background_image_path: str | None = None,
        skip_steps: set[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._video_path = video_path
        self._config_proxy = config_proxy
        self._background_image_path = background_image_path
        self._skip_steps = skip_steps or set()
        self._cancelled = False
        self._log_handler: QtLogHandler | None = None

    def cancel(self) -> None:
        self._cancelled = True
        self.log_emitted.emit("INFO", "用户请求取消，将在当前步骤结束后停止")

    def run(self) -> None:
        report_dict: dict[str, Any] = {}
        success = False
        pipeline: Pipeline | None = None

        # 安装日志桥接
        logger = setup_logger("pipeline")
        self._log_handler = QtLogHandler(self.log_emitted)
        self._log_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(self._log_handler)

        try:
            # 合并 GUI 覆盖项
            self._config_proxy.config_manager.merge_cli_overrides(
                self._config_proxy.build_overrides()
            )

            pipeline = Pipeline(
                video_path=self._video_path,
                config_mgr=self._config_proxy.config_manager,
                logger=logger,
                background_image_path=self._background_image_path,
                skip_steps=self._skip_steps,
                # 通过回调钩子注入步骤事件（替代 monkey-patch，修复 M17）
                on_step_start=self._on_step_start,
                on_step_finish=self._on_step_finish,
                is_cancelled=lambda: self._cancelled,
            )

            self.log_emitted.emit("INFO", "开始运行流水线...")
            success = pipeline.run()
            report_dict = pipeline.report.to_dict()

        except Exception as exc:
            logger.error(f"流水线异常: {exc}")
            try:
                report_dict = pipeline.report.to_dict() if pipeline else {}
            except Exception:
                report_dict = {}
            success = False
        finally:
            if self._log_handler is not None:
                logger.removeHandler(self._log_handler)
                self._log_handler = None
            # 确保完成信号一定发射，避免 UI 卡在"运行中"状态
            self.pipeline_finished.emit(success, report_dict, self._cancelled)

    # ── Pipeline 回调实现 ──────────────────────────────────
    # 这些方法由 Pipeline.run 在步骤开始/结束时调用，
    # 将事件转发为 Qt 信号供 UI 层订阅。

    def _on_step_start(self, step_key: str, step_desc: str) -> None:
        """步骤开始回调：发射 step_started 与 progress_updated 信号"""
        step = STEPS_BY_KEY.get(step_key)
        percent = step.percent if step else 0
        self.step_started.emit(step_key, step_desc)
        self.progress_updated.emit(percent, f"正在执行：{step_desc}")

    def _on_step_finish(
        self, step_key: str, success: bool, elapsed: float, warnings: list
    ) -> None:
        """步骤结束回调：发射 step_finished 信号"""
        self.step_finished.emit(step_key, success, elapsed, warnings)
