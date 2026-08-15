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
    # 子配置变更信号：(config_name, field_path, value)
    # config_name 为 "formation"/"actions"/"track"/"style1"/"style2"，
    # field_path 支持点号分隔的嵌套路径如 "text_overlay.enabled"
    sub_config_changed = pyqtSignal(str, str, object)

    # 子配置路径解析映射：config_name -> (pipeline_key_or_None, fixed_path_or_None)
    # pipeline_key 不为 None 时从 pipeline[pipeline_key] 读取路径（如 formation/actions/track）；
    # fixed_path 不为 None 时使用固定路径（如 video_compose 的两个风格文件）。
    _SUB_CONFIG_PATHS: dict[str, tuple[str | None, str | None]] = {
        "formation": ("formation", None),
        "actions":   ("actions", None),
        "track":     ("track", None),
        "style1":    (None, "config/video_compose/style1.json"),
        "style2":    (None, "config/video_compose/style2.json"),
    }

    def __init__(self, project_dir: str = PROJECT_ROOT, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project_dir = project_dir
        # 视频列表仅保存在当前会话，不持久化到磁盘（启动时始终为空）
        self._session_video_paths: list[str] = []
        self._config_mgr = ConfigManager(project_dir)
        self._config_mgr.load_pipeline_config()
        # 清除旧版配置文件中的残留键，避免 save_all() 将其写回磁盘
        self._config_mgr.pipeline.pop("video_paths", None)
        self._config_mgr.pipeline.pop("video_path", None)
        # 同步 FFmpeg 路径配置到 utils 模块全局（GUI 启动时）
        from arknights_video_pipeline.core.utils import set_ffmpeg_config
        set_ffmpeg_config(
            bool(self._config_mgr.pipeline.get("ffmpeg_custom_enabled", False)),
            self._config_mgr.pipeline.get("ffmpeg_path", ""),
        )
        # 加载所有子配置到内存（track/formation/actions/video_compose style1+style2）
        self._sub_configs: dict[str, dict[str, Any]] = {}
        for name in self._SUB_CONFIG_PATHS:
            self._load_sub_config_into_memory(name)

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
        """保存当前流水线配置到 config/pipeline.json

        .. deprecated::
            新代码应使用 ``save_all()`` 同时保存 pipeline.json 与所有子配置文件。
            保留此方法以兼容仅需要保存 pipeline.json 的调用点。
        """
        self._config_mgr.save_pipeline_config()

    def load(self, path: str | None = None) -> None:
        self._config_mgr.load_pipeline_config(path)
        # 重新加载子配置（pipeline.json 中的路径可能已变更）
        for name in self._SUB_CONFIG_PATHS:
            self._load_sub_config_into_memory(name)
        # 清除旧版配置文件中的残留键，避免 save_all() 将其写回磁盘
        self._config_mgr.pipeline.pop("video_paths", None)
        self._config_mgr.pipeline.pop("video_path", None)
        # 重新同步 FFmpeg 配置到 utils 模块全局（重置/重新加载后，
        # 实际生效值必须与磁盘一致，否则 UI 显示与运行时行为脱节）
        from arknights_video_pipeline.core.utils import set_ffmpeg_config
        set_ffmpeg_config(
            bool(self._config_mgr.pipeline.get("ffmpeg_custom_enabled", False)),
            self._config_mgr.pipeline.get("ffmpeg_path", ""),
        )

    # ── 子配置管理（track/formation/actions/video_compose） ────

    def _load_sub_config_into_memory(self, name: str) -> None:
        """从磁盘加载指定子配置到内存

        对于 formation/actions/track，路径来自 pipeline.json 中对应的键；
        对于 video_compose 的 style1/style2，使用固定路径。
        """
        pipeline_key, fixed_path = self._SUB_CONFIG_PATHS[name]
        if pipeline_key:
            data = self._config_mgr.load_sub_config(pipeline_key)
        else:
            data = self._config_mgr.load_json_file(fixed_path) or {}
        self._sub_configs[name] = dict(data) if data else {}

    def get_sub(self, config_name: str, field_path: str,
                default: Any = None) -> Any:
        """读取子配置字段值，支持点号分隔的嵌套路径

        Args:
            config_name: 子配置名称（"formation"/"actions"/"track"/"style1"/"style2"）
            field_path: 字段路径，如 "match_threshold" 或 "text_overlay.enabled"
            default: 字段不存在时返回的默认值

        Returns:
            字段值，或 ``default``
        """
        data: Any = self._sub_configs.get(config_name, {})
        for part in field_path.split("."):
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                return default
        return data

    def set_sub(self, config_name: str, field_path: str,
                value: Any) -> None:
        """设置子配置字段值，支持点号分隔的嵌套路径

        中间层字典不存在时自动创建。设置后发射 ``sub_config_changed`` 信号。
        """
        data = self._sub_configs.setdefault(config_name, {})
        parts = field_path.split(".")
        for part in parts[:-1]:
            data = data.setdefault(part, {})
        data[parts[-1]] = value
        self.sub_config_changed.emit(config_name, field_path, value)

    def save_all(self) -> None:
        """保存 pipeline.json + 所有子配置文件到磁盘"""
        self._config_mgr.save_pipeline_config()
        for name, (pipeline_key, fixed_path) in self._SUB_CONFIG_PATHS.items():
            if name not in self._sub_configs:
                continue
            if pipeline_key:
                path = self._config_mgr.pipeline.get(pipeline_key)
            else:
                path = fixed_path
            if path:
                self._config_mgr.save_sub_config(path, self._sub_configs[name])

    def reload_sub_config(self, name: str) -> None:
        """从磁盘重新加载指定子配置

        当用户在 GUI 中修改了 formation/actions/track 的路径后，
        需要调用此方法刷新内存中对应的子配置数据。
        """
        self._load_sub_config_into_memory(name)

    # ── 业务字段便捷访问 ──────────────────────────────────

    def video_paths(self) -> list[str]:
        """批量视频路径列表（仅当前会话，不持久化）"""
        return list(self._session_video_paths)

    def set_video_paths(self, paths: list[str]) -> None:
        self._session_video_paths = [os.path.abspath(p) for p in paths if p]
        self.config_changed.emit("video_paths", self._session_video_paths)

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
        # 直接修改内部配置，避免两次 set() 发射两次 config_changed 信号
        self._config_mgr.pipeline["video_compose_style"] = style
        self._config_mgr.pipeline["video_compose_config"] = f"config/video_compose/{style}.json"
        self.config_changed.emit("video_compose_style", style)

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

    # ── Copilot 后端配置 ──────────────────────────────────

    COPILOT_BACKENDS: tuple[str, ...] = ("recognition", "maa")

    def copilot_backend(self) -> str:
        backend = str(self.get("copilot_backend", "recognition")).lower()
        return backend if backend in ConfigProxy.COPILOT_BACKENDS else "recognition"

    def set_copilot_backend(self, backend: str) -> None:
        backend = (backend or "").lower()
        if backend not in ConfigProxy.COPILOT_BACKENDS:
            raise ValueError(
                f"非法的后端名称: {backend!r}，可选: {', '.join(ConfigProxy.COPILOT_BACKENDS)}"
            )
        self.set("copilot_backend", backend)

    # ── Copilot 统一超时与重试（recognition/maa 两后端共用） ─

    def copilot_timeout(self) -> int:
        try:
            return int(self.get("copilot_timeout_seconds", 600))
        except (TypeError, ValueError):
            return 600

    def set_copilot_timeout(self, seconds: int) -> None:
        self.set("copilot_timeout_seconds", int(seconds))

    def copilot_max_retries(self) -> int:
        try:
            return int(self.get("copilot_max_retries", 2))
        except (TypeError, ValueError):
            return 2

    def set_copilot_max_retries(self, n: int) -> None:
        self.set("copilot_max_retries", int(n))

    # ── Recognition 后端配置（recognition.* 嵌套字段） ─────

    def _recognition_field(self, field: str, default: Any = None) -> Any:
        rec = self.get("recognition")
        if isinstance(rec, dict):
            return rec.get(field, default)
        return default

    def _set_recognition_field(self, field: str, value: Any) -> None:
        rec = self._config_mgr.pipeline.setdefault("recognition", {})
        rec[field] = value
        self.config_changed.emit(f"recognition.{field}", value)

    def ocr_source(self) -> str:
        value = str(self._recognition_field("ocr_source", "maamodel")).lower()
        return value if value in ("maamodel", "default") else "maamodel"

    def set_ocr_source(self, source: str) -> None:
        source = (source or "").lower()
        if source not in ("maamodel", "default"):
            raise ValueError(f"非法的 OCR 来源: {source!r}，可选: maamodel, default")
        self._set_recognition_field("ocr_source", source)

    def resolution(self) -> str:
        return str(self._recognition_field("resolution", "1280x720"))

    def set_resolution(self, resolution: str) -> None:
        self._set_recognition_field("resolution", (resolution or "").strip())

    def stage_override(self) -> str:
        return str(self._recognition_field("stage_override", ""))

    def set_stage_override(self, stage: str) -> None:
        self._set_recognition_field("stage_override", (stage or "").strip())

    def with_video_time(self) -> bool:
        return bool(self._recognition_field("with_video_time", False))

    def set_with_video_time(self, enabled: bool) -> None:
        self._set_recognition_field("with_video_time", bool(enabled))

    def recognition_resource_dir(self) -> str:
        return str(self._recognition_field("resource_dir", "resource"))

    def set_recognition_resource_dir(self, path: str) -> None:
        self._set_recognition_field("resource_dir", (path or "").strip())

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
        return max(1, min(n, ConfigProxy.MAX_CONCURRENT_LIMIT))

    def set_max_concurrent(self, n: int) -> None:
        if n < 1:
            n = 1
        elif n > ConfigProxy.MAX_CONCURRENT_LIMIT:
            n = ConfigProxy.MAX_CONCURRENT_LIMIT
        self.set("max_concurrent", int(n))

    # ── FFmpeg 路径配置（仅 Windows）─────────────────────────

    def ffmpeg_custom_enabled(self) -> bool:
        """是否启用自定义 FFmpeg 路径"""
        return bool(self.get("ffmpeg_custom_enabled", False))

    def set_ffmpeg_custom_enabled(self, enabled: bool) -> None:
        self.set("ffmpeg_custom_enabled", bool(enabled))
        # 同步到 utils 模块全局，使下次 ensure_ffmpeg_in_path() 生效
        from arknights_video_pipeline.core.utils import set_ffmpeg_config
        set_ffmpeg_config(bool(enabled), self.get("ffmpeg_path", ""))

    def ffmpeg_path(self) -> str:
        return self.get("ffmpeg_path", "")

    def set_ffmpeg_path(self, path: str) -> None:
        self.set("ffmpeg_path", path or "")
        # 同步到 utils 模块全局
        from arknights_video_pipeline.core.utils import set_ffmpeg_config
        set_ffmpeg_config(self.get("ffmpeg_custom_enabled", False), path or "")

    # ── 日志配置 ────────────────────────────────────────

    def log_to_file(self) -> bool:
        return bool(self.get("log_to_file", True))

    def set_log_to_file(self, enabled: bool) -> None:
        self.set("log_to_file", bool(enabled))

    def log_max_bytes(self) -> int:
        try:
            return int(self.get("log_max_bytes", 10 * 1024 * 1024))
        except (TypeError, ValueError):
            return 10 * 1024 * 1024

    def set_log_max_bytes(self, n: int) -> None:
        self.set("log_max_bytes", int(n))

    def log_backup_count(self) -> int:
        try:
            return int(self.get("log_backup_count", 3))
        except (TypeError, ValueError):
            return 3

    def set_log_backup_count(self, n: int) -> None:
        self.set("log_backup_count", int(n))

    # ── 子配置文件路径（formation/actions/track） ──────────

    def formation_path(self) -> str:
        return self.get("formation", "config/formation.json")

    def set_formation_path(self, path: str) -> None:
        self.set("formation", path or "config/formation.json")
        self.reload_sub_config("formation")

    def actions_path(self) -> str:
        return self.get("actions", "config/actions.json")

    def set_actions_path(self, path: str) -> None:
        self.set("actions", path or "config/actions.json")
        self.reload_sub_config("actions")

    def track_path(self) -> str:
        return self.get("track", "config/track.json")

    def set_track_path(self, path: str) -> None:
        self.set("track", path or "config/track.json")
        self.reload_sub_config("track")

    # ── 构建运行参数 ──────────────────────────────────────

    def build_overrides(self) -> dict[str, Any]:
        """构建用于合并到 ConfigManager 的 CLI/GUI 覆盖项"""
        overrides: dict[str, Any] = {}
        for key in ["maa_path", "output_dir", "log_level", "log_to_file",
                    "log_max_bytes", "log_backup_count",
                    "formation", "actions", "track",
                    "video_compose_style", "video_compose_config",
                    "ffmpeg_custom_enabled", "ffmpeg_path"]:
            value = self.get(key)
            if value is not None:
                overrides[key] = value
        return overrides

    def build_worker_config(self) -> ConfigManager:
        """为单个 worker 线程构建独立的 ConfigManager 快照

        多线程场景下多个 PipelineWorker 并行运行，若共享同一个
        ConfigManager 实例，其 ``pipeline`` 字典的读写将产生数据竞争。
        本方法在调用方（GUI 主线程）执行一次深拷贝，
        返回完全独立的 ConfigManager，worker 线程对其的任何访问都不会
        影响其他 worker 或共享的 ConfigProxy 状态。
        """
        snapshot = ConfigManager(self._project_dir)
        snapshot.pipeline = deepcopy(self._config_mgr.pipeline)
        return snapshot
