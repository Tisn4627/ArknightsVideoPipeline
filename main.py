"""
ArknightsVideoPipeline - 明日方舟视频处理流水线

CLI 入口点，委托给 arknights_video_pipeline.core.pipeline.main() 执行。

使用示例：
  python main.py video.mp4 --background-image bg.png
  python main.py video.mp4 -b bg.png --output-dir results --log-level DEBUG
  python main.py video.mp4 --style style2
  python main.py --init-config
"""

import os
import sys

# 将 src 目录加入 Python 路径，支持未安装包时直接运行
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from arknights_video_pipeline.core.pipeline import main


def _run() -> int:
    """带顶层异常处理的入口包装"""
    try:
        main()
        return 0
    except SystemExit as exc:
        # argparse 等已通过 sys.exit 退出：透传退出码；
        # 裸 sys.exit()（code=None）表示成功，映射为 0 而非 1
        if isinstance(exc.code, int):
            return exc.code
        return 0 if exc.code is None else 1
    except KeyboardInterrupt:
        sys.stderr.write("\n用户中断执行\n")
        return 130
    except Exception as exc:
        # 默认只输出单行消息；设 AVP_DEBUG=1 输出完整堆栈便于定位
        if os.environ.get("AVP_DEBUG"):
            import traceback

            traceback.print_exc()
        sys.stderr.write(f"程序启动失败: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(_run())
