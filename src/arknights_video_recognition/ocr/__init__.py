"""OCR 文字识别模块。

封装 RapidOCR，支持 Maa finetune 模型与 RapidOCR 默认模型双源切换。
"""

from .engine import OcrEngine, OcrSource

__all__ = ["OcrEngine", "OcrSource"]
