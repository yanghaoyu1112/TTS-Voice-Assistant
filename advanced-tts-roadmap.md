<!--
 * @Description: 
 * @Author: yanghaoyu
 * @Date: 2026-04-10 14:07:02
 * @LastEditTime: 2026-04-10 14:38:22
 * @LastEditors: yanghaoyu
-->

# TTS 语音助手 - 技术路线文档（PyQt6轻量版）

## 1. 产品定位

一款**极致轻量**的桌面 TTS 语音转发工具，专为游戏场景优化。用户通过全局热键唤出悬浮输入框，输入文字后通过虚拟音频设备输出语音，供 Discord/QQ/YY/Teams 等语音软件作为麦克风输入使用。

**核心目标**：

- 单进程运行，内存占用 < 100MB
- 启动速度 < 3 秒（冷启动）
- 完全离线可用（支持网络降级）
- 零显卡占用（纯 CPU 推理）

---

## 2. 技术架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     TTS 语音助手 (单一进程)                       │
│                         Python 3.10+                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                 PyQt6 应用层 (UI + 逻辑)                   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │  │
│  │  │  悬浮窗口    │  │  设置面板    │  │   系统托盘菜单   │  │  │
│  │  │  - 无边框   │  │  - 简洁配置  │  │   - 开机自启    │  │  │
│  │  │  - 全局置顶 │  │  - 热键设置  │  │   - 退出/重启   │  │  │
│  │  │  - 透明背景 │  │             │  │                 │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘  │  │
│  │                                                             │  │
│  │  ┌─────────────────────────────────────────────────────────┐│  │
│  │  │         全局热键管理 (RegisterHotKey + NativeEventFilter) ││  │
│  │  │              Ctrl+Shift+T  唤出/隐藏悬浮窗              ││  │
│  │  └─────────────────────────────────────────────────────────┘│  │
│  └───────────────────────────────────────────────────────────┘  │
│                              ↓                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    TTS 引擎管理器                           │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │  │
│  │  │   主引擎     │  │   降级引擎    │  │    本地缓存       │ │  │
│  │  │  edge-tts   │  │  pyttsx3     │  │  - LRU磁盘缓存    │ │  │
│  │  │  (在线/高质)│  │ (离线/保底)   │  │  - 常用语预缓存   │ │  │
│  │  │  失败时自动降级│             │  │  - 无网络时命中   │ │  │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              ↓                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                   音频输出管理                             │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │  │
│  │  │  虚拟声卡控制 │  │   音频播放    │  │   设备监控       │ │  │
│  │  │ VB-CABLE    │  │  pygame/     │  │  - 检测设备      │ │  │
│  │  │ - 路由检测   │  │  sounddevice │  │  - 自动重连      │ │  │
│  │  │ - 音量调节   │  │              │  │                  │ │  │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 技术栈选型

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| **UI 框架** | PyQt6 (6.6+) | 原生性能，内存占用低，支持无边框透明窗口 |
| **全局热键** | Windows `RegisterHotKey` + `QAbstractNativeEventFilter` | 系统级热键，与 Qt 托盘 100% 兼容，游戏内可触发 |
| **TTS 主引擎** | edge-tts | 免费、高音质、中文优秀 |
| **TTS 降级** | pyttsx3 (SAPI5) | Windows 内置，零依赖，离线保底 |
| **音频播放** | pygame.mixer / sounddevice | 低延迟，支持指定输出设备 |
| **虚拟音频** | VB-CABLE (系统级) | 稳定可靠，无需自研驱动 |
| **打包工具** | PyInstaller + Nuitka | 单文件 exe，无需 Python 环境 |
| **配置存储** | JSON (本地文件) | 无需数据库，简单可编辑 |

---

## 3. 核心模块设计

### 3.1 悬浮窗口 (PyQt6)

