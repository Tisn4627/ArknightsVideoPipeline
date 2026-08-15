# ArknightsVideoPipeline × ArknightsVideoRecognition 合并方案

> 状态：方案已实施（2026-08-08）
> 日期：2026-08-07
> 涉及仓库：
> - 父项目：`https://github.com/Tisn4627/ArknightsVideoPipeline`（GPL-2.0）
> - 子项目：`https://github.com/Tisn4627/ArknightsVideoRecognition`（资源 AGPL-3.0）

> **实施调整说明（相对原方案）**：
> 1. 原方案的"Git submodule + `script/sync_recognition_resources.py` 同步资源"已改为
>    **彻底 vendor**：`src/arknights_video_recognition/` 的代码直接入库（排除其
>    `resource/`、`tests/`、`uv.lock`）；识别资源（约 216M）直接入库于
>    顶层 `resource/`（avatar/config/data/ocr/onnx/template/tile，与 font/locales 同层）。
>    克隆后零额外步骤。`sync_recognition_resources.py` 与 `test_sync_resources.py` 已删除。
> 2. 子模块方式（§5.3、§6、§8 等章节）保留为历史方案描述，不再适用于当前仓库。
>    识别资源更新方式：在 Recognition 上游仓库更新后，手动将新资源复制入库并提交。
> 3. 打包（§9）：`builder.py` 已为 Recognition 代码补 `--hidden-import` 与
>    `--paths src/arknights_video_recognition`；`runtime_hook.py` 已设置
>    `AVR_RESOURCE_DIR` 指向打包内 `resource/`。
> 4. 资源自动同步：主仓库新增独立 `.github/workflows/sync-resources.yml`（每周一
>    08:00 UTC 定时 + 手动触发，直接更新本仓库顶层 resource/ 并自动提交）。
>    原子仓库（ArknightsVideoRecognition 上游）自身的 sync-resources.yml 已整体
>    注释停用（2026-08-08，上游提交 7f30007），避免两侧重复同步；vendor 内
>    `.github/workflows/` 保留该文件的全注释副本：GitHub Actions 只扫描仓库根
>    `.github/workflows/`，vendor 内的文件不会被执行，副本仅供对照参考（见 §8.3）。

---

## 1. 背景与目标

### 1.1 背景

`ArknightsVideoPipeline`（下称 **Pipeline**）是一条明日方舟视频处理流水线，包含 5 个步骤：

| 步骤 | 功能 | 实现方式 |
| :-: | --- | --- |
| 1 | 视频转 MAA 作业 JSON | **调用 MAA 的 `asst.Asst` Python 库**（`core/video_to_copilot.py`） |
| 2 | 编队配置转文本 | 解析步骤 1 的 JSON |
| 3 | 操作指令转文本 | 解析步骤 1 的 JSON |
| 4 | 开始按钮识别 | OpenCV 模板匹配 |
| 5 | 视频合成 | movielite |

**核心痛点**：步骤 1 依赖 MAA 的 `VideoRecognition` 任务，而 MAA 已宣布**停止维护视频自动识别功能**。Pipeline 随时可能因 MAA 升级或资源变动而失效。

`ArknightsVideoRecognition`（下称 **Recognition**）正是用 Python 重写了 MAA 的"视频转标准作业 JSON"功能，接受战斗录像输入，输出符合 Maa copilot schema 的作业 JSON。它自带 214M 资源（ONNX 模型、OCR 模型、地图数据、头像库），开箱即用，且核心识别逻辑严格对齐 Maa C++ 实现。

### 1.2 目标

1. **项目关系**：Pipeline 作为父项目，Recognition 作为子项目纳入（Git submodule 方式），Recognition 独立仓库保留并继续维护。
2. **文件关系**：明确划分两套 `resource/`、两套 `src/`、两套 `pyproject.toml` 的边界，避免冲突与重复。
3. **功能适配**：用 Recognition 的 Python 实现作为 Pipeline 步骤 1 的**默认后端**，替代已停止维护的 MAA 调用；同时保留 MAA 调用作为**可选后端**，通过配置切换（双后端可切换）。

### 1.3 关键决策（已确认）

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| 代码组织方式 | Git submodule | Recognition 保持独立仓库与发布周期，父项目锁定版本，文件关系清晰 |
| Recognition 独立仓库 | 保留并继续维护 | 可独立接收 issue/PR、运行资源自动同步 workflow |
| MAA 调用处理 | 双后端可切换 | Recognition 为默认后端；MAA 作为可选回退后端，保留兼容能力 |

---

## 2. 现状分析

### 2.1 Pipeline 现状

- **Python**：`>=3.12`
- **依赖**：`opencv-python`、`numpy`、`movielite`、`pictex`、`Pillow`、`tqdm`、`PyQt6`
- **入口**：`arkpipeline-cli`（`core.pipeline:main`）、`arkpipeline-gui`（`gui.app:main`）
- **许可证**：GPL-2.0
- **MAA 调用机制**（位于 `src/arknights_video_pipeline/core/video_to_copilot.py`）：
  - **非 subprocess、非 CLI**，而是把 `<maa_path>/Python` 加入 `sys.path` 后以 Python 库形式调用：
    ```python
    from asst.asst import Asst
    Asst.load(path=maa_abs_path)
    asst = Asst(callback=callback)
    asst.append_task("VideoRecognition", {"filename": ascii_video_path})
    asst.start()
    while asst.running(): ...
    ```
  - 通过回调捕获 `SubTaskExtraInfo`/`Finished` 事件中 `details.filename` 的结果 JSON 路径。
  - 处理 Windows 非 ASCII 路径问题（8.3 短路径转换）。
- **步骤 1 接入点**（`core/pipeline.py` 中 `Pipeline.step_video_to_copilot`）：
  - 组装子配置（`output_dir`、`maa_path`）
  - `validate_maa_path(maa_path)` 校验 `MaaCore.dll` 与 `resource/`
  - 带 `maa_max_retries` 重试 + `maa_timeout_seconds` 超时
  - 异常包装为 `PipelineStepError(step_name="video_to_copilot", step_index=1, cause=exc)`
  - 产出 `self.copilot_json_path`，供步骤 2/3 读取
