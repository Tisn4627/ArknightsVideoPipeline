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

from PyQt6.QtCore import QObject, pyqtSignal

from arknights_video_pipeline.core.config import ConfigManager
from arknights_video_pipeline.core.pipeline import Pipeline
from arknights_video_pipeline.service.pipeline_worker import _PipelineWorkerBase

# Recognition 模式固定跳过的步骤：仅保留 copilot（步骤1）
_RECOGNIZE_SKIP_STEPS: set[str] = {"formation", "actions", "track", "compose"}


class RecognitionWorker(_PipelineWorkerBase):
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

    recognition_finished = pyqtSignal(bool, str, bool)

    _error_label = "识别异常"

    def __init__(
        self,
        video_path: str,
        config_manager: ConfigManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(video_path, config_manager, parent=parent)
        self._json_path = ""

    def cancel(self) -> None:
        """请求取消：在当前步骤边界退出

        与 PipelineWorker 的区别：此处额外发射一条提示日志。识别工具
        每次仅运行单个 worker，不存在 PipelineService 并发模式下多个
        worker 各刷一条相同日志的刷屏问题，保留提示便于用户确认取消
        已被接受。
        """
        self._cancel_event.set()
        self.log_emitted.emit("INFO", "用户请求取消，将在当前步骤结束后停止")

    def _log_run_start(self) -> None:
        self.log_emitted.emit("INFO", "开始视频识别...")

    def _build_pipeline(self, logger: logging.Logger) -> Pipeline:
        return Pipeline(
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

    def _collect_result(self, pipeline: Pipeline, logger: logging.Logger,
                        success: bool) -> None:
        if success and pipeline.copilot_json_path:
            self._json_path = pipeline.copilot_json_path

    def _emit_finished(self, success: bool) -> None:
        self.recognition_finished.emit(
            success, self._json_path, self._cancel_event.is_set()
        )
