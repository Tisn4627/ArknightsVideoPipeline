"""gui.components.settings_row_builders - 可复用的设置行构建器

为 SettingsPage 提供一组通用的设置行构建函数，返回 ``FieldRow`` 句柄，
供调用方进行值读写、主题刷新和禁用控制。

行形态（MD3 桌面设置列表）：

```
[ 标题 (title_small 14/500)            ]   [ 控件 (最大 360dp) ]
[ 说明 (body_small 12/400, 可换行)      ]
```

- 标题与说明占左侧列，控件右对齐；窄窗时控件列可缩小到 240dp；
- 输入控件统一使用 MD3 outlined 文本字段（全局 QSS），字体 ``body_large``；
- 布尔项使用 ``MaterialSwitch``，不包输入框；
- 所有颜色来自 token，主题切换时由 ``set_colors`` / 组件自身订阅刷新。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from PyQt6.QtCore import QEvent, QObject, QSize, Qt, QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QBoxLayout, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QSizePolicy, QVBoxLayout, QWidget,
)

from arknights_video_pipeline.gui.components.file_selector import FileSelector
from arknights_video_pipeline.gui.components.material_color_picker import (
    ColorPickerDialog,
    ColorSwatchButton,
)
from arknights_video_pipeline.gui.components.material_combo import MaterialComboBox
from arknights_video_pipeline.gui.components.material_switch import MaterialSwitch
from arknights_video_pipeline.gui.theme import (
    MaterialColors,
    MaterialTypography,
    set_text_color,
)
from arknights_video_pipeline.gui.theme.spacing import Space
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller

#: 控件列最大宽度（单列设置页统一控件列，避免长文件名/路径被截断）
CONTROL_MAX_WIDTH = 420
#: 控件列最小宽度（窄窗下仍可输入，同时保证卡片可收缩到 compact 档）
CONTROL_MIN_WIDTH = 160
#: 行内垂直内边距（行间距由布局 spacing 提供，这里只留视觉呼吸）
ROW_PAD = 4
#: 左侧标签列最小宽度（英文长标签可换行，不再用固定 140px 截断）
TITLE_MIN_WIDTH = 120


# ── 颜色辅助 ──────────────────────────────────────────

def _title_font():
    """行标题字体：走统一字体工厂（title_small 14px/500）"""
    return MaterialTypography().font("title_small")


def _desc_font():
    return MaterialTypography().font("body_small")


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
        set_label: (text) -> None，刷新行标签文本（语言切换时调用）
        set_desc: (text) -> None，刷新行描述文本
    """
    widget: QWidget
    set_value: Callable[[Any, bool], None]
    get_value: Callable[[], Any]
    set_colors: Callable[[MaterialColors], None]
    set_enabled: Callable[[bool], None]
    set_label: Callable[[str], None] = field(default=lambda s: None)
    set_desc: Callable[[str], None] = field(default=lambda s: None)
    #: 仅路径行使用：设置文件对话框过滤器
    set_filter: Callable[[str], None] = field(default=lambda s: None)


# ── 行骨架 ─────────────────────────────────────────────

