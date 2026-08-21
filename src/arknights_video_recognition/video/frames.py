"""视频抽帧封装。

用 :class:`cv2.VideoCapture` 打开战斗录像，把每一帧统一 resize 到标准
分辨率（默认 1280x720，便于后续 ROI 定位），并提供按时间间隔采样、取指定
时间点帧等能力。

对应原 Maa ``CombatRecordRecognitionTask`` 中对 ``cv::VideoCapture`` 的
逐帧读取与 ``cv::resize(..., scale, INTER_AREA)`` 处理。
"""

from __future__ import annotations

import ctypes
import os
from collections import OrderedDict
from typing import Iterator, Optional, Tuple

import cv2
import numpy as np

from ..config.settings import DEFAULT_RESOLUTION

# 默认插值方法：抽帧把画面缩小到标准分辨率时用 INTER_AREA，避免摩尔纹。
_DEFAULT_INTERP = cv2.INTER_AREA

# 帧缓存上限（LRU）：每帧 1280x720x3 ≈ 2.6MB，32 帧 ≈ 84MB。
# 不设上限或上限过大（如 500 帧 ≈ 1.3GB）易在长视频 track 步中耗尽内存
_FRAME_CACHE_SIZE = 32


def _get_short_path(path: str) -> Optional[str]:
    """返回 Windows 8.3 短路径；非 Windows 或转换失败返回 None。

    cv2.VideoCapture 对非 ASCII 路径的兼容性依 OpenCV 构建/后端而异，
    打开失败时用短路径重试是与 MAA 后端一致的兜底方案。
    """
    if os.name != "nt":
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))
        if 0 < n < len(buf):
            return buf.value
    except Exception:
        pass
    return None


