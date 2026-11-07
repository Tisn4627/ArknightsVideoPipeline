"""gui.components.material_combo - MD3 下拉框（自绘弹层）

Qt 原生 ``QComboBox`` 的弹层是系统风格的方形列表，选中行会用主色整行填充，
与 MD3 菜单（surface_container + 4dp 圆角 + 状态层 + 勾选标记）不一致；
``QComboBox::down-arrow`` 也无法随主题换色。

本组件做了三件事：

1. 关闭原生箭头，在 ``paintEvent`` 中绘制 Material Symbols Rounded 的
   ``expand_more``（颜色取 ``on_surface_variant``）；
2. 自绘 ``Qt.Popup`` 弹层：``surface_container`` 底、4dp 圆角、level 2 阴影、
   40dp 行高、8% 悬停墨层；选中行用 ``secondary_container`` +
   ``on_secondary_container`` 文字与 ``check`` 图标；
3. 保留 ``QComboBox`` 的全部公开接口（``currentIndex`` / ``currentTextChanged``
   等），设置页与主页可直接替换原生控件。

被 :class:`MaterialTextField` 包裹时，通过 ``set_embedded(True)`` 取消
自身最小高度与箭头绘制，由外框负责浮动标签与 chevron。
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from arknights_video_pipeline.gui.assets.icons.nav_icons import (
    has_icon,
    make_icon_pixmap,
)
from arknights_video_pipeline.gui.components.material_card import CardFrame
from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.shape import Shape
from arknights_video_pipeline.gui.theme.spacing import Space
from arknights_video_pipeline.gui.theme.state import (
    Elevation,
    StateLayer,
    blend,
    with_alpha,
)
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["MaterialComboBox"]

_ITEM_HEIGHT = 44          # MD3 菜单项 48dp 的桌面密度（-1）
_H_PADDING = Space.L       # 左右内边距 16dp
_CHECK_SIZE = 20
_POPUP_MARGIN = Space.M    # 弹层四周留给阴影的透明边距
_POPUP_RADIUS = Shape.EXTRA_SMALL
_MAX_VISIBLE_ITEMS = 8


class _ComboItemDelegate(QStyledItemDelegate):
    """MD3 菜单行：状态层 + 选中容器 + 勾选图标"""

    def __init__(self, colors: MaterialColors, selected_index: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors
        self._selected_index = selected_index
        self._typography = MaterialTypography()

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors

    def set_selected_index(self, index: int) -> None:
        self._selected_index = index

    def _font(self):
        return self._typography.font("body_medium")

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt 命名
        font = self._font()
        metrics = QFontMetrics(font)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        width = (
            metrics.horizontalAdvance(text)
            + 2 * _H_PADDING
            + _CHECK_SIZE
            + Space.S
        )
        return QSize(width, _ITEM_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        c = self._colors
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(option.rect).adjusted(0.0, 2.0, 0.0, -2.0)
        radius = float(_POPUP_RADIUS)
        selected = index.row() == self._selected_index
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        current = bool(option.state & QStyle.StateFlag.State_Selected)
        has_focus = bool(option.state & QStyle.StateFlag.State_HasFocus)

        # 选中容器：secondary_container（不是 primary 整行填充）
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.secondary_container))
            painter.drawRoundedRect(rect, radius, radius)

        # 悬停 / 键盘光标墨层
        if hovered or (current and not selected):
            layer = StateLayer.HOVER if hovered else StateLayer.FOCUS
            overlay = c.on_secondary_container if selected else c.on_surface
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha(overlay, layer))
            painter.drawRoundedRect(rect, radius, radius)

        text_color = c.on_secondary_container if selected else c.on_surface
        font = self._font()
        painter.setFont(font)
        metrics = QFontMetrics(font)
        right_pad = _H_PADDING + (_CHECK_SIZE + Space.S if selected else 0)
        text_rect = rect.adjusted(_H_PADDING, 0, -right_pad, 0)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        elided = metrics.elidedText(
            text, Qt.TextElideMode.ElideRight, int(text_rect.width())
        )
        painter.setPen(QColor(text_color))
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided,
        )

        # 选中勾：Material Symbols Rounded check（20dp）
        if selected and has_icon("check"):
            pixmap = make_icon_pixmap(
                "check", c.on_secondary_container, size_px=_CHECK_SIZE
            )
            if pixmap is not None:
                x = int(rect.right() - _H_PADDING - _CHECK_SIZE)
                y = int(rect.center().y() - _CHECK_SIZE / 2)
                painter.drawPixmap(x, y, pixmap)

        # 键盘焦点环：当前行（未选中时）用 2dp primary 内缩描边
        if current and has_focus and not selected:
            pen = QPen(QColor(c.primary), 2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                rect.adjusted(1.0, 1.0, -1.0, -1.0),
                radius - 1.0, radius - 1.0,
            )

        painter.restore()


class _ComboList(QListWidget):
    """弹层列表：Esc 关闭、Enter 选择"""

    closed = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.closed.emit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.currentItem()
            if item is not None:
                self.itemActivated.emit(item)
            event.accept()
            return
        super().keyPressEvent(event)


class _ComboPopup(QWidget):
    """MD3 下拉弹层（圆角 surface_container + level 2 阴影）"""

    item_chosen = pyqtSignal(int)
    closed = pyqtSignal()

    def __init__(self, combo: "MaterialComboBox", colors: MaterialColors) -> None:
        super().__init__(
            combo,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self._combo = combo
        self._colors = colors
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            _POPUP_MARGIN, _POPUP_MARGIN, _POPUP_MARGIN, _POPUP_MARGIN
        )
        outer.setSpacing(0)

        self._card = CardFrame(
            self,
            surface_role="surface_container",
            radius=_POPUP_RADIUS,
            variant="elevated",
        )
        self._card.set_elevation(Elevation.MENU)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.setSpacing(0)

        self._list = _ComboList(self._card)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
        )
        self._list.viewport().setAutoFillBackground(False)
        self._list.setMouseTracking(True)
        self._list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # 弹层最多展示 8 行；隐藏滚动条，避免 4 行时也出现一条几乎满高的
        # "假滚动条"（QListWidget 内容/视口差 1px 就会触发 AsNeeded）。
        # 超过 8 行时仍可通过滚轮与键盘上下键滚动。
        self._list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list.setSpacing(0)
        self._list.setUniformItemSizes(True)

        self._delegate = _ComboItemDelegate(colors, combo.currentIndex(), self._list)
        self._list.setItemDelegate(self._delegate)

        for i in range(combo.count()):
            item = QListWidgetItem(combo.itemText(i))
            item.setSizeHint(QSize(0, _ITEM_HEIGHT))
            self._list.addItem(item)

        self._list.setCurrentRow(max(0, combo.currentIndex()))
        self._list.itemClicked.connect(self._on_item)
        self._list.itemActivated.connect(self._on_item)
        self._list.closed.connect(self.close)
        card_layout.addWidget(self._list)
        outer.addWidget(self._card)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    # ── 接口 ─────────────────────────────────────────────

    def list_widget(self) -> QListWidget:
        return self._list

    def prepare(self, min_width: int = 0) -> None:
        """按项目数计算列表/弹层尺寸（宽度取 combo / 外框 / 内容最大者）"""
        count = self._list.count()
        visible = max(1, min(count, _MAX_VISIBLE_ITEMS))
        self._list.setFixedHeight(visible * _ITEM_HEIGHT)
        width = max(self._combo.preferred_popup_width(), min_width, 160)
        self._list.setFixedWidth(width - 8)
        self.setFixedSize(
            width + 2 * _POPUP_MARGIN,
            visible * _ITEM_HEIGHT + 8 + 2 * _POPUP_MARGIN,
        )

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._delegate.set_colors(colors)
        self._list.viewport().update()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.closed.emit()

    def _on_item(self, item: QListWidgetItem) -> None:
        self.item_chosen.emit(self._list.row(item))
        self.close()


class MaterialComboBox(QComboBox):
    """MD3 下拉框（自绘 chevron + 自绘菜单弹层）"""

    def __init__(self, parent: QWidget | None = None,
                 colors: MaterialColors | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self._typography = MaterialTypography()
        self._chevron_visible = True
        self._anchor: QWidget | None = None
        self._popup: _ComboPopup | None = None

        self.setFont(self._typography.font("body_large"))
        self.setMinimumHeight(48)
        theme_controller().theme_changed.connect(self._on_theme_changed)

    # ── 嵌入 MaterialTextField ───────────────────────────

    def set_chevron_visible(self, visible: bool) -> None:
        """外框已绘制 chevron 时关闭自身箭头（避免双箭头）"""
        self._chevron_visible = bool(visible)
        self.update()

    def set_embedded(self, embedded: bool) -> None:
        """被浮动标签字段包裹时取消自身 48dp 最小高度"""
        self.setMinimumHeight(0 if embedded else 48)
        self.updateGeometry()

    def set_popup_anchor(self, anchor: QWidget | None) -> None:
        """弹层对齐到该控件（默认自身）——字段包裹时传外框"""
        self._anchor = anchor

    def _on_theme_changed(self, colors: MaterialColors) -> None:
        self._colors = colors
        if self._popup is not None:
            self._popup.set_colors(colors)
        self.update()

    # ── 几何 ─────────────────────────────────────────────

    def preferred_popup_width(self) -> int:
        """弹层需要的宽度：至少与 combo 等宽，长选项自动加宽"""
        metrics = QFontMetrics(self._typography.font("body_medium"))
        max_text = 0
        for i in range(self.count()):
            max_text = max(max_text, metrics.horizontalAdvance(self.itemText(i)))
        content = max_text + 2 * _H_PADDING + _CHECK_SIZE + Space.S + 8
        return max(self.width(), content, 160)

    # ── 弹层 ─────────────────────────────────────────────

    def showPopup(self) -> None:  # noqa: N802 - Qt 命名
        if self.count() == 0:
            return
        if self._popup is not None:
            self.hidePopup()

        anchor = self._anchor or self
        popup = _ComboPopup(self, self._colors)
        popup.item_chosen.connect(self._on_popup_item)
        popup.closed.connect(self._on_popup_closed)
        popup.prepare(min_width=anchor.width())

        anchor_top_left = anchor.mapToGlobal(QPoint(0, 0))
        below_y = anchor_top_left.y() + anchor.height() + 4 - _POPUP_MARGIN
        above_y = (
            anchor_top_left.y()
            - popup.height()
            + 8
        )
        x = anchor_top_left.x() - _POPUP_MARGIN

        screen = (
            QGuiApplication.screenAt(anchor.mapToGlobal(anchor.rect().center()))
            or QGuiApplication.primaryScreen()
        )
        available = screen.availableGeometry() if screen is not None else None
        if available is not None:
            x = min(max(available.left(), x), available.right() - popup.width() + 1)
            if below_y + popup.height() > available.bottom():
                y = max(available.top(), above_y)
            else:
                y = below_y
        else:
            y = below_y

        popup.move(x, y)
        popup.show()
        popup.raise_()
        popup.list_widget().setFocus(Qt.FocusReason.PopupFocusReason)
        popup.list_widget().setCurrentRow(max(0, self.currentIndex()))
        popup.list_widget().scrollToItem(popup.list_widget().currentItem())
        self._popup = popup

    def hidePopup(self) -> None:  # noqa: N802 - Qt 命名
        popup = self._popup
        self._popup = None
        if popup is not None:
            popup.close()

    def _on_popup_item(self, index: int) -> None:
        self.setCurrentIndex(index)
        self.hidePopup()

    def _on_popup_closed(self) -> None:
        self._popup = None

    # ── 键盘 ─────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._popup is not None:
            super().keyPressEvent(event)
            return
        if event.key() in (
            Qt.Key.Key_Down,
            Qt.Key.Key_F4,
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.showPopup()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Up:
            if self.count():
                self.setCurrentIndex(max(0, self.currentIndex() - 1))
            event.accept()
            return
        super().keyPressEvent(event)

    # ── 绘制 ─────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._chevron_visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        color = (
            self._colors.on_surface_variant
            if self.isEnabled()
            else blend(
                self._colors.surface,
                self._colors.on_surface,
                StateLayer.DISABLED_CONTENT,
            ).name()
        )
        # 统一使用 Material Symbols Rounded 的 expand_more（24dp），
        # 不再手绘不同线宽的 chevron，保证与下拉/折叠图标同族同粗细。
        if has_icon("expand_more"):
            pixmap = make_icon_pixmap("expand_more", color, size_px=24)
            if pixmap is not None:
                x = self.width() - Space.M - 24
                y = (self.height() - 24) // 2
                painter.drawPixmap(x, y, pixmap)
        painter.end()
