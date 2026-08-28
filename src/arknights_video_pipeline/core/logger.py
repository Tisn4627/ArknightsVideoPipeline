"""
core.logger - 统一日志系统

提供双通道日志输出（控制台 + 文件），支持日志轮转和步骤子 logger。
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import TextIO

_FILE_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"


def _create_file_handler(
    log_dir: str, max_bytes: int, backup_count: int
) -> RotatingFileHandler:
    """创建写入 log_dir/pipeline.log 的轮转文件 handler（两分支共用）"""
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "pipeline.log")
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(_FILE_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    )
    return file_handler


def setup_logger(
    name: str = "pipeline",
    log_dir: str | None = None,
    log_level: int = logging.INFO,
    log_to_file: bool = True,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 3,
    console_stream: TextIO | None = None,
) -> logging.Logger:
    """配置并返回统一 logger 实例

    Args:
        name: logger 名称
        log_dir: 日志文件目录，为 None 则仅控制台输出
        log_level: 日志级别
        log_to_file: 是否输出到文件
        max_bytes: 单个日志文件最大字节数（轮转阈值）
        backup_count: 保留的历史日志文件数量
        console_stream: 控制台输出流，默认 stdout

    Returns:
        配置好的 logging.Logger 实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # 避免重复添加 handler，但仍更新日志级别以反映最新配置
    if logger.handlers:
        file_handler_ok = False
        for handler in list(logger.handlers):
            if isinstance(handler, RotatingFileHandler):
                # 参数未变化时复用现有文件 handler；log_dir/轮转参数
                # 变化时移除重建，否则运行中切换输出目录后日志仍写入
                # 旧位置，新旧日志割裂
                same = (
                    log_to_file and log_dir
                    and os.path.abspath(handler.baseFilename)
                    == os.path.abspath(os.path.join(log_dir, "pipeline.log"))
                    and handler.maxBytes == max_bytes
                    and handler.backupCount == backup_count
                )
                if not same:
                    logger.removeHandler(handler)
                    handler.close()
                else:
                    file_handler_ok = True
            elif isinstance(handler, logging.StreamHandler):
                handler.setLevel(log_level)
        if log_to_file and log_dir and not file_handler_ok:
            logger.addHandler(
                _create_file_handler(log_dir, max_bytes, backup_count)
            )
        return logger

    # ── 控制台 handler ──────────────────────────────────
    stream = console_stream or sys.stdout
    console_handler = logging.StreamHandler(stream)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(message)s")
    )
    logger.addHandler(console_handler)

    # ── 文件 handler（带轮转） ──────────────────────────
    if log_to_file and log_dir:
        logger.addHandler(_create_file_handler(log_dir, max_bytes, backup_count))

    return logger


def get_step_logger(
    step_name: str,
    log_dir: str | None = None,
    log_level: int = logging.INFO,
    log_to_file: bool = True,
) -> logging.Logger:
    """获取步骤子 logger，名称格式: pipeline.<step_name>

    子 logger 自身不挂任何 handler，日志经 propagate 交给父
    "pipeline" logger 统一输出。若为每个子 logger 单独挂 handler，
    同一条日志会在控制台/文件中各出现两次，且多个 RotatingFileHandler
    轮转同一 pipeline.log 时在 Windows 上会因文件占用互相失败。
    """
    # 确保父 "pipeline" logger 已按当前参数完成配置
    setup_logger(
        "pipeline",
        log_dir=log_dir,
        log_level=log_level,
        log_to_file=log_to_file,
    )
    child = logging.getLogger(f"pipeline.{step_name}")
    child.setLevel(log_level)
    child.propagate = True
    return child
