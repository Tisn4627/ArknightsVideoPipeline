"""core.map_overlay（逐操作显示）单元测试

覆盖：
1. TestParseResolution — 分辨率字符串解析
2. TestHasVideoTime — video_time 扩展字段检测
3. TestActionTimeline — 时间线构建（回退/裁剪）
4. TestMapNumberClips — 地图数字 clips（需求 4 的 1/2/3 场景、全局序号、坐标变换、尺寸算法）
5. TestPanelHighlightClips — 左侧面板高亮（区间、行对齐）
6. TestBuildMapOverlayClips — 顶层入口降级行为

数值断言基于真实关卡数据（act15d0_08，见调研阶段实测值）：
- 近似法全图最小格宽 72.388 / 最小格高 51.145
- 精确法 (row=3, col=6) 最小边长 77.532
"""

from __future__ import annotations

import json
import os

import pytest

from arknights_video_pipeline.core.map_overlay import (
    DEFAULT_MAP_OVERLAY_CONFIG,
    build_action_timeline,
    build_map_number_clips,
    build_map_overlay_clips,
    build_panel_highlight_clips,
    compute_approximate_cell_size,
    compute_precise_cell_size,
    has_video_time,
    load_level,
    parse_resolution,
)
from arknights_video_pipeline.core.utils import PROJECT_ROOT, resolve_font_path

FONT_PATH = resolve_font_path(
    "SOURCEHANSANSCN-HEAVY.OTF", os.path.join(PROJECT_ROOT, "resource", "font")
)
LEVELS_PATH = os.path.join(PROJECT_ROOT, "resource", "tile", "levels.json")


@pytest.fixture(scope="module")
def level():
    """真实关卡数据（act15d0_08，12x8）"""
    with open(LEVELS_PATH, encoding="utf-8") as f:
        levels = json.load(f)
    return next(level for level in levels if level.get("stageId") == "act15d0_08")


def _make_actions():
    """4 个操作：1 个无位置（SpeedUp）+ 3 个同格 (col=6,row=3) 的操作"""
    return [
        {"type": "SpeedUp", "video_time": 0.5},
        {"type": "Deploy", "name": "遥", "location": [6, 3], "direction": "Down", "video_time": 1.0},
        {"type": "Deploy", "name": "米格鲁", "location": [6, 3], "direction": "Left", "video_time": 2.0},
        {"type": "Skill", "name": "遥", "location": [6, 3], "video_time": 3.0},
    ]


def _clip_center(clip) -> tuple[float, float]:
    """clip 左上角 + 尺寸一半 = 中心"""
    w, h = clip.size
    px, py = clip.position(0)
    return (px + w / 2, py + h / 2)


# ── 分辨率解析 ──────────────────────────────────────────


class TestParseResolution:
    def test_valid(self):
        assert parse_resolution("1280x720") == (1280, 720)

    def test_uppercase(self):
        assert parse_resolution("1920X1080") == (1920, 1080)

    def test_invalid_falls_back(self):
        assert parse_resolution("abc") == (1280, 720)
        assert parse_resolution(None) == (1280, 720)
        assert parse_resolution("") == (1280, 720)


# ── video_time 检测 ─────────────────────────────────────


class TestHasVideoTime:
    def test_with_video_time(self):
        assert has_video_time([{"type": "Deploy", "video_time": 1.5}]) is True

    def test_without_video_time(self):
        assert has_video_time([{"type": "Deploy"}]) is False
        assert has_video_time([]) is False

    def test_mixed(self):
        assert has_video_time([{"type": "Deploy"}, {"type": "Skill", "video_time": 2.0}]) is True


# ── 时间线构建 ──────────────────────────────────────────


