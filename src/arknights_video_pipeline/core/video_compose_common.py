"""视频合成公共工具模块

提取 style1 / style2 共享的逻辑，避免重复代码（M11）：
  - QUALITY_MAP：视频质量枚举映射
  - resolve_video_source：解析视频源路径
  - load_text_overlay_inputs：解析文本叠加所需输入文件路径
  - prepare_output_path：构建输出目录与文件路径（支持用户配置的 output_dir，修复 M7）
  - parse_video_quality：解析视频质量字符串为 VideoQuality 枚举
  - run_writer：执行 VideoWriter.write 并在 finally 中释放 clip 资源

同时统一使用 logger 替代 print（M4），便于 GUI / 服务层捕获日志。
"""

import logging
import os

from movielite import VideoQuality

from arknights_video_pipeline.core.utils import PROJECT_ROOT

logger = logging.getLogger(__name__)

# video_quality 可选值与 VideoQuality 枚举的映射
QUALITY_MAP = {
    "low": VideoQuality.LOW,
    "middle": VideoQuality.MIDDLE,
    "high": VideoQuality.HIGH,
    "very_high": VideoQuality.VERY_HIGH,
}


def resolve_video_source(video_source, project_root=PROJECT_ROOT):
    """解析视频源路径：相对路径基于项目根目录，绝对路径直接使用

    Args:
        video_source: 配置中的视频源路径
        project_root: 项目根目录，默认为 PROJECT_ROOT

    Returns:
        视频源的绝对路径

    Raises:
        ValueError: video_source 为空
    """
    if not video_source:
        raise ValueError(
            "缺少 video_source 配置项。"
            "请通过流水线运行（python main.py video.mp4），"
            "或在配置文件中指定 video_source"
        )
    if not os.path.isabs(video_source):
        video_source = os.path.join(project_root, video_source)
    return video_source


def load_text_overlay_inputs(text_config, video_basename, project_root=PROJECT_ROOT):
    """解析文本叠加所需的输入文件路径

    Args:
        text_config: 文本叠加配置 dict
        video_basename: 视频文件名（不含扩展名），用于定位 track_result
        project_root: 项目根目录

    Returns:
        包含 input_json / track_result / formation_config / actions_config 的 dict
    """
    # track_result 由流水线写入 self.output_dir（可能为用户自定义目录），
    # 优先使用 text_config 中注入的 output_dir，避免硬编码默认路径（修复 track_result 路径不一致）
    output_dir = text_config.get("output_dir")
    if output_dir and os.path.isabs(output_dir):
        track_result_dir = output_dir
    else:
        track_result_dir = os.path.join(project_root, "output", video_basename)

    return {
        "input_json": os.path.join(
            project_root, text_config.get("input_json", "input.json")
        ),
        "track_result": os.path.join(
            track_result_dir,
            f"track_result_{video_basename}.json",
        ),
        "formation_config": os.path.join(
            project_root, text_config.get("formation", "config/formation.json")
        ),
        "actions_config": os.path.join(
            project_root, text_config.get("actions", "config/actions.json")
        ),
    }


def prepare_output_path(video_basename, config, project_root=PROJECT_ROOT):
    """构建输出目录与输出文件路径

    优先使用配置中的 output_dir（由 pipeline 注入，支持用户自定义 output_dir 配置项，修复 M7）；
    若未注入则回退到 PROJECT_ROOT/output/video_basename 以保持向后兼容。

    Args:
        video_basename: 视频文件名（不含扩展名）
        config: 合成配置 dict
        project_root: 项目根目录

    Returns:
        (output_dir, output_path) 元组

    Raises:
        RuntimeError: 创建输出目录失败
    """
    output_dir = config.get("output_dir")
    if not output_dir:
        output_dir = os.path.join(project_root, "output", video_basename)
    elif not os.path.isabs(output_dir):
        output_dir = os.path.join(project_root, output_dir)

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"无法创建输出目录 {output_dir}: {e}") from e

    output_path = os.path.join(output_dir, f"output_{video_basename}.mp4")
    return output_dir, output_path


def parse_video_quality(quality_str):
    """解析视频质量字符串为 VideoQuality 枚举

    Args:
        quality_str: 视频质量字符串（low/middle/high/very_high），大小写不敏感

    Returns:
        对应的 VideoQuality 枚举值，未知值回退为 MIDDLE
    """
    quality_str = (quality_str or "middle").lower()
    return QUALITY_MAP.get(quality_str, VideoQuality.MIDDLE)


def run_writer(writer, video_quality, *clips_to_close):
    """执行 VideoWriter.write 并在 finally 中释放 clip 资源

    统一处理 writer.write 的资源释放（M5），避免异常时泄漏。

    Args:
        writer: 已添加 clips 的 VideoWriter 实例
        video_quality: VideoQuality 枚举值
        *clips_to_close: 需要在 finally 中关闭的 clip 实例（如 background / video）
    """
    try:
        writer.write(video_quality=video_quality)
    finally:
        for clip in clips_to_close:
            try:
                clip.close()
            except Exception as close_exc:  # noqa: BLE001
                logger.warning(f"关闭 clip 资源失败: {close_exc}")
