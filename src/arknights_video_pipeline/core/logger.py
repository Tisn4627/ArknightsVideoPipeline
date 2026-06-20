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
        for handler in logger.handlers:
            # 仅更新控制台 handler 的级别，文件 handler 保持 DEBUG 以记录全量日志
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, RotatingFileHandler
            ):
                handler.setLevel(log_level)
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
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)

    return logger


def get_step_logger(
    step_name: str,
    log_dir: str | None = None,
    log_level: int = logging.INFO,
    log_to_file: bool = True,
) -> logging.Logger:
    """获取步骤子 logger，名称格式: pipeline.<step_name>"""
    return setup_logger(
        f"pipeline.{step_name}",
        log_dir=log_dir,
        log_level=log_level,
        log_to_file=log_to_file,
    )
