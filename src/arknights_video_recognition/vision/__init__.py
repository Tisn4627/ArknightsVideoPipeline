"""视觉识别（vision）模块。

提供通用视觉原语：多模板匹配（:class:`MultiMatcher`）、ROI 区域 OCR
（:class:`RegionOCRer`）以及"模板定位 + 相对偏移 OCR"组合识别器
（:class:`TemplDetOCRer`），对应 Maa C++ ``MultiMatcher`` /
``RegionOCRer`` / ``TemplDetOCRer``。

典型用法::

    from arknights_video_recognition.vision import TemplDetOCRer

    ocrer = TemplDetOCRer(frame, ocr_engine)
    ocrer.set_task_info("BattleFormationOCRNameFlag", "BattleFormationOperNames")
    results = ocrer.analyze()
"""

from arknights_video_recognition.vision.multi_matcher import MatchResult, MultiMatcher
from arknights_video_recognition.vision.region_ocrer import RegionOcrResult, RegionOCRer
from arknights_video_recognition.vision.templ_det_ocrer import (
    TemplDetOcrResult,
    TemplDetOCRer,
)

__all__ = [
    "MultiMatcher",
    "MatchResult",
    "RegionOCRer",
    "RegionOcrResult",
    "TemplDetOCRer",
    "TemplDetOcrResult",
]
