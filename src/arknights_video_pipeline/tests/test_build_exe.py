"""build_exe 打包工具单元测试

验证打包过程中正确排除 src 目录下的测试文件，确保生成的可执行文件
不含任何 test 相关代码与资源，同时不影响主程序功能。

覆盖两个层面:
  1. DependencyAnalyzer - AST 解析阶段跳过测试文件/目录
  2. BuildManager - PyInstaller 命令参数包含测试模块排除项
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from script.build_exe.analyzer import DependencyAnalyzer
from script.build_exe.builder import (
    _HIDDEN_IMPORTS,
    _PROJECT_HIDDEN_IMPORTS,
    _TEST_EXCLUDES,
    BuildConfig,
    BuildManager,
)


# ── DependencyAnalyzer: 测试文件跳过 ───────────────────────


class TestAnalyzerSkipsTestFiles:
    """验证 DependencyAnalyzer 在解析导入时跳过测试文件"""

    def _make_src_tree(self, tmpdir: str) -> str:
        """在临时目录中构造一个迷你 src 树

        结构:
            src/
            ├── pkg/
            │   ├── __init__.py
            │   ├── main.py        # 正常模块，import os, json
            │   └── test_inline.py  # 测试文件（文件名匹配），import pytest
            └── tests/
                ├── __init__.py
                └── test_main.py    # 测试目录中的测试文件，import unittest.mock
        """
        root = os.path.join(tmpdir, "src")
        pkg_dir = os.path.join(root, "pkg")
        tests_dir = os.path.join(root, "tests")
        os.makedirs(pkg_dir)
        os.makedirs(tests_dir)

        Path(os.path.join(pkg_dir, "__init__.py")).write_text("", encoding="utf-8")
        Path(os.path.join(pkg_dir, "main.py")).write_text(
            "import os\nimport json\n", encoding="utf-8"
        )
        # 测试文件（文件名匹配 test_*）— 应被跳过
        Path(os.path.join(pkg_dir, "test_inline.py")).write_text(
            "import pytest\n", encoding="utf-8"
        )
        Path(os.path.join(tests_dir, "__init__.py")).write_text("", encoding="utf-8")
        Path(os.path.join(tests_dir, "test_main.py")).write_text(
            "from unittest import mock\nimport pytest\n", encoding="utf-8"
        )
        return root

    def test_test_imports_not_in_used_imports(self, tmp_path: Path) -> None:
        """测试文件的导入不应出现在 used_imports 中"""
        src = self._make_src_tree(str(tmp_path))
        analyzer = DependencyAnalyzer(src)
        result = analyzer.analyze()

        assert "pytest" not in result.used_imports, (
            "pytest 来自测试文件，不应被计入已使用导入"
        )
        assert "unittest" not in result.used_imports, (
            "unittest 来自测试目录，不应被计入已使用导入"
        )

    def test_normal_imports_preserved(self, tmp_path: Path) -> None:
        """正常模块的导入应保留在 used_imports 中"""
        src = self._make_src_tree(str(tmp_path))
        analyzer = DependencyAnalyzer(src)
        result = analyzer.analyze()

        assert "os" in result.used_imports
        assert "json" in result.used_imports

    def test_is_test_file_filename_match(self, tmp_path: Path) -> None:
        """_is_test_file 正确识别 test_*.py / *_test.py"""
        analyzer = DependencyAnalyzer(str(tmp_path))
        assert analyzer._is_test_file("/foo/bar/test_foo.py", "test_foo.py")
        assert analyzer._is_test_file("/foo/bar/foo_test.py", "foo_test.py")

    def test_is_test_file_non_test(self, tmp_path: Path) -> None:
        """_is_test_file 不误判正常文件"""
        analyzer = DependencyAnalyzer(str(tmp_path))
        assert not analyzer._is_test_file("/foo/bar/main.py", "main.py")
        assert not analyzer._is_test_file("/foo/bar/utils.py", "utils.py")

    def test_is_test_file_in_tests_dir(self, tmp_path: Path) -> None:
        """_is_test_file 识别 tests/ 目录下的文件"""
        analyzer = DependencyAnalyzer(str(tmp_path))
        assert analyzer._is_test_file(
            os.path.join("src", "pkg", "tests", "anything.py"),
            "anything.py",
        )

    def test_tests_directory_pruned_from_walk(self, tmp_path: Path) -> None:
        """os.walk 时 tests 目录被剪枝，不递归进入"""
        src = self._make_src_tree(str(tmp_path))
        analyzer = DependencyAnalyzer(src)

        visited_files: list[str] = []
        for imp in analyzer._parse_imports():
            visited_files.append(imp.source_file)

        # 不应出现 tests/ 路径下的文件
        for f in visited_files:
            norm = f.replace("\\", "/")
            assert "/tests/" not in norm, f"测试目录文件不应被解析: {f}"

    def test_real_src_test_imports_excluded(self) -> None:
        """对真实项目 src 目录，pytest 不应出现在 used_imports 中

        这是回归测试：确保 src/arknights_video_pipeline/tests/ 下的
        测试文件不会让 pytest/unittest.mock 污染依赖分析。
        """
        project_root = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )
        src_dir = os.path.join(project_root, "src")
        if not os.path.isdir(src_dir):
            pytest.skip("找不到项目 src 目录")

        analyzer = DependencyAnalyzer(src_dir)
        result = analyzer.analyze()

        assert "pytest" not in result.used_imports
        assert "unittest" not in result.used_imports


# ── BuildManager: PyInstaller 排除参数 ──────────────────────


class TestBuildManagerTestExcludes:
    """验证 BuildManager 在 PyInstaller 参数中包含测试模块排除项"""

    @pytest.fixture
    def project_root(self) -> str:
        """获取项目根目录"""
        return os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )

    @pytest.fixture
    def manager(self, project_root: str) -> BuildManager:
        """构建一个 GUI 模式的 BuildManager（不执行打包）"""
        config = BuildConfig(mode="gui", project_root=project_root)
        return BuildManager(config)

    def test_test_excludes_constant_has_tests_package(self) -> None:
        """_TEST_EXCLUDES 包含项目测试子包"""
        assert "arknights_video_pipeline.tests" in _TEST_EXCLUDES
        assert "unittest" in _TEST_EXCLUDES

    def test_analyze_dependencies_includes_test_excludes(
        self, manager: BuildManager
    ) -> None:
        """_analyze_dependencies 返回的排除列表包含测试模块"""
        excludes = manager._analyze_dependencies()
        assert "arknights_video_pipeline.tests" in excludes
        assert "unittest" in excludes

    def test_pyinstaller_args_include_test_exclude(
        self, manager: BuildManager
    ) -> None:
        """PyInstaller 命令参数包含 --exclude-module arknights_video_pipeline.tests"""
        excludes = manager._analyze_dependencies()
        args = manager._build_pyinstaller_args("/tmp/launcher.py", excludes)

        # 在 args 中找到 --exclude-module 后跟测试包名
        for test_mod in (
            "arknights_video_pipeline.tests",
            "arknights_video_pipeline.tests.test_titlebar",
            "arknights_video_pipeline.tests.test_batch_service",
            "arknights_video_pipeline.tests.test_batch_cli",
            "arknights_video_pipeline.tests.test_batch_video_list",
            "arknights_video_pipeline.tests.test_filename_encoding",
        ):
            assert test_mod in args, (
                f"PyInstaller 参数缺少测试排除项: {test_mod}"
            )

    def test_pyinstaller_args_include_exclude_module_flag(
        self, manager: BuildManager
    ) -> None:
        """参数中出现 --exclude-module 标记且其后跟 arknights_video_pipeline.tests"""
        excludes = manager._analyze_dependencies()
        args = manager._build_pyinstaller_args("/tmp/launcher.py", excludes)

        # 找到 --exclude-module arknights_video_pipeline.tests 的相邻对
        found = False
        for i, arg in enumerate(args):
            if (
                arg == "--exclude-module"
                and i + 1 < len(args)
                and args[i + 1] == "arknights_video_pipeline.tests"
            ):
                found = True
                break
        assert found, (
            "PyInstaller 参数缺少 --exclude-module arknights_video_pipeline.tests"
        )

    def test_all_known_test_files_excluded(self, manager: BuildManager) -> None:
        """src 下所有已知测试文件都被排除"""
        excludes = manager._analyze_dependencies()
        test_files = [
            "test_batch_service.py",
            "test_batch_cli.py",
            "test_batch_video_list.py",
            "test_filename_encoding.py",
            "test_titlebar.py",
        ]
        for tf in test_files:
            mod_name = f"arknights_video_pipeline.tests.{tf[:-3]}"
            assert mod_name in excludes, f"缺少测试模块排除: {mod_name}"

    def test_always_exclude_still_present(self, manager: BuildManager) -> None:
        """原有 _ALWAYS_EXCLUDE 仍生效（pytest 等）"""
        excludes = manager._analyze_dependencies()
        assert "pytest" in excludes
        assert "matplotlib" in excludes

    def test_no_test_imports_in_analysis(self, manager: BuildManager) -> None:
        """依赖分析不将 pytest 标记为已使用"""
        analyzer = DependencyAnalyzer(manager.config.src_dir)
        result = analyzer.analyze()
        assert "pytest" not in result.used_packages, (
            "pytest 来自测试文件，不应被计入已使用包"
        )


# ── BuildManager: 动态导入模块的 hidden imports ──────────────


class TestProjectHiddenImports:
    """验证 PyInstaller 参数包含项目内部通过 importlib.import_module()
    动态导入的模块，这些模块无法被 PyInstaller 静态分析检测到。
    """

    @pytest.fixture
    def project_root(self) -> str:
        return os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )

    @pytest.fixture
    def manager(self, project_root: str) -> BuildManager:
        config = BuildConfig(mode="gui", project_root=project_root)
        return BuildManager(config)

    def test_project_hidden_imports_constant_has_video_compose(self) -> None:
        """_PROJECT_HIDDEN_IMPORTS 包含 video_compose 两个风格模块"""
        assert "arknights_video_pipeline.core.video_compose" in _PROJECT_HIDDEN_IMPORTS
        assert "arknights_video_pipeline.core.video_compose_style2" in _PROJECT_HIDDEN_IMPORTS

    def test_pyinstaller_args_include_video_compose_hidden_imports(
        self, manager: BuildManager
    ) -> None:
        """PyInstaller 命令参数包含 --hidden-import video_compose 模块"""
        excludes = manager._analyze_dependencies()
        args = manager._build_pyinstaller_args("/tmp/launcher.py", excludes)

        for mod in (
            "arknights_video_pipeline.core.video_compose",
            "arknights_video_pipeline.core.video_compose_style2",
        ):
            found = False
            for i, arg in enumerate(args):
                if (
                    arg == "--hidden-import"
                    and i + 1 < len(args)
                    and args[i + 1] == mod
                ):
                    found = True
                    break
            assert found, f"PyInstaller 参数缺少 hidden import: {mod}"


# ── DependencyAnalyzer: 隐藏导入的传递依赖保护 ──────────────


class TestHiddenImportDepsNotExcluded:
    """验证隐藏导入（movielite/pictex）的传递依赖不被排除。

    分析器仅扫描 src/ 源码的 import，无法感知隐藏导入自身的依赖。
    若 numba/skia/multiprocess 等传递依赖被 --clean-stdlib 或未使用包
    分析加入排除列表，打包产物会在运行时报 ModuleNotFoundError。
    """

    @pytest.fixture
    def project_root(self) -> str:
        return os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )

    @pytest.fixture
    def analyzer(self, project_root: str) -> DependencyAnalyzer:
        return DependencyAnalyzer(os.path.join(project_root, "src"))

    def test_hidden_import_deps_constant_has_known_deps(self) -> None:
        """HIDDEN_IMPORT_DEPS 包含已知的隐藏导入传递依赖"""
        expected = {
            "numba", "llvmlite", "multiprocess", "_multiprocess",
            "skia", "skia_python",
            "uharfbuzz", "bidi", "python_bidi", "regex", "stretchable",
        }
        assert expected.issubset(DependencyAnalyzer.HIDDEN_IMPORT_DEPS)

    def test_hidden_import_deps_not_in_excludes(self, analyzer: DependencyAnalyzer) -> None:
        """--clean-stdlib 模式下，传递依赖不出现在排除列表中"""
        excludes = analyzer.get_exclude_modules(clean_stdlib=True)
        for dep in (
            "numba", "llvmlite", "skia", "skia_python", "multiprocess", "_multiprocess",
            "uharfbuzz", "bidi", "python_bidi", "regex", "stretchable",
        ):
            assert dep not in excludes, f"传递依赖 {dep} 不应被排除"

    def test_pyinstaller_args_not_exclude_hidden_import_deps(
        self, project_root: str
    ) -> None:
        """PyInstaller 命令参数不包含 --exclude-module numba/skia/uharfbuzz 等"""
        config = BuildConfig(mode="gui", project_root=project_root, clean_stdlib=True)
        manager = BuildManager(config)
        excludes = manager._analyze_dependencies()
        args = manager._build_pyinstaller_args("/tmp/launcher.py", excludes)

        for dep in (
            "numba", "llvmlite", "skia", "skia_python", "multiprocess", "_multiprocess",
            "uharfbuzz", "bidi", "python_bidi", "regex", "stretchable",
        ):
            for i, arg in enumerate(args):
                if (
                    arg == "--exclude-module"
                    and i + 1 < len(args)
                    and args[i + 1] == dep
                ):
                    pytest.fail(f"PyInstaller 参数错误地排除了传递依赖: {dep}")


# ── pictex 2.x 传递依赖的 --hidden-import 验证 ──────────────


class TestPictexDepsHiddenImports:
    """验证 pictex 2.x 的传递依赖被显式添加到 --hidden-import。

    这些包（uharfbuzz/bidi/regex/stretchable）不被 src/ 源码直接 import，
    仅被 pictex 内部使用。其中 bidi 是函数级导入（pictex/text/bidi_processor.py），
    PyInstaller modulegraph 对函数级导入检测不可靠，必须显式声明。
    """

    @pytest.fixture
    def project_root(self) -> str:
        return os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )

    def test_pictex_deps_in_hidden_imports_constant(self) -> None:
        """_HIDDEN_IMPORTS 包含 pictex 2.x 的四个传递依赖"""
        for dep in ("uharfbuzz", "bidi", "regex", "stretchable"):
            assert dep in _HIDDEN_IMPORTS, (
                f"_HIDDEN_IMPORTS 缺少 pictex 2.x 传递依赖: {dep}"
            )

    def test_pyinstaller_args_include_pictex_deps_hidden_import(
        self, project_root: str
    ) -> None:
        """PyInstaller 命令参数包含 --hidden-import uharfbuzz/bidi/regex/stretchable"""
        config = BuildConfig(mode="gui", project_root=project_root)
        manager = BuildManager(config)
        excludes = manager._analyze_dependencies()
        args = manager._build_pyinstaller_args("/tmp/launcher.py", excludes)

        for dep in ("uharfbuzz", "bidi", "regex", "stretchable"):
            found = False
            for i, arg in enumerate(args):
                if (
                    arg == "--hidden-import"
                    and i + 1 < len(args)
                    and args[i + 1] == dep
                ):
                    found = True
                    break
            assert found, f"PyInstaller 参数缺少 --hidden-import {dep}"


# ── 动态传递依赖发现机制 ──────────────────────────────────────


class TestDynamicTransitiveDepDiscovery:
    """验证 _discover_transitive_deps 动态发现机制

    这是彻底解决库遗漏问题的核心机制：使用 importlib.metadata.requires()
    递归读取 REQUIRED_PACKAGES 的声明依赖，自动适应版本升级带来的新依赖，
    不再依赖手动维护硬编码列表。
    """

    @pytest.fixture
    def project_root(self) -> str:
        return os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )

    @pytest.fixture
    def analyzer(self, project_root: str) -> DependencyAnalyzer:
        return DependencyAnalyzer(os.path.join(project_root, "src"))

    def test_discover_method_exists(self, analyzer: DependencyAnalyzer) -> None:
        """_discover_transitive_deps 方法存在且可调用"""
        assert hasattr(analyzer, "_discover_transitive_deps")
        assert callable(analyzer._discover_transitive_deps)

    def test_discover_returns_set(self, analyzer: DependencyAnalyzer) -> None:
        """_discover_transitive_deps 返回 set"""
        result = analyzer._discover_transitive_deps({"movielite", "pictex"})
        assert isinstance(result, set)

    def test_discover_handles_unknown_package(self, analyzer: DependencyAnalyzer) -> None:
        """未知包不抛异常，返回空集或仅含已知部分"""
        result = analyzer._discover_transitive_deps({"__nonexistent_pkg_xyz__"})
        assert isinstance(result, set)

    def test_discover_handles_empty_input(self, analyzer: DependencyAnalyzer) -> None:
        """空输入返回空集"""
        result = analyzer._discover_transitive_deps(set())
        assert result == set()

    def test_discover_with_mocked_metadata(self, analyzer: DependencyAnalyzer) -> None:
        """使用 mock 验证递归依赖发现逻辑

        模拟 pictex 依赖 uharfbuzz/bidi/regex/stretchable，
        movielite 依赖 numba/llvmlite，验证递归发现全部传递依赖。
        """
        from unittest import mock

        # 模拟 importlib.metadata.requires 的返回值
        # 模拟 pictex 2.x 的依赖链
        fake_requires_map = {
            "pictex": [
                "uharfbuzz>=0.1",
                "python-bidi>=0.4",
                "regex>=2023.0",
                "stretchable>=1.0",
                "Pillow>=10.0",
            ],
            "movielite": [
                "numba>=0.58",
                "numpy>=1.24",
                "tqdm>=4.65",
            ],
            "numba": ["llvmlite>=0.41", "numpy>=1.24"],
            "llvmlite": [],
            "uharfbuzz": [],
            "python-bidi": [],
            "regex": [],
            "stretchable": [],
        }

        def fake_requires(pkg):
            return fake_requires_map.get(pkg)

        with mock.patch(
            "importlib.metadata.requires", side_effect=fake_requires
        ):
            result = analyzer._discover_transitive_deps({"pictex", "movielite"})

        # pictex 的直接依赖应被发现
        assert "uharfbuzz" in result
        assert "python_bidi" in result or "python-bidi" in result
        assert "regex" in result
        assert "stretchable" in result
        # movielite 的直接依赖应被发现
        assert "numba" in result
        # numba 的传递依赖 llvmlite 应被递归发现
        assert "llvmlite" in result
        # python-bidi 的导入名 bidi 应通过 _PACKAGE_TO_IMPORT 映射被发现
        assert "bidi" in result

    def test_discover_no_cycle_infinite_loop(self, analyzer: DependencyAnalyzer) -> None:
        """循环依赖不会导致无限循环"""
        from unittest import mock

        # A 依赖 B，B 依赖 A —— 循环
        fake_requires_map = {
            "pkg_a": ["pkg_b>=1.0"],
            "pkg_b": ["pkg_a>=1.0"],
        }

        def fake_requires(pkg):
            return fake_requires_map.get(pkg)

        with mock.patch(
            "importlib.metadata.requires", side_effect=fake_requires
        ):
            # 应正常返回，不卡死
            result = analyzer._discover_transitive_deps({"pkg_a"})
        assert "pkg_a" in result or "pkgA" in result
        assert "pkg_b" in result or "pkgB" in result

    def test_analyze_populates_protected_deps(self, analyzer: DependencyAnalyzer) -> None:
        """analyze() 结果中 protected_deps 非空"""
        result = analyzer.analyze()
        assert hasattr(result, "protected_deps")
        assert isinstance(result.protected_deps, set)
        # 至少应包含硬编码的 HIDDEN_IMPORT_DEPS
        assert len(result.protected_deps) >= len(DependencyAnalyzer.HIDDEN_IMPORT_DEPS)

    def test_protected_deps_superset_of_hardcoded(self, analyzer: DependencyAnalyzer) -> None:
        """protected_deps 是 HIDDEN_IMPORT_DEPS 的超集（动态发现 + 兜底）"""
        result = analyzer.analyze()
        assert DependencyAnalyzer.HIDDEN_IMPORT_DEPS.issubset(result.protected_deps)

    def test_dynamically_discovered_deps_not_excluded(self, analyzer: DependencyAnalyzer) -> None:
        """动态发现的传递依赖不出现在排除列表中"""
        from unittest import mock

        fake_requires_map = {
            "pictex": ["uharfbuzz>=0.1", "regex>=2023.0"],
            "movielite": ["numba>=0.58"],
            "numba": ["llvmlite>=0.41"],
            "uharfbuzz": [],
            "regex": [],
            "llvmlite": [],
        }

        def fake_requires(pkg):
            return fake_requires_map.get(pkg)

        with mock.patch(
            "importlib.metadata.requires", side_effect=fake_requires
        ):
            excludes = analyzer.get_exclude_modules(clean_stdlib=False)

        for dep in ("uharfbuzz", "regex", "numba", "llvmlite"):
            assert dep not in excludes, (
                f"动态发现的传递依赖 {dep} 不应被排除"
            )

    def test_dynamically_discovered_deps_not_excluded_clean_stdlib(
        self, analyzer: DependencyAnalyzer
    ) -> None:
        """--clean-stdlib 模式下动态发现的传递依赖也不被排除"""
        from unittest import mock

        fake_requires_map = {
            "pictex": ["uharfbuzz>=0.1", "stretchable>=1.0"],
            "movielite": ["multiprocess>=0.70"],
            "uharfbuzz": [],
            "stretchable": [],
            "multiprocess": ["_multiprocess"],
            "_multiprocess": [],
        }

        def fake_requires(pkg):
            return fake_requires_map.get(pkg)

        with mock.patch(
            "importlib.metadata.requires", side_effect=fake_requires
        ):
            excludes = analyzer.get_exclude_modules(clean_stdlib=True)

        for dep in ("uharfbuzz", "stretchable", "multiprocess", "_multiprocess"):
            assert dep not in excludes, (
                f"--clean-stdlib 模式下传递依赖 {dep} 不应被排除"
            )

    def test_empty_hardcoded_deps_still_protects_via_discovery(
        self, analyzer: DependencyAnalyzer
    ) -> None:
        """即使 HIDDEN_IMPORT_DEPS 为空，动态发现仍能保护传递依赖

        验证动态发现是独立的保护机制，不依赖硬编码集合。
        """
        from unittest import mock

        fake_requires_map = {
            "pictex": ["uharfbuzz>=0.1", "regex>=2023.0"],
            "movielite": ["numba>=0.58"],
            "numba": [],
            "uharfbuzz": [],
            "regex": [],
        }

        def fake_requires(pkg):
            return fake_requires_map.get(pkg)

        with mock.patch(
            "importlib.metadata.requires", side_effect=fake_requires
        ):
            # 临时清空 HIDDEN_IMPORT_DEPS，仅靠动态发现保护
            original = DependencyAnalyzer.HIDDEN_IMPORT_DEPS
            DependencyAnalyzer.HIDDEN_IMPORT_DEPS = set()
            try:
                excludes = analyzer.get_exclude_modules(clean_stdlib=False)
            finally:
                DependencyAnalyzer.HIDDEN_IMPORT_DEPS = original

        for dep in ("uharfbuzz", "regex", "numba"):
            assert dep not in excludes, (
                f"动态发现应独立保护 {dep}，即使 HIDDEN_IMPORT_DEPS 为空"
            )

    def test_pyinstaller_args_not_exclude_dynamically_discovered(
        self, project_root: str
    ) -> None:
        """PyInstaller 命令参数不包含 --exclude-module 动态发现的依赖"""
        from unittest import mock

        config = BuildConfig(mode="gui", project_root=project_root)
        manager = BuildManager(config)

        fake_requires_map = {
            "pictex": ["uharfbuzz>=0.1", "regex>=2023.0"],
            "movielite": ["numba>=0.58"],
            "numba": ["llvmlite>=0.41"],
            "uharfbuzz": [],
            "regex": [],
            "llvmlite": [],
        }

        def fake_requires(pkg):
            return fake_requires_map.get(pkg)

        with mock.patch(
            "importlib.metadata.requires", side_effect=fake_requires
        ):
            excludes = manager._analyze_dependencies()
            args = manager._build_pyinstaller_args("/tmp/launcher.py", excludes)

        for dep in ("uharfbuzz", "regex", "numba", "llvmlite"):
            for i, arg in enumerate(args):
                if (
                    arg == "--exclude-module"
                    and i + 1 < len(args)
                    and args[i + 1] == dep
                ):
                    pytest.fail(
                        f"PyInstaller 参数错误地排除了动态发现的依赖: {dep}"
                    )


# ── 打包后库完整性自检 ───────────────────────────────────────


class TestPackagedModuleVerification:
    """验证 BuildManager._verify_packaged_modules 能检测缺失的隐藏导入

    这是库遗漏问题的早期预警机制：打包完成后解析 PyInstaller 输出，
    检测 "Hidden import not found" 警告，让开发者在打包阶段就发现问题。
    """

    @pytest.fixture
    def project_root(self) -> str:
        return os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )

    @pytest.fixture
    def manager(self, project_root: str) -> BuildManager:
        config = BuildConfig(mode="gui", project_root=project_root)
        return BuildManager(config)

    def test_verify_method_exists(self, manager: BuildManager) -> None:
        """_verify_packaged_modules 方法存在且可调用"""
        assert hasattr(manager, "_verify_packaged_modules")
        assert callable(manager._verify_packaged_modules)

    def test_verify_no_output_no_crash(self, manager: BuildManager) -> None:
        """未设置 _pyinstaller_output 时不崩溃，静默返回"""
        # 确保属性不存在
        if hasattr(manager, "_pyinstaller_output"):
            del manager._pyinstaller_output
        manager._verify_packaged_modules()  # 不应抛异常

    def test_verify_detects_missing_hidden_import(
        self, manager: BuildManager, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """能检测 PyInstaller 输出中的缺失隐藏导入警告"""
        manager._pyinstaller_output = [
            "INFO: Analyzing dependencies...\n",
            'WARNING: Hidden import "uharfbuzz" not found in PYZ\n',
            "INFO: Processing module hooks...\n",
            'WARNING: Hidden import "bidi" not found\n',
        ]
        manager._verify_packaged_modules()
        captured = capsys.readouterr()
        assert "uharfbuzz" in captured.out
        assert "bidi" in captured.out
        assert "缺失" in captured.out or "WARN" in captured.out

    def test_verify_passes_when_all_found(
        self, manager: BuildManager, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """所有隐藏导入都找到时打印通过信息"""
        manager._pyinstaller_output = [
            "INFO: Analyzing dependencies...\n",
            "INFO: Processing module hooks...\n",
            "INFO: Loading module hook...\n",
        ]
        manager._verify_packaged_modules()
        captured = capsys.readouterr()
        assert "自检通过" in captured.out

    def test_verify_ignores_non_hidden_import_warnings(
        self, manager: BuildManager, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """非隐藏导入的 "not found" 警告不触发缺失报告"""
        manager._pyinstaller_output = [
            "INFO: Analyzing...\n",
            'WARNING: lib not found "libfoo.dll"\n',
            "WARNING: module not found: some_optional_thing\n",
        ]
        manager._verify_packaged_modules()
        captured = capsys.readouterr()
        # 应该通过（没有缺失的隐藏导入）
        assert "自检通过" in captured.out
