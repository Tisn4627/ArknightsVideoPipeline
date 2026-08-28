"""
gui.components.progress_card - 进度/结果卡片

显示总进度百分比与当前状态消息。
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QLabel, QProgressBar, QWidget

from arknights_video_pipeline.gui.components.material_card import MaterialCard
from arknights_video_pipeline.gui.i18n import i18n, tr


class ProgressCard(MaterialCard):
    """进度卡片"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(tr("progress.title"), parent)

        # _message 可能显示静态可翻译文本（就绪/完成态）或 service 下发的
        # 动态进度消息（不翻译）。用 _message_key 标记当前是否为静态文本：
        # 非 None 时 _retranslate 可安全重译；为 None 时保留动态消息不动。
        self._message_key: str | None = "progress.ready"
        self._message_kwargs: dict[str, Any] = {}
        self._message = QLabel(tr("progress.ready"))
        self._message.setWordWrap(True)
        self.add_widget(self._message)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self.add_widget(self._progress)

        i18n().language_changed.connect(self._retranslate)

    def _retranslate(self) -> None:
        """语言切换时刷新卡片标题；若当前为静态消息则一并刷新"""
        self.set_title(tr("progress.title"))
        if self._message_key is not None:
            self._message.setText(tr(self._message_key, **self._message_kwargs))

    def _set_static_message(self, key: str, **kwargs: Any) -> None:
        """设置静态可翻译消息（语言切换时会自动重译）"""
        self._message_key = key
        self._message_kwargs = kwargs
        self._message.setText(tr(key, **kwargs))

    def set_progress(self, percent: int, message: str) -> None:
        """更新进度条数值与状态文本

        方法名刻意避免使用 ``update``：该名称会覆盖 ``QWidget.update()``
        （无参重绘接口），导致 ``MaterialCard.set_surface_color`` 在
        ProgressCard 实例上调用 ``self.update()`` 时被错误分发到本方法，
        抛 ``TypeError``。所有调用方都应使用 ``set_progress``。

        批量模式下由服务层 ``overall_progress`` 信号驱动，message 形如
        "Processing X/N" 或 "Completed S/N"（动态、不翻译）。
        """
        self._progress.setValue(max(0, min(100, percent)))
        # service 下发的动态消息：标记为非静态，语言切换时不覆盖
        self._message_key = None
        self._message_kwargs = {}
        self._message.setText(message)

    def reset(self) -> None:
        self._progress.setValue(0)
        self._set_static_message("progress.reset_ready")

    def set_batch_finished(self, success_count: int, total: int,
                           cancelled: bool) -> None:
        """批量处理结束态：进度填满，显示成功/总数（或取消）"""
        self._progress.setValue(100)
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
