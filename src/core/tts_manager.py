"""
TTS Voice Assistant - TTS Manager Module
TTS 引擎管理器：支持 edge-tts 主引擎 + pyttsx3 降级 + 本地缓存
"""

import asyncio
import collections
import hashlib
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from src.utils.logger import get_logger
from src.utils.paths import get_data_dir

logger = get_logger("tts_manager")



class TTSSource(Enum):
    """TTS 音频来源"""
    CACHE = "cache"           # 本地缓存（即时，延迟<50ms）
    EDGE_TTS = "edge-tts"     # 在线引擎（高质量，延迟300-650ms）
    SAPI5 = "sapi5"           # 系统 TTS（保底，机械音）


@dataclass
class TTSResult:
    """TTS 执行结果"""
    success: bool
    source: TTSSource
    audio_path: Optional[Path] = None
    error_msg: Optional[str] = None
    duration_ms: int = 0


class TTSManager:
    """
    TTS 管理器
    三级降级策略：缓存 → edge-tts → 系统 TTS
    """
    
    # 缓存配置
    MAX_CACHE_ITEMS = 50
    COMMON_PHRASES = ["救命", "支援", "撤退", "谢谢", "抱歉", "你好", "收到"]
    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
    MAX_TEXT_LENGTH = 500  # 最大文本长度，超出则截断
    
    # Edge TTS 中文语音枚举（仅普通话）
    AVAILABLE_EDGE_VOICES = [
        "zh-CN-XiaoxiaoNeural",
        "zh-CN-YunxiNeural",
        "zh-CN-YunjianNeural",
        "zh-CN-YunyangNeural",
        "zh-CN-YunxiaNeural",
        "zh-CN-XiaoyiNeural",
    ]
    
    def __init__(self, cache_dir: Optional[Path] = None, config=None):
        """
        初始化 TTS 管理器
        
        Args:
            cache_dir: 缓存目录，默认使用项目 cache/audio
            config: 配置对象（用于设备ID持久化）
        """
        if cache_dir is None:
            cache_dir = get_data_dir() / "cache" / "audio"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 配置对象
        self._config = config
        self._override_device_id: Optional[int] = None
        if config is not None:
            self._override_device_id = config.get("audio_device_id", None)
        
        # 初始化状态
        self._fallback_engine = None
        self._fallback_lock = threading.Lock()
        self._pygame_initialized = False
        self._current_playback_thread: Optional[threading.Thread] = None
        self._playback_stop_event = threading.Event()
        
        # 音量控制 (Day 7)
        self._volume = 1.0
        if config is not None:
            self._volume = config.get("volume", 1.0)
        self._volume_lock = threading.Lock()
        
        # Edge TTS 配置
        self._edge_voice = config.get("edge_voice", self.DEFAULT_VOICE) if config else self.DEFAULT_VOICE
        self._edge_rate = config.get("edge_rate", "+0%") if config else "+0%"
        self._edge_pitch = config.get("edge_pitch", "+0Hz") if config else "+0Hz"
        self._edge_volume = config.get("edge_volume", "+0%") if config else "+0%"
        
        # SAPI5 配置
        self._sapi5_rate = config.get("sapi5_rate", 180) if config else 180
        self._sapi5_volume = config.get("sapi5_volume", 0.9) if config else 0.9
        
        # 播放队列 (Day 7)
        self._speak_queue = collections.deque()
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._queue_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self._queue_thread.start()
        
        # 初始化音频系统
        self._init_pygame()
        # pyttsx3 初始化可能较慢，放到后台线程避免阻塞主线程
        threading.Thread(target=self._init_fallback, daemon=True).start()
        
        # 后台预加载常用语
        self._preload_thread: Optional[threading.Thread] = None
        self.preload_common()
        
        logger.info(f"初始化完成，缓存目录: {self.cache_dir}, 音量: {int(self._volume * 100)}%")
    
    def _init_pygame(self):
        """初始化 pygame 音频系统"""
        try:
            import pygame
            pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=512)
            self._pygame_initialized = True
            logger.info("pygame 音频初始化成功")
        except Exception as e:
            logger.warning(f"pygame 初始化失败: {e}")
    
    def _init_fallback(self):
        """初始化降级引擎 (pyttsx3)"""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', self._sapi5_rate)
            engine.setProperty('volume', self._sapi5_volume)
            
            # 尝试设置中文语音
            voices = engine.getProperty('voices')
            for voice in voices:
                if 'chinese' in voice.name.lower() or 'zh' in voice.id.lower():
                    engine.setProperty('voice', voice.id)
                    logger.info(f"系统 TTS 使用中文语音: {voice.name}")
                    break
            else:
                logger.info("系统 TTS 初始化完成（未找到中文语音）")
            
            with self._fallback_lock:
                self._fallback_engine = engine
                
        except Exception as e:
            logger.error(f"系统 TTS 初始化失败: {e}")
            with self._fallback_lock:
                self._fallback_engine = None
    
    def get_cache_path(self, text: str, voice: str = None, rate: str = None, pitch: str = None, volume: str = None) -> Path:
        """
        生成缓存文件路径
        
        Args:
            text: 文本内容
            voice: 语音ID
            rate: 语速
            pitch: 音调
            volume: 合成音量
            
        Returns:
            缓存文件路径
        """
        if voice is None:
            voice = self._edge_voice
        if rate is None:
            rate = self._edge_rate
        if pitch is None:
            pitch = self._edge_pitch
        if volume is None:
            volume = self._edge_volume
        hash_key = hashlib.md5(f"{voice}:{rate}:{pitch}:{volume}:{text}".encode('utf-8')).hexdigest()
        return self.cache_dir / f"{hash_key}.mp3"
    
    def is_cached(self, text: str, voice: str = None) -> bool:
        """检查文本是否已缓存"""
        return self.get_cache_path(text, voice).exists()
    
    def speak(self, text: str, 
              on_complete: Optional[Callable[[TTSResult], None]] = None,
              voice: str = None) -> TTSResult:
        """
        主入口：文字转语音并播放
        
        执行流程：缓存检查 → edge-tts → 系统TTS
        
        Args:
            text: 要朗读的文本
            on_complete: 播放完成后的回调
            voice: 指定的语音ID
            
        Returns:
            TTSResult 执行结果
        """
        start_time = time.time()
        text = text.strip()
        
        if not text:
            result = TTSResult(success=False, source=TTSSource.SAPI5, 
                             error_msg="空文本")
            if on_complete:
                on_complete(result)
            return result
        
        # 超长文本截断（Day 8 边界处理）
        original_len = len(text)
        if original_len > self.MAX_TEXT_LENGTH:
            text = text[:self.MAX_TEXT_LENGTH]
            logger.warning(f"文本超长({original_len}字)，已截断至{self.MAX_TEXT_LENGTH}字")
        
        logger.info(f"开始生成: '{text[:30]}...' " if len(text) > 30 else f"开始生成: '{text}'")
        
        result = None
        
        try:
            # 第一级：检查缓存
            cache_path = self.get_cache_path(text, voice)
            if cache_path.exists():
                logger.info(f"缓存命中: {cache_path.name}")
                self._play_audio(cache_path)
                duration_ms = int((time.time() - start_time) * 1000)
                result = TTSResult(success=True, source=TTSSource.CACHE, 
                                 audio_path=cache_path, duration_ms=duration_ms)
            else:
                # 第二级：edge-tts
                logger.info("缓存未命中，请求 edge-tts...")
                try:
                    audio_path = self._generate_edge_tts_sync(text, voice)
                    self._play_audio(audio_path)
                    self._clean_cache_if_needed()
                    duration_ms = int((time.time() - start_time) * 1000)
                    result = TTSResult(success=True, source=TTSSource.EDGE_TTS, 
                                     audio_path=audio_path, duration_ms=duration_ms)
                except Exception as e:
                    logger.warning(f"edge-tts 失败: {e}")
                    # 第三级：系统 TTS
                    result = self._speak_fallback(text, start_time)
                    
        except Exception as e:
            logger.error(f"TTS 执行失败: {e}")
            result = TTSResult(success=False, source=TTSSource.SAPI5, 
                             error_msg=str(e))
        
        if on_complete:
            on_complete(result)
        
        return result
    
    def speak_async(self, text: str,
                    on_complete: Optional[Callable[[TTSResult], None]] = None,
                    voice: str = None):
        """
        异步执行 TTS（加入播放队列，不阻塞 UI 线程）
        
        Day 7: 支持多文本排队播放，连续发送不丢包
        
        Args:
            text: 要朗读的文本
            on_complete: 播放完成后的回调
            voice: 指定的语音ID
        """
        with self._queue_lock:
            self._speak_queue.append((text, on_complete, voice))
            self._queue_event.set()
    
    def interrupt_and_speak(self, text: str,
                            on_complete: Optional[Callable[[TTSResult], None]] = None,
                            voice: str = None):
        """
        打断当前播放，清空队列，立即播放新文本（Day 7: 打断重播）
        
        Args:
            text: 要朗读的文本
            on_complete: 播放完成后的回调
            voice: 指定的语音ID
        """
        self.stop_playback(clear_queue=True)
        with self._queue_lock:
            self._speak_queue.appendleft((text, on_complete, voice))
            self._queue_event.set()
    
    def _queue_worker(self):
        """队列消费线程：依次取出任务并执行"""
        while not self._shutdown_event.is_set():
            self._queue_event.wait()
            self._queue_event.clear()
            
            while True:
                with self._queue_lock:
                    if not self._speak_queue:
                        break
                    text, on_complete, voice = self._speak_queue.popleft()
                
                self._playback_stop_event.clear()
                result = self.speak(text, on_complete=None, voice=voice)
                if on_complete:
                    on_complete(result)
    
    def _generate_edge_tts_sync(self, text: str, voice: str = None) -> Path:
        """
        同步方式生成 edge-tts 音频（在线）
        
        Args:
            text: 文本内容
            voice: 语音ID
            
        Returns:
            生成的音频文件路径
        """
        import edge_tts
        
        if voice is None:
            voice = self._edge_voice
        
        cache_path = self.get_cache_path(text, voice)
        
        # 运行异步生成（带 5 秒超时，Day 5 新增）
        async def _generate():
            communicate = edge_tts.Communicate(
                text, voice,
                rate=self._edge_rate,
                pitch=self._edge_pitch,
                volume=self._edge_volume,
            )
            await communicate.save(str(cache_path))
        
        async def _generate_with_timeout():
            await asyncio.wait_for(_generate(), timeout=5.0)
        
        try:
            asyncio.run(_generate_with_timeout())
        except asyncio.TimeoutError:
            logger.warning("edge-tts 生成超时（5秒），准备降级...")
            # 清理可能的不完整缓存文件
            try:
                if cache_path.exists():
                    cache_path.unlink()
            except:
                pass
            raise
        
        logger.info(f"edge-tts 生成完成: {cache_path.name}")
        return cache_path
    
    def _speak_fallback(self, text: str, start_time: float = None) -> TTSResult:
        """
        保底方案：使用系统 TTS (pyttsx3)
        
        Args:
            text: 文本内容
            start_time: 开始时间戳
            
        Returns:
            TTSResult
        """
        with self._fallback_lock:
            engine = self._fallback_engine
        
        if engine is None:
            return TTSResult(success=False, source=TTSSource.SAPI5, 
                           error_msg="系统 TTS 未初始化")
        
        try:
            logger.info("使用系统 TTS 保底...")
            
            # 生成临时文件
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
            
            # 合成语音
            engine.save_to_file(text, temp_path)
            engine.runAndWait()
            
            # 播放
            self._play_audio(Path(temp_path))
            
            # 清理临时文件
            try:
                Path(temp_path).unlink(missing_ok=True)
            except:
                pass
            
            duration_ms = 0
            if start_time:
                duration_ms = int((time.time() - start_time) * 1000)
            
            return TTSResult(success=True, source=TTSSource.SAPI5, 
                           duration_ms=duration_ms)
            
        except Exception as e:
            logger.error(f"系统 TTS 失败: {e}")
            return TTSResult(success=False, source=TTSSource.SAPI5, 
                           error_msg=str(e))
    
    def _play_audio(self, audio_path: Path):
        """
        播放音频文件
        优先使用 sounddevice（支持指定输出设备+音量调节），失败时用 pygame
        
        Day 7 改进：
        - sounddevice 播放支持音量调节和中断
        - pygame 降级保留音量和中断
        
        Args:
            audio_path: 音频文件路径
        """
        self._playback_stop_event.clear()
        
        # 获取当前音量
        with self._volume_lock:
            volume = self._volume
        
        # 尝试使用 sounddevice（可以指定虚拟声卡）
        try:
            import sounddevice as sd
            import soundfile as sf
            import numpy as np
            
            data, samplerate = sf.read(str(audio_path))
            
            # 音量调节
            if volume != 1.0:
                data = data * volume
                data = np.clip(data, -1.0, 1.0)
            
            # 查找虚拟声卡
            device_id = self.get_virtual_device_id()
            
            sd.play(data, samplerate, device=device_id)
            
            # 轮询等待播放完成，支持中断
            wait_thread = threading.Thread(target=sd.wait)
            wait_thread.start()
            while wait_thread.is_alive():
                if self._playback_stop_event.is_set():
                    sd.stop()
                wait_thread.join(timeout=0.1)
            
            logger.info("音频播放完成 (sounddevice)")
            return
            
        except Exception as e:
            logger.warning(f"sounddevice 播放失败: {e}")
        
        # 降级到 pygame
        if self._pygame_initialized:
            try:
                import pygame
                pygame.mixer.music.set_volume(volume)
                pygame.mixer.music.load(str(audio_path))
                pygame.mixer.music.play()
                
                # 等待播放完成
                while pygame.mixer.music.get_busy():
                    if self._playback_stop_event.is_set():
                        pygame.mixer.music.stop()
                        break
                    pygame.time.Clock().tick(10)
                
                logger.info("音频播放完成 (pygame)")
                return
            except Exception as e:
                logger.warning(f"pygame 播放失败: {e}")
        
        logger.error("音频播放失败：无可用播放器")
    
    def stop_playback(self, clear_queue: bool = False):
        """
        停止当前播放
        
        Day 7: 支持清空播放队列
        
        Args:
            clear_queue: 是否清空待播放队列
        """
        self._playback_stop_event.set()
        try:
            import sounddevice as sd
            sd.stop()
        except:
            pass
        try:
            import pygame
            pygame.mixer.music.stop()
        except:
            pass
        
        if clear_queue:
            with self._queue_lock:
                self._speak_queue.clear()
            logger.info("播放队列已清空")
    
    def set_volume(self, volume: float):
        """
        设置 TTS 音量
        
        Args:
            volume: 0.0 ~ 1.0
        """
        volume = max(0.0, min(1.0, float(volume)))
        with self._volume_lock:
            self._volume = volume
        if self._config is not None:
            self._config.set("volume", volume)
        logger.info(f"音量已设置为 {int(volume * 100)}%")
    
    def get_volume(self) -> float:
        """获取当前音量"""
        with self._volume_lock:
            return self._volume
    
    def set_edge_voice(self, voice: str):
        """设置 Edge TTS 语音"""
        self._edge_voice = voice
        if self._config is not None:
            self._config.set("edge_voice", voice)
        logger.info(f"Edge TTS 语音已设置为: {voice}")
    
    def set_edge_rate(self, rate: str):
        """设置 Edge TTS 语速"""
        self._edge_rate = rate
        if self._config is not None:
            self._config.set("edge_rate", rate)
        logger.info(f"Edge TTS 语速已设置为: {rate}")
    
    def set_edge_pitch(self, pitch: str):
        """设置 Edge TTS 音调"""
        self._edge_pitch = pitch
        if self._config is not None:
            self._config.set("edge_pitch", pitch)
        logger.info(f"Edge TTS 音调已设置为: {pitch}")
    
    def set_edge_volume(self, volume: str):
        """设置 Edge TTS 合成音量"""
        self._edge_volume = volume
        if self._config is not None:
            self._config.set("edge_volume", volume)
        logger.info(f"Edge TTS 合成音量已设置为: {volume}")
    
    def set_sapi5_rate(self, rate: int):
        """设置系统 TTS 语速"""
        self._sapi5_rate = rate
        if self._config is not None:
            self._config.set("sapi5_rate", rate)
        with self._fallback_lock:
            if self._fallback_engine:
                self._fallback_engine.setProperty('rate', rate)
        logger.info(f"系统 TTS 语速已设置为: {rate}")
    
    def set_sapi5_volume(self, volume: float):
        """设置系统 TTS 音量"""
        self._sapi5_volume = volume
        if self._config is not None:
            self._config.set("sapi5_volume", volume)
        with self._fallback_lock:
            if self._fallback_engine:
                self._fallback_engine.setProperty('volume', volume)
        logger.info(f"系统 TTS 音量已设置为: {volume}")
    
    def get_output_devices(self) -> list:
        """
        获取所有可用音频输出设备列表（按名称去重）
        
        Windows 下同一个设备可能因不同 Host API（MME/WASAPI/DirectSound）
        出现多次，保留第一个 device_id 即可。
        
        Returns:
            列表，元素为 (device_id, device_name)
        """
        try:
            import sounddevice as sd
            seen_names = set()
            devices = []
            for i, device in enumerate(sd.query_devices()):
                if device.get('max_output_channels', 0) > 0:
                    name = device.get('name', 'Unknown')
                    if name not in seen_names:
                        seen_names.add(name)
                        devices.append((i, name))
            return devices
        except Exception as e:
            logger.error(f"查询音频设备失败: {e}")
            return []
    
    def set_virtual_device(self, device_id: Optional[int], device_name: Optional[str] = None):
        """
        设置音频输出设备（持久化到配置）
        
        Args:
            device_id: 设备ID，None 表示自动检测
            device_name: 设备名称（用于显示）
        """
        self._override_device_id = device_id
        if self._config is not None:
            self._config.set("audio_device_id", device_id)
            self._config.set("audio_device_name", device_name)
        
        label = device_name or f"设备 {device_id}"
        logger.info(f"输出设备已设置: {label if device_id is not None else '自动检测'}")
    
    def get_virtual_device_id(self) -> Optional[int]:
        """
        获取 VB-CABLE 虚拟声卡设备 ID
        支持多种 CABLE 变体: CABLE In, CABLE Input, VB-Audio Virtual Cable 等
        
        Returns:
            设备ID，未找到返回 None
        """
        try:
            import sounddevice as sd
            
            # 如果用户配置了特定设备ID，优先使用
            if self._override_device_id is not None:
                try:
                    device = sd.query_devices(self._override_device_id)
                    if device.get('max_output_channels', 0) > 0:
                        return self._override_device_id
                except Exception:
                    pass
                logger.warning(f"配置的设备 {self._override_device_id} 已失效，回退到自动检测")
            
            devices = sd.query_devices()
            
            # 可能的虚拟声卡名称关键字（优先级排序）
            cable_keywords = [
                'CABLE Input',     # 标准 VB-CABLE
                'CABLE In',        # 16ch 版本
                'VB-Audio Virtual Cable',
                'CABLE Output',    # 有时显示为 Output
                'CABLE',
            ]
            
            for keyword in cable_keywords:
                for i, device in enumerate(devices):
                    name = device.get('name', '')
                    if keyword.upper() in name.upper() and device.get('max_output_channels', 0) > 0:
                        logger.info(f"发现虚拟声卡: [{i}] {name}")
                        return i
            
            # 如果没找到，打印所有设备供调试
            logger.warning("未找到虚拟声卡，可用输出设备:")
            for i, device in enumerate(devices):
                if device.get('max_output_channels', 0) > 0:
                    logger.info(f"  [{i}] {device.get('name', 'Unknown')}")
            
            return None
        except Exception as e:
            logger.error(f"查询音频设备失败: {e}")
            return None
    
    def check_virtual_cable(self) -> Tuple[bool, str]:
        """
        检查虚拟声卡状态
        
        Returns:
            (是否安装, 状态信息)
        """
        device_id = self.get_virtual_device_id()
        if device_id is not None:
            return True, f"虚拟声卡已就绪 (设备ID: {device_id})"
        else:
            return False, "未检测到 VB-CABLE 虚拟声卡"
    
    def preload_common(self):
        """后台预加载常用语"""
        def _preload():
            logger.info("后台预加载常用语...")
            for phrase in self.COMMON_PHRASES:
                cache_path = self.get_cache_path(phrase)
                if cache_path.exists():
                    continue
                
                try:
                    self._generate_edge_tts_sync(phrase)
                    logger.info(f"预加载完成: '{phrase}'")
                except Exception as e:
                    logger.warning(f"预加载失败 '{phrase}': {e}")
            
            logger.info("常用语预加载完成")
        
        self._preload_thread = threading.Thread(target=_preload, daemon=True)
        self._preload_thread.start()
    
    def _clean_cache_if_needed(self):
        """清理过期缓存（简单 LRU）"""
        try:
            files = sorted(self.cache_dir.glob("*.mp3"), 
                          key=lambda f: f.stat().st_mtime, reverse=True)
            
            if len(files) > self.MAX_CACHE_ITEMS:
                for old_file in files[self.MAX_CACHE_ITEMS:]:
                    try:
                        old_file.unlink()
                        logger.info(f"清理缓存: {old_file.name}")
                    except:
                        pass
        except Exception as e:
            logger.warning(f"缓存清理失败: {e}")
    
    def get_cache_stats(self) -> dict:
        """
        获取缓存统计信息
        
        Returns:
            统计字典
        """
        try:
            files = list(self.cache_dir.glob("*.mp3"))
            total_size = sum(f.stat().st_size for f in files)
            return {
                "count": len(files),
                "total_size_mb": round(total_size / 1024 / 1024, 2),
                "max_items": self.MAX_CACHE_ITEMS,
                "cache_dir": str(self.cache_dir)
            }
        except Exception as e:
            return {"error": str(e)}
    
    def clear_cache(self):
        """清空缓存"""
        try:
            for f in self.cache_dir.glob("*.mp3"):
                f.unlink()
            logger.info("缓存已清空")
        except Exception as e:
            logger.warning(f"清空缓存失败: {e}")
    
    def shutdown(self):
        """关闭 TTS 管理器，释放资源"""
        logger.info("正在关闭...")
        self._shutdown_event.set()
        self.stop_playback(clear_queue=True)
        self._queue_event.set()
        
        if self._queue_thread.is_alive():
            self._queue_thread.join(timeout=2.0)
        
        if self._fallback_engine:
            try:
                self._fallback_engine.stop()
            except:
                pass
        
        try:
            import pygame
            pygame.mixer.quit()
        except:
            pass
        
        logger.info("已关闭")


# 单例模式
_tts_manager_instance: Optional[TTSManager] = None


def get_tts_manager(config=None) -> TTSManager:
    """获取 TTSManager 单例"""
    global _tts_manager_instance
    if _tts_manager_instance is None:
        _tts_manager_instance = TTSManager(config=config)
    return _tts_manager_instance


def shutdown_tts_manager():
    """关闭 TTSManager 单例"""
    global _tts_manager_instance
    if _tts_manager_instance:
        _tts_manager_instance.shutdown()
        _tts_manager_instance = None



