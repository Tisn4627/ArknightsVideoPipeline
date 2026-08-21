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

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅供类型检查；运行时惰性导入，避免包导入即拉起构建实现
    from script.build_exe.builder import BuildConfig, BuildManager

__all__ = ["BuildConfig", "BuildManager"]

__version__ = "1.0.0"


def __getattr__(name: str):  # PEP 562 模块级 __getattr__
    if name in __all__:
        from script.build_exe import builder as _builder

        return getattr(_builder, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
