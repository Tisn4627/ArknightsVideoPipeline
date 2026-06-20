# CLI 参数说明

本文档为 `main.py` 命令行接口的完整参考手册。

## 基本语法

```bash
# style1（需要背景板图片）
python main.py <video> --background-image <image> [选项]

# style2（无需背景板图片）
python main.py <video> --style style2 [选项]
```

## 位置参数

### `video`

| 属性 | 值 |
|------|-----|
| 类型 | 文件路径 |
| 必填 | 是（除非使用 `--init-config`） |
| 默认值 | 无 |
| 支持格式 | `.mp4`, `.avi`, `.mkv`, `.mov`, `.flv`, `.wmv` |

输入视频文件路径，支持相对路径和绝对路径。

```bash
python main.py video.mp4 -b bg.png
python main.py C:/Videos/game.mp4 -b bg.png
```

---

## 条件必选选项

### `--background-image`, `-b`

| 属性 | 值 |
|------|-----|
| 类型 | 文件路径 |
| 必填 | style1 必填，style2 可选 |
| 默认值 | 无 |
| 支持格式 | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp` |

背景板图片文件路径。使用 style1（默认风格）时必须提供，缺失时将显示错误提示并退出。使用 style2 时不需要背景板图片，因为视频会直接铺满画面。

```bash
# style1（需要背景板图片）
python main.py video.mp4 --background-image bg.png
python main.py video.mp4 -b C:/Images/background.jpg

# style2（不需要背景板图片）
python main.py video.mp4 --style style2
```

---

## 可选选项

### `--output-dir`, `-o`

| 属性 | 值 |
|------|-----|
| 类型 | 目录路径 |
| 必填 | 否 |
| 默认值 | `output/<video_name>/` |

指定输出目录，覆盖 `pipeline.json` 中的 `output_dir` 设置。

```bash
python main.py video.mp4 -b bg.png --output-dir results
python main.py video.mp4 -b bg.png -o C:/Output
```

### `--maa-path`

| 属性 | 值 |
|------|-----|
| 类型 | 目录路径 |
| 必填 | 否 |
| 默认值 | 使用 `pipeline.json` 中的 `maa_path` |

指定 MAA 项目路径，优先级高于配置文件。

```bash
python main.py video.mp4 -b bg.png --maa-path C:/MAA
```

### `--config`, `-c`

| 属性 | 值 |
|------|-----|
| 类型 | 文件路径 |
| 必填 | 否 |
| 默认值 | `config/pipeline.json` |

指定全局流水线配置文件路径。

```bash
python main.py video.mp4 -b bg.png --config my_config.json
```

### `--log-level`

| 属性 | 值 |
|------|-----|
| 类型 | 枚举 |
| 必填 | 否 |
| 可选值 | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| 默认值 | 使用 `pipeline.json` 中的 `log_level` |

设置日志输出级别。

```bash
python main.py video.mp4 -b bg.png --log-level DEBUG
```

各级别输出内容：

| 级别 | 说明 |
|------|------|
| `DEBUG` | 详细的调试信息，包括每帧匹配结果 |
| `INFO` | 常规运行信息，包括步骤进度和结果 |
| `WARNING` | 仅警告和错误信息 |
| `ERROR` | 仅错误信息 |

### `--no-log-file`

| 属性 | 值 |
|------|-----|
| 类型 | 布尔标志 |
| 必填 | 否 |
| 默认值 | 未指定（即启用日志文件） |

禁用日志文件输出，仅输出到控制台。

```bash
python main.py video.mp4 -b bg.png --no-log-file
```

### `--skip-step`

| 属性 | 值 |
|------|-----|
| 类型 | 枚举（可多次使用） |
| 必填 | 否 |
| 可选值 | `copilot`, `formation`, `actions`, `track`, `compose` |
| 默认值 | 无（执行全部步骤） |

跳过指定的流水线步骤，可多次使用以跳过多个步骤。

步骤名称与功能对应：

| 步骤名 | 功能 |
|--------|------|
| `copilot` | 视频转 MAA 作业 JSON |
| `formation` | 编队配置转文本 |
| `actions` | 操作指令转文本 |
| `track` | 开始按钮识别 |
| `compose` | 视频合成 |

```bash
# 跳过开始按钮识别和视频合成
python main.py video.mp4 -b bg.png --skip-step track --skip-step compose

