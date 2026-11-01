"""MD3 角色派生与设计 Token 单元测试

覆盖两层：

- ``gui.theme.scheme``：种子色 → 色调板 → 43 个颜色角色（完整性、明暗对应、
  error 固定色相、缓存、非法种子）；
- 设计 Token：``shape`` / ``spacing`` / ``motion`` / ``state`` 的取值约束，
  保证圆角只有固定档位、间距落在 4dp 栅格、墨层与阴影符合 MD3。
"""

from __future__ import annotations

import dataclasses

import pytest

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.hct import Hct
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.scheme import (
    BASELINE_SEED,
    ROLE_SPECS,
    scheme_from_seed,
)
from arknights_video_pipeline.gui.theme.shape import Shape, ShapeRole
from arknights_video_pipeline.gui.theme.spacing import Grid, Layout, Margin, Space
from arknights_video_pipeline.gui.theme.state import (
    Border,
    Elevation,
    StateLayer,
    blend,
    with_alpha,
)


def _tone(hex_color: str) -> float:
    return Hct.from_hex(hex_color).tone


class TestRoleCompleteness:
    """角色集合必须与 MaterialColors 字段严格一致"""

    def test_role_specs_have_no_duplicates(self) -> None:
        names = [spec[0] for spec in ROLE_SPECS]
        assert len(names) == len(set(names))

    def test_roles_cover_every_dataclass_field(self) -> None:
        fields = {field.name for field in dataclasses.fields(MaterialColors)}
        roles = {spec[0] for spec in ROLE_SPECS}
        assert fields == roles, f"仅字段有：{fields - roles}；仅角色有：{roles - fields}"

    def test_scheme_fills_all_roles(self) -> None:
        colors = MaterialColors.from_seed(BASELINE_SEED)
        assert len(colors.to_dict()) == 43
        assert all(value.startswith("#") and len(value) == 7 for value in colors.to_dict().values())


class TestLightDarkCorrespondence:
    """浅色与深色角色必须一一对应（同一色调板的不同色调）"""

    def test_primary_uses_tone_40_and_80(self) -> None:
        scheme = scheme_from_seed(BASELINE_SEED)
        light = scheme.roles(dark=False)
        dark = scheme.roles(dark=True)
        assert abs(_tone(light["primary"]) - 40) <= 1.5
        assert abs(_tone(dark["primary"]) - 80) <= 1.5

    def test_surface_uses_tone_98_and_6(self) -> None:
        scheme = scheme_from_seed(BASELINE_SEED)
        assert abs(_tone(scheme.roles(dark=False)["surface"]) - 98) <= 2.5
        assert abs(_tone(scheme.roles(dark=True)["surface"]) - 6) <= 1.0

    def test_every_dark_role_is_defined(self) -> None:
        """不存在"深色未定义"的角色：深浅两套键集合相同"""
        light = MaterialColors.light().to_dict()
        dark = MaterialColors.dark().to_dict()
        assert light.keys() == dark.keys()

    def test_container_ladder_shrinks_in_dark(self) -> None:
        """深色主题的容器层级应比 surface 更亮（抬升 = 变亮）"""
        dark = MaterialColors.dark()
        assert _tone(dark.surface_container_low) > _tone(dark.surface)
        assert _tone(dark.surface_container_highest) > _tone(dark.surface_container_low)


class TestSeedDerivation:
    """任意种子都能生成协调配色"""

    def test_baseline_seed_keeps_brand_primary(self) -> None:
        assert MaterialColors.light().primary == BASELINE_SEED

    def test_error_palette_is_seed_independent(self) -> None:
        """error 使用固定色相，换种子不应改变（避免错误色变成品牌色）"""
        purple = MaterialColors.from_seed("#6750A4").error
        green = MaterialColors.from_seed("#386A20").error
        assert purple == green

    def test_primary_chroma_floor(self) -> None:
        """低饱和种子也应得到足够饱和的主色（色度下限 48，经色域映射后仍饱和）"""
        gray_primary = MaterialColors.from_seed("#808080").primary
        assert Hct.from_hex(gray_primary).chroma >= 40

    def test_achromatic_seed_falls_back_to_brand_hue(self) -> None:
        """灰色种子不应产出随机品牌色：色相回落到基线紫"""
        gray_primary = MaterialColors.from_seed("#808080").primary
        assert abs(Hct.from_hex(gray_primary).hue - Hct.from_hex(BASELINE_SEED).hue) <= 6

    def test_scheme_is_cached(self) -> None:
        first = scheme_from_seed("#6455A0")
        second = scheme_from_seed("#6455a0")
        assert first is second

    def test_invalid_seed_raises(self) -> None:
        with pytest.raises(ValueError):
            MaterialColors.from_seed("not-a-color")

    def test_is_dark_flag(self) -> None:
        assert MaterialColors.light().is_dark is False
        assert MaterialColors.dark().is_dark is True


