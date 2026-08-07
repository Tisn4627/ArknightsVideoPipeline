"""
sync_recognition_resources - 同步 Recognition 子模块资源到顶层 resource/

将 src/ArknightsVideoRecognition/resource 下的各资源条目（avatar/config/data/
ocr/onnx/template/tile 等）同步为顶层 resource/ 下的同名条目，与主项目资源
（font/locales/StartButton 等）同层共存（见 docs/merge_plan.md §8）。

支持两种模式（--mode 指定）：
  link（默认）：为每个条目创建目录符号链接 resource/<条目> -> src/ArknightsVideoRecognition/resource/<条目>
                零拷贝；子模块更新后自动生效。Windows 需开发者模式/管理员权限。
  copy：       递归复制每个条目到 resource/<条目>。跨平台无权限问题，
               适合打包与 CI 产物；子模块更新后需重新运行本脚本。

注意：目标为顶层 resource/（与主项目资源同层），因此按条目同步，
不会删除或覆盖 resource/ 下的 font/locales/StartButton 等主项目资源。

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
DEST_DIR = PROJECT_ROOT / "resource"


def _link_resources(force: bool) -> int:
    """为 SUBMODULE_RESOURCE 下每个条目创建 resource/<条目> 符号链接"""
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    linked = 0
    for entry in sorted(SUBMODULE_RESOURCE.iterdir()):
        target = SUBMODULE_RESOURCE / entry.name
        dest = DEST_DIR / entry.name
        if dest.is_symlink():
            if dest.resolve() == target:
                print(f"已存在: {dest} -> {target}")
                linked += 1
                continue
            if force:
                print(f"存在指向其他位置的链接 {dest} -> {dest.resolve()}，--force 移除后重建")
                dest.unlink()
            else:
                print(f"错误: {dest} 已是指向其他位置的符号链接: {dest.resolve()}（使用 --force 覆盖）")
                sys.exit(1)
        elif dest.exists():
            if force:
                print(f"存在非链接条目 {dest}，--force 移除后重建链接")
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            else:
                print(f"错误: {dest} 已存在且不是符号链接（使用 --force 覆盖，或改用 --mode=copy）")
                sys.exit(1)

        try:
            dest.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as exc:
            print(f"符号链接创建失败: {dest} -> {target}: {exc}")
            print("Windows 下需开启开发者模式或以管理员身份运行；")
            print("或改用复制模式: python script/sync_recognition_resources.py --mode=copy")
            sys.exit(1)
        linked += 1
        print(f"已链接: {dest} -> {target}")
    print(f"共链接 {linked} 个条目到 {DEST_DIR}")
    return linked


def _copy_resources(force: bool) -> int:
    """递归复制 SUBMODULE_RESOURCE 下每个条目到 resource/<条目>"""
    if not SUBMODULE_RESOURCE.is_dir():
        print(f"错误: 子模块资源目录不存在: {SUBMODULE_RESOURCE}")
        print("请确认已初始化子模块（git submodule update --init）后重试")
        sys.exit(1)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for entry in sorted(SUBMODULE_RESOURCE.iterdir()):
        dest = DEST_DIR / entry.name
        if dest.is_symlink():
            if not force:
                print(f"错误: {dest} 是符号链接（使用 --force 覆盖）")
                sys.exit(1)
            print(f"存在符号链接 {dest}，--force 移除后复制")
            dest.unlink()
        elif dest.exists():
            if not force:
                print(f"已存在: {dest}（使用 --force 重新复制）")
                continue
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()

        if entry.is_dir():
            shutil.copytree(entry, dest)
        else:
            shutil.copy2(entry, dest)
        copied += 1
        print(f"已复制: {entry} -> {dest}")

    n_files = 0
    for entry in sorted(SUBMODULE_RESOURCE.iterdir()):
        dest = DEST_DIR / entry.name
        if dest.is_dir():
            n_files += sum(1 for _ in dest.rglob("*") if _.is_file())
        elif dest.is_file():
            n_files += 1
    print(f"已复制 {copied} 个条目（共 {n_files} 个文件）到 {DEST_DIR}")
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(
        description="同步 Recognition 子模块资源到顶层 resource/"
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
