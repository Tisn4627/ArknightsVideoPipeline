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
| `maa_path` | string | `""` | MAA 项目路径，**必须手动配置**。支持相对路径（基于项目根目录）或绝对路径，必须指向有效的文件夹 |
| `output_dir` | string | `"output"` | 输出根目录，支持相对路径或绝对路径 |
| `log_level` | string | `"INFO"` | 日志级别，可选值：`DEBUG`、`INFO`、`WARNING`、`ERROR` |
| `log_to_file` | boolean | `true` | 是否将日志输出到文件 |
| `log_max_bytes` | integer | `10485760` | 单个日志文件最大字节数（10MB），超过后触发轮转 |
| `log_backup_count` | integer | `3` | 保留的历史日志文件数量 |
| `maa_timeout_seconds` | integer | `600` | MAA 识别超时时间（秒） |
| `maa_max_retries` | integer | `2` | MAA 识别最大重试次数 |
| `formation` | string | `"config/formation.json"` | 编队转文本配置文件路径 |
| `actions` | string | `"config/actions.json"` | 操作转文本配置文件路径 |
| `track` | string | `"config/track.json"` | 开始按钮识别配置文件路径 |
| `video_compose_style` | string | `"style1"` | 视频合成风格名称，对应 `config/video_compose/` 目录下的同名 JSON 文件 |
| `video_compose_config` | string | `"config/video_compose/style1.json"` | 视频合成配置文件路径 |

### 配置示例

```json
{
    "maa_path": "",
    "output_dir": "output",
    "log_level": "INFO",
    "log_to_file": true,
    "log_max_bytes": 10485760,
    "log_backup_count": 3,
    "maa_timeout_seconds": 600,
    "maa_max_retries": 2,
    "formation": "config/formation.json",
    "actions": "config/actions.json",
    "track": "config/track.json",
    "video_compose_style": "style1",
    "video_compose_config": "config/video_compose/style1.json"
}
```

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
| `video_scale` | float | `0.8` | 视频缩放比例（相对于输出尺寸） |
| `video_x` | integer | `320` | 视频在底板上的 X 坐标偏移 |
| `video_y` | integer | `72` | 视频在底板上的 Y 坐标偏移 |
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
| `font_size` | integer | `45` | 字体大小（`subtitle_auto_fit` 启用时此值被自动覆盖） |
| `font_scale` | float | `1` | 字体缩放比例（`subtitle_auto_fit` 启用时自动设为 1） |
| `text_x` | integer | `0` | 文本 X 坐标偏移 |
| `text_y` | integer | `65` | 文本 Y 坐标偏移 |
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

**style2 text_overlay：**

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `enabled` | boolean | `true` | 是否启用文本叠加 |
| `font` | string | `"SOURCEHANSANSCN-HEAVY.OTF"` | 字体文件名 |
| `font_dir` | string | `"resource/font"` | 字体文件目录 |
| `font_size` | integer | `75` | 字体大小 |
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
    "video_scale": 0.8,
    "video_x": 320,
    "video_y": 72,
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
    "video_scale": 0.8,
    "video_x": 320,
    "video_y": 72,
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
    "video_scale": 0.8,
    "video_x": 320,
    "video_y": 72,
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
        "font_size": 75,
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

> **注意**：视频合成风格配置文件位于 `config/video_compose/` 目录下，每个风格对应一个 JSON 文件。默认风格为 `style1`，可通过 `--style` 参数指定其他风格。
