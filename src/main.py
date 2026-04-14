"""
TTS Voice Assistant - Main Application Entry
Day 9 版本：打包与安装体验（PyInstaller + 资源路径适配 + 首次启动引导）
"""

import sys
import os
import signal
import threading
import warnings

# 过滤 pygame 内部带来的 pkg_resources 弃用警告（不影响功能）
warnings.filterwarnings("ignore", message="pkg_resources is deprecated", category=UserWarning)

# 项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QAction, QFont, QColor, QPainter, QPixmap, QCursor

from src.ui.overlay_window import OverlayWindow
from src.core.tts_manager import TTSManager, TTSSource, get_tts_manager, shutdown_tts_manager
from src.core.hotkey_manager import create_hotkey_manager
from src.utils.config import Config
from src.utils.logger import setup_logger, get_logger
from src.utils.paths import get_resource_path

# 初始化日志（尽早初始化）
setup_logger()
logger = get_logger("main")

# 信号桥接器（用于从非 Qt 线程安全地更新 UI）
class SignalBridge(QObject):
    """用于从工作线程向主线程发送信号"""
    tts_finished = pyqtSignal(bool, str, int)  # success, source, duration_ms
    status_changed = pyqtSignal(str)  # status message
    show_overlay_requested = pyqtSignal()  # 热键请求显示悬浮窗（线程安全）


def create_default_icon():
    """创建默认托盘图标 (32x32 标准尺寸)"""
    icon_path = get_resource_path("resources/icon.png")
    
    if os.path.exists(icon_path):
        return str(icon_path)
        
    os.makedirs(os.path.dirname(icon_path), exist_ok=True)
    
    # 使用 32x32 标准托盘图标尺寸
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    # 蓝色圆形背景
    painter.setBrush(QColor(70, 130, 220))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, 30, 30)
    
    # 绘制麦克风图标（适配 32x32）
    painter.setBrush(QColor(255, 255, 255))
    # 麦克风头部
    painter.drawRoundedRect(11, 8, 10, 12, 5, 5)
    # 麦克风柄
    painter.drawRect(15, 19, 2, 5)
    # 底座
    painter.drawRoundedRect(10, 24, 12, 2, 1, 1)
    
    painter.end()
    pixmap.save(str(icon_path), "PNG")
    logger.info(f"托盘图标已生成: {icon_path} (32x32)")
    
    return str(icon_path)


