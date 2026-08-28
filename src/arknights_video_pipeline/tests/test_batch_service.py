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
    proxy.multithreading.return_value = False
    proxy.max_concurrent.return_value = 1
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

    def test_validate_batch_missing_bound_json(self, qapp, tmp_path) -> None:
        """绑定的自定义作业 JSON 不存在时返回对应错误"""
        service = PipelineService(_make_config_proxy())
        video = tmp_path / "a.mp4"
        video.write_bytes(b"x")
        missing = str(tmp_path / "missing.json")
        with mock.patch(
            "arknights_video_pipeline.service.pipeline_service.validate_video_file",
            return_value={},
        ):
            errors = service.validate_batch([str(video)], [missing])
        assert any("自定义作业JSON文件不存在" in e for e in errors)

    def test_validate_batch_non_json_bound_file(self, qapp, tmp_path) -> None:
        """绑定的自定义文件非 .json 扩展名时返回对应错误"""
        service = PipelineService(_make_config_proxy())
        video = tmp_path / "a.mp4"
        video.write_bytes(b"x")
        txt = tmp_path / "a.txt"
        txt.write_text("{}", encoding="utf-8")
        with mock.patch(
            "arknights_video_pipeline.service.pipeline_service.validate_video_file",
            return_value={},
        ):
            errors = service.validate_batch([str(video)], [str(txt)])
        assert any("必须是 .json 文件" in e for e in errors)

    def test_validate_batch_valid_bound_json_passes(self, qapp, tmp_path) -> None:
        """绑定的 JSON 存在且为 .json 时校验通过"""
        service = PipelineService(_make_config_proxy())
        video = tmp_path / "a.mp4"
        video.write_bytes(b"x")
        jp = tmp_path / "a.json"
        jp.write_text("{}", encoding="utf-8")
        with mock.patch(
            "arknights_video_pipeline.service.pipeline_service.validate_video_file",
            return_value={},
        ):
            errors = service.validate_batch([str(video)], [str(jp)])
        assert errors == []


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

    def test_worker_signals_are_wired(self, qapp) -> None:
        """worker 关键信号必须全部接线（防 connect 参数错位/漏接回归）

        直接调 _on_worker_finished 绕过了 dispatch 时的信号连接，
        若 pipeline_service.py 的五处 .connect 漏接或签名错位，套件仍会
        全绿——此处显式断言接线发生。
        """
        service = PipelineService(_make_config_proxy())
        with mock.patch(_WORKER) as mock_worker_cls:
            with mock.patch.object(service, "validate_batch", return_value=[]):
                service.run_pipeline(["a.mp4"])
            worker = mock_worker_cls.return_value
            worker.step_started.connect.assert_called()
            worker.step_finished.connect.assert_called()
            worker.progress_updated.connect.assert_called()
            worker.log_emitted.connect.assert_called()
            worker.pipeline_finished.connect.assert_called()


# ── 自定义作业 JSON ────────────────────────────────────────


class TestCustomCopilotJson:
    """验证自定义作业 JSON 路径的透传"""

    def test_run_pipeline_forwards_json_to_worker(self, qapp) -> None:
        """run_pipeline 将绑定的 JSON 路径传给 PipelineWorker"""
        service = PipelineService(_make_config_proxy())
        with mock.patch(_WORKER) as mock_worker_cls, \
             mock.patch.object(service, "validate_batch", return_value=[]):
            service.run_pipeline(["a.mp4"], ["C:/json/a.json"])
        _, kwargs = mock_worker_cls.call_args
        assert kwargs["copilot_json_path"] == "C:/json/a.json"

    def test_run_pipeline_forwards_none_json_for_unbound(self, qapp) -> None:
        """未绑定 JSON 的视频传给 worker 的 copilot_json_path 为 None"""
        service = PipelineService(_make_config_proxy())
        with mock.patch(_WORKER) as mock_worker_cls, \
             mock.patch.object(service, "validate_batch", return_value=[]):
            service.run_pipeline(["a.mp4", "b.mp4"], [None, "C:/json/b.json"])
            # 串行模式：先派发文件1，完成后才派发文件2
            service._on_worker_finished(0, True, {}, False)
        assert mock_worker_cls.call_args_list[0].kwargs["copilot_json_path"] is None
        assert mock_worker_cls.call_args_list[1].kwargs["copilot_json_path"] == \
            "C:/json/b.json"

    def test_run_pipeline_without_json_paths_backward_compatible(self, qapp) -> None:
        """不传 json_paths 时行为与旧版一致（全部 None）"""
        service = PipelineService(_make_config_proxy())
        with mock.patch(_WORKER) as mock_worker_cls, \
             mock.patch.object(service, "validate_batch", return_value=[]):
            service.run_pipeline(["a.mp4"])
        assert mock_worker_cls.call_args_list[0].kwargs["copilot_json_path"] is None


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


