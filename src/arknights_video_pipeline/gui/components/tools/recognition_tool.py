"""
gui.components.tools.recognition_tool - Recognition 独立识别工具

功能：
- 选择一个或多个视频文件（支持拖放）
- 配置识别参数（后端/OCR 源/分辨率/关卡指定/with_video_time）
- 选择输出目录（默认 output/）
- 后台线程执行识别（仅步骤1），输出单一 copilot JSON 文件
- 实时进度与日志展示，完成后可打开输出目录

与主页完整流水线的区别：
- 仅执行视频识别（步骤1），跳过编队/操作/跟踪/合成；
- 无需背景板图片；
- 复用 RecognitionWorker（service.recognition_worker）后台执行。

新增工具无需改动 ToolsPage / MainWindow：本类在
``gui.components.tools.TOOL_REGISTRY`` 注册即可。
"""

from __future__ import annotations

import os
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from arknights_video_pipeline.core.utils import SUPPORTED_VIDEO_EXTENSIONS
from arknights_video_pipeline.gui.components.file_selector import FileSelector
from arknights_video_pipeline.gui.components.log_viewer import LogViewer
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import MaterialCard
from arknights_video_pipeline.gui.components.message_dialog import (
    InfoDialog,
    WarningDialog,
)
from arknights_video_pipeline.gui.components.progress_card import ProgressCard
from arknights_video_pipeline.gui.components.settings_row_builders import (
    FieldRow,
    build_combo_row,
    build_string_row,
    build_switch_row,
)
from arknights_video_pipeline.gui.components.tools.base import ToolView
from arknights_video_pipeline.gui.i18n import tr
from arknights_video_pipeline.gui.theme import MaterialColors
from arknights_video_pipeline.service.recognition_worker import RecognitionWorker


