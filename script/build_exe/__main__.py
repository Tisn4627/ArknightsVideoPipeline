"""
__main__ - build_exe CLI 入口

支持以下运行方式:
    python script/build_exe [options]
    python -m script.build_exe [options]
    python -m script.build_exe --help

示例:
    # 打包 GUI 版本
    python script/build_exe --mode gui

    # 打包 CLI 版本（单文件模式）
    python script/build_exe --mode cli --onefile

    # 打包合并版本，包含资源
    python script/build_exe --mode combined --include-resource

    # 打包并清理未使用的标准库
    python script/build_exe --mode gui --clean-stdlib
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

# 确保项目根目录在 sys.path 中，支持以下运行方式:
#   python script/build_exe [options]      (脚本目录运行)
#   python -m script.build_exe [options]   (模块运行)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from script.build_exe.builder import BuildConfig, BuildManager


def create_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="build_exe",
        description=(
            "ArknightsVideoPipeline 可执行文件打包工具\n"
            "将项目 src 目录打包为 Windows .exe，支持 GUI / CLI / 合并三种模式。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
使用示例:
  # 打包 GUI 版本（目录模式，推荐）
  python script/build_exe --mode gui

  # 打包 CLI 版本（单文件模式）
  python script/build_exe --mode cli --onefile

  # 打包合并版本，包含 resource 资源
  python script/build_exe --mode combined --include-resource

  # 打包 GUI 版本，指定名称和图标
  python script/build_exe --mode gui --name MyAVP --icon app.ico

  # 打包并清理未使用的标准库（减小体积）
  python script/build_exe --mode gui --clean-stdlib

  # 仅分析依赖，不执行打包
  python script/build_exe --analyze-only

打包模式说明:
  gui       仅打包图形界面版本，双击 exe 启动 GUI
  cli       仅打包命令行版本，通过命令行参数控制
  combined  合并打包，无参数启动 GUI，有参数启动 CLI
""",
    )

    # ── 打包模式 ──────────────────────────────────────────
    parser.add_argument(
        "--mode", "-m",
        choices=["gui", "cli", "combined"],
        default="gui",
        help="打包模式 (默认: gui)",
    )

    # ── 打包类型 ──────────────────────────────────────────
    parser.add_argument(
        "--onefile",
        action="store_true",
        default=False,
        help="使用单文件模式打包 (默认: 目录模式 onedir)",
    )
    parser.add_argument(
        "--no-console",
        action="store_true",
        default=False,
        help="隐藏控制台窗口 (GUI/合并模式默认隐藏)",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        default=False,
        help="显示控制台窗口 (覆盖默认行为，用于调试)",
    )

    # ── 资源与依赖 ────────────────────────────────────────
    parser.add_argument(
        "--include-resource",
        action="store_true",
        default=False,
        help="打包 resource 资源目录 (模板图片、字体等)",
    )
    parser.add_argument(
        "--clean-stdlib",
        action="store_true",
        default=False,
        help="排除未使用的标准库模块 (默认不开启，可减小体积)",
    )
    parser.add_argument(
        "--no-clean-build",
        action="store_true",
        default=False,
        help="构建前不清理旧输出目录 (默认清理)",
    )

    # ── 输出配置 ──────────────────────────────────────────
    parser.add_argument(
        "--name", "-n",
        default="",
        help="可执行文件名称 (默认根据模式自动生成)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="dist",
        help="输出目录 (默认: dist)",
    )
    parser.add_argument(
        "--work-dir", "-w",
        default="build",
        help="构建工作目录 (默认: build)",
    )
    parser.add_argument(
        "--icon", "-i",
        default="",
        help="可执行文件图标路径 (.ico 格式)",
    )

    # ── 高级选项 ──────────────────────────────────────────
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="MODULE",
        help="额外排除的模块 (可多次使用)",
    )
    parser.add_argument(
        "--hidden-import",
        action="append",
        default=[],
        metavar="MODULE",
        help="额外添加的隐藏导入 (可多次使用)",
    )
    parser.add_argument(
        "--project-root",
        default="",
        help="项目根目录路径 (默认自动检测)",
    )

    # ── 工具选项 ──────────────────────────────────────────
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        default=False,
        help="仅执行依赖分析，不执行打包",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version="build_exe 1.0.0",
    )

    return parser


def run_analyze_only(config: BuildConfig) -> int:
    """仅执行依赖分析，不打包"""
    from script.build_exe.analyzer import DependencyAnalyzer

    print("=" * 60)
    print("  依赖分析 (仅分析模式)")
    print("=" * 60)
    print()

    analyzer = DependencyAnalyzer(config.src_dir)
    result = analyzer.analyze(clean_stdlib=config.clean_stdlib)

    print()
    print("─" * 60)
    print("分析结果汇总")
    print("─" * 60)
    print(f"  使用的顶层导入:    {len(result.used_imports)} 个")
    print(f"  使用的第三方包:    {len(result.used_packages)} 个")
    print(f"  已安装的包:        {len(result.installed_packages)} 个")
    print(f"  未使用的包(可排除): {len(result.unused_packages)} 个")
    if config.clean_stdlib:
        print(f"  标准库排除项:      {len(result.stdlib_excludes)} 个")

    print()
    print("─" * 60)
    print("使用的第三方包")
    print("─" * 60)
    for pkg in sorted(result.used_packages):
        print(f"  - {pkg}")

    print()
    print("─" * 60)
    print("未使用的包(建议排除)")
    print("─" * 60)
    if result.unused_packages:
        for pkg in sorted(result.unused_packages):
            print(f"  - {pkg}")
    else:
        print("  (无)")

    if config.clean_stdlib and result.stdlib_excludes:
        print()
        print("─" * 60)
        print("标准库排除项")
        print("─" * 60)
        for mod in sorted(result.stdlib_excludes):
            print(f"  - {mod}")

    print()
    print("=" * 60)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口

    Args:
        argv: 命令行参数 (默认使用 sys.argv)

    Returns:
        退出码 (0=成功, 非0=失败)
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    # 构建 BuildConfig
    config = BuildConfig(
        mode=args.mode,
        onefile=args.onefile,
        include_resource=args.include_resource,
        clean_stdlib=args.clean_stdlib,
        clean_build=not args.no_clean_build,
        name=args.name,
        output_dir=args.output_dir,
        work_dir=args.work_dir,
        icon=args.icon,
        no_console=args.no_console if not args.console else False,
        extra_excludes=args.exclude,
        extra_hidden_imports=args.hidden_import,
        project_root=args.project_root,
    )

    # 仅分析模式
    if args.analyze_only:
        return run_analyze_only(config)

    # 执行打包
    manager = BuildManager(config)
    success = manager.build()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
