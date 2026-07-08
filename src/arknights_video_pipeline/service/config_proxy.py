"""
service.config_proxy - GUI 配置代理

作为 GUI 控件与 ConfigManager 之间的中间层，封装配置的读取、写入与变更通知。

GUI 运行时偏好（如主题）单独保存在 ``config/gui.json``，与流水线业务配置
``config/pipeline.json`` 完全解耦，互不影响。
"""

from __future__ import annotations

import json
import os
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from arknights_video_pipeline.core.config import ConfigManager
from arknights_video_pipeline.core.utils import PROJECT_ROOT


class ConfigProxy(QObject):
    """配置代理，连接 GUI 控件与 ConfigManager"""

    config_changed = pyqtSignal(str, object)

    def __init__(self, project_dir: str = PROJECT_ROOT, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project_dir = project_dir
        self._config_mgr = ConfigManager(project_dir)
        self._config_mgr.load_pipeline_config()
        # GUI 运行时偏好独立加载/保存，不与 pipeline.json 耦合
        self._gui_config_path = os.path.join(project_dir, "config", "gui.json")
        self._gui_config: dict[str, Any] = {"theme": "light"}
        self._load_gui_config()

    # ── 基础读写 ──────────────────────────────────────────

    @property
    def config_manager(self) -> ConfigManager:
        return self._config_mgr

    def get(self, key: str, default: Any = None) -> Any:
        return self._config_mgr.pipeline.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config_mgr.pipeline[key] = value
        self.config_changed.emit(key, value)

    def save(self) -> None:
        """保存当前配置到 config/pipeline.json 与 config/gui.json"""
        self._config_mgr.save_pipeline_config()
        self._save_gui_config()

    def load(self, path: str | None = None) -> None:
        self._config_mgr.load_pipeline_config(path)

    # ── 业务字段便捷访问 ──────────────────────────────────

    def video_path(self) -> str:
        return self.get("video_path", "")

    def set_video_path(self, path: str) -> None:
        self.set("video_path", os.path.abspath(path) if path else "")

    def background_image(self) -> str:
        return self.get("background_image", "")

    def set_background_image(self, path: str) -> None:
        self.set("background_image", os.path.abspath(path) if path else "")

    def output_dir(self) -> str:
        return self.get("output_dir", "output")

    def set_output_dir(self, path: str) -> None:
        self.set("output_dir", os.path.abspath(path) if path else "output")

    def maa_path(self) -> str:
        return self.get("maa_path", "")

    def set_maa_path(self, path: str) -> None:
        self.set("maa_path", os.path.abspath(path) if path else "")

    def style(self) -> str:
        return self.get("video_compose_style", "style1")

    def set_style(self, style: str) -> None:
        """设置视频合成风格

        Args:
            style: 风格名称，需匹配 config/video_compose/{style}.json 文件

        Raises:
            ValueError: 当 style 包含非法字符或对应配置文件不存在时
        """
        import re
        if not style or not re.match(r"^[a-zA-Z0-9_]+$", style):
            raise ValueError(f"非法的风格名称: {style!r}，仅允许字母、数字和下划线")
        config_path = self._config_mgr.resolve_video_compose_config(style)
        if not os.path.exists(config_path):
            raise ValueError(f"风格配置文件不存在: {config_path}")
        self.set("video_compose_style", style)
        self.set("video_compose_config", f"config/video_compose/{style}.json")

    def log_level(self) -> str:
        return self.get("log_level", "INFO")

    def set_log_level(self, level: str) -> None:
        self.set("log_level", level)

    def skip_steps(self) -> set[str]:
        return set(self.get("skip_steps", []))

    def set_skip_steps(self, steps: set[str]) -> None:
        self.set("skip_steps", list(steps))

    def log_to_file(self) -> bool:
        return self.get("log_to_file", True)

    def set_log_to_file(self, enabled: bool) -> None:
        self.set("log_to_file", enabled)

    # ── GUI 运行时偏好 ─────────────────────────────────────
    # 独立存储于 config/gui.json，不与 pipeline.json 耦合

    def _load_gui_config(self) -> None:
        """从 ``config/gui.json`` 加载 GUI 运行时偏好"""
        if not os.path.exists(self._gui_config_path):
            return
        try:
            with open(self._gui_config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # 只合并顶层键，不覆盖默认值结构
                self._gui_config.update(data)
        except (json.JSONDecodeError, OSError):
            pass

    def _save_gui_config(self) -> None:
        """将 GUI 运行时偏好写入 ``config/gui.json``"""
        os.makedirs(os.path.dirname(self._gui_config_path), exist_ok=True)
        with open(self._gui_config_path, "w", encoding="utf-8") as f:
            json.dump(self._gui_config, f, indent=4, ensure_ascii=False)

    def theme(self) -> str:
        """获取 GUI 主题名称，返回 ``"light"`` 或 ``"dark"``，默认 ``"light"``

        读取 ``config/gui.json`` 中的 ``theme`` 字段，缺失或非法值时
        回退为 ``"light"``，确保旧版本配置文件兼容。
        """
        theme = self._gui_config.get("theme", "light")
        return theme if theme in ("light", "dark") else "light"

    def set_theme(self, theme: str) -> None:
        """设置 GUI 主题名称（``"light"`` 或 ``"dark"``）

        仅写入内存中的 ``_gui_config``，实际持久化发生在 ``save()``
        被调用时（通常由 ``closeEvent`` 触发）。
        """
        if theme not in ("light", "dark"):
            raise ValueError(f"非法的主题名称: {theme!r}，仅允许 'light' 或 'dark'")
        self._gui_config["theme"] = theme

    def is_dark_theme(self) -> bool:
        """便捷方法：当前主题是否为深色"""
        return self.theme() == "dark"

    # ── 构建运行参数 ──────────────────────────────────────

    def build_overrides(self) -> dict[str, Any]:
        """构建用于合并到 ConfigManager 的 CLI/GUI 覆盖项"""
        overrides: dict[str, Any] = {}
        for key in ["maa_path", "output_dir", "log_level", "log_to_file",
                    "video_compose_style", "video_compose_config"]:
            value = self.get(key)
            if value is not None:
                overrides[key] = value
        return overrides
