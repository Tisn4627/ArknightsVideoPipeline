"""加载 resource/avatar 下的头像，BGRA 合成到白底 BGR。

助战干员识别时，SIFT 匹配已返回具体 filename，本模块负责加载该文件
为 BGR 三通道（带 alpha 的 PNG 合成到白底），并提取 charId。
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

from ArknightsVideoRecognition.config.settings import AVATAR_DIR

# 缓存：filename -> (BGR, charId)
_cache: dict[str, Tuple[np.ndarray, str]] = {}


def _extract_char_id(filename: str) -> str:
    """从 filename 提取 charId。

    ``char_285_medic2_boc#4.png`` -> ``char_285_medic2``
    ``char_2025_shu_nian#11.png`` -> ``char_2025_shu``
    ``sp_char_xxx.png`` -> ``sp_char_xxx``（保留完整 sp 前缀）
    """
    stem = Path(filename).stem
    tokens = stem.split("_")
    if not tokens:
        return stem
    if tokens[0] == "char" and len(tokens) >= 3:
        return "_".join(tokens[:3])
    if tokens[0] == "sp" and tokens[1] == "char" and len(tokens) >= 4:
        return "_".join(tokens[:4])
    return stem


def load_resource_avatar(filename: str) -> Tuple[np.ndarray | None, str]:
    """加载 resource/avatar/{filename}，返回 (BGR白底头像, charId)。

    BGRA PNG 合成到白底转 BGR。文件不存在或无 alpha 通道时返回
    ``(None, "")``。结果缓存。

    Parameters
    ----------
    filename:
        如 ``"char_285_medic2_boc#4.png"``。

    Returns
    -------
    tuple
        (BGR numpy 数组, charId 字符串)。失败返回 (None, "")。
    """
    if filename in _cache:
        return _cache[filename]

    path = AVATAR_DIR / filename
    if not path.is_file():
        _cache[filename] = (None, "")
        return None, ""

    bgra = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if bgra is None or bgra.ndim != 3 or bgra.shape[2] != 4:
        _cache[filename] = (None, "")
        return None, ""

    bgr = bgra[:, :, :3]
    alpha = bgra[:, :, 3:4].astype(np.float32) / 255.0
    bgr_white = (bgr.astype(np.float32) * alpha
                 + 255.0 * (1.0 - alpha)).astype(np.uint8)
    char_id = _extract_char_id(filename)
    _cache[filename] = (bgr_white, char_id)
    return bgr_white, char_id
