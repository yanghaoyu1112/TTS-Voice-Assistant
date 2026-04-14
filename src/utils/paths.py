"""
TTS Voice Assistant - Path Utilities
统一处理开发模式与 PyInstaller 打包后的资源路径
"""

import sys
from pathlib import Path


def is_frozen() -> bool:
    """判断是否运行在 PyInstaller 打包后的环境中"""
    return getattr(sys, 'frozen', False)


def get_base_dir() -> Path:
    """
    获取应用基础目录
    - 开发模式：项目根目录
    - 打包模式：exe 所在目录
    """
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


def get_resource_path(relative_path: str) -> Path:
    """
    获取资源文件路径（支持 PyInstaller 打包）
    PyInstaller 会把 --add-data 的资源解压到 _MEIPASS 临时目录
    """
    if is_frozen():
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent.parent.parent
    return base_path / relative_path


def get_data_dir() -> Path:
    """
    获取可写数据目录（用于 config.json, logs, cache）
    - 开发模式：项目根目录
    - 打包模式：exe 所在目录（便携模式）
    """
    return get_base_dir()
