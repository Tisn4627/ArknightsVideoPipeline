"""
视频合成脚本 - style1 风格

使用movielite库将视频叠加到底板图片上
支持动态文本叠加：编队内容 + 操作内容，带淡入淡出效果
支持字幕自适应：根据视频尺寸自动计算最大字体大小

当前为 style1 风格配置，即默认的视频合成模式。
风格配置文件位于 config/video_compose/ 目录下，每个风格对应一个 JSON 文件。
"""

import logging
import os

from movielite import VideoClip, ImageClip, TextClip, VideoWriter
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

# style1 风格默认配置（video_source/background_image/output_dir 由流水线运行时注入）
DEFAULT_CONFIG = {
    "output_width": 1920,
    "output_height": 1080,
    "video_scale": 0.8,
    "video_x": 320,
    "video_y": 72,
    "video_quality": "middle",
    "text_overlay": {
        "enabled": True,
        "font": "SOURCEHANSANSCN-HEAVY.OTF",
        "font_dir": "resource/font",
        "font_size": 45,
        "font_scale": 1,
        "text_x": 0,
        "text_y": 65,
        "fade_duration": 0.5,
        "shadow_enabled": True,
        "shadow_offset_x": 2,
        "shadow_offset_y": 2,
        "shadow_blur": 4,
        "shadow_color": "#000000",
        "text_color": "#FFFFFF",
        "subtitle_auto_fit": False,
        "auto_fit_min_font_size": 10,
        "auto_fit_max_font_size": 200,
        "auto_fit_available_width": None,
    }
}


def compute_auto_fit_font_size(texts, font_path, available_width, text_config, available_height=None):
    """计算字幕自适应字体大小

    使用二分查找算法，在可用宽度和高度内找到最大字体大小，
    使所有文本行均不超出可用区域。编队文本和操作文本
    使用统一的字体大小（取两者中需要更小字体的值）。

    算法流程：
      1. 设定字体大小搜索范围 [min_size, max_size]
      2. 对每个候选字体大小，渲染所有文本行获取实际像素宽度
      3. 同时检查完整多行文本的渲染高度是否超出可用高度
      4. 若所有文本行宽度均 <= 可用宽度且高度未超出，尝试更大的字体
      5. 若任一文本行超出可用宽度或高度超出，尝试更小的字体
      6. 返回满足条件的最大字体大小

    Args:
        texts: 需要适配的文本列表（如 [编队文本, 操作文本]）
        font_path: 字体文件绝对路径
        available_width: 可用像素宽度
        text_config: 文本叠加配置
        available_height: 可用像素高度（None 时不检查高度）

    Returns:
        自适应后的字体大小（像素）
    """
    min_size = text_config.get("auto_fit_min_font_size", 10)
    max_size = text_config.get("auto_fit_max_font_size", 200)

    # 收集所有文本的各行（多行文本需逐行检查宽度）
    all_lines = []
    for text in texts:
        if text:
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    all_lines.append(line)

    if not all_lines:
        return text_config.get("font_size", 45)

    # 预构建 Canvas 模板，二分查找中仅复用 font_size 变化（L5 优化：避免重复创建）
    # 注意：pictex Canvas 是链式 API，font_size() 返回新实例，
    # 因此无法完全避免创建，但提取基础配置减少重复工作
    base_canvas_kwargs = {
        "font_family": font_path,
        "background_color": "transparent",
        "padding": 10,
    }

    # 二分查找最大字体大小
    lo, hi = min_size, max_size
    best_size = min_size

    while lo <= hi:
        mid = (lo + hi) // 2

        canvas = (
            Canvas()
            .font_family(base_canvas_kwargs["font_family"])
            .font_size(mid)
            .background_color(base_canvas_kwargs["background_color"])
            .padding(base_canvas_kwargs["padding"])
        )

        fits = True
        for line in all_lines:
            rendered = canvas.render(line)
            if rendered.width > available_width:
                fits = False
                break

        # 检查完整多行文本的渲染高度是否超出可用高度
        if fits and available_height is not None:
            for text in texts:
                if text and text.strip():
                    full_rendered = canvas.render(text)
                    if full_rendered.height > available_height:
                        fits = False
                        break

        if fits:
            best_size = mid
            lo = mid + 1
        else:
            hi = mid - 1

    return best_size


