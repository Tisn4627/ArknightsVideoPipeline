# ArknightsVideoRecognition

把 Maa（明日方舟助手）的"视频转标准作业 JSON"功能用 Python 重写。接受一段明日方舟战斗录像视频作为输入，识别其中的编队、关卡与战斗操作（部署 / 技能 / 撒退等），输出符合 Maa copilot schema 的作业 JSON，可直接导入 Maa 用于自动战斗（copilot 模式）。

## 特性

- **视频转作业**：从战斗录像自动识别编队、关卡、部署/技能/撒退动作，输出 Maa copilot JSON
- **对齐 Maa 原版**：核心识别逻辑（编队 OCR、战斗切片、动作推断、方向分类）严格对齐 Maa C++ 实现
- **双 OCR 模型源**：支持 Maa 方舟 finetune PaddleOCR 模型（高精度）与 RapidOCR 默认模型（通用）切换
- **标准地图数据**：采用社区标准 Arknights-Tile-Pos 形式（`levels.json` + 3D 投影矩阵），支持 940+ 关卡
- **资源开箱即用**：`resource/` 全部纳入版本控制，clone 后无需额外下载即可运行

## 快速开始

### 安装

```bash
git clone <repo-url>
cd ArknightsVideoRecognition
pip install -e .
```

依赖：Python >= 3.9、numpy、opencv-python、onnxruntime、rapidocr-onnxruntime、pillow（pip 安装时自动拉取）。

### 使用

```bash
# 基本用法：视频转作业 JSON
python -m arknights_video_recognition battle.mp4 -o out.json

# 手动指定关卡 + 指定 OCR 模型源
python -m arknights_video_recognition battle.mp4 --stage 2-10 --ocr maamodel -o out.json

# 指定视频分辨率（默认 1280x720）
python -m arknights_video_recognition battle.mp4 --resolution 1920x1080 -o out.json

# 输出带视频时间戳的扩展字段
python -m arknights_video_recognition battle.mp4 --with-video-time -o out.json
```

安装后也可直接使用入口命令：

```bash
arknights-video-recognition battle.mp4 --output out.json
```

### CLI 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `video`（位置参数） | — | 输入的战斗录像视频路径 |
| `--ocr` | `maamodel` | OCR 模型源：`maamodel`（方舟 finetune，高精度）/ `default`（RapidOCR 自带） |
| `-o` / `--output` | 自动命名 | 输出 JSON 路径，不指定则存到 `cache/MaaAI_{stage}_{video}_{time}.json` |
| `--stage` | 自动 OCR 识别 | 手动指定关卡，支持 code / name / stageId（如 `2-10`） |
| `--resolution` | `1280x720` | 视频归一化分辨率，形如 `WxH` |
| `--with-video-time` | 关闭 | 在 actions 中输出 `video_time`（视频内时间戳，秒） |

退出码：`0` 成功 / `1` 资源缺失或异常 / `2` 关卡未识别（打印候选关卡）。

### 输出示例

```json
{
  "minimum_required": "v4.0.0",
  "stage_name": "main_02-10",
  "opers": [{"name": "德克萨斯", "skill": 0}],
  "groups": [],
  "actions": [
    {"type": "SpeedUp"},
    {"type": "Deploy", "name": "德克萨斯", "location": [5, 3], "direction": "Right"},
    {"type": "Skill", "name": "德克萨斯", "location": [5, 3]},
    {"type": "SkillDaemon"}
  ],
  "doc": {"title": "MAA AI - main_02-10", "details": ""}
}
```

将 JSON 导入 Maa 客户端的"自动战斗（copilot 模式）"即可使用。

> **与原 Maa 的差异**：本项目以视频中的时间点作为 actions 的时间点，不输出 `kills` / `costs` / `cost_changes` 触发条件。如需时间定位，使用 `--with-video-time` 输出 `video_time` 字段。

## 项目结构

