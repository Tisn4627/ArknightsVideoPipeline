"""
core - ArknightsVideoPipeline 核心共享模块

提供配置管理、日志系统、异常定义、类型注解、工具函数和各功能模块。
"""

from arknights_video_pipeline.core.config import ConfigManager
from arknights_video_pipeline.core.exceptions import (
    PipelineError,
    PipelineStepError,
    VideoValidationError,
    ImageValidationError,
    MAARecognitionError,
    ConfigError,
)
from arknights_video_pipeline.core.logger import setup_logger, get_step_logger
from arknights_video_pipeline.core.types import (
    StepResult,
    StepStatus,
    VideoInfo,
    PipelineReport,
)
from arknights_video_pipeline.core.utils import (
    PROJECT_ROOT,
    SUPPORTED_VIDEO_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    MODULE_MAP,
    resolve_path,
    resolve_project_path,
    ensure_dir,
    validate_video_file,
    validate_image_file,
    validate_output_video,
    write_text_file,
    read_json_file,
    write_json_file,
    load_config,
    save_default_config,
    format_duration,
    format_file_size,
    resolve_font_path,
    load_formation_text,
    load_actions_text,
    get_switch_time,
)

__all__ = [
    # 配置
    "ConfigManager",
    # 异常
    "PipelineError",
    "PipelineStepError",
    "VideoValidationError",
    "ImageValidationError",
    "MAARecognitionError",
    "ConfigError",
    # 日志
    "setup_logger",
    "get_step_logger",
    # 类型
    "StepResult",
    "StepStatus",
    "VideoInfo",
    "PipelineReport",
    # 工具
    "PROJECT_ROOT",
    "SUPPORTED_VIDEO_EXTENSIONS",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "MODULE_MAP",
    "resolve_path",
    "resolve_project_path",
    "ensure_dir",
    "validate_video_file",
    "validate_image_file",
    "validate_output_video",
    "write_text_file",
    "read_json_file",
    "write_json_file",
    "load_config",
    "save_default_config",
    "format_duration",
    "format_file_size",
    "resolve_font_path",
    "load_formation_text",
    "load_actions_text",
    "get_switch_time",
]
