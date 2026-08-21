"""
pictex 兼容补丁：消除重复渲染时的字体加载与内存泄漏

背景
----
pictex 每次 ``render`` 都会新建 FontManager（重新从磁盘加载字体）与
HarfBuzzShaper（重新创建 hb 字体并缓存整份字体表数据），且
``TypefaceLoader._typefaces_loading_info`` 会永久持有所有加载过的
typeface。在 text_fit 的换行测量循环（逐字符试探渲染）中，
每次 render 固定泄漏约 8.8MB（CJK 字体表数据），数百次渲染即可
耗尽内存——表现为进程越来越慢直至卡死（甚至原生 Abort）。

本模块在导入时对 pictex 做两处最小补丁，渲染结果逐字节不变：
  1. ``TypefaceLoader.load_from_file`` 按文件路径缓存 typeface，
     同一字体文件全进程只加载一次；
  2. ``HarfBuzzShaper`` 的 hb 字体缓存提升为进程级共享（键为
     typeface 对象 + 字号；typeface 已按路径缓存，因此键稳定），
     避免每次 render 重复读取整份字体表。

补丁后测量循环不再累积内存（实测 100 次 render 内存增长
约 1770MB -> 15MB）。可变字体（Variable Font）的变体克隆仍会
随调用产生新 typeface，本项目使用的静态字体不受影响。
"""

from __future__ import annotations

from pictex.text.harfbuzz_shaper import HarfBuzzShaper
from pictex.text.typeface_loader import TypefaceLoader

__all__ = ["apply_pictex_patches"]

_patched = False

_typeface_cache: dict[str, object] = {}
# value = (typeface 强引用, hb_font)：必须同时持有 typeface 引用，
# 否则对象被 GC 后 id 可能被新对象复用，导致命中陈旧缓存
_hb_font_cache: dict[tuple[int, float], tuple] = {}

_original_load_from_file = TypefaceLoader.load_from_file
_original_get_or_create_hb_font = HarfBuzzShaper._get_or_create_hb_font


def _cached_load_from_file(filepath: str):
    if filepath not in _typeface_cache:
        _typeface_cache[filepath] = _original_load_from_file(filepath)
    return _typeface_cache[filepath]


def _shared_get_or_create_hb_font(self, font):
    typeface = font.getTypeface()
    key = (id(typeface), font.getSize())
    entry = _hb_font_cache.get(key)
    if entry is None:
        entry = (typeface, _original_get_or_create_hb_font(self, font))
        _hb_font_cache[key] = entry
    return entry[1]


def apply_pictex_patches() -> None:
    """应用字体缓存补丁（幂等，重复调用无副作用）"""
    global _patched
    if _patched:
        return
    TypefaceLoader.load_from_file = staticmethod(_cached_load_from_file)
    HarfBuzzShaper._get_or_create_hb_font = _shared_get_or_create_hb_font
    _patched = True


apply_pictex_patches()