def create_text_clip(text, start, duration, text_config, project_root):
    """
    创建带阴影和淡入淡出效果的TextClip

    Args:
        text: 文本内容
        start: 开始时间(秒)
        duration: 持续时间(秒)
        text_config: 文本叠加配置
        project_root: 项目根目录

    Returns:
        TextClip实例
    """
    font_path = resolve_font_path(
        text_config.get("font", "SOURCEHANSANSCN-HEAVY.OTF"),
        os.path.join(project_root, text_config.get("font_dir", "resource/font"))
    )

    font_size = text_config.get("font_size", 45)
    font_scale = text_config.get("font_scale", 1)
    effective_size = font_size * font_scale
    fade_duration = text_config.get("fade_duration", 0.5)
    text_color = text_config.get("text_color", "#FFFFFF")

    # 构建pictex Canvas
    canvas = Canvas().font_family(font_path).font_size(effective_size).color(text_color)

    # 阴影效果
    if text_config.get("shadow_enabled", True):
        shadow = Shadow(
            color=text_config.get("shadow_color", "#000000"),
            offset=(text_config.get("shadow_offset_x", 2), text_config.get("shadow_offset_y", 2)),
            blur_radius=text_config.get("shadow_blur", 4),
        )
        canvas = canvas.text_shadows(shadow)

    canvas = canvas.background_color("transparent").padding(10)

    # 创建TextClip
    clip = TextClip(text, start=start, duration=duration, canvas=canvas)

    # 设置位置（默认值与 DEFAULT_CONFIG 中的 text_x=0、text_y=65 保持一致）
    text_x = text_config.get("text_x", 0)
    text_y = text_config.get("text_y", 65)
    clip.set_position((text_x, text_y))

    # 淡入淡出效果
    if fade_duration > 0:
        actual_fade_in = min(fade_duration, duration / 2)
        actual_fade_out = min(fade_duration, duration / 2)
        clip.add_effect(FadeIn(actual_fade_in))
        clip.add_effect(FadeOut(actual_fade_out))

    return clip


