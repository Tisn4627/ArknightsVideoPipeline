"""批量视频列表组件单元测试

验证 gui/components/batch_video_list.py 中 BatchVideoList widget：
- add_paths：追加、过滤、去重、空值忽略
- clear：清空与信号发射
- 上移/下移/删除：顺序调整与索引重排
- set_editable：按钮启用/禁用
- set_file_running/progress/finished：状态与进度更新
- reset_states：重置所有行
- 拖放：dropEvent / dragEnterEvent
- 主题切换：set_colors
- 边界条件：越界索引不抛异常

所有测试在 offscreen Qt 模式下运行，不依赖真实视频文件。
拖放事件使用 MagicMock 构造，避免 Qt 事件构造的复杂性。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock

import pytest
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.gui.components.batch_video_list import BatchVideoList
from arknights_video_pipeline.gui.theme import MaterialColors


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen 模式）"""
    app = QApplication.instance() or QApplication([])
    yield app


def _make_list(qapp) -> BatchVideoList:
    """创建一个使用浅色主题的 BatchVideoList"""
    return BatchVideoList(MaterialColors.light())


# ── add_paths ──────────────────────────────────────────────


class TestAddPaths:
    """验证 add_paths 方法"""

    def test_add_paths_appends_in_order(self, qapp) -> None:
        """添加多个视频路径后按给定顺序追加，并发射 video_paths_changed"""
        bl = _make_list(qapp)
        events: list = []
        bl.video_paths_changed.connect(lambda paths: events.append(list(paths)))
        bl.add_paths(["a.mp4", "b.mkv"])
        assert bl.video_paths() == ["a.mp4", "b.mkv"]
        assert events == [["a.mp4", "b.mkv"]]

    def test_add_paths_filters_unsupported(self, qapp) -> None:
        """不支持的视频格式（.txt、.png）被过滤，仅保留支持的"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.txt", "c.png"])
        assert bl.video_paths() == ["a.mp4"]

    def test_add_paths_dedupes(self, qapp) -> None:
        """重复路径仅添加一次"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "a.mp4"])
        assert bl.video_paths() == ["a.mp4"]
        assert len(bl._rows) == 1

    def test_add_paths_ignores_empty(self, qapp) -> None:
        """空字符串与纯空白字符串被忽略"""
        bl = _make_list(qapp)
        bl.add_paths(["", "   ", "a.mp4"])
        assert bl.video_paths() == ["a.mp4"]


# ── clear ──────────────────────────────────────────────────


class TestClear:
    """验证 clear 方法"""

    def test_clear_empties_list_and_emits(self, qapp) -> None:
        """清空非空列表后 video_paths() 返回 []，并发射信号"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mkv"])
        events: list = []
        bl.video_paths_changed.connect(lambda paths: events.append(list(paths)))
        bl.clear()
        assert bl.video_paths() == []
        assert events == [[]]

    def test_clear_on_empty_noop(self, qapp) -> None:
        """对空列表调用 clear 不发射信号"""
        bl = _make_list(qapp)
        events: list = []
        bl.video_paths_changed.connect(lambda paths: events.append(paths))
        bl.clear()
        assert len(events) == 0


# ── 上移 / 下移 / 删除 ─────────────────────────────────────


class TestMoveAndRemove:
    """验证上移、下移、删除操作"""

    def test_move_up_swaps_order(self, qapp) -> None:
        """点击第 2 行（index=1）的上移按钮后，该行与上一行交换"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4", "c.mp4"])
        # 点击 index=1 行的上移按钮
        bl._rows[1].up_button().click()
        assert bl.video_paths() == ["b.mp4", "a.mp4", "c.mp4"]

    def test_move_down_swaps_order(self, qapp) -> None:
        """点击第 1 行（index=0）的下移按钮后，该行与下一行交换"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4", "c.mp4"])
        bl._rows[0].down_button().click()
        assert bl.video_paths() == ["b.mp4", "a.mp4", "c.mp4"]

    def test_move_up_first_row_noop(self, qapp) -> None:
        """点击第 1 行（index=0）的上移按钮不改变顺序、不发射信号"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4", "c.mp4"])
        events: list = []
        bl.video_paths_changed.connect(lambda paths: events.append(paths))
        bl._rows[0].up_button().click()
        assert bl.video_paths() == ["a.mp4", "b.mp4", "c.mp4"]
        assert len(events) == 0

    def test_remove_deletes_row(self, qapp) -> None:
        """点击删除按钮后该行被移除，列表长度减少并发射信号"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4", "c.mp4"])
        events: list = []
        bl.video_paths_changed.connect(lambda paths: events.append(list(paths)))
        bl._rows[1].delete_button().click()
        assert len(bl.video_paths()) == 2
        assert bl.video_paths() == ["a.mp4", "c.mp4"]
        assert len(events) == 1

    def test_index_reindexes_after_remove(self, qapp) -> None:
        """删除首行后剩余行的序号标签重新编号为 1、2"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4", "c.mp4"])
        bl._rows[0].delete_button().click()
        assert bl._rows[0]._index_label.text() == "1"
        assert bl._rows[1]._index_label.text() == "2"


