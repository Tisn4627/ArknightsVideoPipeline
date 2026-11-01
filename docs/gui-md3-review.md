# 明日方舟视频流水线 GUI — Material Design 3 全面整改方案

> 范围：`src/arknights_video_pipeline/gui/` 全部界面（应用外壳 + 主页 / 设置页 / 工具页 / 关于页 + 消息对话框 + 工具窗口）。
> 约束：纯 PyQt6 原生实现，不引入任何第三方主题/UI 库；零新增运行时依赖；Windows 优先，同时保持 macOS/Linux 可运行。
> 本文档分两部分：**第一部分是审查结论（问题 + 影响）**，**第二部分是整改方案（目标设计系统 + 组件规格 + 实施与验收）**。

---

# 0. 结论摘要

## 0.1 总体判断

现有界面**借用了 MD3 的色值，但没有 MD3 的结构**。可以概括为四句话：

1. **色彩只有"点"没有"谱"**：17 个硬编码色值，缺 `surface_container_*`、`tertiary`、`inverse_*`、`scrim`、`surface_tint`，因此卡片 / 菜单 / 对话框只能共用同一个 surface，层级只能靠 1px 描边和投影硬撑。
2. **组件只有"壳"没有"态"**：按钮 5 种变体只落地 3 种（且 `elevated` 被降级成 text），hover/pressed 是整块换色而不是墨层，开关 / 复选框 / 页面切换没有任何过渡，全站唯一动效在导航栏。
3. **样式没有"源"只有"补丁"**：全局 `QWidget{background-color}` 与 `QFrame{border...}` 泄漏，逼出 30+ 处 `background: transparent` 与十几处 `border: none` 局部覆盖；输入框 QSS 存在 4 份拷贝，按钮样式存在 3 份拷贝。
4. **排版没有"阶"只有"数"**：13px / 18px / 22px / 48px / 600 字重散落各处，既不落在 MD3 type scale 上，也与非 token 化的 `QFont()` 混用，导致中英切换和 DPI 变化时比例漂移。

## 0.2 整改范围（一句话）

把散落在 20+ 个文件里的颜色、字号、圆角、间距、动效常量收敛成**唯一事实源**（HCT 色调系统 → 43 个颜色角色 → 排版 / 形状 / 间距 / 动效 / 状态 token），把 QSS 表达不了的交互态（墨层、过渡、焦点环）交给**自绘组件**，把像素断点换成 **MD3 窗口尺寸类别**。

## 0.3 验收口径

- `python -m pytest src/arknights_video_pipeline/tests` 全绿（现有约 370 个用例 + 新增用例）。
- `ruff check src/arknights_video_pipeline/gui` 无新增告警。
- 24 张截图逐项核对：2 主题（浅 / 深）× 3 宽度（compact 480 / medium 760 / expanded 1280）× 4 页面，无横向滚动条、无内容裁切、无未上色的透明块。
- 品牌观感回归护栏：由种子 `#6750A4` 生成的 `#6750A4 / #D0BCFF / #EADDFF / #21005D / #4F378B / #381E72` 等基线色必须原样复现。

---

# 第一部分：审查报告

## 1.0 审查方法与分级

- **方法**：以 MD3 规范条目为清单（color roles / tonal palettes / type scale / shape scale / elevation / state layers / motion / window size classes / component anatomy），逐条在代码中取证，记录「现状 → 偏差 → 影响」。
- **取证粒度**：文件名 + 行号（便于逐项复核）。
- **严重度**：
  - **P0（阻断）**：破坏整体风格统一的结构性缺陷，不修则其余整改无法收敛。
  - **P1（明显偏差）**：肉眼可辨的规范偏离，直接造成"形似而不神似"。
  - **P2（细节）**：影响有限，但累积后削弱一致性。

---

## 1.1 配色方案与色调系统

### A1 没有色调系统（P0）

**现状**：`theme/colors.py:60-108` 的 `light()` / `dark()` 直接写死十六进制值，不存在 seed、tonal palette、HCT 求解。

**偏差**：MD3 的颜色不是"挑出来的 40 个好看的色值"，而是**由种子色推导的 5 组色调板（primary / secondary / tertiary / neutral / neutral-variant）× 13 个色调（0-100）**，角色只是"色调板 + 色调号"的引用。

**影响**：角色之间的明度关系不可推导也不可校验。例如 `surface_container_low` 理应比 `surface` 高一档 tone，现有实现无法表达，于是"容器分层"只能靠描边和阴影伪造；任何一次微调都可能让浅色/深色失去对应关系；也无法支持 Material You。

### A2 颜色角色严重缺失（P0）

**现状**：`colors.py:16-50` 仅 17 个字段（primary / secondary / surface / background / error / outline 等）。

**缺失**：`tertiary` 四件套、`surface_dim`、`surface_bright`、`surface_container_lowest/low/container/high/highest`、`inverse_surface`、`inverse_on_surface`、`inverse_primary`、`scrim`、`surface_tint`。

**偏差**：MD3 的"层级"是由 `surface` 家族的 7 个色调表达的（窗口 → 卡片 → 菜单 → 对话框 → 抽屉逐级变亮/变暗），不是由边框和阴影表达的。

**影响**：这是"形似而不神似"的头号原因——卡片、页头、菜单、对话框全部落在同一个 `surface` 上，视觉上永远是"白底上叠白块"，只能加阴影把它推开；深色主题下更是所有容器糊成一片。

### A3 窗口底色不是 MD3 角色（P1）

**现状**：`background = #F5F0FA`（浅）/ `#121014`（深），`tests/test_theme_palette.py:61-64` 还把薰衣草色写成验收项。

**偏差**：MD3 里窗口底色就是 `surface`（或 `surface_container_lowest`），不存在独立的"淡薰衣草背景"。

**影响**：窗口底色（偏紫粉）与卡片 surface（偏紫白）色相/色度不同源，卡片浮在"另一种紫"上，整体色温割裂；深色下 `#121014` 与 `#141218` 又是一对近似但不相等的值，切换容器时会出现极轻微但可感知的色块边界。

### A4 状态色是 MD2 遗留（P1）

**现状**：`success=#2E7D32`、`warning=#ED6C02`（浅），`#81C784`、`#FFB74D`（深）。

**偏差**：这四个值来自 Material Design 2 / Materialize 体系，与 MD3 的 purple 种子无色调关系，且浅色 `#2E7D32` 在浅色表面上的对比度偏暗、深色 `#81C784` 又偏亮，缺乏对应的 container/on 角色。

**影响**：日志与状态标签出现"绿/橙补丁"，与主色系不同源；且没有 `success_container` 这类容器色，无法在卡片内做状态底。

### A5 语义色散落在组件内部（P0）

**现状**：
- `components/log_viewer.py:35-53` 内置两套共 10 个十六进制值（`#C0BCC4`、`#E6E1E5`、`#FFA0A0`、`#FF8A80`、`#B3261E`、`#ED6C02` …）；
- `components/material_checkbox.py:164` 勾选色硬编码 `#FFFFFF`；
- `components/material_card.py:38` 卡片默认底色硬编码 `#FFFBFE`；
- `main_window.py:322-343` 在 `_apply_skip_theme` 里手工拼接 `surface / on_surface_variant` 内联样式。

**偏差**：MD3 要求所有颜色来自角色 token；组件不得自持色值。

**影响**：主题切换必须依赖 `main_window.py:817-862` 里 20+ 处 `if getattr(...)` 手工级联，**漏一个就残留旧色**（代码注释已记录"深色模式下白块、`[INFO]` 几乎不可见"两次真实事故）。这是"每次加功能都会破坏一致性"的根源。

### A6 缺少 state layer 墨层（P0）

**现状**：`theme/styles.py:94-97` 按钮 hover 把底色换成 `primary_container`、文字换成 `on_primary_container`；`:99-102` pressed 换成 `on_primary_container` 底。

**偏差**：MD3 的状态反馈是**在原容器上叠加一层 `on_surface` 的低透明度墨层**（hover 8%、focus 10%、pressed 10%、dragged 16%），容器本色不变。filled 按钮 hover 应是"更深一点的紫"，而不是"变成淡紫底 + 深紫字"。

**影响**：悬停和按下看起来像"换了一个控件"，色彩跳跃大、层级瞬时反转；MD3 标志性的"墨层质感"完全缺失；而且因为 QSS 无法过渡，这种跳变是硬切。

