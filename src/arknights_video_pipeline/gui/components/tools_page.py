"""
gui.components.tools_page - 工具完整页面

与主页 / 设置页同级的完整页面，由左侧导航栏的 Tools 项进入。
页面结构（MD3）：
- Hero 大标题
- 工具索引卡片列表（按 TOOL_REGISTRY 顺序渲染）
- 点击卡片（或卡片上的"打开"按钮）弹出独立预览窗口（ToolDialog），
  窗口内为对应工具的 ToolView，可实时预览文字位置与内容

新增工具无需改动本页：只需在 ``gui.components.tools.TOOL_REGISTRY``
注册 ToolView 子类。
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import MaterialCard
from arknights_video_pipeline.gui.components.tools import TOOL_REGISTRY, ToolView
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import MaterialColors, MaterialTypography


class ToolDialog(QDialog):
    """工具预览独立窗口：非模态，内含 ToolView + 关闭按钮"""

    def __init__(self, tool_id: str, title_key: str, view_cls: type[ToolView],
                 config_proxy: Any, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool_id = tool_id
        self._title_key = title_key
        self._colors = colors or MaterialColors.light()
        self.setWindowTitle(tr(title_key))
        self.setModal(False)
        # 独立正常窗口：任务栏独立条目，标题栏可最小化/最大化/关闭
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 背景交给系统 palette（MaterialStyle 全局设置，与 message_dialog
        # 一致）：不要给对话框设 WA_OpaquePaintEvent，否则跳过背景填充
        # 会在内容四周露出未绘制区域（黑色边框）。拖动乱码防护由
        # 预览控件自身的 WA_OpaquePaintEvent 承担。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(720, 520)
        self.resize(1000, 720)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # 内容放入滚动区：对话框可自由缩放，内容过小时出现滚动条。
        # QScrollArea 是 QFrame 子类，需覆盖全局 QFrame 边框样式，否则
        # 会出现一圈 outline_variant 描边（深色主题下呈黑色）。
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
        self._scroll.setWidget(self._view)
        root.addWidget(self._scroll, 1)

        # 使用系统标准窗口样式：无自定义关闭按钮（用标题栏 X 关闭）
        i18n().language_changed.connect(self._retranslate)

    def view(self) -> ToolView:
        return self._view

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._view.set_colors(colors)

    def _retranslate(self) -> None:
        self.setWindowTitle(tr(self._title_key))
        self._view.retranslate()


class ToolsPage(QWidget):
    """工具页面：索引列表 + 点击卡片弹出预览窗口"""

    # 任一工具将配置写入磁盘（如 style1.json）后发射，供 MainWindow 同步设置页
    tool_config_applied = pyqtSignal()

    def __init__(self, config_proxy: Any, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        self._typo = MaterialTypography()
        self._config_proxy = config_proxy
        self._tr_labels: list[tuple] = []
        self._dialogs: list[ToolDialog] = []

        self.setObjectName("toolsPage")
        # 页面背景跟随全局 QSS；此处仅置透明避免覆盖 app 级背景
        self.setStyleSheet("background: transparent; border: none;")

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(32)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        root.addWidget(self._build_hero())

        cards_widget = QWidget()
        cards_widget.setStyleSheet("background: transparent; border: none;")
        index_layout = QVBoxLayout(cards_widget)
        index_layout.setContentsMargins(0, 0, 0, 0)
        index_layout.setSpacing(24)
        index_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._tool_cards: list[MaterialCard] = []
        self._tool_card_titles: list[QLabel] = []
        self._tool_card_descs: list[QLabel] = []
        self._card_to_index: dict[MaterialCard, int] = {}

        for index, (tool_id, title_key, view_cls) in enumerate(TOOL_REGISTRY):
            card = MaterialCard()
            card.set_surface_color(self._colors.surface)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.installEventFilter(self)
            card_layout = card.layout()

            title = QLabel(tr(title_key))
            title.setStyleSheet(
                f"color: {self._colors.on_surface}; background: transparent; border: none;"
                " font-weight: 500; font-size: 16px;"
            )
            card_layout.addWidget(title)
            self._tool_card_titles.append(title)

            desc_key = f"tools.{tool_id}.desc"
            desc = QLabel(tr(desc_key))
            desc.setWordWrap(True)
            desc.setStyleSheet(
                f"color: {self._colors.on_surface_variant}; background: transparent;"
                " border: none; font-size: 14px;"
            )
            card_layout.addWidget(desc)
            self._tool_card_descs.append(desc)

            open_btn = MaterialButton(
                tr("tools.open"),
                variant=MaterialButton.VARIANT_FILLED,
            )
            open_btn.clicked.connect(
                lambda _checked=False, i=index: self._open_tool(i)
            )
            row = QHBoxLayout()
            row.addStretch()
            row.addWidget(open_btn)
            card_layout.addLayout(row)

            index_layout.addWidget(card)
            self._tool_cards.append(card)
            self._card_to_index[card] = index

        root.addWidget(cards_widget)

        # 语言切换时刷新页面文本
        i18n().language_changed.connect(self._retranslate)

    def _build_hero(self) -> QWidget:
        """Hero 区域：大标题（与主页 / 设置页一致）"""
        hero = QWidget()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 24, 0, 0)
        hero_layout.setSpacing(16)
        hero_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel(tr("tools.title"))
        title.setFont(self._typo.display_large)
        title.setStyleSheet(
            "border: none; background: transparent;"
            " font-size: 48px; font-weight: 600; line-height: 1.15;"
            " letter-spacing: -1.5px;"
        )
        title.setWordWrap(True)
        hero_layout.addWidget(title)
        self._tr_labels.append((title.setText, "tools.title"))
        return hero

    # ── 打开工具（独立窗口） ─────────────────────────────

    def _open_tool(self, index: int) -> None:
        if not (0 <= index < len(TOOL_REGISTRY)):
            return
        tool_id, title_key, view_cls = TOOL_REGISTRY[index]
        dlg = ToolDialog(
            tool_id, title_key, view_cls,
            config_proxy=self._config_proxy, colors=self._colors,
        )
        # 工具写盘信号统一转发给页面外部（MainWindow 同步设置页）
        if hasattr(dlg.view(), "config_applied"):
            dlg.view().config_applied.connect(self.tool_config_applied)
        dlg.finished.connect(
            lambda _r, d=dlg: self._dialogs.remove(d) if d in self._dialogs else None
        )
        self._dialogs.append(dlg)
        dlg.show()

    def eventFilter(self, obj, event) -> bool:
        # 点击卡片任意区域打开工具预览窗口（按钮自身处理点击，不会重复触发）
        if event.type() == QEvent.Type.MouseButtonPress and obj in self._card_to_index:
            self._open_tool(self._card_to_index[obj])
            return True
        return super().eventFilter(obj, event)

    # ── 主题 / 语言 ───────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        for card, title, desc in zip(
            self._tool_cards, self._tool_card_titles, self._tool_card_descs
        ):
            card.set_surface_color(colors.surface)
            title.setStyleSheet(
                f"color: {colors.on_surface}; background: transparent; border: none;"
                " font-weight: 500; font-size: 16px;"
            )
            desc.setStyleSheet(
                f"color: {colors.on_surface_variant}; background: transparent;"
                " border: none; font-size: 14px;"
            )
        for dlg in self._dialogs:
            dlg.set_colors(colors)

    def _retranslate(self) -> None:
        for setter, key in self._tr_labels:
            setter(tr(key))
        for i, (tool_id, title_key, _view_cls) in enumerate(TOOL_REGISTRY):
            if i < len(self._tool_card_titles):
                self._tool_card_titles[i].setText(tr(title_key))
            if i < len(self._tool_card_descs):
                self._tool_card_descs[i].setText(tr(f"tools.{tool_id}.desc"))
        for dlg in self._dialogs:
            dlg._retranslate()