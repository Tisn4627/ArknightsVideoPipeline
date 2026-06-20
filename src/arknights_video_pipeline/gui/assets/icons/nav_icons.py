"""
gui.assets.icons.nav_icons - 导航栏 MD3 图标资源加载与着色

提供 24dp MD3 Material Icons (Filled) 资源加载、单色着色与高 DPI 适配，
避免外部依赖 material-design-icons-master 目录。
"""
from __future__ import annotations

import functools
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap


# 图标资源目录（src/arknights_video_pipeline/gui/assets/icons/nav/）
_ICON_DIR: Path = Path(__file__).parent / "nav"

# 当前 GUI 主要用作 24dp 导航项；@2x (48px) 在主流 HiDPI 上
# 渲染效果最佳，避免拉伸锯齿。文件名映射:
#   home / settings / info  -> Material Design Icons Filled Baseline
#   info 图标采用与 help 同等密度的 24dp @2x 资源，确保 nav rail 三项
#   图标在同一 24dp 网格下渲染尺寸一致、像素对齐。
_ICON_FILES: dict[str, str] = {
    "home": "home_24dp_2x.png",
    "settings": "settings_24dp_2x.png",
    "info": "info_24dp_2x.png",
    # 复选框状态图标（Material Symbols Rounded @ 24dp @2x）
    "check_box": "check_box_24dp_2x.png",
    "check_box_outline_blank": "check_box_outline_blank_24dp_2x.png",
    "indeterminate_check_box": "indeterminate_check_box_24dp_2x.png",
}


@functools.lru_cache(maxsize=16)
def _load_source(name: str) -> QImage | None:
    """加载原始 ARGB32 资源（带透明通道的黑色形状）。"""
    if name not in _ICON_FILES:
        return None
    path = _ICON_DIR / _ICON_FILES[name]
    if not path.is_file():
        return None
    img = QImage(str(path))
    if img.isNull():
        return None
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def make_icon_pixmap(name: str, color: QColor | str, size_px: int = 24) -> QPixmap | None:
    """按给定颜色与像素尺寸生成 QPixmap。

    实现思路：以源 PNG 的 alpha 通道作为形状蒙版，
    使用 QPainter.CompositionMode.SourceIn 将整个形状
    替换为给定颜色，再缩放到目标尺寸。
    """
    src = _load_source(name)
    if src is None:
        return None
    out = src.copy()  # ARGB32
    target = QColor(color)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), target)
    p.end()
    pix = QPixmap.fromImage(out)
    if size_px and (pix.width() != size_px or pix.height() != size_px):
        pix = pix.scaled(
            size_px, size_px,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pix


def has_icon(name: str) -> bool:
    """检查图标资源是否存在。"""
    if name not in _ICON_FILES:
        return False
    return (_ICON_DIR / _ICON_FILES[name]).is_file()


def icon_url(name: str) -> str | None:
    """返回 QSS `image: url(...)` 用的资源 URL（带 file:/// 前缀）。

    用于 QCheckBox::indicator 等支持 QSS image 属性的子控件，
    复选框选中/未选中/禁用三态可以直接引用不同图标。
    """
    if name not in _ICON_FILES:
        return None
    path = _ICON_DIR / _ICON_FILES[name]
    if not path.is_file():
        return None
    # QUrl.fromLocalFile 处理 Windows 路径（含盘符与反斜杠），
    # 输出 file:///C:/.../xxx.png，可被 Qt QSS 正确解析。
    from PyQt6.QtCore import QUrl
    return QUrl.fromLocalFile(str(path)).toString()
