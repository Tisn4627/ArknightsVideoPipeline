"""
gui.workers.pipeline_worker - 向后兼容重导出

实际实现已迁移至 service.pipeline_worker，避免服务层反向依赖 GUI 层。
"""

from arknights_video_pipeline.service.pipeline_worker import PipelineWorker, QtLogHandler

__all__ = ["PipelineWorker", "QtLogHandler"]
