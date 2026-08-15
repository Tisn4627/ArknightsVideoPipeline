# 配置文件说明

本文档详细列出所有配置项的名称、数据类型、默认值、描述及使用场景。

## 配置优先级

配置值按以下优先级从高到低生效：

1. **CLI 参数** - 命令行传入的参数
2. **pipeline.json** - 全局流水线配置文件
3. **子配置 JSON** - 各模块独立配置文件
4. **代码默认值** - 各模块 `DEFAULT_CONFIG` 中定义的值

## 配置文件生成

使用 `--init-config` 参数生成默认配置文件：

```bash
# 生成全部默认配置文件
python main.py --init-config

# 生成指定模块的配置文件
python main.py --init-config pipeline
python main.py --init-config formation
python main.py --init-config actions
python main.py --init-config track
python main.py --init-config compose
```

可用模块名：`pipeline`、`formation`、`actions`、`track`、`compose`、`all`

---

## 1. pipeline.json — 全局流水线配置

文件路径：`config/pipeline.json`

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `copilot_backend` | string | `"recognition"` | 视频转作业 JSON 的识别后端：`"recognition"`（默认，纯 Python 实现，ArknightsVideoRecognition 代码随仓库分发）或 `"maa"`（调用 MAA 项目，需配置 `maa_path`）。CLI 可用 `--backend` 覆盖 |
| `recognition.ocr_source` | string | `"maamodel"` | Recognition 后端的 OCR 模型来源：`"maamodel"`（Maa finetune 模型，默认）或 `"default"`（rapidocr 默认模型）。CLI 可用 `--ocr` 覆盖 |
| `recognition.resolution` | string | `"1280x720"` | Recognition 后端的视频处理分辨率，格式 `"WxH"`。CLI 可用 `--resolution` 覆盖 |
| `recognition.stage_override` | string | `""` | 关卡指定（code/name/stageId，如 `2-10` 或 `main_02-10`）。空=自动识别；指定后跳过关卡 OCR。CLI 可用 `--stage` 覆盖 |
| `recognition.with_video_time` | boolean | `false` | 是否在 actions 中输出非标准的 `video_time` 扩展字段（视频时间点，秒） |
| `recognition.resource_dir` | string | `""` | Recognition 资源目录覆盖。空=使用顶层 `resource/`（识别资源 avatar/config/data/ocr/onnx/template/tile 已随仓库分发，直接位于顶层）；非空时使用该路径（运行时优先级最高，优先于环境变量 `AVR_RESOURCE_DIR`） |
| `maa_path` | string | `""` | MAA 项目路径，**仅 `copilot_backend="maa"` 时生效**。支持相对路径（基于项目根目录）或绝对路径，必须指向有效的文件夹 |
| `output_dir` | string | `"output"` | 输出根目录，支持相对路径或绝对路径 |
| `log_level` | string | `"INFO"` | 日志级别，可选值：`DEBUG`、`INFO`、`WARNING`、`ERROR` |
| `log_to_file` | boolean | `true` | 是否将日志输出到文件 |
| `log_max_bytes` | integer | `10485760` | 单个日志文件最大字节数（10MB），超过后触发轮转 |
| `log_backup_count` | integer | `3` | 保留的历史日志文件数量 |
| `copilot_timeout_seconds` | integer | `600` | 识别统一超时时间（秒），recognition/maa 两后端共用（已合并原 `maa_timeout_seconds`） |
| `copilot_max_retries` | integer | `2` | 识别统一最大重试次数，recognition/maa 两后端共用（已合并原 `maa_max_retries`） |
| `formation` | string | `"config/formation.json"` | 编队转文本配置文件路径 |
| `actions` | string | `"config/actions.json"` | 操作转文本配置文件路径 |
| `track` | string | `"config/track.json"` | 开始按钮识别配置文件路径 |
| `video_compose_style` | string | `"style1"` | 视频合成风格名称，对应 `config/video_compose/` 目录下的同名 JSON 文件 |
| `video_compose_config` | string | `"config/video_compose/style1.json"` | 视频合成配置文件路径 |
| `multithreading` | boolean | `false` | 多线程批量处理开关。`false`（默认）时批量任务严格串行执行，一次仅运行一个合成任务，避免 MAA 资源争用；`true` 时按 `max_concurrent` 上限并发派发多个 PipelineWorker。仅在 GUI 批量处理时生效，CLI 不受此字段影响 |
| `max_concurrent` | integer | `1` | 最大并发视频合成任务数（正整数，范围 1~16）。仅当 `multithreading=true` 时生效；`multithreading=false` 或该值为 1 时退化为完全串行。每个并发任务会拉起独立的 Pipeline 实例及 MAA/ffmpeg 子进程，设置过大可能耗尽 CPU/内存/IO 资源 |
| `ffmpeg_custom_enabled` | boolean | `true` | FFmpeg 自定义路径开关（**仅 Windows**）。`true`（默认）时将 `ffmpeg_path` 指定的目录加入 PATH 最前面，使该目录中的 ffmpeg.exe / ffprobe.exe 优先于系统已安装的版本；`false` 时使用系统 PATH 中的 FFmpeg。非 Windows 平台忽略此项 |
| `ffmpeg_path` | string | `"resource/ffmpeg/bin"` | FFmpeg 可执行文件**所在目录**（**仅 Windows**）。仅当 `ffmpeg_custom_enabled=true` 时生效。该目录须同时包含 ffmpeg.exe 与 ffprobe.exe。支持相对路径（以项目根目录为基准）或绝对路径。示例：`"C:/tools/ffmpeg/bin"` |

