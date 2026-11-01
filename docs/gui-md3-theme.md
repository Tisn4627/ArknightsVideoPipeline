# GUI 主题系统文档（MD3 纯原生实现）

> 本文档描述 `src/arknights_video_pipeline/gui/theme/` 的 Material Design 3
> 设计系统实现：色调系统（HCT + 动态色彩）、排版、形状、间距、阴影、
> 状态层与动效，以及组件与页面应遵守的规则。
>
> 逐项审查结论见 [gui-md3-review.md](gui-md3-review.md)。

## 一、纯原生实现说明

### 1.1 为什么零第三方依赖

不引入 `qt-material`、`qtawesome`、`PyQtDarkTheme` 等第三方主题/UI 库：

1. **可审计**：项目已对流水线代码做了严格的依赖边界（`core/` 与 `service/`
   零 GUI 依赖），GUI 也应保持"每个像素都能在仓库里找到出处"。第三方主题库
   往往内置大量隐式样式，出现视觉问题时难以定位来源。
2. **打包体积**：`qt-material` / `PyQtDarkTheme` 约 200-400 KB QSS 资源，
   `qtawesome` 附带完整 Font Awesome 字体文件（约 900 KB）。`PyInstaller`
   现产物已因 `onnxruntime`（约 250 MB）与 `resource/fonts` 中日文字体
   （约 30 MB）偏大，不再增加无必要的体积。
3. **离线自包含**：图标/字体/QSS 全部本地化到 `gui/assets/` 与 Python 源码，
   不依赖外部字体 CDN 或网络字体加载器。

### 1.2 三层渲染分工

| 层 | 职责 | 实现 |
|---|---|---|
| **Token 层** | 颜色、排版、形状、间距、阴影、动效常量 | `theme/hct.py`、`scheme.py`、`colors.py`、`typography.py`、`shape.py`、`spacing.py`、`state.py`、`motion.py` |
| **QSS** | 只负责静态外壳：颜色、字体、圆角、边框 | `theme/styles.py`（`MaterialStyle.generate_qss()`） |
| **paintEvent** | QSS 表达不了的部分：状态层墨层、焦点环、过渡动画 | 各 `material_*.py` 组件 |

QSS **不支持** `line-height`、`letter-spacing`、`box-shadow`、`transition`；
这些能力必须由 `QFont`（排版）与 `QPropertyAnimation`（动效）承担。

### 1.3 为什么不用独立的 light.qss / dark.qss 文件

- 明暗切换需要在运行时逐控件刷新颜色，两套 QSS 文件无法做到细粒度热切换。
- QSS 颜色值全部来自 `MaterialColors`（token），单一事实源；新增颜色只需改
  token，不需要在多个 QSS 文件里同步修改。
- 单个 `styles.py` 中的模板便于用 Python 表达条件（如按 DPI 计算尺寸）。

### 1.4 字体与图标

- **字体**：`MaterialTypography` 统一工厂，px 单轨 + `QFont.setFamilies`
  回退链（`Roboto` → `Noto Sans SC` → 系统无衬线）；禁止裸 `QFont()`。
- **图标**：统一 **Material Symbols Rounded**（`gui/assets/icons/svg/`），
  通过 `make_icon_pixmap(name, color, size)` 栅格化并按 `lru_cache` 缓存；
  颜色由调用方传 token，禁止在组件里硬编码。

### 1.5 主题切换链路

```
GuiConfig(theme / dynamic_color / seed_color)
   → ThemeController.apply(dark, seed, dynamic, app)
      → MaterialColors.from_seed(seed, dark)   # HCT 色调生成（带缓存）
      → 已应用且配色未变 → 只广播信号，不重绘
      → apply_palette(colors)                  # QApplication.setPalette（约 1ms）
      → _repolish_palette_widgets(app)         # 清空显式调色板 + 重刷 QSS 取色控件
      → theme_changed(MaterialColors) 信号
         → 各组件自订阅刷新（禁止页面层手工遍历）
   → apply_titlebar_theme(window, dark)        # Windows DWM 标题栏（最后）
```

**运行期切换不再重设样式表。** 旧实现每次切换都对整棵控件树
`setStyleSheet`：约 900 个 QWidget 全部重新 polish，单次 0.6–2.5 秒，
是深色主题切换卡顿的根因。现在颜色分三层：

