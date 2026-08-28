"""
core.map_overlay - 逐操作显示（地图操作序号 + 左侧面板当前操作高亮）

功能触发条件（三者同时满足）：
  1. 视频合成风格为 style1
  2. compose 配置 ``map_overlay.enabled = True``
  3. copilot JSON 的 actions 包含 ``video_time`` 扩展字段
     （由 recognition 后端 ``with_video_time`` 配置生成；缺失时记录警告并降级为静态文本）

地图数字显示规则：
  - 仅带 location 的 Deploy/Skill/Retreat 操作参与地图编号（全局序号，与左侧面板一致）
  - 每个格子按 video_time 排序，只显示"下一个将要执行"操作的序号
  - 显示区间 = [max(switch_time, 上一操作时刻), 该操作 video_time)，StartTime 到达即消失
  - 字号按格子可用尺寸计算：``number_size_mode`` 支持
    - ``approximate``：``get_all_tile_positions`` 求全图最小格宽/格高（最坏情况）
    - ``precise``：对每格 4 角调用 ``world_to_screen_pos`` 投影四边形取最小边长

左侧面板：保持静态全列表，以高亮色 + 可选半透明背景框标记"下一个将要执行"的
操作行（默认无打底、无阴影、无过渡，保证高亮行完全不透明地覆盖白色文本），
区间为 [上一个不同 video_time, 该行操作 video_time)，与地图数字规则一致：
前一个操作执行完毕后立即高亮下一行，避免"当前行"语义下操作间长空窗
（如部署完成到下一技能开始之间持续高亮已结束的操作）；末行接管
[最后一个 video_time, 视频结束)。文本范围限定发生截断且操作带 video_time
时（core.text_fit.page_actions_lines），主文本按页切换，面板高亮随页
独立构建：区间裁剪到页显示区间内，仅末页接管到视频结束。
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional, Sequence

import numpy as np
from movielite import TextClip
from movielite.vfx import FadeIn, FadeOut
from pictex import Canvas, Shadow

from arknights_video_pipeline.core.text_fit import (
    ActionsPage,
)

logger = logging.getLogger(__name__)

# map_overlay 默认配置（style1 DEFAULT_CONFIG 中同名子块以此为基准）
DEFAULT_MAP_OVERLAY_CONFIG: dict[str, Any] = {
    "enabled": False,                  # 逐操作显示总开关
    "resolution": "1280x720",          # 识别分辨率 WxH（与 recognition.resolution 一致）
    "number_size_mode": "approximate", # "approximate" | "precise"
    "number_font_ratio": 0.9,          # 字号 = 格子可用尺寸 * 该比例（铺满格子）
    "number_color": "#FFFFFF",         # 白色数字，直接叠加在地图上
    "number_shadow_enabled": True,
    "number_shadow_offset_x": 2,
    "number_shadow_offset_y": 2,
    "number_shadow_blur": 4,
    "number_shadow_color": "#000000",
    "number_bg_enabled": False,        # 数字不打底（默认关）
    "number_bg_color": "#000000",
    "number_bg_alpha": 0.0,            # 背景框不透明度 0~1
    "number_padding": 2,               # 数字与背景框间距
    "number_min_font_size": 8,         # 字号下限
    "fade_duration": 0.15,             # 数字淡入淡出时长（秒）
    "panel_highlight_enabled": True,   # 左侧面板高亮"下一个将要执行"的操作行
    "panel_highlight_color": "#FFD700",
    "panel_highlight_background": "#000000",
    "panel_highlight_bg_alpha": 0.0,   # 高亮背景框不透明度 0~1（默认无打底）
    "panel_fade_duration": 0.0,        # 高亮淡入淡出时长（秒，0=硬切换以完全覆盖白色文本）
}

# 主文本 TextClip 的固定内边距（video_compose.create_text_clip 中硬编码 padding=10），
# 高亮行必须使用相同 padding 才能与主文本逐行对齐
_PANEL_PADDING = 10

# 最小显示区间（秒）：区间过短会闪帧且难以辨认，直接跳过
_MIN_INTERVAL = 0.05


def parse_resolution(resolution: str | None) -> tuple[int, int]:
    """解析 "WxH" 分辨率字符串，非法时回退 (1280, 720)"""
    try:
        w, h = (int(x) for x in str(resolution or "").lower().split("x"))
        return (w, h)
    except (ValueError, AttributeError):
        return (1280, 720)


def load_level(stage_name: str) -> Optional[dict]:
    """按 stageId/code/levelId/name 加载关卡数据（延迟导入 vendored 的 tile loader）

    返回 None 时表示无法加载（导入失败或关卡不存在），调用方应跳过地图数字叠加。
    """
    if not stage_name:
        return None
    try:
        from arknights_video_recognition.tile import find_level
    except ImportError as exc:
        logger.warning("无法导入 arknights_video_recognition.tile，逐操作显示的地图数字不可用: %s", exc)
        return None
    try:
        return find_level(stage_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载关卡数据失败 (stage_name=%s): %s", stage_name, exc)
        return None


def _import_tile_calc():
    """延迟导入 vendored 的 tile.calc（仅依赖 numpy，无重依赖）"""
    from arknights_video_recognition.tile import calc
    return calc


def compute_approximate_cell_size(level: dict, screen_size: Sequence[int]) -> float:
    """近似法：全图最小格宽/格高（最坏情况），返回单值可用尺寸（识别分辨率像素）

    用 ``get_all_tile_positions`` 得到每格中心像素：
    同行相邻列中心距 = 格宽、同列相邻行中心距 = 格高（透视投影下每行/列各自不同），
    取全图最小值作为所有格子的统一可用尺寸。
    """
    calc = _import_tile_calc()
    positions = calc.get_all_tile_positions(level, screen_size)
    min_w = min(
        abs(positions[r][c + 1][0] - positions[r][c][0])
        for r in range(len(positions))
        for c in range(len(positions[r]) - 1)
    )
    min_h = min(
        abs(positions[r + 1][c][1] - positions[r][c][1])
        for r in range(len(positions) - 1)
        for c in range(len(positions[r]))
    )
    return min(min_w, min_h)


def compute_precise_cell_size(level: dict, screen_size: Sequence[int], row: int, col: int) -> float:
    """精确法：对指定格子 4 角投影出屏幕四边形，取最小边长作为可用尺寸

    使用 vendored ``_Calc`` 私有类的 ``world_to_screen_pos``（仅调用，不改动
    vendored 代码）；z 取格子高度类型的标准缩放，与干员站位投影一致。
    """
    calc = _import_tile_calc()
    calc_inst = calc._Calc(screen_size[0], screen_size[1], level)  # noqa: SLF001 - vendored 私有类仅调用
    cx, cy, z = calc_inst.get_character_world_pos(col, row)
    corners = [
        calc_inst.world_to_screen_pos((cx + dx, cy + dy, z))
        for dx, dy in ((0.5, 0.5), (-0.5, 0.5), (-0.5, -0.5), (0.5, -0.5))
    ]
    edges = [math.dist(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    return min(edges)


def has_video_time(actions: list[dict]) -> bool:
    """判断 actions 中是否包含 video_time 扩展字段"""
    return any(isinstance(a.get("video_time"), (int, float)) for a in (actions or []))


def build_action_timeline(
    actions: list[dict],
    switch_time: float,
    video_duration: float,
) -> list[dict]:
    """构建操作时间线：每个操作附带裁剪后的开始时刻

    规则：
    - video_time 缺失时回退到上一操作的时刻（首操作回退到 switch_time）
    - 时刻裁剪到 [switch_time, video_duration] 区间内

    Args:
        actions: copilot JSON 的 actions 列表
        switch_time: 进入战斗时间（BattleStart）
        video_duration: 视频总时长

    Returns:
        按全局序号排列的 ``[{"index", "start", "action"}]`` 列表
    """
    timeline: list[dict] = []
    prev_time = float(switch_time)
    for i, action in enumerate(actions or [], 1):
        raw = action.get("video_time")
        if isinstance(raw, (int, float)):
            t = max(float(raw), float(switch_time))
        else:
            t = prev_time
        t = min(t, float(video_duration))
        timeline.append({"index": i, "start": t, "action": action})
        prev_time = t
    return timeline


def _with_alpha(hex_color: str, alpha: float) -> str:
    """将 #RRGGBB 颜色转为 8 位 RGBA（#RRGGBBAA），支持 pictex 透明背景"""
    hex_color = (hex_color or "#000000").strip().lstrip("#")
    if len(hex_color) == 8:
        hex_color = hex_color[:6]
    a = max(0, min(255, int(round(float(alpha) * 255))))
    return f"#{hex_color}{a:02X}"