# ── set_editable ───────────────────────────────────────────


class TestSetEditable:
    """验证 set_editable 方法"""

    def test_set_editable_disables_buttons(self, qapp) -> None:
        """set_editable(False) 禁用所有行的上移/下移/删除/JSON按钮以及 Add/Clear 按钮"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4"])
        bl.set_editable(False)
        for row in bl._rows:
            assert not row.up_button().isEnabled()
            assert not row.down_button().isEnabled()
            assert not row.delete_button().isEnabled()
            assert not row.json_button().isEnabled()
        assert not bl._add_btn.isEnabled()
        assert not bl._clear_btn.isEnabled()


# ── 文件状态更新 ───────────────────────────────────────────


class TestFileStatus:
    """验证 set_file_running / set_file_progress / set_file_finished"""

    def test_set_file_running_sets_status(self, qapp) -> None:
        """set_file_running(0) 后第 0 行状态为"处理中"、进度为 0"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4"])
        bl.set_file_running(0)
        assert bl._rows[0]._status_label.text() == "处理中"
        assert bl._rows[0]._progress.value() == 0

    def test_set_file_progress_updates_percent(self, qapp) -> None:
        """set_file_progress(0, 50, msg) 后第 0 行进度条值为 50"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4"])
        bl.set_file_progress(0, 50, "msg")
        assert bl._rows[0]._progress.value() == 50

    def test_set_file_finished_success(self, qapp) -> None:
        """set_file_finished(0, True) 后第 0 行状态文本为 '已完成'"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4"])
        bl.set_file_finished(0, True)
        assert bl._rows[0]._status_label.text() == "已完成"

    def test_set_file_finished_failure(self, qapp) -> None:
        """set_file_finished(0, False) 后第 0 行状态文本为 '失败'"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4"])
        bl.set_file_finished(0, False)
        assert bl._rows[0]._status_label.text() == "失败"

    def test_reset_states_resets_all(self, qapp) -> None:
        """设置部分行为运行/完成后调用 reset_states，所有行回到 '等待中'、进度 0"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4"])
        bl.set_file_running(0)
        bl.set_file_finished(1, False)
        bl.reset_states()
        for row in bl._rows:
            assert row._status_label.text() == "等待中"
            assert row._progress.value() == 0

    def test_out_of_range_status_calls_noop(self, qapp) -> None:
        """对 2 行列表调用 set_file_running(99) 不抛 IndexError"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4"])
        # 不应抛出异常
        bl.set_file_running(99)
        bl.set_file_progress(99, 50, "msg")
        bl.set_file_finished(99, True)


# ── 拖放 ───────────────────────────────────────────────────


class TestDragDrop:
    """验证拖放事件处理（使用 MagicMock 模拟 Qt 事件）"""

    def test_drop_event_adds_files(self, qapp) -> None:
        """dropEvent 接收包含 2 个本地文件 URL 的 mime data 后追加到列表"""
        bl = _make_list(qapp)
        event = mock.MagicMock()
        mime = event.mimeData.return_value
        mime.hasUrls.return_value = True
        url1 = mock.MagicMock()
        url1.isLocalFile.return_value = True
        url1.toLocalFile.return_value = "a.mp4"
        url2 = mock.MagicMock()
        url2.isLocalFile.return_value = True
        url2.toLocalFile.return_value = "b.mkv"
        mime.urls.return_value = [url1, url2]
        bl.dropEvent(event)
        assert bl.video_paths() == ["a.mp4", "b.mkv"]
        event.acceptProposedAction.assert_called_once()

    def test_drop_event_ignores_non_files(self, qapp) -> None:
        """mime data 仅含文本（无 URL）时 dropEvent 忽略事件，不添加路径"""
        bl = _make_list(qapp)
        event = mock.MagicMock()
        mime = event.mimeData.return_value
        mime.hasUrls.return_value = False
        mime.urls.return_value = []
        bl.dropEvent(event)
        assert bl.video_paths() == []
        event.ignore.assert_called_once()

    def test_drag_enter_event_accepts_urls(self, qapp) -> None:
        """dragEnterEvent 接收含 URL 的 mime data 时调用 acceptProposedAction"""
        bl = _make_list(qapp)
        event = mock.MagicMock()
        event.mimeData().hasUrls.return_value = True
        bl.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()


# ── 主题与计数 ─────────────────────────────────────────────


class TestThemeAndCount:
    """验证 set_colors 主题切换与计数标签更新"""

    def test_set_colors_updates_theme(self, qapp) -> None:
        """切换深色/浅色主题不抛异常，行内部样式被刷新"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4"])
        # 不应抛出异常
        bl.set_colors(MaterialColors.dark())
        bl.set_colors(MaterialColors.light())

    def test_count_label_updates(self, qapp) -> None:
        """添加 3 个路径后计数标签含 '3'，clear 后含 '0'"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4", "c.mp4"])
        assert "3" in bl._count_label.text()
        bl.clear()
        assert "0" in bl._count_label.text()


# ── 自定义作业 JSON ────────────────────────────────────────


class TestCustomCopilotJson:
    """验证每行自定义作业 JSON 按钮的绑定、状态显示与交互"""

    def test_json_paths_default_none(self, qapp) -> None:
        """未绑定时 json_paths() 返回与行数平行的 None 列表"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4", "b.mp4"])
        assert bl.json_paths() == [None, None]

    def test_set_json_path_updates_state(self, qapp) -> None:
        """绑定 JSON 后 json_paths() 与按钮 tooltip 同步更新"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4"])
        row = bl._rows[0]
        btn = row.json_button()
        assert row.json_path is None
        row.set_json_path("C:/x/job.json")
        assert row.json_path == "C:/x/job.json"
        assert bl.json_paths() == ["C:/x/job.json"]
        assert "job.json" in btn.toolTip()
        # 移除绑定后恢复未绑定状态
        row.set_json_path(None)
        assert row.json_path is None
        assert bl.json_paths() == [None]

    def test_json_button_click_unbound_opens_dialog(self, qapp, tmp_path) -> None:
        """未绑定时点击 JSON 按钮弹出文件对话框并绑定所选文件"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4"])
        row = bl._rows[0]
        jp = str(tmp_path / "job.json")
        with mock.patch(
            "PyQt6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=(jp, ""),
        ):
            bl._on_json_clicked(row)
        assert row.json_path == jp

    def test_json_button_click_dialog_cancelled_no_change(self, qapp) -> None:
        """文件对话框取消时不改变绑定"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4"])
        row = bl._rows[0]
        with mock.patch(
            "PyQt6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=("", ""),
        ):
            bl._on_json_clicked(row)
        assert row.json_path is None

    def test_json_button_click_bound_replace(self, qapp, tmp_path) -> None:
        """已绑定时菜单选择「更换JSON」弹出文件对话框并替换"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4"])
        row = bl._rows[0]
        row.set_json_path("C:/x/old.json")
        new_jp = str(tmp_path / "new.json")
        replace_act = mock.MagicMock()
        remove_act = mock.MagicMock()
        with mock.patch(
            "PyQt6.QtWidgets.QMenu.addAction"
        ) as mock_add, \
             mock.patch("PyQt6.QtWidgets.QMenu.exec") as mock_exec, \
             mock.patch(
                 "PyQt6.QtWidgets.QFileDialog.getOpenFileName",
                 return_value=(new_jp, ""),
             ):
            mock_add.side_effect = [replace_act, remove_act]
            mock_exec.return_value = replace_act
            bl._on_json_clicked(row)
        assert row.json_path == new_jp

    def test_json_button_click_bound_remove(self, qapp) -> None:
        """已绑定时菜单选择「移除JSON」解除绑定"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4"])
        row = bl._rows[0]
        row.set_json_path("C:/x/job.json")
        replace_act = mock.MagicMock()
        remove_act = mock.MagicMock()
        with mock.patch(
            "PyQt6.QtWidgets.QMenu.addAction"
        ) as mock_add, \
             mock.patch("PyQt6.QtWidgets.QMenu.exec") as mock_exec:
            mock_add.side_effect = [replace_act, remove_act]
            mock_exec.return_value = remove_act
            bl._on_json_clicked(row)
        assert row.json_path is None

    def test_json_button_click_bound_menu_dismissed(self, qapp) -> None:
        """已绑定时菜单被取消（exec 返回 None）不改变绑定"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4"])
        row = bl._rows[0]
        row.set_json_path("C:/x/job.json")
        replace_act = mock.MagicMock()
        remove_act = mock.MagicMock()
        with mock.patch(
            "PyQt6.QtWidgets.QMenu.addAction"
        ) as mock_add, \
             mock.patch("PyQt6.QtWidgets.QMenu.exec", return_value=None):
            mock_add.side_effect = [replace_act, remove_act]
            bl._on_json_clicked(row)
        assert row.json_path == "C:/x/job.json"

    def test_json_button_click_wired_in_add_paths(self, qapp, tmp_path) -> None:
        """add_paths 后 JSON 按钮点击直接触发绑定流程"""
        bl = _make_list(qapp)
        bl.add_paths(["a.mp4"])
        row = bl._rows[0]
        jp = str(tmp_path / "job.json")
        with mock.patch(
            "PyQt6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=(jp, ""),
        ):
            row.json_button().click()
        assert row.json_path == jp
