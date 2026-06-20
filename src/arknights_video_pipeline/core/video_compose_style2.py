"""
视频合成脚本 - style2 风格

全屏视频 + 底部居中字幕模式：
  - 视频铺满整个输出画面，不使用底板图片
  - 编队信息和操作信息采用水平编排（空格分隔），区别于 style1 的竖直编排（换行分隔）
  - 编队信息在开始按钮消失前显示于底部
  - 操作信息在开始按钮消失后显示于底部
  - 操作信息超过每行字数限制时自动换行，在完整信息单元处断行
  - 字幕通过渲染 Canvas 获取实际像素宽度，手动计算居中位置

风格配置文件位于 config/video_compose/ 目录下。
"""

import logging
import os
import re
import unicodedata

from movielite import VideoClip, TextClip, VideoWriter
from movielite.vfx import FadeIn, FadeOut
from pictex import Canvas, Shadow

from arknights_video_pipeline.core.utils import (
    PROJECT_ROOT, load_config, save_default_config,
    resolve_font_path, load_formation_text, load_actions_text, get_switch_time,
)
from arknights_video_pipeline.core.video_compose_common import (
    logger,
    resolve_video_source,
    load_text_overlay_inputs,
    prepare_output_path,
    parse_video_quality,
    run_writer,
)

# style2 风格默认配置
DEFAULT_CONFIG = {
    "output_width": 1920,
    "output_height": 1080,
    "video_quality": "middle",
    "text_overlay": {
        "enabled": True,
        "font": "SOURCEHANSANSCN-HEAVY.OTF",
        "font_dir": "resource/font",
        "font_size": 75,
        "font_scale": 1,
        "fade_duration": 0.5,
        "shadow_enabled": True,
        "shadow_offset_x": 2,
        "shadow_offset_y": 2,
        "shadow_blur": 4,
        "shadow_color": "#000000",
        "text_color": "#FFFFFF",
        "max_chars_per_line": 20,
        "line_height": 1.5,
        "bottom_margin": 60,
    },
}


def text_to_horizontal(text):
    """将竖直编排的文本转换为水平编排

    style2 使用水平编排：将每行内容用空格连接成一行。
    与 style1 的竖直编排（每行一条信息）不同，style2 将所有信息排列在同一行。

    例如：
      竖直编排（style1）:     水平编排（style2）:
        1.米格鲁              1.米格鲁 2.遥 3.黑角
        2.遥
        3.黑角

    Args:
        text: 竖直编排的文本（换行符分隔）

    Returns:
        水平编排的文本（空格分隔）
    """
    if not text:
        return text
    # 将换行符替换为空格，合并连续空格
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return " ".join(lines)


def display_width(text):
    """计算文本的显示宽度

    中日韩（CJK）字符占2个宽度单位，其余字符占1个宽度单位。
    因此 max_chars_per_line=20 表示每行最多容纳20个汉字的宽度（40单位）。
    """
    width = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ('W', 'F'):
            width += 2
        else:
            width += 1
    return width


