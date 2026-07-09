"""标题栏主题适配单元测试

通过 mock 验证跨平台分发逻辑与 Windows DWM 调用顺序，不依赖真实
窗口或显示器，可在任意环境（含无显示器的 CI）运行。
"""

from __future__ import annotations

import ctypes
import sys
from unittest import mock

import pytest

from arknights_video_pipeline.gui.theme import titlebar


# ── is_titlebar_theming_supported ─────────────────────────


class TestIsTitlebarThemingSupported:
    def test_windows_supported_build(self) -> None:
        gwv = mock.Mock(build=19044)
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(sys, "getwindowsversion", return_value=gwv, create=True):
            assert titlebar.is_titlebar_theming_supported() is True

    def test_windows_old_build_returns_false(self) -> None:
        gwv = mock.Mock(build=17000)
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(sys, "getwindowsversion", return_value=gwv, create=True):
            assert titlebar.is_titlebar_theming_supported() is False

    def test_macos_returns_true(self) -> None:
        with mock.patch.object(sys, "platform", "darwin"):
            assert titlebar.is_titlebar_theming_supported() is True

    def test_linux_returns_true(self) -> None:
        with mock.patch.object(sys, "platform", "linux"):
            assert titlebar.is_titlebar_theming_supported() is True

    def test_unsupported_platform_returns_false(self) -> None:
        with mock.patch.object(sys, "platform", "unknown"):
            assert titlebar.is_titlebar_theming_supported() is False


# ── apply_titlebar_theme 平台分发 ─────────────────────────


class TestApplyTitlebarThemeDispatch:
    def test_windows_dispatches_to_windows_impl(self) -> None:
        window = mock.Mock()
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(titlebar, "_apply_titlebar_theme_windows", return_value=True) as m:
            result = titlebar.apply_titlebar_theme(window, True)
        m.assert_called_once_with(window, True)
        assert result is True

    def test_macos_dispatches_to_qt_impl(self) -> None:
        window = mock.Mock()
        with mock.patch.object(sys, "platform", "darwin"), \
             mock.patch.object(titlebar, "_apply_titlebar_theme_qt", return_value=True) as m:
            result = titlebar.apply_titlebar_theme(window, False)
        m.assert_called_once_with(False)
        assert result is True

    def test_linux_dispatches_to_qt_impl(self) -> None:
        window = mock.Mock()
        with mock.patch.object(sys, "platform", "linux"), \
             mock.patch.object(titlebar, "_apply_titlebar_theme_qt", return_value=True) as m:
            result = titlebar.apply_titlebar_theme(window, True)
        m.assert_called_once_with(True)
        assert result is True

    def test_unsupported_platform_returns_false(self) -> None:
        with mock.patch.object(sys, "platform", "unknown"):
            assert titlebar.apply_titlebar_theme(mock.Mock(), True) is False


# ── _force_titlebar_redraw 回归测试（核心）─────────────────


