"""
gui.components.material_switch - Material Design 3 开关

MD3 Switch 控件：圆角轨道 + 圆形滑块，支持选中/未选中两种状态，
颜色随主题（MaterialColors）联动。支持鼠标点击与键盘 Space/Enter 切换。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget

from arknights_video_pipeline.gui.theme import MaterialColors


class MaterialSwitch(QWidget):
    """Material Design 3 Switch"""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self._colors = colors or MaterialColors.light()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(52, 32)
        # 防止默认窗口背景（黑边）在圆角轨道边缘透出
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: transparent; border: none;")

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool) -> None:
        """以编程方式设置状态（会发射 toggled 信号）"""
        if self._checked != checked:
            self._checked = checked
            self.toggled.emit(self._checked)
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_checked(not self._checked)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.set_checked(not self._checked)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._colors

        # MD3 轨道：宽 52，高 32，圆角 16
        track = QRectF(0, 0, 52, 32)
        track.moveCenter(QPointF(self.width() / 2, self.height() / 2))
        # 为描边轨道单独缩进 1px（半线宽）
        inset_track = track.adjusted(1, 1, -1, -1)
        radius = 15.0

        if self._checked:
            # 选中：主色填充轨道，on_primary 滑块（直径 24）靠右
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.primary))
            painter.drawRoundedRect(inset_track, radius, radius)

            thumb_d = 24.0
            thumb = QRectF(0, 0, thumb_d, thumb_d)
            thumb.moveCenter(QPointF(inset_track.right() - 16, inset_track.center().y()))
            painter.setBrush(QColor(c.on_primary))
            painter.drawEllipse(thumb)
        else:
            # 未选中：透明轨道 + outline 描边，outline 滑块（直径 16）靠左
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # 先画底色避免穿透
            painter.setBrush(QColor(c.surface))
            painter.drawRoundedRect(inset_track, radius, radius)

            pen = QPen(QColor(c.outline))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(inset_track, radius, radius)

            thumb_d = 16.0
            thumb = QRectF(0, 0, thumb_d, thumb_d)
            thumb.moveCenter(QPointF(inset_track.left() + 16, inset_track.center().y()))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.outline))
            painter.drawEllipse(thumb)
