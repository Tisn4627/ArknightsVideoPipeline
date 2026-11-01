"""gui.components.material_progress - MD3 线性进度指示器

MD3 的线性进度是 **4dp 轨道 + 圆头指示器**，百分比文字在条外（
进度条里再压文字是 MD2 的做法，且浅色底上的白字对比度不足）。

本组件自绘，颜色可由调用方指定（运行中 ``primary``、成功 ``success``、
失败 ``error``、取消 ``warning``），并订阅主题自动换色。

保留 ``setValue`` / ``value`` 的 Qt 风格接口，便于替换现有 ``QProgressBar``。
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller

__all__ = ["MaterialProgress"]


class MaterialProgress(QWidget):
    """MD3 线性进度条（4dp，圆头，无内嵌文字）"""

    _TRACK_HEIGHT = 4

    def __init__(
        self,
        colors: MaterialColors | None = None,
        parent: QWidget | None = None,
        *,
        height: int = _TRACK_HEIGHT,
    ) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self._value = 0
        self._height = max(2, height)
        self._color: str | None = None  # None 表示使用 primary

        self.setFixedHeight(self._height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme_controller().theme_changed.connect(self.set_colors)

    # ── 取值 ─────────────────────────────────────────────

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802 - 保持 Qt 命名
        clamped = max(0, min(100, int(value)))
        if clamped == self._value:
            return
        self._value = clamped
        self.update()

    def set_value(self, value: int) -> None:
        """``setValue`` 的可读别名"""
        self.setValue(value)

    def set_color(self, color: str | None) -> None:
        """设置指示器颜色（``None`` 回到 ``primary``）"""
        self._color = color
        self.update()

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    # ── 绘制 ─────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        c = self._colors
        track = QRectF(0, 0, self.width(), self._height)
        radius = self._height / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.surface_container_highest))
        painter.drawRoundedRect(track, radius, radius)

        if self._value > 0:
            indicator = QRectF(
                0, 0, max(float(self._height), self.width() * self._value / 100.0),
                float(self._height),
            )
            painter.setBrush(QColor(self._color or c.primary))
            painter.drawRoundedRect(indicator, radius, radius)

        painter.end()
