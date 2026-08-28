"""copilot 后端工厂与流水线步骤1 单元测试

验证 core/copilot_backend.py 的后端工厂与 core/pipeline.py 的
step_video_to_copilot 后端选择/重试逻辑。所有后端均为 Mock，测试完全封闭。
"""

from __future__ import annotations

import logging
from unittest import mock

import pytest

from arknights_video_pipeline.core.config import ConfigManager
from arknights_video_pipeline.core.copilot_backend import create_backend
from arknights_video_pipeline.core.exceptions import CopilotBackendError
from arknights_video_pipeline.core.pipeline import Pipeline

# step_video_to_copilot 在函数体内 from ... import create_backend，
# 因此 patch 目标为 copilot_backend 模块属性
_FACTORY = "arknights_video_pipeline.core.copilot_backend.create_backend"


class FakeBackend:
    """最小可用后端替身（仅记录调用，不执行真实识别）"""

    name = "fake"

    def __init__(self, config: dict):
        self.config = config
        self.calls = []

    def recognize(self, video_path, output_dir, config, timeout=None):
        self.calls.append((video_path, output_dir, config, timeout))
        return f"{output_dir}/fake_copilot_out.json"


# ── 工厂 ───────────────────────────────────────────────────


class TestCreateBackend:
    """验证后端工厂创建逻辑"""

    def test_create_recognition_backend(self) -> None:
        """recognition 后端返回 RecognitionBackend 实例"""
        backend = create_backend("recognition", {})
        assert backend.name == "recognition"

    def test_create_maa_backend(self) -> None:
        """maa 后端返回 MAABackend 实例"""
        backend = create_backend("maa", {})
        assert backend.name == "maa"

    def test_unknown_backend_raises(self) -> None:
        """未知后端标识抛出 ValueError"""
        with pytest.raises(ValueError, match="未知的 copilot 后端"):
            create_backend("unknown", {})

    def test_backend_implements_protocol(self) -> None:
        """后端实例满足 CopilotBackend Protocol 的结构要求"""
        from arknights_video_pipeline.core.copilot_backend import CopilotBackend

        backend = create_backend("recognition", {})
        assert isinstance(backend, CopilotBackend)


# ── 流水线步骤1：后端选择与重试 ───────────────────────────


class TestStepBackendSelection:
    """验证 step_video_to_copilot 按配置选择后端并重试"""

    def _make_pipeline(self, tmp_path) -> tuple[Pipeline, ConfigManager]:
        cfg = ConfigManager(str(tmp_path))
        pipe = Pipeline(
            video_path=str(tmp_path / "battle.mp4"),
            config_mgr=cfg,
            logger=logging.getLogger("test_backend"),
        )
        return pipe, cfg

    def test_uses_configured_backend(self, tmp_path) -> None:
        """copilot_backend 配置决定使用哪个后端"""
        pipe, cfg = self._make_pipeline(tmp_path)
        cfg.pipeline["copilot_backend"] = "recognition"
        fake = FakeBackend({})
        with mock.patch(_FACTORY, return_value=fake):
            result = pipe.step_video_to_copilot()
        assert result.status.name == "SUCCESS"
        assert fake.calls and fake.calls[0][0] == str(tmp_path / "battle.mp4")
        assert pipe.copilot_json_path is not None

    def test_retry_on_failure_then_success(self, tmp_path) -> None:
        """前两次失败后重试，第三次成功（退避等待以 mock 替换避免真实耗时）"""
        pipe, cfg = self._make_pipeline(tmp_path)
        cfg.pipeline["copilot_backend"] = "recognition"
        cfg.pipeline["copilot_max_retries"] = 3
        fake = FakeBackend({})
        fake.recognize = mock.Mock(
            side_effect=[
                RuntimeError("boom"),
                RuntimeError("boom"),
                f"{tmp_path}/ok.json",
            ]
        )
        with mock.patch(_FACTORY, return_value=fake):
            with mock.patch.object(Pipeline, "_interruptible_sleep"):
                result = pipe.step_video_to_copilot()
        assert result.status.name == "SUCCESS"
        assert fake.recognize.call_count == 3

    def test_all_retries_failed_raises(self, tmp_path) -> None:
        """全部重试失败时抛出 CopilotBackendError（包装为 PipelineStepError）"""
        pipe, cfg = self._make_pipeline(tmp_path)
        cfg.pipeline["copilot_backend"] = "recognition"
        cfg.pipeline["copilot_max_retries"] = 2
        fake = FakeBackend({})
        fake.recognize = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch(_FACTORY, return_value=fake):
            with mock.patch.object(Pipeline, "_interruptible_sleep"):
                with pytest.raises(Exception) as exc_info:
                    pipe.step_video_to_copilot()
        assert exc_info.value.step_name == "video_to_copilot"
        assert isinstance(exc_info.value.cause, CopilotBackendError)

    def test_non_retryable_error_fails_immediately(self, tmp_path) -> None:
        """retryable=False 的配置类错误不重试，直接失败"""
        pipe, cfg = self._make_pipeline(tmp_path)
        cfg.pipeline["copilot_backend"] = "recognition"
        cfg.pipeline["copilot_max_retries"] = 3
        fake = FakeBackend({})
        fake.recognize = mock.Mock(
            side_effect=CopilotBackendError("MAA路径未配置", retryable=False)
        )
        with mock.patch(_FACTORY, return_value=fake):
            with pytest.raises(Exception) as exc_info:
                pipe.step_video_to_copilot()
        assert isinstance(exc_info.value.cause, CopilotBackendError)
        # 配置类错误：仅调用一次，不做无意义的重试
        assert fake.recognize.call_count == 1

    def test_invalid_retries_config(self, tmp_path) -> None:
        """copilot_max_retries < 1 按 1 次尝试兜底执行，不再让步骤直接失败"""
        pipe, cfg = self._make_pipeline(tmp_path)
        cfg.pipeline["copilot_max_retries"] = 0
        fake = FakeBackend({})
        with mock.patch(_FACTORY, return_value=fake):
            result = pipe.step_video_to_copilot()
        assert result.status.name == "SUCCESS"
        # 兜底语义：只执行一次识别
        assert len(fake.calls) == 1


