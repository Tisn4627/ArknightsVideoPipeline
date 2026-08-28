"""提取后的 ROI 任务定义（``config/roi.json``）访问辅助。

``roi.json`` 是「Maa 任务名 -> 任务定义对象」的扁平映射，
提取自上游 ``resource/tasks/tasks.json``。每个定义可携带
``roi`` 字段（``[x, y, w, h]``，1280x720 坐标系），以及其他字段
如 ``template``、``algorithm``、``text``、``templThreshold``、
``specialParams``、``maskRange``、``rectMove`` 和 ``baseTask``。
"""

import json

from arknights_video_recognition.config.settings import (
    CONFIG_DIR,
)

ROI_FILE = CONFIG_DIR / "roi.json"

# 模块级缓存：首次读盘后缓存完整映射，后续调用直接返回，避免重复 IO。
_ROI_CACHE: dict | None = None


def load_roi():
    """加载并返回完整的 ROI 任务定义映射。

    首次调用从 ``resource/config/roi.json`` 读盘，之后命中模块级缓存
    直接返回；测试需要重置时可调用 :func:`clear_roi_cache`。

    Returns
    -------
    dict
        ``{task_name: task_definition}``，来自 ``resource/config/roi.json``。
    """
    global _ROI_CACHE
    if _ROI_CACHE is None:
        with open(ROI_FILE, encoding="utf-8") as f:
            _ROI_CACHE = json.load(f)
    return _ROI_CACHE


def clear_roi_cache():
    """清空 ROI 缓存，下次调用 :func:`load_roi` 将重新读盘（供测试使用）。"""
    global _ROI_CACHE
    _ROI_CACHE = None


def get_roi(task_name):
    """返回 *task_name* 对应的 ``[x, y, w, h]`` ROI，若无则返回 ``None``。

    查找遵循 Maa 的 ``baseTask`` 链：若 *task_name* 自身没有 ``roi``
    但引用了带 ``roi`` 的 ``baseTask``，则返回基础任务的 ROI。

    Parameters
    ----------
    task_name : str
        要查询 ROI 的任务名。

    Returns
    -------
    list[int] or None
        若定义了 ROI（直接或经由 baseTask）则返回 ``[x, y, w, h]``，
        否则返回 ``None``。
    """
    tasks = load_roi()
    seen = set()
    name = task_name
    while name is not None and name not in seen:
        seen.add(name)
        task = tasks.get(name)
        if not isinstance(task, dict):
            return None
        roi = task.get("roi")
        if roi is not None:
            return list(roi)
        name = task.get("baseTask")
    return None