### 配置示例

```json
{
    "copilot_backend": "recognition",
    "recognition": {
        "ocr_source": "maamodel",
        "resolution": "1280x720",
        "stage_override": "",
        "with_video_time": false,
        "resource_dir": ""
    },
    "maa_path": "",
    "copilot_timeout_seconds": 600,
    "copilot_max_retries": 2,
    "output_dir": "output",
    "log_level": "INFO",
    "log_to_file": true,
    "log_max_bytes": 10485760,
    "log_backup_count": 3,
    "formation": "config/formation.json",
    "actions": "config/actions.json",
    "track": "config/track.json",
    "video_compose_style": "style1",
    "video_compose_config": "config/video_compose/style1.json",
    "multithreading": false,
    "max_concurrent": 1,
    "ffmpeg_custom_enabled": true,
    "ffmpeg_path": "resource/ffmpeg/bin"
}
```

> **识别资源说明（recognition 后端）**：`recognition.resource_dir` 为空时，运行时读取
> `<项目根>/resource/`（识别资源 avatar/config/data/ocr/onnx/template/tile 已随仓库分发，
> 直接位于顶层，与 font/locales 同层）。资源缺失时步骤 1 会报错并提示检查资源目录。
> 详见 [合并方案](docs/merge_plan.md)。

> **视频列表说明**：GUI **Video files** 卡片中的视频列表**仅保存在当前会话内存中，不持久化**——每次启动 GUI 时列表为空，关闭窗口也不会将队列写入 `pipeline.json`。CLI 通过 `video` 位置参数接收视频列表（`python main.py v1.mp4 v2.mp4 ...`）。旧版配置文件中残留的 `video_paths` / `video_path` 字段会在加载时自动清除，不再生成。

> **多线程说明与风险提示**：`multithreading` 默认关闭，保持串行执行以避免 MAA 资源争用（多个 MAA 实例可能共享同一 ADB 连接或资源目录，并发运行可能互相干扰）。启用前请确认你的任务之间不存在共享资源冲突。每个并发 worker 会获得独立的 `ConfigManager` 快照与独立输出目录（按视频名分目录），不存在中间文件冲突；日志按线程过滤后分别回传到 GUI，不会重复显示。任务失败互不影响——单个 worker 的异常会被捕获并标记为 failed，其余并行任务继续执行。

> **FFmpeg 路径自定义说明**：此功能仅适用于 Windows 系统。默认启用（`ffmpeg_custom_enabled=true`），程序将 `ffmpeg_path` 指定的目录（默认值 `resource/ffmpeg/bin`）加入 PATH 最前面，使该目录中的 FFmpeg 优先于系统已安装的版本——这确保打包后的 EXE 在未安装 FFmpeg 的机器上能直接使用内置的 FFmpeg。关闭后（`ffmpeg_custom_enabled=false`）则使用系统 PATH 中的 FFmpeg。`ffmpeg_path` 应为 ffmpeg.exe **所在目录**（非 exe 文件本身），且该目录须同时包含 ffprobe.exe。支持相对路径（以项目根目录为基准）或绝对路径。非 Windows 平台上，GUI 设置页不显示此配置卡片，配置项即使存在也会被忽略。