### A7 禁用态不合规（P1）

**现状**：`styles.py:104-108` disabled 使用 `surface_variant` 底 + `on_surface_variant` 字。

**偏差**：MD3 禁用态是**容器 `on_surface` 12%、内容 38%**，即"几乎透明"，明确表达不可交互。

**影响**：`on_surface_variant` 在浅色下对比度约 4.6:1，禁用按钮看起来仍然"可点"，用户会反复点击；深色下 `#49454F` 底 + `#CAC4D0` 字对比度过高，与启用态难以区分。

---

## 1.2 字体排版层级

### B1 字号大量魔数（P1）

**现状**：13px 出现在 `settings_row_builders.py:121`、`material_checkbox.py:47,99`、`settings_page.py:489,714,1075,1111,1733,1763`、`text_range_tool.py:404,419,489,501,887`；48px Hero 出现在 `main_window.py:202`、`about_page.py:108`、`settings_page.py:227`、`tools_page.py:214`；另有 22px（`about_page.py:71`）、20px（`message_dialog.py:138`）、18px（`message_dialog.py:82`）。

**偏差**：MD3 type scale 只有 11 / 12 / 14 / 16 / 22 / 24 / 28 / 32 / 36 / 45 / 57。13px 和 48px 都不在阶梯上。

**影响**：正文 12/13/14 三档并存，读者无法建立"谁比谁重要"的稳定直觉；48px Hero 既不是 `display_medium`(45) 也不是 `display_large`(57)，在 600-840 的中等窗口里过大，导致标题频繁换行。

### B2 字重越档（P2）

**现状**：Hero、关于页标题、对话框标题使用 `font-weight: 600`（`main_window.py:202`、`about_page.py:71`、`message_dialog.py:82`）。

**偏差**：MD3 字体只使用 400（常规）与 500（中等），仅在极少数强调场景用 700。

**影响**：标题靠"更粗"而不是"更大"来区分层级，导致大标题与卡片标题（500）之间只有粗细差，没有尺寸差，视觉层级被压平；同时中文字体在 600 下容易糊成一团。

### B3 字距用百分比而非绝对像素（P2）

**现状**：`theme/typography.py:61-71` 用 `QFont.SpacingType.PercentageSpacing`，调用处传 -2 / -1 / +1，实际效果是 -2% / -1% / +1%。

**偏差**：MD3 的 tracking 是**绝对像素**（display_large -0.25px、title_medium +0.15px、label_large +0.1px）。

**影响**：字距随字号线性缩放——48px 标题被紧缩约 0.96px（过度）、11px 标签几乎无效果（无效），大字小字都调不准。

### B4 存在不走字体工厂的 `QFont`（P1）

**现状**：`settings_row_builders.py:200-205` 的 `_title_font()` 新建 `QFont()` 只设 `setPointSize(11)` 与字重，**不设 families**。

**偏差**：项目的中文可读性依赖 `typography.py` 的 `setFamilies` 回退链（Roboto → Noto Sans SC → 微软雅黑）。

**影响**：该字体回落到 Qt 平台默认字体，中文 Windows 上可能是宋体，于是同一张卡片里的标题与正文出现两套字形——这是最容易被用户察觉、又最难定位的"廉价感"来源。

### B5 px 与 pt 双轨（P1）

**现状**：`styles.py:40` 全局 `font-size: 14px`；`typography.py` 全部用 `setPointSize(14)`。

**偏差**：两者在 96 DPI 下相差约 33%（14px ≈ 10.5pt）。同一套界面同时存在两套度量单位。

**影响**：任何被 QSS 命中的控件（几乎所有原生控件）用 px，被 `setFont` 命中的控件（Hero、卡片标题、设置行标题）用 pt，两者比例不是设计值；高分屏缩放时偏差进一步放大，于是"有的标题大、有的标题小"。

### B6 无行高规范（P2）

**现状**：`message_dialog.py:91` 写了 `line-height: 1.5`。

**偏差**：**Qt QSS 不支持 `line-height`**，该声明被静默丢弃。

**影响**：多行正文行距等于字体默认行距，长文本挤在一起；开发者误以为已生效，后续不会再去修正——属于"假修复"。

---

## 1.3 组件形态

### C1 按钮变体名存实亡（P0）

**现状**：`styles.py:82-92` 给**所有** `QPushButton` 上 `primary` 填充；`material_button.py` 声明了 filled / tonal / outlined / text / elevated 五种变体，但 tonal 无任何样式、elevated 被映射成 `mdText`（`material_button.py:35`）。

**偏差**：MD3 明确按钮层级——filled（页面上唯一最高优先级）/ tonal（次高）/ outlined（中等）/ text（最低）/ elevated；一屏通常只有 1 个 filled。

**影响**：主页上"浏览""开始""取消"以及对话框按钮全是实心深紫，**主次完全消失**。这是"形似而不神似"最直观的表现：MD3 的克制感来自于"大量 text/outlined + 极少 filled"，而现状是"全是 filled"。

### C2 按钮高度不统一（P1）

**现状**：全局是 min-height 20 + padding 10/24 + 2px 边框 ≈ 44px；`message_dialog.py:203-204` 又叠 `setMinimumWidth(96)` / `setMinimumHeight(40)`。

**偏差**：MD3 按钮高度统一 40dp（小 32 / 大 48）。

**影响**：同一行里按钮与输入框（≈40px）不齐，出现 2-4px 错位；对话框按钮与页面按钮高度不同，跨上下文的"同一组件"不成立。

### C3 输入框形态不是 MD3（P1）

**现状**：`QLineEdit / QComboBox / QSpinBox / QDoubleSpinBox` 一律 `12px` 圆角 + `surface_variant` 底（`styles.py:159-184,357-373`；`settings_row_builders.py:36-115`；`file_selector.py:125-147`；`settings_page.py:1838-1906`）。

**偏差**：MD3 只有两种文本输入：**outlined**（4dp 圆角 + 1dp outline + 浮动标签 + 输入区 56dp 高）与 **filled**（顶部 4dp 圆角 + 底部 1dp 线）。不存在 12dp 圆角、`surface_variant` 底色的"圆角搜索框"形态。

**影响**：输入框与按钮（20px 全圆角）、卡片（20px）混在同一个表单里，圆角语言不成立；更严重的是**同一个输入框有 4 份 QSS 拷贝**，任何一处改动都会让主页 / 设置页 / 文件选择器出现色差（历史上已发生）。

### C4 聚焦时边框变粗导致内容位移（P1）

**现状**：常态 1px 边框，`focus` 变 2px（`styles.py:168-170,186-188,366-368`；`file_selector.py:140-142`）。

**偏差**：MD3 通过**内缩描边**或加焦点环表达聚焦，几何不变。`docs/gui-md3-theme.md:80` 也写着"聚焦态边框宽度与常态一致"。

**影响**：每次点击输入框，文字整体右移/下移 1px，产生肉眼可见的抖动；文档与代码自相矛盾，说明规范未被执行。

### C5 卡片用阴影而非色调分层（P1）

**现状**：`material_card.py` 20px 圆角（`paintEvent` 内硬编码 `radius = 20`），默认色硬编码 `#FFFBFE`，叠加单层 `QGraphicsDropShadowEffect`（`_ELEVATION_SPECS`：blur 16 / dy 2 / alpha 40），同时 `setAutoFillBackground(True)` + `paintEvent` **双绘**。

**偏差**：MD3 卡片是 12dp 圆角；filled 卡片**本就无阴影**，靠 `surface_container_low` 与窗口区分；elevated 才是 1 级阴影。

**影响**：所有卡片都"浮"起来，页面上没有"实心平面"的锚点，视觉噪声大；深色主题下黑阴影几乎不可见（代码只好 `alpha + 30` 硬补），形成"浅色糊、深色无"的两套观感；双绘还在主题切换时造成一次闪白。

### C6 全局 `QFrame` 规则泄漏（P0）

**现状**：`styles.py:48-52` 给**所有** `QFrame` 加 1px `outline_variant` 边框 + 16px 圆角 + `surface` 底。

**偏差**：MD3 中 `QFrame` 是布局容器，不应自带表面与描边。

