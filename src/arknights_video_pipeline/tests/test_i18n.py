"""i18n 语言切换功能单元测试

覆盖 gui/i18n/manager.py 的 I18n 管理器、gui/theme/gui_config.py 的语言持久化、
resource/locales/ 下两个 locale 文件的 key 对等性、以及 SettingsPage 语言下拉框集成。

测试分组：
1. TestI18nCore — I18n 核心功能（加载、切换、信号、回退、占位符）
2. TestI18nExceptionHandling — 异常处理（文件缺失、JSON 损坏、非 dict）
3. TestGuiConfigPersistence — GuiConfig 语言持久化与回退
4. TestGuiConfigSetProtection — set() 对受保护键抛 ValueError
5. TestKeyParity — zh-CN.json 与 en-US.json key 对等性
6. TestSingleton — i18n 单例行为
7. TestSettingsPageIntegration — SettingsPage 语言下拉框集成

所有 Qt 测试在 offscreen 模式下运行，不依赖真实显示器。
I18n / GuiConfig 测试通过临时目录隔离，绝不污染真实 resource/locales/ 或 config/gui.json。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.core.utils import PROJECT_ROOT
from arknights_video_pipeline.gui.i18n import I18n, init_i18n, i18n
from arknights_video_pipeline.gui.i18n import manager as i18n_manager
from arknights_video_pipeline.gui.theme.gui_config import GuiConfig


# ── fixtures ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _restore_i18n_singleton():
    """每个测试前后保存/恢复 i18n 单例，避免测试间互相污染"""
    original = i18n_manager._instance
    yield
    i18n_manager._instance = original


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen 模式）"""
    app = QApplication.instance() or QApplication([])
    yield app


