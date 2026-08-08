"""Project-wide resource paths and configuration constants.

Resource layout (under ``RESOURCE_DIR``)::

    resource/
        tile/levels.json            # standard Arknights-Tile-Pos map data
        onnx/*.onnx                 # skill_ready_cls / deploy_direction_cls / operators_det
        ocr/maa/det/                # PaddleOCR detection model (Maa flavour)
        ocr/maa/rec/                # PaddleOCR recognition model (Maa flavour)
        data/battle_data.json       # operator avatar / battle metadata
        data/ocr_config.json        # OCR equivalence classes
        template/empty.png          # avatar placeholder template
        config/roi.json             # extracted ROI task definitions

The default resource directory is the ``resource`` folder at the project
root, but it can be overridden with the ``AVR_RESOURCE_DIR`` environment
variable.
"""

import os
from pathlib import Path

# --- Project / resource root ----------------------------------------------

# settings.py lives at:
#   <root>/src/ArknightsVideoRecognition/config/settings.py
# so parents[3] is the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_ENV_RESOURCE_DIR = os.environ.get("AVR_RESOURCE_DIR")
RESOURCE_DIR = Path(_ENV_RESOURCE_DIR).resolve() if _ENV_RESOURCE_DIR else _PROJECT_ROOT / "resource"

# --- Common path constants -------------------------------------------------

TILE_DIR = RESOURCE_DIR / "tile"
ONNX_DIR = RESOURCE_DIR / "onnx"
OCR_MAA_DIR = RESOURCE_DIR / "ocr" / "maa"
DATA_DIR = RESOURCE_DIR / "data"
TEMPLATE_DIR = RESOURCE_DIR / "template"
CONFIG_DIR = RESOURCE_DIR / "config"

# --- 助战干员识别相关路径与参数 --------------------------------------------

AVATAR_DIR = RESOURCE_DIR / "avatar"
SUPPORT_TEMPLATE = TEMPLATE_DIR / "empty_support_operator.png"
SUPPORT_MATCH_THRESHOLD = 0.6        # 助战头像匹配最低相似度
SUPPORT_EMPTY_THRESHOLD = 0.8        # 助战槽位判空最低相似度
START_BUTTON_STABLE_FRAMES = 5       # 开始按钮稳定所需连续帧数
SUPPORT_DETECT_MAX_SEC = 30.0        # 助战识别最长检测时间（秒）
SUPPORT_SLOT_ROI = [1027, 71, 151, 293]  # 助战槽位固定位置（720p），经 formation_test.mp4 模板匹配确认

# 编队页面开始按钮 ROI（720p）。
# 诊断确认：编队页面的"开始行动"按钮在 y≈440-580 处（非 StartButton1 的 y=625），
# StartButton1 ROI [1010,625,260,61] 在编队页面 OCR 返回空。
# 此 ROI 覆盖编队页面的按钮文字区域，用于检测编队页面是否可见。
START_BUTTON_FORMATION_ROI = [1020, 440, 200, 140]

# --- 部署栏识别相关参数（对齐 Maa BattleOpersFlag） ---
BATTLE_OPERS_FLAG_TEMPLATE = TEMPLATE_DIR / "BattleOpersFlag.png"
# BattleOpersFlag ROI（720p，来自 Maa tasks.json）
DEPLOYMENT_FLAG_ROI = [35, 588, 1245, 18]
# 模板匹配阈值（Maa templThreshold）
# 0.6：0.65 在部署动画过渡帧漏检严重（实测 ts=42.4 仅检出 2/5 槽位），
# 降至 0.6 提高召回率。虚假检测通过 NMS_DIST=80 过滤（slot 间距约 119px）。
DEPLOYMENT_FLAG_THRESHOLD = 0.6
# NMS 去重最小间距（像素）
# 80：slot 间距约 119px，NMS_DIST=80 合并间距<80 的虚假检测（如 1069/1113），
# 同时保留真实 slot。原 30 无法过滤 thr=0.6 引入的近距离虚假检测。
DEPLOYMENT_FLAG_NMS_DIST = 80
# 部署栏头像 rectMove（相对 flag 左上角）
# 对齐 Maa deployment_analyze：avatar_rect = flag.move(click_move).move(avatar_move)
#   click_move = BattleOperClickRange.rectMove = [-45, 6, 75, 120]
#   avatar_move = BattleOperAvatar.rectMove    = [7, 32, 60, 60]
#   合计 = [-45+7, 6+32, 60, 60] = [-38, 38, 60, 60]
DEPLOYMENT_AVATAR_MOVE = [-38, 38, 60, 60]
# 部署栏脸部子区 rectMove [15, 15, 30, 30]（相对 60×60 头像左上角）
DEPLOYMENT_FACE_MOVE = [15, 15, 30, 30]
# 部署栏↔编队匹配阈值（对齐 Maa BattleAvatarDataForFormation templThreshold=0.6）
# Maa BestMatcher: MatchMethod::Ccoeff → TM_CCOEFF_NORMED（Matcher.cpp:188）
DEPLOYMENT_MATCH_THRESHOLD = 0.6
# 部署栏↔部署栏匹配阈值（对齐 Maa BattleAvatarDataForVideo templThreshold=0.6）
# 同结构 60×60 直接 matchTemplate，无裁剪/缩放，同干员帧间分数 0.8+，用 0.6 安全。
DEPLOYMENT_NAME_MATCH_THRESHOLD = 0.6
# --- 干员职业表（用于 avatar 匹配 role 过滤，对齐 Maa BattleData.get_role） ---
CHAR_ROLE_TABLE_PATH = DATA_DIR / "char_roles.json"
# --- 干员稀有度表（用于部署栏匹配的尺度范围，对齐 Maa BattleData.get_rarity） ---
# Maa analyze_deployment: scale_ends = get_rarity(name)==1 ? 200 : 125
# battle_data.json 中 rarity 为整数（1=小车，2-6=普通干员）
BATTLE_DATA_PATH = DATA_DIR / "battle_data.json"

