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
    """回归测试：确保 DwmFlush 被调用且顺序正确

    历史 bug：DwmFlush 曾被误删，导致标题栏切换后不即时刷新，需晃动
    窗口才更新。此测试防止该问题再次出现。
    """

    def test_dwmflush_called_after_setwindowpos_and_redrawwindow(self) -> None:
        call_order: list[str] = []

        fake_user32 = mock.MagicMock()
        fake_dwmapi = mock.MagicMock()
        fake_user32.SetWindowPos.side_effect = lambda *a, **kw: call_order.append("SetWindowPos")
        fake_user32.RedrawWindow.side_effect = lambda *a, **kw: call_order.append("RedrawWindow")
        fake_dwmapi.DwmFlush.side_effect = lambda *a, **kw: (call_order.append("DwmFlush"), 0)[1]

        def fake_windll(name: str) -> mock.MagicMock:
            if name == "user32":
                return fake_user32
            if name == "dwmapi":
                return fake_dwmapi
            return mock.MagicMock()

        with mock.patch.object(ctypes, "WinDLL", side_effect=fake_windll):
            titlebar._force_titlebar_redraw(12345)

        # 三个关键调用都必须发生，且顺序为 SetWindowPos -> RedrawWindow -> DwmFlush
        assert call_order == ["SetWindowPos", "RedrawWindow", "DwmFlush"], (
            f"调用顺序错误: {call_order}"
        )

    def test_dwmflush_nonzero_result_does_not_raise(self) -> None:
        """DwmFlush 返回非零 HRESULT 时不应抛异常（仅记录 debug 日志）"""
        parent = mock.MagicMock()
        parent.dwmapi.DwmFlush.return_value = -1  # 非 S_OK

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
