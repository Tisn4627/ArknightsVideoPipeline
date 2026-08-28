"""Recognition 后端适配层单元测试

验证 core/recognition_backend.py：
- AVR_RESOURCE_DIR 默认指向 <项目根>/resource/（识别资源并入顶层）
- 配置级 resource_dir 覆盖在首次导入前生效
- 分辨率解析、stage_override 透传
- 输出 JSON 落盘与归一化
- 超时 / StageNotRecognizedError / ResourceMissingError 处理

Recognition 主流水线通过 mock 替换 _import_recognition_pipeline，
不依赖 onnxruntime 等重型依赖。
"""

from __future__ import annotations

import importlib
import json
import os
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from arknights_video_pipeline.core.exceptions import CopilotBackendError
from arknights_video_pipeline.core.recognition_backend import (
    RecognitionBackend,
    _normalize_copilot,
)

_RB = "arknights_video_pipeline.core.recognition_backend"

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class FakeStageError(ValueError):
    pass


class FakeResourceError(Exception):
    pass


class FakePipeline:
    """VideoRecognitionPipeline 替身（记录构造/调用参数）"""

    def __init__(self, ocr_source, resolution):
        self.ocr_source = ocr_source
        self.resolution = resolution

    def run(self, video_path, stage_override=None, output_path=None, with_video_time=False):
        self.last_run = {
            "video_path": video_path,
            "stage_override": stage_override,
            "output_path": output_path,
            "with_video_time": with_video_time,
        }
        return {
            "minimum_required": "v4.0.0",
            "stage_name": "main_02-10",
            "opers": [{"name": "陈"}],
            "groups": [],
            "actions": [{"type": "Deploy", "name": "陈", "location": [5, 3]}],
            "doc": {"title": "MAA AI - main_02-10"},
        }


def _mock_import(pipe_cls=None):
    """返回补丁后的 _import_recognition_pipeline mock 上下文"""
    return mock.patch(
        f"{_RB}._import_recognition_pipeline",
        return_value=(pipe_cls or FakePipeline, FakeStageError, FakeResourceError),
    )


# ── 归一化 ─────────────────────────────────────────────────


class TestNormalizeCopilot:
    """验证 _normalize_copilot 字段补齐"""

    def test_oper_defaults_filled(self) -> None:
        job = {"opers": [{"name": "A"}], "actions": []}
        out = _normalize_copilot(job)
        assert out["opers"][0]["skill"] == 1
        assert out["opers"][0]["skill_usage"] == 0

    def test_existing_values_preserved(self) -> None:
        job = {"opers": [{"name": "A", "skill": 3, "skill_usage": 2}]}
        out = _normalize_copilot(job)
        assert out["opers"][0]["skill"] == 3
        assert out["opers"][0]["skill_usage"] == 2

    def test_missing_top_level_fields(self) -> None:
        out = _normalize_copilot({})
        assert out["minimum_required"] == "v4.0.0"
        assert out["groups"] == []
        assert out["actions"] == []
        assert out["opers"] == []


# ── AVR_RESOURCE_DIR 默认路径 ──────────────────────────────


class TestResourceDir:
    """验证资源目录解析优先级"""

    def test_default_env_set_to_top_level_resource(self, monkeypatch) -> None:
        """模块导入时 AVR_RESOURCE_DIR 默认指向 <项目根>/resource"""
        monkeypatch.delenv("AVR_RESOURCE_DIR", raising=False)
        importlib.reload(importlib.import_module("arknights_video_pipeline.core.recognition_backend"))
        expected = os.path.join(_PROJECT_ROOT, "resource")
        assert os.environ["AVR_RESOURCE_DIR"].replace("\\", "/") == expected.replace("\\", "/")

    def test_existing_env_var_respected(self, monkeypatch) -> None:
        """环境变量已设置时不覆盖"""
        monkeypatch.setenv("AVR_RESOURCE_DIR", "C:/custom_res")
        importlib.reload(importlib.import_module("arknights_video_pipeline.core.recognition_backend"))
        assert os.environ["AVR_RESOURCE_DIR"] == "C:/custom_res"