**影响**：`QScrollArea`、分割线、卡片内部子框架全部被描边，于是代码里出现大量"反向修补"：`tools_page.py:69-79`、`main_window.py:121-128`、`settings_page.py:112-120` 都要单独写 `border: none; background: transparent`。**这是"风格混杂"最直接的物证**——一个选择器污染了整棵控件树。

### C7 导航栏选中指示器形态错误（P1）

**现状**：`navigation_rail.py:70-73` 的 item 固定 `64×56`；`paintEvent`（`:214-243`）把 **整个 item 的 rect** 画成胶囊（半径 = 高度/2 = 28），选中时铺满整块。

**偏差**：MD3 Navigation Rail 的 active indicator 是 **56×32、圆角 16 的胶囊，只包住 24dp 图标**，标签在胶囊下方独立显示；rail 宽 80dp。

**影响**：选中态视觉重量过大（整块 64×56 的紫色），四个导航项挤在一起更像"侧边标签页"而不是 rail；未选中项与选中项的可点击区域与视觉区域不一致，命中感发虚。

### C8 对话框不是 MD3 Basic Dialog（P1）

**现状**：`message_dialog.py` 用 20px 圆角卡片、标题 18px/600、图标是 40dp 彩色圆里塞字符 `"i" / "!" / "?"`、按钮 filled + outlined、最小 360×180。

**偏差**：MD3 Basic Dialog：28dp 圆角、`surface_container_high` 容器、24dp 图标（无彩色底盘）、标题 `headline_small`（24sp）、正文 `body_medium`（14sp）、**text 按钮**右对齐、宽度 280–560dp。

**影响**：对话框是用户注意力最集中的时刻，却呈现"第三方卡片弹窗"的气质：彩色圆底 + 大粗标题 + 实心按钮，与页面内克制的 MD3 语言完全脱节；字符图标在不同字体回退下基线偏移，中英文下还会错位。

### C9 全站没有 FAB（P1）

**现状**：grep 无任何 FAB 实现；主页的"添加视频"是藏在卡片内的小图标按钮（`batch_video_list.py:108-117`）。

**偏差**：FAB 是 MD3 的"主操作锚点"，通常位于右下、elevation 3、圆角 full（regular 56dp）或 16dp（extended）。

**影响**：首页缺少稳定、可预期的"下一步在哪"提示；添加视频这一高频操作需要用户先找到列表卡片再看小图标，操作路径不透明。

### C10 开关缺状态与动效（P2）

**现状**：`material_switch.py:75-117` 尺寸 52×32 正确，但无 hover/focus 墨层、无滑块位移动画、无 thumb 图标、无 disabled 态绘制。

**偏差**：MD3 switch 滑块有 ~200ms 位移与轨道变色，hover 有 8% 墨层，disabled 走 12%/38%。

**影响**：点开关时滑块"瞬移"，与导航栏 180ms 的动画形成两种手感；禁用后外观不变，用户会反复尝试。

### C11 复选框勾色错误（P1）

**现状**：`material_checkbox.py:164` 勾固定 `#FFFFFF`。

**偏差**：MD3 勾色是 `on_primary`。深色主题 `primary = #D0BCFF`（浅紫），`on_primary = #381E72`（深紫）。

**影响**：深色主题下"浅紫底 + 白勾"，对比度约 1.7:1，勾几乎看不见——这是一个真实的可用性缺陷，不只是风格问题。此外无 hover/focus 墨层、无勾选动画。

### C12 进度条是 MD2 形态（P2）

**现状**：`styles.py:222-234` 高 16px、圆角 8px、百分比文字压在条内。

**偏差**：MD3 线性进度轨道 4dp、圆头、文字在条外。

**影响**：进度条看起来像 Windows 经典控件，与 4dp 基线的其余元素（滑轨 4px、分割线）不成体系；文字压在色块上还会出现低对比（浅紫底 + 白字）。

### C13 滚动条常驻且抢注意力（P2）

**现状**：`styles.py:251-299` 8px 轨道常驻不透明、handle hover 变 `primary`。

**偏差**：MD3 滚动条默认半透明、hover 才加深。

**影响**：深色主题下右侧一条常亮灰条，成为"多余的一根线"；hover 变紫又让滚动条短暂地比内容更醒目。

### C14 图标风格混族（P2）

**现状**：`nav_icons.py:22-45` 注释明写：导航项用 **Material Icons Filled**，复选框与批量列表用 **Material Icons Rounded**；对话框用字符 `i / ! / ?`。

**偏差**：一个产品只应使用一套图标族（MD3 对应 Material Symbols Rounded 或 Filled），字符不是图标体系的一部分。

**影响**：同屏出现"直角图标 + 圆角图标 + 字符"，细看即露怯；字符图标还会随字体回退改变形态。

### C15 没有 icon button 组件（P2）

**现状**：`batch_video_list.py:108-117` 的 4 个操作（JSON / 上移 / 下移 / 删除）是 `QPushButton` + 20-24px 图标。

**偏差**：MD3 icon button 是 40dp 命中区 + 24dp 图标 + 圆形墨层，分 standard / filled / tonal / outlined 四变体。

**影响**：密集操作区看起来像"工具栏按钮堆叠"，没有 MD3 的轻盈感；20px 命中区偏小，也不符合 40dp 最小触控目标。

### C16 Tab 与导航形态重复（P2）

**现状**：`styles.py:435-451` 的 `QTabBar::tab` 选中用 20px 胶囊底 + `primary_container`。

**偏差**：MD3 的 primary tabs 是"下划线 + 图标/文字变色"；胶囊是 segmented button 的形态。

**影响**：tab 选中态与 rail 选中态长得一样，用户无法从形态区分"顶部导航"与"页内标签"；层级语言重复。

---

## 1.4 圆角与阴影

### D1 圆角魔数（P2）

**现状**：16 / 20 / 12 / 10 / 9 / 8 / 6 / 5 / 4 / 2 px 并存（`styles.py` 全文、`batch_video_list.py:250,278,284`、`message_dialog.py:137`）。

**偏差**：MD3 shape scale 只有 0 / 4 / 8 / 12 / 16 / 28 / full。

**影响**：12（输入框）与 10（chip）与 8（菜单）之间没有规则，新增控件时无法判断该用哪一档，于是继续产生新魔数；圆角不统一时，卡片与内部元素无法"同心"，视觉上会显得脏。

### D2 阴影不符合 MD3 elevation（P1）

**现状**：单层 `QGraphicsDropShadowEffect`（blur 16 / dy 2 / alpha 40）。

**偏差**：MD3 每级 elevation 是 **key shadow（umbra，低模糊高偏移）+ ambient shadow（penumbra，高模糊低偏移）** 两层；深色主题用 `surface_tint` 叠色来表达抬升，而不是加深黑色阴影。

**影响**：浅色下阴影偏灰、边缘糊；深色下阴影不可见（被迫 `alpha + 30`）；同一份 elevation 规格无法同时服务浅/深两套主题。

### D3 同一张卡片三处圆角（P2）

**现状**：`paintEvent` 画 20px 圆角（`material_card.py:96-97`）、全局 `QFrame` 是 16px（`styles.py:51`）、`QFrame#materialCard` 又是 20px（`styles.py:54-58`）。

**影响**：主题变更或控件尺寸变化时三者不同步，边框与自绘背景出现"错位的双轮廓"（真实可复现）。

### D4 对话框无 scrim 色（P2）

**现状**：依赖系统默认遮罩。

**偏差**：MD3 的遮罩使用 `scrim`（`#000000`）配固定不透明度。

**影响**：遮罩色与主题无关，深色主题下遮罩偏灰、与背景色温不一致。

---

## 1.5 间距与栅格

### E1 间距无基线（P1）

**现状**：页面边距 40（`main_window.py:102`、`settings_page.py:149`、`about_page.py:42`）；卡片内边距 20（`material_card.py:112`）与 28（`message_dialog.py:58`）并存；网格间距 24 / 32；行内 12 / 16 / 8 / 10 / 6 / 4。

**偏差**：MD3 使用 4dp 基线栅格。

**影响**：同类卡片内边距 20 vs 28 造成"哪个是对的"的困惑；40px 页面边距在 720 宽窗口里吃掉 1/9；元素间 6/10/12 混杂让纵向节奏失去可预测性——这是"看起来没对齐但又说不出哪不对"的典型来源。

### E2 固定像素标签宽度（P1）

