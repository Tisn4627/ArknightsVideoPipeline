"""
build_exe - ArknightsVideoPipeline 可执行文件打包工具

将项目 src 目录打包为 Windows 可执行文件(.exe)，支持 GUI、CLI、合并三种模式。

使用方式:
    python script/build_exe --mode gui
    python script/build_exe --mode cli
    python script/build_exe --mode combined
    python script/build_exe --help

详见 README.md。
"""

from script.build_exe.builder import BuildConfig, BuildManager

__all__ = ["BuildConfig", "BuildManager"]

__version__ = "1.0.0"
