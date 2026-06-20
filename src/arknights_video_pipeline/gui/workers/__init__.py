"""
gui.workers - 后台工作线程

提供在独立线程中运行流水线的 Worker。

注：PipelineWorker 已迁移至 service 层（service/pipeline_worker.py），
本模块仅为向后兼容保留重新导出。新代码应直接从 service 层导入。
"""

from arknights_video_pipeline.service.pipeline_worker import PipelineWorker

__all__ = ["PipelineWorker"]
