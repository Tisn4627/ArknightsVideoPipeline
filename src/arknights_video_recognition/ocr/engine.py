"""RapidOCR 封装，支持 Maa finetune 模型与 RapidOCR 默认模型双源切换。

原 Maa 使用 PaddleOCR（PPOCRv3，FastDeploy 推理）；本项目改用 RapidOCR
（``rapidocr-onnxruntime``，本质是 PaddleOCR 的 onnxruntime 封装）。

支持两套模型源，通过 :class:`OcrSource` 切换：

- ``maamodel``：复用 Maa 的方舟 finetune PaddleOCR onnx 模型（默认，保留方舟
  专用精度）。模型位于 ``resource/ocr/maa/``。
- ``default``：使用 RapidOCR pip 包自带的默认模型。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from enum import Enum
from pathlib import Path
from typing import Optional, Union

import numpy as np
from rapidocr_onnxruntime import RapidOCR

try:
    # 新版本 RapidOCR 模块路径
    from rapidocr_onnxruntime.ch_ppocr_rec.text_recognize import TextRecognizer
except ImportError:
    # 旧版本 RapidOCR 模块路径（兼容）
    from rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize import TextRecognizer

from ..config.settings import DATA_DIR, DEFAULT_OCR_SOURCE, OCR_MAA_DIR

logger = logging.getLogger(__name__)


class OcrSource(str, Enum):
    """OCR 模型来源。"""

    MAA_MODEL = "maamodel"  # 复用 Maa 的方舟 finetune PaddleOCR onnx 模型
    DEFAULT = "default"     # 使用 RapidOCR pip 包自带的默认模型


# RapidOCR 实例缓存：同一 source 只加载一次，避免重复加载模型
_ENGINE_CACHE: dict[str, RapidOCR] = {}
# 保护 _ENGINE_CACHE 构造与共享实例上的调用（text_score 临时改写）；
# 也顺带串行化推理，避免并发 worker 的阈值互相踩踏
_ENGINE_LOCK = threading.RLock()

# Maa finetune 模型文件位置
_MAA_DET_ONNX = OCR_MAA_DIR / "det" / "inference.onnx"
_MAA_REC_ONNX = OCR_MAA_DIR / "rec" / "inference.onnx"
_MAA_REC_KEYS = OCR_MAA_DIR / "rec" / "keys.txt"

# OCR 等价类配置文件
_OCR_CONFIG_PATH = DATA_DIR / "ocr_config.json"

# 与 RapidOCR 默认 config.yaml 中 Rec 段保持一致的识别参数
_DEFAULT_REC_IMG_SHAPE = [3, 48, 320]
_DEFAULT_REC_BATCH_NUM = 6


def _build_maa_engine() -> RapidOCR:
    """构造使用 Maa finetune 模型的 RapidOCR 实例。

    Maa 的 rec onnx 模型没有把字符表写入 ONNX 元数据（``have_key`` 返回
    False）。RapidOCR 内部 :class:`TextRecognizer` 在缺少内嵌字符表时会回退
    读取 ``config['keys_path']``，但 RapidOCR 的 kwargs 路由只会把
    ``rec_keys_path`` 原样塞进配置（不去 ``rec_`` 前缀），识别器取不到
    ``keys_path``，构造时即因 ``character_dict_path is None`` 断言失败。

    因此这里分两步：先用 maa 的 det 模型构造（rec 暂用默认模型，默认 rec
    自带内嵌字符表，构造必然成功），再用显式配置（含 ``keys_path``）把识别器
    替换为 maa 的 rec 模型 + ``keys.txt``。
    """
    engine = RapidOCR(det_model_path=str(_MAA_DET_ONNX))
    rec_config = {
        "use_cuda": False,
        "model_path": str(_MAA_REC_ONNX),
        # 新版 RapidOCR 用 rec_keys_path，旧版用 keys_path，两者都传以兼容
        "rec_keys_path": str(_MAA_REC_KEYS),
        "keys_path": str(_MAA_REC_KEYS),
        "rec_img_shape": _DEFAULT_REC_IMG_SHAPE,
        "rec_batch_num": _DEFAULT_REC_BATCH_NUM,
    }
    engine.text_recognizer = TextRecognizer(rec_config)
    return engine


def _build_default_engine() -> RapidOCR:
    """构造使用 RapidOCR pip 包自带默认模型的实例。"""
    return RapidOCR()


def _get_engine(source: str) -> RapidOCR:
    """按 source 取（必要时构造并缓存）RapidOCR 实例。

    加锁保护：批量并发模式下多个 worker 线程可能同时首次触发构造。
    """
    with _ENGINE_LOCK:
        if source not in _ENGINE_CACHE:
            if source == OcrSource.MAA_MODEL.value:
                _ENGINE_CACHE[source] = _build_maa_engine()
            elif source == OcrSource.DEFAULT.value:
                _ENGINE_CACHE[source] = _build_default_engine()
            else:
                raise ValueError(
                    f"未知的 OCR source: {source!r}，可选: "
                    f"{OcrSource.MAA_MODEL.value}, {OcrSource.DEFAULT.value}"
                )
        return _ENGINE_CACHE[source]


def _load_equivalence_rules(path: Path) -> list[tuple[list[str], str]]:
    """读取 OCR 等价类替换规则。

    配置文件结构形如::

        {"equivalence_classes": [
            {"from": ["壹", "貳"], "to": "一"},
            ["繁", "简"]
        ]}

    - 字典项：把 ``from`` 中每个字替换为 ``to``。
    - 列表项：首项为规范字，其余各项都映射到首项。

    返回 ``[(待替换字列表, 规范字), ...]``。文件缺失或 ``equivalence_classes``
    为空时返回 ``[]``（替换逻辑自动跳过）。
    """
    if not path.is_file():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    rules: list[tuple[list[str], str]] = []
    for entry in data.get("equivalence_classes", []) or []:
        if isinstance(entry, dict):
            froms = entry.get("from") or []
            to = entry.get("to")
            if to and froms:
                rules.append((list(froms), str(to)))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            rules.append(([str(c) for c in entry[1:]], str(entry[0])))
    return rules


def _load_replace_rules(path: Path) -> tuple[list[list[str]], bool]:
    """读取 OCR 正则替换规则 ``ocrReplace`` 与 ``replace_full`` 开关。

    配置文件结构形如::

        {"ocrReplace": [[".*ancet-2", "Lancet-2"], ...],
         "replace_full": true}

    - ``ocrReplace``：``[[pattern, replacement], ...]``，正则替换列表。
    - ``replace_full``：``True`` 时整串匹配才替换，``False`` 时部分匹配即替换。

    返回 ``(replace_map, replace_full)``。文件缺失或字段为空时返回
    ``([], False)``（替换逻辑自动跳过）。
    """
    if not path.is_file():
        return [], False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return [], False

    replace_map: list[list[str]] = []
    for entry in data.get("ocrReplace", []) or []:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            replace_map.append([str(entry[0]), str(entry[1])])
    replace_full = bool(data.get("replace_full", False))
    return replace_map, replace_full


class OcrEngine:
    """RapidOCR 封装，支持 Maa finetune 与 RapidOCR 默认两套模型源。

    Parameters
    ----------
    source:
        模型来源，``"maamodel"``（默认，方舟 finetune 精度）或 ``"default"``
        （RapidOCR 自带模型）。也可传 :class:`OcrSource` 枚举。
    """

    def __init__(self, source: Union[str, OcrSource] = DEFAULT_OCR_SOURCE):
        source = source.value if isinstance(source, OcrSource) else str(source)
        self.source = source
        # RapidOCR 实例按 source 缓存，构造较慢，确保每个 source 只加载一次
        self._ocr = _get_engine(source)
        self._equivalence_rules = _load_equivalence_rules(_OCR_CONFIG_PATH)
        # 预构建字符映射表：规则集是静态的，逐识别项重建 dict 是纯浪费
        self._equivalence_map: dict[str, str] = {}
        for froms, to in self._equivalence_rules:
            for ch in froms:
                self._equivalence_map[ch] = to
        # 读取 ocrReplace 正则替换规则与 replace_full 开关，并预编译正则
        replace_map, replace_full = _load_replace_rules(_OCR_CONFIG_PATH)
        self.set_replace(replace_map, replace_full)

    def set_replace(self, replace_map: list, replace_full: bool) -> None:
        """设置 OCR 后正则替换规则。

        Parameters
        ----------
        replace_map : list
            正则替换列表，每条 [pattern, replacement]。
        replace_full : bool
            True 时整串匹配才替换，False 时部分匹配即替换。
        """
        self._replace_map = list(replace_map)
        self._replace_full = bool(replace_full)
        try:
            self._compiled_replace = [
                (re.compile(p), r) for p, r in self._replace_map
            ]
        except re.error as exc:
            # 配置里偶有非法正则：对齐 stage/recognizer.py 的容错风格，
            # 告警后回退为空替换列表（跳过全部替换），不让 OCR 崩溃
            logger.warning("ocrReplace 正则编译失败，回退为空替换列表: %s", exc)
            self._compiled_replace = []

    def _apply_equivalence(self, text: str) -> str:
        """按等价类规则对识别文本做替换。无规则时原样返回。"""
        if not self._equivalence_map or not text:
            return text
        return "".join(self._equivalence_map.get(ch, ch) for ch in text)

    def _apply_replace(self, text: str) -> str:
        """对 OCR 文本应用正则替换规则。"""
        if not text or not self._compiled_replace:
            return text
        for compiled_pattern, replacement in self._compiled_replace:
            if self._replace_full:
                # 整串匹配才替换
                if compiled_pattern.fullmatch(text):
                    text = compiled_pattern.sub(replacement, text)
            else:
                # 部分匹配即替换
                if compiled_pattern.search(text):
                    text = compiled_pattern.sub(replacement, text)
        return text

    def recognize(self, image: np.ndarray,
                  roi: Optional[list[int]] = None,
                  text_score: Optional[float] = None) -> list[dict]:
        """对图像做 OCR。

        Parameters
        ----------
        image:
            numpy BGR 数组（opencv 格式）。
        roi:
            可选，``[x, y, w, h]``。给定则先裁剪再识别；返回的 ``box`` 坐标
            会偏移回原图坐标系。
        text_score:
            可选，文本检测置信度阈值（覆盖 RapidOCR 默认 0.5）。
            单字（如「遥」）的 det 分数可能略低于默认阈值，传 0.3 可提高
            单字检出率。仅在本次调用生效，调用后恢复原值。

        Returns
        -------
        list[dict]
            每项含 ``text``(str)、``box``(四个 ``[x, y]`` 点)、``score``(float)。
        """
        if image is None:
            return []
        img = np.asarray(image)
        offset = (0, 0)
        if roi is not None:
            x, y, w, h = (int(v) for v in roi)
            # 边界钳制：负坐标会触发 numpy 回绕取到画面尾部，越界 w/h
            # 会被静默截断；无效 ROI 直接返回空而不是"看似正常"的错裁剪
            x0, y0 = max(0, x), max(0, y)
            x1 = min(img.shape[1], x + w)
            y1 = min(img.shape[0], y + h)
            if x1 <= x0 or y1 <= y0:
                return []
            img = img[y0:y1, x0:x1]
            offset = (x0, y0)

        # 共享 RapidOCR 实例上的调用全程持锁：text_score 的临时改写
        # 在并发 worker 下会互相踩踏（见 _ENGINE_LOCK 说明）
        with _ENGINE_LOCK:
            # 临时调整 text_score（如需），调用后恢复
            original_score = getattr(self._ocr, "text_score", None)
            if text_score is not None and original_score is not None:
                self._ocr.text_score = text_score
            try:
                result, _ = self._ocr(img)
            finally:
                if text_score is not None and original_score is not None:
                    self._ocr.text_score = original_score
        if not result:
            return []

        items: list[dict] = []
        for box, text, score in result:
            box_pts = [[float(px), float(py)] for px, py in box]
            if offset != (0, 0):
                box_pts = [[px + offset[0], py + offset[1]]
                           for px, py in box_pts]
            items.append({
                "text": self._apply_replace(self._apply_equivalence(str(text))),
                "box": box_pts,
                "score": float(score),
            })
        return items

    def recognize_text(self, image: np.ndarray,
                       roi: Optional[list[int]] = None) -> str:
        """便捷方法：返回所有识别文本拼接成的纯字符串。"""
        items = self.recognize(image, roi=roi)
        return "".join(it["text"] for it in items)
