"""gui.components.tools_page - 工具完整页面

与主页 / 设置页同级的完整页面，由左侧导航栏的 Tools 项进入。
页面结构（MD3）：

- 页面头（标题 + 副标题）
- 工具索引卡片（24dp 前导图标 + 标题 + 描述 + 尾部 text 按钮），
  宽屏双列、其余单列
- 点击卡片（或卡片上的"打开"按钮）弹出独立窗口（ToolDialog），
  窗口内为对应工具的 ToolView

工具视图按 ``ToolRegistry`` 延迟导入：索引页只依赖标题/描述文案，
打开工具时才加载 pictex / movielite 等重资源模块。
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from arknights_video_pipeline.gui.assets.icons.nav_icons import make_icon_pixmap
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import MaterialCard
from arknights_video_pipeline.gui.components.page_header import PageHeader
from arknights_video_pipeline.gui.components.tools import TOOL_REGISTRY
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import Grid, MaterialColors, MaterialTypography
from arknights_video_pipeline.gui.theme.spacing import Margin, Space
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.window_size import WindowSizeClass

# 工具索引图标（Material Symbols 名称 → 24dp 前导图标）
_TOOL_ICONS: dict[str, str] = {
    "style1_text_range": "description",
    "recognition": "pending",
}


class ToolDialog(QDialog):
    """工具预览独立窗口：非模态，内含 ToolView + 系统标题栏关闭"""

    def __init__(self, tool_id: str, title_key: str, view_cls: type,
                 config_proxy: Any, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool_id = tool_id
        self._title_key = title_key
        self._colors = colors or theme_controller().colors()
        self.setWindowTitle(tr(title_key))
        self.setModal(False)
        # 独立正常窗口：任务栏独立条目，标题栏可最小化/最大化/关闭
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 背景交给系统 palette（MaterialStyle 全局设置）：不要设
        # WA_OpaquePaintEvent，否则跳过背景填充、内容四周露出未绘制区域。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(720, 520)
        self.resize(1040, 760)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(Space.XL, Space.XL, Space.XL, Space.XL)
        root.setSpacing(Space.L)

        # 内容放入滚动区：对话框可自由缩放，内容过小时出现滚动条
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self._scroll.viewport().setAutoFillBackground(False)

        self._view = view_cls(config_proxy=config_proxy, colors=self._colors)
        # 进入工具视图：通知工具从配置文件加载参数值。
        # 工具内编辑只改内存与预览，写盘仅在用户点击"应用/写入"按钮时进行
        self._view.on_entered()
        self._scroll.setWidget(self._view)
        root.addWidget(self._scroll, 1)

        i18n().language_changed.connect(self._retranslate)

    def view(self):
        return self._view

    def closeEvent(self, event) -> None:
        # 本对话框设了 WA_DeleteOnClose，关闭即析构 _view 整棵控件树。
        # 工具视图可能仍有后台 QThread 在运行（如识别工具的
        # RecognitionWorker），QThread 先于线程结束被析构会触发
        # "QThread destroyed while running" 直接 abort 进程。若视图
        # 实现了 request_shutdown（取消 + 限时等待 + terminate 兜底），
        # 关闭前先调用它确保线程已退出。
        shutdown = getattr(self._view, "request_shutdown", None)
        if callable(shutdown):
            shutdown()
        super().closeEvent(event)

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._view.set_colors(colors)

    def _retranslate(self) -> None:
        self.setWindowTitle(tr(self._title_key))
        self._view.retranslate()


class ToolCard(MaterialCard):
    """工具索引卡片：前导图标 + 标题 / 描述 + 尾部 text 按钮"""

    def __init__(self, tool_id: str, title_key: str, desc_key: str,
                 colors: MaterialColors, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.tool_id = tool_id
        self._colors = colors
        self._typo = MaterialTypography()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 卡片高度由内容决定，避免宽屏两列时被拉成同高
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(),
                           self.sizePolicy().verticalPolicy())

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Space.L)

        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(24, 24)
        self._icon_label.setStyleSheet("background: transparent; border: none;")
        row.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(Space.XS)
        self._title = QLabel(tr(title_key), self)
        self._title.setFont(self._typo.font("title_medium"))
        text_col.addWidget(self._title)

        self._desc = QLabel(tr(desc_key), self)
        self._desc.setFont(self._typo.font("body_small"))
        self._desc.setWordWrap(True)
        text_col.addWidget(self._desc)
        row.addLayout(text_col, 1)

        self._open_btn = MaterialButton(
            tr("tools.open"), variant=MaterialButton.VARIANT_TEXT
        )
        row.addWidget(self._open_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.add_layout(row)
        self._apply_colors()
        theme_controller().theme_changed.connect(self.set_colors)

    def open_button(self) -> MaterialButton:
        return self._open_btn

    def set_texts(self, title: str, desc: str) -> None:
        self._title.setText(title)
        self._desc.setText(desc)

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._apply_colors()

    def _apply_colors(self) -> None:
        c = self._colors
        icon = _TOOL_ICONS.get(self.tool_id, "tools")
        pixmap = make_icon_pixmap(icon, c.primary, size_px=24)
        if pixmap is not None:
            self._icon_label.setPixmap(pixmap)
        self._title.setStyleSheet(
            f"color: {c.on_surface}; background: transparent; border: none;"
        )
        self._desc.setStyleSheet(
            f"color: {c.on_surface_variant}; background: transparent; border: none;"
        )


class ToolsPage(QWidget):
    """工具页面：索引卡片 + 点击弹出工具窗口"""

    # 任一工具将配置写入磁盘（如 style1.json）后发射，供 MainWindow 同步设置页
    tool_config_applied = pyqtSignal()

    def __init__(self, config_proxy: Any, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self._typo = MaterialTypography()
        self._config_proxy = config_proxy
        self._dialogs: list[ToolDialog] = []
        # tool_id → 已打开的对话框（同一工具去重，重复打开时置前）
        self._dialog_by_tool: dict[str, ToolDialog] = {}

        self.setObjectName("toolsPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._size_class = WindowSizeClass.EXPANDED
        self._two_col: bool | None = None
        root = QVBoxLayout(self)
        self._root = root
        root.setContentsMargins(
            Margin.EXPANDED, Margin.EXPANDED, Margin.EXPANDED, Margin.EXPANDED
        )
        root.setSpacing(Space.XXL)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._header = PageHeader(
            tr("tools.title"), tr("tools.subtitle"), colors=self._colors
        )
        root.addWidget(self._header)

        # 索引卡片网格（宽屏双列，其余单列；见 _apply_grid）
        self._grid_host = QWidget(self)
        self._grid_host.setStyleSheet("background: transparent; border: none;")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(Space.XL)
        root.addWidget(self._grid_host)

        self._cards: list[ToolCard] = []
        for spec in TOOL_REGISTRY:
            card = ToolCard(spec.tool_id, spec.title_key, spec.desc_key, self._colors)
            card.open_button().clicked.connect(
                lambda _checked=False, t=spec.tool_id: self._open_tool(t)
            )
            card.installEventFilter(self)
            self._cards.append(card)

        self._apply_grid(two_column=True)

        i18n().language_changed.connect(self._retranslate)
        theme_controller().theme_changed.connect(self.set_colors)
        self._sync_columns()

    def _sync_columns(self) -> None:
        """按页面实际宽度决定索引卡片列数（双列需要 ≥760dp）"""
        width = self.width()
        if width > 0:
            two = width >= 760
        else:
            two = Grid.columns(self._size_class) > 1
        if two == self._two_col:
            return
        self._two_col = two
        self._apply_grid(two)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_columns()

    # ── 布局 / 响应式 ─────────────────────────────────────

    def _apply_grid(self, two_column: bool) -> None:
        """按列数重排工具卡片（宽屏双列，其余单列）"""
        for card in self._cards:
            self._grid.removeWidget(card)
        if two_column:
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 1)
            for index, card in enumerate(self._cards):
                self._grid.addWidget(
                    card, index // 2, index % 2,
                    Qt.AlignmentFlag.AlignTop,
                )
        else:
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)
            for index, card in enumerate(self._cards):
                self._grid.addWidget(card, index, 0, Qt.AlignmentFlag.AlignTop)

    def set_size_class(self, size_class: str) -> None:
        """按尺寸类别调整页边距、页面头字号与卡片列数"""
        if size_class == self._size_class:
            return
        self._size_class = size_class
        margin = Margin.page(size_class)
        self._root.setContentsMargins(margin, margin, margin, margin)
        self._header.set_size_class(size_class)
        self._sync_columns()

    # ── 打开工具（独立窗口） ─────────────────────────────

    def _open_tool(self, tool_id: str) -> None:
        spec_by_id = {spec.tool_id: spec for spec in TOOL_REGISTRY}
        spec = spec_by_id.get(tool_id)
        if spec is None:
            return

        # 去重：同一工具已打开时置前激活，而非新开窗口——多个同工具
        # 对话框会并发运行各自 worker 并各自 save_all() 写同一份配置
        existing = self._dialog_by_tool.get(tool_id)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return

        # parent 指向主窗口：无 parent 的 QDialog 是独立顶级窗口，
        # QApplication 的 quitOnLastWindowClosed 语义下主窗关闭后
        # 应用仍会驻留，直到该对话框被关闭
        dlg = ToolDialog(
            tool_id, spec.title_key, spec.load_view(),
            config_proxy=self._config_proxy, colors=self._colors,
            parent=self.window(),
        )
        # 工具写盘信号统一转发给页面外部（MainWindow 同步设置页）
        if hasattr(dlg.view(), "config_applied"):
            dlg.view().config_applied.connect(self.tool_config_applied)
        dlg.finished.connect(
            lambda _r, d=dlg: self._dialogs.remove(d) if d in self._dialogs else None
        )
        # 正常关闭（finished）与 WA_DeleteOnClose 析构两条路径都清理映射
        dlg.destroyed.connect(
            lambda _obj=None, tid=tool_id: self._dialog_by_tool.pop(tid, None)
        )
        self._dialogs.append(dlg)
        self._dialog_by_tool[tool_id] = dlg
        dlg.show()

    def shutdown_dialogs(self) -> None:
        """请求所有已打开的工具对话框关闭

        MainWindow 关闭前调用：对话框的 closeEvent 会触发其视图的
        request_shutdown（取消 + 限时等待 + terminate 兜底），确保工具
        内的后台 worker（如 RecognitionWorker）先于控件树析构退出，
        避免 "QThread destroyed while running" 直接 abort 进程。
        """
        for dlg in list(self._dialogs):
            dlg.close()

    def eventFilter(self, obj, event) -> bool:
        # 点击卡片任意区域打开工具窗口（按钮自身处理点击，不会重复触发）
        if event.type() == QEvent.Type.MouseButtonPress:
            for card in self._cards:
                if obj is card:
                    self._open_tool(card.tool_id)
                    return True
        return super().eventFilter(obj, event)

    # ── 主题 / 语言 ───────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        for dlg in self._dialogs:
            dlg.set_colors(colors)

    def _retranslate(self) -> None:
        self._header.set_title(tr("tools.title"))
        self._header.set_subtitle(tr("tools.subtitle"))
        for card, spec in zip(self._cards, TOOL_REGISTRY):
            card.set_texts(tr(spec.title_key), tr(spec.desc_key))
            card.open_button().setText(tr("tools.open"))
        for dlg in self._dialogs:
            dlg._retranslate()
