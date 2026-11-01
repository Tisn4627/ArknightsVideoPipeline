"""gui.components.navigation_rail - MD3 Navigation Rail

规格（MD3）：轨道宽 80dp；每个目的地由 **56×32 的胶囊指示器（圆角 16）**
包住 24dp 图标，标签 ``label_medium`` 位于指示器下方 4dp。

历史实现的选中态把"整个 64×56 的 item"填成胶囊（半径取高度一半），
视觉重量过大、四个目的地挤在一起像侧边标签页；这里改为标准指示器。

交互：

- 未选中图标/标签 ``on_surface_variant``，选中 ``on_secondary_container``；
- 悬停 8% 墨层（只覆盖指示器区域）；
- 指示器 250ms 强调缓动淡入淡出；
- 支持紧凑模式（只显示图标，用于 medium 尺寸类别）。
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QRectF,
    QPropertyAnimation,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from arknights_video_pipeline.gui.assets.app_icon import load_app_icon
from arknights_video_pipeline.gui.assets.icons.nav_icons import has_icon, make_icon_pixmap
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.spacing import Layout, Space
from arknights_video_pipeline.gui.theme.state import StateLayer, with_alpha
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["NavigationRail", "NavigationRailItem"]


def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
    """在 c1(t=0) 与 c2(t=1) 之间线性插值"""
    ratio = min(1.0, max(0.0, t))
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * ratio),
        round(c1.green() + (c2.green() - c1.green()) * ratio),
        round(c1.blue() + (c2.blue() - c1.blue()) * ratio),
    )


class NavigationRailItem(QWidget):
    """单个导航目的地（图标胶囊 + 标签）"""

    clicked = pyqtSignal()

    _WIDTH = 56
    _INDICATOR_H = 32
    _ICON = 24
    _LABEL_GAP = Space.XS

    def __init__(self, icon: str, label: str, selected: bool = False,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label_text = label
        self._icon_name = icon
        self._selected = selected
        self._compact = False
        self._hovered = False
        self._colors = colors or theme_controller().colors()
        self._progress = 1.0 if selected else 0.0
        self._hover_alpha = 0.0
        self._typography = MaterialTypography()
        self._icon_cache: tuple[str, str] | None = None

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(self._WIDTH)
        self.setFixedHeight(self._INDICATOR_H + self._LABEL_GAP + 20)

        self._label = QLabel(label, self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._label.setFont(self._typography.font("label_medium"))
        self._label.setFixedSize(self._WIDTH, 20)
        self._label.move(0, self._INDICATOR_H + self._LABEL_GAP)
        self._label.setStyleSheet(
            f"color: {self._label_color().name()};"
            " background: transparent; border: none;"
        )

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(Duration.MEDIUM2)
        self._anim.setEasingCurve(Easing.emphasized())

        self._hover_anim = QPropertyAnimation(self, b"hoverAlpha", self)
        self._hover_anim.setDuration(Duration.SHORT1)
        self._hover_anim.setEasingCurve(Easing.standard())

    # ── 接口 ─────────────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._icon_cache = None
        # 标签是 QLabel + 一次性样式，必须随主题重设，
        # 否则深色下残留浅色主题的 on_surface_variant（选中项甚至不可见）
        self._label.setStyleSheet(
            f"color: {self._label_color().name()}; background: transparent; border: none;"
        )
        self.update()

    def set_selected(self, selected: bool, animate: bool = True) -> None:
        self._selected = selected
        target = 1.0 if selected else 0.0
        if abs(target - self._progress) < 1e-6:
            self._anim.stop()
            return
        duration = Motion.duration(Duration.MEDIUM2) if animate else 0
        if duration <= 0:
            self._anim.stop()
            self._set_progress(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    def set_compact(self, compact: bool) -> None:
        """紧凑模式：隐藏标签，只保留 56×32 指示器"""
        if compact == self._compact:
            return
        self._compact = compact
        self._label.setVisible(not compact)
        self.setFixedHeight(self._INDICATOR_H if compact else self._INDICATOR_H + self._LABEL_GAP + 20)
        self.update()

    def set_label(self, text: str) -> None:
        """更新标签文本（语言切换时调用）"""
        self._label_text = text
        self._label.setText(text)

    # ── 动画属性 ─────────────────────────────────────────

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        if value == self._progress:
            return
        self._progress = value
        self._icon_cache = None
        self._label.setStyleSheet(
            f"color: {self._label_color().name()}; background: transparent; border: none;"
        )
        self.update()

    progress = pyqtProperty(float, fget=_get_progress, fset=_set_progress)

    def _get_hover(self) -> float:
        return self._hover_alpha

    def _set_hover(self, value: float) -> None:
        if value == self._hover_alpha:
            return
        self._hover_alpha = value
        self.update()

    hoverAlpha = pyqtProperty(float, fget=_get_hover, fset=_set_hover)

    def _animate_hover(self, target: float) -> None:
        duration = Motion.duration(Duration.SHORT1)
        if duration <= 0:
            self._set_hover(target)
            return
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_alpha)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    # ── 事件 ─────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._animate_hover(StateLayer.HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._animate_hover(0.0)
        super().leaveEvent(event)

    # ── 绘制 ─────────────────────────────────────────────

    def _label_color(self) -> QColor:
        return _mix(
            QColor(self._colors.on_surface_variant),
            QColor(self._colors.on_secondary_container),
            self._progress,
        )

    def _indicator_rect(self) -> QRectF:
        return QRectF(0.0, 0.0, float(self._WIDTH), float(self._INDICATOR_H))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        c = self._colors
        indicator = self._indicator_rect()
        radius = indicator.height() / 2.0

        # 悬停墨层（只覆盖指示器）
        if self._hover_alpha > 0.0 and self._progress < 1.0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(c.on_surface, self._hover_alpha))
            painter.drawRoundedRect(indicator, radius, radius)

        # 选中指示器
        if self._progress > 0.0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(c.secondary_container, self._progress))
            painter.drawRoundedRect(indicator, radius, radius)

        # 图标（颜色随选中进度插值，缓存避免逐帧栅格化）
        color = _mix(
            QColor(c.on_surface_variant),
            QColor(c.on_secondary_container),
            self._progress,
        )
        key = (color.name(), self._icon_name)
        if self._icon_cache != key and has_icon(self._icon_name):
            self._icon_cache = key
            pixmap = make_icon_pixmap(self._icon_name, color.name(), size_px=self._ICON)
            self._pixmap = pixmap
        pixmap = getattr(self, "_pixmap", None)
        if pixmap is not None:
            x = (self._WIDTH - self._ICON) // 2
            y = (self._INDICATOR_H - self._ICON) // 2
            painter.drawPixmap(x, y, pixmap)

        painter.end()


class NavigationRail(QFrame):
    """MD3 Navigation Rail（宽 80dp）"""

    selection_changed = pyqtSignal(int)

    _WIDTH = Layout.NAV_RAIL_WIDTH

    def __init__(self, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self.setFixedWidth(self._WIDTH)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._items: list[NavigationRailItem] = []
        self._current_index = -1
        self._compact = False
        self._item_specs: list[tuple[str, str]] = [
            ("home", "nav.home"),
            ("settings", "nav.settings"),
            ("tools", "nav.tools"),
            ("info", "nav.info"),
        ]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.M, Space.M, Space.M, Space.M)
        layout.setSpacing(Space.S)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout = layout

        # 顶部品牌槽位：应用图标（MD3 rail 的 menu / logo slot）
        self._logo = QLabel(self)
        self._logo.setFixedSize(32, 32)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo.setStyleSheet("background: transparent; border: none;")
        pixmap = load_app_icon().pixmap(QSize(32, 32))
        if not pixmap.isNull():
            self._logo.setPixmap(pixmap)
        layout.addWidget(self._logo, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(Space.L)

        for icon_name, key in self._item_specs:
            item = NavigationRailItem(icon_name, tr(key), colors=self._colors)
            item.clicked.connect(self._make_handler(len(self._items)))
            self._items.append(item)
            layout.addWidget(item, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch()

        self.set_selected(0, animate=False)
        i18n().language_changed.connect(self._retranslate)
        theme_controller().theme_changed.connect(self.set_colors)

    # ── 接口 ─────────────────────────────────────────────

    def _retranslate(self) -> None:
        for item, (_icon, key) in zip(self._items, self._item_specs):
            item.set_label(tr(key))

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        for item in self._items:
            item.set_colors(colors)

    def add_top_widget(self, widget: QWidget) -> None:
        """在导航项上方插入控件（MD3 rail 的菜单 / FAB 槽位）"""
        self._layout.insertWidget(0, widget, 0, Qt.AlignmentFlag.AlignHCenter)

    def add_bottom_widget(self, widget: QWidget) -> None:
        """在导航项下方（底部槽位）插入控件"""
        self._layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_selected(self, index: int, animate: bool = True) -> None:
        if index == self._current_index:
            return
        if 0 <= index < len(self._items):
            if self._current_index >= 0:
                self._items[self._current_index].set_selected(False, animate)
            self._current_index = index
            self._items[self._current_index].set_selected(True, animate)
            self.selection_changed.emit(index)

    def set_compact(self, compact: bool) -> None:
        """紧凑模式：隐藏标签（rail 宽度保持 80dp，指示器仍为 56×32）"""
        if compact == self._compact:
            return
        self._compact = compact
        for item in self._items:
            item.set_compact(compact)

    def current_index(self) -> int:
        return self._current_index

    def _make_handler(self, index: int):
        def handler():
            self.set_selected(index)
        return handler
