"""gui.theme.typography - MD3 字体比例（15 档 type scale）

三项关键约束：

1. **px 单轨**：全部用 ``QFont.setPixelSize`` 与 QSS ``font-size: Npx``，
   不再混用 ``setPointSize``（96 DPI 下两者相差约 33%，导致"同样 14 号
   字，有的地方大有的地方小"）；
2. **绝对字距**：``QFont.SpacingType.AbsoluteSpacing``（px），而不是
   百分比——百分比会随字号缩放，大字过度紧缩、小字几乎无效；
3. **行高交给布局**：Qt QSS 不支持 ``line-height``，因此这里只提供
   ``line_height(role)`` 供布局取间距，禁止在 QSS 里写行高。

字重只用 400（常规）与 500（中等），与 MD3 一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QFont

__all__ = ["TYPE_SCALE", "MaterialTypography", "TypeRole"]


# 字重 → QFont.Weight（避免 QFont.Weight(400) 的平台差异）
_WEIGHTS: dict[int, QFont.Weight] = {
    400: QFont.Weight.Normal,
    500: QFont.Weight.Medium,
    700: QFont.Weight.Bold,
}


@dataclass(frozen=True)
class TypeRole:
    """单个排版角色的规格

    Attributes:
        size: 字号（px）
        weight: 字重（400 / 500 / 700）
        line_height: 行高（px），供布局使用
        tracking: 字距（px，绝对间距）
    """

    size: int
    weight: int
    line_height: int
    tracking: float


#: MD3 type scale（15 档，唯一事实源）
TYPE_SCALE: dict[str, TypeRole] = {
    "display_large": TypeRole(57, 400, 64, -0.25),
    "display_medium": TypeRole(45, 400, 52, 0.0),
    "display_small": TypeRole(36, 400, 44, 0.0),
    "headline_large": TypeRole(32, 400, 40, 0.0),
    "headline_medium": TypeRole(28, 400, 36, 0.0),
    "headline_small": TypeRole(24, 400, 32, 0.0),
    "title_large": TypeRole(22, 400, 28, 0.0),
    "title_medium": TypeRole(16, 500, 24, 0.15),
    "title_small": TypeRole(14, 500, 20, 0.1),
    "body_large": TypeRole(16, 400, 24, 0.5),
    "body_medium": TypeRole(14, 400, 20, 0.25),
    "body_small": TypeRole(12, 400, 16, 0.4),
    "label_large": TypeRole(14, 500, 20, 0.1),
    "label_medium": TypeRole(12, 500, 16, 0.5),
    "label_small": TypeRole(11, 500, 16, 0.5),
}


class MaterialTypography:
    """按 MD3 type scale 生成 ``QFont`` 与 QSS 片段

    用法::

        typo = MaterialTypography()
        title.setFont(typo.font("display_medium"))
        label.setStyleSheet(f"QLabel {{ {typo.qss('body_medium')} }}")
    """

    def __init__(self, family: str | None = None) -> None:
        self.family = family or self._default_family()

    # ── 字体族 ───────────────────────────────────────────

    @property
    def family_list(self) -> list[str]:
        """字体族列表（供 ``QFont.setFamilies`` 使用）"""
        return [f.strip() for f in self.family.split(",") if f.strip()]

    @property
    def qss_font_family(self) -> str:
        """QSS ``font-family`` 属性值（带引号，通用族不加引号）"""
        parts: list[str] = []
        for name in self.family_list:
            if name in ("sans-serif", "serif", "monospace", "cursive", "fantasy"):
                parts.append(name)
            else:
                parts.append(f'"{name}"')
        return ", ".join(parts)

    @staticmethod
    def _default_family() -> str:
        """默认字体回退链（内置字体优先，中文最终回退系统字体）

        已注册的内置族名会前置到回退链首；去重避免 QSS 中出现
        ``"Roboto", ..., "Roboto"`` 这类重复项。
        """
        from arknights_video_pipeline.gui.theme.font_manager import FontManager

        base = [
            "Roboto", "Google Sans", "Segoe UI", "Microsoft YaHei UI",
            "Noto Sans SC", "Arial", "sans-serif",
        ]
        ordered: list[str] = []
        for name in [*FontManager.available_families(), *base]:
            if name not in ordered:
                ordered.append(name)
        return ", ".join(ordered)

    # ── 角色查询 ─────────────────────────────────────────

    def role(self, name: str) -> TypeRole:
        """按名称取排版角色

        Raises:
            KeyError: 角色名不在 type scale 中
        """
        try:
            return TYPE_SCALE[name]
        except KeyError as exc:
            raise KeyError(f"未知的排版角色: {name!r}") from exc

    def line_height(self, name: str) -> int:
        """角色对应的行高（px），供布局设置间距"""
        return self.role(name).line_height

    # ── 生成器 ───────────────────────────────────────────

    def font(self, name: str) -> QFont:
        """生成角色对应的 ``QFont``（px 字号 + 绝对字距）"""
        spec = self.role(name)
        font = QFont()
        # setFamilies（复数）是中文不乱码的前提：单 setFamily 在 Roboto
        # 缺字时不会逐字符回退，可能落到宋体
        font.setFamilies(self.family_list)
        font.setPixelSize(spec.size)
        font.setWeight(_WEIGHTS.get(spec.weight, QFont.Weight.Normal))
        if spec.tracking:
            font.setLetterSpacing(
                QFont.SpacingType.AbsoluteSpacing, spec.tracking
            )
        return font

    def qss(self, name: str) -> str:
        """生成角色的 QSS 片段（``font-size`` / ``font-weight``）

        字距与行高不在 QSS 中表达：Qt 不支持 ``letter-spacing`` /
        ``line-height``，写了会静默失效。
        """
        spec = self.role(name)
        return f"font-size: {spec.size}px; font-weight: {spec.weight};"

    def font_for(self, role: str) -> QFont:
        """兼容旧接口：按角色名取字体"""
        return self.font(role)

    @property
    def mono(self) -> QFont:
        """等宽字体（日志、路径）"""
        font = QFont()
        font.setFamilies(
            ["Roboto Mono", "Consolas", "SF Mono", "Sarasa Mono SC", "monospace"]
        )
        font.setPixelSize(TYPE_SCALE["body_small"].size)
        return font

    # ── 兼容属性：旧代码用 typo.body_medium 之类取 QFont ──

    @property
    def display_large(self) -> QFont:
        return self.font("display_large")

    @property
    def display_medium(self) -> QFont:
        return self.font("display_medium")

    @property
    def display_small(self) -> QFont:
        return self.font("display_small")

    @property
    def headline_large(self) -> QFont:
        return self.font("headline_large")

    @property
    def headline_medium(self) -> QFont:
        return self.font("headline_medium")

    @property
    def headline_small(self) -> QFont:
        return self.font("headline_small")

    @property
    def title_large(self) -> QFont:
        return self.font("title_large")

    @property
    def title_medium(self) -> QFont:
        return self.font("title_medium")

    @property
    def title_small(self) -> QFont:
        return self.font("title_small")

    @property
    def body_large(self) -> QFont:
        return self.font("body_large")

    @property
    def body_medium(self) -> QFont:
        return self.font("body_medium")

    @property
    def body_small(self) -> QFont:
        return self.font("body_small")

    @property
    def label_large(self) -> QFont:
        return self.font("label_large")

    @property
    def label_medium(self) -> QFont:
        return self.font("label_medium")

    @property
    def label_small(self) -> QFont:
        return self.font("label_small")
