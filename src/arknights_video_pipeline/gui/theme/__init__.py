"""
gui.theme - Material Design 3 主题系统

提供颜色 Token、字体 Token、QSS 样式生成、标题栏主题适配
以及 GUI 独立配置管理。
"""

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.styles import MaterialStyle
from arknights_video_pipeline.gui.theme.typography import MaterialTypography
from arknights_video_pipeline.gui.theme.button_qss import (
    filled_button_qss,
    outlined_button_qss,
)
from arknights_video_pipeline.gui.theme.titlebar import (
    apply_titlebar_theme,
    is_titlebar_theming_supported,
)
from arknights_video_pipeline.gui.theme.gui_config import GuiConfig

__all__ = [
    "MaterialColors",
    "MaterialStyle",
    "MaterialTypography",
    "filled_button_qss",
    "outlined_button_qss",
    "apply_titlebar_theme",
    "is_titlebar_theming_supported",
    "GuiConfig",
]