```python
# src/ui/overlay_window.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QLabel
from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette


class OverlayWindow(QWidget):
    def __init__(self, tts_manager):
        super().__init__()
        self.tts_manager = tts_manager
        self.drag_pos = None
        self.init_ui()

    def init_ui(self):
        # 关键属性：无边框、透明、置顶、不夺焦
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |      # 无边框
            Qt.WindowType.WindowStaysOnTopHint |       # 全局置顶
            Qt.WindowType.Tool |                       # 不在任务栏显示
            Qt.WindowType.WindowDoesNotAcceptFocus |   # 关键：不抢夺焦点
            Qt.WindowType.WindowTransparentForInput    # 可选：鼠标穿透（输入时关闭）
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)  # 显示但不激活

        # 布局
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        # 输入框
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入文字，回车发送...")
        self.input.setFont(QFont("Microsoft YaHei", 12))
        self.input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(30, 30, 30, 200);
                color: white;
                border: 1px solid rgba(255, 255, 255, 50);
                border-radius: 8px;
                padding: 8px;
            }
        """)
        self.input.returnPressed.connect(self.handle_send)
        self.input.keyPressEvent = self.handle_key_press  # 捕获 ESC

        # 状态标签
        self.status = QLabel("就绪")
        self.status.setStyleSheet("color: rgba(200, 200, 200, 180); font-size: 10px;")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.input)
        layout.addWidget(self.status)
        self.setLayout(layout)

        # 固定大小
        self.setFixedSize(400, 80)

    def handle_send(self):
        text = self.input.text().strip()
        if not text:
            return

        self.status.setText("生成语音...")
        self.input.setEnabled(False)

        # 异步调用 TTS（避免阻塞 UI）
        import threading
        threading.Thread(
            target=self.tts_manager.speak,
            args=(text, self.on_tts_finish),
            daemon=True
        ).start()

    def on_tts_finish(self, success: bool):
        # 使用信号槽或 QTimer 回到主线程更新 UI
        self.input.clear()
        self.input.setEnabled(True)
        self.status.setText("就绪" if success else "生成失败")
        QTimer.singleShot(2000, self.hide)  # 播放完成后自动隐藏

    def handle_key_press(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            QLineEdit.keyPressEvent(self.input, event)

    def show_overlay(self):
        """显示在鼠标当前位置或屏幕中央"""
        self.show()
        self.raise_()
        self.activateWindow()  # 尝试激活（某些游戏会阻止）
        self.input.setFocus()

    # 拖动实现
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
```

### 3.2 TTS 引擎管理（含本地缓存）

