"""
gui.components.settings_row_builders - 可复用的设置行构建器

为 SettingsPage 提供一组通用的输入行构建函数，每种函数创建一个带标签的
控件行并返回 ``FieldRow`` 句柄，供调用方进行值读写、主题刷新和禁用控制。

所有构建器的视觉规格与 SettingsPage 中已有的控件（QSpinBox/QComboBox/QLineEdit）
保持完全一致：surface_variant 底色、outline_variant 边框、12px 圆角、
聚焦时 2px primary 边框。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit,
)

from arknights_video_pipeline.gui.components.file_selector import FileSelector
from arknights_video_pipeline.gui.components.material_switch import MaterialSwitch
from arknights_video_pipeline.gui.theme import MaterialColors


# ── QSS 辅助函数 ──────────────────────────────────────

def _spinbox_qss(colors: MaterialColors) -> str:
    """QSpinBox/QDoubleSpinBox 内联样式：与 SettingsPage._conc_spin_qss 一致"""
    return (
        "QSpinBox, QDoubleSpinBox {"
        f"  background-color: {colors.surface_variant};"
        f"  color: {colors.on_surface};"
        f"  border: 1px solid {colors.outline_variant};"
        f"  border-radius: 12px;"
        f"  padding: 8px 12px;"
        f"  min-height: 20px;"
        "}"
        "QSpinBox:focus, QDoubleSpinBox:focus {"
        f"  border: 2px solid {colors.primary};"
        "}"
        "QSpinBox:disabled, QDoubleSpinBox:disabled {"
        f"  background-color: {colors.surface_variant};"
        f"  color: {colors.on_surface_variant};"
        "}"
        "QSpinBox::up-button, QSpinBox::down-button,"
        "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {"
        "  width: 0px; border: none;"
        "}"
        "QSpinBox::up-arrow, QSpinBox::down-arrow,"
        "QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {"
        "  width: 0px; height: 0px; border: none;"
        "}"
    )


def _combo_qss(colors: MaterialColors, error: bool = False) -> str:
    """QComboBox 内联样式：与 SettingsPage._log_level_combo_qss 一致"""
    border = f"2px solid {colors.error}" if error else f"1px solid {colors.outline_variant}"
    return (
        "QComboBox {"
        f"  background-color: {colors.surface_variant};"
        f"  color: {colors.on_surface};"
        f"  border: {border};"
        f"  border-radius: 12px;"
        f"  padding: 8px 12px;"
        f"  min-height: 20px;"
        "}"
        "QComboBox:focus {"
        f"  border: 2px solid {colors.primary};"
        "}"
        "QComboBox:disabled {"
        f"  background-color: {colors.surface_variant};"
        f"  color: {colors.on_surface_variant};"
        "}"
        "QComboBox QAbstractItemView {"
        f"  background-color: {colors.surface};"
        f"  color: {colors.on_surface};"
        f"  border: 1px solid {colors.outline};"
        f"  border-radius: 8px;"
        f"  selection-background-color: {colors.primary_container};"
        f"  selection-color: {colors.on_primary_container};"
        f"  outline: none;"
        "}"
    )


def _lineedit_qss(colors: MaterialColors, error: bool = False) -> str:
    """QLineEdit 内联样式：与 FileSelector._edit_qss 一致"""
    border = f"2px solid {colors.error}" if error else f"1px solid {colors.outline_variant}"
    return (
        "QLineEdit {"
        f"  background-color: {colors.surface_variant};"
        f"  color: {colors.on_surface};"
        f"  border: {border};"
        f"  border-radius: 12px;"
        f"  padding: 8px 12px;"
        f"  min-height: 20px;"
        "}"
        "QLineEdit:focus {"
        f"  border: 2px solid {colors.primary};"
        "}"
        "QLineEdit:disabled {"
        f"  background-color: {colors.surface_variant};"
        f"  color: {colors.on_surface_variant};"
        "}"
    )


def _dim_label_style(colors: MaterialColors) -> str:
    return (
        f"color: {colors.on_surface_variant}; border: none;"
        f" background: transparent; font-weight: 500; font-size: 13px;"
    )


def _make_label(text: str, colors: MaterialColors) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_dim_label_style(colors))
    return lbl


# ── FieldRow 数据类 ────────────────────────────────────

@dataclass
class FieldRow:
    """构建器返回的句柄，封装控件的值读写、主题刷新和禁用控制

    Attributes:
        widget: 行容器 QWidget，添加到卡片布局中
        set_value: (value, block_signal) -> None，设置值并可选阻塞信号
        get_value: () -> Any，获取当前值
        set_colors: (MaterialColors) -> None，刷新主题色
        set_enabled: (bool) -> None，启用/禁用控件
    """
    widget: QWidget
    set_value: Callable[[Any, bool], None]
    get_value: Callable[[], Any]
    set_colors: Callable[[MaterialColors], None]
    set_enabled: Callable[[bool], None]


# ── 行布局辅助 ─────────────────────────────────────────

def _make_row(label_text: str, colors: MaterialColors) -> tuple[QWidget, QHBoxLayout]:
    """创建带标签的行容器，返回 (container, content_layout)"""
    container = QWidget()
    container.setStyleSheet("background: transparent; border: none;")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    lbl = _make_label(label_text, colors)
    lbl.setFixedWidth(140)
    layout.addWidget(lbl)
    return container, layout


def _make_switch_row(label_text: str, desc: str, colors: MaterialColors) -> tuple[QWidget, QVBoxLayout, MaterialSwitch]:
    """创建带标题+描述的开关行容器，返回 (container, text_box, switch)"""
    container = QWidget()
    container.setStyleSheet("background: transparent; border: none;")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.setSpacing(16)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    text_box = QVBoxLayout()
    text_box.setSpacing(4)
    text_box.setAlignment(Qt.AlignmentFlag.AlignTop)
    title = QLabel(label_text)
    title.setStyleSheet("border: none; background: transparent;")
    title.setFont(_title_font())
    text_box.addWidget(title)

    if desc:
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        text_box.addWidget(desc_lbl)

    layout.addLayout(text_box, 1)
    switch = MaterialSwitch(checked=False, colors=colors)
    layout.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
    return container, text_box, switch


def _title_font():
    from PyQt6.QtGui import QFont
    f = QFont()
    f.setPointSize(11)
    f.setWeight(QFont.Weight.Medium)
    return f


# ── 构建函数 ───────────────────────────────────────────

def build_switch_row(
    label: str,
    desc: str = "",
    default: bool = False,
    colors: MaterialColors | None = None,
    on_changed: Callable[[bool], None] | None = None,
) -> FieldRow:
    """布尔开关行：左侧标题+描述，右侧 MaterialSwitch"""
    c = colors or MaterialColors.light()
    container, text_box, switch = _make_switch_row(label, desc, c)

    dim_labels = [w for w in (text_box.itemAt(1).widget() if text_box.count() > 1 else None,) if w is not None]

    if on_changed:
        switch.toggled.connect(on_changed)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            switch.blockSignals(True)
        switch.set_checked(bool(val))
        if block_signal:
            switch.blockSignals(False)

    def get_value() -> bool:
        return switch.is_checked()

    def set_colors(new_colors: MaterialColors) -> None:
        switch.set_colors(new_colors)
        for lbl in dim_labels:
            lbl.setStyleSheet(
                f"color: {new_colors.on_surface_variant}; border: none;"
                f" background: transparent;"
            )

    def set_enabled(enabled: bool) -> None:
        switch.setEnabled(enabled)

    return FieldRow(container, set_value, get_value, set_colors, set_enabled)


def build_int_row(
    label: str,
    default: int = 0,
    minimum: int = 0,
    maximum: int = 999999,
    step: int = 1,
    colors: MaterialColors | None = None,
    on_changed: Callable[[int], None] | None = None,
) -> FieldRow:
    """整数输入行：标签 + QSpinBox（隐藏箭头）"""
    c = colors or MaterialColors.light()
    container, layout = _make_row(label, c)
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(default)
    spin.setSingleStep(step)
    spin.setStyleSheet(_spinbox_qss(c))
    layout.addWidget(spin, 1)

    if on_changed:
        spin.valueChanged.connect(on_changed)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            spin.blockSignals(True)
        try:
            spin.setValue(int(val))
        except (TypeError, ValueError):
            spin.setValue(default)
        if block_signal:
            spin.blockSignals(False)

    def get_value() -> int:
        return spin.value()

    def set_colors(new_colors: MaterialColors) -> None:
        spin.setStyleSheet(_spinbox_qss(new_colors))
        label_w = layout.itemAt(0).widget()
        label_w.setStyleSheet(_dim_label_style(new_colors))

    def set_enabled(enabled: bool) -> None:
        spin.setEnabled(enabled)

    return FieldRow(container, set_value, get_value, set_colors, set_enabled)


def build_float_row(
    label: str,
    default: float = 0.0,
    minimum: float = 0.0,
    maximum: float = 999999.0,
    step: float = 0.1,
    decimals: int = 2,
    colors: MaterialColors | None = None,
    on_changed: Callable[[float], None] | None = None,
) -> FieldRow:
    """浮点数输入行：标签 + QDoubleSpinBox（隐藏箭头）"""
    c = colors or MaterialColors.light()
    container, layout = _make_row(label, c)
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(default)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setStyleSheet(_spinbox_qss(c))
    layout.addWidget(spin, 1)

    if on_changed:
        spin.valueChanged.connect(on_changed)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            spin.blockSignals(True)
        try:
            spin.setValue(float(val))
        except (TypeError, ValueError):
            spin.setValue(default)
        if block_signal:
            spin.blockSignals(False)

    def get_value() -> float:
        return spin.value()

    def set_colors(new_colors: MaterialColors) -> None:
        spin.setStyleSheet(_spinbox_qss(new_colors))
        label_w = layout.itemAt(0).widget()
        label_w.setStyleSheet(_dim_label_style(new_colors))

    def set_enabled(enabled: bool) -> None:
        spin.setEnabled(enabled)

    return FieldRow(container, set_value, get_value, set_colors, set_enabled)


def build_combo_row(
    label: str,
    items: list[str],
    default: str = "",
    colors: MaterialColors | None = None,
    on_changed: Callable[[str], None] | None = None,
) -> FieldRow:
    """下拉选择行：标签 + QComboBox"""
    c = colors or MaterialColors.light()
    container, layout = _make_row(label, c)
    combo = QComboBox()
    combo.addItems(items)
    if default and default in items:
        combo.setCurrentText(default)
    combo.setStyleSheet(_combo_qss(c))
    layout.addWidget(combo, 1)

    if on_changed:
        combo.currentTextChanged.connect(on_changed)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            combo.blockSignals(True)
        idx = combo.findText(str(val))
        if idx >= 0:
            combo.setCurrentIndex(idx)
        if block_signal:
            combo.blockSignals(False)

    def get_value() -> str:
        return combo.currentText()

    def set_colors(new_colors: MaterialColors) -> None:
        combo.setStyleSheet(_combo_qss(new_colors))
        label_w = layout.itemAt(0).widget()
        label_w.setStyleSheet(_dim_label_style(new_colors))

    def set_enabled(enabled: bool) -> None:
        combo.setEnabled(enabled)

    return FieldRow(container, set_value, get_value, set_colors, set_enabled)


def build_path_row(
    label: str,
    mode: str = FileSelector.MODE_DIRECTORY,
    colors: MaterialColors | None = None,
    on_changed: Callable[[str], None] | None = None,
) -> FieldRow:
    """路径选择行：FileSelector"""
    c = colors or MaterialColors.light()
    selector = FileSelector(mode=mode, label=label)
    selector.set_colors(c)

    if on_changed:
        selector.path_changed.connect(on_changed)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            selector.blockSignals(True)
        selector.set_path(str(val) if val else "")
        if block_signal:
            selector.blockSignals(False)

    def get_value() -> str:
        return selector.path()

    def set_colors(new_colors: MaterialColors) -> None:
        selector.set_colors(new_colors)

    def set_enabled(enabled: bool) -> None:
        selector.setEnabled(enabled)

    return FieldRow(selector, set_value, get_value, set_colors, set_enabled)


def build_string_row(
    label: str,
    default: str = "",
    colors: MaterialColors | None = None,
    on_changed: Callable[[str], None] | None = None,
) -> FieldRow:
    """字符串输入行：标签 + QLineEdit"""
    c = colors or MaterialColors.light()
    container, layout = _make_row(label, c)
    edit = QLineEdit()
    edit.setText(default)
    edit.setStyleSheet(_lineedit_qss(c))
    layout.addWidget(edit, 1)

    if on_changed:
        edit.textChanged.connect(on_changed)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            edit.blockSignals(True)
        edit.setText(str(val) if val is not None else "")
        if block_signal:
            edit.blockSignals(False)

    def get_value() -> str:
        return edit.text()

    def set_colors(new_colors: MaterialColors) -> None:
        edit.setStyleSheet(_lineedit_qss(new_colors))
        label_w = layout.itemAt(0).widget()
        label_w.setStyleSheet(_dim_label_style(new_colors))

    def set_enabled(enabled: bool) -> None:
        edit.setEnabled(enabled)

    return FieldRow(container, set_value, get_value, set_colors, set_enabled)


_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def build_color_row(
    label: str,
    default: str = "#FFFFFF",
    colors: MaterialColors | None = None,
    on_changed: Callable[[str], None] | None = None,
) -> FieldRow:
    """颜色输入行：标签 + QLineEdit（#RRGGBB 格式校验）"""
    c = colors or MaterialColors.light()
    container, layout = _make_row(label, c)
    edit = QLineEdit()
    edit.setText(default)
    edit.setPlaceholderText("#RRGGBB")
    validator = QRegularExpressionValidator(
        QRegularExpression(r"^#[0-9A-Fa-f]{0,6}$")
    )
    edit.setValidator(validator)
    edit.setStyleSheet(_lineedit_qss(c))
    layout.addWidget(edit, 1)

    _is_valid = [True]

    def _check_valid(text: str) -> bool:
        valid = bool(_COLOR_RE.match(text))
        return valid

    def _on_text_changed(text: str) -> None:
        valid = _check_valid(text)
        if valid != _is_valid[0]:
            _is_valid[0] = valid
            edit.setStyleSheet(_lineedit_qss(c, error=not valid))
        if on_changed and valid:
            on_changed(text)

    edit.textChanged.connect(_on_text_changed)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            edit.blockSignals(True)
        text = str(val) if val else ""
        edit.setText(text)
        _is_valid[0] = _check_valid(text)
        edit.setStyleSheet(_lineedit_qss(c, error=not _is_valid[0]))
        if block_signal:
            edit.blockSignals(False)

    def get_value() -> str:
        return edit.text()

    def set_colors(new_colors: MaterialColors) -> None:
        nonlocal c
        c = new_colors
        edit.setStyleSheet(_lineedit_qss(c, error=not _is_valid[0]))
        label_w = layout.itemAt(0).widget()
        label_w.setStyleSheet(_dim_label_style(new_colors))

    def set_enabled(enabled: bool) -> None:
        edit.setEnabled(enabled)

    return FieldRow(container, set_value, get_value, set_colors, set_enabled)


