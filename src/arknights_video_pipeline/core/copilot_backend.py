"""
core.copilot_backend - 视频转 copilot JSON 的后端抽象层

支持多种识别后端（Recognition / MAA），通过配置切换。
见 docs/merge_plan.md §4。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CopilotBackend(Protocol):
    """视频 → Maa copilot 作业 JSON 文件 的统一后端接口。"""

    name: str  # 后端标识，如 "recognition" / "maa"

    def recognize(
        self,
        video_path: str,
        output_dir: str,
        config: dict,
        timeout: float | None = None,
    ) -> str:
        """执行识别，返回生成的 copilot JSON 文件绝对路径。

        Args:
            video_path: 输入视频路径
            output_dir: 输出目录
            config: 后端相关子配置
            timeout: 超时秒数（None 表示不限）

        Returns:
            生成的 copilot JSON 文件绝对路径
        """
        ...


def create_backend(backend_name: str, config: dict) -> CopilotBackend:
    """根据配置创建后端实例。

    Args:
        backend_name: 后端标识（"recognition" / "maa"）
        config: 后端初始化配置

    Raises:
        ValueError: 未知的后端标识
    """
    if backend_name == "recognition":
        from arknights_video_pipeline.core.recognition_backend import (
            RecognitionBackend,
        )

        return RecognitionBackend(config)
    elif backend_name == "maa":
        from arknights_video_pipeline.core.maa_backend import MAABackend

        return MAABackend(config)
    else:
        raise ValueError(
            f"未知的 copilot 后端: {backend_name}（可选: recognition / maa）"
        )
