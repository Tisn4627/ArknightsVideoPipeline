"""应用图标与 Windows 任务栏标识单元测试

验证 ``load_app_icon`` 多尺寸加载与 ``apply_windows_taskbar_identity``
跨平台分发逻辑，不依赖真实窗口，可在任意环境（含无显示器 CI）运行。
"""

from __future__ import annotations

import ctypes
import sys
from unittest import mock

import pytest
from PyQt6.QtWidgets import QApplication

from PyQt6.QtGui import QIcon

from arknights_video_pipeline.gui.assets import app_icon


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen 模式）

    QPixmap/QIcon 创建依赖 QGuiApplication，无实例时会触发底层崩溃
    （STATUS_STACK_BUFFER_OVERRUN），故需在调用 load_app_icon 前确保实例存在。
    """
    app = QApplication.instance() or QApplication([])
    yield app


# ── load_app_icon / app_icon_path ─────────────────────────


class TestLoadAppIcon:
    def test_icon_path_points_to_assets(self) -> None:
        path = app_icon.app_icon_path()
        assert path.name == "app_icon.png"
        assert path.parent.name == "assets"

    def test_load_returns_nonnull_icon_with_multiple_sizes(self, qapp) -> None:
        icon = app_icon.load_app_icon()
        assert not icon.isNull()
        sizes = [s.width() for s in icon.availableSizes()]
        # 预期覆盖常见显示位置尺寸集合
        for expected in (16, 24, 32, 48, 64, 128, 256):
            assert expected in sizes, f"缺少尺寸 {expected}: {sizes}"

    def test_load_returns_empty_icon_when_file_missing(self, qapp, tmp_path) -> None:
        original = app_icon._ICON_PATH
        app_icon._ICON_PATH = tmp_path / "nonexistent.png"
        try:
            icon = app_icon.load_app_icon()
            assert icon.isNull()
        finally:
            app_icon._ICON_PATH = original

    def test_load_returns_empty_icon_when_decode_fails(self, qapp, tmp_path) -> None:
        # 写入无效 PNG 字节，QPixmap 解码失败
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not a png")
        original = app_icon._ICON_PATH
        app_icon._ICON_PATH = bad
        try:
            icon = app_icon.load_app_icon()
            assert icon.isNull()
        finally:
            app_icon._ICON_PATH = original


# ── apply_windows_taskbar_identity ─────────────────────────


class TestApplyWindowsTaskbarIdentity:
    def test_non_windows_skips_silently(self) -> None:
        with mock.patch.object(sys, "platform", "linux"):
            assert app_icon.apply_windows_taskbar_identity() is True
        with mock.patch.object(sys, "platform", "darwin"):
            assert app_icon.apply_windows_taskbar_identity() is True

    def test_windows_calls_set_appusermodelid_with_default_id(self) -> None:
        fake_shell32 = mock.MagicMock()
        fake_shell32.SetCurrentProcessExplicitAppUserModelID.return_value = 0

        def fake_windll(name: str):
            assert name == "shell32", f"应加载 shell32，实际: {name}"
            return fake_shell32

        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(ctypes, "WinDLL", side_effect=fake_windll):
            result = app_icon.apply_windows_taskbar_identity()

        assert result is True
        fake_shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(
            "AVP.ArknightsVideoPipeline"
        )

    def test_windows_custom_app_id_forwarded(self) -> None:
        fake_shell32 = mock.MagicMock()
        fake_shell32.SetCurrentProcessExplicitAppUserModelID.return_value = 0

        def fake_windll(name: str):
            return fake_shell32

        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(ctypes, "WinDLL", side_effect=fake_windll):
            app_icon.apply_windows_taskbar_identity("Custom.App.Id")

        fake_shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(
            "Custom.App.Id"
        )

    def test_windows_nonzero_hresult_returns_false(self) -> None:
        fake_shell32 = mock.MagicMock()
        # 非 S_OK（如 E_INVALIDARG）
        fake_shell32.SetCurrentProcessExplicitAppUserModelID.return_value = -1

        def fake_windll(name: str):
            return fake_shell32

        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(ctypes, "WinDLL", side_effect=fake_windll):
            result = app_icon.apply_windows_taskbar_identity()

        assert result is False

    def test_windows_windll_exception_returns_false(self) -> None:
        def fake_windll(name: str):
            raise OSError("shell32 unavailable")

        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(ctypes, "WinDLL", side_effect=fake_windll):
            # 不应抛异常
            result = app_icon.apply_windows_taskbar_identity()

        assert result is False
