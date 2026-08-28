"""按部署栏变化把战斗录像切片（严格对齐 Maa slice_video）。

Maa ``CombatRecordRecognitionTask::slice_video``（CombatRecordRecognitionTask.cpp:303-479）
以约 5Hz 采样，每帧调 ``BattlefieldMatcher.analyze()`` 取得部署栏、暂停/加速按钮、
击杀数。切片触发条件：

1. 玩家打开干员详情页（``oper_is_clicked``：暂停或加速按钮消失）——关闭片段；
2. 部署栏数量变化（``oper_auto_retreat``：撤退或部署）——关闭片段；
3. 部署栏连续性恢复且不在片段中——开新片段；
4. 连续性破坏（过渡帧）——跳过。

关键时序对齐点（本模块核心）：

- **end_time = 前一采样时刻**：Maa ``pre_clip.end_frame = pre_frame``（变更帧的
  *前一* 采样帧）。详情页打开帧上技能图标被遮挡，必须用前一帧检查 pre_ready
  （compare_skill 用 pre_clip.end_frame 做技能就绪检测）。
- **ends_oper_name 持续重试**：Maa 在后续 ``oper_is_clicked`` 帧上持续尝试 OCR
  ``pre_clip.ends_oper_name`` 直到非空（``if (pre_clip.ends_oper_name.empty())``），
  因为详情页加载需要几帧。本实现同样在关闭片段后继续重试。
- **start_time += 300ms 偏移**：Maa 后处理 ``clip.start_frame_index += offset_frame``
  （offset_ms=300）。compare_skill 在 ``start + 500ms`` 检查 cur_ready，加上
  300ms 偏移共 800ms，跳过技能图标消失动画。

后处理：去掉 ``start>=end`` 退化片段，用 role 序列比较相邻片段设置
``deployment_changed``（对齐 Maa，用 role 而非 name）。

参考：``maa_research/CombatRecordRecognitionTask.cpp`` 第 303-479 行。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from .frames import VideoFrames

logger = logging.getLogger(__name__)

# 采样间隔（秒）。Maa deployment_fps=5 ≈ 0.2s。
_DEFAULT_SAMPLE_INTERVAL = 0.2

# Maa slice_video 后处理 offset_ms=300（CombatRecordRecognitionTask.cpp:437）
_START_OFFSET_SEC = 0.3


@dataclass
class Clip:
    """切片产物：对应一次部署/撤退/技能变化的视频片段。

    Attributes
    ----------
    start_time:
        片段起始时间（秒，含 300ms 偏移，对齐 Maa start_frame_index+offset_frame）。
    end_time:
        片段结束时间（秒，= 变更帧的*前一*采样时刻，对齐 Maa end_frame=pre_frame）。
    key_frame:
        代表帧（BGR numpy 数组），取片段起始处画面（原始开段帧，无偏移）。
    frame_index:
        代表帧在原始视频中的帧索引。
    deployment:
        部署栏快照（list[dict]，来自 DeploymentAnalyzer.detect_slots）。
        每个 dict 含 flag_pos/avatar/box/role。
    deployment_changed:
        后处理设置：本片段的部署栏 role 序列是否与前一片段不同。
    ends_oper_name:
        详情页打开时的干员名（后续 oper_is_clicked 帧持续 OCR 直到非空）。
    """

    start_time: float
    end_time: float
    key_frame: Optional[np.ndarray] = None
    frame_index: int = 0
    deployment: list = field(default_factory=list)
    deployment_changed: bool = False
    ends_oper_name: str = ""


class VideoSlicer:
    """部署栏驱动的录像切片器。

    Parameters
    ----------
    video_frames:
        :class:`VideoFrames` 抽帧器。
    deployment_analyzer:
        :class:`DeploymentAnalyzer`，用于检测部署栏槽位（含 role）。
    button_detector:
        :class:`BattleButtonDetector`，用于检测详情页是否打开。
    sample_interval:
        采样间隔（秒），默认 0.2 对齐 Maa 5Hz。
    """

    def __init__(
        self,
        video_frames: VideoFrames,
        deployment_analyzer,
        button_detector,
        sample_interval: float = _DEFAULT_SAMPLE_INTERVAL,
        ocr_engine=None,
    ) -> None:
        self.video_frames = video_frames
        self.deployment = deployment_analyzer
        self.buttons = button_detector
        self.sample_interval = float(sample_interval)
        self.ocr = ocr_engine
        # OCR 重试节流：Maa 的 PaddleOCR 很快可逐帧重试，RapidOCR 较慢（~1s/次），
        # 同一 clip 的 ends_oper_name 重试限制为每 0.2s 一次。详情页通常打开
        # 0.5-1s，首帧常为过渡帧（OCR 失败），需在窗口内重试。
        self._ocr_retry_min_interval = 0.2
        self._last_ocr_ts: Optional[float] = None
        # 战斗开始时间（暂停按钮首次出现），对齐 Maa battle_start_frame
        self.battle_start_time: Optional[float] = None

    def _read_oper_name(self, frame) -> str:
        """从详情页帧 OCR 干员名（BattleOperName ROI）。

        对齐 Maa analyze_detail_page_oper_name：读 BattleOperName ROI，校验
        非法名（is_name_invalid）。self.ocr 为 None 时返回空串。

        OCR 可能多读/少读字符（如「斩业星熊熊」→「斩业星熊」），用
        battle_data.json 别名索引做模糊匹配校正。
        """
        if self.ocr is None or frame is None or frame.size == 0:
            return ""
        try:
            from arknights_video_recognition.config.roi import get_roi
            from arknights_video_recognition.battle.analyzer import BattleAnalyzer
            roi = get_roi("BattleOperName")
            if roi is None:
                return ""
            text = self.ocr.recognize_text(frame, roi=roi)
            text = text.strip() if text else ""
            # 对齐 Maa is_name_invalid 校验：非法名视为未读到，返回空串持续重试
            if text and not BattleAnalyzer.is_valid_oper_name(text):
                return ""
            # 模糊校正：OCR 多读/少读字符时匹配标准干员名
            resolved = BattleAnalyzer.resolve_oper_name(text)
            return resolved if resolved else text
        except (FileNotFoundError, KeyError, ValueError) as exc:
            # 只吞预期内的配置/数据缺失类异常；其余异常（如代码缺陷）
            # 必须暴露而非静默吞掉导致切片命名错误且无从排查
            logging.getLogger(__name__).warning(
                "详情页干员名 OCR 失败: %s", exc
            )
            return ""

    # --- 主流程 --------------------------------------------------------------

    def slice(self) -> List[Clip]:
        """切片主入口，返回 :class:`Clip` 列表。

        严格对齐 Maa ``slice_video``（CombatRecordRecognitionTask.cpp:303-428）：

        - 逐帧采样（sample_interval），检测部署栏 + 详情页按钮
        - ``oper_is_clicked``（详情页打开）或 ``oper_auto_retreat``（部署栏数量变）
          → 关闭当前片段（end_time = 前一采样时刻）
        - 关闭后仍持续在 ``oper_is_clicked`` 帧上重试 OCR ends_oper_name
        - 连续性恢复且不在片段中 → 开新片段

        性能优化：逐帧检测用轻量级 ``detect_flags``（仅 flag 定位 + NMS，
        无 role 分类），仅在开新片段时调 ``detect_slots`` 获取完整槽位
        （含 role/avatar）。role 分类的 9 次 matchTemplate 是逐帧检测瓶颈。
        """
        clips: List[Clip] = []
        in_segment = False
        cur_clip: Optional[Clip] = None
        prev_ts: Optional[float] = None  # 对齐 Maa pre_frame（前一采样）
        # 对齐 Maa: slice_video 从 m_battle_start_frame 开始。m_battle_start_frame
        # 是 analyze_deployment 中第一个检测到 pause_button 的帧。在此之前（编队页、
        # 加载屏）没有暂停按钮，is_detail_page_open 会误判为 True，阻止 clip 创建。
        battle_started = False

        for ts, frame in self.video_frames.sample(self.sample_interval):
            if frame is None or frame.size == 0:
                prev_ts = ts
                continue
            # 黑帧过滤（< 10 平均亮度）
            if float(frame.mean()) < 10:
                prev_ts = ts
                continue

            # 对齐 Maa: 跳过战斗开始前的帧（编队页、加载屏）。
            # 当帧即触发 battle_started 时，has_pause 结果在下方
            # oper_is_clicked 判定中复用，避免同一帧重复调用按钮检测
            pause = self.buttons.has_pause(frame)
            if not battle_started:
                if pause:
                    battle_started = True
                    self.battle_start_time = ts
                else:
                    prev_ts = ts
                    continue

            # 轻量级 flag 检测（无 role 分类，用于逐帧变化检测）
            flags = self.deployment.detect_flags(frame)
            flag_count = len(flags)
            continuity = self._check_continuity_flags(flags)

            # 对齐 Maa: oper_is_clicked = !speed_button || !pause_button
            # 详情页遮挡两个按钮，任一不可见即视为详情页打开。
            # Maa 原逻辑：speed 或 pause 任一不可见即 oper_is_clicked=true。
            # 这会在 2x→1x 切换（speed 消失但 pause 保留）时产生短暂假阳性，
            # 但 Maa 后处理会过滤 end<=start 的退化片段，不影响最终结果。
            # 关键：技能释放时玩家点开干员面板，speed 会短暂消失（0.5-1s），
            # 必须用此逻辑才能正确在此处切片，否则 clip 过长导致方向分类采样
            # 到远离部署时刻的帧，方向识别错误。
            speed = self.buttons.has_speed(frame)
            oper_is_clicked = (not speed) or (not pause)
            # 对齐 Maa: cur_opers.size() != m_clips.back().deployment.size()。
            # detect_flags 可能产生假阳性（UI 元素被误检为 flag），当 flag 数量
            # 变化时用 detect_slots（含 role 分类，过滤假阳性）验证实际槽位数。
            oper_auto_retreat = False
            if in_segment and continuity and cur_clip is not None:
                if flag_count != len(cur_clip.deployment):
                    actual_slots = self.deployment.detect_slots(frame)
                    oper_auto_retreat = len(actual_slots) != len(cur_clip.deployment)

            if oper_is_clicked or oper_auto_retreat:
                # 对齐 Maa: if (m_clips.empty()) continue;
                # 对齐 Maa: pre_clip = m_clips.back();
                #           if (pre_clip.ends_oper_name.empty())
                #               pre_clip.ends_oper_name = analyze_detail_page_oper_name(frame);
                # 即：对最后一个 clip 持续重试 OCR ends_oper_name（详情页加载需几帧）
                # 节流：同一 clip 的 ends_oper_name OCR 重试间隔为 0.2 秒
                if (clips and oper_is_clicked and not clips[-1].ends_oper_name
                        and (self._last_ocr_ts is None
                             or ts - self._last_ocr_ts >= self._ocr_retry_min_interval)):
                    self._last_ocr_ts = ts
                    name = self._read_oper_name(frame)
                    if name:
                        clips[-1].ends_oper_name = name

                # 对齐 Maa: if (!in_segment) continue;（已关闭，仅获取名字）
                if not in_segment or cur_clip is None:
                    prev_ts = ts
                    continue

                # 关闭当前片段
                # 对齐 Maa: pre_clip.end_frame = pre_frame（前一采样帧）
                # 详情页打开帧技能图标被遮挡，必须用前一帧做 pre_ready 检测
                cur_clip.end_time = prev_ts if prev_ts is not None else ts
                clips.append(cur_clip)
                in_segment = False
                cur_clip = None
            elif not continuity:
                # 过渡帧，跳过（对齐 Maa continue）
                pass
            elif not in_segment:
                # 开新片段：此时才做完整 detect_slots（含 role/avatar）
                slots = self.deployment.detect_slots(frame)
                cur_clip = Clip(
                    start_time=ts,
                    end_time=ts,
                    key_frame=frame.copy(),
                    frame_index=self._frame_index_at(ts),
                    deployment=list(slots),
                )
                in_segment = True

            prev_ts = ts

        # 关闭最后一个片段
        if in_segment and cur_clip is not None:
            # duration_sec 在 fps/帧数元数据异常时返回 0，end_time 会 <= start_time
            # 导致片段被 _postprocess 静默丢弃；回退为 start_time + 一个采样间隔
            # （最小片段时长），保证末尾片段不被误删
            end = self.video_frames.duration_sec
            cur_clip.end_time = (
                end if end > cur_clip.start_time
                else cur_clip.start_time + self.sample_interval
            )
            clips.append(cur_clip)

        return self._postprocess(clips)

    @staticmethod
    def _check_continuity_flags(flags: list) -> bool:
        """部署栏水平间距稳定性（对齐 Maa: |dist - prev_dist| <= 5）。

        轻量级版本：直接接收 ``detect_flags`` 返回的 flag 坐标列表
        （``list[tuple[int, int]]``），无需 role/avatar 信息，用于逐帧检测。

        Parameters
        ----------
        flags:
            ``detect_flags`` 返回的 flag 左上角坐标列表。

        Returns
        -------
        bool
            相邻间距差异均 <= 5 时为 True。
        """
        if len(flags) < 2:
            return True
        xs = sorted(fx[0] for fx in flags)
        prev_dist = 0
        for i in range(1, len(xs)):
            dist = xs[i] - xs[i - 1]
            if prev_dist and abs(dist - prev_dist) > 5:
                return False
            prev_dist = dist
        return True

    def _frame_index_at(self, ts: float) -> int:
        """时间点对应的帧索引。"""
        fps = getattr(self.video_frames, "fps", 0.0) or 0.0
        if fps <= 0:
            return 0
        return int(round(ts * fps))

    def _postprocess(self, clips: List[Clip]) -> List[Clip]:
        """后处理：去掉退化片段 + start_time 偏移 + deployment_changed。

        严格对齐 Maa slice_video 后处理（CombatRecordRecognitionTask.cpp:440-474）：

        - 去掉 ``end <= start`` 退化片段（Maa: ``end_frame_index <= start_frame_index``）
        - ``start_time += 300ms`` 偏移（Maa: ``start_frame_index += offset_frame``，
          offset_ms=300），仅当偏移后仍 < end_time
        - 用 role 序列比较设置 ``deployment_changed``（Maa: 逐位比较 role）
        """
        if not clips:
            return clips
        # 去掉 start>=end 的退化片段
        clips = [c for c in clips if c.end_time > c.start_time]
        # 对齐 Maa: start_frame_index += offset_frame（300ms）
        for clip in clips:
            new_start = clip.start_time + _START_OFFSET_SEC
            if new_start < clip.end_time:
                clip.start_time = new_start
        # 用 role 序列比较设置 deployment_changed
        for i in range(1, len(clips)):
            prev_roles = [s.get("role", "Unknown") for s in clips[i - 1].deployment]
            cur_roles = [s.get("role", "Unknown") for s in clips[i].deployment]
            if len(prev_roles) != len(cur_roles):
                clips[i].deployment_changed = True
            else:
                clips[i].deployment_changed = any(
                    p != c for p, c in zip(prev_roles, cur_roles)
                )
        return clips
