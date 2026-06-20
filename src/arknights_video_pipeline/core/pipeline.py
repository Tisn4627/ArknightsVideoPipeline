"""
pipeline.py - 明日方舟视频处理流水线 CLI 工具

完整自动化工作流：
  1. 接收并验证原始视频文件路径
  2. 调用MAA工具将视频转换为JSON（含超时控制和重试机制）
  3. 解析JSON，提取编队配置文本和操作指令文本
  4. 识别"开始"按钮出现的精确时间戳
  5. 使用编队文本、操作文本和时间戳执行视频合成
  6. 输出最终视频并验证完整性

使用示例：
  python main.py video.mp4
  python main.py video.mp4 --output-dir results --log-level DEBUG
  python main.py video.mp4 --skip-step track --skip-step compose
  python main.py --init-config
  python main.py video.mp4 --dry-run
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Callable

from arknights_video_pipeline.core.config import ConfigManager
from arknights_video_pipeline.core.exceptions import (
    ConfigError,
    ImageValidationError,
    MAARecognitionError,
    PipelineError,
    PipelineStepError,
    VideoValidationError,
)
from arknights_video_pipeline.core.logger import get_step_logger, setup_logger
from arknights_video_pipeline.core.step_defs import STEPS
from arknights_video_pipeline.core.types import PipelineReport, StepResult, StepStatus, VideoInfo
from arknights_video_pipeline.core.utils import (
    PROJECT_ROOT,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    ensure_dir,
    ensure_ffmpeg_in_path,
    format_duration,
    format_file_size,
    load_config,
    resolve_path,
    validate_image_file,
    validate_output_video,
    validate_video_file,
    write_json_file,
    write_text_file,
)

# ── PATH 修复（确保 ffmpeg/ffprobe 可用）──────────────────
ensure_ffmpeg_in_path()


# ══════════════════════════════════════════════════════════
#  流水线核心
# ══════════════════════════════════════════════════════════


class Pipeline:
    """视频处理流水线

    编排 5 个步骤的完整工作流，管理中间文件路径和步骤状态。

    支持通过回调钩子（on_step_start / on_step_finish / is_cancelled）
    让外部（如 PipelineWorker）感知步骤执行进度，避免 monkey-patch（修复 M17）。
    """

    TOTAL_STEPS = 5

    def __init__(
        self,
        video_path: str,
        config_mgr: ConfigManager,
        logger: logging.Logger,
        background_image_path: str | None = None,
        skip_steps: set[str] | None = None,
        on_step_start: Callable[[str, str], None] | None = None,
        on_step_finish: Callable[[str, bool, float, list], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.video_path = os.path.abspath(video_path)
        self.background_image_path = (
            os.path.abspath(background_image_path)
            if background_image_path
            else None
        )
        self.config = config_mgr
        self.logger = logger
        self.skip_steps = skip_steps or set()

        self.video_name = os.path.splitext(os.path.basename(self.video_path))[0]
        self.output_dir = self.config.get_output_dir(self.video_name)
        ensure_dir(self.output_dir)

        # 回调钩子（由 PipelineWorker 注入，避免 monkey-patch，修复 M17）
        self._on_step_start = on_step_start
        self._on_step_finish = on_step_finish
        self._is_cancelled = is_cancelled or (lambda: False)

        # 中间文件路径
        self.copilot_json_path: str | None = None
        self.formation_text_path: str | None = None
        self.actions_text_path: str | None = None
        self.track_result_path: str | None = None
        self.output_video_path: str | None = None

        # 报告
        self.report = PipelineReport(
            video_path=self.video_path,
            video_name=self.video_name,
            output_dir=self.output_dir,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    # ── 步骤头打印 ────────────────────────────────────────

    def _print_step_header(self, step_num: int, description: str) -> None:
        self.logger.info("")
        self.logger.info("=" * 60)
        self.logger.info(
            f"  步骤 {step_num}/{self.TOTAL_STEPS}: {description}"
        )
        self.logger.info("=" * 60)

    # ── 步骤1：视频转 MAA copilot JSON ────────────────────

    def step_video_to_copilot(self) -> StepResult:
        """调用MAA识别引擎，将视频转换为copilot JSON"""
        result = StepResult(
            name="video_to_copilot",
            description="视频转MAA作业JSON",
        )
        result.mark_running()
        start = time.time()

        try:
            from arknights_video_pipeline.core.video_to_copilot import (
                load_config as load_vtc_config,
                validate_maa_path,
                video_to_copilot,
            )

            sub_config_path = resolve_path(
                self.config.project_dir,
                self.config.pipeline.get(
                    "video_to_copilot_config", ""
                ),
            )
            if sub_config_path and os.path.exists(sub_config_path):
                sub_config = load_vtc_config(sub_config_path, {})
            else:
                sub_config = {}
            sub_config["output_dir"] = os.path.relpath(
                self.config.get_output_dir(), self.config.project_dir
            )
            sub_config["maa_path"] = self.config.pipeline.get(
                "maa_path", sub_config.get("maa_path", "")
            )

            maa_path = self.config.get_maa_path()
            validate_maa_path(maa_path)

            self.logger.info(f"输入视频: {self.video_path}")
            self.logger.info(f"MAA路径: {maa_path}")

            # 带重试机制的MAA识别
            max_retries = self.config.get_maa_max_retries()
            timeout = self.config.get_maa_timeout()

            for attempt in range(1, max_retries + 1):
                try:
                    self.logger.info(
                        f"MAA识别尝试 {attempt}/{max_retries}"
                        + (f" (超时: {timeout}s)" if timeout else "")
                    )
                    json_path = video_to_copilot(self.video_path, sub_config, timeout=timeout)
                    self.copilot_json_path = json_path
                    break
                except Exception as exc:
                    if attempt < max_retries:
                        self.logger.warning(
                            f"MAA识别第{attempt}次尝试失败: {exc}，正在重试..."
                        )
                    else:
                        raise MAARecognitionError(
                            f"MAA识别在{max_retries}次尝试后均失败: {exc}"
                        ) from exc

            if not self.copilot_json_path:
                raise MAARecognitionError(
                    "MAA识别完成但未返回有效的JSON文件路径"
                )

            result.mark_success(output_files=[self.copilot_json_path])
            self.logger.info(f"输出JSON: {self.copilot_json_path}")

        except Exception as exc:
            result.mark_failed(str(exc))
            raise PipelineStepError(
                str(exc), step_name="video_to_copilot", step_index=1, cause=exc
            ) from exc
        finally:
            result.elapsed = round(time.time() - start, 2)

        self.report.steps.append(result)
        return result

    # ── 步骤2：编队配置转文本 ─────────────────────────────

    def step_formation_to_text(self) -> StepResult:
        """解析JSON，提取编队配置文本"""
        result = StepResult(
            name="formation_to_text",
            description="编队配置转文本",
        )
        result.mark_running()
        start = time.time()

        try:
            from arknights_video_pipeline.core.formation_to_text import (
                formation_to_text,
                DEFAULT_CONFIG as FMT_DEFAULT_CONFIG,
            )

            if not self.copilot_json_path or not os.path.exists(
                self.copilot_json_path
            ):
                raise FileNotFoundError("copilot JSON文件不存在，请先执行步骤1")

            with open(self.copilot_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            fmt_config_path = resolve_path(
                self.config.project_dir,
                self.config.pipeline.get(
                    "formation", "config/formation.json"
                ),
            )
            fmt_config = load_config(fmt_config_path, FMT_DEFAULT_CONFIG)

            text = formation_to_text(data, fmt_config)

            self.formation_text_path = os.path.join(
                self.output_dir, f"formation_{self.video_name}.txt"
            )
            write_text_file(self.formation_text_path, text)

            result.mark_success(output_files=[self.formation_text_path])
            self.logger.info(f"编队文本: {len(text)}字符")
            self.logger.info(f"输出文件: {self.formation_text_path}")

        except Exception as exc:
            result.mark_failed(str(exc))
            raise PipelineStepError(
                str(exc), step_name="formation_to_text", step_index=2, cause=exc
            ) from exc
        finally:
            result.elapsed = round(time.time() - start, 2)

        self.report.steps.append(result)
        return result

    # ── 步骤3：操作指令转文本 ─────────────────────────────

    def step_actions_to_text(self) -> StepResult:
        """解析JSON，提取操作指令文本"""
        result = StepResult(
            name="actions_to_text",
            description="操作指令转文本",
        )
        result.mark_running()
        start = time.time()

        try:
            from arknights_video_pipeline.core.actions_to_text import (
                actions_to_text,
                DEFAULT_CONFIG as ACT_DEFAULT_CONFIG,
            )

            if not self.copilot_json_path or not os.path.exists(
                self.copilot_json_path
            ):
                raise FileNotFoundError("copilot JSON文件不存在，请先执行步骤1")

            with open(self.copilot_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            act_config_path = resolve_path(
                self.config.project_dir,
                self.config.pipeline.get(
                    "actions", "config/actions.json"
                ),
            )
            act_config = load_config(act_config_path, ACT_DEFAULT_CONFIG)

            text = actions_to_text(data, act_config)

            self.actions_text_path = os.path.join(
                self.output_dir, f"actions_{self.video_name}.txt"
            )
            write_text_file(self.actions_text_path, text)

            result.mark_success(output_files=[self.actions_text_path])
            self.logger.info(f"操作文本: {len(text)}字符")
            self.logger.info(f"输出文件: {self.actions_text_path}")

        except Exception as exc:
            result.mark_failed(str(exc))
            raise PipelineStepError(
                str(exc), step_name="actions_to_text", step_index=3, cause=exc
            ) from exc
        finally:
            result.elapsed = round(time.time() - start, 2)

        self.report.steps.append(result)
        return result

    # ── 步骤4：识别开始按钮时间戳 ─────────────────────────

    def step_track_startbutton(self) -> StepResult:
        """分析视频内容，识别"开始"按钮首次出现的精确时间戳"""
        result = StepResult(
            name="track_startbutton",
            description="识别开始按钮时间戳",
        )
        result.mark_running()
        start = time.time()

        try:
            from arknights_video_pipeline.core.track_startbutton import (
                DEFAULT_CONFIG as TRACK_DEFAULT_CONFIG,
                track_element,
            )

            track_config_path = resolve_path(
                self.config.project_dir,
                self.config.pipeline.get(
                    "track", "config/track.json"
                ),
            )
            track_config = load_config(track_config_path, TRACK_DEFAULT_CONFIG)
            track_config["video_source"] = self.video_path
            track_config["output_result"] = True

            self.logger.info(f"视频源: {self.video_path}")

            track_result = track_element(track_config)

            if track_result is None:
                raise RuntimeError("开始按钮识别失败，未获得跟踪结果")

            self.track_result_path = os.path.join(
                self.output_dir, f"track_result_{self.video_name}.json"
            )
            write_json_file(self.track_result_path, track_result)

            if track_result.get("was_detected"):
                self.logger.info(
                    f"开始按钮出现时间: {track_result['first_appear_time']}s"
                )
                self.logger.info(
                    f"开始按钮消失时间: {track_result['disappear_time']}s"
                )
                result.metadata["first_appear_time"] = track_result[
                    "first_appear_time"
                ]
                result.metadata["disappear_time"] = track_result["disappear_time"]
                result.metadata["max_confidence"] = track_result["max_confidence"]
            else:
                self.logger.warning("未检测到开始按钮")
                result.add_warning("未检测到开始按钮，视频合成将使用默认切换时间")

            result.mark_success(output_files=[self.track_result_path])
            self.logger.info(f"输出文件: {self.track_result_path}")

        except Exception as exc:
            result.mark_failed(str(exc))
            raise PipelineStepError(
                str(exc), step_name="track_startbutton", step_index=4, cause=exc
            ) from exc
        finally:
            result.elapsed = round(time.time() - start, 2)

        self.report.steps.append(result)
        return result

    # ── 步骤5：视频合成 ──────────────────────────────────

    # 风格名称到模块的映射（模块级常量，便于外部引用）
    _STYLE_MODULES: dict[str, str] = {
        "style1": "arknights_video_pipeline.core.video_compose",
        "style2": "arknights_video_pipeline.core.video_compose_style2",
    }

    # 输出文件键名到中文标签的映射（用于报告生成）
    _OUTPUT_LABEL_MAP: dict[str, str] = {
        "copilot_json": "Copilot JSON",
        "formation_text": "编队文本",
        "actions_text": "操作文本",
        "track_result": "跟踪结果",
        "output_video": "输出视频",
    }

    def step_video_compose(self) -> StepResult:
        """使用编队文本、操作文本和时间戳执行视频合成"""
        result = StepResult(
            name="video_compose",
            description="视频合成",
        )
        result.mark_running()
        start = time.time()

        # 根据风格名称动态导入对应的视频合成模块（在 try 之外验证，避免
        # 主动抛出的 PipelineStepError 被下方 except 捕获后重新包装）
        style_name = self.config.get_video_compose_style()
        module_name = self._STYLE_MODULES.get(style_name)
        if module_name is None:
            result.mark_failed(f"未知的视频合成风格: {style_name}")
            result.elapsed = round(time.time() - start, 2)
            self.report.steps.append(result)
            raise PipelineStepError(
                f"未知的视频合成风格: {style_name}，"
                f"可用风格: {', '.join(self._STYLE_MODULES.keys())}",
                step_name="video_compose", step_index=5,
            )

        try:
            self.logger.info(f"视频合成风格: {style_name}")

            style_module = importlib.import_module(module_name)
            compose_video = style_module.compose_video
            COMPOSE_DEFAULT_CONFIG = style_module.DEFAULT_CONFIG

            compose_config_path = resolve_path(
                self.config.project_dir,
                self.config.pipeline.get(
                    "video_compose_config", f"config/video_compose/{style_name}.json"
                ),
            )
            compose_config = load_config(
                compose_config_path, COMPOSE_DEFAULT_CONFIG,
                deep_merge_keys=["text_overlay"],
            )
            compose_config["video_source"] = self.video_path
            # 注入用户配置的 output_dir，使视频合成输出到统一目录（修复 M7）
            compose_config["output_dir"] = self.output_dir

            # 使用 CLI 提供的背景板图片覆盖配置
            if self.background_image_path:
                compose_config["background_image"] = self.background_image_path

            text_overlay = compose_config.get("text_overlay", {})
            text_overlay["enabled"] = True
            if self.copilot_json_path:
                text_overlay["input_json"] = self.copilot_json_path
            text_overlay["formation"] = resolve_path(
                self.config.project_dir,
                self.config.pipeline.get(
                    "formation", "config/formation.json"
                ),
            )
            text_overlay["actions"] = resolve_path(
                self.config.project_dir,
                self.config.pipeline.get(
                    "actions", "config/actions.json"
                ),
            )
            compose_config["text_overlay"] = text_overlay

            self.logger.info(f"视频源: {self.video_path}")
            self.logger.info(
                f"底板图片: {compose_config.get('background_image', 'N/A')}"
            )

            compose_video(compose_config)

            video_basename = self.video_name
            # 输出路径与 compose_video 内部 prepare_output_path 保持一致：
            # 使用 pipeline 注入的 output_dir，避免硬编码 PROJECT_ROOT/output（修复 M7）
            self.output_video_path = os.path.join(
                self.output_dir, f"output_{video_basename}.mp4"
            )

            # 验证输出视频完整性
            if os.path.exists(self.output_video_path):
                try:
                    validate_output_video(self.output_video_path)
                    self.logger.info("输出视频验证通过")
                except VideoValidationError as exc:
                    result.add_warning(f"输出视频验证异常: {exc}")
            else:
                result.add_warning("输出视频文件未找到，可能合成未成功")

            result.mark_success(output_files=[self.output_video_path])
            self.logger.info(f"输出视频: {self.output_video_path}")

        except Exception as exc:
            result.mark_failed(str(exc))
            raise PipelineStepError(
                str(exc), step_name="video_compose", step_index=5, cause=exc
            ) from exc
        finally:
            result.elapsed = round(time.time() - start, 2)

        self.report.steps.append(result)
        return result

    # ── 执行流水线 ────────────────────────────────────────

    def run(self) -> bool:
        """执行完整流水线，返回是否全部成功"""
        run_start_time = time.time()

        self.logger.info("=" * 60)
        self.logger.info("  明日方舟视频处理流水线")
        self.logger.info("=" * 60)
        self.logger.info(f"输入视频: {self.video_path}")
        self.logger.info(f"背景板图片: {self.background_image_path or '未指定'}")
        self.logger.info(f"输出目录: {self.output_dir}")
        if self.skip_steps:
            self.logger.info(f"跳过步骤: {', '.join(sorted(self.skip_steps))}")
        self.logger.info("")

        # 使用 STEPS 统一定义构建步骤映射（修复 M16：单一事实源）
        step_map: dict[str, tuple[int, Callable[[], StepResult], str]] = {
            step.key: (idx, getattr(self, step.method), step.label)
            for idx, step in enumerate(STEPS, start=1)
        }

        for step_key, (step_num, step_func, step_desc) in step_map.items():
            if step_key in self.skip_steps:
                skipped = StepResult(
                    name=step_key,
                    description=f"已跳过",
                    status=StepStatus.SKIPPED,
                )
                self.report.steps.append(skipped)
                self.logger.info(f"步骤 {step_num}: 已跳过 (--skip-step {step_key})")
                continue

            # 取消检查：若外部请求取消，标记当前及后续步骤为 SKIPPED
            if self._is_cancelled():
                self.logger.info(f"步骤 {step_num}: 因取消请求被跳过")
                skipped = StepResult(
                    name=step_key,
                    description=step_desc,
                    status=StepStatus.SKIPPED,
                )
                skipped.mark_skipped()
                self.report.steps.append(skipped)
                if self._on_step_finish is not None:
                    self._on_step_finish(step_key, False, 0.0, ["用户取消"])
                continue

            # 打印步骤 header
            self._print_step_header(step_num, step_desc)

            # 步骤开始回调
            if self._on_step_start is not None:
                self._on_step_start(step_key, step_desc)

            try:
                result = step_func()
                # 步骤完成回调
                if self._on_step_finish is not None:
                    success = (
                        result is not None
                        and result.status == StepStatus.SUCCESS
                    )
                    self._on_step_finish(
                        step_key, success,
                        getattr(result, "elapsed", 0.0),
                        list(getattr(result, "warnings", [])),
                    )
            except PipelineStepError as exc:
                self.logger.error(f"步骤{step_num}失败: {exc}")
                # 步骤失败回调
                if self._on_step_finish is not None:
                    self._on_step_finish(step_key, False, 0.0, [str(exc)])
                self._generate_report(run_start_time, failed=True)
                return False

        self._generate_report(run_start_time)
        return True

    # ── 报告生成 ──────────────────────────────────────────

    def _generate_report(self, run_start_time: float, failed: bool = False) -> None:
        """生成标准化处理报告"""
        pipeline_elapsed = round(time.time() - run_start_time, 2)
        self.report.total_elapsed = pipeline_elapsed
        self.report.pipeline_status = (
            StepStatus.FAILED if failed else StepStatus.SUCCESS
        )
        self.report.output_files = {
            "copilot_json": self.copilot_json_path,
            "formation_text": self.formation_text_path,
            "actions_text": self.actions_text_path,
            "track_result": self.track_result_path,
            "output_video": self.output_video_path,
        }

        self.logger.info("")
        self.logger.info("=" * 60)
        self.logger.info("  处理报告")
        self.logger.info("=" * 60)

        for step in self.report.steps:
            status_icon = {
                StepStatus.SUCCESS: "OK",
                StepStatus.FAILED: "FAIL",
                StepStatus.SKIPPED: "SKIP",
            }.get(step.status, str(step.status))
            self.logger.info(
                f"  [{status_icon}] {step.name}: "
                f"{format_duration(step.elapsed) if step.elapsed else '-'}"
            )
            for w in step.warnings:
                self.logger.info(f"       警告: {w}")
            for f in step.output_files:
                if os.path.exists(f):
                    size = os.path.getsize(f)
                    self.logger.info(
                        f"       输出: {f} ({format_file_size(size)})"
                    )

        self.logger.info("")
        self.logger.info("输出文件:")
        self.logger.info("-" * 50)
        for key, path in self.report.output_files.items():
            label = self._OUTPUT_LABEL_MAP.get(key, key)
            if path and os.path.exists(path):
                size = os.path.getsize(path)
                self.logger.info(f"  {label}: {path} ({format_file_size(size)})")
            elif path:
                self.logger.info(f"  {label}: {path} (未生成)")

        # 保存 JSON 报告
        report_path = os.path.join(
            self.output_dir, f"report_{self.video_name}.json"
        )
        write_json_file(report_path, self.report.to_dict())
        self.logger.info(f"\n报告已保存: {report_path}")


# ══════════════════════════════════════════════════════════
#  CLI 参数解析
# ══════════════════════════════════════════════════════════


def build_argparser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    supported_video = ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
    supported_image = ", ".join(sorted(SUPPORTED_IMAGE_EXTENSIONS))

    parser = argparse.ArgumentParser(
        description="明日方舟视频处理流水线 - 一键完成视频识别、文本提取、视频合成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""\
使用示例:
  python main.py video.mp4 --background-image bg.png
  python main.py video.mp4 -b bg.png --output-dir results
  python main.py video.mp4 -b bg.png --maa-path C:/MAA --skip-step track
  python main.py video.mp4 -b bg.png --log-level DEBUG --dry-run
  python main.py --init-config
  python main.py --init-config formation
  python main.py --init-config all

支持的格式:
  视频: {supported_video}
  图片: {supported_image}
""",
    )

    parser.add_argument(
        "video",
        nargs="?",
        default=None,
        help=f"输入视频文件路径 (支持: {supported_video})",
    )
    parser.add_argument(
        "--background-image", "-b",
        default=None,
        required=False,
        help=f"背景板图片文件路径 (支持: {supported_image})，视频合成步骤必需",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="输出目录 (默认: output/<video_name>/)",
    )
    parser.add_argument(
        "--maa-path",
        default=None,
        help="MAA项目路径 (优先级高于配置文件)",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="流水线配置文件路径 (默认: config/pipeline.json)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="日志级别 (默认: INFO)",
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="禁用日志文件输出",
    )
    parser.add_argument(
        "--skip-step",
        action="append",
        choices=["copilot", "formation", "actions", "track", "compose"],
        default=[],
        help="跳过指定步骤 (可多次使用)",
    )
    parser.add_argument(
        "--init-config",
        nargs="?",
        const="all",
        default=None,
        help="生成默认配置文件并退出。可指定模块名: pipeline, formation, actions, track, compose, compose_style2；不指定则生成全部",
    )
    parser.add_argument(
        "--style", "-s",
        default="style1",
        help="视频合成风格名称 (默认: style1)。对应 config/video_compose/ 目录下的同名 JSON 文件",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅验证输入和配置，不执行实际处理",
    )

    return parser


