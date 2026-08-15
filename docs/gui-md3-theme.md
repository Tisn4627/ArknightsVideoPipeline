# GUI 主题系统文档（MD3 纯原生实现）

本文档面向项目维护者，说明 `src/arknights_video_pipeline/gui/` 下 Material Design 3
紫色主题系统的实现方式、QSS 命名规范与图标资源替换流程。

## 一、纯原生实现说明

### 1.1 为什么零第三方依赖

GUI 主题美化市场上存在 `qt-material`、`qtawesome`、`PyQtDarkTheme` 等成熟库，
但本项目坚持纯 PyQt6 原生实现，原因如下：

1. **可审计性**：主题 Token、QSS、图标染色全部在本仓库内，行为可预期、可测试，
   不会因第三方库升级/弃坑而突然变化。
2. **打包体积**：PyInstaller 打包时无需附带主题库的字体与图标资源。
3. **离线自包含**：字体（Roboto / Noto Sans SC）与 SVG 图标均内置在
   `gui/assets/` 下，无 CDN 依赖，任何环境（包括无外网的生产机）都可运行。
4. **PyQt6 原生能力足够**：QPalette + QSS + 自绘 `paintEvent` 已能覆盖
   MD3 的全部视觉需求，第三方库只是"包装"而非"能力"。

### 1.2 三层渲染分工

| 层 | 载体 | 职责 | 优先级 |
|----|------|------|--------|
| Token | `theme/colors.py` `MaterialColors` | 定义 Light/Dark 两套 MD3 紫色色板（单一事实源） | — |
| 兜底 | `theme/palette.py` | MD3 Token → `QPalette.ColorRole` 映射，覆盖 QSS 未触达的原生控件 | 最低 |
| 主体 | `theme/styles.py` `MaterialStyle` | 根据 Token 生成全局 QSS 字符串（带缓存），覆盖全部项目控件 | 最高 |
| 补充 | `paintEvent` 自绘 | QSS 表达不了的形态：圆角卡片背景、复选框/开关 indicator、SVG 图标染色 | 中等 |

数据流：`MaterialColors`（token）→ `MaterialStyle.generate_qss()`（f-string 注入十六进制
色值）+ `apply_palette()`（QPalette）→ 控件渲染。QSS 渲染优先于 QPalette，
因此 QPalette 不会破坏样式表；它主要补足未被 QSS 覆盖的原生对话框等场景。

### 1.3 为什么不用独立的 light.qss / dark.qss 文件

MD3 明暗两套主题仅色值不同，结构 100% 相同。现有实现用单一 QSS 模板 +
`MaterialColors` 注入色值，并带 `(colors, family)` 元组缓存：

- 切换主题零文件 I/O，~60ms 的 f-string 构建只发生一次；
- 维护两套文件意味着任何结构性修改都要同步两遍，容易漏改；
- 色值集中在 `colors.py`，QSS 中不出现任何硬编码十六进制。

### 1.4 字体与图标

- **字体**：`theme/font_manager.py` 通过 `QFontDatabase.addApplicationFont` 注册
  `gui/assets/fonts/` 下的可变字体（Roboto-Variable.ttf、NotoSansSC-Variable.ttf，
  覆盖 100~900 全字重）。注册成功后将族名前置到 `typography.py` 的字体回退链；
  文件缺失时静默回退系统字体（Windows 中文回退 Microsoft YaHei UI），保证任何
  环境下可启动。
- **图标**：`assets/icons/nav_icons.py` 用 `QSvgRenderer` 把 24x24 SVG 渲染为
  QImage，再以该图像的 **alpha 通道作为形状蒙版**（`QPainter.CompositionMode_SourceIn`）
  替换为目标颜色。该方法不依赖 SVG 内部的 `fill` 属性值，因此任意来源的
  单色图标都可直接染色，比"正则替换 fill"更健壮，且天然支持 HiDPI（@2x 渲染）。

### 1.5 主题切换链路

`GuiConfig`（`config/gui.json` 持久化）→ `MainWindow._toggle_theme` →
`MaterialStyle.apply()`（QSS + QPalette + 全局字体）→ 各组件 `set_colors()`
级联刷新（导航栏、卡片 surface、日志配色、图标颜色）→ `apply_titlebar_theme()`
（Windows DWM 原生标题栏明暗）。

## 二、QSS 命名规范

项目内自定义 QSS 选择器统一遵循以下规则，新增控件时请沿用。

| 类别 | 规则 | 示例 |
|------|------|------|
| 自定义动态属性 | `md` + 帕斯卡命名，值一律为字符串 `"true"`/`"false"` | `[mdOutlined="true"]`、`[mdText="true"]` |
| objectName | 驼峰命名，用 ID 选择器 `#` | `#materialCard`、`#settingsScrollViewport`、`#msgIcon` |
| 作用域 | 避免无差别全局覆盖：局部区域用 ID 选择器限定 | `QWidget#settingsScrollViewport { background-color: transparent; }` |

注意事项：

1. 不得使用 Qt 内置属性名（如 `text`、`outlined`、`checked`）作为自定义属性名，
   否则会覆盖控件原有行为（见 `material_button.py` 中的注释）。
2. 布尔属性取值必须是字符串 `"true"`/`"false"`（小写），QSS 属性选择器不识别
   Python 布尔值。
3. 颜色一律来自 `MaterialColors` 字段，禁止在 QSS 中硬编码十六进制；
   需要变体色时在 `colors.py` 增加字段。
4. 聚焦态边框宽度与常态一致（如都用 2px），避免焦点切换时内容 1px 抖动。

## 三、图标替换流程

所有图标源文件为 24x24 SVG，位于 `gui/assets/icons/svg/`；名称到文件的映射在
`gui/assets/icons/nav_icons.py` 的 `_ICON_FILES` 字典中注册。

### 3.1 从 Google Fonts 下载新图标

1. 打开 <https://fonts.google.com/icons>，搜索所需图标（建议 Filled 风格）。
2. 点击图标 → 右上角 "Download" 可下载该图标系列 zip；或直接访问
   `google/material-design-icons` GitHub 仓库，取
   `src/<category>/<name>/materialicons/24px.svg` 的原始文件。
3. 将 SVG 保存到 `gui/assets/icons/svg/<name>.svg`。
4. 校验：文件应为 24x24 viewBox 的单色形状（`fill` 值不影响染色，可保留）。

### 3.2 注册与使用

```python
# nav_icons.py 的 _ICON_FILES 中新增：
"my_icon": "svg/my_icon.svg",
```

使用方式二选一：

- 程序化着色（推荐，主题切换自动变色）：`make_icon_pixmap("my_icon", color, size_px=24)`
- QSS 引用（适用于 `::indicator` 等子控件）：`icon_url("my_icon")`

### 3.3 主题联动

`make_icon_pixmap` 返回的是已染色的 QPixmap，组件在 `set_colors()` 中
按当前 Token 重新生成即可（参考 `navigation_rail.py`、`batch_video_list.py`）。
无需任何全局注册表——这正是纯原生方案的简洁之处。

### 3.4 注意事项

- 图标染色基于 alpha 蒙版，因此 SVG 中不要保留**半透明**形状（会混入背景色）。
- 相同视觉密度的图标应在同一 24dp 网格下（Material Symbols 均满足）。
- 字体文件（OFL 许可）与图标（Apache 2.0）均可随仓库分发，勿删。
