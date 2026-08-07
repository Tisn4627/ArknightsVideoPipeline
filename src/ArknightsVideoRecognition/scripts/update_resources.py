#!/usr/bin/env python3
"""从本地 Arknights-Tile-Pos、Maa 与 ArknightsResources 仓库同步可更新资源到 resource/ 目录。

仅使用 Python 标准库，可独立运行，不依赖项目的 src 包。
（助战空模板缩放需 Pillow，仅在指定 --support-template 时按需导入。）

同步清单（与 resource 结构对应）：
  1. levels.json           Arknights-Tile-Pos          -> resource/tile/
  2. ONNX 模型             Maa/resource/onnx           -> resource/onnx/
  3. PaddleOCR 模型/字典    Maa/resource/PaddleOCR      -> resource/ocr/maa/{det,rec}/
  4. 战斗/OCR 配置 JSON     Maa/resource                -> resource/data/
  5. empty.png 与编队 OCR   Maa/resource/template       -> resource/template/
     小旗模板
  6. 干员头像 char_*/sp_char_* ArknightsResources/avatar -> resource/avatar/
  7. 助战空模板             --support-template(1080p)   -> resource/template/empty_support_operator.png
  8. CharsNameOcrReplace   Maa/resource/tasks/          -> resource/data/ocr_config.json
     规则                   tasks.json                   (ocrReplace / replace_full)
     (ocrReplace / fullMatch)

注意：resource/config/roi.json 是项目自有产物（从 tasks.json 提取的视频识别相关任务），
本脚本的常规同步不会覆盖它。如需重新生成，请使用 --regen-roi 标志。
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

# 视频识别相关任务名。roi.json 即由这些任务从 Maa 的 tasks.json 提取而来，
# 保留每个任务的完整定义（含 roi / template / baseTask / rectMove 等字段）。
VIDEO_RECOGNITION_TASK_NAMES = [
    "BattleDeployDirectionRectMove",
    "BattleOperBoxRectMove",
    "BattleOperDetailPageOldFlag",
    "BattleOperDetailPageFlag",
    "BattleDroneAvatarData",
    "BattleAvatarCoolingData",
    "BattleAvatarDataForFormation",
    "BattleAvatarDataForVideo",
    "BattleAvatarData",
    "BattleFormationOCRNameFlag",
    "BattleFormationOperNamesOldVersion",
    "BattleFormationOperNames",
    "CharsNameOcrReplace",
    "BattleSwipeOper",
    "BattleUseOper",
    "BattleSkillReady",
    "BattleOperName",
    "NumberOcrReplace",
    "BattleCostData",
    "BattleKillsFlag",
    "BattleKills",
    "BattleStageName",
]


def format_size(num_bytes):
    """将字节数格式化为人类可读字符串。"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def build_sync_plan(tilepos_dir, maa_dir):
    """构建同步清单：返回 (源文件, 相对目标目录) 列表，目标保留源文件名。"""
    tilepos_dir = Path(tilepos_dir)
    maa_dir = Path(maa_dir)
    maa_res = maa_dir / "resource"
    return [
        # 1. 标准地图数据
        (tilepos_dir / "levels.json", "tile"),
        # 2. ONNX 模型
        (maa_res / "onnx" / "skill_ready_cls.onnx", "onnx"),
        (maa_res / "onnx" / "deploy_direction_cls.onnx", "onnx"),
        (maa_res / "onnx" / "operators_det.onnx", "onnx"),
        # 3. PaddleOCR det/rec
        (maa_res / "PaddleOCR" / "det" / "inference.onnx", "ocr/maa/det"),
        (maa_res / "PaddleOCR" / "det" / "version.txt", "ocr/maa/det"),
        (maa_res / "PaddleOCR" / "rec" / "inference.onnx", "ocr/maa/rec"),
        (maa_res / "PaddleOCR" / "rec" / "keys.txt", "ocr/maa/rec"),
        (maa_res / "PaddleOCR" / "rec" / "version.txt", "ocr/maa/rec"),
        # 4. 战斗/OCR 配置 JSON
        (maa_res / "battle_data.json", "data"),
        (maa_res / "ocr_config.json", "data"),
        # 5. 模板：仅同步 empty.png 与编队 OCR 小旗模板，不复制其它模板
        (maa_res / "template" / "empty.png", "template"),
        (maa_res / "template" / "Battle" / "Formation" / "BattleFormationOCRNameFlag.png", "template"),
    ]


