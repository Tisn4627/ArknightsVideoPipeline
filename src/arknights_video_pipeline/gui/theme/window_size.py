"""gui.theme.window_size - MD3 窗口尺寸类别

MD3 用三个断点描述窗口宽度，并据此决定导航形态、页边距、卡片列数与标题字号：

| 类别 | 宽度 | 导航 | 页边距 | 卡片列数 | 标题 |
|---|---|---|---|---|---|
| compact | < 600 | 底部 NavigationBar | 16 | 1 | display_small |
| medium | 600-839 | NavigationRail（仅图标） | 24 | 1 | display_small |
| expanded | >= 840 | NavigationRail（图标 + 标签） | 32 | 2 | display_medium |

历史实现使用 960 / 720 两个像素魔数，并在 ``resizeEvent`` 与
``eventFilter`` 中各写一份宽度同步逻辑，导致拖拽窗口时卡片宽度跳变。
"""

from __future__ import annotations

__all__ = ["BREAKPOINT_EXPANDED", "BREAKPOINT_MEDIUM", "WindowSizeClass"]

COMPACT = "compact"
MEDIUM = "medium"
EXPANDED = "expanded"

BREAKPOINT_MEDIUM = 600
BREAKPOINT_EXPANDED = 840


class WindowSizeClass:
    """窗口尺寸类别判定与派生属性"""

    COMPACT = COMPACT
    MEDIUM = MEDIUM
    EXPANDED = EXPANDED

    #: 全部取值（供测试断言）
    ALL: tuple[str, ...] = (COMPACT, MEDIUM, EXPANDED)

    @staticmethod
    def of(width: int) -> str:
        """按窗口宽度返回尺寸类别"""
        if width < BREAKPOINT_MEDIUM:
            return COMPACT
        if width < BREAKPOINT_EXPANDED:
            return MEDIUM
        return EXPANDED

    @staticmethod
    def uses_bottom_navigation(size_class: str) -> bool:
        """是否使用底部导航（compact）"""
        return size_class == COMPACT

    @staticmethod
    def rail_shows_labels(size_class: str) -> bool:
        """侧边导航是否显示标签（仅 expanded）"""
        return size_class == EXPANDED
