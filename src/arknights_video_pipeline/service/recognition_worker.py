"""
service.recognition_worker - Recognition 独立识别后台工作线程

在 QThread 中仅执行流水线的步骤1（视频转 copilot JSON），跳过编队/操作/
跟踪/合成四步。复用 ``Pipeline`` 与回调钩子机制，将执行进度桥接为 Qt 信号。

与 ``PipelineWorker`` 的区别：
- 固定 ``skip_steps={formation, actions, track, compose}``，仅跑 copilot 步骤；
- 不需要背景板图片（``background_image_path=None``）；
- 不接受 ``copilot_json_path``（识别模式是产出 JSON，而非消费 JSON）；
- 完成信号携带生成的 copilot JSON 路径，便于 UI 直接展示与打开。

线程安全：与 PipelineWorker 一致，接收独立的 ``ConfigManager`` 快照
（由 ``ConfigProxy.build_worker_config`` 在主线程深拷贝生成），不从子线程
读写共享的 ConfigProxy。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from arknights_video_pipeline.core.config import ConfigManager
from arknights_video_pipeline.core.logger import setup_logger
from arknights_video_pipeline.core.pipeline import Pipeline
from arknights_video_pipeline.core.step_defs import STEPS_BY_KEY
from arknights_video_pipeline.service.pipeline_worker import QtLogHandler

# Recognition 模式固定跳过的步骤：仅保留 copilot（步骤1）
_RECOGNIZE_SKIP_STEPS: set[str] = {"formation", "actions", "track", "compose"}


class RecognitionWorker(QThread):
    """Recognition 独立识别工作线程

    Signals:
        step_started(step_key, step_desc): 步骤开始
        step_finished(step_key, success, elapsed, warnings): 步骤结束
        progress_updated(percent, message): 进度更新
        log_emitted(level, message): 日志输出
        recognition_finished(success, json_path, cancelled): 识别完成
            - success: 是否成功
            - json_path: 生成的 copilot JSON 绝对路径（失败时为空字符串）
            - cancelled: 是否被用户取消
    """

    step_started = pyqtSignal(str, str)
    step_finished = pyqtSignal(str, bool, float, list)
    progress_updated = pyqtSignal(int, str)
    log_emitted = pyqtSignal(str, str)
    recognition_finished = pyqtSignal(bool, str, bool)

    def __init__(
        self,
        video_path: str,
        config_manager: ConfigManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._video_path = video_path
        self._config_manager = config_manager
        self._cancel_event = threading.Event()
        self._log_handler: QtLogHandler | None = None

    def cancel(self) -> None:
        """请求取消：在当前步骤边界退出（与 PipelineWorker 一致）"""
        self._cancel_event.set()
        self.log_emitted.emit("INFO", "用户请求取消，将在当前步骤结束后停止")

    def run(self) -> None:
        json_path = ""
        success = False
        pipeline: Pipeline | None = None
        logger: logging.Logger | None = None

        try:
            # 安装日志桥接（thread_ident 必须在 worker 线程内获取）
            worker_thread_ident = threading.get_ident()
            logger = setup_logger("pipeline")
            self._log_handler = QtLogHandler(self.log_emitted, worker_thread_ident)
            self._log_handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(self._log_handler)

            pipeline = Pipeline(
                video_path=self._video_path,
                config_mgr=self._config_manager,
                logger=logger,
                background_image_path=None,  # 识别模式无需背景板图片
                skip_steps=_RECOGNIZE_SKIP_STEPS,
                copilot_json_path=None,  # 识别模式是产出 JSON，不接受输入
                on_step_start=self._on_step_start,
                on_step_finish=self._on_step_finish,
                is_cancelled=lambda: self._cancel_event.is_set(),
            )

            self.log_emitted.emit("INFO", "开始视频识别...")
            success = pipeline.run()
            if success and pipeline.copilot_json_path:
                json_path = pipeline.copilot_json_path
        except Exception as exc:
            if logger is not None:
                logger.error(f"识别异常: {exc}")
            success = False
        finally:
            if logger is not None and self._log_handler is not None:
                logger.removeHandler(self._log_handler)
                self._log_handler = None
            # 确保完成信号一定发射，避免 UI 卡在"运行中"状态
            self.recognition_finished.emit(
                success, json_path, self._cancel_event.is_set()
            )

    # ── Pipeline 回调实现 ──────────────────────────────────

    def _on_step_start(self, step_key: str, step_desc: str) -> None:
        """步骤开始回调：发射 step_started 与 progress_updated 信号"""
        step = STEPS_BY_KEY.get(step_key)
        percent = step.percent if step else 0
        self.step_started.emit(step_key, step_desc)
        self.progress_updated.emit(percent, f"正在执行：{step_desc}")

    def _on_step_finish(
        self, step_key: str, success: bool, elapsed: float, warnings: list[str]
    ) -> None:
        """步骤结束回调：发射 step_finished 信号"""
        self.step_finished.emit(step_key, success, elapsed, warnings)
