"""gui.components.material_icon_button - MD3 图标按钮

MD3 icon button：40dp 命中区、24dp 图标、圆形墨层，四种变体：

- ``standard``：透明底 + ``on_surface_variant`` 图标；
- ``filled``：``primary`` 底 + ``on_primary`` 图标；
- ``tonal``：``secondary_container`` 底 + ``on_secondary_container``；
- ``outlined``：1dp ``outline`` 描边 + ``on_surface_variant`` 图标。

用于列表行、工具栏等密集操作区，替代"QPushButton + 小图标"的工具栏式外观。
"""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from arknights_video_pipeline.gui.assets.icons.nav_icons import (
    has_icon,
    make_icon_pixmap,
)
from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.spacing import Layout
from arknights_video_pipeline.gui.theme.state import StateLayer, blend, with_alpha
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller

__all__ = ["MaterialIconButton"]


class MaterialIconButton(QAbstractButton):
    """MD3 图标按钮（自绘墨层 + 焦点环）"""

    VARIANT_STANDARD = "standard"
    VARIANT_FILLED = "filled"
    VARIANT_TONAL = "tonal"
    VARIANT_OUTLINED = "outlined"

    def __init__(
        self,
        icon_name: str,
        tooltip: str = "",
        variant: str = VARIANT_STANDARD,
        *,
        size: int = Layout.ICON_BUTTON_SIZE,
        icon_size: int = 24,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._variant = variant
        self._size = size
        self._icon_size = icon_size
        self._colors: MaterialColors = theme_controller().colors()
        self._alpha = 0.0
        self._hovered = False
        self._keyboard_focus = False
        self._tint_role: str | None = None

        self.setToolTip(tooltip)
        # 纯图标按钮必须有可读名称（屏幕阅读器 / 无障碍工具）
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._anim = QPropertyAnimation(self, b"overlayAlpha", self)
        self._anim.setDuration(Duration.SHORT1)
        self._anim.setEasingCurve(Easing.standard())

        theme_controller().theme_changed.connect(self._on_theme_changed)

    # ── 接口 ─────────────────────────────────────────────

    def set_icon(self, icon_name: str) -> None:
        self._icon_name = icon_name
        self.update()

    def set_variant(self, variant: str) -> None:
        self._variant = variant
        self.update()

    def set_tint_role(self, role: str | None) -> None:
        """按角色名覆盖图标颜色（如 ``primary`` 表示"已启用/已绑定"）"""
        self._tint_role = role
        self.update()

    def _on_theme_changed(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._size, self._size)

    # ── 动画属性 ─────────────────────────────────────────

    def _get_alpha(self) -> float:
        return self._alpha

    def _set_alpha(self, value: float) -> None:
        if value == self._alpha:
            return
        self._alpha = value
        self.update()

    overlayAlpha = pyqtProperty(float, fget=_get_alpha, fset=_set_alpha)

    def _animate_to(self, target: float) -> None:
        duration = Motion.duration(Duration.SHORT1)
        if duration <= 0:
            self._set_alpha(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._alpha)
        self._anim.setEndValue(target)
        self._anim.start()

    # ── 事件 ─────────────────────────────────────────────

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._animate_to(StateLayer.HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._animate_to(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._animate_to(StateLayer.PRESSED)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._animate_to(StateLayer.HOVER if self._hovered else 0.0)
        super().mouseReleaseEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._keyboard_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        )
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._keyboard_focus = False
        self.update()

    # ── 绘制 ─────────────────────────────────────────────

    def _resolve(self) -> tuple[str, str, str, int, str]:
        c = self._colors
        if self._variant == self.VARIANT_FILLED:
            return c.primary, c.on_primary, "transparent", 0, c.on_primary
        if self._variant == self.VARIANT_TONAL:
            return (
                c.secondary_container,
                c.on_secondary_container,
                "transparent",
                0,
                c.on_secondary_container,
            )
        foreground = (
            getattr(c, self._tint_role, c.on_surface_variant)
            if self._tint_role
            else c.on_surface_variant
        )
        if self._variant == self.VARIANT_OUTLINED:
            return "transparent", foreground, c.outline, 1, foreground
        return "transparent", foreground, "transparent", 0, foreground

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        background, foreground, border_color, border_width, layer_color = self._resolve()
        if not self.isEnabled():
            container = blend(
                self._colors.surface,
                self._colors.on_surface,
                StateLayer.DISABLED_CONTAINER,
            ).name()
            content = blend(
                self._colors.surface,
                self._colors.on_surface,
                StateLayer.DISABLED_CONTENT,
            ).name()
            if self._variant in (self.VARIANT_FILLED, self.VARIANT_TONAL):
                background = container
            foreground = content
            border_color = container if self._variant == self.VARIANT_OUTLINED else "transparent"
            border_width = 1 if self._variant == self.VARIANT_OUTLINED else 0

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = rect.height() / 2.0

        if background != "transparent":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(rect, radius, radius)

        if border_width:
            pen = QPen(QColor(border_color))
            pen.setWidthF(float(border_width))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, radius, radius)

        if self._alpha > 0.0 and self.isEnabled():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(layer_color, self._alpha))
            painter.drawRoundedRect(rect, radius, radius)

        if has_icon(self._icon_name):
            pixmap = make_icon_pixmap(self._icon_name, foreground, size_px=self._icon_size)
            if pixmap is not None:
                x = (self.width() - self._icon_size) // 2
                y = (self.height() - self._icon_size) // 2
                painter.drawPixmap(x, y, pixmap)

        if self._keyboard_focus and self.isEnabled():
            ring = QPen(QColor(foreground))
            ring.setWidthF(2.0)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                rect.adjusted(2.5, 2.5, -2.5, -2.5), radius - 2.5, radius - 2.5
            )

        painter.end()
