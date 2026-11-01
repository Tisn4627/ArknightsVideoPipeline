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


def _channel_close(actual: str, expected: str, tolerance: int = 2) -> bool:
    """逐通道比较两个十六进制色（HCT 求解与参考实现允许 ≤2 的量化差）"""
    return all(
        abs(int(actual[i:i + 2], 16) - int(expected[i:i + 2], 16)) <= tolerance
        for i in (1, 3, 5)
    )


class TestMaterialColorsTokens:
    """颜色角色由 HCT 色调系统推导，不再硬编码十六进制"""

    def test_light_brand_anchor_is_md3_baseline(self) -> None:
        """基线种子 #6750A4 的 primary 必须逐位复现，其余容器色允许 ≤2"""
        c = MaterialColors.light()
        assert c.primary == "#6750A4"
        assert c.on_primary == "#FFFFFF"
        assert _channel_close(c.primary_container, "#EADDFF")
        assert _channel_close(c.on_primary_container, "#21005D")

    def test_light_surface_follows_md3_n98(self) -> None:
        """浅色 surface 取中性板 N98（#FEF7FF），非纯白"""
        c = MaterialColors.light()
        assert _channel_close(c.surface, "#FEF7FF")
        assert _channel_close(c.on_surface, "#1D1B20")

    def test_dark_roles_are_tone_flipped(self) -> None:
        """深色角色与浅色一一对应：primary 取 P80、container 取 P30"""
        c = MaterialColors.dark()
        assert c.surface == "#141218"
        assert c.on_surface == "#E6E0E9"
        assert c.on_primary == "#381E72"
        assert _channel_close(c.primary, "#D0BCFF")
        assert _channel_close(c.primary_container, "#4F378B")

    def test_background_shares_surface_semantics(self) -> None:
        """``background`` 保留字段名但语义等同 surface（不再有薰衣草底）"""
        light = MaterialColors.light()
        dark = MaterialColors.dark()
        assert light.background == light.surface
        assert dark.background == dark.surface

    def test_all_43_roles_present_and_valid(self) -> None:
        """角色集合完整（MD3 标准 35 个 + 扩展 8 个）且为合法十六进制"""
        import re

        roles = MaterialColors.light().to_dict()
        assert len(roles) == 43
        for name, value in roles.items():
            assert re.fullmatch(r"#[0-9A-F]{6}", value), f"{name}={value}"

    def test_container_roles_are_layered(self) -> None:
        """surface 容器家族必须逐级变化（形成可辨的层级）"""
        c = MaterialColors.light()
        ladder = [
            c.surface,
            c.surface_container_low,
            c.surface_container,
            c.surface_container_high,
            c.surface_container_highest,
        ]
        assert len(set(ladder)) == len(ladder)

    def test_as_qcolor_roundtrip(self) -> None:
        assert MaterialColors.light().as_qcolor("primary") == QColor("#6750A4")


# ── QPalette 映射 ───────────────────────────────────────────


class TestPaletteMapping:
    def test_build_palette_window_matches_surface(self) -> None:
        """QPalette.Window 必须等于 surface（MD3 验收项）"""
        light = MaterialColors.light()
        assert build_palette(light).color(
            QPalette.ColorRole.Window
        ) == QColor(light.surface)
        assert build_palette(MaterialColors.dark()).color(
            QPalette.ColorRole.Window
        ) == QColor("#141218")

    def test_build_palette_button_uses_primary(self) -> None:
        pal = build_palette(MaterialColors.light())
        assert pal.color(QPalette.ColorRole.Button) == QColor("#6750A4")
        assert pal.color(QPalette.ColorRole.ButtonText) == QColor("#FFFFFF")

    def test_apply_palette_sets_app_globally(self, qapp) -> None:
        # QApplication 是进程级单例：测试结束必须恢复原 palette，
        # 否则深色主题泄漏给同会话后续运行的 GUI 测试（顺序耦合）
        original = qapp.palette()
        try:
            light = MaterialColors.light()
            apply_palette(light)
            assert qapp.palette().color(
                QPalette.ColorRole.Window
            ) == QColor(light.surface)
            apply_palette(MaterialColors.dark())
            assert qapp.palette().color(
                QPalette.ColorRole.Window
            ) == QColor("#141218")
        finally:
            qapp.setPalette(original)


