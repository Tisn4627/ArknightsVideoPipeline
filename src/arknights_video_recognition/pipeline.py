"""主流水线：把战斗视频识别并组装成 Maa copilot 作业 JSON。

串联 ocr / tile / video / formation / stage / battle / copilot 子模块，
对应原 Maa ``CombatRecordRecognitionTask`` 的完整流程：

    打开视频 → 采样开头帧 → 编队识别 + 关卡识别
            → 切片 → 战场 action 推断
            → battle Action 转 copilot Action → 组装作业 → 输出 JSON

本模块只做串联与转换，不重新实现任何子模块逻辑。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from arknights_video_recognition.battle import (
    Action as BattleAction,
    BattleAnalyzer,
    BattleClassifier,
    OperatorDetector,
)
from arknights_video_recognition.config.settings import (
    DEFAULT_OCR_SOURCE,
    DEFAULT_RESOLUTION,
    MINIMUM_REQUIRED,
    check_resource,
)
from arknights_video_recognition.copilot import (
    Action as CopilotAction,
    ActionType,
    CopilotJob,
    Direction,
)
from arknights_video_recognition.formation import FormationAnalyzer, FormationOper
from arknights_video_recognition.ocr.engine import OcrEngine
from arknights_video_recognition.stage import StageRecognizer
from arknights_video_recognition.video import VideoFrames, VideoSlicer


# --- battle Action → copilot Action 的字符串映射表 -------------------------
#
# battle/analyzer.Action 的 type 用 "Deploy"/"Skill"/"Retreat" 等字符串，
# direction 用 "Right"/"Down"/"Left"/"Up"/"None"；copilot 端用 ActionType /
# Direction 常量（同为字符串），这里显式映射以保证语义一致、便于排查。

_BATTLE_TYPE_TO_COPILOT = {
    "Deploy": ActionType.DEPLOY,
    "Skill": ActionType.SKILL,
    "Retreat": ActionType.RETREAT,
}

_BATTLE_DIR_TO_COPILOT = {
    "Right": Direction.RIGHT,
    "Down": Direction.DOWN,
    "Left": Direction.LEFT,
    "Up": Direction.UP,
    "None": Direction.NONE,
}

# 部署栏 diff 匹配失败时的占位干员名（battle/analyzer.py 的
# UnknownDeployment / Unknown_EndsEmpty，以及内部哨兵 Unknown）。
# 这些名字进入最终 copilot JSON 后，MAA 执行到该动作会因干员不存在
# 而卡住，转换层必须过滤
_PLACEHOLDER_OPER_NAMES = frozenset({
    "Unknown",
    "UnknownDeployment",
    "Unknown_EndsEmpty",
})


class StageNotRecognizedError(ValueError):
    """关卡未识别（OCR 未命中且未手动指定）。

    继承 :class:`ValueError` 以符合"抛 ValueError"的约定，同时携带候选关卡
    列表供 CLI 展示。
    """

    def __init__(self, message: str, candidates: Optional[List[str]] = None):
        super().__init__(message)
        self.candidates = list(candidates) if candidates else []


class VideoRecognitionPipeline:
    """视频识别主流水线。

    串联各子模块，把一段战斗录像识别成 Maa copilot 作业 JSON。

    Parameters
    ----------
    ocr_source:
        OCR 模型源，``"maamodel"``（默认）或 ``"default"``。
    resolution:
        视频归一化分辨率 ``(width, height)``，默认 1280x720。

    Raises
    ------
    ResourceMissingError
        构造时所需资源文件缺失。
    """

    # 开头采样参数：取前 5 秒、每秒一帧用于编队/关卡识别
    _OPENING_MAX_SEC = 5.0
    _OPENING_INTERVAL = 1.0
    # 编队页动态扫描参数
    _SCAN_MAX_SEC = 30.0
    _SCAN_INTERVAL = 0.5
    _BLACK_FRAME_MEAN = 10.0

    def __init__(
        self,
        ocr_source: str = DEFAULT_OCR_SOURCE,
        resolution: Tuple[int, int] = DEFAULT_RESOLUTION,
    ):
        # 先校验资源齐全，缺失直接抛 ResourceMissingError
        check_resource()

        self.ocr_source = ocr_source
        self.resolution = (int(resolution[0]), int(resolution[1]))
        # 所有 ROI 常量与模板尺寸均按 1280x720 标定（config/roi.py），
        # 其他分辨率下模板匹配与 ROI 裁剪会整体错位且无多尺度回退，
        # 识别结果静默全废——必须 fail-fast 而不是带病运行
        if tuple(self.resolution) != tuple(DEFAULT_RESOLUTION):
            raise ValueError(
                f"暂仅支持 {DEFAULT_RESOLUTION[0]}x{DEFAULT_RESOLUTION[1]} "
                f"识别分辨率（所有 ROI 按此标定），当前传入: "
                f"{self.resolution[0]}x{self.resolution[1]}"
            )

        # 各子模块统一复用同一个 OCR 引擎（OcrEngine 内部按 source 缓存）
        self.ocr_engine = OcrEngine(source=ocr_source)
        self.formation_analyzer = FormationAnalyzer(ocr_engine=self.ocr_engine)
        self.stage_recognizer = StageRecognizer(ocr_engine=self.ocr_engine)
        self.operator_detector = OperatorDetector()
        self.battle_classifier = BattleClassifier()
        self.battle_analyzer = BattleAnalyzer(ocr_engine=self.ocr_engine)
        # 注：AvatarMatcher（灰度多尺度场上匹配）当前未接入动作推断链路，
        # 场上定名走部署栏头像回填路线，故不再构造

        # 复用 FormationAnalyzer 的懒加载 support_recognizer（用于编队页开始按钮检测）
        self._support_recognizer = self.formation_analyzer.support_recognizer
        # 部署栏分析器（对齐 Maa analyze_deployment）
        from arknights_video_recognition.battle.buttons import BattleButtonDetector
        from arknights_video_recognition.battle.deployment import DeploymentAnalyzer
        self.deployment_analyzer = DeploymentAnalyzer()
        self.button_detector = BattleButtonDetector()

        # 最近一次 run() 实际写入的输出路径，供 CLI 打印
        self.last_output_path: Optional[Path] = None

    # --- 主流程 ------------------------------------------------------------

    def run(
        self,
        video_path: str,
        stage_override: Optional[str] = None,
        output_path: Optional[str] = None,
        with_video_time: bool = False,
    ) -> Dict[str, Any]:
        """识别视频并组装 copilot 作业，返回作业 dict。

        Parameters
        ----------
        video_path:
            输入视频文件路径。
        stage_override:
            手动指定关卡（code/name/stageId）。非 None 时跳过 OCR 直接查表。
        output_path:
            输出 JSON 路径。为 None 时自动命名存到 resource 同级 cache 目录。
        with_video_time:
            为 True 时输出 JSON 的 actions 携带 ``video_time`` 扩展字段
            （视频内绝对时间戳，秒）；为 False（默认）时剥离，输出纯 Maa
            标准格式。
        """
        # 1) 打开视频（resolution 归一化）
        video_frames = VideoFrames(video_path, resolution=self.resolution)
        try:
            # 2) 采样开头若干帧做编队 + 关卡识别
            opening = self._scan_formation_frames(video_frames)
            formation_opers = self._recognize_formation(opening)
            if not formation_opers:
                # 编队全失败时不得继续：否则会切片、推断并产出 opers 为空、
                # Deploy 动作全是占位名的"结构合法但完全不可用"作业
                raise StageNotRecognizedError(
                    "编队识别失败：视频开头未识别到任何编队干员。"
                    "请确认视频满足 MAA 要求（1080P、16:9、开头为编队页）"
                )
            level = self._recognize_stage(
                opening, stage_override=stage_override, video_frames=video_frames,
            )

            # 3) level 已是关卡 dict（含 tiles/view），取 stageId 作为作业标识
            stage_id = level.get("stageId") or level.get("code") or "unknown"

            # 4) 切片
            slicer = VideoSlicer(
                video_frames,
                deployment_analyzer=self.deployment_analyzer,
                button_detector=self.button_detector,
                ocr_engine=self.ocr_engine,
            )
            clips = slicer.slice()

            # 5) 推断 battle actions
            # 对齐 Maa：m_formation 来自 BattleFormationAnalyzer，包含助战干员；
            # m_all_avatars 与动作推断均基于完整 m_formation，助战干员作为标准
            # 编队干员参与部署栏匹配与动作推断（CombatRecordRecognitionTask.cpp
            # 第 150-297 行无任何助战过滤）。
            battle_actions = self.battle_analyzer.infer_action_conditions(
                clips,
                self.operator_detector,
                self.battle_classifier,
                formation_opers,
                level,
                self.resolution,
                deployment_analyzer=self.deployment_analyzer,
                video_frames=video_frames,
                battle_start_time=slicer.battle_start_time,
            )

            # 6) 转换 battle Action → copilot Action
            copilot_actions = self._convert_actions(battle_actions)

            # 7) 组装 CopilotJob
            # 对齐 Maa：copilot opers 列表包含全部 m_formation（含助战干员）。
            job = CopilotJob(stage_name=stage_id, minimum_required=MINIMUM_REQUIRED)
            for fo in formation_opers:
                job.add_oper(fo.name, skill=0)
            job.add_speedup()
            for act in copilot_actions:
                job.add_action(act)
            job.add_skill_daemon()
            job.set_doc(title=f"MAA AI - {stage_id}")

            # 8) 校验：有问题只警告不阻断
            problems = job.validate()
            if problems:
                print("警告：作业校验发现问题：", file=sys.stderr)
                for p in problems:
                    print(f"  - {p}", file=sys.stderr)

            # 9) 输出
            out_path = self._resolve_output_path(output_path, stage_id, video_path)
            if out_path is not None:
                job.save(out_path, with_video_time=with_video_time)
            self.last_output_path = out_path

            return job.to_dict(with_video_time=with_video_time)
        finally:
            video_frames.release()

    def run_to_json(
        self,
        video_path: str,
        stage_override: Optional[str] = None,
        output_path: Optional[str] = None,
        indent: int = 2,
        with_video_time: bool = False,
    ) -> str:
        """运行流水线并返回 JSON 字符串。"""
        result = self.run(
            video_path,
            stage_override=stage_override,
            output_path=output_path,
            with_video_time=with_video_time,
        )
        return json.dumps(result, indent=indent, ensure_ascii=False)

    # --- 内部：开头采样 / 编队 / 关卡 ---------------------------------------

    def _scan_formation_frames(
        self, video_frames: VideoFrames
    ) -> List[Tuple[float, Any]]:
        """动态扫描编队页，返回最后一段开始按钮窗口内的帧列表。

        流程：
        1. 扫描前 30s，每 0.5s 一帧（顺序读取，避免逐帧 seek）
        2. 逐帧检测开始按钮（detect_start_button）和战斗画面
           （OperatorDetector.detect 有检出即战斗）
        3. 黑帧（mean<10）跳过
        4. 检测到战斗画面立即停止扫描
        5. 未检测到战斗画面则扫描满 30s
        6. 取开始按钮存在的最后一段连续窗口
        """
        duration = video_frames.duration_sec
        end_ts = min(self._SCAN_MAX_SEC, duration) if duration > 0 else self._SCAN_MAX_SEC

        # 顺序采样 + 缓存帧，避免二次 seek
        flags: list[tuple[float, bool, bool]] = []  # (ts, has_start_btn, is_battle)
        cached_frames: list[tuple[float, np.ndarray]] = []
        for ts, frame in video_frames.sample_range(0.0, end_ts, self._SCAN_INTERVAL):
            if frame is None or frame.size == 0:
                continue
            # 黑帧跳过
            if frame.mean() < self._BLACK_FRAME_MEAN:
                flags.append((ts, False, False))
                cached_frames.append((ts, frame))
                continue
            has_btn = self._support_recognizer.detect_start_button(frame)
            is_battle = False
            if self.operator_detector is not None:
                dets = self.operator_detector.detect(frame)
                is_battle = len(dets) > 0
            flags.append((ts, has_btn, is_battle))
            cached_frames.append((ts, frame))
            # 检测到战斗画面立即停止
            if is_battle:
                break

        if not flags:
            return []

        # 找所有连续 has_btn=True 的窗口
        windows: list[tuple[int, int]] = []
        i = 0
        n = len(flags)
        while i < n:
            if flags[i][1]:
                j = i
                while j < n and flags[j][1]:
                    j += 1
                windows.append((i, j))
                i = j
            else:
                i += 1
        if not windows:
            return []

        # 取最后一段窗口（从缓存读取，无需二次 seek）
        start_idx, end_idx = windows[-1]
        result: List[Tuple[float, Any]] = []
        for k in range(start_idx, end_idx):
            result.append(cached_frames[k])
        return result

    def _scan_post_formation_frames(
        self, video_frames: VideoFrames, formation_end_ts: float
    ) -> List[Tuple[float, Any]]:
        """扫描编队页结束后的帧（战斗加载屏），用于关卡名 OCR。

        对齐 Maa C++ ``analyze_stage``：从 ``m_formation_end_frame`` 之后
        开始采样，直到检测到战斗场景（场上干员出现）或视频结束。

        Parameters
        ----------
        video_frames:
            视频帧抽取器。
        formation_end_ts:
            编队页最后一帧的时间戳（秒），后编队帧从此之后开始。

        Returns
        -------
        list[tuple[float, frame]]
            后编队帧列表，每帧为 (时间戳, BGR帧)。
        """
        duration = video_frames.duration_sec
        if duration <= formation_end_ts + self._SCAN_INTERVAL:
            return []

        start_ts = formation_end_ts + self._SCAN_INTERVAL
        end_ts = min(formation_end_ts + self._SCAN_MAX_SEC, duration)
        frames: List[Tuple[float, Any]] = []

        # 顺序采样，避免逐帧 seek
        for ts, frame in video_frames.sample_range(start_ts, end_ts, self._SCAN_INTERVAL):
            if frame is None or frame.size == 0:
                continue
            if frame.mean() < self._BLACK_FRAME_MEAN:
                continue
            frames.append((ts, frame))
            if self.operator_detector is not None:
                dets = self.operator_detector.detect(frame)
                if len(dets) > 0:
                    break

        return frames

    def _recognize_formation(
        self, opening: List[Tuple[float, Any]]
    ) -> List[FormationOper]:
        """识别编队（含助战干员）。

        使用 analyze_with_support 以支持助战槽识别（对齐 Maa 但扩展了助战）。
        """
        return self.formation_analyzer.analyze_with_support(opening)

    def _recognize_stage(
        self,
        opening: List[Tuple[float, Any]],
        stage_override: Optional[str] = None,
        video_frames: Optional[VideoFrames] = None,
    ) -> dict:
        """识别关卡，返回关卡 dict。

        stage_override 非 None 时直接查表（跳过 OCR）；否则先在后编队帧
        （战斗加载屏）上 OCR，对齐 Maa ``analyze_stage`` 从
        ``m_formation_end_frame`` 之后开始。后编队帧全部未命中时回退到
        opening 帧尝试。全部未命中抛 :class:`StageNotRecognizedError`。
        """
        # 手动指定：直接查表
        if stage_override:
            level = self.stage_recognizer.recognize_by_manual(stage_override)
            if level is None:
                raise StageNotRecognizedError(
                    f"手动指定的关卡未在 levels.json 中命中：{stage_override!r}"
                )
            return level

        post_formation: List[Tuple[float, Any]] = []
        if video_frames is not None and opening:
            formation_end_ts = opening[-1][0] if opening else 0.0
            post_formation = self._scan_post_formation_frames(
                video_frames, formation_end_ts
            )

        # OCR 识别：逐帧尝试，命中即返回；未命中保留最后一次候选
        last_candidates: List[str] = []
        for _, frame in post_formation:
            level, candidates = self.stage_recognizer.recognize_with_candidates(frame)
            if level is not None:
                return level
            if candidates:
                last_candidates = candidates

        for _, frame in opening:
            level, candidates = self.stage_recognizer.recognize_with_candidates(frame)
            if level is not None:
                return level
            if candidates:
                last_candidates = candidates

        cand_hint = ""
        if last_candidates:
            cand_hint = "候选关卡：" + " / ".join(last_candidates[:10])
        raise StageNotRecognizedError(
            "未能识别关卡，请用 --stage 手动指定。"
            + (f" {cand_hint}" if cand_hint else ""),
            candidates=last_candidates,
        )

    # --- 内部：battle Action → copilot Action ------------------------------

    def _convert_actions(
        self, battle_actions: List[BattleAction]
    ) -> List[CopilotAction]:
        """把 battle/analyzer 的轻量 Action 列表转成 copilot.Action。

        关键转换点：

        - **location**：battle 端已输出 ``[col, row]``（对齐 Maa ``[loc.x, loc.y]``），
          直接透传为 copilot schema 的 ``[x=col, y=row]``。
        - type：``"Deploy"``/``"Skill"``/``"Retreat"`` → ``ActionType`` 常量。
        - direction：``"Right"``/``"Down"``/... → ``Direction`` 常量；仅 Deploy
          输出 direction（Skill/Retreat 不需要朝向，省略保持 JSON 简洁）。
        """
        copilot_actions: List[CopilotAction] = []
        for ba in battle_actions:
            act_type = _BATTLE_TYPE_TO_COPILOT.get(ba.type, ba.type)

            # 过滤占位名 Deploy：部署栏 diff 匹配失败的 slot 名（见
            # _PLACEHOLDER_OPER_NAMES）进入作业后会让 MAA 卡死在该动作
            if act_type == ActionType.DEPLOY and (
                not ba.name or ba.name in _PLACEHOLDER_OPER_NAMES
            ):
                print(
                    f"警告：丢弃无法确定干员名的 Deploy 动作（t={ba.ts:.1f}s）",
                    file=sys.stderr,
                )
                continue

            # ba.location 已是 [col, row]（对齐 Maa [loc.x, loc.y]），直接透传
            location: Optional[List[int]] = None
            if ba.location is not None and len(ba.location) >= 2:
                location = [int(ba.location[0]), int(ba.location[1])]

            # direction：仅 Deploy 输出
            direction: Optional[str] = None
            if act_type == ActionType.DEPLOY:
                direction = _BATTLE_DIR_TO_COPILOT.get(ba.direction, Direction.NONE)

            copilot_actions.append(CopilotAction(
                type=act_type,
                name=ba.name or None,
                location=location,
                direction=direction,
                video_time=ba.ts,
            ))
        return copilot_actions

    # --- 内部：输出路径 ----------------------------------------------------

    def _resolve_output_path(
        self,
        output_path: Optional[str],
        stage_id: str,
        video_path: str,
    ) -> Optional[Path]:
        """解析输出路径：显式指定则用之，否则按规则命名存到 cache 目录。"""
        if output_path:
            return Path(output_path)

        video_stem = Path(video_path).stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cache_dir = Path.cwd() / "cache"
        return cache_dir / f"MaaAI_{stage_id}_{video_stem}_{timestamp}.json"
