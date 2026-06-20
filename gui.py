"""
ArknightsVideoPipeline - GUI 入口

启动 Material Design 3 风格的图形用户界面。
"""

import os
import sys

# 将 src 目录加入 Python 路径，支持未安装包时直接运行
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from arknights_video_pipeline.core.exceptions import ConfigError


def _show_startup_error(title: str, text: str) -> None:
    """在无 QApplication 时通过 stderr 输出错误，并尝试弹出消息框"""
    sys.stderr.write(f"[{title}] {text}\n")
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, title, text)
        if app.instance() is not None:
            app.exec()
    except Exception:
        # PyQt6 未安装或无法初始化，仅 stderr 输出
        pass


def main() -> int:
    try:
        from PyQt6.QtWidgets import QApplication
        from arknights_video_pipeline.gui.app import create_application
        from arknights_video_pipeline.gui.main_window import MainWindow
        from arknights_video_pipeline.service import ConfigProxy
    except ImportError as exc:
        _show_startup_error("依赖缺失", f"无法加载必要的依赖: {exc}\n请通过 pip install -r requirements.txt 安装依赖。")
        return 1

    try:
        app = create_application(sys.argv)
        config_proxy = ConfigProxy()
        window = MainWindow(config_proxy)
        window.show()
        return QApplication.exec()
    except ConfigError as exc:
        _show_startup_error("配置错误", f"配置文件加载失败: {exc}\n请检查 config/pipeline.json 是否正确。")
        return 2
    except FileNotFoundError as exc:
        _show_startup_error("文件缺失", f"必要的文件不存在: {exc}")
        return 3
    except Exception as exc:
        _show_startup_error("启动失败", f"GUI 启动遇到未知错误: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
