"""
core.types - 类型定义与数据结构

使用 dataclass 定义流水线中各步骤的输入/输出数据结构，
提供类型注解增强代码可读性和 IDE 支持。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class StepStatus(enum.Enum):
    """步骤执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class VideoInfo:
    """视频文件元信息"""
    width: int
    height: int
    duration: float
    file_path: str = ""
    file_size: int = 0

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass
class StepResult:
    """单个步骤执行结果"""
    name: str
    description: str
    status: StepStatus = StepStatus.PENDING
    elapsed: float = 0.0
    error: str | None = None
    output_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_running(self) -> None:
        self.status = StepStatus.RUNNING

    def mark_success(self, output_files: list[str] | None = None) -> None:
        self.status = StepStatus.SUCCESS
        if output_files:
            self.output_files = output_files

    def mark_failed(self, error: str) -> None:
        self.status = StepStatus.FAILED
        self.error = error

    def mark_skipped(self, reason: str = "") -> None:
        self.status = StepStatus.SKIPPED
        if reason:
            self.warnings.append(reason)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


@dataclass
class PipelineReport:
    """流水线完整处理报告"""
    video_path: str
    video_name: str
    output_dir: str
    pipeline_status: StepStatus = StepStatus.PENDING
    total_elapsed: float = 0.0
    timestamp: str = ""
    steps: list[StepResult] = field(default_factory=list)
    output_files: dict[str, str | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可JSON化的字典"""
        return {
            "video_path": self.video_path,
            "video_name": self.video_name,
            "output_dir": self.output_dir,
            "pipeline_status": self.pipeline_status.value,
            "total_elapsed": self.total_elapsed,
            "timestamp": self.timestamp,
            "steps": [
                {
                    "name": s.name,
                    "description": s.description,
                    "status": s.status.value,
                    "elapsed": s.elapsed,
                    "error": s.error,
                    "output_files": s.output_files,
                    "warnings": s.warnings,
                    "metadata": s.metadata,
                }
                for s in self.steps
            ],
            "output_files": self.output_files,
            "warnings": self.warnings,
        }
