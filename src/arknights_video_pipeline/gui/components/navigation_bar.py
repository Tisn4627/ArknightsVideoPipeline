"""gui.components.navigation_bar - MD3 Navigation Bar（紧凑窗口的底部导航）

当窗口宽度进入 compact 尺寸类别（< 600dp）时，侧边 Navigation Rail 会
挤占内容宽度，MD3 的做法是改为**底部导航条**：高 80dp、3-5 个目的地、
指示器 64×32、标签 ``label_medium``。

接口与 :class:`NavigationRail` 保持一致（``selection_changed`` /
``set_selected`` / ``set_colors`` / ``current_index``），页面层可无差别切换。
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QPropertyAnimation, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from arknights_video_pipeline.gui.assets.icons.nav_icons import has_icon, make_icon_pixmap
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.spacing import Layout, Space
from arknights_video_pipeline.gui.theme.state import StateLayer, with_alpha
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["NavigationBar", "NavigationBarItem"]


def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
    ratio = min(1.0, max(0.0, t))
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * ratio),
        round(c1.green() + (c2.green() - c1.green()) * ratio),
        round(c1.blue() + (c2.blue() - c1.blue()) * ratio),
    )


class NavigationBarItem(QWidget):
    """底部导航的单个目的地（64×32 指示器 + 标签）"""

    clicked = pyqtSignal()

    _INDICATOR_W = Layout.NAV_BAR_INDICATOR_WIDTH
    _INDICATOR_H = Layout.NAV_INDICATOR_HEIGHT
    _ICON = 24

    def __init__(self, icon: str, label: str, selected: bool = False,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon
        self._selected = selected
        self._hovered = False
        self._hover_alpha = 0.0
        self._progress = 1.0 if selected else 0.0
        self._colors = colors or theme_controller().colors()
        self._typography = MaterialTypography()
        self._pixmap = None
        self._icon_key: tuple[str, str] | None = None

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(56)
        self.setMinimumWidth(Layout.NAV_BAR_INDICATOR_WIDTH + Space.L)

        self._label = QLabel(label, self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFont(self._typography.font("label_medium"))
        self._label.setStyleSheet("background: transparent; border: none;")

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(Duration.MEDIUM1)
        self._anim.setEasingCurve(Easing.emphasized())

        self._hover_anim = QPropertyAnimation(self, b"hoverAlpha", self)
        self._hover_anim.setDuration(Duration.SHORT1)
        self._hover_anim.setEasingCurve(Easing.standard())

    # ── 接口 ─────────────────────────────────────────────

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._icon_key = None
        self.update()

    def set_selected(self, selected: bool, animate: bool = True) -> None:
        self._selected = selected
        target = 1.0 if selected else 0.0
        if abs(target - self._progress) < 1e-6:
            return
        duration = Motion.duration(Duration.MEDIUM1) if animate else 0
        if duration <= 0:
            self._set_progress(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    # ── 动画属性 ─────────────────────────────────────────

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        if value == self._progress:
            return
        self._progress = value
        self._icon_key = None
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
        x = (self.width() - self._INDICATOR_W) / 2.0
        return QRectF(x, 0.0, float(self._INDICATOR_W), float(self._INDICATOR_H))

    def resizeEvent(self, event) -> None:
        self._label.setGeometry(
            0,
            self._INDICATOR_H + Space.XS,
            self.width(),
            20,
        )
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        c = self._colors
        indicator = self._indicator_rect()
        radius = indicator.height() / 2.0

        if self._hover_alpha > 0.0 and self._progress < 1.0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(c.on_surface, self._hover_alpha))
            painter.drawRoundedRect(indicator, radius, radius)

        if self._progress > 0.0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(c.secondary_container, self._progress))
            painter.drawRoundedRect(indicator, radius, radius)

        color = _mix(
            QColor(c.on_surface_variant),
            QColor(c.on_secondary_container),
            self._progress,
        )
        key = (color.name(), self._icon_name)
        if self._icon_key != key and has_icon(self._icon_name):
            self._icon_key = key
            self._pixmap = make_icon_pixmap(self._icon_name, color.name(), size_px=self._ICON)
        if self._pixmap is not None:
            x = int(indicator.center().x() - self._ICON / 2)
            y = int((self._INDICATOR_H - self._ICON) / 2)
            painter.drawPixmap(x, y, self._pixmap)

        painter.end()


class NavigationBar(QWidget):
    """MD3 Navigation Bar（compact 档底部导航）"""

    selection_changed = pyqtSignal(int)

    def __init__(self, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self._items: list[NavigationBarItem] = []
        self._current_index = -1
        self._item_specs: list[tuple[str, str]] = [
            ("home", "nav.home"),
            ("settings", "nav.settings"),
            ("tools", "nav.tools"),
            ("info", "nav.info"),
        ]

        self.setFixedHeight(Layout.NAV_BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Space.S, Space.S, Space.S, Space.S)
        layout.setSpacing(Space.XS)

        for icon_name, key in self._item_specs:
            item = NavigationBarItem(icon_name, tr(key), colors=self._colors)
            item.clicked.connect(self._make_handler(len(self._items)))
            self._items.append(item)
            layout.addWidget(item, 1)

        self.set_selected(0, animate=False)
        i18n().language_changed.connect(self._retranslate)
        theme_controller().theme_changed.connect(self.set_colors)

    # ── 接口 ─────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        """底部导航条容器：surface_container 底 + 顶部 1dp 分隔线"""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._colors.surface_container))
        painter.setPen(QColor(self._colors.outline_variant))
        painter.drawLine(0, 0, self.width(), 0)
        painter.end()

    def _retranslate(self) -> None:
        for item, (_icon, key) in zip(self._items, self._item_specs):
            item.set_label(tr(key))

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        for item in self._items:
            item.set_colors(colors)
        self.update()

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
        """底部导航本身即为紧凑形态，保留接口以与 Rail 对齐"""

    def current_index(self) -> int:
        return self._current_index

    def _make_handler(self, index: int):
        def handler():
            self.set_selected(index)
        return handler