def build_range_row(
    label: str,
    default_min: float = 0.0,
    default_max: float = 1.0,
    minimum: float = 0.0,
    maximum: float = 100.0,
    step: float = 0.1,
    decimals: int = 2,
    colors: MaterialColors | None = None,
    on_changed: Callable[[list[float]], None] | None = None,
) -> FieldRow:
    """范围输入行：标签 + 两个 QDoubleSpinBox（min/max），on_changed 收到 [min, max]"""
    c = colors or MaterialColors.light()
    container, layout = _make_row(label, c)

    spin_min = QDoubleSpinBox()
    spin_min.setRange(minimum, maximum)
    spin_min.setValue(default_min)
    spin_min.setSingleStep(step)
    spin_min.setDecimals(decimals)
    spin_min.setStyleSheet(_spinbox_qss(c))
    layout.addWidget(spin_min, 1)

    sep = QLabel("–")
    sep.setStyleSheet(_dim_label_style(c))
    layout.addWidget(sep)

    spin_max = QDoubleSpinBox()
    spin_max.setRange(minimum, maximum)
    spin_max.setValue(default_max)
    spin_max.setSingleStep(step)
    spin_max.setDecimals(decimals)
    spin_max.setStyleSheet(_spinbox_qss(c))
    layout.addWidget(spin_max, 1)

    def _emit() -> None:
        if on_changed:
            on_changed([spin_min.value(), spin_max.value()])

    spin_min.valueChanged.connect(_emit)
    spin_max.valueChanged.connect(_emit)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if not isinstance(val, (list, tuple)) or len(val) != 2:
            return
        if block_signal:
            spin_min.blockSignals(True)
            spin_max.blockSignals(True)
        try:
            spin_min.setValue(float(val[0]))
            spin_max.setValue(float(val[1]))
        except (TypeError, ValueError):
            pass
        if block_signal:
            spin_min.blockSignals(False)
            spin_max.blockSignals(False)

    def get_value() -> list[float]:
        return [spin_min.value(), spin_max.value()]

    def set_colors(new_colors: MaterialColors) -> None:
        spin_min.setStyleSheet(_spinbox_qss(new_colors))
        spin_max.setStyleSheet(_spinbox_qss(new_colors))
        sep.setStyleSheet(_dim_label_style(new_colors))
        label_w = layout.itemAt(0).widget()
        label_w.setStyleSheet(_dim_label_style(new_colors))

    def set_enabled(enabled: bool) -> None:
        spin_min.setEnabled(enabled)
        spin_max.setEnabled(enabled)

    return FieldRow(container, set_value, get_value, set_colors, set_enabled)