def sync_file(src, dest_dir, dry_run):
    """同步单个文件到目标目录（保留文件名）。

    返回 (ok, message)：ok=True 表示已处理（含 dry-run），ok=False 表示源缺失已跳过。
    """
    src = Path(src)
    dest_dir = Path(dest_dir)
    dest = dest_dir / src.name
    if not src.is_file():
        return False, f"✗ 源文件不存在，跳过: {src}"
    size = src.stat().st_size
    if dry_run:
        return True, f"✓ [dry-run] {src} -> {dest} ({format_size(size)})"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)  # copy2 保留时间戳
    return True, f"✓ {src} -> {dest} ({format_size(size)})"


def regen_roi(tasks_json_path, roi_json_path, dry_run):
    """从 tasks.json 重新提取视频识别相关任务，写入 roi.json。"""
    tasks_json_path = Path(tasks_json_path)
    roi_json_path = Path(roi_json_path)
    if not tasks_json_path.is_file():
        print(f"✗ 无法重新生成 roi.json：未找到 {tasks_json_path}")
        return False
    with open(tasks_json_path, encoding="utf-8") as f:
        tasks = json.load(f)
    roi = {}
    missing = []
    for name in VIDEO_RECOGNITION_TASK_NAMES:
        if name in tasks:
            roi[name] = tasks[name]
        else:
            missing.append(name)
    if missing:
        print(f"⚠ tasks.json 中缺少以下任务定义: {missing}")
    if dry_run:
        print(f"✓ [dry-run] 将重新生成 {roi_json_path}（共 {len(roi)} 个任务）")
        return True
    roi_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(roi_json_path, "w", encoding="utf-8") as f:
        json.dump(roi, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"✓ 已重新生成 {roi_json_path}（共 {len(roi)} 个任务）")
    return True


def sync_ocr_replace(tasks_json_path, ocr_config_path, dry_run):
    """从 tasks.json 的 CharsNameOcrReplace 任务提取 ocrReplace / fullMatch，
    更新到 ocr_config.json 的 ocrReplace / replace_full 字段，保留其它字段
    （如 equivalence_classes）。

    返回 True 表示已处理（含 dry-run），False 表示源缺失已跳过。
    """
    tasks_json_path = Path(tasks_json_path)
    ocr_config_path = Path(ocr_config_path)
    if not tasks_json_path.is_file():
        print(f"✗ 未找到 {tasks_json_path}，跳过 CharsNameOcrReplace 同步")
        return False
    with open(tasks_json_path, encoding="utf-8") as f:
        tasks = json.load(f)
    task = tasks.get("CharsNameOcrReplace")
    if not task or "ocrReplace" not in task:
        print("✗ tasks.json 中未找到 CharsNameOcrReplace.ocrReplace，跳过")
        return False
    new_ocr_replace = task["ocrReplace"]
    new_replace_full = bool(task.get("fullMatch", False))
    rule_count = len(new_ocr_replace)
    if dry_run:
        print(
            f"✓ [dry-run] 将更新 {ocr_config_path}：ocrReplace（{rule_count} 条规则），"
            f"replace_full={new_replace_full}（保留其它字段）"
        )
        return True
    # 读取现有 ocr_config.json，保留其它字段（如 equivalence_classes）
    if ocr_config_path.is_file():
        with open(ocr_config_path, encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}
    config["ocrReplace"] = new_ocr_replace
    config["replace_full"] = new_replace_full
    ocr_config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ocr_config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(
        f"✓ 已更新 {ocr_config_path}：ocrReplace（{rule_count} 条规则），"
        f"replace_full={new_replace_full}（其它字段保留）"
    )
    return True


