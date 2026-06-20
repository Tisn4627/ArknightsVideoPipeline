"""
service.report_model - 报告数据适配

将 PipelineReport 转换为 GUI 友好的展示结构。
"""

from __future__ import annotations

from typing import Any

from arknights_video_pipeline.core.step_defs import STEPS_BY_METHOD
from arknights_video_pipeline.core.types import PipelineReport, StepStatus
from arknights_video_pipeline.core.utils import format_duration


_OUTPUT_LABEL_MAP: dict[str, str] = {
    "copilot_json": "Copilot JSON",
    "formation_text": "编队文本",
    "actions_text": "操作文本",
    "track_result": "跟踪结果",
    "output_video": "输出视频",
}


class ReportModel:
    """流水线报告展示模型"""

    def __init__(self, report: PipelineReport | None = None) -> None:
        self.report = report

    def update(self, report: PipelineReport) -> None:
        self.report = report

    @property
    def status_text(self) -> str:
        if not self.report:
            return "未运行"
        status_map = {
            StepStatus.SUCCESS: "成功",
            StepStatus.FAILED: "失败",
            StepStatus.PENDING: "准备中",
            StepStatus.RUNNING: "运行中",
        }
        return status_map.get(self.report.pipeline_status, str(self.report.pipeline_status.value))

    @property
    def total_elapsed_text(self) -> str:
        if not self.report:
            return "-"
        # 复用 core.utils.format_duration，避免逻辑重复与精度丢失
        return format_duration(self.report.total_elapsed)

    @property
    def output_files_list(self) -> list[dict[str, str]]:
        if not self.report:
            return []
        result: list[dict[str, str]] = []
        for key, path in self.report.output_files.items():
            label = _OUTPUT_LABEL_MAP.get(key, key)
            result.append({"label": label, "path": path or "", "key": key})
        return result

    @property
    def step_summary(self) -> list[dict[str, Any]]:
        if not self.report:
            return []
        result: list[dict[str, Any]] = []
        for step in self.report.steps:
            # 从统一定义中查找标签，找不到则回退到 step.description
            step_def = STEPS_BY_METHOD.get(step.name)
            label = step_def.label if step_def else step.description
            result.append({
                "name": step.name,
                "label": label,
                "status": step.status.value,
                "elapsed": step.elapsed,
                "error": step.error or "",
                # 返回副本，避免外部修改影响原始 report 数据
                "warnings": list(step.warnings),
            })
        return result
