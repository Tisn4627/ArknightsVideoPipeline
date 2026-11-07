"""配置文件卡片的批量操作状态审查

覆盖：
- 初态：全选可用，清空/生成禁用；
- 全选后：全选禁用，清空/生成可用；
- 清空后回到初态；
- 运行态：整卡复选框与三个按钮全部禁用，退出运行态后按选中数恢复；
- 视觉一致性：全选/清空同用 text 变体、8dp 间距；
- 选择变化会清掉过期的生成状态文本。
"""

import pytest
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.gui.components.material_button import MaterialButton
from arknights_video_pipeline.gui.components.settings_page import SettingsPage
from arknights_video_pipeline.gui.i18n import init_i18n
from arknights_video_pipeline.gui.theme import (
    MaterialColors,
    MaterialStyle,
    MaterialTypography,
)
from arknights_video_pipeline.gui.theme.spacing import Space


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    init_i18n()
    MaterialStyle(
        colors=MaterialColors.light(), typography=MaterialTypography()
    ).apply(app)
    yield app


@pytest.fixture()
def page(qapp):
    widget = SettingsPage(colors=MaterialColors.light(), is_dark=False)
    yield widget
    widget.deleteLater()


class TestConfigCardActions:
    def _boxes(self, page: SettingsPage):
        return list(page._config_checkboxes.values())

    def test_initial_state(self, page) -> None:
        assert all(not cb.isChecked() for cb in self._boxes(page))
        assert page._select_all_btn.isEnabled()
        assert not page._clear_btn.isEnabled()
        assert not page._generate_btn.isEnabled()

    def test_select_all_then_clear(self, page) -> None:
        page._on_select_all()
        assert all(cb.isChecked() for cb in self._boxes(page))
        assert not page._select_all_btn.isEnabled()
        assert page._clear_btn.isEnabled()
        assert page._generate_btn.isEnabled()

        page._on_clear_all()
        assert all(not cb.isChecked() for cb in self._boxes(page))
        assert page._select_all_btn.isEnabled()
        assert not page._clear_btn.isEnabled()
        assert not page._generate_btn.isEnabled()

    def test_running_disables_whole_config_card(self, page) -> None:
        page._on_select_all()
        page.set_config_enabled(False)
        assert not any(cb.isEnabled() for cb in self._boxes(page))
        assert not page._select_all_btn.isEnabled()
        assert not page._clear_btn.isEnabled()
        assert not page._generate_btn.isEnabled()

        page.set_config_enabled(True)
        assert all(cb.isEnabled() for cb in self._boxes(page))
        # 全选已完成 → 全选仍禁用；清空/生成恢复
        assert not page._select_all_btn.isEnabled()
        assert page._clear_btn.isEnabled()
        assert page._generate_btn.isEnabled()

    def test_action_row_emphasis_gap_and_order(self, page) -> None:
        assert page._select_all_btn.variant() == MaterialButton.VARIANT_TEXT
        assert page._clear_btn.variant() == MaterialButton.VARIANT_TEXT
        assert page._generate_btn.variant() == MaterialButton.VARIANT_FILLED
        assert page._action_buttons_layout.spacing() == Space.S
        # 单行动作区顺序：状态文本 → 全选 → 取消全选 → 生成（主操作最后）
        layout = page._action_buttons_layout
        assert [
            layout.itemAt(i).widget()
            for i in range(layout.count())
        ] == [
            page._config_status,
            page._select_all_btn,
            page._clear_btn,
            page._generate_btn,
        ]

    def test_selection_change_clears_stale_status(self, page) -> None:
        page._set_status("生成失败", error=True)
        assert page._config_status.text()
        key = next(iter(page._config_checkboxes))
        page._config_checkboxes[key].setChecked(True)
        assert page._config_status.text() == ""
        assert page._generate_btn.isEnabled()
