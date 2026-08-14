"""core.text_fit（Style1 Actions 文本显示范围拟合）单元测试

覆盖：
1. TestNoBounds — 未配置边界时原样返回（行为与旧版本一致）
2. TestWidthWrap — 超宽行自动换行（宽度不变量、空格优先断行、行号切片一致）
3. TestHeightTruncate — 高度超限按操作从末尾截断
4. TestBothBounds — 宽高边界同时生效
5. TestEdgeCases — 非法/退化边界、空行、超长单词
6. TestPaging — 截断后的分页切换（page_actions_lines）

宽度/高度断言基于 pictex 实测渲染（与合成/预览同一渲染链路）。
"""

from __future__ import annotations

import os
from itertools import pairwise

from pictex import Canvas

from arknights_video_pipeline.core.text_fit import fit_actions_lines, page_actions_lines
from arknights_video_pipeline.core.utils import PROJECT_ROOT, resolve_font_path

FONT_PATH = resolve_font_path(
    "SOURCEHANSANSCN-HEAVY.OTF", os.path.join(PROJECT_ROOT, "resource", "font")
)

# 默认布局：文本锚点 (50, 240)，默认边界右=272、下=965
TEXT_X, TEXT_Y = 50, 240
DEFAULT_RIGHT, DEFAULT_BOTTOM = 272, 965


def _measure_canvas(font_size: float = 25) -> Canvas:
    return Canvas().font_family(FONT_PATH).font_size(font_size).padding(10)


def _block_height(lines: list[str], font_size: float = 25) -> int:
    return _measure_canvas(font_size).render("\n".join(lines)).height


def _actions(n: int) -> list[str]:
    """n 个中等长度操作行（默认边界下无需换行）"""
    return [f"{i}.部署 能天使 (4,3) 左" for i in range(1, n + 1)]


class TestNoBounds:
    def test_returns_original_lines(self):
        lines = _actions(4)
        fitted, groups, dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, None, None, TEXT_X, TEXT_Y
        )
        assert fitted == lines
        assert groups == [(i, i + 1) for i in range(4)]
        assert dropped == 0

    def test_font_scale_applied(self):
        """字体缩放参与测量：font_scale=2 时等效字号 50"""
        lines = ["1.部署 能天使 (4,3) 左"]
        fitted_no, _, _ = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, None, None, TEXT_X, TEXT_Y
        )
        fitted_scaled, _, _ = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25, "font_scale": 2.0},
            200, None, TEXT_X, TEXT_Y,
        )
        assert fitted_no == lines
        assert len(fitted_scaled) > 1  # 大字号下同一行必然被换行


class TestWidthWrap:
    def test_short_lines_unchanged(self):
        """默认边界（右=272）下短行不换行"""
        lines = ["1.技能 能天使", "2.撤退 能天使"]
        fitted, groups, dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, DEFAULT_RIGHT, DEFAULT_BOTTOM, TEXT_X, TEXT_Y
        )
        assert fitted == lines
        assert groups == [(0, 1), (1, 2)]
        assert dropped == 0

    def test_long_line_wrapped_and_width_invariant(self):
        """超宽行换行后每行渲染宽度不超过右边界-锚点X"""
        lines = ["1.Deploy Exusiai (4,3) Left direction long text here"]
        max_right = 272
        fitted, groups, dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, max_right, None, TEXT_X, TEXT_Y
        )
        assert dropped == 0
        assert len(fitted) > 1
        canvas = _measure_canvas()
        for line in fitted:
            assert canvas.render(line).width <= max_right - TEXT_X
        assert groups == [(0, len(fitted))]  # 单操作换行成多行，切片完整覆盖

    def test_wrap_prefers_space_boundary(self):
        """空格优先断行：英文单词不被拆开（拆词仅发生在超长单词）"""
        lines = ["deploy exusiai skill retreat"]
        fitted, _, _ = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, 150, None, TEXT_X, TEXT_Y
        )
        assert len(fitted) > 1
        for line in fitted:
            # 段内不再存在可断行空格：要么整词、要么超长单词被拆
            assert _measure_canvas().render(line).width <= 150 - TEXT_X

    def test_wrap_preserves_characters(self):
        """换行不丢字符（忽略空白）：拼接结果与原文去除空格后一致"""
        lines = ["1.Deploy Exusiai (4,3) Left"]
        fitted, _, _ = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, 150, None, TEXT_X, TEXT_Y
        )
        joined = "".join(fitted).replace(" ", "")
        original = "".join(lines).replace(" ", "")
        assert joined == original

    def test_long_cjk_line_wrapped(self):
        """纯 CJK 无空格按字符断行"""
        lines = ["1.部署能天使德克萨斯银灰艾雅法拉棘刺山"]
        fitted, _, _ = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, 150, None, TEXT_X, TEXT_Y
        )
        assert len(fitted) > 1
        canvas = _measure_canvas()
        for line in fitted:
            assert canvas.render(line).width <= 150 - TEXT_X
        assert "".join(fitted) == lines[0]


