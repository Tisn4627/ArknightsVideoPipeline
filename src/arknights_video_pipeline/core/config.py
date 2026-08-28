"""
core.config - 统一配置管理

集中管理所有配置文件的加载、合并、校验和覆盖逻辑。
优先级：CLI参数 > pipeline.json > 各子配置JSON > 代码默认值
"""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from typing import Any

from arknights_video_pipeline.core.exceptions import ConfigError
# utils 的深合并实现目前仅此一处使用，沿用其私有实现（见合并逻辑归属约定）
from arknights_video_pipeline.core.utils import _deep_merge_dict

logger = logging.getLogger(__name__)

# 全局流水线默认配置
PIPELINE_DEFAULTS: dict[str, Any] = {
    # === 后端选择（新增）===
    # "recognition"（默认，纯 Python 实现，arknights_video_recognition 随仓库分发）
    # | "maa"（可选回退，依赖 MAA 项目安装）
    "copilot_backend": "recognition",

    # === Recognition 后端配置（新增）===
    "recognition": {
        "ocr_source": "maamodel",      # "maamodel" | "default"
        "resolution": "1280x720",      # "WxH"
        "stage_override": "",          # 空=自动识别；否则指定关卡 code/name/stageId
        "with_video_time": False,      # 是否输出 video_time 扩展字段
        "resource_dir": "resource",       # 相对项目根的识别资源目录；默认用项目 resource/
    },

    # === MAA 后端配置（仅 backend=maa 时生效）===
    "maa_path": "",

    # === 通用（recognition/maa 两后端共用的统一超时与重试）===
    "copilot_timeout_seconds": 2400,
    "copilot_max_retries": 1,

    "output_dir": "output",
    "log_level": "INFO",
    "log_to_file": True,
    "log_max_bytes": 10 * 1024 * 1024,
    "log_backup_count": 3,
    "formation": "config/formation.json",
    "actions": "config/actions.json",
    "track": "config/track.json",
    "video_compose_style": "style1",
    "video_compose_config": "config/video_compose/style1.json",
    "skip_steps": [],
    # 合成背景图（仅 style1 使用）；必须存在于默认配置中，
    # 否则重置 pipeline.json 后该键不会写回磁盘，旧值残留在内存与输入框。
    "background_image": "",
    # 多线程批量处理：默认关闭（保持串行，避免 MAA 资源争用）。
    # 启用后由 max_concurrent 限制同时运行的合成任务数。
    "multithreading": False,
    "max_concurrent": 1,
    # FFmpeg 自定义路径（仅 Windows）：启用后使用 ffmpeg_path 指定的目录
    # （含 ffmpeg.exe/ffprobe.exe）；关闭时使用系统 PATH 中的 FFmpeg。
    # 默认启用，使打包后的 EXE 在未安装 FFmpeg 的机器上能直接使用内置的
    # resource/ffmpeg/bin。用户可在设置中关闭以改用系统 PATH 中的 FFmpeg。
    "ffmpeg_custom_enabled": True,
    "ffmpeg_path": "resource/ffmpeg/bin",
}


