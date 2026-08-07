"""从 yuanyan3060/ArknightsGameResource 下载最新 levels.json。

上游仓库每日自动更新（含活动关卡），本地需定期同步。

用法::

    python scripts/update_levels.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

# 让脚本可在不安装包的情况下直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ArknightsVideoRecognition.config.settings import TILE_DIR  # noqa: E402

URL = "https://raw.githubusercontent.com/yuanyan3060/ArknightsGameResource/main/levels.json"


def update_levels() -> Path:
    """下载最新 levels.json 到 TILE_DIR，返回目标路径。

    Raises
    ------
    urllib.error.URLError
        下载失败时抛出，调用方可重试。
    """
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    target = TILE_DIR / "levels.json"
    print(f"Downloading {URL} -> {target}")
    urllib.request.urlretrieve(URL, target)
    size = target.stat().st_size
    print(f"Done. {size} bytes.")
    return target


if __name__ == "__main__":
    update_levels()
