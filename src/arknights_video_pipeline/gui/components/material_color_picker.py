"""
gui.components.material_color_picker - Material Design 3 颜色选择器

提供：
- ``ColorSwatchButton``：圆角颜色预览色块，实时显示当前颜色，点击弹出调色盘；
- ``ColorPickerDialog``：MD3 风格调色盘对话框（SV 取色区 + 色相条 +
  HEX 输入 + 预设色板），支持深浅主题切换。

与 ``settings_row_builders.build_color_row`` 配合，为设置页中所有
#RRGGBB 颜色输入框提供可视化调色能力：色块位于输入框左侧预览，
点击后以模态对话框形式调色。
"""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt, QRegularExpression, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen,
    QRegularExpressionValidator,
)
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import CardFrame
from arknights_video_pipeline.gui.i18n import tr
from arknights_video_pipeline.gui.theme import (
    MaterialColors,
    filled_button_qss as _build_filled_button_qss,
    outlined_button_qss as _build_outlined_button_qss,
)

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# 预设色板：黑白灰 + Material 常用色（500 档）
_PRESET_COLORS = [
    "#000000", "#FFFFFF", "#9E9E9E", "#F44336", "#FF9800", "#FFEB3B",
    "#4CAF50", "#2196F3", "#3F51B5", "#9C27B0", "#E91E63", "#00BCD4",
]
# 预设色板中随主题刷新的 Material 颜色角色
_PRESET_TOKENS = ("primary", "secondary", "error", "success", "warning")


def _hex_edit_qss(colors: MaterialColors, error: bool = False) -> str:
    """HEX 输入框 QSS：与 settings_row_builders._lineedit_qss 视觉一致"""
    border = (f"2px solid {colors.error}" if error
              else f"1px solid {colors.outline_variant}")
    return (
        "QLineEdit {"
        f"  background-color: {colors.surface_variant};"
        f"  color: {colors.on_surface};"
        f"  border: {border};"
        "  border-radius: 12px;"
        "  padding: 8px 12px;"
        "  min-height: 20px;"
        "}"
        "QLineEdit:focus {"
        f"  border: 2px solid {colors.primary};"
        "}"
    )


def _swatch_qss(hex_color: str, colors: MaterialColors) -> str:
    """小色块 QSS（对话框内预览与预设色板通用）"""
    return (
        f"background-color: {hex_color};"
        f" border-radius: 12px;"
        f" border: 1px solid {colors.outline_variant};"
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# ── SV / 色相 取色控件 ──────────────────────────────────

class _HueSquare(QWidget):
    """SV（饱和度/亮度）2D 取色区：左上白、右上当前色相纯色、下沿黑色

    使用两层渐变绘制：横向 白→纯色相，纵向 透明→黑，即标准 HSV 平面。
    """

    color_changed = pyqtSignal()

    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self._colors = MaterialColors.light()
        self.setFixedSize(220, 150)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def color(self) -> QColor:
        return self._color

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    def _pos_to_color(self, pos) -> None:
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if rect.width() <= 0 or rect.height() <= 0:
            return
        s = _clamp01((pos.x() - rect.left()) / rect.width())
        v = 1.0 - _clamp01((pos.y() - rect.top()) / rect.height())
        hue = max(self._color.hue(), 0)
        self._color = QColor.fromHsv(hue, int(s * 255), int(v * 255))
        self.update()
        self.color_changed.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pos_to_color(event.position())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pos_to_color(event.position())
        super().mouseMoveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.setClipPath(path)

        # 横向：白 → 纯色相
        h_grad = QLinearGradient(rect.topLeft(), rect.topRight())
        h_grad.setColorAt(0.0, QColor(Qt.GlobalColor.white))
        h_grad.setColorAt(1.0, QColor.fromHsv(max(self._color.hue(), 0), 255, 255))
        painter.fillRect(rect, h_grad)
        # 纵向：透明 → 黑
        v_grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        v_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        v_grad.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.fillRect(rect, v_grad)
        painter.setClipping(False)

        # 圆角描边
        pen = QPen(QColor(self._colors.outline_variant))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 12, 12)

        # 指示器：白圈 + 内侧细黑线，保证任意底色下可见
        s, v = self._color.saturationF(), self._color.valueF()
        center = QPointF(rect.left() + s * rect.width(),
                         rect.top() + (1.0 - v) * rect.height())
        pen = QPen(QColor("#FFFFFF"))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawEllipse(center, 7.0, 7.0)
        pen = QPen(QColor(0, 0, 0, 130))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawEllipse(center, 5.5, 5.5)