- **步骤定义**：`core/step_defs.py` 的 `STEPS` 列表（单一事实源），5 步顺序：`copilot → formation → actions → track → compose`
- **MAA 相关配置键**（`config/pipeline.json`）：`maa_path`（必填）、`maa_timeout_seconds`（默认 600）、`maa_max_retries`（默认 2）
- **CLI 参数**：`--maa-path`、`--skip-step`（choices: copilot/formation/actions/track/compose）

### 2.2 Recognition 现状

- **Python**：`>=3.9`
- **依赖**：`numpy`、`opencv-python`、`onnxruntime`、`rapidocr-onnxruntime`、`pillow`
- **入口**：`arknights-video-recognition`（`cli:main`）
- **许可证**：代码遵循其声明许可证；`resource/` 资源为 AGPL-3.0（来自 Maa）
- **主流水线类**（`src/arknights_video_recognition/pipeline.py`）：
  ```python
  class VideoRecognitionPipeline:
      def __init__(self, ocr_source: str = "maamodel",
                   resolution: Tuple[int, int] = (1280, 720)): ...
      def run(self, video_path: str, stage_override: Optional[str] = None,
              output_path: Optional[str] = None,
              with_video_time: bool = False) -> Dict[str, Any]: ...
      def run_to_json(self, ...) -> str: ...
  ```
  - `run()` 返回 **copilot 作业 dict**（`CopilotJob.to_dict()`）
  - 构造时调用 `check_resource()` 校验资源，缺失抛 `ResourceMissingError`
  - 实例属性 `last_output_path` 保存最近写入路径
- **资源路径解析**（`src/arknights_video_recognition/config/settings.py`）：
  ```python
  _PROJECT_ROOT = Path(__file__).resolve().parents[3]
  _ENV_RESOURCE_DIR = os.environ.get("AVR_RESOURCE_DIR")
  RESOURCE_DIR = Path(_ENV_RESOURCE_DIR).resolve() if _ENV_RESOURCE_DIR else _PROJECT_ROOT / "resource"
  ```
  - **关键**：`AVR_RESOURCE_DIR` 环境变量可在 **import 时**覆盖资源目录
  - 衍生常量：`TILE_DIR`、`ONNX_DIR`、`OCR_MAA_DIR`、`DATA_DIR`、`TEMPLATE_DIR`、`CONFIG_DIR`、`AVATAR_DIR`
- **输出 schema**（`src/arknights_video_recognition/copilot/builder.py` 的 `CopilotJob.to_dict()`）：
  ```json
  {
    "minimum_required": "v4.0.0",
    "stage_name": "main_02-10",
    "opers": [{"name": "...", "skill": 0, "skill_usage": 0, "requirements": {...}}],
    "groups": [],
    "actions": [{"type": "Deploy", "name": "...", "location": [5, 3], "direction": "Right"}],
    "doc": {"title": "...", "details": ""}
  }
  ```
  - **与 MAA 差异**：以视频时间点为 actions 时间点，不输出 `kills`/`costs`/`cost_changes`；可用 `with_video_time=True` 输出非标准扩展字段 `video_time`
  - `location` = `[col, row]`（x=列、y=行）
- **可导入 API**：`__init__.py` 仅暴露 `__version__`，需用完整子模块路径：
  ```python
  from arknights_video_recognition.pipeline import VideoRecognitionPipeline, StageNotRecognizedError
  ```
- **打包问题**：`pyproject.toml` 无 `package-data`/`data-files`/`MANIFEST.in`，`resource/` 位于包外 → `pip install .`（非 editable）**不会**包含资源；仅 `pip install -e .`（editable）因引用源码树而可用

### 2.3 兼容性矩阵

| 维度 | Pipeline | Recognition | 兼容性 |
| --- | --- | --- | --- |
| Python 版本 | `>=3.12` | `>=3.9` | ✅ 取 `>=3.12` |
| numpy / opencv / Pillow | 有 | 有 | ✅ 无冲突 |
| 额外依赖 | movielite, pictex, tqdm, PyQt6 | onnxruntime, rapidocr-onnxruntime | ⚠️ 需合并依赖声明 |
| 输出格式 | Maa copilot JSON（文件） | Maa copilot JSON（dict） | ⚠️ 接口形态不同（文件 vs dict），需适配层 |
| 资源目录 | 自有 `resource/`（StartButton/font/locales） | 自有 `resource/`（214M 模型/地图/头像） | ⚠️ 需统一到顶层 `resource/`（见 §3、§8） |
| 许可证 | GPL-2.0 | 资源 AGPL-3.0 | ❌ 需合规处理（见 §9） |

---

## 3. 总体架构

### 3.1 子模块布局

