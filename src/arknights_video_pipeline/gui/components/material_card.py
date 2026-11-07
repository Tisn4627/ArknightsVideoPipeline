"""gui.components.material_card - Material Design 3 卡片容器

MD3 卡片的三种变体：

- ``filled``：``surface_container_highest`` 底、无描边、无阴影（MD3 filled card）；
- ``outlined``：``surface`` 底 + 1dp ``outline_variant`` 描边（MD3 outlined card）；
- ``elevated``：``surface_container_low`` + level 1 阴影。

页面上大量卡片默认使用 ``outlined``：MD3 本身允许 outlined card，且它不
需要为每张卡片挂 ``QGraphicsDropShadowEffect``（一个 widget 只能挂一个
effect，且阴影在深色主题几乎不可见）。只有对话框 / FAB / 菜单这类真正
"浮起"的元素使用阴影。

> 说明：三种变体的容器色严格对应 MD3 规范，不再出现"surface_container
> + 描边"的混合形态（既不是 filled 也不是 outlined）。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.palette import set_text_color
from arknights_video_pipeline.gui.theme.shape import ShapeRole
from arknights_video_pipeline.gui.theme.spacing import Layout
from arknights_video_pipeline.gui.theme.state import Elevation
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["CardFrame", "MaterialCard"]

_FILLED = "filled"
_OUTLINED = "outlined"
_ELEVATED = "elevated"

#: 变体 → 默认表面角色（MD3 card color roles）
_VARIANT_SURFACE_ROLE: dict[str, str] = {
    _FILLED: "surface_container_highest",
    _OUTLINED: "surface",
    _ELEVATED: "surface_container_low",
}


class CardFrame(QFrame):
    """圆角卡片基础组件（仅绘制圆角背景，不含布局）

    作为 MaterialCard 与对话框卡片的共同基类，消除重复的 paintEvent 实现。
    背景走"色调分层"而不是投影：``filled`` / ``outlined`` 变体在页面上
    属于同一层平面，只有 ``elevated`` 使用 MD3 level 1 阴影。
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        surface_role: str | None = None,
        variant: str = _OUTLINED,
        radius: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # 说明：不使用 setAutoFillBackground —— 历史实现里它会先用调色板铺
        # 一层矩形，再被 paintEvent 的圆角覆盖，形成双重绘制（主题切换时
        # 闪白、圆角边缘出现直角残影）。背景完全由 paintEvent 自绘。
        self._variant = variant if variant in _VARIANT_SURFACE_ROLE else _OUTLINED
        # 显式传入角色时优先（如对话框 surface_container_high）；
        # 否则严格按 MD3 卡片的容器色角色取色。
        self._surface_role_explicit = surface_role is not None
        self._surface_role = (
            surface_role if surface_role is not None
            else _VARIANT_SURFACE_ROLE[self._variant]
        )
        self._radius = radius if radius is not None else ShapeRole.CARD
        # 构造即取当前主题：深色下新建卡片不会残留浅色底
        self._colors = theme_controller().colors()
        self._surface_color = QColor(getattr(self._colors, self._surface_role))
        self._elevation = 0
        self._shadow: QGraphicsDropShadowEffect | None = None
        self._update_palette()
        theme_controller().theme_changed.connect(self._on_theme_changed)

    # ── 变体 / 颜色 ───────────────────────────────────────

    def _update_palette(self) -> None:
        """同步调色板（供未走 paintEvent 的原生子控件继承底色）"""
        pal = self.palette()
        pal.setColor(self.backgroundRole(), self._surface_color)
        self.setPalette(pal)

    def variant(self) -> str:
        return self._variant

    def set_variant(self, variant: str) -> None:
        """卡片变体：``filled`` / ``outlined``（默认）/ ``elevated``"""
        self._variant = variant if variant in _VARIANT_SURFACE_ROLE else _OUTLINED
        if not self._surface_role_explicit:
            self._surface_role = _VARIANT_SURFACE_ROLE[self._variant]
            self.set_surface_color(getattr(self._colors, self._surface_role))
        if self._variant == _ELEVATED:
            self.set_elevation(1)
        elif self._elevation == 1:
            self.set_elevation(0)
        self.update()

    def _on_theme_changed(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.set_surface_color(getattr(colors, self._surface_role))
        if self._elevation > 0:
            self.set_elevation(self._elevation)

    def set_surface_role(self, role: str) -> None:
        """切换卡片使用的表面角色（如对话框改为 surface_container_high）"""
        self._surface_role = role
        self._surface_role_explicit = True
        self.set_surface_color(getattr(self._colors, role))

    def set_surface_color(self, hex_color: str) -> None:
        """显式指定卡片背景色（少用；优先通过角色名跟随主题）"""
        self._surface_color = QColor(hex_color)
        self._update_palette()
        self.update()

    def surface_color(self) -> QColor:
        return self._surface_color

    # ── MD3 Elevation 阴影 ─────────────────────────────────

    def set_elevation(self, level: int, dark: bool | None = None) -> None:
        """设置 MD3 Elevation 阴影层级（0-5）

        Args:
            level: 0-5 阴影层级，0 表示无阴影
            dark: 当前是否为深色主题；None 时按表面色亮度自动判断
        """
        level = Elevation.clamp(level)
        self._elevation = level
        if level == 0:
            if self._shadow is not None:
                # setGraphicsEffect(None) 会由 Qt 自动删除原效果对象，
                # 只需丢弃引用，无需（也不能）再 deleteLater。
                self.setGraphicsEffect(None)
                self._shadow = None
            return
        if dark is None:
            dark = self._colors.is_dark
        blur, dy, alpha = Elevation.effect(level, dark)
        if self._shadow is None:
            self._shadow = QGraphicsDropShadowEffect(self)
            self.setGraphicsEffect(self._shadow)
        self._shadow.setBlurRadius(max(1, blur))
        self._shadow.setOffset(QPointF(0, max(0, dy)))
        self._shadow.setColor(QColor(0, 0, 0, alpha))
        self.update()

    def elevation(self) -> int:
        return self._elevation

    # ── 绘制 ───────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        """自绘圆角背景（outlined 变体额外画 1dp 描边）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        radius = float(self._radius)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._surface_color)
        painter.drawRoundedRect(rect, radius, radius)

        if self._variant == _OUTLINED:
            pen = QPen(QColor(self._colors.outline_variant))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius
            )

        # 不调用 super().paintEvent()：QFrame 默认帧绘制会盖回矩形底色


