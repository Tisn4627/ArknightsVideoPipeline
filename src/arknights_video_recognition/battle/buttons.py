"""检测暂停/加速按钮是否存在（对齐 Maa 二值化阈值法）。

Maa 的 ``BattlefieldMatcher::pause_button_analyze`` /
``speed_button_analyze`` 在固定 ROI 上做灰度二值化，统计亮像素数。
玩家点开干员详情页时，两个按钮都被详情页遮挡，亮像素数低于阈值，
据此判定 ``oper_is_clicked``（详情页已打开）。

参考：``maa_research/vision/BattlefieldMatcher.cpp`` 第 443-524 行。
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from arknights_video_recognition.config.settings import (
    BATTLE_PAUSE_COUNT_THR,
    BATTLE_PAUSE_ROI,
    BATTLE_PAUSE_VALUE_THR,
    BATTLE_SPEED_COUNT_THR,
    BATTLE_SPEED_ROI,
    BATTLE_SPEED_VALUE_THR,
)

logger = logging.getLogger(__name__)


class BattleButtonDetector:
    """检测暂停/加速按钮是否存在。

    检测逻辑忠实移植 Maa BattlefieldMatcher 的二值化阈值法，不使用模板。
    所有 ROI/阈值常量取自 :mod:`settings`，对齐 Maa tasks.json。
    """

    def has_pause(self, frame: np.ndarray) -> bool:
        """暂停按钮是否存在（任务 BattleHasStarted）。

        Parameters
        ----------
        frame:
            BGR 帧，目标分辨率 1280x720。

        Returns
        -------
        bool
            ROI 内亮像素数 > 阈值时为 True（按钮存在）。
        """
        roi_gray = self._roi_gray(frame, BATTLE_PAUSE_ROI)
        if roi_gray is None:
            return False
        _, bin_img = cv2.threshold(
            roi_gray, BATTLE_PAUSE_VALUE_THR, 255, cv2.THRESH_BINARY
        )
        return cv2.countNonZero(bin_img) > BATTLE_PAUSE_COUNT_THR

    def has_speed(self, frame: np.ndarray) -> bool:
        """加速按钮是否存在（任务 BattleSpeedButton）。"""
        roi_gray = self._roi_gray(frame, BATTLE_SPEED_ROI)
        if roi_gray is None:
            return False
        _, bin_img = cv2.threshold(
            roi_gray, BATTLE_SPEED_VALUE_THR, 255, cv2.THRESH_BINARY
        )
        return cv2.countNonZero(bin_img) > BATTLE_SPEED_COUNT_THR

    def is_detail_page_open(self, frame: np.ndarray) -> bool:
        """详情页是否打开（任意一个按钮消失）。

        对齐 Maa::

            oper_is_clicked = !speed_button || !pause_button

        fail-closed：无效帧/ROI 越界时返回 False（视为详情页未打开）。
        旧实现返回 True，会让切片器把普通战斗帧当详情页、误触发
        ends_oper_name OCR；按钮检测失败（has_* 返回 False）同样按
        未打开处理并记日志便于发现配置问题。

        Parameters
        ----------
        frame:
            BGR 帧。为 None 或空时返回 False。
        """
        if frame is None or frame.size == 0:
            return False
        has_speed = self.has_speed(frame)
        has_pause = self.has_pause(frame)
        if not (has_speed and has_pause):
            # 区分"按钮真的消失（详情页打开）"与"ROI 检测失败"：
            # _roi_gray 返回 None 时两个按钮都测不到，此时不能断言打开
            speed_roi = self._roi_gray(frame, BATTLE_SPEED_ROI)
            pause_roi = self._roi_gray(frame, BATTLE_PAUSE_ROI)
            if speed_roi is None or pause_roi is None:
                logger.warning("详情页按钮 ROI 越界或帧无效，按未打开处理")
                return False
        return not has_speed or not has_pause

    @staticmethod
    def _roi_gray(
        frame: np.ndarray, roi: list
    ) -> np.ndarray | None:
        """裁剪 ROI 并转灰度，越界或空帧返回 None。"""
        if frame is None or frame.size == 0:
            return None
        x, y, w, h = roi
        H, W = frame.shape[:2]
        if x < 0 or y < 0 or x + w > W or y + h > H:
            return None
        roi_img = frame[y:y + h, x:x + w]
        return cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
