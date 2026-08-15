"""自定义作业 JSON 功能单元测试

验证 core/pipeline.py 中 --copilot-json 相关逻辑：
- match_custom_copilot_jsons 匹配规则（1v1 直接绑定 / 按文件名匹配 / 未匹配忽略）
- --copilot-json 参数解析
- Pipeline 传入自定义 JSON 时跳过步骤1（视频识别），其余步骤照常执行
- main() 将匹配结果透传给 Pipeline
- JSON 文件不存在时 parser.error

外部依赖（ConfigManager、setup_logger、validate_*、步骤方法）均通过
unittest.mock 替换，测试完全封闭、不触碰文件系统或 ffmpeg。
"""

from __future__ import annotations

import logging
import os
import sys
from unittest import mock

import pytest

from arknights_video_pipeline.core.pipeline import (
    Pipeline,
    build_argparser,
    main,
    match_custom_copilot_jsons,
)
from arknights_video_pipeline.core.types import StepResult, StepStatus

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


# ── 文件名匹配规则 ─────────────────────────────────────────


class TestMatchCustomCopilotJsons:
    """验证 match_custom_copilot_jsons 的匹配规则"""

    def test_single_video_single_json_direct_binding(self) -> None:
        """单视频+单JSON直接绑定，无任何提示信息"""
        mapping, notes = match_custom_copilot_jsons(["v.mp4"], ["job.json"])
        assert mapping == {os.path.abspath("v.mp4"): os.path.abspath("job.json")}
        assert notes == []

    def test_no_json_returns_empty(self) -> None:
        """未提供 JSON 时返回空映射"""
        mapping, notes = match_custom_copilot_jsons(["v.mp4"], [])
        assert mapping == {}
        assert notes == []

    def test_multiple_match_by_filename(self) -> None:
        """多视频多JSON按文件名（去扩展名）匹配，并给出匹配逻辑与测试功能提示"""
        mapping, notes = match_custom_copilot_jsons(
            ["a.mp4", "b.mp4"], ["a.json", "b.json"]
        )
        assert mapping == {
            os.path.abspath("a.mp4"): os.path.abspath("a.json"),
            os.path.abspath("b.mp4"): os.path.abspath("b.json"),
        }
        assert any("按文件名" in n for n in notes)
        assert any("测试功能" in n for n in notes)

    def test_multiple_videos_single_json_matches_by_filename(self) -> None:
        """多视频+单JSON按文件名匹配，仅同名视频绑定"""
        mapping, _ = match_custom_copilot_jsons(
            ["a.mp4", "b.mp4"], ["a.json"]
        )
        assert mapping == {os.path.abspath("a.mp4"): os.path.abspath("a.json")}

    def test_single_video_multiple_jsons_matches_by_filename(self) -> None:
        """单视频+多JSON按文件名匹配，仅同名 JSON 绑定"""
        mapping, _ = match_custom_copilot_jsons(
            ["a.mp4"], ["a.json", "b.json"]
        )
        assert mapping == {os.path.abspath("a.mp4"): os.path.abspath("a.json")}

    def test_match_is_case_insensitive(self) -> None:
        """文件名匹配不区分大小写（Windows 语义）"""
        mapping, _ = match_custom_copilot_jsons(
            ["A.MP4", "b.mp4"], ["a.json", "b.json"]
        )
        assert mapping == {
            os.path.abspath("A.MP4"): os.path.abspath("a.json"),
            os.path.abspath("b.mp4"): os.path.abspath("b.json"),
        }

    def test_unmatched_json_ignored_with_note(self) -> None:
        """未匹配到任何视频的 JSON 被忽略，并给出提示"""
        mapping, notes = match_custom_copilot_jsons(
            ["a.mp4"], ["a.json", "orphan.json"]
        )
        assert list(mapping.values()) == [os.path.abspath("a.json")]
        assert any("未匹配" in n for n in notes)

    def test_unmatched_video_not_in_mapping(self) -> None:
        """未绑定 JSON 的视频不在映射中（仍执行正常识别）"""
        mapping, _ = match_custom_copilot_jsons(
            ["a.mp4", "b.mp4"], ["a.json"]
        )
        assert os.path.abspath("b.mp4") not in mapping