---

## 2. formation.json — 编队转文本配置

文件路径：`config/formation.json`

控制编队信息中各字段的显示开关。设为 `true` 显示，`false` 隐藏。

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `show_skill` | boolean | `false` | 是否显示干员技能信息 |
| `show_requirements` | boolean | `false` | 是否显示编队要求信息 |
| `show_module` | boolean | `false` | 是否显示干员模组信息 |

### 配置示例

```json
{
    "show_skill": true,
    "show_requirements": false,
    "show_module": true
}
```

---

## 3. actions.json — 操作转文本配置

文件路径：`config/actions.json`

控制操作指令中各字段的显示开关。设为 `true` 显示，`false` 隐藏。

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `show_skill` | boolean | `false` | 是否显示技能使用信息 |
| `show_requirements` | boolean | `false` | 是否显示操作要求信息 |
| `show_module` | boolean | `false` | 是否显示模组信息 |
| `show_location` | boolean | `false` | 是否显示部署位置（坐标） |
| `show_direction` | boolean | `true` | 是否显示部署方向 |
| `show_delay` | boolean | `false` | 是否显示操作延迟时间 |
| `show_conditions` | boolean | `false` | 是否显示执行条件 |
| `show_doc` | boolean | `false` | 是否显示文档说明 |

### 配置示例

```json
{
    "show_skill": true,
    "show_location": true,
    "show_direction": true,
    "show_delay": true
}
```

---

## 4. track.json — 开始按钮识别配置

文件路径：`config/track.json`

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `track_mode` | string | `"startbutton"` | 识别模式：`startbutton`（开始按钮模板匹配，原行为）/ `battlestart`（战斗开始检测，暂停按钮 ROI 亮像素阈值法，思路与 MAA BattleHasStarted 一致） |
| `resource_dir` | string | `"resource/StartButton"` | 模板图片目录路径 |
| `match_threshold` | float | `0.75` | 模板匹配阈值，越高越严格（0.0~1.0） |
| `scale_range` | array | `[0.5, 1.5]` | 模板缩放范围 [最小, 最大] |
| `scale_steps` | integer | `9` | 缩放步数，越多越精确但越慢 |
| `detection_fps` | integer | `2` | 检测采样帧率（从视频中每秒取多少帧检测） |
| `detection_time_limit` | integer | `30` | 检测时间限制（秒），仅检测视频前 N 秒；视频不足 N 秒时自动调整；设为 0 或 null 则检测完整视频 |
| `auto_downscale` | boolean | `true` | 视频高度超过阈值时自动缩小 |
| `downscale_target_height` | integer | `720` | 自动缩放目标高度（像素） |
| `min_consecutive_frames` | integer | `2` | 最少连续匹配帧数，低于此数不视为有效检测 |
| `use_grayscale` | boolean | `true` | 使用灰度匹配（提升速度） |
| `use_roi` | boolean | `true` | 启用 ROI 区域搜索 |
| `roi_padding` | integer | `50` | ROI 区域边距（像素） |
| `roi_search_expand` | float | `1.5` | ROI 搜索区域扩展倍数 |
| `early_stop_threshold` | float | `0.92` | 早停阈值，匹配度超过此值立即返回 |
| `max_workers` | integer | `4` | 并行匹配线程数 |
| `debug_mode` | boolean | `true` | 调试模式，输出详细匹配信息 |
| `output_result` | boolean | `true` | 是否输出识别结果文件 |

### battle_start 子配置

`battle_start` 为嵌套对象，仅在 `track_mode = "battlestart"` 时生效（暂停按钮 ROI 亮像素阈值法，无需 StartButton 模板资源）。

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `time_limit` | integer | `30` | 检测时间限制（秒），仅检测视频前 N 秒；设为 0 或 null 则检测完整视频 |
| `min_consecutive_frames` | integer | `2` | 最少连续命中采样帧数，低于此数不视为进入战斗 |
| `debug_mode` | boolean | `true` | 调试模式，输出逐帧亮像素占比诊断信息 |

