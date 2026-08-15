"""
gui.app - QApplication 初始化

负责应用级配置、主题初始化与全局样式应用。
"""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox

from arknights_video_pipeline.gui.assets.app_icon import (
    apply_windows_taskbar_identity,
    load_app_icon,
)
from arknights_video_pipeline.gui.theme import MaterialStyle, MaterialTypography
from arknights_video_pipeline.gui.theme.font_manager import FontManager


class _WheelGuard(QObject):
    """阻止滚轮修改 QSpinBox/QComboBox 等设置控件的值，避免误操作"""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            widget = obj
            while widget is not None:
                if isinstance(widget, (QAbstractSpinBox, QComboBox)):
                    return True
                widget = widget.parent()
        return super().eventFilter(obj, event)


def create_application(argv: list[str]) -> QApplication:
    """创建并配置 QApplication"""
    # Windows 任务栏图标：必须在 QApplication/窗口创建前设置进程
    # AppUserModelID，否则任务栏回退到 python.exe 默认图标而非 app_icon.png。
    # macOS dock 图标由下方 setWindowIcon → NSApplication.setApplicationIconImage 处理。
    apply_windows_taskbar_identity()

    # 高分屏支持必须在 QApplication 实例化前配置
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(argv)
    app.setApplicationName("ArknightsVideoPipeline")
    app.setOrganizationName("AVP")

    # 全局屏蔽设置控件上的滚轮事件（QSpinBox/QComboBox 默认会随滚轮改值）
    app.setProperty("_wheel_guard", _WheelGuard(app))
    app.installEventFilter(app.property("_wheel_guard"))

    # 应用官方图标：作用于所有窗口标题栏、任务栏与 Alt-Tab 切换视图
    app.setWindowIcon(load_app_icon())

    # 注册内置字体（Roboto / Noto Sans SC），缺失时静默回退系统字体
    FontManager.load()

    # 应用 Material Design 3 主题
    style = MaterialStyle(typography=MaterialTypography())
    style.apply(app)

    return app


def _hard_exit(exit_code: int | None) -> None:
    """绕过 Python 正常关闭流程直接退出进程。

    PipelineWorker 是非 daemon QThread，Python 解释器关闭时会等待其
    退出。长步骤（MAA/track/compose 可达数百秒）中的 worker 无法及时
    响应 cancel，即使 QThread.terminate() 也可能对 C 扩展内部阻塞无效。
    os._exit 是最终兜底，确保进程不残留。
    """
    code = exit_code if isinstance(exit_code, int) else 0
    for _s in (sys.stdout, sys.stderr):
        if _s is not None:
            try:
                _s.flush()
            except Exception:
                pass
    os._exit(code)


def main() -> int:
    """GUI 入口（供 project.scripts 使用）"""
    from arknights_video_pipeline.core.exceptions import ConfigError
    from arknights_video_pipeline.gui.main_window import MainWindow
    from arknights_video_pipeline.service import ConfigProxy

    try:
        create_application(sys.argv)
        config_proxy = ConfigProxy()
        window = MainWindow(config_proxy)
        window.show()
        exit_code = QApplication.exec()
    except ConfigError as exc:
        sys.stderr.write(f"[配置错误] {exc}\n")
        exit_code = 2
    except Exception as exc:
        sys.stderr.write(f"[启动失败] {exc}\n")
        exit_code = 1

    _hard_exit(exit_code)
    return 0  # unreachable: _hard_exit calls os._exit
