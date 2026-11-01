"""gui.components.material_text_field - MD3 描边文本字段（浮动标签）

MD3 outlined text field 的解剖结构：

- 容器高 56dp + 顶部 8dp 标签上浮区，圆角 4dp；
- 常态 1dp ``outline`` 描边；聚焦 / 错误 2dp ``primary`` / ``error``，
  **描边向内扩、几何不变**（不推动内部控件）；
- 标签静止时位于输入区中央（充当 placeholder），聚焦或有值时上浮，
  垂直中心压在描边上，描边在标签处"开缺口"；
- 下拉输入在右侧绘制 24dp chevron（QSS 的 ``down-arrow`` 无法跟随主题换色）。

与既有代码的兼容方式：``MaterialTextField.attach(widget)`` 把任意
``QLineEdit`` / ``QComboBox`` / ``QSpinBox`` 包进容器，控件本身被透明化，
因此设置页无需替换控件类型即可获得浮动标签。
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEvent, QObject, QPropertyAnimation, QRect, QRectF, Qt, pyqtProperty,
)
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QRegion,
)
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QLabel, QLineEdit, QSizePolicy,
    QVBoxLayout, QWidget,
)

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.motion import Duration, Easing, Motion
from arknights_video_pipeline.gui.theme.shape import ShapeRole
from arknights_video_pipeline.gui.theme.spacing import Space
from arknights_video_pipeline.gui.theme.state import StateLayer, blend
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["MaterialTextField"]

#: 描边顶部留白（浮动标签骑在描边上时，上半部分超出描边）
_OUTLINE_TOP = 8
#: 描边高度（MD3 outlined field 的 56dp）
_OUTLINE_HEIGHT = 56
#: 输入控件高度
_INNER_HEIGHT = 24
#: 左右内距
_H_PADDING = Space.L


class _FieldBox(QWidget):
    """字段外框：自绘描边 + 浮动标签，内部承载真实输入控件"""

    _LABEL_PADDING = 6

    def __init__(
        self, label: str, colors: MaterialColors, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._colors = colors
        self._label = label
        self._error = False
        self._focused = False
        self._hovered = False
        self._progress = 0.0  # 0=标签居中，1=标签上浮
        self._typography = MaterialTypography()
        self._rest_size = self._typography.role("body_large").size
        self._float_size = self._typography.role("label_small").size
        self._inner: QWidget | None = None

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(_OUTLINE_TOP + _OUTLINE_HEIGHT)
        # 最小宽度只保证能放下 1/3 条路径；窄窗（compact）下路径行还需要
        # 与左侧标签共享 400dp 左右的卡片宽度
        self.setMinimumWidth(120)

        self._anim = QPropertyAnimation(self, b"floatProgress", self)
        self._anim.setDuration(Duration.SHORT2)
        self._anim.setEasingCurve(Easing.emphasized_decelerate())

    # ── 动画属性 ─────────────────────────────────────────

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        if value == self._progress:
            return
        self._progress = value
        self.update()

    floatProgress = pyqtProperty(float, fget=_get_progress, fset=_set_progress)

    # ── 状态接口 ─────────────────────────────────────────

    def set_float(self, floating: bool, animate: bool = True) -> None:
        """切换标签状态（聚焦 / 有值时上浮）

        Args:
            floating: True 表示标签上浮到描边缺口
            animate: False 时直接落值（初始化回填用）
        """
        target = 1.0 if floating else 0.0
        if abs(target - self._progress) < 1e-6:
            return
        duration = Motion.duration(Duration.SHORT2) if animate else 0
        if duration <= 0 or not self.isVisible():
            self._anim.stop()
            self._set_progress(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    def set_label(self, text: str) -> None:
        self._label = text
        self.update()

    def set_error(self, error: bool) -> None:
        if error == self._error:
            return
        self._error = error
        self.update()

    def is_error(self) -> bool:
        return self._error

    def set_focused(self, focused: bool) -> None:
        if focused == self._focused:
            return
        self._focused = focused
        self.update()

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    def attach(self, widget: QWidget) -> None:
        """放入真实输入控件并透明化其背景与描边"""
        widget.setParent(self)
        # 只清掉背景 / 边框 / 内距；颜色交给全局 QSS（不要写 color: inherit，
        # Qt QSS 不支持 inherit，会解析成灰色导致深色主题下输入文字发暗）
        widget.setStyleSheet(
            "background: transparent; border: none; padding: 0px;"
            " min-height: 0px;"
        )
        widget.setFont(self._typography.font("body_large"))
        widget.installEventFilter(self)
        self._inner = widget
        self._layout_inner()

    # ── 几何 ─────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        self._layout_inner()
        super().resizeEvent(event)

    def _layout_inner(self) -> None:
        if self._inner is None:
            return
        y = _OUTLINE_TOP + (_OUTLINE_HEIGHT - _INNER_HEIGHT) // 2
        width = max(0, self.width() - 2 * _H_PADDING)
        self._inner.setGeometry(_H_PADDING, y, width, _INNER_HEIGHT)

    # ── 事件 ─────────────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() in (
            QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.EnabledChange,
        ):
            self.update()
        return super().eventFilter(obj, event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # ── 绘制 ─────────────────────────────────────────────

    def _outline_rect(self, inset: float = 0.5) -> QRectF:
        return QRectF(
            inset,
            _OUTLINE_TOP + inset,
            self.width() - 2 * inset,
            _OUTLINE_HEIGHT - 2 * inset,
        )

    def _label_font(self) -> QFont:
        """按进度在 body_large(16) 与 label_small(11) 之间插值"""
        size = round(
            self._rest_size + (self._float_size - self._rest_size) * self._progress
        )
        font = QFont()
        font.setFamilies(self._typography.family_list)
        font.setPixelSize(max(9, size))
        font.setWeight(
            QFont.Weight.Normal if self._progress < 0.5 else QFont.Weight.Medium
        )
        return font

    def _label_rect(self, metrics: QFontMetrics) -> QRect:
        """标签矩形：上浮时垂直中心压在描边上，静止时位于输入区中央"""
        width = metrics.horizontalAdvance(self._label) + self._LABEL_PADDING
        outline_top = _OUTLINE_TOP
        outline_center = _OUTLINE_TOP + _OUTLINE_HEIGHT / 2.0
        floated_top = outline_top - metrics.height() / 2.0
        rest_top = outline_center - metrics.height() / 2.0
        top = floated_top + (rest_top - floated_top) * (1.0 - self._progress)
        return QRect(_H_PADDING, int(top), int(width), metrics.height())

    def _line_and_text_color(self) -> tuple[str, str]:
        c = self._colors
        if not self.isEnabled() or (
            self._inner is not None and not self._inner.isEnabled()
        ):
            disabled = blend(
                c.surface, c.on_surface, StateLayer.DISABLED_CONTENT
            ).name()
            return disabled, disabled
        if self._error:
            return c.error, c.error
        if self._focused:
            return c.primary, c.primary
        if self._hovered:
            return c.on_surface, c.on_surface_variant
        return c.outline, c.on_surface_variant

    def _draw_chevron(self, painter: QPainter, color: QColor) -> None:
        """下拉框右侧 chevron（24dp，跟随主题换色）"""
        cx = self.width() - _H_PADDING - 12
        cy = _OUTLINE_TOP + _OUTLINE_HEIGHT / 2.0
        path = QPainterPath()
        path.moveTo(cx - 5, cy - 2.5)
        path.lineTo(cx, cy + 2.5)
        path.lineTo(cx + 5, cy - 2.5)
        pen = QPen(color)
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        line_color, text_color = self._line_and_text_color()
        focused = self._focused or self._error
        pen = QPen(QColor(line_color))
        pen.setWidthF(2.0 if focused else 1.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        rect = self._outline_rect(1.0 if focused else 0.5)

        radius = float(ShapeRole.TEXT_FIELD)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        font = self._label_font()
        metrics = QFontMetrics(font)
        label_rect = self._label_rect(metrics)

        if self._label and self._progress > 0.01:
            # 上浮：在描边上开缺口再描边，避免线穿过文字
            gap = label_rect.adjusted(-3, 0, 3, 0)
            painter.setClipRegion(
                QRegion(self.rect()).subtracted(QRegion(gap))
            )
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setClipping(False)

            painter.setFont(font)
            painter.setPen(QColor(text_color))
            painter.drawText(label_rect, int(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            ), self._label)
        else:
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

            if self._label:
                painter.setFont(font)
                painter.setPen(QColor(text_color))
                painter.drawText(
                    QRect(
                        _H_PADDING,
                        int(_OUTLINE_TOP + _OUTLINE_HEIGHT / 2.0 - metrics.height() / 2.0),
                        self.width() - 2 * _H_PADDING,
                        metrics.height(),
                    ),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    self._label,
                )

        if isinstance(self._inner, QComboBox):
            self._draw_chevron(painter, QColor(text_color))

        painter.end()


class MaterialTextField(QWidget):
    """MD3 描边文本字段容器（浮动标签 + supporting text）

    用法::

        edit = QLineEdit()
        field = MaterialTextField.attach(edit, label="背景图路径")
        layout.addWidget(field)
    """

    def __init__(
        self,
        inner: QWidget,
        *,
        label: str = "",
        supporting: str = "",
        colors: MaterialColors | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self._inner = inner
        self._support: QLabel | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Space.XS)

        self._box = _FieldBox(label, self._colors, self)
        self._box.attach(inner)
        root.addWidget(self._box)

        if supporting:
            self._support = QLabel(supporting, self)
            root.addWidget(self._support)
            self._apply_support_style()

        self._connect_signals(inner)
        inner.installEventFilter(self)
        # 初始回填（如加载配置里的路径）直接落值，避免首帧标签与文字重叠
        self._sync_float(animate=False)

        theme_controller().theme_changed.connect(self.set_colors)

    @classmethod
    def attach(
        cls,
        inner: QWidget,
        *,
        label: str = "",
        supporting: str = "",
        colors: MaterialColors | None = None,
        parent: QWidget | None = None,
    ) -> "MaterialTextField":
        """把既有输入控件包装成 MD3 字段"""
        return cls(
            inner,
            label=label,
            supporting=supporting,
            colors=colors,
            parent=parent,
        )

    # ── 对外接口 ─────────────────────────────────────────

    def inner(self) -> QWidget:
        """被包装的输入控件"""
        return self._inner

    def set_label(self, text: str) -> None:
        self._box.set_label(text)
        self._sync_float()

    def set_supporting(self, text: str, *, error: bool = False) -> None:
        """设置辅助文本（错误提示用 ``error=True`` 同时切错误态）"""
        if self._support is None:
            self._support = QLabel(self)
            self.layout().addWidget(self._support)
        self._support.setText(text)
        self._support.setVisible(bool(text))
        self._box.set_error(error)
        self._apply_support_style()

    def set_error(self, error: bool) -> None:
        """切换错误态（描边转 error 色）"""
        self._box.set_error(error)
        self._apply_support_style()

    def is_error(self) -> bool:
        return self._box.is_error()

    def is_label_floating(self) -> bool:
        """标签是否处于上浮态（供测试断言）"""
        return self._box._progress > 0.5  # noqa: SLF001 - 同类协作

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._box.set_colors(colors)
        self._apply_support_style()

    def refresh_state(self) -> None:
        """程序化改值后同步浮动标签

        ``FieldRow.set_text`` 等回填路径会 ``blockSignals(True)`` 阻断
        ``textChanged``，标签不会自动上浮，必须显式刷新。
        """
        self._sync_float(animate=False)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        # 首次显示时校正：回填的配置值可能在不可见期间写入
        self._sync_float(animate=False)

    # ── 内部 ─────────────────────────────────────────────

    def _apply_support_style(self) -> None:
        if self._support is None:
            return
        color = (
            self._colors.error
            if self._box.is_error()
            else self._colors.on_surface_variant
        )
        font = MaterialTypography().font("body_small")
        self._support.setFont(font)
        self._support.setStyleSheet(
            f"color: {color}; background: transparent; border: none;"
        )

    def _connect_signals(self, inner: QWidget) -> None:
        if isinstance(inner, QLineEdit):
            inner.textChanged.connect(self._sync_float)
        elif isinstance(inner, QComboBox):
            inner.currentTextChanged.connect(self._sync_float)
        elif isinstance(inner, QAbstractSpinBox):
            inner.valueChanged.connect(self._sync_float)

    def _has_value(self) -> bool:
        inner = self._inner
        if isinstance(inner, QLineEdit):
            return bool(inner.text())
        # 下拉与数字输入始终有值，标签常驻上浮
        return isinstance(inner, (QComboBox, QAbstractSpinBox))

    def _sync_float(self, *_args, animate: bool = True) -> None:
        focused = self._inner.hasFocus()
        self._box.set_focused(focused)
        self._box.set_float(focused or self._has_value(), animate=animate)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._sync_float()
        return super().eventFilter(obj, event)