**现状**：`settings_row_builders.py:166` 的 `lbl.setFixedWidth(140)`；`main_window.py:372` 的 `setFixedWidth(72)`。

**偏差**：MD3 表单使用响应式列或堆叠布局。

**影响**：切到英文后标签更长被截断（"Maximum concurrent" > 140px），切到中文又留大片空白；窄窗时列宽不变导致输入框被压缩——这正是"响应式不一致"的具体表现。

### E3 断点是像素魔数且逻辑重复（P1）

**现状**：`main_window.py:875-880` 用 960 / 720 两个魔数；`894-911` 靠 `setMaximumWidth(viewport)` 硬同步四个页面；`resizeEvent`（871-911）与 `eventFilter`（913-950）**重复实现同一套宽度同步**。

**偏差**：MD3 使用窗口尺寸类别 compact(<600) / medium(600-839) / expanded(840+)。

**影响**：拖拽窗口时卡片宽度在断点附近来回跳变，偶尔闪出横向滚动条；四份重复逻辑意味着改断点要改八处，任何一处漏改就出现某页宽某页窄。

### E4 没有 spacing token（P1）

**现状**：间距数值以字面量散落在 20+ 文件。

**影响**：调整视觉密度需要改几十处；无法保证"同一组件在不同页面间距相同"，跨页面一致性只能靠人肉记忆。

---

## 1.6 动效与状态反馈

### F1 全站只有一处动效（P1）

**现状**：`navigation_rail.py:76-78` 的 180ms `InOutCubic` 指示器淡入淡出是唯一的动画。

**偏差**：MD3 的 standard / emphasized 缓动为 `cubic-bezier(0.2, 0, 0, 1)` / `(0.05, 0.7, 0.1, 1)`，时长 200–500ms。

**影响**：只有导航"会动"，按钮、开关、复选框、折叠、弹窗全部硬切，交互手感割裂；且 180ms `InOutCubic` 与 MD3 曲线不同，动效语言也不统一。

### F2 没有状态层过渡（P1）

**现状**：hover/pressed 由 QSS 静态换色（QSS 不支持 transition）。

**影响**：状态切换是"闪变"，鼠标滑过一排按钮时会看到若干个色块同时跳变，产生闪烁感。

### F3 页面切换无过渡（P2）

**现状**：`main_window.py:653-664` 直接 `setCurrentWidget`。

**影响**：切换导航时内容瞬间替换，缺少 MD3 的空间连续性；用户短暂失去"我在哪一层"的定位感。

### F4 键盘焦点不可见（P1）

**现状**：`styles.py:110-112` 用 2px `secondary` 边框做 focus，与 hover 边框互相覆盖；`MaterialSwitch`（`:29`）与 `MaterialCheckBox`（`:41`）设了 `StrongFocus` 却完全不绘制焦点。

**偏差**：MD3 要求 2dp 焦点环 + 明确的可聚焦区域。

**影响**：纯键盘用户无法判断焦点在哪（Tab 到开关/复选框时毫无提示），属于可访问性缺陷。

### F5 禁用没有过渡与分组语义（P2）

**现状**：运行中批量调用 5 组 `set_*_enabled`（`main_window.py:779-794`）。

**影响**：整页控件同时"闪白/变灰"，没有渐进反馈；且分散的启用/禁用方法容易漏掉新增控件。

---

## 1.7 响应式

### G1 三档缺失

**现状**：只有"宽 / 窄"两态，窄态仅把 rail 从 88 收到 56（`navigation_rail.py:314-327`）。

**影响**：480 宽时仍然是一列 56px 的侧栏，内容区只剩约 380px，卡片内表单被压成"标签 + 极小输入框"；无法达到移动端可用的信息密度。

### G2 Rail 无顶部/底部 slot 且未贴顶

**现状**：`navigation_rail.py:277` `addStretch(0)` 在 items 之前、`:286` 又 `addStretch()` 在之后，两者权重不同，items 被挤在中间偏下。

**影响**：rail 顶部留白异常，"菜单 / FAB 槽位"缺失，与 MD3 rail 结构不符。

### G3 对话框与工具窗固定尺寸

**现状**：对话框最小 360×180（`message_dialog.py:44`）；工具窗最小 720×520（`tools_page.py:60`）。

**影响**：1366×768 的低分屏 + 系统缩放 150% 时，工具窗可能超出可用区域，标题栏被推出屏幕。

### G4 Hero 不随尺寸降级

**现状**：四页固定 48px。

**影响**：compact 档标题占据 2 行以上，首屏有效内容被挤出。

### G5 日志区固定最小高

**现状**：`main_window.py:226` `setMinimumHeight(240)`。

**影响**：窄窗竖排时进度卡与日志卡互相挤压，出现双层滚动条。

---

## 1.8 工程性根因（决定整改能否长期保持）

| 编号 | 问题 | 证据 | 后果 |
|---|---|---|---|
| H1 | 全局 `QWidget{background-color}` 强制不透明 | `styles.py:36-42` | 30+ 处 `background: transparent` 补丁 |
| H2 | 内联 QSS 重复实现 | 输入框 4 份、按钮 3 份（`styles.py` / `button_qss.py` / `file_selector.py` / `settings_row_builders.py` / `settings_page.py:1838-1906`） | 改一处漏三处，必然漂移 |
| H3 | 主题切换靠手工级联清单 | `main_window.py:817-862` | 新增控件必忘刷新，深色主题反复出 bug |
| H4 | 测试把旧色值当天条 | `tests/test_theme_palette.py:44-64` 断言 `#FFFBFE` / `#F5F0FA` | 改色板必然失败，倒逼"不敢改" |
| H5 | 文档与代码矛盾 | `docs/gui-md3-theme.md:80` 要求聚焦边框等宽，代码是 1px→2px | 规范失效，后续继续按错的方式扩散 |

---

## 1.9 偏差总表（按严重度）

| # | 偏差 | 严重度 | 影响一句话 | 整改项 |
|---|---|---|---|---|
| A1 | 无色调系统 | P0 | 角色间明度关系不可推导 | 2.2 |
| A2 | 缺 22 个颜色角色 | P0 | 容器无层级，靠阴影伪造 | 2.3 |
| A5 | 语义色散落组件 | P0 | 主题切换靠手工级联，必漏 | 3.1 / 4.1 |
| A6 | 无 state layer | P0 | 悬停像换控件，无墨层质感 | 2.7 / 3.2 |
| C1 | 按钮变体失效 | P0 | 全站皆 filled，主次消失 | 3.2 |
| C6 | 全局 QFrame 泄漏 | P0 | 到处描边 + 到处补丁 | 3.1(styles) |
| H1 | 全局 QWidget 底色 | P0 | 30+ 透明补丁 | 3.1 |
| H3 | 手工主题级联 | P0 | 新增控件必忘刷新 | 4.1(ThemeController) |
| A3 | 非 MD3 窗口底色 | P1 | 色温割裂 | 2.3 |
| A4 | MD2 状态色 | P1 | 绿橙补丁不同源 | 2.3 |
| A7 | 禁用态不合规 | P1 | 禁用看起来可点 | 2.7 |
| B1 | 13/48px 魔数 | P1 | 排版失去节奏 | 2.4 |
| B4 | 裸 `QFont()` | P1 | 同屏两套字形 | 2.4 |
| B5 | px/pt 双轨 | P1 | 标题大小比例漂移 | 2.4 |
| C2 | 按钮高度不一 | P1 | 同行错位 2-4px | 3.2 |
| C3 | 输入框非 MD3 | P1 | 圆角语言不成立 + 4 份拷贝 | 3.3 |
| C4 | 聚焦 1px→2px | P1 | 聚焦抖动 1px | 3.3 |
| C5 | 卡片用阴影 | P1 | 无实心锚点、深色阴影失效 | 3.4 |
| C7 | Rail 指示器过大 | P1 | 像侧边标签页 | 3.6 |
| C8 | 对话框非 MD3 | P1 | 注意力焦点处风格脱节 | 3.8 |
| C9 | 无 FAB | P1 | 主操作不可预期 | 3.5 |
| C11 | 深色勾色不可见 | P1 | 真实可用性缺陷 | 3.9 |
| D2 | 阴影非双层 | P1 | 浅色糊、深色无 | 2.6 |
| E1 | 间距无基线 | P1 | 对齐感缺失 | 2.5 |
| E2 | 固定标签宽 | P1 | 中英切换截断 | 3.3 / 4.4 |
| E3 | 断点魔数 + 重复 | P1 | 缩放抖动、横向滚动条 | 4.1 |
| E4 | 无 spacing token | P1 | 改密度要改几十处 | 2.5 |
| F1 | 动效仅一处 | P1 | 手感割裂 | 2.8 / 5 |
| F2 | 无状态过渡 | P1 | 状态闪变 | 3.2 |
| F4 | 焦点不可见 | P1 | 键盘不可用 | 3.2 / 3.9 |
| B2 | 600 字重 | P2 | 层级靠粗细不靠尺寸 | 2.4 |
| B3 | 百分比字距 | P2 | 大字过度、小字无效 | 2.4 |
| B6 | 无效 line-height | P2 | 多行正文拥挤 | 2.4 |
| C10 | 开关无动效/禁用 | P2 | 瞬移 + 禁用无感 | 3.9 |
| C12 | 进度条 MD2 | P2 | 16px 厚条压字 | 3.10 |
| C13 | 滚动条常驻 | P2 | 多余一根亮线 | 3.1 |
| C14 | 图标混族 | P2 | 直角/圆角/字符混排 | 3.11 |
| C15 | 无 icon button | P2 | 操作区像工具栏 | 3.2 |
| C16 | Tab 用胶囊 | P2 | 与 rail 形态重复 | 3.1 |
| D1 | 圆角魔数 | P2 | 无法同心、继续增生 | 2.5 |
| D3 | 卡片三处圆角 | P2 | 双轮廓 | 3.4 |
| D4 | 无 scrim | P2 | 遮罩与主题无关 | 3.8 |
| G1-G5 | 响应式不足 | P1/P2 | 窄窗不可用 | 4.1-4.3 |

