"""
service.pipeline_worker - 流水线后台工作线程

在 QThread 中运行 Pipeline，并通过 Qt 信号向主界面反馈状态。

注：本模块位于 service 层而非 gui 层，因为它是流水线执行的并发单元，
本质属于服务层职责。gui 层通过 PipelineService 间接使用。

线程安全：每个 worker 接收独立的 ``ConfigManager`` 快照（由
``ConfigProxy.build_worker_config`` 在主线程深拷贝生成），不再从子线程
读写共享的 ConfigProxy。日志 handler 按 thread ident 过滤，确保多 worker
共享 ``pipeline`` logger 时各自只收到本线程的日志记录，避免重复发射。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from arknights_video_pipeline.core.config import PIPELINE_DEFAULTS, ConfigManager
from arknights_video_pipeline.core.logger import setup_logger
from arknights_video_pipeline.core.pipeline import Pipeline
from arknights_video_pipeline.core.step_defs import STEPS_BY_KEY


class _PipelineWorkerBase(QThread):
    """PipelineWorker 与 RecognitionWorker 的公共基类

    统一 run() 骨架：日志配置与桥接 handler 安装/卸载、Pipeline 构造、
    异常处理（logger.exception 保留堆栈）、完成信号在 finally 中发射。
    子类通过钩子定制：_log_run_start / _build_pipeline /
    _collect_result / _collect_error / _emit_finished / _error_label。
    """

    step_started = pyqtSignal(str, str)
    step_finished = pyqtSignal(str, bool, float, list)
    progress_updated = pyqtSignal(int, str)
    log_emitted = pyqtSignal(str, str)

    # 子类覆盖：异常日志前缀
    _error_label = "流水线异常"

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
        # 取消提示由 PipelineService.cancel_pipeline 统一发一次，
        # 避免并发模式下每个在途 worker 各刷一条相同日志
        self._cancel_event.set()

    def _setup_logger(self) -> logging.Logger:
        """按用户配置初始化日志（与 CLI 路径 core.pipeline.main 对齐）

        把设置页的日志级别/文件输出/轮转参数真正传入 setup_logger，
        否则 GUI 模式下这些配置全部静默失效。GUI 批量始终写入基础
        输出目录（与 CLI 多文件路径一致），避免各 worker 争相切换
        文件 handler。
        """
        log_to_file = self._config_manager.pipeline.get(
            "log_to_file", PIPELINE_DEFAULTS["log_to_file"]
        )
        log_dir = (
            self._config_manager.get_output_dir() if log_to_file else None
        )
        return setup_logger(
            "pipeline",
            log_dir=log_dir,
            log_level=self._config_manager.get_log_level(),
            log_to_file=log_to_file,
            max_bytes=self._config_manager.pipeline.get(
                "log_max_bytes", PIPELINE_DEFAULTS["log_max_bytes"]
            ),
            backup_count=self._config_manager.pipeline.get(
                "log_backup_count", PIPELINE_DEFAULTS["log_backup_count"]
            ),
        )

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
        self, step_key: str, success: bool, elapsed: float, warnings: list[str]
    ) -> None:
        """步骤结束回调：发射 step_finished 信号"""
        self.step_finished.emit(step_key, success, elapsed, warnings)

    # ── 子类钩子 ──────────────────────────────────────────

    def _log_run_start(self) -> None:
        """run 开始时的提示日志"""

    def _build_pipeline(self, logger: logging.Logger) -> Pipeline:
        """构造 Pipeline 实例（子类定制参数）"""
        raise NotImplementedError

    def _collect_result(self, pipeline: Pipeline, logger: logging.Logger,
                        success: bool) -> None:
        """运行成功后从 pipeline 提取子类关心的产物"""

    def _collect_error(self, pipeline: Pipeline | None,
                       logger: logging.Logger | None, exc: Exception) -> None:
        """运行异常后提取部分产物（如已有的报告）"""

    def _emit_finished(self, success: bool) -> None:
        """在 finally 中发射完成信号，确保 UI 不会卡在运行状态"""
        raise NotImplementedError

    def run(self) -> None:
        success = False
        pipeline: Pipeline | None = None
        logger: logging.Logger | None = None

        try:
            # 安装日志桥接：捕获本 worker 线程的日志记录。
            # thread_ident 必须在 run() 内（即 worker 线程已启动后）获取，
            # QThread.run 运行在 worker 线程上下文中，此时 threading.get_ident()
            # 返回 worker 线程 id。
            worker_thread_ident = threading.get_ident()
            logger = self._setup_logger()
            self._log_handler = QtLogHandler(self.log_emitted, worker_thread_ident)
            self._log_handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(self._log_handler)

            pipeline = self._build_pipeline(logger)

            self._log_run_start()
            success = pipeline.run()
            self._collect_result(pipeline, logger, success)

        except Exception as exc:
            if logger is not None:
                # exception 保留完整堆栈，便于排障（单行消息不够定位）
                logger.exception(f"{self._error_label}: {exc}")
            self._collect_error(pipeline, logger, exc)
            success = False
        finally:
            if logger is not None and self._log_handler is not None:
                logger.removeHandler(self._log_handler)
                self._log_handler = None
            # 确保完成信号一定发射，避免 UI 卡在"运行中"状态
            self._emit_finished(success)


class QtLogHandler(logging.Handler):
    """将日志记录转发为 Qt 信号的 Handler

    多 worker 共享同一个 ``pipeline`` logger（``setup_logger`` 按名称缓存），
    每个 worker 在自己的线程里 attach 一个 QtLogHandler。若不过滤，一条
    日志会被所有已 attach 的 handler 同时转发，导致 GUI 中重复显示且错误
    归属到其他 worker。这里用 ``thread_ident`` 限定 handler 只处理产生于
    同一线程的记录——步骤子 logger（``pipeline.<step>``）的记录经传播回到
    ``pipeline`` logger 时，``record.thread`` 仍是发起日志的 worker 线程，
    因此能被正确的 handler 捕获。
    """

    def __init__(self, signal: Any, thread_ident: int) -> None:
        super().__init__()
        self._signal = signal
        self._thread_ident = thread_ident

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self._thread_ident:
            return
        try:
            msg = self.format(record)
            self._signal.emit(record.levelname, msg)
        except Exception:
            self.handleError(record)


class PipelineWorker(_PipelineWorkerBase):
    """流水线工作线程

    通过回调钩子（on_step_start / on_step_finish / is_cancelled）将
    Pipeline 的步骤执行进度桥接为 Qt 信号，避免 monkey-patch（修复 M17）。
    """

    pipeline_finished = pyqtSignal(bool, dict, bool)

    def __init__(
        self,
        video_path: str,
        config_manager: ConfigManager,
        background_image_path: str | None = None,
        skip_steps: set[str] | None = None,
        copilot_json_path: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(video_path, config_manager, parent=parent)
        self._background_image_path = background_image_path
        self._skip_steps = skip_steps or set()
        self._copilot_json_path = copilot_json_path
        self._report_dict: dict[str, Any] = {}

    def _log_run_start(self) -> None:
        self.log_emitted.emit("INFO", "开始运行流水线...")

    def _build_pipeline(self, logger: logging.Logger) -> Pipeline:
        # config_manager 已由 ConfigProxy.build_worker_config 在主线程
        # 完成深拷贝与 overrides 合并，此处直接使用，避免子线程写共享状态。
        return Pipeline(
            video_path=self._video_path,
            config_mgr=self._config_manager,
            logger=logger,
            background_image_path=self._background_image_path,
            skip_steps=self._skip_steps,
            copilot_json_path=self._copilot_json_path,
            # 通过回调钩子注入步骤事件（替代 monkey-patch，修复 M17）
            on_step_start=self._on_step_start,
            on_step_finish=self._on_step_finish,
            is_cancelled=lambda: self._cancel_event.is_set(),
        )

    def _collect_result(self, pipeline: Pipeline, logger: logging.Logger,
                        success: bool) -> None:
        self._report_dict = pipeline.report.to_dict()

    def _collect_error(self, pipeline: Pipeline | None,
                       logger: logging.Logger | None, exc: Exception) -> None:
        try:
            self._report_dict = pipeline.report.to_dict() if pipeline else {}
        except Exception as report_exc:
            if logger is not None:
                logger.error(f"提取流水线报告失败: {report_exc}")
            self._report_dict = {}

    def _emit_finished(self, success: bool) -> None:
        self.pipeline_finished.emit(
            success, self._report_dict, self._cancel_event.is_set()
        )
