"""gui.theme.palette - MD3 角色 → QPalette 映射

QSS 渲染优先级高于 QPalette，因此本模块只做**兜底**：

- 未被 QSS 覆盖的原生控件（系统对话框、文件选择框内的原生控件）；
- 绘制过程中的默认色（文本光标、选中背景、禁用态）；
- 由 Qt 内部绘制的部件（如 ``QLineEdit`` 的右键菜单）。

映射要点（与 MD3 语义对齐）：

| QPalette 角色 | 取色 |
|---|---|
| Window / WindowText | surface / on_surface |
| Base / AlternateBase | surface_container_lowest / surface_container_low |
| Text / PlaceholderText | on_surface / on_surface_variant |
| Button / ButtonText | primary / on_primary |
| Highlight / HighlightedText | primary / on_primary |
| Mid / Midlight / Light | outline / outline_variant / primary_container |
| ToolTipBase / ToolTipText | inverse_surface / inverse_on_surface |
| 禁用态文字 | on_surface @ 38% |
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.state import StateLayer, blend

__all__ = ["apply_palette", "build_palette", "set_text_color"]


def build_palette(colors: MaterialColors) -> QPalette:
    """根据 MD3 角色构建 QPalette（不修改应用状态）"""
    palette = QPalette()
    c = colors

    # 表面与文本
    palette.setColor(QPalette.ColorRole.Window, QColor(c.surface))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(c.on_surface))
    palette.setColor(QPalette.ColorRole.Base, QColor(c.surface_container_lowest))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c.surface_container_low))
    palette.setColor(QPalette.ColorRole.Text, QColor(c.on_surface))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c.on_surface_variant))

    # 控件
    palette.setColor(QPalette.ColorRole.Button, QColor(c.primary))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(c.on_primary))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(c.error))

    # 明暗层次（Qt 用 Light/Midlight/Mid/Dark 绘制立体边框）
    # Dark 同时被 QSS 复用为"禁用内容"色（disabled 控件的文字/描边取它），
    # 它是最接近 MD3「on_surface 38%」的调色板角色
    disabled_content = blend(c.on_surface, c.surface, StateLayer.DISABLED_CONTENT)
    disabled_container = blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER)
    palette.setColor(QPalette.ColorRole.Light, QColor(c.primary_container))
    palette.setColor(QPalette.ColorRole.Midlight, QColor(c.outline_variant))
    palette.setColor(QPalette.ColorRole.Mid, QColor(c.outline))
    palette.setColor(QPalette.ColorRole.Dark, disabled_content)
    palette.setColor(QPalette.ColorRole.Shadow, QColor(c.scrim))

    # 选中 / 链接
    palette.setColor(QPalette.ColorRole.Highlight, QColor(c.primary))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c.on_primary))
    palette.setColor(QPalette.ColorRole.Link, QColor(c.primary))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor(c.tertiary))

    # 工具提示：MD3 用反色表面
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c.inverse_surface))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c.inverse_on_surface))

    # 禁用态：内容 38%、容器 12%（不再用高对比的 on_surface_variant）
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled_content)
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, disabled_container
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, disabled_container
    )

    return palette


def apply_palette(colors: MaterialColors) -> None:
    """把 MD3 调色板应用到当前 ``QApplication``（兜底原生控件）

    无 ``QApplication`` 时静默返回（单元测试可直接调用 ``build_palette``）。
    """
    app = QApplication.instance()
    if app is None:
        return
    app.setPalette(build_palette(colors))


def set_text_color(widget: QWidget, color: str) -> None:
    """给单个控件设置文字色：改 ``QPalette``，而不是 widget 级样式表

    主题切换时对几百个标签逐个 ``setStyleSheet`` 是旧实现的另一处卡顿源：
    每次都会新建 QStyleSheetStyle 并触发 polish + 布局失效。直接改
    ``QPalette`` 只触发重绘，也不会与全局 QSS 的解析互相覆盖。

    Args:
        widget: 目标控件（QLabel、自绘文本控件等）
        color: ``#RRGGBB`` 文字色
    """
    palette = widget.palette()
    value = QColor(color)
    palette.setColor(QPalette.ColorRole.WindowText, value)
    palette.setColor(QPalette.ColorRole.Text, value)
    widget.setPalette(palette)
