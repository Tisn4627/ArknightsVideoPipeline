"""FFmpeg 路径自定义功能单元测试

覆盖：
- PIPELINE_DEFAULTS 包含新配置键
- set_ffmpeg_config / _get_effective_ffmpeg_dir 路径解析逻辑
- ensure_ffmpeg_in_path 的 PATH 前置、幂等性、配置变更后重新应用
- ConfigProxy getter/setter 与 build_overrides
- SettingsPage FFmpeg 卡片的平台可见性（Windows 显示 / 非 Windows 隐藏）
- SettingsPage 信号发射
- 配置持久化（save/load 往返）
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock

import pytest
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.core import utils as utils_mod
from arknights_video_pipeline.core.config import PIPELINE_DEFAULTS
from arknights_video_pipeline.core.utils import (
    _get_effective_ffmpeg_dir,
    ensure_ffmpeg_in_path,
    set_ffmpeg_config,
)
from arknights_video_pipeline.gui.components.settings_page import SettingsPage
from arknights_video_pipeline.gui.theme import MaterialColors
from arknights_video_pipeline.service.config_proxy import ConfigProxy


# ── fixtures ───────────────────────────────────────────────


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen 模式）"""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def reset_ffmpeg_globals():
    """每个测试前重置 utils 模块的 FFmpeg 全局状态，避免测试间污染"""
    set_ffmpeg_config(False, "")
    yield
    set_ffmpeg_config(False, "")


@pytest.fixture
def preserve_path():
    """保存/恢复 os.environ["PATH"]，防止测试修改影响后续测试"""
    original = os.environ.get("PATH", "")
    yield
    os.environ["PATH"] = original


# ── 1. PIPELINE_DEFAULTS 包含新键 ─────────────────────────


class TestPipelineDefaults:
    def test_ffmpeg_keys_in_pipeline_defaults(self) -> None:
        assert "ffmpeg_custom_enabled" in PIPELINE_DEFAULTS
        assert "ffmpeg_path" in PIPELINE_DEFAULTS
        assert PIPELINE_DEFAULTS["ffmpeg_custom_enabled"] is False
        assert PIPELINE_DEFAULTS["ffmpeg_path"] == "resource/ffmpeg/bin"


# ── 2. set_ffmpeg_config / _get_effective_ffmpeg_dir ──────


class TestGetEffectiveFfmpegDir:
    def test_custom_enabled_returns_custom_dir(self) -> None:
        """启用自定义路径时，直接返回该路径作为目录"""
        set_ffmpeg_config(True, "/custom/ffmpeg/bin")
        result = _get_effective_ffmpeg_dir()
        assert result == os.path.normpath("/custom/ffmpeg/bin")

    def test_custom_enabled_relative_path_resolved(self) -> None:
        """相对路径以 PROJECT_ROOT 为基准解析"""
        set_ffmpeg_config(True, "resource/ffmpeg/bin")
        result = _get_effective_ffmpeg_dir()
        assert result == os.path.join(utils_mod.PROJECT_ROOT, "resource", "ffmpeg", "bin")

    def test_custom_disabled_returns_none(self) -> None:
        """关闭自定义路径时返回 None，使用系统 PATH"""
        set_ffmpeg_config(False, "resource/ffmpeg/bin")
        assert _get_effective_ffmpeg_dir() is None

    def test_custom_enabled_empty_path_returns_none(self) -> None:
        """custom_enabled=True 但 path 为空时返回 None"""
        set_ffmpeg_config(True, "")
        assert _get_effective_ffmpeg_dir() is None


# ── 3. ensure_ffmpeg_in_path ──────────────────────────────


