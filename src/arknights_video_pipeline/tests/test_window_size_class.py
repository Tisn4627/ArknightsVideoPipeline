"""MD3 窗口尺寸类别与栅格 token 测试

验证 ``gui.theme.window_size`` / ``spacing`` 的断点与派生规则：

- compact(<600) / medium(600-839) / expanded(>=840) 的边界判定；
- 导航形态（底部导航 vs 侧边栏）、页边距、卡片列数随类别变化；
- 页面头字号角色随类别降级（45 → 36）。
"""

from __future__ import annotations

import pytest

from arknights_video_pipeline.gui.theme.spacing import Grid, Margin
from arknights_video_pipeline.gui.theme.window_size import (
    BREAKPOINT_EXPANDED,
    BREAKPOINT_MEDIUM,
    WindowSizeClass,
)


class TestSizeClassBoundaries:
    @pytest.mark.parametrize(
        ("width", "expected"),
        [
            (320, WindowSizeClass.COMPACT),
            (599, WindowSizeClass.COMPACT),
            (600, WindowSizeClass.MEDIUM),
            (839, WindowSizeClass.MEDIUM),
            (840, WindowSizeClass.EXPANDED),
            (1920, WindowSizeClass.EXPANDED),
        ],
    )
    def test_of(self, width: int, expected: str) -> None:
        assert WindowSizeClass.of(width) == expected

    def test_breakpoints(self) -> None:
        assert BREAKPOINT_MEDIUM == 600
        assert BREAKPOINT_EXPANDED == 840

    def test_all_classes_listed(self) -> None:
        assert WindowSizeClass.ALL == ("compact", "medium", "expanded")


class TestDerivedLayout:
    def test_bottom_navigation_only_on_compact(self) -> None:
        assert WindowSizeClass.uses_bottom_navigation("compact")
        assert not WindowSizeClass.uses_bottom_navigation("medium")
        assert not WindowSizeClass.uses_bottom_navigation("expanded")

    def test_rail_labels_only_on_expanded(self) -> None:
        assert WindowSizeClass.rail_shows_labels("expanded")
        assert not WindowSizeClass.rail_shows_labels("medium")
        assert not WindowSizeClass.rail_shows_labels("compact")

    def test_page_margins_grow(self) -> None:
        assert Margin.page("compact") == 16
        assert Margin.page("medium") == 24
        assert Margin.page("expanded") == 32

    def test_columns(self) -> None:
        assert Grid.columns("compact") == 1
        assert Grid.columns("medium") == 1
        assert Grid.columns("expanded") == 2

    def test_unknown_class_falls_back_to_compact(self) -> None:
        assert Margin.page("unknown") == Margin.page("compact")
        assert Grid.columns("unknown") == 1
