"""
gui.components.navigation_rail - Material Design 3 Navigation Rail

左侧垂直导航栏，支持图标+标签，选中态高亮，响应式折叠为仅图标模式。
支持浅色/深色主题切换。

图标使用 MD3 24dp Material Icons (Filled)：
    Home、Settings、Info。图标资源在 gui/assets/icons/nav/，
    加载/着色由 gui.assets.icons.nav_icons 提供。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame

from arknights_video_pipeline.gui.assets.icons.nav_icons import (
    has_icon, make_icon_pixmap,
)
from arknights_video_pipeline.gui.theme import MaterialColors


class NavigationRailItem(QWidget):
    """单个导航项"""

    clicked = pyqtSignal()

    def __init__(self, icon: str, label: str, selected: bool = False,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label_text = label
        self._icon_name = icon  # 资源名（home / settings / info）
        self._selected = selected
        self._compact = False
        self._colors = colors or MaterialColors.light()

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(56)
        # 固定宽度与 nav rail 内容宽度一致，确保图标准确居中
        # (88px rail - 12*2 边距 = 64px)
        self.setFixedWidth(64)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        # 图标 24dp（@2x DPR 下显示 48px），与 MD3 NavigationRail 规范一致
        # 使用固定 24x24 并显式居中 + qproperty-alignment，确保不同 DPI 下
        # 图标与文字共享同一条水平中心线
        self._icon_label = QLabel()
        self._icon_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._icon_label.setFixedSize(24, 24)
        self._icon_label.setStyleSheet(
            "border: none; background: transparent;"
            " qproperty-alignment: AlignHCenter;"
        )
        layout.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._label = QLabel(label)
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._label.setMaximumWidth(72)  # 限定最大宽度，挤压居中
        self._label.setStyleSheet(
            "font-size: 12px; font-weight: 500; border: none; background: transparent;"
            " qproperty-alignment: AlignHCenter;"
        )
        layout.addWidget(self._label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._update_style()

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._update_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_style()

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self._label.setVisible(not compact)
        # compact 模式下 item 高度更紧凑，宽度与 rail 内容宽度同步
        # (56px rail - 8*2 margins = 40px)
        if compact:
            self.setFixedHeight(48)
            self.setFixedWidth(40)
        else:
            self.setFixedHeight(56)
            self.setFixedWidth(64)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)

    def _update_style(self) -> None:
        c = self._colors
        if self._selected:
            self.setStyleSheet(
                f"NavigationRailItem {{ background-color: {c.primary_container}; "
                f"border-radius: 28px; }}"
            )
            icon_color = c.on_primary_container
            text_color = c.on_primary_container
        else:
            self.setStyleSheet(
                f"NavigationRailItem {{ background-color: transparent; border-radius: 28px; }}"
                f"NavigationRailItem:hover {{ background-color: {c.surface_variant}; }}"
            )
            icon_color = c.on_surface_variant
            text_color = c.on_surface_variant

        # 刷新 MD3 着色图标
        if has_icon(self._icon_name):
            pix = make_icon_pixmap(self._icon_name, icon_color, size_px=24)
            if pix is not None:
                self._icon_label.setPixmap(pix)
        # 文字样式
        self._label.setStyleSheet(
            f"font-size: 12px; font-weight: 500; color: {text_color}; "
            "border: none; background: transparent;"
        )


class NavigationRail(QFrame):
    """Material Design 3 Navigation Rail"""

    selection_changed = pyqtSignal(int)

    def __init__(self, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        self.setFixedWidth(88)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._items: list[NavigationRailItem] = []
        self._current_index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # 让 child 自身水平居中（每个 item 宽度固定为 64px = 88-12*2）
        layout.addStretch(0)

        # 三个 MD3 NavigationRail 目的地：Home / Settings / Info
        for icon_name, label in [
            ("home", "Home"),
            ("settings", "Settings"),
            ("info", "Info"),
        ]:
            item = NavigationRailItem(icon_name, label, colors=self._colors)
            item.clicked.connect(self._make_handler(len(self._items)))
            self._items.append(item)
            layout.addWidget(item, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch()

        self.set_selected(0)

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        for item in self._items:
            item.set_colors(colors)

    def set_selected(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self._items[self._current_index].set_selected(False)
            self._current_index = index
            self._items[self._current_index].set_selected(True)
            self.selection_changed.emit(index)

    def set_compact(self, compact: bool) -> None:
        self.setFixedWidth(56 if compact else 88)
        # margins 同步收缩：compact 56 - 8*2 = 40（与 item 40px 居中匹配）
        # normal 88 - 12*2 = 64（与 item 64px 居中匹配）
        if compact:
            self.layout().setContentsMargins(8, 12, 8, 12)
        else:
            self.layout().setContentsMargins(12, 16, 12, 16)
        for item in self._items:
            item.set_compact(compact)

    def _make_handler(self, index: int):
        def handler():
            self.set_selected(index)
        return handler
