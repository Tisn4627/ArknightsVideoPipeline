"""
gui.components.tools.text_range_tool - Style1 左侧文本范围预览工具

功能：
- 选择 copilot JSON 生成操作文本（与视频合成逐字一致的 format_actions_lines）
- 以与 ``video_compose.create_text_clip`` 完全相同的 pictex 参数渲染文本块，
  精确测量显示范围（边界框 + 逐行真实位置，含阴影外溢）
- 以背景板图片 + 视频区域矩形为参照实时预览，所见即所得地调整字号与位置
- 一键将当前参数写入 config/video_compose/style1.json

范围确定原理（与合成渲染保持一致）：
- 文本块左上角锚定 (text_x, text_y)，宽 = 渲染图宽（最长行 + 2*padding），
  高 = 各行行高之和 + 2*padding（padding=10，与 _PANEL_PADDING 一致）
- 逐行 y 通过渲染图 alpha 通道扫描真实行顶（复用
  ``map_overlay._measure_line_top_offsets``，吸收行距取整误差）
- 阴影参与渲染尺寸（与 create_text_clip 一致），边界框含阴影外溢
"""

from __future__ import annotations

import json
import os
from typing import Any

from pictex import Canvas, Shadow
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from arknights_video_pipeline.core.actions_to_text import (
    DEFAULT_CONFIG as ACTIONS_DEFAULT_CONFIG,
)
from arknights_video_pipeline.core.actions_to_text import (
    format_actions_lines,
)
from arknights_video_pipeline.core.map_overlay import _measure_line_top_offsets
from arknights_video_pipeline.core.text_fit import fit_actions_lines, page_actions_lines
from arknights_video_pipeline.core.utils import PROJECT_ROOT, resolve_font_path
from arknights_video_pipeline.gui.components.file_selector import FileSelector
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_card import MaterialCard
from arknights_video_pipeline.gui.components.message_dialog import (
    ConfirmDialog,
    InfoDialog,
)
from arknights_video_pipeline.gui.components.settings_row_builders import (
    FieldRow,
    build_float_row,
    build_int_row,
    build_nullable_int_row,
)
from arknights_video_pipeline.gui.components.tools.base import ToolView
from arknights_video_pipeline.gui.i18n import tr
from arknights_video_pipeline.gui.theme import MaterialColors

# 与 video_compose.create_text_clip / map_overlay._PANEL_PADDING 一致的主文本内边距
_PANEL_PADDING = 10

# 未找到任何 copilot JSON 时用于预览的内置示例数据（让工具开箱即可演示排版）
_DEMO_COPILOT_DATA: dict[str, Any] = {
    "stage_name": "示例关卡",
    "opers": [
        {"name": "能天使"},
        {"name": "德克萨斯"},
    ],
    "actions": [
        {"type": "Deploy", "name": "能天使", "location": [4, 3], "direction": "Left"},
        {"type": "Deploy", "name": "德克萨斯", "location": [5, 3], "direction": "Right"},
        {"type": "Skill", "name": "能天使"},
        {"type": "Attack", "name": "德克萨斯", "location": [5, 3]},
        {"type": "Skill", "name": "德克萨斯"},
        {"type": "Retreat", "name": "能天使"},
    ],
}

# 参数行定义：(子配置字段路径, 构建函数, 标签 key)
_FIELD_SPECS: list[tuple[str, str]] = [
    ("text_overlay.font_size", "tools.style1_text_range.font_size"),
    ("text_overlay.font_scale", "tools.style1_text_range.font_scale"),
    ("text_overlay.text_x", "tools.style1_text_range.text_x"),
    ("text_overlay.text_y", "tools.style1_text_range.text_y"),
    # 文本显示范围限定（null=不限）：右侧不遮挡视频画面、下侧不遮挡 Tips 提示
    ("text_overlay.max_text_right", "tools.style1_text_range.max_text_right"),
    ("text_overlay.max_text_bottom", "tools.style1_text_range.max_text_bottom"),
    ("video_x", "tools.style1_text_range.video_x"),
    ("video_y", "tools.style1_text_range.video_y"),
    ("video_scale", "tools.style1_text_range.video_scale"),
    ("output_width", "tools.style1_text_range.output_width"),
    ("output_height", "tools.style1_text_range.output_height"),
]


