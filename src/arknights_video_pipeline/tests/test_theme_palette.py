"""主题系统单元测试（MD3 紫色 Token / QPalette / 字体 / 图标）

验证 gui/theme 与 gui/assets/icons 的纯原生实现：
- MaterialColors 的 MD3 紫色 Token 值（含验收值 #FFFBFE / #141218）
- QPalette 映射：Window 角色 == surface
- QSS 生成覆盖新增 MD3 控件块
- FontManager 字体注册与缺失静默回退
- nav_icons SVG 资源与动态染色

所有测试在 offscreen Qt 模式下运行，不依赖真实显示器。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.gui.assets.icons import nav_icons
from arknights_video_pipeline.gui.theme import (
    MaterialColors,
    MaterialStyle,
    apply_palette,
    build_palette,
)
from arknights_video_pipeline.gui.theme import font_manager as fm


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen 模式）"""
    app = QApplication.instance() or QApplication([])
    yield app


# ── MD3 紫色 Token ──────────────────────────────────────────


class TestMaterialColorsTokens:
    def test_light_surface_is_md3_fffbfe(self) -> None:
        """浅色 surface 为 #FFFBFE（非纯白），primary 为 #6750A4"""
        c = MaterialColors.light()
        assert c.surface == "#FFFBFE"
        assert c.on_surface == "#1C1B1E"
        assert c.primary == "#6750A4"
        assert c.on_primary == "#FFFFFF"
        assert c.primary_container == "#EADDFF"

    def test_dark_surface_is_md3_141218(self) -> None:
        """深色 surface 为 #141218（非纯黑）"""
        c = MaterialColors.dark()
        assert c.surface == "#141218"
        assert c.on_surface == "#E6E0E9"
        assert c.primary == "#D0BCFF"
        assert c.on_primary == "#381E72"

    def test_light_background_keeps_lavender(self) -> None:
        """窗口底色保持淡薰衣草 #F5F0FA（与 surface 区分）"""
        assert MaterialColors.light().background == "#F5F0FA"
        assert MaterialColors.dark().background == "#121014"

    def test_as_qcolor_roundtrip(self) -> None:
        assert MaterialColors.light().as_qcolor("primary") == QColor("#6750A4")


# ── QPalette 映射 ───────────────────────────────────────────


class TestPaletteMapping:
    def test_build_palette_window_matches_surface(self) -> None:
        """QPalette.Window 必须等于 surface（MD3 验收项）"""
        assert build_palette(MaterialColors.light()).color(
            QPalette.ColorRole.Window
        ) == QColor("#FFFBFE")
        assert build_palette(MaterialColors.dark()).color(
            QPalette.ColorRole.Window
        ) == QColor("#141218")

    def test_build_palette_button_uses_primary(self) -> None:
        pal = build_palette(MaterialColors.light())
        assert pal.color(QPalette.ColorRole.Button) == QColor("#6750A4")
        assert pal.color(QPalette.ColorRole.ButtonText) == QColor("#FFFFFF")

    def test_apply_palette_sets_app_globally(self, qapp) -> None:
        apply_palette(MaterialColors.light())
        assert qapp.palette().color(QPalette.ColorRole.Window) == QColor("#FFFBFE")
        apply_palette(MaterialColors.dark())
        assert qapp.palette().color(QPalette.ColorRole.Window) == QColor("#141218")


# ── QSS 覆盖 ────────────────────────────────────────────────


class TestQssCoverage:
    def test_qss_contains_md3_controls(self) -> None:
        qss = MaterialStyle(colors=MaterialColors.light()).generate_qss()
        for block in (
            "QSpinBox, QDoubleSpinBox",
            "QToolTip",
            "QListWidget, QTreeWidget",
            "QHeaderView::section",
            "QTabBar::tab",
            "QRadioButton::indicator",
            "QSlider::handle",
            "QPushButton[mdOutlined=\"true\"]",
        ):
            assert block in qss, f"QSS 缺少控件块: {block}"

    def test_qss_contains_no_hardcoded_light_hex(self) -> None:
        """QSS 色值全部来自 Token，不得出现旧版硬编码色"""
        qss = MaterialStyle(colors=MaterialColors.light()).generate_qss()
        assert "#4F378B" not in qss  # 旧 primary
        assert "#1C1B1F" not in qss  # 旧 on_surface


# ── 字体管理 ────────────────────────────────────────────────


class TestFontManager:
    def test_load_registers_builtin_fonts(self, qapp) -> None:
        """内置字体存在时注册 Roboto / Noto Sans SC"""
        families = fm.FontManager.load()
        assert isinstance(families, list)
        if any((fm._FONT_ROOT / f).is_file() for f in fm._FONT_FILES):
            # 文件齐全时至少注册成功一个族名
            assert families, "字体文件存在但注册失败"

    def test_missing_font_falls_back_silently(self, qapp, monkeypatch) -> None:
        """字体文件缺失时静默回退，不抛异常"""
        monkeypatch.setattr(fm, "_FONT_FILES", ("NoSuchFont-Regular.ttf",))
        monkeypatch.setattr(fm, "_FAMILIES", [])
        assert fm.FontManager.load() == []

    def test_typography_prepends_registered_families(self, qapp) -> None:
        from arknights_video_pipeline.gui.theme.typography import MaterialTypography

        family = MaterialTypography().family
        assert "Roboto" in family or "sans-serif" in family
        # 回退链必须包含中文系统字体兜底
        assert "Microsoft YaHei" in family or "PingFang SC" in family


# ── SVG 图标 ────────────────────────────────────────────────


class TestSvgIcons:
    _SVG_NAMES = (
        "home", "settings", "tools", "info",
        "check_box", "check_box_outline_blank", "indeterminate_check_box",
        "arrow_upward", "arrow_downward", "delete",
        "pending", "check_circle", "error",
    )

    def test_all_icons_are_svg_sources(self) -> None:
        """验收项：所有图标源文件为 .svg"""
        for name in self._SVG_NAMES:
            assert nav_icons.has_icon(name), f"图标缺失: {name}"
            assert nav_icons._ICON_FILES[name].endswith(".svg"), f"非 SVG: {name}"

    def test_make_icon_pixmap_colors_alpha_mask(self, qapp) -> None:
        """染色后 pixmap 非空且尺寸正确，且存在非透明像素"""
        pix = nav_icons.make_icon_pixmap("home", "#FF0000", size_px=24)
        assert pix is not None
        assert pix.width() == 24 and pix.height() == 24
        img = pix.toImage()
        has_ink = any(
            img.pixelColor(x, y).alpha() > 0
            for x in range(0, 24, 3)
            for y in range(0, 24, 3)
        )
        assert has_ink, "图标渲染后全透明"