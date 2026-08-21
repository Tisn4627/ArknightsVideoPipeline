"""MAA 后端包装单元测试

验证 core/maa_backend.py 对 video_to_copilot 的包装：
- 配置合并（构造配置 + 调用配置）
- maa_path / output_dir 透传
- 其余键透传给 video_to_copilot
- validate_maa_path 失败时包装为不可重试的 CopilotBackendError
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from arknights_video_pipeline.core.exceptions import CopilotBackendError
from arknights_video_pipeline.core.maa_backend import MAABackend

_MB = "arknights_video_pipeline.core.maa_backend"


class TestShortPathConversion:
    """MAA 后端的非 ASCII 路径 8.3 短路径转换（Windows 已知敏感区）"""

    def test_ascii_path_yields_existing_path(self, tmp_path) -> None:
        """纯 ASCII 路径：转换结果必须指向真实存在的文件"""
        from arknights_video_pipeline.core.video_to_copilot import (
            _get_short_path_name,
        )

        target = tmp_path / "v.mp4"
        target.write_bytes(b"")
        out = _get_short_path_name(str(target))
        assert isinstance(out, str) and out
        # 转换失败时回退原路径，两种情况都应存在
        assert os.path.exists(out)

    def test_non_ascii_path_never_crashes(self, tmp_path) -> None:
        """非 ASCII 路径：8.3 被禁用时必须回退原路径而非抛异常"""
        from arknights_video_pipeline.core.video_to_copilot import (
            _get_short_path_name,
        )

        sub = tmp_path / "中文目录"
        sub.mkdir()
        target = sub / "视频.mp4"
        target.write_bytes(b"")
        out = _get_short_path_name(str(target))
        assert isinstance(out, str)
        assert os.path.exists(out)

    def test_is_ascii_path(self) -> None:
        from arknights_video_pipeline.core.video_to_copilot import (
            _is_ascii_path,
        )

        assert _is_ascii_path("C:/video/a.mp4")
        assert not _is_ascii_path("C:/视频/a.mp4")


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
        """MAA 路径校验失败包装为不可重试的 CopilotBackendError"""
        backend = MAABackend({})
        with mock.patch(f"{_MB}.validate_maa_path", side_effect=ValueError("MAA路径未配置")), \
             mock.patch(f"{_MB}.video_to_copilot") as vtc:
            with pytest.raises(CopilotBackendError, match="MAA路径未配置") as exc_info:
                backend.recognize(
                    video_path="b.mp4",
                    output_dir=str(tmp_path / "out"),
                    config={},
                )
            # 配置类错误：重试无意义，标记为不可重试
            assert exc_info.value.retryable is False
        vtc.assert_not_called()

    def test_validate_maa_path_filenotfound_wrapped(self, tmp_path) -> None:
        """FileNotFoundError（如 MAA 路径缺失）同样包装为不可重试错误"""
        backend = MAABackend({})
        with mock.patch(
            f"{_MB}.validate_maa_path",
            side_effect=FileNotFoundError("MAA目录不存在"),
        ), mock.patch(f"{_MB}.video_to_copilot") as vtc:
            with pytest.raises(CopilotBackendError) as exc_info:
                backend.recognize(
                    video_path="b.mp4",
                    output_dir=str(tmp_path / "out"),
                    config={},
                )
            assert exc_info.value.retryable is False
        vtc.assert_not_called()

    def test_video_to_copilot_validation_error_wrapped(self, tmp_path) -> None:
        """video_to_copilot 内部抛出的配置类错误同样包装为不可重试"""
        backend = MAABackend({})
        with mock.patch(f"{_MB}.validate_maa_path", return_value=True), \
             mock.patch(
                 f"{_MB}.video_to_copilot",
                 side_effect=FileNotFoundError("MaaCore.dll 不存在"),
             ) as vtc:
            with pytest.raises(CopilotBackendError) as exc_info:
                backend.recognize(
                    video_path="b.mp4",
                    output_dir=str(tmp_path / "out"),
                    config={},
                )
            assert exc_info.value.retryable is False
        vtc.assert_called_once()
