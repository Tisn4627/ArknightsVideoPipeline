"""3D 透视投影地图地块坐标计算。

本模块精确移植自 ``Arknights-Tile-Pos/python/main.py`` 的 ``Calc`` 类
（数值结果与原版一致），把地图格子的世界坐标投影到屏幕像素坐标。

移植要点：

- ``matrix_p``：透视投影矩阵，FOV=20°，near=0.3，far=1000。
- ``matrix_x``：绕 X 轴旋转 30°。
- ``matrix_y``：绕 Y 轴旋转 10°（仅 side 视角使用）。
- :func:`_adapter`：宽高比适配，9:16 到 3:4 之间对相机 y/z 做偏移。
- 世界→屏幕：``x = (1 + x/w) / 2 * screen_width``，
  ``y = (1 - (1 + y/w) / 2) * screen_height``（与原版符号一致）。

对外提供模块级函数，``level`` 参数为 :mod:`tile.loader` 返回的关卡 dict，
``screen_size`` 为 ``(width, height)``（如 ``(1280, 720)``），``row``/
``col`` 对应 ``tiles[row][col]``（row 为行，col 为列）。
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# --- 固定常量（来自原版 main.py）-------------------------------------------

# 透视投影参数
_FOV_DEGREE = 20.0
_NEAR = 0.3
_FAR = 1000.0

# 旋转角度
_ROT_X_DEGREE = 30.0
_ROT_Y_DEGREE = 10.0

# 撤退/技能按钮相对干员站位的固定偏移（来自原版 main.py）
_BUTTON_OFFSET_X = 1.3143386840820312
_BUTTON_OFFSET_Y = 1.314337134361267
_BUTTON_OFFSET_Z = -0.3967874050140381

# 单格高度对应的 z 偏移
_HEIGHT_TYPE_SCALE = -0.4

# 宽高比适配区间
_ADAPTER_FROM_RATIO = 9.0 / 16.0
_ADAPTER_TO_RATIO = 3.0 / 4.0
_ADAPTER_Y_SCALE = -1.4
_ADAPTER_Z_SCALE = -2.8

ScreenPos = Tuple[float, float]


class _Calc:
    """单关卡投影计算器，精确移植原版 ``Calc``。

    与原版一致：``matrix_p`` / ``matrix_x`` / ``matrix_y`` 为默认 float64
    数组，平移矩阵 ``raw`` 使用 float32 存储，矩阵相乘顺序为
    ``matrix_p @ matrix_x @ [matrix_y] @ raw``。
    """

    def __init__(self, screen_width: int, screen_height: int, level: Dict[str, Any]):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.ratio = screen_height / screen_width
        self.level = level

        # 透视投影矩阵：FOV=20°，near=0.3，far=1000
        self.matrix_p = np.array(
            [
                [self.ratio / math.tan(math.pi * _FOV_DEGREE / 180), 0, 0, 0],
                [0, 1 / math.tan(math.pi * _FOV_DEGREE / 180), 0, 0],
                [0, 0, -(_FAR + _NEAR) / (_FAR - _NEAR), -(_FAR * _NEAR * 2) / (_FAR - _NEAR)],
                [0, 0, -1, 0],
            ]
        )
        # 绕 X 轴旋转 30°
        self.matrix_x = np.array(
            [
                [1, 0, 0, 0],
                [0, math.cos(math.pi * _ROT_X_DEGREE / 180), -math.sin(math.pi * _ROT_X_DEGREE / 180), 0],
                [0, -math.sin(math.pi * _ROT_X_DEGREE / 180), -math.cos(math.pi * _ROT_X_DEGREE / 180), 0],
                [0, 0, 0, 1],
            ]
        )
        # 绕 Y 轴旋转 10°（仅 side 视角使用）
        self.matrix_y = np.array(
            [
                [math.cos(math.pi * _ROT_Y_DEGREE / 180), 0, math.sin(math.pi * _ROT_Y_DEGREE / 180), 0],
                [0, 1, 0, 0],
                [-math.sin(math.pi * _ROT_Y_DEGREE / 180), 0, math.cos(math.pi * _ROT_Y_DEGREE / 180), 0],
                [0, 0, 0, 1],
            ]
        )

        # 相机视点：view[0] 为正视角，view[1] 为 side 视角
        self.view: Tuple[float, float, float] = (
            level["view"][0][0],
            level["view"][0][1],
            level["view"][0][2],
        )
        self.view_side: Tuple[float, float, float] = (
            level["view"][1][0],
            level["view"][1][1],
            level["view"][1][2],
        )
        # 世界→屏幕矩阵缓存：矩阵只依赖 (side, offset)，逐点重建
        # （多次 4x4 matmul）在 get_all_tile_positions 等批量投影中是纯浪费
        self._matrix_cache: Dict[Any, np.ndarray] = {}

    def adapter(self) -> Tuple[float, float]:
        """宽高比适配，返回对相机 y/z 的偏移。

        9:16 → 3:4 之间线性插值：t = (ratio - 9/16) / (3/4 - 9/16)，
        偏移为 (-1.4*t, -2.8*t)。ratio 小于 9/16 时返回 (0, 0)。
        """
        if self.ratio < _ADAPTER_FROM_RATIO - 0.00001:
            return 0, 0
        t = (self.ratio - _ADAPTER_FROM_RATIO) / (_ADAPTER_TO_RATIO - _ADAPTER_FROM_RATIO)
        return _ADAPTER_Y_SCALE * t, _ADAPTER_Z_SCALE * t

    def _get_tile(self, row: int, col: int) -> Optional[Dict[str, Any]]:
        """取 ``tiles[row][col]``，越界返回 None。

        边界用半开区间 ``< height``/``< width``：tiles 恰有 height 行 /
        width 列，原版宽松的 ``<=`` 在查询最边缘外一格时会以裸 IndexError
        崩溃而非返回 None。
        """
        if 0 <= row < self.level["height"] and 0 <= col < self.level["width"]:
            return self.level["tiles"][row][col]
        return None

    def get_focus_offset(self, tile_x: int, tile_y: int) -> Tuple[float, float, float]:
        """聚焦偏移：以关卡中心为原点的格子坐标（z=0）。"""
        x = tile_x - (self.level["width"] - 1) / 2
        y = (self.level["height"] - 1) / 2 - tile_y
        return (x, y, 0)

    def get_character_world_pos(self, tile_x: int, tile_y: int) -> Tuple[float, float, float]:
        """干员站位世界坐标：格子中心平面坐标 + 高度 z。"""
        x = tile_x - (self.level["width"] - 1) / 2
        y = (self.level["height"] - 1) / 2 - tile_y
        tile = self._get_tile(tile_y, tile_x)
        if tile is None:
            # 显式错误而非 assert：python -O 会剥离 assert，届时越界访问
            # 以无上下文的裸 IndexError 崩溃
            raise ValueError(
                f"格子坐标越界: (col={tile_x}, row={tile_y})，"
                f"关卡尺寸 {self.level['width']}x{self.level['height']}"
            )
        z = tile["heightType"] * _HEIGHT_TYPE_SCALE
        return (x, y, z)

    def get_with_draw_world_pos(self, tile_x: int, tile_y: int) -> Tuple[float, float, float]:
        """撤退按钮世界坐标：干员坐标 + 固定偏移。"""
        x, y, _ = self.get_character_world_pos(tile_x, tile_y)
        return (x - _BUTTON_OFFSET_X, y + _BUTTON_OFFSET_Y, _BUTTON_OFFSET_Z)

    def get_skill_world_pos(self, tile_x: int, tile_y: int) -> Tuple[float, float, float]:
        """技能按钮世界坐标：干员坐标 + 固定偏移。"""
        x, y, _ = self.get_character_world_pos(tile_x, tile_y)
        return (x + _BUTTON_OFFSET_X, y - _BUTTON_OFFSET_Y, _BUTTON_OFFSET_Z)

    def world_to_screen_matrix(self, side: bool = False, offset: Optional[Sequence[float]] = None) -> np.ndarray:
        """构造世界→屏幕的完整变换矩阵。

        相机视点取 view（正视角）或 view_side（side 视角），叠加 offset 与
        adapter 偏移后平移，再依次乘 matrix_x（及 side 时的 matrix_y）与
        matrix_p。
        """
        if offset is None:
            offset = (0.0, 0.0, 0.0)
        adapter_y, adapter_z = self.adapter()
        if side:
            x, y, z = self.view_side
        else:
            x, y, z = self.view
        x += offset[0]
        y += offset[1] + adapter_y
        z += offset[2] + adapter_z
        # 平移矩阵（float32，与原版一致）
        raw = np.array(
            [
                [1, 0, 0, -x],
                [0, 1, 0, -y],
                [0, 0, 1, -z],
                [0, 0, 0, 1],
            ],
            np.float32,
        )
        if side:
            matrix = np.dot(self.matrix_x, self.matrix_y)
            matrix = np.dot(matrix, raw)
        else:
            matrix = np.dot(self.matrix_x, raw)
        return np.dot(self.matrix_p, matrix)

    def world_to_screen_pos(
        self,
        pos: Sequence[float],
        side: bool = False,
        offset: Optional[Sequence[float]] = None,
    ) -> ScreenPos:
        """世界坐标 → 屏幕像素坐标。

        归一化方式与原版一致：x'=(1+x/w)/2，y'=(1+y/w)/2，
        返回 ``(x' * screen_width, (1 - y') * screen_height)``。
        """
        cache_key = (bool(side), tuple(offset) if offset is not None else None)
        matrix = self._matrix_cache.get(cache_key)
        if matrix is None:
            matrix = self.world_to_screen_matrix(cache_key[0], offset)
            self._matrix_cache[cache_key] = matrix
        x, y, _, w = np.dot(matrix, np.array([pos[0], pos[1], pos[2], 1]))
        x = (1 + x / w) / 2
        y = (1 + y / w) / 2
        return (x * self.screen_width, (1 - y) * self.screen_height)

    def get_character_screen_pos(self, tile_x: int, tile_y: int, side: bool = False, focus: bool = False) -> ScreenPos:
        """干员站位屏幕坐标。focus=True 时强制 side 视角并叠加聚焦偏移。"""
        if focus:
            side = True
        world_pos = self.get_character_world_pos(tile_x, tile_y)
        if focus:
            offset = self.get_focus_offset(tile_x, tile_y)
        else:
            offset = (0.0, 0.0, 0.0)
        return self.world_to_screen_pos(world_pos, side, offset)

    def get_with_draw_screen_pos(self, tile_x: int, tile_y: int) -> ScreenPos:
        """撤退按钮屏幕坐标（固定 side 视角 + 聚焦偏移）。"""
        world_pos = self.get_with_draw_world_pos(tile_x, tile_y)
        offset = self.get_focus_offset(tile_x, tile_y)
        return self.world_to_screen_pos(world_pos, True, offset)

    def get_skill_screen_pos(self, tile_x: int, tile_y: int) -> ScreenPos:
        """技能按钮屏幕坐标（固定 side 视角 + 聚焦偏移）。"""
        world_pos = self.get_skill_world_pos(tile_x, tile_y)
        offset = self.get_focus_offset(tile_x, tile_y)
        return self.world_to_screen_pos(world_pos, True, offset)


# --- 模块级便捷 API --------------------------------------------------------


def _make_calc(level: Dict[str, Any], screen_size: Sequence[int]) -> _Calc:
    screen_width, screen_height = screen_size
    return _Calc(screen_width, screen_height, level)


def get_tile_screen_pos(
    level: Dict[str, Any],
    row: int,
    col: int,
    screen_size: Sequence[int],
    side: bool = False,
) -> ScreenPos:
    """返回指定格子的屏幕像素坐标 ``(x, y)``。

    ``row`` / ``col`` 对应 ``tiles[row][col]``；该坐标即格子中心（干员
    站位平面坐标 + 高度 z）在无聚焦偏移下的投影，等价于原版 ``run`` 循环
    对每个格子的投影结果。
    """
    calc = _make_calc(level, screen_size)
    # 原版 get_character_screen_pos(tile_x=col, tile_y=row, side, focus=False)
    return calc.get_character_screen_pos(col, row, side=side, focus=False)


def get_all_tile_positions(
    level: Dict[str, Any],
    screen_size: Sequence[int],
    side: bool = False,
) -> List[List[ScreenPos]]:
    """返回与 ``tiles`` 同形状的二维屏幕坐标数组。

    外层长度为 ``height``，内层长度为 ``width``，
    ``result[row][col]`` 对应 ``tiles[row][col]`` 的屏幕坐标。

    Raises
    ------
    ValueError
        关卡数据缺少 ``height``/``width`` 字段时抛出（带明确信息，
        避免 KeyError 难以定位）。
    """
    if "height" not in level or "width" not in level:
        raise ValueError(
            f"关卡数据缺少 height/width 字段: {level.get('code', level.get('stageId', '<unknown>'))}"
        )
    height = level["height"]
    width = level["width"]
    calc = _make_calc(level, screen_size)

    result: List[List[ScreenPos]] = []
    for row in range(height):
        row_pos: List[ScreenPos] = []
        for col in range(width):
            row_pos.append(calc.get_character_screen_pos(col, row, side=side, focus=False))
        result.append(row_pos)
    return result


def get_character_screen_pos(
    level: Dict[str, Any],
    row: int,
    col: int,
    screen_size: Sequence[int],
    side: bool = False,
    focus: bool = False,
) -> ScreenPos:
    """干员站位屏幕坐标。

    ``focus=True`` 时强制 side 视角并叠加聚焦偏移（与原版一致）。
    """
    calc = _make_calc(level, screen_size)
    return calc.get_character_screen_pos(col, row, side=side, focus=focus)


def get_withdraw_screen_pos(
    level: Dict[str, Any],
    row: int,
    col: int,
    screen_size: Sequence[int],
) -> ScreenPos:
    """撤退按钮屏幕坐标（基于干员坐标 + 固定偏移，固定 side 视角）。"""
    calc = _make_calc(level, screen_size)
    return calc.get_with_draw_screen_pos(col, row)


def get_skill_screen_pos(
    level: Dict[str, Any],
    row: int,
    col: int,
    screen_size: Sequence[int],
) -> ScreenPos:
    """技能按钮屏幕坐标（基于干员坐标 + 固定偏移，固定 side 视角）。"""
    calc = _make_calc(level, screen_size)
    return calc.get_skill_screen_pos(col, row)
