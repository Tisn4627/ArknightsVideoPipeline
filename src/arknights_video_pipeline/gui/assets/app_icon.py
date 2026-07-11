"""
gui.assets.app_icon - 应用官方图标加载

通过 ``Path(__file__).parent`` 定位 ``app_icon.png``，在开发环境
（src layout）、pip 安装（site-packages）与 PyInstaller 打包
（``--add-data`` 将 assets/ 释放到 ``arknights_video_pipeline/gui/assets/``）
三种场景下均能正确解析路径。

``load_app_icon`` 将单一高分辨率 PNG 预渲染为多尺寸 QPixmap 注入
``QIcon``，让 Qt 在标题栏（16/24px）、任务栏（32px）、Alt-Tab（48/64px）
等不同显示位置选择最接近的源位图，避免缩放锯齿。

``apply_windows_taskbar_identity`` 设置进程 AppUserModelID：仅
``setWindowIcon`` 不足以改变 Windows 任务栏图标，因为任务栏按 AppID
分组并选取图标，未设置时回退到宿主进程（python.exe → 默认 Python 图标）。
设置唯一 AppID 后 Windows 才转用窗口图标。必须在窗口显示前调用。
macOS 的 dock 图标由 ``setWindowIcon`` →
``NSApplication.setApplicationIconImage:`` 处理，无需额外调用。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap


# 资源根目录：src/arknights_video_pipeline/gui/assets/
_ASSETS_ROOT: Path = Path(__file__).parent

# 官方图标文件名（位于 _ASSETS_ROOT 下）
_ICON_PATH: Path = _ASSETS_ROOT / "app_icon.png"

# 预渲染尺寸集合：覆盖常见显示位置，确保各 DPI 下清晰
_ICON_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)


def app_icon_path() -> Path:
    """返回官方图标文件的绝对路径（无论是否存在）。"""
    return _ICON_PATH


def load_app_icon() -> QIcon:
    """加载应用官方图标为多分辨率 ``QIcon``。

    文件缺失或解码失败时返回空 ``QIcon``（Qt 回退到默认窗口图标），
    不抛异常，避免图标加载失败阻断 GUI 启动。
    """
    icon = QIcon()
    if not _ICON_PATH.is_file():
        return icon

    src = QPixmap(str(_ICON_PATH))
    if src.isNull():
        return icon

    for size in _ICON_SIZES:
        icon.addPixmap(
            src.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ),
            QIcon.Mode.Normal,
            QIcon.State.Off,
        )
    return icon


# 进程级 AppUserModelID：稳定且唯一，使 Windows 任务栏将本进程
# 视为独立应用并采用窗口图标，而非回退到 python.exe 默认图标。
_DEFAULT_APP_ID = "AVP.ArknightsVideoPipeline"


def apply_windows_taskbar_identity(app_id: str = _DEFAULT_APP_ID) -> bool:
    """设置进程 AppUserModelID，使 Windows 任务栏显示应用自定义图标。

    仅 ``QApplication.setWindowIcon`` 不足以改变任务栏图标——Windows 按
    AppUserModelID 对任务栏按钮分组并选取图标；未显式设置时回退到宿主
    可执行文件（开发态为 ``python.exe`` → 默认 Python 图标）。设置唯一
    AppID 后 Windows 转而使用窗口图标（``setWindowIcon`` 设入的图标）。

    必须在窗口显示前调用（在 ``create_application`` 中 QApplication 构造
    之前设置即可）。非 Windows 平台静默跳过，调用方无需关心平台差异。

    Returns:
        True 表示已设置成功或已跳过（非 Windows）；False 表示调用失败
        （API 不可用或返回非 S_OK），此时仅任务栏图标回退默认，不影响功能。
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        shell32 = ctypes.WinDLL("shell32")
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        # HRESULT S_OK == 0
        return shell32.SetCurrentProcessExplicitAppUserModelID(app_id) == 0
    except Exception:
        return False
