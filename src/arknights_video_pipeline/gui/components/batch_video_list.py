"""
gui.components.batch_video_list - 批量视频文件列表组件

展示待处理视频文件队列，支持多选添加、拖放添加、上移/下移调整顺序、
删除条目，以及每个文件的独立进度与状态跟踪。符合 Material Design 3
视觉规范，主题切换通过 ``set_colors`` 刷新。
"""

from __future__ import annotations

import os
from typing import List

from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QProgressBar,
    QPushButton, QSizePolicy, QFrame,
)

from arknights_video_pipeline.core.utils import SUPPORTED_VIDEO_EXTENSIONS
from arknights_video_pipeline.gui.assets.icons.nav_icons import make_icon_pixmap
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.theme import MaterialColors


# 状态枚举（字符串，便于直接作为样式 key）
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

_STATUS_TEXT: dict[str, str] = {
    STATUS_PENDING: "等待中",
    STATUS_RUNNING: "处理中",
    STATUS_SUCCESS: "已完成",
    STATUS_FAILED: "失败",
}


class BatchVideoRow(QWidget):
    """单个视频文件条目"""

    def __init__(self, video_path: str, colors: MaterialColors,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = video_path
        self._colors = colors
        self._status = STATUS_PENDING
        self._percent = 0

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
        self._status_label = QLabel(_STATUS_TEXT[STATUS_PENDING])
        self._status_label.setMinimumWidth(48)
        self._status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._status_label.setStyleSheet(self._status_text_qss())
        layout.addWidget(self._status_label)

        # 上移 / 下移 / 删除按钮
        self._up_btn = self._make_icon_btn("arrow_upward", "上移")
        self._down_btn = self._make_icon_btn("arrow_downward", "下移")
        self._del_btn = self._make_icon_btn("delete", "移除")
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

    def set_status(self, status: str, percent: int | None = None) -> None:
        self._status = status
        if percent is not None:
            self._percent = max(0, min(100, percent))
        self._progress.setValue(self._percent)
        self._status_label.setText(_STATUS_TEXT.get(status, status))
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
        self._status_label.setText(_STATUS_TEXT[STATUS_PENDING])
        self._status_label.setStyleSheet(self._status_text_qss())
        self._progress.setStyleSheet(self._progress_qss())
        self._refresh_status_icon()

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
        self._refresh_status_icon()

    # ── 信号入口（由 BatchVideoList 连接） ────────────────

    def up_button(self) -> QPushButton:
        return self._up_btn

    def down_button(self) -> QPushButton:
        return self._down_btn

    def delete_button(self) -> QPushButton:
        return self._del_btn

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

    def __init__(self, colors: MaterialColors, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors
        self._rows: List[BatchVideoRow] = []
        self._editable = True

        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 顶部操作栏
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        self._add_btn = MaterialButton("Add videos", variant=MaterialButton.VARIANT_FILLED)
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._clear_btn = MaterialButton("Clear", variant=MaterialButton.VARIANT_TEXT)
        self._clear_btn.clicked.connect(self.clear)
        self._count_label = QLabel("0 个文件")
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
        self._placeholder = QLabel("拖放视频文件到此处，或点击「Add videos」添加")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {colors.on_surface_variant}; border: none; background: transparent;"
            " padding: 24px;"
        )
        self._list_layout.addWidget(self._placeholder)

    # ── 公开 API ──────────────────────────────────────────

    def video_paths(self) -> list[str]:
        return [row.video_path for row in self._rows]

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
            row.up_button().clicked.connect(lambda _, r=row: self._move_up(r))
            row.down_button().clicked.connect(lambda _, r=row: self._move_down(r))
            row.delete_button().clicked.connect(lambda _, r=row: self._remove(r))
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

    def set_file_finished(self, index: int, success: bool) -> None:
        if 0 <= index < len(self._rows):
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

    def _on_add_clicked(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择视频文件", "",
            "Video files (*.mp4 *.avi *.mkv *.mov *.flv *.wmv);;All files (*.*)",
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
        self._count_label.setText(f"{len(self._rows)} 个文件")

    def _refresh_placeholder(self) -> None:
        has_rows = bool(self._rows)
        self._placeholder.setVisible(not has_rows)
