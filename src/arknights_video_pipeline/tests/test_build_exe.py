"""build_exe 打包工具单元测试

验证打包过程中正确排除 src 目录下的测试文件，确保生成的可执行文件
不含任何 test 相关代码与资源，同时不影响主程序功能。

覆盖两个层面:
  1. DependencyAnalyzer - AST 解析阶段跳过测试文件/目录
  2. BuildManager - PyInstaller 命令参数包含测试模块排除项
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

from script.build_exe.analyzer import DependencyAnalyzer
from script.build_exe.builder import (
    _ALWAYS_EXCLUDE,
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