---

# 第二部分：整改方案

## 2. 目标设计系统

### 2.1 三层架构

```
GuiConfig(theme, dynamic_color, seed_color)
        │
        ▼
ThemeController ──► HCT 色调生成器 ──► 五组 TonalPalette
        │                                   │
        │                                   ▼
        │                            Scheme（43 个角色）
        │                                   │
        ├──► MaterialStyle（QSS + QPalette）│
        └──► theme_changed(MaterialColors) ─┘
                     │
                     ├──► 原子组件（自绘墨层 / 焦点环 / 动效）
                     └──► 复合组件（导航 / 对话框 / 列表）
                                  ▲
                       WindowSizeClass（compact/medium/expanded）
```

- **Token 层**：`hct.py`（色彩空间，纯标准库）、`scheme.py`（角色派生）、`colors.py`（稳定外观对象）、`shape.py`、`spacing.py`、`motion.py`、`state.py`、`typography.py`。
- **样式层**：`styles.py`（全局 QSS）、`palette.py`（原生控件兜底）、`theme_controller.py`（唯一调度入口）。
- **组件层**：原子（按钮 / 图标按钮 / 输入容器 / 卡片 / FAB / 开关 / 复选框 / 进度）+ 复合（Rail / Bar / 对话框 / 页头 / 列表 / 日志）。

### 2.2 色调系统（HCT）

**为什么必须 HCT**：MD3 的颜色由"种子色的 HCT 色相/色度 → 固定色调取值"生成。用 HCT 而不是 OKLCH，可以直接用基线色做回归护栏——种子 `#6750A4` 必须原样生成 `#6750A4`、`#D0BCFF`、`#EADDFF`、`#21005D`、`#4F378B`、`#381E72`，这也是现有品牌色。

**色度常量**（五组色调板）：

| 色调板 | 色相 | 色度 | 说明 |
|---|---|---|---|
| primary | 种子色相 | `max(48, 种子色度)` | 品牌主色，保证品牌紫不褪色 |
| secondary | 种子色相 | 16 | 次要强调 |
| tertiary | 种子色相 + 60 | 24 | 对比强调（MD3 标准做法） |
| neutral | 种子色相 | 4 | surface 家族 |
| neutral-variant | 种子色相 | 8 | outline / surface_variant |
| error | 25（固定） | 84（固定） | 不随种子变化 |
| success（扩展） | 取自 `#386A20` | — | 非 MD3 标准角色，业务状态用 |
| warning（扩展） | 取自 `#7D5700` | — | 同上 |

**求解算法**：sRGB ↔ 线性 ↔ XYZ(D65) ↔ CAM16；HCT 的 tone 直接等于 CIE L*，因此给定 (hue, chroma, tone) 时对 CAM16 的 J 做二分使 `L*(Y) = tone`；若结果超出 sRGB 色域，则在保持色相与色调的前提下二分降低色度直至落入色域边界。所有结果按 `(hue, chroma, tone)` 缓存。

**验证锚点**（必须逐项通过）：

| 色调 | 期望值 |
|---|---|
| P40 / P80 / P90 / P10 / P30 / P20 | `#6750A4` / `#D0BCFF` / `#EADDFF` / `#21005D` / `#4F378B` / `#381E72` |
| S40 / S90 / S10 | `#625B71` / `#E8DEF8` / `#1D192B` |
| T40 / T90 / T30 | `#7D5260` / `#FFD8E4` / `#633B48` |
| N98 / N96 / N94 / N92 / N90 / N87 / N10 / N6 / N4 | `#FEF7FF` / `#F7F2FA` / `#F3EDF7` / `#ECE6F0` / `#E6E0E9` / `#DED8E1` / `#1D1B20` / `#141218` / `#0F0D13` |
| NV50 / NV60 / NV80 / NV90 / NV30 | `#79747E` / `#938F99` / `#CAC4D0` / `#E7E0EC` / `#49454F` |

> 容差：tone ±2、色相 ±3（浮点实现差异），但上述基线色在 8bit 量化后应完全一致。

### 2.3 颜色角色全表（43 个）

| 角色 | 浅色 | 深色 |
|---|---|---|
| primary | P40 `#6750A4` | P80 `#D0BCFF` |
| on_primary | P100 `#FFFFFF` | P20 `#381E72` |
| primary_container | P90 `#EADDFF` | P30 `#4F378B` |
| on_primary_container | P10 `#21005D` | P90 `#EADDFF` |
| secondary | S40 `#625B71` | S80 `#CCC2DC` |
| on_secondary | S100 `#FFFFFF` | S20 `#332D41` |
| secondary_container | S90 `#E8DEF8` | S30 `#4A4458` |
| on_secondary_container | S10 `#1D192B` | S90 `#E8DEF8` |
| tertiary | T40 `#7D5260` | T80 `#EFB8C8` |
| on_tertiary | T100 `#FFFFFF` | T20 `#492532` |
| tertiary_container | T90 `#FFD8E4` | T30 `#633B48` |
| on_tertiary_container | T10 `#31111D` | T90 `#FFD8E4` |
| error | E40 `#B3261E` | E80 `#F2B8B5` |
| on_error | E100 `#FFFFFF` | E20 `#601410` |
| error_container | E90 `#F9DEDC` | E30 `#8C1D18` |
| on_error_container | E10 `#410E0B` | E90 `#F9DEDC` |
| surface | N98 `#FEF7FF` | N6 `#141218` |
| on_surface | N10 `#1D1B20` | N90 `#E6E0E9` |
| surface_variant | NV90 `#E7E0EC` | NV30 `#49454F` |
| on_surface_variant | NV30 `#49454F` | NV80 `#CAC4D0` |
| outline | NV50 `#79747E` | NV60 `#938F99` |
| outline_variant | NV80 `#CAC4D0` | NV30 `#49454F` |
| surface_dim | N87 `#DED8E1` | N6 `#141218` |
| surface_bright | N98 `#FEF7FF` | N24 `#3B383E` |
| surface_container_lowest | N100 `#FFFFFF` | N4 `#0F0D13` |
| surface_container_low | N96 `#F7F2FA` | N10 `#1D1B20` |
| surface_container | N94 `#F3EDF7` | N12 `#211F26` |
| surface_container_high | N92 `#ECE6F0` | N17 `#2B2930` |
| surface_container_highest | N90 `#E6E0E9` | N22 `#36343B` |
| inverse_surface | N20 `#322F35` | N90 `#E6E0E9` |
| inverse_on_surface | N95 `#F5EFF7` | N20 `#322F35` |
| inverse_primary | P80 `#D0BCFF` | P40 `#6750A4` |
| scrim | N0 `#000000` | N0 `#000000` |
| surface_tint | P40 `#6750A4` | P80 `#D0BCFF` |
| success / on_success | 扩展板 40 / 100 | 80 / 20 |
| success_container / on_success_container | 扩展板 90 / 10 | 30 / 90 |
| warning / on_warning | 扩展板 40 / 100 | 80 / 20 |
| warning_container / on_warning_container | 扩展板 90 / 10 | 30 / 90 |

