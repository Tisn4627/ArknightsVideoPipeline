"""
视频转MAA作业脚本 - 将战斗视频通过MAA识别引擎转换为copilot JSON作业文件
依赖: MAA项目（MaaCore.dll + resource目录）
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from arknights_video_pipeline.core.utils import (
    PROJECT_ROOT,
    ensure_ffmpeg_in_path,
    load_config,
    save_default_config,
    validate_video_file,
)

# 修复PATH
ensure_ffmpeg_in_path()

# 模块级 logger（不在模块导入时调用 basicConfig，避免干扰全局日志配置；
# 由 pipeline.py 的 setup_logger 统一配置 root logger）
logger = logging.getLogger(__name__)

# 默认配置（maa_path/output_dir 由 pipeline.json 统一管理）
DEFAULT_CONFIG = {}


def validate_maa_path(maa_path):
    """验证MAA项目路径有效性"""
    if not maa_path or not maa_path.strip():
        raise ValueError(
            "MAA路径未配置。请在 config/pipeline.json 中设置 maa_path，"
            "或通过 --maa-path 参数指定。\n"
            "示例: python main.py video.mp4 -b bg.png --maa-path MAA-v5.12.1-win-x64"
        )

    if not os.path.exists(maa_path):
        raise FileNotFoundError(f"MAA目录不存在: {maa_path}")

    # 检查关键文件
    dll_path = os.path.join(maa_path, "MaaCore.dll")
    resource_path = os.path.join(maa_path, "resource")

    if not os.path.exists(dll_path):
        raise FileNotFoundError(f"未找到MaaCore.dll: {dll_path}")
    if not os.path.exists(resource_path):
        raise FileNotFoundError(f"未找到resource目录: {resource_path}")

    logger.info(f"MAA路径验证通过: {maa_path}")
    return True


def _safe_add_to_sys_path(path: str) -> str:
    """安全地将路径添加到 sys.path（修复 M10）

    对用户配置的 MAA Python 路径进行校验与规范化，防止路径注入风险：
      1. 解析为绝对路径（消除相对路径 / 符号链接歧义）
      2. 校验目录存在
      3. 校验目录下存在 asst 子目录（防御性检查，确认是合法的 MAA Python 目录）

    Args:
        path: 待添加的目录路径

    Returns:
        规范化后的绝对路径

    Raises:
        FileNotFoundError: 路径不存在或缺少 asst 子目录
    """
    abs_path = os.path.abspath(os.path.normpath(path))
    if not os.path.isdir(abs_path):
        raise FileNotFoundError(
            f"MAA Python 目录不存在或不是目录: {abs_path}"
        )
    # 防御性检查：确认目录下有 asst 子目录，避免误将任意目录加入 sys.path
    asst_dir = os.path.join(abs_path, "asst")
    if not os.path.isdir(asst_dir):
        raise FileNotFoundError(
            f"目录 {abs_path} 下未找到 asst 子目录，"
            f"请确认该路径指向 MAA 的 Python 目录"
        )
    # 幂等控制：仅在 sys.path 中不存在该路径时插入，避免重试时重复插入
    if abs_path not in sys.path:
        sys.path.insert(0, abs_path)
        logger.debug(f"已将 MAA Python 目录加入 sys.path: {abs_path}")
    return abs_path


def run_maa_recognition(maa_path, video_path, timeout=None):
    """
    使用MAA识别引擎分析战斗视频
    通过MAA的Python接口调用视频识别功能

    Args:
        maa_path: MAA 项目根目录
        video_path: 待识别的视频文件路径
        timeout: 超时时间（秒），None 表示不限制
    """
    maa_python_path = os.path.join(maa_path, "Python")
    # 安全地将 MAA Python 目录加入 sys.path（含路径校验，修复 M10）
    _safe_add_to_sys_path(maa_python_path)

    try:
        from asst.asst import Asst
        from asst.utils import Message, InstanceOptionType
    except ImportError as e:
        raise ImportError(f"无法导入MAA Python接口: {e}\n请确认MAA目录下存在Python/asst模块")

    # 加载MAA资源
    maa_abs_path = os.path.abspath(maa_path)
    if not Asst.load(path=maa_abs_path):
        raise RuntimeError("MAA资源加载失败")

    logger.info("MAA资源加载成功")

    # 创建实例
    result_json_path = None

    @Asst.CallBackType
    def callback(msg, details, arg):
        nonlocal result_json_path
        try:
            m = Message(msg)
            d = json.loads(details.decode("utf-8"))

            what = d.get("what", "")
            if m == Message.SubTaskExtraInfo and what == "Finished":
                filename = d.get("details", {}).get("filename", "")
                if filename:
                    result_json_path = filename
                    logger.info(f"识别结果文件: {filename}")
            elif m == Message.SubTaskStart:
                logger.info(f"  开始: {what}")
            elif m == Message.SubTaskCompleted:
                logger.info(f"  完成: {what}")
            elif m == Message.TaskChainError:
                logger.error(f"任务链错误: {d}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"callback 消息解析失败: {e}")

    asst = Asst(callback=callback)

    # 使用VideoRecognition任务进行视频识别
    task_id = asst.append_task("VideoRecognition", {
        "filename": video_path
    })

    if task_id == 0:
        raise RuntimeError("MAA任务创建失败")

    logger.info("开始MAA视频识别...")
    if not asst.start():
        raise RuntimeError("MAA任务启动失败")

    # 等待任务完成（带超时控制）
    start_time = time.time()
    while asst.running():
        if timeout and (time.time() - start_time) > timeout:
            try:
                asst.stop()
            except Exception:
                pass
            raise TimeoutError(f"MAA识别超时({timeout}s)")
        time.sleep(0.5)

    logger.info("MAA视频识别完成")

    return result_json_path


def load_recognition_result(result_json_path):
    """从MAA识别结果JSON文件中读取战斗数据"""
    if not result_json_path or not os.path.exists(result_json_path):
        return None

    with open(result_json_path, "r", encoding="utf-8") as f:
        combat_data = json.load(f)

    logger.info(f"已读取识别结果: {result_json_path}")
    return combat_data


def build_copilot_json(combat_data):
    """
    根据识别数据构建MAA copilot JSON
    符合MAA Combat Operation Protocol规范

    Args:
        combat_data: MAA 识别结果原始数据
    """
    # 如果识别数据已经是完整格式，直接使用
    if combat_data and "stage_name" in combat_data:
        result = combat_data.copy()
    else:
        # 构建基础结构
        result = {}

    # 确保必要字段
    stage_name = ""
    if combat_data:
        stage_name = combat_data.get("stage_name", "")
    if not stage_name:
        stage_name = "未知关卡"
        logger.warning("未识别到关卡名称，请手动修改stage_name字段")

    result["stage_name"] = stage_name

    # 最低版本要求
    result["minimum_required"] = "v4.0.0"

    # 文档信息
    doc = result.get("doc", {})
    if "title" not in doc:
        doc["title"] = f"视频识别 - {stage_name}"
    if "details" not in doc:
        doc["details"] = f"由video_to_copilot.py自动生成\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    result["doc"] = doc

    # 确保actions存在
    if "actions" not in result:
        result["actions"] = combat_data.get("actions", []) if combat_data else []

    # 确保opers存在
    if "opers" not in result:
        result["opers"] = combat_data.get("opers", []) if combat_data else []

    # 确保groups存在
    if "groups" not in result and combat_data and "groups" in combat_data:
        result["groups"] = combat_data["groups"]

    # 清理actions中空值字段
    # 注意：仅清理 None 和空字符串，保留 0/False 等合法假值
    # （MAA copilot 协议中 pre_delay=0、kills=0 等均为合法值）
    for action in result.get("actions", []):
        for key in list(action.keys()):
            if action[key] is None or action[key] == "":
                if key not in ("type", "name"):
                    del action[key]

    # 清理opers中空值字段
    for oper in result.get("opers", []):
        if "skill" not in oper:
            oper["skill"] = 1
        if "skill_usage" not in oper:
            oper["skill_usage"] = 0
        # 清理requirements中的空值（仅清理 None 和空字符串）
        req = oper.get("requirements", {})
        if req:
            for key in list(req.keys()):
                if req[key] is None or req[key] == "":
                    del req[key]
            if not req:
                del oper["requirements"]

    return result


def video_to_copilot(video_path, config, timeout=None):
    """主转换流程

    Args:
        video_path: 输入视频文件路径
        config: 配置字典
        timeout: MAA 识别超时时间（秒），None 表示不限制
    """
    # 1. 验证视频文件（复用 utils.validate_video_file 统一验证逻辑）
    logger.info(f"验证视频文件: {video_path}")
    video_info = validate_video_file(video_path)
    logger.info(
        f"视频信息: {video_info['width']}x{video_info['height']}, "
        f"时长{video_info['duration']:.2f}s"
    )

    # 2. 解析MAA路径（基于项目根目录）
    maa_path = config.get("maa_path", "")
    if maa_path and not os.path.isabs(maa_path):
        maa_path = os.path.join(PROJECT_ROOT, maa_path)
    validate_maa_path(maa_path)

    # 3. 创建输出目录（基于项目根目录）
    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    output_dir = os.path.join(PROJECT_ROOT, config.get("output_dir", "output"), video_basename)
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"输出目录: {output_dir}")

    # 4. 执行MAA视频识别
    result_json_path = None

    try:
        result_json_path = run_maa_recognition(maa_path, video_path, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"MAA视频识别失败: {e}") from e

    if not result_json_path:
        raise RuntimeError("MAA视频识别未生成结果文件")

    combat_data = load_recognition_result(result_json_path)
    if combat_data is None:
        raise RuntimeError("无法读取识别结果文件")

    # 5. 构建copilot JSON
    logger.info("构建MAA copilot JSON...")
    copilot_data = build_copilot_json(combat_data)

    # 6. 保存JSON文件
    json_filename = f"maa_copilot_{video_basename}.json"
    json_path = os.path.join(output_dir, json_filename)

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(copilot_data, f, indent=4, ensure_ascii=False)
        logger.info(f"JSON文件已保存: {json_path}")
    except IOError as e:
        logger.error(f"JSON文件写入失败: {e}")
        raise

    # 7. 输出确认信息
    actions_count = len(copilot_data.get("actions", []))
    opers_count = len(copilot_data.get("opers", []))
    stage_name = copilot_data.get("stage_name", "未知")

    print()
    print("=" * 50)
    print("  转换完成!")
    print(f"  关卡: {stage_name}")
    print(f"  干员数: {opers_count}")
    print(f"  操作数: {actions_count}")
    print(f"  输出: {json_path}")
    print("=" * 50)

    return json_path


def main():
    parser = argparse.ArgumentParser(description="视频转MAA作业JSON工具")
    parser.add_argument("video", nargs="?", default="test.mp4", help="视频文件路径 (默认: test.mp4)")
    parser.add_argument("--maa-path", default=None, help="MAA项目路径 (优先级高于配置文件)")
    parser.add_argument("--output-dir", default=None, help="输出目录 (优先级高于配置文件)")
    parser.add_argument("--config", default=None, help="配置文件路径 (可选，默认不使用配置文件)")
    parser.add_argument("--init-config", action="store_true", help="仅生成默认配置文件并退出")

    args = parser.parse_args()

    config_path = args.config
    if not config_path:
        config = DEFAULT_CONFIG.copy()
    else:
        # 生成默认配置
        if args.init_config:
            save_default_config(config_path, DEFAULT_CONFIG)
            return

        # 加载配置
        if not os.path.exists(config_path):
            save_default_config(config_path, DEFAULT_CONFIG)

        config = load_config(config_path, DEFAULT_CONFIG)

    # 命令行参数覆盖配置文件（命令行优先级最高）
    if args.maa_path:
        config["maa_path"] = args.maa_path
    if args.output_dir:
        config["output_dir"] = args.output_dir

    # 解析视频路径（基于项目根目录）
    video_path = args.video
    if not os.path.isabs(video_path):
        video_path = os.path.join(PROJECT_ROOT, video_path)

    # 执行转换
    try:
        video_to_copilot(video_path, config)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"未知错误: {e}")
        raise


if __name__ == "__main__":
    main()