class TestHeightTruncate:
    def test_tall_block_truncates_trailing_actions(self):
        """高度超限时按操作（换行组）从末尾截断"""
        lines = _actions(10)
        max_bottom = 600  # 可用高 360px，约 8 行容量
        fitted, groups, dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, None, max_bottom, TEXT_X, TEXT_Y
        )
        assert dropped > 0
        assert len(groups) == 10 - dropped
        # 截断后高度不超出可用高
        assert _block_height(fitted) <= max_bottom - TEXT_Y
        # 保留的前缀组完整（组数与内容对应）
        assert fitted[0] == lines[0]
        assert len(fitted) == sum(e - s for s, e in groups)

    def test_keeps_at_least_one_action(self):
        """极端高度（放不下更多组）时仍保留第一个操作"""
        lines = _actions(5)
        fitted, groups, dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, None, 320, TEXT_X, TEXT_Y
        )
        assert dropped == 4
        assert len(groups) == 1
        assert fitted[0] == lines[0]
        assert groups[0] == (0, len(fitted))


class TestBothBounds:
    def test_wrap_then_truncate(self):
        """宽高边界同时生效：先换行再按高度截断"""
        lines = [
            "1.Deploy Exusiai (4,3) Left direction",
            "2.Deploy Texas (5,3) Right direction long",
            "3.Skill Exusiai",
        ]
        fitted, groups, _dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, 272, 420, TEXT_X, TEXT_Y
        )
        canvas = _measure_canvas()
        for line in fitted:
            assert canvas.render(line).width <= 272 - TEXT_X
        assert _block_height(fitted) <= 420 - TEXT_Y
        assert sum(e - s for s, e in groups) == len(fitted)

    def test_default_bounds_keep_normal_actions(self):
        """默认边界（272/965）下，15 个短操作行不换行不截断"""
        lines = [f"{i}.技能 能天使" for i in range(1, 16)]
        fitted, groups, dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, DEFAULT_RIGHT, DEFAULT_BOTTOM, TEXT_X, TEXT_Y
        )
        assert fitted == lines
        assert dropped == 0
        assert len(groups) == 15

    def test_default_bounds_truncate_overflowing_block(self):
        """默认边界下超长列表按操作截断到可用高度内"""
        lines = [f"{i}.技能 能天使" for i in range(1, 40)]
        fitted, groups, dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, DEFAULT_RIGHT, DEFAULT_BOTTOM, TEXT_X, TEXT_Y
        )
        assert dropped > 0
        assert _block_height(fitted) <= DEFAULT_BOTTOM - TEXT_Y
        assert len(groups) + dropped == 39


class TestEdgeCases:
    def test_empty_lines(self):
        fitted, groups, dropped = fit_actions_lines(
            [], FONT_PATH, {"font_size": 25}, DEFAULT_RIGHT, DEFAULT_BOTTOM, TEXT_X, TEXT_Y
        )
        assert fitted == [] and groups == [] and dropped == 0

    def test_empty_line_in_middle(self):
        lines = ["1.部署 能天使", "", "3.技能 能天使"]
        fitted, groups, dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, 150, None, TEXT_X, TEXT_Y
        )
        assert dropped == 0
        assert len(groups) == 3
        assert len(fitted) > 3  # 前后两行被换行展开

    def test_degenerate_width_disabled(self):
        """max_text_right <= text_x + 2*padding 视为未配置宽度（避免死循环/全丢）"""
        lines = ["1.部署 能天使 (4,3) 左", "2.技能 能天使"]
        fitted, groups, dropped = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, 60, None, TEXT_X, TEXT_Y
        )
        assert fitted == lines
        assert groups == [(0, 1), (1, 2)]
        assert dropped == 0

    def test_extra_long_word_split_by_characters(self):
        """超长无空格单词按字符断行且不丢字符"""
        lines = ["deployexusiaitexastexasia"]
        fitted, _, _ = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, 150, None, TEXT_X, TEXT_Y
        )
        assert len(fitted) > 1
        assert "".join(fitted) == lines[0]
        canvas = _measure_canvas()
        for line in fitted:
            assert canvas.render(line).width <= 150 - TEXT_X