def build_nullable_int_row(
    label: str,
    default: int | None = None,
    minimum: int = 0,
    maximum: int = 999999,
    colors: MaterialColors | None = None,
    on_changed: Callable[[int | None], None] | None = None,
) -> FieldRow:
    """可空整数行：MaterialSwitch + QSpinBox。开关关闭时值为 None"""
    c = colors or MaterialColors.light()
    container, layout = _make_row(label, c)

    switch = MaterialSwitch(checked=default is not None, colors=c)
    layout.addWidget(switch)

    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(default if default is not None else minimum)
    spin.setSingleStep(1)
    spin.setStyleSheet(_spinbox_qss(c))
    spin.setEnabled(default is not None)
    layout.addWidget(spin, 1)

    def _emit() -> None:
        if on_changed:
            if switch.is_checked():
                on_changed(spin.value())
            else:
                on_changed(None)

    switch.toggled.connect(lambda checked: (
        spin.setEnabled(checked),
        _emit(),
    ))
    spin.valueChanged.connect(_emit)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            switch.blockSignals(True)
            spin.blockSignals(True)
        if val is None:
            switch.set_checked(False)
            spin.setEnabled(False)
        else:
            switch.set_checked(True)
            spin.setEnabled(True)
            try:
                spin.setValue(int(val))
            except (TypeError, ValueError):
                pass
        if block_signal:
            switch.blockSignals(False)
            spin.blockSignals(False)

    def get_value() -> int | None:
        if switch.is_checked():
            return spin.value()
        return None

    def set_colors(new_colors: MaterialColors) -> None:
        switch.set_colors(new_colors)
        spin.setStyleSheet(_spinbox_qss(new_colors))
        label_w = layout.itemAt(0).widget()
        label_w.setStyleSheet(_dim_label_style(new_colors))

    def set_enabled(enabled: bool) -> None:
        switch.setEnabled(enabled)
        spin.setEnabled(enabled and switch.is_checked())

    return FieldRow(container, set_value, get_value, set_colors, set_enabled)
