"""
launchers - 打包入口脚本生成模块

为不同打包模式（GUI / CLI / 合并）生成 PyInstaller 入口脚本。

核心设计:
    项目源码中 PROJECT_ROOT 通过向上查找 pyproject.toml 确定，
    打包后该文件不存在，回退逻辑在 onedir 模式下恰好指向 exe 目录，
    但 onefile 模式下会指向临时解压目录(_MEIPASS)，导致无法找到
    config/resource/MAA 等外部资源。

    解决方案: 在入口脚本中优先导入 utils 模块并 patch PROJECT_ROOT
    为 sys.executable 所在目录（即 exe 所在目录），确保所有后续模块
    通过 `from ...utils import PROJECT_ROOT` 获取到正确的值。

    由于 Python 的 `from X import Y` 在模块已加载时会从 sys.modules
    中获取属性值，因此在任何业务模块导入之前 patch utils.PROJECT_ROOT，
    即可保证全局一致。
"""

from __future__ import annotations

# ── 公共前缀：PROJECT_ROOT 修正逻辑 ───────────────────────

_HEADER = '''"""
ArknightsVideoPipeline 打包入口脚本

此文件由 build_exe 工具自动生成，请勿手动编辑。
作用: 在导入业务模块前修正 PROJECT_ROOT，确保打包后能正确定位
      config/resource/MAA 等外部资源目录。
"""

import os
import sys


def _fix_project_root() -> str:
    """计算并修正 PROJECT_ROOT

    打包后 PROJECT_ROOT 应为 exe 所在目录，用户需在该目录放置
    config/、resource/、MAA 等运行时所需文件。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包环境: exe 所在目录
        project_root = os.path.dirname(sys.executable)
    else:
        # 开发环境: 脚本所在目录的上级（项目根）
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 在导入任何业务模块前 patch PROJECT_ROOT
    # 必须先导入 utils，再修改其属性，这样后续模块的
    # `from ...utils import PROJECT_ROOT` 才能获取到修正后的值
    from arknights_video_pipeline.core import utils as _utils
    _utils.PROJECT_ROOT = project_root

    # core.__init__ 在导入 utils 时已经绑定了 PROJECT_ROOT，需要同步修正
    from arknights_video_pipeline import core as _core
    if hasattr(_core, "PROJECT_ROOT"):
        _core.PROJECT_ROOT = project_root

    return project_root


# 执行修正
_PROJECT_ROOT = _fix_project_root()
'''


# ── CLI 模式入口 ──────────────────────────────────────────

CLI_LAUNCHER = _HEADER + '''

def main() -> None:
    """CLI 入口"""
    from arknights_video_pipeline.core.pipeline import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
'''


# ── GUI 模式入口 ──────────────────────────────────────────

GUI_LAUNCHER = _HEADER + '''

def main() -> int:
    """GUI 入口

    复用项目根目录 gui.py 的错误处理逻辑，提供友好的启动错误提示。
    """
    from arknights_video_pipeline.core.exceptions import ConfigError

    def _show_startup_error(title: str, text: str) -> None:
        sys.stderr.write(f"[{title}] {text}\\n")
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, title, text)
            if app.instance() is not None:
                app.exec()
        except Exception:
            pass

    try:
        from PyQt6.QtWidgets import QApplication
        from arknights_video_pipeline.gui.app import create_application
        from arknights_video_pipeline.gui.main_window import MainWindow
        from arknights_video_pipeline.service import ConfigProxy
    except ImportError as exc:
        _show_startup_error("依赖缺失", f"无法加载必要的依赖: {exc}")
        return 1

    try:
        app = create_application(sys.argv)
        config_proxy = ConfigProxy()
        window = MainWindow(config_proxy)
        window.show()
        return QApplication.exec()
    except ConfigError as exc:
        _show_startup_error("配置错误", f"配置文件加载失败: {exc}")
        return 2
    except FileNotFoundError as exc:
        _show_startup_error("文件缺失", f"必要的文件不存在: {exc}")
        return 3
    except Exception as exc:
        _show_startup_error("启动失败", f"GUI 启动遇到未知错误: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
'''


# ── 合并模式入口 ──────────────────────────────────────────

COMBINED_LAUNCHER = _HEADER + '''

def _run_cli() -> int:
    """运行 CLI 模式"""
    from arknights_video_pipeline.core.pipeline import main as cli_main
    try:
        cli_main()
        return 0
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    except KeyboardInterrupt:
        sys.stderr.write("\\n用户中断执行\\n")
        return 130
    except Exception as exc:
        sys.stderr.write(f"程序启动失败: {exc}\\n")
        return 1


def _run_gui() -> int:
    """运行 GUI 模式"""
    from arknights_video_pipeline.core.exceptions import ConfigError

    def _show_startup_error(title: str, text: str) -> None:
        sys.stderr.write(f"[{title}] {text}\\n")
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, title, text)
            if app.instance() is not None:
                app.exec()
        except Exception:
            pass

    try:
        from PyQt6.QtWidgets import QApplication
        from arknights_video_pipeline.gui.app import create_application
        from arknights_video_pipeline.gui.main_window import MainWindow
        from arknights_video_pipeline.service import ConfigProxy
    except ImportError as exc:
        _show_startup_error("依赖缺失", f"无法加载必要的依赖: {exc}")
        return 1

    try:
        app = create_application(sys.argv)
        config_proxy = ConfigProxy()
        window = MainWindow(config_proxy)
        window.show()
        return QApplication.exec()
    except ConfigError as exc:
        _show_startup_error("配置错误", f"配置文件加载失败: {exc}")
        return 2
    except FileNotFoundError as exc:
        _show_startup_error("文件缺失", f"必要的文件不存在: {exc}")
        return 3
    except Exception as exc:
        _show_startup_error("启动失败", f"GUI 启动遇到未知错误: {exc}")
        return 1


def main() -> int:
    """合并入口: 根据命令行参数自动选择 GUI 或 CLI 模式

    规则:
        - 无参数 → 启动 GUI
        - 有参数 → 启动 CLI（透传所有参数）
        - --gui 标志 → 强制启动 GUI（即使有其他参数）
    """
    # 检查是否强制 GUI 模式
    if "--gui" in sys.argv:
        sys.argv.remove("--gui")
        return _run_gui()

    # 无额外参数时启动 GUI
    if len(sys.argv) <= 1:
        return _run_gui()

    # 有参数时启动 CLI
    return _run_cli()


if __name__ == "__main__":
    sys.exit(main())
'''


# ── 模式 → 脚本内容 映射 ─────────────────────────────────

LAUNCHERS: dict[str, str] = {
    "cli": CLI_LAUNCHER,
    "gui": GUI_LAUNCHER,
    "combined": COMBINED_LAUNCHER,
}


def get_launcher(mode: str) -> str:
    """获取指定模式的入口脚本内容

    Args:
        mode: 打包模式，可选 "gui" / "cli" / "combined"

    Returns:
        入口脚本的 Python 源码字符串

    Raises:
        ValueError: 不支持的打包模式
    """
    mode = mode.lower().strip()
    if mode not in LAUNCHERS:
        valid = ", ".join(LAUNCHERS.keys())
        raise ValueError(f"不支持的打包模式: {mode}，可选: {valid}")
    return LAUNCHERS[mode]