# ── force_terminate_workers ───────────────────────────────


class TestForceTerminateWorkers:
    """验证 force_terminate_workers 强制终止工作线程逻辑

    wait_for_shutdown 超时后的兜底：对仍在运行的 worker 调用
    QThread.terminate() + wait()，并从 _workers 清除。
    """

    def test_force_terminate_no_workers_is_noop(self, qapp) -> None:
        """无运行 worker 时调用 force_terminate_workers 不报错"""
        service = PipelineService(_make_config_proxy())
        service.force_terminate_workers(timeout_ms=100)
        assert len(service._workers) == 0

    def test_force_terminate_running_worker_calls_terminate_and_wait(self, qapp) -> None:
        """运行中的 worker 被 terminate + wait，并从 _workers 清除"""
        service = PipelineService(_make_config_proxy())
        worker = mock.MagicMock()
        worker.isRunning.return_value = True
        service._workers = {0: worker}

        service.force_terminate_workers(timeout_ms=500)

        worker.terminate.assert_called_once()
        # 统一 deadline 分摊：wait 预算不超过 timeout_ms 且为正
        (wait_ms,), _ = worker.wait.call_args
        assert 1 <= wait_ms <= 500
        assert 0 not in service._workers

    def test_force_terminate_non_running_worker_not_terminated(self, qapp) -> None:
        """未运行的 worker 不调用 terminate，但仍从 _workers 清除"""
        service = PipelineService(_make_config_proxy())
        worker = mock.MagicMock()
        worker.isRunning.return_value = False
        service._workers = {0: worker}

        service.force_terminate_workers(timeout_ms=500)

        worker.terminate.assert_not_called()
        worker.wait.assert_not_called()
        assert 0 not in service._workers

    def test_force_terminate_multiple_workers(self, qapp) -> None:
        """多个 worker 均被 terminate + wait 并清除

        统一 deadline 分摊等待预算：首个 worker 获得完整 timeout，
        后续 worker 获得剩余预算（≤ timeout），总阻塞不超过 timeout。
        """
        service = PipelineService(_make_config_proxy())
        w0 = mock.MagicMock()
        w0.isRunning.return_value = True
        w1 = mock.MagicMock()
        w1.isRunning.return_value = True
        service._workers = {0: w0, 1: w1}

        service.force_terminate_workers(timeout_ms=1000)

        w0.terminate.assert_called_once()
        w1.terminate.assert_called_once()
        # 统一 deadline：deadline 计算与 wait 调用间存在时间流逝，
        # 预算为 (1, timeout] 区间内的值，不做精确相等断言
        for w in (w0, w1):
            (wait_ms,), _ = w.wait.call_args
            assert 1 <= wait_ms <= 1000
        assert len(service._workers) == 0

    def test_force_terminate_emits_warning_log(self, qapp) -> None:
        """强制终止时发射 WARNING 级别日志"""
        service = PipelineService(_make_config_proxy())
        worker = mock.MagicMock()
        worker.isRunning.return_value = True
        service._workers = {0: worker}
        log_events: list = []
        service.log_emitted.connect(lambda level, msg: log_events.append((level, msg)))

        service.force_terminate_workers(timeout_ms=100)

        assert any(level == "WARNING" for level, _ in log_events)

    def test_wait_for_shutdown_does_not_terminate(self, qapp) -> None:
        """wait_for_shutdown 仅等待，不调用 terminate"""
        service = PipelineService(_make_config_proxy())
        worker = mock.MagicMock()
        worker.isRunning.return_value = True
        service._workers = {0: worker}

        service.wait_for_shutdown(timeout_ms=3000)

        worker.wait.assert_called_once_with(3000)
        worker.terminate.assert_not_called()
        # wait_for_shutdown 不清除 _workers（worker 仍在运行）
        assert 0 in service._workers