class TestEnsureFfmpegInPath:
    def test_prepends_custom_dir(self, preserve_path) -> None:
        """启用自定义路径时，将其目录加入 PATH 最前面"""
        custom_dir = os.path.normpath("/custom/ffmpeg/bin")
        set_ffmpeg_config(True, "/custom/ffmpeg/bin")
        os.environ["PATH"] = "/system/bin"

        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("shutil.which", return_value="/fake/ffmpeg"):
            ensure_ffmpeg_in_path()

        assert os.environ["PATH"].startswith(custom_dir)

    def test_idempotent_no_duplicate(self, preserve_path) -> None:
        """连续调用两次不会重复追加同一目录"""
        custom_dir = os.path.normpath("/custom/ffmpeg/bin")
        set_ffmpeg_config(True, "/custom/ffmpeg/bin")
        os.environ["PATH"] = "/system/bin"

        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("shutil.which", return_value="/fake/ffmpeg"):
            ensure_ffmpeg_in_path()
            ensure_ffmpeg_in_path()

        path_parts = os.environ["PATH"].split(os.pathsep)
        assert path_parts.count(custom_dir) == 1

    def test_reapplies_after_config_change(self, preserve_path) -> None:
        """配置变更后重新应用新路径"""
        set_ffmpeg_config(True, "/path1/bin")
        os.environ["PATH"] = "/system/bin"

        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("shutil.which", return_value="/fake/ffmpeg"):
            ensure_ffmpeg_in_path()
            assert os.environ["PATH"].startswith(os.path.normpath("/path1"))

            set_ffmpeg_config(True, "/path2/bin")
            ensure_ffmpeg_in_path()
            assert os.environ["PATH"].startswith(os.path.normpath("/path2"))

    def test_skips_nonexistent_dir(self, preserve_path) -> None:
        """配置的目录不存在时不修改 PATH"""
        set_ffmpeg_config(True, "/nonexistent/bin")
        os.environ["PATH"] = "/system/bin"

        with mock.patch("os.path.isdir", return_value=False), \
             mock.patch("shutil.which", return_value="/fake/ffmpeg"):
            ensure_ffmpeg_in_path()

        # PATH 不应被修改（目录不存在）
        assert os.environ["PATH"] == "/system/bin"


# ── 4. ConfigProxy ────────────────────────────────────────


class TestConfigProxy:
    def test_ffmpeg_roundtrip(self, qapp, tmp_path) -> None:
        proxy = ConfigProxy(project_dir=str(tmp_path))
        proxy.set_ffmpeg_custom_enabled(True)
        proxy.set_ffmpeg_path("/custom/ffmpeg/bin")
        assert proxy.ffmpeg_custom_enabled() is True
        assert proxy.ffmpeg_path() == "/custom/ffmpeg/bin"

    def test_ffmpeg_defaults(self, qapp, tmp_path) -> None:
        proxy = ConfigProxy(project_dir=str(tmp_path))
        assert proxy.ffmpeg_custom_enabled() is False
        assert proxy.ffmpeg_path() == "resource/ffmpeg/bin"

    def test_build_overrides_includes_ffmpeg(self, qapp, tmp_path) -> None:
        proxy = ConfigProxy(project_dir=str(tmp_path))
        proxy.set_ffmpeg_custom_enabled(True)
        proxy.set_ffmpeg_path("/custom/ffmpeg/bin")
        overrides = proxy.build_overrides()
        assert "ffmpeg_custom_enabled" in overrides
        assert "ffmpeg_path" in overrides
        assert overrides["ffmpeg_custom_enabled"] is True

    def test_set_ffmpeg_custom_syncs_utils(self, qapp, tmp_path) -> None:
        """ConfigProxy setter 同步到 utils 模块全局"""
        proxy = ConfigProxy(project_dir=str(tmp_path))
        proxy.set_ffmpeg_path("/synced/ffmpeg/bin")
        proxy.set_ffmpeg_custom_enabled(True)
        assert utils_mod._FFMPEG_CUSTOM_ENABLED is True
        assert utils_mod._FFMPEG_CUSTOM_PATH == "/synced/ffmpeg/bin"

    def test_config_persistence(self, qapp, tmp_path) -> None:
        """save → load 往返保持 FFmpeg 配置"""
        proxy = ConfigProxy(project_dir=str(tmp_path))
        proxy.set_ffmpeg_custom_enabled(True)
        proxy.set_ffmpeg_path("/persisted/ffmpeg/bin")
        proxy.save()

        proxy2 = ConfigProxy(project_dir=str(tmp_path))
        assert proxy2.ffmpeg_custom_enabled() is True
        assert proxy2.ffmpeg_path() == "/persisted/ffmpeg/bin"


