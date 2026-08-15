"""
gui.theme.palette - MD3 Token → QPalette.ColorRole 映射

将 MaterialColors 中的 MD3 紫色 Token 映射到 Qt 的 QPalette 角色，
作为全局底色兜底。QSS 优先级高于 QPalette（见 styles.py 注释），
因此 QPalette 主要影响：

- 未被 QSS 覆盖的原生控件（QDialog 系统背景、QMessageBox、菜单等）
- 无 QSS 的第三方/系统对话框
- QPalette.Window 按 MD3 规范等于 surface（浅色 #FFFBFE / 深色 #141218）

映射表（MD3 Token → Qt ColorRole）：

| MD3 Token            | Light     | Dark      | QPalette 角色           |
|----------------------|-----------|-----------|--------------------------|
| surface              | #FFFBFE   | #141218   | Window, Base, AlternateBase |
| on_surface           | #1C1B1E   | #E6E0E9   | WindowText, ToolTipText  |
| primary              | #6750A4   | #D0BCFF   | Button, Highlight, Link  |
| on_primary           | #FFFFFF   | #381E72   | ButtonText, HighlightedText |
| primary_container    | #EADDFF   | #4F378B   | Light                    |
| surface_variant      | #E7E0EC   | #49454F   | Mid, ToolTipBase         |
| on_surface_variant   | #49454F   | #CAC4D0   | Text, PlaceholderText, Disabled |
| outline              | #79747E   | #938F99   | Midlight                 |
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.gui.theme.colors import MaterialColors


def build_palette(colors: MaterialColors) -> QPalette:
    """根据 MD3 颜色 Token 构建 QPalette（不修改应用状态）"""
    palette = QPalette()
    c = colors

    # Window / 底色
    palette.setColor(QPalette.ColorRole.Window, QColor(c.surface))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(c.on_surface))
    palette.setColor(QPalette.ColorRole.Base, QColor(c.surface_variant))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c.surface))

    # 控件
    palette.setColor(QPalette.ColorRole.Button, QColor(c.primary))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(c.on_primary))
    palette.setColor(QPalette.ColorRole.Text, QColor(c.on_surface_variant))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c.on_surface_variant))

    # 表面层级（复用现有 Token）
    palette.setColor(QPalette.ColorRole.Light, QColor(c.primary_container))
    palette.setColor(QPalette.ColorRole.Midlight, QColor(c.outline))
    palette.setColor(QPalette.ColorRole.Mid, QColor(c.surface_variant))
    palette.setColor(QPalette.ColorRole.Dark, QColor(c.on_surface_variant))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(c.outline_variant))

    # 选中 / 链接
    palette.setColor(QPalette.ColorRole.Highlight, QColor(c.primary))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c.on_primary))
    palette.setColor(QPalette.ColorRole.Link, QColor(c.primary))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor(c.secondary))

    # ToolTip
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c.surface))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c.on_surface))

    # 禁用态：on_surface_variant 的淡化版本（用 surface_variant 作背景）
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText,
        QColor(c.on_surface_variant),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
        QColor(c.on_surface_variant),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
        QColor(c.on_surface_variant),
    )
    return palette


def apply_palette(colors: MaterialColors) -> None:
    """将 MD3 色板应用到当前 QApplication（全局 Palette 兜底）

    Args:
        colors: MaterialColors 实例（light/dark）

    QSS 在渲染时优先于 QPalette，因此设置 Palette 不会破坏
    ``styles.MaterialStyle`` 生成的样式表；它只补足 QSS 未覆盖的
    原生控件（如系统对话框）底色。
    """
    app = QApplication.instance()
    if app is None:
        return
    app.setPalette(build_palette(colors))
