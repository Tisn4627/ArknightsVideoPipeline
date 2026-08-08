"""助战干员识别模块：在编队页面定位助战槽位并匹配出助战干员名。

流程：先在开始按钮 ROI 上做 OCR，找出「开始行动」按钮连续稳定的窗口
（说明玩家停留在编队页面），再在该窗口最后一帧上模板匹配助战空槽位
图，裁剪助战头像并与头像库做 matchTemplate 匹配，得到助战干员名。
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Optional, List, Tuple

import cv2
import numpy as np

from ArknightsVideoRecognition.config.roi import get_roi, load_roi
from ArknightsVideoRecognition.config.settings import (
    AVATAR_DIR, SUPPORT_TEMPLATE, SUPPORT_MATCH_THRESHOLD,
    SUPPORT_EMPTY_THRESHOLD, START_BUTTON_STABLE_FRAMES,
    SUPPORT_DETECT_MAX_SEC, DATA_DIR, SUPPORT_SLOT_ROI,
    START_BUTTON_FORMATION_ROI,
)
from ArknightsVideoRecognition.formation.analyzer import FormationOper
from ArknightsVideoRecognition.formation.avatar_loader import load_resource_avatar


class SupportOperatorRecognizer:
    """助战干员识别器：定位助战槽、裁剪头像、匹配头像库。"""

    def __init__(self, ocr_engine, avatar_dir, support_template_path):
        self.ocr = ocr_engine
        self.avatar_dir = Path(avatar_dir)
        self.template_path = Path(support_template_path)
        # 读助战空槽模板（BGR）；失败直接抛错
        self.support_template = cv2.imread(str(self.template_path))
        if self.support_template is None:
            raise RuntimeError(f"读取助战空槽模板失败：{self.template_path}")
        self._slot_roi = list(SUPPORT_SLOT_ROI)  # [x, y, w, h]
        # 预加载头像库：char_*.png 与 sp_char_*.png，每个文件名/图像对
        self._avatar_lib: List[Tuple[str, np.ndarray]] = []
        if self.avatar_dir.is_dir():
            candidates = list(self.avatar_dir.glob("char_*.png"))
            candidates.extend(self.avatar_dir.glob("sp_char_*.png"))
            for p in sorted(candidates):
                img = cv2.imread(str(p))
                if img is None:
                    continue
                self._avatar_lib.append((p.name, img))
        # 缓存 battle_data.json 的 chars 字典，charId -> {name, ...}
        self._chars_map: dict = {}
        battle_data_path = DATA_DIR / "battle_data.json"
        if battle_data_path.is_file():
            with open(battle_data_path, encoding="utf-8") as f:
                data = json.load(f)
            self._chars_map = data.get("chars") or {}
        # 别名索引（懒构建）：alias -> 标准中文名，用于校正 OCR 干员名
        self._alias_map: dict = {}
        # 开始按钮 ROI 与文本（来自 StartButton1 任务）
        self._start_button_roi = get_roi("StartButton1")
        start_task = load_roi().get("StartButton1") or {}
        self._start_button_texts = list(
            start_task.get("text") or ["开始行动", "开始作战", "开始推演", "开始突袭"]
        )
        # 编队页面开始按钮 ROI（修正后，覆盖编队页面的按钮文字区域）
        self._formation_btn_roi = list(START_BUTTON_FORMATION_ROI)
        # 预计算头像库 SIFT 描述子。matchTemplate 对编队页面半身像 vs 库
        # 方形头像无判别力（库头像与编队页面渲染不同源，最高分仅 0.6-0.74
        # 且 top-10 挤在一起）；改用 SIFT 特征点 + RANSAC，对光照/构图差异
        # 鲁棒（参考 Maa 视觉识别中 SIFT 特征点检测）。实测蛇屠箱 5/5 帧
        # top-1（inliers 15-23，远超第二名古米 10-16）。
        self._sift = cv2.SIFT_create()
        self._flann = cv2.FlannBasedMatcher(
            dict(algorithm=1, trees=5), dict(checks=50)  # FLANN_INDEX_KDTREE
        )
        self._lib_sift: List[Tuple[str, list, np.ndarray]] = []
        for fn, _img in self._avatar_lib:
            bgra = cv2.imread(str(self.avatar_dir / fn), cv2.IMREAD_UNCHANGED)
            if bgra is None or bgra.shape[2] != 4:
                continue
            g = cv2.cvtColor(bgra[:, :, :3], cv2.COLOR_BGR2GRAY)
            kp, des = self._sift.detectAndCompute(g, None)
            if des is None or len(kp) < 2:
                continue
            self._lib_sift.append((fn, kp, des))

    def detect_start_button(self, frame) -> bool:
        """检测编队页面是否可见（通过开始按钮文字 OCR）。

        对齐 Maa ``BattleFormationAnalyzer::analyze()``：每帧先检测开始按钮，
        没检测到则不做后续 OCR。使用修正后的 ROI
        (:data:`START_BUTTON_FORMATION_ROI`，覆盖编队页面 y≈440-580 的按钮
        文字区域）和宽泛的"开始"前缀匹配，覆盖"开始行动"/"开始突袭"等
        所有变体。

        Returns
        -------
        bool
            编队页面可见（检测到"开始"文字）返回 True，否则 False。
        """
        if frame is None or frame.size == 0:
            return False
        items = self.ocr.recognize(frame, roi=self._formation_btn_roi)
        for it in items:
            text = it.get("text") or ""
            if "开始" in text:
                return True
        return False

    def _slot_match_score(self, frame) -> float:
        """计算固定助战槽位置与空模板的匹配分数。

        在固定 ROI 处裁剪画面，与 empty_support_operator.png 模板做
        TM_CCOEFF_NORMED 匹配，返回最高分。槽位为空时分数≈0.99，
        已填充时≈0.5，非编队页面时≈0.33。
        """
        if frame is None or frame.size == 0:
            return -1.0
        x, y, w, h = self._slot_roi
        H, W = frame.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            return -1.0
        slot = frame[y0:y1, x0:x1]
        slot_gray = cv2.cvtColor(slot, cv2.COLOR_BGR2GRAY)
        tpl_gray = cv2.cvtColor(self.support_template, cv2.COLOR_BGR2GRAY)
        # 尺寸对齐（模板与裁剪区可能差几个像素）
        if tpl_gray.shape != slot_gray.shape:
            tpl_gray = cv2.resize(tpl_gray, (slot_gray.shape[1], slot_gray.shape[0]), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(slot_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        return float(res.max()) if res.size else -1.0

    def find_stable_window(self, frames_with_ts, fps=5) -> list:
        """扫描帧序列，找最后一次连续≥5帧为编队页面的稳定窗。

        编队页面判定：开始按钮 OCR 检测到"开始"文字（对齐 Maa
        ``BattleFormationAnalyzer::analyze()`` 的开始按钮前置检查）。
        窗内最多取 SUPPORT_DETECT_MAX_SEC (30) 秒；超出则截断。
        """
        if not frames_with_ts:
            return []
        # 计算每帧的开始按钮检测结果
        flags = []
        for ts, frame in frames_with_ts:
            flags.append(self.detect_start_button(frame))
        # 找所有连续 True 且长度 ≥ START_BUTTON_STABLE_FRAMES 的窗口
        windows = []
        i = 0
        n = len(flags)
        while i < n:
            if flags[i]:
                j = i
                while j < n and flags[j]:
                    j += 1
                if j - i >= START_BUTTON_STABLE_FRAMES:
                    windows.append((i, j))
                i = j
            else:
                i += 1
        if not windows:
            return []
        # 取最后一个窗口
        start_idx, end_idx = windows[-1]
        window = frames_with_ts[start_idx:end_idx]
        # 30s 截断
        if window:
            start_ts = window[0][0]
            window = [(ts, f) for ts, f in window if ts - start_ts <= SUPPORT_DETECT_MAX_SEC]
        return window

    def locate_support_slot(self, frame) -> tuple:
        """定位助战槽位并判断是否为空。

        使用固定 ROI（SUPPORT_SLOT_ROI），通过槽位与空模板的匹配分数判断：
        - 分数 < 0.3：非编队页面，返回 (None, False)
        - 分数 ≥ SUPPORT_EMPTY_THRESHOLD (0.8)：槽位为空，返回 (box, True)
        - 否则：槽位已填充，返回 (box, False)
        """
        score = self._slot_match_score(frame)
        if score < 0.3:
            return None, False
        box = list(self._slot_roi)
        is_empty = score >= SUPPORT_EMPTY_THRESHOLD
        return box, is_empty

    def crop_support_avatar(self, frame, box) -> np.ndarray:
        """按 box=[x,y,w,h] 从 frame 裁剪头像，越界返回空数组。"""
        x, y, w, h = box
        H, W = frame.shape[:2]
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(W, int(x + w))
        y1 = min(H, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return np.empty((0, 0, 3), dtype=frame.dtype)
        return frame[y0:y1, x0:x1]

    def _build_alias_map(self) -> dict:
        """懒构建别名索引：alias -> 标准中文名（用 battle_data.json chars）。"""
        if self._alias_map:
            return self._alias_map
        for info in self._chars_map.values():
            canonical = info.get("name")
            if not canonical:
                continue
            for field in ("name", "name_en", "name_tw", "name_jp", "name_kr"):
                alias = info.get(field)
                if alias and alias not in self._alias_map:
                    self._alias_map[alias] = canonical
        return self._alias_map

    def _resolve_name(self, raw_name: str) -> Optional[str]:
        """校正 OCR 干员名到标准中文名（精确别名 + difflib 模糊匹配）。"""
        if not raw_name:
            return None
        alias_map = self._build_alias_map()
        if raw_name in alias_map:
            return alias_map[raw_name]
        matches = difflib.get_close_matches(
            raw_name, list(alias_map.keys()), n=1, cutoff=0.6
        )
        if matches:
            return alias_map[matches[0]]
        return None

    def match_avatar(self, avatar, candidates=None) -> tuple:
        """匹配助战头像，返回 (name, inliers, filename)。

        用 SIFT 特征点 + FLANN 匹配 + RANSAC 验证。matchTemplate 对编队
        半身像 vs 库方形头像无判别力（库头像与编队页面渲染不同源，最高分
        仅 0.6-0.74 且 top-10 挤在一起），改用特征点匹配——SIFT 对光照/
        尺度/构图差异鲁棒，能跨半身像与头像找到共同的局部特征（脸、配饰
        等）。参考 Maa 视觉识别中 SIFT 特征点检测。

        Parameters
        ----------
        avatar:
            助战槽裁剪图（151×293 半身像）。
        candidates:
            保留参数以兼容调用方，本方法不再使用。

        Returns
        -------
        tuple
            (name, inliers, filename)。inliers 为 RANSAC 内点数（越高越
            可信）。未匹配上（inliers < 5）返回 (None, inliers, filename)。
        """
        if avatar is None or avatar.size == 0:
            return None, 0, None
        gray = cv2.cvtColor(avatar, cv2.COLOR_BGR2GRAY)
        kp, des = self._sift.detectAndCompute(gray, None)
        if des is None or len(kp) < 4:
            return None, 0, None

        best_inliers = 0
        best_filename: Optional[str] = None
        for filename, lib_kp, lib_des in self._lib_sift:
            matches = self._flann.knnMatch(des, lib_des, k=2)
            good = []
            for pair in matches:
                if len(pair) < 2:
                    continue
                a, b = pair
                if a.distance < 0.75 * b.distance:
                    good.append(a)
            if len(good) < 4:
                continue
            src = np.float32(
                [kp[m.queryIdx].pt for m in good]
            ).reshape(-1, 1, 2)
            dst = np.float32(
                [lib_kp[m.trainIdx].pt for m in good]
            ).reshape(-1, 1, 2)
            _H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
            inliers = int(mask.sum()) if mask is not None else 0
            if inliers > best_inliers:
                best_inliers = inliers
                best_filename = filename

        # inliers < 5 视为不可信（噪声匹配），不产出
        if best_filename is None or best_inliers < 5:
            return None, best_inliers, best_filename

        # 由文件名解析 charId 并查 chars 字典取标准中文名
        stem = Path(best_filename).stem
        tokens = stem.split("_")
        if tokens[0] == "char":
            char_id = "_".join(tokens[:3])
        elif len(tokens) > 1 and tokens[0] == "sp" and tokens[1] == "char":
            char_id = "_".join(tokens[:4])
        else:
            char_id = stem
        info = self._chars_map.get(char_id)
        name = info.get("name") if info else None
        return name, best_inliers, best_filename

    def recognize(self, frames_with_ts) -> Optional[FormationOper]:
        """串联完整助战识别流程，返回 FormationOper 或 None。

        多帧稳定窗投票：在稳定窗内采样最多 7 帧（SIFT 单帧需遍历整个
        头像库，全帧匹配过慢），逐帧调 :meth:`match_avatar` 取投票最多
        的候选。一致率 ≥60% 返回该候选，否则返回 None（不稳定，不产出
        错误答案）。
        """
        window = self.find_stable_window(frames_with_ts)
        if not window:
            return None
        # 采样最多 7 帧：稳定窗可能有上百帧，SIFT 全跑过慢；均匀采样保证
        # 覆盖整个窗口（首尾都含），同时控制耗时。
        max_samples = 7
        if len(window) > max_samples:
            step = max(1, len(window) // max_samples)
            sampled = window[::step][:max_samples]
        else:
            sampled = window
        # 逐帧匹配助战头像，按 name 累计票数并记录最佳 inliers/头像/box/filename
        votes: dict[str, list] = {}
        # votes: name -> [票数, 最高inliers, avatar, box, filename]
        for ts, frame in sampled:
            box, is_empty = self.locate_support_slot(frame)
            if box is None or is_empty:
                continue
            avatar = self.crop_support_avatar(frame, box)
            name, inliers, match_fn = self.match_avatar(avatar)
            if name is None:
                continue
            if name not in votes:
                votes[name] = [0, inliers, avatar, box, match_fn]
            else:
                votes[name][0] += 1
                if inliers > votes[name][1]:
                    votes[name][1] = inliers
                    votes[name][2] = avatar
                    votes[name][3] = box
                    votes[name][4] = match_fn

        if not votes:
            return None

        # 取票数最多的候选
        best_name = max(votes, key=lambda n: votes[n][0])
        cnt, _inliers, avatar, box, match_filename = votes[best_name]
        # 一致率 < 60% → 不稳定，不产出
        matched_frames = sum(v[0] + 1 for v in votes.values())
        if matched_frames == 0 or (cnt + 1) / matched_frames < 0.6:
            return None

        # 保留帧裁剪半身像作为 avatar（与部署栏同源，匹配分数 0.6-0.9）；
        # resource 标准头像另存为 resource_avatar（不污染 avatar）。
        resource_avatar: Optional[np.ndarray] = None
        char_id = ""
        if match_filename:
            ra, cid = load_resource_avatar(match_filename)
            if ra is not None:
                resource_avatar = ra
                char_id = cid
        return FormationOper(
            name=best_name,
            avatar=avatar,
            box=box,
            is_support=True,
            char_id=char_id,
            resource_avatar=resource_avatar,
        )
