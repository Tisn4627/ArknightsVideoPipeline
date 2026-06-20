"""gui.theme.button_qss - Material Design 3 按钮 QSS 生成

提取此前在 message_dialog / about_dialog / file_selector / settings_page
中重复出现的 filled / outlined 按钮 QSS 生成逻辑（修复 M15）。

所有函数均接受 MaterialColors 实例，返回可直接传给 setStyleSheet 的字符串。
"""

from __future__ import annotations

from arknights_video_pipeline.gui.theme.colors import MaterialColors


def filled_button_qss(
    colors: MaterialColors,
    *,
    font_size: int = 14,
    font_weight: int = 500,
    padding: str = "10px 24px",
    border_radius: int = 20,
    min_height: int = 20,
) -> str:
    """filled/tonal 按钮的内联样式：主色填充、白色文字、圆角

    Args:
        colors: MaterialColors 实例
        font_size: 字体大小（px）
        font_weight: 字体粗细（数字）
        padding: 内边距（CSS 字符串，如 "10px 24px"）
        border_radius: 圆角半径（px）
        min_height: 最小高度（px），用于与 QLineEdit 对齐

    Returns:
        可直接传给 QPushButton.setStyleSheet 的 QSS 字符串
    """
    return (
        "QPushButton {"
        f"  background-color: {colors.primary};"
        f"  color: {colors.on_primary};"
        f"  border: none;"
        f"  border-radius: {border_radius}px;"
        f"  padding: {padding};"
        f"  font-weight: {font_weight};"
        f"  font-size: {font_size}px;"
        f"  min-height: {min_height}px;"
        "}"
        "QPushButton:hover {"
        f"  background-color: {colors.primary_container};"
        f"  color: {colors.on_primary_container};"
        "}"
        "QPushButton:pressed {"
        f"  background-color: {colors.on_primary_container};"
        f"  color: {colors.primary_container};"
        "}"
        "QPushButton:disabled {"
        f"  background-color: {colors.surface_variant};"
        f"  color: {colors.on_surface_variant};"
        "}"
    )


def outlined_button_qss(
    colors: MaterialColors,
    *,
    font_size: int = 14,
    font_weight: int = 500,
    padding: str = "10px 24px",
    border_radius: int = 20,
    min_height: int = 20,
) -> str:
    """outlined 按钮的内联样式：透明背景、主色描边与文字

    Args:
        colors: MaterialColors 实例
        font_size: 字体大小（px）
        font_weight: 字体粗细（数字）
        padding: 内边距（CSS 字符串）
        border_radius: 圆角半径（px）
        min_height: 最小高度（px）

    Returns:
        可直接传给 QPushButton.setStyleSheet 的 QSS 字符串
    """
    return (
        "QPushButton {"
        f"  background-color: transparent;"
        f"  color: {colors.primary};"
        f"  border: 1px solid {colors.outline};"
        f"  border-radius: {border_radius}px;"
        f"  padding: {padding};"
        f"  font-weight: {font_weight};"
        f"  font-size: {font_size}px;"
        f"  min-height: {min_height}px;"
        "}"
        "QPushButton:hover {"
        f"  background-color: {colors.primary_container};"
        f"  color: {colors.on_primary_container};"
        "}"
        "QPushButton:pressed {"
        f"  background-color: {colors.on_primary_container};"
        f"  color: {colors.primary_container};"
        "}"
        "QPushButton:disabled {"
        f"  background-color: {colors.surface_variant};"
        f"  color: {colors.on_surface_variant};"
        "}"
    )