# 仅执行 MAA 识别
python main.py video.mp4 -b bg.png --skip-step formation --skip-step actions --skip-step track --skip-step compose
```

### `--init-config`

| 属性 | 值 |
|------|-----|
| 类型 | 可选字符串 |
| 必填 | 否 |
| 默认值 | 未指定（不生成配置） |
| 可选值 | `all`, `pipeline`, `formation`, `actions`, `track`, `compose`, `compose_style2` |

生成默认配置文件并退出，不执行任何处理。不指定值时等同于 `--init-config all`，生成全部配置文件。

| 模块名 | 生成的配置文件 |
|--------|---------------|
| `all` | 生成全部配置文件 |
| `pipeline` | `config/pipeline.json` |
| `formation` | `config/formation.json` |
| `actions` | `config/actions.json` |
| `track` | `config/track.json` |
| `compose` | `config/video_compose/style1.json` |
| `compose_style2` | `config/video_compose/style2.json` |

```bash
# 生成全部默认配置文件
python main.py --init-config

# 生成指定模块的配置文件
python main.py --init-config formation
python main.py --init-config track
python main.py --init-config compose
python main.py --init-config compose_style2
```

### `--style`, `-s`

| 属性 | 值 |
|------|-----|
| 类型 | 字符串 |
| 必填 | 否 |
| 默认值 | `style1` |

指定视频合成风格名称。对应 `config/video_compose/` 目录下的同名 JSON 配置文件。例如 `--style style1` 将加载 `config/video_compose/style1.json`。

可用风格：

| 风格名 | 说明 |
|--------|------|
| `style1` | 底板图片 + 视频叠加模式，文本叠加于视频区域旁（支持字幕自适应） |
| `style2` | 全屏视频 + 底部居中字幕模式，视频铺满画面，字幕水平编排显示于底部（无需背景板图片） |

> **字幕自适应**：style1 支持字幕自适应功能，在配置文件中将 `text_overlay.subtitle_auto_fit` 设为 `true` 即可启用。启用后系统自动计算最大字体大小，`font_size` 和 `font_scale` 配置将被覆盖。详见 [配置文件说明](configuration.md)。

```bash
# 使用默认风格 (style1)
python main.py video.mp4 -b bg.png

# 使用 style2 全屏字幕模式
python main.py video.mp4 --style style2
python main.py video.mp4 -s style2
```

### `--dry-run`

| 属性 | 值 |
|------|-----|
| 类型 | 布尔标志 |
| 必填 | 否 |
| 默认值 | 未指定 |

仅验证输入文件和配置，不执行实际处理。用于检查视频、图片和配置是否正确。

```bash
python main.py video.mp4 -b bg.png --dry-run
```

---

## 完整使用示例

### 基础用法

```bash
# style1（需要背景板图片）
python main.py video.mp4 --background-image bg.png

# style2（全屏字幕模式，无需背景板图片）
python main.py video.mp4 --style style2
```

### 完整参数示例

```bash
# style1
python main.py video.mp4 \
    --background-image bg.png \
    --output-dir results \
    --maa-path C:/MAA \
    --log-level DEBUG \
    --skip-step track \
    --style style1 \
    --config my_pipeline.json

# style2
python main.py video.mp4 \
    --style style2 \
    --output-dir results \
    --log-level DEBUG
```

### 仅生成配置

```bash
# 生成全部默认配置文件
python main.py --init-config

# 生成指定模块的配置文件
python main.py --init-config formation
```

### 验证输入

```bash
python main.py video.mp4 -b bg.png --dry-run
```

### 仅运行 MAA 识别

```bash
python main.py video.mp4 -b bg.png \
    --skip-step formation \
    --skip-step actions \
    --skip-step track \
    --skip-step compose
```

### 调试模式运行

```bash
python main.py video.mp4 -b bg.png --log-level DEBUG --no-log-file
```

---

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 流水线全部步骤执行成功 |
| `1` | 流水线执行失败（某个步骤出错或输入验证失败） |

---

## 错误提示

### 缺少视频文件

```
error: 请提供视频文件路径，或使用 --init-config 生成默认配置
用法: python main.py <video> --background-image <image>
```

### 缺少背景板图片

```
error: 请提供背景板图片文件路径 (--background-image / -b)
视频合成需要背景板图片，请同时上传视频和背景板图片。
支持的图片格式: .bmp, .jpeg, .jpg, .png, .webp
用法: python main.py <video> --background-image <image>
```

> **提示**：如果使用 style2（`--style style2`），则不需要背景板图片。

### 视频文件不存在

```
[ERROR] 视频文件不存在: xxx.mp4
```

### 背景板图片格式不支持

```
[ERROR] 背景板图片格式不支持: .gif。支持的格式: .bmp, .jpeg, .jpg, .png, .webp
```

### ffmpeg 未安装

```
[ERROR] ffprobe未找到，请确保ffmpeg已安装并在PATH中
```
