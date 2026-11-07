"""gui.components.material_switch - MD3 开关

规格（MD3）：轨道 52×32、圆角 full；滑块选中 24dp（距轨道边缘 4dp）/
未选中 16dp（距轨道边缘 8dp）；选中轨道 ``primary`` + ``on_primary`` 滑块；
未选中轨道 ``surface_container_highest`` + 2dp ``outline`` 描边 +
``outline`` 滑块。

交互：悬停/按下有 8% / 10% 墨层（滑块外围 40dp 圆形），状态切换有
200ms 强调缓动（滑块位移 + 尺寸 + 轨道变色），禁用走容器 12% / 内容 38%。
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.state import StateLayer, blend, with_alpha
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller

__all__ = ["MaterialSwitch"]


class MaterialSwitch(QWidget):
    """MD3 开关（自绘、带动画与墨层）"""

    toggled = pyqtSignal(bool)

    _TRACK_W = 52
    _TRACK_H = 32
    _THUMB_ON = 24.0
    _THUMB_OFF = 16.0
    # 40dp 状态层的安全区：轨道四周各留 4dp，避免 hover 墨层被控件
    # 边界裁切成直角/半圆
    _SAFE_PAD = 4.0
    _WIDGET_W = _TRACK_W + 2 * int(_SAFE_PAD)
    _WIDGET_H = _TRACK_H + 2 * int(_SAFE_PAD)

    def __init__(self, checked: bool = False,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self._colors = colors or theme_controller().colors()
        self._progress = 1.0 if checked else 0.0
        self._alpha = 0.0
        self._hovered = False
        self._keyboard_focus = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(self._WIDGET_W, self._WIDGET_H)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: transparent; border: none;")

        self._anim = QPropertyAnimation(self, b"toggleProgress", self)
        self._anim.setDuration(Duration.MEDIUM1)
        self._anim.setEasingCurve(Easing.emphasized_decelerate())

        self._layer_anim = QPropertyAnimation(self, b"overlayAlpha", self)
        self._layer_anim.setDuration(Duration.SHORT1)
        self._layer_anim.setEasingCurve(Easing.standard())

        theme_controller().theme_changed.connect(self.set_colors)

    # ── 状态接口 ─────────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool) -> None:
        """以编程方式设置状态（会发射 toggled 信号）"""
        if self._checked != checked:
            self._checked = checked
            self._animate_toggle()
            self.toggled.emit(self._checked)

    def set_checked_silent(self, checked: bool) -> None:
        """程序化回填且不发射 toggled。

        供加载配置/重置默认值场景使用，替代调用方手写
        ``blockSignals(True) + set_checked + blockSignals(False)`` 样板
        （Qt 的 QAbstractButton.setChecked 即为静默语义）。
        """
        if self._checked == checked:
            return
        self.blockSignals(True)
        try:
            self.set_checked(checked)
        finally:
            self.blockSignals(False)

    # ── 动画属性 ─────────────────────────────────────────

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        if value == self._progress:
            return
        self._progress = value
        self.update()

    toggleProgress = pyqtProperty(float, fget=_get_progress, fset=_set_progress)

    def _get_alpha(self) -> float:
        return self._alpha

    def _set_alpha(self, value: float) -> None:
        if value == self._alpha:
            return
        self._alpha = value
        self.update()

    overlayAlpha = pyqtProperty(float, fget=_get_alpha, fset=_set_alpha)

    def _animate_toggle(self) -> None:
        target = 1.0 if self._checked else 0.0
        duration = Motion.duration(Duration.MEDIUM1)
        if duration <= 0:
            self._set_progress(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    def _animate_layer(self, target: float) -> None:
        duration = Motion.duration(Duration.SHORT1)
        if duration <= 0:
            self._set_alpha(target)
            return
        self._layer_anim.stop()
        self._layer_anim.setStartValue(self._alpha)
        self._layer_anim.setEndValue(target)
        self._layer_anim.start()

    # ── 事件 ─────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.set_checked(not self._checked)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.set_checked(not self._checked)
        else:
            super().keyPressEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._animate_layer(StateLayer.HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._animate_layer(0.0)
        super().leaveEvent(event)

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

    @staticmethod
    def _mix(start: str, end: str, ratio: float) -> QColor:
        a, b = QColor(start), QColor(end)
        t = min(1.0, max(0.0, ratio))
        return QColor(
            int(a.red() + (b.red() - a.red()) * t + 0.5),
            int(a.green() + (b.green() - a.green()) * t + 0.5),
            int(a.blue() + (b.blue() - a.blue()) * t + 0.5),
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        c = self._colors
        enabled = self.isEnabled()
        progress = 1.0 if not enabled and self._checked else self._progress

        # 轨道 52×32 居中放在 60×40 控件内（四周 4dp 状态层安全区）；
        # 2dp 描边画在内缩 1dp 的路径上，外缘不超出控件
        pad = self._SAFE_PAD
        track = QRectF(pad, pad, self._TRACK_W, self._TRACK_H)
        radius = track.height() / 2.0

        if enabled:
            track_fill = self._mix(c.surface_container_highest, c.primary, progress)
            border = self._mix(c.outline, c.primary, progress)
            thumb_color = self._mix(c.outline, c.on_primary, progress)
        else:
            track_fill = QColor(
                blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER).name()
            )
            border = QColor(
                blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER).name()
            )
            thumb_color = QColor(
                blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTENT).name()
            )

        # 轨道
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_fill)
        painter.drawRoundedRect(track, radius, radius)

        if progress < 1.0:
            pen = QPen(border)
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                track.adjusted(1, 1, -1, -1), radius - 1.0, radius - 1.0
            )

        # 滑块：选中 24dp 距边缘 4dp（中心 36dp），未选中 16dp 距边缘
        # 8dp（中心 16dp）；尺寸与位置随进度插值，且始终完整落在轨道内
        thumb_d = self._THUMB_OFF + (self._THUMB_ON - self._THUMB_OFF) * progress
        off_center_x = pad + 16.0
        on_center_x = pad + self._TRACK_W - 16.0
        center_x = off_center_x + (on_center_x - off_center_x) * progress
        center = QPointF(center_x, pad + self._TRACK_H / 2.0)

        # 墨层：滑块外 20dp 的圆；选中态用 on_primary，未选中用 on_surface
        if self._alpha > 0.0 and enabled:
            layer_color = self._mix(c.on_surface, c.on_primary, progress)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(layer_color, self._alpha))
            painter.drawEllipse(center, 20.0, 20.0)

        thumb = QRectF(0, 0, thumb_d, thumb_d)
        thumb.moveCenter(center)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(thumb_color)
        painter.drawEllipse(thumb)

        # 焦点环：仅键盘导航可见，围绕轨道外缘 2dp，落在安全区内
        if self._keyboard_focus and enabled:
            pen = QPen(QColor(c.primary))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            ring = track.adjusted(-2.0, -2.0, 2.0, 2.0)
            painter.drawRoundedRect(ring, radius + 2.0, radius + 2.0)

        painter.end()
