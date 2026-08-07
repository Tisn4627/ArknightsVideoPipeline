"""命令行入口：识别战斗视频并产出 Maa copilot 作业 JSON。

用法示例::

    python -m ArknightsVideoRecognition battle.mp4 --stage 2-10 --ocr default -o out.json
    arknights-video-recognition battle.mp4 --output out.json
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import List, Optional, Tuple

from ArknightsVideoRecognition.config.settings import ResourceMissingError
from ArknightsVideoRecognition.pipeline import (
    StageNotRecognizedError,
    VideoRecognitionPipeline,
)


def _parse_resolution(text: str) -> Optional[Tuple[int, int]]:
    """解析 "WxH" → (W, H)，非法返回 None。"""
    if not text:
        return None
    parts = text.lower().split("x")
    if len(parts) != 2:
        return None
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return (w, h)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI 入口。

    成功返回 0（不调 sys.exit，便于被其它脚本直接调用）；失败时通过
    ``sys.exit(code)`` 抛出 :class:`SystemExit` 以设置进程退出码：
    资源缺失/视频无法打开/其它异常 → 1，关卡未识别 → 2。
    """
    parser = argparse.ArgumentParser(
        prog="arknights-video-recognition",
        description="识别明日方舟战斗录像，输出 Maa copilot 作业 JSON。",
    )
    parser.add_argument("video", help="输入视频文件路径")
    parser.add_argument(
        "--ocr",
        choices=["maamodel", "default"],
        default="maamodel",
        help="OCR 模型源：maamodel=方舟 finetune（默认），default=RapidOCR 自带",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="输出 JSON 路径，默认自动命名存到 cache 目录",
    )
    parser.add_argument(
        "--stage",
        default=None,
        help="手动指定关卡（code/name/stageId，如 2-10），默认自动 OCR 识别",
    )
    parser.add_argument(
        "--resolution",
        default="1280x720",
        help="视频归一化分辨率，形如 WxH，默认 1280x720",
    )
    parser.add_argument(
        "--with-video-time",
        action="store_true",
        help="在 actions 中输出 video_time 扩展字段（视频内绝对时间戳，秒）",
    )
    args = parser.parse_args(argv)

    # 解析分辨率
    resolution = _parse_resolution(args.resolution)
    if resolution is None:
        print(
            f"错误：无法解析分辨率 {args.resolution!r}，应为形如 1280x720",
            file=sys.stderr,
        )
        sys.exit(1)

    # 构造流水线（构造时做资源校验）
    try:
        pipeline = VideoRecognitionPipeline(
            ocr_source=args.ocr, resolution=resolution
        )
    except ResourceMissingError as e:
        print(f"错误：资源缺失。\n{e}", file=sys.stderr)
        print(
            "请运行 `python scripts/update_resources.py` 获取所需资源后重试。",
            file=sys.stderr,
        )
        sys.exit(1)

    # 运行流水线
    try:
        pipeline.run(
            args.video,
            stage_override=args.stage,
            output_path=args.output,
            with_video_time=args.with_video_time,
        )
    except StageNotRecognizedError as e:
        print(f"错误：{e}", file=sys.stderr)
        if e.candidates:
            print("候选关卡：" + " / ".join(e.candidates[:10]), file=sys.stderr)
        print(
            "请用 --stage <code|name|stageId> 手动指定关卡。",
            file=sys.stderr,
        )
        sys.exit(2)
    except ValueError as e:
        # 主要是 VideoFrames 无法打开视频
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        # 其它未预期异常：打印完整 traceback
        traceback.print_exc()
        sys.exit(1)

    # 成功：打印输出文件路径
    out = getattr(pipeline, "last_output_path", None)
    if out is not None:
        print(str(out))
    return 0


if __name__ == "__main__":
    main()