> **battlestart 模式说明**：进入战斗后屏幕右上角会出现「暂停」按钮，该区域在灰度图中表现为大片亮像素，通过 ROI 亮像素占比阈值判定进入战斗时机。识别结果中的 `battle_start_time`（进入战斗时间）将作为编队文本的切换时间（`get_switch_time` 优先使用该字段）。

### 配置示例

```json
{
    "match_threshold": 0.8,
    "detection_fps": 5,
    "detection_time_limit": 60,
    "use_grayscale": true,
    "max_workers": 8
}
```

---

## 5. 视频合成风格配置

视频合成配置采用风格（style）机制，每个风格对应 `config/video_compose/` 目录下的一个 JSON 文件。默认风格为 `style1`，配置文件为 `config/video_compose/style1.json`。

可通过 CLI 参数 `--style` 指定风格名称，程序将自动加载 `config/video_compose/<style_name>.json`。

### 可用风格

| 风格名 | 说明 | 模块 |
|--------|------|------|
| `style1` | 底板图片 + 视频叠加模式，文本叠加于视频区域旁 | `core/video_compose.py` |
| `style2` | 全屏视频 + 底部居中字幕模式，视频铺满画面，字幕水平编排显示于底部 | `core/video_compose_style2.py` |

### style1 配置

文件路径：`config/video_compose/style1.json`

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `output_width` | integer | `1920` | 输出视频宽度（像素） |
| `output_height` | integer | `1080` | 输出视频高度（像素） |
| `video_scale` | float | `0.85` | 视频缩放比例（相对于输出尺寸） |
| `video_x` | integer | `272` | 视频在底板上的 X 坐标偏移 |
| `video_y` | integer | `47` | 视频在底板上的 Y 坐标偏移 |
| `video_quality` | string | `"middle"` | 输出视频质量，可选值：`low`、`middle`、`high`、`very_high` |

### style2 配置

文件路径：`config/video_compose/style2.json`

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `output_width` | integer | `1920` | 输出视频宽度（像素） |
| `output_height` | integer | `1080` | 输出视频高度（像素） |
| `video_quality` | string | `"middle"` | 输出视频质量，可选值：`low`、`middle`、`high`、`very_high` |

> **注意**：style2 不需要 `video_scale`、`video_x`、`video_y`，因为视频会自动铺满整个输出画面。style2 也不需要 `background_image`（底板图片），因为视频直接铺满画面。

> **style2 文本编排**：style2 采用水平编排方式，将编队信息和操作信息中的各条目用空格连接在同一行显示（区别于 style1 的竖直编排，每行一条信息）。当操作信息超过 `max_chars_per_line` 限制时，会在完整信息单元处自动换行。

### text_overlay 子配置

`text_overlay` 为嵌套对象，控制文本叠加行为。

**style1 text_overlay：**

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `enabled` | boolean | `true` | 是否启用文本叠加 |
| `font` | string | `"SOURCEHANSANSCN-HEAVY.OTF"` | 字体文件名 |
| `font_dir` | string | `"resource/font"` | 字体文件目录 |
| `font_size` | integer | `25` | 字体大小（`subtitle_auto_fit` 启用时此值被自动覆盖） |
| `font_scale` | float | `1` | 字体缩放比例（`subtitle_auto_fit` 启用时自动设为 1） |
| `text_x` | integer | `50` | 文本 X 坐标偏移 |
| `text_y` | integer | `240` | 文本 Y 坐标偏移 |
| `max_text_right` | integer/null | `272` | Actions 文本块右边界（画布绝对 X）。超宽行自动换行，保证右侧不遮挡视频画面；`null` 表示不限 |
| `max_text_bottom` | integer/null | `965` | Actions 文本块下边界（画布绝对 Y）。自动换行后仍超高时，按操作从末尾截断，保证下侧不遮挡视频画面中的 Tips 提示字样；`null` 表示不限 |
| `fade_duration` | float | `0.5` | 淡入淡出持续时间（秒） |
| `shadow_enabled` | boolean | `true` | 是否启用文字阴影 |
| `shadow_offset_x` | integer | `2` | 阴影 X 偏移 |
| `shadow_offset_y` | integer | `2` | 阴影 Y 偏移 |
| `shadow_blur` | integer | `4` | 阴影模糊半径 |
| `shadow_color` | string | `"#000000"` | 阴影颜色（HEX 格式） |
| `text_color` | string | `"#FFFFFF"` | 文字颜色（HEX 格式） |
| `subtitle_auto_fit` | boolean | `false` | 字幕自适应开关。启用后自动计算最大字体大小，`font_size` 和 `font_scale` 配置将被覆盖 |
| `auto_fit_min_font_size` | integer | `10` | 自适应字体大小搜索下限（像素） |
| `auto_fit_max_font_size` | integer | `200` | 自适应字体大小搜索上限（像素） |
| `auto_fit_available_width` | integer/null | `null` | 自适应可用宽度（像素）。设为 `null` 时自动根据视频区域和字幕位置推断；设为具体数值时使用指定宽度 |

