"""
视频转MAA作业脚本 - 将战斗视频通过MAA识别引擎转换为copilot JSON作业文件
依赖: MAA项目（MaaCore.dll + resource目录）
"""

import argparse
import copy
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime

from arknights_video_pipeline.core.utils import (
    PROJECT_ROOT,
    ensure_ffmpeg_in_path,
    load_config,
    save_default_config,
    validate_video_file,
)

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


def _is_ascii_path(path: str) -> bool:
    """判断路径是否仅含 ASCII 字符"""
    try:
        path.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _get_short_path_name(long_path: str) -> str:
    """将长路径转换为 Windows 8.3 短路径。

    MAA C++ 的 path_to_crt_string 通过 wcstombs_s 将路径转为 CRT 多字节
    字符串后传给 cv::VideoCapture。当路径含非 ASCII 字符时，该转换的结果
    可能无法被 OpenCV 正确解析（导致 ``video_io open failed``）。8.3 短路径
    是纯 ASCII，可绕过所有编码问题，且引用的是同一个文件（无需临时文件）。

    Returns:
        8.3 短路径；如果转换失败或不可用则返回原始路径
    """
    import ctypes
    from ctypes import wintypes

    GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
    GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    GetShortPathNameW.restype = wintypes.DWORD

    buf_size = GetShortPathNameW(long_path, None, 0)
    if buf_size == 0:
        logger.debug(f"GetShortPathNameW 失败: {long_path}")
        return long_path

    buf = ctypes.create_unicode_buffer(buf_size)
    if GetShortPathNameW(long_path, buf, buf_size) == 0:
        logger.debug(f"GetShortPathNameW 第二次调用失败: {long_path}")
        return long_path

    short_path = buf.value
    logger.debug(f"短路径转换: {long_path} -> {short_path}")
    return short_path


def _make_ascii_video_path(video_path: str):
    """为含非 ASCII 字符的视频路径创建纯 ASCII 临时路径（回退方案）。

    当 8.3 短路径不可用（卷上禁用了 8.3 短文件名生成）时，通过硬链接
    （同卷，零拷贝）或复制（跨卷回退）创建纯 ASCII 临时文件。

    Returns:
        (ascii_path, cleanup_fn): cleanup_fn 用于识别结束后删除临时文件
    """
    ext = os.path.splitext(video_path)[1] or ".mp4"
    ascii_name = f"maa_video_{uuid.uuid4().hex}{ext}"
    ascii_path = os.path.join(tempfile.gettempdir(), ascii_name)

    try:
        os.link(video_path, ascii_path)
        logger.debug(f"已创建硬链接: {video_path} -> {ascii_path}")
    except OSError:
        logger.debug(f"硬链接失败，回退到复制: {video_path} -> {ascii_path}")
        shutil.copy2(video_path, ascii_path)

    def cleanup():
        try:
            os.remove(ascii_path)
        except OSError:
            pass

    return ascii_path, cleanup


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

    # MAA C++ 的 path_to_crt_string 通过 wcstombs_s 将路径转为 CRT 多字节
    # 字符串后传给 cv::VideoCapture。当路径含非 ASCII 字符时，转换结果可能
    # 无法被 OpenCV 正确解析（导致 ``video_io open failed``）。
    # 优先使用 Windows 8.3 短路径（纯 ASCII，引用同一文件，无临时文件）；
    # 8.3 不可用时回退到临时硬链接。
    if not _is_ascii_path(video_path):
        short_path = _get_short_path_name(video_path)
        if _is_ascii_path(short_path):
            ascii_video_path = short_path
            cleanup = None
            logger.info(f"视频路径含非ASCII字符，已转换为8.3短路径: {ascii_video_path}")
        else:
            ascii_video_path, cleanup = _make_ascii_video_path(video_path)
            logger.warning(
                f"8.3短路径仍含非ASCII字符（可能已禁用8.3短文件名），"
                f"回退到临时文件: {ascii_video_path}"
            )
    else:
        ascii_video_path = video_path
        cleanup = None

    try:
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
            "filename": ascii_video_path
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
                except Exception as exc:
                    # 停止失败不应掩盖超时错误，但需记录以便排查资源释放问题
                    logger.warning(f"MAA识别超时，停止任务失败: {exc}")
                raise TimeoutError(f"MAA识别超时({timeout}s)")
            time.sleep(0.5)

        logger.info("MAA视频识别完成")

        return result_json_path
    finally:
        if cleanup is not None:
            cleanup()


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
    # 识别结果 JSON 顶层可能是列表/标量（文件损坏或格式变更），
    # 提前给出明确错误而非在 .get() 处抛裸 AttributeError
    if combat_data is not None and not isinstance(combat_data, dict):
        raise ValueError(
            f"识别结果格式异常：顶层应为对象，实际为 {type(combat_data).__name__}"
        )
    # 如果识别数据已经是完整格式，直接使用
    # 使用 deepcopy 避免后续修改（doc/actions/opers）影响传入的 combat_data
    if combat_data and "stage_name" in combat_data:
        result = copy.deepcopy(combat_data)
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
    # 确保 ffmpeg/ffprobe 在 PATH 中（避免模块导入时产生全局副作用，
    # 仅在真正需要执行视频验证与 MAA 识别时才调用）
    ensure_ffmpeg_in_path()

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

    # 3. 创建输出目录（基于项目根目录；流水线注入的 output_dir 可能是绝对路径）
    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    output_dir_value = config.get("output_dir", "output")
    if os.path.isabs(output_dir_value):
        output_dir = output_dir_value
    else:
        output_dir = os.path.join(PROJECT_ROOT, output_dir_value, video_basename)
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"输出目录: {output_dir}")

    # 4. 执行MAA视频识别
    result_json_path = None

    try:
        result_json_path = run_maa_recognition(maa_path, video_path, timeout=timeout)
    except (ValueError, OSError, RuntimeError):
        # 保持异常类型身份：maa_backend 依赖 ValueError/FileNotFoundError
        # 的原始类型做 retryable 分类，pipeline 重试逻辑依赖 TimeoutError
        # （OSError 子类）识别超时；统一包装成 RuntimeError 会让确定性
        # 失败被无差别重试
        raise
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

    # 用 logger 而非 print：本函数会被 GUI/MAA 后端在 --noconsole 的
    # 打包环境下调用，print 输出会完全丢失
    logger.info("=" * 50)
    logger.info("  转换完成!")
    logger.info(f"  关卡: {stage_name}")
    logger.info(f"  干员数: {opers_count}")
    logger.info(f"  操作数: {actions_count}")
    logger.info(f"  输出: {json_path}")
    logger.info("=" * 50)

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
    # --init-config 只依赖 --config 路径，必须先于"未指定 --config 则
    # 落到 test.mp4 演示流程"处理，否则该开关会被静默忽略
    if args.init_config and config_path:
        save_default_config(config_path, DEFAULT_CONFIG)
        return

    if not config_path:
        config = DEFAULT_CONFIG.copy()
    else:
        # 加载配置（文件不存在时先生成默认配置）
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
