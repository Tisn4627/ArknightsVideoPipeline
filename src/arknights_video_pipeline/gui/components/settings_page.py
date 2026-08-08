"""
gui.components.settings_page - 设置页面

页面布局严格参考 Home 选项卡：Hero 区域 + 卡片网格 + 底部信息区，
采用与 Home 一致的淡紫底色（``background``）+ 白色圆角卡片（``surface``）配色，
字体、间距、交互反馈均与 Home 保持一致。

功能模块：
1. 外观（Appearance）：浅色 / 深色主题切换，开关即时生效（实时预览）；
2. 配置文件（Configuration files）：按类型选择并生成默认配置文件，
   与 CLI ``--init-config`` 行为一致，支持"一键选择全部"与"取消全部选择"。
3. 高级（Advanced）：MAA 路径、Output 路径与日志级别的运行时配置，
   全部竖直排列；这三个控件由 MainWindow 共享读写，Home 选项卡不再持有。

页面通过信号与 MainWindow 解耦：
- ``theme_change_requested(bool)``：请求切换主题（True=深色）；
- ``home_requested()``：请求返回主页。
"""

from __future__ import annotations

import sys
from typing import Any, Callable, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QBoxLayout, QLabel,
    QComboBox, QSpinBox, QSizePolicy,
)

