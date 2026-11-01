"""gui.components.material_combo - 跟随主题换色的下拉框

Qt QSS 的 ``QComboBox::down-arrow`` 只能用静态图片，无法随深浅主题换色；
这里关闭原生箭头，在 ``paintEvent`` 里用 ``QPainter`` 画一个 24dp chevron，
颜色取 ``on_surface_variant``。

对外接口与 ``QComboBox`` 完全一致，可直接替换。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QComboBox, QWidget

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.spacing import Space
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["MaterialComboBox"]


class MaterialComboBox(QComboBox):
    """MD3 下拉框（自绘 chevron）"""

    def __init__(self, parent: QWidget | None = None,
                 colors: MaterialColors | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self.setFont(MaterialTypography().font("body_large"))
        self.setMinimumHeight(48)
        theme_controller().theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        color = (
            QColor(self._colors.on_surface_variant)
            if self.isEnabled()
            else QColor(self._colors.outline)
        )
        right = self.width() - Space.M
        cy = self.height() / 2.0
        path = QPainterPath()
        path.moveTo(QPointF(right - 12, cy - 3))
        path.lineTo(right - 6, cy + 3)
        path.lineTo(right, cy - 3)
        pen = QPen(color)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()
