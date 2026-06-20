# 快速入门

本指南帮助你快速使用 ArknightsVideoPipeline。

## 第一步：环境准备

### 1.1 确认 Python 版本

```bash
python --version
# 需要 Python 3.12 或更高版本
```
若未安装 Python 3.12 或更高版本，可参考 [Python 官方文档](https://www.python.org/downloads/) 安装。

### 1.2 确认 ffmpeg 已安装

```bash
ffmpeg -version
ffprobe -version
```

若未安装，可使用以下方法安装：

在Windows上使用 Winget 安装：

```bash
winget install ffmpeg
```

在macOS上使用 Homebrew 安装：

```bash
brew install ffmpeg
```

在Linux上使用 apt 安装：

```bash
sudo apt install ffmpeg
```
注意：若无法使用上述方法安装ffmpeg，请善用搜索引擎和LLM工具，这里不给出解决方案。

### 1.3 创建虚拟环境

```bash
cd ArknightsVideoPipeline
python -m venv venv
#下列命令是激活虚拟环境的命令，按照自己的操作系统选择执行
venv\Scripts\activate        # Windows
source venv/bin/activate   # Linux/macOS
```

### 1.4 安装 Python 依赖

```bash
pip install -r requirements.txt
```

## 第二步：项目初始化

### 2.1 生成默认配置文件

```bash
# 生成全部默认配置文件
python main.py --init-config

# 也可按模块单独生成
python main.py --init-config pipeline
python main.py --init-config formation
```

执行后会在 `config/` 目录下生成以下配置文件：

```
config/
├── pipeline.json          # 全局流水线配置
├── formation.json         # 编队转文本配置
├── actions.json           # 操作转文本配置
├── track.json             # 开始按钮识别配置
└── video_compose/         # 视频合成风格配置
    ├── style1.json        # style1 风格（默认，底板+视频叠加）
    └── style2.json        # style2 风格（全屏视频+底部字幕）
```

### 2.2 配置 MAA 路径（必需）

`maa_path` 是 MAA 识别引擎的安装路径，**必须手动配置**，默认值为空。未配置时流水线的视频转 JSON 步骤将无法执行。

#### 配置步骤

1. 找到 MAA 的安装目录（包含`MAA.exe` 的文件夹）
2. 打开 `config/pipeline.json`，将 `maa_path` 设置为该目录路径

#### 路径格式要求

- 支持**相对路径**（基于项目根目录）或**绝对路径**
- Windows 路径中使用 `/` 或 `\\` 作为分隔符
- 路径必须指向一个**有效的文件夹**，不能是文件

#### 配置示例

```json
{
    "maa_path": "MaaAssistantArknights"
}
```

```json
{
    "maa_path": "C:/Program Files/MAA"
}
```

也可通过 CLI 参数临时覆盖，无需修改配置文件：

```bash
python main.py video.mp4 -b bg.png --maa-path C:/path/to/MAA
```

注意：高版本的MaaAssistantArknights可能会报错，建议使用5.12.1版本。
## 第三步：准备素材

你需要准备以下文件：

| 素材 | 格式要求 | 说明 |大小要求| 适用风格 |
|------|----------|------|----------|----------|
| 视频文件 | `.mp4`, `.avi`, `.mkv`, `.mov`, `.flv`, `.wmv` | 明日方舟游戏录像 |1080p, 30fps| style1, style2 |
| 背景板图片 | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp` | 视频叠加的底板图片 |1920x1080| 仅 style1 |

将文件放置在项目目录下（或记住其完整路径）。

> **提示**：style2（全屏视频+底部字幕模式）不需要背景板图片，视频会直接铺满画面。

## 第四步：运行流水线

### 4.1 激活虚拟环境
每次执行前都需激活虚拟环境，否则会报错。
```bash
venv\Scripts\activate        # Windows
source venv/bin/activate   # Linux/macOS
```

### 4.2 验证输入（Dry-run）

先不执行实际处理，仅验证输入文件和配置是否正确：

```bash
# style1（需要背景板图片）
python main.py video.mp4 --background-image bg.png --dry-run

# style2（无需背景板图片）
python main.py video.mp4 --style style2 --dry-run
```

预期输出：

```
[INFO] 验证视频文件: video.mp4
[INFO] 视频信息: 1920x1080, 时长120.50s
[INFO] 验证背景板图片: bg.png
[INFO] 背景板图片信息: 1920x1080
[INFO] Dry-run模式：输入验证通过
[INFO] 视频: video.mp4
[INFO] 背景板图片: bg.png
[INFO] 输出目录: output\video
[INFO] MAA路径: MAA-v5.12.1-win-x64
```

### 4.3 执行完整流水线

```bash
# style1（底板图片+视频叠加）
python main.py video.mp4 --background-image bg.png

# style2（全屏视频+底部字幕）
python main.py video.mp4 --style style2
```

流水线将依次执行 5 个步骤：

```
============================================================
  步骤 1/5: 视频转MAA作业JSON
============================================================
[INFO] 输入视频: video.mp4
[INFO] MAA识别尝试 1/2
...

============================================================
  步骤 2/5: 编队配置转文本
============================================================
...

============================================================
  步骤 3/5: 操作指令转文本
============================================================
...

============================================================
  步骤 4/5: 识别开始按钮时间戳
============================================================
...

============================================================
  步骤 5/5: 视频合成
============================================================
...
```

### 4.4 查看输出

处理完成后，输出文件位于 `output/<video_name>/` 目录：

```
output/video/
├── pipeline.log              # 流水线日志
├── maa_copilot_video.json    # MAA 识别结果 JSON
├── formation_video.txt       # 编队文本
├── actions_video.txt         # 操作文本
├── track_result_video.json   # 开始按钮识别结果
└── output_video.mp4          # 最终合成视频
```
### 注意事项
- 确保 MAA 路径配置正确，否则会报错。
- 在运行流水线前，先打开一遍MaaAssistantArknights更新资源文件，确保识别正确。
- 流水线会自动创建输出目录，无需手动创建。
## 第五步：常用操作示例

### 仅生成 MAA JSON（跳过后续步骤）

```bash
python main.py video.mp4 -b bg.png --skip-step formation --skip-step actions --skip-step track --skip-step compose
```

### 调整日志级别

```bash
python main.py video.mp4 -b bg.png --log-level DEBUG
```

### 指定输出目录

```bash
python main.py video.mp4 -b bg.png --output-dir my_output
```

### 仅运行视频合成（需要已有中间文件）

```bash
# style1
python main.py video.mp4 -b bg.png --skip-step copilot --skip-step formation --skip-step actions --skip-step track

# style2
python main.py video.mp4 --style style2 --skip-step copilot --skip-step formation --skip-step actions --skip-step track
```

### 启用字幕自适应（style1）

在 `config/video_compose/style1.json` 中将 `subtitle_auto_fit` 设为 `true`，系统将根据视频尺寸自动计算最大字体大小：

```json
{
    "text_overlay": {
        "subtitle_auto_fit": true,
        "auto_fit_min_font_size": 15,
        "auto_fit_max_font_size": 150
    }
}
```

> **注意**：启用字幕自适应后，`font_size` 和 `font_scale` 配置将被自动覆盖。如需手动指定字幕可用宽度，可设置 `auto_fit_available_width`（设为 `null` 则自动推断）。

## 常见问题

### Q: 提示 "ffprobe未找到"

确保 ffmpeg 已安装并在 PATH 中。Windows 用户可尝试重启终端或手动添加 PATH。

### Q: 提示 "请提供背景板图片文件路径"

背景板图片在使用 style1 时是必填项，请使用 `--background-image` 或 `-b` 参数指定：

```bash
python main.py video.mp4 -b bg.png
```

如果使用 style2，则不需要背景板图片：

```bash
python main.py video.mp4 --style style2
```

### Q: MAA 识别超时

可在 `config/pipeline.json` 中调整超时时间和重试次数：

```json
{
    "maa_timeout_seconds": 1200,
    "maa_max_retries": 3
}
```

### Q: 开始按钮识别未检测到

检查 `resource/StartButton/` 目录下是否有对应的模板图片，并确认 `config/track.json` 中的 `match_threshold` 设置是否过高（默认 0.75）。

## 其他信息

- 阅读 [配置文件说明文档](configuration.md) 了解所有可配置项
- 阅读 [CLI 参数说明文档](cli_reference.md) 了解完整的命令行参数