from arknights_video_pipeline.core.pipeline import _init_config
from arknights_video_pipeline.gui.components.file_selector import FileSelector
from arknights_video_pipeline.gui.components.material_checkbox import MaterialCheckBox
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import MaterialCard
from arknights_video_pipeline.gui.components.material_switch import MaterialSwitch
from arknights_video_pipeline.gui.components.settings_row_builders import (
    FieldRow,
    build_switch_row, build_int_row, build_float_row,
    build_combo_row, build_path_row, build_string_row,
    build_color_row, build_range_row, build_nullable_int_row,
)
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import (
    MaterialColors, MaterialTypography,
    filled_button_qss as _build_filled_button_qss,
    outlined_button_qss as _build_outlined_button_qss,
)


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
    maa_timeout_changed = pyqtSignal(int)
    maa_max_retries_changed = pyqtSignal(int)
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
        self._colors = colors or MaterialColors.light()
        self._is_dark = is_dark
        self._typo = MaterialTypography()
        self._status_is_error = False
        self._log_level_valid = True

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

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(32)
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
        self._collapsible_content.setStyleSheet("background: transparent; border: none;")
        collapsible_layout = QVBoxLayout(self._collapsible_content)
        collapsible_layout.setContentsMargins(0, 0, 0, 0)
        collapsible_layout.setSpacing(24)
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

        # 卡片网格：单列竖直堆叠
        self._cards_grid = QGridLayout()
        self._cards_grid.setSpacing(24)
        self._cards_grid.setColumnStretch(0, 1)
        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background: transparent; border: none;")
        self._cards_container.setLayout(self._cards_grid)
        root.addWidget(self._cards_container)
        # 始终可见卡片
        row = 0
        for card in (
            self._language_card,
            self._appearance_card,
            self._advanced_card, self._ffmpeg_card,
            self._compose_style1_main_card, self._compose_style2_main_card,
            self._config_card,
        ):
            if card is not None:
                self._cards_grid.addWidget(card, row, 0)
                row += 1
        # 高级开关卡片 + 内容容器（内容 setVisible 控制显隐）
        self._cards_grid.addWidget(self._advanced_toggle_card, row, 0)
        row += 1
        self._cards_grid.addWidget(self._collapsible_content, row, 0)

    def _build_hero(self) -> QWidget:
        """Hero 区域：大标题 + 描述（与 Home 一致；不放置按钮，遵循
        设计规范 Hero 区聚焦于内容引导）"""
        hero = QWidget()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 24, 0, 0)
        hero_layout.setSpacing(16)
        hero_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # MD3 Hero 标题：与 Home 一致使用 display_large + 48px 内联覆盖
        self._title_label = QLabel(tr("settings.hero_title"))
        self._title_label.setFont(self._typo.display_large)
        self._title_label.setStyleSheet(
            "border: none; background: transparent;"
            " font-size: 48px; font-weight: 600; line-height: 1.15;"
            " letter-spacing: -1.5px;"
        )
        self._title_label.setWordWrap(True)
        hero_layout.addWidget(self._title_label)
        self._tr_labels.append((self._title_label.setText, "settings.hero_title"))

        return hero

    def _build_language_card(self) -> MaterialCard:
        """语言切换卡片（置顶）：下拉选择界面语言，立即生效"""
        card = MaterialCard(tr("settings.language.title"))
        self._tr_labels.append((card.set_title, "settings.language.title"))

        row = QHBoxLayout()
        row.setSpacing(16)
        row.setContentsMargins(0, 4, 0, 4)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        text_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        lang_label = QLabel(tr("settings.language.desc"))
        lang_label.setFont(self._typo.body_medium)
        lang_label.setWordWrap(True)
        self._dim_labels.append(lang_label)
        text_box.addWidget(lang_label)
        self._tr_labels.append((lang_label.setText, "settings.language.desc"))
        row.addLayout(text_box, 1)

        self._lang_combo = QComboBox()
        for code, display_name in i18n().available_languages():
            self._lang_combo.addItem(display_name, code)
        # 应用与其他下拉框（Log level 等）一致的内联样式，
        # 主题切换时由 _apply_colors 刷新
        self._lang_combo.setStyleSheet(self._lang_combo_qss())
        # 同步当前语言到下拉框（阻塞信号避免触发 language_change_requested）
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        row.addWidget(self._lang_combo, 0, Qt.AlignmentFlag.AlignVCenter)

        card.add_layout(row)
        return card

    def _build_theme_card(self) -> MaterialCard:
        card = MaterialCard(tr("settings.appearance.title"))
        self._tr_labels.append((card.set_title, "settings.appearance.title"))
        # 让卡片内所有内容靠上对齐，避免外观标题与下方控件之间
        # 出现大片空白（双列网格中两卡片同高时尤为明显）。
        card._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.setContentsMargins(0, 4, 0, 4)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        text_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._theme_label = QLabel(tr("settings.appearance.label"))
        self._theme_label.setFont(self._typo.title_medium)
        self._theme_label.setStyleSheet("border: none; background: transparent;")
        text_box.addWidget(self._theme_label)
        self._tr_labels.append((self._theme_label.setText, "settings.appearance.label"))

        self._theme_desc = QLabel(tr("settings.appearance.desc"))
        self._theme_desc.setFont(self._typo.body_medium)
        self._theme_desc.setWordWrap(True)
        self._dim_labels.append(self._theme_desc)
        text_box.addWidget(self._theme_desc)
        self._tr_labels.append((self._theme_desc.setText, "settings.appearance.desc"))
        row.addLayout(text_box, 1)

        self._theme_switch = MaterialSwitch(checked=self._is_dark, colors=self._colors)
        self._theme_switch.toggled.connect(self._on_theme_toggled)
        row.addWidget(self._theme_switch, 0, Qt.AlignmentFlag.AlignVCenter)

        card.add_layout(row)
        return card

    def _build_config_card(self) -> MaterialCard:
        card = MaterialCard(tr("settings.config.title"))
        self._tr_labels.append((card.set_title, "settings.config.title"))
        layout = QVBoxLayout()
        layout.setSpacing(16)

        self._config_desc = QLabel(tr("settings.config.desc"))
        self._config_desc.setFont(self._typo.body_medium)
        self._config_desc.setWordWrap(True)
        self._dim_labels.append(self._config_desc)
        self._tr_labels.append((self._config_desc.setText, "settings.config.desc"))
        layout.addWidget(self._config_desc)

        # 复选框网格（容器，以便在窄屏下重新排列为单列）
        self._config_checkboxes: dict[str, MaterialCheckBox] = {}
        self._checkbox_grid = QGridLayout()
        self._checkbox_grid.setSpacing(12)
        for key, title_key, filename in self.CONFIG_TYPES:
            # 传入当前主题 colors，避免 MaterialCheckBox 默认使用浅色
            # MaterialColors.light() 导致首次进入深色模式时 indicator
            # 保持白色的问题
            cb = MaterialCheckBox(
                f"{tr(title_key)}  ·  {filename}", colors=self._colors
            )
            self._config_checkboxes[key] = cb
            self._checkbox_specs.append((cb, title_key, filename))
        self._reflow_checkbox_grid(two_col=True)
        layout.addLayout(self._checkbox_grid)

        # 全选 / 清空：与主页按钮样式一致（使用包装容器以便窄屏重排）
        self._sel_buttons_container = QWidget()
        self._sel_buttons_container.setStyleSheet("background: transparent; border: none;")
        self._sel_buttons_layout = QHBoxLayout(self._sel_buttons_container)
        self._sel_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._sel_buttons_layout.setSpacing(12)
        self._select_all_btn = MaterialButton(tr("settings.config.select_all"), variant=MaterialButton.VARIANT_TONAL)
        self._clear_btn = MaterialButton(tr("settings.config.clear_all"), variant=MaterialButton.VARIANT_OUTLINED)
        self._tr_labels.append((self._select_all_btn.setText, "settings.config.select_all"))
        self._tr_labels.append((self._clear_btn.setText, "settings.config.clear_all"))
        # 直接设置完整内联样式，避免全局 QSS 在某些场景下未生效
        self._select_all_btn.setStyleSheet(self._filled_button_qss())
        self._clear_btn.setStyleSheet(self._outlined_button_qss())
        self._select_all_btn.clicked.connect(self._on_select_all)
        self._clear_btn.clicked.connect(self._on_clear_all)
        # stretch 在前，将按钮推到右侧
        self._sel_buttons_layout.addStretch()
        self._sel_buttons_layout.addWidget(self._select_all_btn)
        self._sel_buttons_layout.addWidget(self._clear_btn)
        layout.addWidget(self._sel_buttons_container)

        # 生成按钮 + 状态文本（同样使用包装容器支持窄屏重排）
        self._action_buttons_container = QWidget()
        self._action_buttons_container.setStyleSheet("background: transparent; border: none;")
        self._action_buttons_layout = QHBoxLayout(self._action_buttons_container)
        self._action_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._action_buttons_layout.setSpacing(12)
        self._generate_btn = MaterialButton(tr("settings.config.generate"), variant=MaterialButton.VARIANT_FILLED)
        self._tr_labels.append((self._generate_btn.setText, "settings.config.generate"))
        self._generate_btn.setStyleSheet(self._filled_button_qss())
        self._generate_btn.clicked.connect(self._on_generate)
        self._config_status = QLabel("")
        self._config_status.setFont(self._typo.body_small)
        self._config_status.setWordWrap(True)
        self._action_buttons_layout.addWidget(self._generate_btn)
        self._action_buttons_layout.addWidget(self._config_status, 1)
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
        row = QHBoxLayout()
        row.setSpacing(16)
        row.setContentsMargins(0, 4, 0, 4)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        text_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._advanced_toggle_label = QLabel(tr("settings.advanced_toggle.label"))
        self._advanced_toggle_label.setFont(self._typo.title_medium)
        self._advanced_toggle_label.setStyleSheet(
            "border: none; background: transparent;"
        )
        text_box.addWidget(self._advanced_toggle_label)
        self._tr_labels.append((self._advanced_toggle_label.setText, "settings.advanced_toggle.label"))

        self._advanced_toggle_desc = QLabel(tr("settings.advanced_toggle.desc"))
        self._advanced_toggle_desc.setFont(self._typo.body_medium)
        self._advanced_toggle_desc.setWordWrap(True)
        self._dim_labels.append(self._advanced_toggle_desc)
        text_box.addWidget(self._advanced_toggle_desc)
        self._tr_labels.append((self._advanced_toggle_desc.setText, "settings.advanced_toggle.desc"))
        row.addLayout(text_box, 1)

        self._advanced_switch = MaterialSwitch(
            checked=False, colors=self._colors
        )
        self._advanced_switch.toggled.connect(self._on_advanced_toggled)
        row.addWidget(self._advanced_switch, 0, Qt.AlignmentFlag.AlignVCenter)

        card.add_layout(row)
        return card

    def _build_advanced_card(self) -> MaterialCard:
        """全局设置卡片：Copilot 后端 / Output 路径（始终可见）+ MAA 路径 /
        MAA 超时 / MAA 重试 / Copilot 超时/重试 / 识别参数 / 日志级别 / 日志文件 /
        子配置文件路径（高级开关打开后可见）。MAA 路径仅在识别后端为 maa 时显示。"""
        card = MaterialCard(tr("settings.global.title"))
        self._tr_labels.append((card.set_title, "settings.global.title"))
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 描述文本
        self._advanced_desc = QLabel(tr("settings.global.desc"))
        self._advanced_desc.setFont(self._typo.body_medium)
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

        # MAA 路径（单行标题 + FileSelector）：仅后端为 maa 时显示
        self._maa_selector = FileSelector(
            mode=FileSelector.MODE_DIRECTORY,
            label=tr("settings.global.maa_path"),
            placeholder=tr("settings.global.maa_path_placeholder"),
        )
        self._maa_selector.setVisible(False)
        layout.addWidget(self._maa_selector)

        # Output 路径
        self._output_selector = FileSelector(
            mode=FileSelector.MODE_DIRECTORY,
            label=tr("settings.global.output"),
            placeholder=tr("settings.global.output_placeholder"),
        )
        layout.addWidget(self._output_selector)
        # 注册 selector label/placeholder 重翻译
        self._tr_labels.append((self._maa_selector.set_label, "settings.global.maa_path"))
        self._tr_labels.append((self._maa_selector.set_placeholder, "settings.global.maa_path_placeholder"))
        self._tr_labels.append((self._output_selector.set_label, "settings.global.output"))
        self._tr_labels.append((self._output_selector.set_placeholder, "settings.global.output_placeholder"))

        # 将内部控件信号转发为公开信号，供 MainWindow 连接
        self._maa_selector.path_changed.connect(self.maa_path_changed)
        self._output_selector.path_changed.connect(self.output_dir_changed)

        card.add_layout(layout)

        # ── 高级字段容器（开关关闭时隐藏，不占用布局空间）──
        self._global_advanced_container = QWidget()
        self._global_advanced_container.setStyleSheet(
            "background: transparent; border: none;"
        )
        adv_layout = QVBoxLayout(self._global_advanced_container)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(16)

        # 日志级别：标签 + 组合框
        log_row = QHBoxLayout()
        log_row.setSpacing(8)
        log_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._log_level_label = QLabel(tr("settings.global.log_level"))
        self._log_level_label.setStyleSheet(
            "border: none; background: transparent;"
            " font-weight: 500; font-size: 13px;"
        )
        log_row.addWidget(self._log_level_label)
        self._tr_labels.append((self._log_level_label.setText, "settings.global.log_level"))
        self._log_level_combo = QComboBox()
        self._log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        log_row.addWidget(self._log_level_combo, 1)
        self._log_level_arrow = QLabel("▾")
        self._log_level_arrow.setFixedWidth(20)
        self._log_level_arrow.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._log_level_arrow.setStyleSheet(
            "border: none; background: transparent; font-size: 14px;"
        )
        log_row.addWidget(self._log_level_arrow)
        adv_layout.addLayout(log_row)

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

        # MAA 超时（秒）
        row = build_int_row(
            tr("settings.global.maa_timeout"), default=600,
            minimum=10, maximum=7200, step=10,
            colors=self._colors,
            on_changed=self.maa_timeout_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["maa_timeout_seconds"] = row
        self._tr_labels.append((row.set_label, "settings.global.maa_timeout"))

        # MAA 最大重试次数
        row = build_int_row(
            tr("settings.global.maa_retries"), default=2,
            minimum=0, maximum=10, step=1,
            colors=self._colors,
            on_changed=self.maa_max_retries_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["maa_max_retries"] = row
        self._tr_labels.append((row.set_label, "settings.global.maa_retries"))

        # Copilot 超时（秒）
        row = build_int_row(
            tr("settings.global.copilot_timeout"), default=600,
            minimum=10, maximum=7200, step=10,
            colors=self._colors,
            on_changed=self.copilot_timeout_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["copilot_timeout_seconds"] = row
        self._tr_labels.append((row.set_label, "settings.global.copilot_timeout"))

        # Copilot 最大重试次数
        row = build_int_row(
            tr("settings.global.copilot_retries"), default=2,
            minimum=0, maximum=10, step=1,
            colors=self._colors,
            on_changed=self.copilot_max_retries_changed.emit,
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["copilot_max_retries"] = row
        self._tr_labels.append((row.set_label, "settings.global.copilot_retries"))

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
        )
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["stage_override"] = row
        self._tr_labels.append((row.set_label, "settings.global.stage_override"))

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
        row.widget.set_filter("JSON files (*.json);;All files (*.*)")
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["formation"] = row
        self._tr_labels.append((row.set_label, "settings.global.formation_path"))

        # Actions 配置文件路径
        row = build_path_row(
            tr("settings.global.actions_path"), mode=FileSelector.MODE_OPEN_FILE,
            colors=self._colors,
            on_changed=self.actions_path_changed.emit,
        )
        row.widget.set_filter("JSON files (*.json);;All files (*.*)")
        adv_layout.addWidget(row.widget)
        self._pipeline_field_rows["actions"] = row
        self._tr_labels.append((row.set_label, "settings.global.actions_path"))

        # Track 配置文件路径
        row = build_path_row(
            tr("settings.global.track_path"), mode=FileSelector.MODE_OPEN_FILE,
            colors=self._colors,
            on_changed=self.track_path_changed.emit,
        )
        row.widget.set_filter("JSON files (*.json);;All files (*.*)")
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
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 多线程开关行：左侧标题+说明，右侧 MaterialSwitch
        mt_row = QHBoxLayout()
        mt_row.setSpacing(16)
        mt_row.setContentsMargins(0, 4, 0, 4)
        mt_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        text_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._mt_label = QLabel(tr("settings.performance.mt_label"))
        self._mt_label.setFont(self._typo.title_medium)
        self._mt_label.setStyleSheet("border: none; background: transparent;")
        text_box.addWidget(self._mt_label)
        self._tr_labels.append((self._mt_label.setText, "settings.performance.mt_label"))

        self._mt_desc = QLabel(tr("settings.performance.mt_desc"))
        self._mt_desc.setFont(self._typo.body_medium)
        self._mt_desc.setWordWrap(True)
        self._dim_labels.append(self._mt_desc)
        text_box.addWidget(self._mt_desc)
        self._tr_labels.append((self._mt_desc.setText, "settings.performance.mt_desc"))
        mt_row.addLayout(text_box, 1)

        self._mt_switch = MaterialSwitch(checked=False, colors=self._colors)
        self._mt_switch.toggled.connect(self._on_multithreading_toggled)
        mt_row.addWidget(self._mt_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(mt_row)

        # 最大并发数行：标签 + QSpinBox，与 Log level 行节奏一致
        # 仅在多线程启用时可编辑；关闭时置灰，避免用户误以为串行模式下
        # 该值会影响行为。
        conc_row = QHBoxLayout()
        conc_row.setSpacing(8)
        conc_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._conc_label = QLabel(tr("settings.performance.max_concurrent"))
        self._conc_label.setStyleSheet(
            "border: none; background: transparent;"
            " font-weight: 500; font-size: 13px;"
        )
        conc_row.addWidget(self._conc_label)
        self._tr_labels.append((self._conc_label.setText, "settings.performance.max_concurrent"))
        self._conc_spin = QSpinBox()
        self._conc_spin.setRange(1, 16)
        self._conc_spin.setValue(1)
        self._conc_spin.setSingleStep(1)
        self._conc_spin.setEnabled(False)
        self._conc_spin.valueChanged.connect(self._on_max_concurrent_changed)
        conc_row.addWidget(self._conc_spin, 1)
        layout.addLayout(conc_row)

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
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 描述 + Windows-only 提示
        self._ffmpeg_desc = QLabel(tr("settings.ffmpeg.desc"))
        self._ffmpeg_desc.setFont(self._typo.body_medium)
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

        # 启用开关行：左侧标题+说明，右侧 MaterialSwitch
        enable_row = QHBoxLayout()
        enable_row.setSpacing(16)
        enable_row.setContentsMargins(0, 4, 0, 4)
        enable_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        text_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._ffmpeg_enable_label = QLabel(tr("settings.ffmpeg.enable_label"))
        self._ffmpeg_enable_label.setFont(self._typo.title_medium)
        self._ffmpeg_enable_label.setStyleSheet("border: none; background: transparent;")
        text_box.addWidget(self._ffmpeg_enable_label)
        self._tr_labels.append((self._ffmpeg_enable_label.setText, "settings.ffmpeg.enable_label"))
        enable_row.addLayout(text_box, 1)

        self._ffmpeg_switch = MaterialSwitch(checked=False, colors=self._colors)
        self._ffmpeg_switch.toggled.connect(self._on_ffmpeg_custom_toggled)
        enable_row.addWidget(self._ffmpeg_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(enable_row)

        # 路径选择器（目录模式，选择 ffmpeg.exe 所在目录）
        self._ffmpeg_selector = FileSelector(
            mode=FileSelector.MODE_DIRECTORY,
            label=tr("settings.ffmpeg.title"),
            placeholder=tr("settings.ffmpeg.placeholder"),
        )
        self._ffmpeg_selector.path_changed.connect(self._on_ffmpeg_path_changed)
        self._tr_labels.append((self._ffmpeg_selector.set_label, "settings.ffmpeg.title"))
        self._tr_labels.append((self._ffmpeg_selector.set_placeholder, "settings.ffmpeg.placeholder"))
        # 开关默认关闭时路径选择器禁用
        self._ffmpeg_selector.setEnabled(False)
        layout.addWidget(self._ffmpeg_selector)

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
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        desc = QLabel(tr("settings.track.desc"))
        desc.setFont(self._typo.body_medium)
        desc.setWordWrap(True)
        self._dim_labels.append(desc)
        layout.addWidget(desc)
        self._tr_labels.append((desc.setText, "settings.track.desc"))

        cn = "track"
        c = self._colors

        def add(field_path: str, row: FieldRow, label_key: str) -> None:
            layout.addWidget(row.widget)
            self._register_sub_row(cn, field_path, row)
            self._tr_labels.append((row.set_label, label_key))

        add("track_mode", build_combo_row(
            tr("settings.track.track_mode"),
            items=["startbutton", "battlestart"],
            default="startbutton",
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
        bs_layout.setSpacing(16)

        bs_title = QLabel(tr("settings.track.battle_start.title"))
        bs_title.setFont(self._typo.body_medium)
        bs_title.setWordWrap(True)
        self._dim_labels.append(bs_title)
        bs_layout.addWidget(bs_title)
        self._tr_labels.append((bs_title.setText, "settings.track.battle_start.title"))

        def add_bs(field_path: str, row: FieldRow, label_key: str) -> None:
            bs_layout.addWidget(row.widget)
            self._register_sub_row(cn, field_path, row)
            self._tr_labels.append((row.set_label, label_key))

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
        layout.setSpacing(16)
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
        layout.setSpacing(16)
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
        layout.setSpacing(16)
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

        def add(field_path: str, row: FieldRow, label_key: str) -> None:
            layout.addWidget(row.widget)
            self._register_sub_row(cn, field_path, row)
            self._tr_labels.append((row.set_label, label_key))

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
        overlay_title = QLabel(tr("settings.compose.overlay_title"))
        overlay_title.setStyleSheet(
            f"color: {c.on_surface_variant}; border: none;"
            f" background: transparent; font-weight: 500; font-size: 13px;"
            f" letter-spacing: 0.5px; margin-top: 8px;"
        )
        layout.addWidget(overlay_title)
        self._dim_labels.append(overlay_title)
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
            add(f"{tp}.auto_fit_min_font_size", build_int_row(
                tr("settings.compose.auto_fit_min_font_size"), default=10, minimum=1, maximum=100, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.auto_fit_min_font_size")), "settings.compose.auto_fit_min_font_size")
            add(f"{tp}.auto_fit_max_font_size", build_int_row(
                tr("settings.compose.auto_fit_max_font_size"), default=200, minimum=10, maximum=500, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.auto_fit_max_font_size")), "settings.compose.auto_fit_max_font_size")

        # 逐操作显示（map_overlay）子区域标题（仅 style1：地图操作序号 + 面板当前操作高亮）
        if style == "style1":
            map_title = QLabel(tr("settings.compose.map_overlay_title"))
            map_title.setStyleSheet(
                f"color: {c.on_surface_variant}; border: none;"
                f" background: transparent; font-weight: 500; font-size: 13px;"
                f" letter-spacing: 0.5px; margin-top: 8px;"
            )
            layout.addWidget(map_title)
            self._dim_labels.append(map_title)
            self._tr_labels.append((map_title.setText, "settings.compose.map_overlay_title"))

            mp = "map_overlay"
            add(f"{mp}.enabled", build_switch_row(
                tr("settings.compose.map_overlay_enabled"), default=False, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.enabled")), "settings.compose.map_overlay_enabled")
            add(f"{mp}.resolution", build_string_row(
                tr("settings.compose.map_overlay_resolution"), default="1280x720", colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.resolution")), "settings.compose.map_overlay_resolution")
            add(f"{mp}.number_size_mode", build_combo_row(
                tr("settings.compose.map_overlay_number_size_mode"),
                items=["approximate", "precise"], default="approximate", colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_size_mode")), "settings.compose.map_overlay_number_size_mode")
            add(f"{mp}.number_font_ratio", build_float_row(
                tr("settings.compose.map_overlay_number_font_ratio"), default=0.5,
                minimum=0.1, maximum=1.0, step=0.05, decimals=2, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_font_ratio")), "settings.compose.map_overlay_number_font_ratio")
            add(f"{mp}.number_color", build_color_row(
                tr("settings.compose.map_overlay_number_color"), default="#FFD700", colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_color")), "settings.compose.map_overlay_number_color")
            add(f"{mp}.panel_highlight_enabled", build_switch_row(
                tr("settings.compose.map_overlay_panel_highlight_enabled"), default=True, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.panel_highlight_enabled")), "settings.compose.map_overlay_panel_highlight_enabled")
            add(f"{mp}.panel_highlight_color", build_color_row(
                tr("settings.compose.map_overlay_panel_highlight_color"), default="#FFD700", colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.panel_highlight_color")), "settings.compose.map_overlay_panel_highlight_color")

        card.add_layout(layout)

        # ── 高级字段容器（开关关闭时隐藏，不占用布局空间）──
        adv_container = QWidget()
        adv_container.setStyleSheet("background: transparent; border: none;")
        adv_layout = QVBoxLayout(adv_container)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(16)

        def add_adv(field_path: str, row: FieldRow, label_key: str) -> None:
            adv_layout.addWidget(row.widget)
            self._register_sub_row(cn, field_path, row)
            self._tr_labels.append((row.set_label, label_key))

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
            add_adv(f"{tp}.auto_fit_available_width", build_nullable_int_row(
                tr("settings.compose.auto_fit_available_width"), default=None,
                minimum=1, maximum=3840, colors=c,
                on_changed=self._emit_sub(cn, f"{tp}.auto_fit_available_width")), "settings.compose.auto_fit_available_width")
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
            add_adv(f"{mp}.number_shadow_enabled", build_switch_row(
                tr("settings.compose.map_overlay_number_shadow_enabled"), default=True, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_shadow_enabled")), "settings.compose.map_overlay_number_shadow_enabled")
            add_adv(f"{mp}.number_shadow_offset_x", build_int_row(
                tr("settings.compose.map_overlay_number_shadow_offset_x"), default=2, minimum=-50, maximum=50, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_shadow_offset_x")), "settings.compose.map_overlay_number_shadow_offset_x")
            add_adv(f"{mp}.number_shadow_offset_y", build_int_row(
                tr("settings.compose.map_overlay_number_shadow_offset_y"), default=2, minimum=-50, maximum=50, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_shadow_offset_y")), "settings.compose.map_overlay_number_shadow_offset_y")
            add_adv(f"{mp}.number_shadow_blur", build_int_row(
                tr("settings.compose.map_overlay_number_shadow_blur"), default=4, minimum=0, maximum=50, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_shadow_blur")), "settings.compose.map_overlay_number_shadow_blur")
            add_adv(f"{mp}.number_shadow_color", build_color_row(
                tr("settings.compose.map_overlay_number_shadow_color"), default="#000000", colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_shadow_color")), "settings.compose.map_overlay_number_shadow_color")
            add_adv(f"{mp}.number_bg_enabled", build_switch_row(
                tr("settings.compose.map_overlay_number_bg_enabled"), default=True, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_bg_enabled")), "settings.compose.map_overlay_number_bg_enabled")
            add_adv(f"{mp}.number_bg_color", build_color_row(
                tr("settings.compose.map_overlay_number_bg_color"), default="#000000", colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_bg_color")), "settings.compose.map_overlay_number_bg_color")
            add_adv(f"{mp}.number_bg_alpha", build_float_row(
                tr("settings.compose.map_overlay_number_bg_alpha"), default=0.45,
                minimum=0.0, maximum=1.0, step=0.05, decimals=2, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_bg_alpha")), "settings.compose.map_overlay_number_bg_alpha")
            add_adv(f"{mp}.number_padding", build_int_row(
                tr("settings.compose.map_overlay_number_padding"), default=2, minimum=0, maximum=50, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_padding")), "settings.compose.map_overlay_number_padding")
            add_adv(f"{mp}.number_min_font_size", build_int_row(
                tr("settings.compose.map_overlay_number_min_font_size"), default=8, minimum=1, maximum=200, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.number_min_font_size")), "settings.compose.map_overlay_number_min_font_size")
            add_adv(f"{mp}.panel_highlight_background", build_color_row(
                tr("settings.compose.map_overlay_panel_highlight_background"), default="#000000", colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.panel_highlight_background")), "settings.compose.map_overlay_panel_highlight_background")
            add_adv(f"{mp}.panel_highlight_bg_alpha", build_float_row(
                tr("settings.compose.map_overlay_panel_highlight_bg_alpha"), default=0.55,
                minimum=0.0, maximum=1.0, step=0.05, decimals=2, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.panel_highlight_bg_alpha")), "settings.compose.map_overlay_panel_highlight_bg_alpha")
            add_adv(f"{mp}.panel_fade_duration", build_float_row(
                tr("settings.compose.map_overlay_panel_fade_duration"), default=0.3,
                minimum=0.0, maximum=5.0, step=0.1, decimals=2, colors=c,
                on_changed=self._emit_sub(cn, f"{mp}.panel_fade_duration")), "settings.compose.map_overlay_panel_fade_duration")

        adv_container.setVisible(False)
        card.add_widget(adv_container)
        if style == "style1":
            self._compose_style1_advanced_container = adv_container
        else:
            self._compose_style2_advanced_container = adv_container
        return card

    def _apply_grid_layout(self, two_column: bool = False) -> None:
        """卡片网格布局：始终保持单列竖直堆叠，
        保留 two_column 参数签名以兼容历史调用点（忽略其值）。

        单列布局避免 2x2 错位，并让卡片保持等宽，与 Hero 标题对齐。
        """
        # 参数兼容：历史断点会传 True，但视觉上卡片单列更协调，故忽略
        for i in reversed(range(self._cards_grid.count())):
            item = self._cards_grid.itemAt(i)
            if item and item.widget():
                self._cards_grid.removeWidget(item.widget())

        self._cards_grid.setColumnStretch(0, 1)
        self._cards_grid.setColumnStretch(1, 0)
        # 始终可见卡片单列竖直堆叠；任一卡片为 None 时跳过（FFmpeg 卡片在非 Windows 上为 None）
        r = 0
        for card in (
            self._language_card,
            self._appearance_card,
            self._advanced_card, self._ffmpeg_card,
            self._compose_style1_main_card, self._compose_style2_main_card,
            self._config_card,
        ):
            if card is not None:
                self._cards_grid.addWidget(card, r, 0)
                r += 1
        # 高级开关卡片 + 内容容器（内容 setVisible 控制显隐）
        self._cards_grid.addWidget(self._advanced_toggle_card, r, 0)
        r += 1
        self._cards_grid.addWidget(self._collapsible_content, r, 0)

    def _reflow_checkbox_grid(self, two_col: bool) -> None:
        """根据可用宽度决定复选框网格是 1 列还是 2 列"""
        # 清空当前布局
        for i in reversed(range(self._checkbox_grid.count())):
            item = self._checkbox_grid.itemAt(i)
            if item and item.widget():
                self._checkbox_grid.removeWidget(item.widget())
        # 重新排列
        cols = 2 if two_col else 1
        for i, cb in enumerate(self._config_checkboxes.values()):
            self._checkbox_grid.addWidget(cb, i // cols, i % cols)

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
                    layout.addWidget(self._generate_btn)
                    layout.addWidget(self._config_status, 1)

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
            cb.setText(f"{tr(title_key)}  ·  {filename}")

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
        """Copilot 后端切换：转发信号并同步 MAA 路径选择框显隐（仅 maa 后端显示）"""
        self.copilot_backend_changed.emit(backend)
        self._maa_selector.setVisible(backend == "maa")

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
                # _init_config 仅对未知模块 sys.exit；此处 key 均来自 CONFIG_TYPES，合法
                # 返回值是成功生成的文件路径列表；空列表表示导入失败被跳过
                result = _init_config(key)
                if result:
                    generated.append(key)
                else:
                    failed.append(tr("settings.config.load_failed", key=key))
            except SystemExit:
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
        self._config_status.setStyleSheet(
            f"color: {color}; border: none; background: transparent;"
        )

    # ── 主题与状态同步 ────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        """主题切换时刷新页面所有颜色相关样式"""
        self._colors = colors
        self._theme_switch.set_colors(colors)
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
            self._config_status.setStyleSheet(
                f"color: {color}; border: none; background: transparent;"
            )

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

    # ── 高级配置控件公开访问 ────────────────────────────────

    def set_maa_path(self, path: str) -> None:
        """设置 MAA 路径（阻塞信号，避免触发 maa_path_changed 回写）"""
        self._maa_selector.blockSignals(True)
        try:
            self._maa_selector.set_path(path)
        finally:
            self._maa_selector.blockSignals(False)

    def set_output_dir(self, path: str) -> None:
        """设置 Output 路径（阻塞信号，避免触发 output_dir_changed 回写）"""
        self._output_selector.blockSignals(True)
        try:
            self._output_selector.set_path(path)
        finally:
            self._output_selector.blockSignals(False)

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

    def set_maa_timeout(self, value: int) -> None:
        row = self._pipeline_field_rows.get("maa_timeout_seconds")
        if row:
            row.set_value(int(value), block_signal=True)

    def set_maa_max_retries(self, value: int) -> None:
        row = self._pipeline_field_rows.get("maa_max_retries")
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
        # 同步 MAA 路径选择框显隐（仅 maa 后端显示）
        self._maa_selector.setVisible(backend == "maa")

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
        self._ffmpeg_selector.blockSignals(True)
        try:
            self._ffmpeg_selector.set_path(path)
        finally:
            self._ffmpeg_selector.blockSignals(False)

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
        # 页面整体背景由全局 QWidget { background-color } 规则统一控制；
        # 此处仅刷新辅助文本颜色（仅作用于单标签，不影响子控件）。
        dim = self._colors.on_surface_variant
        for w in self._dim_labels:
            w.setStyleSheet(
                f"color: {dim}; border: none; background: transparent;"
            )
        # 同步刷新"重置配置文件"卡片内的复选框配色：MaterialCheckBox 在
        # 初始化时使用默认浅色主题（indicator fill = surface = 白），若不在
        # 主题切换时显式调用 set_colors()，深色模式下 indicator 会保持白色
        # 矩形块，与深色背景形成刺眼对比。
        for cb in getattr(self, "_config_checkboxes", {}).values():
            cb.set_colors(self._colors)
        # 高级卡片内 Log level 标签：使用 on_surface_variant 跟随主题
        if getattr(self, "_log_level_label", None) is not None:
            self._log_level_label.setStyleSheet(
                f"color: {dim}; border: none; background: transparent;"
                f" font-weight: 500; font-size: 13px;"
            )
        # 高级卡片内 Log level 下拉箭头：使用 on_surface_variant 跟随主题
        if getattr(self, "_log_level_arrow", None) is not None:
            self._log_level_arrow.setStyleSheet(
                f"color: {dim}; border: none; background: transparent;"
                f" font-size: 14px;"
            )
        # 高级卡片内 Log level 下拉框：与 FileSelector 内 QLineEdit
        # 保持完全一致的视觉规格（surface_variant 底色、outline_variant
        # 边框、12px 圆角、聚焦 2px primary 边框），并保留当前校验状态
        if getattr(self, "_log_level_combo", None) is not None:
            self._log_level_combo.setStyleSheet(
                self._log_level_combo_qss(error=not self._log_level_valid)
            )
        # 语言切换卡片内下拉框：同步主题色到内联样式（含下拉箭头、
        # hover/focus 状态、二级菜单配色），确保深色模式下颜色正确
        if getattr(self, "_lang_combo", None) is not None:
            self._lang_combo.setStyleSheet(self._lang_combo_qss())
        # 高级卡片内 MAA / Output 文件选择器：同步主题色到
        # 内联样式（输入框 + 浏览按钮），确保与主页 Video/Background 一致
        for selector in (getattr(self, "_maa_selector", None),
                         getattr(self, "_output_selector", None)):
            if selector is not None:
                selector.set_colors(self._colors)
        # FFmpeg 卡片内文件选择器：同步主题色
        if getattr(self, "_ffmpeg_selector", None) is not None:
            self._ffmpeg_selector.set_colors(self._colors)
        # 性能卡片内"最大并发数"标签：与 Log level 标签同色
        if getattr(self, "_conc_label", None) is not None:
            self._conc_label.setStyleSheet(
                f"color: {dim}; border: none; background: transparent;"
                f" font-weight: 500; font-size: 13px;"
            )
        # 性能卡片内 QSpinBox：与 Log level 下拉框保持一致视觉规格
        if getattr(self, "_conc_spin", None) is not None:
            self._conc_spin.setStyleSheet(self._conc_spin_qss())
        # 同步刷新卡片背景色：MaterialCard 使用 paintEvent 自绘圆角背景，
        # 此处需调用 set_surface_color 更新颜色，确保暗色模式正确
        all_cards = [
            self._language_card,
            self._appearance_card, self._config_card, self._advanced_card,
            self._ffmpeg_card,
            self._compose_style1_main_card, self._compose_style2_main_card,
            self._advanced_toggle_card,
            self._track_card, self._formation_card, self._actions_card,
            self._performance_card,
        ]
        for card in all_cards:
            if card is not None:
                card.set_surface_color(self._colors.surface)
        # 同步刷新按钮配色，使其在主题切换后保持视觉一致
        if getattr(self, "_select_all_btn", None) is not None:
            self._select_all_btn.setStyleSheet(self._filled_button_qss())
        if getattr(self, "_clear_btn", None) is not None:
            self._clear_btn.setStyleSheet(self._outlined_button_qss())
        if getattr(self, "_generate_btn", None) is not None:
            self._generate_btn.setStyleSheet(self._filled_button_qss())

    # ── 内联样式辅助（避免依赖全局 QSS 的级联） ───────────

    def _filled_button_qss(
        self, font_size: int = 14, font_weight: int = 500,
        padding: str = "10px 24px",
    ) -> str:
        """filled/tonal 按钮的内联样式：主色填充、白色文字、圆角

        委托 gui.theme.button_qss.filled_button_qss 实现（修复 M15）。
        """
        return _build_filled_button_qss(
            self._colors,
            font_size=font_size,
            font_weight=font_weight,
            padding=padding,
        )

    def _outlined_button_qss(
        self, font_size: int = 14, font_weight: int = 500,
        padding: str = "10px 24px",
    ) -> str:
        """outlined 按钮的内联样式：透明背景、主色描边与文字

        委托 gui.theme.button_qss.outlined_button_qss 实现（修复 M15）。
        """
        return _build_outlined_button_qss(
            self._colors,
            font_size=font_size,
            font_weight=font_weight,
            padding=padding,
        )

    def _log_level_combo_qss(self, error: bool = False) -> str:
        """Log level 下拉框内联样式：与主界面 Video 路径输入框
        （FileSelector 内 QLineEdit，由全局 QSS 驱动）保持完全一致的
        视觉规格 —— surface_variant 底色、outline_variant 边框、12px 圆角、
        8px/12px 内边距、20px 最小高度、聚焦时 2px primary 边框。

        通过 ``error`` 参数切换错误状态（与 FileSelector.set_valid 行为一致：
        2px solid error 边框），便于上层按需标记非法输入。
        """
        c = self._colors
        border = f"2px solid {c.error}" if error else f"1px solid {c.outline_variant}"
        return (
            "QComboBox {"
            f"  background-color: {c.surface_variant};"
            f"  color: {c.on_surface};"
            f"  border: {border};"
            f"  border-radius: 12px;"
            f"  padding: 8px 12px;"
            f"  min-height: 20px;"
            "}"
            "QComboBox:focus {"
            f"  border: 2px solid {c.primary};"
            "}"
            "QComboBox:disabled {"
            f"  background-color: {c.surface_variant};"
            f"  color: {c.on_surface_variant};"
            "}"
            "QComboBox QAbstractItemView {"
            f"  background-color: {c.surface};"
            f"  color: {c.on_surface};"
            f"  border: 1px solid {c.outline};"
            f"  border-radius: 8px;"
            f"  selection-background-color: {c.primary_container};"
            f"  selection-color: {c.on_primary_container};"
            f"  outline: none;"
            "}"
        )

    def set_log_level_valid(self, valid: bool) -> None:
        """设置 Log level 下拉框的校验状态（与 FileSelector.set_valid
        行为一致：``valid=False`` 时显示 2px error 边框）。"""
        self._log_level_combo.setStyleSheet(
            self._log_level_combo_qss(error=not valid)
        )

    def _lang_combo_qss(self) -> str:
        """语言下拉框内联样式：与 Log level 下拉框（``_log_level_combo_qss``）
        及 ``settings_row_builders._combo_qss`` 保持完全一致的视觉规格 ——
        surface_variant 底色、outline_variant 边框、12px 圆角、8px/12px 内边距、
        20px 最小高度、聚焦时 2px primary 边框。"""
        c = self._colors
        return (
            "QComboBox {"
            f"  background-color: {c.surface_variant};"
            f"  color: {c.on_surface};"
            f"  border: 1px solid {c.outline_variant};"
            f"  border-radius: 12px;"
            f"  padding: 8px 12px;"
            f"  min-height: 20px;"
            "}"
            "QComboBox:focus {"
            f"  border: 2px solid {c.primary};"
            "}"
            "QComboBox:disabled {"
            f"  background-color: {c.surface_variant};"
            f"  color: {c.on_surface_variant};"
            "}"
            "QComboBox QAbstractItemView {"
            f"  background-color: {c.surface};"
            f"  color: {c.on_surface};"
            f"  border: 1px solid {c.outline};"
            f"  border-radius: 8px;"
            f"  selection-background-color: {c.primary_container};"
            f"  selection-color: {c.on_primary_container};"
            f"  outline: none;"
            "}"
        )

    def _conc_spin_qss(self) -> str:
        """最大并发数 QSpinBox 内联样式：与 Log level 下拉框保持一致的
        视觉规格（surface_variant 底色、outline_variant 边框、12px 圆角、
        聚焦 2px primary 边框）。

        右侧原生上下箭头按钮已隐藏（width: 0），改由纯文本输入方式设置
        数值；用户仍可通过键盘输入或滚轮调整，保持界面简洁。"""
        c = self._colors
        return (
            "QSpinBox {"
            f"  background-color: {c.surface_variant};"
            f"  color: {c.on_surface};"
            f"  border: 1px solid {c.outline_variant};"
            f"  border-radius: 12px;"
            f"  padding: 8px 12px;"
            f"  min-height: 20px;"
            "}"
            "QSpinBox:focus {"
            f"  border: 2px solid {c.primary};"
            "}"
            "QSpinBox:disabled {"
            f"  background-color: {c.surface_variant};"
            f"  color: {c.on_surface_variant};"
            "}"
            # 隐藏右侧上下箭头按钮
            "QSpinBox::up-button, QSpinBox::down-button {"
            "  width: 0px;"
            "  border: none;"
            "}"
            "QSpinBox::up-arrow, QSpinBox::down-arrow {"
            "  width: 0px;"
            "  height: 0px;"
            "  border: none;"
            "}"
        )

    # ── 响应式 ────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "_cards_grid", None) is None:
            return
        w = self.width()
        # 三档断点（以 settings page 宽度计）：
        #   >= 1000  双列卡片 + 2 列复选框 + 横向按钮
        #   720~1000  双列卡片 + 1 列复选框 + 横向按钮
        #                （单列复选框可保留较长文件名不被裁切）
        #   480~720  单列卡片 + 1 列复选框 + 横向按钮
        #   < 480   单列卡片 + 1 列复选框 + 纵向按钮
        two_col_cards = w >= 720
        two_col_checkboxes = w >= 1000
        vertical_buttons = w < 480
        self._apply_grid_layout(two_column=two_col_cards)
        self._reflow_checkbox_grid(two_col=two_col_checkboxes)
        self._reflow_button_rows(vertical=vertical_buttons)
        # 页面边距随宽度收缩
        root_layout = self.layout()
        if isinstance(root_layout, QVBoxLayout):
            if w < 560:
                root_layout.setContentsMargins(20, 24, 20, 24)
            else:
                root_layout.setContentsMargins(40, 40, 40, 40)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 首次显示时强制根据当前宽度刷新一次布局，避免初始默认布局
        # 与响应式断点不一致（例如默认是 2 列卡片 + 2 列复选框）。
        if getattr(self, "_cards_grid", None) is not None:
            w = self.width()
            self._apply_grid_layout(two_column=w >= 720)
            self._reflow_checkbox_grid(two_col=w >= 1000)
            self._reflow_button_rows(vertical=w < 480)

