"""
gui.theme.typography - Material Design 3 字体 Token

参考 Material Design 官网的排版风格，优先使用 Roboto / Google Sans，
在中文环境下回退到系统无衬线字体。
"""

from __future__ import annotations

from PyQt6.QtGui import QFont


class MaterialTypography:
    """Material Design 3 字体比例"""

    def __init__(self, family: str | None = None) -> None:
        self.family = family or self._default_family()

    @staticmethod
    def _default_family() -> str:
        return "Roboto, Google Sans, Segoe UI, Microsoft YaHei UI, Noto Sans SC, Arial, sans-serif"

    def _font(self, size: int, weight: int = QFont.Weight.Normal,
              letter_spacing: int = 0) -> QFont:
        font = QFont()
        font.setFamily(self.family.split(",")[0].strip())
        font.setPointSize(size)
        font.setWeight(weight)
        if letter_spacing:
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + letter_spacing)
        return font

    @property
    def display_large(self) -> QFont:
        return self._font(57, QFont.Weight.Normal, -2)

    @property
    def display_medium(self) -> QFont:
        return self._font(45, QFont.Weight.Normal, -1)

    @property
    def display_small(self) -> QFont:
        return self._font(36, QFont.Weight.Normal, -1)

    @property
    def headline_large(self) -> QFont:
        return self._font(32, QFont.Weight.Normal)

    @property
    def headline_medium(self) -> QFont:
        return self._font(28, QFont.Weight.Normal)

    @property
    def headline_small(self) -> QFont:
        return self._font(24, QFont.Weight.Normal)

    @property
    def title_large(self) -> QFont:
        return self._font(22, QFont.Weight.Medium)

    @property
    def title_medium(self) -> QFont:
        return self._font(16, QFont.Weight.Medium, 1)

    @property
    def title_small(self) -> QFont:
        return self._font(14, QFont.Weight.Medium, 1)

    @property
    def body_large(self) -> QFont:
        return self._font(16, QFont.Weight.Normal)

    @property
    def body_medium(self) -> QFont:
        return self._font(14, QFont.Weight.Normal)

    @property
    def body_small(self) -> QFont:
        return self._font(12, QFont.Weight.Normal)

    @property
    def label_large(self) -> QFont:
        return self._font(14, QFont.Weight.Medium, 1)

    @property
    def label_medium(self) -> QFont:
        return self._font(12, QFont.Weight.Medium, 1)

    @property
    def label_small(self) -> QFont:
        return self._font(11, QFont.Weight.Medium, 1)

    @property
    def mono(self) -> QFont:
        font = QFont("Roboto Mono, Consolas, SF Mono, Sarasa Mono SC, monospace")
        font.setPointSize(12)
        return font

    def font_for(self, role: str) -> QFont:
        return getattr(self, role, self.body_medium)
