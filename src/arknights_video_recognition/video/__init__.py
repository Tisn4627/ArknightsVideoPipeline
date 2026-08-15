"""视频处理模块。

提供战斗录像的抽帧（:class:`VideoFrames`）与按部署变化切片
（:class:`VideoSlicer`）能力，把一段战斗视频切成若干 :class:`Clip` 片段，
每个片段对应一次可识别的部署/撤退/技能事件，供后续 battle 分析。

对应原 Maa ``CombatRecordRecognitionTask`` 的抽帧与 ``slice_video`` 流程。

典型用法::

    from arknights_video_recognition.video import VideoFrames, VideoSlicer

    vf = VideoFrames("battle.mp4")
    slicer = VideoSlicer(vf)
    for clip in slicer.slice():
        print(clip.start_time, clip.end_time, clip.frame_index)
"""

from .frames import VideoFrames
from .slicer import Clip, VideoSlicer

__all__ = ["VideoFrames", "VideoSlicer", "Clip"]
