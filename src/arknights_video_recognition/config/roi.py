"""Access helpers for the extracted ROI task definitions (``config/roi.json``).

``roi.json`` is a flat mapping of Maa task name -> task definition object,
extracted from the upstream ``resource/tasks/tasks.json``. Each definition
may carry a ``roi`` field of the form ``[x, y, w, h]`` (in 1280x720 space)
alongside other fields such as ``template``, ``algorithm``, ``text``,
``templThreshold``, ``specialParams``, ``maskRange``, ``rectMove`` and
``baseTask``.
"""

import json

from arknights_video_recognition.config.settings import (
    CONFIG_DIR,
)

ROI_FILE = CONFIG_DIR / "roi.json"


def load_roi():
    """Load and return the full ROI task definition mapping.

    Returns
    -------
    dict
        ``{task_name: task_definition}`` read from ``resource/config/roi.json``.
    """
    with open(ROI_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_roi(task_name):
    """Return the ``[x, y, w, h]`` ROI for *task_name*, or ``None``.

    The lookup honours the Maa ``baseTask`` chain: if *task_name* has no
    ``roi`` of its own but references a ``baseTask`` that does, the base
    task's ROI is returned.

    Parameters
    ----------
    task_name : str
        Name of the task whose ROI is requested.

    Returns
    -------
    list[int] or None
        ``[x, y, w, h]`` if a ROI is defined (directly or via a baseTask),
        otherwise ``None``.
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