```python
# src/core/tts_manager.py
import asyncio
import edge_tts
import pyttsx3
import tempfile
import hashlib
from pathlib import Path
from typing import Callable, Optional
import pygame
import sounddevice as sd
import soundfile as sf


class TTSManager:
    """TTS管理器：支持edge-tts主引擎 + pyttsx3降级 + 本地缓存"""
    
    # MVP阶段缓存配置
    MAX_CACHE_ITEMS = 50          # 最多保留50条
    COMMON_PHRASES = ["救命", "支援", "撤退", "谢谢", "抱歉"]  # 预缓存常用语
    
    def __init__(self):
        self.cache_dir = Path("cache/audio")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 初始化 pygame 音频（指定输出到虚拟声卡）
        pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=512)

        # 初始化降级引擎（pyttsx3）
        self.fallback_engine = None
        self.init_fallback()

        # 后台预生成常用语
        self.preload_common()

    def init_fallback(self):
        """初始化 Windows 系统 TTS"""
        try:
            self.fallback_engine = pyttsx3.init()
            self.fallback_engine.setProperty('rate', 180)
            self.fallback_engine.setProperty('volume', 0.9)
            voices = self.fallback_engine.getProperty('voices')
            for voice in voices:
                if 'chinese' in voice.name.lower() or 'zh' in voice.id.lower():
                    self.fallback_engine.setProperty('voice', voice.id)
                    break
        except Exception as e:
            print(f"系统 TTS 初始化失败: {e}")

    def get_cache_path(self, text: str, voice: str = "zh-CN-XiaoxiaoNeural") -> Path:
        """生成缓存路径"""
        hash_key = hashlib.md5(f"{voice}:{text}".encode()).hexdigest()
        return self.cache_dir / f"{hash_key}.mp3"

    def speak(self, text: str, callback: Optional[Callable] = None) -> bool:
        """
        主入口：先查缓存 → 再请求edge-tts → 失败时降级到系统TTS
        """
        success = False
        source = "unknown"
        
        try:
            # 1. 尝试从缓存或edge-tts获取音频
            audio_path = self._get_audio_with_cache(text)
            if audio_path:
                self._play_audio(audio_path)
                success = True
                source = "cache" if "cache" in str(audio_path) else "edge-tts"
        except Exception as e:
            print(f"edge-tts/缓存失败: {e}")
            
        # 2. 失败时降级到系统TTS
        if not success:
            success = self._speak_fallback(text)
            source = "sapi5"

        if callback:
            callback(success, source)
        return success

    def _get_audio_with_cache(self, text: str) -> Optional[Path]:
        """获取音频（带缓存机制）"""
        cache_path = self.get_cache_path(text)
        
        # 缓存命中：直接返回
        if cache_path.exists():
            return cache_path
            
        # 缓存未命中：请求edge-tts并保存到缓存
        asyncio.run(self._generate_edge_tts(text, cache_path))
        self._clean_cache_if_needed()  # 清理过期缓存
        return cache_path

    async def _generate_edge_tts(self, text: str, output_path: Path):
        """异步生成语音并保存到缓存"""
        communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
        await communicate.save(str(output_path))

    def _speak_fallback(self, text: str) -> bool:
        """保底方案：系统 TTS（pyttsx3）"""
        if not self.fallback_engine:
            return False

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        self.fallback_engine.save_to_file(text, temp_path)
        self.fallback_engine.runAndWait()
        self._play_audio(temp_path)
        
        # 清理临时文件
        try:
            Path(temp_path).unlink()
        except:
            pass
        return True

    def _play_audio(self, audio_path: Path):
        """播放音频文件到虚拟声卡"""
        try:
            # 优先使用sounddevice（支持指定设备）
            data, samplerate = sf.read(str(audio_path))
            device_id = self.get_virtual_device_id()
            sd.play(data, samplerate, device=device_id)
            sd.wait()
        except Exception as e:
            # 降级到pygame（播放至默认设备）
            pygame.mixer.music.load(str(audio_path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)

    def get_virtual_device_id(self) -> Optional[int]:
        """获取 VB-CABLE 设备 ID"""
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            if 'CABLE' in device['name'] and device['max_output_channels'] > 0:
                return i
        return None

    def preload_common(self):
        """后台预生成常用语（提升首次使用体验）"""
        def preload():
            for phrase in self.COMMON_PHRASES:
                path = self.get_cache_path(phrase)
                if not path.exists():
                    try:
                        asyncio.run(self._generate_edge_tts(phrase, path))
                    except:
                        pass
        import threading
        threading.Thread(target=preload, daemon=True).start()

    def _clean_cache_if_needed(self):
        """简单LRU清理：保留最近MAX_CACHE_ITEMS个文件"""
        files = sorted(self.cache_dir.glob("*.mp3"), 
                      key=lambda f: f.stat().st_mtime, reverse=True)
        for old_file in files[self.MAX_CACHE_ITEMS:]:
            try:
                old_file.unlink()
            except:
                pass
```

### 3.3 全局热键监听

```python
# src/core/hotkey_manager.py
import ctypes
import re
from ctypes import wintypes
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QAbstractNativeEventFilter
from PyQt6.QtWidgets import QApplication, QWidget

WM_HOTKEY = 0x0312

MOD_MAP = {
    'ctrl': 0x0002,
    'alt': 0x0001,
    'shift': 0x0004,
    'cmd': 0x0008,
}

class WinGlobalHotkey(QObject):
    triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._app = QApplication.instance()
        self._hotkey_id = 1
        self._registered = False
        self._hotkey_str = "<ctrl>+<shift>+t"
        # 创建隐藏窗口以获取有效 HWND
        self._hidden = QWidget()
        self._hidden.setWindowFlags(Qt.WindowType.Tool)
        self._hidden.resize(1, 1)
        self._hidden.hide()
        self._hwnd = int(self._hidden.winId())

    def register(self, callback, hotkey=None):
        if hotkey:
            self._hotkey_str = hotkey
        # 解析热键
        parts = re.findall(r'<?([a-zA-Z0-9_-]+)>?', self._hotkey_str.lower())
        mods = [p for p in parts if p in MOD_MAP]
        main = [p for p in parts if p not in MOD_MAP][0]
        mod_flags = 0
        for m in mods:
            mod_flags |= MOD_MAP[m]
        vk = ord(main.upper()) if len(main) == 1 and main.isalnum() else None
        # 注册系统热键
        if ctypes.windll.user32.RegisterHotKey(self._hwnd, self._hotkey_id, mod_flags, vk):
            self._registered = True
            # 安装原生事件过滤器拦截 WM_HOTKEY
            self._filter = _HotkeyNativeEventFilter(self._hotkey_id, callback)
            self._app.installNativeEventFilter(self._filter)
        return self._registered

    def stop(self):
        if self._registered:
            ctypes.windll.user32.UnregisterHotKey(self._hwnd, self._hotkey_id)
            self._registered = False
        if self._filter:
            self._app.removeNativeEventFilter(self._filter)
            self._filter = None
```