> `background` 字段保留（40+ 处调用点兼容），语义改为 `surface`；窗口底色由尺寸类别决定取 `surface` 或 `surface_container_lowest`。

**容器层级用法**（这是"色块分层"的核心规则）：

| 平面 | 角色 |
|---|---|
| 窗口 / 页面背景 | `surface` |
| 卡片（filled） | `surface_container_low` |
| 菜单 / 下拉浮层 | `surface_container` |
| 对话框 | `surface_container_high` |
| 抽屉 / 模态大面板 | `surface_container_highest` |
| 输入框（filled 变体） | `surface_container_highest` |

**有意变更（需在测试与文档中显式说明）**：

| 项 | 旧值 | 新值 | 原因 |
|---|---|---|---|
| `surface` 浅色 | `#FFFBFE`（N99） | `#FEF7FF`（N98） | 现行 MD3 规范 |
| `on_surface` 浅色 | `#1C1B1E` | `#1D1B20` | 现行 MD3 规范 |
| `background` 浅色 | `#F5F0FA` | `#FEF7FF` | 取消非标准"薰衣草底" |
| `background` 深色 | `#121014` | `#141218` | 与 surface 统一 |
| `success` / `warning` | MD2 色 | 扩展色调板派生 | 色相协调 |

### 2.4 排版比例

统一为 **px 单轨**（`QFont.setPixelSize` + QSS px），字距用 `AbsoluteSpacing`，行高由布局间距实现（QSS 无 line-height）。

| Role | Size | Weight | Line height | Tracking |
|---|---|---|---|---|
| display_large | 57 | 400 | 64 | -0.25 |
| display_medium | 45 | 400 | 52 | 0 |
| display_small | 36 | 400 | 44 | 0 |
| headline_large | 32 | 400 | 40 | 0 |
| headline_medium | 28 | 400 | 36 | 0 |
| headline_small | 24 | 400 | 32 | 0 |
| title_large | 22 | 400 | 28 | 0 |
| title_medium | 16 | 500 | 24 | 0.15 |
| title_small | 14 | 500 | 20 | 0.1 |
| body_large | 16 | 400 | 24 | 0.5 |
| body_medium | 14 | 400 | 20 | 0.25 |
| body_small | 12 | 400 | 16 | 0.4 |
| label_large | 14 | 500 | 20 | 0.1 |
| label_medium | 12 | 500 | 16 | 0.5 |
| label_small | 11 | 500 | 16 | 0.5 |

**页面头映射**：expanded → `display_medium`(45/400)；medium / compact → `display_small`(36/400)。取消 600 字重与 48px。

**替换对照**（旧 → 新）：

| 旧 | 新 |
|---|---|
| Hero 48px / 600 | display_medium 45/400（宽）/ display_small 36/400（窄） |
| 卡片标题 16px / 500 | title_medium 16/500（保持不变，但走工厂） |
| 关于页标题 22px / 600 | headline_small 24/400 |
| 对话框标题 18px / 600 | headline_small 24/400 |
| 设置行标签 13px / 500 | label_large 14/500（或 body_medium 14/400） |
| 复选框文本 13px | body_medium 14/400 |
| 导航标签 12px / 500 | label_medium 12/500（保持不变，但走工厂） |
| 日志正文 | `mono` body_small 12/400 |

### 2.5 形状、间距与栅格

**形状**（只允许这些档位）：

| Token | 值 | 用途 |
|---|---|---|
| none | 0 | 分割线、表格 |
| extra_small | 4 | 输入框、菜单项、工具提示 |
| small | 8 | chip、小卡片内元素 |
| medium | 12 | 卡片 |
| large | 16 | FAB（extended）、悬浮面板 |
| extra_large | 28 | 对话框 |
| full | 999 | 按钮、开关、胶囊指示器、头像 |

**间距**（4dp 基线）：

| Token | 值 | 典型用途 |
|---|---|---|
| xs | 4 | 图标与文字微距 |
| s | 8 | 按钮内图标间距、列表图标间距 |
| m | 12 | 表单行内间距、卡片内元素 |
| l | 16 | 卡片内边距（compact）、页边距（compact） |
| xl | 24 | 卡片间距、区块间距 |
| xxl | 32 | 页边距（expanded）、页面头到内容 |
| xxxl | 40 | 大区块分隔 |

**栅格与页边距**：

| 尺寸类别 | 宽度 | 页边距 | 卡片列数 | 卡片内边距 | 页头字号 | 导航外壳 |
|---|---|---|---|---|---|---|
| compact | < 600 | 16 | 1 | 16 | 36 | NavigationBar（底部 80dp） |
| medium | 600-839 | 24 | 1 | 16 | 36 | NavigationRail（仅图标 80dp） |
| expanded | ≥ 840 | 32 | 2 | 20 | 45 | NavigationRail（图标 + 标签 80dp） |

内容区最大宽度 1200dp 居中（超宽屏不拉伸）。

### 2.6 阴影与 elevation

| Level | 用途 | key shadow | ambient shadow |
|---|---|---|---|
| 0 | 卡片（filled）、页面 | 无 | 无 |
| 1 | 卡片（elevated）、搜索栏 | 0 1px 2px / 30% | 0 1px 3px / 15% |
| 2 | 菜单、下拉、chip | 0 2px 6px / 30% | 0 1px 4px / 15% |
| 3 | FAB、对话框 | 0 4px 8px / 30% | 0 1px 6px / 15% |
| 4 | 导航抽屉、模态面板 | 0 6px 10px / 30% | 0 2px 8px / 15% |
| 5 | 最高层浮层 | 0 8px 12px / 30% | 0 4px 10px / 15% |

实现说明：Qt 一个控件只能挂一个 `QGraphicsDropShadowEffect`，因此单 effect 取 key shadow 的偏移与 alpha、blur 取 ambient 的扩散半径；深色主题对 alpha 做 +8% 补偿并叠加 `surface_tint` 提亮表面色（`surface + tint @ 5%`），不再单纯加深黑色。

### 2.7 状态层（state layer）

| 状态 | 不透明度 | 叠色 |
|---|---|---|
| hover | 0.08 | `on_surface`（filled 按钮用 `on_primary`） |
| focus | 0.10 | 同上 + 2dp 焦点环 |
| pressed | 0.10 | 同上 |
| dragged | 0.16 | 同上 |
| disabled 容器 | 0.12 | `on_surface` |
| disabled 内容 | 0.38 | `on_surface` |

**焦点环**：2dp，颜色 `primary`，与控件外沿偏移 2dp；输入类控件用**内缩描边**（常态 1dp → 聚焦 2dp 但绘制在内侧）保证几何不变。

### 2.8 动效

| Token | 时长 | 用途 |
|---|---|---|
| short1 | 100ms | 墨层淡入（hover / press） |
| short2 | 150ms | 复选框勾选、图标切换 |
| medium1 | 200ms | 开关滑块、折叠展开、对话框出现 |
| medium2 | 250ms | 导航指示器、FAB 展开 |
| long1 | 300ms | 页面切换 |
| long2 | 400ms | 大面板进出 |

| 曲线 | cubic-bezier |
|---|---|
| standard | (0.2, 0, 0, 1) |
| standard_decelerate | (0, 0, 0, 1) |
| standard_accelerate | (0.3, 0, 1, 1) |
| emphasized | (0.2, 0, 0, 1) + 长时长 |
| emphasized_decelerate | (0.05, 0.7, 0.1, 1) |
| emphasized_accelerate | (0.3, 0, 0.8, 0.15) |

原则：**只动绘制属性**（opacity / progress），不做几何动画，避免布局抖动与像素断言不稳定。`Motion.enabled = False` 时动画直接落值（测试 / 低配环境）。

### 2.9 图标

