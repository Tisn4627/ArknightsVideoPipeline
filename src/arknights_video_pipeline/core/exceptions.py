"""
core.exceptions - 统一异常层次结构

为流水线各环节定义明确的异常类型，便于精确捕获和处理。
"""


class PipelineError(Exception):
    """流水线基础异常"""

    def __init__(self, message: str, step_name: str = "") -> None:
        self.step_name = step_name
        super().__init__(message)


class PipelineStepError(PipelineError):
    """单个步骤执行失败"""

    def __init__(
        self,
        message: str,
        step_name: str = "",
        step_index: int = -1,
        cause: Exception | None = None,
    ) -> None:
        self.step_index = step_index
        self.cause = cause
        super().__init__(message, step_name)


class VideoValidationError(PipelineError):
    """视频文件验证失败（不存在、为空、格式不支持等）"""
    pass


class ImageValidationError(PipelineError):
    """图片文件验证失败（不存在、为空、格式不支持等）"""
    pass


class MAARecognitionError(PipelineError):
    """MAA识别引擎调用失败"""
    pass


class ConfigError(PipelineError):
    """配置文件加载或校验失败"""
    pass
