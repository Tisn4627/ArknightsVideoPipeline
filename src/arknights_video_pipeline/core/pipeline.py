"""
pipeline.py - 明日方舟视频处理流水线 CLI 工具

完整自动化工作流：
  1. 接收并验证原始视频文件路径
  2. 调用识别后端（recognition 默认 / MAA 可选）将视频转换为JSON（含超时控制和重试机制）
  3. 解析JSON，提取编队配置文本和操作指令文本
  4. 识别"开始"按钮出现的精确时间戳
  5. 使用编队文本、操作文本和时间戳执行视频合成
  6. 输出最终视频并验证完整性

使用示例：
  python main.py video.mp4 --background-image bg.png
  python main.py video.mp4 -b bg.png --output-dir results --log-level DEBUG
  python main.py video.mp4 --style style2 --skip-step track --skip-step compose
  python main.py video.mp4 -b bg.png --copilot-json copilot.json
  python main.py --init-config
  python main.py video.mp4 -b bg.png --dry-run
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
    CopilotBackendError,
    ImageValidationError,
    PipelineStepError,
    VideoValidationError,
)
from arknights_video_pipeline.core.logger import setup_logger
from arknights_video_pipeline.core.step_defs import STEPS
from arknights_video_pipeline.core.types import PipelineReport, StepResult, StepStatus
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
    set_ffmpeg_config,
    validate_image_file,
    validate_output_video,
    validate_video_file,
    write_json_file,
    write_text_file,
)


# ══════════════════════════════════════════════════════════
#  识别重试策略（step_video_to_copilot 及两个后端共用约定）
# ══════════════════════════════════════════════════════════

# 指数退避：第 n 次失败后等待 min(2^n, 上限) 秒（2/4/8/.../10）
RETRY_BACKOFF_CAP_SECONDS = 10
# 退避等待期间以该粒度（秒）轮询取消请求，保证用户取消可及时生效
RETRY_CANCEL_CHECK_INTERVAL = 0.5

# 可重试异常：环境/瞬时类失败（识别引擎异常、超时、IO 抖动），重试有成功可能
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    RuntimeError,
    OSError,
)

# 不可重试异常：确定性失败（数据/配置/编程错误），重试必然得到同样结果。
# 注意 StageNotRecognizedError 继承 ValueError（识别包 pipeline.py），
# 关卡未识别对同一视频是确定性的，同样不应重试——此处显式声明而非依赖
# "恰好不在捕获元组里"的隐式巧合。
_NON_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ValueError,  # 含 StageNotRecognizedError / 识别结果格式异常
    TypeError,
    KeyError,
    AttributeError,
)


def _is_retryable_error(exc: BaseException) -> bool:
    """判定识别异常是否值得重试（重试循环唯一判定入口）

    规则（先命中先生效）：
    1. CopilotBackendError 以后端显式声明的 retryable 属性为准；
    2. 命中不可重试清单（确定性错误）→ False；
    3. 命中可重试清单（超时/运行时/IO 瞬时错误）→ True；
    4. 其余未知类型保守视为不可重试，避免为未知语义付出整次识别成本。
    """
    if isinstance(exc, CopilotBackendError):
        return exc.retryable
    if isinstance(exc, _NON_RETRYABLE_EXCEPTIONS):
        return False
    return isinstance(exc, _RETRYABLE_EXCEPTIONS)


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
        copilot_json_path: str | None = None,
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

        # 自定义作业 JSON（由 CLI --copilot-json 或 GUI 每视频绑定传入）：
        # 非空时步骤1跳过视频识别，直接使用该 JSON，后续步骤照常执行。
        if copilot_json_path:
            self.copilot_json_path = os.path.abspath(copilot_json_path)

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

    # ── 步骤1：视频转 copilot JSON ─────────────────────────

    def _backend_config(self, backend_name: str) -> dict[str, Any]:
        """组装后端子配置（与后端 recognize() 的 config 参数对应）"""
        if backend_name == "maa":
            # 兼容旧配置：加载 video_to_copilot_config 指向的子配置文件
            sub_config_path = resolve_path(
                self.config.project_dir,
                self.config.pipeline.get("video_to_copilot_config", ""),
            )
            if sub_config_path and os.path.exists(sub_config_path):
                from arknights_video_pipeline.core.video_to_copilot import (
                    load_config as load_vtc_config,
                )

                sub_config = load_vtc_config(sub_config_path, {})
            else:
                sub_config = {}
            sub_config["maa_path"] = self.config.get_maa_path()
            return sub_config
        return self.config.get_recognition_config()

    def step_video_to_copilot(self) -> StepResult:
        """调用选定的识别后端（recognition 默认 / maa 可选），将视频转换为copilot JSON"""
        result = StepResult(
            name="video_to_copilot",
            description="视频转作业JSON",
        )
        result.mark_running()
        start = time.time()
        retry_errors: list[str] = []

        try:
            from arknights_video_pipeline.core.copilot_backend import (
                create_backend,
            )

            backend_name = self.config.get_copilot_backend()
            backend_config = self._backend_config(backend_name)
            backend = create_backend(backend_name, backend_config)

            output_dir = self.output_dir
            timeout = self.config.get_copilot_timeout()
            max_retries = self.config.get_copilot_max_retries()
            if max_retries < 1:
                # 兼容 GUI 历史设置/手改配置中的 0：语义为"只执行一次、不重试"，
                # 而非让整个步骤直接失败（旧实现此处抛错，与 GUI 允许的
                # minimum=0 冲突）
                self.logger.warning(
                    f"copilot_max_retries={max_retries} < 1，按 1 次尝试执行"
                )
                max_retries = 1

            self.logger.info(f"输入视频: {self.video_path}")
            self.logger.info(f"识别后端: {backend.name}")
            if backend_name == "maa":
                self.logger.info(f"MAA路径: {self.config.get_maa_path()}")

            # 带重试机制的识别（copilot_max_retries 语义为"总尝试次数"）
            for attempt in range(1, max_retries + 1):
                # 重试前的取消检查：取消后不再发起下一次高成本识别尝试
                if attempt > 1 and self._is_cancelled():
                    raise CopilotBackendError(
                        "识别重试前检测到取消请求，停止重试", retryable=False
                    )
                try:
                    self.logger.info(
                        f"{backend.name}识别尝试 {attempt}/{max_retries}"
                        + (f" (超时: {timeout}s)" if timeout else "")
                    )
                    json_path = backend.recognize(
                        video_path=self.video_path,
                        output_dir=output_dir,
                        config=backend_config,
                        timeout=timeout,
                    )
                    self.copilot_json_path = json_path
                    break
                except Exception as exc:
                    if not _is_retryable_error(exc):
                        # 确定性失败（配置/资源/数据/关卡未识别）：重试必然
                        # 同样失败，直接失败并保留原始异常语义
                        raise
                    retry_errors.append(f"第{attempt}次: {exc}")
                    if attempt < max_retries:
                        delay = min(2 ** attempt, RETRY_BACKOFF_CAP_SECONDS)
                        self.logger.warning(
                            f"{backend.name}识别第{attempt}次尝试失败: {exc}，"
                            f"{delay}s 后重试..."
                        )
                        self._interruptible_sleep(delay)
                    else:
                        raise CopilotBackendError(
                            f"{backend.name}后端识别在{max_retries}次尝试后均失败: {exc}"
                        ) from exc

            if not self.copilot_json_path:
                raise CopilotBackendError(
                    f"{backend.name}识别完成但未返回有效的JSON文件路径"
                )

            # 重试状态记录进步骤元数据（修复：旧实现仅打日志，报告不可观测）
            if retry_errors:
                result.metadata["retry"] = {
                    "attempts": len(retry_errors) + 1,
                    "errors": retry_errors,
                }
                result.add_warning(
                    f"识别经历 {len(retry_errors)} 次失败重试后成功"
                )

            result.mark_success(output_files=[self.copilot_json_path])
            self.logger.info(f"输出JSON: {self.copilot_json_path}")

        except Exception as exc:
            if retry_errors:
                # 失败路径同样记录重试轨迹，报告/排障可观测每次失败原因
                result.metadata["retry"] = {
                    "attempts": len(retry_errors),
                    "errors": retry_errors,
                    "failed": True,
                }
            result.mark_failed(str(exc))
            raise PipelineStepError(
                str(exc), step_name="video_to_copilot", step_index=1, cause=exc
            ) from exc
        finally:
            result.elapsed = round(time.time() - start, 2)
            self.report.steps.append(result)

        return result

    def _interruptible_sleep(self, seconds: float) -> None:
        """可中断的退避等待：以固定粒度轮询取消请求

        旧实现用 time.sleep() 整段阻塞，用户取消后仍需等完整个退避时长
        才能响应；现以 RETRY_CANCEL_CHECK_INTERVAL 粒度轮询，检测到取消
        时抛出不可重试的 CopilotBackendError 终止重试循环。
        """
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._is_cancelled():
                raise CopilotBackendError(
                    "识别重试退避期间检测到取消请求，停止重试",
                    retryable=False,
                )
            time.sleep(min(RETRY_CANCEL_CHECK_INTERVAL, remaining))

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
                TRACK_MODE_BATTLESTART,
                track_element,
            )

            track_config_path = resolve_path(
                self.config.project_dir,
                self.config.pipeline.get(
                    "track", "config/track.json"
                ),
            )
            # battle_start 为嵌套子配置，需要深度合并（缺失子键回退默认值）
            track_config = load_config(
                track_config_path, TRACK_DEFAULT_CONFIG,
                deep_merge_keys=["battle_start"],
            )
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

            if track_result.get("track_mode") == TRACK_MODE_BATTLESTART:
                if track_result.get("battle_start_detected"):
                    self.logger.info(
                        f"进入战斗时间: {track_result['battle_start_time']}s"
                    )
                    result.metadata["battle_start_time"] = track_result[
                        "battle_start_time"
                    ]
                    result.metadata["max_confidence"] = track_result[
                        "battle_start_max_ratio"
                    ]
                else:
                    self.logger.warning("未检测到进入战斗")
                    result.add_warning("未检测到进入战斗，视频合成将使用默认切换时间")
            elif track_result.get("was_detected"):
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
                deep_merge_keys=["text_overlay", "map_overlay"],
            )
            compose_config["video_source"] = self.video_path
            # 注入用户配置的 output_dir，使视频合成输出到统一目录（修复 M7）
            compose_config["output_dir"] = self.output_dir

            # 注入识别分辨率到逐操作显示配置（tile 投影基准须与识别一致）
            if "map_overlay" in compose_config and isinstance(
                compose_config["map_overlay"], dict
            ):
                rec_resolution = self.config.get_recognition_config().get(
                    "resolution", "1280x720"
                )
                compose_config["map_overlay"]["resolution"] = rec_resolution

            # 使用 CLI 提供的背景板图片覆盖配置
            if self.background_image_path:
                compose_config["background_image"] = self.background_image_path

            text_overlay = compose_config.get("text_overlay", {})
            # 尊重用户在 style JSON 中显式设置的 enabled 开关（配置优先级：
            # 模块 JSON > 代码默认值），不再无条件强制开启；仅在开启时注入
            # 路径参数，下游 video_compose 按 enabled 决定是否消费文本叠加
            if text_overlay.get("enabled", True):
                # track_result 由步骤4写入 self.output_dir（见 step_track）。
                # load_text_overlay_inputs 只从 text_overlay 子块读取
                # output_dir，故必须在此同步注入子块；只注入顶层会导致用户
                # 自定义输出目录时找不到跟踪结果、静默回退 3 秒切换时间
                text_overlay["output_dir"] = self.output_dir
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

            self.output_video_path = compose_video(compose_config)

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
                    description="已跳过",
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

            # 自定义作业 JSON：步骤1（视频识别）跳过，直接使用预设 JSON
            if (
                step_key == "copilot"
                and self.copilot_json_path
                and os.path.exists(self.copilot_json_path)
            ):
                custom_desc = "使用自定义作业JSON"
                self.logger.info("")
                self.logger.info("=" * 60)
                self.logger.info(
                    f"  步骤 {step_num}/{self.TOTAL_STEPS}: {custom_desc}"
                )
                self.logger.info("=" * 60)
                self.logger.info(
                    f"自定义作业JSON: {self.copilot_json_path}，跳过视频识别"
                )
                if self._on_step_start is not None:
                    self._on_step_start(step_key, custom_desc)
                result = StepResult(
                    name="video_to_copilot",
                    description=custom_desc,
                    status=StepStatus.SUCCESS,
                    output_files=[self.copilot_json_path],
                )
                self.report.steps.append(result)
                if self._on_step_finish is not None:
                    self._on_step_finish(step_key, True, 0.0, [])
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
        # 若有步骤被取消/跳过（非用户显式 --skip-step），视为非完全成功
        return not any(
            s.status == StepStatus.SKIPPED and s.description != "已跳过"
            for s in self.report.steps
        )

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
                StepStatus.PENDING: "--",
                StepStatus.RUNNING: "..",
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
  python main.py video.mp4 -b bg.png --maa-path C:/MAA --backend maa --skip-step track
  python main.py video.mp4 -b bg.png --backend recognition --stage 2-10
  python main.py video.mp4 -b bg.png --copilot-json copilot.json
  python main.py v1.mp4 v2.mp4 -b bg.png --copilot-json v1.json v2.json
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
        nargs="*",
        default=[],
        help=f"输入视频文件路径，支持多个 (支持: {supported_video})，按给定顺序依次处理",
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
        help="MAA项目路径 (优先级高于配置文件；仅 backend=maa 时生效)",
    )
    parser.add_argument(
        "--backend",
        choices=["recognition", "maa"],
        default=None,
        help="视频识别后端 (默认: recognition)。recognition=纯Python实现（默认）；maa=调用MAA项目（需配置 --maa-path）",
    )
    parser.add_argument(
        "--ocr",
        choices=["maamodel", "default"],
        default=None,
        help="Recognition 后端的 OCR 模型来源 (默认: maamodel)。仅 backend=recognition 时生效",
    )
    parser.add_argument(
        "--stage",
        default=None,
        help="Recognition 后端的关卡指定（code/name/stageId，如 2-10 或 main_02-10），不指定则自动识别。仅 backend=recognition 时生效",
    )
    parser.add_argument(
        "--resolution",
        default=None,
        help='Recognition 后端的视频分辨率 "WxH" (默认: 1280x720)。仅 backend=recognition 时生效',
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
        "--copilot-json",
        nargs="*",
        default=[],
        help="自定义作业JSON文件路径（.json），可指定多个。绑定后对应视频跳过步骤1（视频识别），"
             "后续步骤照常执行。仅单个视频+单个JSON时直接绑定；其余情况（多视频或多JSON）"
             "按文件名（去扩展名，不区分大小写）匹配。多视频的自定义JSON为测试功能，"
             "建议仅对单个视频文件使用",
    )
    parser.add_argument(
        "--init-config",
        nargs="?",
        const="all",
        default=None,
        help="生成默认配置文件并退出。可指定模块名: pipeline, formation, actions, track, compose, compose_style2, gui；不指定则生成全部",
    )
    parser.add_argument(
        "--style", "-s",
        default=None,
        help="视频合成风格名称（未指定时沿用配置中的 video_compose_style，"
             "默认 style1）。对应 config/video_compose/ 目录下的同名 JSON 文件",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅验证输入和配置，不执行实际处理",
    )
    parser.add_argument(
        "--recognize-only",
        action="store_true",
        help="仅执行视频识别（步骤1），输出单一 copilot JSON 文件，"
             "自动跳过编队/操作/跟踪/合成步骤。启用时无需背景板图片，"
             "与 --copilot-json 互斥",
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
    # gui.json 默认值来自 gui_config._GUI_DEFAULTS；动态导入在无 PyQt6 环境
    # （CLI-only）会失败，_init_config 内部已有 ImportError 容错处理。
    "gui": ("gui.json", "arknights_video_pipeline.gui.theme.gui_config", "_GUI_DEFAULTS"),
}


def _init_config(module: str) -> list[str]:
    """生成默认配置文件

    Args:
        module: 模块名 ("all" 生成全部, 或指定单个模块)

    Returns:
        成功生成的文件绝对路径列表（导入失败时对应条目被跳过）

    Raises:
        ValueError: 未知模块名（由 CLI/GUI 调用方决定如何展示与退出）
    """
    config_dir = os.path.join(PROJECT_ROOT, "config")
    os.makedirs(config_dir, exist_ok=True)

    if module == "all":
        modules = list(_MODULE_CONFIGS.keys())
    elif module in _MODULE_CONFIGS:
        modules = [module]
    else:
        valid = ", ".join(list(_MODULE_CONFIGS.keys()) + ["all"])
        raise ValueError(f"未知模块 '{module}'（可用模块: {valid}）")

    # 动态导入 video_compose 会触发 movielite 导入时检查（shutil.which 查找
    # ffmpeg/ffprobe，缺失时抛 RuntimeError）。在导入前先应用 FFmpeg 路径配置
    # 并确保其在 PATH 中，避免无系统 FFmpeg、仅配置了 resource/ffmpeg/bin 时
    # --init-config 或 GUI 重置配置失败（与 build_exe 的 _preapply_ffmpeg_config 对齐）。
    _cfg_mgr = ConfigManager(PROJECT_ROOT)
    _cfg_mgr.load_pipeline_config()
    set_ffmpeg_config(
        bool(_cfg_mgr.pipeline.get("ffmpeg_custom_enabled", False)),
        _cfg_mgr.pipeline.get("ffmpeg_path", ""),
    )
    ensure_ffmpeg_in_path()

    generated: list[str] = []
    for mod_name in modules:
        filename, source_module, attr_name = _MODULE_CONFIGS[mod_name]
        filepath = os.path.join(config_dir, filename)

        # 动态导入模块获取默认配置
        try:
            mod = importlib.import_module(source_module)
            default_config = getattr(mod, attr_name, {})
        except (ImportError, AttributeError, RuntimeError) as exc:
            # RuntimeError 防御：movielite 等第三方库在导入时可能因环境
            # 不满足（如 ffmpeg 缺失）抛 RuntimeError，同样按跳过处理
            print(f"警告: 无法加载 {mod_name} 的默认配置 ({exc})，跳过")
            continue

        # 移除 _comment 等元数据键
        clean_config = {k: v for k, v in default_config.items() if not k.startswith("_")}

        # 确保子目录存在（如 video_compose/）
        file_dir = os.path.dirname(filepath)
        if file_dir:
            os.makedirs(file_dir, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(clean_config, f, indent=4, ensure_ascii=False)

        generated.append(filepath)
        print(f"已生成: {filepath}")

    if generated:
        print(f"\n共生成 {len(generated)} 个配置文件")
    else:
        print("未生成任何配置文件")
    return generated


def ensure_default_configs() -> list[str]:
    """确保默认配置文件存在，仅生成缺失的文件（不覆盖已有用户配置）

    用于打包环境首次启动时自动生成必要的配置文件，避免因 config/ 目录
    不存在导致 GUI 启动失败。与 ``_init_config`` 的区别：
    ``_init_config`` 强制覆盖所有文件（用于 ``--init-config`` 重置），
    本函数跳过已存在的文件（保护用户自定义配置）。

    Returns:
        本次新生成的文件绝对路径列表（已存在的文件不计入）
    """
    # 静态导入默认配置源模块——PyInstaller 静态分析能检测到 from...import，
    # 从而确保这些模块被打包。importlib.import_module(variable) 无法被检测。
    from arknights_video_pipeline.core.config import PIPELINE_DEFAULTS
    from arknights_video_pipeline.core.formation_to_text import (
        DEFAULT_CONFIG as _FORMATION_DEFAULTS,
    )
    from arknights_video_pipeline.core.actions_to_text import (
        DEFAULT_CONFIG as _ACTIONS_DEFAULTS,
    )
    from arknights_video_pipeline.core.track_startbutton import (
        DEFAULT_CONFIG as _TRACK_DEFAULTS,
    )
    from arknights_video_pipeline.core.video_compose import (
        DEFAULT_CONFIG as _STYLE1_DEFAULTS,
    )
    from arknights_video_pipeline.core.video_compose_style2 import (
        DEFAULT_CONFIG as _STYLE2_DEFAULTS,
    )

    _defaults_map: dict[str, dict] = {
        "pipeline.json": PIPELINE_DEFAULTS,
        "formation.json": _FORMATION_DEFAULTS,
        "actions.json": _ACTIONS_DEFAULTS,
        "track.json": _TRACK_DEFAULTS,
        "video_compose/style1.json": _STYLE1_DEFAULTS,
        "video_compose/style2.json": _STYLE2_DEFAULTS,
    }

    # gui_config 需要 PyQt6，CLI 模式下可能不可用
    try:
        from arknights_video_pipeline.gui.theme.gui_config import _GUI_DEFAULTS
        _defaults_map["gui.json"] = _GUI_DEFAULTS
    except ImportError:
        pass

    config_dir = os.path.join(PROJECT_ROOT, "config")

    generated: list[str] = []
    for filename, default_config in _defaults_map.items():
        filepath = os.path.join(config_dir, filename)
        if os.path.exists(filepath):
            continue

        clean_config = {k: v for k, v in default_config.items() if not k.startswith("_")}

        file_dir = os.path.dirname(filepath)
        if file_dir:
            os.makedirs(file_dir, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(clean_config, f, indent=4, ensure_ascii=False)

        generated.append(filepath)

    return generated


# ══════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════


def match_custom_copilot_jsons(
    videos: list[str],
    json_paths: list[str],
) -> tuple[dict[str, str], list[str]]:
    """将自定义作业 JSON 文件与视频文件匹配（CLI --copilot-json）

    规则：
    - 单个视频 + 单个 JSON：直接绑定，无需文件名匹配；
    - 其余情况（多视频或多 JSON）：按文件名（去扩展名，不区分大小写）
      匹配，视频 stem 与 JSON stem 相同才绑定；
    - 未匹配到任何视频的 JSON：警告提示后被忽略。

    Args:
        videos: 视频文件路径列表（可为相对路径）
        json_paths: 自定义作业 JSON 路径列表

    Returns:
        (绑定映射, 提示信息列表)：映射键为视频绝对路径，值为 JSON 绝对路径
    """
    videos_abs = [os.path.abspath(v) for v in videos]
    jsons_abs = [os.path.abspath(j) for j in json_paths]

    if not jsons_abs:
        return {}, []

    if len(videos_abs) == 1 and len(jsons_abs) == 1:
        return {videos_abs[0]: jsons_abs[0]}, []

    # 多视频或多 JSON：按文件名匹配，并提示匹配逻辑与测试状态
    notes: list[str] = [
        "多视频/多JSON场景下，作业JSON按文件名（去扩展名，不区分大小写）与视频匹配",
        "多视频的自定义作业JSON为测试功能，建议仅使用单个视频文件",
    ]
    mapping: dict[str, str] = {}
    video_stems = {
        os.path.splitext(os.path.basename(v))[0].lower(): v for v in videos_abs
    }
    for jp in jsons_abs:
        stem = os.path.splitext(os.path.basename(jp))[0].lower()
        video = video_stems.get(stem)
        if video is None:
            notes.append(f"作业JSON未匹配到任何视频，将被忽略: {jp}")
        else:
            mapping[video] = jp
    return mapping, notes


def main() -> None:
    parser = build_argparser()
    args = parser.parse_args()

    config_mgr = ConfigManager(PROJECT_ROOT)

    # ── 生成默认配置 ──────────────────────────────────────
    if args.init_config is not None:
        try:
            _init_config(args.init_config)
        except ValueError as exc:
            print(f"错误: {exc}")
            sys.exit(1)
        return

    # ── --recognize-only 与 --copilot-json 互斥 ──────────
    # 前者是产出 copilot JSON（仅跑步骤1），后者是消费已有 JSON（跳过步骤1），
    # 两者语义冲突，同时指定会无意义。
    if args.recognize_only and args.copilot_json:
        parser.error(
            "--recognize-only 与 --copilot-json 互斥：\n"
            "  --recognize-only   仅执行视频识别，输出 copilot JSON\n"
            "  --copilot-json     使用已有作业 JSON，跳过视频识别"
        )

    # ── 视频路径必须提供（现为列表，支持批量） ────────────
    if not args.video:
        parser.error(
            "请提供至少一个视频文件路径，或使用 --init-config 生成默认配置\n"
            "用法: python main.py <video...> --background-image <image>"
        )

    videos: list[str] = []
    for v in args.video:
        videos.append(v if os.path.isabs(v) else os.path.abspath(v))

    # ── 加载配置 ──────────────────────────────────────────
    config_mgr.load_pipeline_config(args.config)

    # ── 背景板图片路径（整批共享） ────────────────────────
    # 未指定 --style 时沿用配置中的 video_compose_style（CLI 参数优先于配置）
    style = args.style or config_mgr.get_video_compose_style()
    background_image_path = None
    if args.background_image:
        background_image_path = args.background_image
        if not os.path.isabs(background_image_path):
            background_image_path = os.path.abspath(background_image_path)
    elif style == "style1" and not args.recognize_only:
        # --recognize-only 仅执行识别（步骤1），不涉及视频合成，
        # 无需背景板图片；其余场景 style1 仍要求背景板图片
        parser.error(
            "style1 需要背景板图片，请使用 --background-image / -b 指定\n"
            "若不需要背景板图片，可使用 --style style2 或 --recognize-only\n"
            f"支持的图片格式: {', '.join(sorted(SUPPORTED_IMAGE_EXTENSIONS))}\n"
            "用法: python main.py <video...> --background-image <image>"
        )

    cli_overrides: dict[str, Any] = {}
    if args.maa_path:
        cli_overrides["maa_path"] = args.maa_path
    if args.backend:
        cli_overrides["copilot_backend"] = args.backend
    # Recognition 后端子配置覆盖（合并到已有 recognition 配置块）
    if args.ocr or args.stage or args.resolution:
        rec_cfg = dict(config_mgr.pipeline.get("recognition", {}) or {})
        if args.ocr:
            rec_cfg["ocr_source"] = args.ocr
        if args.stage:
            rec_cfg["stage_override"] = args.stage
        if args.resolution:
            rec_cfg["resolution"] = args.resolution
        cli_overrides["recognition"] = rec_cfg
    if args.output_dir:
        cli_overrides["output_dir"] = args.output_dir
    if args.log_level:
        cli_overrides["log_level"] = args.log_level
    if args.no_log_file:
        cli_overrides["log_to_file"] = False
    if args.style:
        # 根据风格名称设置视频合成配置路径（仅在显式指定时覆盖用户配置）
        style_name = args.style
        cli_overrides["video_compose_style"] = style_name
        cli_overrides["video_compose_config"] = (
            f"config/video_compose/{style_name}.json"
        )
    config_mgr.merge_cli_overrides(cli_overrides)

    # 同步 FFmpeg 路径配置到 utils 模块全局（CLI 路径，不经过 ConfigProxy）
    set_ffmpeg_config(
        bool(config_mgr.pipeline.get("ffmpeg_custom_enabled", False)),
        config_mgr.pipeline.get("ffmpeg_path", ""),
    )

    # ── 初始化日志 ────────────────────────────────────────
    # 单文件：日志写入该视频输出目录（保持向后兼容）；
    # 多文件：日志写入基础输出目录，覆盖整批。
    log_to_file = config_mgr.pipeline.get("log_to_file", True)
    if len(videos) == 1:
        log_video_name = os.path.splitext(os.path.basename(videos[0]))[0]
        log_dir = config_mgr.get_output_dir(log_video_name) if log_to_file else None
    else:
        log_dir = config_mgr.get_output_dir() if log_to_file else None
    logger = setup_logger(
        "pipeline",
        log_dir=log_dir,
        log_level=config_mgr.get_log_level(),
        log_to_file=log_to_file,
        max_bytes=config_mgr.pipeline.get("log_max_bytes", 10 * 1024 * 1024),
        backup_count=config_mgr.pipeline.get("log_backup_count", 3),
    )

    # ── 验证背景板图片（整批共享，失败即退出） ────────────
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

    # ── 自定义作业 JSON（CLI --copilot-json）──────────────
    # 校验 JSON 文件并建立「视频 → 作业JSON」绑定，绑定后跳过步骤1识别。
    custom_json_map: dict[str, str] = {}
    if args.copilot_json:
        json_paths: list[str] = []
        for jp in args.copilot_json:
            if not os.path.isabs(jp):
                jp = os.path.abspath(jp)
            if os.path.splitext(jp)[1].lower() != ".json":
                parser.error(f"作业JSON必须是 .json 文件: {jp}")
            if not os.path.exists(jp):
                parser.error(f"作业JSON文件不存在: {jp}")
            json_paths.append(jp)
        custom_json_map, json_notes = match_custom_copilot_jsons(
            videos, json_paths
        )
        for note in json_notes:
            logger.warning(note)
        for video_path, jp in custom_json_map.items():
            logger.info(
                f"视频绑定自定义作业JSON: "
                f"{os.path.basename(video_path)} -> {jp}"
            )

    # ── --recognize-only：自动跳过 formation/actions/track/compose ──
    # 仅执行步骤1（视频转 copilot JSON），输出单一 JSON 文件。
    # 与用户显式 --skip-step 合并（用户仍可额外指定，但上述四步必跳）。
    effective_skip_steps: set[str] = set(args.skip_step)
    if args.recognize_only:
        effective_skip_steps |= {"formation", "actions", "track", "compose"}
        logger.info(
            "--recognize-only 模式：仅执行视频识别，跳过 "
            "编队/操作/跟踪/合成步骤"
        )

    # ── Dry-run 模式：验证全部视频后返回 ──────────────────
    if args.dry_run:
        logger.info("Dry-run模式：开始验证全部输入")
        logger.info(f"背景板图片: {background_image_path}")
        logger.info(f"识别后端: {config_mgr.get_copilot_backend()}")
        logger.info(f"MAA路径: {config_mgr.get_maa_path()}")
        logger.info(f"跳过步骤: {sorted(effective_skip_steps)}")
        all_ok = True
        for idx, video_path in enumerate(videos, start=1):
            try:
                logger.info(f"[{idx}/{len(videos)}] 验证视频文件: {video_path}")
                video_info = validate_video_file(video_path)
                logger.info(
                    f"  视频信息: {video_info['width']}x{video_info['height']}, "
                    f"时长{video_info['duration']:.2f}s"
                )
            except VideoValidationError as exc:
                logger.error(f"  验证失败: {exc}")
                all_ok = False
        logger.info(
            f"Dry-run完成：{'全部通过' if all_ok else '存在无效输入'}"
        )
        sys.exit(0 if all_ok else 1)

    # ── 批量执行流水线 ────────────────────────────────────
    total = len(videos)
    success_count = 0
    logger.info(f"开始批量处理：共 {total} 个文件")
    for idx, video_path in enumerate(videos, start=1):
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"  批量处理 {idx}/{total}: {video_name}")
        logger.info("=" * 60)

        # 单文件验证失败 → 记录并继续下一个
        try:
            video_info = validate_video_file(video_path)
            logger.info(
                f"视频信息: {video_info['width']}x{video_info['height']}, "
                f"时长{video_info['duration']:.2f}s"
            )
        except VideoValidationError as exc:
            logger.error(f"视频验证失败，跳过该文件: {exc}")
            continue
        except Exception as exc:  # 防御：意外异常不应中断整批
            logger.error(f"视频验证发生意外错误，跳过该文件: {exc}")
            continue

        try:
            pipeline = Pipeline(
                video_path=video_path,
                config_mgr=config_mgr,
                logger=logger,
                background_image_path=background_image_path,
                skip_steps=effective_skip_steps,
                copilot_json_path=custom_json_map.get(video_path),
            )
            if pipeline.run():
                success_count += 1
            else:
                logger.error(f"文件处理失败: {video_path}")
        except Exception as exc:
            # 单文件异常不应中断整个队列
            logger.error(f"文件处理异常，跳过该文件: {video_path} - {exc}")

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"  批量处理结束：成功 {success_count}/{total}")
    logger.info("=" * 60)
    sys.exit(0 if success_count == total else 1)