class _ControlHost(QWidget):
    """控件列宿主：按偏好宽度参与布局，但不抬高行的最小宽度

    字段行需要"控件列固定宽、整体靠右"；若直接 ``setFixedWidth`` 会把
    控件宽度写进行的最小宽度，窄窗时卡片无法收缩并产生横向滚动条。
    这里只覆盖 ``sizeHint``（布局按偏好宽度分配），最小宽度仍由内部
    控件自身的最小宽度决定，因此宽屏时控件列靠右、窄屏时正常收缩。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transparentPane")
        self._preferred_width = 0

    def set_preferred_width(self, width: int) -> None:
        width = max(0, int(width))
        if width == self._preferred_width:
            return
        self._preferred_width = width
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802 - 保持 Qt 命名
        base = super().sizeHint()
        return QSize(self._preferred_width or base.width(), base.height())


class _RowShell(QObject):
    """行骨架：左侧标题/说明 + 右侧控件槽

    构造后通过 :meth:`add_control` 放入控件；:meth:`set_colors` 只刷新
    标签配色（控件负责自己的主题订阅）。

    继承 ``QObject`` 并以行容器为 parent：主题信号的订阅随容器一起
    销毁，避免工具对话框关闭后仍在响应 ``theme_changed``。
    """

    def __init__(self, label: str, colors: MaterialColors, desc: str = "",
                 *, field: bool = False) -> None:
        self.container = QWidget()
        super().__init__(self.container)
        self._colors = colors
        self._field = field
        # 当前行控件自身的最大宽度（普通字段 420、紧凑组 160/168）；
        # 窄卡片堆叠时控件列按它取宽度，普通字段与路径行仍统一 420
        self._widget_max_width = 0
        # 字段行在窄卡片下改为"标签在上、控件在下"，避免 180dp 标签列
        # 挤压控件导致文件名/路径被截断
        self._stacked = False
        # 用 objectName + 全局 ID 选择器保持透明；不要给容器设置 widget 级
        # stylesheet —— 它会级联到子控件，把输入框的描边一起抹掉
        self.container.setObjectName("transparentPane")
        row = QHBoxLayout(self.container)
        row.setContentsMargins(0, ROW_PAD, 0, ROW_PAD)
        row.setSpacing(Space.L)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._row = row

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(Space.XS)
        self._text_col = text_col

        self.title = QLabel(label, self.container)
        self.title.setFont(_title_font())
        # 标题用默认文字色（QPalette::WindowText = on_surface），不设
        # widget 级样式表：既跟随全局调色板，也避免主题切换时逐行重设
        self.title.setWordWrap(True)
        if field:
            # 字段行：标签列至少 180dp（长标签可继续占宽，避免过早换行）；
            # 控件列由右侧宿主固定宽度，二者之间留伸缩空隙
            self.title.setMinimumWidth(TITLE_MIN_WIDTH + 60)
        else:
            self.title.setMinimumWidth(TITLE_MIN_WIDTH)
        self.title.setVisible(bool(label))
        text_col.addWidget(self.title)

        self.desc: QLabel | None = None
        if desc:
            self.desc = QLabel(desc, self.container)
            self.desc.setFont(_desc_font())
            set_text_color(self.desc, colors.on_surface_variant)
            self.desc.setWordWrap(True)
            # 允许 QLabel 通过 heightForWidth 增加行高，避免窄窗下第二行被裁切
            self.desc.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
            )
            text_col.addWidget(self.desc)

        self.container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )

        # 控件列统一放在靠右的宿主里：字段行与开关行的控件右缘因此对齐，
        # 宽卡片不再出现"左侧一列表单 + 右侧大片空白"的失衡
        self._control_host = _ControlHost(self.container)
        self._control_row = QHBoxLayout(self._control_host)
        self._control_row.setContentsMargins(0, 0, 0, 0)
        self._control_row.setSpacing(Space.S)
        # 标签/说明列占满剩余空间，控件宿主按偏好宽度贴右缘：
        # 字段行与开关行的控件右缘因此一致，说明文字也不会过早换行
        row.addLayout(text_col, 1)
        row.addWidget(self._control_host, 0)

        # 字段行的控件列宽度随行宽变化（宽屏上限 360dp，窄屏可收缩）
        self.container.installEventFilter(self)
        if field:
            self._sync_control_width()

        # 行自身订阅主题：无论行被放在哪个卡片、是否登记到 _field_rows，
        # 标题与说明都会随主题刷新（历史实现靠页面手工枚举，必有遗漏）
        theme_controller().theme_changed.connect(self.set_colors)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.container and event.type() == QEvent.Type.Resize:
            self._sync_control_width()
        return super().eventFilter(obj, event)

    def _sync_control_width(self) -> None:
        """字段行的控件列取"行宽 - 标签列 - 行间距"，并在宽屏封顶

        宿主只改变 sizeHint，不参与最小宽度计算，避免窄窗无法收缩。
        """
        if not self._field:
            return
        available = self.container.width()
        if available <= 0:
            return

        # 窄卡片：标签/说明在上，控件在下并占满可用宽度
        stacked = available < 460
        if stacked != self._stacked:
            self._stacked = stacked
            self._row.setDirection(
                QBoxLayout.Direction.TopToBottom if stacked
                else QBoxLayout.Direction.LeftToRight
            )
            if stacked:
                self._row.setAlignment(
                    self._control_host, Qt.AlignmentFlag.AlignLeft
                )
                self.title.setMinimumWidth(0)
            else:
                self._row.setAlignment(self._control_host, Qt.AlignmentFlag(0))
                self.title.setMinimumWidth(TITLE_MIN_WIDTH + 60)

        if stacked:
            # 堆叠时控件列取控件自身宽度（紧凑组 160/168 不被拉宽）
            width = min(self._widget_max_width or CONTROL_MAX_WIDTH, available)
        else:
            # 并排时所有字段统一 420dp，长文件名/路径不再被压缩
            width = available - (TITLE_MIN_WIDTH + 60) - self._row.spacing()
        width = max(CONTROL_MIN_WIDTH, min(CONTROL_MAX_WIDTH, width))
        self._control_host.set_preferred_width(width)

    def add_control(self, widget: QWidget, *, max_width: int = CONTROL_MAX_WIDTH,
                    expanding: bool = False, wide: bool = False,
                    align_end: bool = False) -> None:
        """把控件放到右侧

        Args:
            max_width: 输入类控件的最大宽度（保证各行控件对齐在同一列）
            expanding: 路径行等需要占满剩余空间的控件
            wide: 输入类控件；True 时拉伸到 ``max_width``（至少 240dp），
                布尔开关等紧凑控件保持自身尺寸
            align_end: 控件本身窄于控件列时靠右对齐（如可空整数行的
                开关+数值框组合、种子色值+色块），使其右缘与其他字段/
                开关对齐
        """
        if wide or expanding:
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            widget.setMaximumWidth(max_width)
            widget.setMinimumWidth(min(max_width, CONTROL_MIN_WIDTH))
            self._widget_max_width = max(self._widget_max_width, max_width)
        if align_end:
            self._control_row.addStretch(1)
        self._control_row.addWidget(widget, 1 if (wide or expanding) else 0)
        if self._field:
            self._sync_control_width()

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        # 标题跟随全局调色板（QPalette 传播），只有说明文字需要显式覆盖
        if self.desc is not None:
            set_text_color(self.desc, colors.on_surface_variant)

    def set_label(self, text: str) -> None:
        self.title.setText(text)

    def set_desc(self, text: str) -> None:
        if self.desc is not None:
            self.desc.setText(text)
        elif text:
            self.desc = QLabel(text, self.container)
            self.desc.setFont(_desc_font())
            set_text_color(self.desc, self._colors.on_surface_variant)
            self.desc.setWordWrap(True)
            self._text_col.addWidget(self.desc)


# ── 构建函数 ───────────────────────────────────────────

def make_row(
    label: str,
    control: QWidget,
    colors: MaterialColors | None = None,
    desc: str = "",
    *,
    max_width: int = CONTROL_MAX_WIDTH,
    expanding: bool = False,
    wide: bool = False,
    field: bool = False,
    align_end: bool = False,
) -> _RowShell:
    """把任意控件包成统一设置行（标题/说明 + 右侧控件）

    供少数需要保留控件引用（如 ``_log_level_combo``）的行使用；
    ``_RowShell`` 的 ``container`` 可直接加入卡片布局。
    """
    shell = _RowShell(label, colors or theme_controller().colors(), desc, field=field)
    shell.add_control(
        control, max_width=max_width, expanding=expanding, wide=wide,
        align_end=align_end,
    )
    return shell


def build_switch_row(
    label: str,
    desc: str = "",
    default: bool = False,
    colors: MaterialColors | None = None,
    on_changed: Callable[[bool], None] | None = None,
) -> FieldRow:
    """布尔开关行：左侧标题+描述，右侧 MaterialSwitch"""
    c = colors or theme_controller().colors()
    shell = _RowShell(label, c, desc)

    switch = MaterialSwitch(checked=default, colors=c)
    if on_changed:
        switch.toggled.connect(on_changed)
    shell.add_control(switch)

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
        shell.set_colors(new_colors)

    def set_enabled(enabled: bool) -> None:
        switch.setEnabled(enabled)

    return FieldRow(
        shell.container, set_value, get_value, set_colors, set_enabled,
        set_label=shell.set_label, set_desc=shell.set_desc,
    )


def build_int_row(
    label: str,
    default: int = 0,
    minimum: int = 0,
    maximum: int = 999999,
    step: int = 1,
    colors: MaterialColors | None = None,
    on_changed: Callable[[int], None] | None = None,
    desc: str = "",
) -> FieldRow:
    """整数输入行：左侧标签 + QSpinBox（隐藏箭头）"""
    c = colors or theme_controller().colors()
    shell = _RowShell(label, c, desc, field=True)

    spin = QSpinBox()
    spin.setObjectName("settingsField")
    spin.setFont(MaterialTypography().font("body_large"))
    spin.setRange(minimum, maximum)
    spin.setValue(default)
    spin.setSingleStep(step)
    shell.add_control(spin, wide=True)

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
        shell.set_colors(new_colors)

    def set_enabled(enabled: bool) -> None:
        spin.setEnabled(enabled)

    return FieldRow(shell.container, set_value, get_value, set_colors,
                    set_enabled, set_label=shell.set_label,
                    set_desc=shell.set_desc)


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
    """浮点数输入行：左侧标签 + QDoubleSpinBox（隐藏箭头）"""
    c = colors or theme_controller().colors()
    shell = _RowShell(label, c, field=True)

    spin = QDoubleSpinBox()
    spin.setObjectName("settingsField")
    spin.setFont(MaterialTypography().font("body_large"))
    spin.setRange(minimum, maximum)
    spin.setValue(default)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    shell.add_control(spin, wide=True)

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
        shell.set_colors(new_colors)

    def set_enabled(enabled: bool) -> None:
        spin.setEnabled(enabled)

    return FieldRow(shell.container, set_value, get_value, set_colors,
                    set_enabled, set_label=shell.set_label)


def build_combo_row(
    label: str,
    items: list[str],
    default: str = "",
    colors: MaterialColors | None = None,
    on_changed: Callable[[str], None] | None = None,
) -> FieldRow:
    """下拉选择行：左侧标签 + MD3 下拉框（自绘 chevron）"""
    c = colors or theme_controller().colors()
    shell = _RowShell(label, c, field=True)

    combo = MaterialComboBox(colors=c)
    combo.setObjectName("settingsField")
    combo.addItems(items)
    if default and default in items:
        # 缺省值不在列表时保持首项，避免无效选中态
        combo.setCurrentText(default)
    shell.add_control(combo, wide=True)

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
        shell.set_colors(new_colors)

    def set_enabled(enabled: bool) -> None:
        combo.setEnabled(enabled)

    return FieldRow(shell.container, set_value, get_value, set_colors,
                    set_enabled, set_label=shell.set_label)


def build_path_row(
    label: str,
    mode: str = FileSelector.MODE_DIRECTORY,
    colors: MaterialColors | None = None,
    on_changed: Callable[[str], None] | None = None,
) -> FieldRow:
    """路径选择行：左侧标签 + 描边字段 + 浏览按钮"""
    c = colors or theme_controller().colors()
    shell = _RowShell(label, c, field=True)
    selector = FileSelector(mode=mode, label=label, show_label=False)
    selector.set_colors(c)
    # 字段 + 按钮整体占满统一控件列（420dp，避免路径被过早截断）
    shell.add_control(selector, expanding=True)

    if on_changed:
        selector.path_changed.connect(on_changed)

    def set_value(val: Any, block_signal: bool = True) -> None:
        # 信号由内部 _edit.textChanged 触发，对 selector 自身调用
        # blockSignals 无法阻断，必须走 FileSelector 的阻断入口
        selector.set_path(str(val) if val else "", block_signal=block_signal)

    def get_value() -> str:
        return selector.path()

    def set_colors(new_colors: MaterialColors) -> None:
        shell.set_colors(new_colors)
        selector.set_colors(new_colors)

    def set_enabled(enabled: bool) -> None:
        selector.setEnabled(enabled)

    return FieldRow(shell.container, set_value, get_value, set_colors,
                    set_enabled, set_label=shell.set_label,
                    set_filter=selector.set_filter)


def build_string_row(
    label: str,
    default: str = "",
    colors: MaterialColors | None = None,
    on_changed: Callable[[str], None] | None = None,
    desc: str = "",
) -> FieldRow:
    """字符串输入行：左侧标签 + QLineEdit"""
    c = colors or theme_controller().colors()
    shell = _RowShell(label, c, desc, field=True)

    edit = QLineEdit()
    edit.setObjectName("settingsField")
    edit.setFont(MaterialTypography().font("body_large"))
    edit.setText(default)
    # 文本超出字段宽度时默认显示开头（光标置 0），而不是随光标停在末尾
    edit.setCursorPosition(0)
    shell.add_control(edit, wide=True)

    if on_changed:
        edit.textChanged.connect(on_changed)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            edit.blockSignals(True)
        edit.setText(str(val) if val is not None else "")
        edit.setCursorPosition(0)
        if block_signal:
            edit.blockSignals(False)

    def get_value() -> str:
        return edit.text()

    def set_colors(new_colors: MaterialColors) -> None:
        shell.set_colors(new_colors)

    def set_enabled(enabled: bool) -> None:
        edit.setEnabled(enabled)

    return FieldRow(shell.container, set_value, get_value, set_colors,
                    set_enabled, set_label=shell.set_label,
                    set_desc=shell.set_desc)


_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def build_color_row(
    label: str,
    default: str = "#FFFFFF",
    colors: MaterialColors | None = None,
    on_changed: Callable[[str], None] | None = None,
) -> FieldRow:
    """颜色输入行：左侧标签 + 色块预览 + QLineEdit（#RRGGBB 校验）

    色块位于输入框左侧，实时预览当前颜色；点击色块弹出 MD3 调色盘对话框，
    选择确认后写回输入框。
    """
    c = colors or theme_controller().colors()
    shell = _RowShell(label, c, field=True)

    control = QWidget()
    control.setObjectName("transparentPane")
    row = QHBoxLayout(control)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(Space.S)

    swatch = ColorSwatchButton(default, colors=c)
    row.addWidget(swatch, 0, Qt.AlignmentFlag.AlignVCenter)

    edit = QLineEdit()
    edit.setObjectName("settingsField")
    edit.setFont(MaterialTypography().font("body_large"))
    edit.setText(default)
    edit.setPlaceholderText("#RRGGBB")
    validator = QRegularExpressionValidator(
        QRegularExpression(r"^#[0-9A-Fa-f]{0,6}$")
    )
    edit.setValidator(validator)
    row.addWidget(edit, 1)

    shell.add_control(control, wide=True)

    _is_valid = [True]

    def _check_valid(text: str) -> bool:
        return bool(_COLOR_RE.match(text))

    def _on_text_changed(text: str) -> None:
        valid = _check_valid(text)
        if valid != _is_valid[0]:
            _is_valid[0] = valid
            edit.setProperty("error", "true" if not valid else "false")
            edit.style().unpolish(edit)
            edit.style().polish(edit)
        if valid:
            swatch.set_color(text)
        if on_changed and valid:
            on_changed(text)

    edit.textChanged.connect(_on_text_changed)

    def _open_picker() -> None:
        dlg = ColorPickerDialog(
            initial=swatch.color(), colors=c, parent=control.window()
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            text = dlg.get_color()
            if not text:
                return
            edit.blockSignals(True)
            edit.setText(text)
            edit.blockSignals(False)
            _is_valid[0] = True
            edit.setProperty("error", "false")
            edit.style().unpolish(edit)
            edit.style().polish(edit)
            swatch.set_color(text)
            if on_changed:
                on_changed(text)

    swatch.clicked.connect(_open_picker)

    def set_value(val: Any, block_signal: bool = True) -> None:
        if block_signal:
            edit.blockSignals(True)
        text = str(val) if val else ""
        edit.setText(text)
        _is_valid[0] = _check_valid(text)
        edit.setProperty("error", "true" if not _is_valid[0] else "false")
        edit.style().unpolish(edit)
        edit.style().polish(edit)
        if _is_valid[0]:
            swatch.set_color(text)
        if block_signal:
            edit.blockSignals(False)

    def get_value() -> str:
        return edit.text()

    def set_colors(new_colors: MaterialColors) -> None:
        nonlocal c
        c = new_colors
        shell.set_colors(new_colors)
        swatch.set_colors(new_colors)

    def set_enabled(enabled: bool) -> None:
        edit.setEnabled(enabled)
        swatch.setEnabled(enabled)

    return FieldRow(shell.container, set_value, get_value, set_colors,
                    set_enabled, set_label=shell.set_label)


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
    """范围输入行：左侧标签 + 两个 QDoubleSpinBox（min / max）"""
    c = colors or theme_controller().colors()
    shell = _RowShell(label, c, field=True)

    control = QWidget()
    control.setObjectName("transparentPane")
    row = QHBoxLayout(control)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(Space.S)

    spin_min = QDoubleSpinBox()
    spin_min.setObjectName("settingsField")
    spin_min.setFont(MaterialTypography().font("body_large"))
    spin_min.setRange(minimum, maximum)
    spin_min.setValue(default_min)
    spin_min.setSingleStep(step)
    spin_min.setDecimals(decimals)
    row.addWidget(spin_min, 1)

    sep = QLabel("–", control)
    set_text_color(sep, c.on_surface_variant)
    row.addWidget(sep)

    spin_max = QDoubleSpinBox()
    spin_max.setObjectName("settingsField")
    spin_max.setFont(MaterialTypography().font("body_large"))
    spin_max.setRange(minimum, maximum)
    spin_max.setValue(default_max)
    spin_max.setSingleStep(step)
    spin_max.setDecimals(decimals)
    row.addWidget(spin_max, 1)

    shell.add_control(control, wide=True)

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
        shell.set_colors(new_colors)
        set_text_color(sep, new_colors.on_surface_variant)

    def set_enabled(enabled: bool) -> None:
        spin_min.setEnabled(enabled)
        spin_max.setEnabled(enabled)

    return FieldRow(shell.container, set_value, get_value, set_colors,
                    set_enabled, set_label=shell.set_label)


def build_nullable_int_row(
    label: str,
    default: int | None = None,
    minimum: int = 0,
    maximum: int = 999999,
    colors: MaterialColors | None = None,
    on_changed: Callable[[int | None], None] | None = None,
) -> FieldRow:
    """可空整数行：开关 + QSpinBox。开关关闭时值为 None"""
    c = colors or theme_controller().colors()
    shell = _RowShell(label, c, field=True)

    switch = MaterialSwitch(checked=default is not None, colors=c)

    spin = QSpinBox()
    spin.setObjectName("settingsField")
    spin.setFont(MaterialTypography().font("body_large"))
    spin.setRange(minimum, maximum)
    spin.setValue(default if default is not None else minimum)
    spin.setSingleStep(1)
    spin.setEnabled(default is not None)
    spin.setFixedWidth(100)

    # 开关 + 数值框组成 168dp 的紧凑控件组，并靠右对齐：右缘与同卡片
    # 其他字段的输入框 / 开关右缘一致，而不是紧贴标签列留下大片空白。
    # 组合宽度 = 开关控件 60（轨道 52 + 状态层安全区 4×2）+ 间距 8 +
    # 数值框 100 = 168；行最小宽度 364，仍小于双列卡片最小宽。
    group = QWidget()
    group.setObjectName("transparentPane")
    group_layout = QHBoxLayout(group)
    group_layout.setContentsMargins(0, 0, 0, 0)
    group_layout.setSpacing(Space.S)
    group_layout.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
    group_layout.addWidget(spin, 0, Qt.AlignmentFlag.AlignVCenter)
    shell.add_control(group, max_width=168, wide=True, align_end=True)
    # add_control 的通用最小宽是 160，这里组合本身需要 168，显式抬到
    # 与最大宽一致，避免父布局把它压到 160 后数值框溢出 8dp
    group.setMinimumWidth(168)

    def _emit() -> None:
        if on_changed:
            if switch.is_checked():
                on_changed(spin.value())
            else:
                on_changed(None)

    def _on_switch_toggled(checked: bool) -> None:
        spin.setEnabled(checked)
        _emit()

    switch.toggled.connect(_on_switch_toggled)
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
        shell.set_colors(new_colors)

    def set_enabled(enabled: bool) -> None:
        switch.setEnabled(enabled)
        spin.setEnabled(enabled and switch.is_checked())

    return FieldRow(shell.container, set_value, get_value, set_colors,
                    set_enabled, set_label=shell.set_label)
