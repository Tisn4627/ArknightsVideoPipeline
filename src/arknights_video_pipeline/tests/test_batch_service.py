"""批量流水线服务单元测试

验证 service/pipeline_service.py 中 PipelineService 的批量调度逻辑：
- validate_batch 输入校验（空列表、缺失文件、不支持格式）
- run_pipeline 串行调度（一次仅运行一个 worker）
- 中间文件失败后继续处理后续文件
- 取消请求在当前文件结束后停止
- 总体进度计算

PipelineWorker 被完全 mock 为 MagicMock（非真实 QThread），测试通过
直接调用 service._on_worker_finished() / _on_file_progress() 模拟
worker 完成与进度回调，避免真实线程执行。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock

import pytest
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.service.pipeline_service import PipelineService


_WORKER = "arknights_video_pipeline.service.pipeline_service.PipelineWorker"


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen 模式），确保 QObject 信号可用"""
    app = QApplication.instance() or QApplication([])
    yield app


def _make_config_proxy(style: str = "style2", bg: str = "", maa: str = "") -> mock.MagicMock:
    """创建配置代理 mock，默认 style2（无需背景板图片）"""
    proxy = mock.MagicMock()
    proxy.style.return_value = style
    proxy.background_image.return_value = bg
    proxy.maa_path.return_value = maa
    proxy.skip_steps.return_value = set()
    return proxy


# ── validate_batch ─────────────────────────────────────────


class TestValidateBatch:
    """验证 validate_batch 输入校验"""

    def test_validate_batch_empty_returns_error(self, qapp) -> None:
        """空列表返回包含"请至少添加一个视频文件"的错误"""
        service = PipelineService(_make_config_proxy())
        errors = service.validate_batch([])
        assert len(errors) > 0
        assert any("请至少添加一个视频文件" in e for e in errors)

    def test_validate_batch_missing_file(self, qapp, tmp_path) -> None:
        """不存在的视频文件返回包含"视频文件不存在"的错误"""
        service = PipelineService(_make_config_proxy())
        missing = str(tmp_path / "nonexistent.mp4")
        errors = service.validate_batch([missing])
        assert any("视频文件不存在" in e for e in errors)

    def test_validate_batch_unsupported_ext(self, qapp, tmp_path) -> None:
        """不支持的视频格式（.txt）返回包含"不受支持的视频格式"的错误"""
        service = PipelineService(_make_config_proxy())
        bad_file = tmp_path / "bad.txt"
        bad_file.write_text("not a video")
        errors = service.validate_batch([str(bad_file)])
        assert any("不受支持的视频格式" in e for e in errors)


# ── run_pipeline 调度 ──────────────────────────────────────