# ══════════════════════════════════════════════════════════
#  配置文件生成
# ══════════════════════════════════════════════════════════

# 模块配置定义：(配置文件名, DEFAULT_CONFIG 来源)
_MODULE_CONFIGS: dict[str, tuple[str, str, str]] = {
    "pipeline": ("pipeline.json", "arknights_video_pipeline.core.config", "PIPELINE_DEFAULTS"),
    "formation": ("formation.json", "arknights_video_pipeline.core.formation_to_text", "DEFAULT_CONFIG"),
    "actions": ("actions.json", "arknights_video_pipeline.core.actions_to_text", "DEFAULT_CONFIG"),
    "track": ("track.json", "arknights_video_pipeline.core.track_startbutton", "DEFAULT_CONFIG"),
    "compose": ("video_compose/style1.json", "arknights_video_pipeline.core.video_compose", "DEFAULT_CONFIG"),
    "compose_style2": ("video_compose/style2.json", "arknights_video_pipeline.core.video_compose_style2", "DEFAULT_CONFIG"),
}


def _init_config(module: str) -> None:
    """生成默认配置文件

    Args:
        module: 模块名 ("all" 生成全部, 或指定单个模块)
    """
    config_dir = os.path.join(PROJECT_ROOT, "config")
    os.makedirs(config_dir, exist_ok=True)

    if module == "all":
        modules = list(_MODULE_CONFIGS.keys())
    elif module in _MODULE_CONFIGS:
        modules = [module]
    else:
        valid = ", ".join(list(_MODULE_CONFIGS.keys()) + ["all"])
        print(f"错误: 未知模块 '{module}'")
        print(f"可用模块: {valid}")
        sys.exit(1)

    generated: list[str] = []
    for mod_name in modules:
        filename, source_module, attr_name = _MODULE_CONFIGS[mod_name]
        filepath = os.path.join(config_dir, filename)

        # 动态导入模块获取默认配置
        try:
            mod = importlib.import_module(source_module)
            default_config = getattr(mod, attr_name, {})
        except (ImportError, AttributeError) as exc:
            print(f"警告: 无法加载 {mod_name} 的默认配置 ({exc})，跳过")
            continue

        # 移除 _comment 等元数据键
        clean_config = {k: v for k, v in default_config.items() if not k.startswith("_")}

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(clean_config, f, indent=4, ensure_ascii=False)

        generated.append(filepath)
        print(f"已生成: {filepath}")

    if generated:
        print(f"\n共生成 {len(generated)} 个配置文件")
    else:
        print("未生成任何配置文件")


