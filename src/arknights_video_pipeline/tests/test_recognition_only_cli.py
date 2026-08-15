"""--recognize-only CLI 模式单元测试

验证 core/pipeline.py 中 --recognize-only 参数的：
- 参数解析（store_true）
- 与 --copilot-json 互斥校验
- style1 模式下不要求背景板图片
- 自动补全 skip_steps（formation/actions/track/compose）
- Pipeline 构造时传入正确的 skip_steps 与 background_image_path=None
- 批量识别逐文件调用 Pipeline
- 与 --dry-run 组合
- 与 --stage / --ocr / --resolution 组合透传

所有外部依赖（ConfigManager、setup_logger、Pipeline、validate_*）
均通过 unittest.mock 替换，测试完全封闭。
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest

from arknights_video_pipeline.core.pipeline import build_argparser, main


# ── Mock 目标常量 ──────────────────────────────────────────

_PIPE = "arknights_video_pipeline.core.pipeline"
_PIPE_CLASS = f"{_PIPE}.Pipeline"
_VALIDATE_VIDEO = f"{_PIPE}.validate_video_file"
_CONFIG_MGR = f"{_PIPE}.ConfigManager"
_SETUP_LOGGER = f"{_PIPE}.setup_logger"

_VIDEO_INFO = {
    "width": 1920,
    "height": 1080,
    "duration": 10.0,
    "file_path": "x",
    "file_size": 1000,
}

# --recognize-only 自动补全的跳过步骤集合
_EXPECTED_SKIP_STEPS = {"formation", "actions", "track", "compose"}


# ── 参数解析 ───────────────────────────────────────────────


class TestRecognizeOnlyArgParsing:
    """验证 build_argparser 的 --recognize-only 参数解析"""

    def test_recognize_only_flag_defaults_false(self) -> None:
        parser = build_argparser()
        args = parser.parse_args(["a.mp4", "-b", "bg.png"])
        assert args.recognize_only is False

    def test_recognize_only_flag_parsed_true(self) -> None:
        parser = build_argparser()
        args = parser.parse_args(["a.mp4", "--recognize-only"])
        assert args.recognize_only is True

    def test_recognize_only_with_multiple_videos(self) -> None:
        parser = build_argparser()
        args = parser.parse_args(
            ["a.mp4", "b.mp4", "--recognize-only"]
        )
        assert args.recognize_only is True
        assert args.video == ["a.mp4", "b.mp4"]


# ── 互斥校验 ───────────────────────────────────────────────


class TestRecognizeOnlyMutex:
    """验证 --recognize-only 与 --copilot-json 互斥"""

    def test_recognize_only_with_copilot_json_errors(self) -> None:
        """同时指定 --recognize-only 与 --copilot-json 时 parser.error 触发 SystemExit"""
        argv = ["main.py", "a.mp4", "--recognize-only", "--copilot-json", "c.json"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER):
            with pytest.raises(SystemExit):
                main()


# ── 背景板图片跳过校验 ─────────────────────────────────────


class TestRecognizeOnlySkipsBackgroundCheck:
    """验证 --recognize-only 时 style1 不要求背景板图片"""

    def test_style1_recognize_only_no_background_required(self) -> None:
        """style1 + --recognize-only 不报背景板缺失，Pipeline 被构造且 bg=None"""
        argv = ["main.py", "a.mp4", "--recognize-only"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.return_value = True
            with pytest.raises(SystemExit) as exc_info:
                main()
        # 成功执行（退出码 0），未因背景板缺失而 error
        assert exc_info.value.code == 0
        # Pipeline 构造时 background_image_path 为 None
        _, kwargs = mock_pipeline_cls.call_args
        assert kwargs.get("background_image_path") is None

    def test_style1_without_background_still_errors(self) -> None:
        """未启用 --recognize-only 时 style1 仍要求背景板图片（回归保护）"""
        argv = ["main.py", "a.mp4"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER):
            with pytest.raises(SystemExit):
                main()


# ── skip_steps 自动补全 ────────────────────────────────────


class TestRecognizeOnlySkipSteps:
    """验证 --recognize-only 自动补全 skip_steps"""

    def test_skip_steps_auto_completed(self) -> None:
        """--recognize-only 时 skip_steps 含 formation/actions/track/compose"""
        argv = ["main.py", "a.mp4", "--recognize-only"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.return_value = True
            with pytest.raises(SystemExit):
                main()
        _, kwargs = mock_pipeline_cls.call_args
        skip = kwargs.get("skip_steps", set())
        assert _EXPECTED_SKIP_STEPS <= skip

    def test_skip_steps_merges_with_explicit_skip(self) -> None:
        """--recognize-only 与显式 --skip-step 合并（用户额外指定仍生效）"""
        argv = [
            "main.py", "a.mp4", "--recognize-only", "--skip-step", "copilot",
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.return_value = True
            with pytest.raises(SystemExit):
                main()
        _, kwargs = mock_pipeline_cls.call_args
        skip = kwargs.get("skip_steps", set())
        # 四步必跳 + 用户显式跳过的 copilot
        assert _EXPECTED_SKIP_STEPS <= skip
        assert "copilot" in skip


# ── 批量识别 ───────────────────────────────────────────────


class TestRecognizeOnlyBatch:
    """验证 --recognize-only 批量识别"""

    def test_batch_multiple_videos_calls_pipeline_per_file(self) -> None:
        """多视频 --recognize-only 逐文件调用 Pipeline，退出码 0"""
        argv = ["main.py", "a.mp4", "b.mp4", "c.mp4", "--recognize-only"]
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

    def test_batch_all_files_use_recognize_skip_steps(self) -> None:
        """批量模式下每个文件的 Pipeline 都收到自动补全的 skip_steps"""
        argv = ["main.py", "a.mp4", "b.mp4", "--recognize-only"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.return_value = True
            with pytest.raises(SystemExit):
                main()
        for call in mock_pipeline_cls.call_args_list:
            _, kwargs = call
            skip = kwargs.get("skip_steps", set())
            assert _EXPECTED_SKIP_STEPS <= skip


# ── 与 --dry-run 组合 ──────────────────────────────────────


class TestRecognizeOnlyDryRun:
    """验证 --recognize-only 与 --dry-run 组合"""

    def test_dry_run_with_recognize_only_no_pipeline(self) -> None:
        """--recognize-only --dry-run 仅验证不实例化 Pipeline"""
        argv = ["main.py", "a.mp4", "--recognize-only", "--dry-run"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        mock_pipeline_cls.assert_not_called()


# ── 与 recognition 子参数组合 ──────────────────────────────


class TestRecognizeOnlyWithRecParams:
    """验证 --recognize-only 与 --stage / --ocr / --resolution 组合"""

    def test_stage_override_passed_to_config(self) -> None:
        """--stage 透传到 recognition 子配置（merge_cli_overrides 收到）"""
        argv = [
            "main.py", "a.mp4", "--recognize-only", "--stage", "2-10",
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR) as mock_cfg_mgr_cls, \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.return_value = True
            with pytest.raises(SystemExit):
                main()
        # merge_cli_overrides 被调用时 overrides 含 recognition.stage_override
        cfg_instance = mock_cfg_mgr_cls.return_value
        cfg_instance.merge_cli_overrides.assert_called_once()
        overrides = cfg_instance.merge_cli_overrides.call_args[0][0]
        rec_cfg = overrides.get("recognition", {})
        assert rec_cfg.get("stage_override") == "2-10"
