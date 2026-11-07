"""gui.components.progress_card - 进度/结果内容块

显示状态消息 + MD3 线性进度 + 百分比文字（文字在条外）。

结构说明：本组件**不是**卡片，而是"处理状态"卡片里的内容块——
历史实现让 ``ProgressCard`` 继承 ``MaterialCard``，结果卡片里套卡片，
出现"同色叠同色 + 双重圆角"的层级错误。
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from arknights_video_pipeline.gui.components.material_progress import MaterialProgress
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import MaterialColors
from arknights_video_pipeline.gui.theme.palette import set_text_color
from arknights_video_pipeline.gui.theme.spacing import Space
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

__all__ = ["ProgressCard"]


class ProgressCard(QWidget):
    """进度内容块（消息 + 线性进度 + 百分比）"""

    def __init__(self, parent: QWidget | None = None,
                 colors: MaterialColors | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or theme_controller().colors()
        self._typography = MaterialTypography()
        # _message_key 非 None 表示当前为静态可翻译文本（语言切换可重译）；
        # 为 None 时是 service 下发的动态消息，语言切换不覆盖
        self._message_key: str | None = "progress.ready"
        self._message_kwargs: dict[str, Any] = {}

        self.setObjectName("transparentPane")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Space.M)

        self._message = QLabel(tr("progress.ready"))
        self._message.setWordWrap(True)
        self._message.setFont(self._typography.font("body_medium"))
        set_text_color(self._message, self._colors.on_surface_variant)
        root.addWidget(self._message)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Space.M)
        self._progress = MaterialProgress(colors=self._colors)
        row.addWidget(self._progress, 1)

        self._percent_label = QLabel("0%")
        self._percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._percent_label.setFont(self._typography.font("label_large"))
        set_text_color(self._percent_label, self._colors.on_surface)
        self._percent_label.setMinimumWidth(44)
        row.addWidget(self._percent_label)
        root.addLayout(row)

        i18n().language_changed.connect(self._retranslate)
        theme_controller().theme_changed.connect(self.set_colors)

    # ── 主题 ─────────────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        set_text_color(self._message, colors.on_surface_variant)
        set_text_color(self._percent_label, colors.on_surface)
        self._progress.set_colors(colors)

    # ── 文本 ─────────────────────────────────────────────

    def _retranslate(self) -> None:
        if self._message_key is not None:
            self._message.setText(tr(self._message_key, **self._message_kwargs))

    def _set_static_message(self, key: str, **kwargs: Any) -> None:
        """设置静态可翻译消息（语言切换时自动重译）"""
        self._message_key = key
        self._message_kwargs = kwargs
        self._message.setText(tr(key, **kwargs))

    # ── 进度 ─────────────────────────────────────────────

    def set_progress(self, percent: int, message: str) -> None:
        """更新进度与状态文本

        方法名刻意避免使用 ``update``：该名称会覆盖 ``QWidget.update()``
        （无参重绘接口），导致父类在刷新时被错误分发到本方法。
        """
        value = max(0, min(100, percent))
        self._progress.setValue(value)
        self._percent_label.setText(f"{value}%")
        # service 下发的动态消息：标记为非静态，语言切换时不覆盖
        self._message_key = None
        self._message_kwargs = {}
        self._message.setText(message)

    def reset(self) -> None:
        self._progress.setValue(0)
        self._percent_label.setText("0%")
        self._set_static_message("progress.reset_ready")

    def set_batch_finished(self, success_count: int, total: int,
                           cancelled: bool) -> None:
        """批量处理结束态：进度填满，显示成功/总数（或取消）"""
        self._progress.setValue(100)
        self._percent_label.setText("100%")
        if cancelled:
            self._set_static_message(
                "progress.cancelled", success=success_count, total=total
            )
        elif success_count == total:
            self._set_static_message(
                "progress.all_done", success=success_count, total=total
            )
        else:
            self._set_static_message(
                "progress.finished",
                success=success_count, total=total,
                failed=total - success_count,
            )
