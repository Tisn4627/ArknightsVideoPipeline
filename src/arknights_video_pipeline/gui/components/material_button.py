"""gui.components.material_button - MD3 按钮（五变体 + 墨层动效）

MD3 的按钮层级：一屏通常只有一个 ``filled``，其余用 ``tonal`` /
``outlined`` / ``text``。历史上的实现把**所有** ``QPushButton`` 都填成主色，
导致主页"浏览 / 开始 / 取消"全是实心紫，主次完全消失。

本组件改为**自绘**（不依赖 QSS 伪状态）：

- 五种变体：filled / tonal / elevated / outlined / text；
- 统一高度 40dp、圆角 full、左右内距 24dp（text 为 12dp）；
- 悬停叠 8%、按下 10% 的墨层，100ms 标准缓动淡入（QSS 无法过渡）；
- 2dp 焦点环，键盘可达；
- 禁用态走"容器 12% / 内容 38%"。

由于完全自绘，调用方历史上设置的按钮内联 QSS（``setStyleSheet``）会被
忽略——这正是把样式收回到唯一事实源的目的。
"""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QPushButton, QSizePolicy, QWidget

from arknights_video_pipeline.gui.assets.icons.nav_icons import has_icon, make_icon_pixmap
from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.spacing import Layout, Space
from arknights_video_pipeline.gui.theme.state import StateLayer, blend, with_alpha
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["MaterialButton"]


