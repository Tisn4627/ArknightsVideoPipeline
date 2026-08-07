"""
core.maa_backend - MAA 后端（保留为可选回退）

包装原有 MAA 库式调用（core.video_to_copilot），
作为 copilot_backend 抽象层的 "maa" 实现。
见 docs/merge_plan.md §4.3。
"""

from __future__ import annotations

from arknights_video_pipeline.core.video_to_copilot import (
    validate_maa_path,
    video_to_copilot,
)


class MAABackend:
    """视频转 copilot JSON 的 MAA 后端（依赖 MAA 项目安装）。"""

    name = "maa"

    def __init__(self, config: dict):
        self._config = config or {}

    def recognize(
        self,
        video_path: str,
        output_dir: str,
        config: dict,
        timeout: float | None = None,
    ) -> str:
        cfg = {**self._config, **(config or {})}
        maa_path = cfg.get("maa_path", "")
        validate_maa_path(maa_path)

        sub_config = {
            "maa_path": maa_path,
            "output_dir": output_dir,
            # 其余 MAA 子配置透传（不含本层已消费的键）
            **{k: v for k, v in cfg.items() if k not in ("maa_path", "output_dir")},
        }
        return video_to_copilot(video_path, sub_config, timeout=timeout)