### 3.4 主应用入口

```python
# src/main.py
import sys
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QAction, QFont

from src.ui.overlay_window import OverlayWindow
from src.core.tts_manager import get_tts_manager
from src.core.hotkey_manager import create_hotkey_manager
from src.utils.config import Config


class SignalBridge(QObject):
    """从工作线程/热键回调安全回到主线程"""
    show_overlay_requested = pyqtSignal()


class TTSApplication:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.config = Config()
        self.tts_manager = get_tts_manager(config=self.config)
        self.overlay = OverlayWindow()
        self.hotkey_manager = None
        self.tray_icon = None
        self.signal_bridge = SignalBridge()

        self._setup_tray()
        self._setup_hotkey()
        self.signal_bridge.show_overlay_requested.connect(self._show_overlay)

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self.app)
        self.tray_icon.setIcon(QIcon("resources/icon.png"))
        self.tray_icon.setToolTip("TTS 语音助手")

        menu = QMenu()
        show_action = QAction("显示悬浮窗", menu)
        show_action.triggered.connect(self._show_overlay)
        menu.addAction(show_action)
        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _setup_hotkey(self):
        self.hotkey_manager = create_hotkey_manager()
        hotkey_str = self.config.get("hotkey", "<ctrl>+<shift>+t")

        def on_hotkey():
            # 只发信号，绝不直接操作 GUI
            self.signal_bridge.show_overlay_requested.emit()

        success = self.hotkey_manager.register(on_hotkey, hotkey_str)
        if not success:
            print("全局热键注册失败")

    def _show_overlay(self):
        # 托盘与热键统一使用记忆位置
        self.overlay.show_at_saved_position()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_overlay()
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            self.tray_icon.contextMenu().popup(...)

    def run(self):
        sys.exit(self.app.exec())

    def quit(self):
        if self.hotkey_manager:
            self.hotkey_manager.stop()
        self.app.quit()


if __name__ == "__main__":
    app = TTSApplication()
    app.run()
```

---

## 4. 项目结构

```
tts-voice-assistant/
├── requirements.txt              # 依赖清单
├── build.py                      # PyInstaller 打包脚本
├── README.md
│
├── src/
│   ├── main.py                   # 应用入口
│   ├── __init__.py
│   │
│   ├── core/                     # 核心业务逻辑
│   │   ├── __init__.py
│   │   ├── tts_manager.py        # TTS引擎管理 + 本地缓存
│   │   └── hotkey_manager.py     # 全局热键监听
│   │
│   ├── ui/                       # 界面层
│   │   ├── __init__.py
│   │   └── overlay_window.py     # 悬浮输入框
│   │
│   └── utils/
│       ├── __init__.py
│       └── config.py             # JSON配置管理
│
├── resources/                    # 静态资源
│   └── icon.png                  # 托盘图标
│
└── cache/                        # 语音缓存（运行时生成，无需提交Git）
    └── audio/                    # MP3缓存文件
```

### requirements.txt

```
PyQt6>=6.6.0
edge-tts>=6.1.0
pyttsx3>=2.90
pygame>=2.5.0
sounddevice>=0.4.6
soundfile>=0.12.1
numpy>=1.24.0
```

---

## 5. 打包与分发

### 5.1 开发环境搭建

```bash
# 1. 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 开发模式运行
python src/main.py
```

### 5.2 生产打包（PyInstaller）

```python
# build.py
import PyInstaller.__main__

PyInstaller.__main__.run([
    'src/main.py',
    '--name=TTS语音助手',
    '--onefile',
    '--windowed',
    '--icon=resources/icon.ico',
    '--add-data=resources;resources',
    '--clean',
    '--noconfirm',
    '--hidden-import=edge_tts',
    '--hidden-import=pyttsx3.drivers',
    '--hidden-import=pyttsx3.drivers.sapi5',
])
```

