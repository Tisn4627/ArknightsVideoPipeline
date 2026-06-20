"""
core.step_defs - 流水线步骤统一定义

作为步骤元数据的单一事实源，供 GUI 步骤面板、工作线程、报告模型等复用，
避免多处独立维护导致的键名不一致问题。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDef:
    """单个步骤的定义"""
    key: str           # 信号传递用的短键名（如 "copilot"）
    method: str        # Pipeline 实例上的方法名（如 "step_video_to_copilot"）
    label: str         # 用户可见的中文描述
    percent: int       # 步骤开始时的进度百分比


# 流水线 5 个步骤的统一定义（顺序即执行顺序）
STEPS: list[StepDef] = [
    StepDef(key="copilot",   method="step_video_to_copilot",  label="视频转MAA作业JSON",   percent=10),
    StepDef(key="formation", method="step_formation_to_text", label="编队配置转文本",      percent=30),
    StepDef(key="actions",   method="step_actions_to_text",   label="操作指令转文本",      percent=50),
    StepDef(key="track",     method="step_track_startbutton", label="识别开始按钮时间戳",   percent=70),
    StepDef(key="compose",   method="step_video_compose",     label="视频合成",           percent=90),
]

# 按键名索引
STEPS_BY_KEY: dict[str, StepDef] = {s.key: s for s in STEPS}

# 按方法名索引
STEPS_BY_METHOD: dict[str, StepDef] = {s.method: s for s in STEPS}
