"""战场（battle）分析模块。

提供 YOLOv8 干员检测、技能就绪/部署方向分类、场上头像↔编队头像匹配、
action 推断能力，对应 Maa ``CombatRecordRecognitionTask``
的 ``analyze_clip`` / ``process_changes`` / ``compare_skill`` 流程。
"""

from ArknightsVideoRecognition.battle.detector import Detection, OperatorDetector
from ArknightsVideoRecognition.battle.classifier import BattleClassifier
from ArknightsVideoRecognition.battle.matcher import (
    AvatarMatcher,
    MatchedOper,
    screen_pos_to_tile,
)
from ArknightsVideoRecognition.battle.analyzer import Action, BattleAnalyzer

__all__ = [
    "OperatorDetector",
    "Detection",
    "BattleClassifier",
    "AvatarMatcher",
    "MatchedOper",
    "BattleAnalyzer",
    "Action",
    "screen_pos_to_tile",
]
