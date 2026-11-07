"""gui.components.message_dialog - MD3 Basic Dialog

规格（MD3）：

- **无边框 + 透明窗口**，28dp 圆角由 :class:`CardFrame` 自绘；四周 24dp
  透明边距承载 elevation 3 阴影；父窗口覆盖 32% ``scrim``；
- 容器 ``surface_container_high``、内边距 24dp、宽 280-560dp；
- 图标 24dp（无彩色底盘），颜色取 ``secondary`` / ``warning`` / ``error``；
- 标题 ``headline_small``（24/400），正文 ``body_medium``（14/400，
  ``on_surface_variant``），标题与正文间距 16dp；
- 按钮为 **text 按钮**，右对齐、间距 8dp（历史上是彩色圆图标 + 实心按钮，
  属于"第三方卡片弹窗"的形态，与页面的克制语言脱节）；
- 焦点环只在键盘导航时出现（鼠标点击 / 默认按钮不应长时间带描边）。

取代 ``QMessageBox``，避免 OK / Yes / No 按钮被默认 QSS 裁切/遮挡。

支持四种用法：
    InfoDialog / WarningDialog / CriticalDialog —— 单按钮信息提示
    ConfirmDialog —— 取消 / 确认
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from arknights_video_pipeline.gui.assets.icons.nav_icons import make_icon_pixmap
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import CardFrame
from arknights_video_pipeline.gui.i18n import tr
from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.palette import set_text_color
from arknights_video_pipeline.gui.theme.shape import ShapeRole
from arknights_video_pipeline.gui.theme.spacing import Space
from arknights_video_pipeline.gui.theme.state import Elevation
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = [
    "ConfirmDialog",
    "CriticalDialog",
    "InfoDialog",
    "WarningDialog",
]

_ICON_SIZE = 24
#: 无边框对话框四周留给 elevation 3 阴影的透明边距
_SHADOW_MARGIN = 24


class _BaseMessageDialog(QDialog):
    """MD3 基础对话框（图标 + 标题 + 正文 + 文本按钮）"""

    def __init__(
        self,
        title: str,
        text: str,
        icon_name: str,
        icon_role: str = "secondary",
        colors: MaterialColors | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self._icon_name = icon_name
        self._icon_role = icon_role
        self._typography = MaterialTypography()
        self._scrim: QWidget | None = None
        self._scrim_parent: QWidget | None = None

        self.setWindowTitle(title)
        self.setModal(True)
        # MD3 Basic Dialog 无标题栏：无边框 + 透明窗口，28dp 圆角由
        # CardFrame 自绘；四周 24dp 透明边距用于 level 3 阴影。
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            _SHADOW_MARGIN, _SHADOW_MARGIN, _SHADOW_MARGIN, _SHADOW_MARGIN
        )
        outer.setSpacing(0)

        # MD3 对话框容器：surface_container_high + 28dp 圆角 + elevation 3
        self._card = CardFrame(
            surface_role="surface_container_high",
            radius=ShapeRole.DIALOG,
            variant="elevated",
        )
        self._card.setMinimumWidth(280)
        self._card.setMaximumWidth(560)
        self._card.set_elevation(Elevation.DIALOG)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(Space.XL, Space.XL, Space.XL, Space.XL)
        card_layout.setSpacing(Space.XL)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = QHBoxLayout()
        header.setSpacing(Space.L)
        header.setContentsMargins(0, 0, 0, 0)

        self._icon = QLabel(self._card)
        self._icon.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("background: transparent; border: none;")
        header.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)

        # MD3：标题与正文间距 16dp（不是 4dp）
        text_col = QVBoxLayout()
        text_col.setSpacing(Space.L)
        text_col.setContentsMargins(0, 0, 0, 0)

        self._title_label = QLabel(title, self._card)
        self._title_label.setWordWrap(True)
        self._title_label.setFont(self._typography.font("headline_small"))
        text_col.addWidget(self._title_label)

        self._body_label = QLabel(text, self._card)
        self._body_label.setWordWrap(True)
        self._body_label.setFont(self._typography.font("body_medium"))
        text_col.addWidget(self._body_label)

        header.addLayout(text_col, 1)
        card_layout.addLayout(header)

        self._button_row = QHBoxLayout()
        self._button_row.setSpacing(Space.S)
        self._button_row.setContentsMargins(0, 0, 0, 0)
        self._button_row.addStretch()
        card_layout.addLayout(self._button_row)

        outer.addWidget(self._card)

        self._apply_colors()
        theme_controller().theme_changed.connect(self.set_colors)

    # ── 主题 ─────────────────────────────────────────────

    def _icon_color(self) -> str:
        c = self._colors
        return {
            "error": c.error,
            "warning": c.warning,
        }.get(self._icon_role, c.secondary)

    def _apply_colors(self) -> None:
        c = self._colors
        pixmap = make_icon_pixmap(self._icon_name, self._icon_color(), size_px=_ICON_SIZE)
        if pixmap is not None:
            self._icon.setPixmap(pixmap)
        # 文字色走 QPalette，避免 widget 级样式表写死控件调色板
        set_text_color(self._title_label, c.on_surface)
        set_text_color(self._body_label, c.on_surface_variant)

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._apply_colors()

    # ── 按钮工厂 ─────────────────────────────────────────

    def _add_button(self, text: str, *, primary: bool = False) -> MaterialButton:
        """追加一个 text 按钮（MD3 对话框的按钮形态）

        MD3 对话框的操作区使用 text 按钮，靠文字颜色而不是填充色表达
        "主操作"；``primary`` 仅决定按钮是否获得默认焦点。
        """
        button = MaterialButton(text, MaterialButton.VARIANT_TEXT)
        if primary:
            button.setDefault(True)
        button.setMinimumWidth(64)
        self._button_row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return button

    # ── 遮罩（scrim） ────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._install_scrim()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._remove_scrim()

    def _install_scrim(self) -> None:
        """在父窗口上覆盖 32% scrim（MD3 对话框遮罩）"""
        if self._scrim is not None:
            return
        parent = self.parentWidget()
        if parent is None or not parent.isVisible():
            return
        scrim = QWidget(parent)
        scrim.setObjectName("dialogScrim")
        scrim.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        scrim.setAutoFillBackground(True)
        color = QColor(self._colors.scrim)
        color.setAlphaF(0.32)
        palette = scrim.palette()
        palette.setColor(QPalette.ColorRole.Window, color)
        scrim.setPalette(palette)
        scrim.setGeometry(parent.rect())
        scrim.show()
        scrim.raise_()
        self._scrim = scrim
        self._scrim_parent = parent
        parent.installEventFilter(self)

    def _remove_scrim(self) -> None:
        parent = self._scrim_parent
        if parent is not None:
            parent.removeEventFilter(self)
        if self._scrim is not None:
            self._scrim.hide()
            self._scrim.deleteLater()
            self._scrim = None
        self._scrim_parent = None

    def eventFilter(self, obj, event) -> bool:
        # 父窗口缩放时同步 scrim 尺寸
        if (
            obj is self._scrim_parent
            and event.type() == QEvent.Type.Resize
            and self._scrim is not None
        ):
            self._scrim.setGeometry(self._scrim_parent.rect())
        return super().eventFilter(obj, event)


class InfoDialog(_BaseMessageDialog):
    """信息提示对话框（成功/普通信息，单个按钮）"""

    def __init__(self, title: str, text: str,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            title=title, text=text, icon_name="info", icon_role="secondary",
            colors=colors, parent=parent,
        )
        ok_btn = self._add_button(tr("dialog.ok"))
        ok_btn.clicked.connect(self.accept)
        self._ok_btn = ok_btn
        self.adjustSize()


class WarningDialog(_BaseMessageDialog):
    """警告对话框（单个按钮，warning 色调）"""

    def __init__(self, title: str, text: str,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            title=title, text=text, icon_name="warning", icon_role="warning",
            colors=colors, parent=parent,
        )
        ok_btn = self._add_button(tr("dialog.ok"))
        ok_btn.clicked.connect(self.accept)
        self._ok_btn = ok_btn
        self.adjustSize()


class CriticalDialog(_BaseMessageDialog):
    """严重错误对话框（单个按钮，error 色调）"""

    def __init__(self, title: str, text: str,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            title=title, text=text, icon_name="error", icon_role="error",
            colors=colors, parent=parent,
        )
        ok_btn = self._add_button(tr("dialog.ok"))
        ok_btn.clicked.connect(self.accept)
        self._ok_btn = ok_btn
        self.adjustSize()


class ConfirmDialog(_BaseMessageDialog):
    """确认对话框（取消 / 确认）"""

    CONFIRMED = 1
    CANCELLED = 0

    def __init__(self, title: str, text: str,
                 confirm_text: str | None = None,
                 cancel_text: str | None = None,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            title=title, text=text, icon_name="info", icon_role="secondary",
            colors=colors, parent=parent,
        )
        cancel_btn = self._add_button(cancel_text or tr("dialog.cancel"))
        cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn = cancel_btn

        confirm_btn = self._add_button(confirm_text or tr("dialog.confirm"), primary=True)
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self._on_confirm)
        self._confirm_btn = confirm_btn

        self.adjustSize()

    def _on_confirm(self) -> None:
        self.done(self.CONFIRMED)

    def _on_cancel(self) -> None:
        self.done(self.CANCELLED)
