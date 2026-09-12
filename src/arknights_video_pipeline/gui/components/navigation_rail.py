"""
gui.components.navigation_rail - Material Design 3 Navigation Rail

左侧垂直导航栏，支持图标+标签，选中态高亮，响应式折叠为仅图标模式。
支持浅色/深色主题切换。

图标使用 MD3 24dp Material Icons (Filled)：
    Home、Settings、Tools、Info。图标资源在 gui/assets/icons/svg/，
    加载/着色由 gui.assets.icons.nav_icons 提供。
"""

from __future__ import annotations

from PyQt6.QtCore import (
    Qt, pyqtSignal, pyqtProperty, QPropertyAnimation, QEasingCurve, QRectF,
)
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame

from arknights_video_pipeline.gui.assets.icons.nav_icons import (
    has_icon, make_icon_pixmap,
)
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import MaterialColors


def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
    """在 c1(t=0) 与 c2(t=1) 之间做 RGB 线性插值"""
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * t),
        round(c1.green() + (c2.green() - c1.green()) * t),
        round(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


class NavigationRailItem(QWidget):
    """单个导航项

    选中底色采用 MD3 Navigation Rail 规范中的 **active indicator**（胶囊形
    ``secondary_container``），并以自绘 + ``QPropertyAnimation`` 实现平滑淡入
    淡出过渡：切换时旧项淡出、新项淡入，图标/文字颜色随之在
    ``on_surface_variant`` 与 ``on_secondary_container`` 间插值。底色覆盖整个
    可点击区域（item 自身尺寸即命中区域），圆角半径取高度一半形成胶囊。
    """

    clicked = pyqtSignal()

    # MD3 状态过渡时长（state layer 典型 100–200ms）
    _ANIM_DURATION_MS = 180

    def __init__(self, icon: str, label: str, selected: bool = False,
                 colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label_text = label
        self._icon_name = icon  # 资源名（home / settings / info）
        self._selected = selected
        self._compact = False
        self._hovered = False
        self._colors = colors or MaterialColors.light()
        # 选中指示器进度：0.0=未选中，1.0=选中；动画驱动该值实现平滑过渡
        self._progress = 1.0 if selected else 0.0
        # 前景色缓存：动画期间避免每帧重建图标 pixmap
        self._foreground_hex: str | None = None

        # 背景改由 paintEvent 自绘（active indicator 胶囊 + hover 状态层），
        # 需要鼠标进入/离开事件驱动 hover 层
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(56)
        # 固定宽度与 nav rail 内容宽度一致，确保图标准确居中
        # (88px rail - 12*2 边距 = 64px)
        self.setFixedWidth(64)

        # 进度动画：目标为 pyqtProperty "progress"，淡入淡出共用同一实例
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(self._ANIM_DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        # 图标 24dp（@2x DPR 下显示 48px），与 MD3 NavigationRail 规范一致
        # 使用固定 24x24 并显式居中 + qproperty-alignment，确保不同 DPI 下
        # 图标与文字共享同一条水平中心线
        self._icon_label = QLabel()
        self._icon_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._icon_label.setFixedSize(24, 24)
        self._icon_label.setStyleSheet(
            "border: none; background: transparent;"
            " qproperty-alignment: AlignHCenter;"
        )
        layout.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._label = QLabel(label)
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._label.setMaximumWidth(72)  # 限定最大宽度，挤压居中
        self._label.setStyleSheet(
            "font-size: 12px; font-weight: 500; border: none; background: transparent;"
            " qproperty-alignment: AlignHCenter;"
        )
        layout.addWidget(self._label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._update_foreground()

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._update_foreground()
        self.update()

    def set_selected(self, selected: bool, animate: bool = True) -> None:
        """切换选中态

        animate=True 时通过 QPropertyAnimation 平滑过渡（淡入/淡出）；
        初始化等场景传 False 直接跳到目标状态，避免启动时闪烁。
        """
        self._selected = selected
        target = 1.0 if selected else 0.0
        if target == self._progress:
            # 目标进度已达成（如初始未选中项被取消选中）：无需动画
            self._anim.stop()
            return
        if not animate:
            # 快速路径：初始化等场景直接落值，避免启动闪烁
            self._anim.stop()
            self._set_progress(target)
        else:
            # 从当前进度重新起步：连续快速点击时交叉过渡不跳变
            self._anim.stop()
            self._anim.setStartValue(self._progress)
            self._anim.setEndValue(target)
            self._anim.start()

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self._label.setVisible(not compact)
        # compact 模式下 item 高度更紧凑，宽度与 rail 内容宽度同步
        # (56px rail - 8*2 margins = 40px)
        if compact:
            self.setFixedHeight(48)
            self.setFixedWidth(40)
        else:
            self.setFixedHeight(56)
            self.setFixedWidth(64)
        # 尺寸变化影响胶囊圆角半径，需重绘
        self.update()

    def set_label(self, text: str) -> None:
        """更新导航项标签文本（语言切换时调用）"""
        self._label_text = text
        self._label.setText(text)

    def mousePressEvent(self, event) -> None:
        # 仅左键触发页面切换，右键/中键不响应
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # ── 选中指示器动画属性 ────────────────────────────────

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        if value == self._progress:
            return
        self._progress = value
        self._update_foreground()
        self.update()

    progress = pyqtProperty(float, fget=_get_progress, fset=_set_progress)

    def _update_foreground(self) -> None:
        """按当前进度在 on_surface_variant 与 on_secondary_container
        之间插值，刷新图标与文字颜色

        动画期间本方法以 ~60fps 被驱动，而图标 pixmap 需要 SVG 栅格化 +
        染色，开销较大；因此仅在插值结果（8bit 量化后）真正变化时才重建
        pixmap 与样式表，背景胶囊的连续淡入淡出仍逐帧重绘。
        """
        c = self._colors
        color = _mix(QColor(c.on_surface_variant),
                     QColor(c.on_secondary_container),
                     self._progress)
        hex_color = color.name()
        if hex_color == self._foreground_hex:
            return
        self._foreground_hex = hex_color
        if has_icon(self._icon_name):
            pix = make_icon_pixmap(self._icon_name, hex_color, size_px=24)
            if pix is not None:
                self._icon_label.setPixmap(pix)
        self._label.setStyleSheet(
            f"font-size: 12px; font-weight: 500; color: {hex_color}; "
            "border: none; background: transparent;"
        )

    def paintEvent(self, event) -> None:
        """自绘选中底色（MD3 active indicator 胶囊）与 hover 状态层

        底色铺满整个可点击区域（item 自身 rect），圆角半径取高度一半
        形成胶囊；选中淡入淡出由 progress 动画驱动 alpha 实现。
        """
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = rect.height() / 2.0
        c = self._colors

        # hover 状态层：未选中时悬停显示 surface_variant，
        # 随选中进度淡出，与 active indicator 交叉过渡
        if self._hovered and self._progress < 1.0:
            hover = QColor(c.surface_variant)
            hover.setAlphaF(1.0 - self._progress)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(hover)
            p.drawRoundedRect(rect, radius, radius)

        # active indicator：secondary_container，alpha 随进度淡入
        if self._progress > 0.0:
            indicator = QColor(c.secondary_container)
            indicator.setAlphaF(self._progress)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(indicator)
            p.drawRoundedRect(rect, radius, radius)
        p.end()


class NavigationRail(QFrame):
    """Material Design 3 Navigation Rail"""

    selection_changed = pyqtSignal(int)

    def __init__(self, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        self.setFixedWidth(88)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._items: list[NavigationRailItem] = []
        # -1 表示尚未选中任何项（初始 set_selected(0) 必须真正执行），
        # 同时供 set_selected 同值早退判断
        self._current_index = -1
        # 折叠状态记录，供 set_compact 同值早退判断
        self._compact = False
        # 导航项 (icon_name, 翻译 key) —— 标签文本由 _retranslate 经 tr() 设置
        self._item_specs: list[tuple[str, str]] = [
            ("home", "nav.home"),
            ("settings", "nav.settings"),
            ("tools", "nav.tools"),
            ("info", "nav.info"),
        ]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # 让 child 自身水平居中（每个 item 宽度固定为 64px = 88-12*2）
        layout.addStretch(0)

        # 四个 MD3 NavigationRail 目的地：Home / Settings / Tools / Info
        for icon_name, key in self._item_specs:
            item = NavigationRailItem(icon_name, tr(key), colors=self._colors)
            item.clicked.connect(self._make_handler(len(self._items)))
            self._items.append(item)
            layout.addWidget(item, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch()

        # 初始选中直接落值，不播放淡入动画（避免启动闪烁）
        self.set_selected(0, animate=False)
        # 语言切换时刷新所有 item 标签
        i18n().language_changed.connect(self._retranslate)

    def _retranslate(self) -> None:
        """语言切换时更新所有导航项标签"""
        for item, (_icon, key) in zip(self._items, self._item_specs):
            item.set_label(tr(key))

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        for item in self._items:
            item.set_colors(colors)

    def set_selected(self, index: int, animate: bool = True) -> None:
        if index == self._current_index:
            # 同值早退：避免重复刷新样式并重复发射 selection_changed
            return
        if 0 <= index < len(self._items):
            if self._current_index >= 0:
                self._items[self._current_index].set_selected(False, animate)
            self._current_index = index
            self._items[self._current_index].set_selected(True, animate)
            self.selection_changed.emit(index)

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            # 同值早退：避免重复设置固定尺寸与逐项刷新
            return
        self._compact = compact
        self.setFixedWidth(56 if compact else 88)
        # margins 同步收缩：compact 56 - 8*2 = 40（与 item 40px 居中匹配）
        # normal 88 - 12*2 = 64（与 item 64px 居中匹配）
        if compact:
            self.layout().setContentsMargins(8, 12, 8, 12)
        else:
            self.layout().setContentsMargins(12, 16, 12, 16)
        for item in self._items:
            item.set_compact(compact)

    def _make_handler(self, index: int):
        def handler():
            self.set_selected(index)
        return handler
