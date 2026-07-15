"""
gui.i18n - 国际化子系统

提供 JSON 语言资源加载、``tr()`` 翻译与 ``language_changed`` 信号驱动的
即时重翻译。仅服务 GUI 层，与 ``core`` / ``service`` 完全解耦。

典型用法::

    from arknights_video_pipeline.gui.i18n import init_i18n, i18n, tr
    init_i18n(language="zh-CN")          # MainWindow 启动时
    i18n().language_changed.connect(self._retranslate)  # widget 连接信号
    label.setText(tr("nav.home"))        # 翻译
"""

from arknights_video_pipeline.gui.i18n.manager import (
    I18n,
    init_i18n,
    i18n,
    tr,
)

__all__ = ["I18n", "init_i18n", "i18n", "tr"]