# ══════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════


def main() -> None:
    parser = build_argparser()
    args = parser.parse_args()

    config_mgr = ConfigManager(PROJECT_ROOT)

    # ── 生成默认配置 ──────────────────────────────────────
    if args.init_config is not None:
        _init_config(args.init_config)
        return

    # ── 视频路径必须提供 ──────────────────────────────────
    if args.video is None:
        parser.error(
            "请提供视频文件路径，或使用 --init-config 生成默认配置\n"
            "用法: python main.py <video> --background-image <image>"
        )

    video_path = args.video
    if not os.path.isabs(video_path):
        video_path = os.path.abspath(video_path)

    # ── 背景板图片路径 ────────────────────────────────────
    style = args.style
    background_image_path = None
    if args.background_image:
        background_image_path = args.background_image
        if not os.path.isabs(background_image_path):
            background_image_path = os.path.abspath(background_image_path)
    elif style == "style1":
        parser.error(
            "style1 需要背景板图片，请使用 --background-image / -b 指定\n"
            "若不需要背景板图片，可使用 --style style2\n"
            f"支持的图片格式: {', '.join(sorted(SUPPORTED_IMAGE_EXTENSIONS))}\n"
            "用法: python main.py <video> --background-image <image>"
        )

    # ── 加载配置 ──────────────────────────────────────────
    config_mgr.load_pipeline_config(args.config)

    cli_overrides: dict[str, Any] = {}
    if args.maa_path:
        cli_overrides["maa_path"] = args.maa_path
    if args.output_dir:
        cli_overrides["output_dir"] = args.output_dir
    if args.log_level:
        cli_overrides["log_level"] = args.log_level
    if args.no_log_file:
        cli_overrides["log_to_file"] = False
    # 根据风格名称设置视频合成配置路径
    cli_overrides["video_compose_style"] = style
    cli_overrides["video_compose_config"] = f"config/video_compose/{style}.json"
    config_mgr.merge_cli_overrides(cli_overrides)

    # ── 初始化日志 ────────────────────────────────────────
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    log_dir = (
        config_mgr.get_output_dir(video_name)
        if config_mgr.pipeline.get("log_to_file", True)
        else None
    )
    logger = setup_logger(
        "pipeline",
        log_dir=log_dir,
        log_level=config_mgr.get_log_level(),
        log_to_file=config_mgr.pipeline.get("log_to_file", True),
        max_bytes=config_mgr.pipeline.get("log_max_bytes", 10 * 1024 * 1024),
        backup_count=config_mgr.pipeline.get("log_backup_count", 3),
    )

    # ── 验证视频 ──────────────────────────────────────────
    try:
        logger.info(f"验证视频文件: {video_path}")
        video_info = validate_video_file(video_path)
        logger.info(
            f"视频信息: {video_info['width']}x{video_info['height']}, "
            f"时长{video_info['duration']:.2f}s"
        )
    except VideoValidationError as exc:
        logger.error(str(exc))
        sys.exit(1)

    # ── 验证背景板图片 ────────────────────────────────────
    if background_image_path:
        try:
            logger.info(f"验证背景板图片: {background_image_path}")
            image_info = validate_image_file(background_image_path)
            if image_info["width"] > 0:
                logger.info(
                    f"背景板图片信息: {image_info['width']}x{image_info['height']}"
                )
            else:
                logger.info("背景板图片验证通过（PIL不可用，跳过尺寸检测）")
        except ImageValidationError as exc:
            logger.error(str(exc))
            sys.exit(1)

    # ── Dry-run 模式 ──────────────────────────────────────
    if args.dry_run:
        logger.info("Dry-run模式：输入验证通过")
        logger.info(f"视频: {video_path}")
        logger.info(f"背景板图片: {background_image_path}")
        logger.info(f"输出目录: {config_mgr.get_output_dir(video_name)}")
        logger.info(f"MAA路径: {config_mgr.get_maa_path()}")
        logger.info(f"跳过步骤: {args.skip_step}")
        return

    # ── 执行流水线 ────────────────────────────────────────
    pipeline = Pipeline(
        video_path=video_path,
        config_mgr=config_mgr,
        logger=logger,
        background_image_path=background_image_path,
        skip_steps=set(args.skip_step),
    )

    success = pipeline.run()
    sys.exit(0 if success else 1)
