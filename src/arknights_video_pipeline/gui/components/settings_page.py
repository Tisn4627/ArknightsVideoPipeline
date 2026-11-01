"""
gui.components.settings_page - 设置页面

页面布局：页面头（标题 + 副标题）+ 卡片网格（宽屏双列 / 其余单列）。
卡片使用 ``surface_container_low`` + 1dp 描边（outlined 变体），
与主页 / 工具页 / 关于页保持同一套层级语言。

功能模块：
1. 外观（Appearance）：浅色 / 深色主题、动态色彩与种子色，即时生效；
2. 配置文件（Configuration files）：按类型选择并生成默认配置文件，
   与 CLI ``--init-config`` 行为一致，支持"一键选择全部"与"取消全部选择"。
3. 全局设置（Global）：Copilot 后端、MAA/Output 路径、识别参数与日志，
   这些控件由 MainWindow 共享读写，Home 页不再持有。

页面通过信号与 MainWindow 解耦：
- ``theme_change_requested(bool)``：请求切换主题（True=深色）；
- ``home_requested()``：请求返回主页。
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QBoxLayout, QLabel,
    QSpinBox, QSizePolicy, QDialog,
)

# 复用 CLI 初始化入口（core.pipeline 的私有函数）：暂无公开等价物，
# ruff 默认规则不检查私有成员导入，故保留并注明原因
from arknights_video_pipeline.core.pipeline import _init_config
from arknights_video_pipeline.gui.components.file_selector import FileSelector
from arknights_video_pipeline.gui.components.material_checkbox import MaterialCheckBox
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import MaterialCard
from arknights_video_pipeline.gui.components.material_color_picker import (
    ColorPickerDialog,
    ColorSwatchButton,
)
from arknights_video_pipeline.gui.components.material_combo import MaterialComboBox
from arknights_video_pipeline.gui.components.material_switch import MaterialSwitch
from arknights_video_pipeline.gui.components.page_header import PageHeader
from arknights_video_pipeline.gui.components.settings_row_builders import (
    FieldRow,
    build_switch_row, build_int_row, build_float_row,
    build_combo_row, build_path_row, build_string_row,
    build_color_row, build_range_row, build_nullable_int_row, make_row,
)
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import (
    BASELINE_SEED, Margin, MaterialColors, MaterialTypography, Space,
    WindowSizeClass, normalize_hex, set_text_color,
)
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller


class SettingsPage(QWidget):
    """设置页面：主题切换 + 配置文件生成，布局参考 Home 选项卡"""

    theme_change_requested = pyqtSignal(bool)  # True=深色
    home_requested = pyqtSignal()
    # 语言切换请求（参数：语言码 "zh-CN"/"en-US"）
    language_change_requested = pyqtSignal(str)
    # 配置文件重置完成信号（参数：成功生成的模块 key 列表）
    # MainWindow 监听后需重新加载磁盘配置并刷新 MAA/Output/Log level 等
    # 共享控件，确保关闭 GUI 时不会将重置前的旧值写回配置文件。
    config_reset = pyqtSignal(list)
    # 高级配置变更信号（供 MainWindow 连接到 ConfigProxy 写回）
    maa_path_changed = pyqtSignal(str)
    output_dir_changed = pyqtSignal(str)
    log_level_changed = pyqtSignal(str)
    # 性能配置变更信号（多线程开关 + 最大并发数）
    multithreading_changed = pyqtSignal(bool)
    max_concurrent_changed = pyqtSignal(int)
    # FFmpeg 路径配置变更信号（仅 Windows）
    ffmpeg_custom_changed = pyqtSignal(bool)
    ffmpeg_path_changed = pyqtSignal(str)
    # 新增 pipeline.json 字段变更信号
    log_to_file_changed = pyqtSignal(bool)
    log_max_bytes_changed = pyqtSignal(int)
    log_backup_count_changed = pyqtSignal(int)
    formation_path_changed = pyqtSignal(str)
    actions_path_changed = pyqtSignal(str)
    track_path_changed = pyqtSignal(str)
    # 子配置变更信号：(config_name, field_path, value)
    # config_name 为 "formation"/"actions"/"track"/"style1"/"style2"
    sub_config_changed = pyqtSignal(str, str, object)
    # Pipeline 配置变更信号（Copilot 后端 + recognition 识别参数）
    copilot_backend_changed = pyqtSignal(str)
    copilot_timeout_changed = pyqtSignal(int)
    copilot_max_retries_changed = pyqtSignal(int)
    ocr_source_changed = pyqtSignal(str)
    resolution_changed = pyqtSignal(str)
    stage_override_changed = pyqtSignal(str)
    with_video_time_changed = pyqtSignal(bool)
    resource_dir_changed = pyqtSignal(str)
    # 高级分区折叠状态变更信号（持久化到 gui.json）
    advanced_expanded_changed = pyqtSignal(bool)
    # 动态色彩（Material You）：开关与种子色（持久化到 gui.json）
    dynamic_color_changed = pyqtSignal(bool)
    seed_color_changed = pyqtSignal(str)

    # (module_key, 标题翻译 key, 文件名)
    CONFIG_TYPES: list[tuple[str, str, str]] = [
        ("pipeline", "settings.config_type.pipeline.title", "pipeline.json"),
        ("formation", "settings.config_type.formation.title", "formation.json"),
        ("actions", "settings.config_type.actions.title", "actions.json"),
        ("track", "settings.config_type.track.title", "track.json"),
        ("compose", "settings.config_type.compose.title", "video_compose/style1.json"),
        ("compose_style2", "settings.config_type.compose_style2.title", "video_compose/style2.json"),
        ("gui", "settings.config_type.gui.title", "gui.json"),
    ]

    def __init__(self, colors: MaterialColors | None = None,
                 is_dark: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        # 显式开启 WA_StyledBackground，否则 QSS 中的 QWidget/QFrame 背景色
        # 不会被绘制到该页面上，导致页面与子卡片失去背景色（表现为透明或黑底）。
        # 主页 QWidget 默认携带此属性，故无需额外设置；为避免差异这里强制开启。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 让页面宽度跟随外部 QScrollArea 视口（响应式所必需）：
        # 默认 sizeHint 可能被内部全宽按钮撑大，导致 QScrollArea 在窄窗口
        # 下出现横向裁切。这里 Preferred + horizontalStretch 让父级
        # 容器（QScrollArea）可以按视口宽度约束我们的宽度。
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._colors = colors or theme_controller().colors()
        self._is_dark = is_dark
        self._typo = MaterialTypography()
        self._size_class = "expanded"
        # 配置复选框网格列数（页面宽 ≥640 时双列；卡片本身固定单列）
        self._checkbox_two_col: bool | None = None
        # 动态色彩（由 MainWindow 从 gui.json 回填）
        self._is_dynamic = True
        self._seed_color = BASELINE_SEED
        self._status_is_error = False

        # 记录所有需要随主题刷新的辅助文本控件，便于统一更新颜色
        self._dim_labels: list[QLabel] = []
        # 子配置 FieldRow 注册表：(config_name, field_path) -> FieldRow
        self._sub_field_rows: dict[tuple[str, str], FieldRow] = {}
        # pipeline.json 新增字段的 FieldRow 注册表
        self._pipeline_field_rows: dict[str, FieldRow] = {}
        # 重翻译注册表：(setter, key_or_None)。key 为 str 时调用 setter(tr(key))；
        # key 为 None 时调用 setter()（setter 内部自行调用 tr，用于带占位符的文本）
        self._tr_labels: list[tuple[Callable[[str], None] | Callable[[], None], str | None]] = []
        # 配置文件复选框注册表：(checkbox, title_key, filename)，重翻译时重建 "标题 · 文件名"
        self._checkbox_specs: list[tuple[MaterialCheckBox, str, str]] = []

        self._build_ui()
        self._apply_colors()
        # 语言切换时刷新所有静态文本
        i18n().language_changed.connect(self._retranslate)
        # 订阅主题：字段行 / 卡片 / 辅助文字配色自动跟随
        theme_controller().theme_changed.connect(self.set_colors)

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            Margin.EXPANDED, Margin.EXPANDED, Margin.EXPANDED, Margin.EXPANDED
        )
        root.setSpacing(Space.XXL)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Hero 区域（参考 Home：大标题 + 副标题 + 主按钮）
        root.addWidget(self._build_hero())

        # 始终可见卡片
        self._language_card = self._build_language_card()
        self._appearance_card = self._build_theme_card()
        self._config_card = self._build_config_card()
        self._advanced_card = self._build_advanced_card()
        self._ffmpeg_card = self._build_ffmpeg_card()  # 非 Windows 返回 None
        self._compose_style1_main_card = self._build_compose_main_card("style1")
        self._compose_style2_main_card = self._build_compose_main_card("style2")

        # 高级选项开关卡片（控制下方高级设置项的显隐）
        self._advanced_toggle_card = self._build_advanced_toggle_card()

        # 高级设置内容容器（开关关闭时隐藏，不占用布局空间）
        # 仅包含独立的 Track / Formation / Actions / Performance 卡片
        # 全局设置与 VideoCompose 的高级字段已内嵌到各自卡片中
        self._collapsible_content = QWidget()
        self._collapsible_content.setObjectName("transparentPane")
        collapsible_layout = QVBoxLayout(self._collapsible_content)
        collapsible_layout.setContentsMargins(0, 0, 0, 0)
        collapsible_layout.setSpacing(Space.XL)
        self._track_card = self._build_track_card()
        self._formation_card = self._build_formation_card()
        self._actions_card = self._build_actions_card()
        self._performance_card = self._build_performance_card()
        for card in (
            self._track_card, self._formation_card, self._actions_card,
            self._performance_card,
        ):
            if card is not None:
                collapsible_layout.addWidget(card)
        self._collapsible_content.setVisible(False)  # 默认收起

        # 卡片网格（宽屏双列 / 窄屏单列，由 _apply_grid_layout 统一排布）
        self._cards_grid = QGridLayout()
        self._cards_grid.setContentsMargins(0, 0, 0, 0)
        self._cards_grid.setSpacing(Space.XL)
        self._cards_grid.setColumnStretch(0, 1)
        self._cards_container = QWidget()
        self._cards_container.setObjectName("transparentPane")
        self._cards_container.setLayout(self._cards_grid)
        # 卡片宿主（QVBoxLayout: 卡片 + 底部 stretch）：
        # 卡片按列宽填满，同时保持顶部对齐而不是被拉伸到行高
        self._card_hosts: dict[int, QWidget] = {}
        root.addWidget(self._cards_container)
        self._apply_grid_layout()
        self._sync_checkbox_columns()

    def _sync_checkbox_columns(self) -> None:
        """配置复选框网格列数：页面足够宽时 2 列，否则单列

        设置页卡片本身固定单列（表单字段需要宽度）；复选框没有输入框，
        在宽卡片中双列排布可以缩短配置文件卡片的高度。
        """
        two = self.width() >= 640
        if two == self._checkbox_two_col:
            return
        self._checkbox_two_col = two
        self._reflow_checkbox_grid(two_col=two)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_checkbox_columns()

    def _make_section_title(self, text: str) -> QLabel:
        """卡片内小节标题（14/500，随主题刷新颜色）

        字体与字距走 QFont 而不是 widget 级 stylesheet：``_apply_colors``
        刷新 ``_dim_labels`` 时只重设 color，不会把 500 字重和字距覆盖掉。
        """
        label = QLabel(text)
        font = self._typo.font("title_small")
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        label.setFont(font)
        label.setWordWrap(True)
        self._dim_labels.append(label)
        return label

    def _build_hero(self) -> QWidget:
        """页面头（与主页 / 工具页 / 关于页共用 PageHeader）"""
        self._header = PageHeader(
            tr("settings.hero_title"), tr("settings.subtitle"), colors=self._colors
        )
        self._tr_labels.append((self._header.set_title, "settings.hero_title"))
        self._tr_labels.append((self._header.set_subtitle, "settings.subtitle"))
        return self._header

    def _build_language_card(self) -> MaterialCard:
        """语言切换卡片（置顶）：下拉选择界面语言，立即生效"""
        card = MaterialCard(tr("settings.language.title"))
        self._tr_labels.append((card.set_title, "settings.language.title"))

        self._lang_combo = MaterialComboBox(colors=self._colors)
        self._lang_combo.setObjectName("settingsField")
        for code, display_name in i18n().available_languages():
            self._lang_combo.addItem(display_name, code)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self._lang_row = make_row(
            "",
            self._lang_combo,
            colors=self._colors,
            desc=tr("settings.language.desc"),
            max_width=280,
            wide=True,
        )
        self._tr_labels.append((self._lang_row.set_desc, "settings.language.desc"))
        card.add_widget(self._lang_row.container)
        return card

    def _build_theme_card(self) -> MaterialCard:
        card = MaterialCard(tr("settings.appearance.title"))
        self._tr_labels.append((card.set_title, "settings.appearance.title"))
        # 让卡片内所有内容靠上对齐，避免外观标题与下方控件之间
        # 出现大片空白（双列网格中两卡片同高时尤为明显）。
        card.set_content_alignment(Qt.AlignmentFlag.AlignTop)

        # ── 深色主题 ─────────────────────────────────────
        self._theme_switch = MaterialSwitch(checked=self._is_dark, colors=self._colors)
        self._theme_switch.toggled.connect(self._on_theme_toggled)
        self._theme_row = make_row(
            tr("settings.appearance.label"),
            self._theme_switch,
            colors=self._colors,
            desc=tr("settings.appearance.desc"),
            max_width=80,
        )
        self._tr_labels.append((self._theme_row.set_label, "settings.appearance.label"))
        self._tr_labels.append((self._theme_row.set_desc, "settings.appearance.desc"))
        card.add_widget(self._theme_row.container)

        # ── 动态色彩（Material You）────────────────────────
        self._dynamic_switch = MaterialSwitch(
            checked=self._is_dynamic, colors=self._colors
        )
        self._dynamic_switch.toggled.connect(self._on_dynamic_color_toggled)
        self._dynamic_row = make_row(
            tr("settings.appearance.dynamic"),
            self._dynamic_switch,
            colors=self._colors,
            desc=tr("settings.appearance.dynamic_desc"),
            max_width=80,
        )
        self._tr_labels.append(
            (self._dynamic_row.set_label, "settings.appearance.dynamic")
        )
        self._tr_labels.append(
            (self._dynamic_row.set_desc, "settings.appearance.dynamic_desc")
        )
        card.add_widget(self._dynamic_row.container)

        # ── 种子色 ────────────────────────────────────────
        seed_control = QWidget()
        seed_control.setObjectName("transparentPane")
        seed_layout = QHBoxLayout(seed_control)
        seed_layout.setContentsMargins(0, 0, 0, 0)
        seed_layout.setSpacing(Space.M)
        seed_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        # 值 + 色块作为一个紧凑组靠右：色块右缘与上方开关右缘对齐
        seed_layout.addStretch(1)
        self._seed_value = QLabel(self._seed_color)
        self._seed_value.setFont(self._typo.body_medium)
        self._dim_labels.append(self._seed_value)
        seed_layout.addWidget(self._seed_value, 0)
        self._seed_swatch = ColorSwatchButton(self._seed_color, colors=self._colors)
        self._seed_swatch.setToolTip(tr("settings.appearance.seed_pick"))
        self._seed_swatch.clicked.connect(self._on_pick_seed_color)
        seed_layout.addWidget(self._seed_swatch, 0)

        self._seed_row = make_row(
            tr("settings.appearance.seed"),
            seed_control,
            colors=self._colors,
            max_width=160,
            wide=True,
            field=True,
            align_end=True,
        )
        self._tr_labels.append((self._seed_row.set_label, "settings.appearance.seed"))
        card.add_widget(self._seed_row.container)

        return card

    def _build_config_card(self) -> MaterialCard:
        card = MaterialCard(tr("settings.config.title"))
        self._tr_labels.append((card.set_title, "settings.config.title"))
        layout = QVBoxLayout()
        layout.setSpacing(Space.M)

        self._config_desc = QLabel(tr("settings.config.desc"))
        self._config_desc.setFont(self._typo.body_small)
        self._config_desc.setWordWrap(True)
        self._dim_labels.append(self._config_desc)
        self._tr_labels.append((self._config_desc.setText, "settings.config.desc"))
        layout.addWidget(self._config_desc)

        # 复选框网格（容器，以便在窄屏下重新排列为单列）
        self._config_checkboxes: dict[str, MaterialCheckBox] = {}
        self._checkbox_grid = QGridLayout()
        self._checkbox_grid.setHorizontalSpacing(Space.XL)
        self._checkbox_grid.setVerticalSpacing(Space.S)
        for key, title_key, filename in self.CONFIG_TYPES:
            # 传入当前主题 colors，避免 MaterialCheckBox 默认使用浅色
            # MaterialColors.light() 导致首次进入深色模式时 indicator
            # 保持白色的问题
            cb = MaterialCheckBox(tr(title_key), colors=self._colors)
            # 文件名放进 tooltip：完整 "标题 · path/to/file.json" 在窄卡片里
            # 会顶到卡片边缘，读起来也更噪声
            cb.setToolTip(filename)
            self._config_checkboxes[key] = cb
            self._checkbox_specs.append((cb, title_key, filename))
        self._reflow_checkbox_grid(two_col=False)
        layout.addLayout(self._checkbox_grid)

        # 全选 / 清空：tonal + text（不抢走"生成"的 filled 主操作）
        self._sel_buttons_container = QWidget()
        self._sel_buttons_container.setObjectName("transparentPane")
        self._sel_buttons_layout = QHBoxLayout(self._sel_buttons_container)
        self._sel_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._sel_buttons_layout.setSpacing(Space.M)
        self._select_all_btn = MaterialButton(
            tr("settings.config.select_all"), variant=MaterialButton.VARIANT_TONAL
        )
        self._clear_btn = MaterialButton(
            tr("settings.config.clear_all"), variant=MaterialButton.VARIANT_TEXT
        )
        self._tr_labels.append((self._select_all_btn.setText, "settings.config.select_all"))
        self._tr_labels.append((self._clear_btn.setText, "settings.config.clear_all"))
        self._select_all_btn.clicked.connect(self._on_select_all)
        self._clear_btn.clicked.connect(self._on_clear_all)
        # stretch 在前，将按钮推到右侧
        self._sel_buttons_layout.addStretch()
        self._sel_buttons_layout.addWidget(self._select_all_btn)
        self._sel_buttons_layout.addWidget(self._clear_btn)
        layout.addWidget(self._sel_buttons_container)

        # 生成按钮 + 状态文本（同样使用包装容器支持窄屏重排）
        self._action_buttons_container = QWidget()
        self._action_buttons_container.setObjectName("transparentPane")
        self._action_buttons_layout = QHBoxLayout(self._action_buttons_container)
        self._action_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._action_buttons_layout.setSpacing(Space.M)
        self._generate_btn = MaterialButton(
            tr("settings.config.generate"), variant=MaterialButton.VARIANT_FILLED
        )
        self._tr_labels.append((self._generate_btn.setText, "settings.config.generate"))
        self._generate_btn.clicked.connect(self._on_generate)
        self._config_status = QLabel("")
        self._config_status.setFont(self._typo.body_small)
        self._config_status.setWordWrap(True)
        # 状态文字占左侧剩余空间，主操作"生成默认配置"右对齐——
        # 与上一行"一键选择全部 / 取消全部选择"的右对齐动作区一致
        self._action_buttons_layout.addWidget(self._config_status, 1)
        self._action_buttons_layout.addWidget(self._generate_btn)
        layout.addWidget(self._action_buttons_container)

        card.add_layout(layout)
        return card

    def _build_advanced_toggle_card(self) -> MaterialCard:
        """高级选项开关卡片：MaterialSwitch 控制高级设置项的显隐。

        开关打开时，``_collapsible_content`` 容器内的所有高级卡片立即显示；
        关闭时立即隐藏且不占用布局空间。开关状态持久化到 ``gui.json``。
        """
        card = MaterialCard(tr("settings.advanced_toggle.title"))
        self._tr_labels.append((card.set_title, "settings.advanced_toggle.title"))

        self._advanced_switch = MaterialSwitch(checked=False, colors=self._colors)
        self._advanced_switch.toggled.connect(self._on_advanced_toggled)
        self._advanced_row = make_row(
            tr("settings.advanced_toggle.label"),
            self._advanced_switch,
            colors=self._colors,
            desc=tr("settings.advanced_toggle.desc"),
            max_width=80,
        )
        self._tr_labels.append(
            (self._advanced_row.set_label, "settings.advanced_toggle.label")
        )
        self._tr_labels.append(
            (self._advanced_row.set_desc, "settings.advanced_toggle.desc")
        )
        card.add_widget(self._advanced_row.container)
        return card

    def _build_advanced_card(self) -> MaterialCard:
        """全局设置卡片：Copilot 后端 / Output 路径（始终可见）+ MAA 路径 /
        统一超时/重试（两后端共用）/ 识别参数 / 日志级别 / 日志文件 /
        子配置文件路径（高级开关打开后可见）。MAA 路径仅在识别后端为 maa 时显示。"""
        card = MaterialCard(tr("settings.global.title"))
        self._tr_labels.append((card.set_title, "settings.global.title"))
        layout = QVBoxLayout()
        layout.setSpacing(Space.M)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 描述文本
        self._advanced_desc = QLabel(tr("settings.global.desc"))
        self._advanced_desc.setFont(self._typo.body_small)
        self._advanced_desc.setWordWrap(True)
        self._dim_labels.append(self._advanced_desc)
        self._tr_labels.append((self._advanced_desc.setText, "settings.global.desc"))
        layout.addWidget(self._advanced_desc)

        # Copilot 后端选择：recognition（默认，纯 Python）/ maa（需安装 MAA）
        row = build_combo_row(
            tr("settings.global.backend"), ["recognition", "maa"],
            default="recognition", colors=self._colors,
            on_changed=self._on_copilot_backend_changed,
        )
        layout.addWidget(row.widget)
        self._pipeline_field_rows["copilot_backend"] = row
        self._tr_labels.append((row.set_label, "settings.global.backend"))

        # MAA 路径（左侧标签 + 无浮动标签的路径字段）：仅后端为 maa 时显示
        self._maa_selector = FileSelector(
            mode=FileSelector.MODE_DIRECTORY,
            label=tr("settings.global.maa_path"),
            placeholder=tr("settings.global.maa_path_placeholder"),
            show_label=False,
        )
        self._maa_row = make_row(
            tr("settings.global.maa_path"), self._maa_selector,
            colors=self._colors, expanding=True, field=True,
        )
        self._maa_row.container.setVisible(False)
        layout.addWidget(self._maa_row.container)

        # Output 路径
        self._output_selector = FileSelector(
            mode=FileSelector.MODE_DIRECTORY,
            label=tr("settings.global.output"),
            placeholder=tr("settings.global.output_placeholder"),
            show_label=False,
        )
        self._output_row = make_row(
            tr("settings.global.output"), self._output_selector,
            colors=self._colors, expanding=True, field=True,
        )
        layout.addWidget(self._output_row.container)
        # 注册 selector 行标签 / placeholder 重翻译
        self._tr_labels.append((self._maa_row.set_label, "settings.global.maa_path"))
        self._tr_labels.append((self._maa_selector.set_placeholder, "settings.global.maa_path_placeholder"))
        self._tr_labels.append((self._output_row.set_label, "settings.global.output"))
        self._tr_labels.append((self._output_selector.set_placeholder, "settings.global.output_placeholder"))

        # 将内部控件信号转发为公开信号，供 MainWindow 连接
        self._maa_selector.path_changed.connect(self.maa_path_changed)
        self._output_selector.path_changed.connect(self.output_dir_changed)

        card.add_layout(layout)

        # ── 高级字段容器（开关关闭时隐藏，不占用布局空间）──
        self._global_advanced_container = QWidget()
        self._global_advanced_container.setObjectName("transparentPane")
        adv_layout = QVBoxLayout(self._global_advanced_container)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(Space.M)

        # 日志级别：左侧标签 + MD3 下拉框（自绘 chevron）
        self._log_level_combo = MaterialComboBox(colors=self._colors)
        self._log_level_combo.setObjectName("settingsField")
        self._log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._log_level_row = make_row(
            tr("settings.global.log_level"), self._log_level_combo,
            colors=self._colors, max_width=280, wide=True, field=True,
        )
        self._tr_labels.append((self._log_level_row.set_label, "settings.global.log_level"))
        adv_layout.addWidget(self._log_level_row.container)

        self._log_level_combo.currentTextChanged.connect(self.log_level_changed)

        # 日志文件开关
        row = build_switch_row(
            tr("settings.global.log_to_file"), tr("settings.global.log_to_file_desc"),
            default=True, colors=self._colors,
            on_changed=self.log_to_file_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["log_to_file"] = row
        self._tr_labels.append((row.set_label, "settings.global.log_to_file"))
        self._tr_labels.append((row.set_desc, "settings.global.log_to_file_desc"))

        # 日志文件最大字节数
        row = build_int_row(
            tr("settings.global.log_max_bytes"), default=10485760,
            minimum=1024, maximum=1073741824, step=1024,
            colors=self._colors,
            on_changed=self.log_max_bytes_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["log_max_bytes"] = row
        self._tr_labels.append((row.set_label, "settings.global.log_max_bytes"))

        # 日志备份数
        row = build_int_row(
            tr("settings.global.log_backup_count"), default=3,
            minimum=0, maximum=100, step=1,
            colors=self._colors,
            on_changed=self.log_backup_count_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["log_backup_count"] = row
        self._tr_labels.append((row.set_label, "settings.global.log_backup_count"))

        # Copilot 超时（秒）：recognition/maa 两后端共用的统一超时
        # （默认值与 core/config.py PIPELINE_DEFAULTS 的 2400 统一）
        row = build_int_row(
            tr("settings.global.copilot_timeout"), default=2400,
            minimum=10, maximum=7200, step=10,
            colors=self._colors,
            on_changed=self.copilot_timeout_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["copilot_timeout_seconds"] = row
        self._tr_labels.append((row.set_label, "settings.global.copilot_timeout"))

        # Copilot 识别尝试次数（含首次）：recognition/maa 两后端共用。
        # 语义为"总尝试次数"（1=不重试）；minimum=1 与流水线的兜底语义对齐
        # （<1 时流水线按 1 次执行并告警）。
        row = build_int_row(
            tr("settings.global.copilot_retries"), default=1,
            minimum=1, maximum=10, step=1,
            colors=self._colors,
            on_changed=self.copilot_max_retries_changed.emit,
            desc=tr("settings.global.copilot_retries_desc"),
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["copilot_max_retries"] = row
        self._tr_labels.append((row.set_label, "settings.global.copilot_retries"))
        self._tr_labels.append(
            (row.set_desc, "settings.global.copilot_retries_desc")
        )

        # recognition 识别参数小节标题
        rec_title = QLabel(tr("settings.global.recognition_title"))
        rec_title.setFont(self._typo.title_medium)
        rec_title.setStyleSheet("border: none; background: transparent;")
        adv_layout.addWidget(rec_title)
        self._tr_labels.append((rec_title.setText, "settings.global.recognition_title"))

        # OCR 来源：maamodel（默认，使用 MAA 模型）/ default
        row = build_combo_row(
            tr("settings.global.ocr_source"), ["maamodel", "default"],
            default="maamodel", colors=self._colors,
            on_changed=self.ocr_source_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["ocr_source"] = row
        self._tr_labels.append((row.set_label, "settings.global.ocr_source"))

        # 识别分辨率（宽x高）
        row = build_string_row(
            tr("settings.global.resolution"), default="1280x720",
            colors=self._colors,
            on_changed=self.resolution_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["resolution"] = row
        self._tr_labels.append((row.set_label, "settings.global.resolution"))

        # 关卡覆盖：空=自动识别，否则指定关卡 code/name/stageId
        row = build_string_row(
            tr("settings.global.stage_override"), default="",
            colors=self._colors,
            on_changed=self.stage_override_changed.emit,
            desc=tr("settings.global.stage_override_desc"),
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["stage_override"] = row
        self._tr_labels.append((row.set_label, "settings.global.stage_override"))
        self._tr_labels.append(
            (row.set_desc, "settings.global.stage_override_desc")
        )

        # 输出 video_time 扩展字段
        row = build_switch_row(
            tr("settings.global.with_video_time"),
            tr("settings.global.with_video_time_desc"),
            default=False, colors=self._colors,
            on_changed=self.with_video_time_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["with_video_time"] = row
        self._tr_labels.append((row.set_label, "settings.global.with_video_time"))
        self._tr_labels.append((row.set_desc, "settings.global.with_video_time_desc"))

        # 识别资源目录：空=用顶层 resource/
        row = build_path_row(
            tr("settings.global.resource_dir"), mode=FileSelector.MODE_DIRECTORY,
            colors=self._colors,
            on_changed=self.resource_dir_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["resource_dir"] = row
        self._tr_labels.append((row.set_label, "settings.global.resource_dir"))

        # Formation 配置文件路径
        row = build_path_row(
            tr("settings.global.formation_path"), mode=FileSelector.MODE_OPEN_FILE,
            colors=self._colors,
            on_changed=self.formation_path_changed.emit,
        )
        row.set_filter("JSON files (*.json);;All files (*.*)")
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["formation"] = row
        self._tr_labels.append((row.set_label, "settings.global.formation_path"))

        # Actions 配置文件路径
        row = build_path_row(
            tr("settings.global.actions_path"), mode=FileSelector.MODE_OPEN_FILE,
            colors=self._colors,
            on_changed=self.actions_path_changed.emit,
        )
        row.set_filter("JSON files (*.json);;All files (*.*)")
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["actions"] = row
        self._tr_labels.append((row.set_label, "settings.global.actions_path"))

        # Track 配置文件路径
        row = build_path_row(
            tr("settings.global.track_path"), mode=FileSelector.MODE_OPEN_FILE,
            colors=self._colors,
            on_changed=self.track_path_changed.emit,
        )
        row.set_filter("JSON files (*.json);;All files (*.*)")
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["track"] = row
        self._tr_labels.append((row.set_label, "settings.global.track_path"))

        self._global_advanced_container.setVisible(False)
        card.add_widget(self._global_advanced_container)
        return card

    def _build_performance_card(self) -> MaterialCard:
        """性能配置卡片：多线程开关 + 最大并发数

        多线程开关启用后，批量处理将按 ``max_concurrent`` 上限并发派发
        PipelineWorker；关闭时保持完全串行（默认，避免 MAA 资源争用）。
        这两个控件由 SettingsPage 创建并通过公开信号/方法暴露，MainWindow
        连接到 ConfigProxy 写回，不在 Home 页持有，避免双源状态不同步。
        """
        card = MaterialCard(tr("settings.performance.title"))
        self._tr_labels.append((card.set_title, "settings.performance.title"))
        layout = QVBoxLayout()
        layout.setSpacing(Space.M)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 多线程开关行：左侧标题+说明，右侧 MaterialSwitch
        self._mt_switch = MaterialSwitch(checked=False, colors=self._colors)
        self._mt_switch.toggled.connect(self._on_multithreading_toggled)
        self._mt_row = make_row(
            tr("settings.performance.mt_label"), self._mt_switch,
            colors=self._colors, desc=tr("settings.performance.mt_desc"),
            max_width=80,
        )
        self._tr_labels.append((self._mt_row.set_label, "settings.performance.mt_label"))
        self._tr_labels.append((self._mt_row.set_desc, "settings.performance.mt_desc"))
        layout.addWidget(self._mt_row.container)

        # 最大并发数行：仅在多线程启用时可编辑；关闭时置灰
        self._conc_spin = QSpinBox()
        self._conc_spin.setObjectName("settingsField")
        self._conc_spin.setFont(self._typo.body_large)
        self._conc_spin.setRange(1, 16)
        self._conc_spin.setValue(1)
        self._conc_spin.setSingleStep(1)
        self._conc_spin.setEnabled(False)
        self._conc_spin.valueChanged.connect(self._on_max_concurrent_changed)
        self._conc_row = make_row(
            tr("settings.performance.max_concurrent"), self._conc_spin,
            colors=self._colors, max_width=160, wide=True, field=True,
            align_end=True,
        )
        self._tr_labels.append(
            (self._conc_row.set_label, "settings.performance.max_concurrent")
        )
        layout.addWidget(self._conc_row.container)

        card.add_layout(layout)
        return card

    def _build_ffmpeg_card(self) -> MaterialCard | None:
        """FFmpeg 路径配置卡片（仅 Windows）

        非 Windows 平台返回 None，不构建卡片。包含：
        - 启用自定义路径开关
        - FFmpeg 可执行文件所在目录选择器
        - "此功能仅支持 Windows 系统" 提示
        """
        if sys.platform != "win32":
            return None

        card = MaterialCard(tr("settings.ffmpeg.title"))
        self._tr_labels.append((card.set_title, "settings.ffmpeg.title"))
        layout = QVBoxLayout()
        layout.setSpacing(Space.M)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 描述 + Windows-only 提示
        self._ffmpeg_desc = QLabel(tr("settings.ffmpeg.desc"))
        self._ffmpeg_desc.setFont(self._typo.body_small)
        self._ffmpeg_desc.setWordWrap(True)
        self._dim_labels.append(self._ffmpeg_desc)
        layout.addWidget(self._ffmpeg_desc)
        self._tr_labels.append((self._ffmpeg_desc.setText, "settings.ffmpeg.desc"))

        self._ffmpeg_platform_hint = QLabel(tr("settings.ffmpeg.platform_hint"))
        self._ffmpeg_platform_hint.setFont(self._typo.body_small)
        self._ffmpeg_platform_hint.setWordWrap(True)
        self._dim_labels.append(self._ffmpeg_platform_hint)
        layout.addWidget(self._ffmpeg_platform_hint)
        self._tr_labels.append((self._ffmpeg_platform_hint.setText, "settings.ffmpeg.platform_hint"))

        # 启用开关行：左侧标题，右侧 MaterialSwitch
        self._ffmpeg_switch = MaterialSwitch(checked=False, colors=self._colors)
        self._ffmpeg_switch.toggled.connect(self._on_ffmpeg_custom_toggled)
        self._ffmpeg_row = make_row(
            tr("settings.ffmpeg.enable_label"), self._ffmpeg_switch,
            colors=self._colors, max_width=80,
        )
        self._tr_labels.append(
            (self._ffmpeg_row.set_label, "settings.ffmpeg.enable_label")
        )
        layout.addWidget(self._ffmpeg_row.container)

        # 路径选择器（目录模式，选择 ffmpeg.exe 所在目录）
        self._ffmpeg_selector = FileSelector(
            mode=FileSelector.MODE_DIRECTORY,
            label=tr("settings.ffmpeg.title"),
            placeholder=tr("settings.ffmpeg.placeholder"),
            show_label=False,
        )
        self._ffmpeg_selector.path_changed.connect(self._on_ffmpeg_path_changed)
        self._tr_labels.append((self._ffmpeg_selector.set_placeholder, "settings.ffmpeg.placeholder"))
        # 开关默认关闭时路径选择器禁用
        self._ffmpeg_selector.setEnabled(False)
        self._ffmpeg_path_row = make_row(
            tr("settings.ffmpeg.title"), self._ffmpeg_selector,
            colors=self._colors, expanding=True, field=True,
        )
        self._tr_labels.append(
            (self._ffmpeg_path_row.set_label, "settings.ffmpeg.title")
        )
        layout.addWidget(self._ffmpeg_path_row.container)

        card.add_layout(layout)
        return card

    # ── 子配置卡片构建 ────────────────────────────────────

    def _emit_sub(self, config_name: str, field_path: str) -> Callable:
        """创建子配置变更回调，发射 sub_config_changed 信号"""
        def _emit(value: Any) -> None:
            self.sub_config_changed.emit(config_name, field_path, value)
        return _emit

    def _register_sub_row(self, config_name: str, field_path: str,
                          row: FieldRow) -> FieldRow:
        """注册子配置 FieldRow 到注册表，返回 row 以便链式调用"""
        self._sub_field_rows[(config_name, field_path)] = row
        return row

    def _make_row_registrar(self, layout: QBoxLayout,
                            config_name: str) -> Callable[[str, FieldRow, str], None]:
        """生成参数化行注册闭包，统一 add / add_bs / add_adv 重复写法。

        返回的闭包执行三件事：控件加入指定布局、登记到子配置行注册表、
        挂接重翻译条目。track / compose 各卡片（含 battle_start 子区与
        高级字段容器）均复用本工厂。
        """
        def register(field_path: str, row: FieldRow, label_key: str) -> None:
            layout.addWidget(row.widget)
            self._register_sub_row(config_name, field_path, row)
            self._tr_labels.append((row.set_label, label_key))
        return register

    def _on_track_mode_changed(self, mode: str) -> None:
        """识别模式切换：同步进入战斗检测子区显隐，并广播配置变更"""
        self.sub_config_changed.emit("track", "track_mode", mode)
        section = getattr(self, "_track_bs_section", None)
        if section is not None:
            section.setVisible(mode == "battlestart")

    def _build_track_card(self) -> MaterialCard:
        """Track 配置卡片：开始按钮识别相关参数（17 个字段）"""
        card = MaterialCard(tr("settings.track.title"))
        self._tr_labels.append((card.set_title, "settings.track.title"))
        layout = QVBoxLayout()
        layout.setSpacing(Space.M)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        desc = QLabel(tr("settings.track.desc"))
        desc.setFont(self._typo.body_medium)
        desc.setWordWrap(True)
        self._dim_labels.append(desc)
        layout.addWidget(desc)
        self._tr_labels.append((desc.setText, "settings.track.desc"))

        cn = "track"
        c = self._colors
        # 行注册闭包（控件加入 track 卡片主布局）
        add = self._make_row_registrar(layout, cn)

        add("track_mode", build_combo_row(
            tr("settings.track.track_mode"),
            items=["startbutton", "battlestart"],
            default="battlestart",
            colors=c,
            on_changed=self._on_track_mode_changed,
        ), "settings.track.track_mode")

        add("resource_dir", build_path_row(
            tr("settings.track.resource_dir"), mode=FileSelector.MODE_DIRECTORY, colors=c,
            on_changed=self._emit_sub(cn, "resource_dir")), "settings.track.resource_dir")
        add("match_threshold", build_float_row(
            tr("settings.track.match_threshold"), default=0.75, minimum=0.0, maximum=1.0,
            step=0.01, decimals=2, colors=c,
            on_changed=self._emit_sub(cn, "match_threshold")), "settings.track.match_threshold")
        add("scale_range", build_range_row(
            tr("settings.track.scale_range"), default_min=0.5, default_max=1.5,
            minimum=0.1, maximum=5.0, step=0.1, decimals=2, colors=c,
            on_changed=self._emit_sub(cn, "scale_range")), "settings.track.scale_range")
        add("scale_steps", build_int_row(
            tr("settings.track.scale_steps"), default=9, minimum=1, maximum=50, colors=c,
            on_changed=self._emit_sub(cn, "scale_steps")), "settings.track.scale_steps")
        add("detection_fps", build_int_row(
            tr("settings.track.detection_fps"), default=2, minimum=1, maximum=30, colors=c,
            on_changed=self._emit_sub(cn, "detection_fps")), "settings.track.detection_fps")
        add("detection_time_limit", build_int_row(
            tr("settings.track.detection_time_limit"), default=30, minimum=1, maximum=600, colors=c,
            on_changed=self._emit_sub(cn, "detection_time_limit")), "settings.track.detection_time_limit")
        add("auto_downscale", build_switch_row(
            tr("settings.track.auto_downscale"), default=True, colors=c,
            on_changed=self._emit_sub(cn, "auto_downscale")), "settings.track.auto_downscale")
        add("downscale_target_height", build_int_row(
            tr("settings.track.downscale_target_height"), default=720, minimum=240, maximum=2160, colors=c,
            on_changed=self._emit_sub(cn, "downscale_target_height")), "settings.track.downscale_target_height")
        add("min_consecutive_frames", build_int_row(
            tr("settings.track.min_consecutive_frames"), default=2, minimum=1, maximum=10, colors=c,
            on_changed=self._emit_sub(cn, "min_consecutive_frames")), "settings.track.min_consecutive_frames")
        add("use_grayscale", build_switch_row(
            tr("settings.track.use_grayscale"), default=True, colors=c,
            on_changed=self._emit_sub(cn, "use_grayscale")), "settings.track.use_grayscale")
        add("use_roi", build_switch_row(
            tr("settings.track.use_roi"), default=True, colors=c,
            on_changed=self._emit_sub(cn, "use_roi")), "settings.track.use_roi")
        add("roi_padding", build_int_row(
            tr("settings.track.roi_padding"), default=50, minimum=0, maximum=500, colors=c,
            on_changed=self._emit_sub(cn, "roi_padding")), "settings.track.roi_padding")
        add("roi_search_expand", build_float_row(
            tr("settings.track.roi_search_expand"), default=1.5, minimum=1.0, maximum=5.0,
            step=0.1, decimals=2, colors=c,
            on_changed=self._emit_sub(cn, "roi_search_expand")), "settings.track.roi_search_expand")
        add("early_stop_threshold", build_float_row(
            tr("settings.track.early_stop_threshold"), default=0.92, minimum=0.0, maximum=1.0,
            step=0.01, decimals=2, colors=c,
            on_changed=self._emit_sub(cn, "early_stop_threshold")), "settings.track.early_stop_threshold")
        add("max_workers", build_int_row(
            tr("settings.track.max_workers"), default=4, minimum=1, maximum=32, colors=c,
            on_changed=self._emit_sub(cn, "max_workers")), "settings.track.max_workers")
        add("debug_mode", build_switch_row(
            tr("settings.track.debug_mode"), default=True, colors=c,
            on_changed=self._emit_sub(cn, "debug_mode")), "settings.track.debug_mode")
        add("output_result", build_switch_row(
            tr("settings.track.output_result"), default=True, colors=c,
            on_changed=self._emit_sub(cn, "output_result")), "settings.track.output_result")

        # ── 进入战斗检测子区（track_mode=battlestart 时显示）──
        self._track_bs_section = QWidget()
        bs_layout = QVBoxLayout(self._track_bs_section)
        bs_layout.setContentsMargins(0, 0, 0, 0)
        bs_layout.setSpacing(Space.M)

        bs_title = self._make_section_title(tr("settings.track.battle_start.title"))
        bs_layout.addWidget(bs_title)
        self._tr_labels.append((bs_title.setText, "settings.track.battle_start.title"))

        # 行注册闭包（控件加入 battle_start 子区布局）
        add_bs = self._make_row_registrar(bs_layout, cn)

        add_bs("battle_start.time_limit", build_int_row(
            tr("settings.track.battle_start.time_limit"), default=30, minimum=1, maximum=600,
            colors=c,
            on_changed=self._emit_sub(cn, "battle_start.time_limit")),
            "settings.track.battle_start.time_limit")
        add_bs("battle_start.min_consecutive_frames", build_int_row(
            tr("settings.track.battle_start.min_consecutive_frames"), default=2, minimum=1, maximum=10,
            colors=c,
            on_changed=self._emit_sub(cn, "battle_start.min_consecutive_frames")),
            "settings.track.battle_start.min_consecutive_frames")
        add_bs("battle_start.debug_mode", build_switch_row(
            tr("settings.track.battle_start.debug_mode"), default=True, colors=c,
            on_changed=self._emit_sub(cn, "battle_start.debug_mode")),
            "settings.track.battle_start.debug_mode")

        layout.addWidget(self._track_bs_section)

        card.add_layout(layout)
        return card

    def _build_formation_card(self) -> MaterialCard:
        """Formation 配置卡片：编队文本显示选项（3 个布尔字段）"""
        card = MaterialCard(tr("settings.formation.title"))
        self._tr_labels.append((card.set_title, "settings.formation.title"))
        layout = QVBoxLayout()
        layout.setSpacing(Space.M)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        desc = QLabel(tr("settings.formation.desc"))
        desc.setFont(self._typo.body_medium)
        desc.setWordWrap(True)
        self._dim_labels.append(desc)
        layout.addWidget(desc)
        self._tr_labels.append((desc.setText, "settings.formation.desc"))

        cn = "formation"
        c = self._colors
        for field, label_key in [
            ("show_skill", "settings.formation.show_skill"),
            ("show_requirements", "settings.formation.show_requirements"),
            ("show_module", "settings.formation.show_module"),
        ]:
            row = build_switch_row(
                tr(label_key), default=False, colors=c,
                on_changed=self._emit_sub(cn, field))
            layout.addWidget(row.widget)
            self._register_sub_row(cn, field, row)
            self._tr_labels.append((row.set_label, label_key))

        card.add_layout(layout)
        return card

    def _build_actions_card(self) -> MaterialCard:
        """Actions 配置卡片：操作指令文本显示选项（8 个布尔字段）"""
        card = MaterialCard(tr("settings.actions.title"))
        self._tr_labels.append((card.set_title, "settings.actions.title"))
        layout = QVBoxLayout()
        layout.setSpacing(Space.M)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        desc = QLabel(tr("settings.actions.desc"))
        desc.setFont(self._typo.body_medium)
        desc.setWordWrap(True)
        self._dim_labels.append(desc)
        layout.addWidget(desc)
        self._tr_labels.append((desc.setText, "settings.actions.desc"))

        cn = "actions"
        c = self._colors
        for field, label_key, default in [
            ("show_skill", "settings.actions.show_skill", False),
            ("show_requirements", "settings.actions.show_requirements", False),
            ("show_module", "settings.actions.show_module", False),
            ("show_location", "settings.actions.show_location", False),
            ("show_direction", "settings.actions.show_direction", True),
            ("show_delay", "settings.actions.show_delay", False),
            ("show_conditions", "settings.actions.show_conditions", False),
            ("show_doc", "settings.actions.show_doc", False),
        ]:
            row = build_switch_row(
                tr(label_key), default=default, colors=c,
                on_changed=self._emit_sub(cn, field))
            layout.addWidget(row.widget)
            self._register_sub_row(cn, field, row)
            self._tr_labels.append((row.set_label, label_key))

        card.add_layout(layout)
        return card

    def _build_compose_main_card(self, style: str) -> MaterialCard:
        """Video Compose 主卡片：基础字段（始终可见）
        + 高级字段（字体/阴影/颜色等，开关打开后可见）。"""
        card = MaterialCard(tr("settings.compose.title", style=style))
        # 带 {style} 占位符：用 key=None + lambda 注册，_retranslate 时调用 setter()
        self._tr_labels.append((
            lambda s=style: card.set_title(tr("settings.compose.title", style=s)), None))
        layout = QVBoxLayout()
        layout.setSpacing(Space.M)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        desc = QLabel(tr("settings.compose.desc", style=style))
        desc.setFont(self._typo.body_medium)
        desc.setWordWrap(True)
        self._dim_labels.append(desc)
        layout.addWidget(desc)
        self._tr_labels.append((
            lambda s=style, w=desc: w.setText(tr("settings.compose.desc", style=s)), None))

        cn = style
        c = self._colors
        # 行注册闭包（控件加入 compose 卡片主布局）
        add = self._make_row_registrar(layout, cn)

        # 顶层字段
        add("output_width", build_int_row(
            tr("settings.compose.output_width"), default=1920, minimum=480, maximum=3840, colors=c,
            on_changed=self._emit_sub(cn, "output_width")), "settings.compose.output_width")
        add("output_height", build_int_row(
            tr("settings.compose.output_height"), default=1080, minimum=270, maximum=2160, colors=c,
            on_changed=self._emit_sub(cn, "output_height")), "settings.compose.output_height")

        if style == "style1":
            add("video_scale", build_float_row(
                tr("settings.compose.video_scale"), default=0.85, minimum=0.1, maximum=2.0,
                step=0.01, decimals=2, colors=c,
                on_changed=self._emit_sub(cn, "video_scale")), "settings.compose.video_scale")
            add("video_x", build_int_row(
                tr("settings.compose.video_x"), default=272, minimum=-1920, maximum=3840, colors=c,
                on_changed=self._emit_sub(cn, "video_x")), "settings.compose.video_x")
            add("video_y", build_int_row(
                tr("settings.compose.video_y"), default=47, minimum=-1080, maximum=2160, colors=c,
                on_changed=self._emit_sub(cn, "video_y")), "settings.compose.video_y")

        add("video_quality", build_combo_row(
            tr("settings.compose.video_quality"), items=["low", "middle", "high"], default="middle", colors=c,
            on_changed=self._emit_sub(cn, "video_quality")), "settings.compose.video_quality")

        # 文字叠加（text_overlay）子区域标题
        overlay_title = self._make_section_title(tr("settings.compose.overlay_title"))
        layout.addWidget(overlay_title)
        self._tr_labels.append((overlay_title.setText, "settings.compose.overlay_title"))

        tp = "text_overlay"
        add(f"{tp}.enabled", build_switch_row(
            tr("settings.compose.overlay_enabled"), default=True, colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.enabled")), "settings.compose.overlay_enabled")
        add(f"{tp}.font_size", build_int_row(
            tr("settings.compose.font_size"), default=25 if style == "style1" else 45,
            minimum=8, maximum=300, colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.font_size")), "settings.compose.font_size")
        add(f"{tp}.shadow_enabled", build_switch_row(
            tr("settings.compose.shadow_enabled"), default=True, colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.shadow_enabled")), "settings.compose.shadow_enabled")

        if style == "style1":
            add(f"{tp}.text_x", build_int_row(
                tr("settings.compose.text_x"), default=50, minimum=-1920, maximum=3840, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.text_x")), "settings.compose.text_x")
            add(f"{tp}.text_y", build_int_row(
                tr("settings.compose.text_y"), default=240, minimum=-1080, maximum=2160, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.text_y")), "settings.compose.text_y")
            add(f"{tp}.subtitle_auto_fit", build_switch_row(
                tr("settings.compose.subtitle_auto_fit"), default=False, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.subtitle_auto_fit")), "settings.compose.subtitle_auto_fit")

        # 逐操作显示（map_overlay）子区域标题（仅 style1：地图操作序号 + 面板当前操作高亮）
        # 主区仅保留总开关；数字尺寸/字号/颜色与面板高亮等细项已迁至下方高级设置容器。
        if style == "style1":
            map_title = self._make_section_title(tr("settings.compose.map_overlay_title"))
            layout.addWidget(map_title)
            self._tr_labels.append((map_title.setText, "settings.compose.map_overlay_title"))

            mp = "map_overlay"
            add(f"{mp}.enabled", build_switch_row(
                tr("settings.compose.map_overlay_enabled"), default=False, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.enabled")), "settings.compose.map_overlay_enabled")

        card.add_layout(layout)

        # ── 高级字段容器（开关关闭时隐藏，不占用布局空间）──
        adv_container = QWidget()
        adv_container.setObjectName("transparentPane")
        adv_layout = QVBoxLayout(adv_container)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(Space.M)

        # 行注册闭包（控件加入高级字段容器布局）
        add_adv = self._make_row_registrar(adv_layout, cn)

        # 高级字段按所属主分区加小标题：避免字体/阴影字段直接跟在
        # "逐操作显示"开关后面而看不出归属
        text_adv_title = self._make_section_title(
            tr("settings.compose.overlay_advanced_title")
        )
        adv_layout.addWidget(text_adv_title)
        self._tr_labels.append(
            (text_adv_title.setText, "settings.compose.overlay_advanced_title")
        )

        add_adv(f"{tp}.font", build_string_row(
            tr("settings.compose.font"), default="SOURCEHANSANSCN-HEAVY.OTF", colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.font")), "settings.compose.font")
        add_adv(f"{tp}.font_dir", build_path_row(
            tr("settings.compose.font_dir"), mode=FileSelector.MODE_DIRECTORY, colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.font_dir")), "settings.compose.font_dir")
        add_adv(f"{tp}.font_scale", build_float_row(
            tr("settings.compose.font_scale"), default=1.0, minimum=0.1, maximum=5.0,
            step=0.1, decimals=2, colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.font_scale")), "settings.compose.font_scale")
        add_adv(f"{tp}.fade_duration", build_float_row(
            tr("settings.compose.fade_duration"), default=0.5, minimum=0.0, maximum=5.0,
            step=0.1, decimals=2, colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.fade_duration")), "settings.compose.fade_duration")
        add_adv(f"{tp}.shadow_offset_x", build_int_row(
            tr("settings.compose.shadow_offset_x"), default=2, minimum=-50, maximum=50, colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.shadow_offset_x")), "settings.compose.shadow_offset_x")
        add_adv(f"{tp}.shadow_offset_y", build_int_row(
            tr("settings.compose.shadow_offset_y"), default=2, minimum=-50, maximum=50, colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.shadow_offset_y")), "settings.compose.shadow_offset_y")
        add_adv(f"{tp}.shadow_blur", build_int_row(
            tr("settings.compose.shadow_blur"), default=4, minimum=0, maximum=50, colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.shadow_blur")), "settings.compose.shadow_blur")
        add_adv(f"{tp}.shadow_color", build_color_row(
            tr("settings.compose.shadow_color"), default="#000000", colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.shadow_color")), "settings.compose.shadow_color")
        add_adv(f"{tp}.text_color", build_color_row(
            tr("settings.compose.text_color"), default="#FFFFFF", colors=c,
            on_changed=self._emit_sub(cn, f"{tp}.text_color")), "settings.compose.text_color")

        if style == "style1":
            add_adv(f"{tp}.auto_fit_min_font_size", build_int_row(
                tr("settings.compose.auto_fit_min_font_size"), default=10, minimum=1, maximum=100, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.auto_fit_min_font_size")), "settings.compose.auto_fit_min_font_size")
            add_adv(f"{tp}.auto_fit_max_font_size", build_int_row(
                tr("settings.compose.auto_fit_max_font_size"), default=200, minimum=10, maximum=500, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.auto_fit_max_font_size")), "settings.compose.auto_fit_max_font_size")
            add_adv(f"{tp}.auto_fit_available_width", build_nullable_int_row(
                tr("settings.compose.auto_fit_available_width"), default=None,
                minimum=1, maximum=3840, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.auto_fit_available_width")), "settings.compose.auto_fit_available_width")
            # Actions 文本显示范围限定（null=不限）：文本块左上角固定为
            # (text_x, text_y)，右/下边界围成可显示区域——右边界控制换行，
            # 下边界控制截断（右侧不遮挡视频画面、下侧不遮挡 Tips）
            add_adv(f"{tp}.max_text_right", build_nullable_int_row(
                tr("settings.compose.max_text_right"), default=272,
                minimum=0, maximum=3840, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.max_text_right")), "settings.compose.max_text_right")
            add_adv(f"{tp}.max_text_bottom", build_nullable_int_row(
                tr("settings.compose.max_text_bottom"), default=865,
                minimum=0, maximum=2160, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.max_text_bottom")), "settings.compose.max_text_bottom")
        else:
            add_adv(f"{tp}.max_chars_per_line", build_int_row(
                tr("settings.compose.max_chars_per_line"), default=20, minimum=1, maximum=200, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.max_chars_per_line")), "settings.compose.max_chars_per_line")
            add_adv(f"{tp}.line_height", build_float_row(
                tr("settings.compose.line_height"), default=1.5, minimum=0.5, maximum=5.0,
                step=0.1, decimals=2, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.line_height")), "settings.compose.line_height")
            add_adv(f"{tp}.bottom_margin", build_int_row(
                tr("settings.compose.bottom_margin"), default=60, minimum=0, maximum=500, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.bottom_margin")), "settings.compose.bottom_margin")

        if style == "style1":
            map_adv_title = self._make_section_title(
                tr("settings.compose.map_overlay_advanced_title")
            )
            adv_layout.addWidget(map_adv_title)
            self._tr_labels.append(
                (map_adv_title.setText, "settings.compose.map_overlay_advanced_title")
            )

            # map_overlay 高级字段：数据驱动注册，字段清单与构建参数
            # 与原先的重复 add_adv 行逐一对应（行构建函数与键名完全一致）
            mp_fields: list[tuple[str, Callable[..., FieldRow], dict[str, Any]]] = [
                ("number_size_mode", build_combo_row, dict(
                    label=tr("settings.compose.map_overlay_number_size_mode"),
                    items=["approximate", "precise"], default="approximate")),
                ("resolution", build_string_row, dict(
                    label=tr("settings.compose.map_overlay_resolution"),
                    default="1280x720")),
                ("number_font_ratio", build_float_row, dict(
                    label=tr("settings.compose.map_overlay_number_font_ratio"),
                    default=0.5, minimum=0.1, maximum=1.0, step=0.05, decimals=2)),
                ("number_color", build_color_row, dict(
                    label=tr("settings.compose.map_overlay_number_color"),
                    default="#FFD700")),
                ("panel_highlight_enabled", build_switch_row, dict(
                    label=tr("settings.compose.map_overlay_panel_highlight_enabled"),
                    default=True)),
                ("panel_highlight_color", build_color_row, dict(
                    label=tr("settings.compose.map_overlay_panel_highlight_color"),
                    default="#FFD700")),
                ("number_shadow_enabled", build_switch_row, dict(
                    label=tr("settings.compose.map_overlay_number_shadow_enabled"),
                    default=True)),
                ("number_shadow_offset_x", build_int_row, dict(
                    label=tr("settings.compose.map_overlay_number_shadow_offset_x"),
                    default=2, minimum=-50, maximum=50)),
                ("number_shadow_offset_y", build_int_row, dict(
                    label=tr("settings.compose.map_overlay_number_shadow_offset_y"),
                    default=2, minimum=-50, maximum=50)),
                ("number_shadow_blur", build_int_row, dict(
                    label=tr("settings.compose.map_overlay_number_shadow_blur"),
                    default=4, minimum=0, maximum=50)),
                ("number_shadow_color", build_color_row, dict(
                    label=tr("settings.compose.map_overlay_number_shadow_color"),
                    default="#000000")),
                ("number_bg_enabled", build_switch_row, dict(
                    label=tr("settings.compose.map_overlay_number_bg_enabled"),
                    default=True)),
                ("number_bg_color", build_color_row, dict(
                    label=tr("settings.compose.map_overlay_number_bg_color"),
                    default="#000000")),
                ("number_bg_alpha", build_float_row, dict(
                    label=tr("settings.compose.map_overlay_number_bg_alpha"),
                    default=0.45, minimum=0.0, maximum=1.0, step=0.05, decimals=2)),
                ("number_padding", build_int_row, dict(
                    label=tr("settings.compose.map_overlay_number_padding"),
                    default=2, minimum=0, maximum=50)),
                ("number_min_font_size", build_int_row, dict(
                    label=tr("settings.compose.map_overlay_number_min_font_size"),
                    default=8, minimum=1, maximum=200)),
                ("panel_highlight_background", build_color_row, dict(
                    label=tr("settings.compose.map_overlay_panel_highlight_background"),
                    default="#000000")),
                ("panel_highlight_bg_alpha", build_float_row, dict(
                    label=tr("settings.compose.map_overlay_panel_highlight_bg_alpha"),
                    default=0.55, minimum=0.0, maximum=1.0, step=0.05, decimals=2)),
                ("panel_fade_duration", build_float_row, dict(
                    label=tr("settings.compose.map_overlay_panel_fade_duration"),
                    default=0.3, minimum=0.0, maximum=5.0, step=0.1, decimals=2)),
            ]
            for name, builder, kwargs in mp_fields:
                field_path = f"{mp}.{name}"
                kwargs["colors"] = c
                kwargs["on_changed"] = self._emit_sub(cn, field_path)
                add_adv(field_path, builder(**kwargs),
                        f"settings.compose.map_overlay_{name}")

        adv_container.setVisible(False)
        card.add_widget(adv_container)
        if style == "style1":
            self._compose_style1_advanced_container = adv_container
        else:
            self._compose_style2_advanced_container = adv_container
        return card

    def _card_host(self, card: QWidget) -> QWidget:
        """把卡片包进"卡片 + 底部伸缩"的宿主，按内容宽度填满并顶部对齐

        宿主垂直方向 Fixed：行高取卡片自身 sizeHint，避免 QGridLayout
        把多余高度分给某一行而在卡片下方形成异常空白。
        """
        host = self._card_hosts.get(id(card))
        if host is None:
            host = QWidget(self._cards_container)
            host.setObjectName("transparentPane")
            # 垂直 Fixed：行高取卡片自身的 sizeHint，避免 QGridLayout 把
            # 多出来的高度分配给某一行，在短卡片下方形成异常空白
            host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            host_layout = QVBoxLayout(host)
            host_layout.setContentsMargins(0, 0, 0, 0)
            host_layout.setSpacing(0)
            host_layout.addWidget(card)
            host_layout.addStretch(1)
            self._card_hosts[id(card)] = host
        return host

    def _apply_grid_layout(self) -> None:
        """设置页卡片固定单列

        设置项是表单而不是仪表盘：双列会把字段控件压到约 194dp，长文件名
        与路径被截断；同一行两张卡的高度差异还会让下一张通栏卡从较高卡片
        底部开始，看起来"卡片不对齐"。单列后所有卡片等宽，控件宽度足够，
        卡片之间只按顺序排列。
        """
        for i in reversed(range(self._cards_grid.count())):
            item = self._cards_grid.itemAt(i)
            if item and item.widget():
                self._cards_grid.removeWidget(item.widget())

        self._cards_grid.setColumnStretch(0, 1)
        r = 0
        for card in (
            self._language_card,
            self._appearance_card,
            self._advanced_card,
            self._ffmpeg_card,
            self._config_card,
            self._compose_style1_main_card,
            self._compose_style2_main_card,
            self._advanced_toggle_card,
            self._collapsible_content,
        ):
            if card is None:
                continue
            self._cards_grid.addWidget(
                self._card_host(card), r, 0, Qt.AlignmentFlag.AlignTop
            )
            r += 1

    def _reflow_checkbox_grid(self, two_col: bool) -> None:
        """根据可用宽度决定复选框网格是 1 列还是 2 列（统一列宽）"""
        for i in reversed(range(self._checkbox_grid.count())):
            item = self._checkbox_grid.itemAt(i)
            if item and item.widget():
                self._checkbox_grid.removeWidget(item.widget())
        cols = 2 if two_col else 1
        max_w = max(
            (cb.sizeHint().width() for cb in self._config_checkboxes.values()),
            default=0,
        )
        for i, cb in enumerate(self._config_checkboxes.values()):
            self._checkbox_grid.addWidget(
                cb, i // cols, i % cols,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        for column in range(self._checkbox_grid.columnCount()):
            self._checkbox_grid.setColumnMinimumWidth(column, 0)
            self._checkbox_grid.setColumnStretch(column, 0)
        for column in range(cols):
            self._checkbox_grid.setColumnMinimumWidth(column, max_w)
        self._checkbox_grid.setColumnStretch(cols, 1)

    def _reflow_button_rows(self, vertical: bool) -> None:
        """窄屏下将按钮行改为垂直堆叠，避免按钮被压缩到不可点"""
        for layout, widgets in (
            (self._sel_buttons_layout,
             (self._select_all_btn, self._clear_btn)),
            (self._action_buttons_layout,
             (self._generate_btn, self._config_status)),
        ):
            # 清空布局中所有 item（含 widget 和 spacer/stretch），
            # 避免多次切换后 stretch 累积导致布局异常
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
            is_sel_row = widgets == (self._select_all_btn, self._clear_btn)
            if vertical:
                layout.setDirection(QBoxLayout.Direction.TopToBottom)
                for w in widgets:
                    if is_sel_row:
                        # 全选/清空按钮靠右对齐
                        layout.addWidget(w, alignment=Qt.AlignmentFlag.AlignRight)
                    elif w is self._generate_btn:
                        layout.addWidget(w, alignment=Qt.AlignmentFlag.AlignRight)
                    else:
                        layout.addWidget(w)
            else:
                layout.setDirection(QBoxLayout.Direction.LeftToRight)
                if is_sel_row:
                    # stretch 在前，将全选/清空按钮推到右侧
                    layout.addStretch()
                    layout.addWidget(self._select_all_btn)
                    layout.addWidget(self._clear_btn)
                else:
                    # 状态文字占左侧剩余空间，主操作右对齐
                    layout.addWidget(self._config_status, 1)
                    layout.addWidget(self._generate_btn)

    # ── 事件处理 ──────────────────────────────────────────

    def _on_language_changed(self, index: int) -> None:
        """语言下拉框变更：发射 language_change_requested 信号供 MainWindow 处理"""
        code = self._lang_combo.itemData(index)
        if code:
            self.language_change_requested.emit(code)

    def set_language(self, lang: str) -> None:
        """程序化设置下拉框选中项（阻塞信号，避免触发 language_change_requested 回写）

        供 MainWindow 在初始化或配置重置后同步下拉框状态。
        """
        idx = self._lang_combo.findData(lang)
        if idx >= 0:
            self._lang_combo.blockSignals(True)
            self._lang_combo.setCurrentIndex(idx)
            self._lang_combo.blockSignals(False)

    def _retranslate(self) -> None:
        """语言切换时刷新所有已注册的静态文本"""
        for setter, key in self._tr_labels:
            if key is None:
                setter()
            else:
                setter(tr(key))
        for cb, title_key, filename in self._checkbox_specs:
            cb.setText(tr(title_key))
            cb.setToolTip(filename)

    def _on_theme_toggled(self, dark: bool) -> None:
        self._is_dark = dark
        self.theme_change_requested.emit(dark)

    def _on_advanced_toggled(self, enabled: bool) -> None:
        # 开关切换时立即显示/隐藏所有高级设置容器：
        # 1. 全局设置卡片内的高级字段（日志/子配置路径）
        # 2. VideoCompose style1/style2 卡片内的高级字段（字体/阴影/颜色）
        # 3. 独立的 Track/Formation/Actions/Performance 卡片
        self._global_advanced_container.setVisible(enabled)
        self._compose_style1_advanced_container.setVisible(enabled)
        self._compose_style2_advanced_container.setVisible(enabled)
        self._collapsible_content.setVisible(enabled)
        self.advanced_expanded_changed.emit(enabled)

    def set_advanced_expanded(self, expanded: bool) -> None:
        """程序化设置开关状态（阻塞信号，避免触发 advanced_expanded_changed 回写）"""
        self._advanced_switch.blockSignals(True)
        try:
            self._advanced_switch.set_checked(expanded)
        finally:
            self._advanced_switch.blockSignals(False)
        # set_checked 不触发 toggled，需手动同步所有高级容器显隐
        self._global_advanced_container.setVisible(expanded)
        self._compose_style1_advanced_container.setVisible(expanded)
        self._compose_style2_advanced_container.setVisible(expanded)
        self._collapsible_content.setVisible(expanded)

    def _on_multithreading_toggled(self, enabled: bool) -> None:
        # 开关切换时同步并发数输入框的可用态：关闭时置灰
        self._conc_spin.setEnabled(enabled)
        self.multithreading_changed.emit(enabled)

    def _on_max_concurrent_changed(self, value: int) -> None:
        self.max_concurrent_changed.emit(value)

    def _on_copilot_backend_changed(self, backend: str) -> None:
        """Copilot 后端切换：转发信号并同步 MAA 路径行显隐（仅 maa 后端显示）"""
        self.copilot_backend_changed.emit(backend)
        self._maa_row.container.setVisible(backend == "maa")

    def _on_ffmpeg_custom_toggled(self, enabled: bool) -> None:
        # 开关切换时同步路径选择器可用态
        if getattr(self, "_ffmpeg_selector", None) is not None:
            self._ffmpeg_selector.setEnabled(enabled)
        self.ffmpeg_custom_changed.emit(enabled)

    def _on_ffmpeg_path_changed(self, path: str) -> None:
        self.ffmpeg_path_changed.emit(path)

    def _on_select_all(self) -> None:
        for cb in self._config_checkboxes.values():
            cb.setChecked(True)

    def _on_clear_all(self) -> None:
        for cb in self._config_checkboxes.values():
            cb.setChecked(False)

    def _on_generate(self) -> None:
        selected = [k for k, cb in self._config_checkboxes.items() if cb.isChecked()]
        if not selected:
            self._set_status(tr("settings.config.status_none_selected"), error=True)
            return

        generated: list[str] = []
        failed: list[str] = []
        for key in selected:
            try:
                # _init_config 仅对未知模块抛 ValueError；此处 key 均来自
                # CONFIG_TYPES，合法。返回值是成功生成的文件路径列表；
                # 空列表表示导入失败被跳过。
                result = _init_config(key)
                if result:
                    generated.append(key)
                else:
                    failed.append(tr("settings.config.load_failed", key=key))
            except ValueError:
                failed.append(key)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{key} ({exc})")

        if generated and not failed:
            self._set_status(
                tr("settings.config.status_generated", n=len(generated)), error=False
            )
            # 通知 MainWindow 重新加载磁盘配置并刷新 UI，避免 closeEvent
            # 中 save_all() 将重置前的旧值写回磁盘（撤销重置）。
            self.config_reset.emit(generated)
        elif generated and failed:
            self._set_status(
                tr("settings.config.status_partial",
                   generated=len(generated), failed=', '.join(failed)),
                error=True
            )
            # 部分成功：对已成功生成的配置同样需要刷新内存状态
            self.config_reset.emit(generated)
        else:
            self._set_status(
                tr("settings.config.status_all_failed", failed=', '.join(failed)),
                error=True
            )

    def _set_status(self, text: str, error: bool = False) -> None:
        self._status_is_error = error
        color = self._colors.error if error else self._colors.on_surface_variant
        self._config_status.setText(text)
        set_text_color(self._config_status, color)

    # ── 主题与状态同步 ────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        """主题切换时刷新页面所有颜色相关样式"""
        self._colors = colors
        self._theme_switch.set_colors(colors)
        self._dynamic_switch.set_colors(colors)
        self._seed_swatch.set_colors(colors)
        self._advanced_switch.set_colors(colors)
        self._mt_switch.set_colors(colors)
        if getattr(self, "_ffmpeg_switch", None) is not None:
            self._ffmpeg_switch.set_colors(colors)
        # 刷新所有子配置 FieldRow 的颜色
        for row in self._sub_field_rows.values():
            row.set_colors(colors)
        for row in self._pipeline_field_rows.values():
            row.set_colors(colors)
        self._apply_colors()
        # 状态文本颜色随主题刷新
        if self._config_status.text():
            color = self._colors.error if self._status_is_error else self._colors.on_surface_variant
            set_text_color(self._config_status, color)

    @property
    def colors(self) -> MaterialColors:
        """当前主题颜色（只读访问，修复 M12：避免外部直接访问 _colors 私有属性）"""
        return self._colors

    def set_dark(self, dark: bool) -> None:
        """同步开关状态（不发射信号，避免回环）"""
        self._is_dark = dark
        self._theme_switch.blockSignals(True)
        self._theme_switch.set_checked(dark)
        self._theme_switch.blockSignals(False)

    # ── 动态色彩（Material You）──────────────────────────

    def is_dynamic_color(self) -> bool:
        """当前动态色彩开关状态"""
        return self._is_dynamic

    def set_dynamic_color(self, enabled: bool) -> None:
        """同步动态色彩开关（不发射信号，避免回写配置）"""
        self._is_dynamic = bool(enabled)
        self._dynamic_switch.blockSignals(True)
        self._dynamic_switch.set_checked(bool(enabled))
        self._dynamic_switch.blockSignals(False)
        # 动态色彩关闭时种子色不参与推导，置灰但保留用户选择
        self._seed_swatch.setEnabled(bool(enabled))
        self._seed_value.setEnabled(bool(enabled))

    def seed_color(self) -> str:
        """当前种子色"""
        return self._seed_color

    def set_seed_color(self, color: str) -> None:
        """同步种子色（非法值忽略）"""
        try:
            normalized = normalize_hex(color)
        except ValueError:
            return
        self._seed_color = normalized
        self._seed_value.setText(normalized)
        self._seed_swatch.set_color(normalized)

    def _on_dynamic_color_toggled(self, enabled: bool) -> None:
        self._is_dynamic = enabled
        self._seed_swatch.setEnabled(enabled)
        self._seed_value.setEnabled(enabled)
        self.dynamic_color_changed.emit(enabled)

    def _on_pick_seed_color(self) -> None:
        dialog = ColorPickerDialog(
            initial=self._seed_color, colors=self._colors, parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            text = dialog.get_color()
            if text:
                self.set_seed_color(text)
                self.seed_color_changed.emit(self._seed_color)

    # ── 高级配置控件公开访问 ────────────────────────────────

    def set_maa_path(self, path: str) -> None:
        """设置 MAA 路径（阻塞信号，避免触发 maa_path_changed 回写）"""
        self._maa_selector.set_path(path, block_signal=True)

    def set_output_dir(self, path: str) -> None:
        """设置 Output 路径（阻塞信号，避免触发 output_dir_changed 回写）"""
        self._output_selector.set_path(path, block_signal=True)

    def set_log_level(self, level: str) -> None:
        """设置日志级别（阻塞信号，避免触发 log_level_changed 回写）"""
        self._log_level_combo.blockSignals(True)
        try:
            index = self._log_level_combo.findText(level)
            if index >= 0:
                self._log_level_combo.setCurrentIndex(index)
        finally:
            self._log_level_combo.blockSignals(False)

    def set_advanced_enabled(self, enabled: bool) -> None:
        """启用/禁用所有高级配置控件（MAA/Output/Log level + 新增字段）"""
        self._maa_selector.setEnabled(enabled)
        self._output_selector.setEnabled(enabled)
        self._log_level_combo.setEnabled(enabled)
        for row in self._pipeline_field_rows.values():
            row.set_enabled(enabled)

    # ── 新增 pipeline.json 字段公开访问 ────────────────────

    def set_log_to_file(self, enabled: bool) -> None:
        row = self._pipeline_field_rows.get("log_to_file")
        if row:
            row.set_value(bool(enabled), block_signal=True)

    def set_log_max_bytes(self, value: int) -> None:
        row = self._pipeline_field_rows.get("log_max_bytes")
        if row:
            row.set_value(int(value), block_signal=True)

    def set_log_backup_count(self, value: int) -> None:
        row = self._pipeline_field_rows.get("log_backup_count")
        if row:
            row.set_value(int(value), block_signal=True)

    def set_formation_path(self, path: str) -> None:
        row = self._pipeline_field_rows.get("formation")
        if row:
            row.set_value(path or "", block_signal=True)

    def set_actions_path(self, path: str) -> None:
        row = self._pipeline_field_rows.get("actions")
        if row:
            row.set_value(path or "", block_signal=True)

    def set_track_path(self, path: str) -> None:
        row = self._pipeline_field_rows.get("track")
        if row:
            row.set_value(path or "", block_signal=True)

    # ── Pipeline 配置控件公开访问（Copilot 后端 + recognition 参数） ──

    def set_copilot_backend(self, backend: str) -> None:
        row = self._pipeline_field_rows.get("copilot_backend")
        if row:
            row.set_value(backend, block_signal=True)
        # 同步 MAA 路径行显隐（仅 maa 后端显示）
        self._maa_row.container.setVisible(backend == "maa")

    def set_copilot_timeout(self, value: int) -> None:
        row = self._pipeline_field_rows.get("copilot_timeout_seconds")
        if row:
            row.set_value(int(value), block_signal=True)

    def set_copilot_max_retries(self, value: int) -> None:
        row = self._pipeline_field_rows.get("copilot_max_retries")
        if row:
            row.set_value(int(value), block_signal=True)

    def set_ocr_source(self, value: str) -> None:
        row = self._pipeline_field_rows.get("ocr_source")
        if row:
            row.set_value(value, block_signal=True)

    def set_resolution(self, value: str) -> None:
        row = self._pipeline_field_rows.get("resolution")
        if row:
            row.set_value(value or "", block_signal=True)

    def set_stage_override(self, value: str) -> None:
        row = self._pipeline_field_rows.get("stage_override")
        if row:
            row.set_value(value or "", block_signal=True)

    def set_with_video_time(self, enabled: bool) -> None:
        row = self._pipeline_field_rows.get("with_video_time")
        if row:
            row.set_value(bool(enabled), block_signal=True)

    def set_resource_dir(self, path: str) -> None:
        row = self._pipeline_field_rows.get("resource_dir")
        if row:
            row.set_value(path or "", block_signal=True)

    # ── 子配置控件公开访问 ────────────────────────────────

    def load_sub_config_values(self, config_proxy: Any) -> None:
        """从 ConfigProxy 加载所有子配置值到 UI 控件（阻塞信号避免回写）"""
        for (config_name, field_path), row in self._sub_field_rows.items():
            value = config_proxy.get_sub(config_name, field_path)
            row.set_value(value, block_signal=True)
        # 同步识别模式相关的子区显隐
        mode = config_proxy.get_sub("track", "track_mode")
        section = getattr(self, "_track_bs_section", None)
        if section is not None:
            section.setVisible(mode == "battlestart")

    def set_sub_config_enabled(self, enabled: bool) -> None:
        """启用/禁用所有子配置控件（流水线运行期间调用）"""
        for row in self._sub_field_rows.values():
            row.set_enabled(enabled)

    # ── 性能配置控件公开访问 ────────────────────────────────

    def set_multithreading(self, enabled: bool) -> None:
        """设置多线程开关状态（阻塞信号，避免触发 multithreading_changed 回写）

        同步联动并发数输入框的可用态，与 _on_multithreading_toggled 行为一致。
        """
        self._mt_switch.blockSignals(True)
        try:
            self._mt_switch.set_checked(bool(enabled))
        finally:
            self._mt_switch.blockSignals(False)
        # set_checked 不触发 toggled，需手动同步输入框可用态
        self._conc_spin.setEnabled(bool(enabled))

    def set_max_concurrent(self, value: int) -> None:
        """设置最大并发数（阻塞信号，避免触发 max_concurrent_changed 回写）"""
        self._conc_spin.blockSignals(True)
        try:
            self._conc_spin.setValue(int(value))
        finally:
            self._conc_spin.blockSignals(False)

    def set_performance_enabled(self, enabled: bool) -> None:
        """启用/禁用性能配置控件（多线程开关/最大并发数）

        流水线运行期间调用以禁止修改并发参数（运行中改变不会影响已派发的批次）。
        """
        self._mt_switch.setEnabled(enabled)
        # 并发数输入框需同时受多线程开关状态约束：仅当开关启用且非运行态时可编辑
        self._conc_spin.setEnabled(enabled and self._mt_switch.is_checked())

    # ── FFmpeg 配置控件公开访问 ──────────────────────────

    def set_ffmpeg_custom(self, enabled: bool) -> None:
        """设置 FFmpeg 自定义开关状态（阻塞信号，避免触发回写）"""
        if getattr(self, "_ffmpeg_switch", None) is None:
            return  # 非 Windows 无此控件
        self._ffmpeg_switch.blockSignals(True)
        try:
            self._ffmpeg_switch.set_checked(bool(enabled))
        finally:
            self._ffmpeg_switch.blockSignals(False)
        # set_checked 不触发 toggled，需手动同步路径选择器可用态
        if getattr(self, "_ffmpeg_selector", None) is not None:
            self._ffmpeg_selector.setEnabled(bool(enabled))

    def set_ffmpeg_path(self, path: str) -> None:
        """设置 FFmpeg 路径（阻塞信号，避免触发回写）"""
        if getattr(self, "_ffmpeg_selector", None) is None:
            return
        self._ffmpeg_selector.set_path(path, block_signal=True)

    def set_ffmpeg_enabled(self, enabled: bool) -> None:
        """启用/禁用 FFmpeg 配置控件（流水线运行期间调用）"""
        if getattr(self, "_ffmpeg_switch", None) is None:
            return
        self._ffmpeg_switch.setEnabled(enabled)
        if getattr(self, "_ffmpeg_selector", None) is not None:
            self._ffmpeg_selector.setEnabled(
                enabled and self._ffmpeg_switch.is_checked()
            )

    def _apply_colors(self) -> None:
        # 注意：不要在此调用 self.setStyleSheet()，否则会覆盖整棵 widget tree
        # 的全局 QSS，导致 MaterialCard（白底圆角）与 MaterialButton 失去样式。
        # 页面整体背景由 QPalette::Window 统一绘制；
        # 辅助文本颜色走 QPalette（逐只 setStyleSheet 是主题切换的卡顿源之一）
        dim = self._colors.on_surface_variant
        for w in self._dim_labels:
            set_text_color(w, dim)
        # 同步刷新"重置配置文件"卡片内的复选框配色：MaterialCheckBox 在
        # 初始化时使用默认浅色主题（indicator fill = surface = 白），若不在
        # 主题切换时显式调用 set_colors()，深色模式下 indicator 会保持白色
        # 矩形块，与深色背景形成刺眼对比。
        for cb in getattr(self, "_config_checkboxes", {}).values():
            cb.set_colors(self._colors)
        # 高级卡片内 MAA / Output 文件选择器：同步主题色到
        # 内联样式（输入框 + 浏览按钮），确保与主页 Video/Background 一致
        for selector in (getattr(self, "_maa_selector", None),
                         getattr(self, "_output_selector", None)):
            if selector is not None:
                selector.set_colors(self._colors)
        # FFmpeg 卡片内文件选择器：同步主题色
        if getattr(self, "_ffmpeg_selector", None) is not None:
            self._ffmpeg_selector.set_colors(self._colors)
        # 同步刷新卡片背景色：MaterialCard 使用 paintEvent 自绘圆角背景，
        # 卡片背景由 CardFrame 自订阅主题信号；按钮为自绘组件，同样自动跟随，
        # 因此这里不再枚举卡片与按钮（历史实现每次新增卡片都要往清单里加一行）

    # ── 响应式 ────────────────────────────────────────────

    def set_size_class(self, size_class: str) -> None:
        """按 MD3 窗口尺寸类别调整页边距、卡片列数与控件排布

        断点由 ``WindowSizeClass`` 统一提供（600 / 840），不再使用
        480 / 720 / 1000 三个页面私有魔数——否则窗口与页面各自判定，
        会出现"导航已收起、卡片还是双列"的错位。
        """
        if size_class == getattr(self, "_size_class", None):
            return
        self._size_class = size_class

        margin = Margin.page(size_class)
        root_layout = self.layout()
        if isinstance(root_layout, QVBoxLayout):
            root_layout.setContentsMargins(margin, margin, margin, margin)

        self._sync_checkbox_columns()
        self._reflow_button_rows(vertical=size_class == WindowSizeClass.COMPACT)

        header = getattr(self, "_header", None)
        if header is not None:
            header.set_size_class(size_class)

