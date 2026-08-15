"""编队识别模块：识别编队页面干员名并动态截取头像。"""

from arknights_video_recognition.formation.analyzer import (
    FormationAnalyzer,
    FormationOper,
)
from arknights_video_recognition.formation.support import SupportOperatorRecognizer

__all__ = ["FormationAnalyzer", "FormationOper", "SupportOperatorRecognizer"]