def _number_canvas(text: str, font_size: float, cfg: dict, font_path: str) -> Canvas:
    """构建地图数字的 Canvas（白色 + 阴影 + 可选半透明背景框）"""
    canvas = Canvas().font_family(font_path).font_size(font_size).color(
        # 回退值须与 DEFAULT_MAP_OVERLAY_CONFIG 一致（白色、默认不打底）
        cfg.get("number_color", "#FFFFFF")
    )
    if cfg.get("number_shadow_enabled", True):
        canvas = canvas.text_shadows(
            Shadow(
                offset=(
                    cfg.get("number_shadow_offset_x", 2),
                    cfg.get("number_shadow_offset_y", 2),
                ),
                blur_radius=cfg.get("number_shadow_blur", 4),
                color=cfg.get("number_shadow_color", "#000000"),
            )
        )
    if cfg.get("number_bg_enabled", False):
        canvas = canvas.background_color(
            _with_alpha(cfg.get("number_bg_color", "#000000"), cfg.get("number_bg_alpha", 0.45))
        )
        canvas = canvas.border_radius(max(2, int(font_size * 0.15)))
    canvas = canvas.padding(cfg.get("number_padding", 2))
    return canvas


def _make_number_clip(
    text: str,
    start: float,
    end: float,
    center: tuple[float, float],
    cell_size_out: float,
    cfg: dict,
    font_path: str,
) -> Optional[TextClip]:
    """创建单个地图数字 TextClip（居中对齐格子中心，字号自动适配单元格）

    字号迭代基于**纯字形尺寸**（无阴影/无背景测量）：阴影的模糊边界会大幅撑大
    pictex 渲染尺寸，若将其计入"放不下"约束会把字号过度缩小，导致数字无法铺满
    格子。字形收敛后再以完整样式（阴影/背景）渲染，阴影向外扩展不占格子约束。
    """
    if end <= start + 1e-9:
        return None

    # 基准字号 = 格子可用尺寸 * 比例；按字形宽高与格子比较迭代缩放，
    # 直至放得下或达到字号下限（最多 3 轮，纯字形迭代通常 1-2 轮收敛）。
    font_size = max(
        cell_size_out * float(cfg.get("number_font_ratio", 0.9)),
        float(cfg.get("number_min_font_size", 8)),
    )
    measure_canvas = Canvas().font_family(font_path).font_size(font_size)
    for _ in range(3):
        glyph = measure_canvas.render(text)
        if glyph.width <= cell_size_out and glyph.height <= cell_size_out:
            break
        ratio = min(
            cell_size_out / max(glyph.width, 1.0),
            cell_size_out / max(glyph.height, 1.0),
        )
        new_font_size = max(
            font_size * ratio,
            float(cfg.get("number_min_font_size", 8)),
        )
        if new_font_size >= font_size - 1e-9:
            break  # 已触达字号下限
        font_size = new_font_size
        measure_canvas = measure_canvas.font_size(font_size)

    canvas = _number_canvas(text, font_size, cfg, font_path)
    rendered = canvas.render(text)
    clip = TextClip(text, start=start, duration=end - start, canvas=canvas)
    clip.set_position((center[0] - rendered.width / 2, center[1] - rendered.height / 2))

    fade = float(cfg.get("fade_duration", 0.15))
    if fade > 0:
        actual = min(fade, (end - start) / 3)
        if actual > 0:
            clip.add_effect(FadeIn(actual))
            clip.add_effect(FadeOut(actual))
    return clip


