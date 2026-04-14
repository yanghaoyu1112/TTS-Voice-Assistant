"""
TTS Voice Assistant - Global Hotkey Manager Module
全局热键管理器 - Day 10 修复版

修复记录 (Day10 Fix):
- 弃用 pynput keyboard.Listener（与 PyQt6 QSystemTrayIcon 存在已知兼容性问题，
  会导致托盘左键/右键/中键全部失效）
- 改用 Windows 原生 RegisterHotKey + QAbstractNativeEventFilter
- 完全不使用低级键盘钩子，不创建额外监听线程，与 Qt 事件循环完全兼容
"""

import ctypes
import re
from ctypes import wintypes
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal, Qt, QAbstractNativeEventFilter
from PyQt6.QtWidgets import QApplication, QWidget

from src.utils.logger import get_logger

logger = get_logger("hotkey")

# Windows API 常量
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312

MOD_MAP = {
    'ctrl': 0x0002,   # MOD_CONTROL
    'alt': 0x0001,    # MOD_ALT
    'shift': 0x0004,  # MOD_SHIFT
    'cmd': 0x0008,    # MOD_WIN
}

VK_MAP = {
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'escape': 0x1B, 'esc': 0x1B,
    'space': 0x20,
    'tab': 0x09,
    'return': 0x0D, 'enter': 0x0D,
    'backspace': 0x08,
    'delete': 0x2E, 'del': 0x2E,
    'insert': 0x2D, 'ins': 0x2D,
    'home': 0x24,
    'end': 0x23,
    'pageup': 0x21, 'pgup': 0x21,
    'pagedown': 0x22, 'pgdn': 0x22,
    'left': 0x25,
    'up': 0x26,
    'right': 0x27,
    'down': 0x28,
}

# 设置 ctypes 函数签名
user32.RegisterHotKey.argtypes = [wintypes.HWND, wintypes.INT, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL

user32.UnregisterHotKey.argtypes = [wintypes.HWND, wintypes.INT]
user32.UnregisterHotKey.restype = wintypes.BOOL

kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = wintypes.DWORD


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


class _HotkeyNativeEventFilter(QAbstractNativeEventFilter):
    """拦截 Windows WM_HOTKEY 消息"""

    def __init__(self, hotkey_id: int, callback: Callable[[], None]):
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, eventType, message):
        try:
            et = bytes(eventType)
        except Exception:
            return False, 0

        if et in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                msg_ptr = ctypes.c_void_p(int(message))
                msg = ctypes.cast(msg_ptr, ctypes.POINTER(MSG)).contents
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    self._callback()
                    return True, 0
            except Exception:
                pass
        return False, 0


class WinGlobalHotkey(QObject):
    """
    基于 Windows RegisterHotKey 的全局热键管理器

    优点：
    - 不创建额外线程
    - 不使用低级键盘钩子（WH_KEYBOARD_LL）
    - 完全通过 Qt 原生事件过滤器处理，与 QSystemTrayIcon 100% 兼容
    """

    triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._app = QApplication.instance()
        self._hwnd = None
        self._hotkey_id = 1
        self._registered = False
        self._hotkey_str = "<ctrl>+<shift>+t"
        self._callback: Optional[Callable[[], None]] = None
        self._filter: Optional[_HotkeyNativeEventFilter] = None

        # 创建隐藏窗口以获取有效的 HWND
        self._hidden_window = QWidget()
        self._hidden_window.setWindowFlags(Qt.WindowType.Tool)
        self._hidden_window.resize(1, 1)
        self._hidden_window.hide()
        self._hwnd = int(self._hidden_window.winId())

    def register(self, callback: Callable[[], None], hotkey: str = None) -> bool:
        """
        注册热键回调

        Args:
            callback: 热键触发时执行的回调函数
            hotkey: 热键组合字符串，如 "<ctrl>+<shift>+t" 或 "alt+r"

        Returns:
            是否注册成功
        """
        self._callback = callback
        if hotkey:
            self._hotkey_str = hotkey

        return self.start()

    def start(self) -> bool:
        """启动热键监听"""
        if self._registered:
            self.stop()

        try:
            mod_flags, vk = self._parse_hotkey(self._hotkey_str)
            if vk is None:
                logger.warning(f"无法解析热键: {self._hotkey_str}")
                return False

            if not user32.RegisterHotKey(self._hwnd, self._hotkey_id, mod_flags, vk):
                err = kernel32.GetLastError()
                logger.error(f"RegisterHotKey 失败，错误码: {err}")
                return False

            self._registered = True

            # 安装原生事件过滤器
            self._filter = _HotkeyNativeEventFilter(self._hotkey_id, self._on_hotkey)
            self._app.installNativeEventFilter(self._filter)

            logger.info(f"全局热键注册成功: {self._hotkey_str}")
            return True

        except Exception as e:
            logger.error(f"启动热键失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _on_hotkey(self):
        """热键触发内部处理"""
        logger.info(f"热键触发: {self._hotkey_str}")
        if self._callback:
            try:
                self._callback()
            except Exception as e:
                logger.error(f"热键回调执行错误: {e}")
                import traceback
                traceback.print_exc()

    def stop(self):
        """停止热键监听"""
        if self._registered and self._hwnd:
            user32.UnregisterHotKey(self._hwnd, self._hotkey_id)
            self._registered = False

        if self._filter and self._app:
            self._app.removeNativeEventFilter(self._filter)
            self._filter = None

        logger.info("热键监听已停止")

    def is_running(self) -> bool:
        """检查热键是否正在监听"""
        return self._registered

    def change_hotkey(self, new_hotkey: str) -> bool:
        """动态修改热键组合"""
        was_running = self.is_running()
        if was_running:
            self.stop()
        self._hotkey_str = new_hotkey
        if was_running and self._callback:
            return self.start()
        return True

    def get_current_hotkey(self) -> str:
        """获取当前热键组合"""
        return self._hotkey_str

    @staticmethod
    def _parse_hotkey(hotkey_str: str):
        """解析热键字符串为 Windows 修饰键标志和虚拟键码"""
        parts = re.findall(r'<?([a-zA-Z0-9_-]+)>?', hotkey_str.lower())
        mods = [p for p in parts if p in MOD_MAP]
        main_keys = [p for p in parts if p not in MOD_MAP]
        main_key = main_keys[0] if main_keys else None

        if not main_key:
            return 0, None

        mod_flags = 0
        for m in mods:
            mod_flags |= MOD_MAP[m]

        vk = None
        if len(main_key) == 1 and main_key.isalnum():
            vk = ord(main_key.upper())
        else:
            vk = VK_MAP.get(main_key.lower())

        return mod_flags, vk


def create_hotkey_manager(app=None) -> WinGlobalHotkey:
    """工厂函数：创建全局热键管理器"""
    return WinGlobalHotkey()
