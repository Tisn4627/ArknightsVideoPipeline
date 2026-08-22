"""
gui.components.batch_video_list - 批量视频文件列表组件

展示待处理视频文件队列，支持多选添加、拖放添加、上移/下移调整顺序、
删除条目，以及每个文件的独立进度与状态跟踪。符合 Material Design 3
视觉规范，主题切换通过 ``set_colors`` 刷新。
"""

from __future__ import annotations

import os
from typing import List

from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QProgressBar,
    QPushButton, QSizePolicy, QFrame, QMenu,
)

from arknights_video_pipeline.core.utils import SUPPORTED_VIDEO_EXTENSIONS
from arknights_video_pipeline.gui.assets.icons.nav_icons import make_icon_pixmap
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import MaterialColors


# 状态枚举（字符串，便于直接作为样式 key）
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# 状态码 → 翻译 key
_STATUS_KEYS: dict[str, str] = {
    STATUS_PENDING: "batch.status.pending",
    STATUS_RUNNING: "batch.status.running",
    STATUS_SUCCESS: "batch.status.success",
    STATUS_FAILED: "batch.status.failed",
    STATUS_CANCELLED: "batch.status.cancelled",
}


def _status_text(status: str) -> str:
    """状态码 → 当前语言的显示文本（缺失时回退到状态码本身）"""
    return tr(_STATUS_KEYS.get(status, ""), default=status)