> **字幕自适应说明**：当 `subtitle_auto_fit` 设为 `true` 时，系统会根据视频区域和底板布局自动计算字幕可用的最大宽度（也可通过 `auto_fit_available_width` 手动指定），然后使用二分查找算法在 `[auto_fit_min_font_size, auto_fit_max_font_size]` 范围内搜索最大字体大小，确保编队文本和操作文本的所有行均不超出可用宽度。两段文本使用统一的字体大小（取两者中需要更小字体的值），以保证视觉一致性。
>
> **可用宽度自动推断逻辑**：
> - 若 `auto_fit_available_width` 设为具体数值，直接使用该值
> - 若为 `null`，则根据 `text_x` 与视频区域的相对位置自动推断：
>   - 字幕在视频左侧（`text_x < video_x`）：可用宽度 = `video_x`
>   - 字幕在视频右侧（`text_x >= video_x + video_width`）：可用宽度 = `output_width - text_x`
>   - 字幕与视频重叠：取左侧和右侧区域中较大者
> - 自动推断的可用宽度不超过输出宽度的 40%
>
> **Actions 显示范围限定说明**：`max_text_right` / `max_text_bottom` 与文本锚点
> `(text_x, text_y)` 围成 Actions 文本可显示区域（默认右边界 = 视频左边缘
> `video_x`，下边界 = 视频底边；文本块左上角固定为 `(text_x, text_y)`）。
> 启用后（任一值非 `null`）：
> - 超出右边界的文本行自动换行（优先在空格处断行，CJK 按字符断行）；
> - 换行后文本块高度仍超出下边界时，按整个操作为单位从末尾截断，日志中记录截断数量；
> - 若截断后操作均带 `video_time`（识别输出时间扩展字段），自动**分页切换**：
>   页内最后一个操作完成（到达其 `video_time`）时切换到尚未进行的操作，
>   避免被截断的操作永久丢失；页内全部为同刻操作的退化情形下整页跳过；
> - 逐操作显示（`map_overlay`）的面板高亮会与换行后的行结构保持一致，
>   分页显示时随页独立构建，仅末页高亮接管到视频结束；
> - 该限定仅作用于 Actions 文本，编队文本不受影响。
> 可通过 GUI「工具 → Style1 文本范围预览」实时调整边界并写入配置。

**style2 text_overlay：**

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `enabled` | boolean | `true` | 是否启用文本叠加 |
| `font` | string | `"SOURCEHANSANSCN-HEAVY.OTF"` | 字体文件名 |
| `font_dir` | string | `"resource/font"` | 字体文件目录 |
| `font_size` | integer | `45` | 字体大小 |
| `font_scale` | float | `1` | 字体缩放比例 |
| `fade_duration` | float | `0.5` | 淡入淡出持续时间（秒） |
| `shadow_enabled` | boolean | `true` | 是否启用文字阴影 |
| `shadow_offset_x` | integer | `2` | 阴影 X 偏移 |
| `shadow_offset_y` | integer | `2` | 阴影 Y 偏移 |
| `shadow_blur` | integer | `4` | 阴影模糊半径 |
| `shadow_color` | string | `"#000000"` | 阴影颜色（HEX 格式） |
| `text_color` | string | `"#FFFFFF"` | 文字颜色（HEX 格式） |
| `max_chars_per_line` | integer | `20` | 每行最大汉字个数，超出时在完整信息单元处自动换行（CJK字符占2宽度单位，其余占1单位，宽度上限=该值×2） |
| `line_height` | float | `1.5` | 多行文本行高倍率（基于 font_size，1.0=紧凑，1.5=舒适阅读） |
| `bottom_margin` | integer | `60` | 字幕距底部的边距（像素） |

