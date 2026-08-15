"""地图关卡数据加载与查找。

加载 Arknights-Tile-Pos 标准 ``levels.json``，并按 stageId / code /
levelId / name 进行关卡查找。

``levels.json`` 是一个 JSON 数组，每个元素描述一个关卡，主要字段::

    {
        "stageId": "main_02-10",
        "code": "2-10",
        "levelId": "obt/main/level_main_02-10",
        "name": "病入膏肓",
        "width": 9,
        "height": 6,
        "view": [[x, y, z], [x_side, y_side, z_side]],
        "tiles": [[ {"heightType": 1, "buildableType": 0, "tileKey": "..."}, ... ], ...]
    }

其中 ``tiles`` 为二维数组 ``[[Tile]]``，形状为 ``[height][width]``，即
``tiles[row][col]``。每个 Tile 至少含 ``heightType`` / ``buildableType``
/ ``tileKey`` 字段。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from arknights_video_recognition.config.settings import TILE_DIR

# levels.json 中参与查表的四个键
_LEVEL_KEY_FIELDS = ("stageId", "code", "levelId", "name")

# 缓存已加载的关卡列表，避免重复解析 14MB 的 JSON
_levels_cache: Optional[List[Dict[str, Any]]] = None
_levels_cache_path: Optional[Path] = None


def load_levels(path: Optional[Any] = None) -> List[Dict[str, Any]]:
    """加载 levels.json，返回关卡 dict 列表。

    默认读取 :data:`settings.TILE_DIR` 下的 ``levels.json``。结果会被
    缓存：再次以相同路径调用时直接返回缓存，避免重复 IO 与解析。

    Parameters
    ----------
    path:
        自定义 levels.json 路径。为 ``None`` 时使用默认资源路径。

    Returns
    -------
    list[dict]
        关卡字典列表（原 JSON 数组结构）。
    """
    global _levels_cache, _levels_cache_path

    target = Path(path) if path is not None else TILE_DIR / "levels.json"

    # 命中缓存：路径相同且已加载过
    if _levels_cache is not None and _levels_cache_path == target:
        return _levels_cache

    with open(target, encoding="utf-8") as fp:
        data = json.load(fp)

    _levels_cache = data
    _levels_cache_path = target
    return data


def _field_non_empty_equal(level: Dict[str, Any], field: str, key: str) -> bool:
    """判断关卡的某个字段为非空且等于 ``key``。

    复刻 C++ ``LevelKey::empty_or_equal`` 的语义：空字段视为通配不应
    命中具体 key，因此这里要求字段非空且与 key 严格相等。这样可避免
    「空 name 字段匹配任意 key」的误命中。
    """
    value = level.get(field)
    if value is None or value == "":
        return False
    return value == key


def find_level(key: Optional[str], levels: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """按 stageId / code / levelId / name 查表，返回命中的关卡 dict。

    采用 empty_or_equal 匹配逻辑：遍历所有关卡，只要任一非空字段
    （stageId / code / levelId / name）等于 ``key`` 即命中，返回第一个
    命中的关卡；未命中返回 ``None``。``key`` 为空或 ``None`` 时直接返回
    ``None``。

    Parameters
    ----------
    key:
        待查找的关卡标识，可以是 stageId、code、levelId 或 name。
    levels:
        可选的关卡列表，为 ``None`` 时调用 :func:`load_levels` 获取。
    """
    if key is None or key == "":
        return None

    if levels is None:
        levels = load_levels()

    for level in levels:
        for field in _LEVEL_KEY_FIELDS:
            if _field_non_empty_equal(level, field, key):
                return level
    return None


def find_level_by(
    code: Optional[str] = None,
    name: Optional[str] = None,
    stage_id: Optional[str] = None,
    level_id: Optional[str] = None,
    levels: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """多字段精确查找，任一非空参数命中即返回该关卡。

    调用方可只传部分参数：在提供的非空参数中，只要关卡的对应字段与
    之相等即视为命中（OR 语义），返回第一个命中的关卡；未命中返回
    ``None``。所有参数均为空时返回 ``None``。

    肉鸽关卡（code 为 ``"???"`` 或空，多个关卡共享同一 code）应通过
    ``name`` 定位，因此本函数支持只传 ``name``。

    Parameters
    ----------
    code:
        关卡 code（如 ``"2-10"``）。
    name:
        关卡名（如 ``"病入膏肓"`` / ``"与虫为伴"``）。
    stage_id:
        关卡 stageId（如 ``"main_02-10"``）。
    level_id:
        关卡 levelId（如 ``"obt/main/level_main_02-10"``）。
    levels:
        可选的关卡列表，为 ``None`` 时调用 :func:`load_levels` 获取。
    """
    # 收集调用方提供的非空查询字段，按 (字段名, 查询值) 配对
    queries: List[tuple] = []
    if stage_id is not None and stage_id != "":
        queries.append(("stageId", stage_id))
    if code is not None and code != "":
        queries.append(("code", code))
    if level_id is not None and level_id != "":
        queries.append(("levelId", level_id))
    if name is not None and name != "":
        queries.append(("name", name))

    if not queries:
        return None

    if levels is None:
        levels = load_levels()

    for level in levels:
        for field, qval in queries:
            if level.get(field) == qval:
                return level
    return None
