"""gui.theme.state - 状态层（墨层）、描边与 elevation token

MD3 的交互反馈不是"换一个底色"，而是在原容器上叠加一层 ``on_surface``
（或 ``on_primary`` 等前景色）的低透明度墨层：

| 状态 | 不透明度 |
|------|----------|
| hover | 8% |
| focus | 10% |
| pressed | 10% |
| dragged | 16% |
| disabled 容器 | 12% |
| disabled 内容 | 38% |

另外提供两件事：

- :func:`blend`：把墨层与底色按 alpha 混合成不透明色（QSS / 自绘都能用，
  因为 Qt 的 QSS 不支持 alpha 叠加，组件必须自己算好颜色）；
- :class:`Elevation`：MD3 的 key/ambient 双层阴影参数，以及折算成
  ``QGraphicsDropShadowEffect`` 单层参数的方法。
"""

from __future__ import annotations

from PyQt6.QtGui import QColor

__all__ = ["Border", "Elevation", "StateLayer", "blend", "with_alpha"]


class StateLayer:
    """墨层不透明度（MD3 标准）"""

    HOVER = 0.08
    FOCUS = 0.10
    PRESSED = 0.10
    DRAGGED = 0.16
    DISABLED_CONTAINER = 0.12
    DISABLED_CONTENT = 0.38


class Border:
    """描边宽度（px）"""

    OUTLINE = 1        # 常态描边
    FOCUS = 2          # 聚焦描边（内缩绘制，不改变几何）
    FOCUS_RING = 2     # 焦点环厚度
    FOCUS_RING_OFFSET = 2


def _clamp_byte(value: float) -> int:
    """浮点通道值 → 0-255 整数（四舍五入，与色调量化保持一致）"""
    return min(255, max(0, int(value + 0.5)))


def blend(base: str | QColor, overlay: str | QColor, alpha: float) -> QColor:
    """把 ``overlay`` 以 ``alpha`` 叠在 ``base`` 上，返回不透明混合色

    用于把"状态层"折算成 QSS 可用的实色，或自绘时的一次性取值。

    Args:
        base: 底色（hex 或 QColor）
        overlay: 墨层色（通常是 ``on_surface`` / ``on_primary``）
        alpha: 0-1，超出范围自动钳制

    Returns:
        混合后的不透明 ``QColor``（保留底色的 alpha）
    """
    base_color = QColor(base)
    overlay_color = QColor(overlay)
    ratio = min(1.0, max(0.0, float(alpha)))
    mixed = QColor(
        _clamp_byte(base_color.red() + (overlay_color.red() - base_color.red()) * ratio),
        _clamp_byte(base_color.green() + (overlay_color.green() - base_color.green()) * ratio),
        _clamp_byte(base_color.blue() + (overlay_color.blue() - base_color.blue()) * ratio),
    )
    mixed.setAlpha(base_color.alpha())
    return mixed


def with_alpha(color: str | QColor, alpha: float) -> QColor:
    """给颜色设置 0-1 的 alpha（返回新对象，不修改入参）"""
    result = QColor(color)
    result.setAlphaF(min(1.0, max(0.0, float(alpha))))
    return result


class Elevation:
    """MD3 elevation 0-5 的阴影参数

    MD3 每级由 **key shadow（umbra，低模糊高偏移）** 与 **ambient shadow
    （penumbra，高模糊低偏移）** 两层组成。Qt 一个控件只能挂一个
    ``QGraphicsDropShadowEffect``，因此 :meth:`effect` 折算为单层：
    模糊取 ambient 的扩散、偏移取 key 的位移、alpha 取 key 的不透明度。

    深色主题不靠加深黑色阴影表达抬升（几乎不可见），而是叠加
    ``surface_tint`` —— 见 :meth:`tint_alpha`。
    """

    #: level → ((ambient_blur, ambient_dy, ambient_alpha), (key_blur, key_dy, key_alpha))
    SPECS: dict[int, tuple[tuple[int, int, float], tuple[int, int, float]]] = {
        0: ((0, 0, 0.0), (0, 0, 0.0)),
        1: ((3, 1, 0.15), (2, 1, 0.30)),
        2: ((4, 1, 0.15), (6, 2, 0.30)),
        3: ((6, 1, 0.15), (8, 4, 0.30)),
        4: ((8, 2, 0.15), (10, 6, 0.30)),
        5: ((10, 4, 0.15), (12, 8, 0.30)),
    }

    #: 业务语义 → level
    CARD_ELEVATED = 1
    MENU = 2
    DIALOG = 3
    FAB = 3
    DRAWER = 4

    @classmethod
    def clamp(cls, level: int) -> int:
        """把层级钳制到 0-5"""
        return max(0, min(5, int(level)))

    @classmethod
    def effect(cls, level: int, dark: bool = False) -> tuple[int, int, int]:
        """折算为 ``QGraphicsDropShadowEffect`` 的 (blur, dy, alpha)

        Args:
            level: 0-5
            dark: 深色主题时小幅提高 alpha（黑色阴影在深色底上更难分辨）

        Returns:
            ``(blur_radius, y_offset, alpha_0_255)``；level 0 返回 ``(0, 0, 0)``
        """
        ambient, key = cls.SPECS[cls.clamp(level)]
        if level <= 0:
            return (0, 0, 0)
        blur = ambient[0] * 2  # QGraphicsDropShadowEffect 的 blurRadius ≈ 2σ
        alpha = _clamp_byte(key[2] * 255 + (20 if dark else 0))
        return (blur, key[1], alpha)

    @classmethod
    def tint_alpha(cls, level: int) -> float:
        """深色主题下 ``surface_tint`` 的叠加比例（表达抬升而非加黑阴影）"""
        return {0: 0.0, 1: 0.02, 2: 0.03, 3: 0.05, 4: 0.06, 5: 0.08}.get(
            cls.clamp(level), 0.0
        )
