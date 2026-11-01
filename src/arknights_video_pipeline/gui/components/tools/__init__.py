"""gui.components.tools - 工具页工具注册表

新增工具：继承 ``base.ToolView`` 实现界面，然后在此注册一行即可。
注册表顺序即 ToolsPage 索引页的展示顺序。

**延迟导入**：工具视图会在首次打开时才 ``import`` 对应模块。工具模块依赖
pictex / movielite / onnxruntime 等重资源库，若在 ``import`` 期一并加载，
仅"打开主窗口"就要等待数十秒；索引卡片本身只需要标题与描述文案。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from arknights_video_pipeline.gui.components.tools.base import ToolView

__all__ = ["TOOL_REGISTRY", "ToolSpec", "ToolView"]


@dataclass(frozen=True)
class ToolSpec:
    """工具注册项：索引卡片所需的静态元数据 + 视图类的延迟加载入口"""

    tool_id: str
    title_key: str
    module: str
    class_name: str

    @property
    def desc_key(self) -> str:
        """索引卡片的描述文案 key"""
        return f"tools.{self.tool_id}.desc"

    def load_view(self) -> type[ToolView]:
        """导入并返回工具视图类（仅在真正打开工具时调用）"""
        module = importlib.import_module(self.module)
        return getattr(module, self.class_name)


# (工具 id, 标题 i18n key, 视图模块, 视图类名) —— ToolsPage 据此自动构建索引卡片
TOOL_REGISTRY: tuple[ToolSpec, ...] = (
    ToolSpec(
        "style1_text_range",
        "tools.style1_text_range.title",
        "arknights_video_pipeline.gui.components.tools.text_range_tool",
        "Style1TextRangeTool",
    ),
    ToolSpec(
        "recognition",
        "tools.recognition.title",
        "arknights_video_pipeline.gui.components.tools.recognition_tool",
        "RecognitionTool",
    ),
)