class ConfigManager:
    """统一配置管理器

    负责加载全局流水线配置和各子模块配置，支持路径解析、
    深度合并和 CLI 参数覆盖。
    """

    def __init__(self, project_dir: str) -> None:
        self.project_dir = os.path.abspath(project_dir)
        self.pipeline: dict[str, Any] = deepcopy(PIPELINE_DEFAULTS)

    # ── 路径解析 ──────────────────────────────────────────

    def resolve_path(self, path: str) -> str:
        """将相对路径解析为基于项目根目录的绝对路径

        空路径或纯空白路径统一返回空字符串，与 utils.resolve_path 行为一致（修复 L11）。
        """
        if not path or not path.strip():
            return ""
        if os.path.isabs(path):
            return path
        return os.path.join(self.project_dir, path)

    # ── JSON 读写 ─────────────────────────────────────────

    def _load_json(self, path: str) -> dict[str, Any] | None:
        abs_path = self.resolve_path(path)
        if not os.path.exists(abs_path):
            return None
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"配置文件读取失败: {abs_path} - {exc}") from exc

    def _save_json(self, path: str, data: dict[str, Any]) -> None:
        abs_path = self.resolve_path(path)
        dir_path = os.path.dirname(abs_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def load_json_file(self, path: str) -> dict[str, Any] | None:
        """公开方法：加载指定路径的 JSON 配置文件

        封装 ``_load_json`` 供外部（如 ConfigProxy）直接按路径加载
        子配置文件，无需通过 pipeline 中的键名间接读取。
        """
        return self._load_json(path)

    def save_sub_config(self, config_path: str, data: dict[str, Any]) -> None:
        """保存子配置字典到指定的 JSON 文件路径

        用于将 track/formation/actions/video_compose 等子配置写回磁盘。
        """
        self._save_json(config_path, data)

    # ── 全局配置 ──────────────────────────────────────────

    def load_pipeline_config(self, path: str | None = None) -> dict[str, Any]:
        """加载全局流水线配置，与默认值合并"""
        config_path = path or os.path.join(
            self.project_dir, "config", "pipeline.json"
        )
        user_config = self._load_json(config_path)
        if user_config:
            # 以全新默认值为基底合并，而非当前内存状态：磁盘文件中缺失的键
            # （重置后默认化/删除的字段）不会残留，确保配置重置能真正清空旧值。
            self.pipeline = _deep_merge_dict(PIPELINE_DEFAULTS, user_config)
        return self.pipeline

    def save_pipeline_defaults(self, path: str | None = None) -> None:
        """保存默认流水线配置到文件"""
        config_path = path or os.path.join(
            self.project_dir, "config", "pipeline.json"
        )
        self._save_json(config_path, PIPELINE_DEFAULTS)

    def save_pipeline_config(self, path: str | None = None) -> None:
        """保存当前流水线配置到文件

        Args:
            path: 目标路径，为 None 时使用默认的 config/pipeline.json
        """
        config_path = path or os.path.join(
            self.project_dir, "config", "pipeline.json"
        )
        self._save_json(config_path, self.pipeline)

    # ── 子配置 ────────────────────────────────────────────

    def load_sub_config(self, config_key: str) -> dict[str, Any]:
        """根据 pipeline 中的键名加载子配置文件

        Args:
            config_key: pipeline 配置中的键名（如 "formation"、"actions"）

        Returns:
            子配置字典，文件不存在或键未配置时返回空字典
        """
        config_path = self.pipeline.get(config_key)
        if not config_path:
            return {}
        data = self._load_json(config_path)
        return data if data else {}

    # ── CLI 覆盖 ──────────────────────────────────────────

    # 允许通过 CLI 覆盖的配置键白名单（修复 L3：防止任意键注入）
    _ALLOWED_CLI_KEYS: frozenset[str] = frozenset(PIPELINE_DEFAULTS.keys()) | {
        "video_compose_style",
        "video_compose_config",
    }

    def merge_cli_overrides(self, overrides: dict[str, Any]) -> None:
        """合并命令行参数覆盖，优先级最高

        仅当值不为 None 时才覆盖，以区分"用户未指定"（None）与
        "用户显式指定为 False/0"等合法假值。调用方应仅将用户实际
        指定的参数放入 overrides，避免传入 argparse 的默认值。

        仅接受白名单内的键（修复 L3：防止任意键注入配置）。
        """
        for key, value in overrides.items():
            if key not in self._ALLOWED_CLI_KEYS:
                logger.warning(f"忽略未知的 CLI 配置键: {key}")
                continue
            if value is not None:
                self.pipeline[key] = value

    # ── 便捷访问 ──────────────────────────────────────────

    def get_maa_path(self) -> str:
        return self.resolve_path(
            self.pipeline.get("maa_path", "")
        )

    def get_output_dir(self, video_name: str | None = None) -> str:
        base = self.resolve_path(
            self.pipeline.get("output_dir", "output")
        )
        if video_name:
            return os.path.join(base, video_name)
        return base

    def get_log_level(self) -> int:
        level_str = self.pipeline.get("log_level", "INFO").upper()
        return getattr(logging, level_str, logging.INFO)

    # ── 后端选择（recognition / maa）────────────────────────

    def get_copilot_backend(self) -> str:
        """获取当前 copilot 后端标识，默认 "recognition"（见 docs/merge_plan.md §6）"""
        return str(self.pipeline.get("copilot_backend", "recognition")).lower()

    def get_copilot_timeout(self) -> int:
        """获取 copilot 识别统一超时（秒），recognition/maa 两后端共用"""
        return self.pipeline.get("copilot_timeout_seconds", 2400)

    def get_copilot_max_retries(self) -> int:
        """获取 copilot 识别统一重试次数，recognition/maa 两后端共用"""
        return self.pipeline.get("copilot_max_retries", 1)

    def get_recognition_config(self) -> dict[str, Any]:
        """获取 Recognition 后端子配置块（缺失键回退默认值）"""
        cfg = self.pipeline.get("recognition", {})
        if not isinstance(cfg, dict):
            return {}
        return deepcopy(cfg)

    def get_video_compose_style(self) -> str:
        """获取当前视频合成风格名称，默认为 style1"""
        return self.pipeline.get("video_compose_style", "style1")

    def resolve_video_compose_config(self, style: str | None = None) -> str:
        """根据风格名称解析视频合成配置文件路径

        Args:
            style: 风格名称，为 None 时使用 pipeline 中的 video_compose_style

        Returns:
            配置文件的绝对路径

        Raises:
            ValueError: 风格名包含非法字符（防止路径注入，与
                pipeline._STYLE_MODULES / config_proxy.set_style 白名单对齐）
        """
        style_name = style or self.get_video_compose_style()
        # 纵深防御：风格名拼入路径前校验合法性，防止 "../" 之类输入
        # 遍历到配置目录之外（上游 set_style 已有正则校验，此处兜底）
        if not re.fullmatch(r"[A-Za-z0-9_]+", str(style_name)):
            raise ValueError(f"非法的视频合成风格名: {style_name!r}")
        config_path = f"config/video_compose/{style_name}.json"
        return self.resolve_path(config_path)
