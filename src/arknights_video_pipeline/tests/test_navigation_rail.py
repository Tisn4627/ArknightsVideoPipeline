"""Navigation Rail 选中底色与过渡动画单元测试

验证 gui/components/navigation_rail.py 中 NavigationRail / NavigationRailItem：
- MD3 active indicator 底色：选中项自绘 secondary_container 胶囊（像素验证）
- 未选中项背景透明，露出 rail surface
- 平滑过渡：set_selected 触发 QPropertyAnimation，progress 在 0~1 间变化
- 前景色插值：图标/文字在 on_surface_variant 与 on_secondary_container 间过渡
- 主题切换：set_colors 后 indicator 使用对应主题 secondary_container
- 响应式：compact 折叠后胶囊随 item 尺寸重绘，覆盖整个可点击区域
- 边界：同值早退不重复发射 selection_changed、越界索引安全

所有测试在 offscreen Qt 模式下运行，不依赖真实显示器。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QPoint, QPointF
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.gui.components.navigation_rail import (
    NavigationRail,
    NavigationRailItem,
)
from arknights_video_pipeline.gui.i18n import init_i18n
from arknights_video_pipeline.gui.theme import (
    MaterialColors,
    MaterialStyle,
    MaterialTypography,
)


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen 模式），并应用全局 QSS

    全局 QSS 含 ``QWidget { background-color: background }`` 规则，
    必须模拟真实运行环境，才能验证 item 未选中时确实保持透明
    （而非被全局规则染成淡紫背景）。
    """
    app = QApplication.instance() or QApplication([])
    init_i18n()
    MaterialStyle(
        colors=MaterialColors.light(), typography=MaterialTypography()
    ).apply(app)
    yield app


def _make_rail(qapp, colors: MaterialColors | None = None) -> NavigationRail:
    rail = NavigationRail(colors=colors or MaterialColors.light())
    rail.resize(88, 400)
    rail.show()
    qapp.processEvents()
    return rail


def _sample(qapp, rail: NavigationRail, item: NavigationRailItem,
            rel_x: int, rel_y: int) -> QColor:
    """从 rail 整体渲染结果中采样 item 局部坐标处的像素

    单独 ``item.grab()`` 会把透明区域填充为窗口背景色而非父级 surface，
    无法验证"未选中项露出 rail 底色"，必须在父级渲染图中采样。
    """
    img = rail.grab().toImage()
    pos = item.mapTo(rail, QPoint(rel_x, rel_y))
    return img.pixelColor(pos.x(), pos.y())


def _settle(qapp, *items: NavigationRailItem, timeout_ms: int = 2000) -> None:
    """等待所有传入 item 的选中动画播放完毕"""
    import time

    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        qapp.processEvents()
        if all(i._anim.state().name != "Running" for i in items):
            break
        time.sleep(0.005)
    qapp.processEvents()


# ── MD3 active indicator 底色（像素验证）────────────────────


