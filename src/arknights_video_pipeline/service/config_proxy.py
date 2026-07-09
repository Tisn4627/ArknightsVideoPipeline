"""
service.config_proxy - GUI 配置代理

作为 GUI 控件与 ConfigManager 之间的中间层，封装配置的读取、写入与变更通知。

GUI 运行时偏好（如主题）由 ``gui.theme.gui_config.GuiConfig`` 独立管理，
存储于 ``config/gui.json``，与本模块完全解耦。
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
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
        """保存当前流水线配置到 config/pipeline.json"""
        self._config_mgr.save_pipeline_config()

    def load(self, path: str | None = None) -> None:
        self._config_mgr.load_pipeline_config(path)

    # ── 业务字段便捷访问 ──────────────────────────────────

    def video_path(self) -> str:
        return self.get("video_path", "")

    def set_video_path(self, path: str) -> None:
        self.set("video_path", os.path.abspath(path) if path else "")

    def video_paths(self) -> list[str]:
        """批量视频路径列表（GUI 批量处理用）"""
        return list(self.get("video_paths", []))

    def set_video_paths(self, paths: list[str]) -> None:
        self.set("video_paths", [os.path.abspath(p) for p in paths if p])

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

    # ── 多线程配置 ────────────────────────────────────────

    def multithreading(self) -> bool:
        """是否启用多线程批量处理"""
        return bool(self.get("multithreading", False))

    def set_multithreading(self, enabled: bool) -> None:
        self.set("multithreading", bool(enabled))

    # max_concurrent 的硬上限：防止用户填入过大数值导致资源耗尽
    # （每个 worker 会拉起独立 Pipeline + MAA + ffmpeg 子进程）
    MAX_CONCURRENT_LIMIT = 16

    def max_concurrent(self) -> int:
        """最大并发视频合成任务数（>=1）"""
        value = self.get("max_concurrent", 1)
        try:
            n = int(value)
        except (TypeError, ValueError):
            return 1
        return max(1, min(n, self.MAX_CONCURRENT_LIMIT))

    def set_max_concurrent(self, n: int) -> None:
        if n < 1:
            n = 1
        elif n > self.MAX_CONCURRENT_LIMIT:
            n = self.MAX_CONCURRENT_LIMIT
        self.set("max_concurrent", int(n))

    # ── FFmpeg 路径配置 ──────────────────────────────────

    def ffmpeg_custom_enabled(self) -> bool:
        return bool(self.get("ffmpeg_custom_enabled", False))

    def set_ffmpeg_custom_enabled(self, enabled: bool) -> None:
        self.set("ffmpeg_custom_enabled", bool(enabled))

    def ffmpeg_path(self) -> str:
        return self.get("ffmpeg_path", "resource/ffmpeg/bin/ffmpeg.exe")

    def set_ffmpeg_path(self, path: str) -> None:
        self.set("ffmpeg_path", os.path.abspath(path) if path else "")

    def apply_ffmpeg_path(self) -> None:
        """按当前配置将 FFmpeg 目录前置到 PATH（供 GUI 改配置后即时生效）"""
        from arknights_video_pipeline.core.utils import apply_custom_ffmpeg_path
        apply_custom_ffmpeg_path(self._config_mgr.get_ffmpeg_exe_path())

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

    def build_worker_config(self) -> ConfigManager:
        """为单个 worker 线程构建独立的 ConfigManager 快照

        多线程场景下多个 PipelineWorker 并行运行，若共享同一个
        ConfigManager 实例，其 ``pipeline`` 字典的读写将产生数据竞争。
        本方法在调用方（GUI 主线程）执行一次深拷贝 + overrides 合并，
        返回完全独立的 ConfigManager，worker 线程对其的任何访问都不会
        影响其他 worker 或共享的 ConfigProxy 状态。
        """
        snapshot = ConfigManager(self._project_dir)
        snapshot.pipeline = deepcopy(self._config_mgr.pipeline)
        snapshot.merge_cli_overrides(self.build_overrides())
        return snapshot
