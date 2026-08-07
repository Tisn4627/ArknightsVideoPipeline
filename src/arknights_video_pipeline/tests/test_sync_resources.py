"""资源同步脚本单元测试

通过 importlib 从文件加载 script/sync_recognition_resources.py，
将模块级路径常量替换为临时目录后验证 link/copy 两种模式的边界行为。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _PROJECT_ROOT / "script" / "sync_recognition_resources.py"


@pytest.fixture(scope="module")
def sync_mod():
    """从文件加载同步脚本模块（不依赖项目根在 sys.path）"""
    spec = importlib.util.spec_from_file_location(
        "sync_recognition_resources_test", _SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def setup_paths(sync_mod, tmp_path, monkeypatch):
    """将模块级路径常量指向临时目录"""
    src = tmp_path / "src-resource"
    src.mkdir()
    (src / "levels.json").write_text("{}", encoding="utf-8")
    dest = tmp_path / "resource" / "recognition"
    monkeypatch.setattr(sync_mod, "SUBMODULE_RESOURCE", src)
    monkeypatch.setattr(sync_mod, "DEST_DIR", dest)
    return {"src": src, "dest": dest}


class TestSyncCopyMode:
    """验证 copy 模式"""

    def test_copy_creates_dest(self, sync_mod, setup_paths) -> None:
        sync_mod._copy_resources(force=False)
        assert (setup_paths["dest"] / "levels.json").is_file()

    def test_copy_skips_existing_without_force(self, sync_mod, setup_paths) -> None:
        setup_paths["dest"].mkdir(parents=True)
        marker = setup_paths["dest"] / "user_file.txt"
        marker.write_text("keep", encoding="utf-8")
        sync_mod._copy_resources(force=False)
        assert marker.read_text(encoding="utf-8") == "keep"

    def test_copy_force_recopies(self, sync_mod, setup_paths) -> None:
        setup_paths["dest"].mkdir(parents=True)
        (setup_paths["dest"] / "stale.txt").write_text("old", encoding="utf-8")
        sync_mod._copy_resources(force=True)
        assert not (setup_paths["dest"] / "stale.txt").exists()
        assert (setup_paths["dest"] / "levels.json").is_file()

    def test_copy_missing_source_exits(self, sync_mod, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sync_mod, "SUBMODULE_RESOURCE", tmp_path / "nope")
        with pytest.raises(SystemExit):
            sync_mod._copy_resources(force=False)


class TestSyncLinkMode:
    """验证 link 模式（symlink 调用以替身模拟）"""

    def test_link_creates_symlink(self, sync_mod, setup_paths, monkeypatch) -> None:
        calls = []

        def fake_symlink(target, link, target_is_directory):
            calls.append((str(target), str(link), target_is_directory))
            os.makedirs(link)

        monkeypatch.setattr(os, "symlink", fake_symlink)
        result = sync_mod._link_resources(force=False)
        assert result == setup_paths["dest"]
        assert len(calls) == 1
        assert calls[0][2] is True  # target_is_directory=True

    def test_link_existing_regular_dir_exits(self, sync_mod, setup_paths) -> None:
        setup_paths["dest"].mkdir(parents=True)
        with pytest.raises(SystemExit):
            sync_mod._link_resources(force=False)

    def test_link_existing_dir_force_replaces(
        self, sync_mod, setup_paths, monkeypatch
    ) -> None:
        setup_paths["dest"].mkdir(parents=True)
        (setup_paths["dest"] / "x.txt").write_text("x", encoding="utf-8")

        def fake_symlink(target, link, target_is_directory):
            os.makedirs(link)

        monkeypatch.setattr(os, "symlink", fake_symlink)
        sync_mod._link_resources(force=True)
        assert not (setup_paths["dest"] / "x.txt").exists()

    def test_link_symlink_creation_failure_exits(
        self, sync_mod, setup_paths, monkeypatch
    ) -> None:
        def fail_symlink(*a, **kw):
            raise OSError("WinError 1314 无权限")

        monkeypatch.setattr(os, "symlink", fail_symlink)
        with pytest.raises(SystemExit):
            sync_mod._link_resources(force=False)
