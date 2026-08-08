"""关卡名识别：对视频帧的关卡名区域做 OCR，查表得到 stageId。

移植自 Maa ``CombatRecordRecognitionTask::analyze_stage`` 与
``RegionOCRer``：对 ``BattleStageName`` 任务 ROI 做识别，再用
``Tile.find`` 查表。原 C++ 仅做精确查表（OCR 不准直接放弃该帧）；
本项目额外补充了 ocrReplace 与归一化查表，以容忍 OCR 把 ``2-10``
识成 ``2-l0`` 的情况，但不做模糊匹配（避免错字误命中）。
"""

from __future__ import annotations

import re
from typing import Optional

import numpy as np

from ArknightsVideoRecognition.config.roi import get_roi, load_roi
from ArknightsVideoRecognition.ocr.engine import OcrEngine
from ArknightsVideoRecognition.tile import find_level

# BattleStageName ROI 兜底值（与 resource/config/roi.json 一致，缺失时使用）
_DEFAULT_STAGE_ROI = [250, 435, 800, 100]

# BattleStageName 任务的 ocrReplace 规则缓存：[(正则, 替换), ...]
_stage_ocr_replace: Optional[list[tuple[str, str]]] = None


def _get_stage_ocr_replace() -> list[tuple[str, str]]:
    """读取 BattleStageName 任务的 ocrReplace 正则规则。

    Maa 的 RegionOCRer 识别后会按 ocrReplace 把常见错识文案归一化
    （如 ``.*前顾后`` -> ``瞻前顾后``）。规则解析结果缓存，避免每次
    识别都重新解析 roi.json。
    """
    global _stage_ocr_replace
    if _stage_ocr_replace is None:
        task = load_roi().get("BattleStageName") or {}
        rules = task.get("ocrReplace") or []
        _stage_ocr_replace = [(p, r) for p, r in rules]
    return _stage_ocr_replace


def _apply_ocr_replace(text: str) -> str:
    """按 BattleStageName 的 ocrReplace 正则规则归一化 OCR 文本。"""
    for pattern, repl in _get_stage_ocr_replace():
        try:
            text = re.sub(pattern, repl, text)
        except re.error:
            # 配置里偶有非法正则，跳过不影响整体识别
            continue
    return text


def _normalize(text: str) -> str:
    """归一化用于比较：去空白、转小写。"""
    return re.sub(r"\s+", "", text).lower()


def _normalize_code(text: str) -> str:
    """对 code 类文本做更激进的归一化：把易混字母还原为数字。

    OCR 常把 ``2-10`` 识成 ``2-l0`` / ``2-IO``。仅当文本看起来像 code
    （归一化后只含 ascii 字母数字与连字符）时启用，避免破坏中文名。
    """
    norm = _normalize(text)
    if norm and re.fullmatch(r"[a-z0-9\-]+", norm):
        table = str.maketrans({"i": "1", "l": "1", "o": "0", "s": "5", "z": "2"})
        return norm.translate(table)
    return norm


class StageRecognizer:
    """关卡名识别器。

    对 1280x720 视频帧的 ``BattleStageName`` ROI 做 OCR，将识别文本
    映射为关卡 dict（含 stageId/code/name 等）。查表策略对齐 Maa：
    精确匹配优先，未命中依次尝试 ocrReplace 归一化、code 字符归一化，
    仍不命中即放弃该帧（不做模糊匹配）。

    Parameters
    ----------
    ocr_engine:
        已构造的 :class:`OcrEngine`，为 ``None`` 时新建默认引擎。
    """

    def __init__(self, ocr_engine: Optional[OcrEngine] = None):
        self.ocr = ocr_engine if ocr_engine is not None else OcrEngine()

    def recognize(self, frame: np.ndarray) -> Optional[dict]:
        """识别视频帧中的关卡名，返回命中的关卡 dict，未命中返回 None。"""
        if frame is None:
            return None
        roi = get_roi("BattleStageName") or _DEFAULT_STAGE_ROI
        text = self.ocr.recognize_text(frame, roi=roi)
        return self._match(text)

    def recognize_with_candidates(
        self, frame: np.ndarray
    ) -> tuple[Optional[dict], list[str]]:
        """识别并返回 (命中关卡, 候选名列表)。

        对齐 Maa：未命中时候选列表为空（不再用模糊匹配生成候选）。
        """
        if frame is None:
            return None, []
        roi = get_roi("BattleStageName") or _DEFAULT_STAGE_ROI
        text = self.ocr.recognize_text(frame, roi=roi)
        level = self._match(text)
        return level, []

    def recognize_by_manual(self, stage_key: str) -> Optional[dict]:
        """用户手动指定关卡（code/name/stageId 任一），直接查表。"""
        if not stage_key:
            return None
        return find_level(stage_key)

    # --- 内部：查表 ---

    def _match(self, text: str) -> Optional[dict]:
        """对 OCR 文本依次做精确 -> ocrReplace -> 归一化查表。

        对齐 Maa C++ ``analyze_stage``：纯精确匹配，OCR 不准则放弃该帧。
        不再做 difflib 模糊匹配（原实现阈值 0.6 + 子串加分导致误命中）。
        """
        if not text:
            return None

        # 1) 原文精确查表（stageId/code/levelId/name 任一命中）
        level = find_level(text)
        if level is not None:
            return level

        # 2) 应用 BattleStageName 的 ocrReplace 规则后再查
        replaced = _apply_ocr_replace(text)
        if replaced and replaced != text:
            level = find_level(replaced)
            if level is not None:
                return level

        # 3) 归一化后查（去空格、小写；code 还原易混字母）
        for key in (_normalize(text), _normalize_code(text),
                    _normalize(text).replace("-", "")):
            if key:
                level = find_level(key)
                if level is not None:
                    return level

        # 4) 不再模糊匹配（对齐 Maa：未命中即放弃）
        return None