class VideoFrames:
    """战斗录像抽帧器。

    Parameters
    ----------
    video_path:
        视频文件路径。
    resolution:
        输出帧的目标分辨率 ``(width, height)``。传 ``None`` 则保留原始
        尺寸不做 resize。默认 :data:`DEFAULT_RESOLUTION` (1280, 720)。
    sample_fps:
        可选的默认采样帧率（Hz）。仅作为参考存储，具体采样由
        :meth:`sample` 的 ``interval_sec`` 决定。

    Raises
    ------
    ValueError
        视频无法打开时抛出。
    """

    def __init__(
        self,
        video_path: str,
        resolution: Optional[Tuple[int, int]] = DEFAULT_RESOLUTION,
        sample_fps: Optional[float] = None,
    ) -> None:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            # Windows 非 ASCII 路径兜底：取 8.3 短路径重试一次
            short = _get_short_path(video_path)
            if short and short != video_path:
                cap = cv2.VideoCapture(short)
        if not cap.isOpened():
            raise ValueError(f"无法打开视频文件: {video_path}")

        self._cap = cap
        self.video_path = video_path

        # 原始视频属性
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        # 个别视频元数据缺失时 fps 可能为 0，按 0 处理（按时间采样会退化）
        self._fps = fps if fps > 0 else 0.0
        self._source_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._source_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._source_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # 目标输出分辨率
        if resolution is None:
            self._target_w = self._source_width
            self._target_h = self._source_height
            self._resize = False
        else:
            self._target_w, self._target_h = int(resolution[0]), int(resolution[1])
            self._resize = not (
                self._target_w == self._source_width
                and self._target_h == self._source_height
            )

        self.sample_fps = sample_fps

        # 帧缓存：避免对同一时间点反复 seek。
        # key=frame_idx, value=postprocessed frame；OrderedDict 实现
        # 小容量 LRU（见 _FRAME_CACHE_SIZE 说明）
        self._frame_cache: "OrderedDict[int, np.ndarray]" = OrderedDict()
        # 当前 VideoCapture 位置（帧索引），用于判断是否可顺序读取
        self._cur_pos: int = 0

    # --- 属性 ----------------------------------------------------------------

    @property
    def fps(self) -> float:
        """原始视频帧率（Hz）。"""
        return self._fps

    @property
    def frame_count(self) -> int:
        """原始视频总帧数。"""
        return self._source_frame_count

    @property
    def duration_sec(self) -> float:
        """视频时长（秒）。fps 或帧数缺失时返回 0。"""
        if self._fps > 0 and self._source_frame_count > 0:
            return self._source_frame_count / self._fps
        return 0.0

    @property
    def width(self) -> int:
        """输出帧宽度。"""
        return self._target_w

    @property
    def height(self) -> int:
        """输出帧高度。"""
        return self._target_h

    @property
    def source_width(self) -> int:
        """原始视频宽度。"""
        return self._source_width

    @property
    def source_height(self) -> int:
        """原始视频高度。"""
        return self._source_height

    # --- 内部辅助 ------------------------------------------------------------

    def _postprocess(self, frame: np.ndarray) -> np.ndarray:
        """按目标分辨率 resize（必要时）。"""
        if self._resize and frame.size > 0:
            frame = cv2.resize(
                frame,
                (self._target_w, self._target_h),
                interpolation=_DEFAULT_INTERP,
            )
        return frame

    def _set_pos_frames(self, frame_index: int) -> None:
        """定位到指定帧索引。"""
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(max(0, frame_index)))
        self._cur_pos = max(0, frame_index)

    # --- 公开 API ------------------------------------------------------------

    def __iter__(self) -> Iterator[Tuple[int, np.ndarray]]:
        """逐帧迭代，返回 ``(frame_index, frame_bgr)``。

        从第 0 帧开始顺序读取到结尾，每帧 resize 到目标分辨率。
        """
        if self._cap is None:
            # release() 后再访问：优雅终止而非 AttributeError
            return
        self._set_pos_frames(0)
        idx = 0
        while True:
            ok, frame = self._cap.read()
            if not ok or frame is None:
                break
            yield idx, self._postprocess(frame)
            idx += 1

    def sample(self, interval_sec: float = 1.0) -> Iterator[Tuple[float, np.ndarray]]:
        """按时间间隔采样帧。

        从 ``t=0`` 开始，每隔 ``interval_sec`` 秒取一帧，返回生成器
        ``(timestamp_sec, frame_bgr)``。最后一帧不超过视频时长。

        采用**顺序读取+跳帧**而非逐帧 seek，避免压缩视频反复 seek
        导致的严重性能下降（seek 需从最近关键帧解码到目标帧）。

        Parameters
        ----------
        interval_sec:
            采样间隔（秒），必须 > 0。
        """
        if interval_sec <= 0:
            raise ValueError("interval_sec 必须 > 0")
        if self._cap is None:
            # release() 后再访问：优雅终止而非 AttributeError
            return

        duration = self.duration_sec
        # fps 缺失时退化为单帧
        if self._fps <= 0:
            frame = self.get_frame_at(0.0)
            if frame is not None:
                yield 0.0, frame
            return

        step = max(1, int(round(self._fps * interval_sec)))
        total = self._source_frame_count

        # 顺序读取：从头开始，每 step 帧取一帧，中间帧用 read 丢弃
        self._set_pos_frames(0)
        frame_idx = 0
        while True:
            if total > 0 and frame_idx >= total:
                break
            ts = frame_idx / self._fps
            if duration > 0 and ts > duration + 1e-6:
                break
            ok, frame = self._cap.read()
            if not ok or frame is None:
                break
            self._cur_pos = frame_idx + 1
            frame = self._postprocess(frame)
            yield ts, frame
            # 跳过 (step - 1) 帧到下一个采样点
            for _ in range(step - 1):
                ok, _ = self._cap.read()
                if not ok:
                    break
                self._cur_pos += 1
            frame_idx += step

    def sample_range(
        self,
        start_ts: float,
        end_ts: float,
        interval_sec: float = 1.0,
    ) -> Iterator[Tuple[float, np.ndarray]]:
        """从 ``start_ts`` 到 ``end_ts`` 按间隔采样，顺序读取避免 seek。

        与 :meth:`sample` 类似，但从指定起始时间开始，到指定结束时间停止。
        采用顺序读取+跳帧，避免压缩视频反复 seek 的性能问题。
        """
        if interval_sec <= 0 or self._fps <= 0:
            return
        if self._cap is None:
            # release() 后再访问：优雅终止而非 AttributeError
            return
        step = max(1, int(round(self._fps * interval_sec)))
        start_idx = max(0, int(round(start_ts * self._fps)))
        total = self._source_frame_count
        duration = self.duration_sec
        # 定位到起始帧（仅 seek 一次）
        self._set_pos_frames(start_idx)
        frame_idx = start_idx
        while True:
            if total > 0 and frame_idx >= total:
                break
            ts = frame_idx / self._fps
            if ts > end_ts + 1e-6:
                break
            if duration > 0 and ts > duration + 1e-6:
                break
            ok, frame = self._cap.read()
            if not ok or frame is None:
                break
            self._cur_pos = frame_idx + 1
            frame = self._postprocess(frame)
            yield ts, frame
            for _ in range(step - 1):
                ok, _ = self._cap.read()
                if not ok:
                    break
                self._cur_pos += 1
            frame_idx += step

    def get_frame_at(self, timestamp_sec: float) -> Optional[np.ndarray]:
        """取指定时间点（秒）的帧，已 resize 到目标分辨率。

        超出视频范围或读取失败时返回 ``None``。

        优化：带帧缓存 + 顺序读取。当目标帧在当前 capture 位置之前或
        距离较远时才 seek；否则顺序 read 跳帧到达目标，避免压缩视频
        seek（从关键帧解码）的高开销。
        """
        if timestamp_sec < 0:
            return None
        if self._cap is None:
            # release() 后再访问：返回 None 而非 AttributeError
            return None
        if self._fps <= 0:
            frame_idx = 0
        else:
            frame_idx = int(round(timestamp_sec * self._fps))
            total = self._source_frame_count
            if total > 0 and frame_idx >= total:
                frame_idx = total - 1

        # 缓存命中（LRU：命中后移到最新端）
        cached = self._frame_cache.pop(frame_idx, None)
        if cached is not None:
            self._frame_cache[frame_idx] = cached
            return cached

        # 决定是否 seek：目标在当前位置之前，或距离太远（>30帧）时 seek
        # 否则顺序读取（read 跳帧），大幅减少 seek 开销
        if self._cur_pos > frame_idx or (frame_idx - self._cur_pos) > 30:
            self._set_pos_frames(frame_idx)
            self._cur_pos = frame_idx
        else:
            # 顺序读取到目标帧
            while self._cur_pos < frame_idx:
                ok, _ = self._cap.read()
                if not ok:
                    return None
                self._cur_pos += 1

        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        self._cur_pos = frame_idx + 1
        frame = self._postprocess(frame)
        # 写入缓存并按 LRU 淘汰最旧帧
        self._frame_cache[frame_idx] = frame
        if len(self._frame_cache) > _FRAME_CACHE_SIZE:
            self._frame_cache.popitem(last=False)
        return frame

    def release(self) -> None:
        """释放底层 VideoCapture 资源。"""
        if self._cap is not None:
            self._cap.release()
            self._cap = None  # type: ignore[assignment]

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass
