"""gui.theme.button_qss - MD3 按钮内联 QSS（唯一实现）

此前 ``styles.py``、``file_selector.py``、``settings_row_builders.py``、
``settings_page.py`` 各写一份按钮样式，改动必然漂移。这里收敛为一份实现，
五个变体供任意容器内联使用：

- ``filled``：``primary`` 填充（页面唯一的最高优先级操作）；
- ``tonal``：``secondary_container`` 填充（次高优先级）；
- ``elevated``：``surface_container_low`` + 阴影（需要从表面浮起时）；
- ``outlined``：1dp ``outline`` 描边（中等优先级）；
- ``text``：无容器（最低优先级，对话框按钮默认用它）。

QSS 不能表达透明叠色，也无法过渡，因此墨层颜色由 :func:`state.blend`
预先算成实色；真正的淡入动效由 P3 的自绘 ``MaterialButton`` 承担。
"""

from __future__ import annotations

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.spacing import Layout
from arknights_video_pipeline.gui.theme.state import StateLayer, blend

__all__ = [
    "BUTTON_VARIANTS",
    "button_qss",
    "elevated_button_qss",
    "filled_button_qss",
    "outlined_button_qss",
    "text_button_qss",
    "tonal_button_qss",
    "variant_state_colors",
]

BUTTON_VARIANTS = ("filled", "tonal", "elevated", "outlined", "text")


def variant_state_colors(
    colors: MaterialColors, variant: str
) -> tuple[str, str, str, str, str]:
    """返回 (底, 前景, 悬停底, 按下底, 焦点环)

    墨层按 MD3 规则叠加：hover 8%、pressed 10%，叠色取变体自身的前景色。
    """
    c = colors
    if variant == "tonal":
        base, foreground = c.secondary_container, c.on_secondary_container
        ring = c.on_secondary_container
    elif variant == "elevated":
        base, foreground = c.surface_container_low, c.primary
        ring = c.primary
    elif variant == "outlined":
        # MD3 outlined button：outline 描边 + on_surface_variant 文字
        base, foreground = "transparent", c.on_surface_variant
        ring = c.on_surface_variant
    elif variant == "text":
        base, foreground = "transparent", c.primary
        ring = c.primary
    else:  # filled
        base, foreground = c.primary, c.on_primary
        ring = c.on_primary

    if base == "transparent":
        # 无容器：墨层直接与父级表面混合，得到"淡色块"效果
        hover = blend(c.surface, foreground, StateLayer.HOVER).name()
        pressed = blend(c.surface, foreground, StateLayer.PRESSED).name()
    else:
        hover = blend(base, foreground, StateLayer.HOVER).name()
        pressed = blend(base, foreground, StateLayer.PRESSED).name()
    return base, foreground, hover, pressed, ring