- 统一 **Material Symbols Rounded，24×24 viewBox**（替换现有 Filled/Rounded 混用）。
- 尺寸档：20dp（密集列表）、24dp（标准）、40dp（空态/大按钮内）。
- 全部走 `make_icon_pixmap(name, color, size)`，颜色由 token 传入；新增 `add / close / expand_more / palette / folder_open / play_arrow / warning / info / error` 等。
- 禁止字符图标；对话框图标改为 24dp SVG。
- 命中区：图标按钮 40dp，列表行内图标按钮 40dp。

---

## 3. 组件规格与改造清单

### 3.1 全局样式（`theme/styles.py`）

**必须删除**：
- `QWidget { background-color: ... }`（H1）
- `QFrame { border: 1px solid ...; border-radius: 16px; }`（C6）
- 所有 `QPushButton` 的"默认 filled"语义

**改为**：
```
QWidget { color: on_surface; font-family: ...; }      /* 无背景 */
QMainWindow, QDialog, #pageRoot { background: surface; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
```

**补齐**：菜单、下拉、tooltip、tab（下划线）、slider、scrollbar（半透明）、list/table（行高 56、选中 `secondary_container`）、progress（4dp）、segmented button、chip。

### 3.2 按钮 / 图标按钮

| 变体 | 容器 | 内容 | hover | pressed | disabled |
|---|---|---|---|---|---|
| filled | primary | on_primary | primary + on_primary 8% | +10% | on_surface 12% / 38% |
| tonal | secondary_container | on_secondary_container | 8% | 10% | 同上 |
| elevated | surface_container_low + level1 | primary | 8% primary | 10% | 同上 |
| outlined | transparent + 1dp outline | primary | 8% primary | 10% | outline 12% |
| text | transparent | primary | 8% primary | 10% | 同上 |
| icon（standard） | transparent 40dp | on_surface_variant | 8% | 10% | 38% |

- 高度 40dp（小 32 / 大 48），圆角 full，左右内距 24dp，图标 18dp + 间距 8dp。
- 自绘 `paintEvent`：圆角矩形 + 墨层（`QPropertyAnimation` 驱动 opacity）+ 焦点环。
- 兼容既有属性名 `mdOutlined / mdText`，新增 `mdFilled / mdTonal / mdElevated`。

### 3.3 文本输入（新增 `material_text_field.py`）

- outlined：高 56dp、圆角 4dp、1dp `outline`；聚焦 1dp→2dp `primary`（内缩，不改几何）；错误态 `error` 2dp + supporting text。
- 浮动标签：`label_small`，未聚焦且空值时居中（16dp 缩进），聚焦或有值时上移到边框缺口（paint 位移 + 字号插值，不触发 relayout）。
- `attach(widget)` 可包装现有 `QLineEdit / QComboBox / QSpinBox`，使设置页无需替换控件类型；内部控件背景透明、无边框。
- 删除 `styles.py`、`file_selector.py`、`settings_row_builders.py`、`settings_page.py:1838-1906` 的 4 份字段 QSS。

### 3.4 卡片

- 圆角 12dp；`filled`（`surface_container_low`，无阴影）/ `elevated`（level1）/ `outlined`（1dp `outline_variant`）。
- 去掉 `autoFillBackground` 双绘，统一 `paintEvent` 单次绘制。
- 内边距 16（compact/medium）/ 20（expanded）。

### 3.5 FAB

- regular：56dp 圆形，图标 24dp，elevation 3。
- extended：高 56dp、圆角 16dp、左右内距 20dp、图标 + `label_large` 文字。
- 位置：主页右下，距安全区 24dp；compact 档再上移 80dp 避开 NavigationBar。
- 动效：出现 200ms fade + scale（0.9→1.0，只改 opacity 与绘制缩放）。

### 3.6 导航

| 项 | NavigationRail | NavigationBar |
|---|---|---|
| 位置 | 左侧 | 底部 |
| 尺寸 | 宽 80dp | 高 80dp |
| item | 56 高（图标胶囊 56×32 + 标签 12/500） | 宽均分（最多 5 项） |
| 指示器 | 56×32 圆角 16 `secondary_container` | 64×32 圆角 16 |
| 选中图标/文字 | `on_secondary_container` | 同 |
| 未选中 | `on_surface_variant` | 同 |
| hover | 8% `on_surface` | 同 |
| 动画 | 250ms emphasized | 200ms standard |
| 顶部 slot | 菜单/FAB（可选） | — |
| 底部 slot | 设置/头像（可选） | — |

### 3.7 页头（新增 `page_header.py`）

`display_medium`（expanded）/ `display_small`（medium/compact）+ `body_medium` 副标题 + 可选 trailing 操作；替换四处 48px 内联样式。

### 3.8 对话框

- 圆角 28dp、`surface_container_high`、宽 280–560、内边距 24。
- 图标 24dp（`info` / `warning` / `error` SVG，颜色 `secondary` / `error`），无彩色底盘。
- 标题 `headline_small`，正文 `body_medium`（行距 20，由布局实现）。
- 按钮：text 按钮，右对齐，间距 8dp；主操作 `filled` 仅用于破坏性确认。
- scrim：`scrim` 32%，`QDialog` 自定义遮罩层。
- 保留 `InfoDialog / WarningDialog / CriticalDialog / ConfirmDialog` 公共 API。

### 3.9 开关 / 复选框

- 开关：52×32、轨道圆角 full、thumb 24（选中）/ 16（未选中）、选中 thumb 带 `check` 图标；200ms emphasized 位移；hover 8% 墨层；disabled 12%/38%。
- 复选框：18dp、圆角 2dp、选中 `primary` + `on_primary` 勾（修正深色不可见）、150ms 勾选动画、hover/focus 墨层、支持 tristate。

### 3.10 进度

- 4dp 轨道、圆头、`primary` 指示、可选 stop indicator；百分比文字移到条外（`label_large`）。
- 列表行内进度条与状态文本合并显示（`body_small` + 百分比）。

### 3.11 列表行与图标按钮

- 行高 56dp、hover 8% 墨层、选中 `secondary_container`、圆角 4dp。
- 行内操作统一 40dp icon button，图标 20dp。
- 拖放空态：1dp dashed `outline` + `surface_container_lowest` 底。

### 3.12 日志视图

- 级别色改为由 token 派生：`DEBUG → on_surface_variant`、`INFO → on_surface`、`WARNING → warning`（深色取 80 色调）、`ERROR/CRITICAL → error`。
- 等宽字体走统一工厂；保留 2000 行上限与"仅在底部时自动滚动"。

---

## 4. 页面与响应式

### 4.1 应用外壳与尺寸类别

- `WindowSizeClass.of(width)`：compact < 600 / medium 600–839 / expanded ≥ 840。
- 单一 `_apply_size_class()` 驱动：导航外壳（Rail ↔ Bar）、页边距、卡片列数、页头字号、日志最小高。
- 删除 `resizeEvent` 与 `eventFilter` 中重复的 `setMaximumWidth` 同步（合并为一次布局约束；页面根控件用 `QSizePolicy` + 布局 `setSizeConstraint`，不再手动限宽）。
- 导航切换 fade 150ms（`QGraphicsOpacityEffect` 加在页面根控件，动画结束移除）。
- 主题切换统一走 `ThemeController.apply(dark, seed, dynamic)` → `theme_changed` 信号；组件构造时订阅，删除 `main_window._toggle_theme` 的 20+ 处手工清单。

### 4.2 主页

页头（标题 + 说明）→ 输入配置卡（背景图、风格、跳过步骤、开始/取消）→ 视频文件卡（列表 + 空态）→ 运行状态卡（4dp 进度 + 状态文本）→ 日志卡；右下角 extended FAB「添加视频」。

### 4.3 设置页

页头 → 语言卡 → 外观卡（浅色/深色 segmented + 动态色彩开关 + 种子色板）→ 高级开关卡（折叠 + `expand_more` 旋转 200ms）→ 各配置分组卡；字段行统一"标签 + 描边输入框"，窄档改为上下堆叠（标签在上）。**不改动任何业务信号与公开方法名**。

### 4.4 工具页 / 关于页

- 工具页：页头 + 索引卡（24dp 图标 + 标题 + 描述 + text 按钮"打开"）。
- 关于页：页头 + 居中信息卡（96dp 图标、`headline_small` 名称、`body_medium` 描述）。

### 4.5 动态色彩设置（新增）

