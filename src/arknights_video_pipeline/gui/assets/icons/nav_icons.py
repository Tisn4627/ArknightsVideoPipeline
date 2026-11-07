"""
gui.assets.icons.nav_icons - MD3 图标资源加载与着色

统一使用 **Material Symbols Rounded**（Google 官方 24dp SVG，viewBox
``0 -960 960 960``），不再混用 Material Icons Filled / Rounded 两套族系。

- 每个图标同时提供 ``default``（未选中 / 常态）与 ``fill1``（选中 / 强调）
  两个变体；导航项在选中时按进度做 outline → filled 交叉淡入；
- SVG 经 ``QSvgRenderer`` 栅格化后以 alpha 蒙版染色，颜色由调用方传
  token，任意 DPI 下都保持清晰；
- 尺寸档位：20dp（密集列表）、24dp（标准）、40dp（空态 / 大图标）。
"""
from __future__ import annotations

import functools
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap

# 图标资源根目录（src/arknights_video_pipeline/gui/assets/icons/）
_ICON_ROOT: Path = Path(__file__).parent

# 全部资源来自 Material Symbols Rounded @ 24dp（Google Fonts）。
# 文件名映射：``<name>.svg`` 为 default（填充 0），``<name>_fill.svg``
# 为 fill1（填充 1）。导航项选中时使用 *_fill 变体。
# 值为相对 _ICON_ROOT 的子路径。
_ICON_FILES: dict[str, str] = {
    # 导航（Rounded：home / settings / build / info）
    "home": "svg/home.svg",
    "home_fill": "svg/home_fill.svg",
    "settings": "svg/settings.svg",
    "settings_fill": "svg/settings_fill.svg",
    "tools": "svg/build.svg",
    "tools_fill": "svg/build_fill.svg",
    "info": "svg/info.svg",
    "info_fill": "svg/info_fill.svg",
    # 复选框状态图标
    "check": "svg/check.svg",
    "check_box": "svg/check_box.svg",
    "check_box_fill": "svg/check_box_fill.svg",
    "check_box_outline_blank": "svg/check_box_outline_blank.svg",
    "check_box_outline_blank_fill": "svg/check_box_outline_blank_fill.svg",
    "indeterminate_check_box": "svg/indeterminate_check_box.svg",
    "indeterminate_check_box_fill": "svg/indeterminate_check_box_fill.svg",
    # 批量视频列表
    "arrow_upward": "svg/arrow_upward.svg",
    "arrow_upward_fill": "svg/arrow_upward_fill.svg",
    "arrow_downward": "svg/arrow_downward.svg",
    "arrow_downward_fill": "svg/arrow_downward_fill.svg",
    "delete": "svg/delete.svg",
    "delete_fill": "svg/delete_fill.svg",
    "pending": "svg/pending.svg",
    "pending_fill": "svg/pending_fill.svg",
    "check_circle": "svg/check_circle.svg",
    "check_circle_fill": "svg/check_circle_fill.svg",
    "error": "svg/error.svg",
    "error_fill": "svg/error_fill.svg",
    # 自定义作业 JSON
    "note_add": "svg/note_add.svg",
    "note_add_fill": "svg/note_add_fill.svg",
    "description": "svg/description.svg",
    "description_fill": "svg/description_fill.svg",
    # MD3 复合组件图标（FAB / 对话框 / 折叠 / 浏览）
    "warning": "svg/warning.svg",
    "warning_fill": "svg/warning_fill.svg",
    "add": "svg/add.svg",
    "add_fill": "svg/add_fill.svg",
    "expand_more": "svg/expand_more.svg",
    "expand_more_fill": "svg/expand_more_fill.svg",
    "folder_open": "svg/folder_open.svg",
    "folder_open_fill": "svg/folder_open_fill.svg",
}


def filled_name(name: str) -> str:
    """返回 ``name`` 对应的 filled 变体资源名（存在时）"""
    candidate = f"{name}_fill"
    return candidate if candidate in _ICON_FILES else name


@functools.lru_cache(maxsize=256)
def _load_source(name: str, size: int = 24, optical: int = 24) -> QImage | None:
    """加载原始 ARGB32 资源（带透明通道的黑色形状）。

    ``size`` 为 SVG 矢量栅格化的目标边长（像素）；``optical`` 选择
    Material Symbols 的 optical size 源文件（20 / 24 / 40），使图标在
    40dp 等大尺寸下不会被"放大 24dp 描边"变得过粗。缓存按
    (name, size, optical) 区分。
    """
    rel = _ICON_FILES.get(name)
    if rel is None:
        return None
    path = _ICON_ROOT / rel
    if optical != 24:
        # 同目录下的 <stem>_20 / _40 光学尺寸变体（缺失时回退 24dp）
        candidate = path.with_name(f"{path.stem}_{optical}{path.suffix}")
        if candidate.is_file():
            path = candidate
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
    # Material Symbols 的 optical size 轴：20 / 24 / 40。请求 18/20dp
    # 图标使用 20 光学源，>=32dp 使用 40 光学源，其余使用 24。
    optical = 20 if size_px <= 20 else (40 if size_px >= 32 else 24)
    src = _load_source(name, raster_size, optical)
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
