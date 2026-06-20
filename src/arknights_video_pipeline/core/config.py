"""
core.config - 统一配置管理

集中管理所有配置文件的加载、合并、校验和覆盖逻辑。
优先级：CLI参数 > pipeline.json > 各子配置JSON > 代码默认值
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from typing import Any

from arknights_video_pipeline.core.exceptions import ConfigError
from arknights_video_pipeline.core.utils import _deep_merge_dict

logger = logging.getLogger(__name__)

# 全局流水线默认配置
PIPELINE_DEFAULTS: dict[str, Any] = {
    "maa_path": "",
    "output_dir": "output",
    "log_level": "INFO",
    "log_to_file": True,
    "log_max_bytes": 10 * 1024 * 1024,
    "log_backup_count": 3,
    "maa_timeout_seconds": 600,
    "maa_max_retries": 2,
    "formation": "config/formation.json",
    "actions": "config/actions.json",
    "track": "config/track.json",
    "video_compose_style": "style1",
    "video_compose_config": "config/video_compose/style1.json",
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
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    # ── 全局配置 ──────────────────────────────────────────

    def load_pipeline_config(self, path: str | None = None) -> dict[str, Any]:
        """加载全局流水线配置，与默认值合并"""
        config_path = path or os.path.join(
            self.project_dir, "config", "pipeline.json"
        )
        user_config = self._load_json(config_path)
        if user_config:
            self.pipeline = _deep_merge_dict(self.pipeline, user_config)
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

    def get_maa_timeout(self) -> int:
        return self.pipeline.get("maa_timeout_seconds", 600)

    def get_maa_max_retries(self) -> int:
        return self.pipeline.get("maa_max_retries", 2)

    def get_video_compose_style(self) -> str:
        """获取当前视频合成风格名称，默认为 style1"""
        return self.pipeline.get("video_compose_style", "style1")

    def resolve_video_compose_config(self, style: str | None = None) -> str:
        """根据风格名称解析视频合成配置文件路径

        Args:
            style: 风格名称，为 None 时使用 pipeline 中的 video_compose_style

        Returns:
            配置文件的绝对路径
        """
        style_name = style or self.get_video_compose_style()
        config_path = f"config/video_compose/{style_name}.json"
        return self.resolve_path(config_path)
