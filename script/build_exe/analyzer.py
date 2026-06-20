"""
analyzer - 依赖分析模块

通过 AST 解析 src 目录下所有 Python 文件的 import 语句，
结合已安装包信息，生成 PyInstaller 的 --exclude-module 列表，
以减小最终可执行文件体积。

主要功能:
    - 分析源码中实际使用的顶层导入名
    - 映射导入名到 PyPI 包名（处理 cv2/PIL 等不一致情况）
    - 识别未使用的已安装包，生成排除列表
    - 提供可选的标准库排除列表（默认不开启）
"""

from __future__ import annotations

import ast
import os
import sys
import sysconfig
from dataclasses import dataclass, field
from importlib.metadata import distributions
from typing import NamedTuple


# ── 导入名 → PyPI 包名 映射（处理不一致情况）──────────────

_IMPORT_TO_PACKAGE: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "serial": "pyserial",
    "OpenSSL": "pyOpenSSL",
    "Crypto": "pycryptodome",
    "attr": "attrs",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jose": "python-jose",
    "magic": "python-magic",
    "jwt": "PyJWT",
}


# ── 可安全排除的标准库模块（--clean-stdlib 时启用）─────────
# 这些模块体积较大且本项目不会使用，排除后可显著减小体积。
# 注意：此列表经过筛选，排除后不影响常规 Python 程序运行。

_STDLIB_EXCLUDES: list[str] = [
    # 测试与调试
    "unittest",
    "test",
    "tests",
    "pydoc",
    "doctest",
    "pdb",
    "profile",
    "pstats",
    # GUI（项目使用 PyQt6，不需要 tkinter）
    "tkinter",
    "turtle",
    # 编译与打包
    "distutils",
    "ensurepip",
    "venv",
    "pip",
    "setuptools",
    "wheel",
    # 数据库
    "sqlite3",
    "dbm",
    "gdbm",
    # 网络协议（项目不需要的）
    "http",  # 注意: 某些库可能间接依赖，排除后需测试
    "smtpd",
    "nntplib",
    "telnetlib",
    "ftplib",
    "poplib",
    "imaplib",
    # 其他不常用
    "crypt",
    "fcntl",
    "grp",
    "nis",
    "ossaudiodev",
    "spwd",
    "aifc",
    "au",
    "sunau",
    "chunk",
    "colorsys",
    "mailcap",
    "msilib",
    "msvcrt",
    "winreg",  # 注意: 项目 utils.py 中有条件使用 winreg，排除可能导致问题
]

# 从默认排除列表中移除项目可能需要的模块
_STDLIB_EXCLUDES = [
    m for m in _STDLIB_EXCLUDES if m != "winreg" and m != "http"
]


# ── 数据结构 ──────────────────────────────────────────────


class ImportInfo(NamedTuple):
    """单个导入信息"""

    module: str  # 顶层模块名
    source_file: str  # 来源文件


@dataclass
class AnalysisResult:
    """依赖分析结果"""

    used_imports: set[str] = field(default_factory=set)
    """源码中实际使用的顶层导入名集合"""

    used_packages: set[str] = field(default_factory=set)
    """映射后的 PyPI 包名集合"""

    installed_packages: dict[str, str] = field(default_factory=dict)
    """已安装包: {导入名: 包名}"""

    unused_packages: list[str] = field(default_factory=list)
    """未使用的包名列表（用于 --exclude-module）"""

    stdlib_excludes: list[str] = field(default_factory=list)
    """建议排除的标准库模块列表"""

    all_imports: list[ImportInfo] = field(default_factory=list)
    """所有导入的详细信息"""


# ── 核心分析逻辑 ──────────────────────────────────────────


