"""MAA 后端包装单元测试

验证 core/maa_backend.py 对 video_to_copilot 的包装：
- 配置合并（构造配置 + 调用配置）
- maa_path / output_dir 透传
- 其余键透传给 video_to_copilot
- validate_maa_path 失败时传播异常
"""

from __future__ import annotations

from unittest import mock

import pytest

from arknights_video_pipeline.core.maa_backend import MAABackend

_MB = "arknights_video_pipeline.core.maa_backend"


class TestMAABackend:
    """验证 MAABackend.recognize 包装行为"""

    def test_wraps_video_to_copilot(self, tmp_path) -> None:
        """成功时返回 video_to_copilot 的路径，参数正确透传"""
        backend = MAABackend({"maa_path": "C:/maa", "extra": 1})
        with mock.patch(f"{_MB}.validate_maa_path", return_value=True), \
             mock.patch(f"{_MB}.video_to_copilot", return_value="out.json") as vtc:
            result = backend.recognize(
                video_path="b.mp4",
                output_dir=str(tmp_path / "out"),
                config={"extra": 2, "timeout_factor": 3},
            )
        assert result == "out.json"
        vtc.assert_called_once()
        args, kwargs = vtc.call_args
        assert args[0] == "b.mp4"
        sub_config = args[1]
        assert sub_config["maa_path"] == "C:/maa"
        assert sub_config["output_dir"] == str(tmp_path / "out")
        # 调用配置覆盖构造配置；MAA 消费键不重复注入
        assert sub_config["extra"] == 2
        assert sub_config["timeout_factor"] == 3
        assert kwargs["timeout"] is None

    def test_timeout_passed_through(self, tmp_path) -> None:
        """timeout 参数透传给 video_to_copilot"""
        backend = MAABackend({})
        with mock.patch(f"{_MB}.validate_maa_path", return_value=True), \
             mock.patch(f"{_MB}.video_to_copilot", return_value="out.json") as vtc:
            backend.recognize(
                video_path="b.mp4",
                output_dir=str(tmp_path / "out"),
                config={"maa_path": "C:/maa"},
                timeout=42,
            )
        assert vtc.call_args.kwargs["timeout"] == 42

    def test_validate_maa_path_error_propagates(self, tmp_path) -> None:
        """MAA 路径校验失败（ValueError）原样传播"""
        backend = MAABackend({})
        with mock.patch(f"{_MB}.validate_maa_path", side_effect=ValueError("MAA路径未配置")), \
             mock.patch(f"{_MB}.video_to_copilot") as vtc:
            with pytest.raises(ValueError, match="MAA路径未配置"):
                backend.recognize(
                    video_path="b.mp4",
                    output_dir=str(tmp_path / "out"),
                    config={},
                )
        vtc.assert_not_called()
