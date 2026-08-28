"""编队识别：识别编队页面的干员名并动态截取每个干员头像。

移植自 Maa ``CombatRecordRecognitionTask::analyze_formation`` 与
``BattleFormationAnalyzer``。原 C++ 用 ``TemplDetOCRer`` 先定位编队
名字旁的小旗图标（``BattleFormationOCRNameFlag``），再在小旗相对
位置 OCR 出干员名（``BattleFormationOperNames``，相对 ROI
``[-18, 40, 122, 18]``），最后按 ``BattleFormationOperAvatarMove``
的 ``rectMove = [-120, -250, 150, 165]``、以「名字框右上角」为
基点裁剪头像。

本项目简化：直接对 ``BattleFormationOCRNameFlag`` 名字区域做 OCR 得
到若干干员名（含文本框绝对坐标），再沿用上述 rectMove 相对每个名字
框右上角裁剪头像。``empty.png`` 在本仓库为 1x1 占位图，无法做模板
匹配定位小旗，故改用「名字框定位头像」的动态裁剪方案——头像位置随
识别到的名字框动态计算，仍能产出 name + avatar 配对。

干员名校正：读 ``battle_data.json`` 的 chars（含 name/name_en/
name_tw/name_jp/name_kr），对 OCR 名字做精确别名匹配，未命中再用
difflib 模糊匹配，返回标准中文 name。
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from typing import Optional

import numpy as np

from arknights_video_recognition.config.settings import AVATAR_DIR, DATA_DIR, SUPPORT_TEMPLATE
from arknights_video_recognition.ocr.engine import OcrEngine

# 干员别名索引缓存，避免重复解析 battle_data.json
# 结构: (别名列表, {别名: 标准中文名})
_alias_index: Optional[tuple[list[str], dict[str, str]]] = None

# 编队识别提前停止的连续无新增帧数阈值（超过该值即停，行为保持 >5 不变；
# 与 settings.START_BUTTON_STABLE_FRAMES 的"开始按钮稳定帧数"语义无关）
_NO_CHANGE_STOP_FRAMES = 5


def load_alias_index() -> tuple[list[str], dict[str, str]]:
    """加载 battle_data.json，构建 (别名列表, 别名->标准名 映射)。

    每个干员的 name / name_en / name_tw / name_jp / name_kr 均作为
    别名，统一映射到标准中文 ``name``。同一别名只保留首个出现的标准
    名。
    """
    global _alias_index
    if _alias_index is None:
        with open(DATA_DIR / "battle_data.json", encoding="utf-8") as f:
            data = json.load(f)
        aliases: list[str] = []
        mapping: dict[str, str] = {}
        for info in (data.get("chars") or {}).values():
            canonical = info.get("name")
            if not canonical:
                continue
            for field in ("name", "name_en", "name_tw", "name_jp", "name_kr"):
                alias = info.get(field)
                if alias and alias not in mapping:
                    mapping[alias] = canonical
                    aliases.append(alias)
        _alias_index = (aliases, mapping)
    return _alias_index


@dataclass
class FormationOper:
    """编队中单个干员的识别结果。

    Attributes
    ----------
    name:
        校正后的标准干员名（中文）。
    avatar:
        头像图（numpy BGR 数组），用于后续 battle 模块与场上头像比对。
    box:
        头像在原编队帧中的位置 ``[x, y, w, h]``。
    """

    name: str
    avatar: np.ndarray
    box: list[int]
    is_support: bool = False
    char_id: str = ""
    resource_avatar: Optional[np.ndarray] = None


class FormationAnalyzer:
    """编队页面识别器。

    Parameters
    ----------
    ocr_engine:
        已构造的 :class:`OcrEngine`，为 ``None`` 时新建默认引擎。
    """

    # 头像相对名字左上角的偏移 [dx, dy, w, h]
    # 对齐 Maa BattleFormationOperAvatarMove = [-120, -250, 150, 165]：
    # 头像在名字左上方约 120px、上方约 250px 处。y 偏移过小（如 -165）
    # 会裁到身体而非头像，导致 match_with_formation 分数偏低（实测遥
    # 从 0.44 提升到 0.68）。
    _AVATAR_OFFSET_FROM_NAME = (-120, -250, 150, 165)

    def __init__(self, ocr_engine: Optional[OcrEngine] = None):
        self.ocr = ocr_engine if ocr_engine is not None else OcrEngine()
        self._support_recognizer = None  # 懒加载

    @property
    def support_recognizer(self):
        """懒加载助战识别器，避免无资源时构造即报错。"""
        if self._support_recognizer is None:
            from arknights_video_recognition.formation.support import SupportOperatorRecognizer
            self._support_recognizer = SupportOperatorRecognizer(
                ocr_engine=self.ocr,
                avatar_dir=AVATAR_DIR,
                support_template_path=SUPPORT_TEMPLATE,
            )
        return self._support_recognizer

    def analyze(self, formation_frame: np.ndarray) -> list[FormationOper]:
        """对编队页面帧识别，返回 FormationOper 列表。

        移植自 Maa ``BattleFormationAnalyzer::analyze()``，使用
        ``TemplDetOCRer`` 先模板匹配定位小旗图标（``BattleFormationOCRNameFlag``），
        再相对小旗位置裁名字区域做 OCR（``BattleFormationOperNames``），
        最后按 ``BattleFormationOperAvatarMove`` 裁剪头像。

        相比原版"用等级数字作为锚点"的方案，TemplDetOCRer 更接近 Maa 原版
        实现，且不依赖等级数字的 OCR 稳定性。
        """
        if formation_frame is None:
            return []

        # 1) 用 TemplDetOCRer 定位小旗 + OCR 名字
        from arknights_video_recognition.vision.templ_det_ocrer import TemplDetOCRer
        templ_ocr = TemplDetOCRer(formation_frame, self.ocr)
        templ_ocr.set_task_info("BattleFormationOCRNameFlag", "BattleFormationOperNames")
        templ_ocr.set_bin_expansion(3)
        ocr_results = templ_ocr.analyze()

        if not ocr_results:
            return []

        # 2) 对每个结果校正干员名，去重
        results: list[FormationOper] = []
        seen_names: set[str] = set()
        H, W = formation_frame.shape[:2]

        for r in ocr_results:
            name_text = (r.text or "").strip()
            if not name_text:
                continue
            resolved = self._resolve_name(name_text)
            if not resolved or resolved in seen_names:
                continue
            seen_names.add(resolved)

            # 3) 用名字框的 rect 裁剪头像
            # 对齐 Maa BattleFormationOperAvatarMove = [-120, -250, 150, 165]
            # rect 是 [x, y, w, h] 在原图坐标系
            name_y0 = r.rect[1]
            # 用名字框右上角作为基点（Maa 原版使用名字框右上角）
            name_right = r.rect[0] + r.rect[2]

            a_dx, a_dy, a_w, a_h = self._AVATAR_OFFSET_FROM_NAME
            ax = max(0, int(name_right) + a_dx)
            ay = max(0, int(name_y0) + a_dy)
            ax_end = min(W, int(name_right) + a_dx + a_w)
            ay_end = min(H, int(name_y0) + a_dy + a_h)
            avatar = formation_frame[ay:ay_end, ax:ax_end] if ax_end > ax and ay_end > ay else np.empty((0,0,3), dtype=formation_frame.dtype)
            box = [ax, ay, ax_end - ax, ay_end - ay]
            results.append(FormationOper(name=resolved, avatar=avatar, box=box))

        return results

    def analyze_with_support(self, frames_with_ts) -> list[FormationOper]:
        """识别编队（含助战干员）。

        对齐 Maa ``CombatRecordRecognitionTask::analyze_formation`` 与
        ``BattleFormationAnalyzer::analyze()``：

        1. 逐帧先检测开始按钮（Maa 的前置检查），无按钮则跳过该帧不做 OCR；
        2. 有按钮才调 :meth:`analyze` 做干员名 OCR，多帧累计合并新增干员；
        3. 停止条件：连续 ≥5 帧无新增干员，或开始按钮消失后编队已非空。

        Parameters
        ----------
        frames_with_ts:
            list[(ts_seconds: float, frame: np.ndarray)]，已按 ts 升序。
        """
        if not frames_with_ts:
            return []

        # 逐帧累计：先检测开始按钮，有按钮才做编队 OCR
        accumulated: dict[str, FormationOper] = {}  # name -> FormationOper
        no_changes_count = 0
        for _ts, frame in frames_with_ts:
            # 对齐 Maa：无开始按钮 → 跳过该帧（对应 Maa 返回 nullopt）
            if not self.support_recognizer.detect_start_button(frame):
                # 开始按钮消失后编队已非空 → 停止（对齐 Maa 的停止信号）
                if accumulated:
                    break
                continue

            # 有开始按钮 → 做编队 OCR
            frame_opers = self.analyze(frame)
            if len(frame_opers) > len(accumulated):
                for oper in frame_opers:
                    accumulated[oper.name] = oper
                no_changes_count = 0
            else:
                new_count = 0
                for oper in frame_opers:
                    if oper.name not in accumulated:
                        accumulated[oper.name] = oper
                        new_count += 1
                if new_count == 0:
                    no_changes_count += 1
                else:
                    no_changes_count = 0
            # 连续无新增超过阈值即停（保持原 >5 行为不变，第 6 帧停）
            if no_changes_count > _NO_CHANGE_STOP_FRAMES:
                break

        opers = list(accumulated.values())

        # 助战识别（取稳定窗最后一帧）
        support_oper = self.support_recognizer.recognize(frames_with_ts)
        if support_oper is not None:
            # 去重：助战干员名可能已被 OCR 当作普通干员识别（如 Lancet-2）
            existing = next((o for o in opers if o.name == support_oper.name), None)
            if existing is not None:
                existing.is_support = True
            else:
                opers.append(support_oper)
        return opers

    def correct_name(self, raw_name: str) -> str:
        """校正 OCR 干员名，返回标准干员名。

        用 battle_data.json 做精确别名匹配，未命中再做 difflib 模糊
        匹配。未匹配则原样返回 ``raw_name``。
        """
        resolved = self._resolve_name(raw_name)
        return resolved if resolved is not None else raw_name

    def _resolve_name(self, raw_name: str) -> Optional[str]:
        """返回标准名；精确别名命中后用 difflib 模糊匹配；都不中返回 None。

        模糊匹配阈值随文本类型调整：含中文字符的文本用 0.6（中文名较长、
        区分度高）；纯 ASCII 文本用 0.8（短英文别名如 ``ASH`` 极易与 OCR
        垃圾文本如 ``AST`` 误匹配，需更严格阈值）。
        """
        if not raw_name:
            return None
        aliases, mapping = load_alias_index()

        # 1) 精确别名匹配（含繁体/英/日/韩名）
        if raw_name in mapping:
            return mapping[raw_name]

        # 2) difflib 模糊匹配：纯 ASCII 文本提高阈值，避免短英文别名误匹配
        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in raw_name)
        cutoff = 0.6 if has_cjk else 0.8
        matches = difflib.get_close_matches(raw_name, aliases, n=1, cutoff=cutoff)
        if matches:
            return mapping[matches[0]]
        return None

