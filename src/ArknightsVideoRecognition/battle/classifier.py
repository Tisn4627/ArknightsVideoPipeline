"""技能就绪 / 部署方向分类器。

移植自 Maa ``BattlefieldClassifier``（``Vision/Battle/BattlefieldClassifier.cpp``）。

两个 ONNX 分类模型：

- ``skill_ready_cls.onnx``：3 分类，类别顺序为 ``c, n, y``（可关闭 / 未就绪 /
  就绪）。仅 ``class_id == 2``（y）时视为技能就绪。
- ``deploy_direction_cls.onnx``：4 分类，类别顺序为 ``Right, Down, Left, Up``。

预处理要点（与 Maa 一致）：

- skill_ready：先 resize 到 72x72（``INTER_CUBIC``），再中心裁剪 64x64，
  BGR->RGB /255 NCHW，最后按 ImageNet 均值方差归一化
  (mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])。
- deploy_direction：Maa 原版不 resize（其 ROI 经 ``BattleDeployDirectionRectMove``
  的 ``rectMove=[-48,-48,96,96]`` 恰为 96x96），BGR->RGB /255，**不做 ImageNet
  归一化**（与 skill_ready 不同）。本实现为兼容画面边缘裁剪不足 96x96 的情况，
  统一 resize 到模型输入 96x96，严格对齐 Maa 不做 ImageNet 归一化。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import onnxruntime as ort

from ArknightsVideoRecognition.config.settings import ONNX_DIR

# skill_ready 类别顺序：c, n, y（与 Maa 一致）
_SKILL_READY_LABELS = ("c", "n", "y")

# deploy_direction 类别顺序：Right, Down, Left, Up
_DEPLOY_DIR_LABELS = ("Right", "Down", "Left", "Up")

# ImageNet 归一化常量
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# skill_ready 预处理：Maa 先 resize 到 72 再中心裁剪 64
_SKILL_RESIZE = 72


class BattleClassifier:
    """技能就绪 / 部署方向分类器。

    Parameters
    ----------
    skill_ready_path:
        ``skill_ready_cls.onnx`` 路径，默认 ``ONNX_DIR / "skill_ready_cls.onnx"``。
    deploy_dir_path:
        ``deploy_direction_cls.onnx`` 路径，默认 ``ONNX_DIR / "deploy_direction_cls.onnx"``。
    """

    def __init__(
        self,
        skill_ready_path: Optional[str] = None,
        deploy_dir_path: Optional[str] = None,
    ):
        sr = Path(skill_ready_path) if skill_ready_path else ONNX_DIR / "skill_ready_cls.onnx"
        dd = Path(deploy_dir_path) if deploy_dir_path else ONNX_DIR / "deploy_direction_cls.onnx"

        self.skill_session = ort.InferenceSession(
            str(sr), providers=["CPUExecutionProvider"]
        )
        self.deploy_session = ort.InferenceSession(
            str(dd), providers=["CPUExecutionProvider"]
        )

        self.skill_input_name = self.skill_session.get_inputs()[0].name
        self.deploy_input_name = self.deploy_session.get_inputs()[0].name

        # 探测模型输入尺寸：skill_ready 64x64，deploy_direction 96x96
        sr_shape = self.skill_session.get_inputs()[0].shape  # ['batch_size',3,64,64]
        self.skill_h = int(sr_shape[2]) if len(sr_shape) >= 4 and isinstance(sr_shape[2], int) and sr_shape[2] > 0 else 64
        self.skill_w = int(sr_shape[3]) if len(sr_shape) >= 4 and isinstance(sr_shape[3], int) and sr_shape[3] > 0 else 64

        dd_shape = self.deploy_session.get_inputs()[0].shape  # [1,3,96,96]
        self.deploy_h = int(dd_shape[2]) if len(dd_shape) >= 4 and isinstance(dd_shape[2], int) and dd_shape[2] > 0 else 96
        self.deploy_w = int(dd_shape[3]) if len(dd_shape) >= 4 and isinstance(dd_shape[3], int) and dd_shape[3] > 0 else 96

    # --- 预处理 ------------------------------------------------------------

    def _preprocess_skill(self, patch: np.ndarray) -> np.ndarray:
        """resize->72 INTER_CUBIC，中心裁剪 64，ImageNet 归一化，NCHW。"""
        resized = cv2.resize(patch, (_SKILL_RESIZE, _SKILL_RESIZE), interpolation=cv2.INTER_CUBIC)
        crop = self.skill_h  # 与模型输入一致（64）
        x = (resized.shape[1] - crop) // 2
        y = (resized.shape[0] - crop) // 2
        cropped = resized[y:y + crop, x:x + crop]
        img = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img = (img - _IMAGENET_MEAN) / _IMAGENET_STD
        img = img.transpose(2, 0, 1)  # HWC -> CHW
        return np.expand_dims(img, 0)

    def _preprocess_deploy(self, patch: np.ndarray) -> np.ndarray:
        """对齐 Maa deploy_direction_analyze：BGR->RGB /255，NCHW，不做 ImageNet 归一化。

        Maa 原版 ROI 经 ``BattleDeployDirectionRectMove=[-48,-48,96,96]`` 恰为
        96x96，直接 image_to_tensor（BGR->RGB, HWC->CHW, /255），无 ImageNet
        归一化。本实现与 Maa 一致，不做 resize。
        """
        # Maa 的 image_to_tensor 不 resize；但为兼容画面边缘裁剪不足 96x96 的情况，
        # 统一 resize 到模型输入尺寸（96x96），与 Maa 关键逻辑一致（都不做 ImageNet 归一化）
        if patch.shape[0] != self.deploy_h or patch.shape[1] != self.deploy_w:
            patch = cv2.resize(
                patch, (self.deploy_w, self.deploy_h), interpolation=cv2.INTER_AREA
            )
        img = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img = img.transpose(2, 0, 1)  # HWC -> CHW
        return np.expand_dims(img, 0)

    # --- 工具 --------------------------------------------------------------

    @staticmethod
    def _softmax(x: np.ndarray) -> np.ndarray:
        x = x.astype(np.float64)
        x = x - np.max(x)
        e = np.exp(x)
        return e / np.sum(e)

    @staticmethod
    def _ensure_3ch(patch: np.ndarray) -> Optional[np.ndarray]:
        """保证 patch 为 3 通道 BGR。无效返回 None。"""
        if patch is None or patch.size == 0:
            return None
        if patch.ndim == 2:
            return cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
        if patch.shape[2] == 4:
            return cv2.cvtColor(patch, cv2.COLOR_BGRA2BGR)
        return patch

    # --- 主入口 ------------------------------------------------------------

    def classify_skill_ready(self, avatar_patch: np.ndarray) -> str:
        """对干员头像/技能小图分类，返回 ``"y"`` / ``"n"`` / ``"c"``。

        - ``y``：技能就绪
        - ``n``：未就绪
        - ``c``：可关闭（技能已开，可手动关闭）
        """
        patch = self._ensure_3ch(avatar_patch)
        if patch is None:
            return "n"
        inp = self._preprocess_skill(patch)
        out = self.skill_session.run(None, {self.skill_input_name: inp})[0]
        probs = self._softmax(np.asarray(out)[0])
        cls = int(np.argmax(probs))
        return _SKILL_READY_LABELS[cls]

    def classify_deploy_direction(self, avatar_patch: np.ndarray) -> tuple[str, np.ndarray]:
        """对干员小图分类部署方向，返回 (direction, raw_output)。

        对齐 Maa ``classify_direction``：无置信度阈值，永远返回 argmax 标签。

        - ``direction``：``"Right"`` / ``"Down"`` / ``"Left"`` / ``"Up"`` / ``"None"``
          （``"None"`` 仅在 patch 无效时返回）
        - ``raw_output``：4 类**原始模型输出**（未做 softmax），顺序对齐
          ``_DEPLOY_DIR_LABELS = ("Right", "Down", "Left", "Up")``。
          供下游软投票累加（严格对齐 Maa ``dir_cls_sampling[i] += raw[i]``，
          ``raw`` 是 DeployDirectionResult.raw 即 ONNX 原始输出，非 softmax）。
          argmax(raw) == argmax(softmax)，单帧方向判定不受影响；
          但多帧累加时 raw 与 softmax 结果可能不同（softmax 压缩动态范围）。
          patch 无效时返回全零数组。
        """
        patch = self._ensure_3ch(avatar_patch)
        if patch is None:
            return "None", np.zeros(4, dtype=np.float32)
        inp = self._preprocess_deploy(patch)
        out = self.deploy_session.run(None, {self.deploy_input_name: inp})[0]
        raw = np.asarray(out)[0].astype(np.float32)
        cls = int(np.argmax(raw))
        direction = _DEPLOY_DIR_LABELS[cls]
        return direction, raw
