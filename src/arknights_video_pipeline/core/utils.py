"""
core.utils - 共享工具函数

提供路径解析、文件验证、I/O 操作、配置加载和格式化等通用功能。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from typing import Any

from arknights_video_pipeline.core.exceptions import ImageValidationError, VideoValidationError


# ── 模块级 logger ──────────────────────────────────────────

logger = logging.getLogger(__name__)


# ── PATH 修复（Windows）────────────────────────────────────


def ensure_ffmpeg_in_path() -> None:
    """确保 ffmpeg/ffprobe 在 PATH 中（Windows 注册表回退）

    若 shutil.which 找不到 ffmpeg 或 ffprobe，则尝试从 Windows 注册表
    重建 PATH 环境变量。非 Windows 环境或注册表读取失败时静默跳过。
    """
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    machine_path = os.environ.get("PATH", "")
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ) as key:
            sys_path = winreg.QueryValueEx(key, "Path")[0]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            user_path = winreg.QueryValueEx(key, "Path")[0]
        os.environ["PATH"] = sys_path + ";" + user_path + ";" + machine_path
    except Exception:
        pass


# ── 项目根目录 ────────────────────────────────────────────

def _find_project_root() -> str:
    """动态查找项目根目录

    优先向上查找 pyproject.toml（更鲁棒，对目录结构变化不敏感）；
    若未找到则回退到基于 __file__ 的固定层级推导。
    """
    # 基于当前文件向上查找 pyproject.toml
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):  # 最多向上查找 6 层，避免无限循环
        if os.path.exists(os.path.join(current, "pyproject.toml")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    # 回退：固定层级推导（utils.py -> core -> arknights_video_pipeline -> src -> 项目根）
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


PROJECT_ROOT: str = _find_project_root()
"""项目根目录的绝对路径，所有相对路径应基于此解析"""


# ── 路径与目录 ────────────────────────────────────────────


def resolve_path(base_dir: str, path: str) -> str:
    """将相对路径解析为基于 base_dir 的绝对路径"""
    if not path or not path.strip():
        return ""
    if os.path.isabs(path):
        return path
    return os.path.join(base_dir, path)


def ensure_dir(path: str) -> str:
    """确保目录存在，返回传入的路径"""
    os.makedirs(path, exist_ok=True)
    return path


def resolve_project_path(path: str) -> str:
    """将相对路径解析为基于 PROJECT_ROOT 的绝对路径

    如果 path 已经是绝对路径，则原样返回。
    空字符串原样返回，不拼接。
    """
    if not path or not path.strip():
        return path
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


# ── 共享配置加载 ──────────────────────────────────────────


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归深度合并字典，override 中的值覆盖 base"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def load_config(
    config_path: str,
    default_config: dict[str, Any],
    deep_merge_keys: list[str] | None = None,
) -> dict[str, Any]:
    """加载配置文件并与默认配置合并

    Args:
        config_path: 配置文件路径
        default_config: 默认配置字典
        deep_merge_keys: 需要深度合并的键列表（如 "text_overlay"），
                         其余键使用浅合并

    Returns:
        合并后的配置字典

    Note:
        本函数不会修改传入的 default_config 和 user_config 字典，
        深度合并在新对象上进行。
    """
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        config = deepcopy(default_config)
        # 先深度合并指定键，再浅合并剩余键（不修改 user_config）
        deep_merged_keys: set[str] = set()
        if deep_merge_keys:
            for key in deep_merge_keys:
                if key in user_config and key in config:
                    if isinstance(config[key], dict) and isinstance(
                        user_config[key], dict
                    ):
                        config[key] = _deep_merge_dict(config[key], user_config[key])
                        deep_merged_keys.add(key)
        # 浅合并剩余键（跳过已深度合并的键，避免覆盖深度合并结果）
        for key, value in user_config.items():
            if key not in deep_merged_keys:
                config[key] = value
    else:
        config = deepcopy(default_config)
    return config


def save_default_config(config_path: str, default_config: dict[str, Any]) -> None:
    """保存默认配置文件，自动创建父目录"""
    dir_path = os.path.dirname(config_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(default_config, f, indent=4, ensure_ascii=False)


# ── 支持的文件格式 ────────────────────────────────────────

SUPPORTED_VIDEO_EXTENSIONS: set[str] = {".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv"}
"""支持的视频文件扩展名"""

SUPPORTED_IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
"""支持的图片文件扩展名"""


# ── 视频验证 ──────────────────────────────────────────────


def _run_ffprobe(video_path: str, timeout: int = 60) -> dict[str, Any]:
    """运行 ffprobe 并返回解析后的 JSON（公共实现，修复 L8）

    Args:
        video_path: 视频文件路径
        timeout: ffprobe 执行超时时间（秒）

    Returns:
        ffprobe 输出的 JSON dict

    Raises:
        VideoValidationError: ffprobe 不可用、超时、返回非零、输出无法解析
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", video_path,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise VideoValidationError(f"无法解析视频文件: {video_path}")
        return json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise VideoValidationError(
            "ffprobe未找到，请确保ffmpeg已安装并在PATH中"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoValidationError("ffprobe执行超时") from exc
    except json.JSONDecodeError as exc:
        raise VideoValidationError(
            f"无法解析ffprobe输出: {video_path}"
        ) from exc


def _extract_video_stream(probe: dict, video_path: str) -> dict:
    """从 ffprobe 输出中提取第一个视频流（公共实现，修复 L8）

    Args:
        probe: ffprobe 输出的 JSON dict
        video_path: 视频文件路径（仅用于错误消息）

    Returns:
        第一个视频流 dict

    Raises:
        VideoValidationError: 没有视频流
    """
    streams = probe.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    if not video_streams:
        raise VideoValidationError(f"视频文件中未找到视频流: {video_path}")
    return video_streams[0]


def validate_video_file(video_path: str, timeout: int = 60) -> dict[str, Any]:
    """验证视频文件存在性和基本完整性

    Args:
        video_path: 视频文件路径
        timeout: ffprobe 执行超时时间（秒），默认 60 秒

    Returns:
        包含 width, height, duration 的字典

    Raises:
        VideoValidationError: 文件不存在、为空或无法解析
    """
    if not os.path.exists(video_path):
        raise VideoValidationError(f"视频文件不存在: {video_path}")

    if os.path.getsize(video_path) == 0:
        raise VideoValidationError(f"视频文件为空: {video_path}")

    probe = _run_ffprobe(video_path, timeout=timeout)
    vs = _extract_video_stream(probe, video_path)
    return {
        "width": int(vs.get("width", 0)),
        "height": int(vs.get("height", 0)),
        "duration": float(probe.get("format", {}).get("duration", 0)),
        "file_path": video_path,
        "file_size": os.path.getsize(video_path),
    }


def validate_output_video(video_path: str, timeout: int = 60) -> bool:
    """验证输出视频文件的完整性和可播放性

    Args:
        video_path: 输出视频文件路径
        timeout: ffprobe 执行超时时间（秒），默认 60 秒

    Returns:
        True 如果文件有效

    Raises:
        VideoValidationError: 文件无效（包括 ffprobe 不可用的情况，
                              此时调用方应感知到验证未真正完成）
    """
    if not os.path.exists(video_path):
        raise VideoValidationError(f"输出视频文件不存在: {video_path}")

    file_size = os.path.getsize(video_path)
    if file_size == 0:
        raise VideoValidationError(f"输出视频文件为空: {video_path}")

    # 复用公共 ffprobe 实现（修复 L8：消除重复代码）
    probe = _run_ffprobe(video_path, timeout=timeout)
    _extract_video_stream(probe, video_path)
    return True


# ── 文件 I/O ──────────────────────────────────────────────


def validate_image_file(image_path: str) -> dict[str, Any]:
    """验证图片文件存在性、格式和基本完整性

    Args:
        image_path: 图片文件路径

    Returns:
        包含 width, height, file_size 的字典

    Raises:
        ImageValidationError: 文件不存在、为空、格式不支持
    """
    if not os.path.exists(image_path):
        raise ImageValidationError(f"背景板图片不存在: {image_path}")

    if os.path.getsize(image_path) == 0:
        raise ImageValidationError(f"背景板图片文件为空: {image_path}")

    ext = os.path.splitext(image_path)[1].lower()
    if ext not in SUPPORTED_IMAGE_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_EXTENSIONS))
        raise ImageValidationError(
            f"背景板图片格式不支持: {ext}。"
            f"支持的格式: {supported}"
        )

    try:
        from PIL import Image

        with Image.open(image_path) as img:
            width, height = img.size
            img.verify()
    except ImportError:
        # PIL 不可用时仅做文件大小检查
        file_size = os.path.getsize(image_path)
        return {
            "width": 0,
            "height": 0,
            "file_path": image_path,
            "file_size": file_size,
        }
    except Exception as exc:
        raise ImageValidationError(
            f"背景板图片文件损坏或无法解析: {image_path} ({exc})"
        ) from exc

    return {
        "width": width,
        "height": height,
        "file_path": image_path,
        "file_size": os.path.getsize(image_path),
    }


