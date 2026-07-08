"""
gui.theme.titlebar - 跨平台标题栏主题适配

让原生窗口标题栏跟随应用的浅色/深色主题，避免深色界面下标题栏仍是
刺眼的白色。

平台策略：
- Windows 10 1809+（build 17763+）：DWM API（``DwmSetWindowAttribute``
  设置 ``DWMWA_USE_IMMERSIVE_DARK_MODE``），配合 ``SetWindowPos`` +
  ``RedrawWindow`` 触发应用侧 NC 重绘，再通过 ``DWMWA_CLOAK``
  cloak/decloak + ``DwmFlush`` 强制 DWM 重建合成表面，使标题栏即时上屏
- macOS / Linux：``QApplication.styleHints().setColorScheme()``（Qt 6.5+）
- 其他平台或旧版本静默跳过，调用方无需关心平台差异

参考：
- ``DWMWA_USE_IMMERSIVE_DARK_MODE`` 在 build 18985（20H1）起属性 id = 20
- build 17763~18984 之间属性 id = 19
- ``DWMWA_CLOAK`` (attr id 13) 强制 DWM 丢弃缓存的标题栏位图并重建
  合成表面；在 LTSC 2021 等 DWM 缓存环境中仅靠 ``DwmFlush`` 不足以
  触发标题栏重绘
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# ── Win32 常量 ────────────────────────────────────────────
# SetWindowPos flags
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

# RedrawWindow flags
RDW_INVALIDATE = 0x0001
RDW_UPDATENOW = 0x0100
RDW_FRAME = 0x0400

# DWM window attributes
DWMWA_CLOAK = 13
_DWMWA_USE_IMMERSIVE_DARK_MODE_NEW = 20  # build 18985+
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19  # build 17763-18984

# 懒加载缓存的 Win32 API 句柄（首次调用时初始化，后续复用）
_user32 = None
_dwmapi = None


def _get_win32_apis():
    """懒加载并缓存 user32/dwmapi DLL 及函数签名（仅 Windows 调用）

    首次调用时导入 ``ctypes`` 并配置 ``argtypes``/``restype``，
    后续调用直接返回缓存值，避免每次主题切换都重复配置。
    """
    global _user32, _dwmapi
    if _user32 is not None:
        return _user32, _dwmapi

    import ctypes

    _user32 = ctypes.WinDLL("user32")
    _user32.SetWindowPos.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint32,
    ]
    _user32.SetWindowPos.restype = ctypes.c_bool
    _user32.RedrawWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
    ]
    _user32.RedrawWindow.restype = ctypes.c_bool

    _dwmapi = ctypes.WinDLL("dwmapi")
    _dwmapi.DwmSetWindowAttribute.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
    ]
    _dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    _dwmapi.DwmFlush.argtypes = []
    _dwmapi.DwmFlush.restype = ctypes.c_long
    return _user32, _dwmapi


def _get_windows_build() -> int | None:
    """获取 Windows 内部版本号；非 Windows 或读取失败返回 None"""
    if sys.platform != "win32":
        return None
    try:
        # sys.getwindowsversion() 在 win32 平台返回 named tuple
        return int(sys.getwindowsversion().build)  # type: ignore[attr-defined]
    except Exception:
        return None


def is_titlebar_theming_supported() -> bool:
    """检查当前平台是否支持标题栏主题跟随

    - Windows：需 10 1809（build 17763）及以上版本（DWM API）
    - macOS / Linux：Qt 6.5+ 的 ``setColorScheme`` 可用即支持
    """
    if sys.platform == "win32":
        build = _get_windows_build()
        return build is not None and build >= 17763
    return sys.platform in ("darwin", "linux")


def _force_titlebar_redraw(hwnd: int) -> None:
    """强制 DWM 重建窗口合成表面，使标题栏属性变更即时上屏。

    两步策略：
    1. ``SetWindowPos[FRAMECHANGED]`` + ``RedrawWindow[FRAME|INVALIDATE|UPDATENOW]``
       触发应用侧非客户区同步重绘
    2. ``DWMWA_CLOAK`` cloak/decloak（中间无 ``DwmFlush``）+ 单次 ``DwmFlush``
       强制 DWM 丢弃缓存的标题栏位图并重建合成表面

    在 LTSC 2021 等 DWM 缓存标题栏位图的环境中，仅步骤 1 不足以触发 DWM
    重新渲染标题栏——``DwmFlush`` 在无 pending 工作时立即返回（~1-2ms），
    DWM 继续使用缓存的标题栏位图。步骤 2 的 cloak/decloak 强制 DWM 销毁
    并重建合成表面，重建时读取最新的 ``DWMWA_USE_IMMERSIVE_DARK_MODE`` 属性。

    cloak 和 decloak 之间**不**调用 ``DwmFlush``，避免 DWM 将 cloaked
    （不可见）状态合成到屏幕，从而消除窗口闪烁。
    """
    import ctypes

    user32, dwmapi = _get_win32_apis()

    # 步骤 1：应用侧 NC 区同步重绘
    swp_flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
    if not user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, swp_flags):
        logger.debug("SetWindowPos[FRAMECHANGED] 失败 (hwnd=%s)", hwnd)
    rdw_flags = RDW_FRAME | RDW_INVALIDATE | RDW_UPDATENOW
    if not user32.RedrawWindow(hwnd, None, None, rdw_flags):
        logger.debug("RedrawWindow[FRAME|INVALIDATE|UPDATENOW] 失败 (hwnd=%s)", hwnd)

    # 步骤 2：DWM 侧合成表面重建（cloak → decloak → 单次 flush）
    cloak_val = ctypes.c_int(1)
    result = dwmapi.DwmSetWindowAttribute(
        hwnd, DWMWA_CLOAK, ctypes.byref(cloak_val), ctypes.sizeof(cloak_val)
    )
    if result != 0:
        logger.debug("DwmSetWindowAttribute[cloak] 失败: 0x%08X", result & 0xFFFFFFFF)
    cloak_val = ctypes.c_int(0)
    result = dwmapi.DwmSetWindowAttribute(
        hwnd, DWMWA_CLOAK, ctypes.byref(cloak_val), ctypes.sizeof(cloak_val)
    )
    if result != 0:
        logger.debug("DwmSetWindowAttribute[decloak] 失败: 0x%08X", result & 0xFFFFFFFF)
    result = dwmapi.DwmFlush()
    if result != 0:
        logger.debug("DwmFlush 失败: 0x%08X", result & 0xFFFFFFFF)


def apply_titlebar_theme(window, dark: bool) -> bool:
    """设置窗口标题栏为深色或浅色（跨平台）

    平台策略：
    - Windows 10 1809+：DWM API（``DwmSetWindowAttribute`` + cloak/decloak
      + ``DwmFlush``），原生标题栏即时切换
    - macOS / Linux：``QApplication.styleHints().setColorScheme()``
      （Qt 6.5+），macOS 映射到 NSAppearance 原生标题栏跟随；Linux
      效果取决于窗口管理器/桌面环境
    - 其他/旧版本：静默跳过，返回 False

    Args:
        window: 已实例化的 QWidget（或子类）。Windows 下需要有效窗口句柄，
            可在 show() 之前调用（``winId()`` 会强制创建原生窗口），
            但更推荐在 show() 之后调用以确保稳定。macOS/Linux 下不使用
            该参数但仍需传入以保持签名一致。
        dark: True=深色标题栏；False=浅色标题栏

    Returns:
        True 表示已尝试应用（平台支持）；False 表示平台不支持或调用失败

    Note:
        窗口重建（如 ``setWindowFlags``）后 Windows 句柄可能变化，需
        重新调用本函数。运行时切换主题时调用一次即可。
    """
    if sys.platform == "win32":
        return _apply_titlebar_theme_windows(window, dark)
    if sys.platform in ("darwin", "linux"):
        return _apply_titlebar_theme_qt(dark)
    return False


def _apply_titlebar_theme_windows(window, dark: bool) -> bool:
    """Windows：通过 DWM API 设置标题栏深色/浅色并强制即时刷新

    ``DwmSetWindowAttribute(DWMWA_USE_IMMERSIVE_DARK_MODE)`` 提交属性后，
    调用 ``_force_titlebar_redraw`` 触发非客户区重绘 + cloak/decloak +
    ``DwmFlush`` 强制 DWM 重建合成表面上屏，确保标题栏在用户切换主题后
    立即变色。
    """
    if not is_titlebar_theming_supported():
        return False

    try:
        import ctypes

        hwnd = int(window.winId())
        if hwnd == 0:
            return False

        # DWMWA_USE_IMMERSIVE_DARK_MODE：
        #   build 18985（20H1）起使用 attr id = 20
        #   build 17763~18984 使用 attr id = 19
        build = _get_windows_build() or 0
        attr = _DWMWA_USE_IMMERSIVE_DARK_MODE_NEW if build >= 18985 else _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD

        _, dwmapi = _get_win32_apis()

        value = ctypes.c_int(1 if dark else 0)
        result = dwmapi.DwmSetWindowAttribute(
            hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
        )

        if result != 0:  # S_OK == 0
            logger.debug(
                "DwmSetWindowAttribute 返回非零 HRESULT: 0x%08X (attr=%d, dark=%s)",
                result & 0xFFFFFFFF, attr, dark,
            )
            return False

        _force_titlebar_redraw(hwnd)
        return True
    except Exception as exc:
        logger.debug("_apply_titlebar_theme_windows 调用失败: %s", exc)
        return False


def _apply_titlebar_theme_qt(dark: bool) -> bool:
    """macOS / Linux：通过 Qt 的 colorScheme 设置应用外观

    Qt 6.5+ 的 ``styleHints().setColorScheme()`` 会：
    - macOS：映射到 ``NSAppearance``（``NSAppearanceNameDarkAqua`` /
      ``NSAppearanceNameAqua``），原生标题栏自动跟随应用外观
    - Linux：通知 Qt 平台插件（xcb/wayland）应用外观，标题栏是否
      跟随取决于窗口管理器/桌面环境（KDE 通常跟随，GNOME 标题栏由
      GTK 主题控制可能不跟随）
    """
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False
        scheme = Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light
        app.styleHints().setColorScheme(scheme)
        return True
    except Exception as exc:
        logger.debug("_apply_titlebar_theme_qt 调用失败: %s", exc)
        return False
