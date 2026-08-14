"""
core.text_fit - Style1 Actions 文本显示范围拟合（自动换行 + 末尾截断 + 分页切换）

将逐操作文本（format_actions_lines 输出）拟合到 text_overlay 配置的
限定范围内（``max_text_left`` / ``max_text_right`` / ``max_text_top`` /
``max_text_bottom``，画布绝对坐标）：
  1. 左/上边界生效时锚点向内收敛（文本块不得越过左/上边界），
     超宽行按字符自动换行（优先在空格处断行，CJK 友好），
     使文本块右边界不超过 ``max_text_right``；
  2. 若换行后文本块高度仍超出 ``max_text_bottom``，
     按整个操作（换行组）为单位从末尾截断，直到放得下；
  3. 截断后若每个操作均带有 video_time（识别输出的时间扩展字段），
     自动分页（page_actions_lines）：当页内最后一个操作完成
     （到达其 video_time）时切换到尚未进行的操作，避免操作被永久丢弃。

本模块仅依赖 pictex（与 create_text_clip / map_overlay 同一渲染链路），
被视频合成（core.video_compose）与 GUI 文本范围预览工具
（gui.components.tools.text_range_tool）共用，
保证合成输出与预览渲染逐字一致。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pictex import Canvas

logger = logging.getLogger(__name__)

# 与 video_compose.create_text_clip / map_overlay._PANEL_PADDING 一致的主文本内边距
PANEL_PADDING = 10


def resolve_text_anchor(
    text_x: float,
    text_y: float,
    max_text_left: float | None = None,
    max_text_top: float | None = None,
) -> tuple[float, float]:
    """计算文本块实际左上角锚点：左/上边界生效时锚点向内收敛

    文本块锚点默认即 text_x / text_y；配置了左边界且锚点在其左侧时
    锚点右移到左边界（文本不得越过左边界），配置了上边界且锚点在其
    上方时锚点下移到上边界（文本不得越过上边界）。
    预览、合成、地图面板高亮均须使用同一锚点，保证三者严格对齐。
    """
    x = float(text_x)
    y = float(text_y)
    if max_text_left is not None:
        x = max(x, float(max_text_left))
    if max_text_top is not None:
        y = max(y, float(max_text_top))
    return x, y


def _line_width(canvas: Canvas, text: str) -> int:
    """渲染单行文本的像素宽度（含两侧 padding，与最终渲染一致）"""
    return canvas.render(text).width


def _wrap_line(canvas: Canvas, line: str, max_width: int) -> list[str]:
    """将单行文本按可用宽度自动换行

    换行规则：
      - 若整行（含 padding）不超出 max_width，原样返回；
      - 否则贪心逐字符累积，超出宽度时优先回退到段内最后一个空格断行
        （保持英文单词完整），无空格（如纯 CJK）则按字符断行。
    """
    if _line_width(canvas, line) <= max_width:
        return [line]

    wrapped: list[str] = []
    seg = ""
    for ch in line:
        candidate = seg + ch
        if _line_width(canvas, candidate) <= max_width:
            seg = candidate
            continue
        # 超宽：优先在段内最后一个空格处断行，保持单词完整
        break_at = seg.rfind(" ")
        if break_at > 0:
            wrapped.append(seg[:break_at].rstrip())
            seg = (seg[break_at + 1:] + ch).lstrip()
        else:
            wrapped.append(seg)
            seg = ch
    if seg:
        wrapped.append(seg)
    return [w for w in wrapped if w]


def fit_actions_lines(
    lines: Sequence[str],
    font_path: str,
    text_cfg: dict[str, Any],
    max_text_right: float | None,
    max_text_bottom: float | None,
    text_x: float,
    text_y: float,
    padding: int = PANEL_PADDING,
    max_text_left: float | None = None,
    max_text_top: float | None = None,
) -> tuple[list[str], list[tuple[int, int]], int]:
    """将逐操作文本行拟合到限定范围内

    Args:
        lines: format_actions_lines 输出（每个操作一行）
        font_path: 字体文件绝对路径
        text_cfg: 文本叠加配置（font_size / font_scale）
        max_text_right: 文本块右边界（画布绝对 X，None/<=锚点 X 时不限宽度）
        max_text_bottom: 文本块下边界（画布绝对 Y，None/<=锚点 Y 时不限高度）
        text_x / text_y: 文本块左上角锚点（画布绝对坐标）
        padding: 单行内边距（与 create_text_clip / map_overlay._PANEL_PADDING 一致）
        max_text_left: 文本块左边界（画布绝对 X，锚点在其左侧时右移收敛，
            None/<=锚点 X 时不生效）
        max_text_top: 文本块上边界（画布绝对 Y，锚点在其上方时下移收敛，
            None/<=锚点 Y 时不生效）

    Returns:
        (fitted_lines, line_groups, dropped_count)：
        - fitted_lines: 拟合后的全部文本行（换行已展开、末尾组已截断）
        - line_groups: 每个操作对应的 ``(start, end)`` 行号切片
          （供 map_overlay 面板高亮按操作复用时间区间）
        - dropped_count: 因高度限制被截断的操作数

    文本块实际位置由 ``resolve_text_anchor`` 计算（左/上边界收敛后的锚点），
    调用方须用该锚点渲染文本，保证预览/合成/高亮三者对齐。
    """
    font_size = float(text_cfg.get("font_size", 25)) * float(text_cfg.get("font_scale", 1))
    canvas = Canvas().font_family(font_path).font_size(font_size).padding(padding)

    x_start, y_start = resolve_text_anchor(
        text_x, text_y, max_text_left, max_text_top,
    )

    available_width = None
    if max_text_right is not None and float(max_text_right) - x_start > padding * 2:
        available_width = int(float(max_text_right) - x_start)
    available_height = None
    if max_text_bottom is not None and float(max_text_bottom) - y_start > padding * 2:
        available_height = int(float(max_text_bottom) - y_start)

    # 未配置任何限制：原样返回（行为与旧版本完全一致）
    if available_width is None and available_height is None:
        groups = [(i, i + 1) for i in range(len(lines))]
        return list(lines), groups, 0

    # 1. 超宽行自动换行，同时记录每个操作的行号切片
    fitted_lines: list[str] = []
    line_groups: list[tuple[int, int]] = []
    for line in lines:
        if not line or not line.strip():
            line_groups.append((len(fitted_lines), len(fitted_lines) + 1))
            fitted_lines.append("")
            continue
        wrapped = (
            _wrap_line(canvas, line, available_width)
            if available_width is not None
            else [line]
        )
        start = len(fitted_lines)
        fitted_lines.extend(wrapped)
        line_groups.append((start, len(fitted_lines)))

    # 2. 高度限制：按操作组从末尾截断，直到文本块高度放得下
    dropped = 0
    if available_height is not None:
        block_height = canvas.render("\n".join(fitted_lines)).height
        if block_height > available_height:
            # 先按真实行距粗估批量丢弃，再逐组精确收敛（避免长列表逐行渲染）。
            # 注意：render("0").height 含两侧 padding（58px），实际每行增量约为
            # 38px——用两行块差值得出精确增量，避免粗估过度截断
            if fitted_lines:
                single_height = max(1, canvas.render("0").height)
                double_height = max(1, canvas.render("0\n0").height)
                line_increment = max(1, double_height - single_height)
                bulk = max(0, len(fitted_lines) - (available_height // line_increment))
            else:
                bulk = 0
            while bulk > 0 and len(line_groups) > 1:
                start, end = line_groups.pop()
                bulk -= (end - start)
                dropped += 1
                del fitted_lines[start:]
            while len(line_groups) > 1:
                block_height = canvas.render("\n".join(fitted_lines)).height
                if block_height <= available_height:
                    break
                start, end = line_groups.pop()
                dropped += 1
                del fitted_lines[start:]
            if dropped:
                logger.info(
                    "Actions 文本高度超出限定范围（上限 %dpx），"
                    "从末尾截断 %d 个操作",
                    available_height, dropped,
                )

    return fitted_lines, line_groups, dropped


@dataclass
class ActionsPage:
    """分页显示中的一页操作文本

    Attributes:
        start: 起始操作序号（全量操作列表索引，含）
        end: 结束操作序号（全量操作列表索引，不含）
        lines: 本页拟合后的文本行（自动换行 + 高度截断）
        line_groups: 本页内每个操作的行号切片（页内相对行号）
        t_start: 显示开始时间（秒）
        t_end: 显示结束时间（秒；末页为视频结束）
    """

    start: int
    end: int
    lines: list[str]
    line_groups: list[tuple[int, int]]
    t_start: float
    t_end: float


def page_actions_lines(
    lines: Sequence[str],
    font_path: str,
    text_cfg: dict[str, Any],
    max_text_right: float | None,
    max_text_bottom: float | None,
    text_x: float,
    text_y: float,
    video_times: Sequence[float],
    switch_time: float,
    video_duration: float,
    padding: int = PANEL_PADDING,
    max_text_left: float | None = None,
    max_text_top: float | None = None,
) -> list[ActionsPage] | None:
    """超出限定高度时的分页显示（"最后一个显示操作完成时切换"）

    仅当满足以下全部条件时返回分页列表，否则返回 None（保持单页静态显示）：
      - 配置了高度限定且整表确实发生了末尾截断（放得下无需分页）；
      - 每个操作均有有效的 video_time（切换时刻 = 页内最后一个操作的
        video_time，因此必须存在该字段才能分页）。

    分页规则：
      - 第 1 页自 switch_time 显示；后续每页自前一页末尾操作的
        video_time 开始（即"最后一个显示的 Actions 完成时切换到
        尚未进行的 Actions"），末页显示到视频结束；
      - 每页内容与 fit_actions_lines 相同（超宽换行 + 高度截断，
        左/上边界同样生效），尽可能容纳更多操作；
      - 页内操作完成时刻不晚于页起点（同刻操作、或操作时刻已超出
        视频时长）时整页无法显示，跳过这些操作继续分页；
      - 所有页均为零时长（时间无法前进）时返回 None 回退静态截断。

    Args:
        lines: format_actions_lines 输出（每个操作一行，与 video_times 对齐）
        video_times: 每个操作的 video_time（与 lines 一一对应）
        switch_time: 进入战斗时间
        video_duration: 视频总时长
        max_text_left / max_text_top: 左/上边界，与 fit_actions_lines 一致

    Returns:
        分页列表（每页含拟合行/行号切片/显示区间），无需分页时返回 None
    """
    _, y_start = resolve_text_anchor(text_x, text_y, max_text_left, max_text_top)
    # 高度限定未生效时不产生截断，无需分页
    if max_text_bottom is None or float(max_text_bottom) - y_start <= padding * 2:
        return None
    if not lines or len(video_times) != len(lines):
        return None
    if not all(isinstance(v, (int, float)) for v in video_times):
        return None

    # 整表未截断时保持单页静态显示（与旧行为一致）
    _, _, dropped = fit_actions_lines(
        lines, font_path, text_cfg,
        max_text_right, max_text_bottom, text_x, text_y, padding,
        max_text_left, max_text_top,
    )
    if dropped == 0:
        return None

    def _page_lines(
        start: int, end: int,
    ) -> tuple[list[str], list[tuple[int, int]]]:
        return fit_actions_lines(
            lines[start:end], font_path, text_cfg,
            max_text_right, max_text_bottom, text_x, text_y, padding,
            max_text_left, max_text_top,
        )[:2]

    pages: list[ActionsPage] = []
    skipped = 0
    cursor = 0
    t = float(switch_time)
    while cursor < len(lines):
        fitted, groups = _page_lines(cursor, len(lines))
        end = cursor + len(groups)
        boundary = max(
            float(switch_time),
            min(float(video_duration), float(video_times[end - 1])),
        )
        if boundary <= t + 1e-9:
            # 页时长非正：页内操作完成时刻不晚于页起点（同刻操作、
            # 或时刻已超出视频时长），整页无法显示——跳过继续分页
            if end == len(lines):
                break
            skipped += end - cursor
            cursor = end
            continue
        t_end = boundary if end < len(lines) else float(video_duration)
        pages.append(ActionsPage(cursor, end, fitted, groups, t, t_end))
        cursor = end
        t = boundary

    if skipped:
        logger.info(
            "分页显示: 跳过 %d 个完成时刻不晚于页起点的操作（同刻/超出视频时长）",
            skipped,
        )
    return pages or None
