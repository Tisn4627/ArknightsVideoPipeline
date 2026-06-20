"""
builder - 打包构建管理模块

封装 PyInstaller 打包流程，提供 GUI / CLI / 合并三种打包模式，
支持依赖分析、资源打包、输出清理等功能。

核心类:
    BuildConfig  - 打包配置数据类
    BuildManager - 打包构建管理器

使用示例:
    from script.build_exe import BuildConfig, BuildManager

    config = BuildConfig(mode="gui", include_resource=True)
    manager = BuildManager(config)
    manager.build()
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from script.build_exe.analyzer import DependencyAnalyzer
from script.build_exe.launchers import get_launcher


# ── 常量 ──────────────────────────────────────────────────

VALID_MODES = ("gui", "cli", "combined")

# PyInstaller 隐藏导入（PyInstaller 无法自动检测的模块）
_HIDDEN_IMPORTS: list[str] = [
    # movielite 内部动态导入
    "movielite",
    "movielite.VideoQuality",
    # pictex 字体加载
    "pictex",
    # PyQt6 插件
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    # numpy C 扩展
    "numpy",
    "numpy.core",
    # opencv
    "cv2",
    # tqdm
    "tqdm",
]

# GUI 模式额外的隐藏导入
_GUI_HIDDEN_IMPORTS: list[str] = [
    "PyQt6.QtSvg",
    "PyQt6.QtSvgWidgets",
]

# 始终排除的模块（项目不需要且体积较大）
_ALWAYS_EXCLUDE: list[str] = [
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "notebook",
    "jupyter",
    "pytest",
    "ruff",
    "mypy",
    "sphinx",
]


# ── 配置数据类 ────────────────────────────────────────────


@dataclass
class BuildConfig:
    """打包配置

    封装所有打包参数，可通过 BuildManager 构造函数或 CLI 传入。

    Attributes:
        mode: 打包模式，"gui" / "cli" / "combined"
        onefile: 是否使用单文件模式（默认 False，使用目录模式）
        include_resource: 是否打包 resource 目录（默认 False）
        clean_stdlib: 是否排除未使用的标准库（默认 False）
        clean_build: 构建前是否清理输出目录（默认 True）
        name: 可执行文件名称（默认根据模式自动生成）
        output_dir: 输出目录（默认 dist）
        work_dir: 工作目录（默认 build）
        icon: 图标文件路径（可选）
        no_console: 是否隐藏控制台窗口（GUI 模式默认 True）
        extra_excludes: 额外排除的模块列表
        extra_hidden_imports: 额外的隐藏导入列表
        project_root: 项目根目录（默认自动检测）
    """

    mode: str = "gui"
    onefile: bool = False
    include_resource: bool = False
    clean_stdlib: bool = False
    clean_build: bool = True
    name: str = ""
    output_dir: str = "dist"
    work_dir: str = "build"
    icon: str = ""
    no_console: bool = False
    extra_excludes: list[str] = field(default_factory=list)
    extra_hidden_imports: list[str] = field(default_factory=list)
    project_root: str = ""

    def __post_init__(self) -> None:
        """校验配置参数"""
        self.mode = self.mode.lower().strip()
        if self.mode not in VALID_MODES:
            valid = ", ".join(VALID_MODES)
            raise ValueError(f"无效的打包模式: {self.mode}，可选: {valid}")

        # 自动设置默认名称
        if not self.name:
            self.name = f"ArknightsVideoPipeline-{self.mode}"

        # 自动设置项目根目录
        if not self.project_root:
            self.project_root = self._find_project_root()

        # GUI 模式默认隐藏控制台
        if self.mode in ("gui", "combined") and not self.no_console:
            self.no_console = True

    def _find_project_root(self) -> str:
        """查找项目根目录（包含 pyproject.toml 的目录）"""
        current = os.path.dirname(os.path.abspath(__file__))
        for _ in range(6):
            if os.path.exists(os.path.join(current, "pyproject.toml")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        # 回退到当前工作目录
        return os.getcwd()

    @property
    def src_dir(self) -> str:
        """源码目录路径"""
        return os.path.join(self.project_root, "src")

    @property
    def resource_dir(self) -> str:
        """资源目录路径"""
        return os.path.join(self.project_root, "resource")

    @property
    def abs_output_dir(self) -> str:
        """输出目录绝对路径"""
        if os.path.isabs(self.output_dir):
            return self.output_dir
        return os.path.join(self.project_root, self.output_dir)

    @property
    def abs_work_dir(self) -> str:
        """工作目录绝对路径"""
        if os.path.isabs(self.work_dir):
            return self.work_dir
        return os.path.join(self.project_root, self.work_dir)


# ── 构建管理器 ────────────────────────────────────────────


class BuildManager:
    """打包构建管理器

    管理 PyInstaller 打包的完整流程:
        1. 环境检查（PyInstaller 是否安装）
        2. 依赖分析（识别未使用的包）
        3. 生成入口脚本
        4. 调用 PyInstaller 执行打包
        5. 后处理（复制资源、清理临时文件）
        6. 输出构建摘要

    Example:
        >>> config = BuildConfig(mode="gui", include_resource=True)
        >>> manager = BuildManager(config)
        >>> success = manager.build()
        >>> if success:
        ...     print("打包成功!")
    """

    def __init__(self, config: BuildConfig) -> None:
        """初始化构建管理器

        Args:
            config: 打包配置
        """
        self.config = config
        self._temp_dir: str | None = None
        self._build_start_time: float = 0
        self._pyinstaller_cmd: str = ""  # 记录最终命令，用于调试

    # ── 公共接口 ──────────────────────────────────────────

    def build(self) -> bool:
        """执行完整打包流程

        Returns:
            True 表示打包成功，False 表示失败
        """
        self._build_start_time = time.time()

        try:
            self._print_banner()
            self._check_environment()
            self._prepare_directories()
            excludes = self._analyze_dependencies()
            launcher_path = self._generate_launcher()
            self._run_pyinstaller(launcher_path, excludes)
            self._post_process()
            self._print_summary()
            return True

        except KeyboardInterrupt:
            print("\n[ERROR] 用户中断打包过程")
            return False
        except BuildError as exc:
            print(f"\n[ERROR] 打包失败: {exc}")
            return False
        except Exception as exc:
            print(f"\n[ERROR] 打包过程中发生未预期的错误: {exc}")
            import traceback

            traceback.print_exc()
            return False
        finally:
            self._cleanup_temp()

    # ── 环境检查 ──────────────────────────────────────────

    def _check_environment(self) -> None:
        """检查打包环境是否满足要求"""
        print("[1/6] 检查打包环境...")

        # 检查 Python 版本
        if sys.version_info < (3, 12):
            raise BuildError(
                f"Python 版本过低: {sys.version_info.major}.{sys.version_info.minor}，"
                f"需要 3.12+"
            )
        print(f"  [OK] Python {sys.version_info.major}.{sys.version_info.minor}")

        # 检查 PyInstaller 是否安装
        try:
            import PyInstaller  # noqa: F401

            version = PyInstaller.__version__
            print(f"  [OK] PyInstaller {version}")
        except ImportError:
            raise BuildError(
                "PyInstaller 未安装，请执行: pip install pyinstaller"
            )

        # 检查源码目录
        if not os.path.isdir(self.config.src_dir):
            raise BuildError(f"源码目录不存在: {self.config.src_dir}")
        print(f"  [OK] 源码目录: {self.config.src_dir}")

        # 检查项目包是否可导入
        avp_init = os.path.join(
            self.config.src_dir, "arknights_video_pipeline", "__init__.py"
        )
        if not os.path.isfile(avp_init):
            raise BuildError(
                f"未找到项目包: {avp_init}\n"
                f"请确认 src/arknights_video_pipeline/ 目录存在"
            )
        print(f"  [OK] 项目包: arknights_video_pipeline")

        # 检查图标文件（如果指定）
        if self.config.icon:
            if not os.path.isfile(self.config.icon):
                raise BuildError(f"图标文件不存在: {self.config.icon}")
            print(f"  [OK] 图标: {self.config.icon}")

    # ── 目录准备 ──────────────────────────────────────────

    def _prepare_directories(self) -> None:
        """准备输出和工作目录"""
        print("[2/6] 准备构建目录...")

        # 创建工作目录
        os.makedirs(self.config.abs_work_dir, exist_ok=True)
        print(f"  [OK] 工作目录: {self.config.abs_work_dir}")

        # 清理输出目录
        if self.config.clean_build:
            output_name = self.config.name
            output_path = os.path.join(self.config.abs_output_dir, output_name)
            if os.path.exists(output_path):
                print(f"  [INFO] 清理旧输出: {output_path}")
                shutil.rmtree(output_path, ignore_errors=True)

            # onefile 模式下也清理 exe 文件
            exe_path = os.path.join(self.config.abs_output_dir, f"{output_name}.exe")
            if os.path.exists(exe_path):
                os.remove(exe_path)

        os.makedirs(self.config.abs_output_dir, exist_ok=True)
        print(f"  [OK] 输出目录: {self.config.abs_output_dir}")

    # ── 依赖分析 ──────────────────────────────────────────

    def _analyze_dependencies(self) -> list[str]:
        """执行依赖分析，返回排除模块列表

        Returns:
            PyInstaller --exclude-module 参数列表
        """
        print("[3/6] 分析依赖...")

        analyzer = DependencyAnalyzer(self.config.src_dir)
        result = analyzer.analyze(clean_stdlib=self.config.clean_stdlib)

        # 合并排除列表
        excludes: list[str] = []
        excludes.extend(_ALWAYS_EXCLUDE)
        excludes.extend(result.unused_packages)
        if self.config.clean_stdlib:
            excludes.extend(result.stdlib_excludes)
        excludes.extend(self.config.extra_excludes)

        # 去重
        seen: set[str] = set()
        unique_excludes: list[str] = []
        for mod in excludes:
            if mod not in seen:
                seen.add(mod)
                unique_excludes.append(mod)

        print(f"  [OK] 共排除 {len(unique_excludes)} 个未使用模块")
        if unique_excludes:
            preview = ", ".join(unique_excludes[:10])
            suffix = "..." if len(unique_excludes) > 10 else ""
            print(f"  [INFO] 排除列表(前10): {preview}{suffix}")

        return unique_excludes

    # ── 入口脚本生成 ──────────────────────────────────────

    def _generate_launcher(self) -> str:
        """生成入口脚本

        Returns:
            入口脚本文件路径
        """
        print("[4/6] 生成入口脚本...")

        # 创建临时目录
        self._temp_dir = tempfile.mkdtemp(prefix="avp_build_")

        # 写入入口脚本
        launcher_content = get_launcher(self.config.mode)
        launcher_path = os.path.join(self._temp_dir, "launcher.py")
        with open(launcher_path, "w", encoding="utf-8") as f:
            f.write(launcher_content)

        print(f"  [OK] 入口脚本: {launcher_path}")
        print(f"  [OK] 打包模式: {self.config.mode}")

        return launcher_path

    # ── PyInstaller 调用 ──────────────────────────────────

    def _run_pyinstaller(self, launcher_path: str, excludes: list[str]) -> None:
        """调用 PyInstaller 执行打包

        Args:
            launcher_path: 入口脚本路径
            excludes: 排除模块列表
        """
        print("[5/6] 执行 PyInstaller 打包...")

        args: list[str] = self._build_pyinstaller_args(launcher_path, excludes)

        # 记录完整命令（用于调试）
        self._pyinstaller_cmd = " ".join(args)
        print(f"  [INFO] PyInstaller 命令:")
        print(f"  {self._pyinstaller_cmd}")
        print()

        # 通过子进程调用 PyInstaller（避免 in-process 的副作用）
        try:
            result = subprocess.run(
                args,
                cwd=self.config.project_root,
                # 实时输出，不缓冲
                stdout=None,
                stderr=None,
            )
        except FileNotFoundError:
            raise BuildError(
                "无法启动 PyInstaller，请确认已安装: pip install pyinstaller"
            )

        if result.returncode != 0:
            raise BuildError(
                f"PyInstaller 打包失败，退出码: {result.returncode}\n"
                f"命令: {self._pyinstaller_cmd}"
            )

        print()
        print("  [OK] PyInstaller 打包完成")

    def _build_pyinstaller_args(
        self, launcher_path: str, excludes: list[str]
    ) -> list[str]:
        """构建 PyInstaller 命令行参数

        Args:
            launcher_path: 入口脚本路径
            excludes: 排除模块列表

        Returns:
            PyInstaller 命令行参数列表
        """
        py_exe = sys.executable
        args: list[str] = [py_exe, "-m", "PyInstaller"]

        # 打包模式
        if self.config.onefile:
            args.append("--onefile")
        else:
            args.append("--onedir")

        # 名称
        args.extend(["--name", self.config.name])

        # 源码搜索路径
        args.extend(["--paths", self.config.src_dir])

        # 工作目录
        args.extend(["--workpath", self.config.abs_work_dir])
        args.extend(["--distpath", self.config.abs_output_dir])

        # 运行时钩子
        hook_path = os.path.join(os.path.dirname(__file__), "runtime_hook.py")
        args.extend(["--runtime-hook", hook_path])

        # 隐藏导入
        hidden_imports = list(_HIDDEN_IMPORTS)
        if self.config.mode in ("gui", "combined"):
            hidden_imports.extend(_GUI_HIDDEN_IMPORTS)
        hidden_imports.extend(self.config.extra_hidden_imports)

        for mod in hidden_imports:
            args.extend(["--hidden-import", mod])

        # 排除模块
        for mod in excludes:
            args.extend(["--exclude-module", mod])

        # 控制台窗口
        if self.config.no_console:
            args.append("--noconsole")

        # 图标
        if self.config.icon:
            args.extend(["--icon", self.config.icon])

        # 清理缓存
        args.append("--noconfirm")

        # 清理 PyInstaller 缓存（避免旧缓存导致问题）
        args.append("--clean")

        # GUI 资源数据
        if self.config.mode in ("gui", "combined"):
            gui_assets = os.path.join(
                self.config.src_dir,
                "arknights_video_pipeline",
                "gui",
                "assets",
            )
            if os.path.isdir(gui_assets):
                # Windows 使用 ; 作为分隔符
                sep = ";" if os.name == "nt" else ":"
                args.extend([
                    "--add-data",
                    f"{gui_assets}{sep}arknights_video_pipeline/gui/assets",
                ])

        # 可选: 打包 resource 目录
        if self.config.include_resource:
            resource_dir = self.config.resource_dir
            if os.path.isdir(resource_dir):
                sep = ";" if os.name == "nt" else ":"
                args.extend([
                    "--add-data",
                    f"{resource_dir}{sep}resource",
                ])
                print(f"  [INFO] 包含 resource 目录")
            else:
                print(f"  [WARN] resource 目录不存在，跳过: {resource_dir}")

        # 收集 PyQt6 子模块（确保完整打包）
        args.extend(["--collect-submodules", "PyQt6"])

        # 收集 movielite 数据文件
        args.extend(["--collect-data", "movielite"])

        # 入口脚本（必须放在最后）
        args.append(launcher_path)

        return args

    # ── 后处理 ────────────────────────────────────────────

    def _post_process(self) -> None:
        """打包后处理"""
        print("[6/6] 后处理...")

        output_path = self._get_output_path()

        if not os.path.exists(output_path):
            raise BuildError(
                f"输出文件不存在: {output_path}\n"
                f"PyInstaller 可能未成功完成打包"
            )

        # 如果未通过 --add-data 打包 resource，且用户选择包含资源，
        # 则复制 resource 目录到输出位置旁边
        # （--add-data 已经处理了打包到内部，这里额外复制一份到外部方便用户替换）
        if self.config.include_resource and not self.config.onefile:
            resource_dir = self.config.resource_dir
            if os.path.isdir(resource_dir):
                dest = os.path.join(output_path, "resource")
                if os.path.exists(dest):
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.copytree(resource_dir, dest)
                print(f"  [OK] 已复制 resource 到: {dest}")

        # 创建 README 提示文件
        self._create_readme(output_path)

        # 显示输出大小
        size = self._get_dir_size(output_path)
        size_str = self._format_size(size)
        print(f"  [OK] 输出大小: {size_str}")

    def _create_readme(self, output_path: str) -> None:
        """在输出目录创建使用说明"""
        readme_path = os.path.join(output_path, "使用说明.txt")
        content = self._generate_readme_content()
        try:
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  [OK] 已生成使用说明: {readme_path}")
        except OSError:
            pass  # 非关键步骤，忽略错误

    def _generate_readme_content(self) -> str:
        """生成输出目录的使用说明内容"""
        lines = [
            "=" * 60,
            "ArknightsVideoPipeline 打包输出",
            "=" * 60,
            "",
            f"打包模式: {self.config.mode}",
            f"打包时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "─" * 60,
            "运行前准备",
            "─" * 60,
            "",
            "请将以下目录/文件放置在本程序所在目录:",
            "",
            "  1. config/        - 配置文件目录",
            "     生成方式: 在命令行执行:",
        ]

        if self.config.mode == "gui":
            lines.append(f"       {self.config.name}.exe -- --init-config")
        elif self.config.mode == "cli":
            lines.append(f"       {self.config.name}.exe --init-config")
        else:
            lines.append(f"       {self.config.name}.exe --init-config")

        lines.extend([
            "",
            "  2. MAA/           - MAA 作业识别工具目录",
            "     从 https://github.com/MAAAssistantArknights 下载",
            "",
            "  3. resource/      - 资源文件目录（模板图片、字体）",
        ])

        if self.config.include_resource:
            lines.append("     (已随程序打包，如需替换可覆盖此目录)")
        else:
            lines.append("     (未打包，需从项目源码复制)")

        lines.extend([
            "",
            "─" * 60,
            "使用方式",
            "─" * 60,
            "",
        ])

        if self.config.mode == "gui":
            lines.extend([
                "  双击运行 .exe 文件即可启动图形界面。",
                "",
                "  首次运行前请先执行以下命令生成配置文件:",
                f"    {self.config.name}.exe -- --init-config",
            ])
        elif self.config.mode == "cli":
            lines.extend([
                "  命令行运行:",
                "",
                "  生成配置文件:",
                f"    {self.config.name}.exe --init-config",
                "",
                "  处理视频:",
                f"    {self.config.name}.exe video.mp4 -b bg.png",
                f"    {self.config.name}.exe video.mp4 -b bg.png --output-dir results",
                f"    {self.config.name}.exe video.mp4 -b bg.png --style style2",
            ])
        else:
            lines.extend([
                "  无参数 → 启动图形界面",
                "  有参数 → 启动命令行模式",
                "",
                "  生成配置文件:",
                f"    {self.config.name}.exe --init-config",
                "",
                "  处理视频(CLI模式):",
                f"    {self.config.name}.exe video.mp4 -b bg.png",
                "",
                "  启动GUI:",
                f"    {self.config.name}.exe",
            ])

        lines.extend([
            "",
            "─" * 60,
            "目录结构",
            "─" * 60,
            "",
            "  推荐的目录结构:",
            "",
            "  ├── " + self.config.name + ".exe",
            "  ├── config/           # 配置文件",
            "  ├── resource/         # 资源文件",
            "  ├── MAA/              # MAA 工具",
            "  └── output/           # 输出目录（自动创建）",
            "",
            "=" * 60,
        ])

        return "\n".join(lines)

    # ── 辅助方法 ──────────────────────────────────────────

    def _get_output_path(self) -> str:
        """获取输出路径"""
        if self.config.onefile:
            return os.path.join(
                self.config.abs_output_dir, f"{self.config.name}.exe"
            )
        return os.path.join(self.config.abs_output_dir, self.config.name)

    @staticmethod
    def _get_dir_size(path: str) -> int:
        """获取目录/文件大小"""
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total

    @staticmethod
    def _format_size(size: int) -> str:
        """格式化文件大小"""
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _cleanup_temp(self) -> None:
        """清理临时文件"""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except OSError:
                pass

    # ── 输出展示 ──────────────────────────────────────────

    def _print_banner(self) -> None:
        """打印构建横幅"""
        print()
        print("=" * 60)
        print("  ArknightsVideoPipeline 打包工具")
        print("=" * 60)
        print(f"  模式:     {self.config.mode}")
        print(f"  类型:     {'单文件(onefile)' if self.config.onefile else '目录(onedir)'}")
        print(f"  资源:     {'包含' if self.config.include_resource else '不包含'}")
        print(f"  清理标准库: {'是' if self.config.clean_stdlib else '否'}")
        print(f"  项目根:   {self.config.project_root}")
        print(f"  输出目录: {self.config.abs_output_dir}")
        print("=" * 60)
        print()

    def _print_summary(self) -> None:
        """打印构建摘要"""
        elapsed = time.time() - self._build_start_time
        output_path = self._get_output_path()

        print()
        print("=" * 60)
        print("  打包完成!")
        print("=" * 60)
        print(f"  耗时:     {elapsed:.1f}s")
        print(f"  输出路径: {output_path}")

        if self.config.mode == "gui":
            print(f"  启动方式: 双击 {self.config.name}.exe")
        elif self.config.mode == "cli":
            print(f"  启动方式: {self.config.name}.exe --help")
        else:
            print(f"  启动方式: {self.config.name}.exe (GUI) 或 {self.config.name}.exe <args> (CLI)")

        print()
        print("  注意: 运行前请将 config/、resource/、MAA/ 放置在 exe 所在目录")
        print("=" * 60)
        print()


# ── 异常定义 ──────────────────────────────────────────────


class BuildError(Exception):
    """打包构建异常"""
