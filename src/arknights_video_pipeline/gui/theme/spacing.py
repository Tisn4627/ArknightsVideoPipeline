"""gui.theme.spacing - 4dp 基线间距与栅格 token

此前页面边距 40、卡片内边距 20/28、行内 4/6/8/10/12/16 混用，属于"看起来
没对齐但说不出哪不对"的根源。这里把间距收敛为 4 的倍数，并按窗口尺寸类别
给出页边距、卡片内边距与栅格列数。

只在布局代码里引用本模块的常量，禁止再写字面量间距。
"""

from __future__ import annotations

__all__ = ["Grid", "Layout", "Margin", "Space"]


class Space:
    """4dp 基线间距档位（px）"""

    NONE = 0
    XS = 4      # 图标与文字微距
    S = 8       # 按钮内图标间距、列表图标间距
    M = 12      # 表单行内间距、卡片内元素
    L = 16      # 卡片内边距（紧凑档）、页边距（紧凑档）
    XL = 24     # 卡片间距、区块间距
    XXL = 32    # 页边距（宽屏）、页头到内容
    XXXL = 40   # 大区块分隔

    #: 全部合法档位（供测试断言"间距必须落在 4 的倍数上"）
    ALL: tuple[int, ...] = (NONE, XS, S, M, L, XL, XXL, XXXL)


class Margin:
    """三档窗口尺寸类别对应的页边距（px）"""

    COMPACT = Space.L
    MEDIUM = Space.XL
    EXPANDED = Space.XXL

    @classmethod
    def page(cls, size_class: str) -> int:
        """按尺寸类别名取页边距（未知值回退到紧凑档）"""
        return {
            "compact": cls.COMPACT,
            "medium": cls.MEDIUM,
            "expanded": cls.EXPANDED,
        }.get(size_class, cls.COMPACT)


class Layout:
    """页面级的组合间距（避免各处重复三元表达式）"""

    # 卡片
    CARD_PADDING = Space.L            # 紧凑 / 中等档
    CARD_PADDING_EXPANDED = 20        # 宽屏略放松（仍为 4 的倍数）
    CARD_GAP = Space.XL
    CARD_HEADER_GAP = Space.M

    # 页面结构
    HERO_BOTTOM_GAP = Space.XXL
    SECTION_GAP = Space.XL

    # 表单行
    FIELD_GAP = Space.M
    FIELD_ROW_HEIGHT = 56             # 输入框 / 列表行统一高度
    FIELD_LABEL_GAP = Space.S

    # 导航
    NAV_RAIL_WIDTH = 80
    NAV_RAIL_EXPANDED_WIDTH = 80
    NAV_RAIL_ITEM_HEIGHT = 56
    NAV_BAR_HEIGHT = 80
    NAV_INDICATOR_WIDTH = 56
    NAV_INDICATOR_HEIGHT = 32
    NAV_BAR_INDICATOR_WIDTH = 64

    # 操作
    BUTTON_HEIGHT = 40
    BUTTON_HEIGHT_SMALL = 32
    BUTTON_HEIGHT_LARGE = 48
    BUTTON_PADDING_H = Space.XL
    ICON_BUTTON_SIZE = 40
    FAB_SIZE = 56
    FAB_MARGIN = Space.XL


class Grid:
    """栅格：内容最大宽度与列数"""

    MAX_CONTENT_WIDTH = 1200
    #: 设置页单列表单的最大宽度（表单比仪表盘窄，避免标签与控件间距过大）
    SETTINGS_MAX_WIDTH = 1000

    #: 尺寸类别 → 卡片列数
    COLUMNS: dict[str, int] = {
        "compact": 1,
        "medium": 1,
        "expanded": 2,
    }

    @classmethod
    def columns(cls, size_class: str) -> int:
        """按尺寸类别取卡片列数"""
        return cls.COLUMNS.get(size_class, 1)