class TestActionTimeline:
    def test_starts_follow_video_time(self):
        tl = build_action_timeline(_make_actions(), switch_time=0.5, video_duration=10)
        assert [e["start"] for e in tl] == [0.5, 1.0, 2.0, 3.0]
        assert [e["index"] for e in tl] == [1, 2, 3, 4]

    def test_missing_video_time_falls_back_to_previous(self):
        actions = [
            {"type": "Deploy", "location": [1, 1], "video_time": 1.0},
            {"type": "Skill", "location": [1, 1]},  # 缺失 -> 回退 1.0
        ]
        tl = build_action_timeline(actions, switch_time=0.5, video_duration=10)
        assert [e["start"] for e in tl] == [1.0, 1.0]

    def test_first_missing_falls_back_to_switch_time(self):
        actions = [{"type": "Deploy"}]
        tl = build_action_timeline(actions, switch_time=3.0, video_duration=10)
        assert tl[0]["start"] == 3.0

    def test_clamped_before_switch_time_and_after_duration(self):
        actions = [
            {"type": "Deploy", "video_time": 0.2},   # < switch_time
            {"type": "Skill", "video_time": 99.0},   # > duration
        ]
        tl = build_action_timeline(actions, switch_time=3.0, video_duration=10)
        assert tl[0]["start"] == 3.0
        assert tl[1]["start"] == 10.0

    def test_empty_actions(self):
        assert build_action_timeline([], 0.5, 10) == []


# ── 地图数字 clips ──────────────────────────────────────


class TestMapNumberClips:
    def test_single_cell_multiple_actions_intervals(self, level):
        """需求 4 场景：同格 3 个操作 ST=1/2/3，switch_time=0.5
        预期 0.5-1s 显示"2"、1-2s 显示"3"、2-3s 显示"4"（全局序号，SpeedUp 占 1）"""
        timeline = build_action_timeline(_make_actions(), switch_time=0.5, video_duration=10)
        clips = build_map_number_clips(
            timeline, level, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            cfg={}, font_path=FONT_PATH,
        )
        assert len(clips) == 3
        texts = [c.text for c in clips]
        assert texts == ["2", "3", "4"]
        intervals = sorted((c.start, c.duration) for c in clips)
        assert intervals == [
            (0.5, 0.5),  # 0.5s - 1.0s
            (1.0, 1.0),  # 1.0s - 2.0s
            (2.0, 1.0),  # 2.0s - 3.0s
        ]

    def test_start_time_reached_number_disappears(self, level):
        """到达 StartTime 后数字消失：区间结束即不再渲染"""
        timeline = build_action_timeline(
            [{"type": "Deploy", "location": [6, 3], "video_time": 2.0}],
            switch_time=0.5, video_duration=10,
        )
        clips = build_map_number_clips(
            timeline, level, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            cfg={}, font_path=FONT_PATH,
        )
        assert len(clips) == 1
        clip = clips[0]
        assert clip.start == 0.5
        assert abs(clip.start + clip.duration - 2.0) < 1e-6

    def test_global_index_with_speedup_placeholder(self, level):
        """SpeedUp 无位置不产生数字，但占用全局序号（首操作显示 2）"""
        timeline = build_action_timeline(_make_actions(), switch_time=0.5, video_duration=10)
        clips = build_map_number_clips(
            timeline, level, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            cfg={}, font_path=FONT_PATH,
        )
        assert min(int(c.text) for c in clips) == 2  # 不存在数字 1（SpeedUp 无位置）

    def test_actions_without_location_no_number(self, level):
        timeline = build_action_timeline(
            [{"type": "SpeedUp", "video_time": 1.0}], switch_time=0.5, video_duration=10,
        )
        clips = build_map_number_clips(
            timeline, level, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            cfg={}, font_path=FONT_PATH,
        )
        assert clips == []

    def test_out_of_bounds_location_skipped(self, level):
        timeline = build_action_timeline(
            [{"type": "Deploy", "location": [99, 99], "video_time": 1.0}],
            switch_time=0.5, video_duration=10,
        )
        clips = build_map_number_clips(
            timeline, level, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            cfg={}, font_path=FONT_PATH,
        )
        assert clips == []

    def test_number_centered_on_cell_center(self, level):
        """数字中心 = 格子中心（识别分辨率坐标）"""
        from ArknightsVideoRecognition.tile import get_tile_screen_pos

        center = get_tile_screen_pos(level, 3, 6, (1280, 720))
        timeline = build_action_timeline(
            [{"type": "Deploy", "location": [6, 3], "video_time": 5.0}],
            switch_time=0.5, video_duration=10,
        )
        clips = build_map_number_clips(
            timeline, level, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            cfg={}, font_path=FONT_PATH,
        )
        assert len(clips) == 1
        cx, cy = _clip_center(clips[0])
        assert abs(cx - center[0]) < 1.0
        assert abs(cy - center[1]) < 1.0

    def test_output_transform_with_scale_and_offset(self, level):
        """坐标换算：识别分辨率 -> 视频原生(1920x1080) -> 输出画布(scale=0.85, x=272, y=47)"""
        from ArknightsVideoRecognition.tile import get_tile_screen_pos

        center = get_tile_screen_pos(level, 3, 6, (1280, 720))
        expect_x = center[0] * (1920 / 1280) * 0.85 + 272
        expect_y = center[1] * (1920 / 1280) * 0.85 + 47
        timeline = build_action_timeline(
            [{"type": "Deploy", "location": [6, 3], "video_time": 5.0}],
            switch_time=0.5, video_duration=10,
        )
        clips = build_map_number_clips(
            timeline, level, switch_time=0.5, video_duration=10,
            video_scale=0.85, video_x=272, video_y=47,
            video_native_size=(1920, 1080), cfg={}, font_path=FONT_PATH,
        )
        cx, cy = _clip_center(clips[0])
        assert abs(cx - expect_x) < 1.0
        assert abs(cy - expect_y) < 1.0

    def test_number_fits_cell_size(self, level):
        """数字字形不超出格子可用尺寸（字号按字形自动适配）"""
        from pictex import Canvas

        timeline = build_action_timeline(
            [{"type": "Deploy", "location": [6, 3], "video_time": 5.0}],
            switch_time=0.5, video_duration=10,
        )
        cfg = {**DEFAULT_MAP_OVERLAY_CONFIG, "number_size_mode": "precise"}
        clips = build_map_number_clips(
            timeline, level, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            cfg=cfg, font_path=FONT_PATH,
        )
        assert len(clips) == 1
        cell = compute_precise_cell_size(level, (1280, 720), 3, 6)
        glyph = Canvas().font_family(FONT_PATH).font_size(
            clips[0]._canvas._style.font_size.get()
        ).render(clips[0].text)
        assert glyph.width <= cell + 1.0
        assert glyph.height <= cell + 1.0

    def test_number_fills_cell_glyph_height(self, level):
        """数字铺满格子：字形高度须达到格子尺寸的 95% 以上
        （阴影模糊边界不得计入字号约束，否则字号被过度缩小）"""
        from pictex import Canvas

        timeline = build_action_timeline(
            [{"type": "Deploy", "location": [6, 3], "video_time": 5.0}],
            switch_time=0.5, video_duration=10,
        )
        cfg = {**DEFAULT_MAP_OVERLAY_CONFIG, "number_size_mode": "precise"}
        clips = build_map_number_clips(
            timeline, level, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            cfg=cfg, font_path=FONT_PATH,
        )
        assert len(clips) == 1
        cell = compute_precise_cell_size(level, (1280, 720), 3, 6)
        glyph = Canvas().font_family(FONT_PATH).font_size(
            clips[0]._canvas._style.font_size.get()
        ).render(clips[0].text)
        assert glyph.height >= 0.95 * cell