| 层 | 载体 | 切换时动作 |
|---|---|---|
| 文字 / 背景 / 选中色 | `QPalette`（`theme/palette.py`） | `setPalette` 后清空 QSS 写入的显式调色板，让新调色板沿控件树传播 |
| 描边 / 滚动条 / 菜单等原生控件的外观 | QSS 里的 `palette(role)` | 对这些控件（输入框 / 滚动条等，约 180 个）逐只 `unpolish + polish`，重新解析 |
| 自绘组件（卡片、按钮、开关、复选框、导航、进度条…） | `theme_changed` 信号 | 用新 token 重绘，不经过样式表 |

启动时由 `create_application` 对 `QApplication` 安装一次 QSS（此时控件树
尚未建立，成本接近零），此后样式表**永不重设**：QSS 里不写任何随主题变化
的十六进制颜色，只有 `palette(role)`。新创建的窗口 / 菜单 / 下拉浮层在
创建时 polish，自动取到当前调色板。

两条容易踩的坑：

- `QStyleSheetStyle::polish` 会调用 `QWidget::setPalette`，控件因此带上
  `WA_SetPalette`，之后 `QApplication.setPalette` 不再传播给它——所以切换
  时必须先把每个控件的调色板重置为空 `QPalette()`；
- `palette(role)` 在 polish 时就被解析成具体色值，只改调色板不会让已存在
  控件的描边变色，必须重新 polish（见 `_PALETTE_WIDGET_TYPES`）。

`QToolTip` 没有父窗口，颜色由 `QPalette` 的 `ToolTipBase` / `ToolTipText`
提供，不写入 QSS；这样切换后 tooltip 仍使用当前反色表面。

实测（设置页约 900 个 QWidget，同机同场景）：旧实现整树
`setStyleSheet` 约 0.5 秒（应用级应用样式表时可达 2.6–6.8 秒）；现在的
明暗切换 55–150 毫秒（首次略慢），种子色换色约 25 毫秒。

新增控件只需在构造函数里订阅 `theme_controller().theme_changed`，无需修改
主窗口的切换逻辑；标准控件的文字色交给 QPalette，**不要**用 widget 级
`setStyleSheet(f"color: …")`（见 7.1）。

---

## 二、色调系统（Material You）

### 2.1 HCT 与色调板

`theme/hct.py` 实现 CAM16 / HCT 色彩空间与色调求解（纯标准库，无 Qt 依赖）：

- **H**（hue）：CAM16 色相角；**C**（chroma）：CAM16 色度；**T**（tone）：CIE L*。
- `TonalPalette.of(hue, chroma).tone(t)` 返回 `#RRGGBB`；结果按
  `(hue, chroma, tone)` 缓存。
- 超出 sRGB 色域时保持色相与色调、二分降低色度直至落入色域边界。

种子色 → 五组色调板的色度常量（`theme/scheme.py`）：

| 色调板 | 色相 | 色度 |
|---|---|---|
| primary | 种子色相 | `max(48, 种子色度)` |
| secondary | 种子色相 | 16 |
| tertiary | 种子色相 + 60 | 24 |
| neutral | 种子色相 | 4 |
| neutral-variant | 种子色相 | 8 |
| error | 25（固定） | 84（固定） |
| success / warning（扩展语义） | 取自 `#386A20` / `#7D5700` | — |

**基线种子 `#6750A4` 必须复现以下色值**（回归护栏，见
`tests/test_md3_hct.py`）：`#6750A4`、`#D0BCFF`、`#EADDFF`、`#21005D`、
`#4F378B`、`#381E72`、`#625B71`、`#E8DEF8`、`#1D192B`、`#7D5260`、
`#FFD8E4`、`#633B48`、`#FEF7FF`、`#F7F2FA`、`#F3EDF7`、`#ECE6F0`、
`#E6E0E9`、`#DED8E1`、`#1D1B20`、`#141218`、`#0F0D13`、`#49454F`、
`#79747E`、`#CAC4D0`、`#938F99`、`#E7E0EC`。

### 2.2 颜色角色（43 个）