def button_qss(
    colors: MaterialColors,
    variant: str = "filled",
    *,
    font_size: int = 14,
    font_weight: int = 500,
    height: int = Layout.BUTTON_HEIGHT,
    padding: str | None = None,
    border_radius: int = 999,
    min_height: int | None = None,
) -> str:
    """生成某一变体的按钮 QSS

    Args:
        colors: 当前配色
        variant: ``filled`` / ``tonal`` / ``elevated`` / ``outlined`` / ``text``
        font_size: 字号（px）
        font_weight: 字重
        height: 目标高度（px），用于反推 min-height
        padding: 自定义内边距；``None`` 时按 MD3 规则（左右 24dp）计算
        border_radius: 圆角（默认 full）
        min_height: 自定义 `min-height`；``None`` 时按高度反推

    Returns:
        可直接传给 ``QWidget.setStyleSheet`` 的字符串
    """
    if variant not in BUTTON_VARIANTS:
        raise ValueError(f"未知的按钮变体: {variant!r}")

    c = colors
    base, foreground, hover, pressed, ring = variant_state_colors(c, variant)

    # 边框/内边距之和恒定，聚焦时边框 1px→2px 不会推动内容
    border_width = 1
    horizontal = Layout.BUTTON_PADDING_H - border_width
    vertical = 9 - border_width  # 20 + 2*9 + 2*1 = 40
    if padding is not None:
        pad = padding
        pad_focus = padding
    else:
        pad = f"{vertical}px {horizontal}px"
        pad_focus = f"{vertical - 1}px {horizontal - 1}px"

    if min_height is None:
        min_height = height - 2 * (vertical + border_width)

    disabled_bg = blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER).name()
    disabled_fg = blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTENT).name()

    if variant == "outlined":
        border_color = c.outline
        transparent_bg = "transparent"
    elif variant == "text":
        border_color = "transparent"
        transparent_bg = "transparent"
    else:
        border_color = "transparent"
        transparent_bg = base

    disabled_border = (
        blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER).name()
        if variant == "outlined"
        else "transparent"
    )
    disabled_background = disabled_bg if variant in ("filled", "tonal", "elevated") else "transparent"

    return (
        "QPushButton {"
        f"  background-color: {transparent_bg};"
        f"  color: {foreground};"
        f"  border: {border_width}px solid {border_color};"
        f"  border-radius: {border_radius}px;"
        f"  padding: {pad};"
        f"  font-size: {font_size}px;"
        f"  font-weight: {font_weight};"
        f"  min-height: {min_height}px;"
        "}"
        "QPushButton:hover {"
        f"  background-color: {hover};"
        f"  color: {foreground};"
        "}"
        "QPushButton:pressed {"
        f"  background-color: {pressed};"
        f"  color: {foreground};"
        "}"
        "QPushButton:disabled {"
        f"  background-color: {disabled_background};"
        f"  color: {disabled_fg};"
        f"  border-color: {disabled_border};"
        "}"
        "QPushButton:focus {"
        f"  border: 2px solid {ring};"
        f"  padding: {pad_focus};"
        "}"
    )


# ── 变体快捷入口（保持旧的导入路径可用）──────────────────


def filled_button_qss(
    colors: MaterialColors,
    *,
    font_size: int = 14,
    font_weight: int = 500,
    padding: str | None = None,
    border_radius: int = 999,
    min_height: int | None = None,
) -> str:
    """filled 按钮（主操作）"""
    return button_qss(
        colors, "filled", font_size=font_size, font_weight=font_weight,
        padding=padding, border_radius=border_radius, min_height=min_height,
    )


def tonal_button_qss(
    colors: MaterialColors,
    *,
    font_size: int = 14,
    font_weight: int = 500,
    padding: str | None = None,
    border_radius: int = 999,
    min_height: int | None = None,
) -> str:
    """tonal 按钮（次要操作）"""
    return button_qss(
        colors, "tonal", font_size=font_size, font_weight=font_weight,
        padding=padding, border_radius=border_radius, min_height=min_height,
    )


def elevated_button_qss(
    colors: MaterialColors,
    *,
    font_size: int = 14,
    font_weight: int = 500,
    padding: str | None = None,
    border_radius: int = 999,
    min_height: int | None = None,
) -> str:
    """elevated 按钮（需要浮起时）"""
    return button_qss(
        colors, "elevated", font_size=font_size, font_weight=font_weight,
        padding=padding, border_radius=border_radius, min_height=min_height,
    )


def outlined_button_qss(
    colors: MaterialColors,
    *,
    font_size: int = 14,
    font_weight: int = 500,
    padding: str | None = None,
    border_radius: int = 999,
    min_height: int | None = None,
) -> str:
    """outlined 按钮（中等优先级）"""
    return button_qss(
        colors, "outlined", font_size=font_size, font_weight=font_weight,
        padding=padding, border_radius=border_radius, min_height=min_height,
    )


def text_button_qss(
    colors: MaterialColors,
    *,
    font_size: int = 14,
    font_weight: int = 500,
    padding: str | None = None,
    border_radius: int = 999,
    min_height: int | None = None,
) -> str:
    """text 按钮（最低优先级，对话框默认）"""
    return button_qss(
        colors, "text", font_size=font_size, font_weight=font_weight,
        padding=padding, border_radius=border_radius, min_height=min_height,
    )
