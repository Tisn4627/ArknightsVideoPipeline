"""识别引擎测试环境配置。

本仓库未以 editable 方式安装（运行入口 main.py / gui.py 均在启动时把
``src`` 插入 sys.path），而识别包的测试目录独立于
``arknights_video_pipeline/tests``，故此处自行注入仓库 ``src`` 目录，
保证 ``arknights_video_recognition`` 可导入。识别引擎单元测试不依赖
ffmpeg/movielite，无需 pipeline 侧 conftest 的 FFmpeg 配置。
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
