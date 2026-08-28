"""
gui.assets.icons.nav_icons - 导航栏 MD3 图标资源加载与着色

提供 24dp MD3 Material Icons (Filled) 资源加载、单色着色与高 DPI 适配，
避免外部依赖 material-design-icons-master 目录。
支持 SVG 图标格式，提供更好的缩放性和清晰度。
"""
from __future__ import annotations

import functools
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap


# 图标资源根目录（src/arknights_video_pipeline/gui/assets/icons/）
_ICON_ROOT: Path = Path(__file__).parent

# 当前 GUI 主要用作 24dp 导航项；@2x (48px) 在主流 HiDPI 上
# 渲染效果最佳，避免拉伸锯齿。文件名映射:
#   home / settings / tools / info  -> Material Design Icons Filled Baseline
#   check_box 系列 / batch 系列      -> Material Icons Rounded @24dp SVG
#       （源文件统一为 svg/ 目录下的 24x24 SVG，经 QSvgRenderer 渲染 +
#       alpha 蒙版染色，任意 DPI 下都保持清晰）
# 值为相对 _ICON_ROOT 的子路径。
_ICON_FILES: dict[str, str] = {
    "home": "svg/home.svg",
    "settings": "svg/settings.svg",
    "tools": "svg/tools.svg",
    "info": "svg/info.svg",
    # 复选框状态图标（Material Symbols Rounded @ 24dp）
    "check_box": "svg/check_box.svg",
    "check_box_outline_blank": "svg/check_box_outline_blank.svg",
    "indeterminate_check_box": "svg/indeterminate_check_box.svg",
    # 批量视频列表图标（Material Icons Rounded @ 24dp）
    "arrow_upward": "svg/arrow_upward.svg",
    "arrow_downward": "svg/arrow_downward.svg",
    "delete": "svg/delete.svg",
    "pending": "svg/pending.svg",
    "check_circle": "svg/check_circle.svg",
    "error": "svg/error.svg",
    # 自定义作业 JSON 图标（Material Symbols Rounded @ 24dp）
    "note_add": "svg/note_add.svg",
    "description": "svg/description.svg",
}


@functools.lru_cache(maxsize=64)
def _load_source(name: str, size: int = 24) -> QImage | None:
    """加载原始 ARGB32 资源（带透明通道的黑色形状）。支持 SVG 和 PNG 格式。

    ``size`` 仅对 SVG 生效：为矢量栅格化的目标边长（像素），缓存按
    (name, size) 区分，使不同请求尺寸都能获得矢量级清晰度。
    """
    rel = _ICON_FILES.get(name)
    if rel is None:
        return None
    path = _ICON_ROOT / rel
    if not path.is_file():
        return None

    # 处理 SVG 文件
    if path.suffix.lower() == '.svg':
        return _load_svg_source(path, size)

    # 处理 PNG 文件
    img = QImage(str(path))
    if img.isNull():
        return None
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def _load_svg_source(path: Path, size: int = 24) -> QImage | None:
    """从 SVG 文件加载图标源图像。

    使用 QtSvg 渲染 SVG 为 QImage，确保矢量图形正确缩放。
    ``size`` 为栅格化目标边长：按不小于请求尺寸渲染，避免先渲染成
    固定 24px 再放大导致的模糊。
    """
    try:
        from PyQt6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return None

        # 创建指定尺寸的 QImage 用于着色处理
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
        painter.end()

        return image
    except ImportError:
        # 如果 QtSvg 不可用，回退到 PNG 加载
        return None


def make_icon_pixmap(name: str, color: QColor | str, size_px: int = 24) -> QPixmap | None:
    """按给定颜色与像素尺寸生成 QPixmap。

    实现思路：以源图的 alpha 通道作为形状蒙版，
    使用 QPainter.CompositionMode.SourceIn 将整个形状
    替换为给定颜色，再缩放到目标尺寸。

    SVG 矢量源按 ``max(24, size_px * 2)`` 栅格化（取二者较大值）：
    24px 请求按 48px 渲染（与主流 HiDPI @2x 最佳实践一致），
    大于 24px 的请求按 2 倍尺寸渲染后再平滑缩放到目标尺寸，
    从而获得矢量级清晰度。
    """
    raster_size = max(24, size_px * 2) if size_px else 24
    src = _load_source(name, raster_size)
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
    rel = _ICON_FILES.get(name)
    if rel is None:
        return False
    return (_ICON_ROOT / rel).is_file()
