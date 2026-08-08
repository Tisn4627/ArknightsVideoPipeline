"""
gui.components.about_page - About 完整页面

取代原 About 对话框：作为与主页 / 设置页同级的完整页面，
由左侧导航栏的 Info 项切换进入。页面包含 Hero 大标题与
居中展示应用图标、名称与描述的信息卡片。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QVBoxLayout, QLabel, QWidget,
)

from arknights_video_pipeline.gui.assets.app_icon import load_app_icon
from arknights_video_pipeline.gui.components.material_card import CardFrame
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import (
    MaterialColors, MaterialTypography,
)


class AboutPage(QWidget):
    """关于页面：Hero 大标题 + 应用信息卡片（随主题 / 语言即时刷新）"""

    def __init__(self, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        self._typo = MaterialTypography()
        self._tr_labels: list[tuple] = []

        self.setObjectName("aboutPage")
        # 页面背景跟随全局 QSS；此处仅置透明避免覆盖 app 级背景
        self.setStyleSheet("background: transparent; border: none;")

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(32)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        root.addWidget(self._build_hero())

        # 信息卡片：应用图标 + 名称 + 描述
        self._card = CardFrame()
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background: transparent; border: none;")
        icon_pixmap = load_app_icon().pixmap(QSize(96, 96))
        if not icon_pixmap.isNull():
            icon_label.setPixmap(icon_pixmap)
        else:
            icon_label.setVisible(False)
        card_layout.addWidget(icon_label)
        self._icon_label = icon_label

        title = QLabel(tr("about.app_name"))
        title.setObjectName("aboutTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {self._colors.on_surface}; background: transparent; border: none;"
            " font-size: 22px; font-weight: 600;"
        )
        card_layout.addWidget(title)
        self._title_label = title

        self._desc_labels: list[QLabel] = []
        for key in ("about.desc1", "about.desc2"):
            lbl = QLabel(tr(key))
            lbl.setObjectName("aboutDesc")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {self._colors.on_surface_variant}; background: transparent; border: none;"
                " font-size: 14px;"
            )
            lbl.setWordWrap(True)
            card_layout.addWidget(lbl)
            self._desc_labels.append(lbl)

        root.addWidget(self._card)

        # 同步当前主题色
        self.set_colors(self._colors)
        # 语言切换时刷新文本
        i18n().language_changed.connect(self._retranslate)

    def _build_hero(self) -> QWidget:
        """Hero 区域：大标题（与主页 / 设置页一致）"""
        hero = QWidget()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 24, 0, 0)
        hero_layout.setSpacing(16)
        hero_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel(tr("about.title"))
        title.setFont(self._typo.display_large)
        title.setStyleSheet(
            "border: none; background: transparent;"
            " font-size: 48px; font-weight: 600; line-height: 1.15;"
            " letter-spacing: -1.5px;"
        )
        title.setWordWrap(True)
        hero_layout.addWidget(title)
        self._tr_labels.append((title.setText, "about.title"))

        return hero

    def _retranslate(self) -> None:
        """语言切换时刷新页面文本"""
        for setter, key in self._tr_labels:
            setter(tr(key))
        self._title_label.setText(tr("about.app_name"))
        for lbl, key in zip(self._desc_labels, ("about.desc1", "about.desc2")):
            lbl.setText(tr(key))

    def set_colors(self, colors: MaterialColors) -> None:
        """主题切换时刷新页面配色"""
        self._colors = colors
        # 卡片背景：随主题切换 surface 色
        self._card.set_surface_color(colors.surface)
        # 标题 / 描述颜色随主题切换
        self._title_label.setStyleSheet(
            f"color: {colors.on_surface}; background: transparent; border: none;"
            " font-size: 22px; font-weight: 600;"
        )
        for lbl in self._desc_labels:
            lbl.setStyleSheet(
                f"color: {colors.on_surface_variant}; background: transparent; border: none;"
                " font-size: 14px;"
            )
