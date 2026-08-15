"""track_startbutton 匹配逻辑单元测试

验证 core/track_startbutton.py 的多模板匹配：
- 复用线程池与临时线程池结果一致
- 传入的线程池不被 match_templates_parallel 关闭（整个检测循环共用）
- 单/多模板路径行为一致

注意：模板必须非恒定（CCOEFF_NORMED 对恒定区域结果退化，会出现假匹配）。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np

from arknights_video_pipeline.core.track_startbutton import (
    DEFAULT_CONFIG,
    match_single_template,
    match_templates_parallel,
    precompute_scaled_templates,
)

# 背景：非恒定渐变（避免恒定区域导致的 CCOEFF_NORMED 退化）
_YY, _XX = np.mgrid[0:120, 0:160]
_BACKGROUND = (_XX * 0.5 + _YY * 0.25).astype(np.uint8)

# 目标模板：水平渐变 40x40（任意缩放均非恒定）
_BLOCK = np.tile(np.linspace(100, 255, 40, dtype=np.uint8), (40, 1))

# 合成帧：渐变背景 + 中央目标方块
_FRAME = _BACKGROUND.copy()
_FRAME[40:80, 60:100] = _BLOCK

# 干扰模板：垂直渐变 / 2px 棋盘格（非恒定，但与帧不匹配）
_OTHER_TEMPLATE = np.tile(
    np.linspace(0, 180, 20, dtype=np.uint8).reshape(-1, 1), (1, 20)
)
_THIRD_TEMPLATE = (
    (np.indices((20, 20)).sum(axis=0) % 4 < 2) * 200
).astype(np.uint8)

_TEMPLATES = [
    ("target.png", _BLOCK),
    ("other.png", _OTHER_TEMPLATE),
    ("third.png", _THIRD_TEMPLATE),
]

# 无目标帧：随机噪声（确定种子，保证可复现）
_NO_TARGET_FRAME = np.random.default_rng(0).integers(
    0, 256, (120, 160), dtype=np.uint8
)

_FRAME_SIZE = (120, 160)


def _make_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg["match_threshold"] = 0.8
    cfg["max_workers"] = 2
    return cfg


def _build_scaled_cache():
    return precompute_scaled_templates(
        _TEMPLATES, [0.5, 1.5], 9, _FRAME_SIZE
    )


class TestMatchTemplatesParallel:
    """验证 match_templates_parallel 的线程池复用行为"""

    def test_shared_executor_matches_temp_executor(self) -> None:
        """复用线程池与临时线程池的结果一致"""
        config = _make_config()
        cache = _build_scaled_cache()
        expected_match, expected_val = match_templates_parallel(
            _FRAME, _TEMPLATES, cache, config
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            shared_match, shared_val = match_templates_parallel(
                _FRAME, _TEMPLATES, cache, config, executor
            )

        assert shared_val == expected_val
        assert shared_match == expected_match
        assert shared_match["template"] == "target.png"
        assert shared_match["confidence"] > 0.95

    def test_shared_executor_not_shutdown_by_callee(self) -> None:
        """传入的线程池不应被 match_templates_parallel 关闭（循环内复用）"""
        config = _make_config()
        cache = _build_scaled_cache()
        with ThreadPoolExecutor(max_workers=2) as executor:
            for _ in range(3):
                match_templates_parallel(_FRAME, _TEMPLATES, cache, config, executor)
            # 调用后线程池仍可正常提交任务（未被 shutdown）
            future = executor.submit(lambda: 42)
            assert future.result() == 42

    def test_shared_executor_reusable_after_many_calls(self) -> None:
        """同一线程池连续多次调用结果稳定（模拟整个检测循环）"""
        config = _make_config()
        cache = _build_scaled_cache()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = {
                match_templates_parallel(_FRAME, _TEMPLATES, cache, config, executor)[1]
                for _ in range(10)
            }
        assert len(results) == 1

    def test_few_templates_serial_path(self) -> None:
        """模板数 <=2 时走串行路径，结果与逐模板匹配的最大值一致"""
        config = _make_config()
        two_templates = _TEMPLATES[:2]
        cache = precompute_scaled_templates(two_templates, [0.5, 1.5], 9, _FRAME_SIZE)
        match, val = match_templates_parallel(_FRAME, two_templates, cache, config)

        # 串行路径 = 各模板 match_single_template 的最大值（early_stop 与流水线一致）
        early_stop = config.get("early_stop_threshold", 0.92)
        expected_val = max(
            match_single_template(_FRAME, cache[tname], 0.8, early_stop)[0]
            for tname, _ in two_templates
        )
        assert val == expected_val
        assert match is not None
        assert match["confidence"] == round(float(val), 4)

    def test_no_match_returns_none(self) -> None:
        """无目标时返回 (None, 低置信度)，不抛异常"""
        config = _make_config()
        cache = _build_scaled_cache()
        match, val = match_templates_parallel(
            _NO_TARGET_FRAME, _TEMPLATES, cache, config
        )
        assert match is None
        assert 0 <= val < 0.8