class BatchVideoRow(QWidget):
    """单个视频文件条目"""

    def __init__(self, video_path: str, colors: MaterialColors,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = video_path
        self._colors = colors
        self._status = STATUS_PENDING
        self._percent = 0
        self._json_path: str | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # 序号
        self._index_label = QLabel("1")
        self._index_label.setFixedWidth(20)
        self._index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._index_label.setStyleSheet(self._index_qss())
        layout.addWidget(self._index_label)

        # 状态图标
        self._status_icon = QLabel()
        self._status_icon.setFixedSize(20, 20)
        self._status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_icon)

        # 文件名
        self._name_label = QLabel(os.path.basename(video_path))
        self._name_label.setToolTip(video_path)
        self._name_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._name_label.setStyleSheet(
            f"color: {colors.on_surface}; border: none; background: transparent;"
        )
        layout.addWidget(self._name_label, 1)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedWidth(140)
        self._progress.setTextVisible(True)
        self._progress.setStyleSheet(self._progress_qss())
        layout.addWidget(self._progress)

        # 状态文本
        self._status_label = QLabel(_status_text(STATUS_PENDING))
        self._status_label.setMinimumWidth(48)
        self._status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._status_label.setStyleSheet(self._status_text_qss())
        layout.addWidget(self._status_label)

        # 自定义作业JSON / 上移 / 下移 / 删除按钮
        self._json_btn = self._make_icon_btn(
            "note_add", tr("batch.tooltip.json.add")
        )
        self._up_btn = self._make_icon_btn("arrow_upward", tr("batch.tooltip.up"))
        self._down_btn = self._make_icon_btn("arrow_downward", tr("batch.tooltip.down"))
        self._del_btn = self._make_icon_btn("delete", tr("batch.tooltip.delete"))
        layout.addWidget(self._json_btn)
        layout.addWidget(self._up_btn)
        layout.addWidget(self._down_btn)
        layout.addWidget(self._del_btn)

    # ── 公开 API ──────────────────────────────────────────

    @property
    def video_path(self) -> str:
        return self._path

    def set_index(self, index: int) -> None:
        self._index_label.setText(str(index))

    def set_editable(self, editable: bool) -> None:
        self._up_btn.setEnabled(editable)
        self._down_btn.setEnabled(editable)
        self._del_btn.setEnabled(editable)
        self._json_btn.setEnabled(editable)

    def set_json_button_visible(self, visible: bool) -> None:
        """隐藏/显示 JSON 绑定按钮（识别工具自身生成 JSON，无需该按钮）"""
        self._json_btn.setVisible(visible)

    def set_status(self, status: str, percent: int | None = None) -> None:
        self._status = status
        if percent is not None:
            self._percent = max(0, min(100, percent))
        self._progress.setValue(self._percent)
        self._status_label.setText(_status_text(status))
        self._status_label.setStyleSheet(self._status_text_qss())
        self._progress.setStyleSheet(self._progress_qss())
        self._refresh_status_icon()

    def set_progress(self, percent: int) -> None:
        self._percent = max(0, min(100, percent))
        self._progress.setValue(self._percent)

    def reset_state(self) -> None:
        self._status = STATUS_PENDING
        self._percent = 0
        self._progress.setValue(0)
        self._status_label.setText(_status_text(STATUS_PENDING))
        self._status_label.setStyleSheet(self._status_text_qss())
        self._progress.setStyleSheet(self._progress_qss())
        self._refresh_status_icon()

    def refresh_translations(self) -> None:
        """语言切换时刷新状态文本与按钮 tooltip"""
        self._status_label.setText(_status_text(self._status))
        self._refresh_json_btn()
        self._up_btn.setToolTip(tr("batch.tooltip.up"))
        self._down_btn.setToolTip(tr("batch.tooltip.down"))
        self._del_btn.setToolTip(tr("batch.tooltip.delete"))

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._index_label.setStyleSheet(self._index_qss())
        self._name_label.setStyleSheet(
            f"color: {colors.on_surface}; border: none; background: transparent;"
        )
        self._status_label.setStyleSheet(self._status_text_qss())
        self._progress.setStyleSheet(self._progress_qss())
        for name, btn in (("arrow_upward", self._up_btn),
                          ("arrow_downward", self._down_btn),
                          ("delete", self._del_btn)):
            pix = make_icon_pixmap(name, colors.on_surface_variant, 18)
            if pix is not None:
                btn.setIcon(QIcon(pix))
        self._refresh_json_btn()
        self._refresh_status_icon()

    # ── 信号入口（由 BatchVideoList 连接） ────────────────

    def up_button(self) -> QPushButton:
        return self._up_btn

    def down_button(self) -> QPushButton:
        return self._down_btn

    def delete_button(self) -> QPushButton:
        return self._del_btn

    def json_button(self) -> QPushButton:
        return self._json_btn

    # ── 自定义作业 JSON ──────────────────────────────────

    @property
    def json_path(self) -> str | None:
        """已绑定的自定义作业 JSON 路径（None 表示未绑定）"""
        return self._json_path

    def set_json_path(self, path: str | None) -> None:
        """绑定/移除自定义作业 JSON，并刷新按钮状态显示"""
        self._json_path = path
        self._refresh_json_btn()

    def _refresh_json_btn(self) -> None:
        """按绑定状态刷新 JSON 按钮的图标、颜色与 tooltip"""
        if self._json_path:
            icon_name = "description"
            color = self._colors.primary
            tooltip = tr(
                "batch.tooltip.json.set", path=self._json_path
            )
        else:
            icon_name = "note_add"
            color = self._colors.on_surface_variant
            tooltip = tr("batch.tooltip.json.add")
        pix = make_icon_pixmap(icon_name, color, 18)
        if pix is not None:
            self._json_btn.setIcon(QIcon(pix))
        self._json_btn.setToolTip(tooltip)

    # ── 内联样式 ──────────────────────────────────────────

    def _make_icon_btn(self, icon_name: str, tooltip: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(28, 28)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFlat(True)
        btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; padding: 0; }"
            "QPushButton:disabled { color: transparent; }"
        )
        pix = make_icon_pixmap(icon_name, self._colors.on_surface_variant, 18)
        if pix is not None:
            btn.setIcon(QIcon(pix))
        return btn

    def _index_qss(self) -> str:
        c = self._colors
        return (
            f"background-color: {c.primary_container}; color: {c.on_primary_container};"
            " border-radius: 10px; font-weight: 500; border: none;"
        )

    def _status_text_qss(self) -> str:
        c = self._colors
        color = {
            STATUS_PENDING: c.on_surface_variant,
            STATUS_RUNNING: c.primary,
            STATUS_SUCCESS: c.success,
            STATUS_FAILED: c.error,
            STATUS_CANCELLED: c.warning,
        }.get(self._status, c.on_surface_variant)
        return (
            f"color: {color}; font-weight: 500; border: none; background: transparent;"
        )

    def _progress_qss(self) -> str:
        c = self._colors
        chunk = {
            STATUS_RUNNING: c.primary,
            STATUS_SUCCESS: c.success,
            STATUS_FAILED: c.error,
            STATUS_CANCELLED: c.warning,
        }.get(self._status, c.primary)
        return (
            "QProgressBar {"
            f"  background-color: {c.surface_variant};"
            f"  border: 1px solid {c.outline_variant};"
            "  border-radius: 6px;"
            "  text-align: center;"
            f"  color: {c.on_surface_variant};"
            "}"
            "QProgressBar::chunk {"
            f"  background-color: {chunk};"
            "  border-radius: 5px;"
            "}"
        )

    def _refresh_status_icon(self) -> None:
        icon_map = {
            STATUS_SUCCESS: ("check_circle", self._colors.success),
            STATUS_FAILED: ("error", self._colors.error),
        }
        entry = icon_map.get(self._status)
        if entry is None:
            self._status_icon.clear()
            return
        name, color = entry
        pix = make_icon_pixmap(name, color, 18)
        self._status_icon.setPixmap(pix if pix is not None else QPixmap())


