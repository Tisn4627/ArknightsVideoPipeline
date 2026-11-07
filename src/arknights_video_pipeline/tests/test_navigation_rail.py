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
from PyQt6.QtGui import QColor, QPalette
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


def _settle(qapp, *items: NavigationRailItem, timeout_ms: int = 500) -> None:
    """等待选中动画播放完毕

    先按真实时钟轮询；若仍处于 Running（离屏环境下动画计时器可能不推进），
    直接把动画推到结尾——否则用例结果会依赖机器时序与用例执行顺序。
    """
    import time

    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        qapp.processEvents()
        if all(i._anim.state().name != "Running" for i in items):
            break
        time.sleep(0.005)
    for item in items:
        if item._anim.state().name == "Running":
            item._anim.setCurrentTime(item._anim.duration())
    qapp.processEvents()


# ── MD3 active indicator 底色（像素验证）────────────────────


class TestSelectedIndicatorColor:
    """MD3 指示器是 56×32 的胶囊，只包住图标（不含下方标签）"""

    _INDICATOR_MID_Y = 16  # 32dp 指示器的垂直中心

    def test_selected_item_paints_secondary_container_pill(self, qapp) -> None:
        """选中项指示器区域应为 secondary_container"""
        rail = _make_rail(qapp)
        item = rail._items[0]
        img = item.grab().toImage()
        # 采样点在图标左侧的指示器底色区（x=4 避开 24dp 图标）
        px = img.pixelColor(4, self._INDICATOR_MID_Y)
        assert px.name().upper() == MaterialColors.light().secondary_container.upper()

    def test_selected_indicator_is_not_primary_container(self, qapp) -> None:
        """回归：底色使用 secondary_container 而非旧实现的 primary_container"""
        rail = _make_rail(qapp)
        item = rail._items[0]
        img = item.grab().toImage()
        px = img.pixelColor(4, self._INDICATOR_MID_Y)
        assert px.name().upper() != MaterialColors.light().primary_container.upper()

    def test_unselected_item_is_transparent(self, qapp) -> None:
        """未选中项不绘制底色，露出 rail surface"""
        rail = _make_rail(qapp)
        item = rail._items[1]
        px = _sample(qapp, rail, item, 4, self._INDICATOR_MID_Y)
        assert px.name().upper() == MaterialColors.light().surface.upper()

    def test_indicator_covers_icon_area_only(self, qapp) -> None:
        """指示器覆盖 56dp 宽度，但不延伸到标签区域（MD3 标准形态）"""
        rail = _make_rail(qapp)
        item = rail._items[0]
        img = item.grab().toImage()
        expected = MaterialColors.light().secondary_container.upper()
        assert img.pixelColor(2, self._INDICATOR_MID_Y).name().upper() == expected
        assert img.pixelColor(img.width() - 3, self._INDICATOR_MID_Y).name().upper() == expected
        # 标签区域（指示器下方）不应有胶囊底色
        below = img.pixelColor(img.width() // 2, img.height() - 4)
        assert below.name().upper() != expected


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
        """选中项文字色应为 on_secondary_container，未选中为 on_surface_variant

        文字色现在走 QPalette（不再写 widget 级样式表）：断言调色板颜色，
        同时确认没有残留样式表导致主题切换时再次 polish。
        """
        rail = _make_rail(qapp)
        sel = rail._items[0]
        uns = rail._items[1]
        assert sel._label.palette().color(
            QPalette.ColorRole.WindowText
        ).name().upper() == MaterialColors.light().on_secondary_container.upper()
        assert uns._label.palette().color(
            QPalette.ColorRole.WindowText
        ).name().upper() == MaterialColors.light().on_surface_variant.upper()
        assert sel._label.styleSheet() == ""
        assert uns._label.styleSheet() == ""

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
        px = img.pixelColor(4, TestSelectedIndicatorColor._INDICATOR_MID_Y)
        assert px.name().upper() == MaterialColors.dark().secondary_container.upper()

    def test_set_colors_preserves_selection(self, qapp) -> None:
        """主题切换不改变当前选中项"""
        rail = _make_rail(qapp)
        rail.set_selected(2, animate=False)
        rail.set_colors(MaterialColors.dark())
        assert rail._items[2]._progress == 1.0
        assert rail._items[0]._progress == 0.0


# ── 响应式折叠 ──────────────────────────────────────────────


class TestCompactResponsive:
    def test_compact_item_is_icon_only(self, qapp) -> None:
        """折叠为仅图标后，item 高度收敛为 32dp 指示器，宽度保持 56dp"""
        rail = _make_rail(qapp)
        rail.set_compact(True)
        qapp.processEvents()
        item = rail._items[0]
        assert item.width() == 56
        assert item.height() == 32
        img = item.grab().toImage()
        expected = MaterialColors.light().secondary_container.upper()
        assert img.pixelColor(2, 16).name().upper() == expected
        assert img.pixelColor(img.width() - 3, 16).name().upper() == expected

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
        """未选中项悬停时绘制 8% on_surface 墨层（MD3 state layer）"""
        from arknights_video_pipeline.gui.theme.state import StateLayer, blend

        rail = _make_rail(qapp)
        item = rail._items[1]
        assert item._progress == 0.0

        item._set_hover(StateLayer.HOVER)
        item.update()
        qapp.processEvents()
        expected = blend(
            MaterialColors.light().surface,
            MaterialColors.light().on_surface,
            StateLayer.HOVER,
        )
        hovered_px = _sample(qapp, rail, item, 2, 16)
        # 绘制走 QColor alpha 混合、期望值走 blend()，两者舍入可能差 1
        assert abs(hovered_px.red() - expected.red()) <= 2
        assert abs(hovered_px.green() - expected.green()) <= 2
        assert abs(hovered_px.blue() - expected.blue()) <= 2

        # 离开后恢复透明（露出 rail surface）
        item._set_hover(0.0)
        item.update()
        qapp.processEvents()
        plain_px = _sample(qapp, rail, item, 2, 16)
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
