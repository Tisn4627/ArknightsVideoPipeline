"""
sync_recognition_resources - 同步 Recognition 子模块资源到顶层 resource/

将 src/ArknightsVideoRecognition/resource 同步为顶层 resource/recognition
（运行时唯一读取入口，见 docs/merge_plan.md §8）。

支持两种模式（--mode 指定）：
  link（默认）：创建目录符号链接 resource/recognition -> src/ArknightsVideoRecognition/resource
                零拷贝；子模块更新后自动生效。Windows 需开发者模式/管理员权限。
  copy：       递归复制资源到 resource/recognition/。跨平台无权限问题，
                适合打包与 CI 产物；子模块更新后需重新运行本脚本。

用法:
  python script/sync_recognition_resources.py --mode=link
  python script/sync_recognition_resources.py --mode=copy --force
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUBMODULE_RESOURCE = PROJECT_ROOT / "src" / "ArknightsVideoRecognition" / "resource"
DEST_DIR = PROJECT_ROOT / "resource" / "recognition"


def _link_resources(force: bool) -> Path:
    """创建符号链接 DEST_DIR -> SUBMODULE_RESOURCE"""
    if DEST_DIR.is_symlink():
        target = DEST_DIR.resolve()
        if target == SUBMODULE_RESOURCE:
            print(f"已存在: {DEST_DIR} -> {SUBMODULE_RESOURCE}")
            return DEST_DIR
        if force:
            print(f"存在指向其他位置的链接 {DEST_DIR} -> {target}，--force 移除后重建")
            DEST_DIR.unlink()
        else:
            print(f"错误: {DEST_DIR} 已是指向其他位置的符号链接: {target}（使用 --force 覆盖）")
            sys.exit(1)
    elif DEST_DIR.exists():
        if force:
            print(f"存在非链接目录 {DEST_DIR}，--force 移除后重建链接")
            shutil.rmtree(DEST_DIR)
        else:
            print(f"错误: {DEST_DIR} 已存在且不是符号链接（使用 --force 覆盖，或改用 --mode=copy）")
            sys.exit(1)

    DEST_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        DEST_DIR.symlink_to(SUBMODULE_RESOURCE, target_is_directory=True)
    except OSError as exc:
        print(f"符号链接创建失败: {exc}")
        print("Windows 下需开启开发者模式或以管理员身份运行；")
        print("或改用复制模式: python script/sync_recognition_resources.py --mode=copy")
        sys.exit(1)
    print(f"已链接: {DEST_DIR} -> {SUBMODULE_RESOURCE}")
    return DEST_DIR


def _copy_resources(force: bool) -> Path:
    """递归复制 SUBMODULE_RESOURCE -> DEST_DIR"""
    if not SUBMODULE_RESOURCE.is_dir():
        print(f"错误: 子模块资源目录不存在: {SUBMODULE_RESOURCE}")
        print("请确认已初始化子模块（git submodule update --init）后重试")
        sys.exit(1)

    if DEST_DIR.is_symlink():
        if force:
            print(f"存在符号链接 {DEST_DIR}，--force 移除后复制")
            DEST_DIR.unlink()
        else:
            print(f"错误: {DEST_DIR} 是符号链接（使用 --force 覆盖）")
            sys.exit(1)
    elif DEST_DIR.exists() and not force:
        print(f"已存在: {DEST_DIR}（使用 --force 重新复制）")
        return DEST_DIR

    if DEST_DIR.exists():
        shutil.rmtree(DEST_DIR)
    DEST_DIR.parent.mkdir(parents=True, exist_ok=True)
    print(f"复制中: {SUBMODULE_RESOURCE} -> {DEST_DIR}")
    shutil.copytree(SUBMODULE_RESOURCE, DEST_DIR)
    n_files = sum(1 for _ in DEST_DIR.rglob("*") if _.is_file())
    print(f"已复制 {n_files} 个文件到 {DEST_DIR}")
    return DEST_DIR


def main() -> None:
    parser = argparse.ArgumentParser(
        description="同步 Recognition 子模块资源到顶层 resource/recognition"
    )
    parser.add_argument(
        "--mode",
        choices=["link", "copy"],
        default="link",
        help="同步方式: link=符号链接（默认，零拷贝）；copy=递归复制",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="目标已存在（非预期类型）时强制覆盖",
    )
    args = parser.parse_args()

    if not SUBMODULE_RESOURCE.is_dir():
        print(f"错误: 子模块资源目录不存在: {SUBMODULE_RESOURCE}")
        print("请先初始化子模块: git submodule update --init --recursive")
        sys.exit(1)

    if args.mode == "link":
        _link_resources(args.force)
    else:
        _copy_resources(args.force)


if __name__ == "__main__":
    main()