# ── QSS 覆盖 ────────────────────────────────────────────────


class TestQssCoverage:
    def test_qss_contains_md3_controls(self) -> None:
        qss = MaterialStyle(colors=MaterialColors.light()).generate_qss()
        # QToolTip 颜色由 QPalette 的 ToolTipBase / ToolTipText 提供
        # （见 theme/palette.py），QSS 不再写死颜色；避免窗口级主题
        # 切换后 tooltip 仍停留在启动时的旧色。
        assert "QToolTip" not in qss
        for block in (
            "QSpinBox, QDoubleSpinBox",
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

    def test_qss_uses_palette_roles_for_native_controls(self) -> None:
        """原生控件的外观必须走 palette(role)，否则切主题要整树重设样式表"""
        qss = MaterialStyle(colors=MaterialColors.light()).generate_qss()
        for declaration in (
            "color: palette(text);",
            "border: 1px solid palette(mid);",
            "border: 2px solid palette(highlight);",
            "background-color: palette(alternate-base);",
            "background-color: palette(midlight);",
        ):
            assert declaration in qss, f"QSS 缺少 palette(role) 声明: {declaration}"

    def test_qss_has_no_universal_widget_rule(self) -> None:
        """不允许 ``QWidget { … }`` 通用规则：命中每个控件会写死其调色板"""
        import re

        qss = MaterialStyle(colors=MaterialColors.light()).generate_qss()
        assert re.search(r"^\s*QWidget\s*\{", qss, re.MULTILINE) is None


# ── 运行期切换（不重设样式表）──────────────────────────────


class TestRuntimeThemeSwitch:
    """旧实现切主题会整树 ``setStyleSheet``（0.6-2.5 秒），这里锁死新机制"""

    def test_switch_keeps_stylesheet_and_recolors_via_palette(self, qapp) -> None:
        from PyQt6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

        from arknights_video_pipeline.gui.theme import theme_controller

        original_qss = qapp.styleSheet()
        original_palette = qapp.palette()
        try:
            MaterialStyle(colors=MaterialColors.light()).apply(qapp)
            window = QWidget()
            layout = QVBoxLayout(window)
            label = QLabel("label")
            edit = QLineEdit("edit")
            layout.addWidget(label)
            layout.addWidget(edit)
            window.show()
            qapp.processEvents()

            controller = theme_controller()
            controller.apply(dark=False, seed="#6750A4", dynamic=False, app=qapp)
            light_surface = controller.colors().on_surface
            assert label.palette().color(
                QPalette.ColorRole.WindowText
            ).name().upper() == light_surface.upper()

            qss_before = qapp.styleSheet()
            controller.apply(dark=True, app=qapp)

            # 1) 样式表未被重设（整树 polish 是卡顿根因）
            assert qapp.styleSheet() == qss_before
            # 2) 标签文字色随新调色板（QSS polish 写死的调色板已被清空）
            dark_on_surface = controller.colors().on_surface
            assert label.palette().color(
                QPalette.ColorRole.WindowText
            ).name().upper() == dark_on_surface.upper()
            # 3) 输入框的文字色同样跟随（palette(text) 重新解析）
            assert edit.palette().color(
                QPalette.ColorRole.Text
            ).name().upper() == dark_on_surface.upper()
            window.close()
        finally:
            theme_controller().reset_instance()
            qapp.setStyleSheet(original_qss)
            qapp.setPalette(original_palette)

    def test_set_text_color_uses_window_text_role(self, qapp) -> None:
        from PyQt6.QtWidgets import QLabel

        from arknights_video_pipeline.gui.theme import set_text_color

        label = QLabel("label")
        set_text_color(label, "#123456")
        assert label.palette().color(
            QPalette.ColorRole.WindowText
        ) == QColor("#123456")
        # 不得留下 widget 级样式表（会写死调色板并拖慢主题切换）
        assert label.styleSheet() == ""


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