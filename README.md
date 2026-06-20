# ArknightsVideoPipeline

明日方舟视频处理流水线 —— 一键完成视频识别、文本提取与视频合成。

## 项目简介

ArknightsVideoPipeline 是一个自动化视频处理工具，专为明日方舟（Arknights）游戏录像设计。它将 MAA 中的作业识别功能、OpenCV 模板匹配和 movielite 视频合成库整合为一条完整的处理流水线，从原始视频输入到最终合成视频输出，全程自动化。


**注意**：Maa目前已经取消对视频自动识别的维护与支持，因此本项目可能随时会停止维护。

<br />

## 核心功能

|  步骤 | 功能              | 说明                                  |
| :-: | --------------- | ----------------------------------- |
|  1  | 视频转 MAA 作业 JSON | 调用 MAA 中的作业识别功能，将游戏录像转换为结构化的作业 JSON |
|  2  | 编队配置转文本         | 解析 JSON，提取编队信息（干员、技能、模组等）           |
|  3  | 操作指令转文本         | 解析 JSON，提取操作指令（部署、技能、方向、延迟等）        |
|  4  | 开始按钮识别          | 使用 OpenCV 模板匹配，精确定位"开始"按钮出现的时间戳     |
|  5  | 视频合成            | 将视频叠加到底板图片上，并叠加编队/操作文本，输出最终视频       |

## 技术栈

- **Python 3.12+**
- **MAA 中的作业识别功能 (MaaAssistantArknights)** - 游戏录像作业识别功能
- **OpenCV** - 模板匹配与图像处理
- **movielite** - 视频合成引擎
- **ffmpeg / ffprobe** - 视频验证与处理
- **PIL (Pillow)** - 图片验证（可选）

## 项目结构

```
ArknightsVideoPipeline/
├── main.py                    # CLI 主入口
├── gui.py                     # GUI 主入口
├── src/arknights_video_pipeline/
│   ├── core/                  # 核心模块
│   │   ├── pipeline.py        # 流水线编排与 CLI 参数解析
│   │   ├── config.py          # 统一配置管理器
│   │   ├── logger.py          # 双通道日志系统（控制台 + 文件轮转）
│   │   ├── exceptions.py      # 自定义异常层次
│   │   ├── types.py           # 数据结构定义（dataclass）
│   │   ├── step_defs.py       # 流水线步骤统一定义
│   │   ├── utils.py           # 共享工具函数
│   │   ├── video_to_copilot.py    # 步骤1: 视频转 MAA JSON
│   │   ├── formation_to_text.py   # 步骤2: 编队转文本
│   │   ├── actions_to_text.py     # 步骤3: 操作转文本
│   │   ├── track_startbutton.py   # 步骤4: 开始按钮识别
│   │   ├── video_compose.py       # 步骤5: 视频合成 (style1)
│   │   ├── video_compose_style2.py # 步骤5: 视频合成 (style2)
│   │   └── video_compose_common.py # 视频合成公共工具
│   ├── gui/                   # 图形用户界面
│   │   ├── app.py             # QApplication 初始化
│   │   ├── main_window.py     # 主窗口
│   │   ├── components/        # GUI 组件
│   │   ├── theme/             # Material Design 3 主题
│   │   └── workers/           # 后台工作线程
│   └── service/               # 服务层
│       ├── pipeline_service.py # 流水线服务
│       ├── config_proxy.py     # GUI 配置代理
│       ├── pipeline_worker.py  # 流水线工作线程
│       └── report_model.py     # 报告数据适配
├── config/                    # 配置文件
│   ├── pipeline.json          # 全局流水线配置
│   ├── formation.json         # 编队转文本配置
│   ├── actions.json           # 操作转文本配置
│   ├── track.json             # 开始按钮识别配置
│   └── video_compose/         # 视频合成风格配置
│       ├── style1.json        # style1 风格（默认，底板+视频叠加）
│       └── style2.json        # style2 风格（全屏视频+底部字幕）
├── resource/                  # 资源文件
│   ├── StartButton/           # 开始按钮模板图片
│   └── font/                  # 字体文件
├── docs/                      # 文档
└── output/                    # 输出目录
```

## 安装指南

### 前置依赖

1. **Python 3.12+**
2. **ffmpeg** - 需在系统 PATH 中可用
3. **MAA 中的作业识别功能** - 项目内未包含 `MAAAssistantArknights`，需手动下载并放入项目目录。

### 安装步骤

```bash
# 1. 克隆项目
git clone <repository-url>
cd ArknightsVideoPipeline

# 2. 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

# 3. 安装依赖
pip install -r requirements.txt
```

## 基本使用

```bash
# 完整流水线（视频 + 背景板图片）
python main.py video.mp4 --background-image bg.png

# 指定输出目录
python main.py video.mp4 -b bg.png --output-dir results

# 指定视频合成风格
python main.py video.mp4 -b bg.png --style style1

# 跳过某些步骤
python main.py video.mp4 -b bg.png --skip-step track --skip-step compose

# 仅验证输入（不执行处理）
python main.py video.mp4 -b bg.png --dry-run

# 生成全部默认配置文件
python main.py --init-config

# 生成指定模块的配置文件
python main.py --init-config formation
python main.py --init-config track
```

> 更多 CLI 参数详见 [CLI 参数说明文档](docs/cli_reference.md)

## 配置说明

配置采用分层设计，优先级从高到低：

1. **CLI 参数** - 命令行传入的参数优先级最高
2. **pipeline.json** - 全局流水线配置
3. **子配置 JSON** - 各模块独立配置文件
4. **代码默认值** - 各模块的 `DEFAULT_CONFIG`

> 完整配置项说明详见 [配置文件说明文档](docs/configuration.md)

## 文档

| 文档                              | 说明            |
| ------------------------------- | ------------- |
| [快速入门](docs/quick_start_cli.md)     | 10 分钟完成基本功能验证 |
| [配置说明](docs/configuration.md)   | 所有配置项的详细说明    |
| [CLI 参考](docs/cli_reference.md) | 命令行参数完整手册     |
| [GUI 使用说明](docs/gui_guide.md) | 图形界面使用说明     |

## 贡献指南

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m "Add your feature"`
4. 推送分支：`git push origin feature/your-feature`
5. 提交 Pull Request

代码规范：

- 遵循 PEP 8 编码规范
- 使用类型注解（type hints）
- 保持模块间接口清晰

## 感谢

- **MAA 中的作业识别功能** [(MaaAssistantArknights)](https://github.com/MAAAssistantArknights/MAAAssistantArknights) - 提供游戏录像作业识别功能的工具

## 许可证

本项目仅供学习交流使用。

## 最后说明

本项目完全为Vibe Coding项目，不涉及任何商业用途。
