"""gui.components.file_selector - 文件/目录选择器

结构（MD3）：``[描边文本字段]`` + ``[tonal 图标按钮]``。

- 输入区是 :class:`MaterialTextField`（4dp 圆角、浮动标签、错误态），
  不再自带内联 QSS——历史上这里存着一份 12px 圆角的字段样式拷贝；
- 浏览动作使用 40dp tonal 图标按钮（folder_open），比 "浏览" 文字按钮
  节省约 36dp，窄卡片与长路径字段不再因按钮占宽而被截断；tooltip
  与无障碍名称仍保留 "浏览 / Browse"。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QWidget,
)

from arknights_video_pipeline.gui.components.material_icon_button import (
    MaterialIconButton,
)
from arknights_video_pipeline.gui.components.material_text_field import (
    MaterialTextField,
)
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import MaterialColors
from arknights_video_pipeline.gui.theme.spacing import Space
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller

__all__ = ["FileSelector"]


class FileSelector(QWidget):
    """文件或目录选择器（MD3 描边字段 + tonal 按钮）"""

    path_changed = pyqtSignal(str)

    MODE_OPEN_FILE = "open_file"
    MODE_SAVE_FILE = "save_file"
    MODE_DIRECTORY = "select_directory"

    def __init__(self, mode: str = MODE_OPEN_FILE, label: str = "",
                 placeholder: str = "", parent: QWidget | None = None,
                 show_label: bool = True) -> None:
        super().__init__(parent)
        self._mode = mode
        self._filter = "All files (*.*)"
        self._is_valid = True
        self._colors = theme_controller().colors()
        self._placeholder = placeholder
        self._show_label = show_label

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.S)
        # 字段与按钮垂直居中对齐（字段下方可能有 supporting text）
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setMinimumWidth(80)
        self._edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._edit.textChanged.connect(self._on_text_changed)

        self._field = MaterialTextField(
            self._edit,
            label=label if show_label else "",
            colors=self._colors,
            parent=self,
        )
        layout.addWidget(self._field, 1)

        self._browse_btn = MaterialIconButton(
            "folder_open", tr("file.browse_tooltip"),
            variant=MaterialIconButton.VARIANT_TONAL, size=40, icon_size=20,
        )
        self._browse_btn.setToolTip(tr("file.browse_tooltip"))
        self._browse_btn.setAccessibleName(tr("file.browse"))
        self._browse_btn.clicked.connect(self._on_browse)
        layout.addWidget(self._browse_btn, 0)

        # 语言切换时刷新浏览按钮 tooltip / 无障碍名称
        i18n().language_changed.connect(self._retranslate)
        # 主题订阅由内部字段与按钮各自完成，这里只同步自身缓存
        theme_controller().theme_changed.connect(self.set_colors)

    def _retranslate(self) -> None:
        """语言切换时更新浏览按钮的 tooltip 与无障碍名称"""
        self._browse_btn.setToolTip(tr("file.browse_tooltip"))
        self._browse_btn.setAccessibleName(tr("file.browse"))

    # ── 属性与配置 ─────────────────────────────────────────

    def set_filter(self, filter_str: str) -> None:
        self._filter = filter_str

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def path(self) -> str:
        return self._edit.text().strip()

    def set_path(self, path: str, block_signal: bool = False) -> None:
        """设置路径文本。

        Args:
            path: 要写入的路径。
            block_signal: True 时阻断 ``path_changed`` 发射。用于程序化
                回填（加载配置/重置默认值）场景——信号由内部
                ``_edit.textChanged`` 触发，对 FileSelector 自身调用
                ``blockSignals`` 无法阻断它，必须直接阻断子输入框。
        """
        if block_signal:
            self._edit.blockSignals(True)
        self._edit.setText(path)
        # 长路径默认显示开头（而不是被 setText 推到结尾只露出文件名尾巴）
        self._edit.setCursorPosition(0)
        # 窄窗下字段可能只露出路径开头，完整路径放进 tooltip
        self._edit.setToolTip(path)
        if block_signal:
            self._edit.blockSignals(False)
        # blockSignals 会阻断 textChanged，浮动标签需显式同步
        self._field.refresh_state()

    def set_valid(self, valid: bool) -> None:
        """设置校验状态：``valid=False`` 时字段转错误态（error 描边）"""
        self._is_valid = valid
        self._field.set_error(not valid)

    def set_label(self, text: str) -> None:
        """设置字段标签（语言切换时调用；``show_label=False`` 时为空标签）"""
        self._field.set_label(text if self._show_label else "")

    def set_placeholder(self, text: str) -> None:
        """设置输入框占位符文本（语言切换时调用）

        有浮动标签时占位符会由 ``MaterialTextField`` 自动隐藏，避免标签
        与 placeholder 叠在同一位置（空字段 + 未聚焦时曾出现文字重影）。
        """
        self._placeholder = text
        self._field.set_placeholder(text)

    def set_colors(self, colors: MaterialColors) -> None:
        """切换主题色：字段与按钮各自订阅主题，这里仅同步缓存"""
        self._colors = colors
        self._field.set_colors(colors)

    # ── 事件处理 ───────────────────────────────────────────

    def _on_text_changed(self, text: str) -> None:
        self.set_valid(True)
        self._edit.setToolTip(text.strip())
        self.path_changed.emit(text.strip())

    def _on_browse(self) -> None:
        if self._mode == self.MODE_OPEN_FILE:
            path, _ = QFileDialog.getOpenFileName(
                self, tr("file.open_title"), self.path(), self._filter
            )
        elif self._mode == self.MODE_SAVE_FILE:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("file.save_title"), self.path(), self._filter
            )
        else:
            path = QFileDialog.getExistingDirectory(
                self, tr("file.dir_title"), self.path()
            )

        if path:
            # set_path -> setText -> textChanged -> _on_text_changed -> path_changed
            # 无需再次显式发射，避免重复触发
            self.set_path(path)
