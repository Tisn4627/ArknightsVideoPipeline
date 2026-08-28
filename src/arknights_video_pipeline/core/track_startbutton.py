"""
视频元素识别与跟踪脚本 - 优化版
性能优化：灰度匹配、预缩放模板缓存、ROI区域搜索、早停机制、并行匹配、tqdm进度条
"""

import json
import logging
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2
import numpy as np

from arknights_video_pipeline.core.battlestart import (
    BATTLE_START_DEFAULTS,
    TRACK_MODE_BATTLESTART,
    TRACK_MODE_STARTBUTTON,
    iter_sampled_frames,
    scan_battle_start,
)
from arknights_video_pipeline.core.utils import (
    PROJECT_ROOT,
    _no_window_kwargs,
    ensure_ffmpeg_in_path,
    load_config,
    save_default_config,
)

# 模块级 logger（由 pipeline.py 的 setup_logger 统一配置 root logger）
logger = logging.getLogger(__name__)

# tqdm 为可选依赖：存在时显示进度条，缺失时回退到普通日志输出
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# 默认配置（video_source 由流水线运行时注入）
DEFAULT_CONFIG = {
    "track_mode": TRACK_MODE_BATTLESTART,  # 识别模式：startbutton=开始按钮 / battlestart=战斗开始（默认）
    "resource_dir": "resource/StartButton",
    "match_threshold": 0.75,
    "scale_range": [0.5, 1.5],
    "scale_steps": 9,
    "detection_fps": 2,
    "detection_time_limit": 30,
    "auto_downscale": True,
    "downscale_target_height": 720,
    "min_consecutive_frames": 2,
    "use_grayscale": True,
    "use_roi": True,
    "roi_padding": 50,
    "roi_search_expand": 1.5,
    "early_stop_threshold": 0.92,
    "max_workers": 4,
    "debug_mode": True,
    "output_result": True,
    # battle_start 子配置（battlestart 模式使用，与默认值深度合并）
    "battle_start": dict(BATTLE_START_DEFAULTS),
}


def load_templates(resource_dir, use_grayscale=True):
    """加载模板图片"""
    templates = []
    if not os.path.isdir(resource_dir):
        logger.warning(f"资源目录不存在: {resource_dir}")
        return templates

    for fname in sorted(os.listdir(resource_dir)):
        fpath = os.path.join(resource_dir, fname)
        if not fname.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
            continue
        img = cv2.imread(fpath, cv2.IMREAD_COLOR)
        if img is None:
            continue
        if use_grayscale:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        templates.append((fname, img))
        logger.info(f"  加载模板: {fname} ({img.shape[1]}x{img.shape[0]})")

    return templates


def precompute_scaled_templates(templates, scale_range, scale_steps, frame_size):
    """预计算所有模板的缩放版本，返回 {模板名: [(scale, scaled_img), ...]}"""
    scaled_cache = {}
    scales = np.linspace(scale_range[0], scale_range[1], scale_steps)
    fw, fh = frame_size

    for tname, timg in templates:
        tlist = []
        for scale in scales:
            sw = int(timg.shape[1] * scale)
            sh = int(timg.shape[0] * scale)
            if sw < 10 or sh < 10 or sw > fw or sh > fh:
                continue
            scaled = cv2.resize(timg, (sw, sh), interpolation=cv2.INTER_AREA)
            tlist.append((scale, scaled))
        scaled_cache[tname] = tlist

    return scaled_cache


