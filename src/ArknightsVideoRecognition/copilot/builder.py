"""Maa copilot 作业 JSON 组装器。

把识别结果组装成符合 Maa copilot schema（``resource/copilot/*.json``）的
作业 JSON，用于 Maa 自动战斗（copilot 模式）。schema 协议文档见
``/Maa/docs/zh-cn/protocol/copilot-schema.md``。

只使用标准库 ``dataclasses`` + ``json``，无额外依赖。

坐标约定
--------

Maa copilot 的 ``location`` 字段为 ``[x, y]``，其中 **x = 列 (col)、
y = 行 (row)**，与 ``levels.json`` 的 ``tiles[row][col]`` 一一对应。
（可在 https://map.ark-nights.com/areas 将"坐标展示"设为"MAA"查看。）
使用 :func:`location_from_tile` 把 tile 模块的 ``(row, col)`` 转成作业
``location``。
"""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# --- 枚举常量 ---------------------------------------------------------------
#
# Maa copilot schema 的 type / direction 同时接受中英文，但作业站发布仅
# 支持英文。这里用字符串常量类表示英文枚举值，并提供中文→英文映射表。


class ActionType:
    """操作类型枚举（schema ``actions[].type``）。"""

    DEPLOY = "Deploy"            # 部署
    SKILL = "Skill"              # 技能
    RETREAT = "Retreat"          # 撤退
    SPEED_UP = "SpeedUp"         # 二倍速
    BULLET_TIME = "BulletTime"   # 子弹时间
    SKILL_USAGE = "SkillUsage"   # 技能用法
    OUTPUT = "Output"            # 打印
    SKILL_DAEMON = "SkillDaemon"  # 摆完挂机
    MOVE_CAMERA = "MoveCamera"   # 移动镜头
    RESET_STOPWATCH = "ResetStopwatch"  # 重置全局计时器


class Direction:
    """部署朝向枚举（schema ``actions[].direction``）。"""

    LEFT = "Left"
    RIGHT = "Right"
    UP = "Up"
    DOWN = "Down"
    NONE = "None"


# 中文 → 英文 映射表（供 from_chinese 转换）
_ACTION_TYPE_CN_TO_EN: Dict[str, str] = {
    "部署": ActionType.DEPLOY,
    "技能": ActionType.SKILL,
    "撤退": ActionType.RETREAT,
    "二倍速": ActionType.SPEED_UP,
    "子弹时间": ActionType.BULLET_TIME,
    "技能用法": ActionType.SKILL_USAGE,
    "打印": ActionType.OUTPUT,
    "摆完挂机": ActionType.SKILL_DAEMON,
    "移动镜头": ActionType.MOVE_CAMERA,
    "重置全局计时器": ActionType.RESET_STOPWATCH,
    "重置计时": ActionType.RESET_STOPWATCH,  # 简称别名
}

_DIRECTION_CN_TO_EN: Dict[str, str] = {
    "左": Direction.LEFT,
    "右": Direction.RIGHT,
    "上": Direction.UP,
    "下": Direction.DOWN,
    "无": Direction.NONE,
}


def action_type_from_chinese(text: str) -> str:
    """中文操作类型转英文枚举值，未命中则原样返回。"""
    return _ACTION_TYPE_CN_TO_EN.get(text, text)


def direction_from_chinese(text: str) -> str:
    """中文朝向转英文枚举值，未命中则原样返回。"""
    return _DIRECTION_CN_TO_EN.get(text, text)


def location_from_tile(row: int, col: int) -> List[int]:
    """把 tile 模块的 ``(row, col)`` 转成 Maa copilot 作业的 ``location``。

    Maa copilot 的 ``location`` 为 ``[x, y]``，其中 **x = 列 (col)、
    y = 行 (row)**，与 ``levels.json`` 的 ``tiles[row][col]`` 对应。

    Parameters
    ----------
    row:
        地图行号（``tiles`` 的第一维下标）。
    col:
        地图列号（``tiles`` 的第二维下标）。

    Returns
    -------
    list[int]
        长度为 2 的 ``[x, y]`` 即 ``[col, row]``。
    """
    return [int(col), int(row)]


# --- dataclass：干员练度要求 -------------------------------------------------


@dataclass
class OperRequirements:
    """干员练度要求（schema ``opers[].requirements``，保留接口）。"""

    elite: Optional[int] = None        # 精英化等级
    level: Optional[int] = None        # 干员等级
    skill_level: Optional[int] = None  # 技能等级
    module: Optional[int] = None       # 模组编号
    module_level: Optional[int] = None  # 模组等级
    potential: Optional[int] = None    # 潜能要求

    def to_dict(self) -> Dict[str, Any]:
        """只输出非 None 字段。"""
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if getattr(self, f.name) is not None
        }


# --- dataclass：干员 ---------------------------------------------------------


