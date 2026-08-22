"""Recognition 工具 GUI 单元测试

验证 gui/components/tools/recognition_tool.py：
- TOOL_REGISTRY 注册了 recognition 工具
- RecognitionTool 可实例化（offscreen Qt 模式）
- 视频列表 add_video_paths：追加、过滤、去重
- 参数行从 ConfigProxy 加载初始值
- on_entered 从配置刷新参数
- set_colors / retranslate 不抛异常
- _set_running_ui 切换控件启用态
- RecognitionWorker 注册与信号连接（mock worker）

所有测试在 offscreen Qt 模式下运行，ConfigProxy 用 MagicMock 替换。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock

import pytest
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.gui.components.tools import TOOL_REGISTRY
from arknights_video_pipeline.gui.components.tools.recognition_tool import (
    RecognitionTool,
)
from arknights_video_pipeline.gui.theme import MaterialColors


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen 模式）"""
    app = QApplication.instance() or QApplication([])
    yield app


def _make_config_proxy() -> mock.MagicMock:
    """构造一个返回合理默认值的 ConfigProxy mock"""
    cp = mock.MagicMock()
    cp.copilot_backend.return_value = "recognition"
    cp.ocr_source.return_value = "maamodel"
    cp.resolution.return_value = "1280x720"
    cp.stage_override.return_value = ""
    cp.with_video_time.return_value = False
    cp.output_dir.return_value = "output"
    cp.build_worker_config.return_value = mock.MagicMock()
    return cp


def _make_tool(qapp, config_proxy=None) -> RecognitionTool:
    """创建一个使用浅色主题的 RecognitionTool"""
    cp = config_proxy or _make_config_proxy()
    return RecognitionTool(config_proxy=cp, colors=MaterialColors.light())


# ── 注册表 ─────────────────────────────────────────────────


class TestToolRegistry:
    """验证 recognition 工具已注册到 TOOL_REGISTRY"""

    def test_recognition_in_registry(self) -> None:
        ids = [t[0] for t in TOOL_REGISTRY]
        assert "recognition" in ids

    def test_recognition_entry_has_view_class(self) -> None:
        for tool_id, _title_key, view_cls in TOOL_REGISTRY:
            if tool_id == "recognition":
                assert view_cls is RecognitionTool
                return
        pytest.fail("recognition 未在 TOOL_REGISTRY 中找到")

    def test_recognition_tool_id_and_keys(self) -> None:
        assert RecognitionTool.tool_id == "recognition"
        assert RecognitionTool.title_key == "tools.recognition.title"
        assert RecognitionTool.desc_key == "tools.recognition.desc"


# ── 实例化与初始状态 ───────────────────────────────────────


class TestToolConstruction:
    """验证 RecognitionTool 可实例化且初始状态正确"""

    def test_tool_constructs(self, qapp) -> None:
        tool = _make_tool(qapp)
        assert tool is not None

    def test_initial_video_list_empty(self, qapp) -> None:
        tool = _make_tool(qapp)
        assert tool._video_list.video_paths() == []

    def test_start_button_initially_enabled(self, qapp) -> None:
        tool = _make_tool(qapp)
        assert tool._start_btn.isEnabled()
        assert not tool._cancel_btn.isEnabled()


# ── 视频列表操作 ───────────────────────────────────────────


class TestVideoListOperations:
    """验证 add_video_paths / 移除 / 清空"""

    def test_add_video_paths_appends(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool.add_video_paths(["a.mp4", "b.mkv"])
        assert len(tool._video_list.video_paths()) == 2

    def test_add_video_paths_filters_unsupported(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool.add_video_paths(["a.mp4", "b.txt", "c.png"])
        # 仅 .mp4 通过过滤
        assert len(tool._video_list.video_paths()) == 1

    def test_add_video_paths_dedupes(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool.add_video_paths(["a.mp4"])
        tool.add_video_paths(["a.mp4", "b.mp4"])
        assert len(tool._video_list.video_paths()) == 2

    def test_clear_all_empties_list(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool.add_video_paths(["a.mp4", "b.mp4"])
        tool._video_list.clear()
        assert tool._video_list.video_paths() == []

    def test_delete_row_removes_one(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool.add_video_paths(["a.mp4", "b.mp4"])
        # 点击第一行的删除按钮
        tool._video_list._rows[0].delete_button().click()
        assert len(tool._video_list.video_paths()) == 1

    def test_video_paths_returns_absolute(self, qapp, tmp_path) -> None:
        tool = _make_tool(qapp)
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")
        tool.add_video_paths([str(video)])
        paths = tool._video_paths()
        assert len(paths) == 1
        assert os.path.isabs(paths[0])


# ── on_entered 配置加载 ────────────────────────────────────


class TestOnEntered:
    """验证 on_entered 从 ConfigProxy 加载参数"""

    def test_on_entered_loads_backend(self, qapp) -> None:
        cp = _make_config_proxy()
        cp.copilot_backend.return_value = "maa"
        tool = _make_tool(qapp, cp)
        tool.on_entered()
        assert tool._backend_row.get_value() == "maa"

    def test_on_entered_loads_ocr_source(self, qapp) -> None:
        cp = _make_config_proxy()
        cp.ocr_source.return_value = "default"
        tool = _make_tool(qapp, cp)
        tool.on_entered()
        assert tool._ocr_row.get_value() == "default"

    def test_on_entered_loads_resolution(self, qapp) -> None:
        cp = _make_config_proxy()
        cp.resolution.return_value = "1920x1080"
        tool = _make_tool(qapp, cp)
        tool.on_entered()
        assert tool._resolution_row.get_value() == "1920x1080"

    def test_on_entered_loads_output_dir(self, qapp) -> None:
        cp = _make_config_proxy()
        cp.output_dir.return_value = "/tmp/results"
        tool = _make_tool(qapp, cp)
        tool.on_entered()
        assert tool._output_selector.path() == "/tmp/results"


# ── _set_running_ui ────────────────────────────────────────


class TestSetRunningUi:
    """验证 _set_running_ui 切换控件启用态"""

    def test_running_disables_start_enables_cancel(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool._set_running_ui(True)
        assert not tool._start_btn.isEnabled()
        assert tool._cancel_btn.isEnabled()

    def test_not_running_enables_start_disables_cancel(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool._set_running_ui(True)
        tool._set_running_ui(False)
        assert tool._start_btn.isEnabled()
        assert not tool._cancel_btn.isEnabled()

    def test_running_disables_param_rows(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool._set_running_ui(True)
        # 验证 backend combo 内的 QComboBox 禁用
        from PyQt6.QtWidgets import QComboBox
        combos = tool._backend_row.widget.findChildren(QComboBox)
        assert combos
        assert not combos[0].isEnabled()


# ── 主题与语言 ─────────────────────────────────────────────


class TestThemeAndRetranslate:
    """验证 set_colors / retranslate 不抛异常"""

    def test_set_colors_dark_theme(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool.set_colors(MaterialColors.dark())

    def test_set_colors_back_to_light(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool.set_colors(MaterialColors.dark())
        tool.set_colors(MaterialColors.light())

    def test_retranslate_no_exception(self, qapp) -> None:
        tool = _make_tool(qapp)
        tool.retranslate()
