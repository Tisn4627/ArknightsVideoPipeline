"""测试环境 FFmpeg 路径配置

在测试收集前应用 FFmpeg 路径配置，确保 movielite 的导入时检查
（check_dependencies）能找到 ffmpeg/ffprobe。

test_filename_encoding.py 等测试在模块级导入 video_compose_common → movielite，
movielite 在导入时通过 shutil.which 检查 ffmpeg 是否在 PATH 中。
若不提前应用配置，未安装 FFmpeg 的机器上测试收集阶段即失败。
"""

from arknights_video_pipeline.core.config import ConfigManager
from arknights_video_pipeline.core.utils import (
    PROJECT_ROOT,
    set_ffmpeg_config,
    ensure_ffmpeg_in_path,
)

_cfg = ConfigManager(PROJECT_ROOT)
_cfg.load_pipeline_config()
set_ffmpeg_config(
    bool(_cfg.pipeline.get("ffmpeg_custom_enabled", False)),
    _cfg.pipeline.get("ffmpeg_path", ""),
)
ensure_ffmpeg_in_path()