# ── recognize() 行为 ───────────────────────────────────────


class TestRecognitionBackendRecognize:
    """验证 RecognitionBackend.recognize 全流程（pipeline 为替身）"""

    def test_writes_json_with_normalization(self, tmp_path) -> None:
        """run() 结果归一化后落盘为 recognition_copilot_<stem>.json"""
        backend = RecognitionBackend({})
        with _mock_import() as mi:
            out_path = backend.recognize(
                video_path=str(tmp_path / "battle.mp4"),
                output_dir=str(tmp_path / "out"),
                config={},
            )
        assert out_path.endswith("recognition_copilot_battle.json")
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        assert data["opers"][0]["skill"] == 1
        assert data["stage_name"] == "main_02-10"
        mi.assert_called_once_with(None)

    def test_config_passed_to_pipeline(self, tmp_path) -> None:
        """ocr_source / resolution / stage_override / with_video_time 透传"""
        pipe = mock.MagicMock()
        pipe.run.return_value = {"actions": [], "opers": []}
        pipe_cls = mock.MagicMock(return_value=pipe)
        backend = RecognitionBackend({})
        with mock.patch(
            f"{_RB}._import_recognition_pipeline",
            return_value=(pipe_cls, FakeStageError, FakeResourceError),
        ):
            backend.recognize(
                video_path=str(tmp_path / "b.mp4"),
                output_dir=str(tmp_path / "out"),
                config={
                    "ocr_source": "default",
                    "resolution": "1920x1080",
                    "stage_override": "2-10",
                    "with_video_time": True,
                },
            )
        pipe_cls.assert_called_once_with(ocr_source="default", resolution=(1920, 1080))
        assert pipe.run.call_args.kwargs["stage_override"] == "2-10"
        assert pipe.run.call_args.kwargs["with_video_time"] is True

    def test_config_resource_dir_overrides_env(self, tmp_path) -> None:
        """配置级 resource_dir 在导入前传给 _import_recognition_pipeline"""
        backend = RecognitionBackend({})
        custom = str(tmp_path / "custom_res")
        with _mock_import() as mi:
            backend.recognize(
                video_path=str(tmp_path / "b.mp4"),
                output_dir=str(tmp_path / "out"),
                config={"resource_dir": custom},
            )
        mi.assert_called_once_with(custom)

    def test_timeout_exceeded_raises(self, tmp_path) -> None:
        """识别超过 timeout 抛 TimeoutError"""
        class SlowPipeline(FakePipeline):
            def run(self, *a, **kw):
                time.sleep(0.05)
                return {"actions": [], "opers": []}

        backend = RecognitionBackend({})
        with _mock_import(SlowPipeline):
            with pytest.raises(TimeoutError):
                backend.recognize(
                    video_path=str(tmp_path / "b.mp4"),
                    output_dir=str(tmp_path / "out"),
                    config={},
                    timeout=0.01,
                )

    def test_stage_not_recognized_propagates(self, tmp_path) -> None:
        """StageNotRecognizedError 原样传播（不包装）"""
        class NoStagePipeline(FakePipeline):
            def run(self, *a, **kw):
                raise FakeStageError("关卡未识别")

        backend = RecognitionBackend({})
        with _mock_import(NoStagePipeline):
            with pytest.raises(FakeStageError):
                backend.recognize(
                    video_path=str(tmp_path / "b.mp4"),
                    output_dir=str(tmp_path / "out"),
                    config={},
                )

    def test_resource_missing_not_retryable(self, tmp_path) -> None:
        """ResourceMissingError 包装为不可重试的 CopilotBackendError（不再进入重试）"""
        class NoResPipeline(FakePipeline):
            def run(self, *a, **kw):
                raise FakeResourceError("tile/levels.json 缺失")

        backend = RecognitionBackend({})
        with _mock_import(NoResPipeline):
            with pytest.raises(CopilotBackendError) as exc_info:
                backend.recognize(
                    video_path=str(tmp_path / "b.mp4"),
                    output_dir=str(tmp_path / "out"),
                    config={},
                )
        assert exc_info.value.retryable is False
        assert "顶层 resource/ 目录" in str(exc_info.value)

    def test_timeout_retry_resumes_same_worker(self, tmp_path) -> None:
        """超时后的重试调用续等同一后台线程，不重新启动识别

        修复验证：旧实现重试会并行启动第二个识别线程（CPU 争抢 +
        重复劳动 + 并发写同一输出文件）；新实现重试 = 续等旧线程。
        """
        release = threading.Event()
        run_count = {"n": 0}

        class ControlledPipeline(FakePipeline):
            def run(self, *a, **kw):
                run_count["n"] += 1
                release.wait(5)  # 由测试控制何时完成
                return {"actions": [], "opers": []}

        backend = RecognitionBackend({})
        video = str(tmp_path / "b.mp4")
        with _mock_import(ControlledPipeline):
            # 第 1 次：超时失败，后台线程继续运行
            with pytest.raises(TimeoutError):
                backend.recognize(video, str(tmp_path / "out"), {}, timeout=0.05)
            assert run_count["n"] == 1
            assert backend._worker is not None and backend._worker.is_alive()

            # 0.2s 后放行识别线程（期间第 2 次调用已进入续等分支）
            threading.Timer(0.2, release.set).start()

            # 第 2 次（重试）：续等旧线程并复用结果，而非重启识别
            out_path = backend.recognize(video, str(tmp_path / "out"), {}, timeout=10)

        assert run_count["n"] == 1  # pipe.run 仅执行一次：重试未重启识别
        assert out_path.endswith("recognition_copilot_b.json")
        assert json.loads(Path(out_path).read_text(encoding="utf-8"))["actions"] == []
        # 结果已消费清理，防止后续调用误入续等分支
        assert backend._worker is None

    def test_timeout_retry_timeout_again_keeps_worker(self, tmp_path) -> None:
        """续等再次超时：仍抛 TimeoutError，且不重启识别"""
        release = threading.Event()
        run_count = {"n": 0}

        class ControlledPipeline(FakePipeline):
            def run(self, *a, **kw):
                run_count["n"] += 1
                release.wait(5)
                return {"actions": [], "opers": []}

        backend = RecognitionBackend({})
        video = str(tmp_path / "b.mp4")
        with _mock_import(ControlledPipeline):
            with pytest.raises(TimeoutError):
                backend.recognize(video, str(tmp_path / "out"), {}, timeout=0.05)
            # 第 2 次（重试）续等旧线程，仍然超时
            with pytest.raises(TimeoutError):
                backend.recognize(video, str(tmp_path / "out"), {}, timeout=0.05)
        assert run_count["n"] == 1  # 未重启识别
        release.set()  # 收尾：放行残留 daemon 线程

    def test_worker_error_after_timeout_consumed_on_resume(self, tmp_path) -> None:
        """超时后续等：后台线程以异常结束时，重试调用取到该异常"""
        gate = threading.Event()
        run_count = {"n": 0}

        class FailingLaterPipeline(FakePipeline):
            def run(self, *a, **kw):
                run_count["n"] += 1
                gate.wait(5)
                raise FakeResourceError("资源在中途损坏")

        backend = RecognitionBackend({})
        video = str(tmp_path / "b.mp4")
        with _mock_import(FailingLaterPipeline):
            with pytest.raises(TimeoutError):
                backend.recognize(video, str(tmp_path / "out"), {}, timeout=0.05)
            # 0.2s 后放行识别线程（期间第 2 次调用已进入续等分支）
            threading.Timer(0.2, gate.set).start()
            # 第 2 次（重试）续等，取到线程内的确定性错误而非重启识别
            with pytest.raises(CopilotBackendError) as exc_info:
                backend.recognize(video, str(tmp_path / "out"), {}, timeout=5)
        assert run_count["n"] == 1
        assert exc_info.value.retryable is False
