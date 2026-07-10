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
from arknights_video_pipeline.gui.theme.colors import MaterialColors


_STATUS_TEXT: dict[str, str] = {
    "pending": "等待中",
    "running": "运行中",
    "success": "已完成",
    "failed": "失败",
    "skipped": "已跳过",
}

# 状态 → MaterialColors 字段名映射
_STATUS_COLOR_FIELD: dict[str, str] = {
    "pending": "outline",
    "running": "secondary",
    "success": "success",
    "failed": "error",
    "skipped": "outline",
}

# 索引徽章背景/文字 → MaterialColors 字段名映射
_INDEX_COLOR_FIELDS: dict[str, tuple[str, str]] = {
    "pending": ("primary_container", "on_primary_container"),
    "running": ("secondary", "on_secondary"),
    "success": ("success", "on_primary"),
    "failed": ("error", "on_error"),
    "skipped": ("primary_container", "on_primary_container"),
}


class StepPanel(QWidget):
    """流水线步骤面板"""

    def __init__(
        self,
        parent: QWidget | None = None,
        colors: MaterialColors | None = None,
    ) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        self._cards: dict[str, dict] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for idx, step in enumerate(STEPS, start=1):
            card = self._create_card(idx, step.key, step.label)
            layout.addWidget(card["frame"])
            self._cards[step.key] = card

        layout.addStretch()

    def set_colors(self, colors: MaterialColors) -> None:
        """切换主题时刷新所有卡片配色"""
        self._colors = colors
        for card in self._cards.values():
            frame = card["frame"]
            frame.setStyleSheet(
                f"QFrame {{ background-color: transparent; "
                f"border: 1px solid {colors.outline_variant}; "
                f"border-radius: 12px; }}"
            )
            card["elapsed"].setStyleSheet(
                f"color: {colors.outline}; border: none; "
                "background: transparent;"
            )
            current_status = card.get("_status", "pending")
            self._set_card_state(card, current_status, card["elapsed"].text())

    def _create_card(self, idx: int, name: str, label: str) -> dict:
        c = self._colors
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            f"QFrame {{ background-color: transparent; "
            f"border: 1px solid {c.outline_variant}; border-radius: 12px; }}"
        )

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        index_label = QLabel(f"{idx}")
        index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index_label.setFixedSize(28, 28)
        bg_field, text_field = _INDEX_COLOR_FIELDS["pending"]
        index_label.setStyleSheet(
            f"background-color: {getattr(c, bg_field)}; "
            f"color: {getattr(c, text_field)}; "
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
        status_color = getattr(c, _STATUS_COLOR_FIELD["pending"])
        status_label.setStyleSheet(
            f"color: {status_color}; font-weight: 500; "
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
            f"color: {c.outline}; border: none; background: transparent;"
        )
        layout.addWidget(elapsed_label)

        return {
            "frame": frame,
            "index": index_label,
            "name": name_label,
            "status": status_label,
            "elapsed": elapsed_label,
            "_status": "pending",
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
        card["_status"] = status
        c = self._colors
        card["status"].setText(_STATUS_TEXT.get(status, status))
        status_color = getattr(c, _STATUS_COLOR_FIELD.get(status, "outline"))
        card["status"].setStyleSheet(
            f"color: {status_color}; "
            "font-weight: 500; border: none; background: transparent;"
        )
        card["elapsed"].setText(elapsed)

        bg_field, text_field = _INDEX_COLOR_FIELDS.get(
            status, _INDEX_COLOR_FIELDS["pending"]
        )
        bg_color = getattr(c, bg_field)
        text_color = getattr(c, text_field)
        card["index"].setStyleSheet(
            f"background-color: {bg_color}; color: {text_color}; "
            "border-radius: 14px; font-weight: 500;"
        )
