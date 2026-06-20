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
        """浅色主题：参考 Material Design 官网的淡紫配色"""
        return cls(
            primary="#4F378B",
            on_primary="#FFFFFF",
            primary_container="#EADDFF",
            on_primary_container="#21005D",
            secondary="#6750A4",
            on_secondary="#FFFFFF",
            secondary_container="#E8DEF8",
            on_secondary_container="#1D192B",
            surface="#FFFFFF",
            on_surface="#1C1B1F",
            surface_variant="#F3EDF7",
            on_surface_variant="#49454F",
            outline="#79747E",
            outline_variant="#E8E0EB",
            background="#F5F0FA",
            error="#B3261E",
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
            surface="#1C1B1F",
            on_surface="#E6E1E5",
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
        value = getattr(self, name, "#000000")
        return QColor(value)

    def to_dict(self) -> dict[str, str]:
        return {field.name: getattr(self, field.name) for field in fields(self)}
