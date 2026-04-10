import sys
import os
import time
import json
import traceback
import ctypes
import threading
import queue
from ctypes import wintypes

# ---------------------------------------------------------
# 核心库导入与高分屏适配
# ---------------------------------------------------------
try:
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    ctypes.windll.shcore.SetProcessDpiAwareness(1) 
except:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except: pass

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QPushButton, QLabel, QComboBox, QLineEdit, QScrollArea, 
                               QFileDialog, QTextEdit, QMessageBox, QFrame, QCheckBox, QGroupBox, QToolTip,
                               QListWidget, QListWidgetItem, QAbstractItemView, QInputDialog, QSplitter)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QRect, QSettings, QPoint
from PySide6.QtGui import QCursor, QFont, QColor, QPalette, QBrush, QPen, QPainter, QRegion
import pyperclip
from PIL import Image
import pyautogui

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
try:
    GetCurrentProcessorNumber = ctypes.windll.kernel32.GetCurrentProcessorNumber
    GetCurrentProcessorNumber.restype = ctypes.c_ulong
    HAS_KERNEL_CPU = True
except:
    HAS_KERNEL_CPU = False

pyautogui.FAILSAFE = False 
pyautogui.PAUSE = 0

# ---------------------------------------------------------
# 底层 Hook 结构体、按键映射与 64位指针强制安全声明
# ---------------------------------------------------------
VK_MAP = {
    0x08: 'backspace', 0x09: 'tab', 0x0D: 'enter', 0x10: 'shift', 0x11: 'ctrl', 0x12: 'alt',
    0x14: 'capslock', 0x1B: 'esc', 0x20: 'space', 0x21: 'pageup', 0x22: 'pagedown',
    0x23: 'end', 0x24: 'home', 0x25: 'left', 0x26: 'up', 0x27: 'right', 0x28: 'down',
    0x2C: 'printscreen', 0x2D: 'insert', 0x2E: 'delete',
}
for i in range(65, 91): VK_MAP[i] = chr(i).lower() # A-Z
for i in range(48, 58): VK_MAP[i] = chr(i) # 0-9
for i in range(112, 124): VK_MAP[i] = f'f{i-111}' # F1-F12
for i in range(0x60, 0x6A): VK_MAP[i] = str(i - 0x60) # 小键盘数字 0-9 映射
VK_MAP.update({0x6A: '*', 0x6B: '+', 0x6D: '-', 0x6E: '.', 0x6F: '/'}) # 小键盘运算符

# --- 修复：追加所有常用标点符号的底层映射 ---
VK_MAP.update({
    0xBA: ';', 0xBB: '=', 0xBC: ',', 0xBD: '-', 0xBE: '.', 0xBF: '/', 0xC0: '`',
    0xDB: '[', 0xDC: '\\', 0xDD: ']', 0xDE: '\''
})

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

# --- 核心修复区：强制声明底层函数的参数与返回值，防止64位指针被截断崩溃 ---
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p

user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p]
user32.CallNextHookEx.restype = LRESULT

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p

user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
# ---------------------------------------------------------

# ---------------------------------------------------------
# 全局配置与异步日志系统
# ---------------------------------------------------------
GLOBAL_CONFIG = {
    "log_to_file": False,
    "log_to_ui": True
}

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_log_path():
    return os.path.join(get_base_dir(), "rpa_debug_log.txt")

LOG_QUEUE = queue.Queue()

def log_worker_thread():
    while True:
        try:
            item = LOG_QUEUE.get()
            if item is None: break
            msg, callback = item
            
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            formatted_msg = f"[{timestamp}] {msg}"
            
            if GLOBAL_CONFIG["log_to_file"]:
                try:
                    with open(get_log_path(), "a", encoding="utf-8") as f:
                        f.write(formatted_msg + "\n")
                except: pass
            
            if callback and GLOBAL_CONFIG["log_to_ui"]:
                callback(msg)
        except Exception:
            pass

log_thread = threading.Thread(target=log_worker_thread, daemon=True)
log_thread.start()

def write_log(msg, callback=None):
    LOG_QUEUE.put((msg, callback))

def global_exception_handler(exctype, value, tb):
    err_msg = "".join(traceback.format_exception(exctype, value, tb))
    msg = f"!!! 严重崩溃 !!! {value}\n{err_msg}"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    try:
        with open(get_log_path(), "a", encoding="utf-8") as f:
            f.write(formatted_msg + "\n")
    except: pass
    sys.__excepthook__(exctype, value, tb)

sys.excepthook = global_exception_handler

# --------------------------
# UI组件: 折叠面板与帮助按钮
# --------------------------
class CollapsibleSection(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 5)
        self.main_layout.setSpacing(0)
        
        self.toggle_btn = QPushButton(f"▼ {self.title}")
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                text-align: left; font-weight: bold; padding: 6px 10px; 
                background-color: #e0e0e0; border: 1px solid #c0c0c0; border-radius: 4px;
            }
            QPushButton:hover { background-color: #d0d0d0; }
            QPushButton:checked { border-bottom-left-radius: 0px; border-bottom-right-radius: 0px; }
        """)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.clicked.connect(self.on_toggle)
        
        self.content_widget = QFrame()
        self.content_widget.setObjectName("contentFrame")
        self.content_widget.setStyleSheet("""
            QFrame#contentFrame {
                border: 1px solid #c0c0c0; border-top: none;
                border-bottom-left-radius: 4px; border-bottom-right-radius: 4px;
                background-color: #fafafa;
            }
        """)
        self.main_layout.addWidget(self.toggle_btn)
        self.main_layout.addWidget(self.content_widget)
        
    def set_content_layout(self, layout):
        layout.setContentsMargins(10, 10, 10, 10)
        self.content_widget.setLayout(layout)
        
    def on_toggle(self, checked):
        self.content_widget.setVisible(checked)
        self.toggle_btn.setText(f"▼ {self.title}" if checked else f"▶ {self.title}")

class HelpBtn(QPushButton):
    def __init__(self, tip_text):
        super().__init__("?")
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; border-radius: 10px; font-weight: bold; border: none; }
            QPushButton:hover { background-color: #1976D2; }
        """)
        self.tip_text = tip_text
        self.clicked.connect(self.show_tip)

    def show_tip(self):
        QToolTip.showText(QCursor.pos(), self.tip_text, self, QRect(), 5000)

