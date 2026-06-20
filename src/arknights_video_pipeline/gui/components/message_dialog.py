"""
gui.components.message_dialog - Material 风格消息/确认对话框

采用与主页一致的 Material 风格：白色圆角卡片 + 主题色按钮。
取代 ``QMessageBox``，避免 OK / Yes / No 按钮被默认 QSS 裁切/遮挡。

支持三种使用方式：
    InfoDialog / WarningDialog / CriticalDialog —— 单按钮信息提示
    ConfirmDialog —— Yes / No 确认
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QSizePolicy,
)

from arknights_video_pipeline.gui.components.material_card import CardFrame
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.theme import (
    MaterialColors,
    filled_button_qss as _build_filled_button_qss,
    outlined_button_qss as _build_outlined_button_qss,
)


class _BaseMessageDialog(QDialog):
    """带圆形 icon + 标题 + 描述 + 按钮的 Material 风格 dialog。"""

    def __init__(self, title: str, text: str, icon_text: str, icon_bg: str,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        self.setWindowTitle(title)
        self.setModal(True)
        # 显式最小尺寸 + 适配内容高度，按钮不会被裁切
        self.setMinimumSize(360, 180)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        # 不设 WA_StyledBackground，让 QDialog 走系统背景，
        # 由 CardFrame 自身画白色圆角卡片，避免 minimum 失效

        outer = QVBoxLayout(self)
        # 较大外层 margin 防止按钮贴近屏幕边缘
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = CardFrame()
        self._card = card
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(16)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 顶部：圆形 icon（左对齐，不与标题挤在一起）
        header = QHBoxLayout()
        header.setSpacing(16)
        header.setContentsMargins(0, 0, 0, 0)
        icon = QLabel(icon_text)
        icon.setObjectName("msgIcon")
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"background-color: {icon_bg}; color: #FFFFFF;"
            " border: none; border-radius: 20px;"
            " font-size: 20px; font-weight: 600;"
        )
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        text_col.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("msgTitle")
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(
            f"color: {self._colors.on_surface}; background: transparent; border: none;"
            " font-size: 18px; font-weight: 600;"
        )
        text_col.addWidget(title_lbl)

        body_lbl = QLabel(text)
        body_lbl.setObjectName("msgBody")
        body_lbl.setWordWrap(True)
        body_lbl.setStyleSheet(
            f"color: {self._colors.on_surface_variant}; background: transparent; border: none;"
            " font-size: 14px; line-height: 1.5;"
        )
        text_col.addWidget(body_lbl)

        header.addLayout(text_col, 1)
        card_layout.addLayout(header)

        # 按钮行
        self._button_row = QHBoxLayout()
        self._button_row.setSpacing(8)
        self._button_row.setContentsMargins(0, 4, 0, 0)
        self._button_row.addStretch()
        card_layout.addLayout(self._button_row)

        outer.addWidget(card)
        # 先建按钮，再刷样式，最后适配尺寸
        self._build_buttons()
        self._apply_colors()
        self.adjustSize()

    # ── 子类钩子 ─────────────────────────────────────────
    def _build_buttons(self) -> None:
        """子类重写：在 self._button_row 中放置按钮。"""
        raise NotImplementedError

    # ── 主题同步 ─────────────────────────────────────────
    def _apply_colors(self) -> None:
        c = self._colors
        self._card.set_surface_color(c.surface)
        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "msgTitle":
                lbl.setStyleSheet(
                    f"color: {c.on_surface}; background: transparent; border: none;"
                    " font-size: 18px; font-weight: 600;"
                )
            elif lbl.objectName() == "msgBody":
                lbl.setStyleSheet(
                    f"color: {c.on_surface_variant}; background: transparent; border: none;"
                    " font-size: 14px; line-height: 1.5;"
                )
        # 让子类在颜色变化时重新构建按钮颜色
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        """子类可重写：根据 self._colors 刷新按钮样式。"""
        pass

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._apply_colors()

    # ── 按钮 QSS 工厂 ─────────────────────────────────────
    def _filled_button_qss(self, primary: bool = True) -> str:
        """filled button 内联 QSS，避免被全局 QPushButton 样式表覆盖。

        委托 gui.theme.button_qss.filled_button_qss 实现（修复 M15）。
        ``primary=False`` 时退化为 outlined 风格以保持向后兼容。
        """
        if primary:
            return _build_filled_button_qss(self._colors)
        return _build_outlined_button_qss(self._colors)

    def _outlined_button_qss(self) -> str:
        """outlined button 内联 QSS。

        委托 gui.theme.button_qss.outlined_button_qss 实现（修复 M15）。
        """
        return _build_outlined_button_qss(self._colors)


class InfoDialog(_BaseMessageDialog):
    """信息提示对话框（成功/普通信息，单个 OK 按钮）。"""

    def __init__(self, title: str, text: str,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            title=title, text=text,
            icon_text="i", icon_bg="#6750A4",  # secondary 主色
            colors=colors, parent=parent,
        )

    def _build_buttons(self) -> None:
        ok_btn = MaterialButton("OK")
        ok_btn.setMinimumWidth(96)
        ok_btn.setMinimumHeight(40)
        ok_btn.setStyleSheet(self._filled_button_qss(primary=True))
        ok_btn.clicked.connect(self.accept)
        self._button_row.addWidget(ok_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._ok_btn = ok_btn

    def _refresh_buttons(self) -> None:
        if getattr(self, "_ok_btn", None) is not None:
            self._ok_btn.setStyleSheet(self._filled_button_qss(primary=True))


class WarningDialog(_BaseMessageDialog):
    """警告对话框（单个 OK 按钮，error 主题色）。"""

    def __init__(self, title: str, text: str,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            title=title, text=text,
            icon_text="!", icon_bg="#B3261E",  # error 红
            colors=colors, parent=parent,
        )

    def _build_buttons(self) -> None:
        ok_btn = MaterialButton("OK")
        ok_btn.setMinimumWidth(96)
        ok_btn.setMinimumHeight(40)
        ok_btn.setStyleSheet(self._filled_button_qss(primary=True))
        ok_btn.clicked.connect(self.accept)
        self._button_row.addWidget(ok_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._ok_btn = ok_btn

    def _refresh_buttons(self) -> None:
        if getattr(self, "_ok_btn", None) is not None:
            self._ok_btn.setStyleSheet(self._filled_button_qss(primary=True))


class CriticalDialog(WarningDialog):
    """严重错误对话框（继承 WarningDialog，单个 OK 按钮）。"""
    pass


class ConfirmDialog(_BaseMessageDialog):
    """确认对话框（Cancel / Confirm 两个按钮）。"""

    CONFIRMED = 1
    CANCELLED = 0

    def __init__(self, title: str, text: str,
                 confirm_text: str = "Confirm",
                 cancel_text: str = "Cancel",
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        self._confirm_text = confirm_text
        self._cancel_text = cancel_text
        super().__init__(
            title=title, text=text,
            icon_text="?", icon_bg="#6750A4",
            colors=colors, parent=parent,
        )

    def _build_buttons(self) -> None:
        cancel_btn = MaterialButton(self._cancel_text, variant=MaterialButton.VARIANT_OUTLINED)
        cancel_btn.setMinimumWidth(96)
        cancel_btn.setMinimumHeight(40)
        cancel_btn.setStyleSheet(self._outlined_button_qss())
        cancel_btn.clicked.connect(self._on_cancel)
        self._button_row.addWidget(cancel_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._cancel_btn = cancel_btn

        confirm_btn = MaterialButton(self._confirm_text)
        confirm_btn.setMinimumWidth(96)
        confirm_btn.setMinimumHeight(40)
        confirm_btn.setStyleSheet(self._filled_button_qss(primary=True))
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self._on_confirm)
        self._button_row.addWidget(confirm_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._confirm_btn = confirm_btn

    def _refresh_buttons(self) -> None:
        if getattr(self, "_cancel_btn", None) is not None:
            self._cancel_btn.setStyleSheet(self._outlined_button_qss())
        if getattr(self, "_confirm_btn", None) is not None:
            self._confirm_btn.setStyleSheet(self._filled_button_qss(primary=True))

    def _on_confirm(self) -> None:
        self.done(self.CONFIRMED)

    def _on_cancel(self) -> None:
        self.done(self.CANCELLED)