def match_single_template(frame_gray, scaled_list, threshold, early_stop=1.0):
    """对单个模板的所有缩放版本进行匹配，支持早停"""
    best_val = 0
    best_loc = None
    best_scale = 1.0

    for scale, scaled_tmpl in scaled_list:
        # 跳过超出搜索区域尺寸的模板，避免 matchTemplate 断言失败
        if (scaled_tmpl.shape[0] > frame_gray.shape[0]
                or scaled_tmpl.shape[1] > frame_gray.shape[1]):
            continue
        result = cv2.matchTemplate(frame_gray, scaled_tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val > best_val:
            best_val = max_val
            best_loc = max_loc
            best_scale = scale

        # 早停：置信度已足够高，跳过剩余缩放
        if best_val >= early_stop:
            break

    return best_val, best_loc, best_scale


def match_templates_parallel(frame_gray, templates, scaled_cache, config, executor=None):
    """多模板匹配，返回 (best_match_dict, best_confidence)

    executor 为调用方创建的复用线程池（推荐：整个检测循环共用同一个线程池，
    避免每采样帧创建/销毁）；为 None 时内部临时创建（兼容独立调用场景）。
    模板数量 ≤2 时直接串行，避免线程开销。
    """
    threshold = config.get("match_threshold", DEFAULT_CONFIG["match_threshold"])
    early_stop = config.get("early_stop_threshold", 0.92)
    max_workers = config.get("max_workers", 4)

    best_match = None
    best_val = 0

    # 单模板数量少时直接串行，避免线程开销
    if len(templates) <= 2:
        for tname, timg in templates:
            val, loc, scale = match_single_template(
                frame_gray, scaled_cache[tname], threshold, early_stop
            )
            if val >= threshold and val > best_val:
                best_val = val
                h, w = timg.shape[:2]
                best_match = {
                    "template": tname,
                    "confidence": round(float(val), 4),
                    "location": (int(loc[0]), int(loc[1])),
                    "scale": round(float(scale), 3),
                    "size": (int(w * scale), int(h * scale))
                }
        return best_match, best_val

    # 多模板并行匹配：优先复用调用方传入的线程池（未传入时临时创建）
    own_executor = executor is None
    pool = executor if executor is not None else ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {}
        for tname, timg in templates:
            future = pool.submit(
                match_single_template,
                frame_gray, scaled_cache[tname], threshold, early_stop
            )
            futures[future] = (tname, timg)

        for future in as_completed(futures):
            tname, timg = futures[future]
            val, loc, scale = future.result()
            if val >= threshold and val > best_val:
                best_val = val
                h, w = timg.shape[:2]
                best_match = {
                    "template": tname,
                    "confidence": round(float(val), 4),
                    "location": (int(loc[0]), int(loc[1])),
                    "scale": round(float(scale), 3),
                    "size": (int(w * scale), int(h * scale))
                }
        return best_match, best_val
    finally:
        if own_executor:
            pool.shutdown(wait=True)


def extract_roi(frame_gray, last_location, last_size, frame_size, config):
    """提取ROI区域，减少搜索范围"""
    if last_location is None or last_size is None:
        return frame_gray, (0, 0)

    padding = config.get("roi_padding", 50)
    expand = config.get("roi_search_expand", 1.5)
    fh, fw = frame_size

    # 基于上次位置扩展搜索区域
    cx = last_location[0] + last_size[0] // 2
    cy = last_location[1] + last_size[1] // 2
    half_w = int(last_size[0] * expand / 2) + padding
    half_h = int(last_size[1] * expand / 2) + padding

    x1 = max(0, cx - half_w)
    y1 = max(0, cy - half_h)
    x2 = min(fw, cx + half_w)
    y2 = min(fh, cy + half_h)

    roi = frame_gray[y1:y2, x1:x2]

    # ROI太小则退回全帧
    if roi.shape[0] < 30 or roi.shape[1] < 30:
        return frame_gray, (0, 0)

    return roi, (x1, y1)


def validate_detection_fps(detection_fps, video_fps):
    """验证检测帧率配置是否合法"""
    if detection_fps <= 0:
        raise ValueError(
            f"检测帧率必须大于0，当前配置值: {detection_fps}。"
            f"请在配置文件中将 detection_fps 设置为正数。"
        )
    if detection_fps > video_fps:
        raise ValueError(
            f"检测帧率({detection_fps}fps)不能超过视频原始帧率({video_fps:.2f}fps)。"
            f"请将 detection_fps 设置为不超过 {video_fps:.2f} 的值。"
        )
    return True


def downscale_video(video_path, target_height=720):
    """
    检测视频分辨率，若高度>=target_height则转码为720p。
    返回 (实际使用的视频路径, 缩放比例, 是否进行了转码)
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return video_path, 1.0, False

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    # 分辨率未超过目标高度，无需缩放
    if orig_h < target_height:
        logger.info(f"视频分辨率 {orig_w}x{orig_h} 低于 {target_height}p，保持原始分辨率")
        return video_path, 1.0, False

    # 计算目标宽度，保持宽高比
    scale_ratio = target_height / orig_h
    target_w = int(orig_w * scale_ratio)
    # 确保宽度为偶数（ffmpeg要求）
    target_w = target_w if target_w % 2 == 0 else target_w + 1

    logger.info(f"视频分辨率 {orig_w}x{orig_h} >= {target_height}p，转码为 {target_w}x{target_height}")

    # 使用ffmpeg转码到临时文件
    # 先确保 ffmpeg 在 PATH 中（自定义 ffmpeg 目录或系统 PATH），
    # 使本步骤在跳过前置步骤（copilot/track 之前的校验）时也可独立工作
    ensure_ffmpeg_in_path()
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="track_downscaled_")
    os.close(tmp_fd)

    cmd = [
        "ffmpeg", "-y",
        # 全局选项须位于输出文件之前，置于其后会被当作
        # trailing options 忽略导致日志级别抑制失效
        "-loglevel", "error",
        "-hide_banner",
        "-i", video_path,
        "-vf", f"scale={target_w}:{target_height}",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-an",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        tmp_path,
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            timeout=300,
            capture_output=True,
            # GUI exe（--noconsole）启动 ffmpeg 时，Windows 会为子进程
            # 分配全新 console 窗口（虽然 capture_output 已重定向输出，
            # 窗口仍会弹出且无内容）。CREATE_NO_WINDOW 阻止分配。
            **_no_window_kwargs(),
        )
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else ''
        logger.error(f"转码失败: {e}\nffmpeg stderr: {stderr_msg}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return video_path, 1.0, False
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning(f"转码失败: {e}，将使用原始视频")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return video_path, 1.0, False

    logger.info(f"转码完成: {target_w}x{target_height}")
    return tmp_path, scale_ratio, True


def track_element(config):
    """主跟踪函数（优化版）"""
    video_path = config.get("video_source", "test.mp4")
    # 其余配置项（detection_fps/resource_dir 等）由 _track_element_inner 解析
    auto_downscale = config.get("auto_downscale", True)
    downscale_target = config.get("downscale_target_height", 720)

    # 将相对路径解析为基于项目根目录的绝对路径
    if not os.path.isabs(video_path):
        video_path = os.path.join(PROJECT_ROOT, video_path)

    # 自动降分辨率
    downscaled_path = video_path
    video_scale_ratio = 1.0
    was_downscaled = False
    if auto_downscale:
        downscaled_path, video_scale_ratio, was_downscaled = downscale_video(video_path, downscale_target)

    try:
        return _track_element_inner(
            config, video_path, downscaled_path, video_scale_ratio, was_downscaled
        )
    finally:
        # 确保临时降分辨率视频被清理
        if was_downscaled and downscaled_path != video_path and os.path.exists(downscaled_path):
            try:
                os.remove(downscaled_path)
                logger.info("已清理临时降分辨率视频文件")
            except OSError as e:
                logger.warning(f"清理临时文件失败: {e}")


def _resolve_track_mode(config):
    """解析识别模式配置，未知值回退到默认的开始按钮识别"""
    mode = str(config.get("track_mode", DEFAULT_CONFIG["track_mode"])).strip().lower()
    if mode not in (TRACK_MODE_STARTBUTTON, TRACK_MODE_BATTLESTART):
        logger.warning(
            f"未知的识别模式: {config.get('track_mode')!r}，"
            f"回退到默认值 {DEFAULT_CONFIG['track_mode']!r}"
        )
        mode = DEFAULT_CONFIG["track_mode"]
    return mode


def _battle_start_config(config):
    """提取 battle_start 子配置，与默认值合并（缺失键使用默认值）"""
    bs_cfg = dict(BATTLE_START_DEFAULTS)
    bs_cfg.update(config.get("battle_start") or {})
    return bs_cfg


def _prepare_detection_window(
    bs_cfg, track_mode, detection_time_limit,
    duration, total_frames, fps, detection_fps,
):
    """计算检测时间窗口与采样间隔

    返回 (effective_time_limit, detection_end_frame, sample_interval)；
    检测帧率配置非法时记录错误并返回 None。
    """
    # ── 检测时间限制 ──────────────────────────────────────
    # 边界条件：视频时长不足限制时间时，自动调整为检测完整视频
    # battlestart 模式使用 battle_start.time_limit，startbutton 模式使用 detection_time_limit
    time_limit = (
        bs_cfg["time_limit"] if track_mode == TRACK_MODE_BATTLESTART
        else detection_time_limit
    )
    if time_limit is not None and time_limit > 0:
        effective_time_limit = min(time_limit, duration)
        detection_end_frame = int(effective_time_limit * fps)
        if time_limit > duration:
            logger.info(
                f"检测时间限制: {time_limit}s > 视频时长{duration:.2f}s，"
                f"自动调整为检测完整视频"
            )
        else:
            logger.info(
                f"检测时间限制: 仅检测前{effective_time_limit:.0f}s "
                f"(第0~{detection_end_frame}帧)"
            )
    else:
        effective_time_limit = None
        detection_end_frame = total_frames
        logger.info("检测时间限制: 未设置，检测完整视频")

    # 验证检测帧率
    try:
        validate_detection_fps(detection_fps, fps)
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        return None

    # 根据检测帧率计算采样间隔
    sample_interval = max(1, round(fps / detection_fps))
    actual_detection_fps = fps / sample_interval
    logger.info(
        f"检测帧率: {detection_fps}fps "
        f"(采样间隔: 每{sample_interval}帧, 实际约{actual_detection_fps:.2f}fps)"
    )
    return effective_time_limit, detection_end_frame, sample_interval


def _prepare_templates(config, resource_dir, use_grayscale,
                       was_downscaled, video_scale_ratio, frame_w, frame_h):
    """加载模板资源并预计算缩放缓存

    返回 (templates, scaled_cache, executor)；无模板时返回 (None, None, None)。
    executor 为多模板并行匹配共用的线程池（模板数 >2 时创建，否则 None）。
    """
    logger.info(f"\n加载模板资源: {resource_dir}")
    templates = load_templates(resource_dir, use_grayscale)
    if not templates:
        logger.error("未找到任何模板图片")
        return None, None, None
    logger.info(f"共加载 {len(templates)} 个模板\n")

    # 调整缩放范围：视频降分辨率后，模板需要额外缩小
    base_scale_range = config.get("scale_range", [0.5, 1.5])
    if was_downscaled:
        adjusted_low = base_scale_range[0] * video_scale_ratio
        adjusted_high = base_scale_range[1] * video_scale_ratio
        effective_scale_range = [adjusted_low, adjusted_high]
        logger.info(f"缩放范围调整: {base_scale_range} -> {effective_scale_range} (因视频降分辨率)")
    else:
        effective_scale_range = base_scale_range
    scale_steps = config.get("scale_steps", 9)

    # 预计算缩放模板
    logger.info("预计算缩放模板...")
    scaled_cache = precompute_scaled_templates(
        templates, effective_scale_range, scale_steps, (frame_w, frame_h)
    )
    total_scaled = sum(len(v) for v in scaled_cache.values())
    logger.info(f"预计算完成: {total_scaled} 个缩放模板")
    for tname, tlist in scaled_cache.items():
        if tlist:
            scales = [f"{s:.3f}" for s, _ in tlist]
            logger.info(f"  {tname}: 缩放因子 {', '.join(scales)}")
    logger.info("")

    # 多模板并行匹配时创建一次线程池，检测循环内复用（仅在模板数 >2 时创建）
    executor = None
    if len(templates) > 2:
        executor = ThreadPoolExecutor(max_workers=config.get("max_workers", 4))
    return templates, scaled_cache, executor


def _build_startbutton_result(
    config, track_mode, first_appear_time, disappear_time, max_confidence,
    global_best_confidence, global_best_frame, global_best_template,
    match_count, duration, effective_time_limit,
    was_downscaled, video_scale_ratio, elapsed_total, avg_speed, debug_mode,
):
    """组装 startbutton 模式的识别结果字典（输出诊断总结日志）"""
    # 诊断总结
    if debug_mode:
        logger.info("\n[诊断总结]")
        logger.info(
            f"  全局最佳置信度: {global_best_confidence:.4f} "
            f"(出现在第{global_best_frame}帧, 模板:{global_best_template})"
        )
        logger.info(f"  匹配阈值: {config.get('match_threshold', DEFAULT_CONFIG['match_threshold'])}")
        if global_best_confidence > 0 and global_best_confidence < config.get("match_threshold", DEFAULT_CONFIG["match_threshold"]):
            gap = config.get("match_threshold", DEFAULT_CONFIG["match_threshold"]) - global_best_confidence
            logger.info(f"  最佳置信度距阈值仅差 {gap:.4f}，可尝试降低阈值至 {global_best_confidence:.2f}")

    return {
        "track_mode": track_mode,
        # battle_start 相关字段（startbutton 模式下恒为未检测）
        "battle_start_time": None,
        "battle_start_frame": 0,
        "battle_start_max_ratio": 0.0,
        "battle_start_detected": False,
        "first_appear_time": round(first_appear_time, 2) if first_appear_time is not None else None,
        "disappear_time": round(disappear_time, 2) if disappear_time is not None else None,
        "duration_visible": round(disappear_time - first_appear_time, 2) if first_appear_time is not None and disappear_time is not None else None,
        "max_confidence": round(max_confidence, 4),
        "global_best_confidence": round(global_best_confidence, 4),
        "global_best_frame": global_best_frame,
        "match_count": match_count,
        "video_duration": round(duration, 2),
        "detection_time_limit": effective_time_limit,
        "was_detected": first_appear_time is not None,
        "was_downscaled": was_downscaled,
        "scale_ratio": round(video_scale_ratio, 4),
        "processing_time": round(elapsed_total, 2),
        "avg_speed_fps": round(avg_speed, 2),
    }


def _track_element_inner(config, video_path, downscaled_path, video_scale_ratio, was_downscaled):
    """track_element 的内部实现，临时文件由外层 try/finally 保证清理"""
    track_mode = _resolve_track_mode(config)
    bs_cfg = _battle_start_config(config)
    resource_dir = config.get("resource_dir", "resource/StartButton")
    detection_fps = config.get("detection_fps", 2)
    detection_time_limit = config.get("detection_time_limit", 30)
    min_consecutive = config.get("min_consecutive_frames", 2)
    use_grayscale = config.get("use_grayscale", True)
    use_roi = config.get("use_roi", True)
    debug_mode = config.get("debug_mode", True)

    # 将相对路径解析为基于项目根目录的绝对路径
    if not os.path.isabs(resource_dir):
        resource_dir = os.path.join(PROJECT_ROOT, resource_dir)

    # 打开视频（使用降分辨率后的路径）
    cap = cv2.VideoCapture(downscaled_path)
    pbar = None
    # 多模板并行匹配时复用的线程池（整个检测循环共用，避免每帧创建/销毁）
    executor = None
    try:
        if not cap.isOpened():
            logger.error(f"无法打开视频文件: {downscaled_path}")
            return None

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # 显式校验 fps，避免后续除零错误或空检测结果
        if fps is None or fps <= 0:
            logger.error(
                f"无法读取视频帧率或帧率无效 (fps={fps})，"
                f"视频可能已损坏或 OpenCV 不支持该编码。"
            )
            return None

        duration = total_frames / fps
        logger.info(f"视频信息: {frame_w}x{frame_h}, {total_frames}帧, {fps:.2f}fps, 时长{duration:.2f}秒")
        if was_downscaled:
            logger.info(f"  (已从原始视频降分辨率，视频缩放比例: {video_scale_ratio:.4f})\n")
        else:
            logger.info("")

        prepared = _prepare_detection_window(
            bs_cfg, track_mode, detection_time_limit,
            duration, total_frames, fps, detection_fps,
        )
        if prepared is None:
            return None
        effective_time_limit, detection_end_frame, sample_interval = prepared

        # ── 战斗开始检测模式（battlestart）：无需模板资源 ──
        if track_mode == TRACK_MODE_BATTLESTART:
            logger.info(f"识别模式: {track_mode} (战斗开始识别)")
            return scan_battle_start(
                cap, bs_cfg, fps, total_frames, duration,
                sample_interval, effective_time_limit, debug_mode,
                video_scale_ratio, was_downscaled,
            )

        # ── 开始按钮识别模式（startbutton）：加载模板资源 ──
        logger.info(f"识别模式: {track_mode} (开始按钮识别)")
        templates, scaled_cache, executor = _prepare_templates(
            config, resource_dir, use_grayscale,
            was_downscaled, video_scale_ratio, frame_w, frame_h,
        )
        if templates is None:
            return None

        # 计算需要处理的帧数（仅在检测时间范围内）
        processed_frames = len(range(0, detection_end_frame, sample_interval))

        # 跟踪状态
        first_appear_time = None
        disappear_time = None
        is_visible = False
        consecutive_visible = 0
        consecutive_invisible = 0
        max_confidence = 0
        match_count = 0

        # ROI跟踪状态
        last_location = None
        last_size = None
        roi_miss_count = 0

        # 诊断信息
        global_best_confidence = 0
        global_best_frame = 0
        global_best_template = ""
        diagnostic_interval = max(1, int(fps))

        processed_idx = 0
        start_time = time.time()

        # 进度条（tqdm 为可选依赖，缺失时回退到普通日志）
        pbar = tqdm(
            total=processed_frames, desc="识别进度", unit="帧",
            ncols=80,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        ) if tqdm is not None else None

        # 与 battlestart 模式共用的采样帧迭代器：grab 跳过非采样帧，
        # 避免约 93% 帧的完整解码
        for frame_idx, current_time, frame in iter_sampled_frames(
            cap, sample_interval, detection_end_frame, fps
        ):
            # 灰度化：仅在 use_grayscale=True 时转换，否则保留原帧（含彩色）
            # 以匹配 use_grayscale=False 时的彩色模板通道数
            if use_grayscale and frame.ndim == 3:
                frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                frame_gray = frame

            # ROI搜索优化
            offset = (0, 0)
            search_frame = frame_gray
            if use_roi and is_visible and last_location is not None and roi_miss_count < min_consecutive:
                search_frame, offset = extract_roi(
                    frame_gray, last_location, last_size, (frame_h, frame_w), config
                )

            # 执行匹配（复用检测循环共用的线程池）
            match, raw_confidence = match_templates_parallel(search_frame, templates, scaled_cache, config, executor)

            # 记录全局最佳置信度
            if raw_confidence > global_best_confidence:
                global_best_confidence = raw_confidence
                global_best_frame = frame_idx
                if match:
                    global_best_template = match["template"]
                elif raw_confidence > 0:
                    global_best_template = "未达阈值"

            # 修正ROI偏移
            if match and offset != (0, 0):
                match["location"] = (match["location"][0] + offset[0], match["location"][1] + offset[1])

            detected = match is not None

            if detected:
                consecutive_visible += 1
                consecutive_invisible = 0
                roi_miss_count = 0
                match_count += 1
                if match["confidence"] > max_confidence:
                    max_confidence = match["confidence"]
                last_location = match["location"]
                last_size = match["size"]

                if not is_visible and consecutive_visible >= min_consecutive:
                    is_visible = True
                    first_appear_time = current_time - (min_consecutive - 1) * sample_interval / fps
                    msg = (
                        f"[{current_time:.2f}s] 检测到目标出现! "
                        f"模板:{match['template']} 置信度:{match['confidence']:.4f}"
                    )
                    if pbar:
                        pbar.write(msg)
                    else:
                        logger.info(msg)
            else:
                consecutive_invisible += 1
                consecutive_visible = 0
                roi_miss_count += 1

                if roi_miss_count >= min_consecutive:
                    last_location = None
                    last_size = None

                if is_visible and consecutive_invisible >= min_consecutive:
                    is_visible = False
                    disappear_time = current_time - (min_consecutive - 1) * sample_interval / fps
                    msg = f"[{current_time:.2f}s] 目标消失!"
                    if pbar:
                        pbar.write(msg)
                    else:
                        logger.info(msg)

            # 诊断输出
            if debug_mode and processed_idx % diagnostic_interval == 0 and processed_idx > 0:
                threshold = config.get("match_threshold", DEFAULT_CONFIG["match_threshold"])
                msg = (
                    f"  [诊断] 帧{frame_idx} 最佳置信度:{raw_confidence:.4f} "
                    f"(阈值:{threshold}) {'[匹配]' if detected else '[未达]'}"
                )
                if pbar:
                    pbar.write(msg)
                else:
                    logger.info(msg)

            # 更新进度条
            if pbar:
                pbar.update(1)
            elif processed_idx % 100 == 0 and processed_idx > 0:
                elapsed = time.time() - start_time
                progress = processed_idx / processed_frames * 100
                speed = processed_idx / elapsed if elapsed > 0 else 0
                logger.info(
                    f"  进度: {progress:.1f}% ({processed_idx}/{processed_frames}) "
                    f"{speed:.1f}帧/s 已用时{elapsed:.1f}s"
                )

            processed_idx += 1

        if is_visible:
            disappear_time = round(duration, 2)
            logger.info(f"\n视频结束，目标仍可见，消失时间记为视频末尾: {disappear_time:.2f}s")

        elapsed_total = time.time() - start_time
        avg_speed = processed_frames / elapsed_total if elapsed_total > 0 else 0

        return _build_startbutton_result(
            config, track_mode, first_appear_time, disappear_time,
            max_confidence, global_best_confidence, global_best_frame,
            global_best_template, match_count, duration, effective_time_limit,
            was_downscaled, video_scale_ratio, elapsed_total, avg_speed,
            debug_mode,
        )
    finally:
        # 确保 tqdm 进度条与 VideoCapture 在异常路径下也被释放
        if pbar is not None:
            pbar.close()
        cap.release()
        if executor is not None:
            executor.shutdown(wait=True)


def main():
    # 独立运行时配置基础日志（流水线调用时由 setup_logger 统一配置）
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config_dir = os.path.join(PROJECT_ROOT, "config")
    os.makedirs(config_dir, exist_ok=True)

    config_path = os.path.join(config_dir, "track.json")

    if not os.path.exists(config_path):
        save_default_config(config_path, DEFAULT_CONFIG)
        logger.info(f"已生成默认配置文件: {config_path}\n")

    config = load_config(config_path, DEFAULT_CONFIG)

    logger.info("=" * 50)
    logger.info("视频元素识别与跟踪 (优化版)")
    logger.info("=" * 50)
    logger.info(f"识别模式: {_resolve_track_mode(config)}")
    logger.info(f"视频源: {config.get('video_source', 'test.mp4')}")
    logger.info(f"资源目录: {config.get('resource_dir', 'resource/StartButton')}")
    logger.info(f"匹配阈值: {config.get('match_threshold', DEFAULT_CONFIG['match_threshold'])}")
    logger.info(f"缩放范围: {config.get('scale_range', [0.5, 1.5])}")
    logger.info(f"检测帧率: {config.get('detection_fps', 2)}fps")
    logger.info(f"自动降分辨率: {config.get('auto_downscale', True)}")
    if config.get('auto_downscale', True):
        logger.info(f"降分辨率目标: {config.get('downscale_target_height', 720)}p")
    logger.info(f"灰度匹配: {config.get('use_grayscale', True)}")
    logger.info(f"ROI搜索: {config.get('use_roi', True)}")
    logger.info(f"并行线程: {config.get('max_workers', 4)}")
    logger.info(f"调试模式: {config.get('debug_mode', True)}")
    logger.info("")

    result = track_element(config)

    if result:
        logger.info("=" * 50)
        logger.info("跟踪结果")
        logger.info("=" * 50)
        if result["track_mode"] == TRACK_MODE_BATTLESTART:
            if result["battle_start_detected"]:
                logger.info(f"进入战斗时间: {result['battle_start_time']}s")
                logger.info(f"最高亮像素比: {result['battle_start_max_ratio']}")
            else:
                logger.info("未在检测时间范围内检测到进入战斗")
                logger.info(f"  最高亮像素比: {result['battle_start_max_ratio']}")
        elif result["was_detected"]:
            logger.info(f"首次出现时间: {result['first_appear_time']}s")
            logger.info(f"消失时间: {result['disappear_time']}s")
            logger.info(f"持续可见时长: {result['duration_visible']}s")
            logger.info(f"最高置信度: {result['max_confidence']}")
            logger.info(f"匹配帧数: {result['match_count']}")
        else:
            logger.info("未在视频中检测到目标元素")
            if result["global_best_confidence"] > 0:
                logger.info(f"  最佳置信度: {result['global_best_confidence']} (第{result['global_best_frame']}帧)")
        logger.info(f"视频总时长: {result['video_duration']}s")
        logger.info(f"处理耗时: {result['processing_time']}s")
        logger.info(f"平均速度: {result['avg_speed_fps']} 帧/s")

        if config.get("output_result", True):
            video_basename = os.path.splitext(os.path.basename(config.get("video_source", "test.mp4")))[0]
            output_dir = os.path.join(PROJECT_ROOT, "output", video_basename)
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as e:
                logger.error(f"无法创建输出目录 {output_dir}: {e}")
                return
            result_path = os.path.join(output_dir, f"track_result_{video_basename}.json")
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=4, ensure_ascii=False)
            logger.info(f"结果已保存至: {result_path}")
    else:
        logger.error("跟踪失败")


if __name__ == "__main__":
    main()