完整角色表（浅 / 深）见 `MaterialColors` 字段；关键映射：

| 角色 | 浅色 | 深色 |
|---|---|---|
| primary / on_primary | P40 / P100 | P80 / P20 |
| primary_container / on_primary_container | P90 / P10 | P30 / P90 |
| secondary / on_secondary | S40 / S100 | S80 / S20 |
| tertiary / on_tertiary | T40 / T100 | T80 / T20 |
| error / on_error | E40 / E100 | E80 / E20 |
| surface / on_surface | N98 / N10 | N6 / N90 |
| surface_variant / on_surface_variant | NV90 / NV30 | NV30 / NV80 |
| outline / outline_variant | NV50 / NV80 | NV60 / NV30 |
| surface_container_lowest/low/container/high/highest | N100/N96/N94/N92/N90 | N4/N10/N12/N17/N22 |
| inverse_surface / inverse_on_surface / inverse_primary | N20 / N95 / P80 | N90 / N20 / P40 |
| scrim / surface_tint | N0 / P40 | N0 / P80 |

**容器层级用法**（色块分层，不是阴影分层）：

| 平面 | 角色 |
|---|---|
| 窗口 / 页面背景 | `surface` |
| 卡片（filled） | `surface_container_low` |
| 菜单 / 下拉浮层 | `surface_container` |
| 对话框 | `surface_container_high` |
| 抽屉 / 模态大面板 | `surface_container_highest` |

**有意变更**（相对旧版）：`surface` 由 N99 `#FFFBFE` 改为 N98 `#FEF7FF`；
`on_surface` 浅色由 `#1C1B1E` 改为 `#1D1B20`；`background` 由薰衣草
`#F5F0FA` / `#121014` 统一为 `surface` 语义。原因与影响见审查文档。

### 2.3 动态色彩（Material You）

- 设置页「动态色彩」开关 + 种子色选择（`MaterialColors.from_seed()`）。
- 关闭动态色彩 → 回到基线紫 `#6750A4`；切换即时生效并持久化到
  `config/gui.json`（`GuiConfig.dynamic_color` / `seed_color`，含
  `#RRGGBB` 校验与非法值回退）。

---

## 三、排版（type scale）

`theme/typography.py`：15 个角色，**px 单轨**（`QFont.setPixelSize`）、
绝对字距（`QFont.SpacingType.AbsoluteSpacing`）、字重只用 400/500。

| Role | Size | Weight | Line height | Tracking |
|---|---|---|---|---|
| display_large / medium / small | 57 / 45 / 36 | 400 | 64 / 52 / 44 | -0.25 / 0 / 0 |
| headline_large / medium / small | 32 / 28 / 24 | 400 | 40 / 36 / 32 | 0 |
| title_large / medium / small | 22 / 16 / 14 | 400 / 500 / 500 | 28 / 24 / 20 | 0 / 0.15 / 0.1 |
| body_large / medium / small | 16 / 14 / 12 | 400 | 24 / 20 / 16 | 0.5 / 0.25 / 0.4 |
| label_large / medium / small | 14 / 12 / 11 | 500 | 20 / 16 / 16 | 0.1 / 0.5 / 0.5 |

页面头（`PageHeader`）：expanded → `headline_large`(32)；medium →
`headline_medium`(28)；compact → `headline_small`(24)，配 `body_medium`
副标题。行高由布局间距表达（QSS 不支持 `line-height`）。

**禁止**：13px 等非阶梯字号、600+ 字重、裸 `QFont()`、百分比字距。

---

## 四、形状、间距、阴影、状态层、动效

### 4.1 形状（`theme/shape.py`）

| Token | 值 | 用途 |
|---|---|---|
| none | 0 | 分割线、表格 |
| extra_small | 4 | 输入框、菜单项 |
| small | 8 | chip、下拉列表 |
| medium | 12 | 卡片 |
| large | 16 | FAB（extended）、悬浮面板 |
| extra_large | 28 | 对话框 |
| full | 999 | 按钮、开关、胶囊指示器 |

### 4.2 间距（`theme/spacing.py`，4dp 栅格）

`Space.XS=4 / S=8 / M=12 / L=16 / XL=24 / XXL=32 / XXXL=40`；
页边距 `Margin.page(size_class)`：compact 16 / medium 24 / expanded 32。

