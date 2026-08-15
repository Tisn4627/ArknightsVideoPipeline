"""模板检测+OCR 识别器：先模板匹配定位锚点，再相对锚点裁区域做 OCR。

对应 Maa C++ ``TemplDetOCRer``，串联 ``MultiMatcher`` + ``RegionOCRer``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

from arknights_video_recognition.config.roi import load_roi
from arknights_video_recognition.config.settings import TEMPLATE_DIR
from arknights_video_recognition.vision.multi_matcher import MultiMatcher, MatchResult
from arknights_video_recognition.vision.region_ocrer import RegionOCRer, RegionOcrResult


@dataclass
class TemplDetOcrResult:
    """单个模板检测+OCR 结果。

    Attributes
    ----------
    text:
        OCR 识别文本。
    rect:
        名字框 ``[x, y, w, h]``，在原图坐标系。
    flag_rect:
        小旗 ``[x, y, w, h]``，在原图坐标系。
    flag_score:
        小旗匹配分数，范围 ``[0, 1]``。
    """

    text: str
    rect: List[int]
    flag_rect: List[int]
    flag_score: float


class TemplDetOCRer:
    """模板检测+OCR 识别器。

    先用 ``MultiMatcher`` 在指定 ROI 内找所有模板（小旗），
    再对每个模板位置按偏移量裁出名字小条，用 ``RegionOCRer`` 预处理+OCR。
    """

    # ocrReplace 规则所在的基任务名，baseTask 链查找到此名即停止
    _OCR_REPLACE_BASE = "CharsNameOcrReplace"

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
        self._roi: Optional[List[int]] = None          # 搜索区域 [x,y,w,h]
        self._template: Optional[np.ndarray] = None    # 模板图像
        self._threshold: float = 0.6                    # 匹配阈值
        self._flag_rect_move: Optional[List[int]] = None  # 相对小旗的名字偏移 [dx,dy,w,h]
        # RegionOCRer 参数
        self._bin_threshold = 160
        self._bin_expansion = 3
        # 底部裁剪：Maa specialParams 用于去掉装饰线，但 RapidOCR 自带文本检测，
        # 裁掉底部会损伤汉字下半部分（如「杜」被裁后 OCR 误读为「+」），故设为 0
        self._bottom_line_height = 0
        self._width_threshold = 10
        self._replace_map: List = []
        self._replace_full: bool = False

    # --- 配置 -------------------------------------------------------------

    def set_task_info(self, templ_task_name: str, ocr_task_name: str) -> None:
        """从 ``roi.json`` 读两个 task 的配置。

        Parameters
        ----------
        templ_task_name:
            模板检测任务名（如 ``"BattleFormationOCRNameFlag"``）。
            取其 ``roi`` 作为搜索区域，取其模板（文件名=任务名.png）和 ``templThreshold``。
        ocr_task_name:
            OCR 任务名（如 ``"BattleFormationOperNames"``）。
            取其 ``roi`` 作为 ``flag_rect_move``（相对小旗的偏移量）。
            若其 baseTask 链含 ``CharsNameOcrReplace``，加载 ocrReplace 正则规则。
        """
        roi_data = load_roi()

        # --- 模板任务 ---
        templ_task = roi_data.get(templ_task_name) or {}
        self._roi = templ_task.get("roi")
        self._threshold = templ_task.get("templThreshold", 0.6)
        # 模板文件：文件名 = 任务名 + ".png"，在 TEMPLATE_DIR 下
        template_path = TEMPLATE_DIR / f"{templ_task_name}.png"
        self._template = cv2.imread(str(template_path))

        # --- OCR 任务 ---
        ocr_task = roi_data.get(ocr_task_name) or {}
        self._flag_rect_move = ocr_task.get("roi")  # [dx,dy,w,h] 相对偏移

        # 沿 baseTask 链向上查找 CharsNameOcrReplace 以加载 ocrReplace
        # ocr_task_name 自身可能就是 CharsNameOcrReplace，故先纳入链起点
        replace_task = self._find_replace_task(roi_data, ocr_task_name)
        if replace_task is not None:
            self._replace_map = replace_task.get("ocrReplace", []) or []
            self._replace_full = bool(replace_task.get("fullMatch", False))
        else:
            self._replace_map = []
            self._replace_full = False

    @classmethod
    def _find_replace_task(cls, roi_data: dict, task_name: str):
        """沿 ``baseTask`` 链递归查找 ``CharsNameOcrReplace`` 的任务定义。

        命中则返回该任务 dict，否则返回 None。带循环保护。
        """
        seen = set()
        name = task_name
        while name and name not in seen:
            seen.add(name)
            if name == cls._OCR_REPLACE_BASE:
                return roi_data.get(name)
            task = roi_data.get(name)
            if not isinstance(task, dict):
                return None
            name = task.get("baseTask")
        return None

    def set_threshold(self, threshold: float) -> None:
        """覆盖模板匹配阈值。"""
        self._threshold = float(threshold)

    def set_bin_expansion(self, expansion: int) -> None:
        """覆盖二值化膨胀像素数。"""
        self._bin_expansion = int(expansion)

    # --- 主入口 -----------------------------------------------------------

    def analyze(self) -> List[TemplDetOcrResult]:
        """执行模板检测 + OCR。

        Returns
        -------
        list[TemplDetOcrResult]
            所有识别结果（每个小旗一个，OCR 失败的跳过）。
        """
        if self._template is None or self._roi is None or self._flag_rect_move is None:
            return []

        # 第一步：MultiMatcher 在搜索 ROI 内找所有小旗
        matcher = MultiMatcher(self._image, roi=self._roi)
        matcher.set_template(self._template, threshold=self._threshold)
        matches: List[MatchResult] = matcher.analyze()
        if not matches:
            return []

        # 第二步：对每个小旗位置按 flag_rect_move 偏移裁名字小条做 OCR
        dx, dy, w, h = self._flag_rect_move
        results: List[TemplDetOcrResult] = []
        for match in matches:
            fx, fy, _fw, _fh = match.rect
            # 名字 ROI = 小旗左上角 + 偏移量；宽高直接取用 flag_rect_move 的 w/h
            name_roi = [fx + dx, fy + dy, w, h]
            # 关键：名字小条从全帧裁剪（传完整 image），不是从 ROI 子图裁，
            # 避免 ROI 高度不足截断底行名字
            region_ocrer = RegionOCRer(self._image, self._ocr_engine)
            region_ocrer.set_roi(name_roi)
            region_ocrer.set_bin_threshold(self._bin_threshold)
            region_ocrer.set_bin_expansion(self._bin_expansion)
            region_ocrer.set_bottom_line_height(self._bottom_line_height)
            region_ocrer.set_width_threshold(self._width_threshold)
            if self._replace_map:
                region_ocrer.set_replace(self._replace_map, self._replace_full)
            ocr_result: Optional[RegionOcrResult] = region_ocrer.analyze()
            if ocr_result is None:
                continue
            results.append(TemplDetOcrResult(
                text=ocr_result.text,
                rect=ocr_result.rect,
                flag_rect=match.rect,
                flag_score=match.score,
            ))
        return results