def wrap_text_by_units(text, max_chars):
    """按完整信息单元对文本进行自动换行

    换行规则：
      1. 以换行符为自然分段
      2. 在每个分段内，按 "序号.内容" 的信息单元进行拆分
      3. 逐个追加信息单元，当追加后超过宽度限制时在当前单元前换行
      4. 若单个信息单元本身就超过宽度限制，则在该单元内按空格处断行

    宽度计算：CJK字符占2单位，其余占1单位。max_chars 表示汉字个数，
    实际宽度上限为 max_chars * 2。

    Args:
        text: 原始文本
        max_chars: 每行最大汉字个数（显示宽度上限 = max_chars * 2）

    Returns:
        换行处理后的文本
    """
    if not text:
        return text

    max_width = max_chars * 2

    paragraphs = text.split("\n")
    result_paragraphs = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # 尝试按信息单元拆分：匹配 "数字." 开头的单元
        # 例如 "1.部署干员1 2.部署干员2" -> ["1.部署干员1", "2.部署干员2"]
        # 使用 (?:^|\s)(?=\d+\.) 仅在段落开头或空白后匹配数字序号，
        # 避免误匹配 "部署1.撤退" 这类数字不在序号位置的文本
        units = re.split(r'(?:^|\s)(?=\d+\.)', para)
        units = [u.strip() for u in units if u.strip()]

        # 如果没有匹配到序号模式，按空格拆分为单元
        if len(units) <= 1:
            units = para.split(" ")
            units = [u for u in units if u]

        lines = []
        current_line = ""

        for unit in units:
            # 计算追加后的显示宽度（含空格分隔符）
            candidate = f"{current_line} {unit}".strip() if current_line else unit

            if display_width(candidate) <= max_width:
                current_line = candidate
            else:
                # 当前行已有内容，先保存
                if current_line:
                    lines.append(current_line)
                # 检查单个单元是否超长
                if display_width(unit) > max_width:
                    # 在单元内按空格进一步拆分
                    sub_parts = unit.split(" ")
                    sub_line = ""
                    for part in sub_parts:
                        sub_candidate = f"{sub_line} {part}".strip() if sub_line else part
                        if display_width(sub_candidate) <= max_width:
                            sub_line = sub_candidate
                        else:
                            if sub_line:
                                lines.append(sub_line)
                            sub_line = part
                    current_line = sub_line
                else:
                    current_line = unit

        if current_line:
            lines.append(current_line)

        result_paragraphs.extend(lines)

    return "\n".join(result_paragraphs)