def build_map_number_clips(
    timeline: list[dict],
    level: dict,
    switch_time: float,
    video_duration: float,
    video_scale: float,
    video_x: float,
    video_y: float,
    video_native_size: Optional[Sequence[int]],
    cfg: dict,
    font_path: str,
) -> list[TextClip]:
    """构建地图上的操作序号数字 clips

    坐标换算链：识别分辨率（tile 投影基准）→ 视频原生分辨率（等比）→
    输出画布（video_scale + video_x/video_y 位移）。

    Args:
        timeline: build_action_timeline 的输出
        level: 关卡 dict
        switch_time: 进入战斗时间
        video_duration: 视频总时长
        video_scale / video_x / video_y: style1 视频在输出画布上的变换
        video_native_size: 视频原生分辨率 (w, h)，None 时假设与识别分辨率一致
        cfg: map_overlay 配置块
        font_path: 数字字体绝对路径

    Returns:
        数字 TextClip 列表（可能为空）
    """
    resolution = parse_resolution(cfg.get("resolution", "1280x720"))
    if video_native_size and video_native_size[0] > 0:
        scale_to_video = video_native_size[0] / resolution[0]
    else:
        scale_to_video = 1.0
    scale_out = scale_to_video * float(video_scale)

    def to_output(pos: Sequence[float]) -> tuple[float, float]:
        return (pos[0] * scale_out + video_x, pos[1] * scale_out + video_y)

    # 按格子分组带 location 的操作（location = [col, row]）
    cells: dict[tuple[int, int], list[dict]] = {}
    for entry in timeline:
        location = entry["action"].get("location")
        if not location or len(location) < 2:
            continue
        col, row = int(location[0]), int(location[1])
        if not (0 <= row < int(level["height"]) and 0 <= col < int(level["width"])):
            logger.warning(
                "操作 #%d 的 location %s 超出地图范围 (%dx%d)，跳过地图数字",
                entry["index"], list(location), level["width"], level["height"],
            )
            continue
        cells.setdefault((row, col), []).append(entry)

    if not cells:
        return []

    calc = _import_tile_calc()
    mode = str(cfg.get("number_size_mode", "approximate")).lower()
    if mode == "precise":
        global_usable = None
    else:
        try:
            global_usable = compute_approximate_cell_size(level, resolution)
        except Exception as exc:  # noqa: BLE001
            logger.warning("近似法计算格子尺寸失败，回退精确法: %s", exc)
            mode = "precise"
            global_usable = None

    clips: list[TextClip] = []
    for (row, col), entries in sorted(cells.items()):
        if mode == "precise":
            try:
                cell_usable = compute_precise_cell_size(level, resolution, row, col)
            except Exception as exc:  # noqa: BLE001
                logger.warning("精确法计算格子 (%d,%d) 尺寸失败，跳过: %s", row, col, exc)
                continue
        else:
            cell_usable = global_usable
        cell_usable_out = cell_usable * scale_out

        try:
            center = to_output(calc.get_tile_screen_pos(level, row, col, resolution))
        except Exception as exc:  # noqa: BLE001
            logger.warning("获取格子 (%d,%d) 屏幕坐标失败，跳过: %s", row, col, exc)
            continue

        # 按开始时刻排序（同刻按全局序号），只显示"下一个将要执行"的操作
        entries.sort(key=lambda e: (e["start"], e["index"]))
        prev_start = float(switch_time)
        for entry in entries:
            start = float(entry["start"])
            if start - prev_start >= _MIN_INTERVAL:
                clip = _make_number_clip(
                    str(entry["index"]), prev_start, start, center, cell_usable_out, cfg, font_path
                )
                if clip is not None:
                    clips.append(clip)
            prev_start = max(prev_start, start)
    return clips