# ── 重试策略：错误分类 / 退避 / 取消 / 状态记录 ────────────


class TestRetryPolicy:
    """验证 step_video_to_copilot 重试策略的判定与可观测性"""

    def _make_pipeline(self, tmp_path, **pipeline_cfg) -> Pipeline:
        cfg = ConfigManager(str(tmp_path))
        cfg.pipeline["copilot_backend"] = "recognition"
        cfg.pipeline.update(pipeline_cfg)
        return Pipeline(
            video_path=str(tmp_path / "battle.mp4"),
            config_mgr=cfg,
            logger=logging.getLogger("test_retry"),
        )

    def test_deterministic_valueerror_not_retried(self, tmp_path) -> None:
        """ValueError（含 StageNotRecognizedError 等确定性失败）不重试"""
        pipe = self._make_pipeline(tmp_path, copilot_max_retries=3)
        fake = FakeBackend({})
        fake.recognize = mock.Mock(side_effect=ValueError("识别结果格式异常"))
        with mock.patch(_FACTORY, return_value=fake):
            with pytest.raises(Exception) as exc_info:
                pipe.step_video_to_copilot()
        # 原始异常语义保留，不被包装成"多次尝试后失败"
        assert isinstance(exc_info.value.cause, ValueError)
        assert fake.recognize.call_count == 1

    def test_unknown_error_type_not_retried(self, tmp_path) -> None:
        """未知异常类型保守不重试，避免为未知语义付出整次识别成本"""
        pipe = self._make_pipeline(tmp_path, copilot_max_retries=3)
        fake = FakeBackend({})
        fake.recognize = mock.Mock(side_effect=ImportError("缺依赖"))
        with mock.patch(_FACTORY, return_value=fake):
            with pytest.raises(Exception) as exc_info:
                pipe.step_video_to_copilot()
        assert isinstance(exc_info.value.cause, ImportError)
        assert fake.recognize.call_count == 1

    def test_exponential_backoff_sequence(self, tmp_path) -> None:
        """失败后的退避按 2/4/8 指数增长"""
        pipe = self._make_pipeline(tmp_path, copilot_max_retries=4)
        fake = FakeBackend({})
        fake.recognize = mock.Mock(
            side_effect=[RuntimeError("boom")] * 3 + [f"{tmp_path}/ok.json"]
        )
        delays: list[float] = []
        with mock.patch(_FACTORY, return_value=fake):
            with mock.patch.object(
                Pipeline,
                "_interruptible_sleep",
                side_effect=lambda s: delays.append(s),
            ):
                result = pipe.step_video_to_copilot()
        assert result.status.name == "SUCCESS"
        assert fake.recognize.call_count == 4
        assert delays == [2, 4, 8]

    def test_backoff_capped(self, tmp_path) -> None:
        """退避达到上限后不再增长（10s 封顶）"""
        pipe = self._make_pipeline(tmp_path, copilot_max_retries=6)
        fake = FakeBackend({})
        fake.recognize = mock.Mock(
            side_effect=[RuntimeError("boom")] * 5 + [f"{tmp_path}/ok.json"]
        )
        delays: list[float] = []
        with mock.patch(_FACTORY, return_value=fake):
            with mock.patch.object(
                Pipeline,
                "_interruptible_sleep",
                side_effect=lambda s: delays.append(s),
            ):
                result = pipe.step_video_to_copilot()
        assert result.status.name == "SUCCESS"
        assert delays == [2, 4, 8, 10, 10]

    def test_cancel_before_retry_stops_attempts(self, tmp_path) -> None:
        """重试发起前检测到取消：不再发起后续识别尝试"""
        pipe = self._make_pipeline(tmp_path, copilot_max_retries=5)
        fake = FakeBackend({})
        calls = {"n": 0}

        def _fail(*args, **kwargs):
            calls["n"] += 1
            raise RuntimeError("boom")

        def _cancelled() -> bool:
            # 首次尝试失败后置位取消标志
            return calls["n"] >= 1

        fake.recognize = mock.Mock(side_effect=_fail)
        pipe._is_cancelled = _cancelled
        with mock.patch(_FACTORY, return_value=fake):
            with mock.patch.object(Pipeline, "_interruptible_sleep"):
                with pytest.raises(Exception) as exc_info:
                    pipe.step_video_to_copilot()
        assert "取消" in str(exc_info.value.cause)
        assert fake.recognize.call_count == 1

    def test_interruptible_sleep_raises_on_cancel(self, tmp_path) -> None:
        """退避等待期间取消请求立即中断（不可重试错误）"""
        pipe = self._make_pipeline(tmp_path)
        pipe._is_cancelled = lambda: True
        with pytest.raises(CopilotBackendError) as exc_info:
            pipe._interruptible_sleep(10)
        assert exc_info.value.retryable is False

    def test_interruptible_sleep_completes_when_not_cancelled(self, tmp_path) -> None:
        """未取消时退避等待正常结束"""
        pipe = self._make_pipeline(tmp_path)
        pipe._is_cancelled = lambda: False
        pipe._interruptible_sleep(0.1)  # 不抛异常即通过

    def test_retry_metadata_recorded_on_success(self, tmp_path) -> None:
        """重试轨迹记录进 StepResult.metadata，报告可观测"""
        pipe = self._make_pipeline(tmp_path, copilot_max_retries=2)
        fake = FakeBackend({})
        fake.recognize = mock.Mock(
            side_effect=[RuntimeError("boom-1"), f"{tmp_path}/ok.json"]
        )
        with mock.patch(_FACTORY, return_value=fake):
            with mock.patch.object(Pipeline, "_interruptible_sleep"):
                result = pipe.step_video_to_copilot()
        assert result.status.name == "SUCCESS"
        assert result.metadata["retry"]["attempts"] == 2
        assert result.metadata["retry"]["errors"] == ["第1次: boom-1"]
        assert any("重试" in w for w in result.warnings)

    def test_retry_metadata_recorded_on_failure(self, tmp_path) -> None:
        """全部失败时同样记录每次失败的轨迹（排障可观测）"""
        pipe = self._make_pipeline(tmp_path, copilot_max_retries=2)
        fake = FakeBackend({})
        fake.recognize = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch(_FACTORY, return_value=fake):
            with mock.patch.object(Pipeline, "_interruptible_sleep"):
                with pytest.raises(Exception):
                    pipe.step_video_to_copilot()
        step = pipe.report.steps[-1]
        assert step.metadata["retry"]["attempts"] == 2
        assert step.metadata["retry"]["failed"] is True
        assert len(step.metadata["retry"]["errors"]) == 2