### 4.3 阴影与 elevation（`theme/state.py`）

| Level | 用途 | key shadow | ambient shadow |
|---|---|---|---|
| 0 | filled 卡片 | 无 | 无 |
| 1 | elevated 卡片、搜索栏 | 0 1px 2px / 30% | 0 1px 3px / 15% |
| 2 | 菜单、下拉 | 0 2px 6px / 30% | 0 1px 4px / 15% |
| 3 | FAB、对话框 | 0 4px 8px / 30% | 0 1px 6px / 15% |
| 4 | 抽屉、模态面板 | 0 6px 10px / 30% | 0 2px 8px / 15% |
| 5 | 最高层浮层 | 0 8px 12px / 30% | 0 4px 10px / 15% |

深色主题用 `surface_tint` 提亮表面表达抬升，不加深黑色阴影。列表行禁用阴影。

### 4.4 状态层（`StateLayer`）

| 状态 | 不透明度 | 叠色 |
|---|---|---|
| hover | 0.08 | `on_surface`（filled 按钮用 `on_primary`） |
| focus | 0.10 | 同上 + 2dp 焦点环 |
| pressed | 0.10 | 同上 |
| dragged | 0.16 | 同上 |
| disabled 容器 / 内容 | 0.12 / 0.38 | `on_surface` |

**焦点态不得改变几何**：输入框常态 1dp 描边、聚焦 2dp（内缩描边），
避免 1px 抖动。

### 4.5 动效（`theme/motion.py`）

| Token | 时长 | 用途 |
|---|---|---|
| short1 / short2 | 100 / 150ms | 墨层淡入 / 勾选 |
| medium1 / medium2 | 200 / 250ms | 开关、折叠 / 导航指示器、FAB |
| long1 / long2 | 300 / 400ms | 页面切换 / 大面板 |

缓动曲线：`standard`(0.2,0,0,1)、`standard_decelerate`(0,0,0,1)、
`standard_accelerate`(0.3,0,1,1)、`emphasized_decelerate`(0.05,0.7,0.1,1)、
`emphasized_accelerate`(0.3,0,0.8,0.15)。

原则：**只动绘制属性**（opacity / progress），不做几何动画；
`Motion.enabled = False` 时动画直接落值（测试与低配环境）。

---

## 五、组件规格

| 组件 | 规格 |
|---|---|
| 按钮 | 高 40dp（小 32 / 大 48）、圆角 full、左右内距 24dp、图标 18dp + 8dp；filled / tonal / elevated / outlined / text 五变体 |
| 图标按钮 | 40dp、圆角 full、图标 24dp；standard / filled / tonal / outlined |
| 输入框 | 主页浮动标签字段高 56dp + 8dp 标签区、圆角 4dp、1dp `outline`、聚焦 2dp `primary`（内缩）；设置页字段用 48dp 桌面密度 |
| 卡片 | 圆角 12dp；默认 `outlined` 变体：`surface_container` 底 + 1dp `outline_variant` 描边；`elevated` 才叠加 level1 阴影 |
| FAB | regular 56dp 圆形；extended 高 56dp、圆角 16dp、左右内距 20dp；elevation 3 |
| 导航 Rail | 宽 80dp、项高 56dp、指示器 56×32 圆角 16、标签 `label_medium` |
| 导航 Bar | 高 80dp、指示器 64×32、3-5 项（compact 档） |
| 对话框 | 圆角 28dp、宽 280-560、`surface_container_high` + elevation 3、图标 24dp、text 按钮右对齐间距 8dp |
| 进度 | 轨道 4dp、圆头、百分比文字在条外 |
| 队列列表行 | two-line 高 80dp、圆角 8dp、悬停 8% `on_surface` 墨层；第一行 28dp 序号 chip + 状态图标 + 文件名 + 右对齐状态文字；第二行 4dp 进度 + 百分比 + 40dp 图标按钮；文件名中间省略、完整路径进 tooltip |
| 卡片网格 | 主页/工具页按尺寸类别双列或单列；**设置页固定单列**（内容最大宽 1000dp），卡片按顺序排列、等宽对齐，避免双列压缩字段与同排卡片高度错位 |
| 开关 / 复选框 | 开关轨道 52×32（控件 60×40，四周 4dp 为 40dp 状态层安全区），未选中滑块 16dp / 选中 24dp，含墨层、动画、禁用 12%/38%；复选框 18dp；勾色用 `on_primary` |
| 设置行 | 标签/说明列占左侧剩余空间（字段标签至少 180dp）；字段控件列右对齐、统一 420dp 上限（可空整数行的开关+数值框为 168dp 紧凑组、数值框 100dp）；行宽 < 460dp 时字段行改为"标签在上、控件在下"堆叠；开关行控件同样贴右缘 |
| 路径行 | 描边字段 + 40dp tonal 图标按钮（folder_open，tooltip 为"浏览"）；图标替文字按钮节省约 36dp，长路径尽量完整显示 |
| 窗口 | 最小 440×480；单列设置页最窄卡片约 396dp，加紧凑页边距仍小于最小窗口宽度，因此不出现横向滚动 |

