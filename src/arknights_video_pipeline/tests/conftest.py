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

# 开发者本地 config/pipeline.json 损坏不应让整个套件在收集期崩溃：
# 读取失败时回退到"禁用自定义 FFmpeg"，由 ensure_ffmpeg_in_path 的
# 系统 PATH / 注册表回退兜底
try:
    _cfg = ConfigManager(PROJECT_ROOT)
    _cfg.load_pipeline_config()
except Exception:
    _cfg = None

set_ffmpeg_config(
    bool(_cfg.pipeline.get("ffmpeg_custom_enabled", False)) if _cfg else False,
    _cfg.pipeline.get("ffmpeg_path", "") if _cfg else "",
)
ensure_ffmpeg_in_path()