> **注意**：`video_source`、`background_image`、`input_json`、`formation`、`actions` 为运行时参数，由流水线自动注入，无需在配置文件中指定。

### 配置示例

**style1 示例：**

```json
{
    "output_width": 1920,
    "output_height": 1080,
    "video_scale": 0.85,
    "video_x": 272,
    "video_y": 47,
    "video_quality": "high",
    "text_overlay": {
        "enabled": true,
        "font_size": 50,
        "text_color": "#FFD700",
        "shadow_enabled": true
    }
}
```

**style1 启用字幕自适应示例：**

```json
{
    "output_width": 1920,
    "output_height": 1080,
    "video_scale": 0.85,
    "video_x": 272,
    "video_y": 47,
    "video_quality": "high",
    "text_overlay": {
        "enabled": true,
        "subtitle_auto_fit": true,
        "auto_fit_min_font_size": 15,
        "auto_fit_max_font_size": 150,
        "text_color": "#FFFFFF",
        "shadow_enabled": true
    }
}
```

**style1 手动指定可用宽度示例：**

```json
{
    "output_width": 1920,
    "output_height": 1080,
    "video_scale": 0.85,
    "video_x": 272,
    "video_y": 47,
    "video_quality": "high",
    "text_overlay": {
        "enabled": true,
        "subtitle_auto_fit": true,
        "auto_fit_available_width": 300,
        "text_color": "#FFFFFF",
        "shadow_enabled": true
    }
}
```

**style2 示例：**

```json
{
    "output_width": 1920,
    "output_height": 1080,
    "video_quality": "high",
    "text_overlay": {
        "enabled": true,
        "font_size": 45,
        "text_color": "#FFFFFF",
        "max_chars_per_line": 20,
        "bottom_margin": 60
    }
}
```

---

## 配置文件位置汇总

| 配置文件 | 路径 | 对应模块 | --init-config 模块名 |
|----------|------|----------|---------------------|
| pipeline.json | `config/pipeline.json` | `core/config.py` | `pipeline` |
| formation.json | `config/formation.json` | `core/formation_to_text.py` | `formation` |
| actions.json | `config/actions.json` | `core/actions_to_text.py` | `actions` |
| track.json | `config/track.json` | `core/track_startbutton.py` | `track` |
| style1.json | `config/video_compose/style1.json` | `core/video_compose.py` | `compose` |
| style2.json | `config/video_compose/style2.json` | `core/video_compose_style2.py` | `compose_style2` |
| gui.json | `config/gui.json` | `gui/theme/gui_config.py` | `gui` |

> **注意**：视频合成风格配置文件位于 `config/video_compose/` 目录下，每个风格对应一个 JSON 文件。默认风格为 `style1`，可通过 `--style` 参数指定其他风格。

---

## 6. gui.json — GUI 独立配置

文件路径：`config/gui.json`

> **与 pipeline 配置完全解耦**：`gui.json` 独立管理 GUI 运行时偏好，与流水线业务配置无任何依赖关系。GUI 中对主题的修改持久化到此文件，**不影响** `pipeline.json`；CLI 运行完全不受此文件影响。

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `theme` | string | `"light"` | GUI 主题，可选值：`light`（浅色）、`dark`（深色）。由 `ConfigProxy`（`service/config_proxy.py`）管理，切换后即时生效，关闭窗口时持久化到此文件；下次启动自动恢复 |

### 配置示例

```json
{
    "theme": "light"
}
```

### 管理方式说明

- 该文件**不**由 `--init-config` 生成，也**不在** `PIPELINE_DEFAULTS` 中定义；
- 首次 GUI 启动时，`ConfigProxy` 自动创建此文件并写入默认值；
- 旧版本项目（无此文件）启动时，`ConfigProxy` 自动回退 `"light"`，无需手动迁移。
