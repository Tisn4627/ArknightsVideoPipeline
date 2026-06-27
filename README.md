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

- **Maa** [(MaaAssistantArknights)](https://github.com/MAAAssistantArknights/MAAAssistantArknights) - 提供视频转作业Json功能和开始按钮底板图片

## 最后说明

本项目完全为Vibe Coding项目。