def compose_video(config):
    """根据配置合成视频"""
    output_size = (config["output_width"], config["output_height"])

    # 解析相对路径为基于项目根目录的绝对路径
    # background_image 和 video_source 由流水线运行时注入，
    # 独立运行时需在配置文件中指定
    background_image = config.get("background_image")
    if not background_image:
        raise ValueError(
            "缺少 background_image 配置项。"
            "请通过流水线运行（python main.py video.mp4 -b bg.png），"
            "或在配置文件中指定 background_image"
        )
    if not os.path.isabs(background_image):
        background_image = os.path.join(PROJECT_ROOT, background_image)

    video_source = resolve_video_source(config.get("video_source"))

    # 加载视频素材（先加载视频以获取 duration，再据此设置背景板时长，
    # 避免 ImageClip 先以 duration=0 构造后依赖 set_duration 动态修改的风险）
    logger.info(f"加载视频素材: {video_source}")
    video = VideoClip(video_source, start=0)

    if not video.duration or video.duration <= 0:
        raise ValueError(
            f"无法获取视频时长 (video.duration={video.duration})，"
            f"视频可能已损坏或 movielite 未能正确加载"
        )

    # 设置视频缩放比例
    logger.info(f"设置视频缩放比例: {config['video_scale']}")
    video.set_scale(config["video_scale"])

    # 设置视频位置
    logger.info(f"设置视频位置: X={config['video_x']}, Y={config['video_y']}")
    video.set_position((config["video_x"], config["video_y"]))

    # 加载底板图片（在获取视频时长后构造，直接传入正确 duration）
    logger.info(f"加载底板图片: {background_image}")
    background = ImageClip(
        background_image,
        start=0,
        duration=video.duration,
    )
    background.set_size(width=output_size[0], height=output_size[1])

    # 收集所有clip
    clips = [background, video]

    # 计算视频文件名信息
    video_basename = os.path.splitext(os.path.basename(video_source))[0]

    # 文本叠加
    text_config = config.get("text_overlay", {})
    if text_config.get("enabled", True):
        logger.info("--- 动态文本叠加 ---")

        inputs = load_text_overlay_inputs(text_config, video_basename)
        input_json = inputs["input_json"]
        track_result = inputs["track_result"]
        formation_config = inputs["formation_config"]
        actions_config = inputs["actions_config"]

        # 获取切换时间点
        switch_time = get_switch_time(track_result)
        video_duration = video.duration
        logger.info(f"  编队文本显示: 0s -> {switch_time:.2f}s")
        logger.info(f"  操作文本显示: {switch_time:.2f}s -> {video_duration:.2f}s")

        # 生成编队文本和操作文本
        formation_text = load_formation_text(input_json, formation_config)
        actions_text = load_actions_text(input_json, actions_config)

        # 字幕自适应：根据视频尺寸自动计算最大字体大小
        if text_config.get("subtitle_auto_fit", False):
            font_path = resolve_font_path(
                text_config.get("font", "SOURCEHANSANSCN-HEAVY.OTF"),
                os.path.join(PROJECT_ROOT, text_config.get("font_dir", "resource/font"))
            )

            # 计算字幕可用宽度
            available_width = text_config.get("auto_fit_available_width")
            if available_width is None:
                # 自动计算：根据视频区域和字幕位置推断可用宽度
                video_width = int(output_size[0] * config["video_scale"])
                text_x = text_config.get("text_x", 0)

                if text_x < config["video_x"]:
                    # 字幕在视频左侧区域
                    available_width = config["video_x"]
                elif text_x >= config["video_x"] + video_width:
                    # 字幕在视频右侧区域
                    available_width = output_size[0] - text_x
                else:
                    # 字幕与视频区域重叠，使用视频左侧或右侧中较大的区域
                    left_area = config["video_x"]
                    right_area = output_size[0] - config["video_x"] - video_width
                    available_width = max(left_area, right_area)

                # 限制可用宽度不超过输出宽度的 40%
                available_width = min(available_width, int(output_size[0] * 0.4))

            # 计算可用高度：底板高度减去视频区域高度
            video_height = int(output_size[1] * config["video_scale"])
            available_height = output_size[1] - config["video_y"] - video_height

            auto_font_size = compute_auto_fit_font_size(
                [formation_text, actions_text],
                font_path,
                available_width,
                text_config,
                available_height=available_height,
            )
            logger.info(
                f"  字幕自适应: 可用宽度={available_width}px, "
                f"可用高度={available_height}px, 计算字体大小={auto_font_size}"
            )

            # 覆盖 font_size 配置，font_scale 保持为 1
            text_config["font_size"] = auto_font_size
            text_config["font_scale"] = 1

        # 生成编队文本
        if formation_text:
            formation_duration = switch_time
            if formation_duration > 0:
                formation_clip = create_text_clip(
                    formation_text, 0, formation_duration, text_config, PROJECT_ROOT
                )
                clips.append(formation_clip)
                logger.info(f"  编队文本已加载 ({len(formation_text)}字符)")
        else:
            logger.info("  编队文本为空，跳过")

        # 生成操作文本
        if actions_text:
            actions_duration = video_duration - switch_time
            if actions_duration > 0:
                actions_clip = create_text_clip(
                    actions_text, switch_time, actions_duration, text_config, PROJECT_ROOT
                )
                clips.append(actions_clip)
                logger.info(f"  操作文本已加载 ({len(actions_text)}字符)")
        else:
            logger.info("  操作文本为空，跳过")

        logger.info("--- 文本叠加配置完成 ---")
    else:
        logger.info("动态文本叠加已禁用")

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
    run_writer(writer, video_quality, background, video)
    logger.info("视频合成完成!")


def main():
    """独立运行视频合成（style1 风格）"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    config_path = os.path.join(PROJECT_ROOT, "config", "video_compose", "style1.json")

    if not os.path.exists(config_path):
        save_default_config(config_path, DEFAULT_CONFIG)
        logger.info(f"已生成默认配置文件: {config_path}")

    config = load_config(config_path, DEFAULT_CONFIG, deep_merge_keys=["text_overlay"])
    compose_video(config)


if __name__ == "__main__":
    main()
