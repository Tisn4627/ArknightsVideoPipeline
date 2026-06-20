"""
runtime_hook - PyInstaller 运行时钩子

此文件通过 PyInstaller 的 --runtime-hook 参数注入，在主脚本执行前运行。

主要功能:
    1. 确保 ffmpeg/ffprobe 可在 PATH 中找到（Windows 注册表回退）
    2. 设置环境变量，标记当前处于打包环境

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

    # 确保 ffmpeg/ffprobe 在 PATH 中
    # 复用项目 utils.ensure_ffmpeg_in_path 的逻辑，
    # 但此处不能导入项目模块（会导致 PROJECT_ROOT 在 patch 前被计算）
    _ensure_ffmpeg_in_path()


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
