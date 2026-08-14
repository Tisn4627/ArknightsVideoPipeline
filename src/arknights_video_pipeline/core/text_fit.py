"""
core.text_fit - Style1 Actions 文本显示范围拟合（自动换行 + 末尾截断）

将逐操作文本（format_actions_lines 输出）拟合到 text_overlay 配置的
限定范围内（``max_text_right`` / ``max_text_bottom``，画布绝对坐标）：
  1. 超宽行按字符自动换行（优先在空格处断行，CJK 友好），
     使文本块右边界不超过 ``max_text_right``；
  2. 若换行后文本块高度仍超出 ``max_text_bottom``，
     按整个操作（换行组）为单位从末尾截断，直到放得下。

本模块仅依赖 pictex（与 create_text_clip / map_overlay 同一渲染链路），
被视频合成（core.video_compose）与 GUI 文本范围预览工具
（gui.components.tools.text_range_tool）共用，
保证合成输出与预览渲染逐字一致。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from pictex import Canvas

logger = logging.getLogger(__name__)

# 与 video_compose.create_text_clip / map_overlay._PANEL_PADDING 一致的主文本内边距
PANEL_PADDING = 10


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
) -> tuple[list[str], list[tuple[int, int]], int]:
    """将逐操作文本行拟合到限定范围内

    Args:
        lines: format_actions_lines 输出（每个操作一行）
        font_path: 字体文件绝对路径
        text_cfg: 文本叠加配置（font_size / font_scale）
        max_text_right: 文本块右边界（画布绝对 X，None/<=text_x 时不限宽度）
        max_text_bottom: 文本块下边界（画布绝对 Y，None/<=text_y 时不限高度）
        text_x / text_y: 文本块左上角锚点（画布绝对坐标）
        padding: 单行内边距（与 create_text_clip / map_overlay._PANEL_PADDING 一致）

    Returns:
        (fitted_lines, line_groups, dropped_count)：
        - fitted_lines: 拟合后的全部文本行（换行已展开、末尾组已截断）
        - line_groups: 每个操作对应的 ``(start, end)`` 行号切片
          （供 map_overlay 面板高亮按操作复用时间区间）
        - dropped_count: 因高度限制被截断的操作数
    """
    font_size = float(text_cfg.get("font_size", 25)) * float(text_cfg.get("font_scale", 1))
    canvas = Canvas().font_family(font_path).font_size(font_size).padding(padding)

    available_width = None
    if max_text_right is not None and float(max_text_right) - float(text_x) > padding * 2:
        available_width = int(float(max_text_right) - float(text_x))
    available_height = None
    if max_text_bottom is not None and float(max_text_bottom) - float(text_y) > padding * 2:
        available_height = int(float(max_text_bottom) - float(text_y))

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
            # 先按单行高度粗估批量丢弃，再逐组精确收敛（避免长列表逐行渲染）
            if fitted_lines:
                single_height = max(1, canvas.render("0").height)
                bulk = max(0, len(fitted_lines) - (available_height // single_height))
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