# ── 格子尺寸算法 ────────────────────────────────────────


class TestCellSize:
    def test_approximate_matches_global_min(self, level):
        """近似法：全图最小格宽/格高取最小值（实测 72.388 / 51.145）"""
        size = compute_approximate_cell_size(level, (1280, 720))
        assert 50.0 < size < 60.0
        # 验证与逐行逐列最小值的等价性
        from ArknightsVideoRecognition.tile import get_all_tile_positions

        positions = get_all_tile_positions(level, (1280, 720))
        min_w = min(
            abs(positions[r][c + 1][0] - positions[r][c][0])
            for r in range(len(positions)) for c in range(len(positions[r]) - 1)
        )
        min_h = min(
            abs(positions[r + 1][c][1] - positions[r][c][1])
            for r in range(len(positions) - 1) for c in range(len(positions[r]))
        )
        assert size == min(min_w, min_h)

    def test_precise_matches_projected_min_edge(self, level):
        """精确法：(row=3, col=6) 最小边长实测 77.532"""
        size = compute_precise_cell_size(level, (1280, 720), 3, 6)
        assert abs(size - 77.53) < 0.1

    def test_precise_different_cells_differ(self, level):
        """精确法逐格不同（透视投影），且均大于 0"""
        s1 = compute_precise_cell_size(level, (1280, 720), 0, 0)
        s2 = compute_precise_cell_size(level, (1280, 720), 3, 6)
        assert s1 > 0 and s2 > 0
        assert abs(s1 - s2) > 1.0  # 不同格子投影尺寸差异明显


