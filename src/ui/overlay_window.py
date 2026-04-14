"""
TTS Voice Assistant - Overlay Window Module
悬浮输入窗口 - Day 2 版本（支持 TTS 状态显示）
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QLabel, QApplication
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QCursor

from src.utils.logger import get_logger

logger = get_logger("overlay")


class OverlayWindow(QWidget):
    """
    无边框悬浮输入窗口 - Day 2
    
    新特性：
    - 支持显示 TTS 状态（生成中/成功/失败）
    - 状态颜色指示器
    """
    
    textSubmitted = pyqtSignal(str)
    windowHidden = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos = None
        self._is_dragging = False
        self._saved_pos = None  # 托盘唤出的记忆位置
        
        self._setup_window()
        self._init_ui()
        
    def _setup_window(self):
        """配置窗口 - 恢复 WindowDoesNotAcceptFocus，避免抢夺游戏焦点"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus  # 关键：游戏中不夺焦
        )
        
        # 不使用 WA_TranslucentBackground，改用半透明背景色
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.setFixedSize(420, 110)
        
        # 设置半透明背景
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 30, 35, 230);
                border-radius: 12px;
            }
        """)
        
    def _init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        # 输入框
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入文字，按回车发送...")
        self.input_field.setFont(QFont("Microsoft YaHei", 12))
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: rgba(50, 50, 55, 200);
                color: #ffffff;
                border: 2px solid rgba(100, 150, 255, 180);
                border-radius: 8px;
                padding: 8px 12px;
            }
            QLineEdit:focus {
                border: 2px solid rgba(100, 180, 255, 240);
                background-color: rgba(55, 55, 60, 220);
            }
            QLineEdit:disabled {
                background-color: rgba(40, 40, 45, 200);
                border: 2px solid rgba(100, 100, 100, 180);
                color: #aaaaaa;
            }
        """)
        
        # 保存原始 keyPressEvent
        self._original_keypress = self.input_field.keyPressEvent
        self.input_field.keyPressEvent = self._handle_input_keypress
        self.input_field.returnPressed.connect(self._handle_submit)
        
        # 状态标签（Day 2：支持 TTS 状态显示）
        self.status_label = QLabel("就绪 - 按回车发送，ESC关闭")
        self.status_label.setFont(QFont("Microsoft YaHei", 9))
        self.status_label.setStyleSheet("""
            QLabel {
                color: rgba(180, 180, 190, 200);
            }
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(self.input_field)
        layout.addWidget(self.status_label)
        self.setLayout(layout)
        
    def _handle_input_keypress(self, event):
        """处理键盘事件"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide_window()
        else:
            self._original_keypress(event)
            
    def _handle_submit(self):
        """处理回车提交"""
        text = self.input_field.text().strip()
        if not text:
            self.set_status_text("请输入内容", "warning")
            QTimer.singleShot(1500, lambda: self.set_status_text("就绪 - 按回车发送，ESC关闭"))
            return
            
        logger.info(f"提交内容: {text[:50]}" + ("..." if len(text) > 50 else ""))
        
        # 禁用输入框，等待 TTS 完成
        self.input_field.setEnabled(False)
        self.textSubmitted.emit(text)
        
    def _prepare_show(self):
        """显示前的公共准备：重置状态并恢复焦点"""
        self.input_field.clear()
        self.input_field.setEnabled(True)
        self.set_status_text("就绪 - 按回车发送，ESC关闭")
        
        # 临时移除 WindowDoesNotAcceptFocus，允许输入框获得焦点
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
    
    def _do_show(self, x: int, y: int):
        """在指定坐标显示窗口"""
        self._prepare_show()
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input_field.setFocus()
        
    def show_at_cursor(self):
        """在鼠标位置显示窗口（热键唤出）"""
        cursor_pos = QCursor.pos()
        screen = self.screen() or QApplication.primaryScreen()
        screen_geo = screen.availableGeometry()
        
        # 计算位置（鼠标下方偏右）
        x = cursor_pos.x() - self.width() // 2
        y = cursor_pos.y() + 20
        
        # 边界检查
        margin = 10
        x = max(screen_geo.left() + margin, min(x, screen_geo.right() - self.width() - margin))
        y = max(screen_geo.top() + margin, min(y, screen_geo.bottom() - self.height() - margin))
        x = max(0, x)
        y = max(0, y)
        
        self._do_show(x, y)
        
    def show_at_saved_position(self):
        """在记忆位置显示窗口（托盘唤出），首次为右下角偏上"""
        screen = self.screen() or QApplication.primaryScreen()
        screen_geo = screen.availableGeometry()
        
        if self._saved_pos is None:
            margin = 20
            x = screen_geo.right() - self.width() - margin
            y = screen_geo.bottom() - self.height() - margin - 60  # 偏上 60px
            self._saved_pos = QPoint(x, y)
        
        # 边界保护（防止分辨率变化后窗口跑到屏幕外）
        margin = 10
        x = max(screen_geo.left() + margin, min(self._saved_pos.x(), screen_geo.right() - self.width() - margin))
        y = max(screen_geo.top() + margin, min(self._saved_pos.y(), screen_geo.bottom() - self.height() - margin))
        
        self._do_show(x, y)
        
    def blur_window(self):
        """失焦窗口 - 输入结束后保持窗口可见但失去焦点"""
        self.input_field.clear()
        self.input_field.setEnabled(True)
        self.input_field.clearFocus()
        self.clearFocus()
        self.set_status_text("就绪 - 按回车发送，ESC关闭")
        
    def hide_window(self):
        """隐藏窗口"""
        self.input_field.clear()
        self.input_field.setEnabled(True)
        self.set_status_text("就绪 - 按回车发送，ESC关闭")
        self.hide()
        
        # 恢复 WindowDoesNotAcceptFocus，避免隐藏期间或下次显示时意外抢夺焦点
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        
        self.windowHidden.emit()
        
    def set_status_text(self, text: str, style: str = "normal"):
        """
        设置状态文本
        
        Args:
            text: 状态文本
            style: 样式类型 - normal/warning/success/error
        """
        self.status_label.setText(text)
        
        # 根据样式调整颜色
        colors = {
            "normal": "rgba(180, 180, 190, 200)",
            "warning": "rgba(255, 200, 100, 220)",
            "success": "rgba(100, 255, 150, 220)",
            "error": "rgba(255, 100, 100, 220)",
            "generating": "rgba(100, 180, 255, 220)"
        }
        
        color = colors.get(style, colors["normal"])
        self.status_label.setStyleSheet(f"QLabel {{ color: {color}; }}")
        
    def set_tts_status(self, status: str, detail: str = None, source: str = None):
        """
        设置 TTS 状态（Day 5 新增：按引擎显示不同颜色）
        
        Args:
            status: 状态类型 - generating/success/error
            detail: 详细信息（如播放源和耗时）
            source: 音频来源 - cache/edge-tts/sapi5，用于状态栏颜色指示
        """
        status_map = {
            "generating": ("🔄 正在生成语音...", "generating"),
            "success": (f"✅ 播放完成 {detail or ''}", "success"),
            "error": (f"❌ {detail or '播放失败'}", "error"),
            "playing": ("🔊 正在播放...", "generating")
        }
        
        text, style = status_map.get(status, (status, "normal"))
        
        # Day 5: 不同引擎显示不同颜色
        # 🟢 edge-tts = 绿色(success), 🟡 cache = 黄色(warning), 🔴 sapi5 = 红色(error)
        if status == "success" and source:
            source_styles = {
                "cache": "warning",      # 黄色/金色
                "edge-tts": "success",   # 绿色
                "sapi5": "error"         # 红色
            }
            style = source_styles.get(source, style)
        
        self.set_status_text(text, style)
        
        # 成功后延迟失焦（保持窗口可见）
        if status == "success":
            QTimer.singleShot(2000, lambda: self.blur_window())
        elif status == "error":
            # 错误时恢复输入框
            self.input_field.setEnabled(True)
            self.input_field.setFocus()
            QTimer.singleShot(3000, lambda: self.set_status_text("就绪 - 按回车发送，ESC关闭", "normal"))
        
    def set_generating_status(self):
        """设置为生成中状态"""
        self.set_tts_status("generating")
        self.input_field.setEnabled(False)
        
    def reset_status(self):
        """重置为默认状态"""
        self.input_field.setEnabled(True)
        self.input_field.clear()
        self.set_status_text("就绪 - 按回车发送，ESC关闭")
        
    # 鼠标拖动支持
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._is_dragging = True
            event.accept()
            
    def mouseMoveEvent(self, event):
        if self._is_dragging and self._drag_pos is not None:
            if event.buttons() == Qt.MouseButton.LeftButton:
                new_pos = event.globalPosition().toPoint() - self._drag_pos
                self.move(new_pos)
                event.accept()
                
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_pos = None
            # 保存拖动后的位置，供托盘后续唤出使用
            self._saved_pos = self.pos()
            event.accept()