# ── 参数解析 ───────────────────────────────────────────────


class TestCopilotJsonArgParsing:
    """验证 --copilot-json 参数解析"""

    def test_copilot_json_accepts_multiple_values(self) -> None:
        parser = build_argparser()
        args = parser.parse_args(
            ["a.mp4", "--copilot-json", "j1.json", "j2.json"]
        )
        assert args.copilot_json == ["j1.json", "j2.json"]

    def test_copilot_json_default_empty(self) -> None:
        parser = build_argparser()
        args = parser.parse_args(["a.mp4"])
        assert args.copilot_json == []


# ── Pipeline 跳过识别 ──────────────────────────────────────


def _make_pipeline(tmp_path, json_path=None, on_start=None, on_finish=None) -> Pipeline:
    """构造一个步骤方法均已 mock 的 Pipeline 实例

    步骤2-5 的 mock 通过 side_effect 模拟真实步骤的收尾行为
    （将结果追加到 report.steps），使 run() 的报告结构与真实一致。
    """
    logger = logging.getLogger("test_custom_copilot_json")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())
    config = mock.MagicMock()
    config.project_dir = str(tmp_path)
    config.get_output_dir.return_value = str(tmp_path)
    pipeline = Pipeline(
        video_path=str(tmp_path / "a.mp4"),
        config_mgr=config,
        logger=logger,
        copilot_json_path=json_path,
        on_step_start=on_start,
        on_step_finish=on_finish,
    )
    for name in (
        "step_formation_to_text",
        "step_actions_to_text",
        "step_track_startbutton",
        "step_video_compose",
    ):
        result = StepResult(
            name=name, description=name, status=StepStatus.SUCCESS
        )

        def _fake_step(_p=pipeline, _r=result) -> StepResult:
            _p.report.steps.append(_r)
            return _r

        setattr(pipeline, name, mock.MagicMock(side_effect=_fake_step))
    return pipeline


class TestPipelineCustomJson:
    """验证 Pipeline 使用自定义作业 JSON 时跳过步骤1"""

    def test_custom_json_skips_recognition(self, tmp_path) -> None:
        """步骤1不调用识别方法，标记成功（使用自定义作业JSON），其余步骤照常执行"""
        jp = tmp_path / "a.json"
        jp.write_text('{"groups": []}', encoding="utf-8")
        started: list = []
        finished: list = []
        pipeline = _make_pipeline(
            tmp_path, str(jp),
            on_start=lambda key, desc: started.append((key, desc)),
            on_finish=lambda key, ok, el, warns: finished.append((key, ok)),
        )
        pipeline.step_video_to_copilot = mock.MagicMock()

        result = pipeline.run()

        assert result is True
        pipeline.step_video_to_copilot.assert_not_called()
        assert pipeline.copilot_json_path == str(jp)
        # 步骤1记录为成功且描述为「使用自定义作业JSON」，输出文件为自定义 JSON
        step1 = pipeline.report.steps[0]
        assert step1.name == "video_to_copilot"
        assert step1.status == StepStatus.SUCCESS
        assert step1.description == "使用自定义作业JSON"
        assert step1.output_files == [str(jp)]
        # 5 个步骤全部成功（步骤2-5 正常执行）
        assert len(pipeline.report.steps) == 5
        assert all(s.status == StepStatus.SUCCESS for s in pipeline.report.steps)
        # 步骤1 开始/结束回调照常触发
        assert started[0] == ("copilot", "使用自定义作业JSON")
        assert finished[0] == ("copilot", True)

    def test_missing_custom_json_falls_back_to_recognition(self, tmp_path) -> None:
        """自定义 JSON 文件不存在时回退到正常视频识别"""
        missing = tmp_path / "missing.json"
        pipeline = _make_pipeline(tmp_path, str(missing))
        pipeline.step_video_to_copilot = mock.MagicMock(return_value=StepResult(
            name="video_to_copilot", description="视频转作业JSON",
            status=StepStatus.SUCCESS,
        ))

        result = pipeline.run()

        assert result is True
        pipeline.step_video_to_copilot.assert_called_once()

    def test_skip_step_takes_precedence(self, tmp_path) -> None:
        """--skip-step copilot 优先于自定义 JSON：步骤1标记为已跳过"""
        jp = tmp_path / "a.json"
        jp.write_text("{}", encoding="utf-8")
        pipeline = _make_pipeline(tmp_path, str(jp))
        pipeline.skip_steps = {"copilot"}
        pipeline.step_video_to_copilot = mock.MagicMock()

        result = pipeline.run()

        assert result is True
        pipeline.step_video_to_copilot.assert_not_called()
        assert pipeline.report.steps[0].status == StepStatus.SKIPPED