# --- 战斗按钮检测参数（对齐 Maa BattleHasStarted / BattleSpeedButton） ---
# Maa 用二值化阈值法（非模板），在固定 ROI 上统计亮像素数。
# pause 按钮：BattleHasStarted 任务，roi=[1178,33,53,39], specialParams=[235, 200]
BATTLE_PAUSE_ROI = [1178, 33, 53, 39]
BATTLE_PAUSE_VALUE_THR = 235
BATTLE_PAUSE_COUNT_THR = 200
# speed 按钮：BattleSpeedButton 任务，roi=[1069,22,55,59], specialParams=[245, 160]
BATTLE_SPEED_ROI = [1069, 22, 55, 59]
BATTLE_SPEED_VALUE_THR = 245
BATTLE_SPEED_COUNT_THR = 160

# --- 职业识别参数（对齐 Maa BattleOperRole） ---
# 9 个职业图标模板目录（已下载至 resource/template/Battle/OperRole/）
BATTLE_OPER_ROLE_DIR = TEMPLATE_DIR / "Battle" / "OperRole"
# BattleOperRoleRange.rectMove = [-41, 6, 31, 25]（相对 flag 左上角）
BATTLE_OPER_ROLE_RECT_MOVE = [-41, 6, 31, 25]
# BattleOperRole.templThreshold = 0.65
BATTLE_OPER_ROLE_THRESHOLD = 0.65

# --- Default parameters ----------------------------------------------------

DEFAULT_RESOLUTION = (1280, 720)
DEFAULT_OCR_SOURCE = "maamodel"
MINIMUM_REQUIRED = "v4.0.0"

# Names of the ONNX models required by the battle recognition pipeline.
_REQUIRED_ONNX_MODELS = (
    "skill_ready_cls.onnx",
    "deploy_direction_cls.onnx",
    "operators_det.onnx",
)


class ResourceMissingError(Exception):
    """Raised when a required resource file is absent from RESOURCE_DIR."""


def check_resource():
    """Verify that every required resource file is present.

    Checks for ``tile/levels.json``, the three ONNX models and
    ``data/battle_data.json``. Raises :class:`ResourceMissingError` listing
    every missing file and hinting at ``scripts/update_resources.py``.
    """
    missing = []

    expected = [
        TILE_DIR / "levels.json",
        DATA_DIR / "battle_data.json",
    ]
    expected.extend(ONNX_DIR / name for name in _REQUIRED_ONNX_MODELS)

    for path in expected:
        if not path.is_file():
            missing.append(str(path))

    if missing:
        detail = "\n  - ".join(missing)
        raise ResourceMissingError(
            "Required resource file(s) missing under "
            f"{RESOURCE_DIR}:\n  - {detail}\n"
            "Run script/update_resources.py to fetch/copy the needed "
            "resources from the upstream Maa / Arknights-Tile-Pos repositories."
        )

    # --- 助战干员识别所需资源校验 ---
    if not SUPPORT_TEMPLATE.is_file():
        raise ResourceMissingError(f"助战空模板缺失：{SUPPORT_TEMPLATE}")
    if not AVATAR_DIR.is_dir() or not any(AVATAR_DIR.iterdir()):
        raise ResourceMissingError(f"干员头像目录缺失或为空：{AVATAR_DIR}")
