"""配置（config）模块。

集中管理项目全局资源路径与识别参数（:mod:`settings`），以及提取自
Maa tasks.json 的 ROI 任务定义访问接口（:mod:`roi`）。资源目录默认为
项目根下 ``resource/``，可用环境变量 ``AVR_RESOURCE_DIR`` 覆盖。

典型用法::

    from arknights_video_recognition.config import get_roi, check_resource

    check_resource()          # 校验必需资源文件齐全
    roi = get_roi("BattleStageName")   # 查询任务 ROI [x, y, w, h]
"""

from arknights_video_recognition.config.roi import (
    ROI_FILE,
    clear_roi_cache,
    get_roi,
    load_roi,
)
from arknights_video_recognition.config.settings import (
    CONFIG_DIR,
    DATA_DIR,
    DEFAULT_OCR_SOURCE,
    DEFAULT_RESOLUTION,
    MINIMUM_REQUIRED,
    ONNX_DIR,
    RESOURCE_DIR,
    TEMPLATE_DIR,
    TILE_DIR,
    ResourceMissingError,
    check_resource,
)

__all__ = [
    # 路径常量
    "RESOURCE_DIR",
    "TILE_DIR",
    "ONNX_DIR",
    "DATA_DIR",
    "TEMPLATE_DIR",
    "CONFIG_DIR",
    "ROI_FILE",
    # 默认参数
    "DEFAULT_RESOLUTION",
    "DEFAULT_OCR_SOURCE",
    "MINIMUM_REQUIRED",
    # 资源校验
    "ResourceMissingError",
    "check_resource",
    # ROI 访问
    "load_roi",
    "get_roi",
    "clear_roi_cache",
]