def create_subtitle_clip(text, start, duration, text_config, project_root, output_width, output_height):
    """创建底部居中字幕 TextClip

    居中实现方式：不设置 Canvas 宽度，让 Canvas 自适应文本实际大小，
    然后通过 canvas.render() 获取实际像素宽度，手动计算 x 坐标实现水平居中。

    Args:
        text: 文本内容（可含换行符）
        start: 开始时间(秒)
        duration: 持续时间(秒)
        text_config: 文本叠加配置
        project_root: 项目根目录
        output_width: 输出视频宽度
        output_height: 输出视频高度

    Returns:
        TextClip 实例
    """
    font_path = resolve_font_path(
        text_config.get("font", "SOURCEHANSANSCN-HEAVY.OTF"),
        os.path.join(project_root, text_config.get("font_dir", "resource/font"))
    )

    font_size = text_config.get("font_size", 75)
    font_scale = text_config.get("font_scale", 1)
    effective_size = font_size * font_scale
    fade_duration = text_config.get("fade_duration", 0.5)
    text_color = text_config.get("text_color", "#FFFFFF")
    bottom_margin = text_config.get("bottom_margin", 60)
    line_height = text_config.get("line_height", 1.5)

    # 构建 pictex Canvas
    # 不设置 width，让 Canvas 大小等于文本实际大小
    # 通过 set_position 手动计算居中位置
    canvas = (
        Canvas()
        .font_family(font_path)
        .font_size(effective_size)
        .color(text_color)
    )

    # 阴影效果
    if text_config.get("shadow_enabled", True):
        shadow = Shadow(
            color=text_config.get("shadow_color", "#000000"),
            offset=(text_config.get("shadow_offset_x", 2), text_config.get("shadow_offset_y", 2)),
            blur_radius=text_config.get("shadow_blur", 4),
        )
        canvas = canvas.text_shadows(shadow)

    canvas = (
        canvas
        .background_color("transparent")
        .padding(10)
        .line_height(line_height)
    )

    # 创建 TextClip
    clip = TextClip(text, start=start, duration=duration, canvas=canvas)

    # 手动计算水平居中位置
    # 先渲染 Canvas 获取实际像素宽度和高度
    rendered = canvas.render(text)
    clip_width = rendered.width
    clip_height = rendered.height
    x_pos = max(0, (output_width - clip_width) // 2)
    clip.set_position((x_pos, output_height - bottom_margin - clip_height))

    # 淡入淡出效果
    if fade_duration > 0:
        actual_fade_in = min(fade_duration, duration / 2)
        actual_fade_out = min(fade_duration, duration / 2)
        clip.add_effect(FadeIn(actual_fade_in))
        clip.add_effect(FadeOut(actual_fade_out))

    return clip


def compose_video(config):
    """根据 style2 配置合成视频：全屏视频 + 底部字幕"""
    output_size = (config["output_width"], config["output_height"])

    # 解析视频源路径
    video_source = resolve_video_source(config.get("video_source"))

    # 加载视频素材
    logger.info(f"加载视频素材: {video_source}")
    video = VideoClip(video_source, start=0)

    # 全屏铺满：设置视频尺寸等于输出尺寸
    logger.info(f"设置视频全屏铺满: {output_size[0]}x{output_size[1]}")
    video.set_size(width=output_size[0], height=output_size[1])

    # 收集所有 clip
    clips = [video]

    # 计算视频文件名信息
    video_basename = os.path.splitext(os.path.basename(video_source))[0]

    # 文本叠加
    text_config = config.get("text_overlay", {})
    if text_config.get("enabled", True):
        logger.info("--- 底部字幕叠加 (style2) ---")

        inputs = load_text_overlay_inputs(text_config, video_basename)
        input_json = inputs["input_json"]
        track_result = inputs["track_result"]
        formation_config = inputs["formation_config"]
        actions_config = inputs["actions_config"]

        # 获取切换时间点
        switch_time = get_switch_time(track_result)
        video_duration = video.duration
        logger.info(f"  编队字幕显示: 0s -> {switch_time:.2f}s")
        logger.info(f"  操作字幕显示: {switch_time:.2f}s -> {video_duration:.2f}s")

        max_chars = text_config.get("max_chars_per_line", 20)

        # 生成编队文本（水平编排）
        formation_text = load_formation_text(input_json, formation_config)
        if formation_text:
            # style2: 将竖直编排转为水平编排
            formation_text = text_to_horizontal(formation_text)
            formation_duration = switch_time
            if formation_duration > 0:
                formation_clip = create_subtitle_clip(
                    formation_text, 0, formation_duration, text_config, PROJECT_ROOT, output_size[0], output_size[1]
                )
                clips.append(formation_clip)
                logger.info(f"  编队字幕已加载 ({len(formation_text)}字符)")
        else:
            logger.info("  编队文本为空，跳过")

        # 生成操作文本（水平编排）并自动换行
        actions_text = load_actions_text(input_json, actions_config)
        if actions_text:
            # style2: 将竖直编排转为水平编排
            actions_text = text_to_horizontal(actions_text)
            # 对操作文本进行自动换行处理
            wrapped_text = wrap_text_by_units(actions_text, max_chars)
            actions_duration = video_duration - switch_time
            if actions_duration > 0:
                actions_clip = create_subtitle_clip(
                    wrapped_text, switch_time, actions_duration, text_config, PROJECT_ROOT, output_size[0], output_size[1]
                )
                clips.append(actions_clip)
                logger.info(f"  操作字幕已加载 ({len(actions_text)}字符, 换行后 {len(wrapped_text)}字符)")
        else:
            logger.info("  操作文本为空，跳过")

        logger.info("--- 字幕叠加配置完成 ---")
    else:
        logger.info("底部字幕叠加已禁用")

    # 构建输出路径（支持用户配置的 output_dir，由 pipeline 注入）
    _, output_path = prepare_output_path(video_basename, config)

    # 解析视频质量
    quality_str = config.get("video_quality", "middle")
    video_quality = parse_video_quality(quality_str)
    logger.info(f"视频质量预设: {quality_str}")

    # 创建输出
    logger.info(f"输出分辨率: {output_size[0]}x{output_size[1]}")
    logger.info(f"输出文件: {output_path}")
    writer = VideoWriter(
        output_path,
        fps=video.fps,
        size=output_size,
        duration=video.duration
    )
    writer.add_clips(clips)
    run_writer(writer, video_quality, video)
    logger.info("视频合成完成!")


def main():
    """独立运行视频合成（style2 风格）"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    config_path = os.path.join(PROJECT_ROOT, "config", "video_compose", "style2.json")

    if not os.path.exists(config_path):
        save_default_config(config_path, DEFAULT_CONFIG)
        logger.info(f"已生成默认配置文件: {config_path}")

    config = load_config(config_path, DEFAULT_CONFIG, deep_merge_keys=["text_overlay"])
    compose_video(config)


if __name__ == "__main__":
    main()
