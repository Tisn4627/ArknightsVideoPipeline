"""
gui.theme.gui_config - GUI 独立配置管理

与流水线配置（pipeline.json）完全解耦，单独管理 GUI 运行时偏好，
如主题选择、窗口位置等。配置文件位于 ``config/gui.json``。

设计原则：
- 与 ``ConfigManager`` / ``ConfigProxy`` 无任何依赖关系
- 配置持久化独立写盘，不受 ``save_pipeline_config`` 影响
- 变更即时持久化（``_trigger_save``）；UI 层刷新由调用方驱动，
  不再提供变更信号（历史信号无任何连接方，已移除）
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from PyQt6.QtCore import QObject

from arknights_video_pipeline.core.utils import PROJECT_ROOT

logger = logging.getLogger(__name__)

# 支持的语言码（与 gui.i18n.I18n.SUPPORTED_LANGUAGES 保持一致）
_SUPPORTED_LANGUAGES = ("zh-CN", "en-US")
_DEFAULT_LANGUAGE = "zh-CN"

# 默认 GUI 配置（config/gui.json 缺失时使用）
_GUI_DEFAULTS: dict[str, Any] = {
    "theme": "light",
    "advanced_expanded": False,
    "language": _DEFAULT_LANGUAGE,
}


class GuiConfig(QObject):
    """GUI 独立配置管理器

    管理 ``config/gui.json`` 的加载、读写与持久化。
    实例化时自动加载磁盘配置，写入可调用 ``save()`` 持久化。

    说明：历史版本曾提供 ``theme_changed`` / ``language_changed`` /
    ``config_changed`` 信号，全仓库无任何连接方，已移除；UI 层刷新
    由调用方（MainWindow）自行驱动。
    """

    def __init__(
        self,
        config_dir: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_dir = config_dir or os.path.join(PROJECT_ROOT, "config")
        self._config_path = os.path.join(self._config_dir, "gui.json")
        self._data: dict[str, Any] = dict(_GUI_DEFAULTS)
        self._load()

    # ── 内部 I/O ───────────────────────────────────────────

    def _load(self) -> None:
        """从 ``config/gui.json`` 加载配置（文件不存在时使用默认值）"""
        if not os.path.exists(self._config_path):
            self._data = dict(_GUI_DEFAULTS)
            return
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                user = json.load(f)
            if isinstance(user, dict):
                # 以默认值为基础，用户配置覆盖（保留未知字段供扩展）
                merged = dict(_GUI_DEFAULTS)
                merged.update(user)
                self._data = merged
            else:
                self._data = dict(_GUI_DEFAULTS)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("GUI 配置文件读取失败 (%s)，使用默认值: %s", self._config_path, exc)
            self._data = dict(_GUI_DEFAULTS)

    def save(self) -> None:
        """持久化当前配置到 ``config/gui.json``"""
        os.makedirs(self._config_dir, exist_ok=True)
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=4, ensure_ascii=False)
        except OSError as exc:
            logger.error("GUI 配置文件写入失败 (%s): %s", self._config_path, exc)

    def reload(self) -> None:
        """从磁盘重新加载配置（配置重置后同步内存状态）

        仅同步内存数据，不做任何通知；调用方需自行检查
        ``theme()`` / ``is_advanced_expanded()`` / ``language()`` 并刷新 UI。
        """
        self._load()

    def _trigger_save(self) -> None:
        """触发配置持久化（当前为同步写入，可扩展为防抖）"""
        self.save()

    # ── 主题 ───────────────────────────────────────────────

    def theme(self) -> str:
        """获取当前主题名称，返回 ``"light"`` 或 ``"dark"``"""
        t = self._data.get("theme", "light")
        return t if t in ("light", "dark") else "light"

    def set_theme(self, theme: str) -> None:
        """设置主题并持久化（与 ``set_language`` 行为一致）

        Args:
            theme: ``"light"`` 或 ``"dark"``

        Raises:
            ValueError: theme 不是合法值
        """
        if theme not in ("light", "dark"):
            raise ValueError(f"非法的主题名称: {theme!r}，仅允许 'light' 或 'dark'")
        if self._data.get("theme") != theme:
            self._data["theme"] = theme
            self._trigger_save()

    def is_dark_theme(self) -> bool:
        """便捷方法：当前主题是否为深色"""
        return self.theme() == "dark"

    # ── 语言 ───────────────────────────────────────────────

    def language(self) -> str:
        """获取当前语言码，返回 ``"zh-CN"`` 或 ``"en-US"``。

        非法值回退到默认 ``"zh-CN"``。
        """
        lang = self._data.get("language", _DEFAULT_LANGUAGE)
        return lang if lang in _SUPPORTED_LANGUAGES else _DEFAULT_LANGUAGE

    def set_language(self, language: str) -> None:
        """设置语言并持久化

        Args:
            language: ``"zh-CN"`` 或 ``"en-US"``

        非法值将被忽略并记录 warning（不抛异常，避免 UI 回调崩溃）。
        """
        if language not in _SUPPORTED_LANGUAGES:
            logger.warning("非法的语言码: %r，仅允许 %s", language, _SUPPORTED_LANGUAGES)
            return
        if self._data.get("language") != language:
            self._data["language"] = language
            self._trigger_save()

    # ── 高级分区折叠状态 ─────────────────────────────────

    def is_advanced_expanded(self) -> bool:
        """高级分区是否展开"""
        return bool(self._data.get("advanced_expanded", False))

    def set_advanced_expanded(self, expanded: bool) -> None:
        """设置高级分区展开/收起状态并持久化"""
        self._data["advanced_expanded"] = bool(expanded)
        self._trigger_save()

    # ── 通用访问（供后续扩展用，如窗口位置）───────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key == "theme":
            raise ValueError("使用 set_theme() 设置主题")
        if key == "language":
            raise ValueError("使用 set_language() 设置语言")
        self._data[key] = value
        self._trigger_save()