# ── main() 透传 ────────────────────────────────────────────


class TestMainCustomJson:
    """验证 main() 将匹配结果透传给 Pipeline"""

    def test_main_passes_custom_json_to_pipeline(self, tmp_path) -> None:
        """单视频+单JSON时 Pipeline 收到 copilot_json_path"""
        video = tmp_path / "a.mp4"
        video.write_bytes(b"x")
        jp = tmp_path / "a.json"
        jp.write_text("{}", encoding="utf-8")
        argv = [
            "main.py", str(video), "--style", "style2",
            "--copilot-json", str(jp),
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.return_value = True
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        _, kwargs = mock_pipeline_cls.call_args
        assert kwargs["copilot_json_path"] == str(jp)

    def test_main_missing_custom_json_errors(self, tmp_path) -> None:
        """指定的 JSON 不存在时 parser.error 退出（退出码 2）"""
        video = tmp_path / "a.mp4"
        video.write_bytes(b"x")
        argv = [
            "main.py", str(video), "--style", "style2",
            "--copilot-json", str(tmp_path / "missing.json"),
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls, \
             pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2
        mock_pipeline_cls.assert_not_called()

    def test_main_non_json_custom_file_errors(self, tmp_path) -> None:
        """指定的自定义文件非 .json 扩展名时 parser.error 退出"""
        video = tmp_path / "a.mp4"
        video.write_bytes(b"x")
        txt = tmp_path / "a.txt"
        txt.write_text("{}", encoding="utf-8")
        argv = [
            "main.py", str(video), "--style", "style2",
            "--copilot-json", str(txt),
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls, \
             pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2
        mock_pipeline_cls.assert_not_called()

    def test_main_unmatched_video_gets_no_json(self, tmp_path) -> None:
        """多视频时未匹配的 JSON 不传给对应视频（回退正常识别）"""
        v1 = tmp_path / "a.mp4"
        v1.write_bytes(b"x")
        v2 = tmp_path / "b.mp4"
        v2.write_bytes(b"x")
        jp = tmp_path / "a.json"
        jp.write_text("{}", encoding="utf-8")
        argv = [
            "main.py", str(v1), str(v2), "--style", "style2",
            "--copilot-json", str(jp),
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch(_CONFIG_MGR), \
             mock.patch(_SETUP_LOGGER), \
             mock.patch(_VALIDATE_VIDEO, return_value=_VIDEO_INFO), \
             mock.patch(_PIPE_CLASS) as mock_pipeline_cls:
            mock_pipeline_cls.return_value.run.return_value = True
            with pytest.raises(SystemExit):
                main()
        assert mock_pipeline_cls.call_count == 2
        # 文件1绑定 JSON，文件2 未绑定（copilot_json_path=None）
        kwargs1 = mock_pipeline_cls.call_args_list[0].kwargs
        kwargs2 = mock_pipeline_cls.call_args_list[1].kwargs
        assert kwargs1["copilot_json_path"] == str(jp)
        assert kwargs2["copilot_json_path"] is None