@dataclass
class Oper:
    """干员定义（schema ``opers[]`` 数组元素）。"""

    name: str
    skill: Optional[int] = None          # 技能序号 [0, 3]
    skill_usage: Optional[int] = None    # 技能用法 0/1/2/3
    skill_times: Optional[int] = None    # 技能使用次数
    requirements: Optional[Union[OperRequirements, Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        """只输出非 None 字段，保持 JSON 简洁。"""
        d: Dict[str, Any] = {"name": self.name}
        if self.skill is not None:
            d["skill"] = self.skill
        if self.skill_usage is not None:
            d["skill_usage"] = self.skill_usage
        if self.skill_times is not None:
            d["skill_times"] = self.skill_times
        if self.requirements is not None:
            if isinstance(self.requirements, OperRequirements):
                req = self.requirements.to_dict()
            else:
                req = {k: v for k, v in self.requirements.items() if v is not None}
            if req:
                d["requirements"] = req
        return d


# --- dataclass：操作 ---------------------------------------------------------


@dataclass
class Action:
    """操作（schema ``actions[]`` 数组元素）。

    ``location`` 为 ``[x, y]``，x=列、y=行（见 :func:`location_from_tile`）。
    ``distance`` 为 ``[x, y]`` 格子数（仅 ``MoveCamera`` 使用），可为小数。
    """

    type: str
    name: Optional[str] = None
    location: Optional[List[int]] = None
    direction: Optional[str] = None
    kills: Optional[int] = None           # 击杀数条件
    costs: Optional[int] = None           # 费用条件
    cost_changes: Optional[int] = None    # 费用变化量条件
    cooling: Optional[int] = None         # CD 中干员数量条件
    time_elapsed: Optional[int] = None    # 全局计时条件（毫秒）
    skill_usage: Optional[int] = None     # 修改技能用法（SkillUsage 必选）
    skill_times: Optional[int] = None     # 技能使用次数
    pre_delay: Optional[int] = None       # 前置延时（毫秒）
    post_delay: Optional[int] = None      # 后置延时（毫秒）
    distance: Optional[List[float]] = None  # 镜头移动距离（MoveCamera 必选）
    doc: Optional[str] = None             # 描述
    doc_color: Optional[str] = None       # 描述文字颜色
    video_time: Optional[float] = None    # 视频内绝对时间戳（秒），非 Maa 标准扩展字段

    def to_dict(self) -> Dict[str, Any]:
        """只输出非 None 字段，``type`` 始终输出。"""
        d: Dict[str, Any] = {"type": self.type}
        for f in fields(self):
            if f.name == "type":
                continue
            v = getattr(self, f.name)
            if v is not None:
                d[f.name] = v
        return d


# --- dataclass：作业描述 -----------------------------------------------------


@dataclass
class CopilotDoc:
    """作业描述（schema 顶层 ``doc`` 对象）。"""

    title: str
    details: str = ""
    title_color: Optional[str] = None
    details_color: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"title": self.title, "details": self.details}
        if self.title_color is not None:
            d["title_color"] = self.title_color
        if self.details_color is not None:
            d["details_color"] = self.details_color
        return d


# --- CopilotJob：作业组装器 --------------------------------------------------


class CopilotJob:
    """Maa copilot 作业组装器。

    按照 Maa copilot schema 组装作业 JSON，用于自动战斗（copilot 模式）。

    典型用法::

        job = CopilotJob("main_00-01")
        job.add_oper("阿米娅", skill=2)
        job.add_speedup()
        job.add_action(ActionType.DEPLOY, name="阿米娅",
                       location=[5, 3], direction=Direction.RIGHT)
        job.add_action(ActionType.SKILL, name="阿米娅", location=[5, 3], kills=5)
        job.add_skill_daemon()
        job.set_doc("MAA AI - main_00-01", "测试作业")
        job.save("/tmp/test_job.json")
    """

    def __init__(self, stage_name: str, minimum_required: str = "v4.0.0"):
        """
        Parameters
        ----------
        stage_name:
            关卡标识，使用 stageId（如 ``main_00-01``）。
        minimum_required:
            最低要求 Maa 版本号，默认 ``v4.0.0``。
        """
        self.minimum_required = minimum_required
        self.stage_name = stage_name
        self.opers: List[Oper] = []
        self.groups: List[Dict[str, Any]] = []
        self.actions: List[Action] = []
        self.doc: Optional[CopilotDoc] = None
        self.difficulty: Optional[int] = None  # 0/1/2/3，None 表示不输出

    def add_oper(
        self,
        name: str,
        skill: Optional[int] = None,
        skill_usage: Optional[int] = None,
        skill_times: Optional[int] = None,
        requirements: Optional[Union[OperRequirements, Dict[str, Any]]] = None,
    ) -> Oper:
        """添加干员到 ``opers``。"""
        oper = Oper(
            name=name,
            skill=skill,
            skill_usage=skill_usage,
            skill_times=skill_times,
            requirements=requirements,
        )
        self.opers.append(oper)
        return oper

    def add_action(
        self,
        action: Union[Action, str, None] = None,
        name: Optional[str] = None,
        location: Optional[List[int]] = None,
        direction: Optional[str] = None,
        kills: Optional[int] = None,
        costs: Optional[int] = None,
        cost_changes: Optional[int] = None,
        cooling: Optional[int] = None,
        time_elapsed: Optional[int] = None,
        skill_usage: Optional[int] = None,
        skill_times: Optional[int] = None,
        pre_delay: Optional[int] = None,
        post_delay: Optional[int] = None,
        distance: Optional[List[float]] = None,
        doc: Optional[str] = None,
        doc_color: Optional[str] = None,
    ) -> Action:
        """添加操作到 ``actions``。

        支持两种调用方式：

        1. 传入 :class:`Action` 实例：``job.add_action(Action(type=...))``
        2. 传入 type 字符串加关键字参数：
           ``job.add_action(ActionType.DEPLOY, name=..., location=..., direction=...)``
        """
        if isinstance(action, Action):
            act = action
        else:
            # action 实为 type 字符串（或 None）
            if action is None:
                raise ValueError("add_action 需要传入 Action 实例或 type 字符串")
            act = Action(
                type=action,
                name=name,
                location=location,
                direction=direction,
                kills=kills,
                costs=costs,
                cost_changes=cost_changes,
                cooling=cooling,
                time_elapsed=time_elapsed,
                skill_usage=skill_usage,
                skill_times=skill_times,
                pre_delay=pre_delay,
                post_delay=post_delay,
                distance=distance,
                doc=doc,
                doc_color=doc_color,
            )
        self.actions.append(act)
        return act

    def set_doc(self, title: str, details: str = "") -> None:
        """设置作业描述。"""
        self.doc = CopilotDoc(title=title, details=details)

    def add_speedup(self) -> Action:
        """便捷添加 ``SpeedUp``（二倍速）动作，通常用于作业开头。"""
        return self.add_action(Action(type=ActionType.SPEED_UP))

    def add_skill_daemon(self) -> Action:
        """便捷添加 ``SkillDaemon``（摆完挂机）动作，通常用于作业结尾。"""
        return self.add_action(Action(type=ActionType.SKILL_DAEMON))

    def to_dict(self, with_video_time: bool = False) -> Dict[str, Any]:
        """组装完整作业 dict。

        字段顺序：``minimum_required, stage_name, opers, groups, actions,
        doc``（``difficulty`` 仅在设置时追加于末尾）。

        Parameters
        ----------
        with_video_time:
            为 True 时保留 actions 中的 ``video_time`` 扩展字段；为 False
            （默认）时剥离该字段，输出纯 Maa 标准格式（向后兼容）。
        """
        actions_list = [a.to_dict() for a in self.actions]
        if not with_video_time:
            for ad in actions_list:
                ad.pop("video_time", None)
        d: Dict[str, Any] = {
            "minimum_required": self.minimum_required,
            "stage_name": self.stage_name,
            "opers": [o.to_dict() for o in self.opers],
            "groups": self.groups,
            "actions": actions_list,
        }
        if self.doc is not None:
            d["doc"] = self.doc.to_dict()
        if self.difficulty is not None:
            d["difficulty"] = self.difficulty
        return d

    def to_json(
        self, indent: int = 2, ensure_ascii: bool = False,
        with_video_time: bool = False,
    ) -> str:
        """序列化为 JSON 字符串。"""
        return json.dumps(
            self.to_dict(with_video_time=with_video_time),
            indent=indent, ensure_ascii=ensure_ascii,
        )

    def save(self, path: Union[str, Path], with_video_time: bool = False) -> None:
        """写入文件（UTF-8 编码）。父目录不存在时自动创建。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            self.to_json(with_video_time=with_video_time), encoding="utf-8"
        )

    def validate(self) -> List[str]:
        """校验作业合法性，返回问题列表（空列表表示合法）。

        检查项：

        - ``stage_name`` 非空
        - ``actions`` 非空
        - ``Deploy`` 动作必须含 ``name`` / ``location`` / ``direction``
        - ``location`` 必须是长度为 2 的 ``[int, int]``
        - ``MoveCamera`` 动作必须含 ``distance``
        """
        problems: List[str] = []
        if not self.stage_name:
            problems.append("stage_name 不能为空")
        if not self.actions:
            problems.append("actions 不能为空")
        for i, a in enumerate(self.actions):
            if a.type == ActionType.DEPLOY:
                if not a.name:
                    problems.append(f"actions[{i}] Deploy 缺少 name")
                if not a.location:
                    problems.append(f"actions[{i}] Deploy 缺少 location")
                if not a.direction:
                    problems.append(f"actions[{i}] Deploy 缺少 direction")
            if a.type == ActionType.MOVE_CAMERA and not a.distance:
                problems.append(f"actions[{i}] MoveCamera 缺少 distance")
            if a.location is not None:
                if not (isinstance(a.location, (list, tuple)) and len(a.location) == 2):
                    problems.append(
                        f"actions[{i}] location 必须是长度为 2 的 [x, y]"
                    )
                elif not (
                    isinstance(a.location[0], int) and isinstance(a.location[1], int)
                ):
                    problems.append(
                        f"actions[{i}] location 元素必须为整数 [x, y]"
                    )
        return problems