# --------------------------
# 区域选择窗口
# --------------------------
class RegionWindow(QWidget):
    region_selected = Signal(tuple)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        
        virtual_rect = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(virtual_rect)
        
        phys_w, phys_h = pyautogui.size()
        log_w = virtual_rect.width()
        log_h = virtual_rect.height()
        self.scale_x = phys_w / log_w
        self.scale_y = phys_h / log_h
        
        self.start_point = None
        self.end_point = None
        self.current_pos = QPoint(0, 0)
        self.selection_rect = QRect()
        self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg_color = QColor(0, 0, 0, 100) 
        
        if self.selection_rect.isValid():
            mask_region = QRegion(self.rect())
            selection_region = QRegion(self.selection_rect)
            overlay_region = mask_region.subtracted(selection_region)
            
            painter.setClipRegion(overlay_region)
            painter.fillRect(self.rect(), bg_color)
            painter.setClipping(False)
            
            pen = QPen(QColor(0, 255, 0), 2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.selection_rect)
            
            real_w = int(self.selection_rect.width() * self.scale_x)
            real_h = int(self.selection_rect.height() * self.scale_y)
            info_text = f"选区:{self.selection_rect.width()}x{self.selection_rect.height()} (实际: {real_w}x{real_h})"
            
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 12, QFont.Bold)) 
            text_y = self.selection_rect.y() - 10
            if text_y < 30: text_y = self.selection_rect.y() + 30
            painter.drawText(self.selection_rect.x(), text_y, info_text)
            
        else:
            painter.fillRect(self.rect(), bg_color)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 16, QFont.Bold))
            hint = f"请框选区域 | 右键取消 | 缩放比: {self.scale_x:.2f}"
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(hint)
            painter.drawText((self.width() - tw)//2, 100, hint)

        painter.setClipping(False)
        coord_text = f"Pos: {self.current_pos.x()},{self.current_pos.y()}"
        painter.setPen(QColor(255, 255, 0))
        painter.setFont(QFont("Arial", 10))
        painter.drawText(self.current_pos.x() + 20, self.current_pos.y() + 30, coord_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = event.pos()
            self.selection_rect = QRect()
            self.update()
        elif event.button() == Qt.RightButton:
            self.close()

    def mouseMoveEvent(self, event):
        self.current_pos = event.pos()
        if self.start_point:
            self.end_point = event.pos()
            self.selection_rect = QRect(self.start_point, self.end_point).normalized()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.start_point:
            rect = self.selection_rect
            self.close() 
            if rect.width() > 10 and rect.height() > 10:
                real_x = int(rect.x() * self.scale_x)
                real_y = int(rect.y() * self.scale_y)
                real_w = int(rect.width() * self.scale_x)
                real_h = int(rect.height() * self.scale_y)
                self.region_selected.emit((real_x, real_y, real_w, real_h))

# --------------------------
# 全能钩子录制线程 (修复版)
# --------------------------
class HookThread(QThread):
    finished_signal = Signal(list)
    
    def run(self):
        self.events = []
        self.l_down_pos = None
        self.r_down_pos = None
        self.l_down_time = 0
        self.r_down_time = 0
        
        self.thread_id = kernel32.GetCurrentThreadId()
        self.is_active = True
        
        self.mouse_pointer = HOOKPROC(self.mouse_handler)
        self.mouse_hook = user32.SetWindowsHookExW(14, self.mouse_pointer, kernel32.GetModuleHandleW(None), 0)
        
        self.kb_pointer = HOOKPROC(self.keyboard_handler)
        self.keyboard_hook = user32.SetWindowsHookExW(13, self.kb_pointer, kernel32.GetModuleHandleW(None), 0)
        
        msg = wintypes.MSG()
        while self.is_active and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
            
        if getattr(self, 'mouse_hook', None): user32.UnhookWindowsHookEx(self.mouse_hook)
        if getattr(self, 'keyboard_hook', None): user32.UnhookWindowsHookEx(self.keyboard_hook)
        self.finished_signal.emit(self.events)

    def stop(self):
        self.is_active = False
        user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)

    def mouse_handler(self, nCode, wParam, lParam):
        if nCode >= 0:
            struct = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = struct.pt.x, struct.pt.y
            
            if wParam == 0x0201: # WM_LBUTTONDOWN
                self.l_down_pos = (x, y)
                self.l_down_time = time.time()
            elif wParam == 0x0202: # WM_LBUTTONUP
                if getattr(self, 'l_down_pos', None):
                    dx = abs(x - self.l_down_pos[0])
                    dy = abs(y - self.l_down_pos[1])
                    if dx > 10 or dy > 10:
                        self.events.append((self.l_down_time, 'left_drag', (*self.l_down_pos, x, y)))
                    else:
                        self.events.append((self.l_down_time, 'left', (x, y)))
                    self.l_down_pos = None
            elif wParam == 0x0204: # WM_RBUTTONDOWN
                self.r_down_pos = (x, y)
                self.r_down_time = time.time()
            elif wParam == 0x0205: # WM_RBUTTONUP
                if getattr(self, 'r_down_pos', None):
                    dx = abs(x - self.r_down_pos[0])
                    dy = abs(y - self.r_down_pos[1])
                    if dx > 10 or dy > 10:
                        self.events.append((self.r_down_time, 'right_drag', (*self.r_down_pos, x, y)))
                    else:
                        self.events.append((self.r_down_time, 'right', (x, y)))
                    self.r_down_pos = None
            elif wParam == 0x020A: # WM_MOUSEWHEEL
                delta = ctypes.c_short(struct.mouseData >> 16).value
                self.events.append((time.time(), 'scroll', delta))
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def keyboard_handler(self, nCode, wParam, lParam):
        if nCode >= 0:
            struct = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if wParam == 0x0100 or wParam == 0x0104: 
                vk = struct.vkCode
                if vk != 0x77 and vk != 0x1B: # 强制屏蔽 F8 和 ESC
                    if vk in VK_MAP:
                        self.events.append((time.time(), 'key', VK_MAP[vk]))
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

# --------------------------
# 悬浮录制控制器UI
# --------------------------
class RecorderUI(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(320, 80)
        
        rect = QApplication.primaryScreen().geometry()
        self.move((rect.width() - 320) // 2, 40)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.bg = QFrame()
        self.bg.setStyleSheet("background-color: rgba(20, 20, 25, 230); border-radius: 10px; border: 2px solid #03A9F4;")
        self.layout.addWidget(self.bg)
        
        inner = QVBoxLayout(self.bg)
        self.label = QLabel("✨ 准备就绪\n[F8] 开始录制 | [ESC] 取消")
        self.label.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        self.label.setAlignment(Qt.AlignCenter)
        inner.addWidget(self.label)
        
        self.state = 0 
        self.hook_thread = None
        
        self.f8_pressed = False
        self.esc_pressed = False
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_keys)
        self.timer.start(30)
        self.show()

    def check_keys(self):
        curr_f8 = GetAsyncKeyState(0x77) & 0x8000
        curr_esc = GetAsyncKeyState(0x1B) & 0x8000
        
        if curr_esc and not self.esc_pressed:
            self.esc_pressed = True
            self.abort()
            return
        elif not curr_esc:
            self.esc_pressed = False
            
        if curr_f8 and not self.f8_pressed:
            self.f8_pressed = True
            if self.state == 0:
                self.start_recording()
            elif self.state == 1:
                self.stop_recording()
        elif not curr_f8:
            self.f8_pressed = False

    def start_recording(self):
        self.state = 1
        self.label.setText("🔴 正在全息录制 (键鼠监控中)...\n[F8] 停止并生成 | [ESC] 放弃录制")
        self.bg.setStyleSheet("background-color: rgba(40, 10, 10, 230); border-radius: 10px; border: 2px solid #FF1744;")
        self.hook_thread = HookThread()
        self.hook_thread.finished_signal.connect(self.on_recorded)
        self.hook_thread.start()

    def stop_recording(self):
        self.state = 2
        self.label.setText("⏳ 正在生成指令轴...")
        if self.hook_thread:
            self.hook_thread.stop()
            
    def abort(self):
        if self.hook_thread:
            self.hook_thread.stop()
            self.hook_thread.wait()
        self.main_window.showNormal()
        self.close()

    def on_recorded(self, events):
        tasks = []
        last_time = None
        for t, e_type, val in events:
            if last_time is not None:
                delay = t - last_time
                if delay > 0.15: 
                    tasks.append({"type": 5.0, "value": f"{delay:.2f}"})
            last_time = t
            
            if e_type == 'left':
                tasks.append({"type": 1.0, "value": f"{val[0]},{val[1]}"})
            elif e_type == 'right':
                tasks.append({"type": 3.0, "value": f"{val[0]},{val[1]}"})
            elif e_type == 'left_drag':
                tasks.append({"type": 10.0, "value": f"{val[0]},{val[1]} -> {val[2]},{val[3]}"})
            elif e_type == 'right_drag':
                tasks.append({"type": 11.0, "value": f"{val[0]},{val[1]} -> {val[2]},{val[3]}"})
            elif e_type == 'scroll':
                tasks.append({"type": 6.0, "value": str(val)})
            elif e_type == 'key':
                tasks.append({"type": 7.0, "value": val})
                
        for task in tasks:
            self.main_window.add_row(task)
            
        if tasks:
            self.main_window.append_log(f"<font color='#E91E63'><b>>>> 成功捕捉全息动作，生成了 {len(tasks)} 步指令序列。</b></font>")
        else:
            self.main_window.append_log("<font color='gray'><b>>>> 未录制到任何动作。</b></font>")
            
        self.main_window.showNormal()
        self.close()

# --------------------------
# 独立看门狗线程
# --------------------------
class FailsafeWatchdog(threading.Thread):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.daemon = True 
        self.running = True

    def run(self):
        write_log(">>> 看门狗线程启动")
        while self.running:
            try:
                if self.engine.enable_key_stop:
                    if GetAsyncKeyState(0x1B) & 0x8000: 
                        self.trigger_stop("用户按下了【ESC键】")
                        return
                    if GetAsyncKeyState(0x04) & 0x8000: 
                        self.trigger_stop("用户按下了【鼠标中键】")
                        return

                if self.engine.enable_tr_stop:
                    x, y = pyautogui.position()
                    w, h = pyautogui.size()
                    if x > (w - 10) and y < 10:
                        self.trigger_stop("检测到鼠标【右上角急停】")
                        return

                if self.engine.enable_tm_stop:
                    if int(time.time() * 100) % 10 == 0: 
                        hwnd = ctypes.windll.user32.GetForegroundWindow()
                        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                            if "任务管理器" in buff.value or "Task Manager" in buff.value:
                                self.trigger_stop("检测到【任务管理器】前台")
                                return
                time.sleep(0.02)
            except Exception as e:
                time.sleep(1)

    def trigger_stop(self, reason):
        if not self.engine.stop_requested:
            write_log(f">>> 看门狗触发: {reason}")
            self.engine.log(f"<font color='red'><b>!!! {reason} -> 停止 !!!</b></font>")
            self.engine.stop() 
            try: ctypes.windll.user32.MessageBeep(0xFFFFFFFF)
            except: pass

    def kill(self):
        self.running = False

# --------------------------
# 核心引擎 (V45+ 内核)
# --------------------------
class RPAEngine:
    def __init__(self):
        self.is_running = False
        self.stop_requested = False
        self.min_scale = 1.0
        self.max_scale = 1.0
        self.confidence = 0.8
        self.scan_region = None 
        self.dodge_x1 = 100
        self.dodge_y1 = 100
        self.dodge_x2 = 200
        self.dodge_y2 = 100
        self.enable_dodge = False
        self.enable_double_dodge = False
        self.double_dodge_wait = 0.1
        self.move_duration = 0.0
        self.click_hold = 0.05
        self.settlement_wait = 0.0
        self.timeout_val = 0.0
        self.detect_delay = 0.01
        self.playback_speed = 1.0
        self.loop_mode = "单次"
        self.loop_val = 1.0
        self.log_level = 0
        self.enable_tm_stop = True 
        self.enable_tr_stop = True 
        self.enable_key_stop = True
        
        self.callback_msg = None
        self.opencv_available = False 
        self.img_cache = {} 
        self.scaled_templates_cache = {}

        self.check_engine_status()
        self.set_high_priority()

    def set_high_priority(self):
        try:
            pid = os.getpid()
            handle = ctypes.windll.kernel32.OpenProcess(0x0100, True, pid)
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000080)
        except: pass

    def check_engine_status(self):
        try:
            import cv2
            import numpy
            img = numpy.zeros((10, 10, 3), dtype=numpy.uint8)
            cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            self.opencv_available = True
            write_log("OpenCV/NumPy 引擎就绪。")
        except:
            self.opencv_available = False
            write_log("OpenCV 引擎不可用。")

    def stop(self):
        self.stop_requested = True
        self.is_running = False

    def log(self, msg):
        write_log(msg, self.callback_msg)

    def check_stop_flag(self):
        return self.stop_requested

    def load_and_precompute(self, tasks):
        if not self.opencv_available: return
        try:
            import cv2
            import numpy as np
            write_log("正在预加载资源...")
            for task in tasks:
                path = str(task.get("value", ""))
                # 过滤掉坐标格式的输入
                if not path or not os.path.exists(path) or ',' in path: continue
                if task.get("type") not in [1.0, 2.0, 3.0, 8.0]: continue
                
                img = Image.open(path)
                img.load()
                self.img_cache[path] = img
                
                if self.min_scale != 1.0 or self.max_scale != 1.0:
                    if img.mode != 'L': img = img.convert('L')
                    template = np.array(img)
                    templates_list = []
                    steps = int((self.max_scale - self.min_scale) / 0.05) + 1
                    for scale in np.linspace(self.min_scale, self.max_scale, steps):
                        if 0.99 < scale < 1.01: continue
                        rw = int(template.shape[1] * scale)
                        rh = int(template.shape[0] * scale)
                        if rw < 1 or rh < 1: continue
                        resized_tpl = cv2.resize(template, (rw, rh))
                        templates_list.append((scale, resized_tpl))
                    self.scaled_templates_cache[path] = templates_list
            write_log("资源预加载完成。")
        except Exception as e:
            write_log(f"预计算失败: {e}")

    def find_target_optimized(self, img_path):
        try: screenshot_pil = pyautogui.screenshot(region=self.scan_region)
        except: return None
        
        offset_x = self.scan_region[0] if self.scan_region else 0
        offset_y = self.scan_region[1] if self.scan_region else 0

        if not self.opencv_available:
            if img_path in self.img_cache:
                try: 
                    res = pyautogui.locate(self.img_cache[img_path], screenshot_pil, confidence=self.confidence)
                    if res: return (res.left + (res.width / 2) + offset_x, res.top + (res.height / 2) + offset_y, 1.0)
                except: pass
            elif os.path.exists(img_path):
                 try:
                    res = pyautogui.locate(img_path, screenshot_pil, confidence=self.confidence)
                    if res: return (res.left + (res.width / 2) + offset_x, res.top + (res.height / 2) + offset_y, 1.0)
                 except: pass
            return None

        import cv2
        import numpy as np
        
        screen_np = np.array(screenshot_pil)
        screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
        
        if img_path not in self.img_cache:
            if os.path.exists(img_path):
                try:
                    img = Image.open(img_path)
                    img.load()
                    self.img_cache[img_path] = img
                except: return None
            else: return None
        
        pil_template = self.img_cache[img_path]
        try:
            if pil_template.mode != 'L': pil_template = pil_template.convert('L')
            tpl_gray = np.array(pil_template)
            if tpl_gray.shape[0] <= screen_gray.shape[0] and tpl_gray.shape[1] <= screen_gray.shape[1]:
                res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
                if max_v >= self.confidence:
                    h, w = tpl_gray.shape[:2]
                    return (max_l[0] + w//2 + offset_x, max_l[1] + h//2 + offset_y, 1.0)
        except: pass
        
        if img_path in self.scaled_templates_cache:
            for scale, resized_tpl in self.scaled_templates_cache[img_path]:
                if self.check_stop_flag(): return None
                try:
                    if resized_tpl.shape[0] > screen_gray.shape[0] or resized_tpl.shape[1] > screen_gray.shape[1]: continue
                    res = cv2.matchTemplate(screen_gray, resized_tpl, cv2.TM_CCOEFF_NORMED)
                    min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
                    if max_v >= self.confidence:
                        h, w = resized_tpl.shape[:2]
                        return (max_l[0] + w//2 + offset_x, max_l[1] + h//2 + offset_y, scale)
                except: continue
        return None

    def get_cmd_name(self, cmd_val):
        mapping = {1.0: "左键单击", 2.0: "左键双击", 3.0: "右键单击", 4.0: "输入文本", 5.0: "等待(秒)", 6.0: "滚轮滑动", 7.0: "系统按键", 8.0: "鼠标悬停", 9.0: "截图保存", 10.0: "左键拖拽", 11.0: "右键拖拽"}
        return mapping.get(cmd_val, "未知操作")

    def parse_coordinate(self, val):
        """解析是否为手动输入的坐标格式，如: 960,540"""
        try:
            val_str = str(val).strip()
            if ',' in val_str:
                parts = val_str.split(',')
                if len(parts) == 2:
                    return int(parts[0].strip()), int(parts[1].strip())
        except: pass
        return None

    def mouseClick(self, clickTimes, lOrR, img_path, reTry, step_info=None):
        if step_info is None: step_info = {'step': 0, 'loop': 0, 'cmd': ''}
        start_time = time.time()
        
        waiting_logged = False
        coord = self.parse_coordinate(img_path)

        while True:
            if self.check_stop_flag(): return
            if self.timeout_val > 0.001 and (time.time() - start_time > self.timeout_val): 
                if self.log_level >= 1:
                    self.log(f"<font color='orange'>    [超时] 循环#{step_info['loop']} 步{step_info['step']}: 等待目标超时，已跳过</font>")
                return "timeout"

            if coord:
                location_tuple = (coord[0], coord[1], 1.0)
                find_time = 0.0
            else:
                find_start = time.time()
                location_tuple = self.find_target_optimized(img_path)
                find_time = time.time() - find_start

            if location_tuple:
                try:
                    x, y, scale = location_tuple
                    
                    if self.log_level >= 2:
                        local_t = time.strftime("%H:%M:%S")
                        self.log(f"    <font color='gray'>[{local_t}] => 底层找图耗时 {find_time:.3f}s，缩放倍率: {scale:.2f}x</font>")
                    if self.log_level >= 1:
                        self.log(f"    -> 已在坐标 ({int(x)}, {int(y)}) 锁定目标并执行点击")

                    pyautogui.moveTo(x, y, duration=self.move_duration)
                    for _ in range(clickTimes):
                        pyautogui.mouseDown(button=lOrR)
                        time.sleep(self.click_hold)
                        pyautogui.mouseUp(button=lOrR)
                        if clickTimes > 1: time.sleep(0.02)
                    
                    if self.settlement_wait > 0: time.sleep(self.settlement_wait)
                    
                    if self.enable_dodge:
                        pyautogui.moveTo(self.dodge_x1, self.dodge_y1, duration=0)
                        if self.enable_double_dodge:
                            time.sleep(self.double_dodge_wait) 
                            pyautogui.moveTo(self.dodge_x2, self.dodge_y2, duration=0)
                            
                except Exception as e: 
                    if self.log_level >= 1: self.log(f"<font color='red'>    [错误] 循环#{step_info['loop']} 步{step_info['step']}: {e}</font>")
                return "success"
            else:
                if reTry != -1:
                    if self.log_level >= 1:
                        self.log(f"<font color='orange'>    [跳过] 循环#{step_info['loop']} 步{step_info['step']}: 未能识别到目标图片 ({os.path.basename(img_path)})</font>")
                    return "not_found"
                else:
                    if not waiting_logged and self.log_level >= 1:
                        self.log(f"    -> 未发现目标，进入持续监听等待状态...")
                        waiting_logged = True
                    time.sleep(self.detect_delay)
                    continue

    def mouseDrag(self, button, val, step_info):
        try:
            parts = val.split('->')
            p1 = parts[0].split(',')
            p2 = parts[1].split(',')
            x1, y1 = int(p1[0].strip()), int(p1[1].strip())
            x2, y2 = int(p2[0].strip()), int(p2[1].strip())
        except:
            if self.log_level >= 1: self.log(f"<font color='red'>    [错误] 循环#{step_info['loop']} 步{step_info['step']}: 拖拽坐标格式错误，应为 x1,y1 -> x2,y2</font>")
            return
        
        if self.log_level >= 1:
            self.log(f"    -> 正在从 ({x1},{y1}) 拖拽到 ({x2},{y2})")
            
        pyautogui.moveTo(x1, y1, duration=self.move_duration)
        pyautogui.mouseDown(button=button)
        time.sleep(self.click_hold)
        pyautogui.moveTo(x2, y2, duration=max(self.move_duration, 0.3))
        pyautogui.mouseUp(button=button)
        if self.settlement_wait > 0: time.sleep(self.settlement_wait)

    def run_tasks(self, tasks, callback_msg=None):
        self.is_running = True
        self.stop_requested = False
        self.callback_msg = callback_msg
        
        self.img_cache = {}
        self.scaled_templates_cache = {}
        self.load_and_precompute(tasks)
        
        global_start_time = time.time()
        loop_count = 0

        try:
            while True:
                loop_count += 1
                
                if self.loop_mode == "单次" and loop_count > 1: break
                elif self.loop_mode == "指定次数" and loop_count > self.loop_val:
                    if self.log_level >= 0: self.log(f"<font color='green'>>>> 提示: 已达到指定循环次数 ({int(self.loop_val)}次)，任务正常结束</font>")
                    break
                elif self.loop_mode == "指定时间(时)" and (time.time() - global_start_time) / 3600.0 >= self.loop_val:
                    if self.log_level >= 0: self.log(f"<font color='green'>>>> 提示: 已达到指定运行时间，任务正常结束</font>")
                    break
                elif self.loop_mode == "指定时间(分)" and (time.time() - global_start_time) / 60.0 >= self.loop_val:
                    if self.log_level >= 0: self.log(f"<font color='green'>>>> 提示: 已达到指定运行时间，任务正常结束</font>")
                    break
                elif self.loop_mode == "指定时间(秒)" and (time.time() - global_start_time) >= self.loop_val:
                    if self.log_level >= 0: self.log(f"<font color='green'>>>> 提示: 已达到指定运行时间，任务正常结束</font>")
                    break

                for idx, task in enumerate(tasks):
                    if self.check_stop_flag():
                        if callback_msg: callback_msg("任务由看门狗终止")
                        return

                    cmd = task.get("type")
                    val = task.get("value")
                    retry = task.get("retry", 1)
                    
                    cmd_name = self.get_cmd_name(cmd)
                    step_info = {'step': idx + 1, 'loop': loop_count, 'cmd': cmd_name}
                    step_start_time = time.time()
                    
                    try:
                        status = "success"
                        if cmd == 1.0: status = self.mouseClick(1, "left", val, retry, step_info)
                        elif cmd == 2.0: status = self.mouseClick(2, "left", val, retry, step_info)
                        elif cmd == 3.0: status = self.mouseClick(1, "right", val, retry, step_info)
                        elif cmd == 10.0: self.mouseDrag("left", val, step_info)
                        elif cmd == 11.0: self.mouseDrag("right", val, step_info)
                        elif cmd == 8.0:
                            coord = self.parse_coordinate(val)
                            if coord:
                                loc = (coord[0], coord[1], 1.0)
                                find_time = 0.0
                            else:
                                find_start = time.time()
                                loc = self.find_target_optimized(val)
                                find_time = time.time() - find_start
                                
                            if loc: 
                                x, y, scale = loc
                                if self.log_level >= 2:
                                    local_t = time.strftime("%H:%M:%S")
                                    self.log(f"    <font color='gray'>[{local_t}] => 底层找图耗时 {find_time:.3f}s，缩放: {scale:.2f}x</font>")
                                if self.log_level >= 1:
                                    self.log(f"    -> 已悬停在坐标 ({int(x)}, {int(y)})")
                                pyautogui.moveTo(x, y, duration=self.move_duration)
                            else:
                                status = "not_found"
                                if self.log_level >= 1:
                                    self.log(f"<font color='orange'>    [异常] 循环#{loop_count} 步{idx+1}: 悬停失败，未识别到目标</font>")

                        elif cmd == 4.0: 
                            if self.log_level >= 1: self.log(f"    -> 正在输入文本: {val}")
                            pyperclip.copy(str(val)); pyautogui.hotkey('ctrl', 'v'); time.sleep(0.2)
                        elif cmd == 5.0: 
                            wait_time = float(val) / max(self.playback_speed, 0.1) 
                            if self.log_level >= 1: self.log(f"    -> 强制静默等待 {wait_time:.2f} 秒 (原录制设定 {val}s, 倍速 {self.playback_speed}x)...")
                            t_end = time.time() + wait_time
                            while time.time() < t_end:
                                if self.check_stop_flag(): return
                                time.sleep(0.05)
                        elif cmd == 6.0: 
                            if self.log_level >= 1: self.log(f"    -> 鼠标滚轮滑动 {val}")
                            pyautogui.scroll(int(float(val)))
                        elif cmd == 7.0: 
                            if self.log_level >= 1: self.log(f"    -> 触发系统按键组合: {val}")
                            pyautogui.hotkey(*[k.strip() for k in str(val).lower().split('+')])
                        elif cmd == 9.0:
                            path = str(val)
                            if os.path.isdir(path): path = os.path.join(path, time.strftime("ss_%H%M%S.png"))
                            try: 
                                pyautogui.screenshot(path, region=self.scan_region)
                                if self.log_level >= 1: self.log(f"    -> 已截图并保存至 {path}")
                            except: pass
                    except Exception as step_e:
                        status = "error"
                        if self.log_level >= 1: self.log(f"<font color='red'>    [严重异常] 循环#{loop_count} 步{idx+1}: 执行崩溃 -> {step_e}</font>")

                    step_duration = time.time() - step_start_time
                    if self.log_level >= 0:
                        status_str = "完成"
                        color = "gray"
                        if status == "success": status_str = "完成"; color = "gray"
                        elif status == "timeout": status_str = "超时跳过"; color = "orange"
                        elif status == "not_found": status_str = "未找到目标跳过"; color = "orange"
                        elif status == "error": status_str = "执行异常"; color = "red"
                        
                        self.log(f"<font color='{color}'>循环 #{loop_count} 步 {idx+1} ({cmd_name}) {status_str}，耗时: {step_duration:.2f}s</font>")

                    if self.detect_delay > 0:
                        time.sleep(self.detect_delay)

                if self.check_stop_flag(): return
                
        except Exception as e:
            self.log(f"<font color='red'>引擎异常: {e}</font>")
        finally:
            self.is_running = False
            if callback_msg: callback_msg("结束")

# --------------------------
# GUI 界面
# --------------------------
class WorkerThread(QThread):
    log_signal = Signal(str)
    finished_signal = Signal()
    def __init__(self, engine, tasks):
        super().__init__()
        self.engine = engine
        self.tasks = tasks

    def run(self):
        self.watchdog = FailsafeWatchdog(self.engine)
        self.watchdog.start()
        self.engine.run_tasks(self.tasks, self.log_callback)
        if self.watchdog: self.watchdog.kill()
        self.finished_signal.emit()

    def log_callback(self, msg): 
        if GLOBAL_CONFIG["log_to_ui"]:
            self.log_signal.emit(msg)

class TaskRow(QFrame):
    def __init__(self, delete_callback):
        super().__init__()
        self.parent_item = None
        self.setFrameShape(QFrame.StyledPanel)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)
        
        self.index_label = QLabel("1.")
        self.index_label.setFixedWidth(25)
        self.index_label.setAlignment(Qt.AlignCenter)
        self.index_label.setStyleSheet("color: gray; font-weight: bold;")
        self.layout.addWidget(self.index_label)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["左键单击", "左键双击", "右键单击", "输入文本", "等待(秒)", "滚轮滑动", "系统按键", "鼠标悬停", "截图保存", "左键拖拽", "右键拖拽"])
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        self.layout.addWidget(self.type_combo)
        
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("坐标如: 960,540 或 各种参数")
        self.value_input.textChanged.connect(self.sync_data)
        self.layout.addWidget(self.value_input)
        
        self.file_btn = QPushButton("图")
        self.file_btn.setFixedWidth(30)
        self.file_btn.clicked.connect(self.select_file)
        self.layout.addWidget(self.file_btn)
        
        self.del_btn = QPushButton("X")
        self.del_btn.setStyleSheet("color: red; font-weight: bold;")
        self.del_btn.setFixedWidth(25)
        self.del_btn.clicked.connect(lambda: delete_callback(self))
        self.layout.addWidget(self.del_btn)
        
        self.on_type_changed(self.type_combo.currentText())

    def set_parent_item(self, item):
        self.parent_item = item
        self.sync_data() 

    def sync_data(self):
        if getattr(self, 'parent_item', None):
            self.parent_item.setData(Qt.UserRole, self.get_data())

    def on_type_changed(self, text):
        self.file_btn.setVisible("单击" in text or "悬停" in text or "截图" in text)
        self.sync_data()
            
    def set_data(self, data):
        self.value_input.setText(str(data.get("value", "")))
        TYPES_REV = {1.0: "左键单击", 2.0: "左键双击", 3.0: "右键单击", 4.0: "输入文本", 5.0: "等待(秒)", 6.0: "滚轮滑动", 7.0: "系统按键", 8.0: "鼠标悬停", 9.0: "截图保存", 10.0: "左键拖拽", 11.0: "右键拖拽"}
        t = data.get("type", 1.0)
        if t in TYPES_REV:
            self.type_combo.setCurrentText(TYPES_REV[t])

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择", filter="Images (*.png *.jpg *.bmp)")
        if path: self.value_input.setText(path)

    def get_data(self):
        TYPES = {"左键单击": 1.0, "左键双击": 2.0, "右键单击": 3.0, "输入文本": 4.0, "等待(秒)": 5.0, "滚轮滑动": 6.0, "系统按键": 7.0, "鼠标悬停": 8.0, "截图保存": 9.0, "左键拖拽": 10.0, "右键拖拽": 11.0}
        val = self.value_input.text()
        t = TYPES.get(self.type_combo.currentText(), 1.0)
        if t in [5.0, 6.0] and not val: val = "0"
        return {"type": t, "value": val}

    def set_index(self, index):
        self.index_label.setText(f"{index}.")

class DraggableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def dropEvent(self, event):
        super().dropEvent(event)
        for i in range(self.count()):
            item = self.item(i)
            if self.itemWidget(item) is None:
                data = item.data(Qt.UserRole)
                if data:
                    self.window().restore_row_widget(item, data)
        if hasattr(self.window(), 'update_indexes'):
            self.window().update_indexes()

# --------------------------
# 主窗口
# --------------------------
class RPAWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("不高兴就喝水 RPA配置工具(浮夸改V1.1)")
        self.resize(900, 850)
        self.engine = RPAEngine()
        
        # 修改：放弃注册表，改用当前目录下的 config.ini 存储所有配置
        self.config_path = os.path.join(get_base_dir(), "config.ini")
        self.settings = QSettings(self.config_path, QSettings.IniFormat)
        
        self.recorder_ui = None
        
        # 恢复窗口上次的位置和大小
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # 配置文件体系
        self.profiles_data = {}
        self.current_profile_name = "默认方案"
        self.is_switching_profile = True 
        
        self.hotkey_start_vk = 0x78 # F9
        self.hotkey_stop_vk = 0x79  # F10
        self.current_process = None
        if HAS_PSUTIL:
            try: self.current_process = psutil.Process()
            except: pass
            
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        # ================= 顶部方案管理与工具栏 =================
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("<b>配置方案:</b>"))
        self.profile_combo = QComboBox()
        self.profile_combo.setFixedWidth(150)
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        profile_layout.addWidget(self.profile_combo)
        
        new_prof_btn = QPushButton("+ 新建")
        new_prof_btn.clicked.connect(self.create_new_profile)
        profile_layout.addWidget(new_prof_btn)
        
        rename_prof_btn = QPushButton("重命名")
        rename_prof_btn.clicked.connect(self.rename_current_profile)
        profile_layout.addWidget(rename_prof_btn)
        
        del_prof_btn = QPushButton("- 删除")
        del_prof_btn.clicked.connect(self.delete_current_profile)
        profile_layout.addWidget(del_prof_btn)
        
        prof_up_btn = QPushButton("↑")
        prof_up_btn.setFixedWidth(25)
        prof_up_btn.setToolTip("上移方案")
        prof_up_btn.clicked.connect(self.move_profile_up)
        profile_layout.addWidget(prof_up_btn)
        
        prof_down_btn = QPushButton("↓")
        prof_down_btn.setFixedWidth(25)
        prof_down_btn.setToolTip("下移方案")
        prof_down_btn.clicked.connect(self.move_profile_down)
        profile_layout.addWidget(prof_down_btn)
        
        profile_layout.addStretch()
        
        save_btn = QPushButton("导出方案")
        save_btn.clicked.connect(self.save)
        profile_layout.addWidget(save_btn)
        load_btn = QPushButton("导入方案")
        load_btn.clicked.connect(self.load)
        profile_layout.addWidget(load_btn)
        
        # 新增：打开配置目录按钮
        open_dir_btn = QPushButton("打开配置目录")
        open_dir_btn.clicked.connect(self.open_config_dir)
        profile_layout.addWidget(open_dir_btn)
        
        main_layout.addLayout(profile_layout)
        
        # 工具栏行
        top_bar = QHBoxLayout()
        add_btn = QPushButton("+ 新增指令")
        add_btn.clicked.connect(lambda: self.add_row())
        top_bar.addWidget(add_btn)
        
        record_btn = QPushButton("⏺ 操作录制")
        record_btn.setStyleSheet("color: #E91E63; font-weight: bold;")
        record_btn.clicked.connect(self.start_recording)
        top_bar.addWidget(record_btn)
        
        region_btn = QPushButton("📷 设定识别区域")
        region_btn.setStyleSheet("background-color: #9C27B0; color: white; font-weight: bold;")
        region_btn.clicked.connect(self.open_region_selector)
        top_bar.addWidget(region_btn)
        
        top_bar.addWidget(HelpBtn("【设定识别区域】\n如CPU占用较高，务必使用此功能！\n框选的搜索范围越小，找图速度越快，对CPU的压力呈指数级减小。"))
        
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        # ================= 核心折叠设置区 =================
        # 1. 识别配置
        g1 = CollapsibleSection("识别配置")
        gl1 = QHBoxLayout()
        gl1.addWidget(QLabel("相似:"))
        self.conf_edit = QLineEdit("0.8"); self.conf_edit.setFixedWidth(50); gl1.addWidget(self.conf_edit)
        gl1.addWidget(HelpBtn("【相似度 (0.1 - 1.0)】\n数值越低：越容易匹配，但极易导致乱点误触。\n数值越高：越精确。\n注：修改此数值仅影响精度，不影响CPU占用。"))
        gl1.addSpacing(20)
        gl1.addWidget(QLabel("缩放:"))
        self.scale_min = QLineEdit("0.8"); self.scale_min.setFixedWidth(50); gl1.addWidget(self.scale_min)
        gl1.addWidget(QLabel("-")); 
        self.scale_max = QLineEdit("1.2"); self.scale_max.setFixedWidth(50); gl1.addWidget(self.scale_max)
        gl1.addWidget(HelpBtn("【缩放范围】\n程序启动时会预先生成缩放模板缓存。\n建议不要超过 0.5 - 2.0。\n注意：这两个数值相差越大，每次找图需比对的次数越多，对CPU的压力成倍增加！"))
        gl1.addStretch()
        g1.set_content_layout(gl1)
        main_layout.addWidget(g1)
        
        # 2. 避让设置
        g_dodge = CollapsibleSection("避让设置")
        gl_dodge = QHBoxLayout()
        gl_dodge.addWidget(QLabel("坐标1 X:"))
        self.dodge_x1 = QLineEdit("100"); self.dodge_x1.setFixedWidth(50); gl_dodge.addWidget(self.dodge_x1)
        gl_dodge.addWidget(QLabel("Y:"))
        self.dodge_y1 = QLineEdit("100"); self.dodge_y1.setFixedWidth(50); gl_dodge.addWidget(self.dodge_y1)
        gl_dodge.addSpacing(15)
        gl_dodge.addWidget(QLabel("坐标2 X:"))
        self.dodge_x2 = QLineEdit("200"); self.dodge_x2.setFixedWidth(50); gl_dodge.addWidget(self.dodge_x2)
        gl_dodge.addWidget(QLabel("Y:"))
        self.dodge_y2 = QLineEdit("100"); self.dodge_y2.setFixedWidth(50); gl_dodge.addWidget(self.dodge_y2)
        self.dodge_chk = QCheckBox("启用"); gl_dodge.addWidget(self.dodge_chk)
        self.double_dodge_chk = QCheckBox("二段"); gl_dodge.addWidget(self.double_dodge_chk)
        gl_dodge.addWidget(QLabel("间隔:"))
        self.dbl_wait = QLineEdit("0.1"); self.dbl_wait.setFixedWidth(60); gl_dodge.addWidget(self.dbl_wait)
        gl_dodge.addWidget(HelpBtn("【二段避让间隔】\n第一次避让与第二次避让之间的间隔时间，单位：秒\n部分游戏需要短暂间隔才能识别鼠标移动"))
        gl_dodge.addStretch()
        g_dodge.set_content_layout(gl_dodge)
        main_layout.addWidget(g_dodge)
        
        # 3. 速度控制
        g2 = CollapsibleSection("速度控制 (0为极速)")
        gl2 = QHBoxLayout()
        gl2.addWidget(QLabel("移动(s):")); self.move_spd = QLineEdit("0.0"); self.move_spd.setFixedWidth(50); gl2.addWidget(self.move_spd)
        gl2.addWidget(HelpBtn("【移动耗时】\n0.0=瞬移"))
        gl2.addWidget(QLabel("按住(s):")); self.click_hld = QLineEdit("0.05"); self.click_hld.setFixedWidth(50); gl2.addWidget(self.click_hld)
        gl2.addWidget(HelpBtn("【按住时长】\n建议0.04-0.08模拟真人点击"))
        gl2.addWidget(QLabel("缓冲(s):")); self.settle = QLineEdit("0"); self.settle.setFixedWidth(50); gl2.addWidget(self.settle)
        gl2.addWidget(HelpBtn("【结算缓冲】\n点击后的等待时间"))
        gl2.addWidget(QLabel("超时(s):")); self.timeout = QLineEdit("0.0"); self.timeout.setFixedWidth(50); gl2.addWidget(self.timeout)
        gl2.addWidget(HelpBtn("【单步超时】\n0.0=扫一眼没找到直接过"))
        gl2.addWidget(QLabel("频率(s):")); self.detect_delay = QLineEdit("0.01"); self.detect_delay.setFixedWidth(60); gl2.addWidget(self.detect_delay)
        gl2.addWidget(HelpBtn("【检测频率(找图间隔)】\n没找到图时的等待时间(秒)\n默认极速为0.01，若CPU占用过高，建议设置为 0.1 - 0.5"))
        gl2.addWidget(QLabel("倍速:")); self.playback_speed = QLineEdit("1.0"); self.playback_speed.setFixedWidth(40); gl2.addWidget(self.playback_speed)
        gl2.addWidget(HelpBtn("【倍速执行】\n用于缩短录制时长产生的等待时间（仅影响'等待(秒)'指令）。\n> 1.0 为加速，< 1.0 为减速。\n注意：如果执行出现BUG请调低数值！"))
        gl2.addStretch()
        g2.set_content_layout(gl2)
        main_layout.addWidget(g2)
        
        # 4. 系统设置
        g3 = CollapsibleSection("系统设置")
        gl3_main = QVBoxLayout()
        
        gl3_r1 = QHBoxLayout()
        gl3_r1.addWidget(QLabel("启动热键:"))
        self.hotkey_start_combo = QComboBox(); self.hotkey_start_combo.addItems([f"F{i}" for i in range(1, 13)])
        self.hotkey_start_combo.setCurrentText("F9"); self.hotkey_start_combo.setFixedWidth(75)
        self.hotkey_start_combo.currentTextChanged.connect(self.update_hotkeys)
        gl3_r1.addWidget(self.hotkey_start_combo)
        
        gl3_r1.addWidget(QLabel("停止热键:"))
        self.hotkey_stop_combo = QComboBox(); self.hotkey_stop_combo.addItems([f"F{i}" for i in range(1, 13)])
        self.hotkey_stop_combo.setCurrentText("F10"); self.hotkey_stop_combo.setFixedWidth(75)
        self.hotkey_stop_combo.currentTextChanged.connect(self.update_hotkeys)
        gl3_r1.addWidget(self.hotkey_stop_combo)
        
        gl3_r1.addSpacing(15)
        gl3_r1.addWidget(QLabel("日志级别:"))
        self.log_level_combo = QComboBox(); self.log_level_combo.addItems(["简易", "详细", "完全"])
        self.log_level_combo.setFixedWidth(80)
        gl3_r1.addWidget(self.log_level_combo)
        gl3_r1.addStretch()
        
        gl3_r2 = QHBoxLayout()
        self.tm_failsafe = QCheckBox("任务管理器急停"); self.tm_failsafe.setChecked(True); gl3_r2.addWidget(self.tm_failsafe)
        self.tr_failsafe = QCheckBox("右上角急停"); self.tr_failsafe.setChecked(True); gl3_r2.addWidget(self.tr_failsafe)
        self.key_failsafe = QCheckBox("ESC/中键急停"); self.key_failsafe.setChecked(True); gl3_r2.addWidget(self.key_failsafe)
        
        gl3_r2.addSpacing(15)
        self.log_file_chk = QCheckBox("写入文件日志"); gl3_r2.addWidget(self.log_file_chk)
        self.log_ui_chk = QCheckBox("界面日志"); self.log_ui_chk.setChecked(True); gl3_r2.addWidget(self.log_ui_chk)
        self.log_file_chk.stateChanged.connect(self.update_log_config)
        self.log_ui_chk.stateChanged.connect(self.update_log_config)
        gl3_r2.addStretch()
        
        gl3_main.addLayout(gl3_r1)
        gl3_main.addLayout(gl3_r2)
        g3.set_content_layout(gl3_main)
        main_layout.addWidget(g3)

        # ================= 任务列表与日志分屏 =================
        self.splitter = QSplitter(Qt.Vertical)
        
        self.task_list = DraggableListWidget()
        self.splitter.addWidget(self.task_list)
        
        bottom_widget = QWidget()
        bottom_vbox = QVBoxLayout(bottom_widget)
        bottom_vbox.setContentsMargins(0, 0, 0, 0)
        
        # 底部控制区
        bot_layout = QHBoxLayout()
        self.loop_combo = QComboBox()
        self.loop_combo.addItems(["单次", "无限", "指定次数", "指定时间(时)", "指定时间(分)", "指定时间(秒)"])
        self.loop_combo.currentTextChanged.connect(self.update_loop_ui)
        bot_layout.addWidget(self.loop_combo)
        
        self.loop_val_edit = QLineEdit("10"); self.loop_val_edit.setFixedWidth(50)
        bot_layout.addWidget(self.loop_val_edit)
        self.update_loop_ui(self.loop_combo.currentText())
        
        bot_layout.addSpacing(20)
        self.mini_chk = QCheckBox("最小化"); bot_layout.addWidget(self.mini_chk)
        self.top_chk = QCheckBox("置顶"); self.top_chk.stateChanged.connect(self.toggle_top_window)
        bot_layout.addWidget(self.top_chk)
        bot_layout.addStretch()
        
        self.start_btn = QPushButton("启动"); self.start_btn.clicked.connect(self.start_task)
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; width: 100px; height: 30px;")
        bot_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止"); self.stop_btn.clicked.connect(self.stop_task)
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; width: 100px; height: 30px;")
        self.stop_btn.setEnabled(False)
        bot_layout.addWidget(self.stop_btn)
        
        bottom_vbox.addLayout(bot_layout)
        
        self.log_text = QTextEdit()
        self.log_text.document().setMaximumBlockCount(500)
        bottom_vbox.addWidget(self.log_text)
        
        self.splitter.addWidget(bottom_widget)
        self.splitter.setSizes([450, 200]) # 设定上下初始比例
        main_layout.addWidget(self.splitter)
        
        # 状态栏
        self.status_layout = QHBoxLayout()
        self.log_path_label = QLabel(f"日志: {get_log_path()}")
        self.log_path_label.setStyleSheet("color: gray; font-size: 10px;")
        main_layout.addWidget(self.log_path_label)
        
        self.status_layout = QHBoxLayout()
        self.region_label = QLabel("范围: 全屏")
        self.region_label.setStyleSheet("color: green;")
        self.status_layout.addWidget(self.region_label)
        self.status_layout.addStretch()
        self.cpu_label = QLabel("CPU: --")
        self.cpu_label.setStyleSheet("color: blue; font-weight: bold;")
        self.status_layout.addWidget(self.cpu_label)
        main_layout.addLayout(self.status_layout)
        
        # 初始化定时器与全局配置
        self.cpu_timer = QTimer()
        self.cpu_timer.timeout.connect(self.update_cpu_info)
        self.cpu_timer.start(1000)
        
        self.hotkey_timer = QTimer()
        self.hotkey_timer.timeout.connect(self.check_hotkey)
        self.hotkey_timer.start(100)
        
        self.init_profiles()
        self.bind_setting_logs()

    def open_config_dir(self):
        """打开配置文件所在的本地目录"""
        try:
            os.startfile(get_base_dir())
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开配置目录: {e}")

    def append_log(self, msg):
        """智能日志追加：若用户在看历史记录，则不自动滚动到底部；若在底部，则自动跟随。"""
        scrollbar = self.log_text.verticalScrollBar()
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 5
        old_val = scrollbar.value()
        
        self.log_text.append(msg)
        
        if not is_at_bottom:
            scrollbar.setValue(old_val)
        else:
            scrollbar.setValue(scrollbar.maximum())

    # ================= 方案管理核心逻辑 =================
    def init_profiles(self):
        saved_profiles = self.settings.value("profiles_json", "{}")
        try: self.profiles_data = json.loads(saved_profiles)
        except: self.profiles_data = {}
        
        if not self.profiles_data:
            self.profiles_data["默认方案"] = self.get_default_config_dict()
            
        self.profile_combo.addItems(list(self.profiles_data.keys()))
        last_prof = self.settings.value("current_profile", "默认方案")
        if last_prof in self.profiles_data:
            self.profile_combo.setCurrentText(last_prof)
        else:
            self.profile_combo.setCurrentIndex(0)
            
        self.is_switching_profile = False
        # 修复Bug：切断重新打开被前一个界面状态覆盖的源头
        self.current_profile_name = self.profile_combo.currentText()
        self.apply_ui_config(self.profiles_data[self.current_profile_name])
        self.toggle_top_window()

    def get_default_config_dict(self):
        return {
            "conf": "0.8", "scale_min": "0.8", "scale_max": "1.2",
            "dodge_x1": "100", "dodge_y1": "100", "dodge_x2": "200", "dodge_y2": "100",
            "dodge_en": False, "dbl_dodge": False, "dbl_wait": "0.1",
            "move_spd": "0.0", "click_hld": "0.05", "settle": "0", "timeout": "0.0", "detect_delay": "0.01", "playback_speed": "1.0",
            "hotkey_start": "F9", "hotkey_stop": "F10", "log_level": 0,
            "tm_fs": True, "tr_fs": True, "key_fs": True,
            "log_f": False, "log_ui": True, "mini": False, "top": False,
            "loop_mode": "单次", "loop_val": "10",
            "tasks": []
        }

    def get_current_ui_config(self):
        tasks = []
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            widget = self.task_list.itemWidget(item)
            if widget: tasks.append(widget.get_data())
            else: tasks.append(item.data(Qt.UserRole))
            
        return {
            "conf": self.conf_edit.text(), "scale_min": self.scale_min.text(), "scale_max": self.scale_max.text(),
            "dodge_x1": self.dodge_x1.text(), "dodge_y1": self.dodge_y1.text(), "dodge_x2": self.dodge_x2.text(), "dodge_y2": self.dodge_y2.text(),
            "dodge_en": self.dodge_chk.isChecked(), "dbl_dodge": self.double_dodge_chk.isChecked(), "dbl_wait": self.dbl_wait.text(),
            "move_spd": self.move_spd.text(), "click_hld": self.click_hld.text(), "settle": self.settle.text(), "timeout": self.timeout.text(), "detect_delay": self.detect_delay.text(), "playback_speed": self.playback_speed.text(),
            "hotkey_start": self.hotkey_start_combo.currentText(), "hotkey_stop": self.hotkey_stop_combo.currentText(), "log_level": self.log_level_combo.currentIndex(),
            "tm_fs": self.tm_failsafe.isChecked(), "tr_fs": self.tr_failsafe.isChecked(), "key_fs": self.key_failsafe.isChecked(),
            "log_f": self.log_file_chk.isChecked(), "log_ui": self.log_ui_chk.isChecked(), "mini": self.mini_chk.isChecked(), "top": self.top_chk.isChecked(),
            "loop_mode": self.loop_combo.currentText(), "loop_val": self.loop_val_edit.text(),
            "tasks": tasks
        }

    def apply_ui_config(self, cfg):
        try:
            self.conf_edit.setText(str(cfg.get("conf", "0.8")))
            self.scale_min.setText(str(cfg.get("scale_min", "0.8")))
            self.scale_max.setText(str(cfg.get("scale_max", "1.2")))
            self.dodge_x1.setText(str(cfg.get("dodge_x1", "100")))
            self.dodge_y1.setText(str(cfg.get("dodge_y1", "100")))
            self.dodge_x2.setText(str(cfg.get("dodge_x2", "200")))
            self.dodge_y2.setText(str(cfg.get("dodge_y2", "100")))
            self.dodge_chk.setChecked(bool(cfg.get("dodge_en", False)))
            self.double_dodge_chk.setChecked(bool(cfg.get("dbl_dodge", False)))
            self.dbl_wait.setText(str(cfg.get("dbl_wait", "0.1")))
            
            self.move_spd.setText(str(cfg.get("move_spd", "0.0")))
            self.click_hld.setText(str(cfg.get("click_hld", "0.05")))
            self.settle.setText(str(cfg.get("settle", "0")))
            self.timeout.setText(str(cfg.get("timeout", "0.0")))
            self.detect_delay.setText(str(cfg.get("detect_delay", "0.001")))
            self.playback_speed.setText(str(cfg.get("playback_speed", "1.0")))
            
            self.hotkey_start_combo.setCurrentText(str(cfg.get("hotkey_start", "F9")))
            self.hotkey_stop_combo.setCurrentText(str(cfg.get("hotkey_stop", "F10")))
            self.log_level_combo.setCurrentIndex(int(cfg.get("log_level", 0)))
            
            self.tm_failsafe.setChecked(bool(cfg.get("tm_fs", True)))
            self.tr_failsafe.setChecked(bool(cfg.get("tr_fs", True)))
            self.key_failsafe.setChecked(bool(cfg.get("key_fs", True)))
            
            self.log_file_chk.setChecked(bool(cfg.get("log_f", False)))
            self.log_ui_chk.setChecked(bool(cfg.get("log_ui", True)))
            self.mini_chk.setChecked(bool(cfg.get("mini", False)))
            self.top_chk.setChecked(bool(cfg.get("top", False)))
            
            self.loop_combo.setCurrentText(str(cfg.get("loop_mode", "单次")))
            self.loop_val_edit.setText(str(cfg.get("loop_val", "10")))
            
            self.task_list.clear()
            tasks = cfg.get("tasks", [])
            for d in tasks: self.add_row(d)
            
            self.update_log_config()
            self.update_hotkeys()
        except Exception as e:
            write_log(f"应用配置失败: {e}")

    def on_profile_changed(self, new_name):
        if self.is_switching_profile: return
        old_name = self.current_profile_name
        self.profiles_data[old_name] = self.get_current_ui_config()
        
        self.is_switching_profile = True
        self.current_profile_name = new_name
        self.apply_ui_config(self.profiles_data[new_name])
        self.is_switching_profile = False
        
        if GLOBAL_CONFIG["log_to_ui"]:
            self.append_log(f"<b><font color='purple'>>>> 已切换至配置方案: {new_name}</font></b>")

    def create_new_profile(self):
        text, ok = QInputDialog.getText(self, "新建方案", "请输入新方案名称:")
        if ok and text:
            if text in self.profiles_data:
                QMessageBox.warning(self, "错误", "方案名称已存在！")
                return
            
            self.profiles_data[self.current_profile_name] = self.get_current_ui_config()
            self.profiles_data[text] = self.get_default_config_dict()
            
            self.is_switching_profile = True
            self.profile_combo.addItem(text)
            self.profile_combo.setCurrentText(text)
            self.current_profile_name = text
            self.apply_ui_config(self.profiles_data[text])
            self.is_switching_profile = False
            
    def rename_current_profile(self):
        old_name = self.current_profile_name
        text, ok = QInputDialog.getText(self, "重命名方案", "请输入新的方案名称:", QLineEdit.Normal, old_name)
        if ok and text and text != old_name:
            if text in self.profiles_data:
                QMessageBox.warning(self, "错误", "方案名称已存在！")
                return
            
            # 修复：安全剥离旧名字下的数据
            self.profiles_data[text] = self.profiles_data.pop(old_name, self.get_current_ui_config())
            
            self.is_switching_profile = True
            idx = self.profile_combo.findText(old_name)
            if idx >= 0:
                self.profile_combo.setItemText(idx, text)
            self.current_profile_name = text
            self.is_switching_profile = False
            
            self.settings.setValue("current_profile", self.current_profile_name)
            if GLOBAL_CONFIG["log_to_ui"]:
                self.append_log(f"<font color='#FF9800'><b>>>> 方案已重命名: {old_name} -> {text}</b></font>")

    def delete_current_profile(self):
        if len(self.profiles_data) <= 1:
            QMessageBox.warning(self, "错误", "至少需要保留一个方案！")
            return
        del_name = self.current_profile_name
        
        self.profiles_data.pop(del_name, None)
        
        self.is_switching_profile = True
        idx = self.profile_combo.findText(del_name)
        if idx >= 0:
            self.profile_combo.removeItem(idx)
            
        self.current_profile_name = self.profile_combo.currentText()
        
        if self.current_profile_name not in self.profiles_data:
            if self.profiles_data:
                self.current_profile_name = list(self.profiles_data.keys())[0]
            else:
                self.profiles_data["默认方案"] = self.get_default_config_dict()
                self.current_profile_name = "默认方案"
            self.profile_combo.setCurrentText(self.current_profile_name)
            
        self.apply_ui_config(self.profiles_data[self.current_profile_name])
        self.is_switching_profile = False

    def move_profile_up(self):
        idx = self.profile_combo.currentIndex()
        if idx > 0:
            keys = list(self.profiles_data.keys())
            keys[idx - 1], keys[idx] = keys[idx], keys[idx - 1]
            self.profiles_data = {k: self.profiles_data[k] for k in keys}
            
            self.is_switching_profile = True
            self.profile_combo.clear()
            self.profile_combo.addItems(keys)
            self.profile_combo.setCurrentIndex(idx - 1)
            self.current_profile_name = self.profile_combo.currentText()
            self.is_switching_profile = False
            self.settings.setValue("profiles_json", json.dumps(self.profiles_data))

    def move_profile_down(self):
        idx = self.profile_combo.currentIndex()
        keys = list(self.profiles_data.keys())
        if idx < len(keys) - 1:
            keys[idx + 1], keys[idx] = keys[idx], keys[idx + 1]
            self.profiles_data = {k: self.profiles_data[k] for k in keys}
            
            self.is_switching_profile = True
            self.profile_combo.clear()
            self.profile_combo.addItems(keys)
            self.profile_combo.setCurrentIndex(idx + 1)
            self.current_profile_name = self.profile_combo.currentText()
            self.is_switching_profile = False
            self.settings.setValue("profiles_json", json.dumps(self.profiles_data))

    # ================= 操作录制逻辑 =================
    def start_recording(self):
        self.showMinimized()
        self.recorder_ui = RecorderUI(self)

    # ================= UI基础交互 =================
    def bind_setting_logs(self):
        self.conf_edit.editingFinished.connect(lambda: self.log_setting_change("相似度", self.conf_edit.text()))
        self.scale_min.editingFinished.connect(lambda: self.log_setting_change("最小缩放", self.scale_min.text()))
        self.scale_max.editingFinished.connect(lambda: self.log_setting_change("最大缩放", self.scale_max.text()))
        self.dodge_x1.editingFinished.connect(lambda: self.log_setting_change("避让坐标1 X", self.dodge_x1.text()))
        self.dodge_y1.editingFinished.connect(lambda: self.log_setting_change("避让坐标1 Y", self.dodge_y1.text()))
        self.dodge_x2.editingFinished.connect(lambda: self.log_setting_change("避让坐标2 X", self.dodge_x2.text()))
        self.dodge_y2.editingFinished.connect(lambda: self.log_setting_change("避让坐标2 Y", self.dodge_y2.text()))
        self.dbl_wait.editingFinished.connect(lambda: self.log_setting_change("二段避让间隔(s)", self.dbl_wait.text()))
        self.move_spd.editingFinished.connect(lambda: self.log_setting_change("移动耗时(s)", self.move_spd.text()))
        self.click_hld.editingFinished.connect(lambda: self.log_setting_change("按住时长(s)", self.click_hld.text()))
        self.settle.editingFinished.connect(lambda: self.log_setting_change("结算缓冲(s)", self.settle.text()))
        self.timeout.editingFinished.connect(lambda: self.log_setting_change("单步超时(s)", self.timeout.text()))
        self.detect_delay.editingFinished.connect(lambda: self.log_setting_change("检测频率(s)", self.detect_delay.text()))
        self.playback_speed.editingFinished.connect(lambda: self.log_setting_change("倍速执行", self.playback_speed.text()))
        self.loop_val_edit.editingFinished.connect(lambda: self.log_setting_change("循环参数", self.loop_val_edit.text()))

        self.dodge_chk.stateChanged.connect(lambda s: self.log_setting_change("启用避让", "开启" if s else "关闭"))
        self.double_dodge_chk.stateChanged.connect(lambda s: self.log_setting_change("二段避让", "开启" if s else "关闭"))
        self.tm_failsafe.stateChanged.connect(lambda s: self.log_setting_change("任务管理器急停", "开启" if s else "关闭"))
        self.tr_failsafe.stateChanged.connect(lambda s: self.log_setting_change("右上角急停", "开启" if s else "关闭"))
        self.key_failsafe.stateChanged.connect(lambda s: self.log_setting_change("ESC/中键急停", "开启" if s else "关闭"))
        self.log_file_chk.stateChanged.connect(lambda s: self.log_setting_change("写入文件日志", "开启" if s else "关闭"))
        self.log_ui_chk.stateChanged.connect(lambda s: self.log_setting_change("显示界面日志", "开启" if s else "关闭"))
        self.mini_chk.stateChanged.connect(lambda s: self.log_setting_change("启动时最小化", "开启" if s else "关闭"))
        self.top_chk.stateChanged.connect(lambda s: self.log_setting_change("窗口置顶", "开启" if s else "关闭"))

        self.hotkey_start_combo.currentTextChanged.connect(lambda t: self.log_setting_change("启动热键", t))
        self.hotkey_stop_combo.currentTextChanged.connect(lambda t: self.log_setting_change("停止热键", t))
        self.log_level_combo.currentTextChanged.connect(lambda t: self.log_setting_change("日志级别", t))
        self.loop_combo.currentTextChanged.connect(lambda t: self.log_setting_change("循环模式", t))

    def log_setting_change(self, name, value):
        if GLOBAL_CONFIG["log_to_ui"] and not self.is_switching_profile:
            self.append_log(f"<font color='#FF9800'><b>设置已生效：</b>{name} -> {value}</font>")

    def update_loop_ui(self, text):
        if text in ["指定次数", "指定时间(时)", "指定时间(分)", "指定时间(秒)"]:
            self.loop_val_edit.show()
        else:
            self.loop_val_edit.hide()

    def update_hotkeys(self, _=None):
        try:
            start_txt = self.hotkey_start_combo.currentText()
            stop_txt = self.hotkey_stop_combo.currentText()
            
            self.hotkey_start_vk = 0x70 + (int(start_txt.replace("F", "")) - 1)
            self.hotkey_stop_vk = 0x70 + (int(stop_txt.replace("F", "")) - 1)
            
            self.start_btn.setText(f"启动 ({start_txt})")
            self.stop_btn.setText(f"停止 ({stop_txt})")
        except: pass

    def toggle_top_window(self):
        if self.top_chk.isChecked(): self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else: self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()

    def check_hotkey(self):
        start_pressed = GetAsyncKeyState(self.hotkey_start_vk) & 0x8000
        stop_pressed = GetAsyncKeyState(self.hotkey_stop_vk) & 0x8000
        
        if start_pressed and not self.engine.is_running:
            self.start_task()
            self.hotkey_timer.stop()
            QTimer.singleShot(500, lambda: self.hotkey_timer.start(100))
            return
            
        if stop_pressed and self.engine.is_running:
            self.stop_task()
            self.hotkey_timer.stop()
            QTimer.singleShot(500, lambda: self.hotkey_timer.start(100))
            return

    def open_region_selector(self):
        self.region_win = RegionWindow()
        self.region_win.region_selected.connect(self.on_region_selected)

    def on_region_selected(self, rect_tuple):
        self.engine.scan_region = rect_tuple
        self.region_label.setText(f"范围(物理): {rect_tuple}")
        self.append_log(f"已锁定游戏区域(物理): {rect_tuple} (速度+++)")

    def closeEvent(self, event):
        self.settings.setValue("window_geometry", self.saveGeometry())
        
        self.profiles_data[self.current_profile_name] = self.get_current_ui_config()
        self.settings.setValue("profiles_json", json.dumps(self.profiles_data))
        self.settings.setValue("current_profile", self.current_profile_name)
        event.accept()

    def update_log_config(self):
        GLOBAL_CONFIG["log_to_file"] = self.log_file_chk.isChecked()
        GLOBAL_CONFIG["log_to_ui"] = self.log_ui_chk.isChecked()

    def update_cpu_info(self):
        core_str = "?"
        if HAS_KERNEL_CPU:
            try: core_str = str(GetCurrentProcessorNumber())
            except: pass
        sys_usage = "--"
        proc_usage = "--"
        if HAS_PSUTIL and self.current_process:
            try:
                sys_usage = f"{psutil.cpu_percent(interval=None):.1f}"
                raw_usage = self.current_process.cpu_percent(interval=None)
                proc_usage = f"{raw_usage:.1f}" 
            except: pass
        self.cpu_label.setText(f"逻辑核心: #{core_str} | 系统总占: {sys_usage}% | 脚本单核占: {proc_usage}%")

    def update_indexes(self):
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            widget = self.task_list.itemWidget(item)
            if widget and hasattr(widget, 'set_index'):
                widget.set_index(i + 1)

    def add_row(self, data=None):
        row_widget = TaskRow(delete_callback=self.del_row)
        if data: row_widget.set_data(data)
        item = QListWidgetItem(self.task_list)
        item.setSizeHint(row_widget.sizeHint())
        self.task_list.setItemWidget(item, row_widget)
        row_widget.set_parent_item(item)
        item.setData(Qt.UserRole, row_widget.get_data())
        self.update_indexes()

    def del_row(self, row_widget):
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if self.task_list.itemWidget(item) == row_widget:
                self.task_list.takeItem(i)
                break
        self.update_indexes()

    def save(self):
        data = self.get_current_ui_config()
        path, _ = QFileDialog.getSaveFileName(self, "导出方案", filter="JSON (*.json)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f: 
                    json.dump(data, f, ensure_ascii=False, indent=2)
                if GLOBAL_CONFIG["log_to_ui"]:
                    self.append_log(f"<font color='green'><b>>>> 方案已成功导出至: {path}</b></font>")
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入方案", filter="JSON (*.json)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                base_name = os.path.splitext(os.path.basename(path))[0]
                new_name = base_name
                counter = 1
                while new_name in self.profiles_data:
                    new_name = f"{base_name}_{counter}"
                    counter += 1
                    
                if isinstance(data, list):
                    new_profile_data = self.get_default_config_dict()
                    new_profile_data["tasks"] = data
                elif isinstance(data, dict):
                    new_profile_data = data
                else:
                    raise ValueError("无法识别的配置文件格式")

                self.profiles_data[self.current_profile_name] = self.get_current_ui_config()

                self.profiles_data[new_name] = new_profile_data
                
                self.is_switching_profile = True
                self.profile_combo.addItem(new_name)
                self.profile_combo.setCurrentText(new_name)
                self.current_profile_name = new_name
                self.apply_ui_config(new_profile_data)
                self.is_switching_profile = False
                
                if GLOBAL_CONFIG["log_to_ui"]:
                    self.append_log(f"<font color='green'><b>>>> 成功导入并创建新方案: {new_name}</b></font>")
            except Exception as e:
                QMessageBox.warning(self, "导入失败", str(e))

    def validate_tasks(self, tasks):
        """核心修复：引擎执行前全栈语法校验，防止瞎填参数导致异常"""
        for i, task in enumerate(tasks):
            t = task.get("type")
            v = str(task.get("value", "")).strip()
            
            if not v and t not in [9.0]: 
                return f"第 {i+1} 步参数不能为空！"
            
            if t in [1.0, 2.0, 3.0, 8.0]: 
                if not self.engine.parse_coordinate(v):
                    if not os.path.exists(v):
                        return f"第 {i+1} 步找图错误：图片路径不存在或坐标格式错误 (坐标应为 x,y)\n填入内容: {v}"
            elif t in [10.0, 11.0]: 
                if '->' not in v:
                    return f"第 {i+1} 步拖拽参数错误，需包含 '->' 符号，例如: 100,100 -> 200,200"
                parts = v.split('->')
                if not self.engine.parse_coordinate(parts[0]) or not self.engine.parse_coordinate(parts[1]):
                    return f"第 {i+1} 步拖拽坐标格式异常，无法解析出首尾坐标！"
            elif t in [5.0, 6.0]:
                try: float(v)
                except: return f"第 {i+1} 步参数必须是纯数字！"
        return None

    # ================= 引擎调度 =================
    def start_task(self):
        cfg = self.get_current_ui_config()
        tasks = cfg.get("tasks", [])
        if not tasks: return
        
        # 启动前执行强语法校验装甲
        err_msg = self.validate_tasks(tasks)
        if err_msg:
            QMessageBox.critical(self, "指令语法错误", err_msg)
            return
            
        try:
            self.engine.min_scale = float(cfg["scale_min"])
            self.engine.max_scale = float(cfg["scale_max"])
            self.engine.dodge_x1 = int(cfg["dodge_x1"])
            self.engine.dodge_y1 = int(cfg["dodge_y1"])
            self.engine.dodge_x2 = int(cfg["dodge_x2"])
            self.engine.dodge_y2 = int(cfg["dodge_y2"])
            self.engine.move_duration = float(cfg["move_spd"])
            self.engine.click_hld = float(cfg["click_hld"])
            self.engine.settlement_wait = float(cfg["settle"])
            self.engine.timeout_val = float(cfg["timeout"])
            self.engine.confidence = float(cfg["conf"])
            self.engine.detect_delay = float(cfg["detect_delay"]) 
            self.engine.playback_speed = float(cfg.get("playback_speed", "1.0"))
            
            self.engine.log_level = cfg["log_level"]
            self.engine.loop_mode = cfg["loop_mode"]
            try: self.engine.loop_val = float(cfg["loop_val"])
            except: self.engine.loop_val = 1.0
            
            self.engine.enable_dodge = cfg["dodge_en"]
            self.engine.enable_double_dodge = cfg["dbl_dodge"]
            self.engine.double_dodge_wait = float(cfg["dbl_wait"])
            
            self.engine.enable_tm_stop = cfg["tm_fs"]
            self.engine.enable_tr_stop = cfg["tr_fs"]
            self.engine.enable_key_stop = cfg["key_fs"]
        except: return QMessageBox.warning(self, "错误", "数值格式错误")

        if GLOBAL_CONFIG["log_to_ui"]:
            start_key = cfg["hotkey_start"]
            stop_key = cfg["hotkey_stop"]
            self.append_log(f"<hr><b><font color='blue'>>>> 引擎启动 ({start_key}启动 / {stop_key}停止) - 方案: {self.current_profile_name} - 日志: {self.log_level_combo.currentText()} - 循环: {self.loop_combo.currentText()}</font></b>")
            
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        if self.mini_chk.isChecked(): self.showMinimized()
        
        self.worker = WorkerThread(self.engine, tasks)
        self.worker.log_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_finish)
        self.worker.start()

    def stop_task(self):
        self.engine.stop()
        
    def on_finish(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.showNormal()
        self.activateWindow()
        if GLOBAL_CONFIG["log_to_ui"]:
            self.append_log("<b><font color='blue'>引擎运行结束</font></b>")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = RPAWindow()
    win.show()
    sys.exit(app.exec())
