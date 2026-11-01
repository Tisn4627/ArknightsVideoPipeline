"""gui.theme.theme_controller - 唯一的主题调度入口

历史问题：主题切换由 ``MainWindow._toggle_theme`` 里 20 余处
``if getattr(...)`` 手工级联完成，每新增一个控件就要记得往清单里加一行，
漏一处就出现"深色下残留白块 / 文字不可见"的回归（历史上已发生两次）。

现在改为**订阅制**：

1. :class:`ThemeController` 是进程内唯一的主题状态持有者（明暗 / 种子 /
   是否启用动态色彩）；
2. 组件在自己的构造函数里 ``theme_controller().theme_changed.connect(...)``，
   由 Qt 在对象销毁时自动断开；
3. 页面层只负责"请求切换"，不再枚举需要刷新的控件。

用法::

    from arknights_video_pipeline.gui.theme import theme_controller
    theme_controller().apply(dark=True, app=QApplication.instance())
"""

from __future__ import annotations

import logging

from PyQt6 import sip
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QGroupBox, QHeaderView,
    QLineEdit, QListView, QListWidget, QMenu, QMenuBar, QPlainTextEdit,
    QProgressBar, QRadioButton, QScrollBar, QSlider, QSplitter, QStatusBar,
    QTabBar, QTabWidget, QTableView, QTableWidget, QTextEdit, QToolBar, QTreeWidget,
)

from arknights_video_pipeline.gui.theme.colors import MaterialColors
from arknights_video_pipeline.gui.theme.hct import normalize_hex
from arknights_video_pipeline.gui.theme.palette import apply_palette
from arknights_video_pipeline.gui.theme.scheme import BASELINE_SEED
from arknights_video_pipeline.gui.theme.styles import MaterialStyle
from arknights_video_pipeline.gui.theme.typography import MaterialTypography

logger = logging.getLogger(__name__)

__all__ = ["ThemeController", "theme_controller"]


class ThemeController(QObject):
    """主题状态 + 应用调度（进程内单例）

    Signals:
        theme_changed(object): 主题应用后发出，参数为新的 ``MaterialColors``；
            组件在构造时订阅即可自动跟随主题，无需页面层手工枚举。
    """

    theme_changed = pyqtSignal(object)

    _instance: "ThemeController | None" = None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._typography = MaterialTypography()
        self._dark = False
        self._seed = BASELINE_SEED
        self._dynamic = True
        self._colors = MaterialColors.light()
        # 最近一次实际应用到 QApplication 的颜色（用于跳过同色重复应用）
        self._applied_colors: MaterialColors | None = None
        self._applied_app_id: int | None = None

    @classmethod
    def instance(cls) -> "ThemeController":
        """取进程内单例（首次调用时创建）

        需要处理"底层 C++ 对象已被销毁"的情况：``QApplication`` 析构时
        PyQt 会连带回收无父对象的 ``QObject``，而测试中每个用例模块都会
        独立创建/销毁 ``QApplication``，因此这里用 ``sip.isdeleted`` 兜底重建。
        """
        instance = cls._instance
        if instance is None or sip.isdeleted(instance):
            instance = cls()
            cls._instance = instance
        return instance

    @classmethod
    def reset_instance(cls) -> None:
        """销毁单例（仅测试使用，避免用例之间主题状态泄漏）"""
        cls._instance = None

    # ── 状态查询 ─────────────────────────────────────────

    def colors(self) -> MaterialColors:
        """当前生效的配色"""
        return self._colors

    def is_dark(self) -> bool:
        return self._dark

    def seed(self) -> str:
        """当前种子色（动态色彩关闭时仍保留用户选择，便于再次开启）"""
        return self._seed

    def is_dynamic(self) -> bool:
        """是否启用 Material You 动态色彩"""
        return self._dynamic

    def effective_seed(self) -> str:
        """实际参与推导的种子：动态色彩关闭时固定为品牌基线"""
        return self._seed if self._dynamic else BASELINE_SEED

    # ── 状态变更 ─────────────────────────────────────────

    def resolve(
        self, dark: bool, seed: str, dynamic: bool
    ) -> MaterialColors:
        """纯函数：按参数推导配色（不修改状态、不应用）"""
        return MaterialColors.from_seed(seed if dynamic else BASELINE_SEED, dark=dark)

    def apply(
        self,
        *,
        dark: bool | None = None,
        seed: str | None = None,
        dynamic: bool | None = None,
        app: QApplication | None = None,
    ) -> MaterialColors:
        """应用主题并广播

        切换路径（运行期）：

        1. ``QApplication.setPalette``：文字 / 背景 / 选中色由 QPalette 驱动，
           原生控件即时跟随（约 1ms）；
        2. 对少量"颜色写在 QSS、用 ``palette(role)`` 解析"的控件
           （输入框 / 滚动条 / 菜单等）逐只 ``unpolish + polish`` 重新解析；
        3. 广播 ``theme_changed``，自绘组件按新 token 重绘。

        **不再对整个控件树 ``setStyleSheet``**：旧实现对约 900 个 QWidget
        重新 polish，单次 0.6-2.5 秒，是深色切换卡顿的根因。

        Args:
            dark: 是否深色；None 表示保持当前值
            seed: 种子色；None 表示保持当前值，非法值回退到品牌基线
            dynamic: 是否启用动态色彩；None 表示保持当前值
            app: ``QApplication``；None 时取当前实例（缺失则只更新状态与信号）

        Returns:
            应用后的新配色
        """
        if dark is not None:
            self._dark = bool(dark)
        if dynamic is not None:
            self._dynamic = bool(dynamic)
        if seed is not None:
            try:
                self._seed = normalize_hex(seed)
            except ValueError:
                logger.warning("非法的种子色 %r，回退到基线紫 %s", seed, BASELINE_SEED)
                self._seed = BASELINE_SEED

        colors = self.resolve(self._dark, self._seed, self._dynamic)
        self._colors = colors

        application = app or QApplication.instance()
        if application is not None:
            if self._applied_app_id != id(application):
                # 该应用还没装过样式表（启动期：控件树尚未建立，整树
                # polish 的成本接近零）：装 QSS + 全局字体 + QPalette
                MaterialStyle(
                    colors=colors, typography=self._typography
                ).apply(application)
                self._applied_colors = colors
                self._applied_app_id = id(application)
            elif self._applied_colors != colors:
                apply_palette(colors)
                _repolish_palette_widgets(application)
                self._applied_colors = colors

        self.theme_changed.emit(colors)
        return colors


