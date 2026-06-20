"""
gui.theme.styles - QSS 样式生成器

根据 MaterialColors 与 MaterialTypography 生成全局 QSS 字符串。
适配 Material Design 官网风格：淡紫背景、白色卡片、深紫主按钮。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.typography import MaterialTypography


class MaterialStyle:
    """Material Design 3 样式生成器"""

    def __init__(self, colors: MaterialColors | None = None,
                 typography: MaterialTypography | None = None) -> None:
        self.colors = colors or MaterialColors.light()
        self.typography = typography or MaterialTypography()

    def generate_qss(self) -> str:
        c = self.colors
        return f"""
        QWidget {{
            background-color: {c.background};
            color: {c.on_surface};
            font-family: "{self.typography.family.split(',')[0].strip()}";
            font-size: 14px;
            outline: none;
        }}

        QMainWindow {{
            background-color: {c.background};
        }}

        QFrame {{
            background-color: {c.surface};
            border: 1px solid {c.outline_variant};
            border-radius: 16px;
        }}

        QFrame#materialCard {{
            background-color: {c.surface};
            border: none;
            border-radius: 20px;
        }}

        QGroupBox {{
            background-color: {c.surface};
            border: 1px solid {c.outline_variant};
            border-radius: 16px;
            margin-top: 12px;
            padding-top: 16px;
            padding-bottom: 16px;
            padding-left: 16px;
            padding-right: 16px;
            font-weight: 500;
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 16px;
            top: -10px;
            padding: 0 6px;
            color: {c.on_surface};
            background-color: {c.surface};
        }}

        QPushButton {{
            background-color: {c.primary};
            color: {c.on_primary};
            border: none;
            border-radius: 20px;
            padding: 10px 24px;
            font-weight: 500;
            min-height: 20px;
        }}

        QPushButton:hover {{
            background-color: {c.primary_container};
            color: {c.on_primary_container};
        }}

        QPushButton:pressed {{
            background-color: {c.on_primary_container};
            color: {c.primary_container};
        }}

        QPushButton:disabled {{
            background-color: {c.surface_variant};
            color: {c.on_surface_variant};
        }}

        QPushButton:focus {{
            border: 2px solid {c.secondary};
        }}

        QPushButton[mdOutlined="true"] {{
            background-color: transparent;
            color: {c.primary};
            border: 1px solid {c.outline};
        }}

        QPushButton[mdOutlined="true"]:hover {{
            background-color: {c.primary_container};
        }}

        QPushButton[mdText="true"] {{
            background-color: transparent;
            color: {c.primary};
        }}

        QPushButton[mdText="true"]:hover {{
            background-color: {c.primary_container};
        }}

        QLineEdit {{
            background-color: {c.surface_variant};
            color: {c.on_surface};
            border: 1px solid {c.outline_variant};
            border-radius: 12px;
            padding: 8px 12px;
            min-height: 20px;
        }}

        QLineEdit:focus {{
            border: 2px solid {c.primary};
        }}

        QLineEdit:disabled {{
            background-color: {c.surface_variant};
            color: {c.on_surface_variant};
        }}

        QComboBox {{
            background-color: {c.surface_variant};
            color: {c.on_surface};
            border: 1px solid {c.outline_variant};
            border-radius: 12px;
            padding: 8px 12px;
            min-height: 20px;
        }}

        QComboBox:focus {{
            border: 2px solid {c.primary};
        }}

        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}

        QComboBox QAbstractItemView {{
            background-color: {c.surface};
            color: {c.on_surface};
            border: 1px solid {c.outline};
            border-radius: 8px;
            selection-background-color: {c.primary_container};
            selection-color: {c.on_primary_container};
        }}

        QCheckBox {{
            spacing: 8px;
            color: {c.on_surface};
        }}

        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {c.outline};
            border-radius: 4px;
            background-color: {c.surface};
        }}

        QCheckBox::indicator:checked {{
            background-color: {c.primary};
            border-color: {c.primary};
        }}

        QProgressBar {{
            background-color: {c.surface_variant};
            color: {c.on_surface};
            border: none;
            border-radius: 8px;
            text-align: center;
            height: 16px;
        }}

        QProgressBar::chunk {{
            background-color: {c.primary};
            border-radius: 8px;
        }}

        QPlainTextEdit, QTextEdit {{
            background-color: {c.surface_variant};
            color: {c.on_surface};
            border: 1px solid {c.outline_variant};
            border-radius: 12px;
            padding: 8px;
            font-family: "Consolas";
            font-size: 12px;
        }}

        QScrollArea {{
            background-color: transparent;
            border: none;
        }}

        QScrollBar:vertical {{
            background-color: {c.surface_variant};
            width: 8px;
            border-radius: 4px;
        }}

        QScrollBar::handle:vertical {{
            background-color: {c.outline};
            border-radius: 4px;
            min-height: 24px;
        }}

        QScrollBar::handle:vertical:hover {{
            background-color: {c.primary};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
            border: none;
        }}

        QScrollBar:horizontal {{
            background-color: {c.surface_variant};
            height: 8px;
            border-radius: 4px;
        }}

        QScrollBar::handle:horizontal {{
            background-color: {c.outline};
            border-radius: 4px;
            min-width: 24px;
        }}

        QScrollBar::handle:horizontal:hover {{
            background-color: {c.primary};
        }}

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}

        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: none;
            border: none;
        }}

        /* 在深色模式下显式覆盖滚动条区域背景，避免 Qt 默认调色板
           呈现"雪花"状的纹理图案。 */
        QAbstractScrollArea {{
            background-color: {c.background};
        }}

        QSplitter::handle {{
            background-color: {c.outline_variant};
        }}

        QMenuBar {{
            background-color: {c.surface};
            color: {c.on_surface};
        }}

        QMenuBar::item:selected {{
            background-color: {c.primary_container};
            color: {c.on_primary_container};
        }}

        QMenu {{
            background-color: {c.surface};
            color: {c.on_surface};
            border: 1px solid {c.outline_variant};
            border-radius: 8px;
        }}

        QMenu::item:selected {{
            background-color: {c.primary_container};
            color: {c.on_primary_container};
        }}

        QLabel {{
            color: {c.on_surface};
            background-color: transparent;
            border: none;
        }}

        QLabel[dim="true"] {{
            color: {c.on_surface_variant};
        }}

        QToolBar {{
            background-color: {c.surface};
            border: none;
            spacing: 8px;
            padding: 8px;
        }}

        QStatusBar {{
            background-color: {c.surface_variant};
            color: {c.on_surface_variant};
        }}
        """

    def apply(self, app: QApplication) -> None:
        app.setStyleSheet(self.generate_qss())
        app.setFont(self.typography.body_medium)

    def set_dark(self, dark: bool = True) -> None:
        self.colors = MaterialColors.dark() if dark else MaterialColors.light()