class MaterialCard(CardFrame):
    """Material 卡片容器（标题 + 垂直内容布局）"""

    def __init__(self, title: str = "", parent: QWidget | None = None,
                 elevation: int = 0, variant: str = _OUTLINED,
                 padding: int = Layout.CARD_PADDING) -> None:
        super().__init__(parent, variant=variant)
        self.setObjectName("materialCard")
        # 水平方向填满网格列：默认 Preferred 会让卡片按内容收缩，
        # 双列布局里两张卡宽度不一致并在列内留下空白。
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._typography = MaterialTypography()
        if variant == _ELEVATED:
            self.set_elevation(elevation or 1)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(Layout.CARD_HEADER_GAP)

        self._title_label: QLabel | None = None
        if title:
            self._add_title(title)

    # ── 标题 ─────────────────────────────────────────────

    def _add_title(self, title: str) -> None:
        label = QLabel(title, self)
        label.setFont(self._typography.font("title_medium"))
        label.setWordWrap(True)
        self._layout.addWidget(label)
        self._title_label = label
        self._apply_title_color()
        theme_controller().theme_changed.connect(self._apply_title_color)

    def _apply_title_color(self, *_args) -> None:
        # 文字色走 QPalette（不设 widget 级样式表）：后者会在主题切换时
        # 逐卡新建 QStyleSheetStyle 并触发 polish
        if self._title_label is not None:
            set_text_color(self._title_label, self._colors.on_surface)

    def title_label(self) -> QLabel | None:
        return self._title_label

    def set_title(self, title: str) -> None:
        if self._title_label is None:
            self._add_title(title)
        else:
            self._title_label.setText(title)

    # ── 内容 ─────────────────────────────────────────────

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)

    def set_content_alignment(self, alignment: Qt.AlignmentFlag) -> None:
        """设置卡片内容布局的对齐方式（转发给内部布局）"""
        self._layout.setAlignment(alignment)

    def set_content_spacing(self, spacing: int) -> None:
        self._layout.setSpacing(spacing)

    def set_content_margins(self, left: int, top: int, right: int, bottom: int) -> None:
        self._layout.setContentsMargins(left, top, right, bottom)