# ── 面板高亮 clips ──────────────────────────────────────


class TestPanelHighlightClips:
    def _lines(self):
        return ["1.二倍速", "2.部署 遥 ↓", "3.部署 米格鲁 ←", "4.技能 遥"]

    def test_intervals_follow_timeline(self):
        """"下一操作"语义：行 i 高亮 [上一个不同 video_time, 该行 video_time)
        前一个操作执行完毕后立即预告下一行（与地图数字规则一致）；
        SpeedUp 与 switch_time 同刻不产生区间，末行接管至视频结束"""
        timeline = build_action_timeline(_make_actions(), switch_time=0.5, video_duration=10)
        clips = build_panel_highlight_clips(
            self._lines(), timeline, switch_time=0.5, video_duration=10,
            text_config={"font_size": 25, "text_x": 50, "text_y": 240},
            font_path=FONT_PATH, cfg={},
        )
        assert len(clips) == 3
        assert [c.text for c in clips] == ["2.部署 遥 ↓", "3.部署 米格鲁 ←", "4.技能 遥"]
        intervals = sorted((c.start, c.start + c.duration) for c in clips)
        assert intervals == [
            (0.5, 1.0),   # 行2: 首个操作后立即预告
            (1.0, 2.0),   # 行3
            (2.0, 10.0),  # 行4: 预告区间 + 末行接管，无缝合并
        ]

    def test_lines_aligned_with_block_text(self):
        """高亮行与主文本块逐行对齐：每行内容顶部与主文本多行渲染完全一致
        （按真实行距测量，消除等距近似随行数累积的偏移）"""
        import numpy as np

        from pictex import Canvas

        text_config = {"font_size": 25, "text_x": 50, "text_y": 240}
        timeline = build_action_timeline(_make_actions(), switch_time=0.5, video_duration=10)
        clips = build_panel_highlight_clips(
            self._lines(), timeline, switch_time=0.5, video_duration=10,
            text_config=text_config, font_path=FONT_PATH, cfg={},
        )
        # 主文本多行渲染的每行内容顶部（真实行距）
        block = Canvas().font_family(FONT_PATH).font_size(25).padding(10)
        alpha = block.render("\n".join(self._lines())).to_numpy("RGBA")[:, :, 3]
        tops = []
        in_text = False
        for y in range(alpha.shape[0]):
            has = bool(alpha[y].max() > 0)
            if has and not in_text:
                tops.append(y)
                in_text = True
            elif not has and in_text:
                in_text = False
        # 高亮 clip 的内容顶部须与主文本对应行内容顶部重合（≤1px 取整）
        single_top = int(np.where(
            block.render(self._lines()[0]).to_numpy("RGBA")[:, :, 3].max(axis=1) > 0
        )[0][0])
        # 新语义下 SpeedUp 行（与 switch_time 同刻）无区间，clips 从第 2 行开始
        assert [c.text for c in clips] == self._lines()[1:]
        for i, clip in enumerate(clips, 1):
            px, py = clip.position(0)
            assert px == 50
            assert abs((py + single_top) - (240 + tops[i])) < 1.0

    def test_line_count_mismatch_returns_empty(self):
        timeline = build_action_timeline(_make_actions(), switch_time=0.5, video_duration=10)
        clips = build_panel_highlight_clips(
            ["只有一行"], timeline, switch_time=0.5, video_duration=10,
            text_config={"font_size": 25}, font_path=FONT_PATH, cfg={},
        )
        assert clips == []

    def test_all_missing_video_time_returns_empty(self):
        """全部操作缺 video_time 时时间线全落在 switch_time，无有效区间"""
        actions = [{"type": "Deploy"}, {"type": "Skill"}]
        timeline = build_action_timeline(actions, switch_time=0.5, video_duration=10)
        clips = build_panel_highlight_clips(
            ["1.部署", "2.技能"], timeline, switch_time=0.5, video_duration=10,
            text_config={"font_size": 25}, font_path=FONT_PATH, cfg={},
        )
        assert clips == []

    def test_same_timestamp_adjacent_row_not_skipped(self):
        """同刻相邻行（如 SkillDaemon 缺 video_time 回退到上一操作时刻）：
        行 i 高亮 [上一不同 video_time, 该行 video_time)——同刻组内仅末行
        获得区间（组内非首行零区间不产生 clip），末行接管长区间（挂机提示），
        任何操作都不会被遗漏展示"""
        actions = [
            {"type": "Deploy", "video_time": 1.0},
            {"type": "Skill", "video_time": 3.0},
            {"type": "SkillDaemon"},  # 缺失 -> 回退 3.0（与上一条同刻）
        ]
        timeline = build_action_timeline(actions, switch_time=0.5, video_duration=10)
        clips = build_panel_highlight_clips(
            ["1.部署", "2.技能", "3.技能一键"], timeline, switch_time=0.5, video_duration=10,
            text_config={"font_size": 25}, font_path=FONT_PATH, cfg={},
        )
        assert len(clips) == 3
        assert clips[0].text == "1.部署"
        assert abs(clips[0].start - 0.5) < 1e-6
        assert abs(clips[0].start + clips[0].duration - 1.0) < 1e-6
        # 行2 在 [1.0, 3.0) 预告（下一个要执行的是技能）
        assert clips[1].text == "2.技能"
        assert abs(clips[1].start - 1.0) < 1e-6
        assert abs(clips[1].start + clips[1].duration - 3.0) < 1e-6
        # 行3（挂机）接管 [3.0, 10.0)
        assert clips[2].text == "3.技能一键"
        assert abs(clips[2].start - 3.0) < 1e-6
        assert abs(clips[2].start + clips[2].duration - 10.0) < 1e-6

    def test_default_highlight_has_no_background_or_shadow_or_fade(self):
        """默认高亮行：无背景框、无阴影、无淡入淡出（不透明覆盖白色文本，防重影）"""
        timeline = build_action_timeline(_make_actions(), switch_time=0.5, video_duration=10)
        clips = build_panel_highlight_clips(
            self._lines(), timeline, switch_time=0.5, video_duration=10,
            text_config={"font_size": 25, "text_x": 50, "text_y": 240},
            font_path=FONT_PATH, cfg={},
        )
        assert len(clips) == 3
        for clip in clips:
            style = clip._canvas._style
            assert not style.background_color.was_set  # 无打底
            assert not style.text_shadows.was_set      # 无阴影
            # 无淡入淡出：opacity 保持常量 1.0（FadeIn 会替换为随时间变化的函数）
            assert clip.opacity(0) == 1.0
            assert clip.opacity(clip.duration / 2) == 1.0


