"""gui.theme - Material Design 3 主题系统

分层结构：

1. **色调层**：``hct``（色彩空间与色调求解）→ ``scheme``（种子色 → 色调板
   → 43 个颜色角色）；
2. **Token 层**：``colors``（颜色角色）、``typography``（字体比例）、
   ``shape``（圆角）、``spacing``（间距与栅格）、``motion``（时长与缓动）、
   ``state``（墨层、描边、阴影）；
3. **样式层**：``styles``（全局 QSS）、``palette``（QPalette 兜底）、
   ``button_qss``（兼容薄封装）、``titlebar``（原生标题栏明暗）；
4. **配置**：``gui_config``（``config/gui.json``）。

颜色不是手写常量：``MaterialColors.light()/dark()`` 由基线紫种子推导，
``from_seed()`` 支持 Material You 动态取色。
"""

from arknights_video_pipeline.gui.theme.hct import Hct, TonalPalette, normalize_hex
from arknights_video_pipeline.gui.theme.scheme import (
    BASELINE_SEED,
    ROLE_SPECS,
    TonalScheme,
    scheme_from_seed,
)
from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.shape import Shape, ShapeRole
from arknights_video_pipeline.gui.theme.spacing import Grid, Layout, Margin, Space
from arknights_video_pipeline.gui.theme.window_size import WindowSizeClass
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.state import (
    Border,
    Elevation,
    StateLayer,
    blend,
    with_alpha,
)
from arknights_video_pipeline.gui.theme.styles import MaterialStyle
from arknights_video_pipeline.gui.theme.typography import (
    TYPE_SCALE,
    MaterialTypography,
    TypeRole,
)
from arknights_video_pipeline.gui.theme.palette import (
    apply_palette,
    build_palette,
    set_text_color,
)
from arknights_video_pipeline.gui.theme.font_manager import FontManager
from arknights_video_pipeline.gui.theme.button_qss import (
    BUTTON_VARIANTS,
    button_qss,
    elevated_button_qss,
    filled_button_qss,
    outlined_button_qss,
    text_button_qss,
    tonal_button_qss,
    variant_state_colors,
)
from arknights_video_pipeline.gui.theme.titlebar import (
    apply_titlebar_theme,
    is_titlebar_theming_supported,
)
from arknights_video_pipeline.gui.theme.theme_controller import (
    ThemeController,
    theme_controller,
)
from arknights_video_pipeline.gui.theme.gui_config import GuiConfig

__all__ = [
    # 色调层
    "Hct",
    "TonalPalette",
    "TonalScheme",
    "scheme_from_seed",
    "normalize_hex",
    "BASELINE_SEED",
    "ROLE_SPECS",
    # Token 层
    "MaterialColors",
    "MaterialTypography",
    "TypeRole",
    "TYPE_SCALE",
    "Shape",
    "ShapeRole",
    "Space",
    "Margin",
    "Layout",
    "Grid",
    "WindowSizeClass",
    "Duration",
    "Easing",
    "Motion",
    "StateLayer",
    "Border",
    "Elevation",
    "blend",
    "with_alpha",
    # 样式层
    "MaterialStyle",
    "apply_palette",
    "set_text_color",
    "build_palette",
    "FontManager",
    "BUTTON_VARIANTS",
    "button_qss",
    "filled_button_qss",
    "tonal_button_qss",
    "elevated_button_qss",
    "outlined_button_qss",
    "text_button_qss",
    "variant_state_colors",
    "apply_titlebar_theme",
    "is_titlebar_theming_supported",
    # 调度
    "ThemeController",
    "theme_controller",
    # 配置
    "GuiConfig",
]
