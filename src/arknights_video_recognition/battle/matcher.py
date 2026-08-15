"""场上头像 ↔ 编队头像匹配，以及屏幕坐标 → 格子坐标反查。

移植自 Maa ``BattlefieldMatcher``（``Vision/Battle/BattlefieldMatcher.cpp``）
与 ``CombatRecordRecognitionTask::analyze_deployment`` 中的头像匹配逻辑。

匹配策略：对每个 detector 检出的场上头像框，裁剪 patch，与每个
:class:`~arknights_video_recognition.formation.FormationOper` 的 ``avatar``
做 ``cv2.matchTemplate``（``TM_CCOEFF_NORMED``），取最高分且超阈值的定为
该干员名。一个干员名可能匹配多个场上框（同一干员多次部署），允许重复。

``screen_pos_to_tile`` 用 :func:`~arknights_video_recognition.tile.get_all_tile_positions`
算出所有格子的屏幕坐标，做欧氏距离最近邻，把屏幕坐标反查为格子 ``(row, col)``。
这是把场上头像位置转成作业 ``location [row, col]`` 的关键。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from arknights_video_recognition.tile import get_all_tile_positions


@dataclass
class MatchedOper:
    """场上一个已定名干员。

    Attributes
    ----------
    name:
        匹配到的编队干员名；未匹配上为 ``"Unknown"``。
    box:
       场上头像框 ``[x, y, w, h]``（原图坐标系）。
    avatar_patch:
        裁剪出的场上头像小图（BGR），用于后续分类/调试。无法裁剪时为 ``None``。
    screen_pos:
        头像框中心 ``(x, y)``。
    """

    name: str
    box: List[int]
    avatar_patch: Optional[np.ndarray]
    screen_pos: Tuple[int, int]


class AvatarMatcher:
    """场上头像 ↔ 编队头像匹配器。

    Parameters
    ----------
    match_threshold:
        ``matchTemplate`` 的最低得分阈值，低于此值判为未匹配（``"Unknown"``）。
    """

    def __init__(self, match_threshold: float = 0.5):
        self.match_threshold = float(match_threshold)

    # --- 内部辅助 ----------------------------------------------------------

    @staticmethod
    def _crop_patch(frame: np.ndarray, box: Sequence[int]) -> Optional[np.ndarray]:
        """按 ``[x, y, w, h]`` 从 frame 裁剪并裁到画面范围内。"""
        if frame is None or frame.size == 0:
            return None
        x, y, w, h = box
        if w <= 0 or h <= 0:
            return None
        orig_h, orig_w = frame.shape[:2]
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(orig_w, int(x + w))
        y1 = min(orig_h, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return None
        return frame[y0:y1, x0:x1]

    def _match_one(
        self, patch: np.ndarray, formation_opers: Sequence
    ) -> Tuple[str, float]:
        """对一个 patch 与所有编队头像匹配，返回 (name, score)。"""
        best_name = "Unknown"
        best_score = -1.0
        if patch is None or patch.size == 0:
            return best_name, best_score

        patch_gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        ph, pw = patch_gray.shape[:2]

        for fo in formation_opers:
            avatar = getattr(fo, "avatar", None)
            if avatar is None or avatar.size == 0:
                continue
            avatar_gray = cv2.cvtColor(avatar, cv2.COLOR_BGR2GRAY)
            ah, aw = avatar_gray.shape[:2]

            # matchTemplate 要求 template 不大于 image。编队头像与场上头像
            # 缩放不同，这里把较大的一方按比例缩到与较小一方一致，保证可比。
            if aw > pw or ah > ph:
                scale = min(pw / aw, ph / ah)
                new_w = max(1, int(round(aw * scale)))
                new_h = max(1, int(round(ah * scale)))
                avatar_gray = cv2.resize(avatar_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
                ah, aw = avatar_gray.shape[:2]
            if aw > pw or ah > ph:
                # 缩放后仍大于 patch（极端小 patch），缩到 patch 尺寸
                avatar_gray = cv2.resize(avatar_gray, (pw, ph), interpolation=cv2.INTER_AREA)
                ah, aw = ph, pw

            res = cv2.matchTemplate(patch_gray, avatar_gray, cv2.TM_CCOEFF_NORMED)
            score = float(res.max()) if res.size else -1.0
            if score > best_score:
                best_score = score
                best_name = fo.name
        return best_name, best_score

    # --- 主入口 ------------------------------------------------------------

    def match(
        self,
        detections: Sequence,
        formation_opers: Sequence,
        frame: Optional[np.ndarray] = None,
    ) -> List[MatchedOper]:
        """把 detector 检出的场上头像框与编队头像匹配并定名。

        Parameters
        ----------
        detections:
            :class:`~arknights_video_recognition.battle.detector.Detection` 列表。
        formation_opers:
            :class:`~arknights_video_recognition.formation.FormationOper` 列表。
        frame:
            战场帧。提供时用于裁剪场上头像 patch；为 ``None`` 时
            ``avatar_patch`` 留空 ``None``。
        """
        results: List[MatchedOper] = []
        if not formation_opers:
            # 无编队信息，全部记为 Unknown
            for det in detections:
                box = list(det.box)
                cx = box[0] + box[2] // 2
                cy = box[1] + box[3] // 2
                results.append(MatchedOper(
                    name="Unknown",
                    box=box,
                    avatar_patch=self._crop_patch(frame, box) if frame is not None else None,
                    screen_pos=(int(cx), int(cy)),
                ))
            return results

        for det in detections:
            box = list(det.box)
            cx = box[0] + box[2] // 2
            cy = box[1] + box[3] // 2
            patch = self._crop_patch(frame, box) if frame is not None else None
            name, score = self._match_one(patch, formation_opers)
            if score < self.match_threshold:
                name = "Unknown"
            results.append(MatchedOper(
                name=name,
                box=box,
                avatar_patch=patch,
                screen_pos=(int(cx), int(cy)),
            ))
        return results


# --- 屏幕坐标 -> 格子坐标 ---------------------------------------------------


def screen_pos_to_tile(
    screen_pos: Tuple[float, float],
    level: dict,
    screen_size: Sequence[int],
    positions: Optional[Sequence[Sequence[Tuple[float, float]]]] = None,
) -> Optional[Tuple[int, int]]:
    """屏幕坐标 → 最近格子 ``(row, col)``。

    用 :func:`get_all_tile_positions` 算出所有格子的屏幕坐标，做欧氏距离
    最近邻查找，返回距离最近的格子的 ``(row, col)``。

    Parameters
    ----------
    screen_pos:
        待反查的屏幕坐标 ``(x, y)``。
    level:
        关卡 dict（来自 :func:`~arknights_video_recognition.tile.find_level`）。
    screen_size:
        屏幕尺寸 ``(width, height)``，如 ``(1280, 720)``。
    positions:
        预计算的格子屏幕坐标二维数组（``positions[row][col]``），避免在
        循环中重复调用 :func:`get_all_tile_positions`。为 ``None`` 时现算。
    """
    if screen_pos is None:
        return None
    if positions is None:
        positions = get_all_tile_positions(level, screen_size)

    tx, ty = float(screen_pos[0]), float(screen_pos[1])
    best: Optional[Tuple[int, int]] = None
    best_dist = float("inf")
    for row in range(len(positions)):
        row_pos = positions[row]
        for col in range(len(row_pos)):
            px, py = row_pos[col]
            d = (px - tx) * (px - tx) + (py - ty) * (py - ty)
            if d < best_dist:
                best_dist = d
                best = (row, col)
    return best


def tile_to_screen_pos(tile, level, screen_size, positions=None):
    """格子坐标 (row, col) -> 屏幕坐标 (cx, cy)。

    Parameters
    ----------
    tile:
        ``(row, col)`` 格子坐标。
    level:
        关卡 dict（含 tiles）。
    screen_size:
        屏幕尺寸 ``(w, h)``。
    positions:
        可选的预计算位置映射（来自 :func:`get_all_tile_positions`）。
        为 ``None`` 时现场计算。
    """
    if positions is None:
        positions = get_all_tile_positions(level, screen_size)
    if isinstance(positions, dict):
        return positions.get(tile)
    row, col = tile
    if 0 <= row < len(positions) and 0 <= col < len(positions[row]):
        return positions[row][col]
    return None