```
ArknightsVideoPipeline/                          # 父项目仓库根
├── .gitmodules                                  # 【新增】声明 recognition 子模块
├── .gitignore
├── README.md
├── LICENSE                                      # 建议升级 GPL-3.0+（见 §9）
├── pyproject.toml                               # 【修改】合并依赖、新增后端配置项说明
├── requirements.txt
├── main.py / gui.py / icon.*                    # 父项目入口
│
├── src/                                         # 【统一源码根】父项目代码包 + 子模块在此平级共存
│   ├── arknights_video_pipeline/               # 父项目代码包（snake_case，不变）
│   │   ├── core/
│   │   │   ├── copilot_backend.py              # 【新增】后端抽象 Protocol + 工厂
│   │   │   ├── maa_backend.py                  # 【新增/重构】包装现有 MAA 逻辑
│   │   │   ├── recognition_backend.py          # 【新增】Recognition 适配层
│   │   │   ├── video_to_copilot.py             # 【重构】原 MAA 调用逻辑迁入 maa_backend.py
│   │   │   ├── step_defs.py                    # 【微调】步骤 1 label/说明
│   │   │   ├── pipeline.py                     # 【修改】step_video_to_copilot 按配置选后端
│   │   │   ├── config.py                       # 【修改】新增后端相关 getter
│   │   │   └── ...（其余不变）
│   │   └── gui/ / service/ / tests/ / ...      # 不变
│   │
│   └── arknights_video_recognition/            # 【git submodule】snake_case 命名（原 PascalCase 避免与父项目包冲突）
│       ├── src/arknights_video_recognition/      # 子模块代码包（默认后端实现）
│       ├── resource/                           # 子模块自带资源（来源真相，见 §8.1）
│       ├── scripts/                            # 资源同步脚本
│       ├── .github/workflows/sync-resources.yml
│       ├── pyproject.toml                      # 子模块独立元信息
│       └── doc/
│
├── resource/                                    # 【统一资源根】所有资源均在此目录下
│   ├── StartButton/                            # 父项目自有：开始按钮模板
│   ├── font/                                   # 父项目自有：字体
│   ├── locales/                                # 父项目自有：i18n（en-US/zh-CN）
│   └── recognition/                            # 【新增】Recognition 资源（~214M，统一入口）
│       ├── tile/                               #   地图数据 levels.json（940+ 关卡）
│       ├── avatar/                             #   干员头像库
│       ├── onnx/                               #   战斗识别 ONNX 模型
│       ├── ocr/                                #   Maa finetune OCR 模型
│       ├── data/                               #   战斗/OCR 配置 + 干员职业表
│       ├── template/                           #   模板图片
│       └── config/                             #   roi.json 等 ROI 配置
│
├── docs/                                        # 父项目文档
│   ├── merge_plan.md                           # 本方案文档副本/链接
│   └── ...（quick_start / configuration / cli_reference / gui_guide）
│
└── script/                                      # 父项目构建脚本
    └── sync_recognition_resources.py          # 【新增】子模块资源 → 顶层 resource/ 同步脚本
```

> **布局要点**：
> 1. **不新建 `submodules/` 目录**——recognition 子模块直接作为 `src/arknights_video_recognition/` 与父项目代码包 `src/arknights_video_pipeline/` 平级共存于 `src/` 下。
> 2. **命名隔离**：父项目包与子模块根均用 `snake_case`（`arknights_video_pipeline` / `arknights_video_recognition`，均符合 Python 命名规范），两者在 `src/` 下不冲突。
> 3. **资源统一原则**：所有运行时资源（父项目自有 + Recognition）一律存放在顶层 `resource/` 下。Recognition 资源位于 `resource/`，运行时 `AVR_RESOURCE_DIR` 指向该目录。子模块内的 `resource/` 仅作"来源真相"（git submodule 完整 checkout 必然存在），不作为运行时读取路径，避免双份资源与路径歧义（详见 §8）。

### 3.2 职责边界

