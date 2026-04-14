"""
TTS Voice Assistant - Configuration Manager
JSON 配置管理器：持久化用户设置
"""

import json
from pathlib import Path
from typing import Any, Optional

from src.utils.logger import get_logger
from src.utils.paths import get_data_dir

logger = get_logger("config")


class Config:
    """JSON 配置文件管理器"""
    
    DEFAULT_CONFIG = {
        "audio_device_id": None,        # None = 自动检测
        "audio_device_name": None,      # 设备名称（仅用于显示）
        "volume": 1.0,                  # 播放音量 0.0 ~ 1.0
        "hotkey": "<ctrl>+<shift>+t",   # 全局热键组合
        "edge_voice": "zh-CN-XiaoxiaoNeural",  # Edge TTS 语音
        "edge_rate": "+0%",                      # Edge TTS 语速
        "edge_pitch": "+0Hz",                    # Edge TTS 音调
        "edge_volume": "+0%",                    # Edge TTS 合成音量
        "sapi5_rate": 180,                       # 系统 TTS 语速
        "sapi5_volume": 0.9,                     # 系统 TTS 音量
    }
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置文件路径，默认使用项目根目录 config.json
        """
        if config_path is None:
            config_path = get_data_dir() / "config.json"
        
        self.config_path = Path(config_path)
        self._data = {}
        self.is_first_run = False
        self.load()
    
    def load(self):
        """从文件加载配置"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
            except Exception as e:
                logger.warning(f"加载配置失败: {e}，使用默认配置")
                self._data = {}
        else:
            # 首次运行：创建默认配置
            self._data = self.DEFAULT_CONFIG.copy()
            self.is_first_run = True
            self.save()
            logger.info(f"首次运行，已创建默认配置文件: {self.config_path}")
        
        # 合并默认值（不覆盖已有值）
        updated = False
        for key, value in self.DEFAULT_CONFIG.items():
            if key not in self._data:
                self._data[key] = value
                updated = True
        
        if updated:
            self.save()
    
    def save(self):
        """保存配置到文件"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存配置失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self._data.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置配置项并自动保存"""
        self._data[key] = value
        self.save()
    
    def update(self, updates: dict):
        """批量更新配置"""
        self._data.update(updates)
        self.save()
    
    def all(self) -> dict:
        """获取所有配置的副本"""
        return self._data.copy()


# 单例模式
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """获取 Config 单例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
