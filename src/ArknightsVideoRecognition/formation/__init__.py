"""编队识别模块：识别编队页面干员名并动态截取头像。"""

from ArknightsVideoRecognition.formation.analyzer import (
    FormationAnalyzer,
    FormationOper,
)
from ArknightsVideoRecognition.formation.support import SupportOperatorRecognizer

__all__ = ["FormationAnalyzer", "FormationOper", "SupportOperatorRecognizer"]
