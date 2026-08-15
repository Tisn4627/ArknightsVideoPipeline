"""区域 OCR 识别器：对指定 ROI 做二值化预处理后 OCR。

对应 Maa C++ RegionOCRer / OperNameAnalyzer，
对名字小条做 Gray→inRange→dilate 预处理后单独 OCR。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np


@dataclass
class RegionOcrResult:
    """单个 OCR 结果。

    Attributes
    ----------
    text:
        识别文本。
    rect:
        识别区域 ``[x, y, w, h]``，在原图坐标系。
    """

    text: str
    rect: List[int]


class RegionOCRer:
    """区域 OCR 识别器。

    对指定 ROI 做二值化预处理（Gray→inRange→dilate）后，
    裁剪空白边距，调用 OcrEngine 识别文字。
    """

    def __init__(self, image: np.ndarray, ocr_engine):
        """初始化。

        Parameters
        ----------
        image:
            输入图像（BGR）。
        ocr_engine:
            OCR 引擎实例（``OcrEngine``），需提供 ``recognize(image)`` 方法。
        """
        self._image = image
        self._ocr_engine = ocr_engine
        self._roi: Optional[List[int]] = None
        self._bin_threshold: int = 160
        self._bin_expansion: int = 3
        # Maa specialParams[2,3]，当前均为 0，暂保留接口但不参与处理
        self._bin_trim_low: int = 0
        self._bin_trim_high: int = 0
        self._bottom_line_height: int = 0
        self._width_threshold: int = 10
        self._replace_map: List = []
        self._replace_full: bool = False

    # --- 配置 -------------------------------------------------------------

    def set_roi(self, roi: List[int]) -> None:
        """设置识别区域 ``[x, y, w, h]``（原图坐标系）。"""
        self._roi = list(roi)

    def set_bin_threshold(self, threshold: int) -> None:
        """设置二值化阈值（0-255）。默认 160。"""
        self._bin_threshold = int(threshold)

    def set_bin_expansion(self, expansion: int) -> None:
        """设置膨胀像素数。默认 3。"""
        self._bin_expansion = int(expansion)

    def set_bin_trim_threshold(self, low: int, high: int) -> None:
        """设置裁剪阈值（Maa specialParams[2,3]，当前均为 0，暂不使用）。"""
        self._bin_trim_low = int(low)
        self._bin_trim_high = int(high)

    def set_bottom_line_height(self, height: int) -> None:
        """设置底部裁剪高度（去除装饰线）。默认 3。"""
        self._bottom_line_height = int(height)

    def set_width_threshold(self, width: int) -> None:
        """设置最小有效宽度。裁剪后宽度 < 此值返回 None。默认 10。"""
        self._width_threshold = int(width)

    def set_replace(self, replace_map: List, replace_full: bool) -> None:
        """设置 OCR 后正则替换规则。

        Parameters
        ----------
        replace_map:
            正则替换列表，每条 ``[pattern, replacement]``。
        replace_full:
            True 时整串匹配才替换，False 时部分匹配即替换。
        """
        self._replace_map = list(replace_map) if replace_map else []
        self._replace_full = bool(replace_full)

    # --- 内部辅助 ---------------------------------------------------------

    def _apply_replace(self, text: str) -> str:
        """按 replace_map 对识别文本做正则替换，依次应用每条规则。"""
        if not self._replace_map or not text:
            return text
        for rule in self._replace_map:
            if not rule or len(rule) < 2:
                continue
            pattern, replacement = rule[0], rule[1]
            if self._replace_full:
                # 整串匹配才替换，支持反向引用
                m = re.fullmatch(pattern, text)
                if m is not None:
                    text = m.expand(replacement)
            else:
                # 部分匹配即替换
                text = re.sub(pattern, replacement, text)
        return text

    @staticmethod
    def _find_blank_gap(col_has_content: np.ndarray,
                        width_threshold: int) -> Optional[int]:
        """从左往右逐列扫描，返回第一段长度 >= width_threshold 的全零空白块的起始列。

        不存在则返回 None。用于裁掉名字文本之后的装饰块。
        """
        if width_threshold <= 0:
            return None
        run = 0
        run_start = -1
        for i, has in enumerate(col_has_content.tolist()):
            if has:
                run = 0
                run_start = -1
            else:
                if run == 0:
                    run_start = i
                run += 1
                if run >= width_threshold:
                    return run_start
        return None

    # --- 主入口 -----------------------------------------------------------

    def analyze(self) -> Optional[RegionOcrResult]:
        """执行预处理 + OCR。

        Returns
        -------
        RegionOcrResult or None
            识别成功返回结果（text + rect），空槽/噪声返回 None。
        """
        image = self._image
        if image is None or getattr(image, "size", 0) == 0:
            return None

        orig_h, orig_w = image.shape[:2]

        # 解析 ROI 并裁到画面范围内
        roi = self._roi
        if roi is None:
            roi_x, roi_y, roi_w, roi_h = 0, 0, orig_w, orig_h
        else:
            roi_x, roi_y, roi_w, roi_h = roi
        x0 = max(0, int(roi_x))
        y0 = max(0, int(roi_y))
        x1 = min(orig_w, int(roi_x + roi_w))
        y1 = min(orig_h, int(roi_y + roi_h))
        if x1 <= x0 or y1 <= y0:
            return None

        roi_img = image[y0:y1, x0:x1]

        # 1. 二值化仅用于空槽检测（判断是否有文字内容）。
        #    RapidOCR (PaddleOCR) 自带文本检测，不需要手动裁剪——
        #    诊断验证：直接对原始 122x18 彩图 OCR 返回"杜林"，
        #    但裁剪到 39x15 后 OCR 返回空。因此 OCR 发送原始彩图。
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(
            gray, self._bin_threshold, 255, cv2.THRESH_BINARY
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        binary = cv2.dilate(binary, kernel, iterations=self._bin_expansion)

        if binary.size == 0:
            return None

        # 2. 底部裁剪：去掉底部装饰线（3px），避免干扰 OCR
        if self._bottom_line_height > 0:
            new_h = roi_img.shape[0] - self._bottom_line_height
            if new_h <= 0:
                return None
            roi_img = roi_img[:new_h, :]

        # 3. 空槽检测：二值图无任何非零像素 → 空槽
        col_has_content = np.any(binary > 0, axis=0)
        nonzero_cols = np.where(col_has_content)[0]
        if nonzero_cols.size == 0:
            return None

        # 4. 宽度过滤：原始 ROI 宽度过窄视为空槽/噪声
        if roi_img.shape[1] < self._width_threshold:
            return None

        # 5. 小图填充：RapidOCR det 模型（limit_side_len=736, limit_type=min）
        #    对高度 <48px 的小图会过度放大导致文本检测失败。用黑色边框填充
        #    至 48px 高（与 rec 模型输入一致），使 det 模型正常工作。
        #    黑色填充不会被检测为文本，不影响识别结果。
        _DET_MIN_HEIGHT = 48
        if roi_img.shape[0] < _DET_MIN_HEIGHT:
            pad = (_DET_MIN_HEIGHT - roi_img.shape[0]) // 2
            roi_img = cv2.copyMakeBorder(
                roi_img, pad, _DET_MIN_HEIGHT - roi_img.shape[0] - pad,
                0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0),
            )

        # 6. OCR：直接发送原始彩图（不裁剪、不二值化），RapidOCR 自带预处理。
        #    OcrEngine.recognize 内部已应用 ocrReplace 正则修正，此处不再重复。
        items = self._ocr_engine.recognize(roi_img)
        # 降阈值重试：单字（如「遥」）的 det 分数可能略低于默认阈值 0.5，
        # 导致文本检测失败。首次返回空时用 text_score=0.3 重试。
        if not items:
            items = self._ocr_engine.recognize(roi_img, text_score=0.3)
        text = items[0]["text"] if items else ""

        rect = [
            x0,
            y0,
            int(roi_img.shape[1]),
            int(roi_img.shape[0]),
        ]
        return RegionOcrResult(text=text, rect=rect)
