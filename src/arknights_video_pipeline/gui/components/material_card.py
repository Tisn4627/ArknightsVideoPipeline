"""
gui.components.material_card - Material Design 3 卡片容器
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRect, QPointF
from PyQt6.QtGui import QColor, QPainter, QBrush
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QWidget, QGraphicsDropShadowEffect,
)


class CardFrame(QFrame):
    """圆角卡片基础组件（仅绘制圆角背景，不含布局）

    作为 MaterialCard 与对话框卡片的共同基类，消除重复的 paintEvent 实现。
    支持 MD3 Elevation 0-5 阴影（QGraphicsDropShadowEffect），仅顶层卡片
    开启（列表行等密集场景禁用，避免性能开销）。
    """

    # MD3 Elevation 映射：blur 半径 / 垂直偏移 / 阴影透明度
    # （浅色主题阴影 alpha 基准，深色主题在此基础上加深）
    _ELEVATION_SPECS: dict[int, tuple[int, int, int]] = {
        0: (0, 0, 0),
        1: (16, 2, 40),
        2: (24, 4, 48),
        3: (32, 6, 56),
        4: (40, 8, 64),
        5: (48, 10, 72),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self._surface_color = QColor("#FFFBFE")
        self._elevation = 0
        self._shadow: QGraphicsDropShadowEffect | None = None
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

    # ── MD3 Elevation 阴影 ─────────────────────────────────

    def set_elevation(self, level: int, dark: bool | None = None) -> None:
        """设置 MD3 Elevation 阴影层级（0-5）

        Args:
            level: 0-5 阴影层级，0 表示无阴影
            dark: 当前是否为深色主题；None 时按表面色亮度自动判断
                （深色 surface 上阴影更黑，对比度更强）
        """
        level = max(0, min(5, int(level)))
        self._elevation = level
        if level == 0:
            if self._shadow is not None:
                # setGraphicsEffect(None) 会由 Qt 自动删除原效果对象，
                # 只需丢弃引用，无需（也不能）再 deleteLater。
                self.setGraphicsEffect(None)
                self._shadow = None
            return
        if dark is None:
            dark = self._surface_color.lightness() < 128
        blur, dy, alpha = self._ELEVATION_SPECS[level]
        if self._shadow is None:
            self._shadow = QGraphicsDropShadowEffect(self)
            self.setGraphicsEffect(self._shadow)
        # 深色主题阴影更黑（alpha +30），提升层级可见性
        eff_alpha = min(255, alpha + (30 if dark else 0))
        self._shadow.setBlurRadius(blur)
        self._shadow.setOffset(QPointF(0, dy))
        self._shadow.setColor(QColor(0, 0, 0, eff_alpha))

    def elevation(self) -> int:
        return self._elevation

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

    def __init__(self, title: str = "", parent: QWidget | None = None,
                 elevation: int = 1) -> None:
        super().__init__(parent)
        self.setObjectName("materialCard")
        # MD3 Elevation 1：顶层卡片带柔和阴影，与淡紫窗口背景区分层级
        self.set_elevation(elevation)

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

    def set_content_alignment(self, alignment: Qt.AlignmentFlag) -> None:
        """设置卡片内容布局的对齐方式（转发给内部布局）

        供外部替代对私有 ``_layout`` 的直接访问。
        """
        self._layout.setAlignment(alignment)

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
