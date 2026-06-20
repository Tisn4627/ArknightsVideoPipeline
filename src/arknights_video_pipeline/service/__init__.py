"""
service - GUI 与 CLI 共享的应用服务层

提供配置代理、流水线服务、流水线工作线程、报告模型等中间层组件，
隔离核心引擎与界面表现层。
"""

from arknights_video_pipeline.service.config_proxy import ConfigProxy
from arknights_video_pipeline.service.pipeline_service import PipelineService
from arknights_video_pipeline.service.pipeline_worker import PipelineWorker
from arknights_video_pipeline.service.report_model import ReportModel

__all__ = ["ConfigProxy", "PipelineService", "PipelineWorker", "ReportModel"]
