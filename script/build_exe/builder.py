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
    # 注: 旧版本曾列出 "movielite.VideoQuality"，movielite 0.2.x 中它是
    # 包属性（enums.py 经 __init__ 导出）而非子模块，hidden-import 会报
    # not found；收集 movielite 包本身即已覆盖。
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
    # ctypes 子模块：MAA 的 asst.py 通过 sys.path.insert 运行时动态加载，
    # PyInstaller 静态分析无法检测到 asst.py 内部的 `import ctypes.util`，
    # 导致 ctypes.util（纯 Python 标准库子模块，非内置）未被打包，
    # 运行时报 `No module named 'ctypes.util'`。asst.py 在 OSError 回退路径
    # 用 ctypes.util.find_library('MaaCore') 查找 DLL。
    "ctypes",
    "ctypes.util",
    "ctypes.wintypes",
    # pictex 2.x 传递依赖：这些包不被 src/ 源码直接 import（仅 pictex 内部使用），
    # 分析器的未使用包分析会将其加入排除列表。bidi 还是函数级导入
    # （pictex/text/bidi_processor.py:89 `from bidi.algorithm import ...`），
    # PyInstaller modulegraph 对函数级导入检测不可靠。
    "uharfbuzz",
    "bidi",
    "regex",
    "stretchable",
]

