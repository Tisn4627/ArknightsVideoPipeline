"""进入战斗检测（battlestart 模式）

与 MAA 的 BattleHasStarted 判定思路一致：进入战斗后，屏幕右上角会出现
「暂停」按钮，该区域在灰度图中表现为大片亮像素。本模块通过暂停按钮
ROI 的亮像素占比阈值来判定进入战斗的时机，返回时间戳供后续步骤使用。

battlestart 模式不依赖 StartButton 模板资源，仅需纯 OpenCV 操作。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import cv2
import numpy as np

# tqdm 为可选依赖：存在时显示进度条，缺失时回退到普通日志输出
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

logger = logging.getLogger(__name__)

# 识别模式常量
TRACK_MODE_STARTBUTTON = "startbutton"   # 开始按钮识别（原 track 步骤行为）
TRACK_MODE_BATTLESTART = "battlestart"   # 战斗开始识别（暂停按钮 ROI 阈值法）
TRACK_MODES = (TRACK_MODE_STARTBUTTON, TRACK_MODE_BATTLESTART)

# battle_start 子配置默认值
BATTLE_START_DEFAULTS = {
    "time_limit": 30,              # 检测时间限制（秒），仅检测视频前 N 秒
    "min_consecutive_frames": 2,   # 连续命中最少采样帧数，低于此数不视为有效
    "debug_mode": True,            # 调试模式，输出逐帧诊断信息
}

# 暂停按钮 ROI（相对坐标 x1, y1, x2, y2）
# 以 1080P 实测为基准：暂停按钮（两道竖杠图标）位于右上角
# x[1772,1815] y[59,99]，ROI 取 x 1755~1830、y 45~110 留出余量；
# 按相对比例适配任意分辨率（含自动降分辨率后的 720P）
PAUSE_BTN_ROI = (0.914, 0.042, 0.953, 0.102)

# ROI 内亮像素占比判定阈值：占比超过该值视为暂停按钮出现
# 实测战斗画面约 0.29，备战/加载画面 < 0.02（个别加载闪烁帧约 0.12），
# 取 0.15 兼顾灵敏度与抗误报
DEFAULT_BRIGHTNESS_RATIO_THRESHOLD = 0.15

# 亮像素亮度下限（0~255）
DEFAULT_BRIGHTNESS_VALUE_THRESHOLD = 200


def _brightness_stats(frame_gray: np.ndarray, bs_cfg: dict[str, Any]) -> tuple[int, int, float]:
    """计算暂停按钮 ROI 亮像素统计，返回 (亮像素数, ROI 总像素数, 亮像素占比)"""
    value_threshold = int(bs_cfg.get(
        "brightness_value_threshold", DEFAULT_BRIGHTNESS_VALUE_THRESHOLD
    ))
    h, w = frame_gray.shape[:2]
    if h <= 0 or w <= 0:
        return 0, 0, 0.0
    x1, y1, x2, y2 = PAUSE_BTN_ROI
    roi = frame_gray[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
    total = int(roi.size)
    if total == 0:
        return 0, 0, 0.0
    bright_count = int(np.count_nonzero(roi >= value_threshold))
    return bright_count, total, bright_count / total


def analyze_pause_roi(frame_gray: np.ndarray, bs_cfg: dict[str, Any]) -> tuple[bool, int, int]:
    """分析单帧的暂停按钮 ROI

    返回 (是否命中, 亮像素数, ROI 总像素数)。命中条件为亮像素占比超过阈值。
    """
    bright_count, total, ratio = _brightness_stats(frame_gray, bs_cfg)
    threshold = float(bs_cfg.get(
        "brightness_ratio_threshold", DEFAULT_BRIGHTNESS_RATIO_THRESHOLD
    ))
    return ratio >= threshold, bright_count, total


def scan_battle_start(
    cap: Any,
    bs_cfg: dict[str, Any],
    fps: float,
    total_frames: int,
    duration: float,
    sample_interval: int,
    effective_time_limit: float | None,
    debug_mode: bool,
    video_scale_ratio: float,
    was_downscaled: bool,
) -> dict[str, Any]:
    """battlestart 模式主循环：在检测时间窗口内逐采样帧分析暂停按钮 ROI

    返回与 track 步骤一致的识别结果字典，附带 battle_start_* 键。
    """
    min_consecutive = max(1, int(bs_cfg.get(
        "min_consecutive_frames", BATTLE_START_DEFAULTS["min_consecutive_frames"]
    )))
    detection_end_frame = (
        int(effective_time_limit * fps) if effective_time_limit is not None
        else total_frames
    )
    processed_frames = len(range(0, detection_end_frame, sample_interval))
    diagnostic_interval = max(1, int(fps))

    battle_start_time = None
    battle_start_frame = 0
    consecutive_hits = 0
    hit_count = 0
    max_ratio = 0.0
    frame_idx = 0
    processed_idx = 0
    start_time = time.time()

    logger.info(
        f"战斗开始检测: 暂停按钮 ROI 亮像素阈值法 "
        f"(最少连续命中 {min_consecutive} 个采样帧)"
    )

    pbar = tqdm(
        total=processed_frames, desc="识别进度", unit="帧",
        ncols=80,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
    ) if tqdm is not None else None
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx >= detection_end_frame:
                break

            current_time = frame_idx / fps
            if frame_idx % sample_interval != 0:
                frame_idx += 1
                continue

            processed_idx += 1
            if frame.ndim == 3:
                frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                frame_gray = frame

            _, _, ratio = _brightness_stats(frame_gray, bs_cfg)
            hit = ratio >= float(bs_cfg.get(
                "brightness_ratio_threshold", DEFAULT_BRIGHTNESS_RATIO_THRESHOLD
            ))
            if ratio > max_ratio:
                max_ratio = ratio

            if hit:
                consecutive_hits += 1
                hit_count += 1
                if battle_start_time is None and consecutive_hits >= min_consecutive:
                    battle_start_frame = frame_idx - (min_consecutive - 1) * sample_interval
                    battle_start_time = current_time - (min_consecutive - 1) * sample_interval / fps
                    msg = (
                        f"[{current_time:.2f}s] 检测到进入战斗! "
                        f"(暂停按钮亮像素比:{ratio:.3f})"
                    )
                    if pbar:
                        pbar.write(msg)
                    else:
                        logger.info(msg)
            else:
                consecutive_hits = 0

            # 诊断输出
            if debug_mode and processed_idx % diagnostic_interval == 0 and processed_idx > 0:
                threshold = bs_cfg.get(
                    "brightness_ratio_threshold", DEFAULT_BRIGHTNESS_RATIO_THRESHOLD
                )
                msg = (
                    f"  [诊断] 帧{frame_idx} 亮像素比:{ratio:.3f} "
                    f"(阈值:{threshold}) {'[命中]' if hit else '[未达]'}"
                )
                if pbar:
                    pbar.write(msg)
                else:
                    logger.info(msg)

            # 更新进度条
            if pbar:
                pbar.update(1)
            elif processed_idx % 100 == 0 and processed_idx > 0:
                elapsed = time.time() - start_time
                progress = processed_idx / processed_frames * 100
                speed = processed_idx / elapsed if elapsed > 0 else 0
                logger.info(
                    f"  进度: {progress:.1f}% ({processed_idx}/{processed_frames}) "
                    f"{speed:.1f}帧/s 已用时{elapsed:.1f}s"
                )

            frame_idx += 1
    finally:
        if pbar is not None:
            pbar.close()

    elapsed_total = time.time() - start_time
    avg_speed = processed_frames / elapsed_total if elapsed_total > 0 else 0

    if battle_start_time is None:
        logger.info(
            f"\n未在检测时间范围内检测到进入战斗 (最高亮像素比: {max_ratio:.3f})"
        )
    else:
        logger.info(
            f"\n进入战斗时间: {battle_start_time:.2f}s "
            f"(第{battle_start_frame}帧, 亮像素比:{max_ratio:.3f})"
        )

    return {
        "track_mode": TRACK_MODE_BATTLESTART,
        "battle_start_time": round(battle_start_time, 2) if battle_start_time is not None else None,
        "battle_start_frame": battle_start_frame,
        "battle_start_max_ratio": round(max_ratio, 4),
        "battle_start_detected": battle_start_time is not None,
        # 与 startbutton 模式对齐的通用字段（battlestart 无出现/消失概念）
        "first_appear_time": None,
        "disappear_time": None,
        "duration_visible": None,
        "max_confidence": round(max_ratio, 4),
        "global_best_confidence": round(max_ratio, 4),
        "global_best_frame": battle_start_frame,
        "match_count": hit_count,
        "was_detected": battle_start_time is not None,
        "was_downscaled": was_downscaled,
        "scale_ratio": round(video_scale_ratio, 4),
        "video_duration": round(duration, 2),
        "detection_time_limit": effective_time_limit,
        "processing_time": round(elapsed_total, 2),
        "avg_speed_fps": round(avg_speed, 2),
    }
