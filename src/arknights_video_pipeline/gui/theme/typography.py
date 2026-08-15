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

    @property
    def family_list(self) -> list[str]:
        """字体族列表（供 QFont.setFamilies 使用）"""
        return [f.strip() for f in self.family.split(",") if f.strip()]

    @property
    def qss_font_family(self) -> str:
        """QSS font-family 属性值（带引号，供样式表使用）

        将 "Roboto, Segoe UI, sans-serif" 格式化为
        "Roboto", "Segoe UI", sans-serif
        """
        parts: list[str] = []
        for f in self.family_list:
            # CSS 通用族关键字不加引号
            if f in ("sans-serif", "serif", "monospace", "cursive", "fantasy"):
                parts.append(f)
            else:
                parts.append(f'"{f}"')
        return ", ".join(parts)

    @staticmethod
    def _default_family() -> str:
        """默认字体回退链

        内置字体（Roboto / Noto Sans SC，见 ``font_manager.FontManager``）
        注册成功后置于链首；中文最终回退 Windows 的 Microsoft YaHei 与
        macOS 的 PingFang SC，保证无内置字体时仍可正确显示中文。
        """
        from arknights_video_pipeline.gui.theme.font_manager import FontManager

        base = (
            "Roboto, Google Sans, Segoe UI, Microsoft YaHei UI, "
            "Noto Sans SC, Arial, sans-serif"
        )
        registered = FontManager.available_families()
        if registered:
            # 已注册族名前置（可变字体族名即 "Roboto" / "Noto Sans SC"），
            # 重复族名无害：QFont.setFamilies 按序匹配第一个可用的。
            return ", ".join(registered) + ", " + base
        return base

    def _font(self, size: int, weight: int = QFont.Weight.Normal,
              letter_spacing: int = 0) -> QFont:
        font = QFont()
        # 使用 setFamilies（复数）指定完整回退链，避免 Roboto 未安装时
        # Qt 回退到系统默认字体（中文 Windows 下通常为宋体 SimSun）
        font.setFamilies(self.family_list)
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
        font = QFont()
        font.setFamilies(["Roboto Mono", "Consolas", "SF Mono", "Sarasa Mono SC", "monospace"])
        font.setPointSize(12)
        return font

    def font_for(self, role: str) -> QFont:
        value = getattr(self, role, None)
        if not isinstance(value, QFont):
            raise AttributeError(f"未知字体角色: {role}")
        return value