- `GuiConfig` 新增 `dynamic_color: bool`（默认 `True`）与 `seed_color: str`（默认 `#6750A4`，含 `#RRGGBB` 校验与非法值回退）。
- 设置页：开关 + 调色板（预置 8 个种子 + 自定义取色，复用 `material_color_picker.py`）。
- 关闭动态色彩 → 回到基线紫；切换立即生效并持久化到 `config/gui.json`。
- 新增文案需同时写入 `resource/locales/zh-CN.json` 与 `en-US.json`。

---

## 5. 实施计划（阶段与出口条件）

| 阶段 | 内容 | 主要文件 | 出口条件 |
|---|---|---|---|
| **P0 Token** | HCT、色调板、43 角色、shape/spacing/motion/state、排版重写 | `theme/hct.py`、`scheme.py`、`colors.py`、`shape.py`、`spacing.py`、`motion.py`、`state.py`、`typography.py`、`__init__.py` | 基线色断言全过；`MaterialColors.light()/dark()/from_seed()` 可用 |
| **P1 样式收敛** | 重写全局 QSS、删除裸选择器、palette 重映射、回收内联样式 | `theme/styles.py`、`palette.py`、`button_qss.py` | 三页无透明块/无多余描边；输入框只剩一份 QSS |
| **P2 主题调度** | ThemeController + 信号订阅 + app 初始化 | `theme/theme_controller.py`、`app.py`、`main_window.py` | 主题切换无手工清单；新增控件自动跟随 |
| **P3 原子组件** | 按钮、图标按钮、输入框、卡片、FAB、开关、复选框、进度 | `components/material_*.py`（新增 4 个） | 组件级测试通过；五变体可见地分层 |
| **P4 复合组件** | Rail、Bar、对话框、页头 | `navigation_rail.py`、`navigation_bar.py`、`message_dialog.py`、`page_header.py` | 指示器 56×32；对话框 28dp/text 按钮 |
| **P5 页面改造** | 主窗口尺寸类别、FAB 落位、四页收敛、动态色彩 | `main_window.py`、`settings_page.py`、`settings_row_builders.py`、`tools_page.py`、`about_page.py`、`batch_video_list.py`、`log_viewer.py`、`gui_config.py`、locales | 三档宽度无横滚；英文标签不截断 |
| **P6 验收** | 测试重写与新增、文档、24 张截图核对 | `tests/*`、`docs/gui-md3-theme.md`、`docs/gui_guide.md` | pytest 全绿、ruff 无新增、截图通过 |

依赖关系：P0 → P1 → P2；P3 依赖 P0/P1；P4 依赖 P3；P5 依赖 P2/P4。

---

## 6. 质量保障

### 6.1 测试矩阵

| 文件 | 内容 |
|---|---|
| `tests/test_md3_hct.py`（新） | 色调板复现基线；任意种子不崩溃；色度/色调边界（0/100、超色域） |
| `tests/test_md3_scheme.py`（新） | 43 角色完整性；明暗对应（light.primary=P40，dark.primary=P80）；state/elevation/shape/spacing/type scale token 值 |
| `tests/test_material_components.py`（新） | 按钮五变体高度与属性；输入框浮动标签状态机；FAB 尺寸；对话框圆角与 text 按钮；开关/复选框颜色与禁用透明度；进度 4dp |
| `tests/test_window_size_class.py`（新） | 600/840 边界；导航外壳切换；页边距与列数 |
| `tests/test_theme_palette.py`（改） | 按新 surface 语义与 Window 映射重写断言 |
| `tests/test_navigation_rail.py`（改） | 指示器采样改为 56×32 胶囊区域；hover 改为墨层混色预期 |
| `tests/conftest.py`（改） | 默认 `Motion.enabled = False`，避免像素断言抖动 |

### 6.2 视觉验收

24 张截图（2 主题 × 3 宽度 × 4 页面），逐项核对清单：

- [ ] 所有间距为 4 的倍数
- [ ] 圆角只出现 0/4/8/12/16/28/full
- [ ] 字号只出现 type scale 中的值
- [ ] 字重只有 400/500
- [ ] 卡片/菜单/对话框表面色互不相同（层级可辨）
- [ ] 无横向滚动条、无内容裁切、无透明漏底
- [ ] 键盘 Tab 全程可见焦点
- [ ] 深浅主题切换后无残留旧色块

### 6.3 性能

- 色调板与角色按 `(seed, dark)` 缓存；QSS 保留 `(colors, family)` 缓存。
- 图标按 `24dp × DPR` 栅格化并 `lru_cache`；禁止任意尺寸入参撑爆缓存。
- 列表行禁用 effect；页面切换 fade 只加在根控件且动画结束移除。

### 6.4 风险与对策

| 风险 | 对策 |
|---|---|
| QSS 不支持 line-height / letter-spacing / transition | 排版走 QFont，动效走 paintEvent + QPropertyAnimation |
| 一个 widget 只能一个 QGraphicsEffect | 卡片默认无阴影（MD3 filled 本就无），仅 FAB/对话框/菜单用 |
| 删除全局 `QWidget`/`QFrame` 规则导致容器漏底 | 逐页核对后再删，先加显式上色再移除全局规则 |
| `settings_page.py` 1900 行改动风险 | 只换样式与容器，不动业务信号；回归 `test_ffmpeg_path` / `test_config_proxy` / `test_recognition_tool` |
| QComboBox 弹出列表圆角不生效 | 视图设 `Qt.Popup|FramelessWindowHint|NoDropShadowWindowHint` 实测，不成立改委托绘制 |
| 颜色断言阻断 | 基线紫回归护栏 + 显式记录两处有意变更 |

### 6.5 回滚策略

按阶段提交（P0…P6 各一次），每阶段结束测试全绿；任一阶段出现不可控回归时，回退该阶段提交即可，不影响已完成的 Token 层。

---

## 附录 A：旧值 → 新值 速查

| 位置 | 旧 | 新 |
|---|---|---|
| 浅色 surface | `#FFFBFE` | `#FEF7FF` |
| 浅色 on_surface | `#1C1B1E` | `#1D1B20` |
| 浅色窗口底 | `#F5F0FA` | `#FEF7FF` |
| 深色窗口底 | `#121014` | `#141218` |
| 卡片底 | `#FFFBFE`（硬编码） | `surface_container_low` |
| 卡片圆角 | 20 | 12 |
| 对话框圆角 | 20 | 28 |
| 输入框圆角 | 12 | 4 |
| 按钮高度 | ≈44 | 40 |
| 进度条高 | 16 | 4 |
| Hero 字号/字重 | 48 / 600 | 45 / 400（宽）、36 / 400（窄） |
| 设置标签字号 | 13 / 500 | 14 / 500 |
| 复选框勾色 | `#FFFFFF` | `on_primary` |
| 按钮 hover | `primary_container` 底 | `primary` + 8% `on_primary` 墨层 |
| 按钮 disabled | `surface_variant` + `on_surface_variant` | `on_surface` 12% / 38% |

## 附录 B：新增/修改文件总览

**新增**：`theme/hct.py`、`theme/scheme.py`、`theme/shape.py`、`theme/spacing.py`、`theme/motion.py`、`theme/state.py`、`theme/theme_controller.py`、`theme/window_size.py`、`components/material_icon_button.py`、`components/material_text_field.py`、`components/material_fab.py`、`components/material_progress.py`、`components/navigation_bar.py`、`components/page_header.py`、`tests/test_md3_hct.py`、`tests/test_md3_scheme.py`、`tests/test_material_components.py`、`tests/test_window_size_class.py`、`assets/icons/svg/{add,close,expand_more,palette,folder_open,play_arrow,warning}.svg`。

**修改**：`theme/{colors,typography,styles,palette,button_qss,gui_config,__init__}.py`、`components/{material_button,material_card,material_checkbox,material_switch,navigation_rail,message_dialog,progress_card,file_selector,log_viewer,batch_video_list,settings_row_builders,settings_page,tools_page,about_page,__init__}.py`、`components/tools/*.py`、`main_window.py`、`app.py`、`assets/icons/nav_icons.py`、`resource/locales/{zh-CN,en-US}.json`、`tests/{conftest,test_theme_palette,test_navigation_rail}.py`、`docs/{gui-md3-theme,gui_guide}.md`。

**不动**：`theme/titlebar.py`（DWM 实现）、`core/`、`service/`、`resource/` 大体积资源。
