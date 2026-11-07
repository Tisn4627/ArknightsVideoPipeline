"""
gui.components - 可复用 UI 组件

所有组件遵循 Material Design 3：颜色来自 ``gui.theme`` 的颜色角色，圆角与
间距来自 ``shape`` / ``spacing`` token，交互态（墨层、焦点环、动效）自绘，
并订阅 ``theme_controller().theme_changed`` 自动跟随主题。
"""

from arknights_video_pipeline.gui.components.about_page import AboutPage
from arknights_video_pipeline.gui.components.batch_video_list import BatchVideoList
from arknights_video_pipeline.gui.components.file_selector import FileSelector
from arknights_video_pipeline.gui.components.log_viewer import LogViewer
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import (
    CardFrame,
    MaterialCard,
)
from arknights_video_pipeline.gui.components.material_checkbox import MaterialCheckBox
from arknights_video_pipeline.gui.components.material_combo import MaterialComboBox
from arknights_video_pipeline.gui.components.material_fab import MaterialFab
from arknights_video_pipeline.gui.components.material_icon_button import (
    MaterialIconButton,
)
from arknights_video_pipeline.gui.components.material_progress import MaterialProgress
from arknights_video_pipeline.gui.components.material_switch import MaterialSwitch
from arknights_video_pipeline.gui.components.material_text_field import (
    MaterialTextField,
)
from arknights_video_pipeline.gui.components.navigation_bar import NavigationBar
from arknights_video_pipeline.gui.components.navigation_rail import NavigationRail
from arknights_video_pipeline.gui.components.page_header import PageHeader
from arknights_video_pipeline.gui.components.progress_card import ProgressCard
from arknights_video_pipeline.gui.components.settings_page import SettingsPage
from arknights_video_pipeline.gui.components.tools_page import ToolsPage

__all__ = [
    "AboutPage",
    "BatchVideoList",
    "CardFrame",
    "FileSelector",
    "LogViewer",
    "MaterialButton",
    "MaterialCard",
    "MaterialCheckBox",
    "MaterialComboBox",
    "MaterialFab",
    "MaterialIconButton",
    "MaterialProgress",
    "MaterialSwitch",
    "MaterialTextField",
    "NavigationBar",
    "NavigationRail",
    "PageHeader",
    "ProgressCard",
    "SettingsPage",
    "ToolsPage",
]