打包命令：

```bash
python build.py
# 输出在 dist/TTS语音助手.exe
```

---

## 6. 降级策略

```
用户输入文字
    ↓
[第一级] 本地缓存（LRU磁盘缓存）
    - 缓存命中：直接播放（延迟<50ms）
    - 缓存未命中 → 继续
    ↓
[第二级] edge-tts（在线）
    - 请求微软服务器生成语音
    - 保存到本地缓存供下次使用
    - 失败（超时/无网络）→ 降级
    ↓
[第三级] pyttsx3 系统 TTS
    - Windows SAPI5 语音合成
    - 离线可用，零依赖
    - 机械音质，但保证可用性
```

---

## 7. 性能优化策略

### 7.1 CPU 与内存优化

- **强制 CPU 推理**：不调用 CUDA，确保显卡 100% 留给游戏
- **单线程异步**：edge-tts 网络请求使用 asyncio，播放使用独立线程
- **即时释放**：音频播放完成后立即 unload，不驻留内存
- **托盘驻留**：最小化到托盘时内存占用 < 50MB

### 7.2 本地缓存策略

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `MAX_CACHE_ITEMS` | 50 | 最多保留50条音频 |
| `COMMON_PHRASES` | 5个常用语 | 启动时后台预生成 |
| 清理策略 | 简单LRU | 超出上限时删除最旧文件 |

缓存带来的核心收益：
- **延迟降低**：从 300-650ms 降至 <50ms
- **离线可用**：缓存命中时不依赖网络
- **节省流量**：常用语无需重复下载

---

## 8. 用户交互流程

| 用户行为 | 软件响应 |
|----------|----------|
| 双击 exe 启动 | → 静默驻留系统托盘<br>检测 VB-CABLE，未安装则气泡提示 |
| 游戏中按 Ctrl+Shift+T | → 在记忆位置浮现半透明输入框<br>游戏保持焦点 |
| 输入 "前面有敌人" 按回车 | → 输入框显示"生成中..."<br>语音通过 CABLE 输出到 Discord |
| 播放完成 | → 输入框自动隐藏 |
| 按 ESC 或再次热键 | → 立即隐藏输入框 |

**状态指示**：
- 🟢 **绿色**：edge-tts（高质量）
- 🟡 **黄色**：本地缓存（即时）
- 🔴 **红色**：系统 TTS（保底，机械音）

---

## 9. 风险提示与应对

| 风险 | 应对方案 |
|------|----------|
| **edge-tts 被墙/失效** | 自动降级到系统 TTS，依赖本地缓存 |
| **杀毒软件误报** | 使用 `--onedir` 模式或代码签名 |
| **全屏游戏覆盖失败** | 提示用户切换为"无边框窗口模式" |
| **音频延迟** | 使用 sounddevice 替代 pygame |

---

## 10. 未来规划（非MVP）

以下内容不在 MVP 阶段实现，但可作为后续迭代方向：

### 10.1 增强缓存策略

- **模糊匹配缓存**：通过文本相似度匹配历史缓存（如 "撤退" 和 "快撤退" 复用同一份音频）
- **缓存过期时间**：支持按天数自动清理（如 7 天未使用自动删除）
- **缓存压缩**：对 MP3 进行批量压缩以节省磁盘空间

### 10.2 离线TTS引擎

- **Piper 本地模型**：作为 edge-tts 的替代方案，完全离线运行
- **模型按需下载**：首次使用时后台下载语音模型

### 10.3 高级功能

- **语音克隆**：支持用户录制样本克隆自己的声音
- **音效处理**：添加混响、变调等音效
- **快捷键定制**：支持用户自定义多个热键对应不同语音风格

---

## 参考资源

- **PyQt6 文档**: https://doc.qt.io/qtforpython-6/
- **edge-tts**: https://github.com/rany2/edge-tts
- **pyttsx3**: https://pyttsx3.readthedocs.io/
- **VB-CABLE**: https://vb-audio.com/Cable/
- **PyInstaller**: https://pyinstaller.org/

---

**文档版本**: 2.2 (MVP精简版)  
**更新日期**: 2026-04-14  
**优化方向**: 核心缓存优先、功能精简、快速迭代
