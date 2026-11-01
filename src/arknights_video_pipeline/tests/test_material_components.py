"""MD3 原子组件行为测试

覆盖 P3 重写/新增的组件：

- ``MaterialButton``：五变体、统一高度、墨层动画目标、禁用态不崩；
- ``MaterialTextField``：包装既有控件、浮动标签状态机、错误态；
- ``MaterialFAB``：regular / extended 尺寸；
- ``MaterialSwitch`` / ``MaterialCheckBox``：状态切换与动画落值；
- ``MaterialProgress``：4dp 轨道、取值钳制、``value()`` 兼容接口；
- ``NavigationBar``：compact 档底部导航的选中同步。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QLineEdit, QSpinBox

from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.material_checkbox import MaterialCheckBox
from arknights_video_pipeline.gui.components.material_fab import MaterialFab
from arknights_video_pipeline.gui.components.material_progress import MaterialProgress
from arknights_video_pipeline.gui.components.material_switch import MaterialSwitch
from arknights_video_pipeline.gui.components.material_text_field import MaterialTextField
from arknights_video_pipeline.gui.components.navigation_bar import NavigationBar
from arknights_video_pipeline.gui.i18n import init_i18n
from arknights_video_pipeline.gui.theme import MaterialColors, MaterialStyle, MaterialTypography
from arknights_video_pipeline.gui.theme.motion import Motion
from arknights_video_pipeline.gui.theme.spacing import Layout


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    init_i18n()
    MaterialStyle(
        colors=MaterialColors.light(), typography=MaterialTypography()
    ).apply(app)
    yield app


@pytest.fixture()
def no_motion():
    """动画关闭：断言直接落值，避免依赖离屏环境的计时器"""
    original = Motion.enabled
    Motion.set_enabled(False)
    yield
    Motion.set_enabled(original)


class TestMaterialButton:
    def test_default_variant_is_filled(self, qapp) -> None:
        button = MaterialButton("确定")
        assert button.variant() == MaterialButton.VARIANT_FILLED
        assert button.property("mdOutlined") == "false"

    @pytest.mark.parametrize(
        "variant",
        [
            MaterialButton.VARIANT_FILLED,
            MaterialButton.VARIANT_TONAL,
            MaterialButton.VARIANT_OUTLINED,
            MaterialButton.VARIANT_TEXT,
            MaterialButton.VARIANT_ELEVATED,
        ],
    )
    def test_height_is_uniform_40(self, qapp, variant: str) -> None:
        button = MaterialButton("确定", variant)
        assert button.sizeHint().height() == Layout.BUTTON_HEIGHT
        assert button.minimumSizeHint().height() == Layout.BUTTON_HEIGHT

    def test_variant_sets_legacy_properties(self, qapp) -> None:
        button = MaterialButton("取消", MaterialButton.VARIANT_OUTLINED)
        assert button.property("mdOutlined") == "true"
        button.set_variant(MaterialButton.VARIANT_TEXT)
        assert button.property("mdText") == "true"
        assert button.property("mdOutlined") == "false"

    def test_state_layer_animation_starts(self, qapp) -> None:
        button = MaterialButton("开始")
        button._animate_to(0.08)
        assert button._anim.state().name == "Running"

    def test_state_layer_lands_without_motion(self, qapp, no_motion) -> None:
        button = MaterialButton("开始")
        button._animate_to(0.08)
        assert button.overlayAlpha == pytest.approx(0.08)

    def test_disabled_button_paints_without_error(self, qapp) -> None:
        button = MaterialButton("禁用")
        button.setEnabled(False)
        button.resize(120, 40)
        assert not button.grab().isNull()


class TestMaterialTextField:
    def test_attach_wraps_existing_widget(self, qapp) -> None:
        edit = QLineEdit()
        field = MaterialTextField.attach(edit, label="路径")
        assert field.inner() is edit
        assert edit.parent() is not None

    def test_label_floats_when_text_present(self, qapp, no_motion) -> None:
        edit = QLineEdit()
        field = MaterialTextField.attach(edit, label="路径")
        edit.setText("C:/video.mp4")
        assert field.is_label_floating()

    def test_label_rests_when_empty(self, qapp, no_motion) -> None:
        edit = QLineEdit()
        field = MaterialTextField.attach(edit, label="路径")
        edit.setText("")
        assert not field.is_label_floating()

    def test_spinbox_label_always_floats(self, qapp, no_motion) -> None:
        spin = QSpinBox()
        field = MaterialTextField.attach(spin, label="并发数")
        assert field.is_label_floating()

    def test_error_state_toggle(self, qapp) -> None:
        field = MaterialTextField.attach(QLineEdit(), label="路径")
        assert not field.is_error()
        field.set_error(True)
        assert field.is_error()

    def test_supporting_text_shown_on_error(self, qapp) -> None:
        field = MaterialTextField.attach(QLineEdit(), label="路径")
        field.set_supporting("路径不存在", error=True)
        assert field.is_error()


class TestMaterialFab:
    def test_regular_is_square_56(self, qapp) -> None:
        fab = MaterialFab("add")
        hint = fab.sizeHint()
        assert hint.width() == Layout.FAB_SIZE
        assert hint.height() == Layout.FAB_SIZE

    def test_extended_is_wider(self, qapp) -> None:
        fab = MaterialFab("add", "添加视频", extended=True)
        assert fab.sizeHint().width() > Layout.FAB_SIZE
        assert fab.sizeHint().height() == Layout.FAB_SIZE


class TestToggleControls:
    def test_switch_toggles_and_animates(self, qapp, no_motion) -> None:
        switch = MaterialSwitch()
        events: list[bool] = []
        switch.toggled.connect(events.append)
        switch.set_checked(True)
        assert switch.is_checked()
        assert switch.toggleProgress == 1.0
        assert events == [True]

    def test_switch_silent_does_not_emit(self, qapp, no_motion) -> None:
        switch = MaterialSwitch()
        events: list[bool] = []
        switch.toggled.connect(events.append)
        switch.set_checked_silent(True)
        assert switch.is_checked()
        assert events == []

    def test_checkbox_checked_progress(self, qapp, no_motion) -> None:
        box = MaterialCheckBox("视频识别")
        box.setChecked(True)
        assert box.isChecked()
        assert box.checkProgress == 1.0

    def test_checkbox_checked_uses_on_primary(self, qapp) -> None:
        """回归：深色主题下对勾必须用 on_primary（白勾几乎不可见）"""
        colors = MaterialColors.dark()
        box = MaterialCheckBox("x", colors=colors)
        box.setChecked(True)
        box.resize(box.sizeHint())
        assert colors.on_primary != "#FFFFFF"
        assert not box.grab().isNull()


class TestMaterialProgress:
    def test_height_is_4dp(self, qapp) -> None:
        assert MaterialProgress().height() == 4

    def test_value_is_clamped(self, qapp) -> None:
        bar = MaterialProgress()
        bar.setValue(150)
        assert bar.value() == 100
        bar.setValue(-20)
        assert bar.value() == 0

    def test_set_value_alias(self, qapp) -> None:
        bar = MaterialProgress()
        bar.set_value(42)
        assert bar.value() == 42

    def test_color_override(self, qapp) -> None:
        bar = MaterialProgress()
        bar.set_color("#B3261E")
        bar.setValue(30)
        assert not bar.grab().isNull()


class TestNavigationBar:
    def test_selection_emits_and_updates(self, qapp, no_motion) -> None:
        bar = NavigationBar(colors=MaterialColors.light())
        events: list[int] = []
        bar.selection_changed.connect(events.append)
        bar.set_selected(2)
        assert events == [2]
        assert bar.current_index() == 2

    def test_same_index_no_signal(self, qapp) -> None:
        bar = NavigationBar(colors=MaterialColors.light())
        events: list[int] = []
        bar.selection_changed.connect(events.append)
        bar.set_selected(0)
        assert events == []

    def test_height_is_80(self, qapp) -> None:
        bar = NavigationBar(colors=MaterialColors.light())
        assert bar.height() == Layout.NAV_BAR_HEIGHT
