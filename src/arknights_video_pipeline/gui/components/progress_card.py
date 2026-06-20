"""
gui.components.progress_card - 进度/结果卡片

显示总进度百分比与当前状态消息。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QLabel, QProgressBar, QWidget

from arknights_video_pipeline.gui.components.material_card import MaterialCard


class ProgressCard(MaterialCard):
    """进度卡片"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("处理进度", parent)

        self._message = QLabel("就绪，请点击「开始处理」运行流水线")
        self._message.setWordWrap(True)
        self.add_widget(self._message)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self.add_widget(self._progress)

    def set_progress(self, percent: int, message: str) -> None:
        """更新进度条数值与状态文本

        方法名刻意避免使用 ``update``：该名称会覆盖 ``QWidget.update()``
        （无参重绘接口），导致 ``MaterialCard.set_surface_color`` 在
        ProgressCard 实例上调用 ``self.update()`` 时被错误分发到本方法，
        抛 ``TypeError``。所有调用方都应使用 ``set_progress``。
        """
        self._progress.setValue(max(0, min(100, percent)))
        self._message.setText(message)

    def reset(self) -> None:
        self._progress.setValue(0)
        self._message.setText("就绪，请点击「开始处理」运行流水线")

    def set_finished(self, success: bool, message: str) -> None:
        self._progress.setValue(100 if success else self._progress.value())
        self._message.setText(message)