def _measure_line_top_offsets(lines: Sequence[str], canvas: Canvas) -> Optional[list[int]]:
    """测量多行文本每行内容顶部的真实 y（相对 canvas 顶部，含 padding）

    多行渲染的行距 = 字体行高（约 37.5px，取整后逐行交替 37/38），按"单行
    渲染高度 - 2*padding"近似会随行数累积 1px 级偏差，导致高亮行与主文本
    逐行错位（残影）。此处直接渲染整块文本并按不透明像素扫描每行起点，
    完全吸收取整误差。

    行内字形存在竖向空隙（如行尾 "←" 与正文相隔 1~2 行）时会被拆成两个
    带，与行数不一致；相邻行的字形间距远大于此（约 13px），按小间隙
    （≤6 行）合并后重试。

    返回 None 表示测量失败（如存在空行），调用方应回退到等距行高。
    """
    image = canvas.render("\n".join(lines))
    alpha = image.to_numpy("RGBA")[:, :, 3]
    bands: list[list[int]] = []
    in_text = False
    for y in range(alpha.shape[0]):
        has = bool(alpha[y].max() > 0)
        if has and not in_text:
            bands.append([y, y])
            in_text = True
        elif has and in_text:
            bands[-1][1] = y
        elif not has and in_text:
            in_text = False
    tops = [b[0] for b in bands]
    if len(tops) != len(lines):
        merged: list[list[int]] = []
        for band in bands:
            if merged and band[0] - merged[-1][1] <= 6:
                merged[-1][1] = band[1]
            else:
                merged.append(list(band))
        tops = [b[0] for b in merged]
    if len(tops) != len(lines):
        logger.warning(
            "行位置测量与行数不一致 (%d vs %d)，回退到等距行高",
            len(tops), len(lines),
        )
        return None
    return tops