class TestForceTitlebarRedrawDwmFlush:
    """回归测试：确保 cloak/decloak + DwmFlush 调用顺序正确

    历史 bug：
    1. DwmFlush 曾被误删，导致标题栏切换后不即时刷新
    2. 在 LTSC 2021 上仅 SetWindowPos + RedrawWindow + DwmFlush 不足以
       触发 DWM 重绘标题栏（DWM 缓存了标题栏位图），需 cloak/decloak
       强制 DWM 重建合成表面
    3. cloak 和 decloak 之间不能有 DwmFlush（否则窗口闪烁）
    此测试防止这些问题再次出现。
    """

    @pytest.fixture(autouse=True)
    def _reset_win32_cache(self) -> None:
        """每个测试前后重置 titlebar 模块级 Win32 API 缓存

        ``_get_win32_apis()`` 将 user32/dwmapi 句柄缓存于模块级变量，
        若不在测试间重置，后续测试会复用前一个测试的 mock，导致
        断言失效或 TypeError。
        """
        titlebar._user32 = None
        titlebar._dwmapi = None
        yield
        titlebar._user32 = None
        titlebar._dwmapi = None

    def test_cloak_decloak_flush_called_in_correct_order(self) -> None:
        """验证调用顺序：SetWindowPos → RedrawWindow → cloak → decloak → DwmFlush

        cloak 和 decloak 之间不得有 DwmFlush，否则 DWM 会将 cloaked
        （不可见）状态合成到屏幕，造成窗口闪烁。
        """
        call_order: list[str] = []

        fake_user32 = mock.MagicMock()
        fake_dwmapi = mock.MagicMock()
        fake_user32.SetWindowPos.side_effect = lambda *a, **kw: call_order.append("SetWindowPos")
        fake_user32.RedrawWindow.side_effect = lambda *a, **kw: call_order.append("RedrawWindow")
        fake_dwmapi.DwmSetWindowAttribute.side_effect = lambda *a, **kw: (call_order.append("DwmSetWindowAttribute"), 0)[1]
        fake_dwmapi.DwmFlush.side_effect = lambda *a, **kw: (call_order.append("DwmFlush"), 0)[1]

        def fake_windll(name: str) -> mock.MagicMock:
            if name == "user32":
                return fake_user32
            if name == "dwmapi":
                return fake_dwmapi
            return mock.MagicMock()

        with mock.patch.object(ctypes, "WinDLL", side_effect=fake_windll):
            titlebar._force_titlebar_redraw(12345)

        assert call_order == [
            "SetWindowPos", "RedrawWindow",
            "DwmSetWindowAttribute", "DwmSetWindowAttribute",
            "DwmFlush",
        ], f"调用顺序错误: {call_order}"

    def test_dwmsetwindowattribute_called_twice_for_cloak_and_decloak(self) -> None:
        """cloak (val=1) 和 decloak (val=0) 各调用一次 DwmSetWindowAttribute"""
        fake_user32 = mock.MagicMock()
        fake_dwmapi = mock.MagicMock()
        fake_dwmapi.DwmFlush.return_value = 0

        attr_values: list[int] = []

        def capture_attr(hwnd, attr, value_ptr, cb):
            import ctypes
            attr_values.append(ctypes.cast(value_ptr, ctypes.POINTER(ctypes.c_int))[0])
            return 0

        fake_dwmapi.DwmSetWindowAttribute.side_effect = capture_attr

        def fake_windll(name: str) -> mock.MagicMock:
            if name == "user32":
                return fake_user32
            if name == "dwmapi":
                return fake_dwmapi
            return mock.MagicMock()

        with mock.patch.object(ctypes, "WinDLL", side_effect=fake_windll):
            titlebar._force_titlebar_redraw(12345)

        assert attr_values == [1, 0], f"cloak/decloak 值错误: {attr_values}"

    def test_dwmflush_nonzero_result_does_not_raise(self) -> None:
        """DwmFlush 返回非零 HRESULT 时不应抛异常"""
        parent = mock.MagicMock()
        parent.dwmapi.DwmFlush.return_value = -1  # 非 S_OK
        parent.dwmapi.DwmSetWindowAttribute.return_value = 0  # S_OK

        def fake_windll(name: str) -> mock.MagicMock:
            if name == "user32":
                return parent.user32
            if name == "dwmapi":
                return parent.dwmapi
            return mock.MagicMock()

        with mock.patch.object(ctypes, "WinDLL", side_effect=fake_windll):
            # 不应抛异常
            titlebar._force_titlebar_redraw(12345)

        parent.dwmapi.DwmFlush.assert_called_once()


# ── _apply_titlebar_theme_qt ──────────────────────────────


class TestApplyTitlebarThemeQt:
    def test_sets_dark_color_scheme(self) -> None:
        fake_app = mock.MagicMock()
        with mock.patch("PyQt6.QtWidgets.QApplication") as MockQApp:
            MockQApp.instance.return_value = fake_app
            result = titlebar._apply_titlebar_theme_qt(True)
        assert result is True
        from PyQt6.QtCore import Qt
        fake_app.styleHints().setColorScheme.assert_called_once_with(
            Qt.ColorScheme.Dark
        )

    def test_sets_light_color_scheme(self) -> None:
        fake_app = mock.MagicMock()
        with mock.patch("PyQt6.QtWidgets.QApplication") as MockQApp:
            MockQApp.instance.return_value = fake_app
            result = titlebar._apply_titlebar_theme_qt(False)
        assert result is True
        from PyQt6.QtCore import Qt
        fake_app.styleHints().setColorScheme.assert_called_once_with(
            Qt.ColorScheme.Light
        )

    def test_no_app_returns_false(self) -> None:
        with mock.patch("PyQt6.QtWidgets.QApplication") as MockQApp:
            MockQApp.instance.return_value = None
            result = titlebar._apply_titlebar_theme_qt(True)
        assert result is False