class _HueBar(QWidget):
    """色相条：HSV 彩虹渐变，左右拖动修改色相"""

    color_changed = pyqtSignal()

    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self._colors = MaterialColors.light()
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def color(self) -> QColor:
        return self._color

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    def _pos_to_color(self, pos) -> None:
        rect = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        if rect.width() <= 0:
            return
        frac = _clamp01((pos.x() - rect.left()) / rect.width())
        self._color = QColor.fromHsv(int(frac * 359.0), 255, 255)
        self.update()
        self.color_changed.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pos_to_color(event.position())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pos_to_color(event.position())
        super().mouseMoveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 9, 9)
        painter.setClipPath(path)

        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        for i in range(7):
            grad.setColorAt(i / 6.0,
                            QColor.fromHsv(int(i / 6.0 * 359.0), 255, 255))
        painter.fillRect(rect, grad)
        painter.setClipping(False)

        pen = QPen(QColor(self._colors.outline_variant))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 9, 9)

        # 指示器：白色竖线 + 黑色细线
        frac = max(self._color.hue(), 0) / 359.0
        x = rect.left() + frac * rect.width()
        for color, width in (("#FFFFFF", 2.0), ("#000000", 1.0)):
            pen = QPen(QColor(color))
            pen.setWidthF(width)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, rect.top() + 1),
                             QPointF(x, rect.bottom() - 1))


# ── 色块预览按钮 ────────────────────────────────────────

class ColorSwatchButton(QWidget):
    """圆角颜色预览色块：显示当前颜色，点击发射 clicked 信号

    MD3 风格交互反馈：hover 时 primary 描边、按下时 primary_container
    填充，disabled 时置灰。由 build_color_row 连接后弹出调色盘对话框。
    """

    clicked = pyqtSignal()

    def __init__(self, color: str = "#FFFFFF",
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        parsed = QColor(color)
        self._color = parsed if parsed.isValid() else QColor("#FFFFFF")
        self._hovered = False
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(32, 32)
        # 防止默认窗口背景在圆角边缘透出
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: transparent; border: none;")

    def color(self) -> str:
        return self._color.name().upper()

    def set_color(self, hex_color: str) -> None:
        parsed = QColor(hex_color)
        if parsed.isValid():
            self._color = parsed
            self.update()

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            self.update()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._colors
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = 8.0

        if self.isEnabled():
            painter.setBrush(QColor(self._color))
        else:
            painter.setBrush(QColor(c.surface_variant))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, radius, radius)

        if self.isEnabled() and self._pressed:
            pen = QPen(QColor(c.primary_container))
            pen.setWidthF(2.0)
        elif self.isEnabled() and self._hovered:
            pen = QPen(QColor(c.primary))
            pen.setWidthF(2.0)
        else:
            pen = QPen(QColor(c.outline_variant))
            pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)


# ── 调色盘对话框 ────────────────────────────────────────