class TestShapeTokens:
    def test_shape_scale_is_fixed(self) -> None:
        assert Shape.ALL == (0, 4, 8, 12, 16, 28, 999)

    def test_component_radii_are_from_scale(self) -> None:
        for name in (
            "BUTTON", "ICON_BUTTON", "FAB", "FAB_REGULAR", "CARD", "DIALOG",
            "MENU", "TOOLTIP", "TEXT_FIELD", "LIST_ITEM", "CHIP",
            "NAV_INDICATOR", "SNACKBAR", "PROGRESS",
        ):
            value = getattr(ShapeRole, name)
            assert value in Shape.ALL, f"{name}={value} 不在圆角档位内"


class TestSpacingTokens:
    def test_space_is_four_dp_grid(self) -> None:
        assert all(value % 4 == 0 for value in Space.ALL)

    def test_page_margins_grow_with_size_class(self) -> None:
        assert Margin.page("compact") < Margin.page("medium") < Margin.page("expanded")
        assert Margin.page("unknown") == Margin.page("compact")

    def test_grid_columns(self) -> None:
        assert Grid.columns("compact") == 1
        assert Grid.columns("medium") == 1
        assert Grid.columns("expanded") == 2

    def test_component_sizes_are_on_grid(self) -> None:
        for name in (
            "NAV_RAIL_WIDTH", "NAV_RAIL_ITEM_HEIGHT", "NAV_BAR_HEIGHT",
            "BUTTON_HEIGHT", "ICON_BUTTON_SIZE", "FAB_SIZE", "FAB_MARGIN",
        ):
            value = getattr(Layout, name)
            assert value % 4 == 0, f"{name}={value} 不在 4dp 栅格上"


class TestMotionTokens:
    def test_durations_are_ordered(self) -> None:
        assert list(Duration.ALL) == sorted(Duration.ALL)
        assert all(value > 0 for value in Duration.ALL)

    def test_motion_switch_zeroes_duration(self) -> None:
        original = Motion.enabled
        try:
            Motion.set_enabled(False)
            assert Motion.duration(Duration.MEDIUM1) == 0
            Motion.set_enabled(True)
            assert Motion.duration(Duration.MEDIUM1) == Duration.MEDIUM1
        finally:
            Motion.set_enabled(original)

    def test_easing_curves_are_bezier(self) -> None:
        from PyQt6.QtCore import QEasingCurve

        for factory in (
            Easing.standard, Easing.standard_decelerate, Easing.standard_accelerate,
            Easing.emphasized, Easing.emphasized_decelerate, Easing.emphasized_accelerate,
        ):
            curve = factory()
            assert curve.type() == QEasingCurve.Type.BezierSpline
            # 强调类曲线允许中途冲过 1.0，只断言端点
            assert abs(curve.valueForProgress(0.0)) < 1e-6
            assert abs(curve.valueForProgress(1.0) - 1.0) < 1e-6


class TestStateTokens:
    def test_state_layer_opacities(self) -> None:
        assert StateLayer.HOVER == pytest.approx(0.08)
        assert StateLayer.FOCUS == pytest.approx(0.10)
        assert StateLayer.PRESSED == pytest.approx(0.10)
        assert StateLayer.DRAGGED == pytest.approx(0.16)
        assert StateLayer.DISABLED_CONTAINER == pytest.approx(0.12)
        assert StateLayer.DISABLED_CONTENT == pytest.approx(0.38)

    def test_blend_mixes_channels(self) -> None:
        mixed = blend("#000000", "#FFFFFF", 0.08)
        assert mixed.red() == 20  # 255 * 0.08 = 20.4 → 20
        assert (mixed.red(), mixed.green(), mixed.blue()) == (20, 20, 20)

    def test_blend_clamps_alpha(self) -> None:
        assert blend("#000000", "#FFFFFF", 2.0).name() == "#ffffff"
        assert blend("#000000", "#FFFFFF", -1.0).name() == "#000000"

    def test_with_alpha_does_not_mutate_source(self) -> None:
        # QColor 的 alpha 为 16bit，0.5 会有约 1e-5 的量化误差
        source = with_alpha("#6750A4", 0.5)
        assert source.alphaF() == pytest.approx(0.5, abs=1e-3)
        assert with_alpha("#6750A4", 1.0).alpha() == 255

    def test_elevation_levels(self) -> None:
        assert Elevation.effect(0) == (0, 0, 0)
        blur, offset, alpha = Elevation.effect(3)
        assert blur > 0 and offset > 0 and 0 < alpha <= 255
        assert Elevation.clamp(9) == 5
        assert Elevation.clamp(-2) == 0

    def test_dark_tint_increases_with_elevation(self) -> None:
        alphas = [Elevation.tint_alpha(level) for level in range(6)]
        assert alphas == sorted(alphas)

    def test_border_widths(self) -> None:
        assert Border.OUTLINE == 1
        assert Border.FOCUS == 2
