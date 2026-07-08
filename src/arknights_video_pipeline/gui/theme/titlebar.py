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


def _get_windows_build() -> int | None:
    """获取 Windows 内部版本号；非 Windows 或读取失败返回 None"""
    if sys.platform != "win32":
        return None
    try:
        # sys.getwindowsversion() 在 win32 平台返回 named tuple
        return int(sys.getwindowsversion().build)  # type: ignore[attr-defined]
    except Exception:
        return None


# #region debug-point INSTRUMENT:debug-log
def _debug_log(hypothesis_id: str, msg: str, data=None, location: str = "") -> None:
    """向调试服务器发送日志事件（仅调试会话期间使用）"""
    import json as _json
    import urllib.request as _urlreq
    import time as _time
    import os as _os
    _p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))), ".dbg", "titlebar-ltsc-refresh.env")
    _u, _s = "http://127.0.0.1:7777/event", "titlebar-ltsc-refresh"
    try:
        with open(_p) as f:
            c = f.read()
            _u = next((l.split("=", 1)[1].strip() for l in c.split("\n") if l.startswith("DEBUG_SERVER_URL=")), _u)
            _s = next((l.split("=", 1)[1].strip() for l in c.split("\n") if l.startswith("DEBUG_SESSION_ID=")), _s)
    except Exception:
        pass
    try:
        _urlreq.urlopen(_urlreq.Request(_u, data=_json.dumps({
            "sessionId": _s, "runId": "post-fix", "hypothesisId": hypothesis_id,
            "location": location, "msg": f"[DEBUG] {msg}", "data": data or {},
            "ts": int(_time.time() * 1000)
        }).encode(), headers={"Content-Type": "application/json"})).read()
    except Exception:
        pass
# #endregion


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
    # #region debug-point FIX-A:cloak-decloak-no-intermediate-flush
    import ctypes
    import time as _time
    t0 = _time.perf_counter()
    try:
        user32 = ctypes.WinDLL("user32")
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint32,
        ]
        user32.SetWindowPos.restype = ctypes.c_bool
        user32.RedrawWindow.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        ]
        user32.RedrawWindow.restype = ctypes.c_bool

        dwmapi = ctypes.WinDLL("dwmapi")
        dwmapi.DwmSetWindowAttribute.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
        ]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        dwmapi.DwmFlush.argtypes = []
        dwmapi.DwmFlush.restype = ctypes.c_long

        # 步骤 1：应用侧 NC 区同步重绘
        SWP_FLAGS = 0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020  # NOMOVE|NOSIZE|NOZORDER|NOACTIVATE|FRAMECHANGED
        swp_ret = user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FLAGS)
        RDW_FLAGS = 0x0400 | 0x0001 | 0x0100  # FRAME|INVALIDATE|UPDATENOW
        rdw_ret = user32.RedrawWindow(hwnd, None, None, RDW_FLAGS)

        # 步骤 2：DWM 侧合成表面重建（cloak → decloak → 单次 flush）
        DWMWA_CLOAK = 13
        cloak_val = ctypes.c_int(1)
        cloak_ret = dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_CLOAK, ctypes.byref(cloak_val), ctypes.sizeof(cloak_val)
        )
        cloak_val = ctypes.c_int(0)
        decloak_ret = dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_CLOAK, ctypes.byref(cloak_val), ctypes.sizeof(cloak_val)
        )
        flush_ret = dwmapi.DwmFlush()

        total_ms = round((_time.perf_counter() - t0) * 1000, 1)
        _debug_log("FIX-A",
                   f"Fix A 完成: swp={swp_ret} rdw={rdw_ret} "
                   f"cloak=0x{cloak_ret & 0xFFFFFFFF:08X} decloak=0x{decloak_ret & 0xFFFFFFFF:08X} "
                   f"flush=0x{flush_ret & 0xFFFFFFFF:08X} total_ms={total_ms}",
                   {"swp": swp_ret, "rdw": rdw_ret,
                    "cloak_hresult": cloak_ret & 0xFFFFFFFF,
                    "decloak_hresult": decloak_ret & 0xFFFFFFFF,
                    "flush_hresult": flush_ret & 0xFFFFFFFF,
                    "flush_ok": flush_ret == 0,
                    "total_ms": total_ms},
                   "titlebar.py:_force_titlebar_redraw")
    except Exception as exc:
        _debug_log("FIX-A", f"Fix A 异常: {exc}", {"error": str(exc)}, "titlebar.py:_force_titlebar_redraw")
    # #endregion


def apply_titlebar_theme(window, dark: bool) -> bool:
    """设置窗口标题栏为深色或浅色（跨平台）

    平台策略：
    - Windows 10 1809+：DWM API（``DwmSetWindowAttribute`` + 强制重绘
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
    调用 ``_force_titlebar_redraw`` 触发非客户区重绘 + ``DwmFlush`` 强制
    DWM 合成上屏，确保标题栏在用户切换主题后立即变色。
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
        attr = 20 if build >= 18985 else 19

        dwmapi = ctypes.WinDLL("dwmapi")
        dwmapi.DwmSetWindowAttribute.argtypes = [
            ctypes.c_void_p,  # HWND
            ctypes.c_uint32,  # DWORD (attribute id)
            ctypes.c_void_p,  # LPCVOID (pointer to value)
            ctypes.c_uint32,  # DWORD (cbAttribute)
        ]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long  # HRESULT
        dwmapi.DwmGetWindowAttribute.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
        ]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

        value = ctypes.c_int(1 if dark else 0)
        result = dwmapi.DwmSetWindowAttribute(
            hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
        )

        # #region debug-point DWMSET:attr-result
        readback = ctypes.c_int(-1)
        dwmapi.DwmGetWindowAttribute(hwnd, attr, ctypes.byref(readback), ctypes.sizeof(readback))
        _debug_log("DWMSET", f"DwmSetWindowAttribute attr={attr} dark={dark} hwnd=0x{hwnd:X} hresult=0x{result & 0xFFFFFFFF:08X} readback={readback.value} build={build}",
                   {"attr": attr, "dark": dark, "hwnd": hwnd, "hresult": result & 0xFFFFFFFF,
                    "set_ok": result == 0, "readback": readback.value, "readback_match": readback.value == (1 if dark else 0), "build": build},
                   "titlebar.py:_apply_titlebar_theme_windows")
        # #endregion

        if result != 0:  # S_OK == 0
            logger.debug(
                "DwmSetWindowAttribute 返回非零 HRESULT: 0x%08X (attr=%d, dark=%s)",
                result & 0xFFFFFFFF, attr, dark,
            )
            return False

        # 触发标题栏重绘 + DwmFlush 强制 DWM 合成上屏（同步，约 17-25ms）
        _force_titlebar_redraw(hwnd)
        return True
    except Exception as exc:
        _debug_log("DWMSET", f"_apply_titlebar_theme_windows 异常: {exc}", {"error": str(exc)}, "titlebar.py")
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
