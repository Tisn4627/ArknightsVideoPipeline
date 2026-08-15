"""
gui.theme.font_manager - 本地字体加载与管理（纯原生）

使用 ``QFontDatabase.addApplicationFont`` 注册项目内置的字体文件，
使 GUI 不依赖系统安装字体即可离线渲染：

- ``Roboto-Variable.ttf``（可变字体，覆盖 100~900 全字重）
- ``NotoSansSC-Variable.ttf``（思源黑体简体中文可变字体，覆盖全字重）

设计要点：
- 文件缺失/注册失败时**静默回退**（仅记录 warning），由
  ``typography.MaterialTypography`` 的系统字体回退链兜底，保证任何
  环境都能启动。
- 注册结果模块级缓存，重复调用零开销（QFontDatabase 内部本身也是
  进程级注册表）。
- 中文字符渲染优先级：Noto Sans SC（内置）→ Microsoft YaHei /
  PingFang SC（系统回退，见 typography 的 family 链）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtGui import QFontDatabase, QGuiApplication

logger = logging.getLogger(__name__)

# 字体资源目录（gui/assets/fonts/）
_FONT_ROOT: Path = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# 内置字体文件（按注册顺序；缺失的自动跳过）
_FONT_FILES: tuple[str, ...] = (
    "Roboto-Variable.ttf",
    "NotoSansSC-Variable.ttf",
)

# 注册成功后从 QFontDatabase 查询到的字体族名（模块级缓存）
_FAMILIES: list[str] = []


class FontManager:
    """本地字体注册管理器"""

    @classmethod
    def load(cls) -> list[str]:
        """注册内置字体并返回可用字体族名列表

        Returns:
            成功注册的字体族名列表（如 ``["Roboto", "Noto Sans SC"]``）。
            无 QGuiApplication、文件缺失或注册失败时返回空列表。
        """
        if _FAMILIES:
            return list(_FAMILIES)
        if QGuiApplication.instance() is None:
            return []

        db = QFontDatabase
        for fname in _FONT_FILES:
            path = _FONT_ROOT / fname
            if not path.is_file():
                logger.warning("GUI 内置字体缺失，回退系统字体: %s", path)
                continue
            # Qt 6：addApplicationFont / applicationFontFamilies 为静态方法
            font_id = db.addApplicationFont(str(path))
            families = db.applicationFontFamilies(font_id) if font_id >= 0 else []
            if not families:
                logger.warning("GUI 字体注册失败，回退系统字体: %s", fname)
                continue
            _FAMILIES.extend(families)
            logger.info("已注册 GUI 字体: %s -> %s", fname, ", ".join(families))
        return list(_FAMILIES)

    @classmethod
    def available_families(cls) -> list[str]:
        """已注册的内置字体族名（未调用 load 时为按需加载结果）"""
        return cls.load()

    @classmethod
    def is_loaded(cls) -> bool:
        """内置字体是否已成功注册（至少一个）"""
        return bool(_FAMILIES)
