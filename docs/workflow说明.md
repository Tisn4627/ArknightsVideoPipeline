# GitHub Workflow 说明

本项目使用 GitHub Actions 自动同步 `resource/` 下的部分资源，确保地图数据、干员头像、战斗/OCR 配置等随上游更新而保持最新。

## Workflow 文件

| 文件 | 用途 |
| --- | --- |
| [.github/workflows/sync-resources.yml](../.github/workflows/sync-resources.yml) | 定期从上游仓库同步资源并提交 |

## sync-resources.yml

### 设计原则

**所有 resource 文件均保留在仓库中**（开箱即用，clone 后即可运行），但并非所有资源都通过 workflow 自动同步：

| 资源目录 | 是否在仓库中 | 是否 workflow 自动同步 | 说明 |
| --- | --- | --- | --- |
| `resource/tile/` | 是 | 是 | 地图数据（levels.json），文本文件，上游每日更新 |
| `resource/avatar/` | 是 | 是 | 干员头像库，新干员上线时需更新 |
| `resource/data/` | 是 | 是 | 战斗/OCR 配置 + 干员职业表，文本/JSON |
| `resource/config/` | 是 | 是 | ROI 配置（roi.json），从 tasks.json 提取 |
| `resource/template/` | 是 | 否 | 模板图片，体积大、二进制，更新频率低 |
| `resource/onnx/` | 是 | 否 | ONNX 模型，体积大、二进制，更新频率低 |
| `resource/ocr/` | 是 | 否 | PaddleOCR 模型，体积大、二进制，更新频率低 |

`template` / `onnx` / `ocr` 三类资源虽在仓库中，但不通过 workflow 自动同步，原因：
- 体积大（合计约 53M），频繁自动同步会产生大量二进制 diff
- 更新频率低（Maa 模型/模板不常变动）
- 由开发者在本地运行 `scripts/update_resources.py` 更新后手动提交

### 触发方式

- **定时**：每周一 08:00 UTC（北京时间 16:00）自动运行（`schedule.cron: '0 8 * * 1'`）
- **手动**：在 GitHub 仓库的 Actions 页面选择 "Sync Resources" → "Run workflow" 手动触发（`workflow_dispatch`）

### 执行流程

```
1. Checkout 本仓库
2. 安装 Python 3.11 + Pillow
3. 浅克隆上游 Maa 仓库（sparse checkout，仅取 resource 目录）
4. 浅克隆上游 ArknightsGameResource 仓库（提供 levels.json 与干员头像）
5. 运行 update_character_table.py（从 GitHub 下载 character_table.json → char_roles.json）
6. 运行 update_resources.py --regen-roi（同步 levels/battle_data/ocr_config/头像/roi.json）
7. git add 仅暂存 tile/avatar/data/config（排除 template/onnx/ocr）
8. 若有变更 → 提交并推送
```

### 同步的资源来源

| 资源 | 上游仓库 | 同步方式 |
| --- | --- | --- |
| `resource/tile/levels.json` | [yuanyan3060/ArknightsGameResource](https://github.com/yuanyan3060/ArknightsGameResource) | `update_resources.py` 从克隆仓库复制 |
| `resource/avatar/` | [yuanyan3060/ArknightsGameResource](https://github.com/yuanyan3060/ArknightsGameResource) | `update_resources.py` 的 `sync_avatars` |
| `resource/data/battle_data.json` | [MaaAssistantArknights/MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights) | `update_resources.py` 从克隆仓库复制 |
| `resource/data/ocr_config.json` | [MaaAssistantArknights/MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights) | `update_resources.py` 提取 CharsNameOcrReplace 规则 |
| `resource/data/character_table.json` | [Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData) | `update_character_table.py` 直接 HTTP 下载 |
| `resource/data/char_roles.json` | （由 character_table.json 提取） | `update_character_table.py` 提取 name→profession |
| `resource/config/roi.json` | [MaaAssistantArknights/MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights) | `update_resources.py --regen-roi` 从 tasks.json 提取 |

### 关键实现细节

1. **浅克隆加速**：Maa 仓库较大，使用 `--depth=1 --filter=blob:none --sparse` + `sparse-checkout set resource` 仅克隆 resource 目录，大幅减少下载量。

2. **选择性暂存**：`git add` 仅暂存 `resource/tile/ resource/avatar/ resource/data/ resource/config/`，确保 `template/onnx/ocr` 的本地变更（`update_resources.py` 会同步它们但）不会被 workflow 提交。

3. **无变更跳过**：通过 `git diff --cached --quiet` 检测是否有变更，无变更时跳过提交，避免空提交。

4. **提交信息**：格式为 `chore(resource): 自动同步上游资源 (YYYY-MM-DD)`，由 `github-actions[bot]` 提交。

### 权限要求

workflow 需要 `contents: write` 权限以推送提交到仓库。在仓库 Settings → Actions → General → Workflow permissions 中需设置为 "Read and write permissions"。

### 手动更新 template/onnx/ocr

这三类资源不通过 workflow 自动同步，需开发者手动更新：

```bash
# 1. 克隆 Maa 仓库到本地
git clone --depth=1 https://github.com/MaaAssistantArknights/MaaAssistantArknights.git /tmp/Maa

# 2. 运行同步脚本
python scripts/update_resources.py \
  --maa-dir /tmp/Maa \
  --resource-dir ./resource

# 3. 检查变更并手动提交
git add resource/template/ resource/onnx/ resource/ocr/
git commit -m "chore(resource): 手动更新 template/onnx/ocr 模型"
git push
```

## 本地资源同步

不依赖 GitHub Actions 也能在本地同步全部资源，详见 [资源来源.md](./资源来源.md) 的"资源更新流程"章节。