# ── 顶层入口 ────────────────────────────────────────────


class TestBuildMapOverlayClips:
    def test_level_none_only_panel_highlight(self):
        """关卡数据缺失时优雅降级：仅生成面板高亮"""
        clips = build_map_overlay_clips(
            _make_actions(),
            ["1.二倍速", "2.部署 遥", "3.部署 米格鲁", "4.技能 遥"],
            level=None, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            map_cfg={}, text_config={"font_size": 25},
            font_path=FONT_PATH,
        )
        assert len(clips) == 3  # 只有高亮（SpeedUp 行同刻 switch_time 无区间），无地图数字
        assert all(hasattr(c, "text") for c in clips)

    def test_panel_highlight_disabled(self, level):
        cfg = {**DEFAULT_MAP_OVERLAY_CONFIG, "panel_highlight_enabled": False}
        clips = build_map_overlay_clips(
            _make_actions(),
            ["1.二倍速", "2.部署 遥", "3.部署 米格鲁", "4.技能 遥"],
            level=level, switch_time=0.5, video_duration=10,
            video_scale=1.0, video_x=0, video_y=0, video_native_size=None,
            map_cfg=cfg, text_config={"font_size": 25},
            font_path=FONT_PATH,
        )
        # 仅地图数字（3 个）
        assert len(clips) == 3
        assert all(isinstance(c.text, str) and c.text.isdigit() for c in clips)

    def test_load_level_real_stage(self):
        """真实 stageId 可加载关卡（act15d0_08）"""
        level = load_level("act15d0_08")
        assert level is not None
        assert level["width"] == 12 and level["height"] == 8

    def test_load_level_unknown_stage(self):
        assert load_level("not_a_real_stage_xyz") is None
        assert load_level("") is None
        assert load_level(None) is None