#: QSS 中通过 ``palette(role)`` 取色的原生控件类型。这些控件的颜色在
#: polish 时解析成具体色值，切主题后必须重新 polish 才会跟随新调色板。
#: 其余控件（标签 / 布局容器 / 自绘组件）由 QPalette 传播或 ``theme_changed``
#: 信号刷新，不需要逐个重刷。
_PALETTE_WIDGET_TYPES = (
    QLineEdit,
    QComboBox,
    QAbstractSpinBox,
    QPlainTextEdit,
    QTextEdit,
    QScrollBar,
    QProgressBar,
    QGroupBox,
    QTabBar,
    QTabWidget,
    QHeaderView,
    QListWidget,
    QTreeWidget,
    QTableWidget,
    QListView,
    QTableView,
    QCheckBox,
    QRadioButton,
    QSlider,
    QSplitter,
    QMenu,
    QMenuBar,
    QStatusBar,
    QToolBar,
)


def _repolish_palette_widgets(application: QApplication) -> int:
    """清除显式调色板 + 重新解析 QSS 里的 ``palette(role)``

    两步都不能省：

    1. **清空每条调色板**：``QStyleSheetStyle`` 在 polish 时会调用
       ``QWidget::setPalette``，控件因此带上 ``WA_SetPalette``，之后
       ``QApplication.setPalette`` 不再传播到它，文字会停在旧主题色。
       重置为空 ``QPalette`` 让控件重新从父链继承新主题；
    2. **重刷输入类控件**：QSS 里的 ``palette(role)`` 在 polish 时就已解析成
       具体色值，不重新 polish 不会跟随新调色板。

    逐只 ``unpolish + polish`` 比给整棵树重设样式表便宜两个数量级：实测
    设置页 148 个输入框 + 30 个滚动条约 100-175ms（旧实现整树重设
    0.6-2.5 秒）。返回本次重刷的控件数量，便于测试断言。
    """
    empty = QPalette()
    count = 0
    for widget in application.allWidgets():
        widget.setPalette(empty)
        if not isinstance(widget, _PALETTE_WIDGET_TYPES):
            continue
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
        count += 1
    return count


def theme_controller() -> ThemeController:
    """模块级访问器（等价 ``ThemeController.instance()``，便于组件订阅）"""
    return ThemeController.instance()