def _measure_single_line_glyph_top(line: str, canvas: Canvas) -> int:
    """测量单行渲染时该行字形的顶部 y（相对 canvas 顶部，含 padding）

    同一行文本在多行文本块与单行渲染中的字形垂直位置可能不同：
    "←" 等小字形在行盒内垂直居中，顶部低于常规字形，若以
    ``line_tops[0]`` 为基准定位单行高亮会整行错位（残影）。
    按"块内行顶 - 单行字形顶"定位可抵消该差异，使高亮字形与
    主文本字形严格重合。空行（无字形像素）返回 0。
    """
    alpha = canvas.render(line).to_numpy("RGBA")[:, :, 3]
    rows = np.nonzero(alpha.max(axis=1) > 0)[0]
    return int(rows[0]) if len(rows) else 0


def build_panel_highlight_clips(
    lines: list[str],
    timeline: list[dict],
    switch_time: float,
    video_duration: float,
    text_config: dict,
    font_path: str,
    cfg: dict,
    line_groups: Optional[list[tuple[int, int]]] = None,
    t_range: Optional[tuple[float, float]] = None,
) -> list[TextClip]:
    """构建左侧面板的"下一操作"高亮 clips（静态全列表 + 下一个将要执行的行高亮）

    高亮行与主文本块逐行对齐：使用相同的字体度量与 padding，每行位置
    按真实行距测量（见 _measure_line_top_offsets）并减去该行单行渲染的
    字形顶部偏移（见 _measure_single_line_glyph_top），避免等距近似随
    行数累积偏移、以及 "←" 等小字形在单行渲染中位置差异导致高亮与
    白色文本错位（残影）。

    区间语义与地图数字一致：行 i 高亮 [上一个不同 video_time, 该行
    video_time)——上一操作执行完毕后立即预告下一行，不随"当前行"语义
    在操作间长空窗；同刻行组内仅末行获得区间；末行接管
    [最后一个 video_time, 视频结束)。

    文本范围限定（core.text_fit）将主文本块换行展开后，一个操作可能
    对应多行：``line_groups`` 提供每个操作的行号切片 ``(start, end)``，
    组内所有行共享该操作的时间区间；行号超出时间线的组（被截断的
    操作）不会产生高亮。

    Args:
        lines: 面板文本行（范围限定后为拟合行，否则为 format_actions_lines 输出）
        timeline: build_action_timeline 的输出（分页时为该页对应的子时间线）
        switch_time: 进入战斗时间（分页时为该页的显示开始时间）
        video_duration: 视频总时长
        text_config: 文本叠加配置（主文本，含最终 font_size/font_scale）
        font_path: 字体绝对路径
        cfg: map_overlay 配置块
        line_groups: 每操作对应的 (start, end) 行号切片；None 时每操作一行
        t_range: 可选 (t_start, t_end) 显示区间；分页显示时传入，所有高亮
            区间裁剪到页时长内，且仅当 t_end 到达视频结束时才"末行接管"

    Returns:
        高亮 TextClip 列表（可能为空）
    """
    if line_groups is None:
        line_groups = [(i, i + 1) for i in range(len(lines))]
    if not lines or not line_groups or len(line_groups) > len(timeline):
        logger.warning("面板行数与操作数不一致 (%d vs %d)，跳过面板高亮", len(line_groups), len(timeline))
        return []

    # 时间线全落在 switch_time（所有操作均缺 video_time）：无有效高亮区间
    if all(abs(float(e["start"]) - float(switch_time)) < 1e-9 for e in timeline):
        logger.warning("操作均无有效 video_time，跳过面板高亮")
        return []

    # 区间分配（"下一个将要执行"语义）：
    #   行 i: [prev_distinct, start_i)，prev_distinct 为上一个不同的 start
    #   （首行为 switch_time）；start_i 与 prev_distinct 相同的同刻组内
    #   非首行不产生区间（组内末行代表整组）；末行接管
    #   [最后的不同 start, video_duration)（仅单页显示或末页时）。
    n = len(timeline)
    starts: list[float] = [0.0] * n
    ends: list[float] = [0.0] * n
    prev_distinct = float(switch_time)
    for i in range(n):
        s = float(timeline[i]["start"])
        if s - prev_distinct >= _MIN_INTERVAL:
            starts[i] = prev_distinct
            ends[i] = s
        if s - prev_distinct > 1e-9:
            prev_distinct = s
    if t_range is None or t_range[1] >= float(video_duration) - 1e-9:
        last_s = float(timeline[-1]["start"])
        if float(video_duration) - last_s >= _MIN_INTERVAL:
            if ends[-1] > 0:
                starts[-1] = min(starts[-1], last_s)  # 已有预告区间，无缝合并
            else:
                starts[-1] = last_s
            ends[-1] = float(video_duration)

    font_size = float(text_config.get("font_size", 25)) * float(text_config.get("font_scale", 1))
    measure_canvas = Canvas().font_family(font_path).font_size(font_size).padding(_PANEL_PADDING)
    # 每行内容真实顶部（吸收行距取整误差），失败时回退等距行高
    line_tops = _measure_line_top_offsets(lines, measure_canvas)
    single_height = measure_canvas.render("0").height
    line_height = single_height - 2 * _PANEL_PADDING  # 等距回退用的内在行高

    # 文本块锚点固定为 text_x / text_y（与 text_fit.fit_actions_lines 一致，
    # 保证高亮行与主文本严格对齐）
    text_x = float(text_config.get("text_x", 50))
    text_y = float(text_config.get("text_y", 240))

    clips: list[TextClip] = []
    # 等距回退定位所需的基准字形顶（正常路径 line_tops 有效时不使用），
    # 提到循环外只测量一次；无 groups 时 lines 为空则跳过
    single_top_0 = (
        _measure_single_line_glyph_top(lines[0], measure_canvas)
        if lines and line_tops is None else 0.0
    )
    for i, (group_start, group_end) in enumerate(line_groups):
        start = starts[i]
        end = ends[i]
        if t_range is not None:
            # 分页显示：高亮区间裁剪到当前页的显示区间内
            start = max(start, t_range[0])
            end = min(end, t_range[1])
        if end <= 0 or end - start < _MIN_INTERVAL:
            continue

        # 行定位：line_tops 为多行块内各行的内容顶部，但单行渲染时字形
        # 在行盒内的垂直位置随字形变化（"←" 等小字形顶部偏下），直接以
        # line_tops[0] 为基准定位会整行错位（残影）。按
        # "块内行顶 - 单行字形顶"（回退时以等距行盒顶近似）定位，
        # 使高亮字形与主文本字形严格重合。
        for line_idx in range(group_start, min(group_end, len(lines))):
            single_top = _measure_single_line_glyph_top(lines[line_idx], measure_canvas)
            if line_tops is not None:
                line_offset = line_tops[line_idx] - single_top
            else:
                line_offset = line_idx * line_height - single_top + single_top_0

            canvas = Canvas().font_family(font_path).font_size(font_size)
            # 不带阴影与淡入淡出：高亮行必须完全不透明地覆盖下方白色文本，
            # 阴影/半透明过渡会让白色边缘透出，形成"重影"效果。
            canvas = canvas.color(cfg.get("panel_highlight_color", "#FFD700"))
            bg_alpha = float(cfg.get("panel_highlight_bg_alpha", 0.0))
            if bg_alpha > 0:
                canvas = canvas.background_color(
                    _with_alpha(
                        cfg.get("panel_highlight_background", "#000000"),
                        bg_alpha,
                    )
                )
            canvas = canvas.padding(_PANEL_PADDING)

            clip = TextClip(lines[line_idx], start=start, duration=end - start, canvas=canvas)
            clip.set_position((text_x, text_y + line_offset))

            fade = float(cfg.get("panel_fade_duration", 0.0))
            if fade > 0:
                actual = min(fade, (end - start) / 3)
                if actual > 0:
                    clip.add_effect(FadeIn(actual))
                    clip.add_effect(FadeOut(actual))
            clips.append(clip)
    return clips


