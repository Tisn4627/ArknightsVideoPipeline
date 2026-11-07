"""gui.components.batch_video_list - 批量视频文件列表组件

展示待处理视频文件队列，支持多选添加、拖放添加、上移/下移调整顺序、
删除条目，以及每个文件的独立进度与状态跟踪。

视觉规格（MD3 two-line list item）：

- 行高 80dp、圆角 8dp、悬停 8% 墨层（``on_surface`` 叠在卡片表面）；
- 第一行：序号 chip（28dp ``primary_container``）+ 状态图标 + 文件名 +
  右对齐状态文字；
- 第二行：4dp ``MaterialProgress``（与文件名左对齐）+ 条外百分比 +
  40dp icon button（JSON / 上移 / 下移 / 删除）。

主页队列卡在双列布局中只有约 330dp 宽，单行排布会把进度与操作按钮挤出
可视区，因此采用 MD3 标准的 two-line 列表项。主页不显示卡片内的"添加
视频"按钮（主操作是右下角 FAB），工具页（``show_json_button=False``
场景）仍保留按钮。
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from arknights_video_pipeline.core.utils import SUPPORTED_VIDEO_EXTENSIONS
from arknights_video_pipeline.gui.assets.icons.nav_icons import (
    has_icon,
    make_icon_pixmap,
)
from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_icon_button import (
    MaterialIconButton,
)
from arknights_video_pipeline.gui.components.material_progress import MaterialProgress
from arknights_video_pipeline.gui.i18n import i18n, tr
from arknights_video_pipeline.gui.theme import MaterialColors
from arknights_video_pipeline.gui.theme.spacing import Space
from arknights_video_pipeline.gui.theme.state import StateLayer, with_alpha
from arknights_video_pipeline.gui.theme.theme_controller import theme_controller
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

# 状态枚举（字符串，便于直接作为样式 key）
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# 状态码 → 翻译 key
_STATUS_KEYS: dict[str, str] = {
    STATUS_PENDING: "batch.status.pending",
    STATUS_RUNNING: "batch.status.running",
    STATUS_SUCCESS: "batch.status.success",
    STATUS_FAILED: "batch.status.failed",
    STATUS_CANCELLED: "batch.status.cancelled",
}


def _status_text(status: str) -> str:
    """状态码 → 当前语言的显示文本（缺失时回退到状态码本身）"""
    return tr(_STATUS_KEYS.get(status, ""), default=status)


class _ElidedLabel(QLabel):
    """按自身宽度省略中间文本的标签（长文件名不撑破窄卡片）

    不用 ``setText`` 写省略结果（那会改变 sizeHint 并触发父布局重排，
    在窄卡片里形成 "resize → setText → 重排 → resize" 的递归）。这里保持
    完整文本不变，只在 ``paintEvent`` 里按当前宽度绘制省略形式，并让水平
    size policy 为 ``Ignored``，使标签的最小宽度不随文件名长度增长。
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setText(text)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(self.palette().color(self.foregroundRole()))
        fm = self.fontMetrics()
        text = fm.elidedText(
            self._full_text, Qt.TextElideMode.ElideMiddle, self.width()
        )
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        painter.end()


