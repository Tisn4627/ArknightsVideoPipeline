"""
gui.app - QApplication 初始化

负责应用级配置、主题初始化与全局样式应用。
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.gui.assets.app_icon import (
    apply_windows_taskbar_identity,
    load_app_icon,
)
from arknights_video_pipeline.gui.theme import MaterialStyle, MaterialTypography


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

    # 应用官方图标：作用于所有窗口标题栏、任务栏与 Alt-Tab 切换视图
    app.setWindowIcon(load_app_icon())

    # 应用 Material Design 3 主题
    style = MaterialStyle(typography=MaterialTypography())
    style.apply(app)

    return app


def main() -> int:
    """GUI 入口（供 project.scripts 使用）"""
    from arknights_video_pipeline.core.exceptions import ConfigError
    from arknights_video_pipeline.gui.main_window import MainWindow
    from arknights_video_pipeline.service import ConfigProxy

    try:
        app = create_application(sys.argv)
        config_proxy = ConfigProxy()
        window = MainWindow(config_proxy)
        window.show()
        return QApplication.exec()
    except ConfigError as exc:
        sys.stderr.write(f"[配置错误] {exc}\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"[启动失败] {exc}\n")
        return 1
