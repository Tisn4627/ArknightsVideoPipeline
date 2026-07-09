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

        批量模式下由服务层 ``overall_progress`` 信号驱动，message 形如
        "Processing X/N" 或 "Completed S/N"。
        """
        self._progress.setValue(max(0, min(100, percent)))
        self._message.setText(message)

    def reset(self) -> None:
        self._progress.setValue(0)
        self._message.setText("就绪，请添加视频文件并点击「开始处理」")

    def set_finished(self, success: bool, message: str) -> None:
        self._progress.setValue(100 if success else self._progress.value())
        self._message.setText(message)

    def set_batch_finished(self, success_count: int, total: int,
                           cancelled: bool) -> None:
        """批量处理结束态：进度填满，显示成功/总数（或取消）"""
        self._progress.setValue(100)
        if cancelled:
            self._message.setText(f"已取消 — 完成 {success_count}/{total}")
        elif success_count == total:
            self._message.setText(f"全部完成 — {success_count}/{total}")
        else:
            self._message.setText(
                f"处理结束 — 成功 {success_count}/{total}（{total - success_count} 个失败）"
            )
