"""
gui.main_window - 主窗口

参考 Material Design 官网布局重新设计：
- 左侧 Navigation Rail
- 右侧 Hero 区域 + 卡片网格内容区
- 淡紫背景、深紫主色、白色卡片、大标题排版
- 响应式：窄屏折叠导航栏，卡片自适应列数
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEvent, QObject, QPointF, QPropertyAnimation, QTimer, Qt,
)
from PyQt6.QtGui import QCloseEvent, QResizeEvent, QShowEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QComboBox, QGraphicsOpacityEffect,
    QApplication, QLabel, QFrame, QStackedWidget,
)

from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion

from arknights_video_pipeline.gui.components import (
    AboutPage, BatchVideoList, FileSelector, LogViewer, MaterialButton, MaterialCard,
    MaterialCheckBox, MaterialFab, MaterialTextField, NavigationBar, NavigationRail,
    PageHeader, ProgressCard, SettingsPage, ToolsPage,
)
from arknights_video_pipeline.gui.i18n import init_i18n, i18n, tr
from arknights_video_pipeline.gui.theme import (
    Grid, GuiConfig, Layout, Margin, MaterialColors, MaterialTypography, Space,
    WindowSizeClass, apply_titlebar_theme, set_text_color, theme_controller,
)
from arknights_video_pipeline.service import ConfigProxy, PipelineService


class MainWindow(QMainWindow):
    """主窗口"""

    # SettingsPage.CONFIG_TYPES key → ConfigProxy 子配置名称
    # 用于 _on_config_reset 时按 key 重新加载对应子配置
    _KEY_TO_SUB_CONFIG: dict[str, str] = {
        "formation": "formation",
        "actions": "actions",
        "track": "track",
        "compose": "style1",
        "compose_style2": "style2",
    }

    def __init__(self, config_proxy: ConfigProxy, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config_proxy
        self._service = PipelineService(config_proxy, parent=self)
        # GUI 偏好独立管理（config/gui.json），与 pipeline 配置完全解耦
        self._gui_config = GuiConfig(parent=self)
        self._is_dark = self._gui_config.is_dark_theme()
        # 待后台校验完成后启动的批次输入（_on_run 暂存，
        # _on_validation_finished 消费）
        self._pending_run_paths: list[str] = []
        self._pending_run_json_paths: list[str | None] = []
        # UI 运行态（与 service.is_running() 独立）：点击"开始"后立即置位，
        # 避免后台线程启动前的空档里 FAB 仍然可见可点。
        self._ui_running = False
        # 标记首次 showEvent 是否已处理（用于在窗口句柄就绪后应用标题栏主题）
        self._titlebar_applied = False

        # 初始化 i18n 单例（必须在构建 widget 之前，使 widget 可连接 language_changed）
        init_i18n(language=self._gui_config.language(), parent=self)

        self.setWindowTitle(tr("app.title"))
        # 最小尺寸对齐 MD3 compact 档（< 600）：440dp 是设置页最窄卡片
        # （字段行 180 + 16 + 160 + 卡片内边距 32 = 388）加紧凑页边距 32 后
        # 不产生横向滚动条的下限；仍远小于 600，窄窗可用而不是被卡在 720。
        self.setMinimumSize(440, 480)
        self.resize(1000, 700)

        self._progress_card = ProgressCard()

        self._build_central_widget()
        # 启动时按配置主题应用（create_application 已装浅色 QSS + 调色板，
        # 配色一致时 ThemeController 会跳过重绘）
        self._apply_initial_theme()
        self._connect_signals()
        self._load_config_to_ui()
        # 语言切换时刷新主页所有静态文本
        i18n().language_changed.connect(self._retranslate)

    # ── 界面构建 ──────────────────────────────────────────

    def _build_central_widget(self) -> None:
        central = QWidget()
        central.setObjectName("appShell")
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(central)
        self._central = central
        # 外壳：侧边 rail + 页面栈；compact 档改为底部导航条
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # 左侧 Navigation Rail（扩宽档显示图标 + 标签，中等档仅图标）
        self._nav_rail = NavigationRail(colors=theme_controller().colors())
        self._nav_rail.selection_changed.connect(self._on_nav_changed)
        body_layout.addWidget(self._nav_rail)

        # 右侧页面栈：Home / Settings / Tools / About
        self._stack = QStackedWidget()
        self._stack.setObjectName("pageStack")
        self._stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        body_layout.addWidget(self._stack, 1)
        shell.addWidget(body, 1)

        # compact 档底部导航（与 rail 共用 selection_changed 语义）
        self._nav_bar = NavigationBar(colors=theme_controller().colors())
        self._nav_bar.selection_changed.connect(self._on_nav_changed)
        self._nav_bar.hide()
        shell.addWidget(self._nav_bar)

        # ── Home 页 ─────────────────────────────────────
        self._home_scroll = QScrollArea()
        self._home_scroll.setWidgetResizable(True)
        self._home_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 内容列最大宽度 1120dp 居中：超宽屏上不把卡片拉成一条
        self._home_scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._content = QWidget()
        self._content.setObjectName("homePage")
        self._content.setMaximumWidth(Grid.MAX_CONTENT_WIDTH)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(
            Margin.EXPANDED, Margin.EXPANDED, Margin.EXPANDED, Margin.EXPANDED
        )
        self._content_layout.setSpacing(Space.XXL)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._home_scroll.setWidget(self._content)
        # 监听 home_scroll 视口尺寸变化以同步设置内容最大宽度与
        # Skip 复选框网格列数（避免横向滚动条出现）
        self._home_scroll.viewport().installEventFilter(self)
        self._stack.addWidget(self._home_scroll)

        # ── Settings 页 ─────────────────────────────────
        self._settings_page = SettingsPage(
            colors=theme_controller().colors(), is_dark=self._is_dark
        )
        self._settings_page.theme_change_requested.connect(self._on_theme_change_requested)
        self._settings_page.home_requested.connect(lambda: self._nav_rail.set_selected(0))
        self._settings_scroll = QScrollArea()
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._settings_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        # 设置页是表单，单列布局并限制在较窄的内容宽度，避免双列压缩
        # 控件宽度造成文件名/路径截断，也避免同排卡片高度不一致
        self._settings_page.setMaximumWidth(Grid.SETTINGS_MAX_WIDTH)
        self._settings_scroll.setWidget(self._settings_page)
        self._stack.addWidget(self._settings_scroll)

        # ── Info (About) 页 ──────────────────────────────
        self._about_page = AboutPage(colors=theme_controller().colors())
        self._about_scroll = QScrollArea()
        self._about_scroll.setWidgetResizable(True)
        self._about_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._about_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._about_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self._about_page.setMaximumWidth(Grid.MAX_CONTENT_WIDTH)
        self._about_scroll.setWidget(self._about_page)
        self._stack.addWidget(self._about_scroll)

        # ── Tools 页 ──────────────────────────────────────
        self._tools_page = ToolsPage(
            config_proxy=self._config, colors=theme_controller().colors()
        )
        # 应用工具配置成功后同步设置页子配置字段行
        self._tools_page.tool_config_applied.connect(
            self._on_tool_config_applied
        )
        self._tools_scroll = QScrollArea()
        self._tools_scroll.setWidgetResizable(True)
        self._tools_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._tools_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self._tools_page.setMaximumWidth(Grid.MAX_CONTENT_WIDTH)
        self._tools_scroll.setWidget(self._tools_page)
        self._stack.addWidget(self._tools_scroll)

        self._build_hero()
        self._build_cards_grid()
        # 初始化 Skip steps 容器、标题与复选框配色（使其与初始主题一致，
        # 避免首次进入时仍为默认浅色样式）
        self._apply_skip_theme(self._settings_page.colors)

        # 主页主操作锚点：MD3 extended FAB（浮于内容右下，不进滚动区）
        self._fab = MaterialFab(
            "add", tr("batch.add_videos"), extended=True, parent=central
        )
        self._fab.setToolTip(tr("batch.add_videos"))
        self._fab.clicked.connect(self._on_fab_clicked)
        self._fab.adjustSize()
        self._fab.raise_()

    def _build_hero(self) -> None:
        """页面头：标题 + 说明，字号随窗口尺寸类别降级"""
        self._header = PageHeader(
            tr("home.title"),
            tr("home.subtitle"),
            colors=theme_controller().colors(),
        )
        self._content_layout.addWidget(self._header)

    def _on_fab_clicked(self) -> None:
        """FAB：打开批量列表的"添加视频"流程"""
        self._batch_list.open_add_dialog()

    def _position_fab(self) -> None:
        """把 FAB 定位到内容列右下角（compact 档避让底部导航条）

        使用主页内容列（最大宽度 1120 居中）的右边缘而不是窗口右边缘，
        超宽屏下 FAB 仍贴近内容，不会被甩到屏幕角落。
        """
        fab = getattr(self, "_fab", None)
        central = getattr(self, "_central", None)
        content = getattr(self, "_content", None)
        scroll = getattr(self, "_home_scroll", None)
        if fab is None or central is None or content is None or scroll is None:
            return
        viewport = scroll.viewport()
        viewport_rect = viewport.rect()
        viewport_top_left = viewport.mapTo(central, QPointF(0, 0))
        left = content.mapTo(central, QPointF(0, 0)).x()
        # 内容列窄于视口时用内容右边缘；否则退回到视口右边缘
        content_right = left + content.width()
        if content.width() >= viewport_rect.width():
            content_right = viewport_top_left.x() + viewport_rect.width()
        # 视口本身已经位于底部导航条上方，无需再减一次 NAV_BAR 高度
        bottom = viewport_top_left.y() + viewport_rect.height()
        margin = Space.XL
        x = content_right - fab.width() - margin
        y = bottom - fab.height() - margin
        fab.move(max(margin, int(x)), max(margin, int(y)))
        fab.raise_()

    def _schedule_fab_position(self) -> None:
        """布局完成后再定位 FAB（构造 / resize 期间几何尚未稳定）"""
        QTimer.singleShot(0, self._position_fab)

    def _build_cards_grid(self) -> None:
        """卡片网格：输入配置 + 视频队列（左右两列）、状态与日志（通栏）"""
        self._cards_grid = QGridLayout()
        # 去掉 QGridLayout 的默认 9px 内边距：卡片应与页面内容列（32dp
        # 页边距）左对齐，而不是再缩进 9px
        self._cards_grid.setContentsMargins(0, 0, 0, 0)
        self._cards_grid.setSpacing(Layout.CARD_GAP)
        self._cards_grid.setColumnStretch(0, 5)
        self._cards_grid.setColumnStretch(1, 4)

        self._config_card = self._build_config_card()
        self._steps_card = self._build_steps_card()

        self._progress_card_widget = MaterialCard(tr("home.processing_status"))
        self._progress_card_widget.add_widget(self._progress_card)

        self._log_card = MaterialCard(tr("home.runtime_logs"))
        # 传入当前主题 colors，避免 LogViewer 内部使用浅色默认色板导致
        # 首次进入深色模式时 [INFO] 等行文字颜色几乎与背景同色而不可见
        self._log_viewer = LogViewer(colors=self._settings_page.colors)
        self._log_viewer.setMinimumHeight(240)
        self._log_card.add_widget(self._log_viewer)

        self._cards_container = QWidget()
        self._cards_container.setObjectName("transparentPane")
        self._cards_container.setLayout(self._cards_grid)
        self._content_layout.addWidget(self._cards_container)
        # 底部留白：滚到底时最后一张卡片不被右下角 FAB 压住
        self._content_layout.addSpacing(Space.XXXL + Space.XXL)

        self._apply_grid_layout(two_column=True)

    def _apply_grid_layout(self, two_column: bool) -> None:
        """应用双列或单列卡片布局

        双列：输入配置 | 视频队列；处理状态与运行日志通栏，避免右列被
        拉成一条贯穿三行的空白卡片。
        """
        for i in reversed(range(self._cards_grid.count())):
            item = self._cards_grid.itemAt(i)
            if item and item.widget():
                self._cards_grid.removeWidget(item.widget())

        self._last_two_col = two_column
        self._cards_grid.setColumnStretch(0, 5)
        if two_column:
            self._cards_grid.setColumnStretch(1, 4)
            # 双列首行两张卡不加 AlignTop：填满各自列宽，并与行高一致
            # （队列卡随配置卡同高，列表区多得约 80dp 可视高度）
            self._cards_grid.addWidget(self._config_card, 0, 0)
            self._cards_grid.addWidget(self._steps_card, 0, 1)
            self._cards_grid.addWidget(self._progress_card_widget, 1, 0, 1, 2)
            self._cards_grid.addWidget(self._log_card, 2, 0, 1, 2)
        else:
            self._cards_grid.setColumnStretch(1, 0)
            # 单列：所有卡片按自身内容高度排列，避免被网格纵向拉伸
            for row, card in enumerate((
                self._config_card,
                self._steps_card,
                self._progress_card_widget,
                self._log_card,
            )):
                self._cards_grid.addWidget(card, row, 0, Qt.AlignmentFlag.AlignTop)

    def _reflow_skip_checkboxes(self, available_width: int) -> None:
        """根据可用宽度重新排列 Skip 步骤复选框网格的列数

        每个列宽统一取"最宽复选框 + 间距"，避免各列按自身文字宽度收缩，
        出现"第一行三列、第二行两列且缩进不齐"的参差感。
        """
        grid = getattr(self, "_skip_grid_layout", None)
        checkboxes = list(getattr(self, "_skip_checkboxes", {}).values())
        if grid is None or not checkboxes:
            return
        if available_width <= 0:
            available_width = 0

        spacing = grid.horizontalSpacing()
        if spacing is None or spacing < 0:
            spacing = Space.M
        max_cb_w = max((cb.sizeHint().width() for cb in checkboxes), default=80)
        if max_cb_w <= 0:
            max_cb_w = 80

        # 每行最少 1 列，最多 3 列；列数按"n 列 + (n-1) 个间距"精确计算，
        # 避免 3 列时总宽超出可用宽度、逼出横向滚动条
        per_col = max_cb_w + spacing
        cols = max(1, min(3, (available_width + spacing) // per_col))
        self._last_skip_cols = cols

        for i in reversed(range(grid.count())):
            item = grid.itemAt(i)
            if item and item.widget():
                grid.removeWidget(item.widget())
        for i, cb in enumerate(checkboxes):
            grid.addWidget(
                cb,
                i // cols,
                i % cols,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        # 先把所有列（含历史遗留的空列）的最小宽度与伸展清零，再只为
        # 当前使用的列设置统一列宽：QGridLayout 不会删除空列，残留的
        # columnMinimumWidth 会把卡片最小宽度越撑越大（英文界面尤甚）
        for column in range(grid.columnCount()):
            grid.setColumnMinimumWidth(column, 0)
            grid.setColumnStretch(column, 0)
        for column in range(cols):
            grid.setColumnMinimumWidth(column, max_cb_w)
        grid.setColumnStretch(cols, 1)

    def _config_card_content_width(self) -> int:
        """当前布局下输入配置卡片的内容可用宽度（驱动 Skip 复选框重排）

        以滚动视口宽度（即时更新）推算，而不是读卡片自身的 ``width()``：
        resize 期间卡片几何可能还是旧值，会保留上一次的列数并撑出横向滚动条。
        """
        viewport_w = self._home_scroll.viewport().width()
        if viewport_w <= 0:
            return 0
        margin = Margin.page(getattr(self, "_size_class", WindowSizeClass.EXPANDED))
        content_w = max(0, viewport_w - 2 * margin)
        if getattr(self, "_last_two_col", False):
            content_w = (content_w - Layout.CARD_GAP) // 2
        return max(0, content_w - 2 * Space.L)

    def _apply_skip_theme(self, colors: MaterialColors) -> None:
        """根据当前主题刷新 Skip steps 容器与复选框配色

        容器保持透明（让内容直接落在卡片表面上），标题使用
        ``label_large``（14/500）+ ``on_surface_variant``；复选框各自订阅
        主题信号，这里只负责标题。
        """
        if getattr(self, "_skip_title", None) is not None:
            title = self._skip_title
            title.setFont(MaterialTypography().font("label_large"))
            # 文字色走 QPalette：逐只 setStyleSheet 会新建 QStyleSheetStyle
            # 并触发 polish，是主题切换卡顿的来源之一
            set_text_color(title, colors.on_surface_variant)
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
        card = MaterialCard(tr("home.input_config"))
        layout = QVBoxLayout()
        layout.setSpacing(Space.L)

        self._bg_selector = FileSelector(
            mode=FileSelector.MODE_OPEN_FILE,
            label=tr("home.background"),
            placeholder=tr("home.background_placeholder"),
        )
        self._bg_selector.set_filter(
            "Image files (*.jpg *.jpeg *.png *.bmp *.webp);;All files (*.*)"
        )
        layout.addWidget(self._bg_selector)

        self._style_combo = QComboBox()
        self._style_combo.addItems(["style1", "style2"])
        # 与其他字段一致：MD3 描边字段 + 浮动标签（不再用固定宽度左标签）
        self._style_field = MaterialTextField(
            self._style_combo,
            label=tr("home.style"),
            colors=theme_controller().colors(),
        )
        layout.addWidget(self._style_field)

        # 跳过步骤：与上方 input rows 节奏一致的 sub-section
        # 背景与标题颜色需跟随主题切换（深色模式下不能继续用白色），
        # 因此在 _apply_skip_theme() 中按当前主题刷新其内联样式。
        skip_group = QWidget()
        skip_group.setObjectName("transparentPane")
        skip_layout = QVBoxLayout(skip_group)
        skip_layout.setContentsMargins(0, 0, 0, 0)
        skip_layout.setSpacing(Space.M)

        skip_title = QLabel(tr("home.skip_steps"))
        skip_title.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, False
        )
        skip_layout.addWidget(skip_title)
        self._skip_group = skip_group
        self._skip_title = skip_title

        skip_flow = QGridLayout()
        skip_flow.setContentsMargins(0, 0, 0, 0)
        skip_flow.setHorizontalSpacing(Space.L)
        skip_flow.setVerticalSpacing(Space.S)
        self._skip_checkboxes: dict[str, MaterialCheckBox] = {}
        for key, label in [
            ("copilot", tr("home.skip.copilot")),
            ("formation", tr("home.skip.formation")),
            ("actions", tr("home.skip.actions")),
            ("track", tr("home.skip.track")),
            ("compose", tr("home.skip.compose")),
        ]:
            # MD3 复选框：使用 MaterialCheckBox（自绘 indicator + 对勾），
            # 绕开 PyQt ``QCheckBox::indicator`` 不支持 ``image: url()`` 替换
            # 内置渲染的限制；同时摆脱全局 QSS 给 ``QCheckBox::indicator``
            # 设置 ``background-color: primary`` 造成的"全是紫方块"问题。
            cb = MaterialCheckBox(label, colors=self._settings_page.colors)
            self._skip_checkboxes[key] = cb
            # 初始按单行排列（每列一个），_reflow_skip_checkboxes 会
            # 根据可用宽度重新调整列数，使窄屏下不至于撑出横向滚动条
            skip_flow.addWidget(cb, 0, 0)
        self._skip_grid_layout = skip_flow
        skip_layout.addLayout(skip_flow)
        layout.addWidget(skip_group)

        # 操作按钮：一屏只有一个 filled（开始），取消走 outlined
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(Space.M)
        self._run_btn = MaterialButton(tr("home.start"), variant=MaterialButton.VARIANT_FILLED)
        self._cancel_btn = MaterialButton(tr("home.cancel"), variant=MaterialButton.VARIANT_OUTLINED)
        self._cancel_btn.setEnabled(False)

        btn_layout.addWidget(self._run_btn)
        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        card.add_layout(layout)
        return card

    def _build_steps_card(self) -> MaterialCard:
        """批量视频文件列表卡片（取代原 Pipeline steps 面板）"""
        card = MaterialCard(tr("home.video_files"))
        self._batch_list = BatchVideoList(colors=self._settings_page.colors)
        # 主页的主操作是右下角 FAB，卡片内不再放第二个"添加视频"按钮
        self._batch_list.set_add_visible(False)
        # 单列布局下限制列表高度，避免整张卡片被父布局拉成一屏
        # （two-line 行高 80dp，4 行约 332dp，须留出滚动余量）
        self._batch_list.set_list_max_height(360)
        card.add_widget(self._batch_list)
        return card

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
        # FFmpeg 路径配置（仅 Windows）
        sp.ffmpeg_custom_changed.connect(self._config.set_ffmpeg_custom_enabled)
        sp.ffmpeg_path_changed.connect(self._config.set_ffmpeg_path)
        # 新增 pipeline.json 字段信号
        sp.log_to_file_changed.connect(self._config.set_log_to_file)
        sp.log_max_bytes_changed.connect(self._config.set_log_max_bytes)
        sp.log_backup_count_changed.connect(self._config.set_log_backup_count)
        sp.formation_path_changed.connect(self._config.set_formation_path)
        sp.actions_path_changed.connect(self._config.set_actions_path)
        sp.track_path_changed.connect(self._config.set_track_path)
        # 子配置字段变更（track/formation/actions/video_compose style1+style2）
        sp.sub_config_changed.connect(self._config.set_sub)
        # Pipeline 配置变更（Copilot 后端 + recognition 识别参数）
        sp.copilot_backend_changed.connect(self._config.set_copilot_backend)
        sp.copilot_timeout_changed.connect(self._config.set_copilot_timeout)
        sp.copilot_max_retries_changed.connect(self._config.set_copilot_max_retries)
        sp.ocr_source_changed.connect(self._config.set_ocr_source)
        sp.resolution_changed.connect(self._config.set_resolution)
        sp.stage_override_changed.connect(self._config.set_stage_override)
        sp.with_video_time_changed.connect(self._config.set_with_video_time)
        sp.resource_dir_changed.connect(self._config.set_recognition_resource_dir)
        # 高级分区折叠状态：从 gui.json 加载初始值 + 连接变更信号
        sp.set_advanced_expanded(self._gui_config.is_advanced_expanded())
        sp.advanced_expanded_changed.connect(self._gui_config.set_advanced_expanded)
        # 动态色彩：开关 + 种子色（持久化到 gui.json，切换即时生效）
        sp.dynamic_color_changed.connect(self._on_dynamic_color_changed)
        sp.seed_color_changed.connect(self._on_seed_color_changed)
        sp.set_dynamic_color(self._gui_config.is_dynamic_color())
        sp.set_seed_color(self._gui_config.seed_color())
        # 语言切换：SettingsPage 下拉框 → i18n.set_language → language_changed → 全局 _retranslate
        sp.language_change_requested.connect(self._on_language_change_requested)
        # 同步当前语言到 SettingsPage 下拉框（阻塞信号避免回环）
        sp.set_language(self._gui_config.language())
        self._style_combo.currentTextChanged.connect(self._on_style_changed)

        for key, cb in self._skip_checkboxes.items():
            cb.toggled.connect(self._on_skip_changed)

        # 按钮
        self._run_btn.clicked.connect(self._on_run)
        self._cancel_btn.clicked.connect(self._on_cancel)

        # 主题信号：Skip steps 容器/标题的内联配色随主题刷新（其余组件自订阅）
        theme_controller().theme_changed.connect(self._apply_skip_theme)

        # 服务信号（批量原生，带文件索引）
        self._service.file_started.connect(self._batch_list.set_file_running)
        self._service.file_progress.connect(self._batch_list.set_file_progress)
        self._service.file_finished.connect(
            lambda idx, success, _report, cancelled:
                self._batch_list.set_file_finished(idx, success, cancelled)
        )
        self._service.overall_progress.connect(self._progress_card.set_progress)
        self._service.log_emitted.connect(self._log_viewer.append)
        self._service.batch_finished.connect(self._on_batch_finished)
        # 后台输入校验结果（validate_batch_async 完成后回主线程）
        self._service.validation_finished.connect(self._on_validation_finished)

    # ── 配置加载与同步 ────────────────────────────────────

    def _sync_home_widgets(self) -> None:
        """从配置回填主页共享控件（背景图/风格/Skip 复选框）

        加载期间阻塞 MainWindow 自有控件信号，避免 setChecked/setText
        触发回写配置；同时阻塞批量列表信号避免 add_paths 回写。
        视频列表不持久化：不在此处恢复。
        """
        controls = [
            self._bg_selector,
            self._style_combo,
        ]
        controls.extend(cb for cb in self._skip_checkboxes.values())
        for ctrl in controls:
            ctrl.blockSignals(True)
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
        finally:
            for ctrl in controls:
                ctrl.blockSignals(False)
            self._batch_list.blockSignals(False)

    def _sync_settings_page_fields(self) -> None:
        """从配置回填 SettingsPage 的 pipeline 相关字段行

        SettingsPage 控件通过公开方法设置（内部阻塞信号避免回写）。
        首次加载与配置重置后的刷新共用，避免两份 set_* 清单漂移。
        """
        sp = self._settings_page
        sp.set_maa_path(self._config.maa_path())
        sp.set_output_dir(self._config.output_dir())
        sp.set_log_level(self._config.log_level())
        # 性能配置：多线程开关与最大并发数
        sp.set_multithreading(self._config.multithreading())
        sp.set_max_concurrent(self._config.max_concurrent())
        # FFmpeg 路径配置
        sp.set_ffmpeg_custom(self._config.ffmpeg_custom_enabled())
        sp.set_ffmpeg_path(self._config.ffmpeg_path())
        # 日志 / 统一超时重试 / 子配置路径
        sp.set_log_to_file(self._config.log_to_file())
        sp.set_log_max_bytes(self._config.log_max_bytes())
        sp.set_log_backup_count(self._config.log_backup_count())
        sp.set_formation_path(self._config.formation_path())
        sp.set_actions_path(self._config.actions_path())
        sp.set_track_path(self._config.track_path())
        # Pipeline 配置：Copilot 后端 + recognition 识别参数
        sp.set_copilot_backend(self._config.copilot_backend())
        sp.set_copilot_timeout(self._config.copilot_timeout())
        sp.set_copilot_max_retries(self._config.copilot_max_retries())
        sp.set_ocr_source(self._config.ocr_source())
        sp.set_resolution(self._config.resolution())
        sp.set_stage_override(self._config.stage_override())
        sp.set_with_video_time(self._config.with_video_time())
        sp.set_resource_dir(self._config.recognition_resource_dir())

    def _load_config_to_ui(self) -> None:
        self._config.load()
        self._sync_home_widgets()
        self._sync_settings_page_fields()
        # 子配置字段（track/formation/actions/video_compose style1+style2）
        self._settings_page.load_sub_config_values(self._config)

    def _on_style_changed(self, style: str) -> None:
        self._config.set_style(style)
        is_style1 = style == "style1"
        self._bg_selector.setEnabled(is_style1)
        if not is_style1:
            self._bg_selector.set_path("")

    def _on_config_reset(self, generated: list) -> None:
        """配置文件重置完成后的同步处理

        根据生成的配置文件类型，重新加载对应的磁盘配置并刷新 UI：

        - ``pipeline``: 重新加载 pipeline.json（``load()`` 会同时刷新所有
          子配置路径），刷新共享控件（MAA/Output/Log level/Style 等）。
        - ``formation``/``actions``/``track``/``compose``/``compose_style2``:
          重新加载对应子配置，刷新 SettingsPage 子配置字段行。
        - ``gui``: 重新加载 gui.json，刷新主题开关与高级折叠状态。

        若不刷新内存状态，``closeEvent`` 中的 ``save_all()`` 会将重置前
        的旧值写回磁盘，撤销重置操作。
        """
        sp = self._settings_page

        # 1. 重新加载磁盘配置到内存
        if "pipeline" in generated:
            # pipeline.json 已重置 → load() 同时刷新 pipeline + 所有子配置
            self._config.load()
        else:
            # 仅重置了子配置 → 逐个重新加载（不影响其他子配置的内存状态）
            for key in generated:
                sub_name = self._KEY_TO_SUB_CONFIG.get(key)
                if sub_name:
                    self._config.reload_sub_config(sub_name)

        # 2. 刷新 pipeline 相关共享控件（设置页 + 主页）
        if "pipeline" in generated:
            # 主页控件同步刷新：背景图 / Skip 复选框（视频列表不持久化，保持会话状态）
            self._sync_home_widgets()
            self._sync_settings_page_fields()

            if not self._service.is_running():
                self._run_btn.setEnabled(bool(self._config.video_paths()))

        # 3. 刷新子配置字段行（任何子配置或 pipeline 被重置都需要刷新）
        sub_keys = {"formation", "actions", "track", "compose", "compose_style2"}
        if set(generated) & sub_keys or "pipeline" in generated:
            sp.load_sub_config_values(self._config)

        # 4. 刷新 GUI 偏好（主题 + 高级折叠状态 + 语言）
        if "gui" in generated:
            self._gui_config.reload()
            dark = self._gui_config.is_dark_theme()
            if dark != self._is_dark:
                self._on_theme_change_requested(dark)
            sp.set_advanced_expanded(self._gui_config.is_advanced_expanded())
            # 语言重置后恢复（gui.json 重置为默认 zh-CN）
            lang = self._gui_config.language()
            if lang != i18n().language():
                i18n().set_language(lang)  # 触发 language_changed → 全局 _retranslate
            sp.set_language(lang)  # 同步下拉框（阻塞信号）

    def _on_skip_changed(self) -> None:
        steps = {key for key, cb in self._skip_checkboxes.items() if cb.isChecked()}
        self._config.set_skip_steps(steps)

    def _on_video_paths_changed(self, paths: list) -> None:
        """批量列表变化时同步到配置（持久化）并刷新 Start 按钮可用态"""
        self._config.set_video_paths(list(paths))
        if not self._service.is_running():
            self._run_btn.setEnabled(bool(paths))

    def _on_nav_changed(self, index: int) -> None:
        """导航切换：两侧外壳互相同步 + 页面淡入

        0=Home, 1=Settings, 2=Tools, 3=Info（四个同级页面）。
        两个导航外壳的 ``set_selected`` 都有同值早退，因此相互调用不会递归。
        """
        self._nav_rail.set_selected(index, animate=False)
        self._nav_bar.set_selected(index, animate=False)

        pages = {
            0: self._home_scroll,
            1: self._settings_scroll,
            2: self._tools_scroll,
            3: self._about_scroll,
        }
        page = pages.get(index)
        if page is None or page is self._stack.currentWidget():
            return
        if index == 1:
            # 进入设置页时同步主题开关状态（不触发信号）
            self._settings_page.set_dark(self._is_dark)
        self._switch_page(page)
        # FAB 是主页专属的主操作锚点，其他页面不显示
        self._update_fab_visibility()
        self._schedule_fab_position()

    def _update_fab_visibility(self) -> None:
        """按当前页面与运行状态更新 FAB 可见性（唯一实现）"""
        fab = getattr(self, "_fab", None)
        if fab is None:
            return
        on_home = self._stack.currentWidget() is self._home_scroll
        # 同时看 UI 运行态与 worker 状态：点击"开始"后服务在后台线程启动有
        # 延迟，仅看 service.is_running() 会让 FAB 在启动瞬间残留可见。
        fab.setVisible(
            on_home and not (getattr(self, "_ui_running", False)
                             or self._service.is_running())
        )

    def _switch_page(self, page: QWidget) -> None:
        """切换页面并播放 150ms 淡入（只改 opacity，不做几何动画）"""
        self._stack.setCurrentWidget(page)
        if not Motion.enabled:
            return
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(Duration.SHORT2)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(Easing.standard())

        def _cleanup() -> None:
            # 动画结束即移除 effect：QGraphicsEffect 会阻断子控件部分绘制路径
            page.setGraphicsEffect(None)

        anim.finished.connect(_cleanup)
        self._page_anim = anim
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # ── 语言切换 ──────────────────────────────────────────

    def _on_language_change_requested(self, lang: str) -> None:
        """SettingsPage 语言下拉框变更：切换 i18n 语言并持久化

        i18n().set_language 成功时 emit language_changed，触发所有 widget
        的 _retranslate（包括 SettingsPage 自身与 MainWindow._retranslate）。
        """
        if i18n().set_language(lang):
            self._gui_config.set_language(lang)

    def _on_tool_config_applied(self) -> None:
        """工具页将子配置写入磁盘后，同步设置页子配置字段行"""
        self._settings_page.load_sub_config_values(self._config)

    def _retranslate(self) -> None:
        """语言切换时刷新主页所有静态文本"""
        self.setWindowTitle(tr("app.title"))
        self._header.set_title(tr("home.title"))
        self._header.set_subtitle(tr("home.subtitle"))
        self._config_card.set_title(tr("home.input_config"))
        self._steps_card.set_title(tr("home.video_files"))
        self._progress_card_widget.set_title(tr("home.processing_status"))
        self._log_card.set_title(tr("home.runtime_logs"))
        self._bg_selector.set_label(tr("home.background"))
        self._bg_selector.set_placeholder(tr("home.background_placeholder"))
        self._style_field.set_label(tr("home.style"))
        self._skip_title.setText(tr("home.skip_steps"))
        # Skip 复选框标签（MAA 为产品名保留原文，其余步骤名按语言刷新）
        skip_labels = {
            "copilot": tr("home.skip.copilot"),
            "formation": tr("home.skip.formation"),
            "actions": tr("home.skip.actions"),
            "track": tr("home.skip.track"),
            "compose": tr("home.skip.compose"),
        }
        for key, cb in self._skip_checkboxes.items():
            cb.setText(skip_labels.get(key, key))
        # 语言切换后复选框宽度变化，重排列宽与列数
        self._reflow_skip_checkboxes(self._config_card_content_width())
        self._run_btn.setText(tr("home.start"))
        self._cancel_btn.setText(tr("home.cancel"))
        # FAB 文案随语言刷新（它不在任何卡片的重翻译注册表里）
        if getattr(self, "_fab", None) is not None:
            self._fab.setText(tr("batch.add_videos"))
            self._fab.setToolTip(tr("batch.add_videos"))
            self._fab.updateGeometry()
            self._fab.adjustSize()
            self._schedule_fab_position()

    # ── 操作处理 ──────────────────────────────────────────

    def _on_run(self) -> None:
        paths = self._batch_list.video_paths()
        if not paths:
            self._show_warning(tr("msg.no_video_title"), tr("msg.no_video_text"))
            return

        # 与视频列表平行对齐的自定义作业 JSON 路径（None=未绑定，仍执行识别）
        json_paths = self._batch_list.json_paths()

        # 输入校验在后台线程执行：validate_video_file 内部为同步 ffprobe
        # 子进程调用（单文件超时上限 60 秒），在主线程串行校验大量文件
        # 会长时间冻结 UI；结果经 validation_finished 信号回主线程
        if not self._service.validate_batch_async(paths, json_paths):
            return
        # 校验期间暂禁运行按钮，防止重复发起（失败/成功后统一恢复）
        self._run_btn.setEnabled(False)
        self._pending_run_paths = paths
        self._pending_run_json_paths = json_paths

    def _on_validation_finished(self, errors: list) -> None:
        """后台输入校验完成后继续/中止启动流程"""
        paths = self._pending_run_paths
        json_paths = self._pending_run_json_paths
        self._pending_run_paths = []
        self._pending_run_json_paths = []
        if not paths:
            self._run_btn.setEnabled(bool(self._batch_list.video_paths()))
            return

        try:
            if errors:
                self._run_btn.setEnabled(True)
                self._show_warning(
                    tr("msg.validation_failed_title"), "\n".join(errors)
                )
                return

            # 将 GUI 中的全部配置（含 track/formation/actions/video_compose 等
            # 子配置）落盘后再运行：流水线各步骤从磁盘读取子配置，而此前仅在
            # closeEvent 中 save_all()，本次会话内修改的子配置不会生效
            # （如开启 style1 逐操作显示后输出视频中缺失对应叠加）。
            self._config.save_all()

            self._batch_list.reset_states()
            self._progress_card.reset()
            self._log_viewer.clear_logs()
            self._set_running_ui(True)
            # 运行态 FAB 立即隐藏（_set_running_ui 内已刷新，这里再显式调用
            # 以覆盖服务尚未真正启动的瞬间）
            self._update_fab_visibility()
            # 调用方刚完成校验，validate=False 避免同一批次 ffprobe 重复探测
            if not self._service.run_pipeline(paths, json_paths, validate=False):
                self._set_running_ui(False)
        except Exception as exc:
            # 兜底：任何异常都不应让 UI 卡在"运行中"状态
            self._set_running_ui(False)
            self._show_critical(
                tr("msg.completed_errors_title"), f"{type(exc).__name__}: {exc}"
            )

    def _on_cancel(self) -> None:
        self._service.cancel_pipeline()
        self._cancel_btn.setEnabled(False)

    def _on_batch_finished(self, success_count: int, total: int,
                           cancelled: bool) -> None:
        self._set_running_ui(False)
        self._progress_card.set_batch_finished(success_count, total, cancelled)
        if not cancelled and success_count < total:
            self._show_critical(
                tr("msg.completed_errors_title"),
                tr("msg.completed_errors_text", failed=total - success_count),
            )

    def _set_running_ui(self, running: bool) -> None:
        self._ui_running = running
        self._run_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._batch_list.set_editable(not running)
        self._bg_selector.setEnabled(not running and self._style_combo.currentText() == "style1")
        self._style_combo.setEnabled(not running)
        # MAA / Output / Log level 通过 SettingsPage 公开方法统一控制
        self._settings_page.set_advanced_enabled(not running)
        # 性能配置（多线程开关 / 最大并发数）运行期间禁止修改
        self._settings_page.set_performance_enabled(not running)
        # FFmpeg 路径配置运行期间禁止修改
        self._settings_page.set_ffmpeg_enabled(not running)
        # 子配置字段（track/formation/actions/video_compose）运行期间禁止修改
        self._settings_page.set_sub_config_enabled(not running)
        for cb in self._skip_checkboxes.values():
            cb.setEnabled(not running)
        # 运行期间隐藏 FAB（此时主操作已变为"取消"）
        if getattr(self, "_fab", None) is not None:
            self._update_fab_visibility()

    def _on_theme_change_requested(self, dark: bool) -> None:
        """设置页主题开关触发：应用主题并持久化偏好"""
        self._toggle_theme(dark)
        # 持久化到独立 GUI 配置（config/gui.json），与 pipeline 配置完全解耦
        self._gui_config.set_theme("dark" if dark else "light")

    def _apply_initial_theme(self) -> None:
        """启动时按 ``config/gui.json`` 初始化主题

        ``create_application`` 已安装全局 QSS 并应用浅色 QPalette；这里走一次
        ``_toggle_theme``，让 ``ThemeController`` 的状态与界面一致。若配置是
        浅色，配色与已应用调色板相同，``ThemeController`` 会跳过重绘；配置为
        深色或自定义配色时才应用 QPalette，并对输入类控件重新 polish。
        """
        self._toggle_theme(self._is_dark)

    def _toggle_theme(self, dark: bool) -> None:
        """切换主题：只更新控制器，组件通过 ``theme_changed`` 自刷新

        历史实现用 20 余处 ``if getattr(...)`` 手工枚举需要刷新的控件，
        每新增一个控件都要记得加一行，漏一处就出现"深色下残留白块"。
        现在组件在各自构造函数里订阅主题信号，本方法不再维护清单。
        """
        self._is_dark = dark
        self._apply_theme_colors()
        # 设置页开关保持同步（不触发信号，避免回环）
        if getattr(self, "_settings_page", None) is not None:
            self._settings_page.set_dark(dark)
        # 标题栏放在最后：等所有订阅者重绘完成再切 DWM 主题，
        # 让标题栏与主界面在同一帧上屏，避免"标题栏先变/内容后变"
        apply_titlebar_theme(self, dark)

    def _apply_theme_colors(self) -> None:
        """按当前明暗 + 种子色 + 动态色彩开关重新应用主题"""
        theme_controller().apply(
            dark=self._is_dark,
            seed=self._gui_config.seed_color(),
            dynamic=self._gui_config.is_dynamic_color(),
            app=QApplication.instance(),
        )

    def _on_dynamic_color_changed(self, enabled: bool) -> None:
        """设置页动态色彩开关：持久化并立即重建配色"""
        self._gui_config.set_dynamic_color(enabled)
        self._apply_theme_colors()

    def _on_seed_color_changed(self, color: str) -> None:
        """设置页种子色变更：持久化并立即重建配色"""
        self._gui_config.set_seed_color(color)
        self._apply_theme_colors()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # 首次 show 后窗口句柄（HWND）才稳定可用，此时应用标题栏主题
        if not self._titlebar_applied:
            self._titlebar_applied = True
            apply_titlebar_theme(self, self._is_dark)
        self._schedule_fab_position()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        # 响应式只由尺寸类别驱动（compact / medium / expanded）
        self._apply_size_class(WindowSizeClass.of(self.width()))
        self._reflow_skip_checkboxes(self._config_card_content_width())
        self._position_fab()
        self._schedule_fab_position()

    def _apply_size_class(self, size_class: str) -> None:
        """按 MD3 尺寸类别调整导航外壳、页边距、栅格与页面头字号"""
        if size_class == getattr(self, "_size_class", None):
            return
        self._size_class = size_class

        compact = WindowSizeClass.uses_bottom_navigation(size_class)
        self._nav_rail.setVisible(not compact)
        self._nav_bar.setVisible(compact)
        self._nav_rail.set_compact(not WindowSizeClass.rail_shows_labels(size_class))

        margin = Margin.page(size_class)
        self._content_layout.setContentsMargins(margin, margin, margin, margin)

        if getattr(self, "_cards_grid", None) is not None:
            self._apply_grid_layout(two_column=Grid.columns(size_class) > 1)
            self._reflow_skip_checkboxes(self._config_card_content_width())

        if getattr(self, "_header", None) is not None:
            self._header.set_size_class(size_class)

        for page, setter in (
            (getattr(self, "_settings_page", None), "set_size_class"),
            (getattr(self, "_about_page", None), "set_size_class"),
            (getattr(self, "_tools_page", None), "set_size_class"),
        ):
            hook = getattr(page, setter, None)
            if callable(hook):
                hook(size_class)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # 主页视口尺寸变化时重排 Skip 复选框（页面宽度本身由
        # QScrollArea 的居中对齐 + 内容最大宽度约束，不再手工同步）
        if event.type() == QEvent.Type.Resize and obj is self._home_scroll.viewport():
            self._reflow_skip_checkboxes(self._config_card_content_width())
        return super().eventFilter(obj, event)

    def closeEvent(self, event: QCloseEvent) -> None:
        # 关闭工具对话框：其 closeEvent 会触发视图的 request_shutdown
        # （取消 + 限时等待 + terminate 兜底），确保工具内后台 worker
        # 先于控件树析构退出，避免 "QThread destroyed while running"。
        # 仅在确定退出时执行（用户取消退出时不应误关工具窗口）
        def _shutdown_tool_dialogs() -> None:
            self._tools_page.shutdown_dialogs()

        if self._service.is_running():
            confirmed = self._show_confirm(
                tr("msg.confirm_exit_title"),
                tr("msg.confirm_exit_text"),
                confirm_text=tr("msg.confirm_exit_confirm")
            )
            if confirmed:
                _shutdown_tool_dialogs()
                self._service.cancel_pipeline()
                # 等待 worker 线程退出，避免 QThread 被销毁时仍在运行
                self._service.wait_for_shutdown(timeout_ms=5000)
                # 长步骤（MAA/track/compose 可达数百秒）不会在 5s 内响应 cancel，
                # 强制终止以确保进程能退出
                if self._service.is_running():
                    self._service.force_terminate_workers(timeout_ms=2000)
                self._gui_config.save()
                self._config.save_all()
                event.accept()
            else:
                event.ignore()
        else:
            _shutdown_tool_dialogs()
            self._gui_config.save()
            self._config.save_all()
            event.accept()

    # ── Material 消息对话框快捷方法 ─────────────────────
    # 取代 QMessageBox，避免 OK / Yes / No 按钮被默认 QSS 裁切/遮挡
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

    def _show_confirm(self, title: str, text: str, confirm_text: str | None = None) -> bool:
        from arknights_video_pipeline.gui.components.message_dialog import ConfirmDialog
        dlg = ConfirmDialog(
            title, text,
            confirm_text=confirm_text or tr("dialog.confirm"),
            cancel_text=tr("dialog.cancel"),
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