class MaterialButton(QPushButton):
    """MD3 按钮（自绘墨层 / 焦点环 / 五变体）"""

    VARIANT_FILLED = "filled"
    VARIANT_TONAL = "tonal"
    VARIANT_OUTLINED = "outlined"
    VARIANT_TEXT = "text"
    VARIANT_ELEVATED = "elevated"

    _ICON_SIZE = 18

    def __init__(
        self,
        text: str = "",
        variant: str = VARIANT_FILLED,
        icon: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._variant = variant
        self._icon_name = icon
        self._colors: MaterialColors = theme_controller().colors()
        self._typography = MaterialTypography()
        self._alpha = 0.0
        self._hovered = False
        self._pressed = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(self._typography.font("label_large"))
        self.setFixedHeight(Layout.BUTTON_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # 告诉全局 QSS 不要再画这个按钮（背景/边框/内距全部由自绘负责）
        self.setProperty("mdCustom", "true")
        self._sync_legacy_properties()

        self._anim = QPropertyAnimation(self, b"overlayAlpha", self)
        self._anim.setDuration(Duration.SHORT1)
        self._anim.setEasingCurve(Easing.standard())

        theme_controller().theme_changed.connect(self._on_theme_changed)

    # ── 变体 ─────────────────────────────────────────────

    def _sync_legacy_properties(self) -> None:
        """同步旧的动态属性（``mdOutlined`` / ``mdText``），保持向后兼容"""
        self.setProperty("mdOutlined", "true" if self._variant == self.VARIANT_OUTLINED else "false")
        self.setProperty("mdText", "true" if self._variant == self.VARIANT_TEXT else "false")
        self.setProperty("mdTonal", "true" if self._variant == self.VARIANT_TONAL else "false")
        self.setProperty("mdElevated", "true" if self._variant == self.VARIANT_ELEVATED else "false")

    def set_variant(self, variant: str) -> None:
        """切换变体（未知值回退到 filled）"""
        self._variant = variant if variant in (
            self.VARIANT_FILLED,
            self.VARIANT_TONAL,
            self.VARIANT_OUTLINED,
            self.VARIANT_TEXT,
            self.VARIANT_ELEVATED,
        ) else self.VARIANT_FILLED
        self._sync_legacy_properties()
        self.updateGeometry()
        self.update()

    def variant(self) -> str:
        return self._variant

    def set_icon(self, icon_name: str | None) -> None:
        """设置前导图标（Material Symbols 名称）"""
        self._icon_name = icon_name
        self.updateGeometry()
        self.update()

    def _on_theme_changed(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    # ── 几何 ─────────────────────────────────────────────

    def _horizontal_padding(self) -> int:
        return Space.M if self._variant == self.VARIANT_TEXT else Layout.BUTTON_PADDING_H

    def _content_width(self) -> int:
        metrics = QFontMetrics(self.font())
        width = metrics.horizontalAdvance(self.text())
        if self._icon_name and has_icon(self._icon_name):
            width += self._ICON_SIZE + Space.S
        return width

    def sizeHint(self):  # noqa: N802 - Qt 命名
        width = self._content_width() + 2 * self._horizontal_padding()
        return QSize(max(width, Layout.BUTTON_HEIGHT), Layout.BUTTON_HEIGHT)

    def minimumSizeHint(self):  # noqa: N802
        return self.sizeHint()

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
        if not self._pressed:
            self._animate_to(StateLayer.HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._animate_to(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._pressed = True
            self._animate_to(StateLayer.PRESSED)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._pressed = False
        self._animate_to(StateLayer.HOVER if self._hovered else 0.0)
        super().mouseReleaseEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()

    def changeEvent(self, event) -> None:
        # 启用/禁用切换时刷新绘制
        super().changeEvent(event)
        self.update()

    # ── 配色 ─────────────────────────────────────────────

    def _resolve(self) -> tuple[str, str, str, int, str]:
        """返回 (底, 前景, 描边色, 描边宽, 墨层色)"""
        c = self._colors
        if self._variant == self.VARIANT_TONAL:
            return c.secondary_container, c.on_secondary_container, "transparent", 0, c.on_secondary_container
        if self._variant == self.VARIANT_ELEVATED:
            return c.surface_container_low, c.primary, "transparent", 0, c.primary
        if self._variant == self.VARIANT_OUTLINED:
            return "transparent", c.primary, c.outline, 1, c.primary
        if self._variant == self.VARIANT_TEXT:
            return "transparent", c.primary, "transparent", 0, c.primary
        return c.primary, c.on_primary, "transparent", 0, c.on_primary

    def _disabled_colors(self) -> tuple[str, str]:
        c = self._colors
        container = blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER).name()
        content = blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTENT).name()
        return container, content

    # ── 绘制 ─────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        background, foreground, border_color, border_width, layer_color = self._resolve()
        if not self.isEnabled():
            container, content = self._disabled_colors()
            if self._variant in (self.VARIANT_FILLED, self.VARIANT_TONAL, self.VARIANT_ELEVATED):
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

        # 墨层（hover / pressed），QSS 无法过渡，因此这里用动画驱动 alpha
        if self._alpha > 0.0 and self.isEnabled():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(layer_color, self._alpha))
            painter.drawRoundedRect(rect, radius, radius)

        # 内容：图标 + 文本，整体居中
        content_width = self._content_width()
        left = (self.width() - content_width) / 2.0
        color = QColor(foreground)

        if self._icon_name and has_icon(self._icon_name):
            pixmap = make_icon_pixmap(self._icon_name, foreground, size_px=self._ICON_SIZE)
            if pixmap is not None:
                y = (self.height() - self._ICON_SIZE) / 2.0
                painter.drawPixmap(int(left), int(y), pixmap)
                left += self._ICON_SIZE + Space.S

        painter.setPen(color)
        painter.setFont(self.font())
        metrics = QFontMetrics(self.font())
        baseline_y = (self.height() + metrics.ascent() - metrics.descent()) / 2.0
        painter.drawText(int(left), int(baseline_y), self.text())

        # 焦点环：内缩 2dp，不改变几何
        if self.hasFocus() and self.isEnabled():
            ring = QPen(color)
            ring.setWidthF(2.0)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                rect.adjusted(2.5, 2.5, -2.5, -2.5), radius - 2.5, radius - 2.5
            )

        painter.end()

    # 说明：完全不调用 super().paintEvent()，避免 QStyleSheetStyle 再画一层
    # 背景/边框；这也是"按钮样式唯一事实源"的实现方式。
