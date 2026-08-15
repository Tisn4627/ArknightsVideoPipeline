"""
gui.components.tools - 工具页工具注册表

新增工具：继承 ``base.ToolView`` 实现界面，然后在此注册一行即可。
注册表顺序即 ToolsPage 索引页的展示顺序。
"""

from __future__ import annotations

from arknights_video_pipeline.gui.components.tools.base import ToolView
from arknights_video_pipeline.gui.components.tools.recognition_tool import (
    RecognitionTool,
)
from arknights_video_pipeline.gui.components.tools.text_range_tool import (
    Style1TextRangeTool,
)

# (工具 id, 标题 i18n key, 视图类) —— ToolsPage 据此自动构建索引卡片与视图栈
TOOL_REGISTRY: list[tuple[str, str, type[ToolView]]] = [
    ("style1_text_range", "tools.style1_text_range.title", Style1TextRangeTool),
    ("recognition", "tools.recognition.title", RecognitionTool),
]

__all__ = ["TOOL_REGISTRY", "ToolView"]
