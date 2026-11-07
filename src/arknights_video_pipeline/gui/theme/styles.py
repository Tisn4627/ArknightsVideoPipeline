"""gui.theme.styles - 全局 QSS 生成器（MD3）

三条硬规则：

1. **不写裸选择器**：``QWidget`` / ``QFrame`` 上不加背景与边框，只做
   "默认透明 + 显式容器上色"。历史版本的 ``QWidget{background-color}`` 与
   ``QFrame{border...}`` 会污染整棵控件树，逼出 30 余处 ``background:
   transparent`` 补丁，是"风格混杂"的根因；
2. **QSS 不写随主题变化的颜色**：文字色 / 背景色 / 描边色 / 选中色一律写成
   ``palette(role)``，由 ``QPalette``（``theme/palette.py``）在 polish 时解析。
   写死十六进制颜色的样式表在切换主题时必须对整棵控件树重新
   ``setStyleSheet``（约 900 个 QWidget，旧实现单次 0.6-2.5 秒）；改成
   ``palette(role)`` 后切换只需 ``setPalette`` + 对少量控件重新 polish；
3. **QSS 只负责静态外观**：颜色 / 边框 / 圆角 / 字体。QSS 没有 transition，
   墨层淡入、焦点环、滑块位移等交互态由自绘组件承担（P3 起）。

另外：Qt QSS **不支持** ``line-height`` / ``letter-spacing`` /
``box-shadow``，行高与字距一律通过 ``typography`` 的 QFont 与布局表达，
不要在样式表里写这些属性（写了会静默失效）。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.gui.theme.button_qss import (
    BUTTON_VARIANTS,
    variant_state_colors,
)
from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.palette import apply_palette
from arknights_video_pipeline.gui.theme.shape import Shape, ShapeRole
from arknights_video_pipeline.gui.theme.spacing import Layout, Space
from arknights_video_pipeline.gui.theme.state import StateLayer, blend
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["MaterialStyle"]


class MaterialStyle:
    """Material Design 3 全局样式生成器"""

    # QSS 按 (colors, family) 缓存：MaterialColors 是 frozen dataclass（可哈希），
    # light/dark 各只生成一次，切换主题直接复用
    _qss_cache: dict[tuple[MaterialColors, str], str] = {}

    def __init__(
        self,
        colors: MaterialColors | None = None,
        typography: MaterialTypography | None = None,
    ) -> None:
        self.colors = colors or MaterialColors.light()
        self.typography = typography or MaterialTypography()

    # ── 生成入口 ─────────────────────────────────────────

    def generate_qss(self) -> str:
        """生成完整全局样式表（带缓存）"""
        cache_key = (self.colors, self.typography.family)
        cached = MaterialStyle._qss_cache.get(cache_key)
        if cached is not None:
            return cached

        blocks = [
            self._base_block(),
            self._text_block(),
            self._button_blocks(),
            self._input_blocks(),
            self._selection_blocks(),
            self._container_blocks(),
            self._item_view_blocks(),
            self._tab_blocks(),
            self._menu_blocks(),
            self._scrollbar_blocks(),
            self._progress_block(),
        ]
        qss = "\n".join(blocks)
        MaterialStyle._qss_cache[cache_key] = qss
        return qss

    def apply(self, app: QApplication) -> None:
        """应用样式：QPalette 兜底 → QSS → 全局字体

        只在应用启动时调用一次。QSS 里不含任何随主题变化的十六进制颜色
        （见 :meth:`generate_qss` 的说明），因此运行期切换主题不需要重设。
        """
        apply_palette(self.colors)
        app.setStyleSheet(self.generate_qss())
        # 全局默认字体走 QFont（px 单轨），QSS 不写 font-size：
        # 否则 QSS 会覆盖控件自身 setFont() 的结果（标题被压回正文大小）
        app.setFont(self.typography.body_medium)

    def set_dark(self, dark: bool = True) -> None:
        self.colors = MaterialColors.dark() if dark else MaterialColors.light()

    # ── 基础 ─────────────────────────────────────────────

    def _base_block(self) -> str:
        return f"""
        /* ── 基础：不写通用 QWidget 规则，颜色交给 QPalette ──
           写死十六进制颜色的样式表在切换主题时必须整树重设（约 900 个
           控件触发 unpolish/polish），是旧版深色切换卡顿的根因。
           另外**连字体也不要给 ``QWidget`` 写规则**：任何命中控件的规则都会
           让 QStyleSheetStyle 给该控件写入显式调色板（WA_SetPalette），
           之后 ``QApplication.setPalette`` 就不再传播给它。字体改由
           ``QApplication.setFont``（MaterialStyle.apply）提供，效果相同。

           窗口 / 页面根的背景由 QPalette::Window（surface）绘制，同样不写
           规则，这样切换主题时能即时跟随。

        */

        QScrollArea {{
            background: transparent;
            border: none;
        }}

        /* 纯布局容器：仅自身透明，不向下级联（widget 级 stylesheet 会
           作用于子控件，曾导致输入框边框被 "border: none" 抹掉） */
        QWidget#transparentPane {{
            background: transparent;
            border: none;
        }}

        QScrollArea > QWidget > QWidget {{
            background: transparent;
        }}

        QAbstractScrollArea {{
            background: transparent;
        }}

        QSplitter::handle {{
            background-color: palette(midlight);
            width: 1px;
            height: 1px;
        }}

        QToolBar {{
            border: none;
            spacing: {Space.S}px;
            padding: {Space.S}px;
        }}

        QStatusBar {{
            color: palette(placeholder-text);
        }}
        """

    def _text_block(self) -> str:
        return """
        /* ── 文本 ── */
        QLabel {
            background: transparent;
            border: none;
        }

        QLabel[dim="true"], QLabel[role="supporting"] {
            color: palette(placeholder-text);
        }
        """

    # ── 按钮 ─────────────────────────────────────────────

    def _button_block(self, selector: str, variant: str) -> str:
        """生成单个按钮变体的完整状态块（几何恒定，聚焦不推动内容）"""
        c = self.colors
        base, foreground, hover, pressed, ring = variant_state_colors(c, variant)

        border = 1
        horizontal = Layout.BUTTON_PADDING_H - border
        vertical = 9 - border
        min_height = Layout.BUTTON_HEIGHT - 2 * (vertical + border)

        if variant == "outlined":
            background, border_color = "transparent", c.outline
            disabled_background = "transparent"
            disabled_border = blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER).name()
        elif variant == "text":
            background, border_color = "transparent", "transparent"
            disabled_background = "transparent"
            disabled_border = "transparent"
        else:
            background, border_color = base, "transparent"
            disabled_background = blend(
                c.surface, c.on_surface, StateLayer.DISABLED_CONTAINER
            ).name()
            disabled_border = "transparent"

        disabled_fg = blend(c.surface, c.on_surface, StateLayer.DISABLED_CONTENT).name()

        return f"""
        {selector} {{
            background-color: {background};
            color: {foreground};
            border: {border}px solid {border_color};
            border-radius: {ShapeRole.BUTTON}px;
            padding: {vertical}px {horizontal}px;
            font-weight: 500;
            min-height: {min_height}px;
        }}
        {selector}:hover {{
            background-color: {hover};
            color: {foreground};
        }}
        {selector}:pressed {{
            background-color: {pressed};
            color: {foreground};
        }}
        {selector}:disabled {{
            background-color: {disabled_background};
            color: {disabled_fg};
            border-color: {disabled_border};
        }}
        {selector}:focus {{
            border: 2px solid {ring};
            padding: {vertical - 1}px {horizontal - 1}px;
        }}
        """

    def _button_blocks(self) -> str:
        # 默认变体 = filled（最高优先级）；其余通过动态属性选择
        selector_map = {
            "filled": "QPushButton",
            "tonal": 'QPushButton[mdTonal="true"]',
            "elevated": 'QPushButton[mdElevated="true"]',
            "outlined": 'QPushButton[mdOutlined="true"]',
            "text": 'QPushButton[mdText="true"]',
        }
        blocks = ["        /* ── 按钮：五种变体，默认 filled ── */"]
        for variant in BUTTON_VARIANTS:
            blocks.append(self._button_block(selector_map[variant], variant))
        # 自绘按钮（MaterialButton / MaterialIconButton）不经过 QStyleSheetStyle，
        # 这里清空 QSS 施加的尺寸约束，避免样式表与 sizeHint 打架
        blocks.append(
            """
        QPushButton[mdCustom="true"] {
            background: transparent;
            border: none;
            padding: 0px;
            min-height: 0px;
        }
        """
        )
        return "\n".join(blocks)

    # ── 输入 ─────────────────────────────────────────────

    def _field_common(self) -> str:
        """outlined 文本输入：1dp 常态描边、2dp 聚焦描边，几何恒定"""
        radius = ShapeRole.TEXT_FIELD
        height = Layout.FIELD_ROW_HEIGHT  # 56
        # 边框 + 内边距之和恒定（16），聚焦加粗描边不推动文字
        pad = 15
        min_height = height - 2 * (pad + 1)
        return f"""
        background-color: transparent;
        color: palette(text);
        border: 1px solid palette(mid);
        border-radius: {radius}px;
        padding: {pad}px;
        min-height: {min_height}px;
        selection-background-color: palette(highlight);
        selection-color: palette(highlighted-text);
        """

    def _input_blocks(self) -> str:
        pad = 15
        return f"""
        /* ── 输入：MD3 outlined 文本字段（4dp 圆角，几何恒定）──
           描边 / 文字 / 选中色全部走 QPalette：切换主题后对这些控件逐只
           unpolish+polish 即可重新解析，无需重设整树样式表 */
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox {{
            {self._field_common()}
        }}

        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 2px solid palette(highlight);
            padding: {pad - 1}px;
        }}

        QLineEdit:disabled, QComboBox:disabled,
        QSpinBox:disabled, QDoubleSpinBox:disabled {{
            color: palette(dark);
            border-color: palette(midlight);
        }}

        QLineEdit[error="true"], QComboBox[error="true"] {{
            border: 2px solid palette(bright-text);
            padding: {pad - 1}px;
        }}

        /* 设置页字段：桌面密度 48dp（MD3 density -1），保证长表单可扫读。
           字号不在这里写：由控件自身 setFont(body_large 16) 提供，
           QSS 的 font-size 会覆盖 setFont 的结果（导致主页 16 / 设置 14 双轨）。 */
        QLineEdit#settingsField, QSpinBox#settingsField,
        QDoubleSpinBox#settingsField, QComboBox#settingsField {{
            padding: 10px 12px;
            min-height: 26px;
        }}

        QLineEdit#settingsField:focus, QSpinBox#settingsField:focus,
        QDoubleSpinBox#settingsField:focus, QComboBox#settingsField:focus {{
            padding: 9px 11px;
        }}

        QComboBox::drop-down {{
            border: none;
            width: {Space.XXXL}px;
        }}

        QComboBox::down-arrow {{
            width: 0px;
            height: 0px;
        }}

        QComboBox QAbstractItemView {{
            background-color: palette(alternate-base);
            color: palette(text);
            border: 1px solid palette(midlight);
            border-radius: {Shape.EXTRA_SMALL}px;
            padding: {Space.XS}px;
            outline: none;
            selection-background-color: palette(highlight);
            selection-color: palette(highlighted-text);
        }}

        QComboBox QAbstractItemView::item {{
            /* 桌面密度 -2：MD3 菜单项 48dp 在鼠标环境下压缩到 40dp */
            min-height: 40px;
            padding: 0 {Space.L}px;
            border-radius: {Shape.EXTRA_SMALL}px;
        }}

        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            width: 0px;
            border: none;
            background: transparent;
        }}

        QSpinBox::up-arrow, QSpinBox::down-arrow,
        QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {{
            width: 0px;
            height: 0px;
            border: none;
        }}

        /* 多行文本：MD3 平面容器（4dp 圆角、surface_container 底、无描边），
           用于日志 / JSON 编辑器等代码型内容。用 alternate-base 而不是
           base：base 是 filled 输入区最高一档，作为日志大色块过重。 */
        QPlainTextEdit, QTextEdit {{
            background-color: palette(alternate-base);
            color: palette(text);
            /* 常态描边与底色同色（视觉无边框），聚焦只换描边色：
               几何不变，文字不会因 0→1px 边框而抖动 */
            border: 1px solid palette(alternate-base);
            border-radius: {Shape.EXTRA_SMALL}px;
            padding: {Space.M - 1}px;
            selection-background-color: palette(highlight);
            selection-color: palette(highlighted-text);
        }}

        QPlainTextEdit:focus, QTextEdit:focus {{
            border-color: palette(highlight);
        }}
        """

    # ── 选择控件 ─────────────────────────────────────────

    def _selection_blocks(self) -> str:
        return f"""
        /* ── 复选框 / 单选框 / 滑块 ── */
        QCheckBox, QRadioButton {{
            spacing: {Space.S}px;
            color: palette(text);
        }}

        QCheckBox:disabled, QRadioButton:disabled {{
            color: palette(dark);
        }}

        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid palette(placeholder-text);
            border-radius: 2px;
            background-color: transparent;
        }}

        QCheckBox::indicator:hover {{
            border-color: palette(text);
        }}

        QCheckBox::indicator:checked {{
            background-color: palette(highlight);
            border-color: palette(highlight);
        }}

        QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid palette(placeholder-text);
            border-radius: 9px;
            background-color: transparent;
        }}

        QRadioButton::indicator:checked {{
            border: 5px solid palette(highlight);
            background-color: palette(window);
        }}

        QSlider::groove:horizontal {{
            height: 4px;
            border-radius: 2px;
            background-color: palette(midlight);
        }}

        QSlider::sub-page:horizontal {{
            border-radius: 2px;
            background-color: palette(highlight);
        }}

        QSlider::handle:horizontal {{
            width: 20px;
            height: 20px;
            margin: -8px 0;
            border-radius: 10px;
            background-color: palette(highlight);
            border: none;
        }}

        QSlider::handle:horizontal:hover {{
            background-color: palette(light);
        }}
        """

    # ── 容器 ─────────────────────────────────────────────

    def _container_blocks(self) -> str:
        return f"""
        /* ── 容器：仅显式上色，不做裸 QFrame 规则 ── */
        QGroupBox {{
            background-color: palette(alternate-base);
            border: 1px solid palette(midlight);
            border-radius: {ShapeRole.CARD}px;
            margin-top: {Space.M}px;
            padding: {Space.L}px;
            font-weight: 500;
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: {Space.L}px;
            top: -8px;
            padding: 0 {Space.S}px;
            color: palette(placeholder-text);
            background-color: palette(window);
        }}

        QFrame[mdDivider="true"] {{
            background-color: palette(midlight);
            border: none;
            max-height: 1px;
            min-height: 1px;
        }}
        """

    # ── 列表 / 表格 ──────────────────────────────────────

    def _item_view_blocks(self) -> str:
        return f"""
        /* ── 列表 / 树 / 表格 ── */
        QListWidget, QTreeWidget, QTableWidget, QListView, QTableView {{
            background-color: transparent;
            color: palette(text);
            border: none;
            outline: none;
        }}

        QListWidget::item, QTreeWidget::item {{
            padding: {Space.S}px {Space.M}px;
            border-radius: {Shape.EXTRA_SMALL}px;
        }}

        QListWidget::item:hover, QTreeWidget::item:hover {{
            background-color: palette(alternate-base);
        }}

        QListWidget::item:selected, QTreeWidget::item:selected {{
            background-color: palette(highlight);
            color: palette(highlighted-text);
        }}

        QHeaderView::section {{
            background-color: palette(alternate-base);
            color: palette(placeholder-text);
            border: none;
            border-bottom: 1px solid palette(midlight);
            padding: {Space.S}px {Space.M}px;
            font-weight: 500;
        }}

        QTableWidget {{
            gridline-color: palette(midlight);
            selection-background-color: palette(highlight);
            selection-color: palette(highlighted-text);
            alternate-background-color: palette(alternate-base);
        }}
        """

    # ── 标签页（MD3 primary tabs：下划线指示器）──────────

    def _tab_blocks(self) -> str:
        return f"""
        /* ── 标签页：下划线指示器（胶囊形态属于 segmented button）── */
        QTabWidget::pane {{
            background-color: transparent;
            border: none;
            border-top: 1px solid palette(midlight);
        }}

        QTabBar::tab {{
            background-color: transparent;
            color: palette(placeholder-text);
            border: none;
            border-bottom: 2px solid transparent;
            padding: {Space.M}px {Space.L}px;
            font-weight: 500;
        }}

        QTabBar::tab:hover {{
            color: palette(text);
        }}

        QTabBar::tab:selected {{
            color: palette(highlight);
            border-bottom-color: palette(highlight);
        }}
        """

    # ── 菜单 ─────────────────────────────────────────────

    def _menu_blocks(self) -> str:
        return f"""
        /* ── 菜单：surface_container + 4dp 圆角 ── */
        QMenuBar {{
            color: palette(window-text);
        }}

        QMenuBar::item {{
            padding: 6px 12px;
            background: transparent;
        }}

        QMenuBar::item:selected {{
            background-color: palette(alternate-base);
        }}

        QMenu {{
            background-color: palette(alternate-base);
            color: palette(text);
            border: 1px solid palette(midlight);
            border-radius: {Shape.EXTRA_SMALL}px;
            padding: {Space.XS}px;
        }}

        QMenu::item {{
            padding: {Space.M}px {Space.XL}px;
            border-radius: {Shape.EXTRA_SMALL}px;
        }}

        QMenu::item:selected {{
            background-color: palette(highlight);
            color: palette(highlighted-text);
        }}

        QMenu::separator {{
            height: 1px;
            background-color: palette(midlight);
            margin: {Space.XS}px {Space.S}px;
        }}
        """

    # ── 滚动条（半透明，hover 加深，无箭头）──────────────

    def _scrollbar_blocks(self) -> str:
        thickness = Space.S
        radius = Space.XS
        return f"""
        /* ── 滚动条：半透明把手，无箭头 ── */
        QScrollBar:vertical {{
            background: transparent;
            width: {thickness}px;
            margin: 0px;
        }}

        QScrollBar::handle:vertical {{
            background-color: palette(midlight);
            border-radius: {radius}px;
            min-height: 32px;
        }}

        QScrollBar::handle:vertical:hover {{
            background-color: palette(mid);
        }}

        QScrollBar:horizontal {{
            background: transparent;
            height: {thickness}px;
            margin: 0px;
        }}

        QScrollBar::handle:horizontal {{
            background-color: palette(midlight);
            border-radius: {radius}px;
            min-width: 32px;
        }}

        QScrollBar::handle:horizontal:hover {{
            background-color: palette(mid);
        }}

        QScrollBar::add-line, QScrollBar::sub-line {{
            width: 0px;
            height: 0px;
            border: none;
            background: transparent;
        }}

        QScrollBar::add-page, QScrollBar::sub-page {{
            background: transparent;
            border: none;
        }}
        """

    # ── 进度条 ───────────────────────────────────────────

    def _progress_block(self) -> str:
        # 页面与列表行统一使用自绘 ``MaterialProgress``（4dp 轨道、圆头、
        # 文字在条外）。这里仍保留原生 QProgressBar 的兜底样式（4dp），
        # 避免任何遗留 / 第三方控件退回 MD2 的 16px 厚条。
        return """
        /* ── 进度条（兜底；业务统一用 MaterialProgress）── */
        QProgressBar {
            background-color: palette(midlight);
            color: transparent;
            border: none;
            border-radius: 2px;
            text-align: center;
            min-height: 4px;
            max-height: 4px;
        }

        QProgressBar::chunk {
            background-color: palette(highlight);
            border-radius: 2px;
        }
        """

    # 工具提示不写 QSS 颜色：QToolTip 没有父窗口，写死十六进制颜色会在
    # 主窗口级主题切换后停留在启动时的旧色。交给 QPalette 的
    # ToolTipBase / ToolTipText（palette.py）按平台样式绘制，颜色即时生效。