class TestRunPipelineScheduling:
    """验证 run_pipeline 串行调度逻辑"""

    def test_run_pipeline_empty_returns_false_no_signals(self, qapp) -> None:
        """空列表时返回 False，发射 validation_failed，不发射 batch_finished"""
        service = PipelineService(_make_config_proxy())
        vf_events: list = []
        bf_events: list = []
        service.validation_failed.connect(lambda errs: vf_events.append(errs))
        service.batch_finished.connect(lambda s, t, c: bf_events.append((s, t, c)))
        result = service.run_pipeline([])
        assert result is False
        assert len(vf_events) == 1
        assert len(vf_events[0]) > 0
        assert len(bf_events) == 0

    def test_run_pipeline_serial_scheduling(self, qapp) -> None:
        """3 个有效视频串行调度，依次完成 3 个 worker 后发射 batch_finished(3, 3, False)"""
        service = PipelineService(_make_config_proxy())
        with mock.patch(_WORKER) as mock_worker_cls:
            batch_events: list = []
            service.batch_finished.connect(lambda s, t, c: batch_events.append((s, t, c)))
            with mock.patch.object(service, "validate_batch", return_value=[]):
                assert service.run_pipeline(["a.mp4", "b.mp4", "c.mp4"]) is True
            # 仅第一个 worker 被创建
            assert mock_worker_cls.call_count == 1

            # 模拟文件 1 完成 → 启动文件 2
            service._on_worker_finished(0, True, {}, False)
            assert mock_worker_cls.call_count == 2

            # 模拟文件 2 完成 → 启动文件 3
            service._on_worker_finished(1, True, {}, False)
            assert mock_worker_cls.call_count == 3

            # 模拟文件 3 完成 → 批次结束
            service._on_worker_finished(2, True, {}, False)

        assert len(batch_events) == 1
        assert batch_events[0] == (3, 3, False)

    def test_run_pipeline_middle_failure_continues(self, qapp) -> None:
        """中间文件失败后继续处理后续文件，batch_finished(2, 3, False)"""
        service = PipelineService(_make_config_proxy())
        with mock.patch(_WORKER) as mock_worker_cls:
            batch_events: list = []
            service.batch_finished.connect(lambda s, t, c: batch_events.append((s, t, c)))
            with mock.patch.object(service, "validate_batch", return_value=[]):
                service.run_pipeline(["a.mp4", "b.mp4", "c.mp4"])

            service._on_worker_finished(0, True, {}, False)    # 文件 1 成功
            service._on_worker_finished(1, False, {}, False)   # 文件 2 失败
            service._on_worker_finished(2, True, {}, False)    # 文件 3 成功

        # 3 个 worker 都被创建（失败也创建 worker）
        assert mock_worker_cls.call_count == 3
        # 2 个成功 / 3 个总数 / 未取消
        assert batch_events[-1] == (2, 3, False)

    def test_run_pipeline_cancel_stops_after_current(self, qapp) -> None:
        """取消请求后当前文件完成即停止，文件 2 不启动，batch_finished(1, 3, True)"""
        service = PipelineService(_make_config_proxy())
        with mock.patch(_WORKER) as mock_worker_cls:
            batch_events: list = []
            service.batch_finished.connect(lambda s, t, c: batch_events.append((s, t, c)))
            with mock.patch.object(service, "validate_batch", return_value=[]):
                service.run_pipeline(["a.mp4", "b.mp4", "c.mp4"])

            service.cancel_pipeline()
            # 模拟文件 1 以 cancelled=True 完成
            service._on_worker_finished(0, True, {}, True)

        # 仅文件 1 的 worker 被创建，文件 2 未启动
        assert mock_worker_cls.call_count == 1
        assert batch_events[-1] == (1, 3, True)


# ── 总体进度 ───────────────────────────────────────────────


class TestOverallProgress:
    """验证 overall_progress 信号的计算与发射"""

    def test_overall_progress_calculation(self, qapp) -> None:
        """3 文件：文件1完成(100) + 文件2进度50% → 总体 (100+50+0)//3 = 50"""
        service = PipelineService(_make_config_proxy())
        with mock.patch(_WORKER):
            progress_values: list = []
            service.overall_progress.connect(lambda p, m: progress_values.append(p))
            with mock.patch.object(service, "validate_batch", return_value=[]):
                service.run_pipeline(["a.mp4", "b.mp4", "c.mp4"])

            # 文件 1 完成 → contributions=[100,0,0]
            service._on_worker_finished(0, True, {}, False)
            # 文件 2 进度 50% → contributions=[100,50,0]
            service._on_file_progress(1, 50, "processing")

        assert 50 in progress_values

    def test_overall_progress_reaches_100_on_batch_finish(self, qapp) -> None:
        """全部文件完成后 overall_progress 发射 100"""
        service = PipelineService(_make_config_proxy())
        with mock.patch(_WORKER):
            progress_values: list = []
            service.overall_progress.connect(lambda p, m: progress_values.append(p))
            with mock.patch.object(service, "validate_batch", return_value=[]):
                service.run_pipeline(["a.mp4", "b.mp4", "c.mp4"])

            service._on_worker_finished(0, True, {}, False)
            service._on_worker_finished(1, True, {}, False)
            service._on_worker_finished(2, True, {}, False)

        assert 100 in progress_values
