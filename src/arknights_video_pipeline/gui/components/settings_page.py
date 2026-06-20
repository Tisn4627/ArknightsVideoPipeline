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

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QBoxLayout, QLabel,
    QComboBox, QSizePolicy,
)

from arknights_video_pipeline.core.pipeline import _init_config
from arknights_video_pipeline.gui.components.file_selector import FileSelector
from arknights_video_pipeline.gui.components.material_checkbox import MaterialCheckBox
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import MaterialCard
from arknights_video_pipeline.gui.components.material_switch import MaterialSwitch
from arknights_video_pipeline.gui.theme import (
    MaterialColors, MaterialTypography,
    filled_button_qss as _build_filled_button_qss,
    outlined_button_qss as _build_outlined_button_qss,
)


class SettingsPage(QWidget):
    """设置页面：主题切换 + 配置文件生成，布局参考 Home 选项卡"""

    theme_change_requested = pyqtSignal(bool)  # True=深色
    home_requested = pyqtSignal()
    # 配置文件重置完成信号（参数：成功生成的模块 key 列表）
    # MainWindow 监听后需重新加载磁盘配置并刷新 MAA/Output/Log level 等
    # 共享控件，确保关闭 GUI 时不会将重置前的旧值写回配置文件。
    config_reset = pyqtSignal(list)

    # (module_key, 标题, 说明, 文件名)
    CONFIG_TYPES: list[tuple[str, str, str, str]] = [
        ("pipeline", "Pipeline", "主流水线配置", "pipeline.json"),
        ("formation", "Formation", "编队配置", "formation.json"),
        ("actions", "Actions", "操作指令配置", "actions.json"),
        ("track", "Track", "开始按钮识别配置", "track.json"),
        ("compose", "Compose · style1", "style1 视频合成配置", "video_compose/style1.json"),
        ("compose_style2", "Compose · style2", "style2 视频合成配置", "video_compose/style2.json"),
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

        self._build_ui()
        self._apply_colors()

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(32)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Hero 区域（参考 Home：大标题 + 副标题 + 主按钮）
        root.addWidget(self._build_hero())

        # 卡片网格：参考 Home 选项卡，使用 QGridLayout 排列独立圆角卡片
        # 现包含三张卡片：外观、配置文件、高级（运行时配置）。
        # 始终单列竖直堆叠——三张卡片宽度一致，避免出现 2x2 错位或被压缩。
        self._appearance_card = self._build_theme_card()
        self._config_card = self._build_config_card()
        self._advanced_card = self._build_advanced_card()
        self._cards_grid = QGridLayout()
        self._cards_grid.setSpacing(24)
        self._cards_grid.setColumnStretch(0, 1)
        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background: transparent; border: none;")
        self._cards_container.setLayout(self._cards_grid)
        root.addWidget(self._cards_container)
        # 单列竖直堆叠（保持 hero -> cards 视觉节奏）
        self._cards_grid.addWidget(self._appearance_card, 0, 0)
        self._cards_grid.addWidget(self._config_card, 1, 0)
        self._cards_grid.addWidget(self._advanced_card, 2, 0)

    def _build_hero(self) -> QWidget:
        """Hero 区域：大标题 + 描述（与 Home 一致；不放置按钮，遵循
        设计规范 Hero 区聚焦于内容引导）"""
        hero = QWidget()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 24, 0, 0)
        hero_layout.setSpacing(16)
        hero_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # MD3 Hero 标题：与 Home 一致使用 display_large + 48px 内联覆盖
        self._title_label = QLabel("Settings")
        self._title_label.setFont(self._typo.display_large)
        self._title_label.setStyleSheet(
            "border: none; background: transparent;"
            " font-size: 48px; font-weight: 600; line-height: 1.15;"
            " letter-spacing: -1.5px;"
        )
        self._title_label.setWordWrap(True)
        hero_layout.addWidget(self._title_label)

        return hero

    def _build_theme_card(self) -> MaterialCard:
        card = MaterialCard("外观")
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
        self._theme_label = QLabel("深色主题")
        self._theme_label.setFont(self._typo.title_medium)
        self._theme_label.setStyleSheet("border: none; background: transparent;")
        text_box.addWidget(self._theme_label)

        self._theme_desc = QLabel("切换浅色与深色配色，所有控件即时更新。")
        self._theme_desc.setFont(self._typo.body_medium)
        self._theme_desc.setWordWrap(True)
        self._dim_labels.append(self._theme_desc)
        text_box.addWidget(self._theme_desc)
        row.addLayout(text_box, 1)

        self._theme_switch = MaterialSwitch(checked=self._is_dark, colors=self._colors)
        self._theme_switch.toggled.connect(self._on_theme_toggled)
        row.addWidget(self._theme_switch, 0, Qt.AlignmentFlag.AlignVCenter)

        card.add_layout(row)
        return card

    def _build_config_card(self) -> MaterialCard:
        card = MaterialCard("配置文件")
        layout = QVBoxLayout()
        layout.setSpacing(16)

        self._config_desc = QLabel(
            "选择需要生成（或重置为默认）的配置文件，然后点击“生成”。"
            "生成的文件位于 config/ 目录下，与 CLI --init-config 行为一致。"
        )
        self._config_desc.setFont(self._typo.body_medium)
        self._config_desc.setWordWrap(True)
        self._dim_labels.append(self._config_desc)
        layout.addWidget(self._config_desc)

        # 复选框网格（容器，以便在窄屏下重新排列为单列）
        self._config_checkboxes: dict[str, MaterialCheckBox] = {}
        self._checkbox_grid = QGridLayout()
        self._checkbox_grid.setSpacing(12)
        for key, title, desc, filename in self.CONFIG_TYPES:
            # 传入当前主题 colors，避免 MaterialCheckBox 默认使用浅色
            # MaterialColors.light() 导致首次进入深色模式时 indicator
            # 保持白色的问题
            cb = MaterialCheckBox(
                f"{title}  ·  {filename}", colors=self._colors
            )
            cb.setToolTip(desc)
            self._config_checkboxes[key] = cb
        self._reflow_checkbox_grid(two_col=True)
        layout.addLayout(self._checkbox_grid)

        # 全选 / 清空：与主页按钮样式一致（使用包装容器以便窄屏重排）
        self._sel_buttons_container = QWidget()
        self._sel_buttons_container.setStyleSheet("background: transparent; border: none;")
        self._sel_buttons_layout = QHBoxLayout(self._sel_buttons_container)
        self._sel_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._sel_buttons_layout.setSpacing(12)
        self._select_all_btn = MaterialButton("一键选择全部", variant=MaterialButton.VARIANT_TONAL)
        self._clear_btn = MaterialButton("取消全部选择", variant=MaterialButton.VARIANT_OUTLINED)
        # 直接设置完整内联样式，避免全局 QSS 在某些场景下未生效
        self._select_all_btn.setStyleSheet(self._filled_button_qss())
        self._clear_btn.setStyleSheet(self._outlined_button_qss())
        self._select_all_btn.clicked.connect(self._on_select_all)
        self._clear_btn.clicked.connect(self._on_clear_all)
        self._sel_buttons_layout.addWidget(self._select_all_btn)
        self._sel_buttons_layout.addWidget(self._clear_btn)
        self._sel_buttons_layout.addStretch()
        layout.addWidget(self._sel_buttons_container)

        # 生成按钮 + 状态文本（同样使用包装容器支持窄屏重排）
        self._action_buttons_container = QWidget()
        self._action_buttons_container.setStyleSheet("background: transparent; border: none;")
        self._action_buttons_layout = QHBoxLayout(self._action_buttons_container)
        self._action_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._action_buttons_layout.setSpacing(12)
        self._generate_btn = MaterialButton("生成默认配置", variant=MaterialButton.VARIANT_FILLED)
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

    def _build_advanced_card(self) -> MaterialCard:
        """高级配置卡片：MAA 路径 / Output 路径 / 日志级别，
        全部使用 QVBoxLayout 竖直排列，不做 2x2 网格。
        这三个控件由 MainWindow 共享：在 SettingsPage 创建并暴露属性，
        Home 选项卡不再持有相同的 FileSelector / QComboBox 实例，
        避免双源状态不同步。"""
        card = MaterialCard("高级")
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 描述文本
        self._advanced_desc = QLabel(
            "MAA、Output 与日志级别的运行时配置。修改后立即生效，"
            "无需重新启动；流水线运行期间会暂时禁用编辑。"
        )
        self._advanced_desc.setFont(self._typo.body_medium)
        self._advanced_desc.setWordWrap(True)
        self._dim_labels.append(self._advanced_desc)
        layout.addWidget(self._advanced_desc)

        # MAA 路径（单行标题 + FileSelector）
        self._maa_selector = FileSelector(
            mode=FileSelector.MODE_DIRECTORY,
            label="MAA path",
            placeholder="MAA directory (optional)",
        )
        layout.addWidget(self._maa_selector)

        # Output 路径
        self._output_selector = FileSelector(
            mode=FileSelector.MODE_DIRECTORY,
            label="Output",
            placeholder="Output directory",
        )
        layout.addWidget(self._output_selector)

        # 日志级别：标签 + 组合框，横向布局与 FileSelector 内部节奏一致
        # （spacing=8，标签不固定宽度以匹配 Video 路径输入框的 "Video" 标签
        # 行为）。组合框内联 QSS 已在 _log_level_combo_qss 中与 FileSelector
        # 内 QLineEdit 完全对齐：surface_variant 底色、outline_variant 边框、
        # 12px 圆角、聚焦时 2px primary 边框，支持 set_log_level_valid 错误态。
        # 组合框右侧叠加一个 unicode "▾" 字符（独立 QLabel），补全下拉箭头
        # —— setStyleSheet 后 PyQt 默认 ::down-arrow 不可见。
        log_row = QHBoxLayout()
        log_row.setSpacing(8)
        log_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._log_level_label = QLabel("Log level")
        self._log_level_label.setStyleSheet(
            "border: none; background: transparent;"
            " font-weight: 500; font-size: 13px;"
        )
        log_row.addWidget(self._log_level_label)
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
        layout.addLayout(log_row)

        card.add_layout(layout)
        return card

    def _apply_grid_layout(self, two_column: bool = False) -> None:
        """卡片网格布局：始终保持单列竖直堆叠（外观/配置/高级），
        保留 two_column 参数签名以兼容历史调用点（忽略其值）。

        单列布局避免 2x2 错位，并让三张卡片保持等宽，与 Hero 标题对齐。
        """
        # 参数兼容：历史断点会传 True，但视觉上 3 张卡片单列更协调，故忽略
        for i in reversed(range(self._cards_grid.count())):
            item = self._cards_grid.itemAt(i)
            if item and item.widget():
                self._cards_grid.removeWidget(item.widget())

        self._cards_grid.setColumnStretch(0, 1)
        self._cards_grid.setColumnStretch(1, 0)
        # 三个卡片单列竖直堆叠；任一卡片为 None 时跳过
        for row, card in enumerate(
            (self._appearance_card, self._config_card, self._advanced_card)
        ):
            if card is not None:
                self._cards_grid.addWidget(card, row, 0)

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
            # 解除现有方向
            for w in widgets:
                layout.removeWidget(w)
            if vertical:
                layout.setDirection(QBoxLayout.Direction.TopToBottom)
                for w in widgets:
                    layout.addWidget(w)
            else:
                layout.setDirection(QBoxLayout.Direction.LeftToRight)
                if widgets == (self._select_all_btn, self._clear_btn):
                    layout.addWidget(self._select_all_btn)
                    layout.addWidget(self._clear_btn)
                    layout.addStretch()
                else:
                    layout.addWidget(self._generate_btn)
                    layout.addWidget(self._config_status, 1)

    # ── 事件处理 ──────────────────────────────────────────

    def _on_theme_toggled(self, dark: bool) -> None:
        self._is_dark = dark
        self.theme_change_requested.emit(dark)

    def _on_select_all(self) -> None:
        for cb in self._config_checkboxes.values():
            cb.setChecked(True)

    def _on_clear_all(self) -> None:
        for cb in self._config_checkboxes.values():
            cb.setChecked(False)

    def _on_generate(self) -> None:
        selected = [k for k, cb in self._config_checkboxes.items() if cb.isChecked()]
        if not selected:
            self._set_status("请至少选择一个配置文件类型。", error=True)
            return

        generated: list[str] = []
        failed: list[str] = []
        for key in selected:
            try:
                # _init_config 仅对未知模块 sys.exit；此处 key 均来自 CONFIG_TYPES，合法
                _init_config(key)
                generated.append(key)
            except SystemExit:
                failed.append(key)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{key} ({exc})")

        if generated and not failed:
            self._set_status(
                f"已生成 {len(generated)} 个配置文件到 config/ 目录。", error=False
            )
            # 通知 MainWindow：至少生成了 pipeline 配置，需要重新加载磁盘
            # 上的默认值并刷新 MAA/Output/Log level 等共享控件，保证
            # 关闭 GUI 时保存到配置文件的值与界面显示一致。
            self.config_reset.emit(generated)
        elif generated and failed:
            self._set_status(
                f"已生成 {len(generated)} 个；失败: {', '.join(failed)}", error=True
            )
            # 部分成功：仅当 pipeline 成功生成时才需要同步刷新。
            if "pipeline" in generated:
                self.config_reset.emit(generated)
        else:
            self._set_status(f"生成失败: {', '.join(failed)}", error=True)

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
        # 高级卡片内 MAA / Output 文件选择器：同步主题色到
        # 内联样式（输入框 + 浏览按钮），确保与主页 Video/Background 一致
        for selector in (getattr(self, "_maa_selector", None),
                         getattr(self, "_output_selector", None)):
            if selector is not None:
                selector.set_colors(self._colors)
        # 同步刷新卡片背景色：MaterialCard 使用 paintEvent 自绘圆角背景，
        # 此处需调用 set_surface_color 更新颜色，确保暗色模式正确
        for card in (self._appearance_card, self._config_card, self._advanced_card):
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

