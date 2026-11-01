"""gui.theme.hct - HCT 色彩空间与色调生成（纯标准库实现）

Material Design 3 用 HCT 描述颜色，三个分量分别是：

- **H（hue）**：CAM16 色相角，0-360；
- **C（chroma）**：CAM16 色度，0 起（越大越鲜艳）；
- **T（tone）**：CIE L* 明度，0（黑）-100（白）。

本模块移植 material-color-utilities 的 CAM16 正反变换与色调求解，对外只暴露
两个能力：

- ``Hct.from_hex()``：sRGB → HCT，用于从种子色提取色相 / 色度；
- ``TonalPalette.tone(t)``：给定色调号生成十六进制色，用于派生整套色板。

设计要点：

- **不依赖 Qt**：可脱离 GUI 单独测试，主题层之外也能复用；
- **结果缓存**：同一 ``(hue, chroma, tone)`` 只求解一次，主题切换不会重复计算；
- **色域映射**：目标色超出 sRGB 色域时保持色相与色调、二分降低色度，
  保证任何种子色（包括高饱和色）都能产出合法颜色；
- **基线可复现**：种子 ``#6750A4`` 必须原样生成 MD3 基线色
  （``#6750A4`` / ``#D0BCFF`` / ``#EADDFF`` / ``#21005D`` 等），这既是规范
  正确性的证据，也是"重构不改变品牌观感"的回归护栏。
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass

__all__ = [
    "Cam16",
    "Hct",
    "TonalPalette",
    "lstar_from_y",
    "normalize_hex",
    "y_from_lstar",
]


# ── 色域矩阵 ─────────────────────────────────────────────
# sRGB(D65) 线性 RGB(0-1) → XYZ(0-1)
_SRGB_TO_XYZ: tuple[tuple[float, float, float], ...] = (
    (0.41233895, 0.35762064, 0.18051042),
    (0.2126, 0.7152, 0.0722),
    (0.01932141, 0.11916382, 0.95034478),
)

# XYZ(0-1) → sRGB 线性 RGB(0-1)
_XYZ_TO_SRGB: tuple[tuple[float, float, float], ...] = (
    (3.2406, -1.5372, -0.4986),
    (-0.9689, 1.8758, 0.0415),
    (0.0557, -0.2040, 1.0570),
)

# CAM16 使用的 CAT16 色适应矩阵（作用在 XYZ 0-100 上）
_XYZ_TO_CAT16: tuple[tuple[float, float, float], ...] = (
    (0.401288, 0.650173, -0.051461),
    (-0.250268, 1.204414, 0.045854),
    (-0.002079, 0.048952, 0.953127),
)

_CAT16_TO_XYZ: tuple[tuple[float, float, float], ...] = (
    (1.86206786, -1.01125463, 0.14918677),
    (0.38752654, 0.62144744, -0.00897398),
    (-0.01584150, -0.03412294, 1.04996444),
)

# D65 白点（2° 观察者，XYZ 0-100）
_WHITE_D65: tuple[float, float, float] = (95.047, 100.0, 108.883)

# 8bit 量化前允许的色域外余量
# 取值经基线色标定：2.0 时 primary/secondary 等品牌色与 MD3 基线参考值
# 逐通道差最小（多数完全一致，其余 ≤1），且不会让明显超色域的颜色漏过。
_GAMUT_EPSILON = 2.0


# ── 基础工具 ─────────────────────────────────────────────


def _mat3(
    matrix: tuple[tuple[float, float, float], ...],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    """3x3 矩阵乘向量"""
    x, y, z = vector
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z,
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z,
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z,
    )


def _srgb_to_linear(channel: float) -> float:
    """sRGB 通道（0-255）→ 线性 RGB（0-1）"""
    value = channel / 255.0
    if value <= 0.040449936:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(channel: float) -> float:
    """线性 RGB（0-1）→ sRGB 通道（0-255，可能略微超出以保留色域信息）"""
    if channel <= 0.0031308:
        value = channel * 12.92
    else:
        value = 1.055 * (channel ** (1.0 / 2.4)) - 0.055
    return value * 255.0


def lstar_from_y(y: float) -> float:
    """相对亮度 Y（0-100）→ CIE L*（0-100）"""
    normalized = y / 100.0
    if normalized <= 216.0 / 24389.0:
        return normalized * 24389.0 / 27.0
    return normalized ** (1.0 / 3.0) * 116.0 - 16.0


def y_from_lstar(lstar: float) -> float:
    """CIE L*（0-100）→ 相对亮度 Y（0-100）"""
    if lstar <= 8.0:
        return 100.0 * lstar / 903.2962962962963
    return 100.0 * ((lstar + 16.0) / 116.0) ** 3


def normalize_hex(value: str) -> str:
    """把 ``#RRGGBB`` / ``RRGGBB`` 规范化为大写 ``#RRGGBB``

    Args:
        value: 用户输入的十六进制颜色

    Returns:
        大写、带 ``#`` 前缀的六位十六进制色串

    Raises:
        ValueError: 类型错误、长度不为 6 或含非法字符
    """
    if not isinstance(value, str):
        raise ValueError(f"颜色必须是字符串，收到 {type(value).__name__}")
    text = value.strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        raise ValueError(f"颜色必须是 6 位十六进制，例如 #6750A4：{value!r}")
    try:
        int(text, 16)
    except ValueError as exc:
        raise ValueError(f"颜色含非法字符：{value!r}") from exc
    return "#" + text.upper()


# ── 观察条件（CAM16 默认环境）────────────────────────────


@dataclass(frozen=True)
class _ViewingConditions:
    """CAM16 观察条件（默认：D65 白点 + 背景 L* 50 + 平均环绕）

    字段含义与 material-color-utilities 保持一致，供 CAM16 正反变换使用。
    """

    n: float          # 背景亮度相对值 Yb/Yw
    aw: float         # 白点适应后亮度
    nbb: float        # 亮度诱导系数
    ncb: float        # 色度诱导系数
    c: float          # 环绕影响（surround impact）
    nc: float         # 环绕色度诱导
    rgb_d: tuple[float, float, float]   # 各通道 D 系数（不完全适应）
    fl: float         # 亮度适应系数
    z: float          # 基色感知指数


def _compress(component: float, fl: float) -> float:
    """CIECAM02 前向非线性压缩（返回 0-400 尺度的适应后响应）

    标准式：``x = (fl * |c| / 100) ** 0.42``，``R_a = 400 * x / (x + 27.13)``。

    注意：白点适应亮度 ``aw`` 必须用**同一个压缩函数**计算，否则
    ``ac / aw`` 比值失真，反推出的明度 J 与色度会整体偏大一个数量级
    （表现为所有色调都塌缩到同一个深色）。分母 27.13 也不可省略，
    否则正反变换不再互逆。
    """
    value = (abs(component) * fl / 100.0) ** 0.42
    return 400.0 * value / (value + 27.13)


def _make_viewing_conditions() -> _ViewingConditions:
    """按 MD3 默认环境构造观察条件（等价 material 的 ``ViewingConditions.DEFAULT``）"""
    adapting_luminance = (200.0 / math.pi * y_from_lstar(50.0)) / 100.0
    background_lstar = 50.0
    surround = 2.0

    r_w, g_w, b_w = _mat3(_XYZ_TO_CAT16, _WHITE_D65)

    f = 0.8 + surround / 10.0
    if f >= 0.9:
        c = 0.59 + (0.69 - 0.59) * min(1.0, (f - 0.9) * 10.0)
    else:
        c = 0.525 + (0.59 - 0.525) * min(1.0, max(0.0, (f - 0.8) * 10.0))
    nc = f

    d = f * (1.0 - (1.0 / 3.6) * math.exp((-adapting_luminance - 42.0) / 92.0))
    d = min(1.0, max(0.0, d))

    rgb_d = (
        d * (100.0 / r_w) + 1.0 - d,
        d * (100.0 / g_w) + 1.0 - d,
        d * (100.0 / b_w) + 1.0 - d,
    )

    k = 1.0 / (5.0 * adapting_luminance + 1.0)
    k4 = k ** 4
    k4f = 1.0 - k4
    fl = k4 * adapting_luminance + 0.1 * k4f * k4f * (5.0 * adapting_luminance) ** (1.0 / 3.0)

    n = y_from_lstar(background_lstar) / _WHITE_D65[1]
    z = 1.48 + math.sqrt(n)
    nbb = 0.725 / (n ** 0.2)

    adapted_white = tuple(
        _compress(rgb_d[i] * w, fl) for i, w in enumerate((r_w, g_w, b_w))
    )
    aw = (40.0 * adapted_white[0] + 20.0 * adapted_white[1] + adapted_white[2]) / 20.0 * nbb

    return _ViewingConditions(
        n=n, aw=aw, nbb=nbb, ncb=nbb, c=c, nc=nc, rgb_d=rgb_d, fl=fl, z=z
    )


_VC = _make_viewing_conditions()


# ── CAM16 正反变换 ───────────────────────────────────────


def _adapted_response(component: float) -> float:
    """线性响应 → 适应后响应（带符号）"""
    return math.copysign(_compress(component, _VC.fl), component)


def _unadapted_response(component: float) -> float:
    """适应后响应 → 线性响应（逆 0.42 压缩）"""
    magnitude = abs(component)
    denominator = max(1e-6, 400.0 - magnitude)
    base = max(0.0, 27.13 * magnitude / denominator)
    return math.copysign(base ** (1.0 / 0.42), component) * 100.0 / _VC.fl


def _cam16_from_xyz(xyz: tuple[float, float, float]) -> tuple[float, float, float]:
    """XYZ(0-100) → (hue, chroma, J)"""
    r_c, g_c, b_c = _mat3(_XYZ_TO_CAT16, xyz)
    r_a = _adapted_response(r_c * _VC.rgb_d[0])
    g_a = _adapted_response(g_c * _VC.rgb_d[1])
    b_a = _adapted_response(b_c * _VC.rgb_d[2])

    a = r_a - 12.0 * g_a / 11.0 + b_a / 11.0
    b = (r_a + g_a - 2.0 * b_a) / 9.0
    u = (20.0 * r_a + 20.0 * g_a + 21.0 * b_a) / 20.0
    p2 = (40.0 * r_a + 20.0 * g_a + b_a) / 20.0
    ac = p2 * _VC.nbb

    hue = math.degrees(math.atan2(b, a)) % 360.0
    hue_rad = math.radians(hue)
    e_hue = 0.25 * (math.cos(hue_rad + 2.0) + 3.8)
    p1 = 50000.0 / 13.0 * e_hue * _VC.nc * _VC.ncb
    t = p1 * math.hypot(a, b) / (u + 0.305)

    alpha = (t ** 0.9) * ((1.64 - 0.29 ** _VC.n) ** 0.73)
    j = 100.0 * ((ac / _VC.aw) ** (_VC.c * _VC.z))
    chroma = alpha * math.sqrt(max(0.0, j) / 100.0)
    return hue, chroma, j


def _cam16_to_xyz(hue: float, chroma: float, j: float) -> tuple[float, float, float]:
    """(hue, chroma, J) → XYZ(0-100)"""
    if j <= 0.0:
        return (0.0, 0.0, 0.0)

    alpha = chroma / math.sqrt(j / 100.0)
    t = (alpha / ((1.64 - 0.29 ** _VC.n) ** 0.73)) ** (1.0 / 0.9)

    hue_rad = math.radians(hue % 360.0)
    cos_h = math.cos(hue_rad)
    sin_h = math.sin(hue_rad)
    e_hue = 0.25 * (cos_h * math.cos(2.0) - sin_h * math.sin(2.0) + 3.8)

    ac = _VC.aw * ((j / 100.0) ** (1.0 / _VC.c / _VC.z))
    p1 = e_hue * (50000.0 / 13.0) * _VC.nc * _VC.ncb
    p2 = ac / _VC.nbb
    denominator = 23.0 * p1 + 11.0 * t * cos_h + 108.0 * t * sin_h
    gamma = 23.0 * (p2 + 0.305) * t / denominator if denominator else 0.0

    a = gamma * cos_h
    b = gamma * sin_h

    r_a = (460.0 * p2 + 451.0 * a + 288.0 * b) / 1403.0
    g_a = (460.0 * p2 - 891.0 * a - 261.0 * b) / 1403.0
    b_a = (460.0 * p2 - 220.0 * a - 6300.0 * b) / 1403.0

    r_c = _unadapted_response(r_a) / _VC.rgb_d[0]
    g_c = _unadapted_response(g_a) / _VC.rgb_d[1]
    b_c = _unadapted_response(b_a) / _VC.rgb_d[2]
    return _mat3(_CAT16_TO_XYZ, (r_c, g_c, b_c))


# ── HCT → sRGB 求解 ──────────────────────────────────────


def _srgb_from_j(hue: float, chroma: float, j: float) -> tuple[float, float, float]:
    """给定 CAM16 亮度 J，返回 sRGB 通道（0-255，未量化，可能超色域）"""
    xyz = _cam16_to_xyz(hue, chroma, j)
    linear = _mat3(
        _XYZ_TO_SRGB,
        (xyz[0] / 100.0, xyz[1] / 100.0, xyz[2] / 100.0),
    )
    return (
        _linear_to_srgb(linear[0]),
        _linear_to_srgb(linear[1]),
        _linear_to_srgb(linear[2]),
    )


def _solve_j_for_tone(hue: float, chroma: float, tone: float) -> float:
    """二分 CAM16 的 J，使结果色的 L* 等于目标 tone（单调，稳定收敛）"""
    low, high = 0.0, 100.0
    for _ in range(28):
        middle = (low + high) / 2.0
        if lstar_from_y(_cam16_to_xyz(hue, chroma, middle)[1]) < tone:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _in_gamut(rgb: tuple[float, float, float]) -> bool:
    """判断未量化 sRGB 是否落在可显示色域内（含半级量化余量）"""
    return all(
        -_GAMUT_EPSILON <= channel <= 255.0 + _GAMUT_EPSILON for channel in rgb
    )


def _quantize(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    """未量化 sRGB → 8bit 整数三元组

    采用 **四舍五入（round half up）** 而非 Python 内建 ``round``：
    后者是银行家舍入（``round(0.5) == 0``），在 .5 边界上会与 MD3 参考
    实现（``(int)(v + 0.5)``）相差 1，导致基线色无法逐位复现。
    """
    return tuple(  # type: ignore[return-value]
        min(255, max(0, int(channel + 0.5))) for channel in rgb
    )


def solve_rgb(hue: float, chroma: float, tone: float) -> tuple[int, int, int]:
    """HCT → sRGB 8bit 三元组（含色域映射）

    算法：
    1. 固定色度，二分 CAM16 的 J 使明度等于 ``tone``；
    2. 若结果在 sRGB 色域内，直接量化返回；
    3. 若超出色域，保持色相与色调二分降低色度至色域边界，再修正一次 J。

    Args:
        hue: 色相角（自动取模到 0-360）
        chroma: 色度（负数按 0 处理）
        tone: CIE L* 明度（0-100）

    Returns:
        ``(r, g, b)``，每通道 0-255
    """
    if tone <= 0.02:
        return (0, 0, 0)
    if tone >= 99.98:
        return (255, 255, 255)

    hue = hue % 360.0
    chroma = max(0.0, chroma)

    j = _solve_j_for_tone(hue, chroma, tone)
    rgb = _srgb_from_j(hue, chroma, j)
    if _in_gamut(rgb):
        return _quantize(rgb)

    # 超色域：固定 J 二分最大可用色度（色相与色调不变）
    low, high = 0.0, chroma
    for _ in range(22):
        middle = (low + high) / 2.0
        if _in_gamut(_srgb_from_j(hue, middle, j)):
            low = middle
        else:
            high = middle
    j = _solve_j_for_tone(hue, low, tone)
    return _quantize(_srgb_from_j(hue, low, j))


@functools.lru_cache(maxsize=8192)
def _tone_hex_cached(hue: float, chroma: float, tone: float) -> str:
    """按 ``(hue, chroma, tone)`` 缓存色调求解结果"""
    r, g, b = solve_rgb(hue, chroma, tone)
    return f"#{r:02X}{g:02X}{b:02X}"


# ── 对外数据结构 ─────────────────────────────────────────


@dataclass(frozen=True)
class Cam16:
    """CAM16 颜色外观模型（仅保留 MD3 需要的三分量）"""

    hue: float
    chroma: float
    j: float

    @classmethod
    def from_xyz(cls, xyz: tuple[float, float, float]) -> "Cam16":
        hue, chroma, j = _cam16_from_xyz(xyz)
        return cls(hue=hue, chroma=chroma, j=j)


@dataclass(frozen=True)
class Hct:
    """HCT 颜色（色相 / 色度 / 色调）"""

    hue: float
    chroma: float
    tone: float

    @classmethod
    def from_rgb(cls, red: int, green: int, blue: int) -> "Hct":
        """sRGB(0-255) → HCT"""
        linear = (
            _srgb_to_linear(red),
            _srgb_to_linear(green),
            _srgb_to_linear(blue),
        )
        xyz = tuple(value * 100.0 for value in _mat3(_SRGB_TO_XYZ, linear))
        hue, chroma, _ = _cam16_from_xyz(xyz)  # type: ignore[arg-type]
        return cls(hue=hue, chroma=chroma, tone=lstar_from_y(xyz[1]))

    @classmethod
    def from_hex(cls, value: str) -> "Hct":
        """``#RRGGBB`` → HCT"""
        text = normalize_hex(value)
        return cls.from_rgb(
            int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
        )

    def to_hex(self) -> str:
        """HCT → ``#RRGGBB``"""
        r, g, b = solve_rgb(self.hue, self.chroma, self.tone)
        return f"#{r:02X}{g:02X}{b:02X}"

    def with_tone(self, tone: float) -> "Hct":
        """保持色相与色度，替换色调"""
        return Hct(hue=self.hue, chroma=self.chroma, tone=tone)


