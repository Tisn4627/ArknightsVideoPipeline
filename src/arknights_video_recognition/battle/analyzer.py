"""战斗分析：action 推断（对齐 Maa 双指针主循环）。

移植自 Maa ``CombatRecordRecognitionTask::_run`` 的主循环::

    ClipInfo* pre_valid = nullptr;
    for (auto iter = m_clips.begin(); iter != m_clips.end(); ++iter) {
        auto& clip = *iter;
        if (!clip.deployment_changed && iter != m_clips.begin()) {
            compare_skill(clip, *(iter - 1));   // Skill 路径
            continue;
        }
        analyze_clip(clip, pre_valid);          // Deploy/Retreat 路径
        pre_valid = &clip;
    }

关键点：
- ``pre_valid`` 仅在 ``deployment_changed`` 时前进；
- Skill 推断用紧邻前一片段（``iter-1``）的 ``ends_oper_name`` 定位目标；
- ``deployment_changed`` 由切片器后处理用 role 序列比较设置。

参考：``maa_research/CombatRecordRecognitionTask.cpp`` 第 71-85 行。
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import List, Optional, Sequence, Tuple

import numpy as np
import cv2

from arknights_video_recognition.config.roi import load_roi
from arknights_video_recognition.ocr.engine import OcrEngine
from arknights_video_recognition.tile import get_all_tile_positions

logger = logging.getLogger(__name__)

# 战场干员检测的最大采样帧数（对齐 Maa OperDetSamplingCount=20）
_OPER_DET_SAMPLING_COUNT = 20

# 自动召唤干员白名单：这些干员在部署/开技能时会自动在可部署格上部署召唤物，
# 召唤物不占部署栏槽位（出现与撤退均不改变部署栏），只增加场上新生格子。
# 召唤物守卫（Deploy 数量守卫 + 头像仲裁）仅对白名单干员生效；其他干员的
# 部署保留 Maa 兜底配对（ends_oper_name → Unknown_EndsEmpty），避免其
# M > N（检测异常）时误丢真实部署。
# 维什戴尔：部署时在攻击范围内自动部署一个召唤物（延后约 0.2s，周围四格
# 存在可部署地块时）；开三技能后再自动部署两个（最多三个）。
_AUTO_SUMMON_OPERATORS = frozenset({"维什戴尔"})


@dataclass
class Action:
    """单个推断出的战斗操作（对应 copilot JSON 的一个 action）。

    Attributes
    ----------
    type:
        ``"Deploy"`` / ``"Skill"`` / ``"Retreat"``。
    name:
        干员名。
    location:
        ``[row, col]`` 格子坐标。
    direction:
        部署方向 ``"Right"`` / ``"Down"`` / ``"Left"`` / ``"Up"`` / ``"None"``。
    ts:
        该动作对应视频片段的起始时间（秒）。None 表示无法确定（不输出）。
    """

    type: str
    name: str = ""
    location: Optional[List[int]] = None
    direction: str = "None"
    ts: Optional[float] = None


@dataclass
class _OperState:
    """场上单个干员的状态快照（内部传递用）。

    对齐 Maa ``BattlefieldOper``：``new_here`` 标记该格子是否为本 clip 新部署
    （classify_direction 中设置，process_changes 中用于判定 Deploy 目标）。
    """
    name: str
    tile: Tuple[int, int]
    direction: str = "None"
    skill_ready: str = "n"
    box: List[int] = field(default_factory=lambda: [0, 0, 0, 0])
    avatar: Optional[np.ndarray] = None  # 60x60 BGR 战场头像（BattleOperBoxRectMove 裁剪）
    new_here: bool = False  # 对齐 Maa BattlefieldOper.new_here


class BattleAnalyzer:
    """战斗分析器：推断 actions（双指针主循环）。

    Parameters
    ----------
    ocr_engine:
        已弃用：仅为兼容既有调用方保留，构造时不再使用（原 ``self.ocr``
        死属性已删除）。
    """

    _DEFAULT_SKILL_RECT_MOVE = [-28, -140, 64, 64]
    _DEFAULT_DIR_RECT_MOVE = [-48, -48, 96, 96]
    _DEFAULT_DET_BOX_MOVE = [0, -50, 60, 60]
    # tile 反查最近邻回退的距离上限（px^2）：720p 下相邻格子约 60px
    _MAX_TILE_FALLBACK_DIST_SQ = 80 * 80

    def __init__(self, ocr_engine: Optional[OcrEngine] = None):
        # 兼容说明：ocr_engine 参数保留以兼容既有调用方，但已不使用——
        # 原 self.ocr 属性从未被读取（死属性），已整体删除
        try:
            tasks = load_roi()
            skill_task = tasks.get("BattleSkillReady", {})
            dir_task = tasks.get("BattleDeployDirectionRectMove", {})
            det_box_task = tasks.get("BattleOperBoxRectMove", {})
            self._skill_rect_move = list(
                skill_task.get("rectMove") or self._DEFAULT_SKILL_RECT_MOVE
            )
            self._dir_rect_move = list(
                dir_task.get("rectMove") or self._DEFAULT_DIR_RECT_MOVE
            )
            self._det_box_move = list(
                det_box_task.get("rectMove") or self._DEFAULT_DET_BOX_MOVE
            )
        except Exception as exc:
            # roi.json 缺失/损坏时回退内置默认值，保证分析器仍可工作
            logger.warning("读取 roi.json 的 rectMove 失败，使用内置默认值: %s", exc)
            self._skill_rect_move = list(self._DEFAULT_SKILL_RECT_MOVE)
            self._dir_rect_move = list(self._DEFAULT_DIR_RECT_MOVE)
            self._det_box_move = list(self._DEFAULT_DET_BOX_MOVE)

        # 双向映射（对齐 Maa m_operator_locations / m_location_operators）
        self.operator_locations: dict[str, tuple[int, int]] = {}
        self.location_operators: dict[tuple[int, int], str] = {}
        # 部署栏已定名头像缓存（对齐 Maa m_all_avatars）
        self.all_avatars: dict[str, np.ndarray] = {}
        # 部署栏分析器（由 infer_action_conditions 注入，_backfill_deployment_names 使用）
        self.deployment_analyzer = None
        # 编队干员（由 infer_action_conditions 注入）
        self._formation_opers: list = []
        # 干员部署时间戳（由 _process_changes 的 Deploy 分支记录），
        # 仅记录部署时间戳（诊断用途），当前无读取方
        self._deploy_times: dict[str, float] = {}

    # --- ROI 裁剪 ----------------------------------------------------------

    @staticmethod
    def is_valid_oper_name(name: str) -> bool:
        """校验干员名是否有效（对齐 Maa BattleData.is_name_invalid）。

        规则：
        - 非空且去除空白后含 1-6 个名字字符（中文 \\u4e00-\\u9fff 或拉丁字母）；
          数字与标点后缀（如 Lancet-2 的 -2）不计入长度
        - 纯数字、纯标点、空串均被拒绝
        """
        if not name:
            return False
        s = name.strip()
        if not s:
            return False
        name_chars = re.findall(r"[\u4e00-\u9fffa-zA-Z]", s)
        if not (1 <= len(name_chars) <= 6):
            return False
        return True

    @staticmethod
    def resolve_oper_name(raw_name: str) -> Optional[str]:
        """OCR 干员名模糊校正，返回标准名；未匹配返回 None。

        复用 FormationAnalyzer 的别名索引（battle_data.json），先精确别名
        匹配，未命中再用 difflib 模糊匹配。用于详情页 OCR 多读/少读字符
        的校正（如「斩业星熊熊」→「斩业星熊」）。
        """
        if not raw_name:
            return None
        from arknights_video_recognition.formation.analyzer import load_alias_index

        aliases, mapping = load_alias_index()
        if raw_name in mapping:
            return mapping[raw_name]
        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in raw_name)
        cutoff = 0.6 if has_cjk else 0.8
        matches = difflib.get_close_matches(raw_name, aliases, n=1, cutoff=cutoff)
        if matches:
            return mapping[matches[0]]
        return None

    # --- ROI 裁剪 ----------------------------------------------------------

    @staticmethod
    def _crop_rect_move(
        frame: np.ndarray, center: Tuple[float, float], rect_move: Sequence[int]
    ) -> np.ndarray:
        if frame is None or frame.size == 0 or len(rect_move) < 4:
            return np.empty((0, 0, 3), dtype=np.uint8)
        cx, cy = center
        dx, dy, w, h = (int(v) for v in rect_move[:4])
        orig_h, orig_w = frame.shape[:2]
        # 对齐 Maa：tile 屏幕坐标在 Maa 中存储为 int（Point），
        # Maa 的 Point 使用 static_cast<int> 截断转换，
        # 本实现使用 int() 截断以匹配 Maa 的整型坐标存储方式
        cx_int = int(cx)
        cy_int = int(cy)
        x0 = max(0, cx_int + dx)
        y0 = max(0, cy_int + dy)
        x1 = min(orig_w, cx_int + dx + w)
        y1 = min(orig_h, cy_int + dy + h)
        if x1 <= x0 or y1 <= y0:
            return np.empty((0, 0, 3), dtype=np.uint8)
        return frame[y0:y1, x0:x1]

    def _yolo_box_to_tile(
        self, yolo_box, level, screen_size, positions,
    ):
        """YOLO 检测框 → 格子坐标（对齐 Maa rect.include(t.pos)）。

        Maa 逻辑（CombatRecordRecognitionTask.cpp:595-601）::
            Rect rect = box.rect.move(det_box_move);  // det_box_move=[0,-50,60,60]
            auto iter = find_if(tiles, [&](t) { return rect.include(t.pos); });

        即：把 YOLO 框按 det_box_move 偏移+缩放为 60x60 rect，
        找 tile 屏幕坐标落在 rect 内的格子。多命中取距离 rect 中心最近的；
        无命中回退偏移后 rect 中心做最近邻。

        Parameters
        ----------
        yolo_box:
            ``[x, y, w, h]``，YOLO 检测框左上角 + 宽高（原图坐标系）。
        level, screen_size, positions:
            同 :func:`screen_pos_to_tile`。
        """
        from arknights_video_recognition.battle.matcher import screen_pos_to_tile

        if not yolo_box or len(yolo_box) < 4 or positions is None:
            return None
        bx, by = int(yolo_box[0]), int(yolo_box[1])
        dx, dy, rw, rh = (int(v) for v in self._det_box_move[:4])
        # 偏移后 rect：左上角 (bx+dx, by+dy)，宽高 (rw, rh)
        rect_x0 = bx + dx
        rect_y0 = by + dy
        rect_x1 = rect_x0 + rw
        rect_y1 = rect_y0 + rh
        rect_cx = rect_x0 + rw / 2.0
        rect_cy = rect_y0 + rh / 2.0

        # 包含测试：找 tile 屏幕坐标落在 rect 内的格子
        candidates = []
        for row in range(len(positions)):
            row_pos = positions[row]
            for col in range(len(row_pos)):
                tx, ty = row_pos[col]
                if rect_x0 <= tx <= rect_x1 and rect_y0 <= ty <= rect_y1:
                    dist = (tx - rect_cx) ** 2 + (ty - rect_cy) ** 2
                    candidates.append((dist, (row, col)))

        if candidates:
            candidates.sort(key=lambda c: c[0])
            return candidates[0][1]

        # 无命中时的受限最近邻（偏离 Maa rect.include 的部分保留，但加
        # 距离上限）：无上限时 YOLO 误检框（UI 元素等）会被强行安到
        # 最近格子，幽灵 tile 进入整帧集合投票后产生假 newcomer/假
        # Deploy。720p 下相邻格子约 60px，取 80px 半径拦截离谱投影
        nearest = screen_pos_to_tile(
            (rect_cx, rect_cy), level, screen_size, positions=positions
        )
        if nearest is None:
            return None
        row_i, col_i = nearest
        tx, ty = positions[row_i][col_i]
        dist_sq = (tx - rect_cx) ** 2 + (ty - rect_cy) ** 2
        if dist_sq <= self._MAX_TILE_FALLBACK_DIST_SQ:
            return nearest
        return None

    @staticmethod
    def _buildable_tiles(level) -> Optional[set]:
        """提取关卡中可部署格子的集合（``buildableType != 0``）。

        levels.json 的每个 tile 携带 ``buildableType``（0=不可部署，
        1=地面，2=高台）。干员只能位于可部署格；而部分干员技能会把
        召唤物自动部署到**非可部署格**上（如圣聆初雪二技能在蓝门
        ``tile_end`` 处部署的"冻结的蓝门"），该召唤物无法手动部署/
        撤退，却带与干员一致的头像框与血条，会被 YOLO 检出并映射到
        蓝门格，进而产生假 Deploy/Retreat 并污染格子↔干员映射。

        本方法是**有意偏离 Maa 对齐**的过滤点（Maa C++ 无此逻辑）：
        战场集合收集阶段直接丢弃落在非可部署格上的检测。copilot 作业
        的动作只涉及编队干员，此类自动召唤物本就不应产出任何动作；
        且在非可部署格上的 Deploy 对 MAA 执行而言必然非法。

        Returns
        -------
        set or None
            ``{(row, col), ...}`` 可部署格集合；level 缺失 tiles 或结构
            异常时返回 ``None``（fail-open：调用方跳过过滤，保持旧行为）。
            单个 tile 缺 ``buildableType`` 字段时视为可部署（兼容最小化
            测试关卡与脏数据）。
        """
        tiles = level.get("tiles") if isinstance(level, dict) else None
        if not isinstance(tiles, list) or not tiles:
            return None
        buildable: set = set()
        try:
            for row, row_tiles in enumerate(tiles):
                if not isinstance(row_tiles, list):
                    return None
                for col, tile in enumerate(row_tiles):
                    if not isinstance(tile, dict):
                        return None
                    bt = tile.get("buildableType")
                    # 字段缺失按可部署处理：真实关卡数据必有该字段，
                    # 只有手工构造的最小 fixture 才会缺省，此时保持旧行为
                    if bt is None or int(bt) != 0:
                        buildable.add((row, col))
        except (TypeError, ValueError):
            return None
        return buildable

    # --- 双指针主循环（对齐 Maa _run） ------------------------------------

    @staticmethod
    def _fallback_positions(level, screen_size):
        """当 level 缺少 height/width/view 等投影字段时（如单元测试的最小
        fake level），按 ``tiles`` 形状构造均匀分布的占位屏幕坐标网格，使
        :func:`screen_pos_to_tile` / :func:`tile_to_screen_pos` 仍可工作。
        """
        tiles = level.get("tiles", []) if isinstance(level, dict) else []
        h = len(tiles)
        w = len(tiles[0]) if h and isinstance(tiles[0], (list, tuple)) else 0
        sw, sh = int(screen_size[0]), int(screen_size[1])
        return [
            [((c + 1) / (w + 1) * sw, (r + 1) / (h + 1) * sh) for c in range(w)]
            for r in range(h)
        ]

    def infer_action_conditions(
        self,
        clips: Sequence,
        detector,
        classifier,
        formation_opers: Sequence,
        level: dict,
        screen_size: Sequence[int],
        deployment_analyzer=None,
        video_frames=None,
        battle_start_time: Optional[float] = None,
    ) -> List[Action]:
        """遍历 clips 推断 actions（严格对齐 Maa 双指针主循环）。

        Maa ``_run``（CombatRecordRecognitionTask.cpp:71-85）::

            ClipInfo* pre_valid = nullptr;
            for (auto iter = m_clips.begin(); iter != m_clips.end(); ++iter) {
                auto& clip = *iter;
                if (!clip.deployment_changed && iter != m_clips.begin()) {
                    compare_skill(clip, *(iter - 1));   // Skill 路径
                    continue;
                }
                analyze_clip(clip, pre_valid);          // Deploy/Retreat 路径
                pre_valid = &clip;
            }

        关键对齐点：
        - Skill 路径用紧邻前一个 clip（``clips[i-1]``），仅检查其
          ``ends_oper_name`` 指向的单个干员（``compare_skill`` 全部逻辑）；
        - Deploy/Retreat 路径**不**检查技能（Maa 仅在 Skill 路径调 compare_skill）；
        - ``pre_valid`` 仅在 ``deployment_changed=True`` 时前进。
        """
        actions: List[Action] = []
        if not clips:
            return actions

        # 状态重置：这些映射仅在 __init__ 初始化，同一实例跑第二个视频
        # 会继承上一局的格子↔干员映射并产出错误动作
        self.operator_locations.clear()
        self.location_operators.clear()
        self.all_avatars.clear()
        self._deploy_times.clear()

        try:
            positions = get_all_tile_positions(level, screen_size)
        except Exception as exc:
            logger.warning("get_all_tile_positions 失败，使用最近邻回退: %s", exc)
            positions = self._fallback_positions(level, screen_size)

        # 阶段 1：在 battle_start_frame 上做编队↔部署栏匹配，填充 all_avatars
        # 对齐 Maa analyze_deployment：使用 battle_start_frame（暂停按钮首次出现的帧）
        # 而非 clips[0].key_frame，因为第一个 clip 的 key_frame 可能已在部署之后
        # （如 16.30s，此时部分干员已被部署，导致头像匹配不全）
        self._init_avatars(
            clips[0], formation_opers, deployment_analyzer, video_frames,
            battle_start_time=battle_start_time,
        )
        self.deployment_analyzer = deployment_analyzer  # 供 _backfill_deployment_names 使用
        self._formation_opers = list(formation_opers) if formation_opers else []

        # 处理战斗开始到第一个 clip 之间的部署缺口
        # 场景：battle_start_time（13.20s）时部署栏有 3 个槽位，但第一个 clip（16.30s）
        # 只剩 2 个槽位 —— 说明有干员在第一个 clip 之前已被部署，切片器未捕捉到该变化。
        # 方案：创建一个合成初始 clip 作为 pre_valid，使主循环的 process_changes 能正常检测到部署。
        pre_valid = None
        first_clip = clips[0] if clips else None
        if (battle_start_time is not None and video_frames is not None
                and first_clip is not None and deployment_analyzer is not None):
            initial_frame = video_frames.get_frame_at(battle_start_time)
            if initial_frame is not None and initial_frame.size > 0:
                initial_slots = deployment_analyzer.detect_slots(initial_frame)
                if initial_slots and first_clip.deployment and len(initial_slots) > len(first_clip.deployment):
                    # 合成初始 clip，deployment=初始状态（与 _recognize_deployment 一致格式），
                    # battlefield=空（场上尚无干员）
                    synthetic_dep = [
                        {
                            "name": "Unknown",
                            "role": s.get("role", "Unknown"),
                            "avatar": s["avatar"],
                        }
                        for s in initial_slots
                    ]
                    pre_valid = SimpleNamespace(
                        deployment=synthetic_dep,
                        battlefield={},
                        ends_oper_name="",
                    )
        for i, clip in enumerate(clips):
            if not clip.deployment_changed and i != 0:
                # Skill 路径：compare_skill(clip, *(iter-1))
                # 仅检查 pre_clip.ends_oper_name 指向的单个干员（对齐 Maa）
                pre_clip = clips[i - 1]
                skill_actions = self._compare_skill(
                    clip, pre_clip, video_frames, classifier,
                    level, screen_size, positions,
                )
                actions.extend(skill_actions)
                # 补充检测所有场上干员的技能状态变化
                # compare_skill 仅检查 ends_oper_name 指向的单个干员，
                # 若 ends_oper_name OCR 有误或玩家未打开详情页就释放技能
                # （直接点击场上干员头像释放），该路径会漏检。
                # 此处对所有场上干员做技能就绪状态变化检测作为补充。
                # 关键：用紧邻前一个 clip（pre_clip）作为参考，而非 pre_valid，
                # 避免跨越多个 clip 重复检测同一次技能释放。
                extra_skills = self._detect_skill_actions(
                    clip, pre_clip, video_frames, classifier,
                    level, screen_size, positions,
                )
                # 去重：跳过 compare_skill 已检测到的同名干员
                detected_names = {a.name for a in skill_actions}
                for a in extra_skills:
                    if a.name not in detected_names:
                        actions.append(a)
                continue
            # Deploy/Retreat 路径：analyze_clip(clip, pre_valid)
            deploy_actions = self._analyze_clip(
                clip, pre_valid, detector, classifier,
                formation_opers, level, screen_size, positions,
                deployment_analyzer, video_frames,
            )
            actions.extend(deploy_actions)

            # 在 Deploy/Retreat 路径中补充检测所有场上干员的技能状态变化
            # 当所有 clip 都有 deployment_changed=True 时，Skill 路径永远不会被
            # 触发，导致技能动作漏检。此处对所有场上干员做一次技能就绪状态变化检测。
            # 关键：用紧邻前一个 clip（clips[i-1]）作为参考，而非 pre_valid，
            # 避免跨越多个 clip 重复检测同一次技能释放。
            if i > 0:
                skill_actions = self._detect_skill_actions(
                    clip, clips[i - 1], video_frames, classifier,
                    level, screen_size, positions,
                )
                actions.extend(skill_actions)

            pre_valid = clip
        return actions

    # --- 辅助方法（spec §4.4.1 契约） -------------------------------------

    def _init_avatars(self, first_clip, formation_opers, deployment_analyzer, video_frames=None, battle_start_time: Optional[float] = None) -> None:
        """在 battle_start_frame 上做编队↔部署栏匹配，填充 all_avatars。

        严格对齐 Maa ``analyze_deployment``（CombatRecordRecognitionTask.cpp:227-301）：

        Maa 逻辑：
        1. 在 ``battle_start_frame`` **单帧**上调用 ``deployment_analyze()`` 得到
           ``deployment``（list of DeploymentOper，含 rect/role/avatar 60×60）
        2. 对每个 formation_oper (fo)：
           - ``BestMatcher best_match_analyzer(formation_avatar)``：编队半身像作 scene
           - ``roles = { BattleData.get_role(name) }``，阿米娅额外加 Warrior
           - 对每个 deployment oper (slot)：
             - ``if (!roles.contains(oper.role)) continue``：role 硬过滤
             - ``crop_avatar = oper.avatar(crop_roi)``：裁 30×30 脸部
             - 多尺度缩放裁剪后的脸部，``append_templ`` 作为模板
             - ``candidate.emplace(flag, oper.avatar)``：记录 60×60 avatar
           - ``best_match_analyzer.analyze()``：在 formation_avatar 上匹配所有模板
           - 匹配成功：``m_all_avatars.emplace(name, candidate.at(...))``
           - 匹配失败：``continue``，跳过该 fo

        关键对齐点：
        - **单帧检测**：Maa 只用 battle_start_frame 单帧，无多帧合并
        - **每个 fo 独立匹配**：无 used_slots 去重（Maa 信任多尺度匹配的可靠性）
        - **role 硬过滤**：slot.role not in fo_roles 则不进候选
        - **失败则跳过**：不写入 all_avatars，无回退、无阶段2

        Parameters
        ----------
        battle_start_time:
            战斗开始时间（暂停按钮首次出现），对应 Maa battle_start_frame。
            为 None 时回退到 first_clip.key_frame。
        """
        if deployment_analyzer is None or not formation_opers:
            return

        # 对齐 Maa：使用 battle_start_frame 单帧做部署栏检测
        if battle_start_time is not None and video_frames is not None:
            first_frame = video_frames.get_frame_at(battle_start_time)
        else:
            first_frame = getattr(first_clip, "key_frame", None)
        if first_frame is None or first_frame.size == 0:
            return

        # 对齐 Maa：单帧检测部署栏
        slots = deployment_analyzer.detect_slots(first_frame)
        if not slots:
            return

        # 跨类私有访问说明：DeploymentAnalyzer 的 _char_roles/_match_thr 为其
        # 私有属性，因跨模块无公开访问器且包结构限制（不宜反向暴露接口），
        # 这里以 getattr 防御式读取；若 DeploymentAnalyzer 结构变更需同步此处
        char_roles = getattr(deployment_analyzer, "_char_roles", {}) or {}
        match_thr = float(getattr(deployment_analyzer, "_match_thr", 0.6))

        # 对齐 Maa：每个 fo 独立匹配，无 used_slots 去重
        for fo in formation_opers:
            name = getattr(fo, "name", "")
            if not name or name in self.all_avatars:
                continue  # 不覆盖已缓存条目（对齐 Maa emplace 仅插入语义）
            fo_avatar = getattr(fo, "avatar", None)
            if fo_avatar is None or fo_avatar.size == 0:
                continue
            fo_role = char_roles.get(name)
            if fo_role is None:
                # char_roles.json 滞后于游戏更新的新干员无职业条目：
                # 与 match_with_formation 的"缺条目不过滤"降级保持一致，
                # 跳过会导致该干员永不进入 all_avatars，后续部署只能得到
                # UnknownDeployment 占位名
                fo_roles = None  # type: ignore[assignment]
            else:
                fo_roles = {fo_role}
                if name == "阿米娅":
                    fo_roles.add("Warrior")  # 阿米娅特例

            # 对齐 Maa BestMatcher：在所有 role 匹配的 slot 中取最高分
            best_score = -1.0
            best_slot_avatar = None
            for slot in slots:
                slot_role = slot.get("role")
                if fo_roles is not None and slot_role not in fo_roles:
                    continue  # role 硬过滤（缺条目时放弃过滤）
                slot_av = slot.get("avatar")
                if slot_av is None or slot_av.size == 0:
                    continue
                _, score = deployment_analyzer.match_with_formation(
                    slot_av, [fo], role_hint=slot_role,
                )
                if score > best_score:
                    best_score = score
                    best_slot_avatar = slot_av

            # 对齐 Maa：匹配失败则 continue，不写入 all_avatars（无回退）
            if best_slot_avatar is not None and best_score >= match_thr:
                self.all_avatars[name] = best_slot_avatar

    def _backfill_deployment_names(self, clip) -> None:
        """对 clip.deployment 中 name=="Unknown" 的 slot 用 all_avatars 重新匹配。

        严格对齐 Maa ``ananlyze_deployment_names``（CombatRecordRecognitionTask.cpp:775-807）：

        Maa 逻辑：
        - 对 clip.deployment 中每个 oper (slot)：
          - 已有 name 则跳过（``if (!oper.name.empty()) continue``）
          - ``BestMatcher avatar_analyzer(oper.avatar)``：slot 60×60 作 scene
          - 对 m_all_avatars 中每个 (name, avatar)：
            - ``roles = { BattleData.get_role(name) }``，阿米娅额外加 Warrior
            - ``if (roles.contains(oper.role))``：role 硬过滤
              - ``avatar_analyzer.append_templ(name, avatar)``：60×60 known avatar 作模板
          - ``avatar_analyzer.analyze()``：在 slot avatar 上匹配
          - 匹配成功：``oper.name = result.templ_info.name``
          - 匹配失败：``oper.name = "UnknownDeployment"``

        关键对齐点：
        - **role 硬过滤**：slot.role not in fo_roles 则该 known avatar 不进候选
        - **失败标 "UnknownDeployment"**（无 idx，对齐 Maa）
        - **无排除场上干员**：Maa 的 all_avatars 永不更新，已部署干员不在部署栏
          （detect_slots 自然检测不到），无需额外排除
        - **无回退**：role 过滤匹配失败直接标 UnknownDeployment，无无 role 重试
        """
        deployment = getattr(clip, "deployment", []) or []
        for idx, slot in enumerate(deployment):
            if not isinstance(slot, dict):
                continue
            if slot.get("name", "Unknown") != "Unknown":
                continue  # 对齐 Maa：已有 name 则跳过
            if not self.all_avatars or self.deployment_analyzer is None:
                slot["name"] = "UnknownDeployment"
                continue
            # 对齐 Maa：role 硬过滤（slot.role 永远已知，Unknown 时标 UnknownDeployment）
            slot_role = slot.get("role")
            if not slot_role or slot_role == "Unknown":
                slot["name"] = "UnknownDeployment"
                continue
            name, _ = self.deployment_analyzer.match_with_known_avatars(
                slot["avatar"], self.all_avatars, role_hint=slot_role,
            )
            # 对齐 Maa：匹配失败标 "UnknownDeployment"（无 idx、无回退）
            slot["name"] = name if name != "Unknown" else "UnknownDeployment"

    def _detect_skill_actions(
        self, clip, pre_ref, video_frames, classifier,
        level, screen_size, positions,
    ) -> List[Action]:
        """检测所有场上干员的技能状态变化（边界检查，对齐 Maa compare_skill）。

        对齐 Maa ``compare_skill`` 的边界检查逻辑：仅在 ``pre_ref.end_time``
        和 ``clip.start + 500ms`` 两个时间点检查技能就绪状态，检测
        ``'y' → 'n'`` 的跃迁（即技能从就绪变为未就绪，表示技能已释放）。

        与 Maa ``compare_skill`` 的区别：本方法检查 ``operator_locations`` 中
        **所有**场上干员，而 compare_skill 仅检查 ``ends_oper_name`` 指向的
        单个干员。这使得即使 ends_oper_name OCR 有误或玩家未打开详情页
        就释放技能（直接点击场上干员），也能检测到技能动作。

        边界检查的优势（vs 多帧采样）：
        - 不会误检长 clip 中间的技能恢复→再次释放循环
        - auto-trigger 技能在 0.5s 内恢复 'y'，边界两端均为 'y'，自然过滤

        Parameters
        ----------
        pre_ref:
            参考 clip。``pre_ref.end_time`` 作为 pre_ready 检查时间点。
        clip:
            当前 clip。``clip.start + 500ms`` 作为 cur_ready 检查时间点。
        """
        actions: List[Action] = []
        if video_frames is None or classifier is None or not self.operator_locations:
            return actions

        clip_start = getattr(clip, "start_time", 0)
        clip_end = getattr(clip, "end_time", clip_start)
        if clip_end <= clip_start:
            return actions

        # pre_ready: pre_ref.end_time 单帧检查（对齐 Maa compare_skill）
        pre_end = getattr(pre_ref, "end_time", 0)
        pre_frame = video_frames.get_frame_at(pre_end)
        if pre_frame is None:
            return actions

        # cur_ready: clip.start + 500ms 单帧检查（对齐 Maa skip_ms=500）
        cur_ts = clip_start + 0.5
        if cur_ts > clip_end:
            cur_ts = clip_start + (clip_end - clip_start) / 2
        cur_frame = video_frames.get_frame_at(cur_ts)
        if cur_frame is None:
            return actions

        for name, loc in self.operator_locations.items():
            pre_ready = self._skill_ready_at(
                pre_frame, loc, classifier, level, screen_size, positions
            )
            if pre_ready != "y":
                continue  # 对齐 Maa: if (!pre_ready) return true;
            cur_ready = self._skill_ready_at(
                cur_frame, loc, classifier, level, screen_size, positions
            )
            if cur_ready != "y":
                # 对齐 Maa: if (pre_ready && !cur_ready) emit Skill
                actions.append(Action(
                    type="Skill", name=name,
                    location=[loc[1], loc[0]],
                    ts=clip_start,
                ))

        return actions

    def _compare_skill(
        self, clip, pre_clip, video_frames, classifier,
        level, screen_size, positions,
    ) -> List[Action]:
        """Skill 推断（严格对齐 Maa ``compare_skill``，CombatRecordRecognitionTask.cpp:498-553）。

        仅检查 ``pre_clip.ends_oper_name`` 指向的单个干员：
        - ``pre_ready``：``pre_clip.end_frame`` **单帧**检查，非 ``'y'`` 直接
          返回（无 backward scan，对齐 Maa 第 507-515 行）；
        - ``cur_ready``：``clip.start + 500ms`` 单帧检查（对齐 Maa ``skip_ms=500``）；
        - ``pre_ready == 'y'`` 且 ``cur_ready != 'y'`` → 发射 Skill action。

        Maa 用 ``pre_clip.end_frame``（切片时缓存的 cv::Mat）做 pre_ready 检查；
        本实现用 ``video_frames.get_frame_at(pre_clip.end_time)`` 取等价帧。
        """
        oper_name = getattr(pre_clip, "ends_oper_name", "")
        if not oper_name or oper_name not in self.operator_locations:
            return []
        target_loc = self.operator_locations[oper_name]
        if video_frames is None or classifier is None:
            return []

        # pre_ready: pre_clip.end_frame 单帧检查（对齐 Maa，无 backward scan）
        pre_end = getattr(pre_clip, "end_time", 0)
        pre_frame = video_frames.get_frame_at(pre_end)
        if pre_frame is None:
            return []
        pre_ready = self._skill_ready_at(
            pre_frame, target_loc, classifier, level, screen_size, positions
        )
        if pre_ready != "y":
            # 对齐 Maa：if (!pre_ready) return true;
            return []

        # cur_ready: clip.start + 500ms（对齐 Maa skip_ms=500）
        clip_start = getattr(clip, "start_time", 0)
        clip_end = getattr(clip, "end_time", clip_start)
        cur_ts = clip_start + 0.5
        # 对齐 Maa 行 521-524：if (cls_begin > clip.end_frame_index)
        #   cls_begin = start + (end - start) / 2;
        if cur_ts > clip_end:
            cur_ts = clip_start + (clip_end - clip_start) / 2
        cur_frame = video_frames.get_frame_at(cur_ts)
        if cur_frame is None:
            return []
        cur_ready = self._skill_ready_at(
            cur_frame, target_loc, classifier, level, screen_size, positions
        )
        if cur_ready != "y":
            # 对齐 Maa：if (pre_ready && !cur_ready) emit Skill
            # 对齐 Maa 行 543: location = [target_location.x, target_location.y] = [col, row]
            # Python tiles 是 (row, col)，故输出 [target_loc[1], target_loc[0]]
            return [Action(
                type="Skill", name=oper_name,
                location=[target_loc[1], target_loc[0]],
                ts=clip_start,
            )]
        return []

    def _analyze_clip(
        self, clip, pre_valid, detector, classifier,
        formation_opers, level, screen_size, positions,
        deployment_analyzer, video_frames,
    ) -> List[Action]:
        """Deploy/Retreat 推断（对齐 Maa analyze_clip + process_changes）。

        严格对齐 Maa ``analyze_clip``（CombatRecordRecognitionTask.cpp:481-496）：
        1. ``detect_operators(clip, pre_clip_ptr)`` —— YOLO 检测场上干员
        2. ``classify_direction(clip, pre_clip_ptr)`` —— 对 newcomer 分类方向
        3. ``process_changes(clip, pre_clip_ptr)`` —— 生成 action + 更新映射

        pre_valid 为 None 时（第一个 clip）不产出 action 也不更新映射
        （对齐 Maa ``process_changes`` 中 ``if (!pre_clip_ptr) return true``）。

        关键对齐点：映射（m_operator_locations / m_location_operators）仅在
        process_changes 的 Deploy/Retreat 分支内更新，不全局更新所有 battlefield
        tiles（对齐 Maa，行 736-737 / 758-759）。
        """
        actions: List[Action] = []
        battlefield = self._detect_battlefield_voted(
            clip, pre_valid, video_frames, detector, classifier,
            level, screen_size, positions,
        )
        deployment = self._recognize_deployment(
            clip, deployment_analyzer, formation_opers, video_frames,
        )
        # 把识别结果挂到 clip 上，供 _backfill_deployment_names 读取/改写
        clip.deployment = deployment
        clip.battlefield = battlefield
        if pre_valid is not None:
            # 对齐 Maa process_changes 行 694-695：
            # ananlyze_deployment_names(clip) + ananlyze_deployment_names(*pre_clip)
            self._backfill_deployment_names(pre_valid)
            self._backfill_deployment_names(clip)
            actions.extend(
                self._process_changes(
                    battlefield, deployment, pre_valid, clip,
                    deployment_analyzer,
                )
            )
        # 对齐 Maa：第一个 clip（pre_clip_ptr==null）直接 return，不更新映射
        return actions

    def _detect_battlefield_voted(
        self, clip, pre_valid, video_frames, detector, classifier,
        level, screen_size, positions,
    ) -> dict:
        """检测场上干员 + 方向分类（严格对齐 Maa 两步分离逻辑）。

        Maa 流程（CombatRecordRecognitionTask.cpp:555-673）：

        1. ``detect_operators``（行 555-624）：
           - 在 ``[det_begin, det_end]`` 内采样最多 20 帧
             （``OperDetSamplingCount=20``，``skip_count = frame_count/21 - 1``）
           - 每帧 YOLO 检测 → ``box.rect.move(det_box_move)`` → 找
             ``rect.include(t.pos)`` 的 tile → 收集 ``cur_locations`` 集
           - 以**整帧格子集合**为 key 计数：``oper_det_samping[cur_locations] += 1``
           - ``max_element`` 取计数最多的集合作为 ``clip.battlefield``
           - 采样帧存入 ``clip.random_frames``（供 classify_direction 复用）

        2. ``classify_direction``（行 626-673）：
           - ``if (!pre_clip_ptr)`` 跳过（第一个 clip 无方向分类）
           - 找 newcomer：``clip.battlefield`` 中有但 **``pre_clip.battlefield``** 没有的格子
           - 对每个 newcomer，遍历 ``random_frames``，累加 raw probs：
             ``dir_cls_sampling[loc][i] += result->deploy_direction.raw[i]``
           - ``argmax`` 取方向，无阈值
           - 设置 ``clip.battlefield[loc].direction`` 和 ``new_here = true``

        关键对齐点：
        - 众数是**整帧集合**，不是逐格子计票
        - newcomer 判定用 **pre_valid.battlefield**（对齐 Maa pre_clip.battlefield），
          非 location_operators
        - 方向复用用 **pre_valid.battlefield[loc].direction**（对齐 Maa），
          非 _last_oper_states
        - newcomer 标记 ``new_here=True``（对齐 Maa，供 process_changes 使用）
        """
        from arknights_video_recognition.battle.matcher import tile_to_screen_pos
        from arknights_video_recognition.battle.classifier import _DEPLOY_DIR_LABELS

        if detector is None:
            return {}
        start = getattr(clip, "start_time", 0.0) or 0.0
        end = getattr(clip, "end_time", start) or start
        if video_frames is None or end <= start:
            frames = [getattr(clip, "key_frame", None)]
        else:
            # 严格对齐 Maa detect_operators 的帧采样逻辑
            # (CombatRecordRecognitionTask.cpp:561-606)：
            # 1. frame_count = end_frame - start_frame
            # 2. skip_count = frame_count > 21 ? frame_count/21 - 1 : 0
            # 3. det_begin = start_frame + skip_count
            # 4. det_end = end_frame - skip_count
            # 5. 采样步长 = skip_count + 1
            # 关键：Maa 修剪 clip 边缘各 skip_count 帧，避免部署动画等过渡帧
            fps = video_frames.fps
            if fps > 0:
                start_frame = int(round(start * fps))
                end_frame = int(round(end * fps))
                frame_count = end_frame - start_frame
                if frame_count > _OPER_DET_SAMPLING_COUNT + 1:
                    skip_count = frame_count // (_OPER_DET_SAMPLING_COUNT + 1) - 1
                else:
                    skip_count = 0
                det_begin = start_frame + skip_count
                det_end = end_frame - skip_count

                frames = []
                i = det_begin
                step = skip_count + 1
                while i <= det_end:
                    ts = i / fps
                    f = video_frames.get_frame_at(ts)
                    if f is not None:
                        frames.append(f)
                    i += step

                if not frames:
                    frames = [getattr(clip, "key_frame", None)]
            else:
                # fps 缺失时退化为时间戳均匀采样
                duration = end - start
                n_frames = min(20, max(3, int(duration / 0.3) + 1))
                frames = []
                for k in range(n_frames):
                    ts = start + (end - start) * k / max(1, n_frames - 1)
                    f = video_frames.get_frame_at(ts)
                    if f is not None:
                        frames.append(f)
                if not frames:
                    frames = [getattr(clip, "key_frame", None)]

        # === 步骤 1：detect_operators —— 整帧集合众数 ===
        # 对齐 Maa oper_det_samping[cur_locations] += 1; max_element(...)
        # 有意偏离 Maa：先提取可部署格白名单，收集阶段丢弃落在非可部署格
        # （蓝门 tile_end、禁区等）上的检测——那里只可能是技能自动部署的
        # 召唤物（见 _buildable_tiles），不参与集合投票，避免假 newcomer
        buildable = self._buildable_tiles(level)
        set_votes: dict[frozenset, int] = {}
        set_boxes: dict[frozenset, dict[tuple, list]] = {}  # 集合 -> {tile: box}
        set_frames: dict[frozenset, np.ndarray] = {}  # 集合 -> 最后一次投该集合的帧（供头像裁剪）
        for frame in frames:
            if frame is None or frame.size == 0:
                continue
            dets = detector.detect(frame)
            cur_locations: set = set()
            cur_boxes: dict[tuple, list] = {}
            for d in dets:
                # 对齐 Maa rect.include(t.pos)：用 det_box_move 偏移 rect 包含测试
                tile = self._yolo_box_to_tile(
                    d.box, level, screen_size, positions
                )
                if tile is None:
                    continue
                if buildable is not None and tile not in buildable:
                    # 非可部署格上不会有玩家干员：丢弃召唤物/误检框
                    continue
                cur_locations.add(tile)
                cur_boxes[tile] = d.box
            if not cur_locations:
                continue
            key = frozenset(cur_locations)
            set_votes[key] = set_votes.get(key, 0) + 1
            if key not in set_boxes:
                set_boxes[key] = {}
            set_boxes[key].update(cur_boxes)
            # 整体覆盖，帧与 cur_boxes 同源（同为该采样帧）：
            # 召唤物比干员晚约 0.2s 出现，最晚投票帧上召唤物必然在场，裁出的
            # 头像才对应最终战场状态（供 M>N 场景头像仲裁使用）。
            set_frames[key] = frame

        # 取众数（对齐 Maa max_element(oper_det_samping)）
        if not set_votes:
            return {}
        mode_set = max(set_votes, key=lambda k: set_votes[k])
        mode_tiles = set(mode_set)

        # === 步骤 2：classify_direction —— 仅 newcomer 软投票 ===
        # 对齐 Maa classify_direction（行 626-673）：
        # newcomer = clip.bf 中有但 pre_clip.bf 中没有的格子
        # pre_clip 对应 pre_valid（上一个 deployment_changed=True 的 clip）
        prev_bf = getattr(pre_valid, "battlefield", None) or {}
        prev_tiles = set(prev_bf.keys())
        newcomers = [t for t in mode_tiles if t not in prev_tiles]

        # 对齐 Maa：if (!pre_clip_ptr) 跳过方向分类（第一个 clip）
        # 此时 newcomers 包含所有 mode_tiles，但 pre_valid=None 时不做方向分类
        dir_sampling: dict[tuple, np.ndarray] = {}
        if pre_valid is not None and newcomers and classifier is not None:
            for tile in newcomers:
                dir_sampling[tile] = np.zeros(4, dtype=np.float32)
            # tile→屏幕坐标仅依赖 tile/level，与帧无关：在帧循环外预取一次，
            # 避免每帧重复调用 tile_to_screen_pos
            newcomer_positions = {
                tile: tile_to_screen_pos(
                    tile, level, screen_size, positions=positions
                )
                for tile in newcomers
            }
            for frame in frames:
                if frame is None or frame.size == 0:
                    continue
                for tile in newcomers:
                    tile_pos = newcomer_positions[tile]
                    if tile_pos is None:
                        continue
                    dir_patch = self._crop_rect_move(
                        frame, tile_pos, self._dir_rect_move
                    )
                    if dir_patch.size == 0:
                        continue
                    _, probs = classifier.classify_deploy_direction(dir_patch)
                    dir_sampling[tile] += probs

        # 构造 _OperState
        final_frame = set_frames.get(mode_set)
        final_boxes = set_boxes[mode_set]
        battlefield: dict = {}
        for tile in mode_tiles:
            is_newcomer = tile in newcomers and pre_valid is not None
            if is_newcomer:
                # newcomer：argmax(Σ raw)（严格对齐 Maa classify_direction）
                # Maa 行 665-668: max_element(sampling) 无阈值，直接取 argmax。
                # dir_sampling[tile] 是原始模型输出累加（非 softmax），值可正可负，
                # 不做 > 0 阈值检查（否则负值会被误判为无方向）。
                probs = dir_sampling.get(tile)
                if probs is not None:
                    direction = _DEPLOY_DIR_LABELS[int(np.argmax(probs))]
                else:
                    direction = "None"
            elif pre_valid is not None and tile in prev_bf:
                # 已存在格子：复用 pre_clip.bf 的 direction（对齐 Maa）
                prev_state = prev_bf.get(tile)
                direction = getattr(prev_state, "direction", "None") if prev_state else "None"
            else:
                # pre_valid=None（第一个 clip）或 prev_bf 无此格子：方向未知
                direction = "None"
            name = self.location_operators.get(tile, "Unknown")
            box = final_boxes.get(tile, [0, 0, 0, 0])
            # 战场头像（供 M>N 场景 _score_tile_name_pairs 仲裁使用）
            avatar = (
                self._crop_avatar_from_box(final_frame, box)
                if final_frame is not None else None
            )
            battlefield[tile] = _OperState(
                name=name, tile=tile, direction=direction,
                skill_ready="n", box=box, avatar=avatar,
                new_here=is_newcomer,  # 对齐 Maa：newcomer 标记 new_here=True
            )
        return battlefield

    def _recognize_deployment(
        self, clip, deployment_analyzer, formation_opers, video_frames=None,
    ) -> list:
        """部署栏槽位检测（仅检测，不匹配名字）。

        严格对齐 Maa ``slice_video`` 中对 clip.deployment 的记录
        （CombatRecordRecognitionTask.cpp:419-424）：

        Maa 逻辑：
        - 切片时对每帧调用 ``BattlefieldMatcher.deployment_analyze()``
        - 记录 ``info.deployment = cur_opers``（DeploymentOper list，含
          rect/role/avatar 60×60/name=""）
        - name 在 ``process_changes`` 时由 ``ananlyze_deployment_names`` 用
          ``m_all_avatars`` 赋值

        本实现对应 Maa 的"记录 deployment"步骤：单帧检测部署栏槽位，
        返回 ``[{name="Unknown", role, avatar}]``，name 留空由
        ``_backfill_deployment_names`` 赋值。

        关键对齐点：
        - **单帧检测**：Maa 用切片时的单帧，无多帧合并
        - **不匹配名字**：name 留空 "Unknown"，由 _backfill_deployment_names 赋值
        - **不缓存 all_avatars**：Maa 的 m_all_avatars 只在 analyze_deployment
          中一次性写入，永不更新
        """
        if deployment_analyzer is None:
            return []
        frame = getattr(clip, "key_frame", None)
        if frame is None or frame.size == 0:
            return []
        slots = deployment_analyzer.detect_slots(frame)
        return [
            {
                "name": "Unknown",  # 由 _backfill_deployment_names 赋值
                "role": slot.get("role", "Unknown"),
                "avatar": slot["avatar"],
            }
            for slot in slots
        ]

    def _process_changes(
        self, battlefield, deployment, pre_valid, clip,
        deployment_analyzer=None,
    ) -> List[Action]:
        """生成 Deploy/Retreat action + 更新映射（严格对齐 Maa ``process_changes``）。

        Maa 逻辑（CombatRecordRecognitionTask.cpp:675-773）：

        - Deploy 分支（OR）：``pre.dep.size > cur.dep.size`` 或
          ``pre.bf.size < cur.bf.size``
          1. ``ananlyze_deployment_names(clip)`` + ``ananlyze_deployment_names(pre_clip)``
          2. ``deployed = [name in pre.dep but not in clip.dep]``（按 pre.dep 顺序）
          3. 对 ``clip.bf`` 中 ``new_here`` 的格子，按顺序配 deployed name：
             ``name = deployed_iter.next() or pre_clip.ends_oper_name or "Unknown_EndsEmpty"``
          4. 更新双向映射 ``insert_or_assign``（行 736-737）

        - Retreat 分支（OR）：``pre.dep.size < cur.dep.size`` 或
          ``pre.bf.size > cur.bf.size``
          1. 找 ``pre.bf`` 中有但 ``clip.bf`` 中没有的格子
          2. ``name = m_location_operators[pre_loc]``
          3. 删除双向映射 ``erase``（行 758-759）

        - Unknown 分支：其他情况，只 warn 不生成 action

        有意偏离 Maa（自动召唤物防护，仅 ``_AUTO_SUMMON_OPERATORS`` 白名单
        干员生效，见方法内注释与 ``_pair_newcomers``）：
        - Deploy 侧：白名单干员在本批部署中或已在场上且新增格多于消失名
          （M > N）时，多余格视为其自动召唤物跳过（数量守卫 + 头像仲裁）；
          其他干员保留 Maa 兜底配对（ends_oper_name → Unknown_EndsEmpty）。
        - Retreat 侧：从未入映射的消失格不产出空名/占位名 Retreat（召唤物
          的出现与撤退均不经部署栏，无从命名）。

        严格对齐：
        - ``prev_bf`` 用 ``pre_valid.battlefield``（对齐 Maa pre_clip.battlefield）
        - Deploy 目标格子用 ``oper.new_here``（对齐 Maa，由 classify_direction 设置）
        - 映射更新仅在 Deploy/Retreat 分支内，不全局更新（对齐 Maa）
        - location 输出 ``[loc[1], loc[0]]`` = ``[col, row]``（对齐 Maa ``[loc.x, loc.y]``）
        """
        actions: List[Action] = []
        clip_ts = getattr(clip, "start_time", None)

        # 对齐 Maa：prev_bf 直接用 pre_valid.battlefield，不从映射反推
        prev_bf = getattr(pre_valid, "battlefield", None) or {}
        prev_dep = getattr(pre_valid, "deployment", []) or []

        # 对齐 Maa 分支判定（OR 条件）
        deploy_branch = (
            len(prev_dep) > len(deployment)
            or len(prev_bf) < len(battlefield)
        )
        retreat_branch = (
            len(prev_dep) < len(deployment)
            or len(prev_bf) > len(battlefield)
        )

        if deploy_branch:
            # === Deploy 分支（对齐 Maa 行 690-741，有意偏离点见下）===
            # deployed：pre.dep 中有但 clip.dep 中没有的 name（按 pre.dep 顺序）
            cur_names = {d.get("name", "") for d in deployment}
            deployed = [
                d.get("name", "") for d in prev_dep
                if d.get("name", "") and d.get("name", "") not in cur_names
            ]

            # 召唤物守卫（有意偏离 Maa，仅 _AUTO_SUMMON_OPERATORS 白名单干员生效）：
            # 白名单干员（维什戴尔）的召唤物随部署/开技能自动部署在可部署格上，
            # 不占部署栏槽位（出现与撤退均不改变部署栏），只增加场上新生格子，
            # 使新增格多于部署栏消失名（M > N）。守卫生效时多余格视为召唤物
            # 跳过（数量守卫 + 头像仲裁，不产出 Deploy、不写入映射），防止召唤物
            # 被误判为手动部署或抢占真干员的名字。
            # 守卫范围：本批部署含白名单干员（部署触发召唤），或白名单干员已在
            # 场上（其技能召唤物可在后续任意 clip 浮现）。
            # 其他干员不启用守卫：其 M > N 属检测异常，保留 Maa 兜底配对
            # （ends_oper_name → Unknown_EndsEmpty），避免误丢真实部署。
            new_tiles = sorted(
                loc for loc, oper in battlefield.items()
                if getattr(oper, "new_here", False)
            )
            summon_guard = (
                any(n in _AUTO_SUMMON_OPERATORS for n in deployed)
                or any(
                    n in _AUTO_SUMMON_OPERATORS
                    for n in self.operator_locations
                )
            )
            if summon_guard and new_tiles and len(new_tiles) > len(deployed):
                pairs = self._pair_newcomers(new_tiles, deployed, battlefield)
                logger.warning(
                    "场上新增 %d 个单位但部署栏仅消失 %d 个槽位，多余 %d 个"
                    "疑似白名单干员自动召唤物，已跳过其 Deploy/映射",
                    len(new_tiles), len(deployed), len(new_tiles) - len(deployed),
                )
            else:
                # Maa 兜底配对（对齐 Maa 行 715-734）：按格子坐标序配 deployed
                # 名，耗尽后回退 pre_clip.ends_oper_name，仍空用占位名
                ends_name = getattr(pre_valid, "ends_oper_name", "")
                pairs = []
                name_iter = iter(deployed)
                for loc in new_tiles:
                    try:
                        name = next(name_iter)
                    except StopIteration:
                        name = ends_name
                    if not name:
                        name = "Unknown_EndsEmpty"
                    pairs.append((loc, name))
            for loc, name in pairs:
                oper = battlefield[loc]
                oper.name = name
                actions.append(Action(
                    type="Deploy", name=name,
                    # 对齐 Maa 行 730: location = [loc.x, loc.y] = [col, row]
                    # Python tiles 是 (row, col)，故输出 [loc[1], loc[0]]
                    location=[loc[1], loc[0]],
                    direction=getattr(oper, "direction", "None"),
                    ts=clip_ts,
                ))
                # 对齐 Maa 行 736-737：insert_or_assign(name, loc) + (loc, name)
                self.operator_locations[name] = loc
                self.location_operators[loc] = name
                # 仅记录部署时间戳（诊断用途），当前无读取方
                if clip_ts is not None:
                    self._deploy_times[name] = clip_ts
        elif retreat_branch:
            # === Retreat 分支（对齐 Maa 行 742-761）===
            # 对齐 Maa：找 pre.bf 中有但 clip.bf 中没有的格子
            for loc in prev_bf:
                if loc in battlefield:
                    continue
                # name 来自 m_location_operators[pre_loc]（对齐 Maa）
                name = self.location_operators.get(loc, "")
                # 有意偏离 Maa：从未入映射的格子（白名单干员的自动召唤物，
                # 其出现与撤退均不改变部署栏，无从命名）不产出空名/占位名
                # Retreat，避免假撤退污染最终 JSON
                if not name:
                    continue
                actions.append(Action(
                    type="Retreat", name=name,
                    # 对齐 Maa 行 752: location = [pre_loc.x, pre_loc.y] = [col, row]
                    location=[loc[1], loc[0]],
                    ts=clip_ts,
                ))
                # 对齐 Maa 行 758-759：erase(pre_loc) + erase(name)
                self.location_operators.pop(loc, None)
                # name 经上方 `if not name: continue` 保证非空，无需再判
                self.operator_locations.pop(name, None)
        # else: Unknown 分支（对齐 Maa 行 762-771）：只 warn 不生成 action

        return actions

    # --- 自动召唤物防护：Deploy 配对（有意偏离 Maa）--------------------------

    def _pair_newcomers(self, new_tiles, deployed, battlefield):
        """把 ``new_here`` 格子与新部署干员名配对（数量守卫 + 头像仲裁）。

        背景：手动部署必然伴随部署栏槽位减少（``deployed`` 长度 N = 消失槽位数），
        而白名单干员（``_AUTO_SUMMON_OPERATORS``，如维什戴尔）的自动召唤物
        **出现时不经部署栏流程**（随本体部署或开技能自动上场上），只会增加
        场上新生格子。故在守卫生效的 clip 中：
        - ``M = len(new_tiles)`` 恒等于 手动部署数 + 自动召唤物数；
        - ``M > N``  ⟺  存在自动召唤物（假设检测无误差）。

        注：本方法仅由 ``_process_changes`` Deploy 分支在召唤物守卫生效
        （白名单干员部署/在场且 M > N）时调用；其他干员的 M > N 走 Maa
        兜底配对（见 _process_changes）。召唤物的出现与撤退均不经部署栏。

        配对规则：
        - ``M <= N``：无自动召唤物，按格子坐标序全配对（对齐 Maa battlefield=
          ``std::map`` 的有序遍历），多余名字丢弃。
        - ``M > N``：存在自动召唤物。用战场头像↔部署栏已定名头像的相对匹配
          分数贪心配对前 N 个格子，其余格子视为召唤物跳过（不产出 Deploy、
          不写入映射）。
        - 头像数据不可用（``all_avatars`` 缺失 / 战场头像未采集）时回退为按坐标
          序取前 N 个——仲裁是相对增强，不作为硬依赖，保证不比旧行为更差。
        - ``deployed`` 为空但 ``new_tiles`` 非空（纯召唤物 clip）：返回空，全部跳过。

        Parameters
        ----------
        new_tiles:
            按 ``(row, col)`` 排序的本次新部署格列表。
        deployed:
            部署栏 diff 出的本批干员名列表（调用方已过滤空名与当前仍在槽位的名字）。
        battlefield:
            当前 clip 战场 ``{tile: _OperState}``。

        Returns
        -------
        list[tuple[tuple, str]]
            ``[(tile, name), ...]`` 配对结果，长度 <= ``min(M, N)``。
        """
        if not new_tiles or not deployed:
            return []
        if len(new_tiles) <= len(deployed):
            return list(zip(new_tiles, deployed[:len(new_tiles)]))
        # M > N：优先头像仲裁
        scores = self._score_tile_name_pairs(new_tiles, deployed, battlefield)
        if scores is None:
            # 回退：按坐标序取前 N（确定性的保守策略，不产生任何名字兜底）
            return list(zip(new_tiles[:len(deployed)], deployed))
        # 贪心：反复取剩余 (tile, name) 中分数最高者，直到名字耗尽。
        # 只用相对排序，不设绝对阈值——不会因召唤物头像匹配分偏低而误杀真干员。
        pairs = []
        used_tiles = set()
        used_names = set()
        for _ in range(len(deployed)):
            best = None
            for score, tile, name in scores:
                if tile in used_tiles or name in used_names:
                    continue
                if best is None or score > best[0]:
                    best = (score, tile, name)
            if best is None:
                break
            _, tile, name = best
            pairs.append((tile, name))
            used_tiles.add(tile)
            used_names.add(name)
        return pairs

    def _score_tile_name_pairs(self, new_tiles, deployed, battlefield):
        """为 M>N 场景计算 ``(tile, name)`` 的头像匹配分数。

        用战场头像（``_OperState.avatar``，_detect_battlefield_voted 采集）作 scene、
        ``self.all_avatars[name]``（部署栏已定名头像）作模板，TM_CCOEFF_NORMED 打分。

        任一数据缺失（``all_avatars`` 为空 / 某格或某名头像未采集）返回 ``None``，
        调用方回退为坐标序配对。

        Returns
        -------
        list[tuple[float, tuple, str]] or None
            ``[(score, tile, name), ...]``；数据不可用时返回 ``None``。
        """
        if not self.all_avatars:
            return None
        scores = []
        for tile in new_tiles:
            oper = battlefield.get(tile)
            avatar = getattr(oper, "avatar", None) if oper else None
            if avatar is None or avatar.size == 0:
                return None  # 任一格子缺头像 → 整体回退
            for name in deployed:
                tpl = self.all_avatars.get(name)
                if tpl is None or tpl.size == 0:
                    return None
                if tpl.shape != avatar.shape:
                    tpl_r = cv2.resize(
                        tpl, (avatar.shape[1], avatar.shape[0]),
                        interpolation=cv2.INTER_AREA,
                    )
                else:
                    tpl_r = tpl
                # 对齐 DeploymentAnalyzer：BGR 彩色 TM_CCOEFF_NORMED
                r = cv2.matchTemplate(avatar, tpl_r, cv2.TM_CCOEFF_NORMED)
                s = float(r.max()) if r.size else -1.0
                scores.append((s, tile, name))
        return scores

    @staticmethod
    def _crop_avatar_from_box(frame, box):
        """从 YOLO 检测框裁剪战场单位头像（供 M>N 场景头像仲裁）。

        直接用框坐标在帧上裁剪；尺寸不必为 60×60，打分侧会缩放到与部署栏
        头像一致。框非法或越界返回 ``None``。
        """
        if frame is None or frame.size == 0 or not box or len(box) < 4:
            return None
        x, y, w, h = (int(v) for v in box[:4])
        x0, y0 = max(0, x), max(0, y)
        x1 = min(frame.shape[1], x + w)
        y1 = min(frame.shape[0], y + h)
        if x1 <= x0 or y1 <= y0:
            return None
        return frame[y0:y1, x0:x1]

    def _skill_ready_at(
        self, frame, tile, classifier, level, screen_size, positions,
    ) -> str:
        """把 tile 转屏幕坐标，裁 BattleSkillReady 区域，分类返回 y/n/c。"""
        from arknights_video_recognition.battle.matcher import tile_to_screen_pos

        screen_pos = tile_to_screen_pos(
            tile, level, screen_size, positions=positions
        )
        if screen_pos is None:
            return "n"
        patch = self._crop_rect_move(frame, screen_pos, self._skill_rect_move)
        if patch.size == 0:
            return "n"
        return classifier.classify_skill_ready(patch)
