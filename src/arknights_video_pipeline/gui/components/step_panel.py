"""
gui.components.step_panel - 流水线步骤可视化面板

以卡片形式展示 5 个步骤的状态。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
)

from arknights_video_pipeline.core.step_defs import STEPS


_STATUS_TEXT: dict[str, str] = {
    "pending": "等待中",
    "running": "运行中",
    "success": "已完成",
    "failed": "失败",
    "skipped": "已跳过",
}

_STATUS_COLOR: dict[str, str] = {
    "pending": "#79747E",
    "running": "#6750A4",
    "success": "#2E7D32",
    "failed": "#B3261E",
    "skipped": "#79747E",
}


class StepPanel(QWidget):
    """流水线步骤面板"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: dict[str, dict] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for idx, step in enumerate(STEPS, start=1):
            card = self._create_card(idx, step.key, step.label)
            layout.addWidget(card["frame"])
            self._cards[step.key] = card

        layout.addStretch()

    def _create_card(self, idx: int, name: str, label: str) -> dict:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            f"QFrame {{ background-color: transparent; "
            f"border: 1px solid #CAC4D0; border-radius: 12px; }}"
        )

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        index_label = QLabel(f"{idx}")
        index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index_label.setFixedSize(28, 28)
        index_label.setStyleSheet(
            "background-color: #EADDFF; color: #21005D; "
            "border-radius: 14px; font-weight: 500;"
        )
        layout.addWidget(index_label)

        name_label = QLabel(label)
        name_label.setWordWrap(True)
        name_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        name_label.setStyleSheet(
            "font-weight: 500; border: none; background: transparent;"
        )
        layout.addWidget(name_label, 1)

        status_label = QLabel(_STATUS_TEXT["pending"])
        status_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        status_label.setMinimumWidth(48)
        status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_label.setStyleSheet(
            f"color: {_STATUS_COLOR['pending']}; font-weight: 500; "
            "border: none; background: transparent;"
        )
        layout.addWidget(status_label)

        elapsed_label = QLabel("-")
        elapsed_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        elapsed_label.setMinimumWidth(36)
        elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elapsed_label.setStyleSheet(
            "color: #79747E; border: none; background: transparent;"
        )
        layout.addWidget(elapsed_label)

        return {
            "frame": frame,
            "index": index_label,
            "name": name_label,
            "status": status_label,
            "elapsed": elapsed_label,
        }

    def reset_all(self) -> None:
        for card in self._cards.values():
            self._set_card_state(card, "pending", "-")

    def set_step_running(self, name: str) -> None:
        card = self._cards.get(name)
        if card:
            self._set_card_state(card, "running", "-")

    def set_step_finished(self, name: str, success: bool, elapsed: float,
                          warnings: list[str]) -> None:
        card = self._cards.get(name)
        if card:
            status = "success" if success else "failed"
            elapsed_text = f"{elapsed:.1f}s" if elapsed else "-"
            self._set_card_state(card, status, elapsed_text)

    def set_step_skipped(self, name: str) -> None:
        card = self._cards.get(name)
        if card:
            self._set_card_state(card, "skipped", "-")

    def _set_card_state(self, card: dict, status: str, elapsed: str) -> None:
        card["status"].setText(_STATUS_TEXT.get(status, status))
        card["status"].setStyleSheet(
            f"color: {_STATUS_COLOR.get(status, '#79747E')}; "
            "font-weight: 500; border: none; background: transparent;"
        )
        card["elapsed"].setText(elapsed)

        if status == "running":
            card["index"].setStyleSheet(
                "background-color: #6750A4; color: #FFFFFF; "
                "border-radius: 14px; font-weight: 500;"
            )
        elif status == "success":
            card["index"].setStyleSheet(
                "background-color: #2E7D32; color: #FFFFFF; "
                "border-radius: 14px; font-weight: 500;"
            )
        elif status == "failed":
            card["index"].setStyleSheet(
                "background-color: #B3261E; color: #FFFFFF; "
                "border-radius: 14px; font-weight: 500;"
            )
        else:
            card["index"].setStyleSheet(
                "background-color: #EADDFF; color: #21005D; "
                "border-radius: 14px; font-weight: 500;"
            )
