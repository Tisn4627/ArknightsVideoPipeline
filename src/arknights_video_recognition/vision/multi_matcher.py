"""多模板匹配器：在 ROI 内找所有匹配位置。

对应 Maa C++ ``MultiMatcher``，用 ``cv2.matchTemplate`` 做多峰值匹配 + NMS 去重。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

# NMS 去重默认 IoU 阈值：重叠超过该值的匹配视为同一目标
_DEFAULT_NMS_IOU = 0.3


@dataclass
class MatchResult:
    """单个匹配结果。

    Attributes
    ----------
    rect:
        匹配矩形 ``[x, y, w, h]``，在原图坐标系。
    score:
        匹配分数，范围 ``[0, 1]``。
    """

    rect: List[int]
    score: float


class MultiMatcher:
    """多模板匹配器。

    在指定 ROI 内用 ``cv2.matchTemplate`` 找所有超过阈值的匹配位置，
    对重叠匹配做 NMS 去重后返回。
    """

    def __init__(self, image: np.ndarray, roi: Optional[List[int]] = None):
        """初始化。

        Parameters
        ----------
        image:
            输入图像（BGR）。
        roi:
            搜索区域 ``[x, y, w, h]``。``None`` 表示全图。
        """
        self._image = image
        self._template: Optional[np.ndarray] = None
        self._threshold: float = 0.6
        # None 表示全图，在 analyze 时按图像尺寸展开
        self._roi: Optional[List[int]] = list(roi) if roi is not None else None

    def set_template(self, template: np.ndarray, threshold: float = 0.6) -> None:
        """设置模板与阈值。"""
        self._template = template
        self._threshold = float(threshold)

    def set_roi(self, roi: List[int]) -> None:
        """设置搜索区域 ``[x, y, w, h]``。"""
        self._roi = list(roi)

    # --- 内部辅助 ----------------------------------------------------------

    @staticmethod
    def _iou(a: List[int], b: List[int]) -> float:
        """计算两个 ``[x, y, w, h]`` 矩形的交并比 IoU。"""
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ix1 = max(ax, bx)
        iy1 = max(ay, by)
        ix2 = min(ax + aw, bx + bw)
        iy2 = min(ay + ah, by + bh)
        iw = ix2 - ix1
        ih = iy2 - iy1
        if iw <= 0 or ih <= 0:
            return 0.0
        inter = iw * ih
        union = aw * ah + bw * bh - inter
        if union <= 0:
            return 0.0
        return inter / union

    def _nms(
        self, candidates: List[MatchResult], iou_threshold: float = _DEFAULT_NMS_IOU
    ) -> List[MatchResult]:
        """对候选匹配做 NMS 去重。

        按 score 降序依次取最高分匹配保留，移除与之 IoU 超过阈值的其它匹配。
        """
        order = sorted(
            range(len(candidates)), key=lambda i: candidates[i].score, reverse=True
        )
        suppressed = [False] * len(candidates)
        kept: List[MatchResult] = []
        for pos, i in enumerate(order):
            if suppressed[i]:
                continue
            kept.append(candidates[i])
            for j in order[pos + 1:]:
                if suppressed[j]:
                    continue
                if self._iou(candidates[i].rect, candidates[j].rect) > iou_threshold:
                    suppressed[j] = True
        return kept

    # --- 主入口 ------------------------------------------------------------

    def analyze(self) -> List[MatchResult]:
        """执行多模板匹配。

        Returns
        -------
        list[MatchResult]
            所有匹配结果（已 NMS 去重），按 score 降序排列。
        """
        image = self._image
        template = self._template
        # 空图 / 空模板保护
        if image is None or getattr(image, "size", 0) == 0:
            return []
        if template is None or getattr(template, "size", 0) == 0:
            return []

        orig_h, orig_w = image.shape[:2]
        tpl_h, tpl_w = template.shape[:2]

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
            return []

        # 边界保护：模板大于 ROI 时无法匹配
        if tpl_w > (x1 - x0) or tpl_h > (y1 - y0):
            return []

        roi_img = image[y0:y1, x0:x1]

        # 模板匹配，得到分数图（尺寸 = roi - tpl + 1）
        score_map = cv2.matchTemplate(roi_img, template, cv2.TM_CCOEFF_NORMED)
        if score_map.size == 0:
            return []

        # 多峰值提取：用模板尺寸的核做膨胀，得到每个邻域内的最大值；
        # 原值等于膨胀值且超阈值的点即为局部峰值
        kernel = np.ones((tpl_h, tpl_w), dtype=np.uint8)
        dilated = cv2.dilate(score_map, kernel)
        peaks_mask = (score_map == dilated) & (score_map >= self._threshold)
        if not np.any(peaks_mask):
            return []

        ys, xs = np.where(peaks_mask)
        candidates: List[MatchResult] = []
        for py, px in zip(ys.tolist(), xs.tolist()):
            # 偏移回原图坐标系
            rect = [x0 + px, y0 + py, tpl_w, tpl_h]
            candidates.append(MatchResult(rect=rect, score=float(score_map[py, px])))

        # NMS 去重后按 score 降序返回
        kept = self._nms(candidates, iou_threshold=_DEFAULT_NMS_IOU)
        kept.sort(key=lambda r: r.score, reverse=True)
        return kept
