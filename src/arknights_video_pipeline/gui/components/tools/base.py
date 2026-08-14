"""
gui.components.tools.base - 工具视图抽象基类

工具页采用注册表模式：``tools/__init__.py`` 中的 ``TOOL_REGISTRY``
声明全部工具，``ToolsPage`` 据此自动构建索引卡片与视图栈。
新增工具只需继承本基类、实现界面并注册一行即可，无需改动 MainWindow。
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QWidget

from arknights_video_pipeline.gui.theme import MaterialColors


class ToolView(QWidget):
    """工具视图基类：统一主题切换 / 语言切换 / 进入刷新接口

    Attributes:
        tool_id: 工具唯一标识（用作 i18n key 前缀 ``tools.<tool_id>.*``）
        title_key: 索引卡片标题 i18n key
        desc_key: 索引卡片描述 i18n key
        config_proxy: ConfigProxy 实例（由 ToolsPage 注入，供各工具读写配置）
    """

    tool_id: str = ""
    title_key: str = ""
    desc_key: str = ""

    def __init__(self, config_proxy: Any, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_proxy = config_proxy
        self._colors = colors or MaterialColors.light()

    def set_colors(self, colors: MaterialColors) -> None:
        """主题切换时刷新配色（子类覆盖）"""
        self._colors = colors

    def retranslate(self) -> None:
        """语言切换时刷新文本（子类覆盖）"""

    def on_entered(self) -> None:
        """每次进入该工具视图时调用（子类覆盖，可在此刷新配置）"""