class DependencyAnalyzer:
    """依赖分析器

    分析源码目录中的 import 语句，对比已安装的包，
    生成未使用包的排除列表供 PyInstaller 使用。

    Example:
        >>> analyzer = DependencyAnalyzer("src")
        >>> result = analyzer.analyze()
        >>> print(result.unused_packages)
        ['pytest', 'ruff', 'mypy']
    """

    # 本项目自身的包名（不应被排除）
    SELF_PACKAGES: set[str] = {"arknights_video_pipeline"}

    # PyInstaller 运行时必需的包（不应被排除）
    REQUIRED_PACKAGES: set[str] = {
        "PyQt6",
        "opencv-python",
        "numpy",
        "movielite",
        "pictex",
        "Pillow",
        "tqdm",
    }

    def __init__(self, source_dir: str) -> None:
        """初始化分析器

        Args:
            source_dir: 要分析的源码目录路径（通常是 src/）
        """
        self.source_dir = os.path.abspath(source_dir)
        if not os.path.isdir(self.source_dir):
            raise FileNotFoundError(f"源码目录不存在: {self.source_dir}")

    # ── AST 解析 ──────────────────────────────────────────

    def _parse_imports(self) -> list[ImportInfo]:
        """解析源码目录中所有 .py 文件的 import 语句

        使用 ast 模块进行语法分析，比正则表达式更准确。

        Returns:
            所有导入信息的列表
        """
        imports: list[ImportInfo] = []

        for root, dirs, files in os.walk(self.source_dir):
            # 跳过 __pycache__ 等目录
            dirs[:] = [d for d in dirs if d != "__pycache__"]

            for filename in files:
                if not filename.endswith(".py"):
                    continue

                filepath = os.path.join(root, filename)
                file_imports = self._parse_file(filepath)
                imports.extend(file_imports)

        return imports

    def _parse_file(self, filepath: str) -> list[ImportInfo]:
        """解析单个 Python 文件的 import 语句

        Args:
            filepath: Python 文件路径

        Returns:
            该文件中的导入信息列表
        """
        imports: list[ImportInfo] = []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=filepath)
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            # 跳过无法解析的文件
            print(f"  [WARN] 跳过无法解析的文件: {filepath} ({exc})")
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # import foo, bar.baz
                for alias in node.names:
                    top_level = alias.name.split(".")[0]
                    imports.append(ImportInfo(module=top_level, source_file=filepath))

            elif isinstance(node, ast.ImportFrom):
                # from foo.bar import baz
                # from . import baz (relative, node.level > 0)
                if node.module and node.level == 0:
                    top_level = node.module.split(".")[0]
                    imports.append(
                        ImportInfo(module=top_level, source_file=filepath)
                    )

        return imports

    # ── 已安装包检测 ──────────────────────────────────────

    def _get_installed_packages(self) -> dict[str, str]:
        """获取当前环境中已安装的包

        Returns:
            {顶层导入名: PyPI包名} 字典
        """
        packages: dict[str, str] = {}

        for dist in distributions():
            name = dist.metadata["Name"]
            if not name:
                continue

            # 获取该包的顶层模块
            top_levels = self._get_top_level_modules(dist)
            for tl in top_levels:
                if tl and tl not in packages:
                    packages[tl] = name

            # 同时用包名本身作为 key（处理包名=模块名的情况）
            normalized = name.replace("-", "_")
            if normalized not in packages:
                packages[normalized] = name

        return packages

    def _get_top_level_modules(self, dist) -> set[str]:
        """获取一个包的顶层模块名

        通过读取 RECORD 或 top_level.txt 推断。
        """
        top_levels: set[str] = set()

        # 方法1: top_level.txt
        try:
            tops = dist.read_text("top_level.txt")
            if tops:
                for line in tops.strip().splitlines():
                    line = line.strip()
                    if line:
                        top_levels.add(line)
        except Exception:
            pass

        # 方法2: 从 RECORD 文件推断
        if not top_levels:
            try:
                files = dist.files or []
                for f in files:
                    parts = str(f).replace("\\", "/").split("/")
                    if not parts:
                        continue
                    first = parts[0]
                    # 顶层 .py 文件 → 模块名
                    if first.endswith(".py") and len(parts) == 1:
                        top_levels.add(first[:-3])
                    # 顶层目录（包含 __init__.py）→ 包名
                    elif (
                        len(parts) > 1
                        and parts[-1] == "__init__.py"
                        and "." not in first
                        and "-" not in first
                    ):
                        top_levels.add(first)
            except Exception:
                pass

        return top_levels

    # ── 标准库路径检测 ────────────────────────────────────

    def _get_stdlib_path(self) -> str:
        """获取标准库目录路径"""
        return sysconfig.get_paths()["stdlib"]

    def _is_stdlib(self, module_name: str) -> bool:
        """判断模块是否属于标准库

        使用三种方式检测:
        1. sys.stdlib_module_names (Python 3.10+，最可靠)
        2. sys.builtin_module_names (内置编译模块)
        3. 文件系统检查 (回退方案)
        """
        # 方法1: sys.stdlib_module_names (Python 3.10+)
        stdlib_names = getattr(sys, "stdlib_module_names", None)
        if stdlib_names is not None:
            return module_name in stdlib_names

        # 方法2: 内置模块
        if module_name in sys.builtin_module_names:
            return True

        # 方法3: 文件系统检查（回退）
        stdlib_path = self._get_stdlib_path()
        module_path = os.path.join(stdlib_path, module_name)
        return os.path.exists(module_path + ".py") or os.path.isdir(module_path)

    # ── 主分析入口 ────────────────────────────────────────

    def analyze(self, clean_stdlib: bool = False) -> AnalysisResult:
        """执行完整的依赖分析

        Args:
            clean_stdlib: 是否生成标准库排除列表（默认 False）

        Returns:
            AnalysisResult 分析结果
        """
        print("[INFO] 开始依赖分析...")

        # 1. 解析源码中的 import
        all_imports = self._parse_imports()
        used_imports = {imp.module for imp in all_imports}
        print(f"  [OK] 发现 {len(used_imports)} 个不同的顶层导入")

        # 2. 获取已安装包
        installed = self._get_installed_packages()
        print(f"  [OK] 检测到 {len(installed)} 个已安装包")

        # 3. 映射导入名到包名
        used_packages: set[str] = set()
        for imp_name in used_imports:
            # 跳过标准库和项目自身包
            if imp_name in self.SELF_PACKAGES:
                continue
            if self._is_stdlib(imp_name):
                continue

            # 查找对应的包名
            pkg_name = _IMPORT_TO_PACKAGE.get(imp_name, imp_name)
            # 也检查 installed 字典
            if imp_name in installed:
                pkg_name = installed[imp_name]

            used_packages.add(pkg_name)

        print(f"  [OK] 实际使用 {len(used_packages)} 个第三方包")

        # 4. 计算未使用的包
        unused: list[str] = []
        for import_name, pkg_name in installed.items():
            # 跳过项目自身包
            if pkg_name in self.SELF_PACKAGES:
                continue
            # 跳过必需包
            if pkg_name in self.REQUIRED_PACKAGES:
                continue
            # 跳过 PyInstaller 自身及其依赖
            if pkg_name.lower() in ("pyinstaller", "altgraph", "pyinstaller-hooks-contrib"):
                continue
            # 如果包名或导入名在已使用列表中，跳过
            if pkg_name in used_packages or import_name in used_imports:
                continue
            # 跳过 setuptools/pip/wheel 等构建工具
            if pkg_name.lower() in ("setuptools", "pip", "wheel", "packaging"):
                continue

            # 添加导入名到排除列表（PyInstaller 使用导入名而非包名）
            if import_name not in unused:
                unused.append(import_name)

        print(f"  [OK] 识别出 {len(unused)} 个未使用的包可排除")

        # 5. 标准库排除列表
        stdlib_excludes: list[str] = []
        if clean_stdlib:
            stdlib_excludes = list(_STDLIB_EXCLUDES)
            print(f"  [OK] 生成 {len(stdlib_excludes)} 个标准库排除项")

        return AnalysisResult(
            used_imports=used_imports,
            used_packages=used_packages,
            installed_packages=installed,
            unused_packages=unused,
            stdlib_excludes=stdlib_excludes,
            all_imports=all_imports,
        )

    def get_exclude_modules(self, clean_stdlib: bool = False) -> list[str]:
        """获取 PyInstaller --exclude-module 参数列表

        Args:
            clean_stdlib: 是否包含标准库排除项

        Returns:
            排除模块名列表
        """
        result = self.analyze(clean_stdlib=clean_stdlib)
        excludes = list(result.unused_packages)
        if clean_stdlib:
            excludes.extend(result.stdlib_excludes)
        return excludes
