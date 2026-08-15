"""copilot 作业 JSON 生成模块。

把识别结果组装成符合 Maa copilot schema 的作业 JSON，用于 Maa 自动战斗
（copilot 模式）。

典型用法::

    from arknights_video_recognition.copilot import (
        CopilotJob, Action, ActionType, Direction, location_from_tile,
    )

    job = CopilotJob("main_00-01")
    job.add_oper("阿米娅", skill=2)
    job.add_speedup()
    job.add_action(ActionType.DEPLOY, name="阿米娅",
                   location=location_from_tile(row=3, col=5),
                   direction=Direction.RIGHT)
    job.add_action(ActionType.SKILL, name="阿米娅", kills=5)
    job.add_skill_daemon()
    job.set_doc("MAA AI - main_00-01", "测试作业")
    job.save("/tmp/test_job.json")
"""

from arknights_video_recognition.copilot.builder import (
    Action,
    ActionType,
    CopilotDoc,
    CopilotJob,
    Direction,
    Oper,
    OperRequirements,
    action_type_from_chinese,
    direction_from_chinese,
    location_from_tile,
)

__all__ = [
    "Action",
    "ActionType",
    "CopilotDoc",
    "CopilotJob",
    "Direction",
    "Oper",
    "OperRequirements",
    "action_type_from_chinese",
    "direction_from_chinese",
    "location_from_tile",
]
