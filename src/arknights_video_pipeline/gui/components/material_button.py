"""
gui.components.material_button - Material Design 3 按钮

支持 filled / tonal / outlined / text / elevated 五种变体。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QPushButton


class MaterialButton(QPushButton):
    """Material 风格按钮"""

    VARIANT_FILLED = "filled"
    VARIANT_TONAL = "tonal"
    VARIANT_OUTLINED = "outlined"
    VARIANT_TEXT = "text"
    VARIANT_ELEVATED = "elevated"

    def __init__(self, text: str = "", variant: str = VARIANT_FILLED,
                 parent=None) -> None:
        super().__init__(text, parent)
        self._variant = variant
        self.set_variant(variant)

    def set_variant(self, variant: str) -> None:
        self._variant = variant
        # 注意：不可使用 Qt 内置属性名 text / outlined，否则会覆盖按钮文本
        self.setProperty("mdOutlined", "false")
        self.setProperty("mdText", "false")

        if variant == self.VARIANT_OUTLINED:
            self.setProperty("mdOutlined", "true")
        elif variant in (self.VARIANT_TEXT, self.VARIANT_ELEVATED):
            self.setProperty("mdText", "true")
        # filled / tonal 使用默认 QPushButton 样式
        self.style().unpolish(self)
        self.style().polish(self)

    def variant(self) -> str:
        return self._variant