def write_text_file(path: str, content: str, encoding: str = "utf-8") -> None:
    """写入文本文件，自动创建父目录"""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def read_json_file(path: str, encoding: str = "utf-8") -> Any:
    """读取 JSON 文件"""
    with open(path, "r", encoding=encoding) as f:
        return json.load(f)


def write_json_file(
    path: str,
    data: Any,
    encoding: str = "utf-8",
) -> None:
    """写入 JSON 文件，自动创建父目录"""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ── 格式化 ────────────────────────────────────────────────


def format_duration(seconds: float) -> str:
    """格式化耗时显示"""
    if seconds < 0:
        return "0.0秒"
    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}分{secs:.1f}秒"


def format_file_size(size_bytes: int | float) -> str:
    """格式化文件大小

    Args:
        size_bytes: 文件字节数（int 或 float）

    Returns:
        带单位的大小字符串（B/KB/MB/GB/TB）

    Note:
        使用 float 进行单位换算以保持显示精度，结果保留 1 位小数。
        当 size_bytes 恰好等于 1024 时会进入下一单位返回 "1.0KB"。
    """
    size = float(size_bytes)
    if size < 0:
        return "0.0B"
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


# ── 视频合成共享工具 ──────────────────────────────────────

# 模组映射（干员模组编号 -> 显示名称）
MODULE_MAP: dict[int, str] = {
    1: "X模组",
    2: "Y模组",
    3: "α模组",
    4: "Δ模组",
}


