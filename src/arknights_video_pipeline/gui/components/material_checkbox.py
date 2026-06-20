"""
gui.components.material_checkbox - Material Design 3 复选框

完全自绘 indicator：因为 PyQt 的 ``QCheckBox::indicator`` 不支持
``image: url(...)`` 替换内置渲染（Qt 5/6 行为），需要子类化 + paintEvent
直接绘制 MD3 复选框图标。状态：
- 未选中：外框（outline 颜色） + 透明背景
- 选中：填充（primary） + 白色对勾（来自 check_box 图标）
- 悬停：边框换 primary
- 禁用：opacity 0.38（MD3 标准）
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QRect, QSize
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QPen
from PyQt6.QtWidgets import QWidget, QLabel

from arknights_video_pipeline.gui.theme import MaterialColors


class MaterialCheckBox(QWidget):
    """MD3 复选框：自定义 indicator + 文本标签。

    - 未选中：外框（hover 时换 primary） + 透明填充
    - 选中：primary 填充 + 白色对勾（QPainterPath 绘制，MD3 check 比例）
    - 禁用：opacity 0.38（MD3 标准）
    """

    toggled = pyqtSignal(bool)

    INDICATOR_SIZE = 18

    def __init__(self, text: str = "", colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = False
        self._colors = colors or MaterialColors.light()
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 文本子控件（右侧 label），左侧 indicator 由 paintEvent 自绘
        self._label = QLabel(text, self)
        self._label.setStyleSheet(
            f"background-color: transparent; border: none;"
            f" color: {self._colors.on_surface}; font-size: 13px;"
        )
        self._label.move(self.INDICATOR_SIZE + 8, 0)
        self._label.adjustSize()
        self._relayout()

    # ── 状态接口 ──────────────────────────────────────────
    def isChecked(self) -> bool:  # noqa: N802 - Qt 命名
        return self._checked

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        if checked == self._checked:
            return
        self._checked = checked
        self.update()
        self.toggled.emit(checked)

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
        self._label.setStyleSheet(
            f"background-color: transparent; border: none;"
            f" color: {colors.on_surface}; font-size: 13px;"
        )
        self.update()

    # ── 事件 ──────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.setChecked(not self._checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self._label.fontMetrics()
        return QSize(self.INDICATOR_SIZE + 8 + fm.horizontalAdvance(self._label.text()) + 4,
                     max(self.INDICATOR_SIZE, fm.height() + 4))

    def resizeEvent(self, event) -> None:  # noqa: N802
        # label 跟随 self 调整位置（上下居中）
        fm = self._label.fontMetrics()
        self._label.move(self.INDICATOR_SIZE + 8, (self.height() - fm.height()) // 2)
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        # 整体绘制：左侧 indicator 由 QPainter 直绘（绕过 PyQt
        # QCheckBox::indicator 不支持 image: url 的限制），
        # 右侧文字交给 QLabel 子控件（Material 风格：左 indicator + 右 label）
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRect(0, (self.height() - self.INDICATOR_SIZE) // 2,
                     self.INDICATOR_SIZE, self.INDICATOR_SIZE)
        checked = self._checked and self.isEnabled()
        if not self.isEnabled():
            p.setOpacity(0.38)  # MD3 disabled 透明度

        if checked:
            # 选中：primary 填充方块 + 白色对勾
            p.setBrush(QColor(self._colors.primary))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rect, 2.0, 2.0)
            # 对勾路径（按 24px viewBox 比例缩放到 INDICATOR_SIZE）：
            #   起点(3, 12) → 拐点(10, 18) → 终点(21, 5)
            check_path = QPainterPath()
            s = self.INDICATOR_SIZE / 24.0
            check_path.moveTo(3 * s, 12 * s)
            check_path.lineTo(10 * s, 18 * s)
            check_path.lineTo(21 * s, 5 * s)
            pen = QPen(QColor("#FFFFFF"))
            pen.setWidthF(2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(check_path)
        else:
            # 未选中：透明填充 + 边框（hover 时换 primary 色）
            p.setBrush(QColor(self._colors.surface))
            border_color = (
                self._colors.primary if self._hover
                else self._colors.outline
            )
            pen = QPen(QColor(border_color))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 2.0, 2.0)

        p.end()