---

## 六、窗口尺寸类别（响应式）

| 类别 | 宽度 | 导航 | 页边距 | 卡片列数 | 页头字号 |
|---|---|---|---|---|---|
| compact | < 600 | 底部 NavigationBar（80dp） | 16 | 1 | 24 |
| medium | 600-839 | NavigationRail（仅图标） | 24 | 1 | 28 |
| expanded | ≥ 840 | NavigationRail（图标 + 标签） | 32 | 2 | 32 |

`WindowSizeClass.of(width)` 是唯一断点来源；页面通过
`set_size_class(size_class)` 调整布局，**禁止**再写像素断点或重复的宽度
同步逻辑。内容列最大宽度 1120dp 居中（超宽屏不把卡片拉成一条）。

---

## 七、QSS 与代码规范

### 7.1 QSS 命名规范

| 规范 | 约定 | 示例 |
|------|------|------|
| 命名法 | lowerCamelCase | `videoPathEdit` |
| 前缀 | 按组件类型 | `edit`/`btn`/`card`/`label`/`nav`/`page` |
| objectName | 全局唯一 | `videoPathEdit`、`startButton` |
| 选择器 | 优先 ID 精确匹配 | `QLineEdit#videoPathEdit` |
| **禁止** | 全局裸选择器污染 | 不允许 `QWidget{background}`、`QFrame{border}` |
| **禁止** | 在容器上设 widget 级 stylesheet | `parent.setStyleSheet("background: transparent; border: none;")` 会级联到子控件，把输入框描边抹掉；纯布局容器统一用 `objectName("transparentPane")` + 全局 ID 规则 |

**新组件接入步骤**：

1. `create_*()` 中 `setObjectName()`；
2. `theme/styles.py` 的 `MaterialStyle.generate_qss()` 增加 `QType#objectName`
   精确规则；
3. 颜色按用途分两条路：
   - **原生控件的外观**（输入框描边、菜单底色、滚动条把手……）写
     `palette(primary)` / `palette(outline)` 这类表达式，由 QPalette 解析；
     QSS 里**禁止**写死 `#RRGGBB`（否则切主题必须整树重设样式表）；
   - **自绘组件**从 `MaterialColors` 取 token 在 `paintEvent` 里画；
   - **单个标签的文字色**用 `set_text_color(label, colors.on_surface_variant)`，
     **禁止** `label.setStyleSheet("color: …")`：后者会创建 widget 级
     QStyleSheetStyle、写死控件调色板，主题切换时还要逐个重设（旧版每次
     切换有 200+ 次这种调用）。

### 7.2 图标替换流程

从 [Google Fonts Icons](https://fonts.google.com/icons) 搜索 Material Symbols
**Rounded**，下载 SVG：

1. 保存到 `gui/assets/icons/svg/<name>.svg`；
2. 在 `nav_icons.py` 的 `_ICON_FILES` 中注册；
3. 用 `make_icon_pixmap(name, color, size)` 使用（`size` 只允许
   20 / 24 / 40 三档）；
4. 一个控件只能挂一个 `QGraphicsEffect`；若需要 opacity 动画，不能同时
   挂 `QGraphicsDropShadowEffect`；
5. 图标颜色必须传 token，禁止硬编码 hex。