class BatchVideoRow(QWidget):
    """单个视频文件条目（MD3 two-line 80dp 列表行）"""

    ROW_HEIGHT = 80

    def __init__(self, video_path: str, colors: MaterialColors,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = video_path
        self._colors = colors
        self._status = STATUS_PENDING
        self._percent = 0
        self._json_path: str | None = None
        self._hover = 0.0
        self._typo = MaterialTypography()

        self.setFixedHeight(self.ROW_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        # 4dp 栅格：上下 4、两行间距 4，28 + 4 + 40 + 8 = 80dp
        layout.setContentsMargins(Space.M, Space.XS, Space.S, Space.XS)
        layout.setSpacing(Space.XS)

        # ── 第一行：序号 / 状态图标 / 文件名 / 状态文字 ──
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(Space.S)

        # 序号 chip：28×28 primary_container
        self._index_label = QLabel("1", self)
        self._index_label.setFixedSize(28, 28)
        self._index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._index_label.setFont(self._typo.font("label_medium"))
        top.addWidget(self._index_label)

        # 状态图标
        self._status_icon = QLabel(self)
        self._status_icon.setFixedSize(20, 20)
        self._status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_icon.setStyleSheet("background: transparent; border: none;")
        top.addWidget(self._status_icon)

        # 文件名（中间省略，完整路径放 tooltip）
        self._name_label = _ElidedLabel(os.path.basename(video_path), self)
        self._name_label.setToolTip(video_path)
        # MD3 列表项主文本使用 body_large（16/400）
        self._name_label.setFont(self._typo.font("body_large"))
        top.addWidget(self._name_label, 1)

        # 状态文本（右对齐，固定列宽保证各行一致）
        self._status_label = QLabel(_status_text(STATUS_PENDING), self)
        self._status_label.setFixedWidth(64)
        self._status_label.setFont(self._typo.font("label_medium"))
        self._status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        top.addWidget(self._status_label)
        layout.addLayout(top)

        # ── 第二行：进度 / 百分比 / 操作按钮 ──
        # 左缩进 = 序号 chip 28 + 间距 8 + 状态图标槽 20 + 间距 8，
        # 使进度条起点与第一行文件名左缘对齐（MD3 two-line list item）
        bottom = QHBoxLayout()
        bottom.setContentsMargins(28 + Space.S + 20 + Space.S, 0, 0, 0)
        bottom.setSpacing(Space.XS)

        self._progress = MaterialProgress(colors, self)
        bottom.addWidget(self._progress, 1, Qt.AlignmentFlag.AlignVCenter)

        self._percent_label = QLabel("0%", self)
        self._percent_label.setFixedWidth(34)
        self._percent_label.setFont(self._typo.font("label_medium"))
        self._percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        bottom.addWidget(self._percent_label)

        # 自定义作业JSON / 上移 / 下移 / 删除（40dp 标准 icon button）
        self._json_btn = self._make_icon_btn("note_add", tr("batch.tooltip.json.add"))
        self._up_btn = self._make_icon_btn("arrow_upward", tr("batch.tooltip.up"))
        self._down_btn = self._make_icon_btn("arrow_downward", tr("batch.tooltip.down"))
        self._del_btn = self._make_icon_btn("delete", tr("batch.tooltip.delete"))
        bottom.addWidget(self._json_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self._up_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self._down_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self._del_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(bottom)

        self._apply_styles()
        self.setMouseTracking(True)
        theme_controller().theme_changed.connect(self.set_colors)

    # ── 公开 API ──────────────────────────────────────────

    @property
    def video_path(self) -> str:
        return self._path

    def set_index(self, index: int) -> None:
        self._index_label.setText(str(index))

    def set_editable(self, editable: bool) -> None:
        self._up_btn.setEnabled(editable)
        self._down_btn.setEnabled(editable)
        self._del_btn.setEnabled(editable)
        self._json_btn.setEnabled(editable)

    def set_json_button_visible(self, visible: bool) -> None:
        """隐藏/显示 JSON 绑定按钮（识别工具自身生成 JSON，无需该按钮）"""
        self._json_btn.setVisible(visible)

    def set_status(self, status: str, percent: int | None = None) -> None:
        self._status = status
        if percent is not None:
            self._percent = max(0, min(100, percent))
        self._progress.setValue(self._percent)
        self._progress.set_color(self._progress_color())
        self._percent_label.setText(f"{self._percent}%")
        self._status_label.setText(_status_text(status))
        self._status_label.setStyleSheet(self._status_text_qss())
        self._refresh_status_icon()

    def set_progress(self, percent: int) -> None:
        self._percent = max(0, min(100, percent))
        self._progress.setValue(self._percent)
        self._percent_label.setText(f"{self._percent}%")

    def reset_state(self) -> None:
        self._status = STATUS_PENDING
        self._percent = 0
        self._progress.setValue(0)
        self._progress.set_color(self._progress_color())
        self._percent_label.setText("0%")
        self._status_label.setText(_status_text(STATUS_PENDING))
        self._status_label.setStyleSheet(self._status_text_qss())
        self._refresh_status_icon()

    def refresh_translations(self) -> None:
        """语言切换时刷新状态文本与按钮 tooltip"""
        self._status_label.setText(_status_text(self._status))
        self._refresh_json_btn()
        self._up_btn.setToolTip(tr("batch.tooltip.up"))
        self._down_btn.setToolTip(tr("batch.tooltip.down"))
        self._del_btn.setToolTip(tr("batch.tooltip.delete"))

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._apply_styles()
        self._progress.set_colors(colors)
        self._progress.set_color(self._progress_color())
        # 图标按钮自绘且自订阅主题，这里只需恢复绑定态图标
        self._refresh_json_btn()
        self._refresh_status_icon()

    # ── 状态辅助 ──────────────────────────────────────────

    def _progress_color(self) -> str:
        """按状态取进度指示器颜色"""
        return {
            STATUS_RUNNING: self._colors.primary,
            STATUS_SUCCESS: self._colors.success,
            STATUS_FAILED: self._colors.error,
            STATUS_CANCELLED: self._colors.warning,
        }.get(self._status, self._colors.primary)

    # ── 信号入口（由 BatchVideoList 连接） ────────────────

    def up_button(self) -> MaterialIconButton:
        return self._up_btn

    def down_button(self) -> MaterialIconButton:
        return self._down_btn

    def delete_button(self) -> MaterialIconButton:
        return self._del_btn

    def json_button(self) -> MaterialIconButton:
        return self._json_btn

    # ── 自定义作业 JSON ──────────────────────────────────

    @property
    def json_path(self) -> str | None:
        """已绑定的自定义作业 JSON 路径（None 表示未绑定）"""
        return self._json_path

    def set_json_path(self, path: str | None) -> None:
        """绑定/移除自定义作业 JSON，并刷新按钮状态显示"""
        self._json_path = path
        self._refresh_json_btn()

    def _refresh_json_btn(self) -> None:
        """按绑定状态刷新 JSON 按钮的图标、色调与 tooltip"""
        if self._json_path:
            icon_name = "description"
            tint = "primary"
            tooltip = tr("batch.tooltip.json.set", path=self._json_path)
        else:
            icon_name = "note_add"
            tint = None
            tooltip = tr("batch.tooltip.json.add")
        self._json_btn.set_icon(icon_name)
        self._json_btn.set_tint_role(tint)
        self._json_btn.setToolTip(tooltip)

    # ── 视觉 ─────────────────────────────────────────────

    def _make_icon_btn(self, icon_name: str, tooltip: str) -> MaterialIconButton:
        # MD3 标准 40dp 命中区；窄队列卡片（≥375dp）内 4 个并排仍有余量
        return MaterialIconButton(icon_name, tooltip, size=40, icon_size=20)

    def _apply_styles(self) -> None:
        c = self._colors
        self._index_label.setStyleSheet(
            f"background-color: {c.primary_container};"
            f" color: {c.on_primary_container};"
            f" border-radius: {Space.S}px; border: none;"
        )
        self._name_label.setStyleSheet(
            f"color: {c.on_surface}; background: transparent; border: none;"
        )
        self._percent_label.setStyleSheet(
            f"color: {c.on_surface_variant}; background: transparent; border: none;"
        )
        self._status_label.setStyleSheet(self._status_text_qss())

    def _status_text_qss(self) -> str:
        c = self._colors
        color = {
            STATUS_PENDING: c.on_surface_variant,
            STATUS_RUNNING: c.primary,
            STATUS_SUCCESS: c.success,
            STATUS_FAILED: c.error,
            STATUS_CANCELLED: c.warning,
        }.get(self._status, c.on_surface_variant)
        return (
            f"color: {color}; font-weight: 500; border: none; background: transparent;"
        )

    def _refresh_status_icon(self) -> None:
        icon_map = {
            STATUS_SUCCESS: ("check_circle", self._colors.success),
            STATUS_FAILED: ("error", self._colors.error),
            STATUS_CANCELLED: ("warning", self._colors.warning),
        }
        entry = icon_map.get(self._status)
        if entry is None:
            self._status_icon.clear()
            return
        name, color = entry
        pix = make_icon_pixmap(name, color, 20)
        self._status_icon.setPixmap(pix if pix is not None else QPixmap())

    # ── 事件 ─────────────────────────────────────────────

    def enterEvent(self, event) -> None:
        self._hover = StateLayer.HOVER
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = 0.0
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        """悬停墨层（8% on_surface），圆角 8dp"""
        if self._hover <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(with_alpha(self._colors.on_surface, self._hover))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8.0, 8.0)
        painter.drawPath(path)
        painter.end()


class BatchVideoList(QWidget):
    """批量视频文件列表"""

    video_paths_changed = pyqtSignal(list)

    def __init__(self, colors: MaterialColors, parent: QWidget | None = None,
                 show_json_button: bool = True) -> None:
        super().__init__(parent)
        self._colors = colors
        self._rows: list[BatchVideoRow] = []
        self._editable = True
        self._show_json_button = show_json_button
        self._typo = MaterialTypography()

        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(Space.M)

        # 顶部操作栏：计数在左，操作在右（清空为 text 按钮，最低优先级）
        top_bar = QHBoxLayout()
        top_bar.setSpacing(Space.S)
        self._count_label = QLabel(tr("batch.count", n=0), self)
        self._count_label.setFont(self._typo.font("label_medium"))
        top_bar.addWidget(self._count_label)
        top_bar.addStretch()
        self._add_btn = MaterialButton(
            tr("batch.add_videos"),
            variant=MaterialButton.VARIANT_TONAL,
        )
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._clear_btn = MaterialButton(
            tr("batch.clear"), variant=MaterialButton.VARIANT_TEXT
        )
        self._clear_btn.clicked.connect(self.clear)
        top_bar.addWidget(self._add_btn)
        top_bar.addWidget(self._clear_btn)
        outer.addLayout(top_bar)

        # 列表区（无边框；行自身负责悬停态）
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(Space.XS)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)

        # 空列表占位：图标 + 说明（MD3 空态不用虚线框）
        self._placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self._placeholder)
        # 底部留出 FAB 的安全区：compact 档 FAB 悬浮在视口右下角，
        # 空态图标/文案必须上移足够距离才不会被按钮压住（历史实测
        # 72dp 仍会重叠文字，这里取 160dp）
        placeholder_layout.setContentsMargins(0, Space.XXL, 0, Space.XXXL * 4)
        placeholder_layout.setSpacing(Space.S)
        placeholder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._placeholder_icon = QLabel(self._placeholder)
        self._placeholder_icon.setFixedSize(40, 40)
        self._placeholder_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_icon.setStyleSheet("background: transparent; border: none;")
        placeholder_layout.addWidget(
            self._placeholder_icon, 0, Qt.AlignmentFlag.AlignHCenter
        )

        self._placeholder_text = QLabel(tr("batch.placeholder"), self._placeholder)
        self._placeholder_text.setFont(self._typo.font("body_medium"))
        self._placeholder_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_text.setWordWrap(True)
        placeholder_layout.addWidget(self._placeholder_text)

        self._list_layout.addWidget(self._placeholder)

        # 语言切换时刷新所有静态文本与已有行
        i18n().language_changed.connect(self._retranslate)
        # 订阅主题：行、空态与图标配色自动跟随
        theme_controller().theme_changed.connect(self.set_colors)
        self._apply_styles()
        self._refresh_placeholder()

    def _retranslate(self) -> None:
        """语言切换时刷新按钮文本、计数、占位提示与所有行的状态/tooltip"""
        self._add_btn.setText(tr("batch.add_videos"))
        self._clear_btn.setText(tr("batch.clear"))
        self._count_label.setText(tr("batch.count", n=len(self._rows)))
        self._placeholder_text.setText(tr("batch.placeholder"))
        for row in self._rows:
            row.refresh_translations()

    # ── 公开 API ──────────────────────────────────────────

    def set_add_visible(self, visible: bool) -> None:
        """显示/隐藏卡片内的"添加视频"按钮（主页由 FAB 承担主操作）"""
        self._add_btn.setVisible(visible)

    def set_list_max_height(self, height: int) -> None:
        """限制列表区最大高度（文件再多也在列表内滚动）

        主页卡片在单列布局中会被父布局拉伸，需要带上界；工具窗口空间充足，
        保持不限制（默认）。
        """
        self._scroll.setMaximumHeight(max(120, int(height)))

    def open_add_dialog(self) -> None:
        """打开"添加视频"文件选择流程（供主页 FAB 调用）"""
        self._on_add_clicked()

    def video_paths(self) -> list[str]:
        return [row.video_path for row in self._rows]

    def json_paths(self) -> list[str | None]:
        """与 video_paths() 平行对齐的自定义作业 JSON 路径列表（None=未绑定）

        仅本次会话有效，不持久化到配置文件。
        """
        return [row.json_path for row in self._rows]

    def add_paths(self, paths: list[str]) -> None:
        added = False
        # 方法开头一次性构建已有路径集合并随添加同步维护，
        # 避免循环内反复调用 video_paths() 造成的 O(n²) 重复扫描
        existing = set(self.video_paths())
        for p in paths:
            p = p.strip() if isinstance(p, str) else p
            if not p:
                continue
            ext = os.path.splitext(p)[1].lower()
            if ext not in SUPPORTED_VIDEO_EXTENSIONS:
                continue
            if p in existing:
                continue  # 去重
            existing.add(p)
            row = BatchVideoRow(p, self._colors)
            row.set_editable(self._editable)
            if not self._show_json_button:
                row.set_json_button_visible(False)
            row.up_button().clicked.connect(lambda _, r=row: self._move_up(r))
            row.down_button().clicked.connect(lambda _, r=row: self._move_down(r))
            row.delete_button().clicked.connect(lambda _, r=row: self._remove(r))
            row.json_button().clicked.connect(
                lambda _, r=row: self._on_json_clicked(r)
            )
            self._rows.append(row)
            self._list_layout.addWidget(row)
            added = True
        if added:
            self._reindex()
            self._refresh_placeholder()
            self.video_paths_changed.emit(self.video_paths())

    def clear(self) -> None:
        if not self._rows:
            return
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._reindex()
        self._refresh_placeholder()
        self.video_paths_changed.emit([])

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        self._add_btn.setEnabled(editable)
        self._clear_btn.setEnabled(editable and bool(self._rows))
        for row in self._rows:
            row.set_editable(editable)

    def reset_states(self) -> None:
        for row in self._rows:
            row.reset_state()

    # ── 状态更新（由服务层信号驱动） ─────────────────────

    def set_file_running(self, index: int) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index].set_status(STATUS_RUNNING, 0)

    def set_file_progress(self, index: int, percent: int, message: str) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index].set_status(STATUS_RUNNING, percent)

    def set_file_finished(self, index: int, success: bool,
                          cancelled: bool = False) -> None:
        if 0 <= index < len(self._rows):
            if cancelled:
                status = STATUS_CANCELLED
            else:
                status = STATUS_SUCCESS if success else STATUS_FAILED
            self._rows[index].set_status(status, None)

    # ── 主题 ─────────────────────────────────────────────

    def set_colors(self, colors: MaterialColors) -> None:
        self._colors = colors
        self._apply_styles()
        for row in self._rows:
            row.set_colors(colors)

    def _apply_styles(self) -> None:
        c = self._colors
        self._count_label.setStyleSheet(
            f"color: {c.on_surface_variant}; background: transparent; border: none;"
        )
        self._placeholder_text.setStyleSheet(
            f"color: {c.on_surface_variant}; background: transparent; border: none;"
        )
        if has_icon("folder_open"):
            pix = make_icon_pixmap("folder_open", c.on_surface_variant, 40)
            if pix is not None:
                self._placeholder_icon.setPixmap(pix)

    # ── 拖放 ─────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        # 与"添加/清空"按钮一致：批次运行中禁止改动列表，否则列表与
        # 服务端批次索引错位，且会在运行期间改写 config.video_paths
        if not self._editable:
            event.ignore()
            return
        paths: list[str] = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    # ── 内部 ─────────────────────────────────────────────

    def _on_json_clicked(self, row: BatchVideoRow) -> None:
        """自定义作业 JSON 按钮点击处理

        未绑定：弹出文件对话框选择 JSON；
        已绑定：弹出菜单选择「更换 JSON」或「移除 JSON」。
        """
        if row.json_path:
            menu = QMenu(self)
            # exec 后立即销毁：父控件存活期间反复右键会累积子 QMenu 对象
            menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            replace_act = menu.addAction(tr("batch.tooltip.json.replace"))
            remove_act = menu.addAction(tr("batch.tooltip.json.remove"))
            chosen = menu.exec(self._json_pos(row.json_button()))
            if chosen is replace_act:
                self._pick_json_for_row(row)
            elif chosen is remove_act:
                row.set_json_path(None)
        else:
            self._pick_json_for_row(row)

    def _pick_json_for_row(self, row: BatchVideoRow) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, tr("batch.json_open_title"), "",
            "Copilot JSON (*.json);;All files (*.*)",
        )
        if path:
            row.set_json_path(path)

    def _json_pos(self, btn: MaterialIconButton) -> QPoint:
        """计算 JSON 按钮在屏幕上的位置，用于弹出菜单"""
        return btn.mapToGlobal(QPoint(0, btn.height()))

    def _on_add_clicked(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        exts = ' '.join(f'*{e}' for e in sorted(SUPPORTED_VIDEO_EXTENSIONS))
        filter_str = f'Video files ({exts});;All files (*.*)'
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("batch.open_title"), "", filter_str,
        )
        if paths:
            self.add_paths(paths)

    def _move_up(self, row: BatchVideoRow) -> None:
        idx = self._rows.index(row)
        if idx <= 0:
            return
        self._rows[idx], self._rows[idx - 1] = self._rows[idx - 1], self._rows[idx]
        self._reorder_layout()
        self._reindex()
        self.video_paths_changed.emit(self.video_paths())

    def _move_down(self, row: BatchVideoRow) -> None:
        idx = self._rows.index(row)
        if idx >= len(self._rows) - 1:
            return
        self._rows[idx], self._rows[idx + 1] = self._rows[idx + 1], self._rows[idx]
        self._reorder_layout()
        self._reindex()
        self.video_paths_changed.emit(self.video_paths())

    def _remove(self, row: BatchVideoRow) -> None:
        idx = self._rows.index(row)
        self._list_layout.removeWidget(row)
        row.deleteLater()
        self._rows.pop(idx)
        self._reindex()
        self._refresh_placeholder()
        self.video_paths_changed.emit(self.video_paths())

    def _reorder_layout(self) -> None:
        # 按 _rows 顺序重排布局中的行 widget（保留 placeholder 在最后）
        for row in self._rows:
            self._list_layout.removeWidget(row)
        for row in self._rows:
            self._list_layout.addWidget(row)
        self._list_layout.addWidget(self._placeholder)

    def _reindex(self) -> None:
        for i, row in enumerate(self._rows, start=1):
            row.set_index(i)
        self._count_label.setText(tr("batch.count", n=len(self._rows)))

    def _refresh_placeholder(self) -> None:
        has_rows = bool(self._rows)
        self._placeholder.setVisible(not has_rows)
        # 空态保留一块稳定的拖放区域高度，与左侧配置卡片视觉平衡
        self._scroll.setMinimumHeight(220 if not has_rows else 0)
        # 空列表时"清空"无意义，置灰
        self._clear_btn.setEnabled(bool(self._rows) and self._editable)
