"""
gui.components.about_dialog - About 对话框

采用与主页一致的 Material 风格：淡紫色背景 + 白色圆角卡片 + 主色填充按钮。
取代 ``QMessageBox.about``，避免 OK 按钮被默认 QSS 样式裁切/遮挡。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget,
)

from arknights_video_pipeline.gui.components.material_card import CardFrame
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.theme import (
    MaterialColors,
    filled_button_qss as _build_filled_button_qss,
)


class AboutDialog(QDialog):
    """关于弹窗：与主页一致的视觉风格"""

    def __init__(self, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        self.setObjectName("aboutDialog")
        self.setWindowTitle("About")
        # 自适应内容尺寸，并留出充足边距避免 OK 按钮被裁切
        self.setMinimumWidth(360)
        self.setModal(True)
        # 背景色由全局 QSS 控制；这里不调用 setStyleSheet 避免覆盖子控件样式
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = CardFrame()
        self._card = card
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 标题
        title = QLabel("ArknightsVideoPipeline")
        title.setObjectName("aboutTitle")
        title.setStyleSheet(
            f"color: {self._colors.on_surface}; background: transparent; border: none;"
            " font-size: 22px; font-weight: 600;"
        )
        card_layout.addWidget(title)

        # 描述
        desc_lines = [
            "Arknights video processing pipeline GUI",
            "Built with PyQt6 and Material Design 3",
        ]
        for line in desc_lines:
            lbl = QLabel(line)
            lbl.setObjectName("aboutDesc")
            lbl.setStyleSheet(
                f"color: {self._colors.on_surface_variant}; background: transparent; border: none;"
                " font-size: 14px;"
            )
            lbl.setWordWrap(True)
            card_layout.addWidget(lbl)

        # 间隔
        card_layout.addSpacing(12)

        # 按钮行（右对齐）
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addStretch()
        ok_btn = MaterialButton("OK", variant=MaterialButton.VARIANT_FILLED)
        ok_btn.setMinimumWidth(96)
        ok_btn.setMinimumHeight(40)
        ok_btn.setStyleSheet(self._ok_button_qss())
        ok_btn.clicked.connect(self.accept)
        self._ok_btn = ok_btn
        button_row.addWidget(ok_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        card_layout.addLayout(button_row)

        outer.addWidget(card)
        # 同步当前主题色
        self.set_colors(self._colors)

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        # 卡片背景：随主题切换 surface 色
        self._card.set_surface_color(colors.surface)
        # 标题 / 描述 / 按钮颜色随主题切换
        self.findChild(QLabel, "aboutTitle").setStyleSheet(
            f"color: {colors.on_surface}; background: transparent; border: none;"
            " font-size: 22px; font-weight: 600;"
        )
        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "aboutDesc":
                lbl.setStyleSheet(
                    f"color: {colors.on_surface_variant}; background: transparent; border: none;"
                    " font-size: 14px;"
                )
        if getattr(self, "_ok_btn", None) is not None:
            self._ok_btn.setStyleSheet(self._ok_button_qss())

    def _ok_button_qss(self) -> str:
        """与 MaterialButton 主色填充样式保持一致（直接内联，避免级联问题）

        委托 gui.theme.button_qss.filled_button_qss 实现（修复 M15）。
        """
        return _build_filled_button_qss(self._colors)
