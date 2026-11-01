"""gui.theme.colors - Material Design 3 颜色角色（Material You 动态取色）

颜色**不是**手写的十六进制常量，而是由种子色经色调系统推导的结果
（见 :mod:`gui.theme.scheme`）：

- ``MaterialColors.light()`` / ``dark()``：等价于基线紫种子 ``#6750A4``，
  即"品牌默认外观"，40 余处调用点无需关心动态取色；
- ``MaterialColors.from_seed(seed, dark)``：任意种子（Material You），
  用于设置页的"动态色彩 + 种子色"。

层级由色调差表达而非阴影：窗口 ``surface`` → 卡片
``surface_container_low`` → 菜单 ``surface_container`` → 对话框
``surface_container_high`` → 抽屉 ``surface_container_highest``。
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from PyQt6.QtGui import QColor

from arknights_video_pipeline.gui.theme.hct import normalize_hex
from arknights_video_pipeline.gui.theme.scheme import (
    BASELINE_SEED,
    TonalScheme,
    scheme_from_seed,
)

__all__ = ["BASELINE_SEED", "MaterialColors"]


@dataclass(frozen=True)
class MaterialColors:
    """Material Design 3 颜色角色（43 个）

    字段名与 MD3 角色一一对应；新增字段必须同步
    :data:`gui.theme.scheme.ROLE_SPECS`，否则 ``scheme.roles()`` 无法覆盖。
    """

    # ── Primary ──────────────────────────────────────────
    primary: str
    on_primary: str
    primary_container: str
    on_primary_container: str

    # ── Secondary ────────────────────────────────────────
    secondary: str
    on_secondary: str
    secondary_container: str
    on_secondary_container: str

    # ── Tertiary ─────────────────────────────────────────
    tertiary: str
    on_tertiary: str
    tertiary_container: str
    on_tertiary_container: str

    # ── Error ────────────────────────────────────────────
    error: str
    on_error: str
    error_container: str
    on_error_container: str

    # ── Surface ──────────────────────────────────────────
    surface: str
    on_surface: str
    surface_variant: str
    on_surface_variant: str
    outline: str
    outline_variant: str

    # 窗口底色（保留字段名以兼容既有调用点，语义等同 surface）
    background: str

    # Surface 层级：容器分层替代阴影
    surface_dim: str
    surface_bright: str
    surface_container_lowest: str
    surface_container_low: str
    surface_container: str
    surface_container_high: str
    surface_container_highest: str

    # ── Inverse ──────────────────────────────────────────
    inverse_surface: str
    inverse_on_surface: str
    inverse_primary: str

    # ── 遮罩与色调叠加 ───────────────────────────────────
    scrim: str
    surface_tint: str

    # ── 扩展语义（非 MD3 标准角色，供业务状态使用）───────
    success: str
    on_success: str
    success_container: str
    on_success_container: str
    warning: str
    on_warning: str
    warning_container: str
    on_warning_container: str

    # ── 构造 ─────────────────────────────────────────────

    @classmethod
    def light(cls) -> "MaterialColors":
        """浅色主题（基线紫种子）"""
        return cls.from_seed(BASELINE_SEED, dark=False)

    @classmethod
    def dark(cls) -> "MaterialColors":
        """深色主题（基线紫种子）"""
        return cls.from_seed(BASELINE_SEED, dark=True)

    @classmethod
    def from_seed(cls, seed: str, dark: bool = False) -> "MaterialColors":
        """由种子色构造完整角色集（结果按种子缓存）

        Args:
            seed: 任意 ``#RRGGBB`` 种子色
            dark: True 取深色角色，False 取浅色角色

        Returns:
            填充了全部 43 个角色的 :class:`MaterialColors`

        Raises:
            ValueError: 种子色格式非法
        """
        scheme: TonalScheme = scheme_from_seed(normalize_hex(seed))
        return cls(**scheme.roles(dark=dark))

    # ── 查询 ─────────────────────────────────────────────

    @property
    def is_dark(self) -> bool:
        """当前配色是否为深色（按 surface 明度判断）"""
        return QColor(self.surface).lightness() < 128

    def as_qcolor(self, name: str) -> QColor:
        """按角色名取 ``QColor``

        Raises:
            AttributeError: 角色名不存在
        """
        valid_names = {field.name for field in fields(self)}
        if name not in valid_names:
            raise AttributeError(f"{name} 不是有效的颜色字段")
        return QColor(getattr(self, name))

    def to_dict(self) -> dict[str, str]:
        """导出为 ``{角色名: 十六进制}``"""
        return {field.name: getattr(self, field.name) for field in fields(self)}
