"""gui.components.material_fab - MD3 悬浮操作按钮（FAB）

MD3 的 FAB 是"当前页面主操作"的锚点，通常固定在右下角、elevation 3：

- **regular**：56dp 圆形，图标 24dp；
- **extended**：高 56dp、圆角 16dp、左右内距 20dp，图标 + 文字。

本实现自绘容器与墨层，阴影用 ``QGraphicsDropShadowEffect`` 的 elevation 3
参数（``Elevation.effect``）。FAB 数量应保持为每屏一个。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QFontMetrics, QPainter
from PyQt6.QtWidgets import (
    QAbstractButton,
    QGraphicsDropShadowEffect,
    QSizePolicy,
    QWidget,
)

from arknights_video_pipeline.gui.assets.icons.nav_icons import has_icon, make_icon_pixmap
from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.spacing import Layout, Space
from arknights_video_pipeline.gui.theme.state import Elevation, StateLayer, blend, with_alpha
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["MaterialFab"]


class MaterialFab(QAbstractButton):
    """MD3 FAB（regular / extended）"""

    _ICON_SIZE = 24
    _H_PADDING = Space.XL  # 20dp 左右内距（extended）

    def __init__(
        self,
        icon_name: str,
        text: str = "",
        extended: bool = False,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._extended = extended
        self._colors: MaterialColors = theme_controller().colors()
        self._typography = MaterialTypography()
        self._alpha = 0.0

        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(self._typography.font("label_large"))
        self.setFixedHeight(Layout.FAB_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._apply_shadow()
        self.setGraphicsEffect(self._shadow)

        self._anim = QPropertyAnimation(self, b"overlayAlpha", self)
        self._anim.setDuration(Duration.SHORT1)
        self._anim.setEasingCurve(Easing.standard())

        theme_controller().theme_changed.connect(self._on_theme_changed)

    # ── 接口 ─────────────────────────────────────────────

    def set_extended(self, extended: bool) -> None:
        self._extended = extended
        self.updateGeometry()
        self.update()

    def set_icon(self, icon_name: str) -> None:
        self._icon_name = icon_name
        self.update()

    def _on_theme_changed(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._apply_shadow()
        self.update()

    def _apply_shadow(self) -> None:
        blur, offset, alpha = Elevation.effect(Elevation.FAB, self._colors.is_dark)
        self._shadow.setBlurRadius(max(1, blur))
        self._shadow.setOffset(QPointF(0, max(1, offset)))
        self._shadow.setColor(QColor(0, 0, 0, alpha))

    def sizeHint(self) -> QSize:  # noqa: N802
        if not self._extended:
            return QSize(Layout.FAB_SIZE, Layout.FAB_SIZE)
        metrics = QFontMetrics(self.font())
        width = (
            self._H_PADDING * 2
            + self._ICON_SIZE
            + Space.M
            + metrics.horizontalAdvance(self.text())
        )
        return QSize(max(Layout.FAB_SIZE + Space.L, width), Layout.FAB_SIZE)

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
        self._animate_to(StateLayer.HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_to(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._animate_to(StateLayer.PRESSED)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._animate_to(StateLayer.HOVER)
        super().mouseReleaseEvent(event)

    # ── 绘制 ─────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        c = self._colors
        background, foreground = c.primary_container, c.on_primary_container
        if not self.isEnabled():
            background = blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER).name()
            foreground = blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTENT).name()

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 16.0 if self._extended else rect.height() / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, radius, radius)

        if self._alpha > 0.0 and self.isEnabled():
            painter.setBrush(with_alpha(foreground, self._alpha))
            painter.drawRoundedRect(rect, radius, radius)

        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self.text()) if self._extended else 0
        content_width = self._ICON_SIZE + (Space.M + text_width if self._extended else 0)
        left = (self.width() - content_width) / 2.0

        if has_icon(self._icon_name):
            pixmap = make_icon_pixmap(self._icon_name, foreground, size_px=self._ICON_SIZE)
            if pixmap is not None:
                painter.drawPixmap(
                    int(left), (self.height() - self._ICON_SIZE) // 2, pixmap
                )

        if self._extended and self.text():
            painter.setPen(QColor(foreground))
            painter.setFont(self.font())
            baseline = (self.height() + metrics.ascent() - metrics.descent()) / 2.0
            painter.drawText(
                int(left + self._ICON_SIZE + Space.M), int(baseline), self.text()
            )

        painter.end()