def build_map_overlay_clips(
    actions: list[dict],
    lines: list[str],
    level: Optional[dict],
    switch_time: float,
    video_duration: float,
    video_scale: float,
    video_x: float,
    video_y: float,
    video_native_size: Optional[Sequence[int]],
    map_cfg: dict,
    text_config: dict,
    font_path: str,
    line_groups: Optional[list[tuple[int, int]]] = None,
    pages: Optional[list[ActionsPage]] = None,
) -> list[TextClip]:
    """逐操作显示入口：构建地图数字 + 面板高亮的全部 clips

    level 为 None 时仅生成面板高亮（地图数字不可用时优雅降级）；
    各部分构建失败仅记录警告，不影响其余叠加。

    Args:
        line_groups: 每操作对应的 (start, end) 行号切片（范围限定后
            一个操作对应多行时使用）；None 时每操作一行
        pages: 分页显示时的页列表（core.text_fit.ActionsPage）；
            提供时面板高亮按页构建：每页使用页内文本行与子时间线，
            区间裁剪到页显示区间内；None 时按整表单页构建

    Returns:
        所有附加 clips 列表（可能为空）
    """
    clips: list[TextClip] = []
    cfg = {**DEFAULT_MAP_OVERLAY_CONFIG, **(map_cfg or {})}
    timeline = build_action_timeline(actions, switch_time, video_duration)

    if level is not None:
        try:
            clips.extend(
                build_map_number_clips(
                    timeline, level, switch_time, video_duration,
                    video_scale, video_x, video_y, video_native_size, cfg, font_path,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("地图操作序号叠加失败，仅保留面板高亮: %s", exc)

    if cfg.get("panel_highlight_enabled", True):
        try:
            if pages:
                # 分页显示：每页独立构建（文本行/子时间线/显示区间各不相同）
                for page in pages:
                    clips.extend(
                        build_panel_highlight_clips(
                            page.lines,
                            timeline[page.start:page.end],
                            page.t_start, video_duration, text_config, font_path, cfg,
                            line_groups=page.line_groups,
                            t_range=(page.t_start, page.t_end),
                        )
                    )
            else:
                clips.extend(
                    build_panel_highlight_clips(
                        lines, timeline, switch_time, video_duration, text_config, font_path, cfg,
                        line_groups=line_groups,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("左侧面板操作高亮叠加失败: %s", exc)

    return clips
