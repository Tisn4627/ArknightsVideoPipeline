"""ConfigProxy 子配置持久化与流水线读取一致性测试

回归验证：GUI 会话内修改子配置（如开启 style1 逐操作显示
``map_overlay.enabled``）后直接运行流水线，流水线各步骤从磁盘读取
子配置，必须能看到最新值。

此前子配置仅在 closeEvent 中 ``save_all()`` 落盘，运行按钮（``_on_run``）
不会先行保存，导致本次会话内修改的子配置在运行时不生效——典型现象是
开启逐操作显示后输出视频中缺失对应叠加。
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from arknights_video_pipeline.core.utils import load_config
from arknights_video_pipeline.core.video_compose import DEFAULT_CONFIG as STYLE1_DEFAULT
from arknights_video_pipeline.service.config_proxy import ConfigProxy


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication（offscreen 模式），确保 QObject 信号可用"""
    app = QApplication.instance() or QApplication([])
    yield app


def _write_style1(project_dir: str, enabled: bool) -> str:
    """在临时项目目录写入 style1 配置（map_overlay.enabled 可指定）"""
    path = os.path.join(project_dir, "config", "video_compose", "style1.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = json.loads(json.dumps(STYLE1_DEFAULT))
    cfg["map_overlay"]["enabled"] = enabled
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
    return path


def _load_compose(style1_path: str) -> dict:
    """按流水线合成步骤的方式加载 style1 配置（深度合并 map_overlay）"""
    return load_config(
        style1_path, STYLE1_DEFAULT, deep_merge_keys=["text_overlay", "map_overlay"]
    )


class TestSubConfigPersistence:
    def test_set_sub_then_save_all_updates_disk(self, qapp, tmp_path) -> None:
        """set_sub 后必须 save_all() 落盘，流水线才能读到新值"""
        style1_path = _write_style1(str(tmp_path), enabled=False)
        proxy = ConfigProxy(project_dir=str(tmp_path))

        proxy.set_sub("style1", "map_overlay.enabled", True)

        # 未落盘前：流水线合成步骤读到的仍是旧值（复现回归场景）
        assert _load_compose(style1_path)["map_overlay"]["enabled"] is False

        proxy.save_all()

        # 落盘后：流水线合成步骤能读到本次会话的修改
        assert _load_compose(style1_path)["map_overlay"]["enabled"] is True

    def test_worker_snapshot_sees_latest_sub_config(self, qapp, tmp_path) -> None:
        """GUI 运行前保存后，worker 快照 + 合成步骤组合必须看到最新子配置"""
        style1_path = _write_style1(str(tmp_path), enabled=False)
        proxy = ConfigProxy(project_dir=str(tmp_path))
        proxy.set_sub("style1", "map_overlay.enabled", True)
        proxy.save_all()

        worker_cfg = proxy.build_worker_config()
        compose_path = worker_cfg.resolve_path(
            worker_cfg.pipeline.get(
                "video_compose_config", "config/video_compose/style1.json"
            )
        )
        assert _load_compose(compose_path)["map_overlay"]["enabled"] is True


class TestVideoPathsSessionOnly:
    """视频列表仅保存在当前会话内存，不持久化到磁盘"""

    def test_video_paths_not_persisted_to_disk(self, qapp, tmp_path) -> None:
        """set_video_paths 后 save_all() 落盘，pipeline.json 不含 video_paths/video_path"""
        proxy = ConfigProxy(project_dir=str(tmp_path))
        proxy.set_video_paths([str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")])
        proxy.save_all()

        with open(
            os.path.join(str(tmp_path), "config", "pipeline.json"),
            encoding="utf-8",
        ) as f:
            disk = json.load(f)
        assert "video_paths" not in disk
        assert "video_path" not in disk

    def test_fresh_instance_starts_empty(self, qapp, tmp_path) -> None:
        """新建 ConfigProxy 实例的视频列表始终为空（不恢复上次会话）"""
        proxy = ConfigProxy(project_dir=str(tmp_path))
        proxy.set_video_paths([str(tmp_path / "a.mp4")])
        proxy.save_all()

        new_proxy = ConfigProxy(project_dir=str(tmp_path))
        assert new_proxy.video_paths() == []

    def test_legacy_residual_keys_cleared_on_load(self, qapp, tmp_path) -> None:
        """磁盘存在旧版 video_paths/video_path 残留时，加载后从内存清除且不再写回"""
        config_dir = os.path.join(str(tmp_path), "config")
        os.makedirs(config_dir, exist_ok=True)
        path = os.path.join(config_dir, "pipeline.json")
        legacy = {
            "video_paths": [str(tmp_path / "old.mp4")],
            "video_path": str(tmp_path / "old.mp4"),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(legacy, f)

        proxy = ConfigProxy(project_dir=str(tmp_path))
        assert proxy.video_paths() == []
        proxy.save_all()
        with open(path, encoding="utf-8") as f:
            disk = json.load(f)
        assert "video_paths" not in disk
        assert "video_path" not in disk
