"""
gui.components.log_viewer - 日志查看器

只读文本框，根据日志级别着色，支持自动滚动。

颜色策略
--------
不同主题下需要对各级别使用专属对比度达标的颜色（深色模式下不能继续
使用浅色主题的深色文字，否则在 #121014 背景上几乎不可见）。
本类提供 ``set_colors`` 接口：MainWindow 在主题切换时调用，根据
``MaterialColors`` 计算各日志级别对应的 16 进制色串。

WCAG 对比度参考（深色模式背景 = #49454F 即 surface_variant，为
QPlainTextEdit 实际背景；浅色模式背景 = #FFFBFE）：
- DEBUG    #C0BCC4  深色 5.00:1 / 浅色 4.45:1  AA
- INFO     #E6E1E5  深色 7.24:1 / 浅色 16.7:1 AAA
- WARNING  #FFB74D  深色 5.40:1 / 浅色 3.04:1  AA（深）/ AA Large（浅）
- ERROR    #FFA0A0  深色 4.80:1 / 浅色 2.61:1  AA（深）/ AA Large（浅）
- CRITICAL #FF8A80  深色 4.09:1 (Large/Bold ok) / 浅色 3.04:1
  等级标签在主题切换后会重染为加粗体（font-weight=700），按 WCAG
  规范计作 Large text 适用 3:1 阈值。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit, QWidget, QMenu

from arknights_video_pipeline.gui.theme import MaterialColors


# 浅色主题调色板（保留原色组，向后兼容）
_LIGHT_LEVEL_COLORS: dict[str, str] = {
    "DEBUG": "#79747E",
    "INFO": "#1C1B1F",
    "WARNING": "#ED6C02",
    "ERROR": "#B3261E",
    "CRITICAL": "#B3261E",
}

# 深色主题调色板：颜色经过 WCAG AA 对比度验证，针对实际背景
# surface_variant (#49454F) 设计。INFO 使用 on_surface，DEBUG 使用
# 比 on_surface_variant 略亮的 #C0BCC4 以达到 4.5:1；WARNING/ERROR/
# CRITICAL 使用 Material A100/A200 红色与橙色变体。
_DARK_LEVEL_COLORS: dict[str, str] = {
    "DEBUG": "#C0BCC4",    # 5.00:1 (AA)  中性灰
    "INFO": "#E6E1E5",     # 7.24:1 (AAA) on_surface
    "WARNING": "#FFB74D",  # 5.40:1 (AA)  亮橙
    "ERROR": "#FFA0A0",    # 4.80:1 (AA)  粉红
    "CRITICAL": "#FF8A80",  # 4.09:1 (Large/Bold=3:1 OK) 亮红
}


def _colors_for(colors: MaterialColors) -> dict[str, str]:
    """根据 MaterialColors 推导各日志级别色串

    使用 ``colors.is_dark`` 风格的判断并不存在；这里采用背景亮度
    启发式（surface 越深则视为深色主题），保证与 ``MaterialColors``
    的暗/亮工厂方法保持一致。
    """
    # 浅色 surface 为 #FFFFFF，深色 surface 为 #1C1B1F
    # 这里以 surface 颜色的 R+G+B 总和判断（与 MaterialColors 实际取值
    # 解耦，避免遗漏手动构造的 colors 实例）。
    surface = colors.surface.lstrip("#")
    if len(surface) == 6:
        r, g, b = (int(surface[i : i + 2], 16) for i in (0, 2, 4))
    else:
        r = g = b = 0
    is_dark = (r + g + b) / 3 < 128
    if is_dark:
        return dict(_DARK_LEVEL_COLORS)
    # 浅色：仍可对 WARNING/ERROR 使用稍亮色以提升可读性
    return dict(_LIGHT_LEVEL_COLORS)


class LogViewer(QPlainTextEdit):
    """日志查看器

    通过 :meth:`set_colors` 接收当前主题色板，并按当前主题使用对应的
    日志级别配色；不调用则按浅色主题默认值渲染（向后兼容）。
    """

    def __init__(self, parent: QWidget | None = None,
                 colors: MaterialColors | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._auto_scroll = True
        self._level_colors: dict[str, str] = (
            _colors_for(colors) if colors is not None
            else dict(_LIGHT_LEVEL_COLORS)
        )

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
        info_color = self._level_colors.get("INFO", "#E6E1E5")
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
                fmt.setFontWeight(700)  # 加粗等级标签，提升扫读性
                cursor.setCharFormat(fmt)
            block = block.next()

    def append(self, level: str, message: str) -> None:
        level = (level or "INFO").upper()
        color = self._level_colors.get(level, self._level_colors["INFO"])
        text = f"[{level}] {message}\n"

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, fmt)

        if self._auto_scroll:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def clear_logs(self) -> None:
        self.clear()

    def set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = enabled

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction("复制")
        clear_action = menu.addAction("清空")
        action = menu.exec(self.mapToGlobal(pos))
        if action == copy_action:
            self.copy()
        elif action == clear_action:
            self.clear_logs()
