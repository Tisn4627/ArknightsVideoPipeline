"""gui.theme.scheme - 种子色 → 色调板 → 完整 MD3 颜色角色

MD3 的配色不是一组固定色值，而是「种子色 → 色调板 → 角色」的推导链：

1. 从种子色取 HCT 色相与色度（见 :mod:`gui.theme.hct`）；
2. 按固定色度常量派生 primary / secondary / tertiary / neutral /
   neutral-variant 五组色调板，外加固定色相的 error 板与两组扩展语义板
   （success / warning，非 MD3 标准角色，供业务状态使用）；
3. 每个颜色角色 = 某组色调板上的某个色调号（如 ``primary = P40``、
   ``primary_container = P90``）。

因此任意种子色都能得到一整套协调的颜色；浅色与深色主题的角色一一对应
（浅色取中低色调、深色取中高色调），不存在"某个角色深色没定义"的情况。

色度常量的选取依据：

- primary 取 ``max(48, 种子色度)``：保证品牌紫的饱和度不因换种子而塌陷；
- secondary 16 / tertiary 24（色相 +60）：MD3 标准的"同族弱强调 / 对位强调"；
- neutral 6 / neutral-variant 8：与 Material Theme Builder 对基线种子
  ``#6750A4`` 的输出一致（``#1D1B20`` / ``#E6E0E9`` / ``#49454F`` 等可逐位复现）；
- error 取固定色相 26 / 色度 77：使 E40 / E90 与 MD3 基线
  ``#B3261E`` / ``#F9DEDC`` 的通道差最小（规范写法的 25 / 84 在本实现下偏红）。
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

from arknights_video_pipeline.gui.theme.hct import (
    Hct,
    TonalPalette,
    normalize_hex,
)

__all__ = [
    "BASELINE_SEED",
    "ROLE_SPECS",
    "TonalScheme",
    "scheme_from_seed",
]


# 品牌基线种子（MD3 官方基线紫）
BASELINE_SEED = "#6750A4"

# 基线种子的 HCT 色相（无彩色种子的色相回落目标；导入期算一次）
_BASELINE_HUE = Hct.from_hex(BASELINE_SEED).hue

# ── 色调板色度常量 ───────────────────────────────────────
_PRIMARY_MIN_CHROMA = 48.0
_SECONDARY_CHROMA = 16.0
_TERTIARY_CHROMA = 24.0
_TERTIARY_HUE_SHIFT = 60.0
_NEUTRAL_CHROMA = 6.0
_NEUTRAL_VARIANT_CHROMA = 8.0
_ERROR_HUE = 26.0
_ERROR_CHROMA = 77.0

# 无彩色种子（色度低于该值）的色相无意义，回落到品牌基线色相
_ACHROMATIC_CHROMA = 2.0

# 扩展语义色的种子（成功绿 / 警告琥珀）：作为色调板种子参与整套推导，
# 保证状态色与主色同源、明暗表现一致
_SUCCESS_SEED = "#386A20"
_WARNING_SEED = "#7D5700"


# ── 角色 → (色调板, 浅色调, 深色调) ──────────────────────
# 顺序即文档与测试中的展示顺序；任何角色缺失都会被 scheme 完整性测试发现
ROLE_SPECS: tuple[tuple[str, str, float, float], ...] = (
    # Primary
    ("primary", "primary", 40, 80),
    ("on_primary", "primary", 100, 20),
    ("primary_container", "primary", 90, 30),
    ("on_primary_container", "primary", 10, 90),
    # Secondary
    ("secondary", "secondary", 40, 80),
    ("on_secondary", "secondary", 100, 20),
    ("secondary_container", "secondary", 90, 30),
    ("on_secondary_container", "secondary", 10, 90),
    # Tertiary
    ("tertiary", "tertiary", 40, 80),
    ("on_tertiary", "tertiary", 100, 20),
    ("tertiary_container", "tertiary", 90, 30),
    ("on_tertiary_container", "tertiary", 10, 90),
    # Error（固定色相，不随种子变化）
    ("error", "error", 40, 80),
    ("on_error", "error", 100, 20),
    ("error_container", "error", 90, 30),
    ("on_error_container", "error", 10, 90),
    # Surface
    ("surface", "neutral", 98, 6),
    ("on_surface", "neutral", 10, 90),
    ("surface_variant", "neutral_variant", 90, 30),
    ("on_surface_variant", "neutral_variant", 30, 80),
    ("outline", "neutral_variant", 50, 60),
    ("outline_variant", "neutral_variant", 80, 30),
    # 窗口底（保留 background 字段，语义等同 surface）
    ("background", "neutral", 98, 6),
    # Surface 层级（容器分层，替代阴影）
    ("surface_dim", "neutral", 87, 6),
    ("surface_bright", "neutral", 98, 24),
    ("surface_container_lowest", "neutral", 100, 4),
    ("surface_container_low", "neutral", 96, 10),
    ("surface_container", "neutral", 94, 12),
    ("surface_container_high", "neutral", 92, 17),
    ("surface_container_highest", "neutral", 90, 22),
    # Inverse（反色表面：Snackbar / 反色提示）
    ("inverse_surface", "neutral", 20, 90),
    ("inverse_on_surface", "neutral", 95, 20),
    ("inverse_primary", "primary", 80, 40),
    # 遮罩与色调叠加
    ("scrim", "neutral", 0, 0),
    ("surface_tint", "primary", 40, 80),
    # 扩展语义（非 MD3 标准角色）
    ("success", "success", 40, 80),
    ("on_success", "success", 100, 20),
    ("success_container", "success", 90, 30),
    ("on_success_container", "success", 10, 90),
    ("warning", "warning", 40, 80),
    ("on_warning", "warning", 100, 20),
    ("warning_container", "warning", 90, 30),
    ("on_warning_container", "warning", 10, 90),
)


@dataclass(frozen=True)
class TonalScheme:
    """由单个种子色派生的一整套色调板

    Attributes:
        seed: 规范化后的种子色（大写 ``#RRGGBB``）
        primary: 品牌主色板（色相 = 种子色相，色度 ≥ 48）
        secondary: 次要色板（同色相、低色度）
        tertiary: 对位强调色板（色相 +60）
        neutral: 中性板（surface 家族）
        neutral_variant: 中性变体板（outline / surface_variant）
        error: 错误色板（固定色相）
        success / warning: 扩展语义板
    """

    seed: str
    primary: TonalPalette
    secondary: TonalPalette
    tertiary: TonalPalette
    neutral: TonalPalette
    neutral_variant: TonalPalette
    error: TonalPalette
    success: TonalPalette
    warning: TonalPalette

    # ── 构造 ─────────────────────────────────────────────

    @classmethod
    def from_seed(cls, seed: str) -> "TonalScheme":
        """由种子色推导五组色调板（结果按种子缓存）"""
        return scheme_from_seed(normalize_hex(seed))

    # ── 取色 ─────────────────────────────────────────────

    def palette(self, name: str) -> TonalPalette:
        """按名称取色调板

        Args:
            name: ``primary`` / ``secondary`` / ``tertiary`` / ``neutral`` /
                ``neutral_variant`` / ``error`` / ``success`` / ``warning``

        Raises:
            KeyError: 名称不存在
        """
        value = getattr(self, name, None)
        if not isinstance(value, TonalPalette):
            raise KeyError(f"未知的色调板: {name!r}")
        return value

    def roles(self, dark: bool = False) -> dict[str, str]:
        """生成全部颜色角色（浅色或深色）

        Returns:
            ``{角色名: "#RRGGBB"}``，键集合与 ``MaterialColors`` 字段一一对应
        """
        # ROLE_SPECS 的元组结构：(角色名, 色调板, 浅色调, 深色调)
        color_index = 3 if dark else 2
        return {
            spec[0]: self.palette(spec[1]).tone(spec[color_index])
            for spec in ROLE_SPECS
        }

    def role(self, name: str, dark: bool = False) -> str:
        """取单个角色颜色（未知角色抛 ``KeyError``）"""
        for spec in ROLE_SPECS:
            if spec[0] == name:
                return self.palette(spec[1]).tone(spec[3] if dark else spec[2])
        raise KeyError(f"未知的颜色角色: {name!r}")


def scheme_from_seed(seed: str) -> TonalScheme:
    """按种子色构造 :class:`TonalScheme`（进程级缓存）

    主题切换 / 动态取色只在种子变化时重新推导一次，之后全部命中缓存。
    输入先规范化再进缓存，保证 ``#6750a4`` 与 ``6750A4`` 命中同一实例。

    Raises:
        ValueError: 种子色格式非法
    """
    return _scheme_from_normalized(normalize_hex(seed))


@functools.lru_cache(maxsize=32)
def _scheme_from_normalized(normalized: str) -> TonalScheme:
    """规范化种子 → 色调板的实际推导（缓存键为规范化后的色串）"""
    hct = Hct.from_hex(normalized)
    hue = hct.hue
    if hct.chroma < _ACHROMATIC_CHROMA:
        # 无彩色种子的色相由浮点噪声决定（任意值），若直接使用会让"灰色"
        # 种子随机产出一套彩色品牌色；这里回落到品牌基线色相。
        hue = _BASELINE_HUE
    return TonalScheme(
        seed=normalized,
        primary=TonalPalette.of(hue, max(_PRIMARY_MIN_CHROMA, hct.chroma)),
        secondary=TonalPalette.of(hue, _SECONDARY_CHROMA),
        tertiary=TonalPalette.of(hue + _TERTIARY_HUE_SHIFT, _TERTIARY_CHROMA),
        neutral=TonalPalette.of(hue, _NEUTRAL_CHROMA),
        neutral_variant=TonalPalette.of(hue, _NEUTRAL_VARIANT_CHROMA),
        error=TonalPalette.of(_ERROR_HUE, _ERROR_CHROMA),
        success=TonalPalette.from_hex(_SUCCESS_SEED),
        warning=TonalPalette.from_hex(_WARNING_SEED),
    )
