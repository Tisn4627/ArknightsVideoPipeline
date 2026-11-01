"""gui.components.about_page - About 完整页面

结构：统一页面头（:class:`PageHeader`）+ 居中信息卡（应用图标、名称、描述）。

历史实现内联了 48px / 600 字重的大标题，与首页、设置页各写一份且都不是
MD3 type scale 的档位；现在四页共用 PageHeader，字号随窗口尺寸类别降级。
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from arknights_video_pipeline.gui.assets.app_icon import load_app_icon
from arknights_video_pipeline.gui.components.material_card import CardFrame
from arknights_video_pipeline.gui.components.page_header import PageHeader
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import MaterialColors, MaterialTypography
from arknights_video_pipeline.gui.theme.spacing import Margin, Space
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller

__all__ = ["AboutPage"]

#: 信息卡最大宽度（宽屏下保持居中的窄栏，避免文字行过长）
_CARD_MAX_WIDTH = 560


class AboutPage(QWidget):
    """关于页面：页面头 + 应用信息卡（随主题 / 语言即时刷新）"""

    def __init__(self, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self._typo = MaterialTypography()
        self._size_class = "expanded"

        self.setObjectName("aboutPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(
            Margin.EXPANDED, Margin.EXPANDED, Margin.EXPANDED, Margin.EXPANDED
        )
        self._root.setSpacing(Space.XXL)
        self._root.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._header = PageHeader(
            tr("about.title"), tr("about.subtitle"), colors=self._colors
        )
        self._root.addWidget(self._header)

        # 信息卡片居中：左右 stretch + 最大宽度
        host = QWidget()
        host.setStyleSheet("background: transparent; border: none;")
        host_layout = QHBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        host_layout.addStretch()
        self._root.addWidget(host)

        self._card = CardFrame()
        self._card.setMaximumWidth(_CARD_MAX_WIDTH)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(Space.XXXL, Space.XXXL, Space.XXXL, Space.XXXL)
        card_layout.setSpacing(Space.M)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background: transparent; border: none;")
        icon_pixmap = load_app_icon().pixmap(QSize(96, 96))
        if not icon_pixmap.isNull():
            icon_label.setPixmap(icon_pixmap)
        else:
            icon_label.setVisible(False)
        card_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._icon_label = icon_label

        title = QLabel(tr("about.app_name"))
        title.setObjectName("aboutTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(self._typo.font("headline_small"))
        card_layout.addWidget(title)
        self._title_label = title

        self._desc_labels: list[QLabel] = []
        for key in ("about.desc1", "about.desc2"):
            lbl = QLabel(tr(key))
            lbl.setObjectName("aboutDesc")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(self._typo.font("body_medium"))
            lbl.setWordWrap(True)
            card_layout.addWidget(lbl)
            self._desc_labels.append(lbl)

        host_layout.addWidget(self._card)
        host_layout.addStretch()

        self.set_colors(self._colors)
        i18n().language_changed.connect(self._retranslate)
        # 订阅主题：卡片与文字配色自动跟随
        theme_controller().theme_changed.connect(self.set_colors)

    # ── 响应式 ───────────────────────────────────────────

    def set_size_class(self, size_class: str) -> None:
        """按尺寸类别调整页边距与页面头字号"""
        if size_class == self._size_class:
            return
        self._size_class = size_class
        margin = Margin.page(size_class)
        self._root.setContentsMargins(margin, margin, margin, margin)
        self._header.set_size_class(size_class)

    # ── 主题 / 语言 ───────────────────────────────────────

    def _retranslate(self) -> None:
        self._header.set_title(tr("about.title"))
        self._header.set_subtitle(tr("about.subtitle"))
        self._title_label.setText(tr("about.app_name"))
        for lbl, key in zip(self._desc_labels, ("about.desc1", "about.desc2")):
            lbl.setText(tr(key))

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._title_label.setStyleSheet(
            f"color: {colors.on_surface}; background: transparent; border: none;"
        )
        for lbl in self._desc_labels:
            lbl.setStyleSheet(
                f"color: {colors.on_surface_variant};"
                " background: transparent; border: none;"
            )
