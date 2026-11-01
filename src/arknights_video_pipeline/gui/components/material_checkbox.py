"""gui.components.material_checkbox - MD3 复选框

完全自绘 indicator（PyQt 的 ``QCheckBox::indicator`` 不支持用 SVG 替换
内置渲染），状态如下：

- 未选中：透明底 + 2dp ``on_surface_variant`` 描边；
- 选中：``primary`` 填充 + **``on_primary`` 对勾**（历史上硬编码白色，
  深色主题下浅紫底 + 白勾对比度仅约 1.7:1，几乎看不见）；
- 悬停：8% 墨层（indicator 外围 40dp 圆形），描边转 ``on_surface``；
- 禁用：容器 12% / 内容 38%；
- 勾选有 150ms 描边展开动画，焦点有 2dp 焦点环。
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, QRectF, QPropertyAnimation, QPointF, QSize, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QLabel, QWidget

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.palette import set_text_color
from arknights_video_pipeline.gui.theme.state import StateLayer, blend, with_alpha
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["MaterialCheckBox"]


class MaterialCheckBox(QWidget):
    """MD3 复选框：自绘 indicator + 文本标签 + 勾选动画"""

    toggled = pyqtSignal(bool)

    INDICATOR_SIZE = 18

    def __init__(self, text: str = "", colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = False
        self._colors = colors or theme_controller().colors()
        self._hover = False
        self._alpha = 0.0
        self._check = 0.0  # 勾选进度（0-1）
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 文本子控件（右侧 label），左侧 indicator 由 paintEvent 自绘
        # 字号走 QFont、文字色走 QPalette：不设 widget 级样式表，
        # 主题切换时无需逐个重设（省掉 polish 与布局失效）
        self._label = QLabel(text, self)
        self._label.setFont(MaterialTypography().font("body_medium"))
        set_text_color(self._label, self._colors.on_surface)
        self._label.move(self.INDICATOR_SIZE + 8, 0)
        self._label.adjustSize()
        self._relayout()

        self._check_anim = QPropertyAnimation(self, b"checkProgress", self)
        self._check_anim.setDuration(Duration.SHORT2)
        self._check_anim.setEasingCurve(Easing.standard())

        self._layer_anim = QPropertyAnimation(self, b"overlayAlpha", self)
        self._layer_anim.setDuration(Duration.SHORT1)
        self._layer_anim.setEasingCurve(Easing.standard())

        # 订阅主题：indicator 与文字颜色自动跟随
        theme_controller().theme_changed.connect(self.set_colors)

    # ── 动画属性 ─────────────────────────────────────────

    def _get_check(self) -> float:
        return self._check

    def _set_check(self, value: float) -> None:
        if value == self._check:
            return
        self._check = value
        self.update()

    checkProgress = pyqtProperty(float, fget=_get_check, fset=_set_check)

    def _get_alpha(self) -> float:
        return self._alpha

    def _set_alpha(self, value: float) -> None:
        if value == self._alpha:
            return
        self._alpha = value
        self.update()

    overlayAlpha = pyqtProperty(float, fget=_get_alpha, fset=_set_alpha)

    def _animate_check(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        duration = Motion.duration(Duration.SHORT2)
        if duration <= 0:
            self._set_check(target)
            return
        self._check_anim.stop()
        self._check_anim.setStartValue(self._check)
        self._check_anim.setEndValue(target)
        self._check_anim.start()

    def _animate_layer(self, target: float) -> None:
        duration = Motion.duration(Duration.SHORT1)
        if duration <= 0:
            self._set_alpha(target)
            return
        self._layer_anim.stop()
        self._layer_anim.setStartValue(self._alpha)
        self._layer_anim.setEndValue(target)
        self._layer_anim.start()

    # ── 状态接口 ──────────────────────────────────────────

    def isChecked(self) -> bool:  # noqa: N802 - Qt 命名
        return self._checked

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        if checked == self._checked:
            return
        self._checked = checked
        self._animate_check(checked)
        self.toggled.emit(checked)

    def setCheckedSilent(self, checked: bool) -> None:  # noqa: N802
        """程序化回填且不发射 toggled（加载配置/重置默认值场景）"""
        if checked == self._checked:
            return
        self.blockSignals(True)
        try:
            self.setChecked(checked)
        finally:
            self.blockSignals(False)

    def setText(self, text: str) -> None:  # noqa: N802
        self._label.setText(text)
        self._label.adjustSize()
        self._relayout()

    def text(self) -> str:
        return self._label.text()

    def _relayout(self) -> None:
        """根据文字与 indicator 调整 self 大小，保持上下居中。"""
        fm = self._label.fontMetrics()
        w = self.INDICATOR_SIZE + 8 + fm.horizontalAdvance(self._label.text()) + 4
        h = max(self.INDICATOR_SIZE, fm.height() + 4)
        self.setFixedSize(int(w), int(h))
        self._label.move(self.INDICATOR_SIZE + 8, (h - fm.height()) // 2)

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        set_text_color(self._label, colors.on_surface)
        self.update()

    # ── 事件 ──────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self._animate_layer(StateLayer.HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._animate_layer(0.0)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.setChecked(not self._checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self._label.fontMetrics()
        return QSize(self.INDICATOR_SIZE + 8 + fm.horizontalAdvance(self._label.text()) + 4,
                     max(self.INDICATOR_SIZE, fm.height() + 4))

    def resizeEvent(self, event) -> None:  # noqa: N802
        fm = self._label.fontMetrics()
        self._label.move(self.INDICATOR_SIZE + 8, (self.height() - fm.height()) // 2)
        super().resizeEvent(event)

    # ── 绘制 ─────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        c = self._colors
        enabled = self.isEnabled()
        size = self.INDICATOR_SIZE
        rect = QRect(0, (self.height() - size) // 2, size, size)
        center = QPointF(rect.center())

        # 墨层：indicator 外围 20dp 圆形
        if self._alpha > 0.0 and enabled:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(c.on_surface, self._alpha))
            painter.drawEllipse(center, 20.0, 20.0)

        if not enabled:
            painter.setOpacity(1.0)

        if self._checked:
            container = (
                c.primary
                if enabled
                else blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER).name()
            )
            content = (
                c.on_primary
                if enabled
                else blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTENT).name()
            )
            painter.setBrush(QColor(container))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 2.0, 2.0)

            # 对勾：按进度展开（0 → 完整路径）
            s = size / 24.0
            full = QPainterPath()
            full.moveTo(3 * s, 12 * s)
            full.lineTo(10 * s, 18 * s)
            full.lineTo(21 * s, 5 * s)
            pen = QPen(QColor(content))
            pen.setWidthF(2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._check >= 0.999:
                painter.drawPath(full)
            else:
                painter.setOpacity(max(0.0, min(1.0, self._check)))
                painter.drawPath(full)
                painter.setOpacity(1.0)
        else:
            border_color = (
                c.on_surface_variant if enabled
                else blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTENT).name()
            )
            if self._hover and enabled:
                border_color = c.on_surface
            pen = QPen(QColor(border_color))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 2.0, 2.0)

        # 焦点环
        if self.hasFocus() and enabled:
            ring = QPen(QColor(c.primary))
            ring.setWidthF(2.0)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(rect).adjusted(-3, -3, 3, 3), 4.0, 4.0)

        painter.end()
