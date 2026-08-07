"""
core.recognition_backend - Recognition 后端（默认）

用随仓库分发的 ArknightsVideoRecognition 代码完成视频转 copilot JSON。
代码位于 src/ArknightsVideoRecognition/（vendor，原为 git 子模块）。

资源目录优先级（必须在 import ArknightsVideoRecognition.* 之前确定）：
  1. 配置 recognition.resource_dir（recognize() 内应用）
  2. 环境变量 AVR_RESOURCE_DIR
  3. 默认 <项目根>/resource/（识别资源并入顶层 resource/）
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# === 关键：在 import ArknightsVideoRecognition 之前设置资源目录 ===
# 识别资源（avatar/config/data/ocr/onnx/template/tile）并入父项目顶层 resource/。
# 此处仅设置默认值；配置层的 resource_dir 覆盖在 recognize() 内、首次导入前应用。
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_RESOURCE_DIR = _PROJECT_ROOT / "resource"
_VENDORED_ROOT = _PROJECT_ROOT / "src" / "ArknightsVideoRecognition"
_VENDORED_SRC_DIR = _VENDORED_ROOT / "src"

if "AVR_RESOURCE_DIR" not in os.environ:
    os.environ["AVR_RESOURCE_DIR"] = str(_DEFAULT_RESOURCE_DIR)

# 确保 vendor 的识别代码可导入（editable 安装则无需）
# 代码包位于 src/ArknightsVideoRecognition/src/ArknightsVideoRecognition
if str(_VENDORED_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDORED_SRC_DIR))


def _import_recognition_pipeline(resource_dir: str | None = None):
    """按需导入 Recognition 主流水线（首次导入前应用配置级资源目录覆盖）

    延迟导入使本模块在识别代码缺失或 onnxruntime 未安装时仍可被导入
    （工厂/测试环境不强制依赖 Recognition）。
    """
    if resource_dir:
        os.environ["AVR_RESOURCE_DIR"] = str(Path(resource_dir).resolve())

    from ArknightsVideoRecognition.config.settings import ResourceMissingError
    from ArknightsVideoRecognition.pipeline import (
        StageNotRecognizedError,
        VideoRecognitionPipeline,
    )

    return VideoRecognitionPipeline, StageNotRecognizedError, ResourceMissingError


def _normalize_copilot(job: dict) -> dict:
    """薄归一化层：补齐字段默认值，兼容下游 formation/actions 文本提取。

    与 MAA 后端输出保持一致的约定字段（见 docs/merge_plan.md §5.2）：
    - opers 补默认 skill=1 / skill_usage=0
    - 保证 minimum_required / groups / actions / opers 字段存在
    - 不强行添加 kills/costs（保持 Recognition 语义）
    """
    # opers: 补默认 skill / skill_usage（与 build_copilot_json 行为对齐）
    for oper in job.get("opers", []):
        oper.setdefault("skill", 1)
        oper.setdefault("skill_usage", 0)
    # 保证关键字段存在
    job.setdefault("minimum_required", "v4.0.0")
    job.setdefault("groups", [])
    job.setdefault("actions", [])
    job.setdefault("opers", [])
    return job


class RecognitionBackend:
    """视频转 copilot JSON 的 Recognition 后端。"""

    name = "recognition"

    def __init__(self, config: dict):
        self._config = config or {}

    def recognize(
        self,
        video_path: str,
        output_dir: str,
        config: dict,
        timeout: float | None = None,
    ) -> str:
        cfg = {**self._config, **(config or {})}
        ocr_source = cfg.get("ocr_source", "maamodel")
        resolution_str = cfg.get("resolution", "1280x720")
        stage_override = cfg.get("stage_override") or None
        with_video_time = bool(cfg.get("with_video_time", False))
        resource_dir = cfg.get("resource_dir") or None

        # 解析分辨率 "WxH" -> (W, H)
        try:
            w, h = (int(x) for x in str(resolution_str).lower().split("x"))
            resolution = (w, h)
        except (ValueError, AttributeError):
            resolution = (1280, 720)

        # 首次导入前应用配置级资源目录覆盖（优先级最高）
        VideoRecognitionPipeline, StageNotRecognizedError, ResourceMissingError = (
            _import_recognition_pipeline(resource_dir)
        )

        # VideoRecognitionPipeline 构造时自动调用 check_resource() 校验资源
        pipe = VideoRecognitionPipeline(
            ocr_source=ocr_source,
            resolution=resolution,
        )

        # run() 返回 dict，需落盘为 JSON 文件以匹配流水线"文件路径"接口
        start = time.time()
        try:
            job_dict = pipe.run(
                video_path=video_path,
                stage_override=stage_override,
                output_path=None,  # 由本适配层统一控制输出路径
                with_video_time=with_video_time,
            )
        except StageNotRecognizedError:
            raise
        except ResourceMissingError as exc:
            raise RuntimeError(
                f"Recognition 资源缺失: {exc}\n"
                "请检查顶层 resource/ 目录（识别资源已随仓库分发，不应缺失）"
            ) from exc

        if timeout is not None and (time.time() - start) > timeout:
            raise TimeoutError(f"Recognition 识别超时（>{timeout}s）")

        # 归一化：补齐 opers 默认值，确保与 MAA 后端输出一致（见 docs/merge_plan.md §5）
        job_dict = _normalize_copilot(job_dict)

        # 落盘
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        video_stem = Path(video_path).stem
        out_path = out_dir / f"recognition_copilot_{video_stem}.json"
        out_path.write_text(
            json.dumps(job_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(out_path.resolve())
