"""YOLOv8 干员检测器。

移植自 Maa ``BattlefieldDetector``（``Vision/Battle/BattlefieldDetector.cpp``）。
用 onnxruntime 加载 ``operators_det.onnx``（YOLOv8，1 类 "operator"），
对战场帧做检测，返回场上干员头像框列表。

预处理要点（与 Maa 一致，保证模型输入分布与训练时相同）：

- 直接 stretch resize 到模型输入尺寸（640x640），用 ``INTER_AREA``。
  Maa 原版即用拉伸缩放（非 letterbox），模型也以此方式训练，故此处沿用
  拉伸缩放以保证检测精度。坐标还原按 ``原图/640`` 线性缩放即可。
- BGR -> RGB，归一化到 0-1，HWC -> NCHW。

后处理：YOLOv8 输出形如 ``[1, 5, 8400]``（1 类时 ``4+nc=5``），
5 个通道依次为 ``cx, cy, w, h, conf``，共 8400 个 anchor。按置信度阈值
过滤后做 NMS，再把 ``cx,cy,w,h`` 还原回原图坐标系。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
import onnxruntime as ort

from arknights_video_recognition.config.settings import ONNX_DIR


@dataclass
class Detection:
    """单个干员检测结果。

    Attributes
    ----------
    box:
        ``[x, y, w, h]``，左上角坐标 + 宽高（原图坐标系）。
    score:
        置信度（0-1）。
    class_id:
        类别 id（恒为 0，"operator"）。
    """

    box: List[int]
    score: float
    class_id: int


class OperatorDetector:
    """YOLOv8 干员头像框检测器。

    Parameters
    ----------
    model_path:
        ``operators_det.onnx`` 路径。为 ``None`` 时取
        ``settings.ONNX_DIR / "operators_det.onnx"``。
    """

    def __init__(self, model_path: Optional[str] = None):
        path = Path(model_path) if model_path else ONNX_DIR / "operators_det.onnx"
        # 仅用 CPU 提供器，避免沙箱无 GPU/CUDA 时报错
        self.session = ort.InferenceSession(
            str(path), providers=["CPUExecutionProvider"]
        )

        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        # 输入形如 [1, 3, 640, 640]（固定尺寸）
        shape = inp.shape
        self.input_h = int(shape[2]) if len(shape) >= 4 and isinstance(shape[2], int) and shape[2] > 0 else 640
        self.input_w = int(shape[3]) if len(shape) >= 4 and isinstance(shape[3], int) and shape[3] > 0 else 640

        self.output_name = self.session.get_outputs()[0].name

    # --- 预处理 ------------------------------------------------------------

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        """拉伸缩放到模型输入尺寸，BGR->RGB，归一化 0-1，转 NCHW。"""
        img = cv2.resize(
            frame, (self.input_w, self.input_h), interpolation=cv2.INTER_AREA
        )
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = img.transpose(2, 0, 1)  # HWC -> CHW
        img = np.expand_dims(img, 0)  # -> NCHW
        return np.ascontiguousarray(img)

    # --- 后处理 ------------------------------------------------------------

    @staticmethod
    def _nms(
        boxes: np.ndarray, scores: np.ndarray, iou_threshold: float
    ) -> List[int]:
        """单类 NMS。

        ``boxes`` 为 ``[N, 4]`` 的 ``xywh``（左上角 + 宽高）。
        返回保留的下标列表（按分数降序）。
        """
        if boxes.shape[0] == 0:
            return []
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 0] + boxes[:, 2]
        y2 = boxes[:, 1] + boxes[:, 3]
        areas = boxes[:, 2] * boxes[:, 3]

        order = scores.argsort()[::-1]
        keep: List[int] = []
        while order.size > 0:
            i = int(order[0])
            keep.append(i)
            if order.size == 1:
                break
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            inter_w = np.maximum(0.0, xx2 - xx1)
            inter_h = np.maximum(0.0, yy2 - yy1)
            inter = inter_w * inter_h
            union = areas[i] + areas[order[1:]] - inter + 1e-9
            iou = inter / union
            inds = np.where(iou <= iou_threshold)[0]
            order = order[inds + 1]
        return keep

    # --- 主入口 ------------------------------------------------------------

    def detect(
        self,
        frame: np.ndarray,
        conf_threshold: float = 0.3,
        iou_threshold: float = 0.45,
    ) -> List[Detection]:
        """对战场帧做 YOLOv8 检测，返回干员头像框列表。

        Parameters
        ----------
        frame:
            战场帧（numpy BGR）。
        conf_threshold:
            置信度阈值，低于此值的框被丢弃。对齐 Maa 原版默认 0.3。
        iou_threshold:
            NMS 的 IoU 阈值。
        """
        if frame is None or frame.size == 0:
            return []

        orig_h, orig_w = frame.shape[:2]
        inp = self._preprocess(frame)
        out = self.session.run([self.output_name], {self.input_name: inp})[0]

        # 输出形如 [1, 5, 8400]：5 个通道 = cx, cy, w, h, conf
        out = np.asarray(out)
        # -> [5, N] -> [N, 5]
        preds = out[0].T  # [N, 5]

        if preds.shape[1] < 5:
            return []

        conf = preds[:, 4]
        mask = conf >= conf_threshold
        preds = preds[mask]
        if preds.shape[0] == 0:
            return []

        # 还原到原图坐标系
        sx = orig_w / self.input_w
        sy = orig_h / self.input_h
        cx = preds[:, 0] * sx
        cy = preds[:, 1] * sy
        w = preds[:, 2] * sx
        h = preds[:, 3] * sy
        scores = preds[:, 4]

        # cx,cy,w,h -> 左上角 x,y,w,h
        x = cx - w / 2.0
        y = cy - h / 2.0
        boxes = np.stack([x, y, w, h], axis=1)

        keep = self._nms(boxes, scores, iou_threshold)

        results: List[Detection] = []
        for i in keep:
            bx, by, bw, bh = boxes[i]
            # 裁剪到画面范围
            x0 = max(0, int(round(bx)))
            y0 = max(0, int(round(by)))
            x1 = min(orig_w, int(round(bx + bw)))
            y1 = min(orig_h, int(round(by + bh)))
            results.append(
                Detection(
                    box=[x0, y0, x1 - x0, y1 - y0],
                    score=float(scores[i]),
                    class_id=0,
                )
            )
        return results
