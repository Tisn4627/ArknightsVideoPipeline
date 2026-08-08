"""从 Kengxxiao/ArknightsGameData 下载 character_table.json，提取 name→profession。

profession 映射到部署栏 9 模板名（Pioneer/Warrior/Tank/Sniper/Caster/Medic/
Support/Special/Drone），用于 avatar 匹配时的 role 过滤。

用法::

    python script/update_character_table.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ArknightsVideoRecognition.config.settings import DATA_DIR  # noqa: E402

URL = (
    "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/"
    "master/zh_CN/gamedata/excel/character_table.json"
)

# gamedata profession → 部署栏模板名
_PROFESSION_MAP = {
    "PIONEER": "Pioneer",
    "WARRIOR": "Warrior",
    "TANK": "Tank",
    "SNIPER": "Sniper",
    "CASTER": "Caster",
    "MEDIC": "Medic",
    "SUPPORT": "Support",
    "SPECIAL": "Special",
}


def update_character_table() -> Path:
    """下载 character_table.json，提取 {name: profession} 存为 char_roles.json。

    Returns
    -------
    Path
        char_roles.json 的路径。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = DATA_DIR / "character_table.json"
    print(f"Downloading {URL} -> {raw_path}")
    urllib.request.urlretrieve(URL, raw_path)

    raw = json.loads(raw_path.read_bytes())
    roles: dict[str, str] = {}
    for _cid, info in raw.items():
        name = info.get("name", "")
        prof = info.get("profession", "")
        mapped = _PROFESSION_MAP.get(prof)
        if name and mapped:
            roles[name] = mapped

    out_path = DATA_DIR / "char_roles.json"
    out_path.write_text(json.dumps(roles, ensure_ascii=False), encoding="utf-8")
    print(f"Done. {len(roles)} operators -> {out_path}")
    return out_path


if __name__ == "__main__":
    update_character_table()
