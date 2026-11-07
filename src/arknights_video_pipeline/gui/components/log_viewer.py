"""
gui.components.log_viewer - 日志查看器

只读文本框，根据日志级别着色，支持自动滚动。
本类提供 ``set_colors`` 接口：主题切换时由 ``theme_changed`` 自动调用。

颜色策略
--------
级别色**全部来自 ``MaterialColors`` 角色**，组件内不再维护十六进制常量
（历史实现把两套主题的日志色写死在组件里，调色板改动会漏掉它）：

- ``DEBUG``   → ``on_surface_variant``
- ``INFO``    → ``on_surface``
- ``WARNING`` → ``warning``（扩展语义角色，与主色同源）
- ``ERROR``   / ``CRITICAL`` → ``error``（标签加粗，按 Large text 计对比度）

浅色取 tone 40 附近的深色、深色取 tone 80 的亮色，对比度由角色本身保证。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QMenu, QPlainTextEdit, QWidget

from arknights_video_pipeline.gui.i18n import tr
from arknights_video_pipeline.gui.theme import MaterialColors
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

#: 未传入 colors 时的兜底色（正常路径都会由 MaterialColors 覆盖）
_FALLBACK_LEVEL_COLORS: dict[str, str] = {
    "DEBUG": "#49454F",
    "INFO": "#1D1B20",
    "WARNING": "#7D5700",
    "ERROR": "#B3261E",
    "CRITICAL": "#B3261E",
}


def _colors_for(colors: MaterialColors) -> dict[str, str]:
    """由颜色角色推导各日志级别色串

    级别色全部来自 ``MaterialColors``：
    ``DEBUG → on_surface_variant``、``INFO → on_surface``、
    ``WARNING → warning``、``ERROR/CRITICAL → error``。
    浅色取 tone 40 附近的深色、深色取 tone 80 的亮色，对比度由角色本身
    保证，组件内不再维护两套十六进制常量。
    """
    return {
        "DEBUG": colors.on_surface_variant,
        "INFO": colors.on_surface,
        "WARNING": colors.warning,
        "ERROR": colors.error,
        "CRITICAL": colors.error,
    }


class LogViewer(QPlainTextEdit):
    """日志查看器

    通过 :meth:`set_colors` 接收当前主题色板，并按当前主题使用对应的
    日志级别配色；不调用则按浅色主题默认值渲染（向后兼容）。

    内容上限：通过 ``setMaximumBlockCount(2000)`` 限制最多保留 2000 行，
    超出后自动丢弃最旧的日志，防止长时间批量运行时内存无限增长。
    """

    # 日志最大保留行数（QTextBlock 数），防止无限增长
    MAX_BLOCKS = 2000

    def __init__(self, parent: QWidget | None = None,
                 colors: MaterialColors | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # 等宽字体走统一工厂（12px，行高紧凑，便于扫读日志）
        self.setFont(MaterialTypography().mono)
        self.setPlaceholderText(tr("home.logs_empty"))
        self.document().setDocumentMargin(4)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        # 限制日志最大行数（超出自动丢弃最旧内容）
        self.setMaximumBlockCount(self.MAX_BLOCKS)
        self._level_colors: dict[str, str] = (
            _colors_for(colors) if colors is not None
            else dict(_FALLBACK_LEVEL_COLORS)
        )
        # 订阅主题：日志级别配色自动跟随，无需调用方手工刷新
        theme_controller().theme_changed.connect(self.set_colors)

    def set_colors(self, colors: MaterialColors) -> None:
        """主题切换时刷新各级别颜色，并按行重染已存在的日志文本。

        实现细节：``QPlainTextEdit`` 的 ``QTextCharFormat`` 是按字符
        存储的，无法在不重写文本的情况下整体换色。本方法先把已有
        内容按 ``\\n`` 切分，识别每行首部的 ``[LEVEL]`` 前缀，对齐
        长度后批量覆盖：先把整段设为新 INFO 颜色（兜底），再对
        ``[LEVEL]`` 前缀单独设色——如此一次刷新即可，无需清空用户
        日志内容。
        """
        self._level_colors = _colors_for(colors)
        self._recolor_existing()

    def _recolor_existing(self) -> None:
        """按行重染已存在的日志文本（不丢失内容）"""
        doc = self.document()
        block = doc.begin()
        info_color = self._level_colors.get("INFO", _FALLBACK_LEVEL_COLORS["INFO"])
        while block.isValid():
            text = block.text()
            if not text:
                block = block.next()
                continue
            # 解析行首 [LEVEL]
            level_key = "INFO"
            if text.startswith("[") and "]" in text:
                tag = text[1:text.index("]")]
                if tag in self._level_colors:
                    level_key = tag
            tag_color = self._level_colors.get(
                level_key, info_color
            )
            # 先把整行染成 INFO 颜色（兜底）
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(info_color))
            cursor.setCharFormat(fmt)
            # 再把 [LEVEL] 前缀单独染色
            tag_end = text.find("]")
            if text.startswith("[") and tag_end > 0:
                cursor = QTextCursor(block)
                cursor.setPosition(block.position())
                cursor.setPosition(
                    block.position() + tag_end + 1,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(tag_color))
                # MD3 只使用 400 / 500 字重；500 已足以让等级标签从正文中区分
                fmt.setFontWeight(500)
                cursor.setCharFormat(fmt)
            block = block.next()

    def append(self, level: str, message: str) -> None:
        level = (level or "INFO").upper()
        color = self._level_colors.get(level, self._level_colors["INFO"])
        text = f"[{level}] {message}\n"

        # 先记录追加前滚动条是否位于底部，再追加文本；追加后仅当原本
        # 处于底部时才自动滚动，避免打断用户向上翻阅历史日志。
        sb = self.verticalScrollBar()
        was_at_bottom = sb.value() >= sb.maximum() - 4

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, fmt)

        if was_at_bottom:
            sb.setValue(sb.maximum())

    def clear_logs(self) -> None:
        self.clear()

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        # exec 后立即销毁：父控件存活期间反复右键会累积子 QMenu 对象
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        copy_action = menu.addAction(tr("log_viewer.copy"))
        clear_action = menu.addAction(tr("log_viewer.clear"))
        action = menu.exec(self.mapToGlobal(pos))
        if action == copy_action:
            self.copy()
        elif action == clear_action:
            self.clear_logs()
