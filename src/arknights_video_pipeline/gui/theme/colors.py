"""
gui.theme.colors - Material Design 3 颜色 Token

定义浅色/深色两套配色，使用 dataclass 组织核心颜色角色。
本次配色参考 Material Design 官网：淡薰衣草背景、深紫主色、白色卡片。
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from PyQt6.QtGui import QColor


@dataclass(frozen=True)
class MaterialColors:
    """Material Design 3 颜色角色"""

    # Primary
    primary: str
    on_primary: str
    primary_container: str
    on_primary_container: str

    # Secondary
    secondary: str
    on_secondary: str
    secondary_container: str
    on_secondary_container: str

    # Surface
    surface: str
    on_surface: str
    surface_variant: str
    on_surface_variant: str
    outline: str
    outline_variant: str

    # Background
    background: str

    # Error
    error: str
    on_error: str
    error_container: str
    on_error_container: str

    # Custom
    success: str
    warning: str

    @classmethod
    def light(cls) -> "MaterialColors":
        """浅色主题：MD3 标准紫色 Token（surface 为 #FFFBFE 非纯白）

        窗口底色使用独立 ``background``（淡薰衣草 #F5F0FA，参考 Material
        Design 官网风格）；surface 用于卡片等容器。QPalette 映射见
        ``theme.palette``，其中 Window 角色固定为 surface 以符合 MD3 验收。
        """
        return cls(
            primary="#6750A4",
            on_primary="#FFFFFF",
            primary_container="#EADDFF",
            on_primary_container="#21005D",
            secondary="#625B71",
            on_secondary="#FFFFFF",
            secondary_container="#E8DEF8",
            on_secondary_container="#1D192B",
            surface="#FFFBFE",
            on_surface="#1C1B1E",
            surface_variant="#E7E0EC",
            on_surface_variant="#49454F",
            outline="#79747E",
            outline_variant="#CAC4D0",
            background="#F5F0FA",
            error="#BA1A1A",
            on_error="#FFFFFF",
            error_container="#F9DEDC",
            on_error_container="#410E0B",
            success="#2E7D32",
            warning="#ED6C02",
        )

    @classmethod
    def dark(cls) -> "MaterialColors":
        return cls(
            primary="#D0BCFF",
            on_primary="#381E72",
            primary_container="#4F378B",
            on_primary_container="#EADDFF",
            secondary="#CCC2DC",
            on_secondary="#332D41",
            secondary_container="#4A4458",
            on_secondary_container="#E8DEF8",
            surface="#141218",
            on_surface="#E6E0E9",
            surface_variant="#49454F",
            on_surface_variant="#CAC4D0",
            outline="#938F99",
            outline_variant="#49454F",
            background="#121014",
            error="#F2B8B5",
            on_error="#601410",
            error_container="#8C1D18",
            on_error_container="#F9DEDC",
            success="#81C784",
            warning="#FFB74D",
        )

    def as_qcolor(self, name: str) -> QColor:
        valid_names = {f.name for f in fields(self)}
        if name not in valid_names:
            raise AttributeError(f"{name} 不是有效的颜色字段")
        value = getattr(self, name)
        return QColor(value)

    def to_dict(self) -> dict[str, str]:
        return {field.name: getattr(self, field.name) for field in fields(self)}
