"""
gui.components.material_card - Material Design 3 卡片容器
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPainter, QPalette, QBrush
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget


class CardFrame(QFrame):
    """圆角卡片基础组件（仅绘制圆角背景，不含布局）

    作为 MaterialCard 与对话框卡片的共同基类，消除重复的 paintEvent 实现。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self._surface_color = QColor("#FFFFFF")
        self._update_palette()

    def _update_palette(self) -> None:
        pal = self.palette()
        pal.setColor(self.backgroundRole(), self._surface_color)
        self.setPalette(pal)

    def set_surface_color(self, hex_color: str) -> None:
        """主题切换时刷新卡片背景色"""
        self._surface_color = QColor(hex_color)
        self._update_palette()
        self.update()

    def paintEvent(self, event) -> None:
        """自绘圆角背景，确保全局 QSS 失效时卡片仍能正确显示"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRect(0, 0, self.width(), self.height())
        # 圆角矩形填充
        painter.setBrush(QBrush(self._surface_color))
        painter.setPen(Qt.PenStyle.NoPen)
        radius = 20
        painter.drawRoundedRect(rect, radius, radius)
        super().paintEvent(event)


class MaterialCard(CardFrame):
    """Material 风格卡片容器（带标题与垂直布局）"""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("materialCard")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setSpacing(12)

        self._title_label: QLabel | None = None
        if title:
            self._title_label = QLabel(title)
            self._title_label.setStyleSheet(
                "background: transparent; border: none;"
                " font-weight: 500; font-size: 16px;"
            )
            self._layout.addWidget(self._title_label)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)

    def set_title(self, title: str) -> None:
        if self._title_label is None:
            self._title_label = QLabel(title)
            self._title_label.setStyleSheet(
                "background: transparent; border: none;"
                " font-weight: 500; font-size: 16px;"
            )
            self._layout.insertWidget(0, self._title_label)
        else:
            self._title_label.setText(title)
