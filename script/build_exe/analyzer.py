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
    "sunau",
    "chunk",
    "colorsys",
    "mailcap",
    "msilib",
    "msvcrt",
    "winreg",  # 注意: 项目 utils.py 中有条件使用 winreg，排除可能导致问题
]

# 从默认排除列表中移除项目或其依赖可能需要的模块：
# - winreg: 项目 utils.py / runtime_hook 的 ffmpeg 注册表回退在用
# - http:   某些第三方库可能间接依赖
# - msvcrt: Windows 下 click/colorama 系库运行期可能导入，排除会崩
_STDLIB_EXCLUDES = [
    m for m in _STDLIB_EXCLUDES if m not in ("winreg", "http", "msvcrt")
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

    protected_deps: set[str] = field(default_factory=set)
    """受保护的传递依赖集合（动态发现 + 硬编码兜底）。
    这些包是隐藏导入（movielite/pictex 等）的传递依赖，绝不能被排除，
    否则打包产物运行时报 ModuleNotFoundError。"""


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
        # Recognition 后端依赖（默认后端开箱即用）
        "onnxruntime",
        "rapidocr-onnxruntime",
    }

    # 隐藏导入（movielite/pictex 等）的运行时传递依赖——兜底集
    # 分析器仅扫描 src/ 源码的 import，无法感知隐藏导入自身的依赖；
    # 若这些依赖被 --clean-stdlib 或未使用包分析加入排除列表，
    # 打包产物会在运行时报 ModuleNotFoundError。
    #
    # 注意：此集合为兜底，主要保护由 _discover_transitive_deps() 动态发现。
    # 动态发现使用 importlib.metadata.requires() 读取包元数据的声明依赖，
    # 能自动适应版本升级带来的新依赖（如 pictex 2.x 新增 uharfbuzz/bidi 等）。
    # 此处的硬编码仅作为元数据缺失/不可读时的防御性补充，以及已知但
    # 元数据未声明的函数级导入（如 pictex 内部 bidi 的函数级 import）的保护。
    HIDDEN_IMPORT_DEPS: set[str] = {
        "numba",
        "llvmlite",
        "multiprocess",
        "_multiprocess",
        "skia",
        "skia_python",
        "uharfbuzz",
        "bidi",
        "python_bidi",
        "regex",
        "stretchable",
    }

    # 反向映射：PyPI 包名 → 顶层导入名（补充 _IMPORT_TO_PACKAGE 的反向查询）
    # 用于将动态发现的传递依赖包名映射回导入名，确保排除检查双向匹配
    _PACKAGE_TO_IMPORT: dict[str, str] = {
        "opencv-python": "cv2",
        "Pillow": "PIL",
        "scikit-image": "skimage",
        "scikit-learn": "sklearn",
        "PyYAML": "yaml",
        "beautifulsoup4": "bs4",
        "pyserial": "serial",
        "pyOpenSSL": "OpenSSL",
        "pycryptodome": "Crypto",
        "attrs": "attr",
        "python-dateutil": "dateutil",
        "python-dotenv": "dotenv",
        "python-jose": "jose",
        "python-magic": "magic",
        "PyJWT": "jwt",
        "python-bidi": "bidi",
        "skia-python": "skia",
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

    def _is_test_file(self, filepath: str, filename: str) -> bool:
        """判断文件是否为测试文件

        测试文件的导入不应参与依赖分析，否则 pytest/unittest.mock 等
        测试专用依赖会被误判为"已使用"而无法排除。

        Args:
            filepath: 文件完整路径
            filename: 文件名

        Returns:
            True 表示是测试文件
        """
        # 文件名匹配 test_*.py / *_test.py
        if filename.startswith("test_") or filename.endswith("_test.py"):
            return True
        # 路径中包含 tests/ 或 test/ 目录段
        parts = filepath.replace("\\", "/").split("/")
        return "tests" in parts or "test" in parts

    def _parse_imports(self) -> list[ImportInfo]:
        """解析源码目录中所有 .py 文件的 import 语句

        使用 ast 模块进行语法分析，比正则表达式更准确。
        跳过测试文件，避免测试专用导入污染依赖分析结果。

        Returns:
            所有导入信息的列表
        """
        imports: list[ImportInfo] = []

        for root, dirs, files in os.walk(self.source_dir):
            # 跳过 __pycache__ 和测试目录
            dirs[:] = [
                d for d in dirs
                if d != "__pycache__" and d not in ("tests", "test")
            ]

            for filename in files:
                if not filename.endswith(".py"):
                    continue

                filepath = os.path.join(root, filename)
                if self._is_test_file(filepath, filename):
                    continue

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

    # ── 传递依赖动态发现 ──────────────────────────────────

    def _discover_transitive_deps(self, root_packages: set[str]) -> set[str]:
        """动态发现一组包的全部传递依赖（导入名 + 包名）

        使用 importlib.metadata.requires() 读取包元数据声明的依赖，
        递归展开至叶子节点。这是彻底解决库遗漏问题的关键：
        当 movielite/pictex 等隐藏导入新增传递依赖时（如 pictex 2.x
        新增 uharfbuzz/bidi/regex/stretchable），本方法能自动发现并保护，
        无需手动维护硬编码列表。

        Args:
            root_packages: 起始包的 PyPI 名称集合（如 {"movielite", "pictex"}）

        Returns:
            受保护的标识符集合，包含每个传递依赖的:
              - 规范化 PyPI 包名（- 替换为 _）
              - 顶层导入名（通过 _PACKAGE_TO_IMPORT 映射）
            两种形式都加入集合，确保排除检查双向匹配。
        """
        protected: set[str] = set()
        # 待处理的包队列（规范化为 PyPI 名，- 保留）
        queue: list[str] = list(root_packages)
        visited: set[str] = set()

        while queue:
            pkg = queue.pop(0)
            # 规范化 key 用于去重（大小写不敏感、- 与 _ 等价）
            norm_key = pkg.lower().replace("-", "_")
            if norm_key in visited:
                continue
            visited.add(norm_key)

            # 获取该包声明的依赖
            try:
                from importlib.metadata import requires as _requires
                deps = _requires(pkg)
            except Exception:
                # 包未安装或元数据不可读，跳过（由 HIDDEN_IMPORT_DEPS 兜底）
                continue

            if not deps:
                continue

            for req_str in deps:
                # 解析需求字符串，提取包名
                # 格式示例: "numpy>=1.24", "Pillow>=10.0; extra == 'x'", "pictex"
                dep_name = self._parse_dep_name(req_str)
                if not dep_name:
                    continue

                # 环境标记过滤：extras 依赖与当前环境不满足的标记不纳入保护集
                if not self._dep_marker_applies(req_str):
                    continue

                # 跳过标准库（Python 自带，无需保护）
                if self._is_stdlib(dep_name.replace("-", "_")):
                    continue

                # 规范化：PyPI 名（- 形式）与导入名（_ 形式）
                dep_normalized = dep_name.replace("-", "_")
                protected.add(dep_normalized)
                protected.add(dep_name)

                # 同时加入导入名形式（如 python-bidi → bidi）
                import_name = self._PACKAGE_TO_IMPORT.get(dep_name)
                if import_name:
                    protected.add(import_name)
                # 也查 installed 字典的反向（但此处无 installed，用 _IMPORT_TO_PACKAGE 反查）
                for imp, pkg_n in _IMPORT_TO_PACKAGE.items():
                    if pkg_n.lower() == dep_name.lower():
                        protected.add(imp)

                # 递归：将此依赖加入队列继续展开（深度优先发现完整传递链）
                queue.append(dep_name)

        return protected

    @staticmethod
    def _parse_dep_name(req_str: str) -> str | None:
        """从需求字符串提取包名，解析失败返回 None

        优先用 packaging 规范解析（正确处理带环境标记/复杂版本约束的
        条目）；packaging 不可用时回退为取分号前的首个 token。
        """
        try:
            from packaging.requirements import Requirement
        except ImportError:
            import re

            match = re.match(
                r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req_str.split(";", 1)[0]
            )
            return match.group(1) if match else None
        try:
            return Requirement(req_str).name
        except Exception:
            return None

    @staticmethod
    def _dep_marker_applies(req_str: str) -> bool:
        """判断需求条目的环境标记是否适用于当前构建环境

        - 含 extra == 的条目属于可选 extras 依赖（如 dev 测试依赖），
          打包场景一律不纳入保护集，避免误打包导致体积膨胀；
        - 其余标记（如 sys_platform == 'win32'）按当前环境求值，
          求值失败时保守视为适用，宁可多保护不可漏保护。
        """
        _, _, marker_str = req_str.partition(";")
        marker_str = marker_str.strip()
        if not marker_str:
            return True
        if "extra" in marker_str:
            return False
        try:
            from packaging.markers import Marker

            return Marker(marker_str).evaluate()
        except Exception:
            return True

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

        # 4. 动态发现隐藏导入的传递依赖，构建保护集
        # 这一步是彻底解决库遗漏问题的关键：用 importlib.metadata.requires()
        # 递归读取必需包 + 实际使用包的声明依赖，自动适应版本升级带来的
        # 新依赖，不再依赖手动维护硬编码列表。
        # 注意起点必须包含 used_packages：仅扫 src/ 的分析无法感知
        # "已用包自身的依赖"（如 rapidocr 的 pyclipper/Shapely/PyYAML/six、
        # onnxruntime 的 flatbuffers/protobuf），遗漏会导致运行时崩溃。
        # HIDDEN_IMPORT_DEPS 作为元数据缺失时的兜底补充。
        discovered_deps = self._discover_transitive_deps(
            set(used_packages) | set(self.REQUIRED_PACKAGES)
        )
        protected_deps: set[str] = discovered_deps | self.HIDDEN_IMPORT_DEPS
        # 小写视图：包名大小写在元数据中不统一（如 rapidocr 声明 "Shapely"，
        # 实际安装名为 "shapely"），匹配时统一转小写避免漏保护
        protected_lower = {p.lower() for p in protected_deps}
        print(
            f"  [OK] 保护 {len(protected_deps)} 个传递依赖"
            f"（动态发现 {len(discovered_deps)}，兜底 {len(self.HIDDEN_IMPORT_DEPS)}）"
        )

        # 5. 计算未使用的包
        unused: list[str] = []
        for import_name, pkg_name in installed.items():
            # 跳过项目自身包
            if pkg_name in self.SELF_PACKAGES:
                continue
            # 跳过必需包
            if pkg_name in self.REQUIRED_PACKAGES:
                continue
            # 跳过隐藏导入的传递依赖（import_name 和 pkg_name 都要检查，
            # 因为 skia 的导入名是 "skia"，PyPI 包名是 "skia-python"）
            # 使用动态发现的保护集 + 硬编码兜底集，大小写不敏感匹配
            if (
                import_name.lower() in protected_lower
                or pkg_name.lower() in protected_lower
            ):
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

        # 6. 标准库排除列表
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
            protected_deps=protected_deps,
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
