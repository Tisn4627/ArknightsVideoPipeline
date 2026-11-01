"""gui.components.message_dialog - MD3 Basic Dialog

规格（MD3）：

- 容器 28dp 圆角、``surface_container_high``、内边距 24dp、宽 280-560dp；
- 图标 24dp（无彩色底盘），颜色取 ``secondary`` / ``warning`` / ``error``；
- 标题 ``headline_small``（24/400），正文 ``body_medium``（14/400，
  ``on_surface_variant``）；
- 按钮为 **text 按钮**，右对齐、间距 8dp（历史上是彩色圆图标 + 实心按钮，
  属于"第三方卡片弹窗"的形态，与页面的克制语言脱节）。

取代 ``QMessageBox``，避免 OK / Yes / No 按钮被默认 QSS 裁切/遮挡。

支持四种用法：
    InfoDialog / WarningDialog / CriticalDialog —— 单按钮信息提示
    ConfirmDialog —— 取消 / 确认
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from arknights_video_pipeline.gui.assets.icons.nav_icons import make_icon_pixmap
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import CardFrame
from arknights_video_pipeline.gui.i18n import tr
from arknights_video_pipeline.gui.theme.colors import MaterialColors
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

        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(280)
        self.setMaximumWidth(560)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Space.XL, Space.XL, Space.XL, Space.XL)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # MD3 对话框容器：surface_container_high + 28dp 圆角 + elevation 3
        self._card = CardFrame(
            surface_role="surface_container_high",
            radius=ShapeRole.DIALOG,
            variant="elevated",
        )
        self._card.set_elevation(Elevation.DIALOG)
        self._card.setStyleSheet("background: transparent; border: none;")
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

        text_col = QVBoxLayout()
        text_col.setSpacing(Space.XS)
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
        self._title_label.setStyleSheet(
            f"color: {c.on_surface}; background: transparent; border: none;"
        )
        self._body_label.setStyleSheet(
            f"color: {c.on_surface_variant}; background: transparent; border: none;"
        )

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
