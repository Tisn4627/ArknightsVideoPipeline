"""编队识别（含助战干员）测试脚本。

遍历 test/ 下两个 mp4，运行 FormationAnalyzer.analyze_with_support，
把识别结果（普通 + 助战干员）组装为 Maa copilot JSON 输出到 debug/。

支持 --ocr-source 参数选择 OCR 引擎（maamodel / default），
两种引擎分别测试。
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path
from ArknightsVideoRecognition.config.settings import DEFAULT_RESOLUTION, MINIMUM_REQUIRED
from ArknightsVideoRecognition.copilot.builder import CopilotJob
from ArknightsVideoRecognition.formation import FormationAnalyzer
from ArknightsVideoRecognition.ocr.engine import OcrEngine, OcrSource
from ArknightsVideoRecognition.video.frames import VideoFrames

TEST_DIR = Path("/workspace/test")
DEBUG_DIR = Path("/workspace/debug")
SAMPLE_INTERVAL_SEC = 0.2   # 5 fps
MAX_DURATION_SEC = 60.0


def sample_frames(video_path: Path) -> list:
    """打开视频归一化 720p，采样前 60s 帧（5fps），返回 [(ts, frame), ...]。"""
    vf = VideoFrames(str(video_path), resolution=DEFAULT_RESOLUTION)
    frames = []
    for ts, frame in vf.sample(interval_sec=SAMPLE_INTERVAL_SEC):
        if ts > MAX_DURATION_SEC:
            break
        frames.append((ts, frame))
    vf.release()
    return frames


def recognize_one(video_path: Path, ocr_engine: OcrEngine, ocr_tag: str) -> None:
    """对单个视频做编队识别 + 助战识别，输出 copilot JSON。"""
    stem = video_path.stem
    print(f"\n=== 处理视频: {video_path.name} (OCR: {ocr_tag}) ===")
    frames = sample_frames(video_path)
    print(f"采样帧数: {len(frames)}")
    if not frames:
        print("  无帧可用，跳过")
        return

    analyzer = FormationAnalyzer(ocr_engine=ocr_engine)
    opers = analyzer.analyze_with_support(frames)

    normal_opers = [o for o in opers if not o.is_support]
    support_opers = [o for o in opers if o.is_support]
    support_name = support_opers[0].name if support_opers else None
    print(f"普通干员数: {len(normal_opers)}")
    print(f"普通干员: {[o.name for o in normal_opers]}")
    print(f"助战干员: {support_name if support_name else '无'}")

    # 组装 CopilotJob
    # stage_name 用占位 "unknown"：本脚本只测编队识别，未识别关卡；
    # CopilotJob.validate() 要求 stage_name 非空，占位值使 JSON 通过格式校验。
    job = CopilotJob(stage_name="unknown", minimum_required=MINIMUM_REQUIRED)
    for o in opers:
        job.add_oper(name=o.name)
    job.add_speedup()
    job.add_skill_daemon()

    details_lines = [f"普通干员数: {len(normal_opers)}"]
    details_lines.append(f"助战干员: {support_name if support_name else '无'}")
    details_lines.append(f"OCR引擎: {ocr_tag}")
    job.set_doc(title=f"{stem} 编队识别结果", details="\n".join(details_lines))

    # 校验
    problems = job.validate()
    print(f"validate 问题: {problems if problems else '（通过）'}")

    # 输出（文件名带 OCR source 后缀）
    out_path = DEBUG_DIR / f"{stem}_{ocr_tag}.json"
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    job.save(out_path)
    print(f"输出: {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="编队识别测试")
    parser.add_argument(
        "--ocr-source",
        choices=["maamodel", "default", "both"],
        default="both",
        help="OCR 引擎来源：maamodel（Maa finetune）、default（RapidOCR 默认）、both（两者都测，默认）",
    )
    args = parser.parse_args()

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    videos = sorted(
        v for v in TEST_DIR.glob("*.mp4") if "actions" not in v.name
    )
    if not videos:
        print(f"未在 {TEST_DIR} 找到 mp4 文件")
        return 1
    print(f"找到 {len(videos)} 个视频: {[v.name for v in videos]}")

    sources = ["maamodel", "default"] if args.ocr_source == "both" else [args.ocr_source]
    for src in sources:
        print(f"\n{'='*50}")
        print(f"OCR 引擎: {src}")
        print(f"{'='*50}")
        ocr_engine = OcrEngine(source=OcrSource(src))
        for video in videos:
            recognize_one(video, ocr_engine, src)

    print("\n全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