```text
ArknightsVideoRecognition/
├── pyproject.toml                      # 项目元信息与依赖
├── .github/workflows/sync-resources.yml # 资源自动同步 workflow
├── scripts/                            # 资源同步脚本
├── resource/                           # 内置资源（约 214M，开箱即用）
│   ├── tile/levels.json                # 地图数据（940+ 关卡）
│   ├── avatar/                         # 干员头像库
│   ├── onnx/                           # 战斗识别 ONNX 模型
│   ├── ocr/maa/                        # Maa finetune OCR 模型
│   ├── data/                           # 战斗/OCR 配置 + 干员职业表
│   ├── template/                       # 模板图片
│   └── config/roi.json                 # ROI 任务定义
├── src/arknights_video_recognition/
│   ├── cli.py                          # 命令行入口
│   ├── pipeline.py                     # 主流水线
│   ├── video/                          # 抽帧、切片
│   ├── formation/                      # 编队识别
│   ├── stage/                          # 关卡名识别
│   ├── tile/                           # 地图加载与投影
│   ├── battle/                         # 战场分析（检测/分类/动作推断）
│   ├── ocr/                            # OCR 引擎封装
│   ├── copilot/                        # 作业 JSON 组装
│   └── config/                         # 路径与 ROI 配置
└── doc/                                # 文档
```

## 处理流程

```text
战斗录像视频
   │
   ▼
VideoFrames（按 resolution 归一化抽帧）
   │
   ├──► FormationAnalyzer（编队页 OCR + 头像截取）──► 干员列表
   └──► StageRecognizer（关卡名 OCR → stageId 查表）──► 关卡数据
   │
   ▼
VideoSlicer（按部署栏变化切片为 Clip 序列）
   │
   ▼
BattleAnalyzer（逐片段：干员检测 → 分类 → 头像匹配 → 动作推断）
   │
   ▼
CopilotJob（组装 opers + SpeedUp + actions + SkillDaemon）
   │
   ▼
Maa copilot 作业 JSON
```

各子模块职责单一、可独立测试，`pipeline.py` 只做串联与转换。

## 文档

- [快速使用](./doc/快速使用.md) — 安装、CLI 参数、输出格式、FAQ
- [开发指南](./doc/开发指南.md) — 架构、目录布局、模块职责、扩展点
- [资源来源](./doc/资源来源.md) — 各资源文件的来源仓库、许可证与更新方式
- [GitHub Workflow 说明](./doc/workflow说明.md) — 资源自动同步 workflow 的设计与用法

## 资源同步

`resource/` 下所有文件均纳入版本控制，开箱即用。其中 `tile` / `avatar` / `data` / `config` 由 GitHub Actions workflow 每周自动从上游仓库同步；`template` / `onnx` / `ocr` 已在仓库中但不自动同步，由开发者手动更新。

手动更新资源：

```bash
# 同步全部资源（需本地克隆 Maa 与 ArknightsGameResource 仓库）
python scripts/update_resources.py

# 仅更新地图数据（直接从 GitHub 下载，无需本地仓库）
python scripts/update_levels.py

# 仅更新干员职业表（直接从 GitHub 下载）
python scripts/update_character_table.py
```

详见 [资源来源.md](./doc/资源来源.md) 与 [GitHub Workflow 说明](./doc/workflow说明.md)。

## 测试

```bash
# 运行单元测试（默认跳过慢测试）
pytest

# 运行全部测试（含真实视频流水线测试）
pytest -m slow
```

## 致谢

本项目复用以下上游仓库的资源：

- [MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights) — ONNX 模型、OCR 模型、战斗/OCR 配置、模板（AGPL-3.0）
- [ArknightsGameResource](https://github.com/yuanyan3060/ArknightsGameResource) — 地图数据、干员头像
- [ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData) — 干员职业表

核心识别逻辑移植自 Maa 的 `CombatRecordRecognitionTask` C++ 实现。

## 许可证

本项目代码遵循其声明的许可证。`resource/` 下的资源分别遵循各自上游仓库的许可证（Maa 资源为 AGPL-3.0）。