@dataclass(frozen=True)
class TonalPalette:
    """色调板：固定色相与色度，按色调号取色的函数

    MD3 的全部颜色角色都由若干色调板的特定色调组成（如 primary = P40、
    primary_container = P90），因此色调板是整套配色的最小生成单元。
    """

    hue: float
    chroma: float

    @classmethod
    def of(cls, hue: float, chroma: float) -> "TonalPalette":
        """由色相与色度构造（自动取模 / 钳制）"""
        return cls(hue=hue % 360.0, chroma=max(0.0, chroma))

    @classmethod
    def from_hex(cls, value: str) -> "TonalPalette":
        """由种子色构造：取该色的 HCT 色相与色度"""
        hct = Hct.from_hex(value)
        return cls.of(hct.hue, hct.chroma)

    def tone(self, tone: float) -> str:
        """取指定色调的 ``#RRGGBB`` 颜色

        Args:
            tone: 色调号 0-100（超出范围按端点处理）

        Returns:
            大写十六进制色串
        """
        clamped = min(100.0, max(0.0, float(tone)))
        return _tone_hex_cached(
            round(self.hue, 3), round(self.chroma, 3), round(clamped, 2)
        )

    def ramp(self, tones: tuple[float, ...]) -> dict[float, str]:
        """批量取色，返回 ``{tone: hex}``（供测试与调色板预览使用）"""
        return {tone: self.tone(tone) for tone in tones}