def resolve_font_path(font_value: str, font_dir: str) -> str:
    """解析字体路径：支持font文件夹内字体名称或绝对路径

    Args:
        font_value: 字体文件名或绝对路径
        font_dir: 字体文件搜索目录

    Returns:
        字体文件的绝对路径

    Raises:
        FileNotFoundError: 字体文件不存在
    """
    if os.path.isabs(font_value):
        if os.path.exists(font_value):
            return font_value
        raise FileNotFoundError(f"字体文件不存在: {font_value}")

    font_path = os.path.join(font_dir, font_value)
    if os.path.exists(font_path):
        return font_path

    raise FileNotFoundError(f"字体文件不存在: {font_value} (搜索目录: {font_dir})")


def _load_text_from_json(
    input_json_path: str,
    config_path: str,
    convert_fn,
) -> str:
    """从 input.json 与配置文件加载并转换文本的公共实现

    Args:
        input_json_path: MAA copilot JSON 文件路径
        config_path: 转换配置文件路径
        convert_fn: 实际执行转换的函数（formation_to_text / actions_to_text）

    Returns:
        转换后的文本内容；输入文件不存在时返回空字符串
    """
    if not os.path.exists(input_json_path):
        logger.warning(f"输入文件不存在: {input_json_path}")
        return ""

    with open(input_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    config = load_config(config_path, {})
    return convert_fn(data, config)


def load_formation_text(input_json_path: str, formation_config_path: str) -> str:
    """从input.json和formation配置生成编队文本

    Args:
        input_json_path: MAA copilot JSON 文件路径
        formation_config_path: 编队配置文件路径

    Returns:
        编队文本内容
    """
    from arknights_video_pipeline.core.formation_to_text import formation_to_text

    return _load_text_from_json(
        input_json_path,
        formation_config_path,
        formation_to_text,
    )


def load_actions_text(input_json_path: str, actions_config_path: str) -> str:
    """从input.json和actions配置生成操作文本

    Args:
        input_json_path: MAA copilot JSON 文件路径
        actions_config_path: 操作配置文件路径

    Returns:
        操作文本内容
    """
    from arknights_video_pipeline.core.actions_to_text import actions_to_text

    return _load_text_from_json(
        input_json_path,
        actions_config_path,
        actions_to_text,
    )


def get_switch_time(track_result_path: str) -> float:
    """从track_result.json获取开始按钮消失时间点

    Args:
        track_result_path: 跟踪结果文件路径

    Returns:
        编队文本的切换时间（开始按钮消失时间），默认3秒
    """
    if not os.path.exists(track_result_path):
        logger.warning(f"跟踪结果文件不存在: {track_result_path}，编队文本将显示3秒")
        return 3.0

    with open(track_result_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    disappear_time = result.get("disappear_time")
    if disappear_time is not None and disappear_time > 0:
        return disappear_time

    # 回退：使用首次出现时间 + 持续时长
    first_appear = result.get("first_appear_time", 0)
    duration_visible = result.get("duration_visible", 3.0)
    return first_appear + duration_visible
