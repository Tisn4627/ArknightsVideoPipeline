"""部署栏识别：模板匹配 BattleOpersFlag 定位槽位，裁剪 60×60 头像。

对齐 Maa ``CombatRecordRecognitionTask::analyze_deployment`` 的槽位定位：
用 ``BattleOpersFlag`` 模板在底部窄横条 ROI 上做 matchTemplate，NMS 去重，
每个 flag 位置用 rectMove ``[7, 32, 60, 60]`` 裁剪 60×60 头像。

身份匹配分两阶段（对齐 Maa）：
- 阶段 1 ``match_with_formation``：30×30 脸部子区多尺度匹配编队半身像
- 阶段 2 ``match_with_known_avatars``：60×60 直接匹配已定名头像
"""
from __future__ import annotations

import json
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from arknights_video_recognition.config.settings import (
    BATTLE_DATA_PATH,
    BATTLE_OPERS_FLAG_TEMPLATE,
    BATTLE_OPER_ROLE_DIR,
    BATTLE_OPER_ROLE_RECT_MOVE,
    BATTLE_OPER_ROLE_THRESHOLD,
    CHAR_ROLE_TABLE_PATH,
    DEPLOYMENT_AVATAR_MOVE,
    DEPLOYMENT_FACE_MOVE,
    DEPLOYMENT_FLAG_NMS_DIST,
    DEPLOYMENT_FLAG_ROI,
    DEPLOYMENT_FLAG_THRESHOLD,
    DEPLOYMENT_MATCH_THRESHOLD,
    DEPLOYMENT_NAME_MATCH_THRESHOLD,
    TEMPLATE_DIR,
)


