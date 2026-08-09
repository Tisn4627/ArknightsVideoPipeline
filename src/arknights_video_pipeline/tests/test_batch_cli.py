"""批量 CLI 处理单元测试

验证 core/pipeline.py 中 main() 的批量视频处理逻辑：
- 命令行参数解析（nargs="*" 支持多视频）
- --init-config 早返回
- 无视频时 parser.error
- 批量执行：逐文件验证、Pipeline 调用、异常捕获、退出码
- --dry-run 验证模式

所有外部依赖（ConfigManager、setup_logger、Pipeline、validate_*）
均通过 unittest.mock 替换，测试完全封闭、不触碰文件系统或 ffmpeg。
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

from arknights_video_pipeline.core.exceptions import VideoValidationError
from arknights_video_pipeline.core.pipeline import _init_config, build_argparser, main


# ── Mock 目标常量（提升可读性） ────────────────────────────

_PIPE = "arknights_video_pipeline.core.pipeline"
_PIPE_CLASS = f"{_PIPE}.Pipeline"
_VALIDATE_VIDEO = f"{_PIPE}.validate_video_file"
_VALIDATE_IMAGE = f"{_PIPE}.validate_image_file"
_INIT_CONFIG = f"{_PIPE}._init_config"
_CONFIG_MGR = f"{_PIPE}.ConfigManager"
_SETUP_LOGGER = f"{_PIPE}.setup_logger"

# validate_video_file 的真实返回结构
_VIDEO_INFO = {
    "width": 1920,
    "height": 1080,
    "duration": 10.0,
    "file_path": "x",
    "file_size": 1000,
}


# ── 参数解析 ───────────────────────────────────────────────


class TestVideoArgParsing:
    """验证 build_argparser 的 video 参数解析"""

    def test_video_arg_accepts_multiple_values(self) -> None:
        """video 参数通过 nargs='*' 接受多个值并保持给定顺序"""
        parser = build_argparser()
        args = parser.parse_args(["a.mp4", "b.mp4", "c.mp4"])
        assert args.video == ["a.mp4", "b.mp4", "c.mp4"]

    def test_video_arg_default_empty_list(self) -> None:
        """无位置参数时 video 默认为空列表（而非 None）"""
        parser = build_argparser()
        args = parser.parse_args(["--init-config", "all"])
        assert args.video == []

    def test_single_video_backward_compatible(self) -> None:
        """单个视频路径仍然正常解析为长度 1 的列表"""
        parser = build_argparser()
        args = parser.parse_args(["a.mp4"])
        assert args.video == ["a.mp4"]


# ── main() 入口逻辑 ────────────────────────────────────────


class TestMainEntrypoint:
    """验证 main() 入口的分支逻辑"""

    def test_main_no_videos_calls_parser_error(self) -> None:
        """无视频且无 --init-config 时调用 parser.error 触发 SystemExit"""
        with mock.patch.object(sys, "argv", ["main.py"]), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER):
            with pytest.raises(SystemExit):
                main()

    def test_main_init_config_returns_early(self) -> None:
        """--init-config 时调用 _init_config 并提前返回，不实例化 Pipeline"""
        with mock.patch.object(sys, "argv", ["main.py", "--init-config", "all"]), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_INIT_CONFIG) as mock_init, \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            main()
        mock_init.assert_called_once_with("all")
        mock_pipeline_cls.assert_not_called()


# ── _init_config FFmpeg 预应用 ─────────────────────────────


class TestInitConfigFfmpegPreApply:
    """验证 _init_config 在导入 video_compose（movielite 导入时检查 ffmpeg）前
    先应用 FFmpeg 路径配置，并在导入失败时优雅跳过而非崩溃"""

    def test_init_config_compose_writes_config(self, tmp_path, monkeypatch) -> None:
        """无系统 FFmpeg 时（仅自定义 ffmpeg 目录），--init-config compose 仍可生成"""
        monkeypatch.setattr(
            "arknights_video_pipeline.core.pipeline.PROJECT_ROOT", str(tmp_path)
        )
        result = _init_config("compose")
        assert result == [
            os.path.join(str(tmp_path), "config", "video_compose/style1.json")
        ]
        assert os.path.exists(result[0])

    def test_init_config_skips_module_on_import_runtime_error(
        self, tmp_path, monkeypatch
    ) -> None:
        """导入时抛 RuntimeError（movielite 检查 ffmpeg 缺失）按跳过处理，不崩溃"""
        monkeypatch.setattr(
            "arknights_video_pipeline.core.pipeline.PROJECT_ROOT", str(tmp_path)
        )
        with mock.patch(
            f"{_PIPE}.ensure_ffmpeg_in_path"
        ) as mock_ensure, \
             mock.patch(f"{_PIPE}.set_ffmpeg_config") as mock_set, \
             mock.patch(
                 f"{_PIPE}.importlib.import_module",
                 side_effect=RuntimeError("Could not find required command(s): ffmpeg"),
             ):
            result = _init_config("all")
        mock_ensure.assert_called_once()
        mock_set.assert_called_once()
        assert result == []


# ── 批量执行 ───────────────────────────────────────────────


class TestMainBatchExecution:
    """验证 main() 批量执行循环"""

    def test_main_batch_all_success_exits_zero(self) -> None:
        """3 个视频全部成功时退出码为 0，Pipeline 被调用 3 次"""
        argv = ["main.py", "a.mp4", "b.mp4", "c.mp4", "--style", "style2"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.return_value = True
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        assert mock_pipeline_cls.call_count == 3

    def test_main_batch_middle_failure_exits_one(self) -> None:
        """中间文件 Pipeline.run() 返回 False 时退出码为 1，Pipeline 仍调用 3 次"""
        argv = ["main.py", "a.mp4", "b.mp4", "c.mp4", "--style", "style2"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.side_effect = [True, False, True]
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert mock_pipeline_cls.call_count == 3

    def test_main_batch_validation_skip_continues(self) -> None:
        """中间文件验证失败（VideoValidationError）时跳过该文件，Pipeline 仅对有效文件调用"""
        argv = ["main.py", "a.mp4", "b.mp4", "c.mp4", "--style", "style2"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, side_effect=[
                 _VIDEO_INFO,
                 VideoValidationError("bad file"),
                 _VIDEO_INFO,
             ]) as mock_validate, \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.return_value = True
            with pytest.raises(SystemExit) as exc_info:
                main()
        # 2 个文件成功（文件 1 和 3），总 3 个 → 退出码 1
        assert exc_info.value.code == 1
        assert mock_validate.call_count == 3
        # 文件 2 验证失败被跳过，Pipeline 仅被调用 2 次
        assert mock_pipeline_cls.call_count == 2

    def test_main_batch_exception_caught_continues(self) -> None:
        """Pipeline 构造函数对文件 2 抛异常时被捕获，继续处理文件 3"""
        argv = ["main.py", "a.mp4", "b.mp4", "c.mp4", "--style", "style2"]
        good_instance = mock.MagicMock()
        good_instance.run.return_value = True
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS, side_effect=[
                 good_instance,
                 RuntimeError("constructor boom"),
                 good_instance,
             ]) as mock_pipeline_cls:
            with pytest.raises(SystemExit) as exc_info:
                main()
        # 文件 1 和 3 成功（各 +1），文件 2 异常被跳过 → 2/3 → 退出码 1
        assert exc_info.value.code == 1
        # Pipeline 构造函数对所有 3 个文件都尝试了
        assert mock_pipeline_cls.call_count == 3


# ── Dry-run 模式 ───────────────────────────────────────────


class TestMainDryRun:
    """验证 --dry-run 模式：仅验证不执行"""

    def test_dry_run_all_valid_exits_zero(self) -> None:
        """所有视频验证通过时 dry-run 退出码为 0，不实例化 Pipeline"""
        argv = ["main.py", "a.mp4", "b.mp4", "--style", "style2", "--dry-run"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        mock_pipeline_cls.assert_not_called()

    def test_dry_run_one_invalid_exits_one(self) -> None:
        """中间文件验证失败时 dry-run 退出码为 1，不实例化 Pipeline"""
        argv = ["main.py", "a.mp4", "b.mp4", "c.mp4", "--style", "style2", "--dry-run"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, side_effect=[
                 _VIDEO_INFO,
                 VideoValidationError("bad file"),
                 _VIDEO_INFO,
             ]), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        mock_pipeline_cls.assert_not_called()
