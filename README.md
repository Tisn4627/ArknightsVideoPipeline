# ArknightsVideoPipeline

<p align="center">
  <img src="icon.png" alt="ArknightsVideoPipeline" width="200">
</p>

明日方舟视频处理流水线 —— 一键完成视频识别、文本提取与视频合成。

## 项目简介

ArknightsVideoPipeline 是一个自动化视频处理工具，专为明日方舟（Arknights）游戏录像设计。它将视频识别功能（recognition 后端默认 / MAA 后端可选）、OpenCV 模板匹配和 movielite 视频合成库整合为一条完整的处理流水线，从原始视频输入到最终合成视频输出，全程自动化。

> **说明**：Maa 已停止对视频自动识别的维护与支持。本项目的步骤 1 默认使用
> [ArknightsVideoRecognition](https://github.com/Tisn4627/ArknightsVideoRecognition)
> 子模块（纯 Python 重写的视频转作业 JSON 实现）作为识别后端，不再依赖 MAA 的
> 视频识别；MAA 调用保留为可选后端（`--backend maa`），可无缝回退。

## 核心功能

|  步骤 | 功能              | 说明                                  |
| :-: | --------------- | ----------------------------------- |
|  1  | 视频转作业 JSON | 默认调用 recognition 后端（ArknightsVideoRecognition 子模块），也可切换 MAA 后端，将游戏录像转换为结构化的作业 JSON |
|  2  | 编队配置转文本         | 解析 JSON，提取编队信息（干员、技能、模组等）           |
|  3  | 操作指令转文本         | 解析 JSON，提取操作指令（部署、技能、方向、延迟等）        |
|  4  | 开始按钮识别          | 使用 OpenCV 模板匹配，精确定位"开始"按钮出现的时间戳     |
|  5  | 视频合成            | 将视频叠加到底板图片上，并叠加编队/操作文本，输出最终视频       |

## 双识别后端

| 后端 | 说明 | 依赖 |
| --- | --- | --- |
| `recognition`（默认） | 纯 Python 视频识别（[ArknightsVideoRecognition](https://github.com/Tisn4627/ArknightsVideoRecognition) 子模块），自带 214M 模型/地图/头像资源，开箱即用 | 仅 pip 依赖 |
| `maa`（可选回退） | 调用 MAA 项目的 `VideoRecognition` 任务 | 需本地安装 MAA（`--maa-path`） |

切换方式：

```bash
# 使用默认 recognition 后端（无需任何额外配置）
python main.py video.mp4 -b bg.png

# 指定关卡（识别失败时的兜底手段）
python main.py video.mp4 -b bg.png --stage 2-10

# 回退到 MAA 后端
python main.py video.mp4 -b bg.png --backend maa --maa-path C:/MAA
```

配置文件中通过 `copilot_backend` 键切换，详见 [配置说明](docs/configuration.md)。

## 克隆与资源同步

recognition 识别资源（约 214M）由 `src/ArknightsVideoRecognition` 子模块提供。
首次克隆后需初始化子模块并同步资源到顶层 `resource/recognition/`：

```bash
# 1. 初始化子模块
git submodule update --init --recursive

# 2. 同步资源（符号链接模式，零拷贝；Windows 无符号链接权限时回退复制模式）
python script/sync_recognition_resources.py --mode=link
# 或: python script/sync_recognition_resources.py --mode=copy

# 3. 安装依赖（含 recognition 后端所需 onnxruntime / rapidocr-onnxruntime）
pip install -e .
```

> 本仓库当前为直接放置的子模块 checkout；若以 git 方式管理，请先执行
> `git submodule add https://github.com/Tisn4627/ArknightsVideoRecognition src/ArknightsVideoRecognition`
> 建立子模块关联（`.gitmodules` 已预置）。

## 视频要求

与 MAA 对视频的要求一致：视频需无模拟器边框和 Windows 标题栏，分辨率为 1080P，宽高比为 16:9。请勿使用助战干员，MAA 目前的视频转作业 JSON 功能不支持识别助战干员。

## 文档

| 文档                              | 说明            |
| ------------------------------- | ------------- |
| [快速入门](docs/quick_start_cli.md)     | 10 分钟完成基本功能验证 |
| [配置说明](docs/configuration.md)   | 所有配置项的详细说明    |
| [CLI 参考](docs/cli_reference.md) | 命令行参数完整手册     |
| [GUI 使用说明](docs/gui_guide.md) | 图形界面使用说明     |
| [合并方案](docs/merge_plan.md)    | Pipeline × Recognition 合并方案设计 |

## 贡献指南

代码规范：

- 遵循 PEP 8 编码规范
- 使用类型注解（type hints）
- 保持模块间接口清晰

## 许可证

- 本项目代码遵循 [LICENSE](LICENSE) 声明。
- `resource/recognition/` 目录下的识别资源（模型、地图数据、头像库等）源自
  `src/ArknightsVideoRecognition/resource/`，遵循其上游（Maa 等）的 **AGPL-3.0** 许可，
  详见 [NOTICE](NOTICE)。
- `resource/StartButton/` 开始按钮底板图片由 **Maa** 提供。

## 感谢

- **Maa** [(MaaAssistantArknights)](https://github.com/MAAAssistantArknights/MAAAssistantArknights) - 提供视频转作业Json功能和开始按钮底板图片
- **ArknightsVideoRecognition** [(Tisn4627/ArknightsVideoRecognition)](https://github.com/Tisn4627/ArknightsVideoRecognition) - 纯 Python 视频识别后端实现

## 最后说明

本项目完全为Vibe Coding项目。