| 关注点 | 归属 | 说明 |
| --- | --- | --- |
| 视频识别算法（编队/关卡/动作） | `src/arknights_video_recognition/`（子模块） | 子模块独立实现，父项目不重复 |
| ONNX/OCR 模型、地图数据、头像库 | 父项目 `resource/` | **统一存放于顶层 resource/**，由同步脚本从子模块 `src/arknights_video_recognition/resource/` 拉取（见 §8） |
| 开始按钮模板、字体、i18n | 父项目 `resource/`（StartButton/font/locales） | 父项目自有，与识别无关 |
| 视频合成（movielite）、文本渲染（pictex） | Pipeline | 父项目独有 |
| GUI（PyQt6）、CLI、流水线编排 | Pipeline | 父项目独有 |
| 后端选择与切换 | Pipeline `core/copilot_backend.py` | 父项目新增的适配层 |

---

## 4. 后端抽象层设计

### 4.1 抽象接口

在 `src/arknights_video_pipeline/core/copilot_backend.py` 新增后端协议与工厂：

```python
"""视频转 copilot JSON 的后端抽象层。

支持多种识别后端（Recognition / MAA），通过配置切换。
"""
from __future__ import annotations
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class CopilotBackend(Protocol):
    """视频 → Maa copilot 作业 JSON 文件 的统一后端接口。"""

    name: str  # 后端标识，如 "recognition" / "maa"

    def recognize(
        self,
        video_path: str,
        output_dir: str,
        config: dict,
        timeout: float | None = None,
    ) -> str:
        """执行识别，返回生成的 copilot JSON 文件绝对路径。

        Args:
            video_path: 输入视频路径
            output_dir: 输出目录
            config: 后端相关子配置
            timeout: 超时秒数（None 表示不限）

        Returns:
            生成的 copilot JSON 文件绝对路径
        """
        ...


def create_backend(backend_name: str, config: dict) -> CopilotBackend:
    """根据配置创建后端实例。"""
    if backend_name == "recognition":
        from arknights_video_pipeline.core.recognition_backend import RecognitionBackend
        return RecognitionBackend(config)
    elif backend_name == "maa":
        from arknights_video_pipeline.core.maa_backend import MAABackend
        return MAABackend(config)
    else:
        raise ValueError(f"未知的 copilot 后端: {backend_name}（可选: recognition / maa）")
```

### 4.2 Recognition 适配层

`src/arknights_video_pipeline/core/recognition_backend.py`（新增）：

```python
"""Recognition 后端：用 ArknightsVideoRecognition 子模块完成视频转 copilot JSON。

依赖子模块 src/arknights_video_recognition，需可导入 arknights_video_recognition 包。
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

# === 关键：在 import recognition 之前设置资源目录 ===
# 资源统一存放于父项目顶层 resource/（见 §3.1、§8）。
# 优先级：配置 > 环境变量 AVR_RESOURCE_DIR > 默认 resource/
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_RESOURCE_DIR = _PROJECT_ROOT / "resource" / "recognition"
_SUBMODULE_ROOT = _PROJECT_ROOT / "src" / "arknights_video_recognition"

# 仅当未被外部（配置/环境变量）显式设置时，回退到顶层 resource/
if "AVR_RESOURCE_DIR" not in os.environ:
    os.environ["AVR_RESOURCE_DIR"] = str(_DEFAULT_RESOURCE_DIR)

# 确保子模块源码可导入（editable 安装则无需）
# 子模块代码包位于 src/arknights_video_recognition
_SRC_DIR = _SUBMODULE_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from arknights_video_recognition.pipeline import (
    VideoRecognitionPipeline,
    StageNotRecognizedError,
)
from arknights_video_recognition.config.settings import ResourceMissingError


class RecognitionBackend:
    """视频转 copilot JSON 的 Recognition 后端。"""

    name = "recognition"

    def __init__(self, config: dict):
        self._config = config or {}

    def recognize(
        self,
        video_path: str,
        output_dir: str,
        config: dict,
        timeout: float | None = None,
    ) -> str:
        cfg = {**self._config, **(config or {})}
        ocr_source = cfg.get("ocr_source", "maamodel")
        resolution_str = cfg.get("resolution", "1280x720")
        stage_override = cfg.get("stage_override") or None
        with_video_time = bool(cfg.get("with_video_time", False))

        # 解析分辨率 "WxH" -> (W, H)
        w, h = (int(x) for x in resolution_str.lower().split("x"))

        # 校验资源
        # （VideoRecognitionPipeline 构造时已调用 check_resource）

        pipe = VideoRecognitionPipeline(
            ocr_source=ocr_source,
            resolution=(w, h),
        )

        # run() 返回 dict，需落盘为 JSON 文件以匹配流水线"文件路径"接口
        start = time.time()
        try:
            job_dict = pipe.run(
                video_path=video_path,
                stage_override=stage_override,
                output_path=None,  # 由本适配层统一控制输出路径
                with_video_time=with_video_time,
            )
        except StageNotRecognizedError:
            raise
        except ResourceMissingError as e:
            raise RuntimeError(f"Recognition 资源缺失: {e}") from e

        if timeout is not None and (time.time() - start) > timeout:
            raise TimeoutError(f"Recognition 识别超时（>{timeout}s）")

        # 归一化：补齐 opers 默认值，确保与 MAA 后端输出一致（见 §5）
        job_dict = _normalize_copilot(job_dict)

        # 落盘
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        video_stem = Path(video_path).stem
        out_path = out_dir / f"recognition_copilot_{video_stem}.json"
        out_path.write_text(
            json.dumps(job_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(out_path.resolve())


def _normalize_copilot(job: dict) -> dict:
    """薄归一化层：补齐字段默认值，兼容下游 formation/actions 文本提取。"""
    # opers: 补默认 skill / skill_usage（与 Pipeline 原 build_copilot_json 行为对齐）
    for op in job.get("opers", []):
        op.setdefault("skill", 1)
        op.setdefault("skill_usage", 0)
    # 保证关键字段存在
    job.setdefault("minimum_required", "v4.0.0")
    job.setdefault("groups", [])
    job.setdefault("actions", [])
    job.setdefault("opers", [])
    return job
```

### 4.3 MAA 后端（保留为可选）

`src/arknights_video_pipeline/core/maa_backend.py`（新增，包装现有逻辑）：

```python
"""MAA 后端：保留原有 MAA 库式调用作为可选回退后端。

原 core/video_to_copilot.py 的 run_maa_recognition / build_copilot_json /
video_to_copilot 逻辑迁移至此，video_to_copilot.py 改为向后兼容的 re-export。
"""
from __future__ import annotations
from arknights_video_pipeline.core.video_to_copilot import (
    validate_maa_path,
    video_to_copilot,
)


class MAABackend:
    """视频转 copilot JSON 的 MAA 后端（依赖 MAA 项目）。"""

    name = "maa"

    def __init__(self, config: dict):
        self._config = config or {}

    def recognize(
        self,
        video_path: str,
        output_dir: str,
        config: dict,
        timeout: float | None = None,
    ) -> str:
        cfg = {**self._config, **(config or {})}
        maa_path = cfg.get("maa_path", "")
        validate_maa_path(maa_path)

        sub_config = {
            "maa_path": maa_path,
            "output_dir": output_dir,
            # 其余 MAA 子配置透传
            **{k: v for k, v in cfg.items() if k not in ("maa_path", "output_dir")},
        }
        return video_to_copilot(video_path, sub_config, timeout=timeout)
```

`video_to_copilot.py` 保留原函数签名，仅将其内部实现移至 `maa_backend.py`（或保留原位由 `maa_backend.py` 调用），并向后兼容地 re-export，避免破坏现有 import。

### 4.4 流水线步骤 1 改造

`core/pipeline.py` 中 `Pipeline.step_video_to_copilot` 改为按配置选后端：

```python
def step_video_to_copilot(self) -> StepResult:
    result = StepResult(...).mark_running()

    backend_name = self.config.get_copilot_backend()  # 新增 getter，默认 "recognition"
    backend = create_backend(backend_name, self._backend_config(backend_name))

    output_dir = os.path.relpath(self.config.get_output_dir(), ...)
    timeout = self.config.get_copilot_timeout()  # 通用超时

    max_retries = self.config.get_copilot_max_retries()
    if max_retries < 1:
        raise CopilotBackendError(f"max_retries 必须 >=1，当前 {max_retries}")

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            json_path = backend.recognize(
                video_path=self.video_path,
                output_dir=output_dir,
                config=self._backend_config(backend_name),
                timeout=timeout,
            )
            self.copilot_json_path = json_path
            return result.mark_success(output_files=[json_path])
        except (RuntimeError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                # 退避重试
                time.sleep(min(2 ** attempt, 10))
                continue
    raise PipelineStepError(
        step_name="video_to_copilot", step_index=1,
        cause=CopilotBackendError(f"{backend_name} 后端识别失败: {last_exc}"),
    )
```

---

## 5. Schema 适配

### 5.1 输出结构对比

| 字段 | Pipeline（MAA 后端） | Recognition 后端 | 适配动作 |
| --- | --- | --- | --- |
| `minimum_required` | `"v4.0.0"` | `"v4.0.0"` | ✅ 一致 |
| `stage_name` | stageId | stageId（如 `main_02-10`） | ✅ 一致 |
| `opers[].name/skill` | 有，补默认 `skill=1` | 有，`skill` 可为 0 | 归一化补默认 |
| `opers[].skill_usage` | 补默认 `0` | 可选输出 | 归一化补默认 |
| `groups` | `[]` | `[]` | ✅ 一致 |
| `actions[].type` | Maa 协议 | Maa 协议（DEPLOY/SKILL/RETREAT/SPEED_UP/...） | ✅ 一致 |
| `actions[].location` | `[x, y]` | `[col, row]`（x=列、y=行） | ✅ 语义一致 |
| `actions[].direction` | LEFT/RIGHT/UP/DOWN/NONE | 同 | ✅ 一致 |
| `actions[].kills/costs` | MAA 可能输出 | **不输出**（用 video_time） | ⚠️ 下游文本提取需兼容缺失 |
| `doc` | title/details | title/details | ✅ 一致 |

### 5.2 归一化策略

适配层 `_normalize_copilot()` 负责：
1. 补齐 `opers` 的 `skill`（默认 1）、`skill_usage`（默认 0）
2. 保证 `groups`/`actions`/`opers`/`minimum_required` 字段存在
3. **不**强行添加 `kills/costs`（保持 Recognition 语义）；下游 `formation_to_text`/`actions_to_text` 需用 `.get()` 容错读取可选字段

### 5.3 下游步骤兼容性

步骤 2（`formation_to_text`）与步骤 3（`actions_to_text`）读取 `copilot_json_path` 提取文本。需审查这两处对 `kills`/`costs`/`skill` 等字段的访问方式：
- 若使用 `dict.get()` 容错 → 无需改动
- 若直接下标访问 → 改为 `.get(key, default)`

> **行动项**：实施时审查 `core/formation_to_text.py` 与 `core/actions_to_text.py`，确保所有字段访问容错。

---

## 6. 配置设计

### 6.1 新增配置项（`config/pipeline.json`）

```jsonc
{
  "pipeline": {
    // === 后端选择（新增）===
    "copilot_backend": "recognition",   // "recognition"（默认） | "maa"

    // === Recognition 后端配置（新增）===
    "recognition": {
      "ocr_source": "maamodel",         // "maamodel" | "default"
      "resolution": "1280x720",         // "WxH"
      "stage_override": "",             // 空=自动识别；否则指定关卡 code/name/stageId
      "with_video_time": false,          // 是否输出 video_time 扩展字段
      "resource_dir": ""                // 空=用顶层 resource/；否则覆盖（见 §8.4）
    },

    // === MAA 后端配置（保留，仅 backend=maa 时生效）===
    "maa_path": "",
    "maa_timeout_seconds": 600,
    "maa_max_retries": 2,

    // === 通用（新增，两后端共用）===
    "copilot_timeout_seconds": 600,
    "copilot_max_retries": 2
  }
}
```

### 6.2 配置优先级

`config.py` 中 `ConfigManager` 新增 getter：
- `get_copilot_backend()` → 读 `copilot_backend`，默认 `"recognition"`
- `get_copilot_timeout()` → 优先 `copilot_timeout_seconds`，回退 `maa_timeout_seconds`
- `get_copilot_max_retries()` → 优先 `copilot_max_retries`，回退 `maa_max_retries`
- `get_recognition_config()` → 读 `recognition` 子配置块

### 6.3 CLI 参数（`core/pipeline.py` 的 `build_argparser`）

新增：
- `--backend {recognition,maa}`：覆盖 `copilot_backend`
- `--ocr {maamodel,default}`：覆盖 recognition 的 `ocr_source`
- `--stage STAGE`：覆盖 recognition 的 `stage_override`
- `--resolution WxH`：覆盖 recognition 的 `resolution`

保留：
- `--maa-path`：仅 `backend=maa` 时生效
- `--skip-step`：不变

---

## 7. 依赖与构建

### 7.1 父项目 `pyproject.toml` 修改

```toml
[project]
requires-python = ">=3.12"   # 不变（兼容 Recognition 的 >=3.9）

dependencies = [
    # 父项目原有
    "opencv-python>=4.8.0,<5",
    "numpy>=1.24.0,<3",
    "movielite>=0.1.0,<1",
    "pictex>=2.0,<3",
    "Pillow>=10.0.0,<12",
    "tqdm>=4.65.0,<5",
    "PyQt6>=6.6.0,<7",
    # 【新增】Recognition 后端依赖
    "onnxruntime>=1.16",
    "rapidocr-onnxruntime>=1.3",
]
```

> **说明**：Recognition 的依赖上移到父项目，使默认后端开箱即用。MAA 后端无需额外 pip 依赖（依赖外部 MAA 安装）。

### 7.2 Recognition 子模块的安装方式

Recognition 作为子模块直接位于 `src/arknights_video_recognition/`，有两种集成方式（推荐方式 A）：

**方式 A（推荐）：editable 安装子模块**
```bash
# 父项目根目录
git submodule add https://github.com/Tisn4627/ArknightsVideoRecognition src/arknights_video_recognition
git submodule update --init --recursive
pip install -e src/arknights_video_recognition
```
- editable 模式直接引用源码树，子模块代码包 `arknights_video_recognition` 可正常 import
- 父项目 `pyproject.toml` 无需声明对子模块的依赖（同 `src/` 下平级共存）

**方式 B：sys.path 注入（免安装）**
- 由 `recognition_backend.py` 在 import 前将 `src`（vendor 包 `src/arknights_video_recognition` 的父目录）加入 `sys.path`（已在 §4.2 代码中实现）
- 适合开发期快速切换；生产部署建议方式 A

> **注意 `settings.py` 路径解析**：子模块 `settings.py` 位于 `src/arknights_video_recognition/config/settings.py`，其 `parents[3]` 解析到仓库根，默认 `RESOURCE_DIR` 指向顶层 `resource/`（识别资源已并入）。适配层仍显式设置 `AVR_RESOURCE_DIR`（见 §4.2、§8.4），覆盖该默认值。

### 7.3 构建脚本（`script/build_exe/`）

打包 exe 时需注意：
- 顶层 `resource/` 下的识别资源（214M）需一并打包，路径需与运行时 `AVR_RESOURCE_DIR` 一致
- 在 `runtime_hook.py` 中设置 `os.environ["AVR_RESOURCE_DIR"]` 指向打包后的 `resource/` 目录
- ONNX 运行时依赖需包含在打包目标中

---

## 8. 资源管理

### 8.1 统一资源根原则

**所有运行时资源一律存放在父项目顶层 `resource/` 目录下**，不再保留两套分散的 `resource/`：

```
resource/                                    # 父项目统一资源根
├── StartButton/                             # 父项目自有
├── font/                                    # 父项目自有
├── locales/                                 # 父项目自有
└── recognition/                             # Recognition 资源（运行时唯一读取入口）
    ├── tile/   avatar/   onnx/   ocr/
    ├── data/   template/  config/
    └── ...
```

- **运行时读取路径**：`AVR_RESOURCE_DIR` 指向 `resource/`（见 §4.2 适配层代码）
- **子模块内 `resource/` 的角色**：仅为"来源真相"——git submodule 完整 checkout 必然包含它（214M 由子模块仓库版本控制），但**运行时不直接读取**，避免双份资源与路径歧义
- **父项目 `resource/` 的角色**：运行时唯一入口，由同步脚本（§8.2）从子模块拉取/链接

### 8.2 资源同步策略

子模块的资源需"进入"父项目顶层 `resource/`。提供两种实现方式（推荐方式 A）：

**方式 A（推荐）：符号链接（开发期零拷贝）**
- 子模块初始化后，运行 `script/sync_recognition_resources.py` 为每个条目创建符号链接：
  ```
  resource/<条目>  ->  src/arknights_video_recognition/resource/<条目>
  （如 resource/template -> src/arknights_video_recognition/resource/template）
  ```
- 优点：零存储重复、子模块更新后自动生效（链接指向最新 checkout）
- 注意：Windows 创建符号链接需开发者模式或管理员权限；CI 环境通常允许
- 同步脚本示意：
  ```python
  # script/sync_recognition_resources.py
  import os, sys
  from pathlib import Path
  ROOT = Path(__file__).resolve().parents[1]
  SRC = ROOT / "src" / "arknights_video_recognition" / "resource"
  DST = ROOT / "resource"
  for entry in SRC.iterdir():
      link = DST / entry.name
      if link.is_symlink() or link.exists():
          continue
      os.symlink(entry, link, target_is_directory=True)
  ```

**方式 B：复制（打包期 / 无符号链接权限环境）**
- 同步脚本按条目递归复制 `SRC/<条目> → DST/<条目>`（绝不删除/覆盖 `resource/` 下的
  font/locales/StartButton 等主项目资源），并加 `.gitignore` 忽略 `resource/` 下的
  识别资源子目录（avatar/config/data/ocr/onnx/template/tile）
- 优点：跨平台无权限问题、打包友好
- 缺点：214M 重复存储，子模块更新需重新运行脚本

**方式选择**：
- 开发环境 → 方式 A（符号链接）
- 打包 exe / CI 产物 → 方式 B（复制）
- 同步脚本应支持 `--mode=link|copy` 参数切换

<!--
### 8.3 子模块资源更新流程（历史方案，见下方"现行流程"）

1. Recognition 仓库的 `.github/workflows/sync-resources.yml` 继续每周自动同步 `tile`/`avatar`/`data`/`config`（在子模块仓库内完成）
2. 父项目通过 `git submodule update --remote` 拉取子模块最新版本（含资源更新）
3. 父项目重新运行 `sync_recognition_resources.py`（方式 A 链接自动生效；方式 B 需重新复制）
4. `template`/`onnx`/`ocr` 仍由 Recognition 开发者在子模块仓库内手动更新
-->

### 8.3 资源更新流程（现行）

本仓库新增 `.github/workflows/sync-resources.yml`
（移植自 Recognition 上游同名 workflow，适配本仓库布局）：

1. 每周一 08:00 UTC（北京时间 16:00）定时自动运行，也可在 Actions 页面手动触发
2. 自动同步 `tile`/`avatar`/`data`（battle_data/ocr_config/character_table/char_roles）与
   重新生成 `config/roi.json`，直接更新本仓库顶层 `resource/`，有变更时自动提交推送
3. `template`/`onnx`/`ocr` 三类大体积资源仍不自动同步：从 Recognition 上游仓库
   （https://github.com/Tisn4627/ArknightsVideoRecognition）获取更新后，由开发者
   本地复制入库并手动提交
4. Recognition 上游仓库（原子仓库）自身的 `sync-resources.yml` 已整体注释停用
   （2026-08-08，上游提交 7f30007），资源同步统一由本仓库 workflow 负责，避免
   两侧重复同步提交；本仓库 vendor 目录
   `src/arknights_video_recognition/.github/workflows/sync-resources.yml`
   保留其全注释副本（仅作对照参考——GitHub Actions 只扫描仓库根目录，vendor 内的
   workflow 文件不会被执行）

### 8.4 资源路径运行时解析（优先级）

`recognition_backend.py` 中（见 §4.2）：
1. **配置覆盖**：`recognition.resource_dir` 非空 → 用该路径
2. **环境变量**：`AVR_RESOURCE_DIR` 已设置 → 用该路径
3. **默认**：`<父项目根>/resource/`
4. **必须在 import `arknights_video_recognition.*` 之前完成设置**（因 `settings.py` 在 import 时读取环境变量）

### 8.5 .gitignore 处理

- 方式 A（符号链接）：`resource/<条目>` 作为符号链接，**可纳入父项目版本控制**（git 记录链接目标，不记录内容），无需 ignore
- 方式 B（复制）：`resource/` 下的识别资源子目录加入 `.gitignore`（214M 不入库），由同步脚本生成

```
# .gitignore（方式 B 时追加）
resource/
```

### 8.6 资源完整性校验

适配层在创建后端时通过 `VideoRecognitionPipeline` 构造函数自动调用 `check_resource()`，校验以下关键资源存在：
- `tile/levels.json`
- `data/battle_data.json`
- `onnx/{skill_ready_cls,deploy_direction_cls,operators_det}.onnx`
- 助战空模板、avatar 目录

缺失时抛 `ResourceMissingError`，适配层包装为 `RuntimeError` 提示用户运行同步脚本。

---

## 9. 许可证合规（重要）

### 9.1 问题

- Pipeline 代码：**GPL-2.0**
- Recognition 代码：声明许可证（pyproject.toml 未显式声明，需补充确认）
- Recognition `resource/` 资源：**AGPL-3.0**（来自 Maa）

**GPL-2.0 与 AGPL-3.0 不兼容**：AGPL-3.0 是更强的 copyleft，GPL-2.0（除非"或更高版本"措辞）无法与 AGPL-3.0 代码/资源组合分发。

### 9.2 建议方案

1. **父项目许可证升级为 GPL-3.0+**（推荐）：
   - GPL-3.0 与 AGPL-3.0 兼容（组合作品可按 AGPL-3.0 分发）
   - GPL-2.0 → GPL-3.0 升级需所有贡献者同意（当前仅 1 位贡献者 Tisn4627，可行）
2. **资源归属声明**：在父项目 `LICENSE`/`NOTICE` 中明确：
   - `resource/` 内的资源遵循 AGPL-3.0（源自子模块 `src/arknights_video_recognition/resource/`）
   - 资源作为独立数据目录分发，不与父项目代码"链接"
3. **补充 Recognition 代码许可证**：在子模块 `pyproject.toml` 显式声明代码许可证

> **行动项**：合并前需由仓库所有者确认许可证升级方案，本方案不替代法律意见。

---

## 10. 迁移步骤

> 以下为建议的实施顺序，**本方案不执行任何步骤**，仅作规划。

### 阶段 1：子模块接入与资源统一（不影响现有功能）
1. 父项目执行 `git submodule add https://github.com/Tisn4627/ArknightsVideoRecognition src/arknights_video_recognition`（子模块直接入 `src/`，不新建 `submodules/`）
2. 更新 `.gitmodules`（path 指向 `src/arknights_video_recognition`）
3. 新增 `script/sync_recognition_resources.py`（资源同步脚本，支持 `--mode=link|copy`）
4. 运行同步脚本：`resource/` ← `src/arknights_video_recognition/resource/`（方式 A 符号链接）
5. 更新 `.gitignore`（若用方式 B 复制，追加识别资源子目录 avatar/config/data/ocr/onnx/template/tile）
6. 文档补充 `git submodule update --init --recursive` + 运行同步脚本的克隆说明
7. CI 中增加子模块初始化 + 资源同步步骤

### 阶段 2：后端抽象层（新增代码，不改现有逻辑）
8. 新增 `core/copilot_backend.py`（Protocol + 工厂）
9. 新增 `core/maa_backend.py`，包装现有 `video_to_copilot.py` 逻辑
10. 新增 `core/recognition_backend.py`（适配层 + 归一化，`AVR_RESOURCE_DIR` 指向 `resource/`）
11. `video_to_copilot.py` 保留向后兼容 re-export

### 阶段 3：流水线接入
12. 修改 `core/pipeline.py` 的 `step_video_to_copilot`：按 `copilot_backend` 选后端
13. 修改 `core/config.py`：新增 `get_copilot_backend()` 等 getter
14. 修改 `build_argparser`：新增 `--backend`/`--ocr`/`--stage`/`--resolution`
15. 审查 `formation_to_text.py`/`actions_to_text.py` 字段访问容错

### 阶段 4：配置与依赖
16. 更新 `config/pipeline.json` 默认配置（默认 `copilot_backend=recognition`）
17. 更新 `docs/configuration.md` 文档
18. 更新 `pyproject.toml` 依赖（新增 onnxruntime/rapidocr-onnxruntime）
19. 更新 `requirements.txt`

### 阶段 5：验证
20. 单元测试：后端工厂、归一化函数、Mock 两个后端
21. 集成测试：用样例视频跑 recognition 后端全流程（资源从 `resource/` 读取）
22. 回归测试：切换 `copilot_backend=maa` 验证 MAA 后端仍可用
23. 资源同步测试：方式 A/B 切换、子模块更新后重新同步
24. 打包测试：exe 构建含 `resource/` 资源路径

### 阶段 6：文档与发布
25. 更新 `README.md`：说明双后端、子模块克隆 + 资源同步方式
26. 更新 `docs/quick_start_cli.md`：默认走 recognition 后端的快速开始
27. 处理许可证（见 §9）
28. 打 tag 发布

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| Recognition 资源 214M 导致父项目 clone 慢 | 中 | submodule 默认不下载，需 `--init`；文档说明；CI 缓存 |
| 资源未同步到 `resource/` → 运行时找不到 | 高 | 适配层启动时校验并提示运行同步脚本；CI 强制同步步骤 |
| 符号链接在 Windows 无权限创建 | 中 | 同步脚本支持 `--mode=copy` 回退；文档说明开启开发者模式 |
| `AVR_RESOURCE_DIR` 未在 import 前设置 → 资源找不到 | 高 | 适配层在模块顶部最早设置；单测覆盖路径解析 |
| Recognition 输出无 `kills/costs`，下游文本步骤异常 | 中 | 归一化 + `.get()` 容错；集成测试验证 |
| MAA 后端因 MAA 停更逐渐失效 | 低（已降级为可选） | 默认 recognition；保留 maa 仅作回退 |
| 双后端行为不一致（关卡识别能力差异） | 中 | 文档说明差异；`stage_override` 提供手动兜底 |
| 许可证 GPL-2.0 vs AGPL-3.0 不兼容 | 高 | 升级 GPL-3.0+（见 §9） |
| ONNX/OCR 模型在打包环境缺失 | 中 | runtime_hook 设置资源路径；打包测试 |
| Python 版本（3.12 vs 3.9）依赖差异 | 低 | 统一 >=3.12；CI 矩阵测试 |
| 子模块版本漂移导致接口不兼容 | 中 | 父项目锁定子模块 commit；子模块接口变更需同步升级父项目适配层 |

---

## 12. 测试策略

### 12.1 单元测试
- `test_copilot_backend.py`：后端工厂创建、未知后端报错
- `test_recognition_backend.py`：Mock `VideoRecognitionPipeline.run()`，验证落盘、归一化、超时、`AVR_RESOURCE_DIR` 默认指向 `resource/`
- `test_maa_backend.py`：Mock `video_to_copilot`，验证包装正确
- `test_normalize.py`：归一化函数各字段补默认
- `test_sync_resources.py`：同步脚本链接/复制模式、已存在时跳过、跨平台兼容

### 12.2 集成测试
- 用样例视频跑 recognition 后端完整 5 步流水线（资源从 `resource/` 读取）
- 切换 `copilot_backend` 配置，验证两后端产出可被下游步骤消费
- `pytest -m slow`（Recognition 已有慢测试标记）

### 12.3 回归测试
- `copilot_backend=maa` 时行为与改造前完全一致
- `--skip-step` 仍可用

### 12.4 资源同步测试
- 子模块更新后重新运行同步脚本（方式 A 链接自动生效、方式 B 重新复制）
- `resource/` 缺失时适配层抛出友好错误提示运行同步脚本

---

## 13. 文档更新清单

| 文档 | 更新内容 |
| --- | --- |
| `README.md` | 新增双后端说明、子模块克隆 + 资源同步命令、许可证变更 |
| `docs/quick_start_cli.md` | 默认 recognition 后端的快速开始（含资源同步步骤） |
| `docs/configuration.md` | 新增 `copilot_backend` 及 recognition 配置项（含 `resource_dir`） |
| `docs/cli_reference.md` | 新增 `--backend`/`--ocr`/`--stage`/`--resolution` 参数 |
| `docs/gui_guide.md` | GUI 后端选择控件说明（若 GUI 增加切换） |
| `src/arknights_video_recognition/doc/` | 保持子模块文档独立 |

---

## 14. 后续可演进方向（非本次范围）

1. **GUI 后端切换控件**：在 PyQt6 界面增加后端选择下拉框与 recognition 参数面板
2. **资源共享优化**：复用 `resource/template/` 给 Pipeline 的开始按钮识别（如有重叠）
3. **缓存机制**：对同一视频的识别结果缓存，避免重复识别
4. **并行识别**：多视频批量时，recognition 后端（纯 Python）比 MAA（资源争用）更适合并发
5. **Recognition 包发布**：将 Recognition 发布到 PyPI，父项目改用 pip 依赖（替代 submodule + 资源同步）

---

## 附录 A：关键文件映射

| 父项目文件 | 操作 | 说明 |
| --- | --- | --- |
| `.gitmodules` | 新增 | 声明 recognition 子模块（path 指向 `src/arknights_video_recognition`） |
| `src/arknights_video_recognition/` | 新增 | git submodule（与父项目代码包平级共存于 `src/`，含代码 + 子模块内 resource 作来源） |
| `script/sync_recognition_resources.py` | 新增 | 资源同步脚本（`--mode=link\|copy`），子模块 resource → 顶层 `resource/` |
| `resource/` 下的识别资源子目录（avatar/config/data/ocr/onnx/template/tile） | 新增 | Recognition 资源统一入口（符号链接或复制，见 §8） |
| `.gitignore` | 修改 | 方式 B 复制时追加识别资源子目录 |
| `src/arknights_video_pipeline/core/copilot_backend.py` | 新增 | 后端 Protocol + 工厂 |
| `src/arknights_video_pipeline/core/recognition_backend.py` | 新增 | Recognition 适配层（`AVR_RESOURCE_DIR` 指向 `resource/`） |
| `src/arknights_video_pipeline/core/maa_backend.py` | 新增 | MAA 后端包装 |
| `src/arknights_video_pipeline/core/video_to_copilot.py` | 重构/兼容 | 逻辑迁出，保留 re-export |
| `src/arknights_video_pipeline/core/pipeline.py` | 修改 | step1 选后端、新增 CLI 参数 |
| `src/arknights_video_pipeline/core/config.py` | 修改 | 新增后端 getter |
| `src/arknights_video_pipeline/core/formation_to_text.py` | 审查 | 字段访问容错 |
| `src/arknights_video_pipeline/core/actions_to_text.py` | 审查 | 字段访问容错 |
| `pyproject.toml` | 修改 | 新增依赖 |
| `requirements.txt` | 修改 | 新增依赖 |
| `config/pipeline.json` | 修改 | 新增后端配置项 |
| `LICENSE` | 待定 | 许可证升级（见 §9） |
| `README.md` / `docs/*` | 修改 | 文档同步（含资源同步步骤） |

## 附录 B：Recognition 可导入 API 速查

```python
# 主流水线
from arknights_video_recognition.pipeline import VideoRecognitionPipeline, StageNotRecognizedError

# Copilot 数据结构
from arknights_video_recognition.copilot import CopilotJob, Action, ActionType, Direction, Oper

# 配置与资源校验
from arknights_video_recognition.config.settings import (
    RESOURCE_DIR, ResourceMissingError, check_resource,
    DEFAULT_OCR_SOURCE, DEFAULT_RESOLUTION, MINIMUM_REQUIRED,
)

# 典型用法
pipe = VideoRecognitionPipeline(ocr_source="maamodel", resolution=(1280, 720))
job_dict = pipe.run("battle.mp4", stage_override="2-10", with_video_time=False)
```

---

*本方案为设计文档，未对任何仓库进行实际修改。实施前请确认许可证合规与接口细节。*
