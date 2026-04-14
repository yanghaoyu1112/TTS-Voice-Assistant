"""
TTS Voice Assistant - Logger Module
基础日志系统：输出到控制台并写入 logs/app.log
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from src.utils.paths import get_data_dir


def setup_logger(name: str = "tts_app", log_dir: Optional[Path] = None) -> logging.Logger:
    """
    初始化日志记录器
    
    Args:
        name: 日志器名称
        log_dir: 日志目录，默认使用项目根目录/程序所在目录下的 logs/
        
    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # 日志格式
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件输出
    if log_dir is None:
        log_dir = get_data_dir() / "logs"
    
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / "app.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = "tts_app") -> logging.Logger:
    """获取已配置的日志记录器"""
    return logging.getLogger(name)