class BatchVideoList(QWidget):
    """批量视频文件列表"""

    video_paths_changed = pyqtSignal(list)

    def __init__(self, colors: MaterialColors, parent: QWidget | None = None,
                 show_json_button: bool = True) -> None:
        super().__init__(parent)
        self._colors = colors
        self._rows: List[BatchVideoRow] = []
        self._editable = True
        self._show_json_button = show_json_button

        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 顶部操作栏
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        self._add_btn = MaterialButton(tr("batch.add_videos"), variant=MaterialButton.VARIANT_FILLED)
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._clear_btn = MaterialButton(tr("batch.clear"), variant=MaterialButton.VARIANT_TEXT)
        self._clear_btn.clicked.connect(self.clear)
        self._count_label = QLabel(tr("batch.count", n=0))
        self._count_label.setStyleSheet(
            f"color: {colors.on_surface_variant}; border: none; background: transparent;"
        )
        top_bar.addWidget(self._add_btn)
        top_bar.addWidget(self._clear_btn)
        top_bar.addStretch()
        top_bar.addWidget(self._count_label)
        outer.addLayout(top_bar)

        # 滚动列表区
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background-color: transparent; border: 1px dashed {colors.outline_variant}; border-radius: 12px; }}"
        )
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(8, 8, 8, 8)
        self._list_layout.setSpacing(6)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)

        # 空列表占位提示
        self._placeholder = QLabel(tr("batch.placeholder"))
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {colors.on_surface_variant}; border: none; background: transparent;"
            " padding: 24px;"
        )
        self._list_layout.addWidget(self._placeholder)

        # 语言切换时刷新所有静态文本与已有行
        i18n().language_changed.connect(self._retranslate)

    def _retranslate(self) -> None:
        """语言切换时刷新按钮文本、计数、占位提示与所有行的状态/tooltip"""
        self._add_btn.setText(tr("batch.add_videos"))
        self._clear_btn.setText(tr("batch.clear"))
        self._count_label.setText(tr("batch.count", n=len(self._rows)))
        self._placeholder.setText(tr("batch.placeholder"))
        for row in self._rows:
            row.refresh_translations()

    # ── 公开 API ──────────────────────────────────────────

    def video_paths(self) -> list[str]:
        return [row.video_path for row in self._rows]

    def json_paths(self) -> list[str | None]:
        """与 video_paths() 平行对齐的自定义作业 JSON 路径列表（None=未绑定）

        仅本次会话有效，不持久化到配置文件。
        """
        return [row.json_path for row in self._rows]

    def add_paths(self, paths: list[str]) -> None:
        added = False
        for p in paths:
            p = p.strip() if isinstance(p, str) else p
            if not p:
                continue
            ext = os.path.splitext(p)[1].lower()
            if ext not in SUPPORTED_VIDEO_EXTENSIONS:
                continue
            if p in self.video_paths():
                continue  # 去重
            row = BatchVideoRow(p, self._colors)
            row.set_editable(self._editable)
            if not self._show_json_button:
                row.set_json_button_visible(False)
            row.up_button().clicked.connect(lambda _, r=row: self._move_up(r))
            row.down_button().clicked.connect(lambda _, r=row: self._move_down(r))
            row.delete_button().clicked.connect(lambda _, r=row: self._remove(r))
            row.json_button().clicked.connect(
                lambda _, r=row: self._on_json_clicked(r)
            )
            self._rows.append(row)
            self._list_layout.addWidget(row)
            added = True
        if added:
            self._reindex()
            self._refresh_placeholder()
            self.video_paths_changed.emit(self.video_paths())

    def clear(self) -> None:
        if not self._rows:
            return
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._reindex()
        self._refresh_placeholder()
        self.video_paths_changed.emit([])

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        self._add_btn.setEnabled(editable)
        self._clear_btn.setEnabled(editable)
        for row in self._rows:
            row.set_editable(editable)

    def reset_states(self) -> None:
        for row in self._rows:
            row.reset_state()

    # ── 状态更新（由服务层信号驱动） ─────────────────────

    def set_file_running(self, index: int) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index].set_status(STATUS_RUNNING, 0)

    def set_file_progress(self, index: int, percent: int, message: str) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index].set_status(STATUS_RUNNING, percent)

    def set_file_finished(self, index: int, success: bool,
                          cancelled: bool = False) -> None:
        if 0 <= index < len(self._rows):
            if cancelled:
                status = STATUS_CANCELLED
            else:
                status = STATUS_SUCCESS if success else STATUS_FAILED
            self._rows[index].set_status(status, None)

    # ── 主题 ─────────────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background-color: transparent; border: 1px dashed {colors.outline_variant}; border-radius: 12px; }}"
        )
        self._count_label.setStyleSheet(
            f"color: {colors.on_surface_variant}; border: none; background: transparent;"
        )
        self._placeholder.setStyleSheet(
            f"color: {colors.on_surface_variant}; border: none; background: transparent; padding: 24px;"
        )
        for row in self._rows:
            row.set_colors(colors)

    # ── 拖放 ─────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        # 与"添加/清空"按钮一致：批次运行中禁止改动列表，否则列表与
        # 服务端批次索引错位，且会在运行期间改写 config.video_paths
        if not self._editable:
            event.ignore()
            return
        paths: list[str] = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    # ── 内部 ─────────────────────────────────────────────

    def _on_json_clicked(self, row: BatchVideoRow) -> None:
        """自定义作业 JSON 按钮点击处理

        未绑定：弹出文件对话框选择 JSON；
        已绑定：弹出菜单选择「更换 JSON」或「移除 JSON」。
        """
        if row.json_path:
            menu = QMenu(self)
            # exec 后立即销毁：父控件存活期间反复右键会累积子 QMenu 对象
            menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            replace_act = menu.addAction(tr("batch.tooltip.json.replace"))
            remove_act = menu.addAction(tr("batch.tooltip.json.remove"))
            chosen = menu.exec(self._json_pos(row.json_button()))
            if chosen is replace_act:
                self._pick_json_for_row(row)
            elif chosen is remove_act:
                row.set_json_path(None)
        else:
            self._pick_json_for_row(row)

    def _pick_json_for_row(self, row: BatchVideoRow) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, tr("batch.json_open_title"), "",
            "Copilot JSON (*.json);;All files (*.*)",
        )
        if path:
            row.set_json_path(path)

    def _json_pos(self, btn: QPushButton) -> QPoint:
        """计算 JSON 按钮在屏幕上的位置，用于弹出菜单"""
        return btn.mapToGlobal(QPoint(0, btn.height()))

    def _on_add_clicked(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        exts = ' '.join(f'*{e}' for e in sorted(SUPPORTED_VIDEO_EXTENSIONS))
        filter_str = f'Video files ({exts});;All files (*.*)'
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("batch.open_title"), "", filter_str,
        )
        if paths:
            self.add_paths(paths)

    def _move_up(self, row: BatchVideoRow) -> None:
        idx = self._rows.index(row)
        if idx <= 0:
            return
        self._rows[idx], self._rows[idx - 1] = self._rows[idx - 1], self._rows[idx]
        self._reorder_layout()
        self._reindex()
        self.video_paths_changed.emit(self.video_paths())

    def _move_down(self, row: BatchVideoRow) -> None:
        idx = self._rows.index(row)
        if idx >= len(self._rows) - 1:
            return
        self._rows[idx], self._rows[idx + 1] = self._rows[idx + 1], self._rows[idx]
        self._reorder_layout()
        self._reindex()
        self.video_paths_changed.emit(self.video_paths())

    def _remove(self, row: BatchVideoRow) -> None:
        idx = self._rows.index(row)
        self._list_layout.removeWidget(row)
        row.deleteLater()
        self._rows.pop(idx)
        self._reindex()
        self._refresh_placeholder()
        self.video_paths_changed.emit(self.video_paths())

    def _reorder_layout(self) -> None:
        # 按 _rows 顺序重排布局中的行 widget（保留 placeholder 在最后）
        for row in self._rows:
            self._list_layout.removeWidget(row)
        for row in self._rows:
            self._list_layout.addWidget(row)

    def _reindex(self) -> None:
        for i, row in enumerate(self._rows, start=1):
            row.set_index(i)
        self._count_label.setText(tr("batch.count", n=len(self._rows)))

    def _refresh_placeholder(self) -> None:
        has_rows = bool(self._rows)
        self._placeholder.setVisible(not has_rows)