class TTSApplication:
    """TTS 语音助手主应用 - Day 9 版本"""
    
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("TTS语音助手")
        self.app.setApplicationVersion("0.9.0")
        
        font = QFont("Microsoft YaHei", 9)
        self.app.setFont(font)
        
        # 组件
        self.overlay = None
        self.tray_icon = None
        self.tts_manager = None
        self.signal_bridge = SignalBridge()
        self.config = None
        self.hotkey_manager = None
        
        self._init()
        
    def _init(self):
        """初始化所有组件"""
        logger.info("初始化 TTS 语音助手 Day 9...")
        
        # 1. 创建信号桥接
        self.signal_bridge.tts_finished.connect(self._on_tts_finished)
        self.signal_bridge.status_changed.connect(self._on_status_changed)
        
        # 2. 加载配置
        self.config = Config()
        logger.info(f"配置加载完成: {self.config.config_path}")
        
        # 3. 初始化 TTS 管理器（传入配置以支持设备持久化）
        self.tts_manager = get_tts_manager(config=self.config)
        
        # 4. 创建悬浮窗口
        self.overlay = OverlayWindow()
        self.overlay.textSubmitted.connect(self._on_text_submitted)
        
        # 5. 创建图标
        create_default_icon()
        
        # 6. 设置托盘
        self._setup_tray()
        
        # 7. 检查虚拟声卡
        self._check_virtual_cable()
        
        # 8. 首次启动引导（Day 9）
        if self.config.is_first_run:
            self._show_first_run_guide()
        
        # 9. 初始化全局热键（通过信号桥接确保线程安全，避免影响托盘事件）
        self._setup_hotkey()
        
        logger.info("初始化完成")
        
    def _setup_tray(self):
        """设置系统托盘"""
        logger.info("正在设置系统托盘...")
        
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("系统托盘不可用")
            return
            
        # 设置托盘图标父对象为 QApplication，确保生命周期受 Qt 管理
        self.tray_icon = QSystemTrayIcon(self.app)
        
        # 加载图标 - 按需取用带尺寸后缀的图片
        icon_candidates = [
            "resources/icon_32x32.png",
            "resources/icon_64x64.png",
            "resources/icon_128x128.png",
            "resources/icon.png",
        ]
        icon_path = None
        for candidate in icon_candidates:
            p = get_resource_path(candidate)
            if os.path.exists(str(p)):
                icon_path = str(p)
                break
        
        if not icon_path:
            logger.info("图标不存在，创建默认图标...")
            icon_path = create_default_icon()
        
        logger.info(f"托盘图标加载: {icon_path}")
        icon = QIcon(str(icon_path))
        if icon.isNull():
            logger.warning(f"图标加载失败: {icon_path}")
        else:
            logger.info(f"图标加载成功: {icon_path}")
            
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("TTS语音助手 v0.9.0\n托盘菜单唤出悬浮窗")
        
        # 设置应用图标和显示名称（系统通知用）
        self.app.setWindowIcon(icon)
        self.app.setApplicationDisplayName("TTS语音助手")
        
        # 创建菜单 - 不指定 QWidget 父对象（QApplication 不能作为 QMenu 父对象）
        # 通过保存为实例变量 self.tray_menu 防止被垃圾回收
        self.tray_menu = QMenu()
        self.tray_menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d30;
                color: #ffffff;
                border: 1px solid #3f3f46;
                padding: 5px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #094771;
            }
            QMenu::separator {
                height: 1px;
                background-color: #3f3f46;
                margin: 5px 0px;
            }
        """)
        
        # 显示悬浮窗
        show_action = QAction("🎯 显示悬浮窗", self.tray_menu)
        show_action.triggered.connect(lambda: self._show_overlay())
        self.tray_menu.addAction(show_action)
        
        self.tray_menu.addSeparator()
        
        # 音频设备子菜单 (Day 6)
        self._setup_audio_device_menu()
        
        # 音量控制子菜单 (Day 7)
        self._setup_volume_menu()
        
        self.tray_menu.addSeparator()
        
        # 停止播放 (Day 7)
        stop_action = QAction("⏹ 停止播放", self.tray_menu)
        stop_action.triggered.connect(lambda: self._stop_playback())
        self.tray_menu.addAction(stop_action)
        
        self.tray_menu.addSeparator()
        
        # 缓存统计
        cache_action = QAction("📊 缓存统计", self.tray_menu)
        cache_action.triggered.connect(lambda: self._show_cache_stats())
        self.tray_menu.addAction(cache_action)
        
        # 清空缓存
        clear_cache_action = QAction("🗑️ 清空缓存", self.tray_menu)
        clear_cache_action.triggered.connect(lambda: self._clear_cache())
        self.tray_menu.addAction(clear_cache_action)
        
        self.tray_menu.addSeparator()
        
        # 退出
        quit_action = QAction("❌ 退出", self.tray_menu)
        quit_action.triggered.connect(lambda: self.quit())
        self.tray_menu.addAction(quit_action)
        
        # 托盘图标激活事件
        self.tray_icon.activated.connect(self._on_tray_activated)
        
        # 显示托盘图标
        self.tray_icon.show()
        
        # 检查托盘是否真的显示
        if self.tray_icon.isVisible():
            logger.info("托盘图标已显示")
        else:
            logger.warning("托盘图标可能未显示，尝试延迟显示...")
            # 延迟显示托盘（某些系统需要）
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self.tray_icon.show)
        
        # 启动提示
        logger.info("发送启动通知")
        self.tray_icon.showMessage(
            "TTS 语音助手",
            "已启动\n左键/双击托盘图标唤出悬浮窗口\n支持三级降级: 缓存→edge-tts→系统TTS",
            QSystemTrayIcon.MessageIcon.Information,
            4000
        )
        
    def _get_current_audio_label(self) -> str:
        """获取当前音频设备显示名称"""
        current_id = self.config.get("audio_device_id", None)
        if current_id is None:
            return "自动检测"
        current_name = self.config.get("audio_device_name", None)
        return current_name or f"设备 {current_id}"
    
    def _setup_audio_device_menu(self):
        """设置音频设备选择子菜单 (Day 6)"""
        from PyQt6.QtGui import QActionGroup
        
        label = self._get_current_audio_label()
        self._audio_menu = QMenu(f"🔊 音频设备 ({label})", self.tray_menu)
        self._audio_menu.setStyleSheet(self.tray_menu.styleSheet())
        
        self._audio_device_group = QActionGroup(self._audio_menu)
        self._audio_device_group.setExclusive(True)
        
        self._audio_device_actions: dict = {}
        self._audio_device_action_texts: dict = {}
        
        # 自动检测选项
        auto_text = "🔄 自动检测"
        auto_action = QAction(auto_text, self._audio_menu)
        auto_action.setCheckable(True)
        auto_action.setActionGroup(self._audio_device_group)
        auto_action.triggered.connect(lambda: self._set_audio_device(None, None))
        self._audio_menu.addAction(auto_action)
        self._audio_device_actions[None] = auto_action
        self._audio_device_action_texts[None] = auto_text
        self._audio_menu.addSeparator()
        
        # 列出所有可用输出设备（已去重）
        devices = self.tts_manager.get_output_devices()
        if devices:
            for dev_id, dev_name in devices:
                raw_text = f"[{dev_id}] {dev_name}"
                action = QAction(raw_text, self._audio_menu)
                action.setCheckable(True)
                action.setActionGroup(self._audio_device_group)
                action.triggered.connect(
                    lambda checked, did=dev_id, dname=dev_name: self._set_audio_device(did, dname)
                )
                self._audio_menu.addAction(action)
                self._audio_device_actions[dev_id] = action
                self._audio_device_action_texts[dev_id] = raw_text
        else:
            no_dev_action = QAction("未检测到输出设备", self._audio_menu)
            no_dev_action.setEnabled(False)
            self._audio_menu.addAction(no_dev_action)
        
        # 初始化选中状态（带 ✅ 高亮）
        current_device_id = self.config.get("audio_device_id", None)
        self._update_audio_menu_selection(current_device_id)
        
        self.tray_menu.addMenu(self._audio_menu)
    
    def _update_audio_menu_selection(self, selected_id):
        """更新音频设备菜单的选中高亮显示"""
        for dev_id, action in self._audio_device_actions.items():
            is_selected = dev_id == selected_id
            action.setChecked(is_selected)
            raw = self._audio_device_action_texts[dev_id]
            if is_selected:
                action.setText(f"{raw}  ← 当前")
            else:
                action.setText(raw)
    
    def _set_audio_device(self, device_id, device_name):
        """设置音频输出设备 (Day 6)"""
        self.tts_manager.set_virtual_device(device_id, device_name)
        
        # 动态更新菜单标题和选中高亮
        if hasattr(self, "_audio_menu") and self._audio_menu:
            label = self._get_current_audio_label()
            self._audio_menu.setTitle(f"🔊 音频设备 ({label})")
            self._update_audio_menu_selection(device_id)
        
        if device_id is None:
            msg = "已切换到自动检测模式"
        else:
            msg = f"已切换到: {device_name}"
        logger.info(msg)
    
    def _setup_volume_menu(self):
        """设置音量控制子菜单 (Day 7)"""
        from PyQt6.QtGui import QActionGroup
        
        current_vol = int(self.tts_manager.get_volume() * 100)
        self._volume_menu = QMenu(f"🎚️ 音量 ({current_vol}%)", self.tray_menu)
        self._volume_menu.setStyleSheet(self.tray_menu.styleSheet())
        
        volume_group = QActionGroup(self._volume_menu)
        volume_group.setExclusive(True)
        
        self._volume_actions = {}
        
        for pct in [25, 50, 75, 100]:
            action = QAction(f"{pct}%", self._volume_menu)
            action.setCheckable(True)
            action.setActionGroup(volume_group)
            action.setChecked(current_vol == pct)
            action.triggered.connect(lambda checked, p=pct: self._set_volume(p))
            self._volume_menu.addAction(action)
            self._volume_actions[pct] = action
        
        self.tray_menu.addMenu(self._volume_menu)
        
        # TTS 语音选择子菜单
        self._setup_voice_menu()
    
    def _set_volume(self, pct):
        """设置音量 (Day 7)"""
        vol = pct / 100.0
        self.tts_manager.set_volume(vol)
        if hasattr(self, "_volume_menu") and self._volume_menu:
            self._volume_menu.setTitle(f"🎚️ 音量 ({pct}%)")
        logger.info(f"音量已设置为 {pct}%")
    
    def _setup_voice_menu(self):
        """设置 Edge TTS 语音选择子菜单"""
        from PyQt6.QtGui import QActionGroup
        
        current_voice = self.tts_manager._edge_voice
        self._voice_menu = QMenu(f"🗣️ 语音 ({current_voice})", self.tray_menu)
        self._voice_menu.setStyleSheet(self.tray_menu.styleSheet())
        
        voice_group = QActionGroup(self._voice_menu)
        voice_group.setExclusive(True)
        
        self._voice_actions = {}
        
        for voice in self.tts_manager.AVAILABLE_EDGE_VOICES:
            action = QAction(voice, self._voice_menu)
            action.setCheckable(True)
            action.setActionGroup(voice_group)
            action.setChecked(current_voice == voice)
            action.triggered.connect(lambda checked, v=voice: self._set_edge_voice(v))
            self._voice_menu.addAction(action)
            self._voice_actions[voice] = action
        
        self.tray_menu.addMenu(self._voice_menu)
    
    def _set_edge_voice(self, voice: str):
        """设置 Edge TTS 语音"""
        self.tts_manager.set_edge_voice(voice)
        if hasattr(self, "_voice_menu") and self._voice_menu:
            self._voice_menu.setTitle(f"🗣️ 语音 ({voice})")
        for v, action in self._voice_actions.items():
            action.setChecked(v == voice)
        logger.info(f"已切换到语音: {voice}")
    
    def _stop_playback(self):
        """停止播放并清空队列 (Day 7)"""
        self.tts_manager.stop_playback(clear_queue=True)
        if self.tray_icon:
            self.tray_icon.showMessage(
                "TTS 语音助手",
                "已停止播放并清空队列",
                QSystemTrayIcon.MessageIcon.Information,
                1500
            )
        logger.info("已停止播放并清空队列")
    
    def _check_virtual_cable(self):
        """检查虚拟声卡状态"""
        installed, msg = self.tts_manager.check_virtual_cable()
        
        if installed:
            logger.info(msg)
        else:
            logger.warning(msg)
            if self.tray_icon:
                self.tray_icon.showMessage(
                    "TTS 语音助手",
                    f"⚠️ {msg}\n\n请在语音软件中手动设置音频输出设备",
                    QSystemTrayIcon.MessageIcon.Warning,
                    5000
                )
    
    def _setup_hotkey(self):
        """初始化全局热键（Day 10 修复：通过信号桥接在主线程处理 GUI 操作）"""
        try:
            self.hotkey_manager = create_hotkey_manager()
            
            # 从配置读取热键，默认 Ctrl+Shift+T
            hotkey_str = self.config.get("hotkey", "<ctrl>+<shift>+t")
            
            # 热键回调只发射信号，绝不直接操作 Qt GUI（避免托盘点击失效）
            def on_hotkey():
                logger.info(f"热键触发: {hotkey_str}")
                self.signal_bridge.show_overlay_requested.emit()
            
            success = self.hotkey_manager.register(on_hotkey, hotkey_str)
            if success:
                logger.info(f"全局热键注册成功: {hotkey_str}")
            else:
                logger.warning("全局热键注册失败")
                
            # 连接信号到主线程的显示方法（热键与托盘均使用记忆位置）
            self.signal_bridge.show_overlay_requested.connect(self._show_overlay)
            
        except Exception as e:
            logger.error(f"热键初始化失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _show_first_run_guide(self):
        """首次启动引导（Day 9）"""
        logger.info("首次运行，显示引导提示")
        if self.tray_icon:
            self.tray_icon.showMessage(
                "TTS 语音助手",
                "欢迎使用！\n"
                "首次启动配置已初始化\n"
                "• 按 Ctrl+Shift+T 唤出悬浮窗\n"
                "• 在托盘菜单可切换音频设备\n"
                "• 确保语音软件使用 VB-CABLE 麦克风",
                QSystemTrayIcon.MessageIcon.Information,
                8000
            )
    
    def _show_overlay(self):
        """显示悬浮窗口（托盘/热键均使用记忆位置）"""
        if self.overlay:
            logger.info("显示悬浮窗口（记忆位置）")
            self.overlay.show_at_saved_position()
            
    def _hide_overlay(self):
        """隐藏悬浮窗口"""
        if self.overlay:
            self.overlay.hide_window()
            
    def _toggle_overlay(self):
        """切换显示/隐藏（托盘单击使用记忆位置）"""
        if self.overlay and self.overlay.isVisible():
            self._hide_overlay()
        else:
            self._show_overlay()
            
    def _on_tray_activated(self, reason):
        """托盘图标激活事件"""
        reason_name = {
            0: "Unknown",
            1: "Context",      # 右键 - 手动弹出菜单
            2: "DoubleClick",  # 双击
            3: "Trigger",      # 左键单击
            4: "MiddleClick",  # 中键
        }.get(int(reason.value), f"Unknown({reason})")
        
        logger.debug(f"托盘激活事件: {reason_name}")
        
        # 左键单击切换显隐，双击显示悬浮窗
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            logger.debug("单击 - 切换悬浮窗口")
            self._toggle_overlay()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            logger.debug("双击 - 显示悬浮窗口")
            self._show_overlay()
        
        # 右键 - 在鼠标右上方手动弹出菜单
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            from PyQt6.QtCore import QPoint
            cursor_pos = QCursor.pos()
            menu_height = self.tray_menu.sizeHint().height()
            # 放在鼠标右上角，距离底部稍微远一些
            popup_pos = QPoint(cursor_pos.x() + 10, cursor_pos.y() - menu_height - 20)
            
            # 边界检查
            screen = QApplication.primaryScreen().availableGeometry()
            popup_pos.setX(max(screen.left(), min(popup_pos.x(), screen.right() - self.tray_menu.sizeHint().width())))
            popup_pos.setY(max(screen.top() + 10, popup_pos.y()))
            
            self.tray_menu.popup(popup_pos)
        
        # 中键直接退出（方便测试）
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            logger.info("中键 - 退出应用")
            self.quit()
    
    def _on_text_submitted(self, text: str):
        """文本提交 - 开始 TTS (Day 7: 打断重播)"""
        # 更新 UI 状态
        self.overlay.set_tts_status("generating")
        
        # 异步执行 TTS：打断当前并播放新文本
        def on_complete(result):
            # 通过信号桥接安全地回到主线程
            self.signal_bridge.tts_finished.emit(
                result.success, 
                result.source.value, 
                result.duration_ms
            )
        
        self.tts_manager.interrupt_and_speak(text, on_complete=on_complete)
    
    def _on_tts_finished(self, success: bool, source: str, duration_ms: int):
        """TTS 完成回调（在主线程执行）"""
        # 状态图标
        source_icons = {
            "cache": "⚡",
            "edge-tts": "🔵", 
            "sapi5": "🔴"
        }
        icon = source_icons.get(source, "❓")
        
        # 更新 UI
        if success:
            self.overlay.set_tts_status("success", f"{icon} {source} ({duration_ms}ms)", source=source)
        else:
            self.overlay.set_tts_status("error", "播放失败")
        
        logger.info(f"TTS 完成: success={success}, source={source}, duration={duration_ms}ms")
    
    def _on_status_changed(self, status: str):
        """状态变更回调"""
        if self.overlay:
            self.overlay.set_status_text(status)
    
    def _show_cache_stats(self):
        """显示缓存统计"""
        stats = self.tts_manager.get_cache_stats()
        
        msg = f"缓存统计:\n"
        msg += f"  文件数: {stats.get('count', 0)}\n"
        msg += f"  总大小: {stats.get('total_size_mb', 0)} MB\n"
        msg += f"  上限: {stats.get('max_items', 50)} 条\n"
        msg += f"  目录: {stats.get('cache_dir', 'N/A')}"
        
        logger.info(msg)
        
        if self.tray_icon:
            self.tray_icon.showMessage(
                "TTS 语音助手",
                msg,
                QSystemTrayIcon.MessageIcon.Information,
                3000
            )
    
    def _clear_cache(self):
        """清空缓存"""
        self.tts_manager.clear_cache()
        
        if self.tray_icon:
            self.tray_icon.showMessage(
                "TTS 语音助手",
                "缓存已清空",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
    
    def run(self):
        """运行应用"""
        logger.info("=" * 60)
        logger.info("TTS Voice Assistant - Day 10")
        logger.info("=" * 60)
        current_hotkey = self.hotkey_manager.get_current_hotkey() if self.hotkey_manager else "N/A"
        logger.info(f"热键: {current_hotkey} - 唤出悬浮窗（RegisterHotKey 原生实现）")
        logger.info("托盘: 左键单击/双击 - 显示悬浮窗")
        logger.info("托盘: 右键 - 打开菜单（含音频设备/音量选择）")
        logger.info("TTS: 输入文字 → 生成语音 → 播放声音")
        logger.info("缓存: LRU 自动管理 | 常用语预缓存 | 命中<200ms")
        logger.info("降级: 缓存 → edge-tts(5秒超时) → 系统 TTS")
        logger.info("音频: 支持虚拟声卡自动检测 / 手动选择 / 设备持久化")
        logger.info("Day7: 播放队列 | 音量控制 | 停止播放 | 打断重播")
        logger.info("Day8: 日志系统 | 边界处理 | 全流程测试 | 稳定运行")
        logger.info("Day9: PyInstaller 打包 | 资源路径适配 | 首次启动引导")
        logger.info("Day10: 全局热键集成 | 焦点安全获取")
        logger.info("状态: 🟢edge-tts | 🟡cache | 🔴sapi5")
        logger.info("=" * 60)
        
        # 信号处理
        signal.signal(signal.SIGINT, lambda s, f: self.quit())
        
        return self.app.exec()
        
    def quit(self):
        """退出应用"""
        logger.info("正在退出...")
        
        # 停止热键监听
        if self.hotkey_manager:
            try:
                self.hotkey_manager.stop()
                logger.info("热键监听已停止")
            except Exception as e:
                logger.warning(f"停止热键监听时出错: {e}")
        
        # 停止 TTS
        if self.tts_manager:
            self.tts_manager.stop_playback()
        
        # 关闭窗口
        if self.overlay:
            self.overlay.close()
        
        # 隐藏托盘
        if self.tray_icon:
            self.tray_icon.hide()
        
        # 释放资源
        shutdown_tts_manager()
        
        logger.info("已退出")
        self.app.quit()


def main():
    try:
        app = TTSApplication()
        sys.exit(app.run())
    except Exception as e:
        logger.error(f"程序异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