class ColorPickerDialog(QDialog):
    """MD3 风格调色盘对话框

    包含 SV 取色区、色相条、HEX 输入框与预设色板，实时联动；
    确认后通过 ``get_color()`` 返回 ``#RRGGBB`` 文本。
    """

    def __init__(self, initial: str = "#FFFFFF",
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        parsed = QColor(initial)
        self._color = parsed if parsed.isValid() else QColor("#FFFFFF")
        self.setWindowTitle(tr("dialog.color_picker"))
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = CardFrame()
        self._card = card
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(16)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 顶部：当前色预览 + 标题
        header = QHBoxLayout()
        header.setSpacing(16)
        self._preview_lbl = QLabel()
        self._preview_lbl.setFixedSize(48, 48)
        header.addWidget(self._preview_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        title_lbl = QLabel(tr("dialog.color_picker"))
        title_lbl.setStyleSheet(
            "background: transparent; border: none;"
            " font-weight: 500; font-size: 16px;"
        )
        header.addWidget(title_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        card_layout.addLayout(header)

        # SV 取色区 + 色相条
        self._sv_area = _HueSquare(self._color)
        card_layout.addWidget(self._sv_area)
        self._hue_bar = _HueBar(self._color)
        card_layout.addWidget(self._hue_bar)

        # HEX 输入行
        hex_row = QHBoxLayout()
        hex_row.setSpacing(8)
        hex_lbl = QLabel("HEX")
        hex_lbl.setStyleSheet(
            "background: transparent; border: none;"
            " font-weight: 500; font-size: 13px;"
        )
        hex_row.addWidget(hex_lbl)
        self._hex_edit = QLineEdit()
        self._hex_edit.setPlaceholderText("#RRGGBB")
        self._hex_edit.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"^#[0-9A-Fa-f]{0,6}$")))
        hex_row.addWidget(self._hex_edit, 1)
        card_layout.addLayout(hex_row)

        # 预设色板（基础色 + 主题色角色）
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        self._preset_buttons: list[tuple[QPushButton, str, bool]] = []
        for preset in _PRESET_COLORS:
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked=False, h=preset: self._apply_preset(h))
            preset_row.addWidget(btn)
            self._preset_buttons.append((btn, preset, False))
        for token in _PRESET_TOKENS:
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked=False, t=token: self._apply_preset(
                    getattr(self._colors, t)))
            preset_row.addWidget(btn)
            self._preset_buttons.append((btn, token, True))
        preset_row.addStretch(1)
        card_layout.addLayout(preset_row)

        # 按钮行：取消（outlined）+ 确定（filled）
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.setContentsMargins(0, 4, 0, 0)
        button_row.addStretch()
        self._cancel_btn = MaterialButton(
            tr("dialog.cancel"), variant=MaterialButton.VARIANT_OUTLINED)
        self._cancel_btn.setMinimumWidth(96)
        self._cancel_btn.setMinimumHeight(40)
        self._cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self._cancel_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._ok_btn = MaterialButton(tr("dialog.ok"))
        self._ok_btn.setMinimumWidth(96)
        self._ok_btn.setMinimumHeight(40)
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self.accept)
        button_row.addWidget(self._ok_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        card_layout.addLayout(button_row)

        outer.addWidget(card)

        # 信号联动
        self._sv_area.color_changed.connect(self._on_pickers_changed)
        self._hue_bar.color_changed.connect(self._on_pickers_changed)
        self._hex_edit.textChanged.connect(self._on_hex_changed)

        # 先把合法的初始颜色同步到 HEX 输入框，再统一刷新样式：
        # 若先 _apply_colors，此时 HEX 输入框还是空文本（非法），会被
        # 误标为错误（红）边框，导致打开对话框即显示红框
        self._sync_controls(update_hex=True)
        self._apply_colors()
        self.adjustSize()

    # ── 公开 API ─────────────────────────────────────────

    def get_color(self) -> str:
        """返回当前选中颜色（#RRGGBB 大写）"""
        return self._color.name().upper()

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._apply_colors()

    # ── 事件处理 ─────────────────────────────────────────

    def _on_pickers_changed(self) -> None:
        sv_color = self._sv_area.color()
        hue = max(self._hue_bar.color().hue(), 0)
        self._color = QColor.fromHsv(
            hue, sv_color.saturation(), sv_color.value())
        self._sync_controls(update_hex=True)

    def _on_hex_changed(self, text: str) -> None:
        if _COLOR_RE.match(text):
            self._color = QColor(text)
            self._sync_controls(update_hex=False)
        else:
            # 非法（含尚未输完）输入：立即标记错误边框，提供即时反馈
            self._hex_edit.setStyleSheet(_hex_edit_qss(self._colors, error=True))

    def _apply_preset(self, hex_color: str) -> None:
        parsed = QColor(hex_color)
        if not parsed.isValid():
            return
        self._color = parsed
        self._sync_controls(update_hex=True)

    def _sync_controls(self, update_hex: bool) -> None:
        self._sv_area.set_color(self._color)
        self._hue_bar.set_color(self._color)
        if update_hex:
            self._hex_edit.blockSignals(True)
            self._hex_edit.setText(self._color.name().upper())
            self._hex_edit.blockSignals(False)
        self._preview_lbl.setStyleSheet(_swatch_qss(
            self._color.name(), self._colors))
        # HEX 输入框边框随校验状态刷新：合法→正常边框，非法→错误边框
        # （程序化 setText 后 textChanged 不触发，需在此统一刷新）
        valid = bool(_COLOR_RE.match(self._hex_edit.text()))
        self._hex_edit.setStyleSheet(_hex_edit_qss(self._colors, error=not valid))

    # ── 主题同步 ─────────────────────────────────────────

    def _apply_colors(self) -> None:
        c = self._colors
        self._card.set_surface_color(c.surface)
        self._sv_area.set_colors(c)
        self._hue_bar.set_colors(c)
        valid = bool(_COLOR_RE.match(self._hex_edit.text()))
        self._hex_edit.setStyleSheet(_hex_edit_qss(c, error=not valid))
        self._cancel_btn.setStyleSheet(_build_outlined_button_qss(c))
        self._ok_btn.setStyleSheet(_build_filled_button_qss(c))
        for btn, value, is_token in self._preset_buttons:
            color = getattr(c, value) if is_token else value
            btn.setStyleSheet(_swatch_qss(color, c))
        self._preview_lbl.setStyleSheet(
            _swatch_qss(self._color.name(), c))
