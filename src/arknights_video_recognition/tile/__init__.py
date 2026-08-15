"""地图地块（tile）模块。

提供 Arknights-Tile-Pos 标准地图数据的加载、关卡查找，以及基于 3D 透视
投影的屏幕坐标计算。坐标算法精确移植自 ``Arknights-Tile-Pos/python/main.py``，
数值结果与原版一致。

典型用法::

    from arknights_video_recognition.tile import (
        load_levels, find_level, get_tile_screen_pos, get_all_tile_positions,
    )

    levels = load_levels()
    level = find_level("2-10", levels)
    positions = get_all_tile_positions(level, (1280, 720))
"""

from arknights_video_recognition.tile.loader import (
    find_level,
    find_level_by,
    load_levels,
)
from arknights_video_recognition.tile.calc import (
    get_all_tile_positions,
    get_character_screen_pos,
    get_skill_screen_pos,
    get_tile_screen_pos,
    get_withdraw_screen_pos,
)

__all__ = [
    "load_levels",
    "find_level",
    "find_level_by",
    "get_tile_screen_pos",
    "get_all_tile_positions",
    "get_character_screen_pos",
    "get_withdraw_screen_pos",
    "get_skill_screen_pos",
]