class DeploymentAnalyzer:
    """部署栏槽位定位与身份匹配。

    Parameters
    ----------
    flag_template_path:
        ``BattleOpersFlag.png`` 路径，默认取配置常量。
    """

    # 9 个职业模板（已下载至 resource/template/Battle/OperRole/）
    # 对齐 Maa BattlefieldMatcher::oper_role_analyze 的 BestMatcher
    _ROLE_TEMPLATES = {
        "Pioneer": "BattleOperRolePioneer.png",
        "Warrior": "BattleOperRoleWarrior.png",
        "Tank":    "BattleOperRoleTank.png",
        "Sniper":  "BattleOperRoleSniper.png",
        "Caster":  "BattleOperRoleCaster.png",
        "Medic":   "BattleOperRoleMedic.png",
        "Support": "BattleOperRoleSupport.png",
        "Special": "BattleOperRoleSpecial.png",
        "Drone":   "BattleOperRoleDrone.png",
    }

    def __init__(self, flag_template_path: Optional[str] = None):
        path = flag_template_path or str(BATTLE_OPERS_FLAG_TEMPLATE)
        tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            raise RuntimeError(f"读取 BattleOpersFlag 模板失败：{path}")
        self._flag_gray = tpl
        self._flag_roi = list(DEPLOYMENT_FLAG_ROI)
        self._flag_thr = float(DEPLOYMENT_FLAG_THRESHOLD)
        self._nms_dist = int(DEPLOYMENT_FLAG_NMS_DIST)
        self._avatar_move = list(DEPLOYMENT_AVATAR_MOVE)
        self._face_move = list(DEPLOYMENT_FACE_MOVE)
        self._match_thr = float(DEPLOYMENT_MATCH_THRESHOLD)
        self._name_match_thr = float(DEPLOYMENT_NAME_MATCH_THRESHOLD)
        self._role_templates = self._load_role_templates()
        self._role_rect_move = list(BATTLE_OPER_ROLE_RECT_MOVE)
        self._role_threshold = float(BATTLE_OPER_ROLE_THRESHOLD)
        # 加载 char_roles.json（缺失时降级为空 dict，不过滤）
        self._char_roles: dict[str, str] = {}
        try:
            if CHAR_ROLE_TABLE_PATH.exists():
                self._char_roles = json.loads(
                    CHAR_ROLE_TABLE_PATH.read_text(encoding="utf-8")
                )
        except Exception:
            self._char_roles = {}
        # 加载 battle_data.json → name→rarity（对齐 Maa BattleData.get_rarity）
        # 用于 match_with_formation 的尺度范围：rarity==1（小车）用 1.00-1.99，
        # 其余用 1.00-1.24（对齐 Maa analyze_deployment 的 scale_ends=200/125）
        self._char_rarities: dict[str, int] = {}
        try:
            if BATTLE_DATA_PATH.exists():
                data = json.loads(BATTLE_DATA_PATH.read_text(encoding="utf-8"))
                for _cid, info in (data or {}).get("chars", {}).items():
                    r = info.get("rarity")
                    nm = info.get("name")
                    if r is not None and nm:
                        self._char_rarities[nm] = int(r)
        except Exception:
            self._char_rarities = {}

    # --- 职业识别（对齐 Maa BattleOperRole） -----------------------------

    def _load_role_templates(self) -> dict:
        """加载 9 个职业彩色模板（BGR）。

        对齐 Maa ``BattlefieldMatcher::oper_role_analyze``：BestMatcher 在原始
        BGR 彩色图上 matchTemplate，不做灰度转换。角色图标靠颜色区分
        （Support 青色 vs Drone 灰色），灰度匹配会丢失颜色信息导致误分类。

        Returns
        -------
        dict
            ``{role_name: bgr_template_ndarray}``。缺失文件跳过，不抛异常。
        """
        out: dict = {}
        for role, fname in self._ROLE_TEMPLATES.items():
            tpl_path = BATTLE_OPER_ROLE_DIR / fname
            tpl = cv2.imread(str(tpl_path), cv2.IMREAD_COLOR)
            if tpl is not None:
                out[role] = tpl
        return out

    def _classify_role(
        self, frame: np.ndarray, fx: int, fy: int
    ) -> str:
        """9 个职业模板 BestMatcher，返回最佳匹配职业名。

        对齐 Maa ``oper_role_analyze``（BattlefieldMatcher.cpp:162-197）：
        - BestMatcher 在 BGR 彩色图上 matchTemplate（TM_CCOEFF_NORMED）
        - threshold=0.65（BattleOperRole task config）
        - 9 个模板取最高分，无匹配返回 Unknown

        Parameters
        ----------
        frame:
            BGR 帧（1280x720）。
        fx, fy:
            flag 左上角坐标（来自 detect_slots 的 flag_pos）。

        Returns
        -------
        str
            职业名（Pioneer/Warrior/.../Drone），无匹配返回 "Unknown"。
        """
        if frame is None or frame.size == 0 or not self._role_templates:
            return "Unknown"
        dx, dy, w, h = self._role_rect_move
        H, W = frame.shape[:2]
        x0 = max(0, fx + dx)
        y0 = max(0, fy + dy)
        x1 = min(W, fx + dx + w)
        y1 = min(H, fy + dy + h)
        if x1 <= x0 or y1 <= y0:
            return "Unknown"
        role_roi = frame[y0:y1, x0:x1]
        if role_roi.size == 0:
            return "Unknown"
        # 对齐 Maa：BGR 彩色匹配（不做灰度转换）
        roi_bgr = role_roi
        best_name, best_score = "Unknown", -1.0
        for name, tpl in self._role_templates.items():
            if tpl.shape[0] > roi_bgr.shape[0] or tpl.shape[1] > roi_bgr.shape[1]:
                continue
            res = cv2.matchTemplate(roi_bgr, tpl, cv2.TM_CCOEFF_NORMED)
            score = float(res.max()) if res.size else -1.0
            if score > best_score:
                best_score, best_name = score, name
        return best_name if best_score >= self._role_threshold else "Unknown"

    # --- 槽位定位 ----------------------------------------------------------

    def detect_flags(self, frame: np.ndarray) -> List[Tuple[int, int]]:
        """轻量级部署栏 flag 检测（无 role 分类），返回 flag 位置列表。

        对齐 Maa ``deployment_analyze`` 的 flag 定位 + NMS 部分，跳过
        role 分类和 avatar 裁剪，用于切片器的高频逐帧检测（性能优化：
        _classify_role 的 9 次 matchTemplate 是逐帧检测的瓶颈）。

        Parameters
        ----------
        frame:
            战斗帧（BGR，1280×720）。

        Returns
        -------
        list[tuple[int, int]]
            flag 左上角坐标列表，按 x 升序。黑帧或无匹配返回空列表。
        """
        if frame is None or frame.size == 0:
            return []
        if frame.mean() < 10:
            return []

        rx, ry, rw, rh = self._flag_roi
        H, W = frame.shape[:2]
        x0 = max(0, rx)
        y0 = max(0, ry)
        x1 = min(W, rx + rw)
        y1 = min(H, ry + rh)
        if x1 <= x0 or y1 <= y0:
            return []
        roi = frame[y0:y1, x0:x1]
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        res = cv2.matchTemplate(roi_gray, self._flag_gray, cv2.TM_CCOEFF_NORMED)
        if res.size == 0:
            return []
        locs = np.where(res >= self._flag_thr)
        if len(locs[0]) == 0:
            return []

        scores = res[locs]
        order = np.argsort(-scores)
        pts = [(int(locs[1][i]) + x0, int(locs[0][i]) + y0) for i in order]

        kept: List[Tuple[int, int]] = []
        for px, py in pts:
            if all((px - kx) ** 2 + (py - ky) ** 2 >= self._nms_dist ** 2
                   for kx, ky in kept):
                kept.append((px, py))
        kept.sort(key=lambda p: p[0])
        return kept

    def detect_slots(self, frame: np.ndarray) -> List[dict]:
        """检测部署栏槽位，返回 [{flag_pos, avatar, box}, ...]。

        Parameters
        ----------
        frame:
            战斗帧（BGR，1280×720）。

        Returns
        -------
        list[dict]
            每个槽位含：
            - ``flag_pos``: (x, y) flag 左上角
            - ``avatar``: 60×60 BGR 头像
            - ``box``: [x, y, w, h] 头像绝对坐标
            黑帧或无匹配返回空列表。
        """
        if frame is None or frame.size == 0:
            return []
        if frame.mean() < 10:
            return []

        kept = self.detect_flags(frame)
        if not kept:
            return []

        H, W = frame.shape[:2]
        slots: List[dict] = []
        ax_off, ay_off, aw, ah = self._avatar_move
        for fx, fy in kept:
            ax = fx + ax_off
            ay = fy + ay_off
            av_x0 = max(0, ax)
            av_y0 = max(0, ay)
            av_x1 = min(W, ax + aw)
            av_y1 = min(H, ay + ah)
            if av_x1 <= av_x0 or av_y1 <= av_y0:
                continue
            role = self._classify_role(frame, fx, fy)
            # 对齐 Maa deployment_analyze：role==Unknown 时跳过该槽位
            # （CombatRecordRecognitionTask.cpp:108-111: if (oper.role == Unknown) continue）
            if role == "Unknown":
                continue
            avatar = frame[av_y0:av_y1, av_x0:av_x1]
            slots.append({
                "flag_pos": (fx, fy),
                "avatar": avatar,
                "box": [av_x0, av_y0, av_x1 - av_x0, av_y1 - av_y0],
                "role": role,
            })
        return slots

    # --- 阶段 1：编队↔部署栏匹配 ------------------------------------------

    def match_with_formation(
        self,
        slot_avatar: np.ndarray,
        formation_opers: Sequence,
        role_hint: Optional[str] = None,
    ) -> Tuple[str, float]:
        """30×30 脸部子区多尺度匹配编队半身像，返回 (name, score)。

        严格对齐 Maa ``analyze_deployment``（CombatRecordRecognitionTask.cpp:259-297）：

        Maa 逻辑（每个 formation_oper 一次 BestMatcher）：
        - ``BestMatcher best_match_analyzer(formation_avatar)``：编队半身像作 scene
        - ``roles = { BattleData.get_role(name) }``，阿米娅额外加 Warrior
        - 对每个 role 匹配的 deployment slot：
          - ``crop_avatar = oper.avatar(crop_roi)``：[15,15,30,30] 裁 30×30 脸部
          - ``scale_ends = get_rarity(name)==1 ? 200 : 125``
          - ``for (i=100; i<scale_ends; ++i)``：scale=i/100.0，resize crop_avatar
            （``resize_method = scale<1.0 ? INTER_AREA : INTER_LINEAR`` → 始终 INTER_LINEAR）
          - ``append_templ(flag, resized)``：缩放后的脸部作模板
        - ``analyze()``：TM_CCOEFF_NORMED 在 formation_avatar 上滑窗，取最高分

        本实现按 (slot, fo) 对调用：scene=fo_avatar，模板=slot 脸部多尺度缩放，
        等价于 Maa 单 fo BestMatcher 内对该 slot 的打分。

        Parameters
        ----------
        slot_avatar:
            部署栏 60×60 BGR 头像。
        formation_opers:
            ``FormationOper`` 列表，取 ``.avatar`` 和 ``.name``。

        Returns
        -------
        tuple
            (最佳匹配干员名, 最高分)。无匹配返回 ("Unknown", -1.0)。
        """
        if slot_avatar is None or slot_avatar.size == 0 or not formation_opers:
            return "Unknown", -1.0

        # 裁 30×30 脸部子区（BGR 彩色，对齐 Maa BestMatcher 在原始彩色图上 matchTemplate）
        fx_off, fy_off, fw, fh = self._face_move
        face = slot_avatar[fy_off:fy_off + fh, fx_off:fx_off + fw]
        if face.size == 0:
            return "Unknown", -1.0
        face_h, face_w = face.shape[:2]

        best_name = "Unknown"
        best_score = -1.0
        for fo in formation_opers:
            fo_avatar = getattr(fo, "avatar", None)
            if fo_avatar is None or fo_avatar.size == 0:
                continue
            # role 过滤（对齐 Maa BattleData.get_role）
            # role_hint 为 None 或 "Unknown"（分类失败）时跳过过滤，避免误杀
            # fo_role 为 None（char_roles 缺条目）时降级为不过滤，对齐 Maa 永远可用语义
            if role_hint is not None and role_hint != "Unknown":
                fo_role = self._char_roles.get(fo.name)
                if fo_role is not None and fo_role != role_hint:
                    # 阿米娅特例：额外允许 Warrior
                    if not (fo.name == "阿米娅" and role_hint == "Warrior"):
                        continue

            # 对齐 Maa：scale_ends = get_rarity(name)==1 ? 200 : 125
            # for (i=100; i<scale_ends; ++i) avatar_scale = i/100.0
            rarity = self._char_rarities.get(fo.name)
            scale_ends = 200 if rarity == 1 else 125
            scene_bgr = fo_avatar
            scene_h, scene_w = scene_bgr.shape[:2]
            for i in range(100, scale_ends):
                scale = i / 100.0
                # 对齐 Maa：resize_method = scale<1.0 ? INTER_AREA : INTER_LINEAR
                # min scale=1.0 → 始终 INTER_LINEAR
                rw = max(1, int(face_w * scale))
                rh = max(1, int(face_h * scale))
                if rw > scene_w or rh > scene_h:
                    continue
                face_r = cv2.resize(face, (rw, rh), interpolation=cv2.INTER_LINEAR)
                r = cv2.matchTemplate(scene_bgr, face_r, cv2.TM_CCOEFF_NORMED)
                s = float(r.max()) if r.size else -1.0
                if s > best_score:
                    best_score = s
                    best_name = fo.name
        if best_score < self._match_thr:
            best_name = "Unknown"
        return best_name, best_score

    # --- 阶段 2：部署栏↔部署栏匹配 ----------------------------------------

    def match_with_known_avatars(
        self,
        slot_avatar: np.ndarray,
        known_avatars: dict,
        role_hint: Optional[str] = None,
    ) -> Tuple[str, float]:
        """60×60 直接匹配已定名头像，返回 (name, score)。

        严格对齐 Maa ``ananlyze_deployment_names``（CombatRecordRecognitionTask.cpp:783-806）：

        - ``BestMatcher avatar_analyzer(oper.avatar)``：slot 60×60 作 scene
        - ``avatar_analyzer.set_method(MatchMethod::Ccoeff)``
        - ``avatar_analyzer.set_threshold(threshold)``：BattleAvatarDataForVideo=0.6
        - 对 m_all_avatars 中每个 (name, avatar)：role 硬过滤后 append_templ
        - ``analyze()``：取最高分模板

        关键对齐点：
        - **TM_CCOEFF_NORMED**：Maa ``MatchMethod::Ccoeff`` 在 Matcher.cpp:188 统一映射到
          ``cv::TM_CCOEFF_NORMED``（注释："目前所有的匹配都是用 TM_CCOEFF_NORMED"）。
          分数范围 [-1, 1]，阈值 0.6 是有意义的过滤。
        - **BGR 彩色匹配**：Maa BestMatcher 在原始彩色图上 matchTemplate。
        - **role 硬过滤**：slot.role not in candidate roles 则跳过该模板。

        Parameters
        ----------
        slot_avatar:
            新部署栏 60×60 BGR 头像。
        known_avatars:
            ``{name: 60×60 BGR 头像}`` 字典（来自阶段 1 的输出）。

        Returns
        -------
        tuple
            (最佳匹配干员名, 最高分)。无匹配返回 ("Unknown", -1.0)。
        """
        if slot_avatar is None or slot_avatar.size == 0 or not known_avatars:
            return "Unknown", -1.0
        a_bgr = slot_avatar
        best_name = "Unknown"
        best_score = -1.0
        for name, tpl in known_avatars.items():
            if tpl is None or tpl.size == 0:
                continue
            # role 过滤（role_hint 为 None 或 "Unknown" 时跳过）
            # tpl_role 为 None（char_roles 缺条目）时降级为不过滤，对齐 Maa 永远可用语义
            if role_hint is not None and role_hint != "Unknown":
                tpl_role = self._char_roles.get(name)
                if tpl_role is not None and tpl_role != role_hint:
                    if not (name == "阿米娅" and role_hint == "Warrior"):
                        continue
            tpl_bgr = tpl
            if tpl_bgr.shape != a_bgr.shape:
                tpl_bgr = cv2.resize(
                    tpl_bgr, (a_bgr.shape[1], a_bgr.shape[0]),
                    interpolation=cv2.INTER_AREA,
                )
            # 对齐 Maa: MatchMethod::Ccoeff → TM_CCOEFF_NORMED（Matcher.cpp:188）
            r = cv2.matchTemplate(a_bgr, tpl_bgr, cv2.TM_CCOEFF_NORMED)
            s = float(r.max()) if r.size else -1.0
            if s > best_score:
                best_score = s
                best_name = name
        # 对齐 Maa: threshold=0.6 (BattleAvatarDataForVideo)
        if best_score < self._name_match_thr:
            best_name = "Unknown"
        return best_name, best_score
