"""
gui.main_window - 主窗口

参考 Material Design 官网布局重新设计：
- 左侧 Navigation Rail
- 右侧 Hero 区域 + 卡片网格内容区
- 淡紫背景、深紫主色、白色卡片、大标题排版
- 响应式：窄屏折叠导航栏，卡片自适应列数
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QComboBox, QCheckBox,
    QApplication, QLabel, QFrame, QStackedWidget,
)

from arknights_video_pipeline.gui.components import (
    BatchVideoList, FileSelector, LogViewer, MaterialButton, MaterialCard,
    MaterialCheckBox, NavigationRail, ProgressCard, SettingsPage,
)
from arknights_video_pipeline.gui.theme import (
    MaterialColors, MaterialStyle, MaterialTypography, apply_titlebar_theme,
    GuiConfig,
)
from arknights_video_pipeline.service import ConfigProxy, PipelineService


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self, config_proxy: ConfigProxy, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config_proxy
        self._service = PipelineService(config_proxy, parent=self)
        # GUI 偏好独立管理（config/gui.json），与 pipeline 配置完全解耦
        self._gui_config = GuiConfig(parent=self)
        self._is_dark = self._gui_config.is_dark_theme()
        self._current_page = 0  # 0=Home, 1=Settings
        # 标记首次 showEvent 是否已处理（用于在窗口句柄就绪后应用标题栏主题）
        self._titlebar_applied = False

        self.setWindowTitle("ArknightsVideoPipeline")
        self.setMinimumSize(720, 480)
        self.resize(900, 600)

        self._progress_card = ProgressCard()

        self._build_central_widget()
        # 启动时按配置主题应用 QSS（create_application 默认应用浅色，需覆盖）
        self._apply_initial_theme()
        self._connect_signals()
        self._load_config_to_ui()

    # ── 界面构建 ──────────────────────────────────────────

    def _build_central_widget(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧 Navigation Rail
        self._nav_rail = NavigationRail(colors=MaterialColors.light())
        self._nav_rail.selection_changed.connect(self._on_nav_changed)
        main_layout.addWidget(self._nav_rail)

        # 右侧页面栈：Home / Settings
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack, 1)

        # ── Home 页 ─────────────────────────────────────
        self._home_scroll = QScrollArea()
        self._home_scroll.setWidgetResizable(True)
        self._home_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(40, 40, 40, 40)
        self._content_layout.setSpacing(32)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._home_scroll.setWidget(self._content)
        # 监听 home_scroll 视口尺寸变化以同步设置内容最大宽度与
        # Skip 复选框网格列数（避免横向滚动条出现）
        self._home_scroll.viewport().installEventFilter(self)
        self._stack.addWidget(self._home_scroll)

        # ── Settings 页 ─────────────────────────────────
        self._settings_page = SettingsPage(
            colors=MaterialColors.light(), is_dark=self._is_dark
        )
        self._settings_page.theme_change_requested.connect(self._on_theme_change_requested)
        self._settings_page.home_requested.connect(lambda: self._nav_rail.set_selected(0))
        self._settings_scroll = QScrollArea()
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 关键：让滚动区域视口透明，使 SettingsPage 的背景色可见。
        # 这里使用 objectName + ID 选择器限定作用域，避免无差别级联到
        # SettingsPage 及其所有子控件（否则会覆盖 app 级 QSS，导致
        # QWidget/QFrame 背景色失效，卡片显示为透明）。
        self._settings_scroll.viewport().setObjectName("settingsScrollViewport")
        self._settings_scroll.viewport().setStyleSheet(
            "QWidget#settingsScrollViewport { background-color: transparent; }"
        )
        self._settings_scroll.setWidget(self._settings_page)
        # 让 SettingsPage 跟随滚动视口宽度：QScrollArea 在 setWidgetResizable
        # 时仍会使用 widget 的 sizeHint.minimumWidth 作为下界。由于
        # SettingsPage 内部"返回主页"按钮全宽（由 hero widget 撑大），
        # 其 sizeHint 经常超过视口，导致横向裁切。这里设置 maxWidth 让
        # settings page 始终不超出视口，触发响应式断点切换单列布局。
        self._settings_page.setMaximumWidth(
            self._settings_scroll.viewport().width()
        )
        self._settings_scroll.viewport().installEventFilter(self)
        self._stack.addWidget(self._settings_scroll)

        self._build_hero()
        self._build_cards_grid()
        # 初始化 Skip steps 容器、标题与复选框配色（使其与初始主题一致，
        # 避免首次进入时仍为默认浅色样式）
        self._apply_skip_theme(self._settings_page.colors)

    def _build_hero(self) -> None:
        """Hero 区域：大标题 + 描述 + 主按钮"""
        hero = QWidget()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 24, 0, 0)
        hero_layout.setSpacing(24)
        hero_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Arknights Video Pipeline")
        # MD3 Hero 标题：使用 display_large 字体作为基线 + 内联 QSS
        # 覆盖更大的像素尺寸与字重，符合设计规范中 Hero 区域"大号"
        # display_large 标题的视觉强调。
        title.setFont(MaterialTypography().display_large)
        title.setStyleSheet(
            "border: none; background: transparent;"
            " font-size: 48px; font-weight: 600; line-height: 1.15;"
            " letter-spacing: -1.5px;"
        )
        title.setWordWrap(True)
        hero_layout.addWidget(title)

        self._content_layout.addWidget(hero)

    def _build_cards_grid(self) -> None:
        """卡片网格：配置、步骤、进度、日志（支持响应式单列/双列）"""
        self._cards_grid = QGridLayout()
        self._cards_grid.setSpacing(24)
        self._cards_grid.setColumnStretch(0, 1)

        self._config_card = self._build_config_card()
        self._steps_card = self._build_steps_card()

        self._progress_card_widget = MaterialCard("Processing status")
        self._progress_card_widget.add_widget(self._progress_card)

        self._log_card = MaterialCard("Runtime logs")
        # 传入当前主题 colors，避免 LogViewer 内部使用浅色默认色板导致
        # 首次进入深色模式时 [INFO] 等行文字颜色几乎与背景同色而不可见
        self._log_viewer = LogViewer(colors=self._settings_page.colors)
        self._log_viewer.setMinimumHeight(240)
        self._log_card.add_widget(self._log_viewer)

        self._cards_container = QWidget()
        self._cards_container.setLayout(self._cards_grid)
        self._content_layout.addWidget(self._cards_container)

        self._apply_grid_layout(two_column=True)

    def _apply_grid_layout(self, two_column: bool) -> None:
        """应用双列或单列卡片布局"""
        # 移除现有 widget（不删除）
        for i in reversed(range(self._cards_grid.count())):
            item = self._cards_grid.itemAt(i)
            if item and item.widget():
                self._cards_grid.removeWidget(item.widget())

        self._cards_grid.setColumnStretch(0, 1)
        if two_column:
            self._cards_grid.setColumnStretch(1, 1)
            self._cards_grid.addWidget(self._config_card, 0, 0)
            self._cards_grid.addWidget(self._steps_card, 0, 1, 3, 1)
            self._cards_grid.addWidget(self._progress_card_widget, 1, 0)
            self._cards_grid.addWidget(self._log_card, 2, 0)
        else:
            # 单列时清除第二列 stretch
            self._cards_grid.setColumnStretch(1, 0)
            self._cards_grid.addWidget(self._config_card, 0, 0)
            self._cards_grid.addWidget(self._steps_card, 1, 0)
            self._cards_grid.addWidget(self._progress_card_widget, 2, 0)
            self._cards_grid.addWidget(self._log_card, 3, 0)

    def _reflow_skip_checkboxes(self, available_width: int) -> None:
        """根据可用宽度重新排列 Skip 步骤复选框网格的列数

        复选框本身是固定尺寸的（由 MaterialCheckBox 决定），若全部
        横向铺开会撑大所在容器的 minimum width，导致窄屏出现横向
        滚动条。本方法计算每行可容纳多少列并重新插入到 QGridLayout，
        使 5 个复选框在窄屏下自动换行。
        """
        grid = getattr(self, "_skip_grid_layout", None)
        checkboxes = list(getattr(self, "_skip_checkboxes", {}).values())
        if grid is None or not checkboxes:
            return
        if available_width <= 0:
            available_width = 0

        # 计算单个复选框的最大宽度（包含水平 spacing）
        spacing = grid.horizontalSpacing()
        if spacing is None or spacing < 0:
            spacing = 12
        max_cb_w = 0
        for cb in checkboxes:
            hint = cb.sizeHint().width()
            if hint > max_cb_w:
                max_cb_w = hint
        if max_cb_w <= 0:
            max_cb_w = 80  # 兜底值

        # 每行最少 1 列，最多 5 列
        per_col = max_cb_w + spacing
        cols = max(1, min(len(checkboxes), available_width // per_col))

        # 先清空再按新列数重排
        for i in reversed(range(grid.count())):
            item = grid.itemAt(i)
            if item and item.widget():
                grid.removeWidget(item.widget())
        for i, cb in enumerate(checkboxes):
            grid.addWidget(cb, i // cols, i % cols)
        self._last_skip_cols = cols

    def _config_card_content_width(self) -> int:
        """计算当前布局下 Input configuration 卡片的内容可用宽度

        在 2 列布局中，配置卡占据左半列；1 列布局中则占据全部可用宽度。
        该宽度用于驱动 Skip 复选框的列数重排。
        """
        viewport_w = self._home_scroll.viewport().width()
        if viewport_w <= 0:
            return 0
        # 复刻 _content_layout 的左右内边距 40*2
        content_w = max(0, viewport_w - 80)
        two_col = getattr(self, "_last_two_col", False)
        if two_col:
            # 双列：去掉列间距 24 后对半
            return max(0, (content_w - 24) // 2 - 20)  # 20 = 卡片左右内边距
        # 单列
        return max(0, content_w - 20)

    def _apply_skip_theme(self, colors: MaterialColors) -> None:
        """根据当前主题刷新 Skip steps 容器与复选框配色

        主页的 skip_group 原先使用硬编码 ``background-color: #FFFFFF``，
        在深色模式下会形成刺眼的白色块。这里将容器底色改为与卡片
        surface 一致（亮色为白、暗色为 #1C1B1F），标题文字使用
        on_surface_variant，复选框则调用 set_colors() 同步 indicator
        与 label 颜色。
        """
        if getattr(self, "_skip_group", None) is not None:
            self._skip_group.setStyleSheet(
                f"background-color: {colors.surface}; border: none;"
            )
        if getattr(self, "_skip_title", None) is not None:
            self._skip_title.setStyleSheet(
                f"background-color: transparent; border: none;"
                f" color: {colors.on_surface_variant};"
                f" font-weight: 500; font-size: 12px;"
                f" letter-spacing: 0.5px;"
            )
        for cb in getattr(self, "_skip_checkboxes", {}).values():
            cb.set_colors(colors)

    def _build_config_card(self) -> MaterialCard:
        """输入配置卡片（主页）

        只保留主页相关的轻量配置：Background、Style、Skip steps，
        以及运行按钮。视频输入由独立的 ``BatchVideoList`` 卡片承担；
        MAA path、Output、Log level 已迁移到 Settings 页
        （``_build_advanced_card``），由 MainWindow 通过 settings_page
        共享同一组控件实例，避免双源状态不同步。
        """
        card = MaterialCard("Input configuration")
        layout = QVBoxLayout()
        layout.setSpacing(16)

        self._bg_selector = FileSelector(
            mode=FileSelector.MODE_OPEN_FILE,
            label="Background",
            placeholder="Background image (style1)",
        )
        self._bg_selector.set_filter(
            "Image files (*.jpg *.jpeg *.png *.bmp *.webp);;All files (*.*)"
        )
        layout.addWidget(self._bg_selector)

        self._style_combo = QComboBox()
        self._style_combo.addItems(["style1", "style2"])
        layout.addLayout(self._labeled_row("Style", self._style_combo))

        # 跳过步骤：与上方 input rows 节奏一致的 sub-section
        # 背景与标题颜色需跟随主题切换（深色模式下不能继续用白色），
        # 因此在 _apply_skip_theme() 中按当前主题刷新其内联样式。
        skip_group = QWidget()
        skip_group.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        skip_layout = QVBoxLayout(skip_group)
        skip_layout.setContentsMargins(0, 0, 0, 0)
        skip_layout.setSpacing(10)

        skip_title = QLabel("Skip steps")
        skip_title.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, False
        )
        skip_layout.addWidget(skip_title)
        self._skip_group = skip_group
        self._skip_title = skip_title

        skip_flow = QGridLayout()
        skip_flow.setContentsMargins(0, 0, 0, 0)
        skip_flow.setHorizontalSpacing(20)
        skip_flow.setVerticalSpacing(8)
        self._skip_checkboxes: dict[str, MaterialCheckBox] = {}
        for key, label in [
            ("copilot", "MAA"),
            ("formation", "Formation"),
            ("actions", "Actions"),
            ("track", "Track"),
            ("compose", "Compose"),
        ]:
            # MD3 复选框：使用 MaterialCheckBox（自绘 indicator + 对勾），
            # 绕开 PyQt ``QCheckBox::indicator`` 不支持 ``image: url()`` 替换
            # 内置渲染的限制；同时摆脱全局 QSS 给 ``QCheckBox::indicator``
            # 设置 ``background-color: primary`` 造成的"全是紫方块"问题。
            cb = MaterialCheckBox(label, colors=self._settings_page.colors)
            cb.setToolTip(f"Skip {key} step")
            self._skip_checkboxes[key] = cb
            # 初始按单行排列（每列一个），_reflow_skip_checkboxes 会
            # 根据可用宽度重新调整列数，使窄屏下不至于撑出横向滚动条
            skip_flow.addWidget(cb, 0, 0)
        self._skip_grid_layout = skip_flow
        skip_layout.addLayout(skip_flow)
        layout.addWidget(skip_group)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        self._run_btn = MaterialButton("Start", variant=MaterialButton.VARIANT_FILLED)
        self._cancel_btn = MaterialButton("Cancel", variant=MaterialButton.VARIANT_OUTLINED)
        self._cancel_btn.setEnabled(False)

        btn_layout.addWidget(self._run_btn)
        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        card.add_layout(layout)
        return card

    def _build_steps_card(self) -> MaterialCard:
        """批量视频文件列表卡片（取代原 Pipeline steps 面板）"""
        card = MaterialCard("Video files")
        self._batch_list = BatchVideoList(colors=self._settings_page.colors)
        card.add_widget(self._batch_list)
        return card

    @staticmethod
    def _labeled_row(label: str, widget: QWidget) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(12)
        lbl = QLabelEx(label)
        lbl.setFixedWidth(72)
        layout.addWidget(lbl)
        layout.addWidget(widget, 1)
        return layout

    # ── 信号连接 ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        # 配置同步
        self._batch_list.video_paths_changed.connect(self._on_video_paths_changed)
        self._bg_selector.path_changed.connect(self._config.set_background_image)
        # MAA / Output / Log level 通过 SettingsPage 公开信号连接
        sp = self._settings_page
        sp.maa_path_changed.connect(self._config.set_maa_path)
        sp.output_dir_changed.connect(self._config.set_output_dir)
        sp.log_level_changed.connect(self._config.set_log_level)
        sp.config_reset.connect(self._on_config_reset)
        # 性能配置（多线程开关 / 最大并发数）
        sp.multithreading_changed.connect(self._config.set_multithreading)
        sp.max_concurrent_changed.connect(self._config.set_max_concurrent)
        self._style_combo.currentTextChanged.connect(self._on_style_changed)

        for key, cb in self._skip_checkboxes.items():
            cb.toggled.connect(self._on_skip_changed)

        # 按钮
        self._run_btn.clicked.connect(self._on_run)
        self._cancel_btn.clicked.connect(self._on_cancel)

        # 服务信号（批量原生，带文件索引）
        self._service.file_started.connect(self._batch_list.set_file_running)
        self._service.file_progress.connect(self._batch_list.set_file_progress)
        self._service.file_finished.connect(
            lambda idx, success, _report: self._batch_list.set_file_finished(idx, success)
        )
        self._service.overall_progress.connect(self._progress_card.set_progress)
        self._service.log_emitted.connect(self._log_viewer.append)
        self._service.batch_finished.connect(self._on_batch_finished)

    # ── 配置加载与同步 ────────────────────────────────────

    def _load_config_to_ui(self) -> None:
        self._config.load()
        # 加载期间阻塞 MainWindow 自有控件信号，避免 setChecked/setText
        # 触发回写配置。SettingsPage 的控件由其公开方法内部自行阻塞信号。
        controls = [
            self._bg_selector,
            self._style_combo,
        ]
        controls.extend(cb for cb in self._skip_checkboxes.values())
        for ctrl in controls:
            ctrl.blockSignals(True)
        # 阻塞批量列表信号，避免 add_paths 回写配置
        self._batch_list.blockSignals(True)
        try:
            self._bg_selector.set_path(self._config.background_image())

            style = self._config.style()
            index = self._style_combo.findText(style)
            if index >= 0:
                self._style_combo.setCurrentIndex(index)
            self._on_style_changed(style)

            skip_steps = self._config.skip_steps()
            for key, cb in self._skip_checkboxes.items():
                cb.setChecked(key in skip_steps)

            # 从配置恢复视频路径列表
            self._batch_list.clear()
            self._batch_list.add_paths(self._config.video_paths())
        finally:
            for ctrl in controls:
                ctrl.blockSignals(False)
            self._batch_list.blockSignals(False)
        # SettingsPage 控件通过公开方法设置（内部阻塞信号避免回写）
        sp = self._settings_page
        sp.set_maa_path(self._config.maa_path())
        sp.set_output_dir(self._config.output_dir())
        sp.set_log_level(self._config.log_level())
        # 性能配置：从 pipeline.json 恢复多线程开关与最大并发数
        sp.set_multithreading(self._config.multithreading())
        sp.set_max_concurrent(self._config.max_concurrent())

    def _on_style_changed(self, style: str) -> None:
        self._config.set_style(style)
        is_style1 = style == "style1"
        self._bg_selector.setEnabled(is_style1)
        if not is_style1:
            self._bg_selector.set_path("")

    def _on_config_reset(self, generated: list) -> None:
        """配置文件重置完成后的同步处理

        当用户在 Settings 页点击"生成默认配置"且 pipeline 配置生成成功时，
        ``SettingsPage`` 会发出 ``config_reset`` 信号。本方法负责：

        1. 重新加载磁盘上的 pipeline.json，使内存中的 ConfigProxy
           与重置后的文件保持一致（否则在 ``closeEvent`` 中调用
           ``self._config.save()`` 会把重置前的旧值写回文件）。
        2. 刷新共享控件（MAA/Output 路径、Log level、Style）的显示，
           阻塞控件信号以避免刷新过程触发回写配置。
        3. 不修改与重置无关的字段（如 video_paths、skip_steps），
           保证其他路径设置功能正常使用。
        """
        if "pipeline" not in generated:
            return

        # 1. 重新从磁盘加载配置，让内存 pipeline 与刚写入的默认文件一致
        self._config.load()

        # 2. 刷新 Style（MainWindow 自有控件，需阻塞信号）
        self._style_combo.blockSignals(True)
        try:
            style = self._config.style()
            index = self._style_combo.findText(style)
            if index >= 0:
                self._style_combo.setCurrentIndex(index)
            self._on_style_changed(style)
        finally:
            self._style_combo.blockSignals(False)

        # 3. 刷新 SettingsPage 控件（公开方法内部阻塞信号避免回写）
        sp = self._settings_page
        sp.set_maa_path(self._config.maa_path())
        sp.set_output_dir(self._config.output_dir())
        sp.set_log_level(self._config.log_level())
        # 性能配置同步刷新（重置后恢复默认值 multithreading=false, max_concurrent=1）
        sp.set_multithreading(self._config.multithreading())
        sp.set_max_concurrent(self._config.max_concurrent())

    def _on_skip_changed(self) -> None:
        steps = {key for key, cb in self._skip_checkboxes.items() if cb.isChecked()}
        self._config.set_skip_steps(steps)

    def _on_video_paths_changed(self, paths: list) -> None:
        """批量列表变化时同步到配置（持久化）并刷新 Start 按钮可用态"""
        self._config.set_video_paths(list(paths))
        if not self._service.is_running():
            self._run_btn.setEnabled(bool(paths))

    def _on_nav_changed(self, index: int) -> None:
        # 0=Home, 1=Settings, 2=Info（仅弹出关于对话框，不切换页面）
        if index == 0:
            self._current_page = 0
            self._stack.setCurrentWidget(self._home_scroll)
        elif index == 1:
            self._current_page = 1
            # 进入设置页时同步主题开关状态（不触发信号）
            self._settings_page.set_dark(self._is_dark)
            self._stack.setCurrentWidget(self._settings_scroll)
        elif index == 2:
            self._show_about()
            # 恢复到原页面选中态，避免 Info 误高亮
            self._nav_rail.blockSignals(True)
            self._nav_rail.set_selected(self._current_page)
            self._nav_rail.blockSignals(False)

    # ── 操作处理 ──────────────────────────────────────────

    def _on_run(self) -> None:
        paths = self._batch_list.video_paths()
        if not paths:
            self._show_warning("No video files", "请先添加至少一个视频文件")
            return

        errors = self._service.validate_batch(paths)
        if errors:
            self._show_warning("Input validation failed", "\n".join(errors))
            return

        self._batch_list.reset_states()
        self._progress_card.reset()
        self._log_viewer.clear_logs()
        self._set_running_ui(True)
        if not self._service.run_pipeline(paths):
            self._set_running_ui(False)

    def _on_cancel(self) -> None:
        self._service.cancel_pipeline()
        self._cancel_btn.setEnabled(False)

    def _on_batch_finished(self, success_count: int, total: int,
                           cancelled: bool) -> None:
        self._set_running_ui(False)
        self._progress_card.set_batch_finished(success_count, total, cancelled)
        if not cancelled and success_count < total:
            self._show_critical(
                "Processing completed with errors",
                f"{total - success_count} 个文件处理失败，请查看日志。",
            )

    def _set_running_ui(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._batch_list.set_editable(not running)
        self._bg_selector.setEnabled(not running and self._style_combo.currentText() == "style1")
        self._style_combo.setEnabled(not running)
        # MAA / Output / Log level 通过 SettingsPage 公开方法统一控制
        self._settings_page.set_advanced_enabled(not running)
        # 性能配置（多线程开关 / 最大并发数）运行期间禁止修改
        self._settings_page.set_performance_enabled(not running)
        for cb in self._skip_checkboxes.values():
            cb.setEnabled(not running)

    def _on_theme_change_requested(self, dark: bool) -> None:
        """设置页主题开关触发：应用主题并同步设置页配色"""
        self._toggle_theme(dark)
        colors = MaterialColors.dark() if dark else MaterialColors.light()
        self._settings_page.set_colors(colors)
        # 持久化到独立 GUI 配置（config/gui.json），与 pipeline 配置完全解耦
        self._gui_config.set_theme("dark" if dark else "light")

    def _apply_initial_theme(self) -> None:
        """启动时按独立 GUI 配置（config/gui.json）中的主题刷新界面与标题栏

        ``create_application`` 默认应用浅色主题；若配置为深色，需在此
        覆盖 QSS、卡片表面色与标题栏。仅当 ``self._is_dark`` 为 True
        时执行完整切换；浅色时仅尝试应用标题栏（QSS 已是浅色无需重刷）。
        """
        if self._is_dark:
            self._toggle_theme(True)
        else:
            # 浅色：QSS 已由 create_application 应用，仅尝试标题栏
            apply_titlebar_theme(self, False)

    def _toggle_theme(self, dark: bool) -> None:
        self._is_dark = dark
        colors = MaterialColors.dark() if dark else MaterialColors.light()
        style = MaterialStyle(colors=colors, typography=MaterialTypography())
        app = QApplication.instance()
        if app is not None:
            style.apply(app)
        # 更新导航栏、设置页与辅助文字颜色
        self._nav_rail.set_colors(colors)
        self._settings_page.set_colors(colors)
        # 同步刷新主页所有卡片的表面色（paintEvent 自绘模式需手动更新）
        for card in (
            getattr(self, "_config_card", None),
            getattr(self, "_steps_card", None),
            getattr(self, "_progress_card_widget", None),
            getattr(self, "_log_card", None),
            # 内层 ProgressCard（自绘 surface 同样需要刷新，
            # 否则在深色模式下仍为白色背景，与外层卡片形成色块差）
            getattr(self, "_progress_card", None),
        ):
            if card is not None:
                card.set_surface_color(colors.surface)
        # 同步刷新主页 FileSelector 内联样式（输入框 + 浏览按钮）
        if getattr(self, "_bg_selector", None) is not None:
            self._bg_selector.set_colors(colors)
        # 同步刷新批量视频列表配色（行/进度条/状态图标按主题切换）
        if getattr(self, "_batch_list", None) is not None:
            self._batch_list.set_colors(colors)
        # 同步刷新 Skip steps 容器、标题与复选框配色（修复深色模式下
        # 硬编码白色背景导致的刺眼白块，以及复选框 indicator 颜色不更新）
        self._apply_skip_theme(colors)
        # 同步刷新日志查看器配色：LogViewer 内部按行重新染字符，
        # 无需清空历史日志；解决深色模式下 [INFO] 文字几乎不可见问题
        if getattr(self, "_log_viewer", None) is not None:
            self._log_viewer.set_colors(colors)
        # 标题栏放在最后：QSS 重计算（~200ms）+ 自定义组件刷新完成后，
        # 标题栏与主界面在同一帧切换，避免标题栏先变/主界面后变的视觉不同步。
        # apply_titlebar_theme 含 DwmFlush（~15ms），放在最后让 DWM 合成
        # 新帧时主界面已完成重绘，标题栏与主界面同时上屏。
        apply_titlebar_theme(self, dark)

    def _show_about(self) -> None:
        # 使用自定义 AboutDialog 而非 QMessageBox.about()：
        # 后者在我们的 Material 主题下 OK 按钮的样式被裁切/遮挡。
        from arknights_video_pipeline.gui.components.about_dialog import AboutDialog
        dlg = AboutDialog(colors=self._settings_page.colors, parent=self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.exec()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # 首次 show 后窗口句柄（HWND）才稳定可用，此时应用标题栏主题
        if not self._titlebar_applied:
            self._titlebar_applied = True
            apply_titlebar_theme(self, self._is_dark)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        # 响应式：窄屏折叠导航栏
        self._nav_rail.set_compact(width < 960)
        # 响应式：卡片网格在窄屏时切换为单列（仅在断点变化时重建，避免卡顿）
        if getattr(self, "_cards_grid", None) is not None:
            nav_width = 56 if width < 960 else 88
            content_width = max(0, width - nav_width - 80)  # 80 = 左右内边距 40*2
            new_two_col = content_width >= 720
            if new_two_col != getattr(self, "_last_two_col", None):
                self._last_two_col = new_two_col
                self._apply_grid_layout(two_column=new_two_col)
            # 重新排列 Skip 复选框网格列数，避免窄屏下 5 个固定宽度
            # 复选框横向铺开撑出整个内容（导致 home_scroll 出现横滚条）
            skip_w = self._config_card_content_width()
            if skip_w > 0:
                self._reflow_skip_checkboxes(skip_w)
        # 限制 home 内容宽度不超过视口，避免内容 sizeHint 超过视口时
        # 触发横向滚动条
        if getattr(self, "_home_scroll", None) is not None and getattr(
            self, "_content", None
        ) is not None:
            vw = self._home_scroll.viewport().width()
            if vw > 0 and self._content.maximumWidth() != vw:
                self._content.setMaximumWidth(vw)
        # 同步 SettingsPage 最大宽度，让其跟随滚动视口（避免横向裁切）
        if getattr(self, "_settings_scroll", None) is not None:
            vw = self._settings_scroll.viewport().width()
            if vw > 0 and self._settings_page.maximumWidth() != vw:
                self._settings_page.setMaximumWidth(vw)

    def eventFilter(self, obj, event) -> bool:
        # 监听 home/settings 滚动视口的尺寸变化（窗口尺寸变化时触发），
        # 同步更新对应页面的最大宽度，确保响应式断点正确切换。
        if event.type() == QEvent.Type.Resize:
            if (
                getattr(self, "_home_scroll", None) is not None
                and obj is self._home_scroll.viewport()
            ):
                vw = self._home_scroll.viewport().width()
                if vw > 0 and getattr(self, "_content", None) is not None:
                    if self._content.maximumWidth() != vw:
                        self._content.setMaximumWidth(vw)
                # 视口变化时同步重新排列 Skip 复选框
                skip_w = self._config_card_content_width()
                if skip_w > 0:
                    self._reflow_skip_checkboxes(skip_w)
            elif (
                getattr(self, "_settings_scroll", None) is not None
                and obj is self._settings_scroll.viewport()
            ):
                vw = self._settings_scroll.viewport().width()
                if vw > 0:
                    self._settings_page.setMaximumWidth(vw)
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:
        if self._service.is_running():
            confirmed = self._show_confirm(
                "Confirm exit",
                "Pipeline is running. Are you sure you want to exit?",
                confirm_text="Exit",
            )
            if confirmed:
                self._service.cancel_pipeline()
                # 等待 worker 线程退出，避免 QThread 被销毁时仍在运行
                self._service.wait_for_shutdown(timeout_ms=5000)
                self._gui_config.save()
                self._config.save()
                event.accept()
            else:
                event.ignore()
        else:
            self._gui_config.save()
            self._config.save()
            event.accept()

    # ── Material 消息对话框快捷方法 ─────────────────────
    # 取代 QMessageBox，避免 OK / Yes / No 按钮被默认 QSS 裁切/遮挡
    def _show_info(self, title: str, text: str) -> None:
        from arknights_video_pipeline.gui.components.message_dialog import InfoDialog
        dlg = InfoDialog(title, text, colors=self._settings_page.colors, parent=self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.exec()

    def _show_warning(self, title: str, text: str) -> None:
        from arknights_video_pipeline.gui.components.message_dialog import WarningDialog
        dlg = WarningDialog(title, text, colors=self._settings_page.colors, parent=self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.exec()

    def _show_critical(self, title: str, text: str) -> None:
        from arknights_video_pipeline.gui.components.message_dialog import CriticalDialog
        dlg = CriticalDialog(title, text, colors=self._settings_page.colors, parent=self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.exec()

    def _show_confirm(self, title: str, text: str, confirm_text: str = "Confirm") -> bool:
        from arknights_video_pipeline.gui.components.message_dialog import ConfirmDialog
        dlg = ConfirmDialog(
            title, text, confirm_text=confirm_text, cancel_text="Cancel",
            colors=self._settings_page.colors, parent=self,
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        return dlg.exec() == ConfirmDialog.CONFIRMED


class QLabelEx(QLabel):
    """扩展标签，支持加粗与字号快速设置"""

    def __init__(self, text: str = "", bold: bool = False, size: int = 0,
                 parent=None) -> None:
        super().__init__(text, parent)
        style = "border: none; background: transparent;"
        if bold:
            style += " font-weight: 500;"
        if size:
            style += f" font-size: {size}px;"
        self.setStyleSheet(style)
