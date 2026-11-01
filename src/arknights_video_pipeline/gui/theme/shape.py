"""gui.theme.shape - MD3 形状（圆角）token

MD3 的圆角只有 7 档。此前项目里 2/4/5/6/8/9/10/12/16/20 px 并存，导致
卡片与内部元素无法"同心"，新增控件时也无从判断该用哪一档。

用法：

- 组件自绘 / QSS 一律引用 ``Shape`` 常量（禁止再写字面量）；
- 具体控件该用哪档由 :class:`ShapeRole` 统一规定，避免同类控件不同圆角。
"""

from __future__ import annotations

__all__ = ["Shape", "ShapeRole"]


class Shape:
    """MD3 圆角档位（px）"""

    NONE = 0
    EXTRA_SMALL = 4
    SMALL = 8
    MEDIUM = 12
    LARGE = 16
    EXTRA_LARGE = 28
    # 胶囊 / 圆形：QSS 与自绘都按"足够大的半径"处理
    FULL = 999

    #: 全部合法档位（供测试断言"界面不得出现其它圆角"）
    ALL: tuple[int, ...] = (
        NONE,
        EXTRA_SMALL,
        SMALL,
        MEDIUM,
        LARGE,
        EXTRA_LARGE,
        FULL,
    )


class ShapeRole:
    """控件 → 圆角档位映射（唯一事实源）"""

    BUTTON = Shape.FULL
    ICON_BUTTON = Shape.FULL
    FAB = Shape.LARGE            # extended FAB；regular FAB 用 Shape.FULL
    FAB_REGULAR = Shape.FULL
    CARD = Shape.MEDIUM          # 12
    DIALOG = Shape.EXTRA_LARGE   # 28
    MENU = Shape.EXTRA_SMALL     # 4
    TOOLTIP = Shape.EXTRA_SMALL
    TEXT_FIELD = Shape.EXTRA_SMALL
    LIST_ITEM = Shape.EXTRA_SMALL
    CHIP = Shape.SMALL
    NAV_INDICATOR = Shape.LARGE  # 56×32 胶囊的半径 16
    SNACKBAR = Shape.EXTRA_SMALL
    PROGRESS = Shape.FULL        # 4dp 轨道圆头