class _VideoListWidget(QListWidget):
    """支持拖放的视频文件列表"""

    def __init__(self, colors: MaterialColors, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(120)
        self.setMaximumHeight(220)
        self._apply_qss(colors)

    def _apply_qss(self, c: MaterialColors) -> None:
        self.setStyleSheet(
            "QListWidget {"
            f"  background-color: {c.surface_variant};"
            f"  color: {c.on_surface};"
            f"  border: 1px solid {c.outline_variant};"
            f"  border-radius: 12px;"
            f"  padding: 6px;"
            "}"
            "QListWidget::item { padding: 4px 6px; border: none; }"
            "QListWidget::item:selected {"
            f"  background-color: {c.primary_container};"
            f"  color: {c.on_primary_container};"
            "}"
        )

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._apply_qss(colors)

    # ── 拖放 ──────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return
        paths: list[str] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local and os.path.isfile(local):
                paths.append(local)
        if paths:
            # 向上查找实现了 add_video_paths 的祖先控件（RecognitionTool）。
            # 不能假设 window() 就是该控件：列表被 ToolDialog 包裹时
            # window() 是对话框本身，直接调用会 AttributeError 并在
            # PyQt6 事件回调中直接崩溃进程
            w = self.parentWidget()
            while w is not None and not hasattr(w, "add_video_paths"):
                w = w.parentWidget()
            if w is not None:
                w.add_video_paths(paths)
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()


class RecognitionTool(ToolView):
    """Recognition 独立识别工具

    选择视频 → 配置参数 → 后台识别 → 输出单一 copilot JSON。
    """

    tool_id = "recognition"
    title_key = "tools.recognition.title"
    desc_key = "tools.recognition.desc"

    # 配置写盘成功后发射（与 Style1TextRangeTool 一致的接口约定）
    config_applied = pyqtSignal()

    def __init__(self, config_proxy: Any, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(config_proxy, colors, parent)
        c = self._colors
        self._tr_labels: list[tuple] = []
        self._rows: dict[str, FieldRow] = {}
        self._worker: RecognitionWorker | None = None
        self._cancelled: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(24)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── 视频选择卡片 ──────────────────────────────────
        self._video_card = MaterialCard(tr("tools.recognition.video_input"))
        self._video_card.set_surface_color(c.surface)
        v_layout = self._video_card.layout()

        self._video_list = _VideoListWidget(c)
        v_layout.addWidget(self._video_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self._add_btn = MaterialButton(
            tr("tools.recognition.add_videos"),
            variant=MaterialButton.VARIANT_OUTLINED,
        )
        self._add_btn.clicked.connect(self._on_add_videos)
        btn_row.addWidget(self._add_btn)

        self._remove_btn = MaterialButton(
            tr("tools.recognition.remove_selected"),
            variant=MaterialButton.VARIANT_OUTLINED,
        )
        self._remove_btn.clicked.connect(self._on_remove_selected)
        btn_row.addWidget(self._remove_btn)

        self._clear_btn = MaterialButton(
            tr("tools.recognition.clear_all"),
            variant=MaterialButton.VARIANT_OUTLINED,
        )
        self._clear_btn.clicked.connect(self._on_clear_all)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()
        v_layout.addLayout(btn_row)

        root.addWidget(self._video_card)

        # ── 识别参数卡片 ──────────────────────────────────
        self._param_card = MaterialCard(tr("tools.recognition.params"))
        self._param_card.set_surface_color(c.surface)
        p_layout = self._param_card.layout()
        p_layout.setSpacing(8)

        # 后端
        self._backend_row = build_combo_row(
            tr("tools.recognition.backend"),
            items=["recognition", "maa"],
            default=self._config_proxy.copilot_backend(),
            colors=c,
            on_changed=self._on_param_changed,
        )
        p_layout.addWidget(self._backend_row.widget)
        self._rows["backend"] = self._backend_row
        self._tr_labels.append((self._backend_row.set_label, "tools.recognition.backend"))

        # OCR 源
        self._ocr_row = build_combo_row(
            tr("tools.recognition.ocr_source"),
            items=["maamodel", "default"],
            default=self._config_proxy.ocr_source(),
            colors=c,
            on_changed=self._on_param_changed,
        )
        p_layout.addWidget(self._ocr_row.widget)
        self._rows["ocr_source"] = self._ocr_row
        self._tr_labels.append((self._ocr_row.set_label, "tools.recognition.ocr_source"))

        # 分辨率
        self._resolution_row = build_string_row(
            tr("tools.recognition.resolution"),
            default=self._config_proxy.resolution(),
            colors=c,
            on_changed=self._on_param_changed,
        )
        p_layout.addWidget(self._resolution_row.widget)
        self._rows["resolution"] = self._resolution_row
        self._tr_labels.append(
            (self._resolution_row.set_label, "tools.recognition.resolution")
        )

        # 关卡指定
        self._stage_row = build_string_row(
            tr("tools.recognition.stage_override"),
            default=self._config_proxy.stage_override(),
            colors=c,
            on_changed=self._on_param_changed,
        )
        p_layout.addWidget(self._stage_row.widget)
        self._rows["stage_override"] = self._stage_row
        self._tr_labels.append(
            (self._stage_row.set_label, "tools.recognition.stage_override")
        )

        # with_video_time 开关
        self._video_time_row = build_switch_row(
            tr("tools.recognition.with_video_time"),
            desc=tr("tools.recognition.with_video_time_desc"),
            colors=c,
        )
        self._video_time_row.set_value(self._config_proxy.with_video_time(), False)
        p_layout.addWidget(self._video_time_row.widget)
        self._rows["with_video_time"] = self._video_time_row
        self._tr_labels.append(
            (self._video_time_row.set_label, "tools.recognition.with_video_time")
        )
        self._tr_labels.append(
            (self._video_time_row.set_desc, "tools.recognition.with_video_time_desc")
        )

        root.addWidget(self._param_card)

        # ── 输出目录卡片 ──────────────────────────────────
        self._output_card = MaterialCard(tr("tools.recognition.output_dir"))
        self._output_card.set_surface_color(c.surface)
        o_layout = self._output_card.layout()

        self._output_selector = FileSelector(
            mode=FileSelector.MODE_DIRECTORY,
            label=tr("tools.recognition.output_dir"),
            placeholder=tr("tools.recognition.output_placeholder"),
        )
        self._output_selector.set_colors(c)
        default_out = self._config_proxy.output_dir() or "output"
        self._output_selector.set_path(default_out)
        o_layout.addWidget(self._output_selector)
        self._tr_labels.append(
            (self._output_selector.set_label, "tools.recognition.output_dir")
        )
        self._tr_labels.append(
            (self._output_selector.set_placeholder, "tools.recognition.output_placeholder")
        )

        root.addWidget(self._output_card)

        # ── 操作按钮 ──────────────────────────────────────
        op_row = QHBoxLayout()
        op_row.setSpacing(12)
        self._start_btn = MaterialButton(
            tr("tools.recognition.start"),
            variant=MaterialButton.VARIANT_FILLED,
        )
        self._start_btn.clicked.connect(self._on_start)
        op_row.addWidget(self._start_btn)

        self._cancel_btn = MaterialButton(
            tr("tools.recognition.cancel"),
            variant=MaterialButton.VARIANT_OUTLINED,
        )
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        op_row.addWidget(self._cancel_btn)

        self._open_output_btn = MaterialButton(
            tr("tools.recognition.open_output"),
            variant=MaterialButton.VARIANT_OUTLINED,
        )
        self._open_output_btn.clicked.connect(self._on_open_output)
        op_row.addWidget(self._open_output_btn)
        op_row.addStretch()
        root.addLayout(op_row)

        # ── 进度卡片 ──────────────────────────────────────
        self._progress_card = ProgressCard()
        self._progress_card.set_surface_color(c.surface)
        root.addWidget(self._progress_card)

        # ── 日志卡片 ──────────────────────────────────────
        self._log_card = MaterialCard(tr("tools.recognition.logs"))
        self._log_card.set_surface_color(c.surface)
        self._log_viewer = LogViewer(colors=c)
        self._log_viewer.setMinimumHeight(180)
        self._log_card.add_widget(self._log_viewer)
        root.addWidget(self._log_card)

    # ── 公开接口（供 ToolsPage 拖放回调） ────────────────

    def add_video_paths(self, paths: list[str]) -> None:
        """向视频列表追加路径（去重，仅保留支持的视频扩展名）"""
        existing = set()
        for i in range(self._video_list.count()):
            existing.add(self._video_list.item(i).data(Qt.ItemDataRole.UserRole) or "")
        for p in paths:
            abs_p = os.path.abspath(p)
            ext = os.path.splitext(abs_p)[1].lower()
            if ext not in SUPPORTED_VIDEO_EXTENSIONS:
                continue
            if abs_p in existing:
                continue
            item = QListWidgetItem(os.path.basename(abs_p))
            item.setToolTip(abs_p)
            item.setData(Qt.ItemDataRole.UserRole, abs_p)
            self._video_list.addItem(item)

    # ── 视频列表操作 ──────────────────────────────────────

    def _on_add_videos(self) -> None:
        filter_str = (
            "Video files (*.mp4 *.avi *.mkv *.mov *.flv *.wmv);;All files (*.*)"
        )
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("tools.recognition.select_videos"), "", filter_str
        )
        if paths:
            self.add_video_paths(paths)

    def _on_remove_selected(self) -> None:
        for item in self._video_list.selectedItems():
            self._video_list.takeItem(self._video_list.row(item))

    def _on_clear_all(self) -> None:
        self._video_list.clear()

    def _video_paths(self) -> list[str]:
        paths: list[str] = []
        for i in range(self._video_list.count()):
            item = self._video_list.item(i)
            p = item.data(Qt.ItemDataRole.UserRole)
            if p:
                paths.append(p)
        return paths

    # ── 参数变更 ──────────────────────────────────────────

    def _on_param_changed(self, _value: Any = None) -> None:
        """参数变更时同步到 ConfigProxy（仅内存，不立即写盘）

        实际写盘在点击"开始识别"时由 _config.save_all() 完成，
        与 MainWindow._on_run 的行为一致。
        """
        try:
            self._config_proxy.set_copilot_backend(self._backend_row.get_value())
            self._config_proxy.set_ocr_source(self._ocr_row.get_value())
            self._config_proxy.set_resolution(self._resolution_row.get_value())
            self._config_proxy.set_stage_override(self._stage_row.get_value())
            self._config_proxy.set_with_video_time(
                bool(self._video_time_row.get_value())
            )
        except ValueError:
            # 非法值（如分辨率格式错误）由启动校验捕获，此处静默
            pass

    # ── 启动 / 取消 / 完成 ────────────────────────────────

    def _on_start(self) -> None:
        paths = self._video_paths()
        if not paths:
            WarningDialog(
                tr("tools.recognition.no_video_title"),
                tr("tools.recognition.no_video_text"),
                colors=self._colors, parent=self.window(),
            ).exec()
            return

        if self._worker is not None and self._worker.isRunning():
            WarningDialog(
                tr("tools.recognition.already_running_title"),
                tr("tools.recognition.already_running_text"),
                colors=self._colors, parent=self.window(),
            ).exec()
            return

        # 写入输出目录到配置（worker 通过 ConfigManager 快照读取）
        out_dir = self._output_selector.path().strip()
        if out_dir:
            self._config_proxy.set_output_dir(out_dir)
        # 同步全部参数到配置并落盘
        self._on_param_changed()
        try:
            self._config_proxy.save_all()
        except Exception as exc:
            WarningDialog(
                tr("tools.recognition.save_config_failed_title"),
                str(exc),
                colors=self._colors, parent=self.window(),
            ).exec()
            return

        # 重置 UI 状态
        self._progress_card.reset()
        self._log_viewer.clear_logs()
        self._cancelled = False
        self._set_running_ui(True)

        # 启动第一个视频识别
        self._pending_paths: list[str] = paths
        self._success_count = 0
        self._total_count = len(paths)
        self._current_index = 0
        self._current_json_path = ""
        self._log_viewer.append(
            "INFO",
            tr("tools.recognition.log_batch_start", n=self._total_count),
        )
        self._start_next()

    def _start_next(self) -> None:
        """启动队列中下一个视频的识别"""
        if self._current_index >= self._total_count:
            self._finish_batch()
            return

        video_path = self._pending_paths[self._current_index]
        self._current_json_path = ""
        self._log_viewer.append(
            "INFO",
            tr(
                "tools.recognition.log_file_start",
                idx=self._current_index + 1,
                total=self._total_count,
                name=os.path.basename(video_path),
            ),
        )

        # 构建 ConfigManager 快照（主线程深拷贝，避免子线程竞争）
        worker_config = self._config_proxy.build_worker_config()
        self._worker = RecognitionWorker(
            video_path=video_path,
            config_manager=worker_config,
            parent=self,
        )
        self._worker.step_started.connect(self._on_step_started)
        self._worker.step_finished.connect(self._on_step_finished)
        self._worker.progress_updated.connect(self._progress_card.set_progress)
        self._worker.log_emitted.connect(self._log_viewer.append)
        self._worker.recognition_finished.connect(self._on_recognition_finished)
        self._worker.start()

    def _on_step_started(self, step_key: str, step_desc: str) -> None:
        self._log_viewer.append("INFO", f"[{step_key}] {step_desc}")

    def _on_step_finished(
        self, step_key: str, success: bool, elapsed: float, warnings: list[str]
    ) -> None:
        status = "OK" if success else "FAIL"
        self._log_viewer.append(
            "INFO" if success else "ERROR",
            f"[{step_key}] {status} ({elapsed:.1f}s)",
        )
        for w in warnings:
            self._log_viewer.append("WARNING", f"  {w}")

    def _on_recognition_finished(
        self, success: bool, json_path: str, cancelled: bool
    ) -> None:
        """单个视频识别完成回调"""
        video_path = self._pending_paths[self._current_index]
        name = os.path.basename(video_path)

        if success and json_path:
            self._success_count += 1
            self._current_json_path = json_path
            self._log_viewer.append(
                "INFO",
                tr("tools.recognition.log_success", name=name, path=json_path),
            )
        else:
            msg = tr("tools.recognition.log_cancelled") if cancelled else tr(
                "tools.recognition.log_failed", name=name
            )
            self._log_viewer.append("ERROR", msg)

        # 清理 worker
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

        self._current_index += 1

        # 取消请求：停止后续派发
        if cancelled or self._cancelled:
            self._finish_batch()
            return

        self._start_next()

    def _finish_batch(self) -> None:
        """批次结束：更新 UI 与进度"""
        total = self._total_count
        success = self._success_count
        self._progress_card.set_progress(100, f"Completed {success}/{total}")
        self._set_running_ui(False)

        if success == total and not self._cancelled:
            InfoDialog(
                tr("tools.recognition.success_title"),
                tr("tools.recognition.success_text", n=success),
                colors=self._colors, parent=self.window(),
            ).exec()
        elif self._cancelled:
            WarningDialog(
                tr("tools.recognition.cancelled_title"),
                tr("tools.recognition.cancelled_text", success=success, total=total),
                colors=self._colors, parent=self.window(),
            ).exec()
        else:
            WarningDialog(
                tr("tools.recognition.partial_title"),
                tr("tools.recognition.partial_text", success=success, total=total),
                colors=self._colors, parent=self.window(),
            ).exec()

    def _on_cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._cancelled = True
            self._worker.cancel()
            self._cancel_btn.setEnabled(False)

    def request_shutdown(self) -> None:
        """对话框关闭前的兜底：请求取消并等待 worker 退出。

        ToolDialog 设有 WA_DeleteOnClose，关闭即析构整棵控件树；若此时
        QThread 仍在运行会触发 "QThread destroyed while running" 直接
        abort 进程。cancel 只在步骤边界生效，故限时等待后仍需 terminate
        兜底（与 PipelineService.force_terminate_workers 同一策略）。
        """
        self._cancelled = True
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            if not worker.wait(3000):
                worker.terminate()
                worker.wait(1000)

    def _on_open_output(self) -> None:
        """打开输出目录（识别产物所在目录）"""
        out_dir = self._output_selector.path().strip()
        if not out_dir:
            out_dir = self._config_proxy.output_dir() or "output"
        if not os.path.isabs(out_dir):
            out_dir = os.path.abspath(out_dir)
        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        # Windows 资源管理器打开目录
        if os.name == "nt":
            os.startfile(out_dir)  # type: ignore[attr-defined]
        else:
            import subprocess
            import sys
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, out_dir])

    # ── UI 状态 ───────────────────────────────────────────

    def _set_running_ui(self, running: bool) -> None:
        self._start_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._add_btn.setEnabled(not running)
        self._remove_btn.setEnabled(not running)
        self._clear_btn.setEnabled(not running)
        for row in self._rows.values():
            row.set_enabled(not running)
        self._output_selector.setEnabled(not running)

    # ── ToolView 接口 ─────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        super().set_colors(colors)
        c = colors
        self._video_card.set_surface_color(c.surface)
        self._param_card.set_surface_color(c.surface)
        self._output_card.set_surface_color(c.surface)
        self._log_card.set_surface_color(c.surface)
        self._progress_card.set_surface_color(c.surface)
        self._video_list.set_colors(c)
        self._output_selector.set_colors(c)
        self._log_viewer.set_colors(c)
        for row in self._rows.values():
            row.set_colors(c)

    def retranslate(self) -> None:
        self._video_card.set_title(tr("tools.recognition.video_input"))
        self._param_card.set_title(tr("tools.recognition.params"))
        self._output_card.set_title(tr("tools.recognition.output_dir"))
        self._log_card.set_title(tr("tools.recognition.logs"))
        self._add_btn.setText(tr("tools.recognition.add_videos"))
        self._remove_btn.setText(tr("tools.recognition.remove_selected"))
        self._clear_btn.setText(tr("tools.recognition.clear_all"))
        self._start_btn.setText(tr("tools.recognition.start"))
        self._cancel_btn.setText(tr("tools.recognition.cancel"))
        self._open_output_btn.setText(tr("tools.recognition.open_output"))
        self._output_selector.set_label(tr("tools.recognition.output_dir"))
        self._output_selector.set_placeholder(
            tr("tools.recognition.output_placeholder")
        )
        for setter, key in self._tr_labels:
            setter(tr(key))

    def on_entered(self) -> None:
        """进入工具视图时从配置加载参数值"""
        self._backend_row.set_value(self._config_proxy.copilot_backend(), True)
        self._ocr_row.set_value(self._config_proxy.ocr_source(), True)
        self._resolution_row.set_value(self._config_proxy.resolution(), True)
        self._stage_row.set_value(self._config_proxy.stage_override(), True)
        self._video_time_row.set_value(self._config_proxy.with_video_time(), True)
        out_dir = self._config_proxy.output_dir() or "output"
        # 从配置回填 UI，阻断信号避免触发 path_changed 回写配置
        self._output_selector.set_path(out_dir, block_signal=True)
