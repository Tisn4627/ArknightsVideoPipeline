"""
操作转文本脚本 - 将MAA作业中的操作转为可读文本
配置项：可控制是否显示技能、练度、模组信息
"""

import json
import os

from arknights_video_pipeline.core.utils import PROJECT_ROOT, load_config, save_default_config, MODULE_MAP

# 操作类型映射（中英文）
ACTION_TYPE_MAP = {
    "Deploy": "部署",
    "部署": "部署",
    "Skill": "技能",
    "技能": "技能",
    "Retreat": "撤退",
    "撤退": "撤退",
    "SpeedUp": "二倍速",
    "二倍速": "二倍速",
    "BulletTime": "子弹时间",
    "子弹时间": "子弹时间",
    "SkillDaemon": "摆完挂机",
    "摆完挂机": "摆完挂机",
    "MoveCamera": "移动镜头",
    "移动镜头": "移动镜头",
}

# 方向映射
DIRECTION_MAP = {
    "Left": "←",
    "Right": "→",
    "Up": "↑",
    "Down": "↓",
    "None": "",
    "左": "←",
    "右": "→",
    "上": "↑",
    "下": "↓",
    "无": "",
}

# 默认配置
DEFAULT_CONFIG = {
    "show_skill": False,
    "show_requirements": False,
    "show_module": False,
    "show_location": False,
    "show_direction": True,
    "show_delay": False,
    "show_conditions": False,
    "show_doc": False
}


def get_oper_info(name, opers_map, config):
    """根据干员名获取技能/练度/模组信息"""
    info_parts = []
    oper = opers_map.get(name)
    if not oper:
        return ""

    # 练度
    if config.get("show_requirements", False):
        requirements = oper.get("requirements", {})
        if requirements:
            req_parts = []
            elite = requirements.get("elite", 0)
            level = requirements.get("level", 0)
            skill_level = requirements.get("skill_level", 0)
            if elite and elite > 0:
                req_parts.append(f"精英{elite}")
            if level and level > 0:
                req_parts.append(f"Lv{level}")
            if skill_level and skill_level > 0:
                req_parts.append(f"专{skill_level - 7}" if skill_level > 7 else f"技能{skill_level}级")
            if req_parts:
                info_parts.append(" ".join(req_parts))

    # 模组
    if config.get("show_module", False):
        requirements = oper.get("requirements", {})
        if requirements:
            module = requirements.get("module", 0)
            if module and module > 0:
                info_parts.append(MODULE_MAP.get(module, f"模组{module}"))

    # 技能
    if config.get("show_skill", False):
        skill = oper.get("skill", 1)
        info_parts.append(f"{skill}技能")

    return " ".join(info_parts) if info_parts else ""


def format_action(action, index, opers_map, config):
    """格式化单条操作"""
    action_type = action.get("type", "Deploy")
    type_text = ACTION_TYPE_MAP.get(action_type, action_type)
    name = action.get("name", "")
    location = action.get("location", [])
    direction = action.get("direction", "")
    pre_delay = action.get("pre_delay", 0)
    post_delay = action.get("post_delay", 0)
    doc = action.get("doc", "")
    kills = action.get("kills", 0)
    costs = action.get("costs", 0)
    cost_changes = action.get("cost_changes", 0)

    parts = [f"{index}.{type_text}"]

    # 干员名 + 技能/练度/模组信息
    if name:
        oper_info = get_oper_info(name, opers_map, config)
        if oper_info:
            parts.append(f"{name} [{oper_info}]")
        else:
            parts.append(name)

    # 位置（默认值与 DEFAULT_CONFIG 中 show_location=False 保持一致）
    if config.get("show_location", False) and location:
        parts.append(f"({location[0]},{location[1]})")

    # 方向（DEFAULT_CONFIG 中 show_direction=True）
    if config.get("show_direction", True) and direction and direction != "None":
        dir_text = DIRECTION_MAP.get(direction, direction)
        parts.append(dir_text)

    # 条件（默认值与 DEFAULT_CONFIG 中 show_conditions=False 保持一致）
    if config.get("show_conditions", False):
        cond_parts = []
        if kills and kills > 0:
            cond_parts.append(f"击杀>={kills}")
        if costs and costs > 0:
            cond_parts.append(f"费用>={costs}")
        if cost_changes and cost_changes != 0:
            cond_parts.append(f"费用变化{cost_changes:+d}")
        if cond_parts:
            parts.append(f"[{'&'.join(cond_parts)}]")

    # 延时（默认值与 DEFAULT_CONFIG 中 show_delay=False 保持一致）
    if config.get("show_delay", False):
        if pre_delay and pre_delay > 0:
            parts.append(f"前延{pre_delay}ms")
        if post_delay and post_delay > 0:
            parts.append(f"后延{post_delay}ms")

    line = " ".join(parts)

    # 描述（默认值与 DEFAULT_CONFIG 中 show_doc=False 保持一致）
    if config.get("show_doc", False) and doc:
        line += f"\n  💬 {doc}"

    return line


def actions_to_text(data, config):
    """将操作数据转为文本"""
    lines = []

    # 构建干员名到信息的映射（opers + groups中的opers）
    opers_map = {}
    for oper in data.get("opers", []):
        opers_map[oper.get("name", "")] = oper
    for group in data.get("groups", []):
        for oper in group.get("opers", []):
            opers_map[oper.get("name", "")] = oper

    actions = data.get("actions", [])

    for i, action in enumerate(actions, 1):
        line = format_action(action, i, opers_map, config)
        lines.append(line)

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="操作转文本工具")
    parser.add_argument(
        "input",
        nargs="?",
        default=os.path.join(PROJECT_ROOT, "input.json"),
        help="MAA copilot JSON 文件路径 (默认: 项目根目录下的 input.json)",
    )
    args = parser.parse_args()

    config_dir = os.path.join(PROJECT_ROOT, "config")
    os.makedirs(config_dir, exist_ok=True)

    input_path = args.input
    config_path = os.path.join(config_dir, "actions.json")

    # 加载配置
    if not os.path.exists(config_path):
        save_default_config(config_path, DEFAULT_CONFIG)
        print(f"已生成默认配置文件: {config_path}")

    config = load_config(config_path, DEFAULT_CONFIG)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 输出标题信息
    doc = data.get("doc", {})
    title = doc.get("title", data.get("stage_name", "未知关卡"))
    print(f"=== {title} - 操作流程 ===")
    print()

    text = actions_to_text(data, config)
    print(text)


if __name__ == "__main__":
    main()