# 项目内部通过 importlib.import_module() 动态导入的模块
# PyInstaller 静态分析无法检测变量参数的 import_module 调用，
# 这些模块在 _STYLE_MODULES / _MODULE_CONFIGS 字典中以字符串形式
# 引用，运行时才通过 importlib.import_module(module_name) 加载。
_PROJECT_HIDDEN_IMPORTS: list[str] = [
    "arknights_video_pipeline.core.video_compose",
    "arknights_video_pipeline.core.video_compose_style2",
    # recognition 后端：recognition_backend 在函数内延迟导入并在运行时
    # 注入 sys.path，PyInstaller 静态分析无法从标准搜索路径收集
    "arknights_video_recognition",
    "arknights_video_recognition.pipeline",
    "arknights_video_recognition.config.settings",
    # recognition 后端的函数级导入子包（modulegraph 对函数级导入检测
    # 不可靠，见下方 bidi 的同类问题）：
    # - tile: core/map_overlay.py 函数内 `from arknights_video_recognition.tile import ...`
    # - vision.templ_det_ocrer: formation/analyzer.py 函数内兜底导入，
    #   其内部再静态引用 multi_matcher / region_ocrer
    "arknights_video_recognition.tile",
    "arknights_video_recognition.vision.templ_det_ocrer",
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

# 始终排除的测试模块/子包（确保打包产物不含测试代码）
_TEST_EXCLUDES: list[str] = [
    "arknights_video_pipeline.tests",
    "arknights_video_pipeline.tests.test_batch_service",
    "arknights_video_pipeline.tests.test_batch_cli",
    "arknights_video_pipeline.tests.test_batch_video_list",
    "arknights_video_pipeline.tests.test_filename_encoding",
    "arknights_video_pipeline.tests.test_titlebar",
    "tests",
    "test",
    "unittest",
]

# 防御性排除的重型 PyQt6 子模块（项目未使用）
# 默认打包仅按隐藏导入收集实际使用的 QtCore/QtGui/QtWidgets
# （GUI 模式另加 QtSvg/QtSvgWidgets），不再全量收集 PyQt6——
# 全量收集会拖入全部 110 个 Qt 原生 DLL（约 207MB，实际仅需约 35MB）。
# 本列表防止未来某个传递依赖意外 import 重型 Qt 模块而拖入对应 DLL。
# --collect-pyqt6（排障逃生通道）启用时自动跳过本列表。
_QT_HEAVY_EXCLUDES: list[str] = [
    # WebEngine 家族（内嵌 Chromium，体积最大头）
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineQuick",
    "PyQt6.QtWebChannel",
    "PyQt6.QtWebSockets",
    # Qml/Quick 家族
    "PyQt6.QtQml",
    "PyQt6.QtQmlModels",
    "PyQt6.QtQuick",
    "PyQt6.QtQuickWidgets",
    "PyQt6.QtQuickControls2",
    "PyQt6.QtQuick3D",
    "PyQt6.QtLabsAnimation",
    "PyQt6.QtLabsFolderListModel",
    "PyQt6.QtLabsPlatform",
    "PyQt6.QtLabsQmlModels",
    "PyQt6.QtLabsSettings",
    "PyQt6.QtLabsSharedImage",
    "PyQt6.QtLabsWavefrontMesh",
    # 图表/数据可视化
    "PyQt6.QtCharts",
    "PyQt6.QtDataVisualization",
    # 多媒体/音视频（视频处理走 cv2/movielite，不经 Qt Multimedia）
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtSpatialAudio",
    "PyQt6.QtTextToSpeech",
    # PDF
    "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets",
    # 设计器/帮助/测试/数据库
    "PyQt6.QtDesigner",
    "PyQt6.QtHelp",
    "PyQt6.QtTest",
    "PyQt6.QtSql",
    # 传感器/定位/蓝牙等硬件相关
    "PyQt6.QtBluetooth",
    "PyQt6.QtNfc",
    "PyQt6.QtPositioning",
    "PyQt6.QtSensors",
    "PyQt6.QtSerialPort",
    "PyQt6.QtRemoteObjects",
    "PyQt6.QtStateMachine",
]

# UPX 压缩排除清单：这些 DLL 被压缩后运行时会崩溃或行为异常
# （VC 运行时与 Python 核心 DLL 不容忍 UPX 的按需解压加载方式）。
# 通过 PyInstaller 原生 --upx-exclude 传入（支持通配模式）。
_UPX_EXCLUDES: list[str] = [
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "vcruntime140_threads.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll",
    "msvcp140_codecvt_ids.dll",
    "concrt140.dll",
    "ucrtbase.dll",
    "python3.dll",
    "python3*.dll",
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
        use_upx: 是否启用 UPX 压缩（默认 False；可再减 35-45% 体积，
            但会增加杀毒软件误报率与启动时间）
        upx_path: upx 可执行文件路径（文件或所在目录均可，空则从 PATH 检测）
        collect_pyqt6: 排障逃生通道——恢复全量收集 PyQt6 子模块的旧行为
            （体积增加约 170MB，仅在裁剪模式导致 GUI 异常时使用）
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
    use_upx: bool = False
    upx_path: str = ""
    collect_pyqt6: bool = False

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
        self._upx_dir: str = ""  # 解析后的 UPX 所在目录（启用压缩时有效）

    # ── 公共接口 ──────────────────────────────────────────

    def build(self) -> bool:
        """执行完整打包流程

        Returns:
            True 表示打包成功，False 表示失败
        """
        self._build_start_time = time.time()

        try:
            # 先做环境检查再打印横幅：横幅中的 UPX 标签依赖
            # _check_environment 解析出的 _upx_dir，顺序颠倒会
            # 导致 --upx 时横幅只显示"启用"而缺少路径
            self._check_environment()
            self._print_banner()
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

        # 检查 UPX（如果启用）
        self._upx_dir = ""
        if self.config.use_upx:
            self._upx_dir = self._locate_upx()
            print(f"  [OK] UPX: {self._upx_dir}")
        elif shutil.which("upx"):
            # PyInstaller 在 PATH 中发现 upx 时会隐式启用压缩，
            # 未显式开启时提示用户，避免"以为没压缩其实压了"的认知偏差
            print("  [INFO] 检测到 PATH 中存在 upx，但未启用 --upx。")
            print("         PyInstaller 可能隐式应用 UPX 压缩；如需明确控制请加 --upx 参数")

    def _locate_upx(self) -> str:
        """定位 upx 可执行文件

        优先使用 --upx-path 指定路径（文件或所在目录均可），
        否则从 PATH 环境变量检测。

        Returns:
            upx.exe 所在目录（用于 PyInstaller --upx-dir）

        Raises:
            BuildError: 未找到有效的 upx 可执行文件
        """
        candidates: list[str] = []
        if self.config.upx_path:
            candidates.append(self.config.upx_path)
        else:
            which_hit = shutil.which("upx")
            if which_hit:
                candidates.append(which_hit)

        for cand in candidates:
            path = os.path.abspath(cand)
            if os.path.isdir(path):
                if os.path.isfile(os.path.join(path, "upx.exe")):
                    return path
            elif os.path.isfile(path):
                return os.path.dirname(path)

        raise BuildError(
            "未找到 UPX: 请通过 --upx-path 指定 upx.exe（或其所在目录），"
            "或将 upx.exe 加入 PATH。\n"
            "下载地址: https://github.com/upx/upx/releases"
        )

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
        excludes.extend(_TEST_EXCLUDES)
        if not self.config.collect_pyqt6:
            # 防御性排除重型 Qt 模块（全量收集排障模式下不适用）
            excludes.extend(_QT_HEAVY_EXCLUDES)
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

        捕获 PyInstaller 输出用于后续的库完整性自检
        （_verify_packaged_modules 解析缺失模块警告）。

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

        # 通过 Popen 调用 PyInstaller，实时显示输出同时捕获用于自检
        self._pyinstaller_output: list[str] = []
        try:
            proc = subprocess.Popen(
                args,
                cwd=self.config.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except FileNotFoundError:
            raise BuildError(
                "无法启动 PyInstaller，请确认已安装: pip install pyinstaller"
            )

        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            self._pyinstaller_output.append(line)
        proc.wait()

        if proc.returncode != 0:
            raise BuildError(
                f"PyInstaller 打包失败，退出码: {proc.returncode}\n"
                f"命令: {self._pyinstaller_cmd}"
            )

        print()
        print("  [OK] PyInstaller 打包完成")

    def _verify_packaged_modules(self) -> None:
        """打包后库完整性自检

        解析 PyInstaller 输出中的缺失模块警告，并对照 _HIDDEN_IMPORTS
        和动态发现的传递依赖进行交叉验证。发现缺失时打印警告，
        让开发者在打包阶段就发现问题，而非等到运行时崩溃。

        这是库遗漏问题的早期预警机制，配合 analyzer 的动态依赖发现
        形成双重保障：
          1. analyzer 动态发现 → 防止传递依赖被错误排除
          2. 本方法 → 检测 PyInstaller 自身未找到的隐藏导入
        """
        if not hasattr(self, "_pyinstaller_output"):
            return

        # 收集所有声明的隐藏导入
        declared_hidden = set(_HIDDEN_IMPORTS)
        declared_hidden.update(_PROJECT_HIDDEN_IMPORTS)
        if self.config.mode in ("gui", "combined"):
            declared_hidden.update(_GUI_HIDDEN_IMPORTS)
        declared_hidden.update(self.config.extra_hidden_imports)

        # 解析 PyInstaller 输出中的缺失模块警告
        # 典型格式: WARNING: Hidden import "foo" not found in PYZ
        # 或:       ERROR: Hidden import 'foo' not found（单双引号均兼容）
        missing_modules: list[str] = []
        for line in self._pyinstaller_output:
            stripped = line.strip()
            if "not found" not in stripped.lower():
                continue
            if "hidden import" not in stripped.lower():
                continue
            # 提取模块名（引号内的内容，单/双引号均支持）
            import re
            match = re.search(r"""[Hh]idden import ['"]([^'"]+)['"]""", stripped)
            if match:
                mod = match.group(1)
                if mod in declared_hidden:
                    missing_modules.append(mod)

        if missing_modules:
            print()
            print("  [WARN] 库完整性自检发现缺失的隐藏导入:")
            for mod in missing_modules:
                print(f"    - {mod}")
            print("  [WARN] 这些模块在打包环境中未安装，运行时可能报 ModuleNotFoundError")
            print("  [WARN] 请安装缺失的依赖后重新打包")
        else:
            print("  [OK] 库完整性自检通过：所有隐藏导入均已打包")

    # ── 产物审计 ──────────────────────────────────────────

    # 审计中判定为"不应出现"的重型 DLL 名称片段（对文件名小写匹配）。
    # 仅扫描 _internal/PyQt6 目录，避免误报 cv2 自带的
    # opencv_videoio_ffmpeg.dll（视频处理必需，位于 _internal/cv2 下）。
    # 注意: 不含 qt6pdf —— Qt6Pdf.dll 会经 QtGui 的 PDF 图像格式插件
    # （imageformats/qpdf.dll，QtGui 钩子默认收集）被连带复制，
    # 约 4.4MB，属预期行为；项目不渲染 PDF，无功能影响。
    _AUDIT_HEAVY_PATTERNS: tuple[str, ...] = (
        "qt6webengine",
        "qt6quick",
        "qt6qml",
        "qt6designer",
        "qt6charts",
        "avcodec",
        "avformat",
    )

    def _audit_output(self) -> None:
        """产物审计：校验关键依赖在/不在，输出体积分解

        - 应存在（GUI/combined 且非全量收集模式）：qwindows 平台插件与
          Qt6Core/Gui/Widgets —— 缺失说明 PyQt6 裁剪过度，直接报错
        - 应缺失：WebEngine/Quick/Qml 等重型 DLL —— 发现说明排除失效，警告
        - 体积分解：_internal 各组件降序输出，便于确认优化效果

        Raises:
            BuildError: 关键文件缺失（裁剪过度）
        """
        output_path = self._get_output_path()
        if self.config.onefile:
            print("  [INFO] onefile 单文件产物，跳过目录审计")
            return

        internal = os.path.join(output_path, "_internal")
        if not os.path.isdir(internal):
            print("  [WARN] 未找到 _internal 目录，跳过审计")
            return

        qt_bin = os.path.join(internal, "PyQt6", "Qt6", "bin")
        errors: list[str] = []
        warnings: list[str] = []

        # ── 应存在的关键文件 ──────────────────────────────
        if self.config.mode in ("gui", "combined") and not self.config.collect_pyqt6:
            required = [
                (
                    "平台插件 qwindows.dll",
                    os.path.join(
                        internal,
                        "PyQt6",
                        "Qt6",
                        "plugins",
                        "platforms",
                        "qwindows.dll",
                    ),
                ),
                ("Qt6Core.dll", os.path.join(qt_bin, "Qt6Core.dll")),
                ("Qt6Gui.dll", os.path.join(qt_bin, "Qt6Gui.dll")),
                ("Qt6Widgets.dll", os.path.join(qt_bin, "Qt6Widgets.dll")),
            ]
            for label, path in required:
                if os.path.isfile(path):
                    print(f"  [OK] 关键文件存在: {label}")
                else:
                    errors.append(f"{label} 缺失: {path}")

        # ── 应缺失的重型 DLL ──────────────────────────────
        heavy_found: list[str] = []
        pyqt_dir = os.path.join(internal, "PyQt6")
        if os.path.isdir(pyqt_dir):
            for root, _, files in os.walk(pyqt_dir):
                for f in files:
                    lower = f.lower()
                    if any(pat in lower for pat in self._AUDIT_HEAVY_PATTERNS):
                        heavy_found.append(
                            os.path.relpath(os.path.join(root, f), internal)
                        )
        if heavy_found:
            preview = ", ".join(heavy_found[:8])
            suffix = f" 等 {len(heavy_found)} 个" if len(heavy_found) > 8 else ""
            warnings.append(f"发现重型 Qt DLL（裁剪可能失效）: {preview}{suffix}")

        for w in warnings:
            print(f"  [WARN] {w}")

        # ── 体积分解 ──────────────────────────────────────
        entries: list[tuple[str, int]] = []
        for name in os.listdir(internal):
            entries.append((name, self._get_dir_size(os.path.join(internal, name))))
        entries.sort(key=lambda x: -x[1])
        print("  [INFO] _internal 体积分解 (前12):")
        for name, size in entries[:12]:
            print(f"    {self._format_size(size):>10}  {name}")

        if errors:
            raise BuildError(
                "产物审计失败:\n  "
                + "\n  ".join(errors)
                + "\n如为误判可使用 --collect-pyqt6 回退全量收集模式"
            )
        if not warnings:
            print("  [OK] 产物审计通过")

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
        hidden_imports.extend(_PROJECT_HIDDEN_IMPORTS)
        if self.config.mode in ("gui", "combined"):
            hidden_imports.extend(_GUI_HIDDEN_IMPORTS)
        hidden_imports.extend(self.config.extra_hidden_imports)

        for mod in hidden_imports:
            args.extend(["--hidden-import", mod])

        # recognition 后端代码（vendor 于 src/arknights_video_recognition，与父项目包
        # 平级共存）已由上方 --paths src_dir 覆盖，无需额外 pathex

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

        # PyQt6 收集策略：
        # 默认仅按隐藏导入收集实际使用的 QtCore/QtGui/QtWidgets
        # （GUI 模式另加 QtSvg/QtSvgWidgets），避免全量收集拖入全部
        # 110 个 Qt 原生 DLL（约 207MB，实际仅需约 35MB）。
        # --collect-pyqt6 为排障逃生通道，恢复旧的全量收集行为。
        if self.config.collect_pyqt6:
            args.extend(["--collect-submodules", "PyQt6"])

        # recognition 模块整体收集（34 个纯 Python 文件，体积可忽略）：
        # 该模块存在多处函数级导入（tile/vision 等），逐个维护隐藏导入
        # 易遗漏，整体收集一劳永逸
        args.extend(["--collect-submodules", "arknights_video_recognition"])

        # 收集 movielite 数据文件
        args.extend(["--collect-data", "movielite"])

        # UPX 压缩（可选）：指定 upx 目录并排除不可压缩的系统 DLL
        if self.config.use_upx and self._upx_dir:
            args.extend(["--upx-dir", self._upx_dir])
            for pattern in _UPX_EXCLUDES:
                args.extend(["--upx-exclude", pattern])

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

        # 库完整性自检：解析 PyInstaller 输出，检测缺失的隐藏导入
        self._verify_packaged_modules()

        # 产物审计：关键 DLL 在/不在检查 + 体积分解
        self._audit_output()

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

        # 创建 info.txt 提示文件
        self._create_readme(output_path)

        # 显示输出大小
        size = self._get_dir_size(output_path)
        size_str = self._format_size(size)
        print(f"  [OK] 输出大小: {size_str}")

    def _create_readme(self, output_path: str) -> None:
        """在输出目录创建 info.txt 提示文件"""
        readme_path = os.path.join(output_path, "info.txt")
        content = self._generate_readme_content()
        try:
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  [OK] 已生成提示文件: {readme_path}")
        except OSError:
            pass  # 非关键步骤，忽略错误

    def _generate_readme_content(self) -> str:
        """生成输出目录的 info.txt 内容"""
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
            "     首次启动时自动生成默认配置文件，无需手动操作。",
            "     如需重置为默认值，删除对应文件后重新启动即可，",
            "     或在命令行执行:",
        ]

        if self.config.mode == "gui":
            lines.append(f"       {self.config.name}.exe -- --init-config all")
        elif self.config.mode == "cli":
            lines.append(f"       {self.config.name}.exe --init-config all")
        else:
            lines.append(f"       {self.config.name}.exe --init-config all")

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
                "  首次启动时会自动在 exe 同级目录生成 config/ 默认配置。",
            ])
        elif self.config.mode == "cli":
            lines.extend([
                "  命令行运行:",
                "",
                "  首次运行会自动生成 config/ 默认配置文件。",
                "  如需手动重置配置:",
                f"    {self.config.name}.exe --init-config all",
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
                "  首次运行会自动生成 config/ 默认配置文件。",
                "  如需手动重置配置:",
                f"    {self.config.name}.exe --init-config all",
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
        if self.config.use_upx:
            upx_label = f"启用 ({self._upx_dir})" if self._upx_dir else "启用"
        else:
            upx_label = "关闭"
        print(f"  UPX:      {upx_label}")
        if self.config.collect_pyqt6:
            print("  PyQt6:    全量收集（排障模式，体积 +约170MB）")
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
        if self.config.use_upx:
            print("  UPX:      已应用压缩（排除系统运行时 DLL）")

        if self.config.mode == "gui":
            print(f"  启动方式: 双击 {self.config.name}.exe")
        elif self.config.mode == "cli":
            print(f"  启动方式: {self.config.name}.exe --help")
        else:
            print(f"  启动方式: {self.config.name}.exe (GUI) 或 {self.config.name}.exe <args> (CLI)")

        print()
        print("  注意: config/ 首次启动时自动生成; resource/ 和 MAA/ 需手动放置在 exe 所在目录")
        print("=" * 60)
        print()


# ── 异常定义 ──────────────────────────────────────────────


class BuildError(Exception):
    """打包构建异常"""
