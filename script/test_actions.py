"""动作识别测试脚本：跑完整 pipeline，输出含编队/关卡/actions 的 copilot JSON。

遍历 test/test_actions_*.mp4，调 VideoRecognitionPipeline.run（编队+关卡+
切片+动作一体化），打印每条 action 的 type/name/location/ts，输出 JSON
到 debug/。

参数：
  --ocr-source maamodel|default|both  OCR 引擎（默认 both）
  --with-video-time                   输出 video_time 扩展字段，文件名加 _vt
  --stage <code>                      手动指定关卡（跳过 OCR）
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path
from arknights_video_recognition.config.settings import DEFAULT_RESOLUTION
from arknights_video_recognition.pipeline import (
    StageNotRecognizedError,
    VideoRecognitionPipeline,
)

TEST_DIR = Path("/workspace/test")
DEBUG_DIR = Path("/workspace/debug")


def recognize_one(
    video_path: Path,
    ocr_source: str,
    with_video_time: bool,
    stage_override: str | None,
) -> None:
    """对单个视频跑完整 pipeline，输出 copilot JSON。"""
    stem = video_path.stem
    tag = "with-video-time" if with_video_time else "default"
    print(f"\n=== 处理视频: {video_path.name} (OCR: {ocr_source}, {tag}) ===")

    pipeline = VideoRecognitionPipeline(
        ocr_source=ocr_source, resolution=DEFAULT_RESOLUTION
    )
    suffix = "_vt" if with_video_time else ""
    out_path = DEBUG_DIR / f"{stem}_{ocr_source}{suffix}.json"

    try:
        result = pipeline.run(
            str(video_path),
            stage_override=stage_override,
            output_path=str(out_path),
            with_video_time=with_video_time,
        )
    except StageNotRecognizedError as e:
        print(f"  关卡未识别：{e}")
        if e.candidates:
            print("  候选关卡：" + " / ".join(e.candidates[:10]))
        print("  请用 --stage <code|name|stageId> 手动指定后重试")
        return

    # 打印结果
    opers = result.get("opers", [])
    print(f"编队干员数: {len(opers)}")
    print(f"编队干员: {[o.get('name') for o in opers]}")
    print(f"关卡: {result.get('stage_name')}")

    actions = result.get("actions", [])
    print(f"actions ({len(actions)} 条):")
    for i, a in enumerate(actions):
        atype = a.get("type", "?")
        name = a.get("name", "")
        loc = a.get("location")
        direction = a.get("direction", "")
        ts = a.get("video_time")
        ts_str = f"ts={ts}" if ts is not None else ""
        dir_str = f"dir={direction}" if direction else ""
        loc_str = f"loc={loc}" if loc else ""
        parts = [f"  [{i}] {atype:8s}", name]
        if loc_str:
            parts.append(loc_str)
        if dir_str:
            parts.append(dir_str)
        if ts_str:
            parts.append(ts_str)
        print("  ".join(p for p in parts if p))

    print(f"输出: {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="动作识别测试")
    parser.add_argument(
        "--ocr-source",
        choices=["maamodel", "default", "both"],
        default="both",
        help="OCR 引擎来源（默认 both）",
    )
    parser.add_argument(
        "--with-video-time",
        action="store_true",
        help="输出 video_time 扩展字段，文件名加 _vt 后缀",
    )
    parser.add_argument(
        "--stage",
        default=None,
        help="手动指定关卡（code/name/stageId），跳过 OCR",
    )
    args = parser.parse_args()

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    videos = sorted(TEST_DIR.glob("test_actions_*.mp4"))
    if not videos:
        print(f"未在 {TEST_DIR} 找到 test_actions_*.mp4 文件")
        return 1
    print(f"找到 {len(videos)} 个视频: {[v.name for v in videos]}")

    sources = (
        ["maamodel", "default"] if args.ocr_source == "both" else [args.ocr_source]
    )
    for src in sources:
        print(f"\n{'='*50}")
        print(f"OCR 引擎: {src}")
        print(f"{'='*50}")
        for video in videos:
            recognize_one(
                video, src, args.with_video_time, args.stage
            )

    print("\n全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
