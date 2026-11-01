"""gui.theme.motion - MD3 动效时长与缓动曲线

此前全站只有导航栏一处 180ms 的 ``InOutCubic`` 动画，其余交互全是硬切。
这里把时长与缓动收敛为 token，并提供全局开关 ``Motion.enabled``：

- 关闭时所有动画时长返回 0，组件直接落到目标状态；
- 测试（offscreen）与低配环境默认关闭，避免像素断言抖动。

注意：MD3 的动效原则是**只动绘制属性**（opacity / progress），不做几何
动画，因此这些 token 只用于 ``QPropertyAnimation`` 驱动自绘量。
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPointF

__all__ = ["Duration", "Easing", "Motion"]


class Duration:
    """动效时长（ms）"""

    SHORT1 = 100   # 墨层：hover
    SHORT2 = 150   # 墨层：press、页面切换、复选框勾选
    MEDIUM1 = 200  # 开关滑块、折叠展开、对话框出现
    MEDIUM2 = 250  # 导航指示器
    LONG1 = 300
    LONG2 = 400

    #: 全部合法时长（供测试断言）
    ALL: tuple[int, ...] = (SHORT1, SHORT2, MEDIUM1, MEDIUM2, LONG1, LONG2)


class Easing:
    """MD3 标准缓动曲线（cubic-bezier → ``QEasingCurve``）

    曲线为 (x1, y1, x2, y2)，终点固定 (1, 1)。
    """

    @staticmethod
    def _bezier(x1: float, y1: float, x2: float, y2: float) -> QEasingCurve:
        # Qt6 中自定义三次贝塞尔对应 Type.BezierSpline（Type.Bezier 已移除）
        curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
        curve.addCubicBezierSegment(
            QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0)
        )
        return curve

    @classmethod
    def standard(cls) -> QEasingCurve:
        """标准曲线 (0.2, 0, 0, 1)：最常用"""
        return cls._bezier(0.2, 0.0, 0.0, 1.0)

    @classmethod
    def standard_decelerate(cls) -> QEasingCurve:
        """减速 (0, 0, 0, 1)：入场、出现在屏幕内的元素"""
        return cls._bezier(0.0, 0.0, 0.0, 1.0)

    @classmethod
    def standard_accelerate(cls) -> QEasingCurve:
        """加速 (0.3, 0, 1, 1)：退场、离开屏幕的元素"""
        return cls._bezier(0.3, 0.0, 1.0, 1.0)

    @classmethod
    def emphasized(cls) -> QEasingCurve:
        """强调 (0.2, 0, 0, 1)：配合更长时长使用"""
        return cls._bezier(0.2, 0.0, 0.0, 1.0)

    @classmethod
    def emphasized_decelerate(cls) -> QEasingCurve:
        """强调减速 (0.05, 0.7, 0.1, 1)：指示器、面板入场"""
        return cls._bezier(0.05, 0.7, 0.1, 1.0)

    @classmethod
    def emphasized_accelerate(cls) -> QEasingCurve:
        """强调加速 (0.3, 0, 0.8, 0.15)：面板退场"""
        return cls._bezier(0.3, 0.0, 0.8, 0.15)

    @classmethod
    def linear(cls) -> QEasingCurve:
        """线性：进度类动画"""
        return QEasingCurve(QEasingCurve.Type.Linear)


class Motion:
    """动效全局开关与时长解析"""

    #: False 时所有动画时长归零（测试 / 低配环境 / 用户偏好）
    enabled: bool = True

    @classmethod
    def set_enabled(cls, enabled: bool) -> None:
        """全局开启动画/关闭动画"""
        cls.enabled = bool(enabled)

    @classmethod
    def duration(cls, milliseconds: int) -> int:
        """解析动画时长：关闭动画时返回 0

        Args:
            milliseconds: ``Duration`` 中的 token 值

        Returns:
            实际时长；0 表示应直接落值、不启动动画
        """
        return int(milliseconds) if cls.enabled else 0
