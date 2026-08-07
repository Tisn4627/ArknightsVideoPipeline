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
        """前两次失败后重试，第三次成功"""
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
            with pytest.raises(Exception) as exc_info:
                pipe.step_video_to_copilot()
        assert exc_info.value.step_name == "video_to_copilot"
        assert isinstance(exc_info.value.cause, CopilotBackendError)

    def test_invalid_retries_config(self, tmp_path) -> None:
        """copilot_max_retries < 1 直接报错"""
        pipe, cfg = self._make_pipeline(tmp_path)
        cfg.pipeline["copilot_max_retries"] = 0
        with mock.patch(_FACTORY, return_value=FakeBackend({})):
            with pytest.raises(Exception) as exc_info:
                pipe.step_video_to_copilot()
        assert "copilot_max_retries" in str(exc_info.value)