def sync_avatars(src_dir, dst_dir, dry_run=False):
    """从 ArknightsResources 仓库同步干员头像到 resource/avatar/。

    只同步 char_*.png 与 sp_char_*.png，跳过 npc_*/token_*/trap_*/enemy_*/bavg_*/avg_*
    等非干员文件。同步策略：源文件 mtime 更新或目标不存在时拷贝；不主动删除目标中多余文件。

    返回同步文件数。
    """
    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)
    if not src_dir.is_dir():
        print(f"✗ 头像源目录不存在，跳过: {src_dir}")
        return 0

    # 仅匹配干员头像，排除 npc_/token_/trap_/enemy_/bavg_/avg_ 等非干员文件
    candidates = []
    for pattern in ("char_*.png", "sp_char_*.png"):
        candidates.extend(sorted(src_dir.glob(pattern)))

    synced = 0
    up_to_date = 0
    for src in candidates:
        dst = dst_dir / src.name
        # 源文件 mtime 不更新且目标已存在时跳过
        if dst.exists() and src.stat().st_mtime <= dst.stat().st_mtime:
            up_to_date += 1
            continue
        action = "新增" if not dst.exists() else "更新"
        size = src.stat().st_size
        if dry_run:
            print(f"✓ [dry-run] {action} {src.name} -> {dst} ({format_size(size)})")
        else:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"✓ {action} {src.name} -> {dst} ({format_size(size)})")
        synced += 1

    print(f"头像同步: 同步 {synced} 个, 已最新 {up_to_date} 个, 共扫描 {len(candidates)} 个候选")
    return synced