class TextRangePreview(QWidget):
    """自绘预览：背景板 + 视频区域矩形 + 逐行范围 + 文本块边界框 + 真实文本位图

    坐标统一为输出画布坐标（默认 1920x1080），绘制时等比缩放到控件尺寸。
    """

    def __init__(self, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or MaterialColors.light()
        self._bg: QPixmap | None = None
        self._out_size: tuple[int, int] | None = None
        self._video_rect: QRectF | None = None
        self._text_image: QImage | None = None
        self._text_rect: QRectF | None = None
        self._line_rects: list[QRectF] | None = None
        # 范围限定边界线（画布坐标线段），由 set_bounds 注入
        self._bounds_lines: list[tuple[QPointF, QPointF]] = []
        self.setMinimumHeight(320)
        # paintEvent 始终全量绘制自身像素，声明不透明避免 Windows
        # 拖动/缩放窗口时残留旧像素（文字乱码）
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet("border: none;")

    def set_content(
        self,
        bg: QPixmap | None,
        out_size: tuple[int, int] | None,
        video_rect: QRectF | None,
        text_image: QImage | None,
        text_rect: QRectF | None,
        line_rects: list[QRectF] | None,
    ) -> None:
        self._bg = bg
        self._out_size = out_size
        self._video_rect = video_rect
        self._text_image = text_image
        self._text_rect = text_rect
        self._line_rects = line_rects
        self.update()

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self.update()

    def set_bounds(
        self,
        max_right: int | None,
        max_bottom: int | None,
        text_x: float,
        text_y: float,
        out_size: tuple[int, int],
    ) -> None:
        """设置范围限定边界线（画布坐标），未配置的方向不绘制

        右边界：从文本锚点垂直向下延伸；下边界：从文本锚点水平向右延伸，
        另一端对齐到另一方向边界或画布边缘。
        """
        out_w, out_h = out_size
        lines: list[tuple[QPointF, QPointF]] = []
        if max_right is not None:
            bottom_y = float(max_bottom) if max_bottom is not None else float(out_h)
            lines.append((
                QPointF(float(max_right), float(text_y)),
                QPointF(float(max_right), bottom_y),
            ))
        if max_bottom is not None:
            right_x = float(max_right) if max_right is not None else float(out_w)
            lines.append((
                QPointF(float(text_x), float(max_bottom)),
                QPointF(right_x, float(max_bottom)),
            ))
        self._bounds_lines = lines
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._colors

        # 预览底框（surface_variant 底色 + outline_variant 描边）
        painter.setPen(QPen(QColor(c.outline_variant), 1))
        painter.setBrush(QColor(c.surface_variant))
        painter.drawRoundedRect(self.rect(), 12, 12)

        if self._out_size is None:
            return
        out_w, out_h = self._out_size
        if out_w <= 0 or out_h <= 0:
            return

        scale = min(self.width() / out_w, self.height() / out_h)
        if scale <= 0:
            return
        painter.translate(
            (self.width() - out_w * scale) / 2,
            (self.height() - out_h * scale) / 2,
        )
        painter.scale(scale, scale)
        pen_w = 2.0 / scale

        if self._bg is not None and not self._bg.isNull():
            painter.drawPixmap(0, 0, out_w, out_h, self._bg)

        # 视频区域：虚线轮廓
        if self._video_rect is not None:
            pen = QPen(QColor(c.on_surface_variant), pen_w)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._video_rect)

        # 范围限定边界线：secondary 虚线（右边界/下边界）
        if self._bounds_lines:
            pen = QPen(QColor(c.secondary), pen_w)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for start, end in self._bounds_lines:
                painter.drawLine(start, end)

        # 逐行范围：primary_container 半透明填充
        if self._line_rects:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.primary_container))
            for rect in self._line_rects:
                painter.drawRect(rect)

        # 文本块边界框：primary 描边 + 半透明填充
        if self._text_rect is not None:
            fill = QColor(c.primary)
            fill.setAlpha(40)
            painter.setPen(QPen(QColor(c.primary), pen_w))
            painter.setBrush(fill)
            painter.drawRect(self._text_rect)

        # 真实文本位图（pictex 渲染，所见即所得，置于最上层）
        if self._text_image is not None and self._text_rect is not None:
            painter.drawImage(self._text_rect, self._text_image)


