"""
编队转文本脚本 - 将MAA作业中的编队内容转为可读文本
格式：序号.（练度）（模组）（技能）（干员名）
"""

import json
import os

from arknights_video_pipeline.core.utils import PROJECT_ROOT, load_config, save_default_config, MODULE_MAP

# 默认配置
DEFAULT_CONFIG = {
    "show_skill": False,
    "show_requirements": False,
    "show_module": False
}


def format_requirements(requirements, config):
    """格式化练度和模组信息"""
    if not requirements:
        return "", ""

    elite = requirements.get("elite", 0)
    level = requirements.get("level", 0)
    skill_level = requirements.get("skill_level", 0)
    module = requirements.get("module", 0)
    potentiality = requirements.get("potentiality", 0)

    # 练度行（默认值与 DEFAULT_CONFIG 中 show_requirements=False 保持一致）
    level_text = ""
    if config.get("show_requirements", False):
        level_parts = []
        if elite and elite > 0:
            level_parts.append(f"精英{elite}")
        if level and level > 0:
            level_parts.append(f"Lv{level}")
        if skill_level and skill_level > 0:
            level_parts.append(f"专{skill_level - 7}" if skill_level > 7 else f"技能{skill_level}级")
        if potentiality and potentiality > 0:
            level_parts.append(f"潜{potentiality}")
        level_text = " ".join(level_parts)

    # 模组行（默认值与 DEFAULT_CONFIG 中 show_module=False 保持一致）
    module_text = ""
    if config.get("show_module", False):
        if module and module > 0:
            module_text = MODULE_MAP.get(module, f"模组{module}")

    return level_text, module_text


def formation_to_text(data, config):
    """将编队数据转为文本"""
    lines = []

    opers = data.get("opers", [])
    groups = data.get("groups", [])

    index = 1

    # 处理 opers 中的干员
    for oper in opers:
        name = oper.get("name", "未知")
        skill = oper.get("skill", 1)
        requirements = oper.get("requirements", {})

        # 技能信息（默认值与 DEFAULT_CONFIG 中 show_skill=False 保持一致）
        skill_text = f"{skill}技能" if config.get("show_skill", False) else ""

        # 练度和模组
        level_text, module_text = format_requirements(requirements, config)

        # 组装行：序号. 练度 模组 技能 干员名
        parts = [f"{index}."]
        if level_text:
            parts.append(level_text)
        if module_text:
            parts.append(module_text)
        if skill_text:
            parts.append(skill_text)
        parts.append(name)
        lines.append(" ".join(parts))

        index += 1

    # 处理 groups 中的干员组
    for group in groups:
        group_name = group.get("name", "未知组")
        group_opers = group.get("opers", [])

        lines.append(f"{index}.【{group_name}】")

        for oper in group_opers:
            name = oper.get("name", "未知")
            skill = oper.get("skill", 1)
            requirements = oper.get("requirements", {})

            skill_text = f"{skill}技能" if config.get("show_skill", False) else ""

            level_text, module_text = format_requirements(requirements, config)

            # 组装行：- 练度 模组 技能 干员名
            parts = ["  -"]
            if level_text:
                parts.append(level_text)
            if module_text:
                parts.append(module_text)
            if skill_text:
                parts.append(skill_text)
            parts.append(name)
            lines.append(" ".join(parts))

        index += 1

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="编队转文本工具")
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
    config_path = os.path.join(config_dir, "formation.json")

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
    print(f"=== {title} ===")
    print()

    text = formation_to_text(data, config)
    print(text)


if __name__ == "__main__":
    main()