class TestPaging:
    """page_actions_lines 分页显示（截断后按 video_time 切换）"""

    def _paged(self, lines, vts, duration=90.0, switch=0.5, right=DEFAULT_RIGHT,
               bottom=DEFAULT_BOTTOM):
        return page_actions_lines(
            lines, FONT_PATH, {"font_size": 25}, right, bottom,
            TEXT_X, TEXT_Y, vts, switch, duration,
        )

    def test_no_bounds_returns_none(self):
        assert self._paged(_actions(30), [1.0 + i for i in range(30)],
                           right=None, bottom=None) is None

    def test_no_truncation_returns_none(self):
        """放得下时不分页（保持单页静态显示）"""
        lines = [f"{i}.技能 能天使" for i in range(1, 11)]
        assert self._paged(lines, [1.0 + i for i in range(10)]) is None

    def test_missing_video_time_returns_none(self):
        """任一操作缺 video_time 则不分页（切换需要该字段）"""
        vts = [1.0 + i for i in range(40)]
        vts[5] = None
        assert self._paged(_actions(40), vts) is None

    def test_video_time_count_mismatch_returns_none(self):
        assert self._paged(_actions(40), [1.0] * 39) is None

    def test_empty_lines_returns_none(self):
        assert self._paged([], []) is None

    def test_pages_cover_all_actions(self):
        """分页覆盖全部操作、页间无缝衔接、每页不超高、末页到视频结束"""
        lines = [f"{i}.技能 能天使" for i in range(1, 41)]
        vts = [5.0 + i * 2.0 for i in range(40)]
        pages = self._paged(lines, vts)
        assert pages is not None
        assert len(pages) >= 2
        assert abs(pages[0].t_start - 0.5) < 1e-6
        for a, b in pairwise(pages):
            assert a.end == b.start  # 无丢失无重叠
            assert abs(a.t_end - b.t_start) < 1e-6
        assert pages[-1].end == 40
        assert abs(pages[-1].t_end - 90.0) < 1e-6
        for page in pages:
            assert page.t_end - page.t_start > 0
            assert _block_height(page.lines) <= DEFAULT_BOTTOM - TEXT_Y
            assert sum(e - s for s, e in page.line_groups) == len(page.lines)

    def test_switch_at_last_action_video_time(self):
        """切换时刻 = 页内最后一个操作的 video_time（未到末页时）"""
        lines = [f"{i}.技能 能天使" for i in range(1, 41)]
        vts = [5.0 + i * 2.0 for i in range(40)]
        pages = self._paged(lines, vts)
        assert pages is not None
        for page in pages[:-1]:
            assert abs(page.t_end - vts[page.end - 1]) < 1e-6

    def test_first_page_matches_static_fit(self):
        """分页首页与单页静态拟合完全一致"""
        lines = [f"{i}.技能 能天使" for i in range(1, 41)]
        vts = [5.0 + i * 2.0 for i in range(40)]
        fitted, groups, _ = fit_actions_lines(
            lines, FONT_PATH, {"font_size": 25},
            DEFAULT_RIGHT, DEFAULT_BOTTOM, TEXT_X, TEXT_Y,
        )
        pages = self._paged(lines, vts)
        assert pages is not None
        assert pages[0].lines == fitted
        assert pages[0].line_groups == groups

    def test_same_time_actions_skipped(self):
        """完成时刻不晚于页起点的操作（同刻）整页跳过，不丢后续页"""
        lines = [f"{i}.技能 能天使" for i in range(1, 41)]
        # 前 30 个操作同刻 10.0（一页放不下），其后操作时间递增
        vts = [10.0] * 30 + [20.0 + (i - 30) * 2.0 for i in range(30, 40)]
        pages = self._paged(lines, vts)
        assert pages is not None
        assert len(pages) >= 2
        # 第 1 页显示到 10.0；同刻操作被跳过；后续页切换时刻严格递增
        assert abs(pages[0].t_end - 10.0) < 1e-6
        assert pages[0].end < 30
        for a, b in pairwise(pages):
            assert b.start >= a.end  # 无重叠；同刻操作可留在同页（无跳过）
            assert a.t_end - a.t_start > 0
            assert b.t_start >= a.t_end - 1e-6
        assert pages[-1].end == 40

    def test_video_time_clamped_to_video_duration(self):
        """video_time 超出视频时长时切换时刻被钳制，不产生负时长页"""
        lines = [f"{i}.技能 能天使" for i in range(1, 40)]
        vts = [5.0 + i * 2.0 for i in range(39)]  # 末操作 81s > 60s
        pages = self._paged(lines, vts, duration=60.0)
        assert pages is not None
        for page in pages:
            assert page.t_end <= 60.0 + 1e-6
            assert page.t_end - page.t_start > 0
        assert pages[-1].t_end == 60.0