# ── 5. SettingsPage FFmpeg 卡片 ───────────────────────────


class TestSettingsPageFfmpegCard:
    def test_card_hidden_on_non_windows(self, qapp) -> None:
        """非 Windows 平台不构建 FFmpeg 卡片"""
        with mock.patch.object(sys, "platform", "linux"):
            page = SettingsPage(colors=MaterialColors.light(), is_dark=False)
        assert page._ffmpeg_card is None
        # setter 方法在非 Windows 上是 no-op
        page.set_ffmpeg_custom(True)
        page.set_ffmpeg_path("/test/ffmpeg.exe")
        page.set_ffmpeg_enabled(False)

    def test_card_shown_on_windows(self, qapp) -> None:
        """Windows 平台构建 FFmpeg 卡片，开关默认关闭、路径选择器禁用"""
        with mock.patch.object(sys, "platform", "win32"):
            page = SettingsPage(colors=MaterialColors.light(), is_dark=False)
        assert page._ffmpeg_card is not None
        assert page._ffmpeg_switch.is_checked() is False
        assert page._ffmpeg_selector.isEnabled() is False

    def test_ffmpeg_custom_signal(self, qapp) -> None:
        """切换开关发射 ffmpeg_custom_changed 信号"""
        with mock.patch.object(sys, "platform", "win32"):
            page = SettingsPage(colors=MaterialColors.light(), is_dark=False)

        received: list[bool] = []
        page.ffmpeg_custom_changed.connect(lambda v: received.append(v))
        page._ffmpeg_switch.set_checked(True)
        assert received == [True]
        # 开关启用后路径选择器应可用
        assert page._ffmpeg_selector.isEnabled() is True

    def test_ffmpeg_path_signal(self, qapp) -> None:
        """修改路径发射 ffmpeg_path_changed 信号"""
        with mock.patch.object(sys, "platform", "win32"):
            page = SettingsPage(colors=MaterialColors.light(), is_dark=False)
        received: list[str] = []
        page.ffmpeg_path_changed.connect(lambda v: received.append(v))
        page._ffmpeg_selector.set_path("/test/ffmpeg/bin")
        assert len(received) == 1
        assert received[0] == "/test/ffmpeg/bin"

    def test_set_ffmpeg_custom_enables_selector(self, qapp) -> None:
        """set_ffmpeg_custom(True) 后路径选择器可用"""
        with mock.patch.object(sys, "platform", "win32"):
            page = SettingsPage(colors=MaterialColors.light(), is_dark=False)
        page.set_ffmpeg_custom(True)
        assert page._ffmpeg_selector.isEnabled() is True
        page.set_ffmpeg_custom(False)
        assert page._ffmpeg_selector.isEnabled() is False

    def test_set_ffmpeg_enabled_disables_controls(self, qapp) -> None:
        """set_ffmpeg_enabled(False) 禁用开关和路径选择器（运行期间）"""
        with mock.patch.object(sys, "platform", "win32"):
            page = SettingsPage(colors=MaterialColors.light(), is_dark=False)
        page.set_ffmpeg_custom(True)
        assert page._ffmpeg_selector.isEnabled() is True
        page.set_ffmpeg_enabled(False)
        assert page._ffmpeg_switch.isEnabled() is False
        assert page._ffmpeg_selector.isEnabled() is False
