"""
gui.i18n.manager - 国际化管理器

加载 JSON 语言资源文件，提供 ``tr()`` 翻译与 ``language_changed`` 信号驱动的
即时重翻译（无需重启）。与 ``core`` / ``service`` 完全解耦，仅服务 GUI 层。

设计：
- 语言文件位于 ``resource/locales/<code>.json``（扁平 key→text 映射）
- 缺失 key 时回退到默认语言 zh-CN，再回退到 ``default`` / key 本身
- 加载失败（文件缺失/JSON 损坏）记录 warning 并保持当前状态，界面不崩
- 单例（``init_i18n`` / ``i18n`` / ``tr``）供 widget 连接信号；测试可注入临时目录
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import QObject, pyqtSignal

from arknights_video_pipeline.core.utils import PROJECT_ROOT

logger = logging.getLogger(__name__)

_DEFAULT_LOCALES_DIR = os.path.join(PROJECT_ROOT, "resource", "locales")


class I18n(QObject):
    """国际化管理器

    Signals:
        language_changed(): 当前语言切换后发出，widget 连接此信号在回调中重设文本
    """

    language_changed = pyqtSignal()

    DEFAULT_LANGUAGE = "zh-CN"
    SUPPORTED_LANGUAGES = ("zh-CN", "en-US")
    _DISPLAY_NAMES = {
        "zh-CN": "中文（简体）",
        "en-US": "English (US)",
    }

    def __init__(self, locales_dir: str | None = None,
                 language: str | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._locales_dir = locales_dir or _DEFAULT_LOCALES_DIR
        # 始终加载默认语言作为兜底字典（即使当前语言是 en-US，key 缺失时回退到中文）
        self._fallback: dict[str, str] = self._load_file(self.DEFAULT_LANGUAGE)
        self._translations: dict[str, str] = dict(self._fallback)
        self._language: str = self.DEFAULT_LANGUAGE
        # 构造期静默切换到指定语言（不发信号，widget 尚未连接）
        want = language or self.DEFAULT_LANGUAGE
        if want != self.DEFAULT_LANGUAGE:
            data = self._load_file(want)
            if data:
                self._language = want
                self._translations = data
            else:
                logger.warning("初始语言 %s 加载失败，回退到默认 %s",
                               want, self.DEFAULT_LANGUAGE)

    # ── 文件 I/O ──────────────────────────────────────────

    def _load_file(self, lang: str) -> dict[str, str]:
        """加载单个语言文件，失败返回空字典并记录 warning"""
        path = os.path.join(self._locales_dir, f"{lang}.json")
        if not os.path.exists(path):
            logger.warning("语言文件不存在: %s", path)
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("语言文件加载失败 (%s): %s", path, exc)
            return {}
        if not isinstance(data, dict):
            logger.warning("语言文件格式非法（期望对象）: %s", path)
            return {}
        return {str(k): str(v) for k, v in data.items()}

    # ── 公开 API ──────────────────────────────────────────

    def language(self) -> str:
        """当前语言码"""
        return self._language

    def load_language(self, lang: str) -> bool:
        """加载指定语言到当前翻译字典。

        成功返回 True；失败（不支持/文件缺失/损坏）返回 False 且保持当前字典不变。
        不发 ``language_changed`` 信号（如需通知请用 ``set_language``）。
        """
        if lang not in self.SUPPORTED_LANGUAGES:
            logger.warning("不支持的语言码: %s", lang)
            return False
        data = self._load_file(lang)
        if not data:
            return False
        self._translations = data
        return True

    def set_language(self, lang: str) -> bool:
        """切换当前语言。

        成功加载且语言确实变更时发出 ``language_changed`` 信号并返回 True；
        与当前语言相同返回 True（无操作）；加载失败或不支持返回 False 且不切换、不发信号。
        """
        if lang not in self.SUPPORTED_LANGUAGES:
            logger.warning("不支持的语言码: %s", lang)
            return False
        if lang == self._language:
            return True
        data = self._load_file(lang)
        if not data:
            logger.warning("语言 %s 加载失败，保持当前语言 %s", lang, self._language)
            return False
        self._language = lang
        self._translations = data
        # 仅当本实例是全局单例时记录语言码，供单例重建时恢复当前语言
        # （见 i18n()；测试中的独立实例不应污染模块级状态）
        if self is _instance:
            global _current_language
            _current_language = lang
        self.language_changed.emit()
        return True

    def tr(self, key: str, default: str | None = None,
           **kwargs: Any) -> str:
        """翻译 key。

        查找顺序：当前语言 → 默认语言 zh-CN → ``default`` → key 本身。
        支持 ``{name}`` 占位符（``str.format``）；格式化失败时返回未格式化文本。
        """
        text = self._translations.get(key)
        if text is None:
            text = self._fallback.get(key)
        if text is None:
            text = default if default is not None else key
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                pass
        return text

    def available_languages(self) -> list[tuple[str, str]]:
        """返回 ``[(code, 显示名)]`` 供语言选择下拉框使用"""
        return [(code, self._DISPLAY_NAMES.get(code, code))
                for code in self.SUPPORTED_LANGUAGES]

    def reload(self) -> None:
        """从磁盘重新加载默认语言与当前语言，并发出 ``language_changed`` 信号"""
        # 与 load_language 相同的守卫：加载失败（空字典）时保留旧 _fallback，
        # 避免磁盘文件暂时不可读时把回退翻译清空
        fallback = self._load_file(self.DEFAULT_LANGUAGE)
        if fallback:
            self._fallback = fallback
        self.load_language(self._language)
        self.language_changed.emit()


# ── 单例 ────────────────────────────────────────────────

_instance: I18n | None = None
# 最近一次生效的语言码：单例因底层 C++ 对象被销毁而重建时用于恢复当前
# 语言，避免界面语言意外回落到默认 zh-CN。仅由全局单例自身维护
# （init_i18n / I18n.set_language 中 ``self is _instance`` 时更新），
# 测试中创建的独立 I18n 实例不会污染该值。
_current_language: str | None = None


def init_i18n(locales_dir: str | None = None, language: str | None = None,
              parent: QObject | None = None) -> I18n:
    """创建并设置全局 i18n 单例。

    应在 ``MainWindow`` 构建 widget 之前调用，使 widget 可连接 ``language_changed``。
    """
    global _instance, _current_language
    _instance = I18n(locales_dir=locales_dir, language=language, parent=parent)
    _current_language = _instance.language()
    return _instance


def i18n() -> I18n:
    """获取全局 i18n 单例（未初始化或底层 C++ 对象已被销毁时重建）"""
    global _instance
    if _instance is None or sip.isdeleted(_instance):
        _instance = I18n()
        # 重建单例后恢复最近一次生效的语言，避免回落到默认 zh-CN
        if _current_language is not None:
            _instance.set_language(_current_language)
    return _instance


def tr(key: str, default: str | None = None, **kwargs: Any) -> str:
    """便捷翻译函数：等价 ``i18n().tr(key, default, **kwargs)``"""
    return i18n().tr(key, default=default, **kwargs)