class TestSelectedIndicatorColor:
    def test_selected_item_paints_secondary_container_pill(self, qapp) -> None:
        """选中项中心像素应为 secondary_container（MD3 active indicator）"""
        rail = _make_rail(qapp)
        item = rail._items[0]
        img = item.grab().toImage()
        # 中心像素落在胶囊内（图标区域透明，露出底色）
        center = img.pixelColor(img.width() // 2, img.height() - 6)
        assert center.name().upper() == MaterialColors.light().secondary_container.upper()

    def test_selected_indicator_is_not_primary_container(self, qapp) -> None:
        """回归：底色使用 secondary_container 而非旧实现的 primary_container"""
        rail = _make_rail(qapp)
        item = rail._items[0]
        img = item.grab().toImage()
        center = img.pixelColor(img.width() // 2, img.height() - 6)
        assert center.name().upper() != MaterialColors.light().primary_container.upper()

    def test_unselected_item_is_transparent(self, qapp) -> None:
        """未选中项不绘制底色，露出 rail surface（#FFFBFE）"""
        rail = _make_rail(qapp)
        item = rail._items[1]
        px = _sample(qapp, rail, item, 4, item.height() - 6)
        assert px.name().upper() == MaterialColors.light().surface.upper()

    def test_pill_covers_full_clickable_area(self, qapp) -> None:
        """胶囊应覆盖整个可点击区域宽度（左右边缘中点均为底色）"""
        rail = _make_rail(qapp)
        item = rail._items[0]
        img = item.grab().toImage()
        mid_y = img.height() // 2
        left = img.pixelColor(2, mid_y).name().upper()
        right = img.pixelColor(img.width() - 3, mid_y).name().upper()
        expected = MaterialColors.light().secondary_container.upper()
        assert left == expected
        assert right == expected


# ── 平滑过渡动画 ────────────────────────────────────────────


class TestSelectionTransition:
    def test_switch_starts_animation_and_interpolates(self, qapp) -> None:
        """切换选中项时，旧项淡出、新项淡入（progress 处于中间态）"""
        rail = _make_rail(qapp)
        old, new = rail._items[0], rail._items[1]
        assert old._progress == 1.0 and new._progress == 0.0
        rail.set_selected(1)
        # 刚触发：动画运行中，旧项 progress 应 <1、新项 >0（或至少动画在跑）
        assert old._anim.state().name == "Running" or new._anim.state().name == "Running"
        _settle(qapp, old, new)
        assert old._progress == 0.0
        assert new._progress == 1.0

    def test_initial_selection_has_no_animation(self, qapp) -> None:
        """构造时初始选中直接落值，不播放淡入（避免启动闪烁）"""
        rail = NavigationRail(colors=MaterialColors.light())
        assert rail._items[0]._progress == 1.0
        assert rail._items[0]._anim.state().name != "Running"

    def test_foreground_color_interpolates(self, qapp) -> None:
        """选中项文字色应为 on_secondary_container，未选中为 on_surface_variant"""
        rail = _make_rail(qapp)
        sel = rail._items[0]
        uns = rail._items[1]
        assert MaterialColors.light().on_secondary_container.upper() in sel._label.styleSheet().upper()
        assert MaterialColors.light().on_surface_variant.upper() in uns._label.styleSheet().upper()

    def test_rapid_reselect_does_not_jump(self, qapp) -> None:
        """动画中途再次切换：从当前 progress 重新起步，不跳变到端点"""
        rail = _make_rail(qapp)
        a, b = rail._items[0], rail._items[1]
        rail.set_selected(1)  # a 淡出、b 淡入
        # 手动推进动画到中途（不依赖真实时钟）
        b._anim.setCurrentTime(b._anim.duration() // 2)
        a._anim.setCurrentTime(a._anim.duration() // 2)
        mid = b._progress
        assert 0.0 < mid < 1.0
        rail.set_selected(0)  # 立即切回，b 应从当前值起步淡出
        assert b._anim.state().name == "Running"
        # 起步值即当前进度：动画第一帧不应跳回 1.0
        b._anim.setCurrentTime(0)
        assert abs(b._progress - mid) < 0.05
        _settle(qapp, a, b)
        assert a._progress == 1.0 and b._progress == 0.0


# ── 主题切换兼容 ────────────────────────────────────────────


class TestThemeSwitch:
    def test_dark_theme_indicator_uses_dark_secondary_container(self, qapp) -> None:
        """深色主题下选中底色切换为深色 secondary_container"""
        rail = _make_rail(qapp)
        rail.set_colors(MaterialColors.dark())
        qapp.processEvents()
        item = rail._items[0]
        img = item.grab().toImage()
        center = img.pixelColor(img.width() // 2, img.height() - 6)
        assert center.name().upper() == MaterialColors.dark().secondary_container.upper()

    def test_set_colors_preserves_selection(self, qapp) -> None:
        """主题切换不改变当前选中项"""
        rail = _make_rail(qapp)
        rail.set_selected(2, animate=False)
        rail.set_colors(MaterialColors.dark())
        assert rail._items[2]._progress == 1.0
        assert rail._items[0]._progress == 0.0


# ── 响应式折叠 ──────────────────────────────────────────────


class TestCompactResponsive:
    def test_compact_pill_covers_smaller_clickable_area(self, qapp) -> None:
        """折叠为仅图标后，胶囊仍覆盖收缩后的整个可点击区域"""
        rail = _make_rail(qapp)
        rail.set_compact(True)
        qapp.processEvents()
        item = rail._items[0]
        assert item.width() == 40
        img = item.grab().toImage()
        mid_y = img.height() // 2
        expected = MaterialColors.light().secondary_container.upper()
        assert img.pixelColor(2, mid_y).name().upper() == expected
        assert img.pixelColor(img.width() - 3, mid_y).name().upper() == expected

    def test_compact_hides_labels(self, qapp) -> None:
        rail = _make_rail(qapp)
        rail.set_compact(True)
        assert not rail._items[0]._label.isVisible()
        rail.set_compact(False)
        assert rail._items[0]._label.isVisible()


# ── 交互逻辑与边界 ──────────────────────────────────────────


class TestInteractionAndEdges:
    def test_click_emits_selection_changed(self, qapp) -> None:
        rail = _make_rail(qapp)
        events: list[int] = []
        rail.selection_changed.connect(events.append)
        rail._items[2].clicked.emit()
        assert events == [2]

    def test_same_index_no_signal(self, qapp) -> None:
        """同值早退：重复选中当前项不重复发射 selection_changed"""
        rail = _make_rail(qapp)
        events: list[int] = []
        rail.selection_changed.connect(events.append)
        rail.set_selected(0)  # 当前已是 0
        assert events == []

    def test_out_of_range_index_safe(self, qapp) -> None:
        """越界索引不抛异常、不改变选中态"""
        rail = _make_rail(qapp)
        rail.set_selected(99)
        rail.set_selected(-5)
        assert rail._current_index == 0
        assert rail._items[0]._progress == 1.0

    def test_hover_state_layer_when_unselected(self, qapp) -> None:
        """未选中项悬停时绘制 surface_variant 状态层（覆盖原 hover 效果）"""
        rail = _make_rail(qapp)
        item = rail._items[1]
        assert item._progress == 0.0
        item._hovered = True
        item.update()
        qapp.processEvents()
        # hover 层为 surface_variant，明显区别于未 hover 的 surface
        hovered_px = _sample(qapp, rail, item, 2, item.height() // 2)
        assert hovered_px.name().upper() == MaterialColors.light().surface_variant.upper()
        # 离开后恢复透明
        item._hovered = False
        item.update()
        qapp.processEvents()
        plain_px = _sample(qapp, rail, item, 2, item.height() // 2)
        assert plain_px.name().upper() == MaterialColors.light().surface.upper()

    def test_click_only_left_button(self, qapp) -> None:
        """仅左键触发 clicked，右键/中键不响应"""
        from unittest import mock

        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QMouseEvent

        rail = _make_rail(qapp)
        item = rail._items[1]

        def _press(button: Qt.MouseButton) -> QMouseEvent:
            return QMouseEvent(
                QMouseEvent.Type.MouseButtonPress,
                QPointF(0, 0),
                QPointF(0, 0),
                button,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )

        with mock.patch.object(item, "clicked") as sig:
            item.mousePressEvent(_press(Qt.MouseButton.LeftButton))
            assert sig.emit.called

            sig.reset_mock()
            item.mousePressEvent(_press(Qt.MouseButton.RightButton))
            assert not sig.emit.called
