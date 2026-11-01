"""gui.components.page_header - 统一页面头

四个页面共用同一个页面头：标题 + 可选副标题 + 可选尾部操作。

字号按窗口尺寸类别选择 MD3 type scale 档位（历史上四页各自内联
``48px / 600``，既不在 type scale 上，也让 720 宽窗口的首屏被标题占满）：

| 尺寸类别 | 标题角色 | 字号 |
|---|---|---|
| expanded | ``headline_large`` | 32 / 400 |
| medium | ``headline_medium`` | 28 / 400 |
| compact | ``headline_small`` | 24 / 400 |

副标题固定 ``body_medium``（14 / 400，``on_surface_variant``）。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.palette import set_text_color
from arknights_video_pipeline.gui.theme.spacing import Space
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography
from arknights_video_pipeline.gui.theme.window_size import WindowSizeClass

__all__ = ["PageHeader"]

_TITLE_ROLE_BY_SIZE: dict[str, str] = {
    WindowSizeClass.EXPANDED: "headline_large",
    WindowSizeClass.MEDIUM: "headline_medium",
    WindowSizeClass.COMPACT: "headline_small",
}


class PageHeader(QWidget):
    """页面头：标题 + 副标题，字号随窗口尺寸类别降级"""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        *,
        colors: MaterialColors | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self._typography = MaterialTypography()
        self._size_class = WindowSizeClass.EXPANDED

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent; border: none;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.L)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(Space.XS)

        self._title = QLabel(title, self)
        self._title.setWordWrap(True)
        self._title.setFont(self._title_font())
        text_col.addWidget(self._title)

        self._subtitle = QLabel(subtitle, self)
        self._subtitle.setWordWrap(True)
        self._subtitle.setFont(self._typography.font("body_medium"))
        text_col.addWidget(self._subtitle)
        self._subtitle.setVisible(bool(subtitle))

        layout.addLayout(text_col, 1)
        self._trailing_row = QHBoxLayout()
        self._trailing_row.setContentsMargins(0, 0, 0, 0)
        self._trailing_row.setSpacing(Space.S)
        layout.addLayout(self._trailing_row, 0)

        self._apply_colors()
        theme_controller().theme_changed.connect(self.set_colors)

    # ── 接口 ─────────────────────────────────────────────

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def title(self) -> str:
        return self._title.text()

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))

    def set_size_class(self, size_class: str) -> None:
        """按尺寸类别切换标题字号（compact / medium / expanded）"""
        if size_class == self._size_class:
            return
        self._size_class = size_class
        self._title.setFont(self._title_font())

    def add_trailing(self, widget: QWidget) -> None:
        """在标题右侧追加操作控件（如主按钮 / 图标按钮）"""
        self._trailing_row.addWidget(widget)

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._apply_colors()

    # ── 内部 ─────────────────────────────────────────────

    def _title_font(self):
        role = _TITLE_ROLE_BY_SIZE.get(self._size_class, "headline_large")
        return self._typography.font(role)

    def _apply_colors(self) -> None:
        # 标题/副标题文字色走 QPalette，避免主题切换时逐控件重设样式表
        set_text_color(self._title, self._colors.on_surface)
        set_text_color(self._subtitle, self._colors.on_surface_variant)
