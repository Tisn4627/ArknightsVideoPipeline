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


@functools.lru_cache(maxsize=32)
def _load_source(name: str) -> QImage | None:
    """加载原始 ARGB32 资源（带透明通道的黑色形状）。支持 SVG 和 PNG 格式。"""
    rel = _ICON_FILES.get(name)
    if rel is None:
        return None
    path = _ICON_ROOT / rel
    if not path.is_file():
        return None
    
    # 处理 SVG 文件
    if path.suffix.lower() == '.svg':
        return _load_svg_source(path)
    
    # 处理 PNG 文件
    img = QImage(str(path))
    if img.isNull():
        return None
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def _load_svg_source(path: Path) -> QImage | None:
    """从 SVG 文件加载图标源图像。
    
    使用 QtSvg 渲染 SVG 为 QImage，确保矢量图形正确缩放。
    """
    try:
        from PyQt6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return None
        
        # 创建固定尺寸的 QImage 用于着色处理
        image = QImage(24, 24, QImage.Format.Format_ARGB32)
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
    rel = _ICON_FILES.get(name)
    if rel is None:
        return False
    return (_ICON_ROOT / rel).is_file()

def icon_url(name: str) -> str | None:
    """返回 QSS `image: url(...)` 用的资源 URL（带 file:/// 前缀）。

    用于 QCheckBox::indicator 等支持 QSS image 属性的子控件，
    复选框选中/未选中/禁用三态可以直接引用不同图标。
    """
    rel = _ICON_FILES.get(name)
    if rel is None:
        return None
    path = _ICON_ROOT / rel
    if not path.is_file():
        return None
    # QUrl.fromLocalFile 处理 Windows 路径（含盘符与反斜杠），
    # 输出 file:///C:/.../xxx.png，可被 Qt QSS 正确解析。
    from PyQt6.QtCore import QUrl
    return QUrl.fromLocalFile(str(path)).toString()
