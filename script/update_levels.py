"""从 yuanyan3060/ArknightsGameResource 下载最新 levels.json。

上游仓库每日自动更新（含活动关卡），本地需定期同步。

用法::

    python script/update_levels.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

# 让脚本可在不安装包的情况下直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arknights_video_recognition.config.settings import TILE_DIR  # noqa: E402

URL = "https://raw.githubusercontent.com/yuanyan3060/ArknightsGameResource/main/levels.json"

# 下载超时（秒）：urlretrieve 默认无限等待，网络停滞时会永久挂起
_DOWNLOAD_TIMEOUT_SEC = 60


def update_levels() -> Path:
    """下载最新 levels.json 到 TILE_DIR，返回目标路径。

    先写临时文件再原子替换：直接写目标文件时，下载中途失败会在
    levels.json 留下截断的坏文件并顶掉原本可用的旧版。

    Raises
    ------
    urllib.error.URLError
        下载失败时抛出，调用方可重试。
    """
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    target = TILE_DIR / "levels.json"
    print(f"Downloading {URL} -> {target}")
    with urllib.request.urlopen(URL, timeout=_DOWNLOAD_TIMEOUT_SEC) as resp:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(TILE_DIR), prefix="levels_", suffix=".tmp",
            delete=False,
        ) as tmp:
            shutil.copyfileobj(resp, tmp)
            tmp_path = Path(tmp.name)
    try:
        os.replace(tmp_path, target)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise
    size = target.stat().st_size
    print(f"Done. {size} bytes.")
    return target


if __name__ == "__main__":
    update_levels()
