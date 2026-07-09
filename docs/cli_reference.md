# CLI 参数说明

本文档为 `main.py` 命令行接口的完整参考手册。

## 基本语法

```bash
# style1（需要背景板图片）
python main.py <video1> <video2> ... --background-image <image> [选项]

# style2（无需背景板图片）
python main.py <video1> <video2> ... --style style2 [选项]
```

支持一次传入多个视频文件，按给定顺序依次处理（批量模式）。仅传入一个视频时与旧版完全兼容，等价于长度为 1 的批量。

## 位置参数

### `video`

| 属性 | 值 |
|------|-----|
| 类型 | 文件路径（可多个） |
| 必填 | 是，至少一个（除非使用 `--init-config`） |
| 默认值 | `[]`（空列表） |
| 支持格式 | `.mp4`, `.avi`, `.mkv`, `.mov`, `.flv`, `.wmv` |

输入视频文件路径，支持相对路径和绝对路径。可一次传入多个文件，按给定顺序依次处理（批量模式）。使用 `--init-config` 时无需提供视频。

```bash
# 单文件（与旧版完全兼容）
python main.py video.mp4 -b bg.png
python main.py C:/Videos/game.mp4 -b bg.png

# 多文件批量处理
python main.py v1.mp4 v2.mp4 v3.mp4 -b bg.png
```

#### 批量处理要点

- 多个视频按命令行中的顺序依次处理；
- 某个文件失败时跳过该文件，继续处理后续文件，不中断整批；
- 退出码：仅当全部文件成功时为 `0`，任意文件失败或输入验证失败时为 `1`；
- 共享选项（`--background-image`、`--maa-path`、`--output-dir`、`--style`、`--log-level`、`--skip-step`）作用于整批视频；
- 多文件运行时，日志文件写入到基础输出目录（`output/`）；单文件运行时仍写入到该视频的输出子目录（`output/<video_name>/`，保持向后兼容）；
- `--dry-run` 会一次性验证全部视频后退出。

详见下方 [批量处理](#批量处理) 章节。

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

## FFmpeg 路径配置

CLI 不提供独立的 FFmpeg 路径参数，但可通过 `config/pipeline.json` 中的两个字段配置：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ffmpeg_custom_enabled` | boolean | `false` | FFmpeg 自定义路径开关 |
| `ffmpeg_path` | string | `"resource/ffmpeg/bin/ffmpeg.exe"` | FFmpeg 可执行文件路径 |

- **关闭**（默认）：使用内置 FFmpeg `resource/ffmpeg/bin/ffmpeg.exe`；
- **开启**：将 `ffmpeg_custom_enabled` 设为 `true`，并在 `ffmpeg_path` 填入目标 `ffmpeg.exe` 的完整路径；
- 生效方式：程序将目标 `ffmpeg.exe` 所在目录前置到 `PATH`，使 ffprobe 验证、ffmpeg 转码与 movielite 合成库统一解析到该二进制；
- **平台限制**：此功能仅 Windows GUI 暴露设置卡片；CLI 用户可手动编辑 pipeline.json。非 Windows 上内置 `ffmpeg.exe` 不存在时自动回退到系统 PATH 中的 ffmpeg，不会报错。

```json
// pipeline.json 中启用自定义 FFmpeg 路径示例
{
    "ffmpeg_custom_enabled": true,
    "ffmpeg_path": "C:/tools/ffmpeg/bin/ffmpeg.exe"
}
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

# 批量处理多个视频（共享同一背景板与配置）
python main.py C:/Videos/v1.mp4 C:/Videos/v2.mp4 C:/Videos/v3.mp4 \
    --background-image bg.png \
    --output-dir results \
    --maa-path C:/MAA \
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

## 批量处理

`video` 位置参数支持传入多个文件，多个视频将按给定顺序依次处理。批量模式适用于一次性处理整批录像、夜间队列等场景。

### 处理规则

- **顺序执行**：按命令行中给出的顺序依次处理，不并行；
- **错误隔离**：单个文件验证或处理失败时跳过该文件，继续处理后续文件，不会中断整批；
- **退出码**：仅当全部文件成功时返回 `0`；任意文件失败（或输入验证失败）时返回 `1`；
- **共享选项**：以下选项作用于整批视频，不为单个文件单独配置：
  - `--background-image` / `-b`：背景板图片（style1 必填）
  - `--maa-path`：MAA 项目路径
  - `--output-dir` / `-o`：输出根目录（每个视频仍会写入到 `<output-dir>/<video_name>/` 子目录）
  - `--style` / `-s`：视频合成风格
  - `--log-level`：日志级别
  - `--skip-step`：跳过的步骤
- **日志文件**：多文件运行时，日志写入到基础输出目录（`output/pipeline.log`）；单文件运行时仍写入到该视频的输出子目录（`output/<video_name>/pipeline.log`，保持向后兼容）；
- **`--dry-run`**：一次性验证全部视频文件后退出，不会执行实际处理。

### 示例

```bash
# 批量处理 3 个视频，共享同一背景板与输出目录
python main.py v1.mp4 v2.mp4 v3.mp4 -b bg.png --output-dir results

# 批量处理并使用 style2（无需背景板图片）
python main.py v1.mp4 v2.mp4 --style style2 --output-dir results

# 批量验证输入（不执行实际处理）
python main.py v1.mp4 v2.mp4 v3.mp4 -b bg.png --dry-run

# 批量处理并跳过部分步骤
python main.py v1.mp4 v2.mp4 -b bg.png \
    --skip-step track --skip-step compose --output-dir results
```

> **提示**：单文件调用 `python main.py video.mp4 -b bg.png` 等价于长度为 1 的批量，行为与旧版完全一致。

---

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 全部视频文件处理成功（批量模式下要求每个文件均成功） |
| `1` | 流水线执行失败（某个步骤出错、输入验证失败，或批量模式下任意文件失败） |

---

## 错误提示

### 缺少视频文件

```
error: 请提供至少一个视频文件路径，或使用 --init-config 生成默认配置
用法: python main.py <video...> --background-image <image>
```

### 缺少背景板图片

```
error: 请提供背景板图片文件路径 (--background-image / -b)
视频合成需要背景板图片，请同时上传视频和背景板图片。
支持的图片格式: .bmp, .jpeg, .jpg, .png, .webp
用法: python main.py <video...> --background-image <image>
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
