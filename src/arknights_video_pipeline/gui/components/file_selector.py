"""
gui.components.file_selector - 文件/目录选择器

封装 QLineEdit + 浏览按钮，支持打开文件、保存文件、选择目录三种模式。
所有子控件使用内联 QSS 确保在主页 / 设置页等不同容器上下文中
视觉完全一致（不依赖全局 QPushButton/QLineEdit 级联规则）。
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel,
    QSizePolicy,
)

from arknights_video_pipeline.gui.theme import (
    MaterialColors,
    filled_button_qss as _build_filled_button_qss,
)


class FileSelector(QWidget):
    """文件或目录选择器"""

    path_changed = pyqtSignal(str)

    MODE_OPEN_FILE = "open_file"
    MODE_SAVE_FILE = "save_file"
    MODE_DIRECTORY = "select_directory"

    def __init__(self, mode: str = MODE_OPEN_FILE, label: str = "",
                 placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._filter = "All files (*.*)"
        self._is_valid = True
        self._colors = MaterialColors.light()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if label:
            self._label = QLabel(label)
            layout.addWidget(self._label)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setMinimumWidth(80)
        self._edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._edit.setStyleSheet(self._edit_qss())
        self._edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._edit, 1)

        self._browse_btn = QPushButton("浏览")
        self._browse_btn.setToolTip("选择文件或目录")
        self._browse_btn.setStyleSheet(self._btn_qss())
        self._browse_btn.clicked.connect(self._on_browse)
        layout.addWidget(self._browse_btn)

    # ── 属性与配置 ─────────────────────────────────────────

    def set_filter(self, filter_str: str) -> None:
        self._filter = filter_str

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def path(self) -> str:
        return self._edit.text().strip()

    def set_path(self, path: str) -> None:
        self._edit.setText(path)

    def set_valid(self, valid: bool) -> None:
        """设置校验状态：valid=False 时显示 2px error 红色边框"""
        self._is_valid = valid
        self._edit.setStyleSheet(self._edit_qss(error=not valid))

    def set_colors(self, colors: MaterialColors) -> None:
        """切换主题色（浅色/深色），刷新所有子控件内联样式"""
        self._colors = colors
        self._edit.setStyleSheet(self._edit_qss(error=not self._is_valid))
        self._browse_btn.setStyleSheet(self._btn_qss())

    # ── 内联样式（确保在任意容器上下文中视觉一致） ────────

    def _edit_qss(self, error: bool = False) -> str:
        """输入框内联样式：与全局 QLineEdit QSS 完全对齐
        （surface_variant 底色、outline_variant 边框、12px 圆角），
        支持 error 态切换。"""
        c = self._colors
        border = f"2px solid {c.error}" if error else f"1px solid {c.outline_variant}"
        return (
            "QLineEdit {"
            f"  background-color: {c.surface_variant};"
            f"  color: {c.on_surface};"
            f"  border: {border};"
            f"  border-radius: 12px;"
            f"  padding: 8px 12px;"
            f"  min-height: 20px;"
            "}"
            "QLineEdit:focus {"
            f"  border: 2px solid {c.primary};"
            "}"
            "QLineEdit:disabled {"
            f"  background-color: {c.surface_variant};"
            f"  color: {c.on_surface_variant};"
            "}"
        )

    def _btn_qss(self) -> str:
        """浏览按钮内联样式：与全局 QPushButton QSS（filled 风格）
        完全一致 —— 主色填充、白色文字、20px 圆角、10px 24px 内边距。

        委托 gui.theme.button_qss.filled_button_qss 实现（修复 M15）。
        """
        return _build_filled_button_qss(self._colors)

    # ── 事件处理 ───────────────────────────────────────────

    def _on_text_changed(self, text: str) -> None:
        self.set_valid(True)
        self.path_changed.emit(text.strip())

    def _on_browse(self) -> None:
        if self._mode == self.MODE_OPEN_FILE:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择文件", self.path(), self._filter
            )
        elif self._mode == self.MODE_SAVE_FILE:
            path, _ = QFileDialog.getSaveFileName(
                self, "保存文件", self.path(), self._filter
            )
        else:
            path = QFileDialog.getExistingDirectory(
                self, "选择目录", self.path()
            )

        if path:
            # set_path -> setText -> textChanged -> _on_text_changed -> path_changed.emit
            # 无需再次显式发射，避免重复触发
            self.set_path(path)