class Style1TextRangeTool(ToolView):
    """Style1 左侧文本范围预览工具"""

    tool_id = "style1_text_range"
    title_key = "tools.style1_text_range.title"
    desc_key = "tools.style1_text_range.desc"

    # 应用配置成功（写入 style1.json）后发射，供 MainWindow 同步设置页
    config_applied = pyqtSignal()

    def __init__(self, config_proxy: Any, colors: MaterialColors | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(config_proxy, colors, parent)
        c = self._colors
        self._tr_labels: list[tuple] = []
        self._tr_setters: list[tuple] = []
        self._rows: dict[str, FieldRow] = {}
        self._bg_cache: tuple | None = None  # (path, out_w, out_h, pixmap)
        # 输入防抖定时器：连续键入只合并为最后一次渲染（pictex 全量
        # 位图渲染耗时可达数百毫秒，逐字符立即渲染会阻塞界面线程）
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(300)
        self._refresh_timer.timeout.connect(self._do_refresh_preview)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(24)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── 预览卡片（置于最前，打开工具立即可见渲染结果） ──
        self._preview_card = MaterialCard(tr("tools.style1_text_range.range_title"))
        self._preview_card.set_surface_color(c.surface)
        preview_layout = self._preview_card.layout()

        self._preview = TextRangePreview(colors=c)
        preview_layout.addWidget(self._preview)

        self._legend = self._build_legend(c)
        preview_layout.addWidget(self._legend)

        self._info_label = QLabel(tr("tools.style1_text_range.range_no_input"))
        self._info_label.setWordWrap(True)
        self._info_label.setStyleSheet(
            f"color: {c.on_surface_variant}; background: transparent; border: none;"
            " font-size: 13px;"
        )
        preview_layout.addWidget(self._info_label)

        root.addWidget(self._preview_card)

        # ── 参数卡片 ──────────────────────────────────────
        self._param_card = MaterialCard(tr(self.title_key))
        self._param_card.set_surface_color(c.surface)
        card_layout = self._param_card.layout()
        card_layout.setSpacing(12)

        self._json_selector = FileSelector(
            mode=FileSelector.MODE_OPEN_FILE,
            label=tr("tools.style1_text_range.input_json"),
            placeholder=tr("tools.style1_text_range.input_json_placeholder"),
        )
        self._json_selector.set_filter(
            "JSON files (*.json);;All files (*.*)"
        )
        self._json_selector.set_colors(c)
        self._json_selector.path_changed.connect(self._refresh_preview)
        card_layout.addWidget(self._json_selector)

        self._bg_selector = FileSelector(
            mode=FileSelector.MODE_OPEN_FILE,
            label=tr("tools.style1_text_range.background"),
            placeholder=tr("tools.style1_text_range.background_placeholder"),
        )
        self._bg_selector.set_filter(
            "Image files (*.jpg *.jpeg *.png *.bmp *.webp);;All files (*.*)"
        )
        self._bg_selector.set_colors(c)
        self._bg_selector.path_changed.connect(self._refresh_preview)
        card_layout.addWidget(self._bg_selector)

        card_layout.addWidget(self._build_section_title(
            "tools.style1_text_range.fields_title"
        ))

        for field_path, label_key in _FIELD_SPECS:
            row = self._build_field_row(field_path, label_key, c)
            card_layout.addWidget(row.widget)
            self._rows[field_path] = row
            self._tr_labels.append((row.set_label, label_key))

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        self._load_btn = MaterialButton(
            tr("tools.style1_text_range.load_style1"),
            variant=MaterialButton.VARIANT_OUTLINED,
        )
        self._load_btn.clicked.connect(self._on_load_style1)
        btn_layout.addWidget(self._load_btn)
        btn_layout.addStretch()
        self._apply_btn = MaterialButton(
            tr("tools.style1_text_range.apply"),
            variant=MaterialButton.VARIANT_FILLED,
        )
        self._apply_btn.clicked.connect(self._on_apply)
        btn_layout.addWidget(self._apply_btn)
        card_layout.addLayout(btn_layout)

        root.addWidget(self._param_card)

        # 自动定位已有 copilot JSON，避免首次打开预览空白
        self._auto_locate_copilot_json()
        self._refresh_preview()

    # ── copilot JSON 自动定位 ─────────────────────────────

    def _auto_locate_copilot_json(self) -> None:
        """优先选择项目根的 input.json，其次扫描 output 下流水线
        生成的 maa_copilot_*.json / recognition_copilot_*.json（最新者）。
        均无则保持未选择，由示例数据兜底预览。
        """
        candidates = [os.path.join(PROJECT_ROOT, "input.json")]
        out_dir = os.path.join(PROJECT_ROOT, "output")
        for root, _, files in os.walk(out_dir):
            for name in files:
                if name.startswith(("maa_copilot_", "recognition_copilot_")):
                    candidates.append(os.path.join(root, name))
        existing = [p for p in candidates if os.path.isfile(p)]
        if not existing:
            return
        newest = max(existing, key=os.path.getmtime)
        self._json_selector.set_path(newest)

    # ── 界面构建辅助 ──────────────────────────────────────

    def _build_section_title(self, label_key: str) -> QLabel:
        c = self._colors
        title = QLabel(tr(label_key))
        title.setStyleSheet(
            f"color: {c.on_surface_variant}; border: none;"
            f" background: transparent; font-weight: 500; font-size: 13px;"
            f" letter-spacing: 0.5px; margin-top: 8px;"
        )
        self._tr_labels.append((title.setText, label_key))
        return title

    def _build_field_row(self, field_path: str, label_key: str,
                         c: MaterialColors) -> FieldRow:
        defaults = {
            "text_overlay.font_size": 25,
            "text_overlay.font_scale": 1.0,
            "text_overlay.text_x": 50,
            "text_overlay.text_y": 240,
            "text_overlay.max_text_right": 272,
            "text_overlay.max_text_bottom": 965,
            "video_x": 272,
            "video_y": 47,
            "video_scale": 0.85,
            "output_width": 1920,
            "output_height": 1080,
        }
        default = defaults.get(field_path, 0)
        if field_path == "video_scale":
            return build_float_row(
                tr(label_key), default=default, minimum=0.1, maximum=2.0,
                step=0.01, decimals=2, colors=c,
                on_changed=self._refresh_preview,
            )
        if field_path == "text_overlay.font_scale":
            return build_float_row(
                tr(label_key), default=default, minimum=0.1, maximum=5.0,
                step=0.1, decimals=2, colors=c,
                on_changed=self._refresh_preview,
            )
        if field_path == "text_overlay.font_size":
            return build_int_row(
                tr(label_key), default=default, minimum=8, maximum=300,
                colors=c, on_changed=self._refresh_preview,
            )
        # 范围限定边界：可空整型（开关关闭 = 该方向不限）
        if field_path == "text_overlay.max_text_right":
            return build_nullable_int_row(
                tr(label_key), default=default, minimum=0, maximum=3840,
                colors=c, on_changed=self._refresh_preview,
            )
        if field_path == "text_overlay.max_text_bottom":
            return build_nullable_int_row(
                tr(label_key), default=default, minimum=0, maximum=2160,
                colors=c, on_changed=self._refresh_preview,
            )
        if field_path in ("text_overlay.text_x", "video_x"):
            return build_int_row(
                tr(label_key), default=default, minimum=-1920, maximum=3840,
                colors=c, on_changed=self._refresh_preview,
            )
        if field_path in ("text_overlay.text_y", "video_y"):
            return build_int_row(
                tr(label_key), default=default, minimum=-1080, maximum=2160,
                colors=c, on_changed=self._refresh_preview,
            )
        if field_path == "output_width":
            return build_int_row(
                tr(label_key), default=default, minimum=480, maximum=3840,
                colors=c, on_changed=self._refresh_preview,
            )
        return build_int_row(
            tr(label_key), default=default, minimum=270, maximum=2160,
            colors=c, on_changed=self._refresh_preview,
        )

    def _build_legend(self, c: MaterialColors) -> QWidget:
        legend = QWidget()
        legend.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(legend)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        # (标签, i18n key, 颜色角色) —— 色块随主题切换，需按角色重建 HTML
        self._legend_items: list[tuple[QLabel, str, str]] = []

        for key, role in (
            ("tools.style1_text_range.preview_legend_video", "video"),
            ("tools.style1_text_range.preview_legend_text", "text"),
            ("tools.style1_text_range.preview_legend_line", "line"),
            ("tools.style1_text_range.preview_legend_bound", "bound"),
        ):
            lbl = QLabel(self._legend_html(tr(key), self._legend_color(role, c)))
            lbl.setStyleSheet(
                f"color: {c.on_surface_variant}; background: transparent; border: none;"
                " font-size: 12px;"
            )
            layout.addWidget(lbl)
            self._legend_items.append((lbl, key, role))
        layout.addStretch()
        return legend

    @staticmethod
    def _legend_color(role: str, c: MaterialColors) -> str:
        """图例色块按语义取色：video=on_surface_variant / text=primary / line=primary_container / bound=secondary"""
        if role == "text":
            return c.primary
        if role == "line":
            return c.primary_container
        if role == "bound":
            return c.secondary
        return c.on_surface_variant

    @staticmethod
    def _legend_html(text: str, color: str) -> str:
        return f'<span style="color:{color};">&#9608;</span> {text}'

    # ── 配置读写 ──────────────────────────────────────────

    def _get_style1(self, field_path: str, default: Any) -> Any:
        return self._config_proxy.get_sub("style1", field_path, default)

    def _load_values_from_config(self) -> None:
        """从 style1.json（内存态）读取全部参数行"""
        for field_path in self._rows:
            default = {
                "text_overlay.font_size": 25,
                "text_overlay.font_scale": 1.0,
                "text_overlay.text_x": 50,
                "text_overlay.text_y": 240,
                "text_overlay.max_text_right": 272,
                "text_overlay.max_text_bottom": 965,
                "video_x": 272,
                "video_y": 47,
                "video_scale": 0.85,
                "output_width": 1920,
                "output_height": 1080,
            }.get(field_path)
            value = self._get_style1(field_path, default)
            if value is not None:
                self._rows[field_path].set_value(value, block_signal=True)

    def _current_values(self) -> dict[str, Any]:
        return {path: row.get_value() for path, row in self._rows.items()}

    # ── 预览刷新 ──────────────────────────────────────────

    def _refresh_preview(self, *args) -> None:
        """输入行/文件变更后的防抖刷新入口：连续键入合并为一次渲染。

        直接渲染为 pictex 全量位图（数百毫秒级），若每敲一个字符立即
        执行会阻塞界面线程，导致输入框卡顿、预览更新明显滞后。
        """
        self._refresh_timer.start()

    def _do_refresh_preview(self) -> None:
        values = self._current_values()
        out_w = int(values["output_width"])
        out_h = int(values["output_height"])
        text_x = int(values["text_overlay.text_x"])
        text_y = int(values["text_overlay.text_y"])
        try:
            # 视频区域矩形
            video_w = out_w * float(values["video_scale"])
            video_h = out_h * float(values["video_scale"])
            video_rect = QRectF(
                float(values["video_x"]), float(values["video_y"]),
                video_w, video_h,
            )

            # 背景板（优先用户选择，回退 pipeline 配置）
            bg = self._load_background(out_w, out_h)

            text_image, text_rect, line_rects = self._build_text_overlay(
                text_x, text_y
            )
            self._preview.set_content(
                bg, (out_w, out_h), video_rect, text_image, text_rect, line_rects,
            )
            self._preview.set_bounds(
                values["text_overlay.max_text_right"],
                values["text_overlay.max_text_bottom"],
                text_x, text_y, (out_w, out_h),
            )
            self._update_info(text_rect, line_rects, video_rect, out_w, out_h)
        except Exception as exc:  # noqa: BLE001
            # 渲染/瞬时输入状态异常：显示错误信息并清空预览，不中断交互
            self._last_error = tr(
                "tools.style1_text_range.range_render_error", msg=str(exc)
            )
            self._preview.set_content(None, None, None, None, None, None)
            self._preview.set_bounds(None, None, 0, 0, (out_w, out_h))
            self._update_info(None, None, QRectF(), out_w, out_h)

    def _load_background(self, out_w: int, out_h: int) -> QPixmap | None:
        path = self._bg_selector.path().strip()
        if not path:
            path = self._config_proxy.background_image()
        if not path:
            return None
        key = (path, out_w, out_h)
        if self._bg_cache is not None and self._bg_cache[0] == key:
            return self._bg_cache[1]
        pix = QPixmap(path)
        if pix.isNull():
            return None
        pix = pix.scaled(
            out_w, out_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._bg_cache = (key, pix)
        return pix

    def _build_text_overlay(
        self, text_x: int, text_y: int,
    ) -> tuple[QImage | None, QRectF | None, list[QRectF] | None]:
        """渲染操作文本块，返回 (文本位图, 边界框, 逐行矩形)"""
        self._last_error = None
        self._last_empty = False
        self._last_demo = False
        self._last_fit = None
        json_path = self._json_selector.path().strip()
        if not json_path or not os.path.exists(json_path):
            # 未选择 JSON 时用内置示例数据，保证预览始终有内容
            data = _DEMO_COPILOT_DATA
            self._last_demo = True
        else:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                self._last_error = tr(
                    "tools.style1_text_range.range_json_error", msg=str(exc)
                )
                return None, None, None

        # actions 配置：默认值 + GUI 内存态（与 load_config 合并行为一致）
        actions_cfg = dict(ACTIONS_DEFAULT_CONFIG)
        for key in actions_cfg:
            value = self._config_proxy.get_sub("actions", key)
            if value is not None:
                actions_cfg[key] = value

        lines = format_actions_lines(data, actions_cfg)
        if not lines:
            self._last_empty = True
            return None, None, None

        font_value = self._get_style1("text_overlay.font", "SOURCEHANSANSCN-HEAVY.OTF")
        font_dir = self._get_style1("text_overlay.font_dir", "resource/font")
        try:
            font_path = resolve_font_path(
                font_value, os.path.join(PROJECT_ROOT, font_dir)
            )
        except FileNotFoundError as exc:
            self._last_error = tr(
                "tools.style1_text_range.range_font_error", msg=str(exc)
            )
            return None, None, None

        values = self._current_values()
        text_cfg = {
            "font_size": float(values["text_overlay.font_size"]),
            "font_scale": float(values["text_overlay.font_scale"]),
            "shadow_enabled": bool(self._get_style1("text_overlay.shadow_enabled", True)),
            "shadow_offset_x": int(self._get_style1("text_overlay.shadow_offset_x", 2)),
            "shadow_offset_y": int(self._get_style1("text_overlay.shadow_offset_y", 2)),
            "shadow_blur": int(self._get_style1("text_overlay.shadow_blur", 4)),
            "shadow_color": str(self._get_style1("text_overlay.shadow_color", "#000000")),
            "text_color": str(self._get_style1("text_overlay.text_color", "#FFFFFF")),
        }

        # 显示范围限定：与视频合成共用 core.text_fit（自动换行 + 末尾截断；
        # 截断后操作均带 video_time 时自动分页，随操作执行切换显示——
        # 预览展示第 1 页，其余页在合成中按 video_time 依次切换）
        max_right = values["text_overlay.max_text_right"]
        max_bottom = values["text_overlay.max_text_bottom"]
        video_times = [a.get("video_time") for a in (data.get("actions") or [])]
        page_count = 0
        if len(video_times) == len(lines) and all(
            isinstance(v, (int, float)) for v in video_times
        ):
            pages = page_actions_lines(
                lines, font_path, text_cfg, max_right, max_bottom,
                text_x, text_y, video_times, 0.0, 1e9,
                padding=_PANEL_PADDING,
            )
            if pages:
                fitted_lines = pages[0].lines
                page_count = len(pages)
                dropped = 0
        if page_count == 0:
            fitted_lines, _line_groups, dropped = fit_actions_lines(
                lines, font_path, text_cfg, max_right, max_bottom,
                text_x, text_y, padding=_PANEL_PADDING,
            )
        self._last_fit = (
            max_right, max_bottom, dropped,
            len(fitted_lines) - len(lines), page_count,
        )
        lines = fitted_lines

        image, w, h, tops = self._render_text_block(lines, font_path, text_cfg)
        text_rect = QRectF(text_x, text_y, w, h)

        line_rects: list[QRectF] = []
        if tops is not None:
            for i, top in enumerate(tops):
                top_h = (tops[i + 1] - top) if i + 1 < len(tops) else (h - top)
                line_rects.append(QRectF(text_x, text_y + top, w, top_h))
        else:
            # 等距行高回退（与 map_overlay 一致）
            measure_canvas = (
                Canvas().font_family(font_path)
                .font_size(text_cfg["font_size"] * text_cfg["font_scale"])
                .padding(_PANEL_PADDING)
            )
            single = measure_canvas.render("0").height
            line_height = single - 2 * _PANEL_PADDING
            for i in range(len(lines)):
                line_rects.append(QRectF(
                    text_x, text_y + _PANEL_PADDING + i * line_height, w, line_height
                ))
        return image, text_rect, line_rects

    @staticmethod
    def _render_text_block(
        lines: list[str], font_path: str, text_cfg: dict,
    ) -> tuple[QImage, int, int, list[int] | None]:
        """以与 create_text_clip 相同参数渲染整块文本

        Returns:
            (QImage 位图, 宽, 高, 逐行顶部 y 列表或 None)
        """
        font_size = text_cfg["font_size"] * text_cfg["font_scale"]
        canvas = (
            Canvas().font_family(font_path).font_size(font_size)
            .color(text_cfg.get("text_color", "#FFFFFF"))
        )
        if text_cfg.get("shadow_enabled", True):
            canvas = canvas.text_shadows(
                Shadow(
                    offset=(
                        text_cfg.get("shadow_offset_x", 2),
                        text_cfg.get("shadow_offset_y", 2),
                    ),
                    blur_radius=text_cfg.get("shadow_blur", 4),
                    color=text_cfg.get("shadow_color", "#000000"),
                )
            )
        canvas = canvas.background_color("#00000000").padding(_PANEL_PADDING)

        # 视觉位图：带阴影（与 create_text_clip 完全一致，边界框含阴影外溢）
        bitmap = canvas.render("\n".join(lines))
        array = bitmap.to_numpy("RGBA")
        height, width = array.shape[:2]
        image = QImage(
            array.tobytes(), width, height, width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()

        # 逐行位置：用无阴影测量画布（阴影模糊带会让相邻行连成一片，
        # alpha 扫描无法分行；map_overlay 的面板对齐同样按无阴影测量）
        measure_canvas = (
            Canvas().font_family(font_path).font_size(font_size)
            .padding(_PANEL_PADDING)
        )
        tops = _measure_line_top_offsets(lines, measure_canvas)
        return image, bitmap.width, bitmap.height, tops

    def _update_info(
        self, text_rect: QRectF | None, line_rects: list[QRectF] | None,
        video_rect: QRectF, out_w: int, out_h: int,
    ) -> None:
        c = self._colors
        if getattr(self, "_last_error", None):
            color, text = c.error, self._last_error
        elif getattr(self, "_last_empty", False):
            color, text = c.warning, tr("tools.style1_text_range.range_empty")
        elif text_rect is None or not line_rects:
            color, text = c.on_surface_variant, tr(
                "tools.style1_text_range.range_no_input"
            )
        else:
            parts = [
                tr(
                    "tools.style1_text_range.range_block",
                    x=int(text_rect.x()), y=int(text_rect.y()),
                    w=int(text_rect.width()), h=int(text_rect.height()),
                ),
                tr(
                    "tools.style1_text_range.range_lines",
                    n=len(line_rects),
                    h=int(line_rects[0].height()),
                ),
            ]
            # 重叠检测
            overlap_w = min(text_rect.right(), video_rect.right()) - max(
                text_rect.left(), video_rect.left()
            )
            overlap_h = min(text_rect.bottom(), video_rect.bottom()) - max(
                text_rect.top(), video_rect.top()
            )
            overflow_r = int(text_rect.right() - out_w)
            overflow_b = int(text_rect.bottom() - out_h)

            if overlap_w > 0 and overlap_h > 0:
                parts.append(tr(
                    "tools.style1_text_range.range_overlap",
                    w=int(overlap_w), h=int(overlap_h),
                ))
                color = c.error
            elif overflow_r > 0 or overflow_b > 0:
                parts.append(tr(
                    "tools.style1_text_range.range_overflow",
                    r=max(overflow_r, 0), b=max(overflow_b, 0),
                ))
                color = c.warning
            else:
                parts.append(tr("tools.style1_text_range.range_ok"))
                color = c.success
            # 范围限定拟合统计（自动换行 / 末尾截断 / 分页切换 / 未启用）
            max_right, max_bottom, dropped, wrapped_extra, page_count = getattr(
                self, "_last_fit", (None, None, 0, 0, 0)
            )
            if max_right is None and max_bottom is None:
                parts.append(tr("tools.style1_text_range.range_unbounded"))
            else:
                if page_count > 1:
                    parts.append(tr(
                        "tools.style1_text_range.range_paged", n=page_count
                    ))
                if wrapped_extra > 0:
                    parts.append(tr(
                        "tools.style1_text_range.range_wrapped", n=wrapped_extra
                    ))
                if dropped > 0:
                    parts.append(tr(
                        "tools.style1_text_range.range_truncated", n=dropped
                    ))
                    color = c.warning
            if getattr(self, "_last_demo", False):
                parts.insert(0, tr("tools.style1_text_range.demo_notice"))
                color = c.warning
            text = "\n".join(parts)
        self._info_label.setStyleSheet(
            f"color: {color}; background: transparent; border: none;"
            " font-size: 13px;"
        )
        self._info_label.setText(text)

    # ── 按钮处理 ──────────────────────────────────────────

    def _on_load_style1(self) -> None:
        self._load_values_from_config()
        self._refresh_preview()

    def _on_apply(self) -> None:
        dlg = ConfirmDialog(
            tr("tools.style1_text_range.apply_confirm_title"),
            tr("tools.style1_text_range.apply_confirm_text"),
            confirm_text=tr("dialog.confirm"),
            cancel_text=tr("dialog.cancel"),
            colors=self._colors, parent=self.window(),
        )
        if dlg.exec() != ConfirmDialog.CONFIRMED:
            return
        values = self._current_values()
        for field_path, value in values.items():
            self._config_proxy.set_sub("style1", field_path, value)
        self._config_proxy.save_all()
        self.config_applied.emit()
        dlg2 = InfoDialog(
            tr("tools.style1_text_range.apply_ok_title"),
            tr("tools.style1_text_range.apply_ok_text"),
            colors=self._colors, parent=self.window(),
        )
        dlg2.exec()

    # ── ToolView 接口 ─────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        super().set_colors(colors)
        c = colors
        self._param_card.set_surface_color(c.surface)
        self._preview_card.set_surface_color(c.surface)
        self._json_selector.set_colors(c)
        self._bg_selector.set_colors(c)
        self._preview.set_colors(c)
        for row in self._rows.values():
            row.set_colors(c)
        self._refresh_legend()
        self._refresh_preview()

    def retranslate(self) -> None:
        self._param_card.set_title(tr(self.title_key))
        self._preview_card.set_title(
            tr("tools.style1_text_range.range_title")
        )
        self._json_selector.set_label(tr("tools.style1_text_range.input_json"))
        self._json_selector.set_placeholder(
            tr("tools.style1_text_range.input_json_placeholder")
        )
        self._bg_selector.set_label(tr("tools.style1_text_range.background"))
        self._bg_selector.set_placeholder(
            tr("tools.style1_text_range.background_placeholder")
        )
        self._load_btn.setText(tr("tools.style1_text_range.load_style1"))
        self._apply_btn.setText(tr("tools.style1_text_range.apply"))
        for setter, key in self._tr_labels:
            setter(tr(key))
        self._refresh_legend()
        self._refresh_preview()

    def _refresh_legend(self) -> None:
        """主题/语言切换时重建图例（色块颜色与文字均需刷新）"""
        c = self._colors
        for lbl, key, role in self._legend_items:
            lbl.setText(self._legend_html(tr(key), self._legend_color(role, c)))

    def on_entered(self) -> None:
        self._load_values_from_config()
        self._refresh_preview()