"""
runtime_hook - PyInstaller 运行时钩子

此文件通过 PyInstaller 的 --runtime-hook 参数注入，在主脚本执行前运行。

主要功能:
    1. 在 noconsole 模式下将 None 的 sys.stdout/sys.stderr 重定向到 null sink
    2. 确保 ffmpeg/ffprobe 可在 PATH 中找到（Windows 注册表回退）
    3. 设置环境变量，标记当前处于打包环境
    4. 设置 AVR_RESOURCE_DIR 指向打包内的 resource（recognition 后端必需）

注意:
    PROJECT_ROOT 的修正逻辑在入口脚本(launcher)中处理，而非此处。
    因为 runtime_hook 执行时业务模块尚未导入，无法 patch PROJECT_ROOT。
    runtime_hook 主要用于环境级别的准备工作。
"""

from __future__ import annotations

import os
import sys


def _setup_environment() -> None:
    """设置打包环境"""

    # 标记当前处于 PyInstaller 打包环境
    os.environ["ARKNIGHTS_PIPELINE_PACKAGED"] = "1"

    # noconsole 模式下 sys.stdout/sys.stderr 为 None，替换为 null sink
    _redirect_null_stdio()

    # 确保 ffmpeg/ffprobe 在 PATH 中
    # 复用项目 utils.ensure_ffmpeg_in_path 的逻辑，
    # 但此处不能导入项目模块（会导致 PROJECT_ROOT 在 patch 前被计算）
    _ensure_ffmpeg_in_path()

    # recognition 后端资源目录（recognition_backend 在导入时读取该变量）
    # 打包时识别资源并入 resource/ 随 bundle 分发；_MEIPASS 为解包临时目录
    _ensure_recognition_resource_dir()


def _ensure_recognition_resource_dir() -> None:
    """设置 AVR_RESOURCE_DIR 指向打包内的 resource

    recognition 后端在导入 arknights_video_recognition 前读取
    AVR_RESOURCE_DIR 环境变量（见 core/recognition_backend.py）。
    打包环境下资源随 bundle 分发（--add-data <resource>;resource），
    此处将环境变量指向解包后的资源目录。

    非打包环境不设置，交由 recognition_backend 的默认路径解析。
    """
    if os.environ.get("ARKNIGHTS_PIPELINE_PACKAGED") != "1":
        return
    if os.environ.get("AVR_RESOURCE_DIR"):
        # 用户显式指定的资源目录优先
        return
    bundle_dir = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.abspath(sys.argv[0])
    )
    resource_dir = os.path.join(bundle_dir, "resource")
    if os.path.isdir(resource_dir):
        os.environ["AVR_RESOURCE_DIR"] = resource_dir


def _redirect_null_stdio() -> None:
    """将 None 的 sys.stdout/sys.stderr 重定向到 os.devnull

    PyInstaller --noconsole 模式（GUI/combined）下，sys.stdout 和 sys.stderr
    是 None。许多第三方库（tqdm、logging.StreamHandler 等）假设这两个流
    总是可用的，调用 .write() 时会抛
    ``AttributeError: 'NoneType' object has no attribute 'write'``。

    替换为 os.devnull 后，写入被静默丢弃，库能正常工作。
    launchers.py 中已有的 ``if sys.stderr is not None`` 防御检查仍有效
    （stream 不再为 None，但写入行为一致）。

    仅在流为 None 时替换，不影响 CLI 模式（终端运行时 stdout/stderr
    连接到终端，不是 None）。
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")


def _ensure_ffmpeg_in_path() -> None:
    """确保 ffmpeg/ffprobe 在 PATH 中

    复制自 core.utils.ensure_ffmpeg_in_path，避免导入项目模块。
    """
    import shutil

    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return

    machine_path = os.environ.get("PATH", "")
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ) as key:
            sys_path = winreg.QueryValueEx(key, "Path")[0]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            user_path = winreg.QueryValueEx(key, "Path")[0]
        os.environ["PATH"] = sys_path + ";" + user_path + ";" + machine_path
    except Exception:
        # 非 Windows 或注册表读取失败，静默跳过
        pass


# 执行环境设置
_setup_environment()
