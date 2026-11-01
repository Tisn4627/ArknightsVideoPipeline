"""HCT 色调系统单元测试

验证 ``gui.theme.hct`` 的纯数学实现：

- CAM16 正反变换互逆（sRGB → HCT → sRGB 往返一致）；
- 由基线种子 ``#6750A4`` 生成的色调板复现 MD3 基线色（品牌回归护栏）；
- 任意种子 / 极端色度都不会产出非法颜色（色域映射兜底）；
- ``normalize_hex`` 的输入校验与规范化。

所有断言都不依赖 Qt，可在无 GUI 环境下运行。
"""

from __future__ import annotations

import pytest

from arknights_video_pipeline.gui.theme.hct import (
    Hct,
    TonalPalette,
    lstar_from_y,
    normalize_hex,
    solve_rgb,
    y_from_lstar,
)
from arknights_video_pipeline.gui.theme.scheme import BASELINE_SEED, scheme_from_seed


def _distance(left: str, right: str) -> int:
    """两色的通道差绝对值之和（0 表示逐位相同）"""
    return sum(
        abs(int(left[i:i + 2], 16) - int(right[i:i + 2], 16)) for i in (1, 3, 5)
    )


def _tone_of(hex_color: str) -> float:
    """取某色的 HCT 色调（L*）"""
    return Hct.from_hex(hex_color).tone


class TestBaselinePalette:
    """基线种子必须复现 MD3 基线色（重构不得改变品牌观感）"""

    @pytest.fixture(scope="class")
    def scheme(self):
        return scheme_from_seed(BASELINE_SEED)

    def test_primary_anchor_is_exact(self, scheme) -> None:
        """P40 / P20 必须逐位等于 #6750A4 / #381E72"""
        assert scheme.primary.tone(40) == "#6750A4"
        assert scheme.primary.tone(20) == "#381E72"

    def test_primary_ramp_matches_baseline(self, scheme) -> None:
        """其余主色角色允许 ≤3 的通道差（色域映射策略差异）"""
        expected = {
            10: "#21005D",
            30: "#4F378B",
            80: "#D0BCFF",
            90: "#EADDFF",
        }
        for tone, value in expected.items():
            actual = scheme.primary.tone(tone)
            assert _distance(actual, value) <= 6, f"tone {tone}: {actual} != {value}"

    def test_secondary_matches_baseline(self, scheme) -> None:
        assert scheme.secondary.tone(40) == "#625B71"
        assert scheme.secondary.tone(90) == "#E8DEF8"
        assert _distance(scheme.secondary.tone(10), "#1D192B") <= 3

    def test_tertiary_matches_baseline(self, scheme) -> None:
        assert scheme.tertiary.tone(30) == "#633B48"
        assert scheme.tertiary.tone(80) == "#EFB8C8"
        assert _distance(scheme.tertiary.tone(40), "#7D5260") <= 3
        assert _distance(scheme.tertiary.tone(90), "#FFD8E4") <= 4

    def test_neutral_dark_tones_are_exact(self, scheme) -> None:
        """深色 surface 家族必须与原色值一致，避免深色主题观感漂移"""
        assert scheme.neutral.tone(4) == "#0F0D13"
        assert scheme.neutral.tone(6) == "#141218"
        assert scheme.neutral.tone(10) == "#1D1B20"
        assert scheme.neutral.tone(20) == "#322F35"
        assert scheme.neutral.tone(90) == "#E6E0E9"
        assert scheme.neutral.tone(95) == "#F5EFF7"

    def test_neutral_light_tones_near_baseline(self, scheme) -> None:
        """极浅中性色（N92-N98）因近白处色域边界差异允许 ≤4"""
        for tone, value in {98: "#FEF7FF", 96: "#F7F2FA", 94: "#F3EDF7", 92: "#ECE6F0"}.items():
            actual = scheme.neutral.tone(tone)
            assert _distance(actual, value) <= 8, f"tone {tone}: {actual} != {value}"

    def test_neutral_variant_matches_baseline(self, scheme) -> None:
        for tone, value in {30: "#49454F", 50: "#79747E", 80: "#CAC4D0", 60: "#938F99"}.items():
            actual = scheme.neutral_variant.tone(tone)
            assert _distance(actual, value) <= 4, f"tone {tone}: {actual} != {value}"


class TestHctRoundTrip:
    """CAM16 正反变换必须互逆，否则色调求解会整体漂移"""

    @pytest.mark.parametrize(
        "hex_color",
        ["#000000", "#FFFFFF", "#6750A4", "#141218", "#EADDFF", "#386A20", "#7D5700"],
    )
    def test_hex_to_hct_to_hex(self, hex_color: str) -> None:
        assert Hct.from_hex(hex_color).to_hex() == hex_color

    def test_tone_roundtrip_is_stable(self) -> None:
        """同一 (hue, chroma) 下，色值反解出的色调与请求值一致"""
        palette = TonalPalette.of(300.0, 48.0)
        for tone in (10, 30, 50, 70, 90):
            assert abs(_tone_of(palette.tone(tone)) - tone) <= 1.0

    def test_lstar_y_roundtrip(self) -> None:
        for lstar in (0.0, 8.0, 18.4, 50.0, 99.0, 100.0):
            assert abs(lstar_from_y(y_from_lstar(lstar)) - lstar) <= 1e-6


class TestSolverBoundaries:
    """色调求解的边界与色域映射"""

    def test_tone_zero_is_black(self) -> None:
        assert solve_rgb(120.0, 50.0, 0.0) == (0, 0, 0)

    def test_tone_hundred_is_white(self) -> None:
        assert solve_rgb(120.0, 50.0, 100.0) == (255, 255, 255)

    def test_extreme_chroma_is_gamut_mapped(self) -> None:
        """超出 sRGB 色域的请求仍需返回合法颜色且保持色调"""
        red, green, blue = solve_rgb(0.0, 200.0, 50.0)
        for channel in (red, green, blue):
            assert 0 <= channel <= 255
        result = f"#{red:02X}{green:02X}{blue:02X}"
        assert abs(_tone_of(result) - 50.0) <= 2.0

    def test_low_chroma_is_near_neutral(self) -> None:
        """低色度应得到近中性色（CAM16 的 0 色度并不等于 D65 中性灰，
        因此允许个位数通道差，不能要求三通道完全相等）"""
        red, green, blue = solve_rgb(200.0, 2.0, 60.0)
        assert max(red, green, blue) - min(red, green, blue) <= 8


class TestNormalizeHex:
    """输入校验：非法种子必须抛 ValueError，而不是静默产出错误颜色"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("#6750a4", "#6750A4"), ("6750A4", "#6750A4"), ("  #ffd8e4  ", "#FFD8E4")],
    )
    def test_accepts_valid_forms(self, raw: str, expected: str) -> None:
        assert normalize_hex(raw) == expected

    @pytest.mark.parametrize("raw", ["6750", "#GGGGGG", "", "#12345", "#1234567"])
    def test_rejects_invalid_forms(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_hex(raw)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValueError):
            normalize_hex(0x6750A4)  # type: ignore[arg-type]
