# build\_exe - 可执行文件打包工具

将 ArknightsVideoPipeline 项目打包为 Windows 可执行文件(.exe)的自动化工具。

## 目录

- [脚本功能说明](#脚本功能说明)
- [环境要求及前置依赖](#环境要求及前置依赖)
- [安装与配置步骤](#安装与配置步骤)
- [打包模式与使用命令](#打包模式与使用命令)
- [参数说明](#参数说明)
- [常见问题排查](#常见问题排查与解决方案)
- [输出文件说明及目录结构](#输出文件说明及目录结构)

***

## 脚本功能说明

本工具基于 [PyInstaller](https://pyinstaller.org/) 实现，专门针对 ArknightsVideoPipeline 项目结构进行优化，提供以下核心功能：

### 1. 精准打包范围

- **仅打包** **`src/`** **目录**：不打包 MAA、output、config、docs、README 等非代码文件
- **可选打包** **`resource/`** **目录**：通过 `--include-resource` 参数控制
- **自动打包 GUI 资源**：`src/arknights_video_pipeline/gui/assets/` 下的图标资源会自动包含

### 2. 依赖分析与优化

- **AST 级导入分析**：使用 Python `ast` 模块解析源码中的所有 `import` 语句，精准识别实际使用的第三方库
- **自动排除未使用的包**：对比已安装包与实际使用包，自动生成 `--exclude-module` 列表
- **标准库清理（可选）**：通过 `--clean-stdlib` 参数排除未使用的标准库模块（如 `tkinter`、`unittest` 等），进一步减小体积
- **导入名映射**：处理 `cv2` → `opencv-python`、`PIL` → `Pillow` 等导入名与包名不一致的情况

### 3. 三种打包模式

| 模式         | 说明                       | 适用场景       |
| ---------- | ------------------------ | ---------- |
| `gui`      | 仅打包 GUI 版本，双击 exe 启动图形界面 | 普通用户使用     |
| `cli`      | 仅打包 CLI 版本，通过命令行参数控制     | 批处理、自动化场景  |
| `combined` | 合并打包，无参数启动 GUI，有参数启动 CLI | 需要兼顾两种使用方式 |

### 4. PROJECT\_ROOT 自动修正

项目源码通过向上查找 `pyproject.toml` 确定 `PROJECT_ROOT`，打包后该文件不存在。本工具生成的入口脚本会在导入业务模块前自动修正 `PROJECT_ROOT` 为 exe 所在目录，确保能正确定位 `config/`、`resource/`、`MAA/` 等外部资源。

### 5. 其他特性

- **进度提示**：打包过程分为 6 个阶段，每个阶段都有清晰的状态输出
- **错误处理**：完善的异常捕获和友好的错误提示
- **自动清理**：支持构建前清理旧输出，自动清理临时文件
- **使用说明生成**：打包完成后自动在输出目录生成 `使用说明.txt`

***

## 环境要求及前置依赖

### 系统要求

- **操作系统**：Windows 10/11（64位）
- **Python**：3.12 或更高版本
- **磁盘空间**：至少 2GB（用于构建缓存和输出）

### 必需依赖

```
# 项目运行依赖（已在 requirements.txt 中声明）
opencv-python>=4.8.0,<5
numpy>=1.24.0,<3
movielite>=0.1.0,<1
pictex>=0.1.0,<1
Pillow>=10.0.0,<12
tqdm>=4.65.0,<5
PyQt6>=6.6.0,<7

# 打包工具依赖（需额外安装）
pyinstaller>=6.0
```

### 外部工具

- **ffmpeg / ffprobe**：需在系统 PATH 中可用（用于视频验证和处理）
- **MAA**：运行时需要，但打包时不包含（需用户自行下载放置）

***

## 安装与配置步骤

### 1. 安装项目依赖

```bash
# 在项目根目录执行
pip install -r requirements.txt
```

### 2. 安装 PyInstaller

```bash
pip install pyinstaller>=6.0
```

### 3. 验证安装

```bash
# 验证 PyInstaller 安装
python -m PyInstaller --version

# 验证项目可正常导入
python -c "import arknights_video_pipeline; print('OK')"
```

### 4. 验证打包工具

```bash
# 查看帮助信息
python script/build_exe --help

# 仅执行依赖分析（不打包）
python script/build_exe --analyze-only
```

***

## 打包模式与使用命令

### 模式一：GUI 版本打包

打包纯图形界面版本，双击 exe 即可启动 GUI。

```bash
# 基本打包（目录模式，推荐）
python script/build_exe --mode gui

# 单文件模式（生成单个 .exe，启动较慢）
python script/build_exe --mode gui --onefile

# 包含 resource 资源目录
python script/build_exe --mode gui --include-resource

# 指定名称和图标
python script/build_exe --mode gui --name MyAVP --icon app.ico

# 清理标准库以减小体积
python script/build_exe --mode gui --clean-stdlib
```

### 模式二：CLI 版本打包

打包纯命令行版本，通过命令行参数控制视频处理流程。

```bash
# 基本打包
python script/build_exe --mode cli

# 单文件模式
python script/build_exe --mode cli --onefile

# 显示控制台窗口（CLI 默认显示，可用 --no-console 隐藏）
python script/build_exe --mode cli --no-console
```

### 模式三：合并版本打包

将 GUI 和 CLI 整合为单一可执行文件。

```bash
# 基本打包
python script/build_exe --mode combined

# 包含资源
python script/build_exe --mode combined --include-resource

# 单文件模式
python script/build_exe --mode combined --onefile
```

**合并版本的使用方式：**

```bash
# 无参数 → 启动 GUI
ArknightsVideoPipeline-combined.exe

# 有参数 → 启动 CLI
ArknightsVideoPipeline-combined.exe video.mp4 -b bg.png

# 生成配置文件
ArknightsVideoPipeline-combined.exe --init-config

# 强制启动 GUI（即使有其他参数）
ArknightsVideoPipeline-combined.exe --gui
```

### 仅分析依赖（不打包）

```bash
# 分析项目使用的依赖
python script/build_exe --analyze-only

# 分析并生成标准库排除列表
python script/build_exe --analyze-only --clean-stdlib
```

***

## 参数说明

### 核心参数

| 参数                   | 简写   | 默认值     | 说明                              |
| -------------------- | ---- | ------- | ------------------------------- |
| `--mode`             | `-m` | `gui`   | 打包模式：`gui` / `cli` / `combined` |
| `--onefile`          | -    | `False` | 使用单文件模式（默认目录模式）                 |
| `--include-resource` | -    | `False` | 打包 resource 资源目录                |
| `--clean-stdlib`     | -    | `False` | 排除未使用的标准库模块                     |

### 输出参数

| 参数                 | 简写   | 默认值     | 说明           |
| ------------------ | ---- | ------- | ------------ |
| `--name`           | `-n` | 自动生成    | 可执行文件名称      |
| `--output-dir`     | `-o` | `dist`  | 输出目录         |
| `--work-dir`       | `-w` | `build` | 构建工作目录       |
| `--icon`           | `-i` | 无       | 图标文件路径(.ico) |
| `--no-clean-build` | -    | `False` | 不清理旧输出       |

### 控制台参数

| 参数             | 说明                    |
| -------------- | --------------------- |
| `--no-console` | 隐藏控制台窗口（GUI/合并模式默认隐藏） |
| `--console`    | 显示控制台窗口（覆盖默认行为，用于调试）  |

### 高级参数

| 参数                       | 说明              |
| ------------------------ | --------------- |
| `--exclude MODULE`       | 额外排除的模块（可多次使用）  |
| `--hidden-import MODULE` | 额外的隐藏导入（可多次使用）  |
| `--project-root PATH`    | 项目根目录路径（默认自动检测） |
| `--analyze-only`         | 仅执行依赖分析，不打包     |

### 默认输出名称

| 模式         | 默认名称                              |
| ---------- | --------------------------------- |
| `gui`      | `ArknightsVideoPipeline-gui`      |
| `cli`      | `ArknightsVideoPipeline-cli`      |
| `combined` | `ArknightsVideoPipeline-combined` |

***

## 常见问题排查与解决方案

### 1. PyInstaller 未安装

**错误信息：**

```
[ERROR] PyInstaller 未安装，请执行: pip install pyinstaller
```

**解决方案：**

```bash
pip install pyinstaller>=6.0
```

### 2. 打包后 exe 无法找到 config/resource/MAA

**原因：** 打包后 `PROJECT_ROOT` 指向 exe 所在目录，需在该目录放置运行时资源。

**解决方案：**

确保 exe 所在目录结构如下：

```
output_dir/
├── ArknightsVideoPipeline-gui.exe   # 或目录
├── config/                          # 配置文件目录
│   ├── pipeline.json
│   ├── formation.json
│   ├── actions.json
│   ├── track.json
│   └── video_compose/
│       ├── style1.json
│       └── style2.json
├── resource/                        # 资源文件目录
│   ├── StartButton/
│   └── font/
└── MAA/                             # MAA 工具目录
```

**生成配置文件：**

```bash
# CLI 模式
ArknightsVideoPipeline-cli.exe --init-config

# GUI 模式（通过 -- 传递参数）
ArknightsVideoPipeline-gui.exe -- --init-config

# 合并模式
ArknightsVideoPipeline-combined.exe --init-config
```

### 3. 打包后 GUI 无法启动，提示 PyQt6 缺失

**原因：** PyInstaller 未能正确收集 PyQt6 的所有子模块。

**解决方案：**

工具已默认添加 `--collect-submodules PyQt6`，如仍有问题，可手动添加隐藏导入：

```bash
python script/build_exe --mode gui --hidden-import PyQt6.QtSvg --hidden-import PyQt6.QtSvgWidgets
```

### 4. 打包后视频处理报错 "ffmpeg not found"

**原因：** ffmpeg 未在系统 PATH 中。

**解决方案：**

- **方案一**：将 ffmpeg 安装到系统 PATH
  ```bash
  # Windows (使用 winget)
  winget install ffmpeg
  ```
- **方案二**：将 ffmpeg.exe 和 ffprobe.exe 放置在 exe 同目录下
- **方案三**：打包时通过 runtime\_hook 自动从注册表修复 PATH（工具已内置此功能）

### 5. 打包体积过大

**解决方案：**

```bash
# 1. 启用标准库清理
python script/build_exe --mode gui --clean-stdlib

# 2. 使用单文件模式（压缩更好，但启动较慢）
python script/build_exe --mode gui --onefile

# 3. 排除不需要的大型库
python script/build_exe --mode cli --exclude matplotlib --exclude scipy

# 4. 先分析依赖，确认排除列表
python script/build_exe --analyze-only
```

### 6. 单文件模式(onefile)启动缓慢

**原因：** 单文件模式每次启动都会将所有文件解压到临时目录。

**解决方案：**

- 使用目录模式(onedir)（默认），启动更快
- 如果必须使用单文件模式，可接受 5-10 秒的启动延迟

### 7. 打包过程中出现 "ModuleNotFoundError"

**原因：** 某些模块有动态导入，PyInstaller 无法自动检测。

**解决方案：**

```bash
# 添加隐藏导入
python script/build_exe --mode gui --hidden-import 模块名
```

### 8. 杀毒软件误报

**原因：** PyInstaller 打包的 exe 常被杀毒软件误报。

**解决方案：**

- 将 exe 添加到杀毒软件白名单
- 使用数字签名对 exe 进行签名
- 使用目录模式(onedir)而非单文件模式(onefile)，误报率更低

### 9. 打包后无法找到字体文件

**原因：** 字体文件在 `resource/font/` 目录下，未正确放置。

**解决方案：**

- 使用 `--include-resource` 参数打包资源
- 或手动将 `resource/` 目录复制到 exe 所在目录

### 10. 构建中断后无法重新打包

**解决方案：**

```bash
# 清理构建缓存
rmdir /s /q build
rmdir /s /q dist

# 重新打包
python script/build_exe --mode gui
```

***

## 输出文件说明及目录结构

### 目录模式(onedir)输出结构

```
dist/
└── ArknightsVideoPipeline-gui/          # 输出目录（名称取决于 --name）
    ├── ArknightsVideoPipeline-gui.exe   # 主程序
    ├── _internal/                        # PyInstaller 内部依赖
    │   ├── arknights_video_pipeline/    # 项目代码
    │   ├── PyQt6/                       # PyQt6 库
    │   ├── cv2/                         # OpenCV 库
    │   ├── numpy/                       # NumPy 库
    │   ├── movielite/                   # movielite 库
    │   ├── pictex/                      # pictex 库
    │   ├── PIL/                         # Pillow 库
    │   └── ...                          # 其他依赖
    ├── resource/                        # 资源目录（--include-resource 时存在）
    │   ├── StartButton/
    │   │   ├── BattleStartNormal.png
    │   │   ├── BattleStartAdverse.png
    │   │   ├── BattleStartExercise.png
    │   │   └── BattleStartRaid.png
    │   └── font/
    │       └── SOURCEHANSANSCN-HEAVY.OTF
    └── 使用说明.txt                     # 自动生成的使用说明
```

### 单文件模式(onefile)输出结构

```
dist/
└── ArknightsVideoPipeline-gui.exe       # 单个可执行文件
```

> **注意**：单文件模式不包含 `resource/` 目录，需手动放置。

### 运行时推荐目录结构

无论哪种打包模式，运行时都需要在 exe 所在目录放置以下内容：

```
程序目录/
├── ArknightsVideoPipeline-gui.exe       # 打包生成的 exe
├── config/                              # 配置文件（通过 --init-config 生成）
│   ├── pipeline.json                    # 全局流水线配置
│   ├── formation.json                   # 编队转文本配置
│   ├── actions.json                     # 操作转文本配置
│   ├── track.json                       # 开始按钮识别配置
│   └── video_compose/                   # 视频合成风格配置
│       ├── style1.json
│       └── style2.json
├── resource/                            # 资源文件
│   ├── StartButton/                     # 开始按钮模板图片
│   └── font/                            # 字体文件
├── MAA/                                 # MAA 作业识别工具
│   └── ...
├── ffmpeg.exe                           # ffmpeg（可选，如未在 PATH 中）
├── ffprobe.exe                          # ffprobe（可选，如未在 PATH 中）
└── output/                              # 输出目录（程序自动创建）
    └── <video_name>/                    # 按视频名分目录
        ├── copilot_*.json               # MAA 识别结果
        ├── formation_*.txt              # 编队文本
        ├── actions_*.txt                # 操作文本
        ├── track_result_*.json          # 跟踪结果
        ├── output_*.mp4                 # 最终输出视频
        └── report_*.json                # 处理报告
```

### 构建过程输出说明

打包过程分为 6 个阶段，每个阶段都有状态输出：

```
[1/6] 检查打包环境...          # 检查 Python、PyInstaller、源码目录
[2/6] 准备构建目录...          # 创建/清理输出和工作目录
[3/6] 分析依赖...              # AST 分析导入，生成排除列表
[4/6] 生成入口脚本...          # 生成带 PROJECT_ROOT 修正的入口脚本
[5/6] 执行 PyInstaller 打包... # 调用 PyInstaller（最耗时）
[6/6] 后处理...                # 复制资源、生成说明、统计大小
```

### 日志与调试

- **构建日志**：PyInstaller 的输出会直接打印到控制台
- **工作目录**：`build/` 目录包含 PyInstaller 的中间文件(.spec 等)
- **PyInstaller 命令**：构建时会打印完整的 PyInstaller 命令，便于调试

如需调试打包问题，可使用 `--console` 参数保留控制台窗口：

```bash
python script/build_exe --mode gui --console
```

***

## 工具源码结构

```
script/
├── __init__.py                          # script 包标记
└── build_exe/                           # 打包工具主目录
    ├── __init__.py                      # 包入口，导出 BuildConfig/BuildManager
    ├── __main__.py                      # CLI 入口（argparse 参数解析）
    ├── builder.py                       # 构建管理器（BuildConfig + BuildManager）
    ├── analyzer.py                      # 依赖分析器（AST 导入分析）
    ├── launchers.py                     # 入口脚本模板（GUI/CLI/合并）
    ├── runtime_hook.py                  # PyInstaller 运行时钩子
    └── README.md                        # 本文档
```

### 模块职责

| 模块                | 职责                                            |
| ----------------- | --------------------------------------------- |
| `__main__.py`     | CLI 参数解析，创建 BuildConfig 并调用 BuildManager      |
| `builder.py`      | 打包流程编排：环境检查→目录准备→依赖分析→入口生成→PyInstaller 调用→后处理 |
| `analyzer.py`     | AST 解析源码导入，对比已安装包，生成排除列表                      |
| `launchers.py`    | 生成三种模式的入口脚本，内置 PROJECT\_ROOT 修正逻辑             |
| `runtime_hook.py` | PyInstaller 运行时钩子，设置环境变量和 PATH                |