def _write_locale(tmp_path: Path, code: str, data: dict) -> None:
    """在 tmp_path 下写入语言文件 <code>.json"""
    (tmp_path / f"{code}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── TestI18nCore ──────────────────────────────────────────


class TestI18nCore:
    """I18n 核心功能：加载、切换、信号、回退链、占位符格式化"""

    def test_default_language_is_zh_cn(self) -> None:
        """无参数构造时默认语言为 zh-CN，tr 返回中文"""
        inst = I18n()
        assert inst.language() == "zh-CN"
        assert inst.tr("nav.home") == "主页"

    def test_init_with_en_us(self) -> None:
        """指定 en-US 构造时语言为 en-US，tr 返回英文"""
        inst = I18n(language="en-US")
        assert inst.language() == "en-US"
        assert inst.tr("nav.home") == "Home"

    def test_set_language_emits_signal(self) -> None:
        """set_language 成功切换时发射 language_changed 信号一次"""
        inst = I18n()  # 默认 zh-CN
        emitted: list = []
        inst.language_changed.connect(lambda: emitted.append(True))
        assert inst.set_language("en-US") is True
        assert len(emitted) == 1

    def test_set_language_same_returns_true_no_signal(self) -> None:
        """set_language 与当前语言相同时返回 True 但不发信号"""
        inst = I18n()  # 默认 zh-CN
        emitted: list = []
        inst.language_changed.connect(lambda: emitted.append(True))
        assert inst.set_language("zh-CN") is True
        assert len(emitted) == 0

    def test_set_language_unsupported_returns_false(self) -> None:
        """set_language 不支持的语言码返回 False，不发信号，语言不变"""
        inst = I18n()
        emitted: list = []
        inst.language_changed.connect(lambda: emitted.append(True))
        assert inst.set_language("fr-FR") is False
        assert inst.language() == "zh-CN"
        assert len(emitted) == 0

    def test_tr_fallback_to_default_language(self, tmp_path: Path) -> None:
        """当前语言缺失 key 时回退到默认语言 zh-CN"""
        _write_locale(tmp_path, "zh-CN", {"only.zh": "中文值", "common": "中文"})
        _write_locale(tmp_path, "en-US", {"common": "English"})  # 缺 only.zh
        inst = I18n(locales_dir=str(tmp_path), language="en-US")
        assert inst.tr("only.zh") == "中文值"

    def test_tr_fallback_to_default_param(self, tmp_path: Path) -> None:
        """key 在当前语言与默认语言均缺失时返回 default 参数"""
        _write_locale(tmp_path, "zh-CN", {"a": "b"})
        _write_locale(tmp_path, "en-US", {"a": "c"})
        inst = I18n(locales_dir=str(tmp_path), language="en-US")
        assert inst.tr("nonexistent", default="FALLBACK") == "FALLBACK"

    def test_tr_fallback_to_key_itself(self, tmp_path: Path) -> None:
        """key 全部缺失且无 default 时返回 key 本身"""
        _write_locale(tmp_path, "zh-CN", {"a": "b"})
        inst = I18n(locales_dir=str(tmp_path))
        assert inst.tr("nonexistent") == "nonexistent"

    def test_tr_placeholder_formatting(self) -> None:
        """tr 支持 {placeholder} 占位符格式化"""
        inst = I18n()  # 真实 locale 文件
        result = inst.tr("settings.config.status_generated", n=3)
        assert "3" in result
        assert "已生成" in result

    def test_tr_placeholder_missing_kwarg_returns_unformatted(
        self, tmp_path: Path
    ) -> None:
        """占位符缺少对应 kwarg 时返回未格式化原文（不抛异常）"""
        _write_locale(tmp_path, "zh-CN", {"greeting": "Hello {name}!"})
        inst = I18n(locales_dir=str(tmp_path))
        # 缺少 name kwarg → KeyError 被捕获 → 返回原文
        assert inst.tr("greeting") == "Hello {name}!"

    def test_available_languages(self) -> None:
        """available_languages 返回 [(code, 显示名)] 列表"""
        inst = I18n()
        langs = inst.available_languages()
        assert ("zh-CN", "中文（简体）") in langs
        assert ("en-US", "English (US)") in langs
        assert len(langs) == 2

    def test_load_language_returns_false_for_missing_file(
        self, tmp_path: Path
    ) -> None:
        """load_language 对不存在的语言文件返回 False，当前字典不变"""
        _write_locale(tmp_path, "zh-CN", {"a": "b"})  # 仅 zh-CN 存在
        inst = I18n(locales_dir=str(tmp_path))
        assert inst.load_language("en-US") is False
        # 当前字典不变（仍为 zh-CN 内容）
        assert inst.tr("a") == "b"


# ── TestI18nExceptionHandling ────────────────────────────


class TestI18nExceptionHandling:
    """异常处理：文件缺失、JSON 损坏、非 dict JSON — 均不抛异常"""

    def test_missing_file_falls_back_to_default(self, tmp_path: Path) -> None:
        """en-US.json 不存在时构造 I18n(language=en-US) 回退到 zh-CN"""
        _write_locale(tmp_path, "zh-CN", {"key": "中文"})
        # 不创建 en-US.json
        inst = I18n(locales_dir=str(tmp_path), language="en-US")
        assert inst.language() == "zh-CN"  # 回退到默认
        assert inst.tr("key") == "中文"

    def test_corrupt_json_returns_false(self, tmp_path: Path) -> None:
        """JSON 损坏时 load_language 返回 False 不抛异常"""
        _write_locale(tmp_path, "zh-CN", {"key": "中文"})
        (tmp_path / "en-US.json").write_text("{invalid json", encoding="utf-8")
        inst = I18n(locales_dir=str(tmp_path))
        assert inst.load_language("en-US") is False
        assert inst.language() == "zh-CN"

    def test_non_dict_json_returns_false(self, tmp_path: Path) -> None:
        """合法 JSON 但非 dict（如数组）时 load_language 返回 False"""
        _write_locale(tmp_path, "zh-CN", {"key": "中文"})
        (tmp_path / "en-US.json").write_text("[1, 2, 3]", encoding="utf-8")
        inst = I18n(locales_dir=str(tmp_path))
        assert inst.load_language("en-US") is False

    def test_set_language_failure_keeps_current(self, tmp_path: Path) -> None:
        """set_language 加载失败时保持当前语言且不发信号"""
        _write_locale(tmp_path, "zh-CN", {"key": "中文"})
        (tmp_path / "en-US.json").write_text("corrupted", encoding="utf-8")
        inst = I18n(locales_dir=str(tmp_path))
        emitted: list = []
        inst.language_changed.connect(lambda: emitted.append(True))
        assert inst.set_language("en-US") is False
        assert inst.language() == "zh-CN"
        assert len(emitted) == 0


# ── TestGuiConfigPersistence ─────────────────────────────


class TestGuiConfigPersistence:
    """GuiConfig 语言持久化（使用 config_dir=tmp_path 隔离）"""

    def test_default_language_is_zh_cn(self, tmp_path: Path) -> None:
        """新 GuiConfig（空 config_dir）默认语言为 zh-CN"""
        gc = GuiConfig(config_dir=str(tmp_path))
        assert gc.language() == "zh-CN"

    def test_set_language_persists_and_reloads(self, tmp_path: Path) -> None:
        """set_language 持久化后重新构造 GuiConfig 仍能读到"""
        gc = GuiConfig(config_dir=str(tmp_path))
        gc.set_language("en-US")
        # 重新加载（从磁盘读取 gui.json）
        gc2 = GuiConfig(config_dir=str(tmp_path))
        assert gc2.language() == "en-US"

    def test_invalid_language_falls_back(self, tmp_path: Path) -> None:
        """gui.json 含非法语言码时回退到 zh-CN"""
        (tmp_path / "gui.json").write_text(
            json.dumps({"language": "fr-FR"}), encoding="utf-8"
        )
        gc = GuiConfig(config_dir=str(tmp_path))
        assert gc.language() == "zh-CN"


# ── TestGuiConfigSetProtection ───────────────────────────


class TestGuiConfigSetProtection:
    """GuiConfig.set() 对受保护键（language/theme）抛 ValueError"""

    def test_set_language_key_raises(self, tmp_path: Path) -> None:
        """set('language', ...) 抛 ValueError，必须用 set_language()"""
        gc = GuiConfig(config_dir=str(tmp_path))
        with pytest.raises(ValueError):
            gc.set("language", "en-US")

    def test_set_theme_key_raises(self, tmp_path: Path) -> None:
        """set('theme', ...) 抛 ValueError，必须用 set_theme()"""
        gc = GuiConfig(config_dir=str(tmp_path))
        with pytest.raises(ValueError):
            gc.set("theme", "dark")


# ── TestKeyParity ────────────────────────────────────────


class TestKeyParity:
    """两个 locale 文件的 key 对等性（使用真实 resource/locales/）"""

    def test_zh_cn_and_en_us_have_identical_keys(self) -> None:
        """zh-CN.json 与 en-US.json 的 key 集合完全一致且非空"""
        locales_dir = os.path.join(PROJECT_ROOT, "resource", "locales")
        with open(os.path.join(locales_dir, "zh-CN.json"), encoding="utf-8") as f:
            zh = json.load(f)
        with open(os.path.join(locales_dir, "en-US.json"), encoding="utf-8") as f:
            en = json.load(f)
        zh_keys = set(zh.keys())
        en_keys = set(en.keys())
        assert zh_keys == en_keys, (
            f"Key 不对等: 仅中文 {zh_keys - en_keys}; 仅英文 {en_keys - zh_keys}"
        )
        assert len(zh_keys) > 0, "locale 文件不应为空"


# ── TestSingleton ────────────────────────────────────────


class TestSingleton:
    """i18n 单例行为"""

    def test_init_i18n_replaces_instance(self) -> None:
        """init_i18n 创建新单例，i18n() 返回同一对象；再次调用替换旧实例"""
        inst = init_i18n()
        assert i18n() is inst
        inst2 = init_i18n()
        assert i18n() is inst2
        assert inst is not inst2  # 新实例替换旧实例

    def test_i18n_creates_default_when_not_initialized(self) -> None:
        """_instance 为 None 时 i18n() 自动创建默认实例"""
        i18n_manager._instance = None
        inst = i18n()
        assert inst is not None
        assert inst.language() == "zh-CN"


# ── TestSettingsPageIntegration ──────────────────────────


class TestSettingsPageIntegration:
    """SettingsPage 语言下拉框集成（需 QApplication offscreen 模式）"""

    def test_language_combo_has_both_languages(self, qapp) -> None:
        """下拉框包含 zh-CN 与 en-US 两个选项，itemData 为语言码"""
        init_i18n()
        from arknights_video_pipeline.gui.components.settings_page import SettingsPage

        sp = SettingsPage()
        assert sp._lang_combo.count() == 2
        assert sp._lang_combo.itemData(0) == "zh-CN"
        assert sp._lang_combo.itemData(1) == "en-US"

    def test_set_language_updates_combo_without_emitting(self, qapp) -> None:
        """set_language 阻塞信号更新下拉框，不发射 language_change_requested"""
        init_i18n()
        from arknights_video_pipeline.gui.components.settings_page import SettingsPage

        sp = SettingsPage()
        emitted: list = []
        sp.language_change_requested.connect(lambda code: emitted.append(code))
        sp.set_language("en-US")
        # 下拉框已切换到 en-US
        assert sp._lang_combo.currentData() == "en-US"
        # 但信号未被发射（阻塞信号）
        assert len(emitted) == 0

    def test_combo_change_emits_signal(self, qapp) -> None:
        """程序化切换下拉框（不阻塞信号）发射 language_change_requested"""
        init_i18n()
        from arknights_video_pipeline.gui.components.settings_page import SettingsPage

        sp = SettingsPage()
        emitted: list = []
        sp.language_change_requested.connect(lambda code: emitted.append(code))
        # 程序化切换到 en-US（不阻塞信号 → 触发 _on_language_changed）
        en_idx = sp._lang_combo.findData("en-US")
        sp._lang_combo.setCurrentIndex(en_idx)
        assert emitted == ["en-US"]