def sync_support_template(src_path, dst_path, dry_run=False):
    """将 1080p 助战空模板缩放至 720p 并写入目标路径。

    使用 PIL.Image.LANCZOS 按 720/1080=2/3 比例缩放。返回是否执行
    （True=已处理含 dry-run，False=跳过）。
    """
    src_path = Path(src_path)
    dst_path = Path(dst_path)
    if not src_path.is_file():
        print(f"✗ 助战空模板源文件不存在，跳过: {src_path}")
        return False
    if dry_run:
        print(f"✓ [dry-run] 将缩放并写入 {src_path} -> {dst_path}（1080p -> 720p, LANCZOS）")
        return True
    # 懒加载 Pillow，避免对标准库运行环境造成硬依赖
    try:
        from PIL import Image
    except ImportError:
        print("✗ 缺少 Pillow 依赖，无法缩放助战空模板。请 pip install Pillow")
        return False
    with Image.open(src_path) as img:
        src_w, src_h = img.size
        new_w = round(src_w * 2 / 3)
        new_h = round(src_h * 2 / 3)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        resized.save(dst_path)
    print(f"✓ 助战空模板已缩放并写入: {src_path} -> {dst_path} ({src_w}x{src_h} -> {new_w}x{new_h})")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="从本地 Arknights-Tile-Pos、Maa 与 ArknightsResources 仓库同步可更新资源到 resource/ 目录。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将做什么，不实际复制")
    parser.add_argument(
        "--resource-dir", default="/workspace/resource", help="目标 resource 根目录"
    )
    parser.add_argument(
        "--tilepos-dir", default="/Arknights-Tile-Pos", help="Arknights-Tile-Pos 仓库根目录"
    )
    parser.add_argument("--maa-dir", default="/Maa", help="Maa 仓库根目录")
    parser.add_argument(
        "--arknights-resources-dir",
        default="/ArknightsResources",
        help="ArknightsResources 仓库根目录（干员头像来源）",
    )
    parser.add_argument(
        "--regen-roi",
        action="store_true",
        help="从 tasks.json 重新提取 roi.json（视频识别相关任务）。常规同步不会覆盖 roi.json。",
    )
    parser.add_argument(
        "--support-template",
        default=None,
        help="1080p 助战空模板源图片路径；指定后将缩放至 720p 写入 "
        "resource/template/empty_support_operator.png",
    )
    args = parser.parse_args()

    resource_dir = Path(args.resource_dir)
    tilepos_dir = Path(args.tilepos_dir)
    maa_dir = Path(args.maa_dir)
    arknights_resources_dir = Path(args.arknights_resources_dir)

    # 检查上游仓库存在性
    if not tilepos_dir.is_dir():
        print(
            f"未找到 {tilepos_dir}，请先 git clone "
            f"https://github.com/yuanyan3060/Arknights-Tile-Pos"
        )
        sys.exit(1)
    if not maa_dir.is_dir():
        print(
            f"未找到 {maa_dir}，请先 git clone "
            f"https://github.com/MaaAssistantArknights/MaaAssistantArknights"
        )
        sys.exit(1)

    mode = "（dry-run，不实际复制）" if args.dry_run else ""
    print(f"=== 开始同步资源{mode} ===")
    print(f"resource 目录: {resource_dir}")
    print(f"TilePos 仓库:   {tilepos_dir}")
    print(f"Maa 仓库:       {maa_dir}")
    print(f"ArknightsResources: {arknights_resources_dir}")
    print()

    plan = build_sync_plan(tilepos_dir, maa_dir)
    success_count = 0
    fail_count = 0
    for src, rel_dest_dir in plan:
        dest_dir = resource_dir / rel_dest_dir
        ok, message = sync_file(src, dest_dir, args.dry_run)
        print(message)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    print()
    print(f"=== 同步完成: ✓ {success_count} 项, ✗ {fail_count} 项 ===")

    # 6. 干员头像同步（助战干员识别）
    print()
    print("--- 干员头像同步 ---")
    if not arknights_resources_dir.is_dir():
        print(
            f"未找到 {arknights_resources_dir}，请先 git clone "
            f"https://github.com/yuanyan3060/ArknightsGameResource，跳过头像同步"
        )
    else:
        avatar_src = arknights_resources_dir / "avatar"
        avatar_dst = resource_dir / "avatar"
        sync_avatars(avatar_src, avatar_dst, dry_run=args.dry_run)

    # 7. 助战空模板同步（可选，仅当 --support-template 指定时执行）
    print()
    print("--- 助战空模板同步 ---")
    if args.support_template:
        support_dst = resource_dir / "template" / "empty_support_operator.png"
        sync_support_template(args.support_template, support_dst, dry_run=args.dry_run)
    else:
        print("ℹ 未指定 --support-template，跳过助战空模板同步")

    # 8. CharsNameOcrReplace 规则同步（从 tasks.json 提取 ocrReplace / fullMatch
    #    到 ocr_config.json 的 ocrReplace / replace_full，保留其它字段）
    print()
    print("--- CharsNameOcrReplace 规则同步 ---")
    tasks_json = maa_dir / "resource" / "tasks" / "tasks.json"
    ocr_config = resource_dir / "data" / "ocr_config.json"
    sync_ocr_replace(tasks_json, ocr_config, args.dry_run)

    # 处理 roi.json：常规同步不覆盖；--regen-roi 时重新生成
    roi_json = resource_dir / "config" / "roi.json"
    if args.regen_roi:
        print()
        regen_roi(tasks_json, roi_json, args.dry_run)
    elif roi_json.exists():
        print(
            f"ℹ 已保留 {roi_json}（项目自有产物，未被覆盖；如需重新生成请使用 --regen-roi）"
        )

    # 同步后提示
    print()
    print("--- 提示 ---")
    print(
        f"若需获取最新 levels.json，请先 `git -C {tilepos_dir} pull`"
        f"（该仓库会同步上游 Arknights-Bot-Resource），再运行本脚本。"
    )
    print(
        f"ONNX/OCR/干员数据来自 {maa_dir}，可 `git -C {maa_dir} pull` 后再运行本脚本同步。"
    )
    print(
        f"干员头像来自 {arknights_resources_dir}，可 `git -C {arknights_resources_dir} pull` 后再运行本脚本同步。"
    )

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
