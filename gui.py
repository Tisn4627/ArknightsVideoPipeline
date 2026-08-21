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
        QApplication.instance() or QApplication(sys.argv)
        # QMessageBox.critical 自带模态事件循环，弹窗关闭后直接返回；
        # 不能再调用 app.exec()——此时已无任何窗口，事件循环启动后
        # 永远等不到 quitOnLastWindowClosed，进程会假死只能任务管理器杀
        QMessageBox.critical(None, title, text)
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
    _exit_code = 0
    try:
        _exit_code = main() or 0
    except SystemExit as exc:
        _exit_code = exc.code if isinstance(exc.code, int) else 1
    for _s in (sys.stdout, sys.stderr):
        if _s is not None:
            try:
                _s.flush()
            except Exception:
                pass
    # 有意使用 os._exit 立即退出：绕过 Python 关机序列中残留的
    # 非 daemon 线程/Qt 对象析构崩溃（GUI 退出阶段的已知问题源）。
    # stdout/stderr 已在上方手工 flush，其余 atexit 清理被跳过是
    # 接受的代价
    os._exit(_exit_code)
