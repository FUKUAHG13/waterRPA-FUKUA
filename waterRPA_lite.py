import sys
import os
import time
import json
import random
import subprocess
import traceback
import ctypes
import threading
import queue
import hashlib
import webbrowser
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
                               QListWidget, QListWidgetItem, QAbstractItemView, QInputDialog, QSplitter,
                               QDialog, QDialogButtonBox, QFormLayout)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QRect, QSettings, QPoint
from PySide6.QtGui import QCursor, QFont, QColor, QPalette, QBrush, QPen, QPainter, QRegion, QDrag, QPixmap
import pyperclip
from PIL import Image
import pyautogui

SLIM_BUILD = True

try:
    import mss
    HAS_MSS = True
except ImportError:
    mss = None
    HAS_MSS = False

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
VK_MAP.update({
    0xBA: ';', 0xBB: '=', 0xBC: ',', 0xBD: '-', 0xBE: '.', 0xBF: '/', 0xC0: '`',
    0xDB: '[', 0xDC: '\\', 0xDD: ']', 0xDE: '\''
})

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
except:
    pass

HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
HOTKEY_ID_START = 0x5741
HOTKEY_ID_STOP = 0x5742

try:
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
except:
    pass

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
# 全局配置与异步日志系统
# ---------------------------------------------------------
GLOBAL_CONFIG = {"log_to_file": False, "log_to_ui": True}

def get_base_dir():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.dirname(os.path.abspath(__file__))

def config_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "启用", "是")
    return bool(value)

def parse_coordinate_text(val):
    try:
        val_str = str(val).strip()
        if ',' in val_str:
            parts = val_str.split(',')
            if len(parts) == 2:
                return int(parts[0].strip()), int(parts[1].strip())
    except:
        pass
    return None

def parse_float_text(value, default=0.0):
    try:
        return float(str(value).strip())
    except:
        return default

def parse_coord_step_manual_points(value):
    try:
        if isinstance(value, dict):
            raw = value
        else:
            text = str(value or "").strip()
            if not text:
                return {}
            raw = json.loads(text)
        points = {}
        for key, coord in raw.items():
            idx = int(key)
            if idx <= 0:
                continue
            if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                points[idx] = (float(coord[0]), float(coord[1]))
        return points
    except:
        return {}

def serialize_coord_step_manual_points(points):
    normalized = {}
    for idx, coord in (points or {}).items():
        try:
            idx = int(idx)
            if idx <= 0:
                continue
            x, y = coord
            normalized[str(idx)] = [int(round(float(x))), int(round(float(y)))]
        except:
            continue
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)

def coord_step_delta_values(direction, distance, dx, dy):
    direction = str(direction)
    if direction in ("\u5411\u4e0a", "鍚戜笂"):
        return 0.0, -distance
    if direction in ("\u5411\u4e0b", "鍚戜笅"):
        return 0.0, distance
    if direction in ("\u5411\u5de6", "鍚戝乏"):
        return -distance, 0.0
    if direction in ("\u5411\u53f3", "鍚戝彸"):
        return distance, 0.0
    if direction == "\u81ea\u5b9a\u4e49\u504f\u79fb" or direction.startswith("鑷"):
        return dx, dy
    return 0.0, 0.0

def build_coord_step_positions(base_x, base_y, options, max_points=200):
    base_x = float(base_x)
    base_y = float(base_y)
    direction = str(options.get("direction", "向下"))
    max_steps = max(0, int(parse_float_text(options.get("max_steps", 0), 0.0)))
    max_distance = max(0.0, parse_float_text(options.get("max_distance", 0), 0.0))
    positions = [(base_x, base_y)]

    if direction == "\u79fb\u52a8\u5230\u65b0\u70b9\u4f4d" or direction.startswith("绉诲姩"):
        point = parse_coordinate_text(options.get("point", ""))
        if not point:
            return positions
        target_x, target_y = float(point[0]), float(point[1])
        total_points = max_steps if max_steps >= 2 else 2
        for idx in range(1, min(total_points, max_points)):
            ratio = idx / (total_points - 1)
            x = base_x + (target_x - base_x) * ratio
            y = base_y + (target_y - base_y) * ratio
            distance_from_base = ((x - base_x) ** 2 + (y - base_y) ** 2) ** 0.5
            if max_distance > 0 and distance_from_base > max_distance:
                break
            positions.append((x, y))
        manual_points = parse_coord_step_manual_points(options.get("manual_points", options.get("coord_step_manual_points", {})))
        for idx, manual_point in manual_points.items():
            if 0 < idx < len(positions):
                positions[idx] = manual_point
        return positions

    distance = parse_float_text(options.get("distance", 0), 0.0)
    dx = parse_float_text(options.get("dx", 0), 0.0)
    dy = parse_float_text(options.get("dy", 0), 0.0)
    step_dx, step_dy = coord_step_delta_values(direction, distance, dx, dy)
    if step_dx == 0 and step_dy == 0:
        return positions

    move_count = max_steps if max_steps > 0 else min(10, max_points - 1)
    for idx in range(1, min(move_count + 1, max_points)):
        x = base_x + step_dx * idx
        y = base_y + step_dy * idx
        distance_from_base = ((x - base_x) ** 2 + (y - base_y) ** 2) ** 0.5
        if max_distance > 0 and distance_from_base > max_distance:
            break
        positions.append((x, y))
    return positions

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
        except: pass

log_thread = threading.Thread(target=log_worker_thread, daemon=True)
log_thread.start()

def write_log(msg, callback=None):
    LOG_QUEUE.put((msg, callback))

class NativeRect(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("w", ctypes.c_int),
        ("h", ctypes.c_int),
    ]

class NativeMatch(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("scale", ctypes.c_double),
        ("score", ctypes.c_double),
        ("radius", ctypes.c_double),
    ]

class NativeVisionCore:
    def __init__(self):
        self.dll = None
        self.available = False
        self.load_error = ""
        self.version = 0
        self._load()

    def _candidate_paths(self):
        names = ["water_rpa_core.dll"]
        bases = [get_base_dir()]
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            bases.append(sys._MEIPASS)
        bases.append(os.path.join(get_base_dir(), "native_core"))
        for base in bases:
            for name in names:
                yield os.path.join(base, name)

    def _load(self):
        last_error = ""
        for dll_path in self._candidate_paths():
            if not os.path.exists(dll_path):
                continue
            try:
                dll = ctypes.CDLL(dll_path)
                dll.wrpa_version.argtypes = []
                dll.wrpa_version.restype = ctypes.c_int
                dll.wrpa_find_template.argtypes = [
                    ctypes.POINTER(ctypes.c_wchar),
                    ctypes.POINTER(NativeRect),
                    ctypes.c_int,
                    ctypes.c_double,
                    ctypes.c_double,
                    ctypes.c_double,
                    ctypes.c_int,
                    ctypes.c_double,
                    ctypes.c_int,
                    ctypes.POINTER(NativeMatch),
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.c_wchar_p,
                    ctypes.c_int,
                ]
                dll.wrpa_find_template.restype = ctypes.c_int
                self.version = int(dll.wrpa_version())
                self.dll = dll
                self.available = True
                self.load_error = ""
                return
            except Exception as e:
                last_error = f"{dll_path}: {e}"
        self.load_error = last_error or "water_rpa_core.dll not found"

    def find_template(self, image_path, regions, min_scale, max_scale, scale_step, use_gray, threshold, find_all=False, max_matches=512):
        if not self.available or not self.dll:
            return None
        try:
            clean_regions = []
            for region in regions or []:
                x, y, w, h = [int(float(v)) for v in region]
                if w > 0 and h > 0:
                    clean_regions.append((x, y, w, h))
            rect_array = None
            rect_ptr = None
            if clean_regions:
                rect_array = (NativeRect * len(clean_regions))()
                for idx, (x, y, w, h) in enumerate(clean_regions):
                    rect_array[idx] = NativeRect(x, y, w, h)
                rect_ptr = rect_array

            max_matches = max(1, min(int(max_matches), 4096))
            out_array = (NativeMatch * max_matches)()
            out_count = ctypes.c_int(0)
            err_buf = ctypes.create_unicode_buffer(512)
            rc = self.dll.wrpa_find_template(
                os.path.abspath(str(image_path)),
                rect_ptr,
                len(clean_regions),
                float(min_scale),
                float(max_scale),
                float(scale_step),
                1 if use_gray else 0,
                float(threshold),
                1 if find_all else 0,
                out_array,
                max_matches,
                ctypes.byref(out_count),
                err_buf,
                len(err_buf),
            )
            if rc < 0:
                self.load_error = err_buf.value or f"native rc {rc}"
                return None
            result = []
            for idx in range(max(0, min(out_count.value, max_matches))):
                item = out_array[idx]
                result.append((float(item.x), float(item.y), float(item.scale), float(item.score), float(item.radius)))
            return result
        except Exception as e:
            self.load_error = str(e)
            return None

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
# UI组件: 折叠面板与独立配置弹窗
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

class ImageClickPointWidget(QWidget):
    point_changed = Signal(float, float)

    def __init__(self, pixmap, rx=0.5, ry=0.5, scale=2.0, selectable=True):
        super().__init__()
        self.pixmap = pixmap
        self.rx = max(0.0, min(1.0, float(rx)))
        self.ry = max(0.0, min(1.0, float(ry)))
        self.selectable = selectable
        self.display_scale = max(0.2, float(scale))
        self.setFixedSize(
            max(1, int(self.pixmap.width() * self.display_scale)),
            max(1, int(self.pixmap.height() * self.display_scale))
        )
        self.setCursor(Qt.CrossCursor if selectable else Qt.ArrowCursor)

    def set_point(self, rx, ry):
        self.rx = max(0.0, min(1.0, float(rx)))
        self.ry = max(0.0, min(1.0, float(ry)))
        self.point_changed.emit(self.rx, self.ry)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self.rect(), self.pixmap)

        px = int(self.rx * self.width())
        py = int(self.ry * self.height())
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(0, 0, 0, 210), 5, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(px - 18, py, px + 18, py)
        painter.drawLine(px, py - 18, px, py + 18)
        painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(px - 18, py, px + 18, py)
        painter.drawLine(px, py - 18, px, py + 18)
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawEllipse(QPoint(px, py), 5, 5)

    def mousePressEvent(self, event):
        if self.selectable and event.button() == Qt.LeftButton:
            pos = event.position() if hasattr(event, "position") else event.pos()
            self.set_point(pos.x() / max(1, self.width()), pos.y() / max(1, self.height()))
            event.accept()
            return
        super().mousePressEvent(event)

class ImageClickPointDialog(QDialog):
    def __init__(self, image_path, rx=0.5, ry=0.5, selectable=True, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.selectable = selectable
        self.pixmap = QPixmap(image_path)
        if self.pixmap.isNull():
            raise ValueError("图片无法打开或格式不受支持")

        self.setWindowTitle("选择图片内点击位置" if selectable else "预览图片内点击位置")
        self.setMinimumSize(520, 420)
        layout = QVBoxLayout(self)

        hint = "左键点击放大图片中的目标位置；保存的是相对位置，缩放识别后仍会点同一处。"
        if not selectable:
            hint = "红色十字即当前将点击的图片内相对位置。"
        hint_label = QLabel(hint)
        hint_label.setStyleSheet("color: #555;")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        screen_rect = QApplication.primaryScreen().availableGeometry()
        max_w = max(360, int(screen_rect.width() * 0.78))
        max_h = max(280, int(screen_rect.height() * 0.68))
        fit_scale = min(max_w / max(1, self.pixmap.width()), max_h / max(1, self.pixmap.height()))
        longest = max(self.pixmap.width(), self.pixmap.height())
        if longest <= 120:
            preferred_scale = 6.0
        elif longest <= 300:
            preferred_scale = 4.0
        elif longest <= 700:
            preferred_scale = 2.0
        else:
            preferred_scale = 1.0
        display_scale = max(0.2, min(preferred_scale, fit_scale))

        self.image_widget = ImageClickPointWidget(self.pixmap, rx, ry, display_scale, selectable)
        self.image_widget.point_changed.connect(self.update_info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setWidget(self.image_widget)
        layout.addWidget(scroll, 1)

        self.info_label = QLabel()
        self.info_label.setStyleSheet("color: #333; font-weight: bold;")
        layout.addWidget(self.info_label)
        self.update_info(self.image_widget.rx, self.image_widget.ry)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel) if selectable else QDialogButtonBox(QDialogButtonBox.Close)
        if selectable:
            buttons.button(QDialogButtonBox.Ok).setText("使用此位置")
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
        else:
            buttons.rejected.connect(self.reject)
            buttons.button(QDialogButtonBox.Close).clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(
            min(max_w + 40, self.image_widget.width() + 60),
            min(max_h + 120, self.image_widget.height() + 150)
        )

    def update_info(self, rx, ry):
        img_x = int(round(rx * self.pixmap.width()))
        img_y = int(round(ry * self.pixmap.height()))
        self.info_label.setText(
            f"当前相对位置：X {rx:.3f} / Y {ry:.3f}；原图像素约 ({img_x}, {img_y})"
        )

    def selected_ratio(self):
        return self.image_widget.rx, self.image_widget.ry

class TaskConfigDialog(QDialog):
    def __init__(self, parent, data, image_settings_available=True, point_limit_available=False, coordinate_step_available=False, base_coordinate=None, image_path="", image_click_point_available=False, base_coordinate_changed=None):
        super().__init__(None)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowModality(Qt.NonModal)
        self.image_settings_available = image_settings_available and not SLIM_BUILD
        self.point_limit_available = point_limit_available
        self.coordinate_step_available = coordinate_step_available
        self.base_coordinate = base_coordinate
        self.image_path = image_path
        self.image_click_point_available = image_click_point_available
        self.base_coordinate_changed = base_coordinate_changed
        self.coord_step_picker = None
        self.coord_step_preview = None
        self.coord_step_manual_points = parse_coord_step_manual_points(data.get("coord_step_manual_points", "{}"))
        self.coord_step_max_steps_initial = str(data.get("coord_step_max_steps", "0"))
        self.coord_step_clearing_due_to_count = False
        self.dialog_settings = QSettings(os.path.join(get_base_dir(), "config.ini"), QSettings.IniFormat)
        self.setWindowTitle("步骤设置")
        self.setMinimumSize(720, 560)
        layout = QVBoxLayout(self)
        
        note = QLabel("图片识别设置仅对图片点击/图片悬停生效；直接输入坐标时会自动忽略这些参数。")
        note.setStyleSheet("color: #666;")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.enable_chk = QCheckBox("✓ 为当前图片指令启用独立识别参数")
        self.enable_chk.setChecked(data.get("custom_en", False))
        self.enable_chk.setStyleSheet("font-weight: bold; color: #E91E63;")
        layout.addWidget(self.enable_chk)
        
        self.form_widget = QWidget()
        form = QFormLayout(self.form_widget)
        form.setContentsMargins(0, 10, 0, 10)
        
        self.conf_edit = QLineEdit(str(data.get("custom_conf", "0.8")))
        self.s_min_edit = QLineEdit(str(data.get("custom_scale_min", "1.0")))
        self.s_max_edit = QLineEdit(str(data.get("custom_scale_max", "1.0")))
        self.s_step_edit = QLineEdit(str(data.get("custom_scale_step", "0.05")))
        self.gray_chk = QCheckBox("灰度匹配 (取消则严格区分颜色)")
        self.gray_chk.setChecked(data.get("custom_gray", True))
        
        form.addRow("目标相似度:", self.conf_edit)
        form.addRow("最小缩放倍率:", self.s_min_edit)
        form.addRow("最大缩放倍率:", self.s_max_edit)
        form.addRow("缩放步长:", self.s_step_edit)
        form.addRow("色彩模式:", self.gray_chk)
        
        layout.addWidget(self.form_widget)
        self.enable_chk.setEnabled(self.image_settings_available)
        self.form_widget.setEnabled(self.image_settings_available and self.enable_chk.isChecked())
        self.enable_chk.toggled.connect(self.update_image_settings_enabled)

        if not self.image_settings_available:
            disabled_text = "精简版已移除独立识别参数；图片步骤会按原图原尺寸精确匹配。" if SLIM_BUILD else "当前步骤不是图片识别模式，以上图片识别参数不会参与执行。"
            disabled_note = QLabel(disabled_text)
            disabled_note.setStyleSheet("color: #999;")
            disabled_note.setWordWrap(True)
            layout.addWidget(disabled_note)

        control_box = QGroupBox("执行控制 / 条件分支")
        control_form = QFormLayout(control_box)

        self.repeat_combo = QComboBox()
        self.repeat_combo.addItems(["执行一次", "指定次数", "无限重复"])
        self.repeat_combo.setCurrentText(str(data.get("repeat_mode", "执行一次")))
        self.repeat_combo.currentTextChanged.connect(self.update_repeat_ui)

        self.repeat_count_edit = QLineEdit(str(data.get("repeat_count", "1")))
        self.repeat_count_edit.setFixedWidth(90)

        self.step_loop_start_edit = QLineEdit(str(data.get("step_loop_start", "1")))
        self.step_loop_start_edit.setFixedWidth(70)
        self.step_loop_start_edit.setToolTip("本步骤从第几次脚本循环开始执行；默认 1 表示从第一轮就生效。")
        self.step_loop_end_edit = QLineEdit(str(data.get("step_loop_end", "0")))
        self.step_loop_end_edit.setFixedWidth(70)
        self.step_loop_end_edit.setToolTip("本步骤执行到第几次脚本循环后不再执行；填 0 表示不限。填 5 表示第 1-5 轮执行，第 6 轮开始跳过。")

        step_loop_row = QWidget()
        step_loop_layout = QHBoxLayout(step_loop_row)
        step_loop_layout.setContentsMargins(0, 0, 0, 0)
        step_loop_layout.addWidget(QLabel("从第"))
        step_loop_layout.addWidget(self.step_loop_start_edit)
        step_loop_layout.addWidget(QLabel("次循环开始"))
        step_loop_layout.addSpacing(10)
        step_loop_layout.addWidget(QLabel("到第"))
        step_loop_layout.addWidget(self.step_loop_end_edit)
        step_loop_layout.addWidget(QLabel("次循环后停止"))
        step_loop_layout.addWidget(HelpBtn("【本步骤循环范围】\n控制当前步骤在脚本第几轮循环中生效。\n起始循环默认 1；停止循环填 0 表示不限。\n被范围跳过时不会触发成功/失败跳转，只会继续执行下一步。"))
        step_loop_layout.addStretch()

        self.point_limit_chk = QCheckBox("图片点击同一点位达到上限后忽略此点位")
        self.point_limit_chk.setChecked(config_bool(data.get("point_limit_en", False)) and self.point_limit_available)
        self.point_limit_chk.setEnabled(self.point_limit_available)
        self.point_limit_chk.setToolTip("仅对图片点击生效。填坐标时自动忽略；达到上限后会尝试点击下一个匹配点位。")
        self.point_limit_chk.toggled.connect(self.update_point_limit_ui)

        self.point_limit_count_edit = QLineEdit(str(data.get("point_limit_count", "0")))
        self.point_limit_count_edit.setFixedWidth(90)
        self.point_limit_count_edit.setToolTip("填 0 表示不限制；例如填 1 表示同一个识别点位只点击一次。")

        self.image_click_point_chk = QCheckBox("命中图片后点击图片内指定位置")
        self.image_click_point_chk.setMinimumWidth(245)
        self.image_click_point_chk.setChecked(config_bool(data.get("image_click_point_en", False)) and self.image_click_point_available)
        self.image_click_point_chk.setEnabled(self.image_click_point_available)
        self.image_click_point_chk.setToolTip("仅对图片路径的左键单击、左键双击、右键单击生效；直接坐标点击会自动忽略。")
        self.image_click_point_chk.toggled.connect(self.update_image_click_point_ui)
        self.image_click_point_rx = str(data.get("image_click_point_rx", "0.5"))
        self.image_click_point_ry = str(data.get("image_click_point_ry", "0.5"))

        image_point_row = QWidget()
        image_point_layout = QHBoxLayout(image_point_row)
        image_point_layout.setContentsMargins(0, 0, 0, 0)
        image_point_layout.addWidget(self.image_click_point_chk)
        self.image_click_point_select_btn = QPushButton("选择")
        self.image_click_point_select_btn.setFixedWidth(54)
        self.image_click_point_select_btn.setToolTip("打开放大的模板图片，左键点击要实际点击的位置。")
        self.image_click_point_select_btn.clicked.connect(self.select_image_click_point)
        image_point_layout.addWidget(self.image_click_point_select_btn)
        self.image_click_point_preview_btn = QPushButton("预览")
        self.image_click_point_preview_btn.setFixedWidth(54)
        self.image_click_point_preview_btn.setToolTip("预览当前保存的图片内点击位置。")
        self.image_click_point_preview_btn.clicked.connect(self.preview_image_click_point)
        image_point_layout.addWidget(self.image_click_point_preview_btn)
        self.image_click_point_info = QLabel("")
        self.image_click_point_info.setStyleSheet("color: #666;")
        image_point_layout.addWidget(self.image_click_point_info)
        image_point_layout.addStretch()

        self.coord_step_chk = QCheckBox("坐标点击启用步进偏移")
        self.coord_step_chk.setChecked(config_bool(data.get("coord_step_en", False)) and self.coordinate_step_available)
        self.coord_step_chk.setEnabled(self.coordinate_step_available)
        self.coord_step_chk.setToolTip("仅对直接输入坐标的点击步骤生效；图片识别点击会自动忽略。")
        self.coord_step_chk.toggled.connect(self.update_coord_step_ui)

        self.coord_step_every_edit = QLineEdit(str(data.get("coord_step_every", "1")))
        self.coord_step_every_edit.setFixedWidth(70)
        self.coord_step_every_edit.setToolTip("每执行本坐标点击步骤多少次后，移动到下一个点击位置。")

        self.coord_step_direction_combo = QComboBox()
        self.coord_step_direction_combo.addItems(["向上", "向下", "向左", "向右", "自定义偏移", "移动到新点位"])
        self.coord_step_direction_combo.setCurrentText(str(data.get("coord_step_direction", "向下")))
        self.coord_step_direction_combo.currentTextChanged.connect(self.update_coord_step_ui)

        self.coord_step_distance_edit = QLineEdit(str(data.get("coord_step_distance", "0")))
        self.coord_step_distance_edit.setFixedWidth(70)
        self.coord_step_dx_edit = QLineEdit(str(data.get("coord_step_dx", "0")))
        self.coord_step_dx_edit.setFixedWidth(70)
        self.coord_step_dy_edit = QLineEdit(str(data.get("coord_step_dy", "0")))
        self.coord_step_dy_edit.setFixedWidth(70)
        self.coord_step_point_edit = QLineEdit(str(data.get("coord_step_point", "")))
        self.coord_step_point_edit.setPlaceholderText("例如 960,540")

        self.coord_step_max_steps_edit = QLineEdit(str(data.get("coord_step_max_steps", "0")))
        self.coord_step_max_steps_edit.setFixedWidth(70)
        self.coord_step_max_steps_edit.setToolTip("普通方向：最多偏移多少次后不再移动，填 0 表示不限次数。移动到新点位：这里表示起点到目标点之间总共点击多少个点位，例如填 5 会点击起点、3 个中间点、目标点；填 0 表示直接从起点移动到目标点。")
        self.coord_step_max_steps_edit.textChanged.connect(self.on_coord_step_count_changed)
        self.coord_step_max_distance_edit = QLineEdit(str(data.get("coord_step_max_distance", "0")))
        self.coord_step_max_distance_edit.setFixedWidth(70)
        self.coord_step_max_distance_edit.setToolTip("累计偏移距离达到多少像素后不再移动；填 0 表示不限距离。")
        self.coord_step_stop_chk = QCheckBox("达到移动上限后停止脚本")
        self.coord_step_stop_chk.setChecked(config_bool(data.get("coord_step_stop", False)))
        self.coord_step_reset_after_edit = QLineEdit(str(data.get("coord_step_reset_after", "0")))
        self.coord_step_reset_after_edit.setFixedWidth(70)
        self.coord_step_reset_after_edit.setToolTip("本坐标步进成功点击多少次后自动回到起点并重新开始移动；填 0 表示不自动重置。重置触发时优先于“达到移动上限后停止脚本”。左键双击按一次本步骤点击动作计数。")

        coord_every_row = QWidget()
        coord_every_layout = QHBoxLayout(coord_every_row)
        coord_every_layout.setContentsMargins(0, 0, 0, 0)
        coord_every_layout.addWidget(self.coord_step_every_edit)
        coord_every_layout.addWidget(QLabel("次后移动"))
        coord_every_layout.addStretch()

        coord_direction_row = QWidget()
        coord_direction_layout = QHBoxLayout(coord_direction_row)
        coord_direction_layout.setContentsMargins(0, 0, 0, 0)
        coord_direction_layout.addWidget(self.coord_step_direction_combo)
        coord_direction_layout.addWidget(QLabel("距离:"))
        coord_direction_layout.addWidget(self.coord_step_distance_edit)
        coord_direction_layout.addWidget(QLabel("dx:"))
        coord_direction_layout.addWidget(self.coord_step_dx_edit)
        coord_direction_layout.addWidget(QLabel("dy:"))
        coord_direction_layout.addWidget(self.coord_step_dy_edit)
        coord_direction_layout.addStretch()

        coord_point_row = QWidget()
        coord_point_layout = QHBoxLayout(coord_point_row)
        coord_point_layout.setContentsMargins(0, 0, 0, 0)
        coord_point_layout.addWidget(self.coord_step_point_edit)
        self.coord_step_pick_btn = QPushButton("取")
        self.coord_step_pick_btn.setFixedWidth(34)
        self.coord_step_pick_btn.setToolTip("点击后直接进入取点状态，左键选取目标点位，右键取消。")
        self.coord_step_pick_btn.clicked.connect(self.start_coord_step_point_pick)
        coord_point_layout.addWidget(self.coord_step_pick_btn)
        self.coord_step_preview_btn = QPushButton("预览")
        self.coord_step_preview_btn.setFixedWidth(54)
        self.coord_step_preview_btn.setToolTip("在屏幕上临时显示本步骤会点击的点位；预览不会执行点击。")
        self.coord_step_preview_btn.clicked.connect(self.show_coord_step_preview)
        coord_point_layout.addWidget(self.coord_step_preview_btn)

        coord_limit_row = QWidget()
        coord_limit_layout = QHBoxLayout(coord_limit_row)
        coord_limit_layout.setContentsMargins(0, 0, 0, 0)
        coord_limit_layout.addWidget(QLabel("次数:"))
        coord_limit_layout.addWidget(self.coord_step_max_steps_edit)
        coord_limit_layout.addWidget(QLabel("距离:"))
        coord_limit_layout.addWidget(self.coord_step_max_distance_edit)
        coord_limit_layout.addWidget(self.coord_step_stop_chk)
        coord_limit_layout.addStretch()

        coord_reset_row = QWidget()
        coord_reset_layout = QHBoxLayout(coord_reset_row)
        coord_reset_layout.setContentsMargins(0, 0, 0, 0)
        coord_reset_layout.addWidget(self.coord_step_reset_after_edit)
        coord_reset_layout.addWidget(QLabel("次点击后回到起点"))
        coord_reset_layout.addStretch()

        coord_manual_row = QWidget()
        coord_manual_layout = QHBoxLayout(coord_manual_row)
        coord_manual_layout.setContentsMargins(0, 0, 0, 0)
        self.coord_step_manual_info = QLabel("")
        self.coord_step_manual_info.setStyleSheet("color: #7B1FA2; font-weight: bold;")
        coord_manual_layout.addWidget(self.coord_step_manual_info)
        self.coord_step_clear_manual_btn = QPushButton("清除手动修正点")
        self.coord_step_clear_manual_btn.setToolTip("清除本步骤预览中拖动中间点产生的手动修正坐标。")
        self.coord_step_clear_manual_btn.clicked.connect(self.clear_coord_step_manual_points)
        coord_manual_layout.addWidget(self.coord_step_clear_manual_btn)
        coord_manual_layout.addStretch()

        self.fail_limit_edit = QLineEdit(str(data.get("fail_limit", "1")))
        self.fail_limit_edit.setFixedWidth(90)
        self.fail_limit_edit.setToolTip("例如填 1 表示失败一次就执行下一步；填 3 表示连续失败三次后才放弃本步。优先级低于“禁止跳过”：开启禁止跳过时，会先一直等待本步骤成功或超时。")

        self.no_skip_wait_chk = QCheckBox("禁止跳过：失败后一直等待本步骤")
        self.no_skip_wait_chk.setChecked(config_bool(data.get("no_skip_wait", False)))
        self.no_skip_wait_chk.setToolTip("开启后，本步骤执行失败不会进入下一步，会按全局“识别频率”反复等待并重试，直到成功或达到单步超时。")

        self.success_skip_edit = QLineEdit(str(data.get("success_skip", "0")))
        self.success_skip_edit.setFixedWidth(90)
        self.success_skip_edit.setToolTip("本步骤成功后跳过后续 N 步。填 0 表示不跳过。")

        self.success_jump_edit = QLineEdit(str(data.get("success_jump", "0")))
        self.success_jump_edit.setFixedWidth(90)
        self.success_jump_edit.setToolTip("本步骤成功后跳至指定步号继续执行。填 0 表示关闭；步号从 1 开始。")

        self.fail_skip_edit = QLineEdit(str(data.get("fail_skip", "0")))
        self.fail_skip_edit.setFixedWidth(90)
        self.fail_skip_edit.setToolTip("达到连续失败次数后，跳过后续 N 步。填 0 表示直接执行下一步。")

        self.fail_jump_edit = QLineEdit(str(data.get("fail_jump", "0")))
        self.fail_jump_edit.setFixedWidth(90)
        self.fail_jump_edit.setToolTip("达到连续失败次数后跳至指定步号继续执行。填 0 表示关闭；步号从 1 开始。")

        control_form.addRow("本步骤重复:", self.repeat_combo)
        control_form.addRow("重复次数:", self.repeat_count_edit)
        control_form.addRow("循环范围:", step_loop_row)
        control_form.addRow("同点点击上限:", self.point_limit_chk)
        control_form.addRow("上限次数:", self.point_limit_count_edit)
        control_form.addRow("图片内点击点:", image_point_row)
        control_form.addRow("坐标步进:", self.coord_step_chk)
        control_form.addRow("步进频率:", coord_every_row)
        control_form.addRow("步进方向:", coord_direction_row)
        control_form.addRow("目标点位:", coord_point_row)
        control_form.addRow("移动上限:", coord_limit_row)
        control_form.addRow("重置循环:", coord_reset_row)
        control_form.addRow("手动修正:", coord_manual_row)
        control_form.addRow("连续失败次数:", self.fail_limit_edit)
        control_form.addRow("禁止跳过:", self.no_skip_wait_chk)
        control_form.addRow("成功后跳过:", self.success_skip_edit)
        control_form.addRow("成功后跳至:", self.success_jump_edit)
        control_form.addRow("失败后跳过:", self.fail_skip_edit)
        control_form.addRow("失败后跳至:", self.fail_jump_edit)

        control_note = QLabel("跳至填 0 表示关闭；同一结果里“跳至”优先于“跳过”。循环范围只控制本步骤在哪些脚本循环轮次生效，被范围跳过不会触发成功/失败分支。开启禁止跳过后，连续失败次数暂不生效，失败分支会等到成功或超时后再处理。移动到新点位时，“移动上限”表示起点到目标点之间的总点位数；“重置循环”可让本路径点击指定次数后回到起点。")
        control_note.setStyleSheet("color: #666;")
        control_note.setWordWrap(True)
        control_form.addRow("", control_note)
        layout.addWidget(control_box)
        self.update_repeat_ui()
        self.update_point_limit_ui()
        self.update_image_click_point_ui()
        self.update_coord_step_ui()
        self.update_coord_step_manual_ui()
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        geometry = self.dialog_settings.value("task_config_dialog_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(780, 650)

    def update_image_settings_enabled(self):
        self.form_widget.setEnabled(self.image_settings_available and self.enable_chk.isChecked())

    def update_repeat_ui(self, _=None):
        self.repeat_count_edit.setEnabled(self.repeat_combo.currentText() == "指定次数")

    def update_point_limit_ui(self, _=None):
        self.point_limit_count_edit.setEnabled(self.point_limit_available and self.point_limit_chk.isChecked())

    def update_image_click_point_ui(self, _=None):
        enabled = self.image_click_point_available
        checked = enabled and self.image_click_point_chk.isChecked()
        self.image_click_point_chk.setEnabled(enabled)
        self.image_click_point_select_btn.setEnabled(enabled)
        self.image_click_point_preview_btn.setEnabled(checked)
        if not enabled:
            self.image_click_point_info.setText("请先选择图片路径")
            return
        rx = parse_float_text(self.image_click_point_rx, 0.5)
        ry = parse_float_text(self.image_click_point_ry, 0.5)
        self.image_click_point_info.setText(f"X {rx:.3f}, Y {ry:.3f}" if checked else "默认点击图片中心")

    def select_image_click_point(self):
        if not self.image_click_point_available:
            QMessageBox.information(self, "无法选择", "当前步骤不是可用的图片点击步骤。请先选择左键/右键点击指令，并填写存在的图片路径。")
            return
        try:
            dialog = ImageClickPointDialog(
                self.image_path,
                parse_float_text(self.image_click_point_rx, 0.5),
                parse_float_text(self.image_click_point_ry, 0.5),
                selectable=True,
                parent=self
            )
        except Exception as e:
            QMessageBox.warning(self, "图片打开失败", str(e))
            return
        if dialog.exec() == QDialog.Accepted:
            rx, ry = dialog.selected_ratio()
            self.image_click_point_rx = f"{rx:.6f}"
            self.image_click_point_ry = f"{ry:.6f}"
            self.image_click_point_chk.setChecked(True)
            self.update_image_click_point_ui()

    def preview_image_click_point(self):
        if not (self.image_click_point_available and self.image_click_point_chk.isChecked()):
            return
        try:
            dialog = ImageClickPointDialog(
                self.image_path,
                parse_float_text(self.image_click_point_rx, 0.5),
                parse_float_text(self.image_click_point_ry, 0.5),
                selectable=False,
                parent=self
            )
        except Exception as e:
            QMessageBox.warning(self, "图片打开失败", str(e))
            return
        dialog.exec()

    def update_coord_step_ui(self, _=None):
        enabled = self.coordinate_step_available and self.coord_step_chk.isChecked()
        direction = self.coord_step_direction_combo.currentText()
        for widget in [
            self.coord_step_every_edit, self.coord_step_direction_combo,
            self.coord_step_distance_edit, self.coord_step_dx_edit, self.coord_step_dy_edit,
            self.coord_step_point_edit, self.coord_step_max_steps_edit,
            self.coord_step_max_distance_edit, self.coord_step_stop_chk,
            self.coord_step_reset_after_edit, self.coord_step_pick_btn, self.coord_step_preview_btn
        ]:
            widget.setEnabled(enabled)
        self.coord_step_distance_edit.setEnabled(enabled and direction in ["向上", "向下", "向左", "向右"])
        self.coord_step_dx_edit.setEnabled(enabled and direction == "自定义偏移")
        self.coord_step_dy_edit.setEnabled(enabled and direction == "自定义偏移")
        self.coord_step_point_edit.setEnabled(enabled and direction == "移动到新点位")
        self.coord_step_pick_btn.setEnabled(enabled and direction == "移动到新点位")
        self.coord_step_preview_btn.setEnabled(enabled and self.base_coordinate is not None)
        self.update_coord_step_manual_ui()

    def coord_step_manual_active(self):
        return self.coord_step_direction_combo.currentText() == "移动到新点位"

    def manual_point_indices(self):
        return sorted(int(idx) for idx in self.coord_step_manual_points.keys())

    def update_coord_step_manual_ui(self):
        active = self.coordinate_step_available and self.coord_step_chk.isChecked() and self.coord_step_manual_active()
        count = len(self.coord_step_manual_points) if active else 0
        if count:
            nums = "、".join(str(idx + 1) for idx in self.manual_point_indices())
            self.coord_step_manual_info.setText(f"已手动修正 {count} 个点：第 {nums} 个")
        else:
            self.coord_step_manual_info.setText("无手动修正点")
        self.coord_step_clear_manual_btn.setEnabled(active and count > 0)

    def current_coord_step_points(self):
        if self.base_coordinate is None:
            return []
        return build_coord_step_positions(self.base_coordinate[0], self.base_coordinate[1], self.current_coord_step_options())

    def refresh_coord_step_preview_points(self):
        preview = getattr(self, "coord_step_preview", None)
        if not preview:
            return
        points = self.current_coord_step_points()
        if points:
            preview.set_points(points)
            if hasattr(preview, "set_marked_indices"):
                preview.set_marked_indices(self.manual_point_indices())

    def clear_coord_step_manual_points(self, silent=False):
        if not self.coord_step_manual_points:
            self.update_coord_step_manual_ui()
            return
        self.coord_step_manual_points = {}
        self.update_coord_step_manual_ui()
        self.refresh_coord_step_preview_points()
        if not silent:
            QToolTip.showText(QCursor.pos(), "已清除本步骤的手动修正点", self, QRect(), 1800)

    def on_coord_step_count_changed(self, text):
        if self.coord_step_clearing_due_to_count:
            return
        if self.coord_step_manual_points and str(text) != str(self.coord_step_max_steps_initial):
            self.coord_step_clearing_due_to_count = True
            try:
                self.clear_coord_step_manual_points(silent=True)
                self.coord_step_max_steps_initial = str(text)
            finally:
                self.coord_step_clearing_due_to_count = False

    def current_coord_step_options(self):
        return {
            "every": max(1, int(parse_float_text(self.coord_step_every_edit.text(), 1))),
            "direction": self.coord_step_direction_combo.currentText(),
            "distance": parse_float_text(self.coord_step_distance_edit.text(), 0.0),
            "dx": parse_float_text(self.coord_step_dx_edit.text(), 0.0),
            "dy": parse_float_text(self.coord_step_dy_edit.text(), 0.0),
            "point": self.coord_step_point_edit.text().strip(),
            "max_steps": max(0, int(parse_float_text(self.coord_step_max_steps_edit.text(), 0.0))),
            "max_distance": max(0.0, parse_float_text(self.coord_step_max_distance_edit.text(), 0.0)),
            "reset_after": max(0, int(parse_float_text(self.coord_step_reset_after_edit.text(), 0.0))),
            "manual_points": dict(self.coord_step_manual_points) if self.coord_step_manual_active() else {}
        }

    def start_coord_step_point_pick(self):
        self.coord_step_picker = CoordinatePickerUI("point", self.on_coord_step_point_picked)

    def on_coord_step_point_picked(self, value):
        self.coord_step_point_edit.setText(value)
        self.update_coord_step_ui()

    def on_coord_step_preview_point_moved(self, index, x, y):
        direction = self.coord_step_direction_combo.currentText()
        point_count = len(getattr(self.coord_step_preview, "points", []))
        if index < 0:
            index = point_count + index
        if index == 0:
            value = f"{int(x)},{int(y)}"
            self.base_coordinate = (int(x), int(y))
            if self.base_coordinate_changed:
                self.base_coordinate_changed(value)
        elif direction == "移动到新点位" and point_count > 1 and index == point_count - 1:
            self.coord_step_point_edit.setText(f"{int(x)},{int(y)}")
        elif direction == "移动到新点位" and 0 < index < max(0, point_count - 1):
            self.coord_step_manual_points[int(index)] = (int(x), int(y))
            self.update_coord_step_manual_ui()
            if getattr(self, "coord_step_preview", None) and hasattr(self.coord_step_preview, "set_marked_indices"):
                self.coord_step_preview.set_marked_indices(self.manual_point_indices())
        options = self.current_coord_step_options()
        if self.base_coordinate is None:
            return None
        return build_coord_step_positions(self.base_coordinate[0], self.base_coordinate[1], options)

    def show_coord_step_preview(self):
        if self.base_coordinate is None:
            QMessageBox.information(self, "无法预览", "当前步骤没有可用的起点坐标。请先在步骤参数里直接填写起点坐标，例如 100,200。")
            return
        options = self.current_coord_step_options()
        if options["direction"] == "移动到新点位" and not parse_coordinate_text(options.get("point", "")):
            QMessageBox.information(self, "无法预览", "请先填写或选取目标点位，例如 960,540。")
            return
        points = build_coord_step_positions(self.base_coordinate[0], self.base_coordinate[1], options)
        if len(points) <= 1:
            QMessageBox.information(self, "无法预览", "当前步进设置不会产生新的点击点位，请检查步进方向、距离或目标点位。")
            return
        self.close_coord_step_preview()
        editable = [0]
        drag_text = "可拖动起点，右键或空白处关闭。"
        if options["direction"] == "移动到新点位":
            editable = list(range(len(points)))
            drag_text = "拖起点/终点会重算整条路径；拖中间点只修正该点并显示星号。右键或空白处关闭。"
        self.coord_step_preview = CoordinateStepPreviewOverlay(
            points,
            options,
            title=f"坐标步进预览：{len(points)} 个可轮到的点位",
            detail_text=f"实际执行每次只点当前点；再次执行本步骤才移动到下一个点。{drag_text}",
            editable_indices=editable,
            point_moved_callback=self.on_coord_step_preview_point_moved,
            auto_close_ms=0,
            marked_indices=self.manual_point_indices()
        )
        self.coord_step_preview.destroyed.connect(self.clear_coord_step_preview)

    def clear_coord_step_preview(self, *_):
        self.coord_step_preview = None

    def close_coord_step_preview(self):
        preview = getattr(self, "coord_step_preview", None)
        if preview:
            try:
                preview.close()
            except RuntimeError:
                pass
            self.coord_step_preview = None

    def save_dialog_geometry(self):
        try:
            self.dialog_settings.setValue("task_config_dialog_geometry", self.saveGeometry())
        except:
            pass

    def accept(self):
        self.save_dialog_geometry()
        super().accept()

    def reject(self):
        self.save_dialog_geometry()
        super().reject()

    def closeEvent(self, event):
        if getattr(self, "coord_step_picker", None):
            self.coord_step_picker.close()
        self.close_coord_step_preview()
        self.save_dialog_geometry()
        super().closeEvent(event)

    def get_data(self):
        return {
            "custom_en": self.enable_chk.isChecked() and self.image_settings_available,
            "custom_conf": self.conf_edit.text(),
            "custom_scale_min": self.s_min_edit.text(),
            "custom_scale_max": self.s_max_edit.text(),
            "custom_scale_step": self.s_step_edit.text(),
            "custom_gray": self.gray_chk.isChecked(),
            "repeat_mode": self.repeat_combo.currentText(),
            "repeat_count": self.repeat_count_edit.text(),
            "step_loop_start": self.step_loop_start_edit.text(),
            "step_loop_end": self.step_loop_end_edit.text(),
            "point_limit_en": self.point_limit_chk.isChecked() and self.point_limit_available,
            "point_limit_count": self.point_limit_count_edit.text(),
            "image_click_point_en": self.image_click_point_chk.isChecked() and self.image_click_point_available,
            "image_click_point_rx": self.image_click_point_rx,
            "image_click_point_ry": self.image_click_point_ry,
            "coord_step_en": self.coord_step_chk.isChecked() and self.coordinate_step_available,
            "coord_step_every": self.coord_step_every_edit.text(),
            "coord_step_direction": self.coord_step_direction_combo.currentText(),
            "coord_step_distance": self.coord_step_distance_edit.text(),
            "coord_step_dx": self.coord_step_dx_edit.text(),
            "coord_step_dy": self.coord_step_dy_edit.text(),
            "coord_step_point": self.coord_step_point_edit.text(),
            "coord_step_max_steps": self.coord_step_max_steps_edit.text(),
            "coord_step_max_distance": self.coord_step_max_distance_edit.text(),
            "coord_step_stop": self.coord_step_stop_chk.isChecked(),
            "coord_step_reset_after": self.coord_step_reset_after_edit.text(),
            "coord_step_manual_points": serialize_coord_step_manual_points(self.coord_step_manual_points if (self.coord_step_chk.isChecked() and self.coordinate_step_available and self.coord_step_manual_active()) else {}),
            "fail_limit": self.fail_limit_edit.text(),
            "no_skip_wait": self.no_skip_wait_chk.isChecked(),
            "success_skip": self.success_skip_edit.text(),
            "success_jump": self.success_jump_edit.text(),
            "fail_skip": self.fail_skip_edit.text(),
            "fail_jump": self.fail_jump_edit.text()
        }

class FloatingSettingsDialog(QDialog):
    def __init__(self, settings, geometry_key, title, default_size):
        super().__init__(None)
        self.settings = settings
        self.geometry_key = geometry_key
        self.default_size = default_size
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowModality(Qt.NonModal)
        self.setWindowTitle(title)

        geometry = self.settings.value(self.geometry_key)
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(*self.default_size)

    def save_dialog_geometry(self):
        try:
            self.settings.setValue(self.geometry_key, self.saveGeometry())
        except:
            pass

    def hideEvent(self, event):
        self.save_dialog_geometry()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.save_dialog_geometry()
        super().closeEvent(event)

# --------------------------
# 区域选择窗口
# --------------------------
class RegionWindow(QWidget):
    region_selected = Signal(tuple)
    regions_selected = Signal(list)

    def __init__(self, multi=False):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.multi = multi
        
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
        self.selections = []
        self.show()

    def valid_regions_for_paint(self):
        regions = list(self.selections)
        if self.selection_rect.isValid():
            regions.append(self.selection_rect)
        return regions

    def physical_rect(self, rect):
        return (
            int(rect.x() * self.scale_x),
            int(rect.y() * self.scale_y),
            int(rect.width() * self.scale_x),
            int(rect.height() * self.scale_y)
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg_color = QColor(0, 0, 0, 100) 
        
        regions = self.valid_regions_for_paint()
        if regions:
            painter.fillRect(self.rect(), bg_color)
            
            pen = QPen(QColor(0, 255, 0), 2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 255, 0, 35))
            for idx, rect in enumerate(regions, 1):
                painter.drawRect(rect)
                real_w = int(rect.width() * self.scale_x)
                real_h = int(rect.height() * self.scale_y)
                prefix = f"区域{idx}: " if self.multi else "选区:"
                info_text = f"{prefix}{rect.width()}x{rect.height()} (实际: {real_w}x{real_h})"
                painter.setPen(QColor(255, 255, 255))
                painter.setFont(QFont("Arial", 12, QFont.Bold)) 
                text_y = rect.y() - 10
                if text_y < 30: text_y = rect.y() + 30
                painter.drawText(rect.x(), text_y, info_text)
                painter.setPen(pen)
            
        else:
            painter.fillRect(self.rect(), bg_color)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 16, QFont.Bold))
            if self.multi:
                hint = f"左键拖拽添加多个小区域 | 右键完成 | 区域相近时建议框成一个大矩形 | 缩放比: {self.scale_x:.2f}"
            else:
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
            if self.multi and self.selections:
                self.regions_selected.emit([self.physical_rect(rect) for rect in self.selections])
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
            if rect.width() > 10 and rect.height() > 10:
                if self.multi:
                    self.selections.append(QRect(rect))
                    self.selection_rect = QRect()
                    self.start_point = None
                    self.end_point = None
                    self.update()
                else:
                    self.region_selected.emit(self.physical_rect(rect))
                    self.close() 

# --------------------------
# 全能钩子录制线程
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
                if vk != 0x77 and vk != 0x1B: 
                    if vk in VK_MAP:
                        self.events.append((time.time(), 'key', VK_MAP[vk]))
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

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
            if self.state == 0: self.start_recording()
            elif self.state == 1: self.stop_recording()
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
            
            if e_type == 'left': tasks.append({"type": 1.0, "value": f"{val[0]},{val[1]}"})
            elif e_type == 'right': tasks.append({"type": 3.0, "value": f"{val[0]},{val[1]}"})
            elif e_type == 'left_drag': tasks.append({"type": 10.0, "value": f"{val[0]},{val[1]} -> {val[2]},{val[3]}"})
            elif e_type == 'right_drag': tasks.append({"type": 11.0, "value": f"{val[0]},{val[1]} -> {val[2]},{val[3]}"})
            elif e_type == 'scroll': tasks.append({"type": 6.0, "value": str(val)})
            elif e_type == 'key': tasks.append({"type": 7.0, "value": val})
                
        for task in tasks:
            self.main_window.add_row(task)
            
        if tasks:
            self.main_window.append_log(f"<font color='#E91E63'><b>>>> 成功捕捉全息动作，生成了 {len(tasks)} 步指令序列。</b></font>")
        else:
            self.main_window.append_log("<font color='gray'><b>>>> 未录制到任何动作。</b></font>")
            
        self.main_window.showNormal()
        self.close()

class CoordinatePickThread(QThread):
    pos_signal = Signal(int, int)
    done_signal = Signal(str)
    cancelled_signal = Signal()

    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.is_active = False
        self.down_pos = None

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        self.is_active = True

        self.mouse_pointer = HOOKPROC(self.mouse_handler)
        self.mouse_hook = user32.SetWindowsHookExW(14, self.mouse_pointer, kernel32.GetModuleHandleW(None), 0)

        msg = wintypes.MSG()
        while self.is_active and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if getattr(self, 'mouse_hook', None):
            user32.UnhookWindowsHookEx(self.mouse_hook)

    def stop(self):
        self.is_active = False
        if getattr(self, 'thread_id', None):
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)

    def finish_with_value(self, value):
        self.done_signal.emit(value)
        self.stop()

    def cancel(self):
        self.cancelled_signal.emit()
        self.stop()

    def mouse_handler(self, nCode, wParam, lParam):
        if nCode >= 0:
            struct = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = struct.pt.x, struct.pt.y
            self.pos_signal.emit(x, y)

            if wParam == 0x0204:  # WM_RBUTTONDOWN
                self.cancel()
                return 1

            if self.mode == "point":
                if wParam == 0x0201:  # WM_LBUTTONDOWN
                    self.down_pos = (x, y)
                    return 1
                if wParam == 0x0202 and self.down_pos:
                    px, py = self.down_pos
                    self.down_pos = None
                    self.finish_with_value(f"{px},{py}")
                    return 1
            else:
                if wParam == 0x0201:
                    self.down_pos = (x, y)
                    return 1
                if wParam == 0x0202 and self.down_pos:
                    x1, y1 = self.down_pos
                    self.down_pos = None
                    self.finish_with_value(f"{x1},{y1} -> {x},{y}")
                    return 1

        return user32.CallNextHookEx(None, nCode, wParam, lParam)

class CoordinatePickerUI(QWidget):
    def __init__(self, mode, callback, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.callback = callback
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bg = QFrame()
        self.bg.setStyleSheet("background-color: rgba(20, 20, 25, 235); border-radius: 8px; border: 2px solid #2196F3;")
        layout.addWidget(self.bg)

        inner = QVBoxLayout(self.bg)
        inner.setContentsMargins(12, 10, 12, 10)
        hint = "左键单击选取坐标" if mode == "point" else "按住左键拖动，松开后选取轨迹"
        self.label = QLabel(f"{hint}\n当前鼠标位置: --,--\n右键取消")
        self.label.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
        self.label.setAlignment(Qt.AlignCenter)
        inner.addWidget(self.label)
        try:
            px, py = pyautogui.position()
            self.update_pos(px, py)
        except: pass

        self.pick_thread = CoordinatePickThread(mode)
        self.pick_thread.pos_signal.connect(self.update_pos)
        self.pick_thread.done_signal.connect(self.finish_pick)
        self.pick_thread.cancelled_signal.connect(self.cancel_pick)
        self.pick_thread.start()

        self.resize(300, 92)
        self.move_to_top()
        self.show()

    def move_to_top(self):
        rect = QApplication.primaryScreen().availableGeometry()
        self.move(rect.x() + (rect.width() - self.width()) // 2, rect.y() + 24)

    def update_pos(self, x, y):
        hint = "左键单击选取坐标" if self.mode == "point" else "按住左键拖动，松开后选取轨迹"
        self.label.setText(f"{hint}\n当前鼠标位置: {x},{y}\n右键取消")

    def finish_pick(self, value):
        self.callback(value)
        self.close()

    def cancel_pick(self):
        self.close()

    def closeEvent(self, event):
        if getattr(self, 'pick_thread', None) and self.pick_thread.isRunning():
            self.pick_thread.stop()
            self.pick_thread.wait(500)
        event.accept()

class CoordinateStepPreviewOverlay(QWidget):
    def __init__(self, points, options=None, title=None, auto_close_ms=6000, draw_lines=True, editable_indices=None, point_moved_callback=None, detail_text=None, close_on_left_blank=True, marked_indices=None):
        super().__init__()
        self.points = [(float(x), float(y)) for x, y in points]
        self.options = options or {}
        self.custom_title = title
        self.detail_text = detail_text
        self.auto_close_ms = auto_close_ms
        self.draw_lines = draw_lines
        self.editable_indices = set(editable_indices or [])
        self.marked_indices = set(marked_indices or [])
        self.point_moved_callback = point_moved_callback
        self.close_on_left_blank = close_on_left_blank
        self.drag_index = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

        virtual_rect = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(virtual_rect)
        phys_w, phys_h = pyautogui.size()
        self.scale_x = phys_w / max(1, virtual_rect.width())
        self.scale_y = phys_h / max(1, virtual_rect.height())

        if self.auto_close_ms > 0:
            QTimer.singleShot(self.auto_close_ms, self.close)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def to_screen_point(self, x, y):
        return QPoint(int(x / self.scale_x), int(y / self.scale_y))

    def set_points(self, points):
        self.points = [(float(x), float(y)) for x, y in points]
        self.update()

    def set_marked_indices(self, marked_indices):
        self.marked_indices = set(marked_indices or [])
        self.update()

    def from_screen_point(self, point):
        return int(round(point.x() * self.scale_x)), int(round(point.y() * self.scale_y))

    def nearest_editable_index(self, pos):
        if not self.editable_indices or not self.points:
            return None
        screen_points = [self.to_screen_point(x, y) for x, y in self.points]
        best_idx = None
        best_dist = 18 * 18
        for idx in self.editable_indices:
            if idx < 0:
                idx = len(screen_points) + idx
            if idx < 0 or idx >= len(screen_points):
                continue
            point = screen_points[idx]
            dist = (point.x() - pos.x()) ** 2 + (point.y() - pos.y()) ** 2
            if dist <= best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if not self.points:
            return

        if self.custom_title:
            title = self.custom_title
        else:
            title = f"坐标步进预览：{len(self.points)} 个可轮到的点位"
            if self.auto_close_ms > 0:
                title += f"，{int(self.auto_close_ms / 1000)} 秒后自动关闭"
        if not self.custom_title and self.options.get("direction") == "移动到新点位":
            max_steps = max(0, int(parse_float_text(self.options.get("max_steps", 0), 0)))
            if max_steps >= 2:
                title += f"；移动上限 {max_steps} = 起点到目标点共 {max_steps} 个点"
            else:
                title += "；移动上限 0 = 起点后直接移动到目标点"
        painter.setFont(QFont("Arial", 13, QFont.Bold))
        fm = painter.fontMetrics()
        max_title_width = max(360, self.width() - 40)
        title = fm.elidedText(title, Qt.ElideRight, max_title_width - 24)
        detail = self.detail_text or ""
        min_title_width = 520 if detail else 0
        title_rect = QRect(20, 24, min(max(fm.horizontalAdvance(title) + 24, min_title_width), max_title_width), 58 if detail else 34)
        title_rect.moveLeft(max(20, (self.width() - title_rect.width()) // 2))
        painter.fillRect(title_rect, QColor(0, 0, 0, 190))
        painter.setPen(QColor(255, 255, 255))
        if detail:
            painter.drawText(QRect(title_rect.x() + 12, title_rect.y() + 5, title_rect.width() - 24, 24), Qt.AlignCenter, title)
            painter.setFont(QFont("Arial", 9))
            dfm = painter.fontMetrics()
            draw_detail = dfm.elidedText(detail, Qt.ElideRight, title_rect.width() - 24)
            painter.drawText(QRect(title_rect.x() + 12, title_rect.y() + 30, title_rect.width() - 24, 22), Qt.AlignCenter, draw_detail)
        else:
            painter.drawText(title_rect, Qt.AlignCenter, title)

        screen_points = [self.to_screen_point(x, y) for x, y in self.points]
        if self.draw_lines and len(screen_points) > 1:
            painter.setPen(QPen(QColor(0, 188, 212, 220), 3, Qt.SolidLine, Qt.RoundCap))
            for idx in range(len(screen_points) - 1):
                painter.drawLine(screen_points[idx], screen_points[idx + 1])

        painter.setFont(QFont("Arial", 10, QFont.Bold))
        normalized_editable = set()
        for edit_idx in self.editable_indices:
            normalized_editable.add(len(screen_points) + edit_idx if edit_idx < 0 else edit_idx)
        normalized_marked = set()
        for mark_idx in self.marked_indices:
            normalized_marked.add(len(screen_points) + mark_idx if mark_idx < 0 else mark_idx)
        for idx, point in enumerate(screen_points, 1):
            zero_idx = idx - 1
            if zero_idx in normalized_marked:
                fill = QColor(156, 39, 176, 240)
            elif idx == 1:
                fill = QColor(76, 175, 80, 235)
            elif idx == len(screen_points):
                fill = QColor(244, 67, 54, 235)
            else:
                fill = QColor(255, 193, 7, 235)

            radius = 13 if zero_idx in normalized_marked else (12 if zero_idx in normalized_editable else 9)
            painter.setBrush(fill)
            painter.setPen(QPen(QColor(255, 255, 255), 3 if zero_idx in normalized_editable or zero_idx in normalized_marked else 2))
            painter.drawEllipse(point, radius, radius)

            label = f"{idx}*" if zero_idx in normalized_marked else str(idx)
            label_rect = QRect(point.x() + 12, point.y() - 22, 48, 22)
            painter.fillRect(label_rect, QColor(0, 0, 0, 175))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(label_rect, Qt.AlignCenter, label)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.close()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            idx = self.nearest_editable_index(event.position().toPoint())
            if idx is not None:
                self.drag_index = idx
                self.setCursor(Qt.SizeAllCursor)
                event.accept()
                return
            if self.close_on_left_blank:
                self.close()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self.drag_index is not None:
            x, y = self.from_screen_point(pos)
            self.points[self.drag_index] = (x, y)
            if self.point_moved_callback:
                updated_points = self.point_moved_callback(self.drag_index, int(round(x)), int(round(y)))
                if updated_points:
                    self.set_points(updated_points)
            self.update()
            event.accept()
            return
        self.setCursor(Qt.SizeAllCursor if self.nearest_editable_index(pos) is not None else Qt.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drag_index is not None:
            idx = self.drag_index
            self.drag_index = None
            self.setCursor(Qt.PointingHandCursor)
            x, y = self.points[idx]
            if self.point_moved_callback:
                updated_points = self.point_moved_callback(idx, int(round(x)), int(round(y)))
                if updated_points:
                    self.set_points(updated_points)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

class RunningStatusOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.position_name = "右上角"
        self.start_time = time.time()
        self.status_data = {}
        self.setFixedWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bg = QFrame()
        self.bg.setStyleSheet("background-color: rgba(10, 35, 45, 235); border-radius: 8px; border: 2px solid #00BCD4;")
        layout.addWidget(self.bg)

        inner = QVBoxLayout(self.bg)
        inner.setContentsMargins(12, 8, 12, 8)
        self.label = QLabel()
        self.label.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setFixedWidth(248)
        inner.addWidget(self.label)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_text)

    def start_overlay(self, position_name):
        self.position_name = position_name
        self.start_time = time.time()
        self.status_data = {}
        self.timer.start(500)
        self.refresh_text()
        self.show()
        self.raise_()

    def set_status(self, data):
        self.status_data.update(data)
        self.refresh_text()

    def refresh_text(self):
        elapsed = int(time.time() - self.start_time)
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        elapsed_text = f"{h:02d}:{m:02d}:{s:02d}"
        loop = self.status_data.get("loop", 1)
        step = self.status_data.get("step", 0)
        total = self.status_data.get("total", 0)
        cmd = self.status_data.get("cmd", "")
        step_text = f"步骤 {step}/{total}" if step and total else "准备中"
        if cmd:
            step_text += f" | {cmd}"
        self.label.setText(f"脚本正在执行中\n第 {loop} 次 | {step_text}\n已运行 {elapsed_text}")
        self.adjustSize()
        self.move_to_position()

    def move_to_position(self):
        rect = QApplication.primaryScreen().availableGeometry()
        margin = 18
        x = max(rect.x() + margin, rect.x() + rect.width() - self.width() - margin)
        if self.position_name == "右下角":
            y = rect.y() + rect.height() - self.height() - margin
        else:
            y = rect.y() + margin
        self.move(x, y)

    def stop_overlay(self):
        self.timer.stop()
        self.hide()

class ClickPointOverlay(QWidget):
    def __init__(self, x, y, text="", duration_ms=650):
        super().__init__()
        self.x = float(x)
        self.y = float(y)
        self.text = str(text or "")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_DeleteOnClose)

        virtual_rect = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(virtual_rect)
        phys_w, phys_h = pyautogui.size()
        self.scale_x = phys_w / max(1, virtual_rect.width())
        self.scale_y = phys_h / max(1, virtual_rect.height())
        QTimer.singleShot(max(200, int(duration_ms)), self.close)
        self.show()
        self.raise_()

    def to_screen_point(self):
        return QPoint(int(self.x / self.scale_x), int(self.y / self.scale_y))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        point = self.to_screen_point()

        painter.setPen(QPen(QColor(255, 255, 255, 235), 4))
        painter.setBrush(QColor(33, 150, 243, 90))
        painter.drawEllipse(point, 18, 18)
        painter.setPen(QPen(QColor(244, 67, 54, 245), 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(point.x() - 24, point.y(), point.x() + 24, point.y())
        painter.drawLine(point.x(), point.y() - 24, point.x(), point.y() + 24)

        if self.text:
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            label = painter.fontMetrics().elidedText(self.text, Qt.ElideRight, 160)
            rect = QRect(point.x() + 24, point.y() - 14, min(170, painter.fontMetrics().horizontalAdvance(label) + 20), 28)
            if rect.right() > self.width() - 8:
                rect.moveRight(point.x() - 24)
            painter.fillRect(rect, QColor(0, 0, 0, 180))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect, Qt.AlignCenter, label)

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
            except: time.sleep(1)

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
# 核心引擎
# --------------------------
class RPAEngine:
    def __init__(self):
        self.is_running = False
        self.stop_requested = False
        self.min_scale = 1.0
        self.max_scale = 1.0
        self.scale_step = 0.05
        self.enable_grayscale = True
        self.confidence = 0.8
        self.scan_region = None 
        self.scan_regions = []
        self.dodge_x1 = 100
        self.dodge_y1 = 100
        self.dodge_x2 = 200
        self.dodge_y2 = 100
        self.enable_dodge = False
        self.enable_double_dodge = False
        self.double_dodge_wait = 0.015
        self.move_duration = 0.0
        self.click_hold = 0.04
        self.settlement_wait = 0.0
        self.timeout_val = 0.0
        self.timeout_stop = False
        self.detect_delay = 0.0
        self.adaptive_backoff = True
        self.show_click_indicator = True
        self.use_native_core = False if SLIM_BUILD else True
        self.use_fast_screenshot = True
        self.playback_speed = 1.0
        self.start_step_index = 0
        self.loop_start_round = 1
        self.loop_end_round = 0
        self.multi_target_mode = "最佳一个"
        self.multi_target_order = "从上到下"
        self.loop_mode = "单次"
        self.loop_val = 1.0
        self.log_level = 0
        self.enable_tm_stop = True 
        self.enable_tr_stop = True 
        self.enable_key_stop = True
        
        self.callback_msg = None
        self.callback_status = None
        self.callback_click_indicator = None
        self.opencv_available = False 
        self.native_core = None if SLIM_BUILD else NativeVisionCore()
        self.native_core_logged = False
        self.img_cache = {} 
        self.scaled_templates_cache = {}
        self.scale_options_cache = {}
        self.point_click_counts = {}
        self.coord_step_states = {}
        self.miss_streaks = {}
        self.last_target_positions = {}
        self._mss_instance = None

        self.check_engine_status()
        if not SLIM_BUILD:
            self._log_native_core_status()
        self.set_high_priority()

    def set_high_priority(self):
        try:
            pid = os.getpid()
            handle = ctypes.windll.kernel32.OpenProcess(0x0100, True, pid)
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000080)
        except: pass

    def check_engine_status(self):
        if SLIM_BUILD:
            self.opencv_available = False
            write_log("精简版引擎就绪：已移除 OpenCV/NumPy/DLL 原生识别，仅支持原图原尺寸精确匹配。")
            return
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

    def _log_native_core_status(self):
        if SLIM_BUILD:
            return
        if self.native_core.available:
            write_log(f"Native vision core ready (v{self.native_core.version}).")
        else:
            write_log(f"Native vision core unavailable, fallback enabled: {self.native_core.load_error}")

    def stop(self):
        self.stop_requested = True
        self.is_running = False

    def log(self, msg):
        write_log(msg, self.callback_msg)

    def report_status(self, loop_count=1, step=0, total=0, cmd=""):
        if self.callback_status:
            try:
                self.callback_status({
                    "loop": int(loop_count),
                    "step": int(step),
                    "total": int(total),
                    "cmd": str(cmd)
                })
            except: pass

    def report_click_indicator(self, x, y, text=""):
        if not self.show_click_indicator or not self.callback_click_indicator:
            return
        try:
            self.callback_click_indicator({
                "x": int(round(float(x))),
                "y": int(round(float(y))),
                "text": str(text or "")
            })
        except:
            pass

    def positive_int_value(self, value, default=1):
        try:
            return max(1, int(float(value)))
        except:
            return default

    def non_negative_int_value(self, value, default=0):
        try:
            return max(0, int(float(value)))
        except:
            return default

    def check_stop_flag(self):
        return self.stop_requested

    def wait_recognition_interval(self, extra_delay=0.0):
        wait_time = max(0.0, self.detect_delay + max(0.0, extra_delay))
        if wait_time <= 0:
            return True
        end_time = time.time() + wait_time
        while time.time() < end_time:
            if self.check_stop_flag():
                return False
            time.sleep(min(0.05, max(0.0, end_time - time.time())))
        return True

    def wait_step_interval(self):
        wait_time = max(0.0, float(self.settlement_wait or 0.0))
        if wait_time <= 0:
            return True
        end_time = time.time() + wait_time
        while time.time() < end_time:
            if self.check_stop_flag():
                return False
            time.sleep(min(0.05, max(0.0, end_time - time.time())))
        return True

    def is_wait_command(self, cmd):
        try:
            return float(cmd) == 5.0
        except:
            return False

    def task_active_in_loop(self, task, loop_count):
        if not task:
            return False
        step_loop_start = self.positive_int_value(task.get("step_loop_start", 1), 1)
        step_loop_end = self.non_negative_int_value(task.get("step_loop_end", 0), 0)
        if loop_count < step_loop_start:
            return False
        if step_loop_end > 0 and loop_count > step_loop_end:
            return False
        return True

    def next_interval_task(self, tasks, next_idx, loop_count):
        for look_idx in range(max(0, int(next_idx)), len(tasks)):
            task = tasks[look_idx]
            if self.task_active_in_loop(task, loop_count):
                return task

        next_loop = loop_count + 1
        if self.loop_mode == "单次":
            return None
        if self.loop_end_round > 0 and next_loop > self.loop_end_round:
            return None
        start_idx = min(max(int(getattr(self, "start_step_index", 0)), 0), max(len(tasks) - 1, 0))
        for look_idx in range(start_idx, len(tasks)):
            task = tasks[look_idx]
            if self.task_active_in_loop(task, next_loop):
                return task
        return None

    def should_wait_step_interval(self, tasks, current_cmd, next_idx, loop_count):
        if max(0.0, float(self.settlement_wait or 0.0)) <= 0:
            return False
        if self.is_wait_command(current_cmd):
            return False
        next_task = self.next_interval_task(tasks, next_idx, loop_count)
        if not next_task:
            return False
        if self.is_wait_command(next_task.get("type")):
            return False
        return True

    def recognition_key(self, img_path, step_info):
        step = step_info.get("step", 0) if step_info else 0
        return (step, os.path.abspath(str(img_path)))

    def record_recognition_miss(self, img_path, step_info):
        key = self.recognition_key(img_path, step_info)
        self.miss_streaks[key] = self.miss_streaks.get(key, 0) + 1
        return self.miss_streaks[key]

    def reset_recognition_miss(self, img_path, step_info):
        self.miss_streaks.pop(self.recognition_key(img_path, step_info), None)

    def adaptive_extra_delay(self, img_path, step_info):
        if not self.adaptive_backoff:
            return 0.0
        miss_count = self.miss_streaks.get(self.recognition_key(img_path, step_info), 0)
        if miss_count < 3:
            return 0.0
        return min(0.8, 0.05 * (miss_count - 2))

    def as_bool(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "启用", "是")
        return bool(value)

    def normalized_regions(self, regions):
        result = []
        for region in regions or []:
            try:
                x, y, w, h = [int(float(v)) for v in region]
                if w > 0 and h > 0:
                    result.append((x, y, w, h))
            except:
                continue
        return result

    def capture_screenshot(self, region=None):
        if self.use_fast_screenshot and HAS_MSS:
            try:
                if self._mss_instance is None:
                    self._mss_instance = mss.mss()
                if region:
                    x, y, w, h = [int(v) for v in region]
                    monitor = {"left": x, "top": y, "width": w, "height": h}
                    offset_x, offset_y = x, y
                else:
                    monitor = self._mss_instance.monitors[0]
                    offset_x, offset_y = int(monitor.get("left", 0)), int(monitor.get("top", 0))
                shot = self._mss_instance.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.rgb), offset_x, offset_y
            except Exception as e:
                if self.log_level >= 2:
                    self.log(f"<font color='orange'>    [截图] mss快速截图失败，已回退到pyautogui: {e}</font>")

        screenshot_pil = pyautogui.screenshot(region=region)
        offset_x = region[0] if region else 0
        offset_y = region[1] if region else 0
        return screenshot_pil, offset_x, offset_y

    def region_bounding_rect(self, regions):
        left = min(r[0] for r in regions)
        top = min(r[1] for r in regions)
        right = max(r[0] + r[2] for r in regions)
        bottom = max(r[1] + r[3] for r in regions)
        return (left, top, right - left, bottom - top)

    def screen_bounds(self):
        if HAS_MSS:
            try:
                if self._mss_instance is None:
                    self._mss_instance = mss.mss()
                monitor = self._mss_instance.monitors[0]
                return (int(monitor.get("left", 0)), int(monitor.get("top", 0)), int(monitor["width"]), int(monitor["height"]))
            except:
                pass
        w, h = pyautogui.size()
        return (0, 0, int(w), int(h))

    def clip_region_to_bounds(self, region, bounds):
        x, y, w, h = [int(v) for v in region]
        bx, by, bw, bh = [int(v) for v in bounds]
        left = max(x, bx)
        top = max(y, by)
        right = min(x + w, bx + bw)
        bottom = min(y + h, by + bh)
        if right <= left or bottom <= top:
            return None
        return (left, top, right - left, bottom - top)

    def should_batch_regions(self, regions):
        if len(regions) < 2:
            return False
        total_area = sum(w * h for _x, _y, w, h in regions)
        bx, by, bw, bh = self.region_bounding_rect(regions)
        bbox_area = bw * bh
        return bbox_area <= max(total_area * 3, total_area + 50000)

    def iter_search_screenshots(self):
        active_regions = self.normalized_regions(getattr(self, "scan_regions", []))
        if not active_regions:
            yield self.capture_screenshot(self.scan_region)
            return

        if self.should_batch_regions(active_regions):
            bbox = self.region_bounding_rect(active_regions)
            try:
                screenshot_pil, offset_x, offset_y = self.capture_screenshot(bbox)
                for x, y, w, h in active_regions:
                    crop_box = (x - offset_x, y - offset_y, x - offset_x + w, y - offset_y + h)
                    yield screenshot_pil.crop(crop_box), x, y
                return
            except Exception as e:
                if self.log_level >= 2:
                    self.log(f"<font color='orange'>    [截图] 多区域合并截图失败，改为逐区域截图: {e}</font>")

        for region in active_regions:
            if self.check_stop_flag():
                return
            yield self.capture_screenshot(region)

    def target_position_key(self, img_path, cache_key, task_conf, use_gray):
        return (os.path.abspath(str(img_path)), str(cache_key), float(task_conf), bool(use_gray))

    def template_dimensions(self, img_path):
        try:
            if img_path not in self.img_cache and os.path.exists(img_path):
                img = Image.open(img_path)
                img.load()
                self.img_cache[img_path] = img
            img = self.img_cache.get(img_path)
            if img:
                return img.size
        except:
            pass
        return (80, 80)

    def image_click_point_options(self, task):
        if not task or not self.as_bool(task.get("image_click_point_en", False)):
            return None
        rx = max(0.0, min(1.0, self.parse_float_value(task.get("image_click_point_rx", 0.5), 0.5)))
        ry = max(0.0, min(1.0, self.parse_float_value(task.get("image_click_point_ry", 0.5), 0.5)))
        return {"rx": rx, "ry": ry}

    def adjusted_image_click_point(self, img_path, location_tuple, image_click_config):
        x, y, scale, score = location_tuple
        if not image_click_config:
            return x, y
        tpl_w, tpl_h = self.template_dimensions(img_path)
        matched_w = tpl_w * max(0.01, float(scale))
        matched_h = tpl_h * max(0.01, float(scale))
        rx = image_click_config.get("rx", 0.5)
        ry = image_click_config.get("ry", 0.5)
        click_x = x + (rx - 0.5) * matched_w
        click_y = y + (ry - 0.5) * matched_h
        return click_x, click_y

    def quick_search_region(self, img_path, cache_key, task_conf, use_gray):
        if self.normalized_regions(getattr(self, "scan_regions", [])):
            return None
        key = self.target_position_key(img_path, cache_key, task_conf, use_gray)
        last = self.last_target_positions.get(key)
        if not last:
            return None

        tpl_w, tpl_h = self.template_dimensions(img_path)
        radius = max(120, int(max(tpl_w, tpl_h) * 3))
        x = int(last[0] - radius)
        y = int(last[1] - radius)
        region = (x, y, radius * 2, radius * 2)
        bounds = self.scan_region if self.scan_region else self.screen_bounds()
        return self.clip_region_to_bounds(region, bounds)

    def scale_options_for(self, cache_key):
        if SLIM_BUILD:
            return (1.0, 1.0, 0.05)
        return self.scale_options_cache.get(str(cache_key), (self.min_scale, self.max_scale, self.scale_step))

    def native_search_regions(self, quick_region=None):
        if quick_region:
            return [quick_region]
        active_regions = self.normalized_regions(getattr(self, "scan_regions", []))
        if active_regions:
            return active_regions
        if self.scan_region:
            return [self.scan_region]
        return []

    def native_find_targets(self, img_path, cache_key, task_conf, use_gray, find_all=False, quick_region=None):
        if SLIM_BUILD:
            return None
        if not self.use_native_core:
            return None
        if not getattr(self, "native_core", None) or not self.native_core.available:
            return None
        path = str(img_path)
        if not path or ',' in path or not os.path.exists(path):
            return None
        if self.check_stop_flag():
            return None

        s_min, s_max, s_step = self.scale_options_for(cache_key)
        max_matches = 1024 if find_all else 1
        matches = self.native_core.find_template(
            path,
            self.native_search_regions(quick_region),
            s_min,
            s_max,
            s_step,
            use_gray,
            task_conf,
            find_all=find_all,
            max_matches=max_matches,
        )
        if matches is None:
            if self.log_level >= 2 and self.native_core.load_error:
                self.log(f"<font color='gray'>    [native] fallback: {self.native_core.load_error}</font>")
            return None
        return [(x, y, scale, score) for x, y, scale, score, _radius in matches]

    def load_and_precompute(self, tasks):
        if SLIM_BUILD:
            try:
                write_log("正在预加载精简版图片资源...")
                for task in tasks:
                    path = str(task.get("value", ""))
                    if not path or not os.path.exists(path) or ',' in path:
                        continue
                    if task.get("type") not in [1.0, 2.0, 3.0, 8.0]:
                        continue
                    img = Image.open(path)
                    img.load()
                    self.img_cache[path] = img
                    task['cache_key'] = path
                write_log("精简版图片资源预加载完成。")
            except Exception as e:
                write_log(f"精简版图片预加载失败: {e}")
            return
        if not self.opencv_available: return
        try:
            import cv2
            import numpy as np
            write_log("正在预加载资源...")
            for task in tasks:
                path = str(task.get("value", ""))
                if not path or not os.path.exists(path) or ',' in path: continue
                if task.get("type") not in [1.0, 2.0, 3.0, 8.0]: continue
                
                img = Image.open(path)
                img.load()
                self.img_cache[path] = img
                
                if task.get("custom_en", False):
                    try:
                        s_min = float(task.get("custom_scale_min", self.min_scale))
                        s_max = float(task.get("custom_scale_max", self.max_scale))
                        s_step = float(task.get("custom_scale_step", self.scale_step))
                    except:
                        s_min, s_max, s_step = self.min_scale, self.max_scale, self.scale_step
                    use_gray = bool(task.get("custom_gray", self.enable_grayscale))
                else:
                    s_min, s_max, s_step = self.min_scale, self.max_scale, self.scale_step
                    use_gray = self.enable_grayscale
                    
                cache_key = f"{path}_{s_min}_{s_max}_{s_step}_{use_gray}"
                task['cache_key'] = cache_key
                self.scale_options_cache[str(cache_key)] = (s_min, s_max, s_step)
                
                if s_min != 1.0 or s_max != 1.0:
                    if cache_key not in self.scaled_templates_cache:
                        if use_gray:
                            if img.mode != 'L': img = img.convert('L')
                            template = np.array(img)
                        else:
                            if img.mode != 'RGB': img = img.convert('RGB')
                            template = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                            
                        templates_list = []
                        safe_step = max(s_step, 0.01)
                        steps = int((s_max - s_min) / safe_step) + 1
                        for scale in np.linspace(s_min, s_max, steps):
                            if 0.99 < scale < 1.01: continue
                            rw = int(template.shape[1] * scale)
                            rh = int(template.shape[0] * scale)
                            if rw < 1 or rh < 1: continue
                            resized_tpl = cv2.resize(template, (rw, rh))
                            templates_list.append((scale, resized_tpl))
                        self.scaled_templates_cache[cache_key] = templates_list
            write_log("资源预加载完成。")
        except Exception as e:
            write_log(f"预计算失败: {e}")

    def find_target_in_screenshot(self, img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y):
        if SLIM_BUILD:
            try:
                target = self.img_cache.get(img_path)
                if target is None:
                    if not os.path.exists(str(img_path)):
                        return None
                    target = Image.open(str(img_path))
                    target.load()
                    self.img_cache[img_path] = target
                res = pyautogui.locate(target, screenshot_pil)
                if res:
                    return (res.left + (res.width / 2) + offset_x, res.top + (res.height / 2) + offset_y, 1.0)
            except:
                pass
            return None
        if not self.opencv_available:
            if img_path in self.img_cache:
                try: 
                    res = pyautogui.locate(self.img_cache[img_path], screenshot_pil, confidence=task_conf, grayscale=use_gray)
                    if res: return (res.left + (res.width / 2) + offset_x, res.top + (res.height / 2) + offset_y, 1.0)
                except: pass
            elif os.path.exists(img_path):
                 try:
                    res = pyautogui.locate(img_path, screenshot_pil, confidence=task_conf, grayscale=use_gray)
                    if res: return (res.left + (res.width / 2) + offset_x, res.top + (res.height / 2) + offset_y, 1.0)
                 except: pass
            return None

        import cv2
        import numpy as np
        
        screen_np = np.array(screenshot_pil)
        if use_gray:
            screen_img = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
        else:
            screen_img = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)
        
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
            if use_gray:
                if pil_template.mode != 'L': pil_template = pil_template.convert('L')
                tpl_img = np.array(pil_template)
            else:
                if pil_template.mode != 'RGB': pil_template = pil_template.convert('RGB')
                tpl_img = cv2.cvtColor(np.array(pil_template), cv2.COLOR_RGB2BGR)
                
            if tpl_img.shape[0] <= screen_img.shape[0] and tpl_img.shape[1] <= screen_img.shape[1]:
                res = cv2.matchTemplate(screen_img, tpl_img, cv2.TM_CCOEFF_NORMED)
                min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
                if max_v >= task_conf:
                    h, w = tpl_img.shape[:2]
                    return (max_l[0] + w//2 + offset_x, max_l[1] + h//2 + offset_y, 1.0)
        except: pass
        
        if cache_key in self.scaled_templates_cache:
            for scale, resized_tpl in self.scaled_templates_cache[cache_key]:
                if self.check_stop_flag(): return None
                try:
                    if resized_tpl.shape[0] > screen_img.shape[0] or resized_tpl.shape[1] > screen_img.shape[1]: continue
                    res = cv2.matchTemplate(screen_img, resized_tpl, cv2.TM_CCOEFF_NORMED)
                    min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
                    if max_v >= task_conf:
                        h, w = resized_tpl.shape[:2]
                        return (max_l[0] + w//2 + offset_x, max_l[1] + h//2 + offset_y, scale)
                except: continue
        return None

    def find_target_optimized(self, img_path, cache_key, task_conf, use_gray):
        position_key = self.target_position_key(img_path, cache_key, task_conf, use_gray)
        quick_region = self.quick_search_region(img_path, cache_key, task_conf, use_gray)
        if quick_region:
            native_found = self.native_find_targets(img_path, cache_key, task_conf, use_gray, find_all=False, quick_region=quick_region)
            if native_found:
                found = native_found[0]
                self.last_target_positions[position_key] = (found[0], found[1])
                return found
            try:
                screenshot_pil, offset_x, offset_y = self.capture_screenshot(quick_region)
                found = self.find_target_in_screenshot(img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y)
                if found:
                    self.last_target_positions[position_key] = (found[0], found[1])
                    return found
            except:
                pass
            self.last_target_positions.pop(position_key, None)

        native_found = self.native_find_targets(img_path, cache_key, task_conf, use_gray, find_all=False)
        if native_found:
            found = native_found[0]
            self.last_target_positions[position_key] = (found[0], found[1])
            return found

        try:
            for screenshot_pil, offset_x, offset_y in self.iter_search_screenshots():
                if self.check_stop_flag():
                    return None
                found = self.find_target_in_screenshot(img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y)
                if found:
                    self.last_target_positions[position_key] = (found[0], found[1])
                    return found
        except:
            return None
        return None

    def _collect_template_matches(self, screen_img, tpl_img, task_conf, offset_x, offset_y, scale):
        import cv2
        import numpy as np

        if tpl_img.shape[0] > screen_img.shape[0] or tpl_img.shape[1] > screen_img.shape[1]:
            return []

        res = cv2.matchTemplate(screen_img, tpl_img, cv2.TM_CCOEFF_NORMED)
        h, w = tpl_img.shape[:2]
        kernel_w = max(3, int(w * 0.6))
        kernel_h = max(3, int(h * 0.6))
        peak_map = cv2.dilate(res, np.ones((kernel_h, kernel_w), dtype=np.uint8))
        ys, xs = np.where((res >= task_conf) & (res == peak_map))
        if len(xs) == 0:
            return []

        scores = res[ys, xs]
        if len(xs) > 2000:
            keep = np.argpartition(scores, -2000)[-2000:]
            xs, ys, scores = xs[keep], ys[keep], scores[keep]

        matches = []
        for x, y, score in zip(xs, ys, scores):
            matches.append({
                "x": float(x + w // 2 + offset_x),
                "y": float(y + h // 2 + offset_y),
                "scale": float(scale),
                "score": float(score),
                "radius": max(4.0, min(w, h) * 0.55)
            })
        return matches

    def _dedupe_targets(self, matches):
        accepted = []
        for match in sorted(matches, key=lambda m: m["score"], reverse=True):
            too_close = False
            for item in accepted:
                dx = match["x"] - item["x"]
                dy = match["y"] - item["y"]
                radius = max(match["radius"], item["radius"])
                if dx * dx + dy * dy <= radius * radius:
                    too_close = True
                    break
            if not too_close:
                accepted.append(match)
        return accepted

    def _sort_targets_for_click(self, targets):
        order = self.multi_target_order
        if order == "随机顺序":
            random.shuffle(targets)
            return targets
        if order == "距离鼠标最近优先":
            try:
                mx, my = pyautogui.position()
                targets.sort(key=lambda p: ((p["x"] - mx) ** 2 + (p["y"] - my) ** 2, p["y"], p["x"]))
            except:
                targets.sort(key=lambda p: (p["y"], p["x"]))
            return targets
        if order == "从左到右":
            targets.sort(key=lambda p: (p["x"], p["y"]))
        elif order == "从右到左":
            targets.sort(key=lambda p: (-p["x"], p["y"]))
        else:
            targets.sort(key=lambda p: (p["y"], p["x"]))
        return targets

    def _point_limit_key(self, step_info, img_path, x, y):
        step = step_info.get("step", 0) if step_info else 0
        bucket_x = int(round(float(x) / 8.0) * 8)
        bucket_y = int(round(float(y) / 8.0) * 8)
        return (step, os.path.abspath(str(img_path)), bucket_x, bucket_y)

    def _filter_point_limit_targets(self, locations, img_path, step_info, point_limit_en, point_limit_count):
        if not point_limit_en or point_limit_count <= 0:
            return locations

        filtered = []
        skipped = 0
        for location_tuple in locations:
            x, y = location_tuple[0], location_tuple[1]
            key = self._point_limit_key(step_info, img_path, x, y)
            if self.point_click_counts.get(key, 0) >= point_limit_count:
                skipped += 1
                continue
            filtered.append(location_tuple)

        if skipped and self.log_level >= 1:
            self.log(f"    -> 同点点击上限已过滤 {skipped} 个已达上限的点位")
        return filtered

    def _record_point_click(self, img_path, step_info, x, y):
        key = self._point_limit_key(step_info, img_path, x, y)
        self.point_click_counts[key] = self.point_click_counts.get(key, 0) + 1
        return self.point_click_counts[key]

    def find_all_targets_in_screenshot(self, img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y):
        if SLIM_BUILD:
            try:
                target = self.img_cache.get(img_path)
                if target is None:
                    if not os.path.exists(str(img_path)):
                        return []
                    target = Image.open(str(img_path))
                    target.load()
                    self.img_cache[img_path] = target
                boxes = list(pyautogui.locateAll(target, screenshot_pil))
                matches = [{
                    "x": box.left + (box.width / 2) + offset_x,
                    "y": box.top + (box.height / 2) + offset_y,
                    "scale": 1.0,
                    "score": 1.0,
                    "radius": max(4.0, min(box.width, box.height) * 0.55)
                } for box in boxes]
                return [(p["x"], p["y"], p["scale"], p["score"]) for p in self._sort_targets_for_click(self._dedupe_targets(matches))]
            except:
                one = self.find_target_optimized(img_path, cache_key, task_conf, use_gray)
                return [(one[0], one[1], one[2], 1.0)] if one else []
        if not self.opencv_available:
            try:
                target = self.img_cache.get(img_path, img_path)
                boxes = list(pyautogui.locateAll(target, screenshot_pil, confidence=task_conf, grayscale=use_gray))
                matches = [{
                    "x": box.left + (box.width / 2) + offset_x,
                    "y": box.top + (box.height / 2) + offset_y,
                    "scale": 1.0,
                    "score": 1.0,
                    "radius": max(4.0, min(box.width, box.height) * 0.55)
                } for box in boxes]
                return [(p["x"], p["y"], p["scale"], p["score"]) for p in self._sort_targets_for_click(self._dedupe_targets(matches))]
            except:
                one = self.find_target_optimized(img_path, cache_key, task_conf, use_gray)
                return [(one[0], one[1], one[2], task_conf)] if one else []

        import cv2
        import numpy as np

        screen_np = np.array(screenshot_pil)
        if use_gray:
            screen_img = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
        else:
            screen_img = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)

        if img_path not in self.img_cache:
            if os.path.exists(img_path):
                try:
                    img = Image.open(img_path)
                    img.load()
                    self.img_cache[img_path] = img
                except: return []
            else: return []

        pil_template = self.img_cache[img_path]
        matches = []
        try:
            if use_gray:
                if pil_template.mode != 'L': pil_template = pil_template.convert('L')
                tpl_img = np.array(pil_template)
            else:
                if pil_template.mode != 'RGB': pil_template = pil_template.convert('RGB')
                tpl_img = cv2.cvtColor(np.array(pil_template), cv2.COLOR_RGB2BGR)

            matches.extend(self._collect_template_matches(screen_img, tpl_img, task_conf, offset_x, offset_y, 1.0))
        except: pass

        if cache_key in self.scaled_templates_cache:
            for scale, resized_tpl in self.scaled_templates_cache[cache_key]:
                if self.check_stop_flag(): return []
                try:
                    matches.extend(self._collect_template_matches(screen_img, resized_tpl, task_conf, offset_x, offset_y, scale))
                except: continue

        targets = self._sort_targets_for_click(self._dedupe_targets(matches))
        return [(p["x"], p["y"], p["scale"], p["score"]) for p in targets]

    def find_all_targets_optimized(self, img_path, cache_key, task_conf, use_gray):
        native_targets = self.native_find_targets(img_path, cache_key, task_conf, use_gray, find_all=True)
        if native_targets:
            target_dicts = [{
                "x": float(x),
                "y": float(y),
                "scale": float(scale),
                "score": float(score),
                "radius": 8.0
            } for x, y, scale, score in native_targets]
            targets = self._sort_targets_for_click(self._dedupe_targets(target_dicts))
            return [(p["x"], p["y"], p["scale"], p["score"]) for p in targets]

        all_targets = []
        try:
            for screenshot_pil, offset_x, offset_y in self.iter_search_screenshots():
                if self.check_stop_flag():
                    return []
                all_targets.extend(self.find_all_targets_in_screenshot(img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y))
        except:
            return []

        target_dicts = [{
            "x": float(x),
            "y": float(y),
            "scale": float(scale),
            "score": float(score),
            "radius": 8.0
        } for x, y, scale, score in all_targets]
        targets = self._sort_targets_for_click(self._dedupe_targets(target_dicts))
        return [(p["x"], p["y"], p["scale"], p["score"]) for p in targets]

    def get_cmd_name(self, cmd_val):
        mapping = {
            1.0: "左键单击", 2.0: "左键双击", 3.0: "右键单击", 4.0: "输入文本", 
            5.0: "等待(秒)", 6.0: "滚轮滑动", 7.0: "系统按键", 8.0: "鼠标悬停", 
            9.0: "截图保存", 10.0: "左键拖拽", 11.0: "右键拖拽", 12.0: "弹窗提醒", 
            13.0: "停止运行", 14.0: "声音提示"
        }
        return mapping.get(cmd_val, "未知操作")

    def parse_coordinate(self, val):
        return parse_coordinate_text(val)

    def parse_float_value(self, value, default=0.0):
        return parse_float_text(value, default)

    def coord_step_options(self, task):
        if not task or not self.as_bool(task.get("coord_step_en", False)):
            return None
        try:
            every = max(1, int(float(task.get("coord_step_every", 1))))
        except:
            every = 1
        return {
            "every": every,
            "direction": str(task.get("coord_step_direction", "向下")),
            "distance": self.parse_float_value(task.get("coord_step_distance", 0), 0.0),
            "dx": self.parse_float_value(task.get("coord_step_dx", 0), 0.0),
            "dy": self.parse_float_value(task.get("coord_step_dy", 0), 0.0),
            "point": str(task.get("coord_step_point", "")).strip(),
            "max_steps": max(0, int(self.parse_float_value(task.get("coord_step_max_steps", 0), 0.0))),
            "max_distance": max(0.0, self.parse_float_value(task.get("coord_step_max_distance", 0), 0.0)),
            "stop": self.as_bool(task.get("coord_step_stop", False)),
            "reset_after": max(0, int(self.parse_float_value(task.get("coord_step_reset_after", 0), 0.0))),
            "manual_points": parse_coord_step_manual_points(task.get("coord_step_manual_points", "{}"))
        }

    def _coord_step_key(self, step_info, base_x, base_y):
        return (int(step_info.get("step", 0)) if step_info else 0, int(base_x), int(base_y))

    def _coord_step_delta(self, options):
        direction = options.get("direction", "向下")
        distance = options.get("distance", 0.0)
        return coord_step_delta_values(direction, distance, options.get("dx", 0.0), options.get("dy", 0.0))

    def _get_coord_step_state(self, step_info, base_x, base_y):
        key = self._coord_step_key(step_info, base_x, base_y)
        if key not in self.coord_step_states:
            self.coord_step_states[key] = {
                "base_x": float(base_x), "base_y": float(base_y),
                "x": float(base_x), "y": float(base_y),
                "clicks_since_move": 0,
                "clicks_since_reset": 0,
                "offset_times": 0,
                "movement_locked": False
            }
        return key, self.coord_step_states[key]

    def _reset_coord_step_state(self, state):
        state["x"] = float(state.get("base_x", state.get("x", 0.0)))
        state["y"] = float(state.get("base_y", state.get("y", 0.0)))
        state["clicks_since_move"] = 0
        state["clicks_since_reset"] = 0
        state["offset_times"] = 0
        state["movement_locked"] = False

    def _advance_coord_step_state(self, state, options, step_info):
        reset_after = max(0, int(options.get("reset_after", 0)))
        state["clicks_since_reset"] = state.get("clicks_since_reset", 0) + 1
        if reset_after > 0 and state["clicks_since_reset"] >= reset_after:
            self._reset_coord_step_state(state)
            if self.log_level >= 2:
                self.log(f"       坐标步进已成功点击 {reset_after} 次，已重置到起点（{int(state['x'])}，{int(state['y'])}）")
            return "reset"

        if state.get("movement_locked"):
            return "locked_stop" if options.get("stop") else "locked"

        state["clicks_since_move"] += 1
        if state["clicks_since_move"] < options["every"]:
            return "ok"

        state["clicks_since_move"] = 0
        if options["direction"] == "移动到新点位":
            point = self.parse_coordinate(options.get("point", ""))
            if not point:
                if self.log_level >= 1:
                    self.log("<font color='red'>    -> 坐标步进的新点位格式错误，已停止本步进移动。</font>")
                state["movement_locked"] = True
                return "locked_stop" if options.get("stop") else "locked"

            total_points = options["max_steps"] if options["max_steps"] >= 2 else 2
            max_offset_times = total_points - 1
            if state["offset_times"] >= max_offset_times:
                state["movement_locked"] = True
                if self.log_level >= 1:
                    self.log(f"<font color='orange'>    -> 坐标步进已到达目标点位，本路径共 {total_points} 个点，后续不再移动。</font>")
                return "locked_stop" if options.get("stop") else "locked"

            next_index = state["offset_times"] + 1
            ratio = next_index / max_offset_times
            next_x = state["base_x"] + (float(point[0]) - state["base_x"]) * ratio
            next_y = state["base_y"] + (float(point[1]) - state["base_y"]) * ratio
            manual_point = options.get("manual_points", {}).get(next_index)
            if manual_point:
                next_x, next_y = manual_point
        else:
            if options["max_steps"] > 0 and state["offset_times"] >= options["max_steps"]:
                state["movement_locked"] = True
                if self.log_level >= 1:
                    self.log(f"<font color='orange'>    -> 坐标步进已达到最大偏移次数 {options['max_steps']}，后续不再移动。</font>")
                return "locked_stop" if options.get("stop") else "locked"

            dx, dy = self._coord_step_delta(options)
            next_x, next_y = state["x"] + dx, state["y"] + dy

        distance_from_base = ((next_x - state["base_x"]) ** 2 + (next_y - state["base_y"]) ** 2) ** 0.5
        if options["max_distance"] > 0 and distance_from_base > options["max_distance"]:
            state["movement_locked"] = True
            if self.log_level >= 1:
                self.log(f"<font color='orange'>    -> 坐标步进将超过最大偏移距离 {options['max_distance']:.1f}px，后续不再移动。</font>")
            return "locked_stop" if options.get("stop") else "locked"

        state["x"], state["y"] = next_x, next_y
        state["offset_times"] += 1
        return "moved"

    def coord_step_log_message(self, x, y, state, options):
        next_after = options["every"] - state["clicks_since_move"]
        if next_after <= 0:
            next_after = options["every"]
        reset_after = max(0, int(options.get("reset_after", 0)))
        reset_text = ""
        if reset_after > 0:
            reset_count = min(state.get("clicks_since_reset", 0) + 1, reset_after)
            reset_text = f"，重置计数 {reset_count}/{reset_after}"

        if options.get("direction") == "移动到新点位":
            total_points = options["max_steps"] if options["max_steps"] >= 2 else 2
            point_no = min(state["offset_times"] + 1, total_points)
            manual_text = "，手动修正点" if state["offset_times"] in options.get("manual_points", {}) else ""
            return f"       当前点击位置（{int(x)}，{int(y)}），为第{state['offset_times']}次偏移（第{point_no}/{total_points}个点位{manual_text}），将在第{next_after}次后进行下次偏移{reset_text}"

        return f"       当前点击位置（{int(x)}，{int(y)}），为第{state['offset_times']}次偏移，将在第{next_after}次后进行下次偏移{reset_text}"

    def perform_mouse_click(self, x, y, clickTimes, lOrR, indicator_text=""):
        pyautogui.moveTo(x, y, duration=self.move_duration)
        for _ in range(clickTimes):
            pyautogui.mouseDown(button=lOrR)
            time.sleep(self.click_hold)
            pyautogui.mouseUp(button=lOrR)
            if clickTimes > 1: time.sleep(0.02)

        self.report_click_indicator(x, y, indicator_text or f"{'左键' if lOrR == 'left' else '右键'}点击")

        if self.enable_dodge:
            pyautogui.moveTo(self.dodge_x1, self.dodge_y1, duration=0)
            if self.enable_double_dodge:
                time.sleep(self.double_dodge_wait)
                pyautogui.moveTo(self.dodge_x2, self.dodge_y2, duration=0)

    def mouseClick(self, clickTimes, lOrR, img_path, reTry, step_info=None, cache_key=None, task_conf=0.8, use_gray=True, point_limit_en=False, point_limit_count=0, coord_step_config=None, image_click_config=None):
        if step_info is None: step_info = {'step': 0, 'loop': 0, 'cmd': ''}
        start_time = time.time()
        
        waiting_logged = False
        coord = self.parse_coordinate(img_path)
        use_all_targets = (not coord and self.multi_target_mode == "全部匹配")
        try:
            point_limit_count = max(0, int(float(point_limit_count)))
        except:
            point_limit_count = 0
        point_limit_en = bool(point_limit_en) and not coord and point_limit_count > 0
        need_all_matches = not coord and (use_all_targets or point_limit_en)

        while True:
            if self.check_stop_flag(): return "stopped"
            if self.timeout_val > 0 and (time.time() - start_time > self.timeout_val): 
                if self.log_level >= 1:
                    self.log(f"<font color='orange'>    [超时] 循环#{step_info['loop']} 步{step_info['step']}: 等待目标超时</font>")
                return "timeout"

            if coord:
                if coord_step_config:
                    _step_key, coord_state = self._get_coord_step_state(step_info, coord[0], coord[1])
                    locations = [(coord_state["x"], coord_state["y"], 1.0, 1.0)]
                else:
                    coord_state = None
                    locations = [(coord[0], coord[1], 1.0, 1.0)]
                find_time = 0.0
            elif need_all_matches:
                find_start = time.time()
                locations = self.find_all_targets_optimized(img_path, cache_key, task_conf, use_gray)
                find_time = time.time() - find_start
            else:
                find_start = time.time()
                location_tuple = self.find_target_optimized(img_path, cache_key, task_conf, use_gray)
                find_time = time.time() - find_start
                locations = [(location_tuple[0], location_tuple[1], location_tuple[2], task_conf)] if location_tuple else []

            if locations:
                if not coord:
                    self.reset_recognition_miss(img_path, step_info)
                if point_limit_en:
                    locations = self._filter_point_limit_targets(locations, img_path, step_info, point_limit_en, point_limit_count)
                    if not locations:
                        if not coord:
                            self.record_recognition_miss(img_path, step_info)
                        if self.log_level >= 1:
                            self.log(f"<font color='orange'>    [跳过] 循环#{step_info['loop']} 步{step_info['step']}: 当前图片所有识别点位都已达到同点点击上限</font>")
                        return "not_found"

                click_locations = locations if use_all_targets else locations[:1]

                try:
                    if self.log_level >= 2:
                        local_t = time.strftime("%H:%M:%S")
                        self.log(f"    <font color='gray'>[{local_t}] => 底层找图耗时 {find_time:.3f}s</font>")

                    if use_all_targets:
                        if self.log_level >= 1:
                            self.log(f"    -> 共识别到 {len(click_locations)} 个可点击目标，按【{self.multi_target_order}】顺序执行点击")
                    elif self.log_level >= 1:
                        x, y, scale, _score = click_locations[0]
                        click_x, click_y = self.adjusted_image_click_point(img_path, click_locations[0], image_click_config)
                        if image_click_config:
                            self.log(f"    -> 已在坐标 ({int(x)}, {int(y)}) 锁定目标，实际点击图片内位置 ({int(click_x)}, {int(click_y)})")
                        else:
                            self.log(f"    -> 已在坐标 ({int(x)}, {int(y)}) 锁定目标并执行点击")

                    for target_idx, location_tuple in enumerate(click_locations, 1):
                        if self.check_stop_flag(): return "stopped"
                        x, y, scale, score = location_tuple
                        click_x, click_y = self.adjusted_image_click_point(img_path, location_tuple, image_click_config)
                        if use_all_targets and self.log_level >= 2:
                            if image_click_config:
                                self.log(f"       多目标 {target_idx}/{len(click_locations)} -> 命中中心({int(x)}, {int(y)})，点击({int(click_x)}, {int(click_y)})，相似度 {score:.3f} 缩放 {scale:.2f}x")
                            else:
                                self.log(f"       多目标 {target_idx}/{len(click_locations)} -> ({int(x)}, {int(y)}) 相似度 {score:.3f} 缩放 {scale:.2f}x")
                        if coord_step_config and coord_state and self.log_level >= 2:
                            self.log(self.coord_step_log_message(x, y, coord_state, coord_step_config))
                        click_label = ("左键" if lOrR == "left" else "右键") + ("双击" if clickTimes == 2 else "单击")
                        self.perform_mouse_click(click_x, click_y, clickTimes, lOrR, click_label)
                        if coord_step_config and coord_state:
                            step_result = self._advance_coord_step_state(coord_state, coord_step_config, step_info)
                            if step_result == "locked_stop":
                                if self.log_level >= 0:
                                    self.log("<font color='red'><b>    -> 坐标步进达到移动上限，已按设置停止脚本。</b></font>")
                                self.stop()
                                return "stopped"
                        if point_limit_en:
                            used_count = self._record_point_click(img_path, step_info, x, y)
                            if self.log_level >= 2:
                                self.log(f"       同点位已点击 {used_count}/{point_limit_count} 次")
                            
                except Exception as e: 
                    if self.log_level >= 1: self.log(f"<font color='red'>    [错误] 循环#{step_info['loop']} 步{step_info['step']}: {e}</font>")
                    return "error"
                return "success"
            else:
                if not coord:
                    self.record_recognition_miss(img_path, step_info)
                if reTry != -1:
                    if self.log_level >= 1:
                        self.log(f"<font color='orange'>    [未找到] 循环#{step_info['loop']} 步{step_info['step']}: 未能识别到目标图片 ({os.path.basename(img_path)})</font>")
                    return "not_found"
                else:
                    if not waiting_logged and self.log_level >= 1:
                        self.log(f"    -> 未发现目标，进入持续监听等待状态...")
                        waiting_logged = True
                    if not self.wait_recognition_interval(self.adaptive_extra_delay(img_path, step_info)):
                        return "stopped"
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
            return "error"
        
        if self.log_level >= 1:
            self.log(f"    -> 正在从 ({x1},{y1}) 拖拽到 ({x2},{y2})")
            
        pyautogui.moveTo(x1, y1, duration=self.move_duration)
        pyautogui.mouseDown(button=button)
        time.sleep(self.click_hold)
        pyautogui.moveTo(x2, y2, duration=max(self.move_duration, 0.3))
        pyautogui.mouseUp(button=button)
        self.report_click_indicator(x2, y2, "拖拽结束")
        return "success"

    def execute_task_once(self, cmd, val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en=False, point_limit_count=0, coord_step_config=None, image_click_config=None):
        status = "success"
        try:
            if cmd == 1.0: status = self.mouseClick(1, "left", val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en, point_limit_count, coord_step_config, image_click_config)
            elif cmd == 2.0: status = self.mouseClick(2, "left", val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en, point_limit_count, coord_step_config, image_click_config)
            elif cmd == 3.0: status = self.mouseClick(1, "right", val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en, point_limit_count, coord_step_config, image_click_config)
            elif cmd == 10.0: status = self.mouseDrag("left", val, step_info)
            elif cmd == 11.0: status = self.mouseDrag("right", val, step_info)
            elif cmd == 12.0:
                if self.log_level >= 1: self.log(f"    -> 触发弹窗提醒: {val}")
                ctypes.windll.user32.MessageBoxW(0, str(val), "脚本提醒", 0x00040000 | 0x00010000 | 0x00000040)
            elif cmd == 13.0:
                if self.log_level >= 1: self.log(f"    -> 触发停止指令，脚本即将终止。备注: {val}")
                self.stop()
            elif cmd == 14.0:
                if self.log_level >= 0:
                    self.log(f"<br><font color='#00BCD4' size='4'><b>🔊 声音提示: {val}</b></font><br>")
                try:
                    import winsound
                    winsound.MessageBeep(0x00000040)
                except: pass
            elif cmd == 8.0:
                coord = self.parse_coordinate(val)
                if coord:
                    loc = (coord[0], coord[1], 1.0)
                    find_time = 0.0
                else:
                    find_start = time.time()
                    loc = self.find_target_optimized(val, cache_key, task_conf, use_gray)
                    find_time = time.time() - find_start

                if loc:
                    x, y, scale = loc
                    if self.log_level >= 2:
                        local_t = time.strftime("%H:%M:%S")
                        self.log(f"    <font color='gray'>[{local_t}] => 底层找图耗时 {find_time:.3f}s，缩放: {scale:.2f}x</font>")
                    if self.log_level >= 1:
                        self.log(f"    -> 已悬停在坐标 ({int(x)}, {int(y)})")
                    pyautogui.moveTo(x, y, duration=self.move_duration)
                    self.report_click_indicator(x, y, "悬停")
                else:
                    status = "not_found"
                    if self.log_level >= 1:
                        self.log(f"<font color='orange'>    [异常] 循环#{step_info['loop']} 步{step_info['step']}: 悬停失败，未识别到目标</font>")
            elif cmd == 4.0:
                if self.log_level >= 1: self.log(f"    -> 正在输入文本: {val}")
                pyperclip.copy(str(val)); pyautogui.hotkey('ctrl', 'v'); time.sleep(0.2)
            elif cmd == 5.0:
                wait_time = float(val) / max(self.playback_speed, 0.1)
                if self.log_level >= 1: self.log(f"    -> 强制静默等待 {wait_time:.2f} 秒 (原录制设定 {val}s, 倍速 {self.playback_speed}x)...")
                t_end = time.time() + wait_time
                while time.time() < t_end:
                    if self.check_stop_flag(): return "stopped"
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
            if self.log_level >= 1:
                self.log(f"<font color='red'>    [严重异常] 循环#{step_info['loop']} 步{step_info['step']}: 执行崩溃 -> {step_e}</font>")
        return status

    def run_tasks(self, tasks, callback_msg=None, callback_status=None, callback_click_indicator=None):
        self.is_running = True
        self.stop_requested = False
        self.callback_msg = callback_msg
        self.callback_status = callback_status
        self.callback_click_indicator = callback_click_indicator
        
        self.img_cache = {}
        self.scaled_templates_cache = {}
        self.scale_options_cache = {}
        self.point_click_counts = {}
        self.coord_step_states = {}
        self.miss_streaks = {}
        self.last_target_positions = {}
        self.load_and_precompute(tasks)
        
        global_start_time = time.time()
        loop_count = 0

        try:
            while True:
                loop_count += 1
                
                if self.loop_end_round > 0 and loop_count > self.loop_end_round:
                    if self.log_level >= 0:
                        self.log(f"<font color='green'>>>> 提示: 已达到全局循环停止轮次 ({self.loop_end_round})，任务正常结束</font>")
                    break

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

                if loop_count < self.loop_start_round:
                    self.report_status(loop_count, 0, len(tasks), "等待循环范围")
                    if self.log_level >= 1:
                        self.log(f"<font color='gray'>循环 #{loop_count} 低于全局起始循环 {self.loop_start_round}，本轮不执行步骤。</font>")
                    continue

                self.report_status(loop_count, 0, len(tasks), "")

                idx = min(max(int(getattr(self, "start_step_index", 0)), 0), max(len(tasks) - 1, 0))
                while idx < len(tasks):
                    task = tasks[idx]
                    
                    if self.check_stop_flag():
                        if callback_msg: callback_msg("任务由看门狗终止")
                        return

                    step_loop_start = self.positive_int_value(task.get("step_loop_start", 1), 1)
                    step_loop_end = self.non_negative_int_value(task.get("step_loop_end", 0), 0)
                    if loop_count < step_loop_start:
                        if self.log_level >= 2:
                            self.log(f"<font color='gray'>循环 #{loop_count} 步 {idx+1} 尚未到起始循环 {step_loop_start}，跳过本步。</font>")
                        idx += 1
                        continue
                    if step_loop_end > 0 and loop_count > step_loop_end:
                        if self.log_level >= 2:
                            self.log(f"<font color='gray'>循环 #{loop_count} 步 {idx+1} 已超过结束循环 {step_loop_end}，跳过本步。</font>")
                        idx += 1
                        continue

                    cmd = task.get("type")
                    val = task.get("value")
                    retry = task.get("retry", 1)
                    no_skip_wait = self.as_bool(task.get("no_skip_wait", False))
                    try: success_skip = max(0, int(float(task.get("success_skip", 0))))
                    except: success_skip = 0
                    try: success_jump = max(0, int(float(task.get("success_jump", 0))))
                    except: success_jump = 0
                    try: fail_skip = max(0, int(float(task.get("fail_skip", 0))))
                    except: fail_skip = 0
                    try: fail_jump = max(0, int(float(task.get("fail_jump", 0))))
                    except: fail_jump = 0
                    point_limit_en = self.as_bool(task.get("point_limit_en", False)) and cmd in [1.0, 2.0, 3.0] and not self.parse_coordinate(val)
                    try: point_limit_count = max(0, int(float(task.get("point_limit_count", 0))))
                    except: point_limit_count = 0
                    coord_step_config = None
                    if cmd in [1.0, 2.0, 3.0] and self.parse_coordinate(val):
                        coord_step_config = self.coord_step_options(task)
                    image_click_config = None
                    if cmd in [1.0, 2.0, 3.0] and not self.parse_coordinate(val):
                        image_click_config = self.image_click_point_options(task)
                    
                    if task.get("custom_en", False):
                        try: task_conf = float(task.get("custom_conf", self.confidence))
                        except: task_conf = self.confidence
                        use_gray = bool(task.get("custom_gray", self.enable_grayscale))
                    else:
                        task_conf = self.confidence
                        use_gray = self.enable_grayscale
                        
                    cache_key = task.get('cache_key', f"{val}_{self.min_scale}_{self.max_scale}_{self.scale_step}_{use_gray}")

                    cmd_name = self.get_cmd_name(cmd)
                    repeat_mode = str(task.get("repeat_mode", "执行一次"))
                    try: repeat_count = max(1, int(float(task.get("repeat_count", 1))))
                    except: repeat_count = 1
                    try: fail_limit = max(1, int(float(task.get("fail_limit", 1))))
                    except: fail_limit = 1

                    target_successes = 1
                    if repeat_mode == "指定次数":
                        target_successes = repeat_count
                    elif repeat_mode == "无限重复":
                        target_successes = None

                    attempt = 0
                    success_count = 0
                    consecutive_failures = 0
                    step_failed_for_branch = False
                    step_wall_start = time.time()

                    while target_successes is None or success_count < target_successes:
                        if self.check_stop_flag(): return
                        if no_skip_wait and self.timeout_val > 0 and (time.time() - step_wall_start > self.timeout_val):
                            status = "timeout"
                            step_duration = time.time() - step_wall_start
                            if self.log_level >= 0:
                                self.log(f"<font color='orange'>循环 #{loop_count} 步 {idx+1} ({cmd_name}) 禁止跳过等待超时，耗时: {step_duration:.2f}s</font>")
                            if self.timeout_stop:
                                if self.log_level >= 0:
                                    self.log(f"<font color='red'><b>    -> [超时急停] 步骤 {idx+1} 达到单步超时，已停止全部循环。</b></font>")
                                self.stop()
                                return
                            step_failed_for_branch = True
                            break
                        attempt += 1

                        if target_successes is None:
                            attempt_label = f"{attempt}/∞"
                        elif target_successes > 1:
                            attempt_label = f"{success_count + 1}/{target_successes}"
                        else:
                            attempt_label = ""

                        status_cmd_name = f"{cmd_name} {attempt_label}".strip()
                        step_info = {'step': idx + 1, 'loop': loop_count, 'cmd': status_cmd_name}
                        self.report_status(loop_count, idx + 1, len(tasks), status_cmd_name)
                        step_start_time = time.time()

                        needs_recognition_wait = cmd in [1.0, 2.0, 3.0, 8.0] and not self.parse_coordinate(val)
                        extra_delay = self.adaptive_extra_delay(val, step_info) if needs_recognition_wait else 0.0
                        if (needs_recognition_wait or no_skip_wait) and not self.wait_recognition_interval(extra_delay):
                            return
                        status = self.execute_task_once(cmd, val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en, point_limit_count, coord_step_config, image_click_config)

                        step_duration = time.time() - step_start_time
                        if self.log_level >= 0:
                            status_str = "完成"
                            color = "gray"
                            if status == "success": status_str = "完成"; color = "gray"
                            elif status == "timeout":
                                status_str = "超时急停" if self.timeout_stop else "超时失败"
                                color = "red" if self.timeout_stop else "orange"
                            elif status == "not_found":
                                status_str = "未找目标，继续等待" if no_skip_wait else "未找目标失败"
                                color = "orange"
                            elif status == "error": status_str = "执行异常"; color = "red"
                            elif status == "stopped": status_str = "已停止"; color = "red"

                            repeat_suffix = f" 第{attempt_label}次" if attempt_label else ""
                            self.log(f"<font color='{color}'>循环 #{loop_count} 步 {idx+1} ({cmd_name}){repeat_suffix} {status_str}，耗时: {step_duration:.2f}s</font>")

                        if status == "stopped":
                            return

                        if status == "timeout" and self.timeout_stop:
                            if self.log_level >= 0:
                                self.log(f"<font color='red'><b>    -> [超时急停] 步骤 {idx+1} 达到单步超时，已停止全部循环。</b></font>")
                            self.stop()
                            return

                        if status in ["timeout", "not_found", "error"]:
                            if no_skip_wait and status != "timeout":
                                if self.log_level >= 1:
                                    self.log(f"    -> 本步骤已启用禁止跳过，将继续等待本步骤成功。")
                                if not self.is_wait_command(cmd) and not self.wait_step_interval():
                                    return
                                continue
                            consecutive_failures += 1
                            if consecutive_failures >= fail_limit:
                                step_failed_for_branch = True
                                if self.log_level >= 0:
                                    self.log(f"<font color='#9C27B0'><b>    -> [条件分支] 步骤 {idx+1} 连续失败 {consecutive_failures} 次，结束本步。</b></font>")
                                break
                        else:
                            success_count += 1
                            consecutive_failures = 0

                        if target_successes is None or success_count < target_successes:
                            if not self.is_wait_command(cmd) and not self.wait_step_interval():
                                return

                    next_idx = idx + 1
                    if step_failed_for_branch:
                        if fail_jump > 0:
                            next_idx = fail_jump - 1
                            if self.log_level >= 0:
                                self.log(f"<font color='#9C27B0'><b>    -> [条件分支] 失败后跳至第 {fail_jump} 步继续执行</b></font>")
                        elif fail_skip > 0:
                            next_idx = idx + fail_skip + 1
                            if self.log_level >= 0:
                                self.log(f"<font color='#9C27B0'><b>    -> [条件分支] 失败后跳过后续 {fail_skip} 步指令</b></font>")
                    else:
                        if success_jump > 0:
                            next_idx = success_jump - 1
                            if self.log_level >= 0:
                                self.log(f"<font color='#4CAF50'><b>    -> [条件分支] 成功后跳至第 {success_jump} 步继续执行</b></font>")
                        elif success_skip > 0:
                            next_idx = idx + success_skip + 1
                            if self.log_level >= 0:
                                self.log(f"<font color='#4CAF50'><b>    -> [条件分支] 成功后跳过后续 {success_skip} 步指令</b></font>")

                    if self.should_wait_step_interval(tasks, cmd, next_idx, loop_count):
                        if not self.wait_step_interval():
                            return

                    idx = next_idx

                if self.check_stop_flag(): return
                
        except Exception as e:
            self.log(f"<font color='red'>引擎异常: {e}</font>")
        finally:
            self.is_running = False
            self.callback_status = None
            self.callback_click_indicator = None
            if callback_msg: callback_msg("结束")

# --------------------------
# GUI 界面
# --------------------------
class WorkerThread(QThread):
    log_signal = Signal(str)
    status_signal = Signal(dict)
    click_signal = Signal(dict)
    finished_signal = Signal()
    def __init__(self, engine, tasks):
        super().__init__()
        self.engine = engine
        self.tasks = tasks

    def run(self):
        self.watchdog = FailsafeWatchdog(self.engine)
        self.watchdog.start()
        self.engine.run_tasks(self.tasks, self.log_callback, self.status_callback, self.click_callback)
        if self.watchdog: self.watchdog.kill()
        self.finished_signal.emit()

    def log_callback(self, msg): 
        if GLOBAL_CONFIG["log_to_ui"]:
            self.log_signal.emit(msg)

    def status_callback(self, data):
        self.status_signal.emit(data)

    def click_callback(self, data):
        self.click_signal.emit(data)

class TaskRow(QFrame):
    def __init__(self, delete_callback):
        super().__init__()
        self.parent_item = None
        self.custom_data = {
            "custom_en": False,
            "custom_conf": "0.8",
            "custom_scale_min": "1.0",
            "custom_scale_max": "1.0",
            "custom_scale_step": "0.05",
            "custom_gray": True,
            "repeat_mode": "执行一次",
            "repeat_count": "1",
            "step_loop_start": "1",
            "step_loop_end": "0",
            "fail_limit": "1",
            "success_skip": "0",
            "success_jump": "0",
            "fail_skip": "0",
            "fail_jump": "0",
            "no_skip_wait": False,
            "point_limit_en": False,
            "point_limit_count": "0",
            "image_click_point_en": False,
            "image_click_point_rx": "0.5",
            "image_click_point_ry": "0.5",
            "coord_step_en": False,
            "coord_step_every": "1",
            "coord_step_direction": "向下",
            "coord_step_distance": "0",
            "coord_step_dx": "0",
            "coord_step_dy": "0",
            "coord_step_point": "",
            "coord_step_max_steps": "0",
            "coord_step_max_distance": "0",
            "coord_step_stop": False,
            "coord_step_reset_after": "0",
            "coord_step_manual_points": "{}"
        }
        
        self.setFrameShape(QFrame.StyledPanel)
        self.set_selected(False)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)
        
        self.index_label = QLabel("1.")
        self.index_label.setFixedWidth(25)
        self.index_label.setAlignment(Qt.AlignCenter)
        self.index_label.setStyleSheet("color: gray; font-weight: bold;")
        self.layout.addWidget(self.index_label)

        self.manual_mark_label = QLabel("修")
        self.manual_mark_label.setFixedWidth(18)
        self.manual_mark_label.setAlignment(Qt.AlignCenter)
        self.manual_mark_label.setToolTip("本步骤包含坐标步进手动修正点")
        self.manual_mark_label.setStyleSheet("color: white; background-color: #9C27B0; border-radius: 4px; font-weight: bold;")
        self.manual_mark_label.hide()
        self.layout.addWidget(self.manual_mark_label)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "左键单击", "左键双击", "右键单击", "输入文本", "等待(秒)", 
            "滚轮滑动", "系统按键", "鼠标悬停", "截图保存", "左键拖拽", 
            "右键拖拽", "弹窗提醒", "停止运行", "声音提示"
        ])
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        self.layout.addWidget(self.type_combo)
        
        self.value_input = QLineEdit()
        self.value_input.textChanged.connect(self.sync_data)
        self.layout.addWidget(self.value_input)
        
        self.file_btn = QPushButton("图")
        self.file_btn.setFixedWidth(30)
        self.file_btn.clicked.connect(self.select_file)
        self.layout.addWidget(self.file_btn)

        self.pick_btn = QPushButton("取")
        self.pick_btn.setFixedWidth(30)
        self.pick_btn.setToolTip("选取屏幕坐标\n单击/悬停：左键单击目标位置\n拖拽：按住左键拖动并松开\n右键取消")
        self.pick_btn.clicked.connect(self.start_coordinate_pick)
        self.layout.addWidget(self.pick_btn)
        
        self.cfg_btn = QPushButton("⚙️")
        self.cfg_btn.setFixedWidth(30)
        self.cfg_btn.setToolTip("步骤设置\n包含图片识别参数、重复次数、同点点击上限和条件分支")
        self.cfg_btn.clicked.connect(self.open_custom_config)
        self.layout.addWidget(self.cfg_btn)
        
        self.del_btn = QPushButton("X")
        self.del_btn.setStyleSheet("color: red; font-weight: bold;")
        self.del_btn.setFixedWidth(25)
        self.del_btn.clicked.connect(lambda: delete_callback(self))
        self.layout.addWidget(self.del_btn)
        
        self.on_type_changed(self.type_combo.currentText())

    def set_parent_item(self, item):
        self.parent_item = item
        self.sync_data() 

    def set_selected(self, selected):
        if selected:
            self.setStyleSheet("TaskRow { background-color: #D9ECFF; border: 2px solid #2196F3; border-radius: 4px; }")
        else:
            self.setStyleSheet("TaskRow { background-color: transparent; border: 1px solid #CFCFCF; border-radius: 4px; }")

    def sync_data(self):
        text = self.type_combo.currentText()
        coord_mode = self.is_direct_coordinate_value(text)
        self.update_manual_marker()
        if "单击" in text or "双击" in text or "悬停" in text:
            self.cfg_btn.setVisible(True)
            if coord_mode:
                self.cfg_btn.setToolTip("步骤设置\n当前参数是屏幕坐标，图片识别参数会自动忽略；重复和条件分支仍然生效")
            else:
                self.cfg_btn.setToolTip("步骤设置\n包含图片识别参数、图片内点击点、重复次数、同点点击上限和条件分支")
        else:
            self.cfg_btn.setVisible(True)
            self.cfg_btn.setToolTip("步骤设置\n包含重复次数和条件分支")

        self.pick_btn.setVisible(self.is_coordinate_pickable(text))
            
        if getattr(self, 'parent_item', None):
            self.parent_item.setData(Qt.UserRole, self.get_data())
            self.parent_item.setData(Qt.UserRole + 1, self.drag_summary())
            self.parent_item.setText("")

    def drag_summary(self):
        value = self.value_input.text().replace("\n", " ").strip()
        if len(value) > 80:
            value = value[:77] + "..."
        mark = " [修]" if self.has_coord_step_manual_points() else ""
        return f"{self.index_label.text()}{mark} {self.type_combo.currentText()} | {value}"

    def has_coord_step_manual_points(self):
        return (
            config_bool(self.custom_data.get("coord_step_en", False))
            and str(self.custom_data.get("coord_step_direction", "")) == "移动到新点位"
            and bool(parse_coord_step_manual_points(self.custom_data.get("coord_step_manual_points", "{}")))
        )

    def update_manual_marker(self):
        self.manual_mark_label.setVisible(self.has_coord_step_manual_points())

    def is_coordinate_pickable(self, text=None):
        if text is None:
            text = self.type_combo.currentText()
        return text in ["左键单击", "左键双击", "右键单击", "左键拖拽", "右键拖拽", "鼠标悬停"]

    def parse_direct_coordinate(self, val):
        try:
            parts = str(val).strip().split(',')
            if len(parts) == 2:
                int(parts[0].strip())
                int(parts[1].strip())
                return True
        except: pass
        return False

    def direct_coordinate_tuple(self):
        return parse_coordinate_text(self.value_input.text())

    def is_direct_coordinate_value(self, text=None):
        if text is None:
            text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击", "鼠标悬停"]:
            return False
        return self.parse_direct_coordinate(self.value_input.text())

    def start_coordinate_pick(self):
        text = self.type_combo.currentText()
        if not self.is_coordinate_pickable(text):
            return
        mode = "drag" if "拖拽" in text else "point"
        self.coordinate_picker = CoordinatePickerUI(mode, self.on_coordinate_picked)

    def on_coordinate_picked(self, value):
        self.value_input.setText(value)
        self.sync_data()

    def open_custom_config(self):
        if getattr(self, "config_dialog", None) and self.config_dialog.isVisible():
            self.config_dialog.show()
            self.config_dialog.raise_()
            self.config_dialog.activateWindow()
            return

        self._config_original_value = self.value_input.text()
        dialog = TaskConfigDialog(
            None,
            self.custom_data,
            self.image_settings_available(),
            self.point_limit_available(),
            self.coordinate_step_available(),
            self.direct_coordinate_tuple(),
            self.value_input.text().strip(),
            self.image_click_point_available(),
            self.on_config_base_coordinate_changed
        )
        self.config_dialog = dialog
        dialog.accepted.connect(lambda d=dialog: self.apply_custom_config(d))
        dialog.finished.connect(lambda result, d=dialog: self.clear_custom_config_dialog(d, result))
        main_window = self.window()
        if hasattr(main_window, "apply_ui_scale_to_widget"):
            main_window.apply_ui_scale_to_widget(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def apply_custom_config(self, dialog):
        self.custom_data = dialog.get_data()
        self.sync_data()

    def on_config_base_coordinate_changed(self, value):
        self.value_input.setText(str(value))
        if getattr(self, "config_dialog", None):
            self.config_dialog.base_coordinate = parse_coordinate_text(value)
            self.config_dialog.update_coord_step_ui()
        self.sync_data()

    def clear_custom_config_dialog(self, dialog, result=None):
        if result != QDialog.Accepted and hasattr(self, "_config_original_value"):
            self.value_input.setText(self._config_original_value)
            self.sync_data()
        if hasattr(self, "_config_original_value"):
            del self._config_original_value
        if getattr(self, "config_dialog", None) is dialog:
            self.config_dialog = None
        dialog.deleteLater()

    def image_settings_available(self):
        text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击", "鼠标悬停"]:
            return False
        return not self.is_direct_coordinate_value(text)

    def point_limit_available(self):
        text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击"]:
            return False
        return not self.is_direct_coordinate_value(text)

    def image_click_point_available(self):
        text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击"]:
            return False
        if self.is_direct_coordinate_value(text):
            return False
        return os.path.isfile(self.value_input.text().strip())

    def coordinate_step_available(self):
        text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击"]:
            return False
        return self.is_direct_coordinate_value(text)

    def on_type_changed(self, text):
        tips = {
            "左键单击": ("【左键单击】\n识别目标图片并点击其中心，或直接点击指定屏幕坐标。\n参数格式：图片完整路径 或 屏幕坐标，如：100,100", "输入图片路径 或 屏幕坐标，如：960,540"),
            "左键双击": ("【左键双击】\n识别目标图片并双击其中心，或直接双击指定屏幕坐标。\n参数格式：图片完整路径 或 屏幕坐标，如：100,100", "输入图片路径 或 屏幕坐标，如：960,540"),
            "右键单击": ("【右键单击】\n识别目标图片并右击其中心，或直接右击指定屏幕坐标。\n参数格式：图片完整路径 或 屏幕坐标，如：100,100", "输入图片路径 或 屏幕坐标，如：960,540"),
            "输入文本": ("【输入文本】\n模拟键盘自动输入文本内容（支持中文）。\n参数格式：任意想要输入的文字内容", "输入想要发送的文本内容，如：Hello"),
            "等待(秒)": ("【等待(秒)】\n强行让脚本暂停执行一段时间，受倍速设置影响。\n参数格式：纯数字，如：1.5 或 3", "输入等待的秒数，如：1.5"),
            "滚轮滑动": ("【滚轮滑动】\n模拟鼠标滚轮上下滚动。\n参数格式：纯数字（正数向上滚，负数向下滚），如：500 或 -500", "输入滚动距离，如：500 或 -500"),
            "系统按键": ("【系统按键】\n模拟敲击键盘单键或组合快捷键。\n参数格式：单键(如 A, enter, esc) 或 组合键(如 ctrl+c, alt+tab)", "输入按键或组合，如：A、enter 或 ctrl+v"),
            "鼠标悬停": ("【鼠标悬停】\n将鼠标移动到指定图片或坐标上方，不进行点击。\n参数格式：图片完整路径 或 屏幕坐标，如：100,100", "输入图片路径 或 屏幕坐标，如：960,540"),
            "截图保存": ("【截图保存】\n将当前整个屏幕或设定的识别区域截图并保存。\n参数格式：保存的文件夹目录 或 具体的.png文件路径", "输入保存目录，如：D:\\Screenshots"),
            "左键拖拽": ("【左键拖拽】\n按住鼠标左键，从起点拖动到终点。\n参数格式：起点 -> 终点。例如：100,100 -> 500,500", "输入轨迹坐标，如：100,100 -> 500,500"),
            "右键拖拽": ("【右键拖拽】\n按住鼠标右键，从起点拖动到终点。\n参数格式：起点 -> 终点。例如：100,100 -> 500,500", "输入轨迹坐标，如：100,100 -> 500,500"),
            "弹窗提醒": ("【弹窗提醒】\n暂停脚本并弹出一个系统强制定顶提示框，点击确定后继续。\n参数格式：你想提示的文字内容", "输入你想提示的文字，如：任务已完成"),
            "停止运行": ("【停止运行】\n执行到此步时，直接强行停止整个脚本的运行。\n参数格式：停止时的日志备注（可选）", "输入停止备注，如：条件满足，中止运行"),
            "声音提示": ("【声音提示】\n播放系统提示音，并在日志中醒目显示备注，不打断操作。\n参数格式：任意内容（作为日志醒目备注）", "输入大号日志备注，如：发现目标！")
        }

        if text in tips:
            self.type_combo.setToolTip(tips[text][0])
            self.value_input.setToolTip(tips[text][0])
            self.value_input.setPlaceholderText(tips[text][1])

        if "截图" in text:
            self.file_btn.setVisible(True)
            self.file_btn.setText("夹")
            self.file_btn.setToolTip("选择保存截图的文件夹目录")
        elif "单击" in text or "双击" in text or "悬停" in text:
            self.file_btn.setVisible(True)
            self.file_btn.setText("图")
            self.file_btn.setToolTip("选择本地图片\n性能建议：尽量截取小而独特的目标图片，少包含背景，可降低CPU匹配压力并减少误识别")
        else:
            self.file_btn.setVisible(False)

        self.sync_data()
            
    def set_data(self, data):
        self.value_input.setText(str(data.get("value", "")))
        
        self.custom_data = {
            "custom_en": data.get("custom_en", False),
            "custom_conf": data.get("custom_conf", "0.8"),
            "custom_scale_min": data.get("custom_scale_min", "1.0"),
            "custom_scale_max": data.get("custom_scale_max", "1.0"),
            "custom_scale_step": data.get("custom_scale_step", "0.05"),
            "custom_gray": data.get("custom_gray", True),
            "repeat_mode": data.get("repeat_mode", "执行一次"),
            "repeat_count": data.get("repeat_count", "1"),
            "step_loop_start": data.get("step_loop_start", "1"),
            "step_loop_end": data.get("step_loop_end", "0"),
            "fail_limit": data.get("fail_limit", "1"),
            "success_skip": data.get("success_skip", "0"),
            "success_jump": data.get("success_jump", "0"),
            "fail_skip": data.get("fail_skip", "0"),
            "fail_jump": data.get("fail_jump", "0"),
            "no_skip_wait": data.get("no_skip_wait", False),
            "point_limit_en": data.get("point_limit_en", False),
            "point_limit_count": data.get("point_limit_count", "0"),
            "image_click_point_en": data.get("image_click_point_en", False),
            "image_click_point_rx": data.get("image_click_point_rx", "0.5"),
            "image_click_point_ry": data.get("image_click_point_ry", "0.5"),
            "coord_step_en": data.get("coord_step_en", False),
            "coord_step_every": data.get("coord_step_every", "1"),
            "coord_step_direction": data.get("coord_step_direction", "向下"),
            "coord_step_distance": data.get("coord_step_distance", "0"),
            "coord_step_dx": data.get("coord_step_dx", "0"),
            "coord_step_dy": data.get("coord_step_dy", "0"),
            "coord_step_point": data.get("coord_step_point", ""),
            "coord_step_max_steps": data.get("coord_step_max_steps", "0"),
            "coord_step_max_distance": data.get("coord_step_max_distance", "0"),
            "coord_step_stop": data.get("coord_step_stop", False),
            "coord_step_reset_after": data.get("coord_step_reset_after", "0"),
            "coord_step_manual_points": data.get("coord_step_manual_points", "{}")
        }
        self.update_manual_marker()
        
        TYPES_REV = {
            1.0: "左键单击", 2.0: "左键双击", 3.0: "右键单击", 4.0: "输入文本", 
            5.0: "等待(秒)", 6.0: "滚轮滑动", 7.0: "系统按键", 8.0: "鼠标悬停", 
            9.0: "截图保存", 10.0: "左键拖拽", 11.0: "右键拖拽", 12.0: "弹窗提醒", 
            13.0: "停止运行", 14.0: "声音提示"
        }
        t = data.get("type", 1.0)
        if t in TYPES_REV:
            self.type_combo.setCurrentText(TYPES_REV[t])

    def select_file(self):
        cmd_type = self.get_data()["type"]
        if cmd_type == 9.0: 
            folder = QFileDialog.getExistingDirectory(self, "选择保存文件夹", os.getcwd())
            if folder: self.value_input.setText(folder)
        else: 
            path, _ = QFileDialog.getOpenFileName(self, "选择", filter="Images (*.png *.jpg *.bmp)")
            if path: self.value_input.setText(path)

    def get_data(self):
        TYPES = {
            "左键单击": 1.0, "左键双击": 2.0, "右键单击": 3.0, "输入文本": 4.0, 
            "等待(秒)": 5.0, "滚轮滑动": 6.0, "系统按键": 7.0, "鼠标悬停": 8.0, 
            "截图保存": 9.0, "左键拖拽": 10.0, "右键拖拽": 11.0, "弹窗提醒": 12.0, 
            "停止运行": 13.0, "声音提示": 14.0
        }
        val = self.value_input.text()
        t = TYPES.get(self.type_combo.currentText(), 1.0)
        if t in [5.0, 6.0] and not val: val = "0"
        
        data_dict = {"type": t, "value": val}
        data_dict.update(self.custom_data)
        if self.is_direct_coordinate_value(self.type_combo.currentText()):
            data_dict["custom_en"] = False
            data_dict["point_limit_en"] = False
            data_dict["image_click_point_en"] = False
        else:
            data_dict["coord_step_en"] = False
            data_dict["coord_step_manual_points"] = "{}"
            if not self.image_click_point_available():
                data_dict["image_click_point_en"] = False
        return data_dict

    def set_index(self, index):
        self.index_label.setText(f"{index}.")

class DraggableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDropIndicatorShown(False)
        self.drop_line_row = None
        self.drop_line_after = False

    def _event_pos(self, event):
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _update_drop_line(self, event):
        pos = self._event_pos(event)
        item = self.itemAt(pos)
        if item is None:
            self.drop_line_row = self.count() - 1 if self.count() else 0
            self.drop_line_after = True
            self.viewport().update()
            return

        row = self.row(item)
        rect = self.visualItemRect(item)
        self.drop_line_row = row
        self.drop_line_after = pos.y() > rect.center().y()
        self.viewport().update()

    def dragMoveEvent(self, event):
        self._update_drop_line(event)
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.drop_line_row = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.drop_line_row is None or self.count() == 0:
            return

        row = max(0, min(self.drop_line_row, self.count() - 1))
        rect = self.visualItemRect(self.item(row))
        y = rect.bottom() + 1 if self.drop_line_after else rect.top()

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QPen(QColor(255, 255, 255), 12, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(6, y, self.viewport().width() - 6, y)
        painter.setPen(QPen(QColor(0, 0, 0), 8, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(6, y, self.viewport().width() - 6, y)

    def _drag_preview_pixmap(self, item):
        widget = self.itemWidget(item)
        if widget:
            pixmap = widget.grab()
            if not pixmap.isNull():
                return pixmap

        summary = item.data(Qt.UserRole + 1) or item.text() or "正在移动步骤"
        preview_width = max(260, min(self.viewport().width() - 12, 900))
        preview_height = max(44, min(item.sizeHint().height(), 72))

        pixmap = QPixmap(preview_width, preview_height)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(245, 250, 255, 245))
        painter.setPen(QPen(QColor(33, 150, 243), 2))
        painter.drawRoundedRect(QRect(1, 1, preview_width - 2, preview_height - 2), 5, 5)

        text_rect = QRect(14, 0, preview_width - 28, preview_height)
        text = painter.fontMetrics().elidedText(summary, Qt.ElideRight, text_rect.width())
        painter.setPen(QColor(30, 30, 30))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.end()
        return pixmap

    def startDrag(self, supported_actions):
        selected_items = self.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(selected_items))

        pixmap = self._drag_preview_pixmap(item)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            rect = self.visualItemRect(item)
            cursor_pos = self.viewport().mapFromGlobal(QCursor.pos())
            if rect.isValid() and rect.contains(cursor_pos):
                hotspot = cursor_pos - rect.topLeft()
                hotspot.setX(max(1, min(hotspot.x(), pixmap.width() - 1)))
                hotspot.setY(max(1, min(hotspot.y(), pixmap.height() - 1)))
            else:
                hotspot = QPoint(min(36, pixmap.width() // 2), pixmap.height() // 2)
            drag.setHotSpot(hotspot)

        drag.exec(Qt.MoveAction)
        self.drop_line_row = None
        self.viewport().update()

    def dropEvent(self, event):
        if hasattr(self.window(), 'push_undo_state'):
            self.window().push_undo_state()
        super().dropEvent(event)
        self.drop_line_row = None
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
        self.setWindowTitle("RPA配置工具（浮夸改v1.5 精简版）")
        self.resize(800, 850)
        self.engine = RPAEngine()
        
        self.config_path = os.path.join(get_base_dir(), "config.ini")
        self.settings = QSettings(self.config_path, QSettings.IniFormat)
        self.ui_base_font = QFont(QApplication.font())
        self.ui_scale = 1.0
        self.recorder_ui = None
        self.all_points_preview = None
        self.click_indicator_overlays = []
        
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        self.profiles_data = {}
        self.current_profile_name = "默认方案"
        self.is_switching_profile = True 
        
        self.hotkey_start_vk = 0x78 
        self.hotkey_stop_vk = 0x79  
        self.global_hotkeys_registered = False
        self.current_process = None
        self.running_overlay = None
        self.task_clipboard = None
        self.undo_stack = []
        self.redo_stack = []
        self.restoring_history = False
        if HAS_PSUTIL:
            try: self.current_process = psutil.Process()
            except: pass
            
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        # ================= 顶部方案管理与工具栏 (完全恢复老版本经典结构) =================
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
        prof_up_btn.clicked.connect(self.move_profile_up)
        profile_layout.addWidget(prof_up_btn)
        
        prof_down_btn = QPushButton("↓")
        prof_down_btn.setFixedWidth(25)
        prof_down_btn.clicked.connect(self.move_profile_down)
        profile_layout.addWidget(prof_down_btn)
        
        profile_layout.addStretch()

        settings_btn = QPushButton("⚙ 设置")
        settings_btn.setToolTip("打开全局设置、方案导入导出和配置目录")
        settings_btn.clicked.connect(self.show_settings_dialog)
        profile_layout.addWidget(settings_btn)
        
        main_layout.addLayout(profile_layout)
        
        top_bar = QHBoxLayout()
        add_btn = QPushButton("+ 新增指令")
        add_btn.clicked.connect(lambda: self.add_row())
        top_bar.addWidget(add_btn)

        insert_btn = QPushButton("插入")
        insert_btn.setToolTip("在当前选中步骤前插入一条新指令")
        insert_btn.clicked.connect(self.insert_row_before_selected)
        top_bar.addWidget(insert_btn)

        redo_btn = QPushButton("重做")
        redo_btn.setToolTip("恢复刚撤销的步骤列表操作 (Ctrl+Y)")
        redo_btn.clicked.connect(self.redo_task_change)
        top_bar.addWidget(redo_btn)
        
        record_btn = QPushButton("⏺ 操作录制")
        record_btn.setStyleSheet("color: #E91E63; font-weight: bold;")
        record_btn.clicked.connect(self.start_recording)
        top_bar.addWidget(record_btn)
        
        region_btn = QPushButton("📷 设定识别区域")
        region_btn.setStyleSheet("background-color: #9C27B0; color: white; font-weight: bold;")
        region_btn.clicked.connect(self.open_region_selector)
        top_bar.addWidget(region_btn)

        preview_points_btn = QPushButton("预览坐标点")
        preview_points_btn.setToolTip("在屏幕上预览当前脚本中所有直接坐标点击点；仅统计坐标点击，不识别图片。")
        preview_points_btn.clicked.connect(self.show_all_coordinate_click_preview)
        top_bar.addWidget(preview_points_btn)
        
        top_bar.addWidget(HelpBtn("【设定识别区域】\n如CPU占用较高，务必使用此功能。\n左键拖拽框选一个或多个区域，右键完成。\n多区域适合目标分散在几个相距较远的小区域，且这些区域总面积只占屏幕很小一部分的情况。\n如果几个区域相隔很近，通常框成一个较大的单区域更快、更稳定。"))
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        # ================= 设置窗口 =================
        self.settings_dialog = FloatingSettingsDialog(self.settings, "settings_dialog_geometry", "设置", (760, 620))
        settings_outer = QVBoxLayout(self.settings_dialog)

        settings_action_bar = QHBoxLayout()
        save_btn = QPushButton("导出方案")
        save_btn.clicked.connect(self.save)
        settings_action_bar.addWidget(save_btn)
        load_btn = QPushButton("导入方案")
        load_btn.clicked.connect(self.load)
        settings_action_bar.addWidget(load_btn)
        open_dir_btn = QPushButton("打开配置目录")
        open_dir_btn.clicked.connect(self.open_config_dir)
        settings_action_bar.addWidget(open_dir_btn)
        settings_action_bar.addStretch()
        settings_outer.addLayout(settings_action_bar)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_body = QWidget()
        settings_content_layout = QVBoxLayout(settings_body)
        settings_content_layout.setContentsMargins(4, 4, 4, 4)
        settings_content_layout.setSpacing(8)
        settings_scroll.setWidget(settings_body)
        settings_outer.addWidget(settings_scroll)

        settings_close_btns = QDialogButtonBox(QDialogButtonBox.Close)
        settings_close_btns.rejected.connect(self.close_settings_dialog)
        settings_close_btns.button(QDialogButtonBox.Close).clicked.connect(self.close_settings_dialog)
        settings_outer.addWidget(settings_close_btns)

        # ================= 核心折叠设置区 =================
        # 1. 识别配置
        g1 = CollapsibleSection("全局识别配置")
        gl1_wrap = QVBoxLayout()
        gl1 = QHBoxLayout()
        gl1.addWidget(QLabel("相似:"))
        self.conf_edit = QLineEdit("0.8"); self.conf_edit.setFixedWidth(70); gl1.addWidget(self.conf_edit)
        gl1.addWidget(HelpBtn("【相似度 (0.1 - 1.0)】\n数值越低：越容易匹配，但极易导致乱点误触。\n数值越高：越精确。"))
        gl1.addSpacing(15)
        gl1.addWidget(QLabel("缩放:"))
        self.scale_min = QLineEdit("0.8"); self.scale_min.setFixedWidth(70); gl1.addWidget(self.scale_min)
        gl1.addWidget(QLabel("-")); 
        self.scale_max = QLineEdit("1.2"); self.scale_max.setFixedWidth(70); gl1.addWidget(self.scale_max)
        gl1.addWidget(HelpBtn("【缩放范围】\n程序启动时会预先生成缩放模板缓存。建议不要超过 0.8 - 2.0。"))
        gl1.addSpacing(15)
        gl1.addWidget(QLabel("步长:")); 
        self.scale_step = QLineEdit("0.05"); self.scale_step.setFixedWidth(70); gl1.addWidget(self.scale_step)
        gl1.addWidget(HelpBtn("【缩放步长】\n默认值 0.05，调低会增加CPU压力。"))
        gl1.addSpacing(15)
        self.gray_chk = QCheckBox("全局灰度匹配 (极速)"); self.gray_chk.setChecked(True); gl1.addWidget(self.gray_chk)
        gl1.addWidget(HelpBtn("【灰度匹配】\n开启后极快且省CPU。如果两张图形状一样颜色不同，请关闭！"))
        gl1.addStretch()
        gl1_native = QHBoxLayout()
        self.native_core_chk = QCheckBox("启用DLL原生识别")
        self.native_core_chk.setChecked(True)
        self.native_core_chk.setToolTip("开启后优先使用内置 water_rpa_core.dll 做图片识别；不可用或不适合时自动回退到原来的 OpenCV/Python 识别。")
        gl1_native.addWidget(self.native_core_chk)
        gl1_native.addWidget(HelpBtn("【DLL原生识别】\n开启后，图片点击/悬停会优先尝试使用内置 C++ DLL 识别核心，通常可降低部分识别场景的 CPU 压力并提高速度。\n如果遇到兼容性问题、识别结果异常，或想对比旧版效果，可以关闭；关闭后完全使用原来的 OpenCV/Python 识别路径。\nDLL 加载失败时会自动回退，不会影响脚本启动。"))
        gl1_native.addStretch()
        gl1_wrap.addLayout(gl1)
        gl1_wrap.addLayout(gl1_native)
        if SLIM_BUILD:
            self.scale_min.setText("1.0")
            self.scale_max.setText("1.0")
            self.scale_step.setText("0.05")
            self.gray_chk.setChecked(False)
            self.native_core_chk.setChecked(False)
            for widget in [self.scale_min, self.scale_max, self.scale_step, self.gray_chk, self.native_core_chk]:
                widget.setEnabled(False)
            slim_note = QLabel("精简版：已移除缩放识别、灰度识别、DLL 原生识别、OpenCV/NumPy 运行库，仅按原图原尺寸精确匹配。")
            slim_note.setStyleSheet("color: #666;")
            slim_note.setWordWrap(True)
            gl1_wrap.addWidget(slim_note)
        g1.set_content_layout(gl1_wrap)
        settings_content_layout.addWidget(g1)
        
        # 2. 避让设置
        g_dodge = CollapsibleSection("避让设置")
        gl_dodge = QHBoxLayout()
        gl_dodge.addWidget(QLabel("坐标1 X:"))
        self.dodge_x1 = QLineEdit("100"); self.dodge_x1.setFixedWidth(70); gl_dodge.addWidget(self.dodge_x1)
        gl_dodge.addWidget(QLabel("Y:"))
        self.dodge_y1 = QLineEdit("100"); self.dodge_y1.setFixedWidth(70); gl_dodge.addWidget(self.dodge_y1)
        gl_dodge.addSpacing(15)
        gl_dodge.addWidget(QLabel("坐标2 X:"))
        self.dodge_x2 = QLineEdit("200"); self.dodge_x2.setFixedWidth(70); gl_dodge.addWidget(self.dodge_x2)
        gl_dodge.addWidget(QLabel("Y:"))
        self.dodge_y2 = QLineEdit("100"); self.dodge_y2.setFixedWidth(70); gl_dodge.addWidget(self.dodge_y2)
        gl_dodge.addSpacing(15)
        self.dodge_chk = QCheckBox("启用"); gl_dodge.addWidget(self.dodge_chk)
        self.double_dodge_chk = QCheckBox("二段"); gl_dodge.addWidget(self.double_dodge_chk)
        gl_dodge.addSpacing(15)
        gl_dodge.addWidget(QLabel("间隔:"))
        self.dbl_wait = QLineEdit("0.015"); self.dbl_wait.setFixedWidth(70); gl_dodge.addWidget(self.dbl_wait)
        gl_dodge.addWidget(HelpBtn("【二段避让间隔】\n间隔时间，单位：秒"))
        gl_dodge.addStretch()
        g_dodge.set_content_layout(gl_dodge)
        settings_content_layout.addWidget(g_dodge)
        
        # 3. 速度控制
        g2 = CollapsibleSection("速度控制 (0为极速)")
        gl2 = QHBoxLayout()
        gl2.addWidget(QLabel("移动(s):")); self.move_spd = QLineEdit("0.0"); self.move_spd.setFixedWidth(70); gl2.addWidget(self.move_spd)
        gl2.addWidget(HelpBtn("【移动耗时】 0.0=瞬移"))
        gl2.addSpacing(15)
        gl2.addWidget(QLabel("按住(s):")); self.click_hld = QLineEdit("0.04"); self.click_hld.setFixedWidth(70); gl2.addWidget(self.click_hld)
        gl2.addWidget(HelpBtn("【按住时长】 建议0.04-0.08模拟真人点击"))
        gl2.addSpacing(15)
        gl2.addWidget(QLabel("间隔(s):")); self.settle = QLineEdit("0.5"); self.settle.setFixedWidth(70); gl2.addWidget(self.settle)
        gl2.addWidget(HelpBtn("【步间隔】\n每一步执行完毕后等待多久再进入下一步；0 表示立刻执行下一步。\n优先级低于“等待”指令：如果当前步骤是等待，或下一步实际要执行的是等待，程序会自动屏蔽等待指令前后的全局间隔。\n例如：第1步点击、第2步等待3秒、第3步点击，则第1步后不会额外加间隔，第2步后也不会额外加间隔，确保第1步后准确等待3秒再执行第3步。"))
        gl2.addSpacing(15)
        gl2.addWidget(QLabel("超时(s):")); self.timeout = QLineEdit("0.0"); self.timeout.setFixedWidth(70); gl2.addWidget(self.timeout)
        gl2.addWidget(HelpBtn("【单步超时】\n0 表示不设置等待上限。\n未开启“超时急停”时：达到超时会把本步骤视为失败，再按小齿轮里的失败跳过/跳至规则处理。\n开启“超时急停”时：达到超时会立即停止整个脚本和后续循环。"))
        self.timeout_stop_chk = QCheckBox("超时急停")
        self.timeout_stop_chk.setToolTip("开启后，任意步骤达到单步超时都会立即停止全部循环，不再执行后续步骤。")
        gl2.addWidget(self.timeout_stop_chk)
        gl2.addSpacing(15)
        gl2.addWidget(QLabel("识别频率(s):")); self.detect_delay = QLineEdit("0.1"); self.detect_delay.setFixedWidth(70); gl2.addWidget(self.detect_delay)
        gl2.addWidget(HelpBtn("【识别频率】\n每次执行识别/重试前先等待这么多秒，用于降低CPU占用。\n0 表示不额外等待，速度最快但CPU压力更高。"))
        gl2.addSpacing(15)
        self.adaptive_backoff_chk = QCheckBox("自适应降频")
        self.adaptive_backoff_chk.setChecked(True)
        self.adaptive_backoff_chk.setToolTip("连续找不到同一目标时自动逐步放慢重试；找到目标后自动恢复。")
        gl2.addWidget(self.adaptive_backoff_chk)
        gl2.addWidget(HelpBtn("【自适应降频】\n开启后，如果某张图连续多次找不到，程序会在识别频率之外额外等待一点时间，避免CPU一直满速空转。\n找到目标后会自动清零恢复速度。"))
        gl2.addSpacing(15)
        gl2.addWidget(QLabel("倍速:")); self.playback_speed = QLineEdit("1.0"); self.playback_speed.setFixedWidth(70); gl2.addWidget(self.playback_speed)
        gl2.addWidget(HelpBtn("【倍速执行】 用于缩放录制的等待指令时间，> 1 为加速"))
        gl2.addStretch()
        g2.set_content_layout(gl2)
        settings_content_layout.addWidget(g2)

        # 4. 多目标点击
        g_multi = CollapsibleSection("多目标点击")
        gl_multi = QHBoxLayout()
        gl_multi.addWidget(QLabel("目标模式:"))
        self.multi_mode_combo = QComboBox()
        self.multi_mode_combo.addItems(["最佳一个", "全部匹配"])
        self.multi_mode_combo.setFixedWidth(120)
        self.multi_mode_combo.currentTextChanged.connect(self.update_multi_target_ui)
        gl_multi.addWidget(self.multi_mode_combo)
        gl_multi.addWidget(HelpBtn("【目标模式】\n最佳一个：走最快路径，只计算当前截图里相似度最高的一个位置并点击，适合普通单目标脚本。\n全部匹配：执行更完整的峰值搜索，一次找出所有超过相似度阈值的目标并逐个点击，CPU压力更高。"))
        gl_multi.addSpacing(15)
        gl_multi.addWidget(QLabel("点击顺序:"))
        self.multi_order_combo = QComboBox()
        self.multi_order_combo.addItems(["从上到下", "从左到右", "从右到左", "距离鼠标最近优先", "随机顺序"])
        self.multi_order_combo.setMinimumWidth(190)
        gl_multi.addWidget(self.multi_order_combo)
        gl_multi.addWidget(HelpBtn("【点击顺序】\n仅在目标模式为“全部匹配”时生效。程序会先识别本轮截图中的全部目标，再按此顺序点击。"))
        gl_multi.addStretch()
        g_multi.set_content_layout(gl_multi)
        settings_content_layout.addWidget(g_multi)
        
        # 5. 系统设置
        g3 = CollapsibleSection("系统设置")
        gl3_main = QVBoxLayout()
        
        gl3_r1 = QHBoxLayout()
        gl3_r1.addWidget(QLabel("启动热键:"))
        self.hotkey_start_combo = QComboBox(); self.hotkey_start_combo.addItems([f"F{i}" for i in range(1, 13)])
        self.hotkey_start_combo.setCurrentText("F9"); self.hotkey_start_combo.setFixedWidth(100)
        self.hotkey_start_combo.currentTextChanged.connect(self.update_hotkeys)
        gl3_r1.addWidget(self.hotkey_start_combo)
        
        gl3_r1.addWidget(QLabel("停止热键:"))
        self.hotkey_stop_combo = QComboBox(); self.hotkey_stop_combo.addItems([f"F{i}" for i in range(1, 13)])
        self.hotkey_stop_combo.setCurrentText("F10"); self.hotkey_stop_combo.setFixedWidth(100)
        self.hotkey_stop_combo.currentTextChanged.connect(self.update_hotkeys)
        gl3_r1.addWidget(self.hotkey_stop_combo)
        
        gl3_r1.addSpacing(15)
        gl3_r1.addWidget(QLabel("日志级别:"))
        self.log_level_combo = QComboBox(); self.log_level_combo.addItems(["简易", "详细", "完全"])
        self.log_level_combo.setFixedWidth(100)
        gl3_r1.addWidget(self.log_level_combo)
        gl3_r1.addStretch()
        
        gl3_r2 = QHBoxLayout()
        self.tm_failsafe = QCheckBox("任务管理器急停"); self.tm_failsafe.setChecked(True); gl3_r2.addWidget(self.tm_failsafe)
        self.tr_failsafe = QCheckBox("右上角急停"); self.tr_failsafe.setChecked(True); gl3_r2.addWidget(self.tr_failsafe)
        self.key_failsafe = QCheckBox("ESC/中键急停"); self.key_failsafe.setChecked(True); gl3_r2.addWidget(self.key_failsafe)
        gl3_r2.addSpacing(15)
        self.log_file_chk = QCheckBox("写入文件日志"); gl3_r2.addWidget(self.log_file_chk)
        self.log_ui_chk = QCheckBox("界面日志"); self.log_ui_chk.setChecked(True); gl3_r2.addWidget(self.log_ui_chk)
        gl3_r2.addSpacing(15)
        self.mini_chk = QCheckBox("启动时最小化")
        self.top_chk = QCheckBox("窗口置顶"); self.top_chk.stateChanged.connect(self.toggle_top_window)
        gl3_r2.addStretch()

        gl3_r3 = QHBoxLayout()
        self.run_status_chk = QCheckBox("运行状态提示")
        self.run_status_chk.setChecked(True)
        gl3_r3.addWidget(self.run_status_chk)
        gl3_r3.addWidget(QLabel("提示位置:"))
        self.run_status_pos_combo = QComboBox()
        self.run_status_pos_combo.addItems(["右上角", "右下角"])
        self.run_status_pos_combo.setFixedWidth(100)
        gl3_r3.addWidget(self.run_status_pos_combo)
        gl3_r3.addWidget(HelpBtn("【运行状态提示】\n脚本运行时在屏幕角落显示“脚本正在执行中”、当前循环、当前步骤和已运行时间。"))
        gl3_r3.addSpacing(15)
        self.click_indicator_chk = QCheckBox("点击位置提示")
        self.click_indicator_chk.setChecked(True)
        self.click_indicator_chk.setToolTip("脚本执行点击、拖拽或悬停时，在屏幕上短暂标出实际位置。")
        gl3_r3.addWidget(self.click_indicator_chk)
        gl3_r3.addWidget(HelpBtn("【点击位置提示】\n开启后，脚本每次点击、拖拽结束或鼠标悬停时，会在屏幕上短暂显示一个定位标记，方便确认刚刚操作了哪里。\n关闭后不显示定位标记，脚本执行逻辑不变。"))
        gl3_r3.addSpacing(15)
        gl3_r3.addWidget(QLabel("从第"))
        self.start_step_edit = QLineEdit("1")
        self.start_step_edit.setFixedWidth(60)
        gl3_r3.addWidget(self.start_step_edit)
        gl3_r3.addWidget(QLabel("步开始"))
        gl3_r3.addWidget(HelpBtn("【从第X步开始执行】\n默认 1。启动脚本后每轮循环都从这里开始；成功/失败跳至仍按列表中的实际步号计算。"))
        gl3_r3.addStretch()

        gl3_r3b = QHBoxLayout()
        gl3_r3b.addWidget(QLabel("脚本从第"))
        self.loop_start_round_edit = QLineEdit("1")
        self.loop_start_round_edit.setFixedWidth(60)
        gl3_r3b.addWidget(self.loop_start_round_edit)
        gl3_r3b.addWidget(QLabel("次循环开始"))
        gl3_r3b.addSpacing(15)
        gl3_r3b.addWidget(QLabel("到第"))
        self.loop_end_round_edit = QLineEdit("0")
        self.loop_end_round_edit.setFixedWidth(60)
        gl3_r3b.addWidget(self.loop_end_round_edit)
        gl3_r3b.addWidget(QLabel("次循环停止"))
        gl3_r3b.addWidget(HelpBtn("【全局循环范围】\n从第几次循环开始真正执行步骤；前面的循环轮次会直接跳过。\n停止循环填 0 表示不限；填 5 表示执行到第 5 次循环后结束。\n这个设置和“从第X步开始”不同：它控制第几轮循环生效。"))
        gl3_r3b.addStretch()

        gl3_r4 = QHBoxLayout()
        self.low_power_ui_chk = QCheckBox("省电UI模式")
        self.low_power_ui_chk.setChecked(True)
        self.low_power_ui_chk.setToolTip("降低主窗口空闲刷新频率：快捷键轮询约 250ms，CPU显示约 3秒刷新一次。可减轻拖动窗口和空闲时的单核占用。")
        self.low_power_ui_chk.stateChanged.connect(self.apply_ui_performance_mode)
        gl3_r4.addWidget(self.low_power_ui_chk)
        gl3_r4.addWidget(HelpBtn("【省电UI模式】\n只影响界面刷新和热键轮询频率，不改变脚本识别逻辑。\n如果你感觉热键响应慢，可以关闭。"))
        gl3_r4.addSpacing(15)
        gl3_r4.addWidget(QLabel("界面倍率(%):"))
        self.ui_scale_edit = QLineEdit("100")
        self.ui_scale_edit.setFixedWidth(60)
        self.ui_scale_edit.setToolTip("调整主界面、设置窗口和小齿轮窗口的字体与控件尺寸，建议范围 75-180。")
        gl3_r4.addWidget(self.ui_scale_edit)
        gl3_r4.addWidget(HelpBtn("【界面倍率】\n用于适配不同分辨率或缩放习惯的显示屏。\n100 表示原始大小；例如 125 会把字体和多数按钮/输入框放大到 125%。\n倍率过大时窗口内容需要更多空间，可以手动拉大窗口。"))
        gl3_r4.addStretch()
        
        gl3_main.addLayout(gl3_r1)
        gl3_main.addLayout(gl3_r2)
        gl3_main.addLayout(gl3_r3)
        gl3_main.addLayout(gl3_r3b)
        gl3_main.addLayout(gl3_r4)
        g3.set_content_layout(gl3_main)
        settings_content_layout.addWidget(g3)

        links_row = QHBoxLayout()
        links_row.addStretch()
        bilibili_btn = QPushButton("作者B站主页")
        bilibili_btn.clicked.connect(lambda: self.open_web_url("https://space.bilibili.com/95794432/dynamic"))
        links_row.addWidget(bilibili_btn)
        github_btn = QPushButton("GitHub下载页")
        github_btn.clicked.connect(lambda: self.open_web_url("https://github.com/FUKUAHG13/waterRPA-FUKUA/releases"))
        links_row.addWidget(github_btn)
        settings_content_layout.addLayout(links_row)
        settings_content_layout.addStretch()

        # ================= 任务列表与日志分屏 =================
        self.splitter = QSplitter(Qt.Vertical)
        
        self.task_list = DraggableListWidget()
        self.task_list.itemSelectionChanged.connect(self.update_selection_highlight)
        self.task_list.setStyleSheet("""
            QListWidget::item:selected { background: #D9ECFF; border: 1px solid #2196F3; }
            QListWidget::item { margin: 1px; }
        """)
        self.splitter.addWidget(self.task_list)
        
        bottom_widget = QWidget()
        bottom_vbox = QVBoxLayout(bottom_widget)
        bottom_vbox.setContentsMargins(0, 0, 0, 0)
        
        # 底部控制区 (Start/Stop 回到这里)
        bot_layout = QHBoxLayout()
        self.loop_combo = QComboBox()
        self.loop_combo.addItems(["单次", "无限", "指定次数", "指定时间(时)", "指定时间(分)", "指定时间(秒)"])
        self.loop_combo.currentTextChanged.connect(self.update_loop_ui)
        bot_layout.addWidget(self.loop_combo)
        
        self.loop_val_edit = QLineEdit("10"); self.loop_val_edit.setFixedWidth(50)
        bot_layout.addWidget(self.loop_val_edit)
        self.update_loop_ui(self.loop_combo.currentText())
        
        bot_layout.addStretch()
        bot_layout.addWidget(self.mini_chk)
        bot_layout.addWidget(self.top_chk)
        bot_layout.addSpacing(10)
        
        self.start_btn = QPushButton("启动"); self.start_btn.clicked.connect(self.start_task)
        self.start_btn.setMinimumSize(100, 30)
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        bot_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止"); self.stop_btn.clicked.connect(self.stop_task)
        self.stop_btn.setMinimumSize(100, 30)
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
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
        self.cpu_timer.start(self.current_cpu_interval())
        
        self.hotkey_timer = QTimer()
        self.hotkey_timer.timeout.connect(self.check_hotkey)
        self.hotkey_timer.setInterval(self.current_hotkey_interval())
        
        self.init_profiles()
        self.bind_setting_logs()
        self.update_hotkeys()

    def open_config_dir(self):
        try:
            config_dir = os.path.normpath(get_base_dir())
            if not os.path.isdir(config_dir):
                config_dir = os.path.dirname(os.path.abspath(self.config_path))
            subprocess.Popen(["explorer.exe", config_dir])
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开配置目录: {e}")

    def open_web_url(self, url):
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开网页: {e}")

    def current_hotkey_interval(self):
        return 250 if getattr(self, "low_power_ui_chk", None) and self.low_power_ui_chk.isChecked() else 100

    def current_cpu_interval(self):
        return 3000 if getattr(self, "low_power_ui_chk", None) and self.low_power_ui_chk.isChecked() else 1000

    def apply_ui_performance_mode(self, *_):
        if getattr(self, "hotkey_timer", None):
            self.hotkey_timer.setInterval(self.current_hotkey_interval())
        if getattr(self, "cpu_timer", None):
            self.cpu_timer.setInterval(self.current_cpu_interval())

    def parse_ui_scale_percent(self):
        raw = str(getattr(self, "ui_scale_edit", QLineEdit("100")).text()).strip().replace("%", "")
        value = parse_float_text(raw, 100.0)
        value = max(75.0, min(180.0, value))
        if abs(value - round(value)) < 0.01:
            text = str(int(round(value)))
        else:
            text = f"{value:.1f}".rstrip("0").rstrip(".")
        if getattr(self, "ui_scale_edit", None) and self.ui_scale_edit.text().strip().replace("%", "") != text:
            self.ui_scale_edit.setText(text)
        return value

    def apply_ui_scale_from_edit(self, *_):
        percent = self.parse_ui_scale_percent()
        self.apply_ui_scale(percent / 100.0)
        if not self.is_switching_profile:
            self.log_setting_change("界面倍率(%)", self.ui_scale_edit.text())

    def apply_ui_scale_to_widgets(self, widgets, scale):
        qwidget_max = 16777215
        for widget in widgets:
            if widget is None:
                continue
            try:
                if not widget.property("_ui_scale_base_saved"):
                    widget.setProperty("_ui_scale_base_saved", True)
                    widget.setProperty("_ui_base_min_w", widget.minimumWidth())
                    widget.setProperty("_ui_base_min_h", widget.minimumHeight())
                    widget.setProperty("_ui_base_max_w", widget.maximumWidth())
                    widget.setProperty("_ui_base_max_h", widget.maximumHeight())

                min_w = int(widget.property("_ui_base_min_w") or 0)
                min_h = int(widget.property("_ui_base_min_h") or 0)
                max_w = int(widget.property("_ui_base_max_w") or qwidget_max)
                max_h = int(widget.property("_ui_base_max_h") or qwidget_max)

                if min_w > 0:
                    widget.setMinimumWidth(max(1, int(round(min_w * scale))))
                if min_h > 0:
                    widget.setMinimumHeight(max(1, int(round(min_h * scale))))
                if 0 < max_w < qwidget_max:
                    widget.setMaximumWidth(max(1, int(round(max_w * scale))))
                if 0 < max_h < qwidget_max:
                    widget.setMaximumHeight(max(1, int(round(max_h * scale))))
            except RuntimeError:
                continue
            except Exception:
                continue

    def apply_ui_scale_to_widget(self, widget):
        if not widget:
            return
        scale = float(getattr(self, "ui_scale", 1.0))
        widgets = [widget] + widget.findChildren(QWidget)
        self.apply_ui_scale_to_widgets(widgets, scale)

    def apply_ui_scale(self, scale):
        scale = max(0.75, min(1.8, float(scale)))
        self.ui_scale = scale
        try:
            font = QFont(self.ui_base_font)
            if font.pointSizeF() > 0:
                font.setPointSizeF(max(6.0, self.ui_base_font.pointSizeF() * scale))
            elif font.pixelSize() > 0:
                font.setPixelSize(max(8, int(round(self.ui_base_font.pixelSize() * scale))))
            QApplication.setFont(font)
        except:
            pass
        try:
            self.apply_ui_scale_to_widgets(QApplication.allWidgets(), scale)
            self.updateGeometry()
            if getattr(self, "settings_dialog", None):
                self.settings_dialog.updateGeometry()
            for i in range(self.task_list.count()):
                item = self.task_list.item(i)
                widget = self.task_list.itemWidget(item)
                if widget:
                    item.setSizeHint(widget.sizeHint())
        except:
            pass

    def show_settings_dialog(self):
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def close_settings_dialog(self):
        self.settings_dialog.save_dialog_geometry()
        self.settings_dialog.hide()

    def show_running_status_overlay(self, position_name):
        if self.running_overlay is None:
            self.running_overlay = RunningStatusOverlay()
        self.running_overlay.start_overlay(position_name)

    def update_running_status_overlay(self, data):
        if self.running_overlay and self.running_overlay.isVisible():
            self.running_overlay.set_status(data)

    def hide_running_status_overlay(self):
        if self.running_overlay:
            self.running_overlay.stop_overlay()

    def show_click_indicator_overlay(self, data):
        try:
            overlay = ClickPointOverlay(data.get("x", 0), data.get("y", 0), data.get("text", ""))
            if not hasattr(self, "click_indicator_overlays"):
                self.click_indicator_overlays = []
            self.click_indicator_overlays.append(overlay)
            overlay.destroyed.connect(lambda *_args, o=overlay: self.click_indicator_overlays.remove(o) if o in self.click_indicator_overlays else None)
        except Exception as e:
            write_log(f"显示点击位置提示失败: {e}")

    def coordinate_preview_options_from_task(self, task):
        return {
            "every": max(1, int(parse_float_text(task.get("coord_step_every", 1), 1))),
            "direction": str(task.get("coord_step_direction", "向下")),
            "distance": parse_float_text(task.get("coord_step_distance", 0), 0.0),
            "dx": parse_float_text(task.get("coord_step_dx", 0), 0.0),
            "dy": parse_float_text(task.get("coord_step_dy", 0), 0.0),
            "point": str(task.get("coord_step_point", "")).strip(),
            "max_steps": max(0, int(parse_float_text(task.get("coord_step_max_steps", 0), 0.0))),
            "max_distance": max(0.0, parse_float_text(task.get("coord_step_max_distance", 0), 0.0)),
            "reset_after": max(0, int(parse_float_text(task.get("coord_step_reset_after", 0), 0.0))),
            "manual_points": parse_coord_step_manual_points(task.get("coord_step_manual_points", "{}"))
        }

    def collect_coordinate_click_preview_points(self, max_points=800):
        points = []
        truncated = False
        tasks = self.get_current_ui_config().get("tasks", [])
        for task in tasks:
            try:
                cmd = float(task.get("type", 0))
            except:
                continue
            if cmd not in [1.0, 2.0, 3.0]:
                continue
            coord = parse_coordinate_text(task.get("value", ""))
            if not coord:
                continue

            step_points = [coord]
            if config_bool(task.get("coord_step_en", False)):
                options = self.coordinate_preview_options_from_task(task)
                step_points = build_coord_step_positions(coord[0], coord[1], options, max_points=120)
            for point in step_points:
                points.append(point)
                if len(points) >= max_points:
                    truncated = True
                    return points, truncated
        return points, truncated

    def show_all_coordinate_click_preview(self):
        points, truncated = self.collect_coordinate_click_preview_points()
        if not points:
            QMessageBox.information(self, "无法预览", "当前脚本没有直接坐标点击步骤。\n图片识别点击不会参与此预览。")
            return
        self.close_all_coordinate_click_preview()
        suffix = "，已截断前 800 个" if truncated else ""
        title = f"坐标点击总预览：{len(points)} 个点位{suffix}；仅显示直接坐标点击，左键/右键/Esc 可关闭"
        self.all_points_preview = CoordinateStepPreviewOverlay(
            points,
            {"direction": "全部坐标点击"},
            title=title,
            auto_close_ms=15000,
            draw_lines=True,
            detail_text="坐标步进点表示该步骤多次执行时会轮到的位置，实际执行不会在单次步骤里一次点完全部点。"
        )
        self.all_points_preview.destroyed.connect(self.clear_all_coordinate_click_preview)

    def clear_all_coordinate_click_preview(self, *_):
        self.all_points_preview = None

    def close_all_coordinate_click_preview(self):
        preview = getattr(self, "all_points_preview", None)
        if preview:
            try:
                preview.close()
            except RuntimeError:
                pass
            self.all_points_preview = None

    def append_log(self, msg):
        scrollbar = self.log_text.verticalScrollBar()
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 5
        old_val = scrollbar.value()
        self.log_text.append(msg)
        if not is_at_bottom: scrollbar.setValue(old_val)
        else: scrollbar.setValue(scrollbar.maximum())

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
        self.current_profile_name = self.profile_combo.currentText()
        self.apply_ui_config(self.profiles_data[self.current_profile_name])

    def get_default_config_dict(self):
        return {
            "conf": "0.8", "scale_min": "1.0" if SLIM_BUILD else "0.8", "scale_max": "1.0" if SLIM_BUILD else "1.2", "scale_step": "0.05", "gray_en": False if SLIM_BUILD else True, "native_core_en": False if SLIM_BUILD else True,
            "dodge_x1": "100", "dodge_y1": "100", "dodge_x2": "200", "dodge_y2": "100",
            "dodge_en": False, "dbl_dodge": False, "dbl_wait": "0.015",
            "move_spd": "0.0", "click_hld": "0.04", "settle": "0.5", "timeout": "0.0", "timeout_stop": False, "detect_delay": "0.1", "adaptive_backoff": True, "playback_speed": "1.0",
            "multi_target_mode": "最佳一个", "multi_target_order": "从上到下",
            "hotkey_start": "F9", "hotkey_stop": "F10", "log_level": 0,
            "tm_fs": True, "tr_fs": True, "key_fs": True,
            "log_f": False, "log_ui": True, "mini": False, "top": False,
            "run_status_tip": True, "run_status_pos": "右上角", "click_indicator": True, "start_step": "1", "loop_start_round": "1", "loop_end_round": "0", "low_power_ui": True, "ui_scale": "100",
            "loop_mode": "单次", "loop_val": "10",
            "scan_region": None, "scan_regions": [],
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
            "conf": self.conf_edit.text(), "scale_min": self.scale_min.text(), "scale_max": self.scale_max.text(), "scale_step": self.scale_step.text(), "gray_en": self.gray_chk.isChecked(), "native_core_en": self.native_core_chk.isChecked(),
            "dodge_x1": self.dodge_x1.text(), "dodge_y1": self.dodge_y1.text(), "dodge_x2": self.dodge_x2.text(), "dodge_y2": self.dodge_y2.text(),
            "dodge_en": self.dodge_chk.isChecked(), "dbl_dodge": self.double_dodge_chk.isChecked(), "dbl_wait": self.dbl_wait.text(),
            "move_spd": self.move_spd.text(), "click_hld": self.click_hld.text(), "settle": self.settle.text(), "timeout": self.timeout.text(), "timeout_stop": self.timeout_stop_chk.isChecked(), "detect_delay": self.detect_delay.text(), "adaptive_backoff": self.adaptive_backoff_chk.isChecked(), "playback_speed": self.playback_speed.text(),
            "multi_target_mode": self.multi_mode_combo.currentText(), "multi_target_order": self.multi_order_combo.currentText(),
            "hotkey_start": self.hotkey_start_combo.currentText(), "hotkey_stop": self.hotkey_stop_combo.currentText(), "log_level": self.log_level_combo.currentIndex(),
            "tm_fs": self.tm_failsafe.isChecked(), "tr_fs": self.tr_failsafe.isChecked(), "key_fs": self.key_failsafe.isChecked(),
            "log_f": self.log_file_chk.isChecked(), "log_ui": self.log_ui_chk.isChecked(), "mini": self.mini_chk.isChecked(), "top": self.top_chk.isChecked(),
            "run_status_tip": self.run_status_chk.isChecked(), "run_status_pos": self.run_status_pos_combo.currentText(), "click_indicator": self.click_indicator_chk.isChecked(), "start_step": self.start_step_edit.text(), "loop_start_round": self.loop_start_round_edit.text(), "loop_end_round": self.loop_end_round_edit.text(), "low_power_ui": self.low_power_ui_chk.isChecked(), "ui_scale": self.ui_scale_edit.text(),
            "loop_mode": self.loop_combo.currentText(), "loop_val": self.loop_val_edit.text(),
            "scan_region": self.engine.scan_region, "scan_regions": self.engine.scan_regions,
            "tasks": tasks
        }

    def apply_ui_config(self, cfg):
        try:
            self.conf_edit.setText(str(cfg.get("conf", "0.8")))
            self.scale_min.setText(str(cfg.get("scale_min", "0.8")))
            self.scale_max.setText(str(cfg.get("scale_max", "1.2")))
            self.scale_step.setText(str(cfg.get("scale_step", "0.05")))
            self.gray_chk.setChecked(bool(cfg.get("gray_en", True)))
            self.native_core_chk.setChecked(config_bool(cfg.get("native_core_en", True)))
            if SLIM_BUILD:
                self.scale_min.setText("1.0")
                self.scale_max.setText("1.0")
                self.scale_step.setText("0.05")
                self.gray_chk.setChecked(False)
                self.native_core_chk.setChecked(False)
            self.dodge_x1.setText(str(cfg.get("dodge_x1", "100")))
            self.dodge_y1.setText(str(cfg.get("dodge_y1", "100")))
            self.dodge_x2.setText(str(cfg.get("dodge_x2", "200")))
            self.dodge_y2.setText(str(cfg.get("dodge_y2", "100")))
            self.dodge_chk.setChecked(bool(cfg.get("dodge_en", False)))
            self.double_dodge_chk.setChecked(bool(cfg.get("dbl_dodge", False)))
            self.dbl_wait.setText(str(cfg.get("dbl_wait", "0.015")))
            
            self.move_spd.setText(str(cfg.get("move_spd", "0.0")))
            self.click_hld.setText(str(cfg.get("click_hld", "0.04")))
            self.settle.setText(str(cfg.get("settle", "0.5")))
            self.timeout.setText(str(cfg.get("timeout", "0.0")))
            self.timeout_stop_chk.setChecked(config_bool(cfg.get("timeout_stop", False)))
            self.detect_delay.setText(str(cfg.get("detect_delay", "0.1")))
            self.adaptive_backoff_chk.setChecked(config_bool(cfg.get("adaptive_backoff", True)))
            self.playback_speed.setText(str(cfg.get("playback_speed", "1.0")))
            self.multi_mode_combo.setCurrentText(str(cfg.get("multi_target_mode", "最佳一个")))
            self.multi_order_combo.setCurrentText(str(cfg.get("multi_target_order", "从上到下")))
            self.update_multi_target_ui()
            
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
            self.run_status_chk.setChecked(bool(cfg.get("run_status_tip", True)))
            self.run_status_pos_combo.setCurrentText(str(cfg.get("run_status_pos", "右上角")))
            self.click_indicator_chk.setChecked(config_bool(cfg.get("click_indicator", True)))
            self.start_step_edit.setText(str(cfg.get("start_step", "1")))
            self.loop_start_round_edit.setText(str(cfg.get("loop_start_round", "1")))
            self.loop_end_round_edit.setText(str(cfg.get("loop_end_round", "0")))
            self.low_power_ui_chk.setChecked(config_bool(cfg.get("low_power_ui", True)))
            self.ui_scale_edit.setText(str(cfg.get("ui_scale", "100")))
            self.apply_ui_performance_mode()
            
            self.loop_combo.setCurrentText(str(cfg.get("loop_mode", "单次")))
            self.loop_val_edit.setText(str(cfg.get("loop_val", "10")))
            self.apply_scan_region_config(cfg.get("scan_region"), cfg.get("scan_regions"))
            
            self.task_list.clear()
            tasks = cfg.get("tasks", [])
            for d in tasks: self.add_row(d)
            
            self.update_log_config()
            self.update_hotkeys()
            self.apply_ui_scale(self.parse_ui_scale_percent() / 100.0)
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
            self.profiles_data[text] = self.profiles_data.pop(old_name, self.get_current_ui_config())
            self.is_switching_profile = True
            idx = self.profile_combo.findText(old_name)
            if idx >= 0: self.profile_combo.setItemText(idx, text)
            self.current_profile_name = text
            self.is_switching_profile = False
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
        if idx >= 0: self.profile_combo.removeItem(idx)
            
        self.current_profile_name = self.profile_combo.currentText()
        if self.current_profile_name not in self.profiles_data:
            if self.profiles_data: self.current_profile_name = list(self.profiles_data.keys())[0]
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

    def start_recording(self):
        self.showMinimized()
        self.recorder_ui = RecorderUI(self)

    def bind_setting_logs(self):
        self.conf_edit.editingFinished.connect(lambda: self.log_setting_change("相似度", self.conf_edit.text()))
        self.scale_min.editingFinished.connect(lambda: self.log_setting_change("最小缩放", self.scale_min.text()))
        self.scale_max.editingFinished.connect(lambda: self.log_setting_change("最大缩放", self.scale_max.text()))
        self.scale_step.editingFinished.connect(lambda: self.log_setting_change("缩放步长", self.scale_step.text()))
        self.dodge_x1.editingFinished.connect(lambda: self.log_setting_change("避让坐标1 X", self.dodge_x1.text()))
        self.dodge_y1.editingFinished.connect(lambda: self.log_setting_change("避让坐标1 Y", self.dodge_y1.text()))
        self.dodge_x2.editingFinished.connect(lambda: self.log_setting_change("避让坐标2 X", self.dodge_x2.text()))
        self.dodge_y2.editingFinished.connect(lambda: self.log_setting_change("避让坐标2 Y", self.dodge_y2.text()))
        self.dbl_wait.editingFinished.connect(lambda: self.log_setting_change("二段避让间隔(s)", self.dbl_wait.text()))
        self.move_spd.editingFinished.connect(lambda: self.log_setting_change("移动耗时(s)", self.move_spd.text()))
        self.click_hld.editingFinished.connect(lambda: self.log_setting_change("按住时长(s)", self.click_hld.text()))
        self.settle.editingFinished.connect(lambda: self.log_setting_change("步间隔(s)", self.settle.text()))
        self.timeout.editingFinished.connect(lambda: self.log_setting_change("单步超时(s)", self.timeout.text()))
        self.detect_delay.editingFinished.connect(lambda: self.log_setting_change("识别频率(s)", self.detect_delay.text()))
        self.playback_speed.editingFinished.connect(lambda: self.log_setting_change("倍速执行", self.playback_speed.text()))
        self.loop_val_edit.editingFinished.connect(lambda: self.log_setting_change("循环参数", self.loop_val_edit.text()))
        self.start_step_edit.editingFinished.connect(lambda: self.log_setting_change("从第X步开始", self.start_step_edit.text()))
        self.loop_start_round_edit.editingFinished.connect(lambda: self.log_setting_change("脚本起始循环", self.loop_start_round_edit.text()))
        self.loop_end_round_edit.editingFinished.connect(lambda: self.log_setting_change("脚本停止循环", self.loop_end_round_edit.text()))
        self.ui_scale_edit.editingFinished.connect(self.apply_ui_scale_from_edit)

        self.gray_chk.stateChanged.connect(lambda s: self.log_setting_change("灰度匹配", "开启" if s else "关闭"))
        self.native_core_chk.stateChanged.connect(lambda s: self.log_setting_change("DLL原生识别", "开启" if s else "关闭"))
        self.dodge_chk.stateChanged.connect(lambda s: self.log_setting_change("启用避让", "开启" if s else "关闭"))
        self.double_dodge_chk.stateChanged.connect(lambda s: self.log_setting_change("二段避让", "开启" if s else "关闭"))
        self.tm_failsafe.stateChanged.connect(lambda s: self.log_setting_change("任务管理器急停", "开启" if s else "关闭"))
        self.tr_failsafe.stateChanged.connect(lambda s: self.log_setting_change("右上角急停", "开启" if s else "关闭"))
        self.key_failsafe.stateChanged.connect(lambda s: self.log_setting_change("ESC/中键急停", "开启" if s else "关闭"))
        self.log_file_chk.stateChanged.connect(lambda s: self.log_setting_change("写入文件日志", "开启" if s else "关闭"))
        self.log_ui_chk.stateChanged.connect(lambda s: self.log_setting_change("显示界面日志", "开启" if s else "关闭"))
        self.mini_chk.stateChanged.connect(lambda s: self.log_setting_change("启动时最小化", "开启" if s else "关闭"))
        self.top_chk.stateChanged.connect(lambda s: self.log_setting_change("窗口置顶", "开启" if s else "关闭"))
        self.run_status_chk.stateChanged.connect(lambda s: self.log_setting_change("运行状态提示", "开启" if s else "关闭"))
        self.click_indicator_chk.stateChanged.connect(lambda s: self.log_setting_change("点击位置提示", "开启" if s else "关闭"))
        self.timeout_stop_chk.stateChanged.connect(lambda s: self.log_setting_change("超时急停", "开启" if s else "关闭"))
        self.low_power_ui_chk.stateChanged.connect(lambda s: self.log_setting_change("省电UI模式", "开启" if s else "关闭"))
        self.adaptive_backoff_chk.stateChanged.connect(lambda s: self.log_setting_change("自适应降频", "开启" if s else "关闭"))
        
        self.hotkey_start_combo.currentTextChanged.connect(lambda t: self.log_setting_change("启动热键", t))
        self.hotkey_stop_combo.currentTextChanged.connect(lambda t: self.log_setting_change("停止热键", t))
        self.log_level_combo.currentTextChanged.connect(lambda t: self.log_setting_change("日志级别", t))
        self.log_level_combo.currentTextChanged.connect(self.warn_heavy_log_level)
        self.loop_combo.currentTextChanged.connect(lambda t: self.log_setting_change("循环模式", t))
        self.multi_mode_combo.currentTextChanged.connect(lambda t: self.log_setting_change("多目标模式", t))
        self.multi_order_combo.currentTextChanged.connect(lambda t: self.log_setting_change("多目标顺序", t))
        self.run_status_pos_combo.currentTextChanged.connect(lambda t: self.log_setting_change("运行提示位置", t))

    def log_setting_change(self, name, value):
        if GLOBAL_CONFIG["log_to_ui"] and not self.is_switching_profile:
            self.append_log(f"<font color='#FF9800'><b>设置已生效：</b>{name} -> {value}</font>")

    def warn_heavy_log_level(self, text):
        if self.is_switching_profile or text == "简易":
            return
        if self.settings.value("ack_heavy_log_warning", "") == "1":
            return
        QMessageBox.warning(
            self,
            "日志性能提示",
            "详细/完全日志会更频繁地刷新界面，可能拖慢UI响应，尤其是完全日志。\n\n"
            "如果运行时感觉卡顿，可以切回“简易”，或者关闭“界面日志”。"
        )
        self.settings.setValue("ack_heavy_log_warning", "1")

    def update_loop_ui(self, text):
        if text in ["指定次数", "指定时间(时)", "指定时间(分)", "指定时间(秒)"]:
            self.loop_val_edit.show()
        else:
            self.loop_val_edit.hide()

    def update_multi_target_ui(self, _=None):
        self.multi_order_combo.setEnabled(self.multi_mode_combo.currentText() == "全部匹配")

    def normalize_region_list(self, regions):
        normalized = []
        for region in regions or []:
            try:
                x, y, w, h = [int(float(v)) for v in region]
                if w > 0 and h > 0:
                    normalized.append((x, y, w, h))
            except:
                continue
        return normalized

    def update_region_label(self):
        regions = self.normalize_region_list(getattr(self.engine, "scan_regions", []))
        if regions:
            self.region_label.setText(f"范围: 多区域 {len(regions)} 个")
            return
        if self.engine.scan_region:
            self.region_label.setText(f"范围(物理): {self.engine.scan_region}")
        else:
            self.region_label.setText("范围: 全屏")

    def apply_scan_region_config(self, scan_region=None, scan_regions=None):
        regions = self.normalize_region_list(scan_regions)
        if regions:
            self.engine.scan_regions = regions
            self.engine.scan_region = regions[0] if len(regions) == 1 else None
            self.update_region_label()
            return

        single = self.normalize_region_list([scan_region])
        self.engine.scan_regions = []
        self.engine.scan_region = single[0] if single else None
        self.update_region_label()

    def hotkey_hwnd(self):
        return wintypes.HWND(int(self.winId()))

    def unregister_global_hotkeys(self):
        hwnd = self.hotkey_hwnd()
        for hotkey_id in (HOTKEY_ID_START, HOTKEY_ID_STOP):
            try:
                user32.UnregisterHotKey(hwnd, hotkey_id)
            except:
                pass
        self.global_hotkeys_registered = False

    def register_global_hotkeys(self):
        try:
            self.unregister_global_hotkeys()
            hwnd = self.hotkey_hwnd()
            start_ok = bool(user32.RegisterHotKey(hwnd, HOTKEY_ID_START, MOD_NOREPEAT, self.hotkey_start_vk))
            stop_ok = bool(user32.RegisterHotKey(hwnd, HOTKEY_ID_STOP, MOD_NOREPEAT, self.hotkey_stop_vk))
            if start_ok and stop_ok:
                self.global_hotkeys_registered = True
                return True
            write_log("注册全局热键失败，可能热键已被其他程序占用，回退到轮询模式。")
            self.unregister_global_hotkeys()
        except Exception as e:
            write_log(f"注册全局热键失败，回退到轮询模式: {e}")
        self.global_hotkeys_registered = False
        return False

    def refresh_hotkey_backend(self):
        if not getattr(self, "hotkey_timer", None):
            return
        if self.register_global_hotkeys():
            self.hotkey_timer.stop()
        else:
            self.hotkey_timer.start(self.current_hotkey_interval())

    def nativeEvent(self, eventType, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_ID_START and not self.engine.is_running:
                    QTimer.singleShot(0, self.start_task)
                    return True, 0
                if msg.wParam == HOTKEY_ID_STOP and self.engine.is_running:
                    QTimer.singleShot(0, self.stop_task)
                    return True, 0
        except:
            pass
        return super().nativeEvent(eventType, message)

    def update_hotkeys(self, _=None):
        try:
            start_txt = self.hotkey_start_combo.currentText()
            stop_txt = self.hotkey_stop_combo.currentText()
            self.hotkey_start_vk = 0x70 + (int(start_txt.replace("F", "")) - 1)
            self.hotkey_stop_vk = 0x70 + (int(stop_txt.replace("F", "")) - 1)
            self.start_btn.setText(f"启动 ({start_txt})")
            self.stop_btn.setText(f"停止 ({stop_txt})")
            self.refresh_hotkey_backend()
        except: pass

    def toggle_top_window(self):
        """使用 Win32 API 切换置顶，避免 setWindowFlags 重建窗口导致标题栏异常。"""
        should_be_top = self.top_chk.isChecked()
        hwnd = wintypes.HWND(int(self.winId()))
        insert_after = HWND_TOPMOST if should_be_top else HWND_NOTOPMOST
        swp_flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER

        if self.isVisible():
            swp_flags |= SWP_SHOWWINDOW

        if not user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, swp_flags):
            err = kernel32.GetLastError()
            write_log(f"切换窗口置顶失败: WinError {err}")

    def check_hotkey(self):
        start_pressed = GetAsyncKeyState(self.hotkey_start_vk) & 0x8000
        stop_pressed = GetAsyncKeyState(self.hotkey_stop_vk) & 0x8000
        
        if start_pressed and not self.engine.is_running:
            self.start_task()
            self.hotkey_timer.stop()
            QTimer.singleShot(500, lambda: self.hotkey_timer.start(self.current_hotkey_interval()) if not self.global_hotkeys_registered else None)
            return
            
        if stop_pressed and self.engine.is_running:
            self.stop_task()
            self.hotkey_timer.stop()
            QTimer.singleShot(500, lambda: self.hotkey_timer.start(self.current_hotkey_interval()) if not self.global_hotkeys_registered else None)
            return

    def open_region_selector(self):
        self.region_win = RegionWindow(multi=True)
        self.region_win.regions_selected.connect(self.on_regions_selected)

    def open_multi_region_selector(self):
        self.open_region_selector()

    def on_region_selected(self, rect_tuple):
        self.engine.scan_region = rect_tuple
        self.engine.scan_regions = []
        self.update_region_label()
        self.append_log(f"已锁定游戏区域(物理): {rect_tuple} (速度+++)")

    def on_regions_selected(self, rects):
        regions = self.normalize_region_list(rects)
        if not regions:
            return
        self.engine.scan_regions = regions
        self.engine.scan_region = regions[0] if len(regions) == 1 else None
        self.update_region_label()
        self.append_log(f"已锁定 {len(regions)} 个识别区域(物理)，只在这些区域内找图 (速度+++)") 

    def closeEvent(self, event):
        """终极修复：强力异常捕获+强制放行，确保不管什么情况点X号都能瞬间关掉软件"""
        try:
            self.unregister_global_hotkeys()
            self.settings.setValue("window_geometry", self.saveGeometry())
            if getattr(self, "settings_dialog", None):
                self.settings_dialog.save_dialog_geometry()
            self.profiles_data[self.current_profile_name] = self.get_current_ui_config()
            self.settings.setValue("profiles_json", json.dumps(self.profiles_data))
            self.settings.setValue("current_profile", self.current_profile_name)
            self.close_all_coordinate_click_preview()
            for overlay in list(getattr(self, "click_indicator_overlays", [])):
                try:
                    overlay.close()
                except RuntimeError:
                    pass
            
            if getattr(self, 'worker', None) and self.worker.isRunning():
                self.engine.stop()
                self.worker.quit()
                self.worker.wait(1000)
            if self.running_overlay:
                self.running_overlay.close()
            self.close_all_coordinate_click_preview()
        except Exception as e:
            write_log(f"退出前保存异常: {e}")
        finally:
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
            if widget is None:
                data = item.data(Qt.UserRole)
                if data:
                    self.restore_row_widget(item, data)
                    widget = self.task_list.itemWidget(item)
            if widget and hasattr(widget, 'set_index'):
                widget.set_index(i + 1)
                item.setData(Qt.UserRole, widget.get_data())
                if hasattr(widget, 'drag_summary'):
                    item.setData(Qt.UserRole + 1, widget.drag_summary())
                item.setText("")
        self.update_selection_highlight()

    def selected_row_index(self):
        row = self.task_list.currentRow()
        return row if row >= 0 else None

    def snapshot_tasks(self):
        tasks = []
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            widget = self.task_list.itemWidget(item)
            if widget:
                tasks.append(widget.get_data())
            else:
                tasks.append(item.data(Qt.UserRole))
        return json.loads(json.dumps(tasks, ensure_ascii=False))

    def push_undo_state(self):
        if self.restoring_history or self.is_switching_profile:
            return
        self.undo_stack.append(self.snapshot_tasks())
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def restore_task_snapshot(self, tasks):
        self.restoring_history = True
        try:
            self.task_list.clear()
            for data in tasks:
                self.add_row(data, record_undo=False, select=False)
            self.update_indexes()
        finally:
            self.restoring_history = False

    def restore_row_widget(self, item, data):
        row_widget = TaskRow(delete_callback=self.del_row)
        if data:
            row_widget.set_data(data)
        item.setSizeHint(row_widget.sizeHint())
        self.task_list.setItemWidget(item, row_widget)
        row_widget.set_parent_item(item)
        item.setData(Qt.UserRole, row_widget.get_data())
        item.setData(Qt.UserRole + 1, row_widget.drag_summary())
        item.setText("")

    def update_selection_highlight(self):
        current = self.task_list.currentItem()
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            widget = self.task_list.itemWidget(item)
            if widget and hasattr(widget, "set_selected"):
                widget.set_selected(item is current)

    def add_row(self, data=None, index=None, record_undo=True, select=True):
        if record_undo:
            self.push_undo_state()
        row_widget = TaskRow(delete_callback=self.del_row)
        if data: row_widget.set_data(data)
        item = QListWidgetItem()
        item.setSizeHint(row_widget.sizeHint())
        if index is None:
            self.task_list.addItem(item)
        else:
            self.task_list.insertItem(max(0, min(index, self.task_list.count())), item)
        self.task_list.setItemWidget(item, row_widget)
        row_widget.set_parent_item(item)
        item.setData(Qt.UserRole, row_widget.get_data())
        item.setData(Qt.UserRole + 1, row_widget.drag_summary())
        item.setText("")
        if select:
            self.task_list.setCurrentItem(item)
        self.update_indexes()

    def del_row(self, row_widget):
        self.push_undo_state()
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if self.task_list.itemWidget(item) == row_widget:
                self.task_list.takeItem(i)
                break
        self.update_indexes()

    def insert_row_before_selected(self):
        row = self.selected_row_index()
        self.add_row(index=(row if row is not None else self.task_list.count()))

    def copy_selected_row(self):
        row = self.selected_row_index()
        if row is None:
            return
        item = self.task_list.item(row)
        widget = self.task_list.itemWidget(item)
        if not widget:
            return
        self.task_clipboard = widget.get_data()
        try:
            pyperclip.copy(json.dumps({"waterRPA_task": self.task_clipboard}, ensure_ascii=False))
        except:
            pass
        if GLOBAL_CONFIG["log_to_ui"]:
            self.append_log(f"<font color='gray'>已复制第 {row + 1} 步。</font>")

    def paste_row_after_selected(self):
        data = self.task_clipboard
        if data is None:
            try:
                clip = json.loads(pyperclip.paste())
                if isinstance(clip, dict) and "waterRPA_task" in clip:
                    data = clip["waterRPA_task"]
            except:
                data = None
        if not isinstance(data, dict):
            return
        row = self.selected_row_index()
        insert_at = self.task_list.count() if row is None else row + 1
        self.add_row(json.loads(json.dumps(data, ensure_ascii=False)), index=insert_at)

    def undo_task_change(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.snapshot_tasks())
        tasks = self.undo_stack.pop()
        self.restore_task_snapshot(tasks)

    def redo_task_change(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.snapshot_tasks())
        tasks = self.redo_stack.pop()
        self.restore_task_snapshot(tasks)

    def keyPressEvent(self, event):
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)):
            return super().keyPressEvent(event)
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_C:
                self.copy_selected_row(); return
            if event.key() == Qt.Key_V:
                self.paste_row_after_selected(); return
            if event.key() == Qt.Key_Z:
                self.undo_task_change(); return
            if event.key() == Qt.Key_Y:
                self.redo_task_change(); return
            if event.key() == Qt.Key_D:
                self.insert_row_before_selected(); return
        if event.key() == Qt.Key_Insert:
            self.insert_row_before_selected(); return
        return super().keyPressEvent(event)

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
        start_step = str(self.start_step_edit.text()).strip()
        if not start_step.isdigit() or int(start_step) < 1 or int(start_step) > len(tasks):
            return f"设置里的'从第X步开始执行'必须是 1 到 {len(tasks)} 之间的整数！\n填入内容: {start_step}"

        loop_start_round = str(self.loop_start_round_edit.text()).strip()
        loop_end_round = str(self.loop_end_round_edit.text()).strip()
        if not loop_start_round.isdigit() or int(loop_start_round) < 1:
            return f"设置里的'脚本从第X次循环开始'必须是大于等于 1 的整数！\n填入内容: {loop_start_round}"
        if not loop_end_round.isdigit() or int(loop_end_round) < 0:
            return f"设置里的'到第X次循环停止'必须是大于等于 0 的整数！\n填入内容: {loop_end_round}"
        if int(loop_end_round) > 0 and int(loop_end_round) < int(loop_start_round):
            return f"设置里的'到第X次循环停止'不能小于起始循环！\n起始循环: {loop_start_round}，停止循环: {loop_end_round}"
        if self.loop_combo.currentText() == "单次" and int(loop_start_round) > 1:
            return "当前是'单次'循环模式，脚本起始循环必须为 1；如果要从第多次循环开始，请把循环模式改为'无限'或'指定次数'。"

        for i, task in enumerate(tasks):
            t = task.get("type")
            v = str(task.get("value", "")).strip()
            success_skip = str(task.get("success_skip", "0")).strip()
            success_jump = str(task.get("success_jump", "0")).strip()
            fail_skip = str(task.get("fail_skip", "0")).strip()
            fail_jump = str(task.get("fail_jump", "0")).strip()
            repeat_mode = str(task.get("repeat_mode", "执行一次"))
            repeat_count = str(task.get("repeat_count", "1")).strip()
            step_loop_start = str(task.get("step_loop_start", "1")).strip()
            step_loop_end = str(task.get("step_loop_end", "0")).strip()
            fail_limit = str(task.get("fail_limit", "1")).strip()
            point_limit_count = str(task.get("point_limit_count", "0")).strip()
            image_click_point_en = config_bool(task.get("image_click_point_en", False))
            image_click_point_rx = str(task.get("image_click_point_rx", "0.5")).strip()
            image_click_point_ry = str(task.get("image_click_point_ry", "0.5")).strip()
            coord_step_en = config_bool(task.get("coord_step_en", False))
            coord_step_every = str(task.get("coord_step_every", "1")).strip()
            coord_step_direction = str(task.get("coord_step_direction", "向下")).strip()
            coord_step_distance = str(task.get("coord_step_distance", "0")).strip()
            coord_step_dx = str(task.get("coord_step_dx", "0")).strip()
            coord_step_dy = str(task.get("coord_step_dy", "0")).strip()
            coord_step_point = str(task.get("coord_step_point", "")).strip()
            coord_step_max_steps = str(task.get("coord_step_max_steps", "0")).strip()
            coord_step_max_distance = str(task.get("coord_step_max_distance", "0")).strip()
            coord_step_reset_after = str(task.get("coord_step_reset_after", "0")).strip()
            
            if success_skip and not success_skip.isdigit():
                return f"第 {i+1} 步小齿轮里的'成功后跳过'必须是整数！\n填入内容: {success_skip}"
            if fail_skip and not fail_skip.isdigit():
                return f"第 {i+1} 步小齿轮里的'失败后跳过'必须是整数！\n填入内容: {fail_skip}"
            if success_jump and (not success_jump.isdigit() or int(success_jump) > len(tasks)):
                return f"第 {i+1} 步小齿轮里的'成功后跳至'必须是 0 到 {len(tasks)} 之间的整数！\n填入内容: {success_jump}"
            if fail_jump and (not fail_jump.isdigit() or int(fail_jump) > len(tasks)):
                return f"第 {i+1} 步小齿轮里的'失败后跳至'必须是 0 到 {len(tasks)} 之间的整数！\n填入内容: {fail_jump}"
            if fail_limit and (not fail_limit.isdigit() or int(fail_limit) < 1):
                return f"第 {i+1} 步小齿轮里的'连续失败次数'必须是大于等于 1 的整数！\n填入内容: {fail_limit}"
            if repeat_mode == "指定次数" and (not repeat_count.isdigit() or int(repeat_count) < 1):
                return f"第 {i+1} 步小齿轮里的'重复次数'必须是大于等于 1 的整数！\n填入内容: {repeat_count}"
            if not step_loop_start.isdigit() or int(step_loop_start) < 1:
                return f"第 {i+1} 步小齿轮里的'循环范围起始'必须是大于等于 1 的整数！\n填入内容: {step_loop_start}"
            if not step_loop_end.isdigit() or int(step_loop_end) < 0:
                return f"第 {i+1} 步小齿轮里的'循环范围停止'必须是大于等于 0 的整数！\n填入内容: {step_loop_end}"
            if int(step_loop_end) > 0 and int(step_loop_end) < int(step_loop_start):
                return f"第 {i+1} 步小齿轮里的'循环范围停止'不能小于起始循环！\n起始循环: {step_loop_start}，停止循环: {step_loop_end}"
            if point_limit_count and not point_limit_count.isdigit():
                return f"第 {i+1} 步小齿轮里的'同点点击上限'必须是大于等于 0 的整数！\n填入内容: {point_limit_count}"
            if image_click_point_en:
                if t not in [1.0, 2.0, 3.0] or self.engine.parse_coordinate(v) or not os.path.isfile(v):
                    return f"第 {i+1} 步小齿轮里的'图片内点击点'仅能用于左键/右键图片点击步骤，且参数必须是存在的图片路径。\n填入内容: {v}"
                try:
                    rx = float(image_click_point_rx)
                    ry = float(image_click_point_ry)
                    if not (0.0 <= rx <= 1.0 and 0.0 <= ry <= 1.0):
                        return f"第 {i+1} 步小齿轮里的'图片内点击点'相对位置必须在 0 到 1 之间！\n填入内容: X={image_click_point_rx}, Y={image_click_point_ry}"
                except:
                    return f"第 {i+1} 步小齿轮里的'图片内点击点'相对位置必须是数字！\n填入内容: X={image_click_point_rx}, Y={image_click_point_ry}"
            if coord_step_en and t in [1.0, 2.0, 3.0] and self.engine.parse_coordinate(v):
                if not coord_step_every.isdigit() or int(coord_step_every) < 1:
                    return f"第 {i+1} 步小齿轮里的'步进频率'必须是大于等于 1 的整数！\n填入内容: {coord_step_every}"
                if coord_step_max_steps and (not coord_step_max_steps.isdigit() or int(coord_step_max_steps) < 0):
                    return f"第 {i+1} 步小齿轮里的'最大偏移次数'必须是大于等于 0 的整数！\n填入内容: {coord_step_max_steps}"
                if coord_step_reset_after and (not coord_step_reset_after.isdigit() or int(coord_step_reset_after) < 0):
                    return f"第 {i+1} 步小齿轮里的'重置循环'必须是大于等于 0 的整数！\n填入内容: {coord_step_reset_after}"
                try:
                    if float(coord_step_max_distance or 0) < 0:
                        return f"第 {i+1} 步小齿轮里的'最大偏移距离'不能小于 0！\n填入内容: {coord_step_max_distance}"
                except:
                    return f"第 {i+1} 步小齿轮里的'最大偏移距离'必须是数字！\n填入内容: {coord_step_max_distance}"
                if coord_step_direction in ["向上", "向下", "向左", "向右"]:
                    try: float(coord_step_distance)
                    except: return f"第 {i+1} 步小齿轮里的'步进距离'必须是数字！\n填入内容: {coord_step_distance}"
                elif coord_step_direction == "自定义偏移":
                    try:
                        float(coord_step_dx); float(coord_step_dy)
                    except:
                        return f"第 {i+1} 步小齿轮里的'自定义偏移 dx/dy'必须是数字！\n填入内容: dx={coord_step_dx}, dy={coord_step_dy}"
                elif coord_step_direction == "移动到新点位":
                    if not self.engine.parse_coordinate(coord_step_point):
                        return f"第 {i+1} 步小齿轮里的'目标点位'必须是 x,y 坐标格式！\n填入内容: {coord_step_point}"
                    if int(coord_step_max_steps or 0) == 1:
                        return f"第 {i+1} 步小齿轮里的'移动上限'在移动到新点位时不能填 1。\n填 0 表示起点后直接移动到目标点；填 2 或更大表示从起点到目标点一共点击多少个点位。"
                else:
                    return f"第 {i+1} 步小齿轮里的'步进方向'无效！\n填入内容: {coord_step_direction}"
            
            if not v and t not in [9.0, 12.0, 13.0, 14.0]: 
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

    def analyze_loop_risks(self, tasks, cfg):
        risks = []
        try:
            global_loop_end = int(float(cfg.get("loop_end_round", 0)))
        except:
            global_loop_end = 0
        if cfg.get("loop_mode") == "无限" and global_loop_end <= 0:
            risks.append("全局循环模式为【无限】，脚本会在步骤列表执行完后重新开始，直到手动停止或急停。")

        for i, task in enumerate(tasks):
            step_no = i + 1
            cmd_name = self.engine.get_cmd_name(task.get("type"))
            repeat_mode = str(task.get("repeat_mode", "执行一次"))
            if repeat_mode == "无限重复":
                risks.append(f"第 {step_no} 步【{cmd_name}】设置为【无限重复】，会一直执行本步骤，直到手动停止或触发失败/超时分支。")
            if config_bool(task.get("no_skip_wait", False)):
                risks.append(f"第 {step_no} 步【{cmd_name}】启用【禁止跳过】，失败时会一直等待本步骤成功，直到满足目标、达到超时或触发急停。")

            try:
                reset_after = int(float(task.get("coord_step_reset_after", 0)))
            except:
                reset_after = 0
            coord_step_en = config_bool(task.get("coord_step_en", False))
            if coord_step_en and reset_after > 0 and self.engine.parse_coordinate(str(task.get("value", "")).strip()):
                if repeat_mode == "无限重复" or cfg.get("loop_mode") == "无限":
                    risks.append(f"第 {step_no} 步【{cmd_name}】启用【坐标步进重置循环】，每成功点击 {reset_after} 次会回到起点；当前又存在无限循环设置，可能会反复点击同一路径。")
                else:
                    risks.append(f"第 {step_no} 步【{cmd_name}】启用【坐标步进重置循环】，每成功点击 {reset_after} 次会回到起点，请确认这是预期的重复路径。")

            for key, label in [("success_jump", "成功后跳至"), ("fail_jump", "失败后跳至")]:
                try:
                    jump_to = int(float(task.get(key, 0)))
                except:
                    jump_to = 0
                if jump_to > 0 and jump_to <= step_no:
                    if jump_to == step_no:
                        risks.append(f"第 {step_no} 步【{cmd_name}】设置【{label}第 {jump_to} 步】，可能在本步骤原地循环。")
                    else:
                        risks.append(f"第 {step_no} 步【{cmd_name}】设置【{label}第 {jump_to} 步】，可能在第 {jump_to} 到第 {step_no} 步之间循环。")
        return risks

    def confirm_loop_risks(self, tasks, cfg):
        risks = self.analyze_loop_risks(tasks, cfg)
        if not risks:
            return True

        signature_src = json.dumps({
            "loop_mode": cfg.get("loop_mode"),
            "loop_start_round": cfg.get("loop_start_round"),
            "loop_end_round": cfg.get("loop_end_round"),
            "risks": risks,
            "tasks": [
                {
                    "type": task.get("type"),
                    "repeat_mode": task.get("repeat_mode"),
                    "step_loop_start": task.get("step_loop_start"),
                    "step_loop_end": task.get("step_loop_end"),
                    "no_skip_wait": task.get("no_skip_wait"),
                    "coord_step_en": task.get("coord_step_en"),
                    "coord_step_reset_after": task.get("coord_step_reset_after"),
                    "success_jump": task.get("success_jump"),
                    "fail_jump": task.get("fail_jump")
                } for task in tasks
            ]
        }, ensure_ascii=False, sort_keys=True)
        signature = hashlib.sha256(signature_src.encode("utf-8")).hexdigest()
        if self.settings.value("ack_loop_risk_signature", "") == signature:
            return True

        preview = "\n".join(risks[:8])
        if len(risks) > 8:
            preview += f"\n……另有 {len(risks) - 8} 条风险未显示。"

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("可能存在无限循环/等待")
        msg.setText("检测到当前方案可能长时间停在某一步或循环执行。")
        msg.setInformativeText(preview)
        msg.setDetailedText("\n".join(risks))
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.button(QMessageBox.Ok).setText("我知道了，继续运行")
        msg.button(QMessageBox.Cancel).setText("取消运行")
        if msg.exec() != QMessageBox.Ok:
            return False
        self.settings.setValue("ack_loop_risk_signature", signature)
        return True

    def start_task(self):
        cfg = self.get_current_ui_config()
        tasks = cfg.get("tasks", [])
        if not tasks: return
        
        err_msg = self.validate_tasks(tasks)
        if err_msg:
            QMessageBox.critical(self, "指令语法错误", err_msg)
            return

        if not self.confirm_loop_risks(tasks, cfg):
            return
            
        try:
            self.engine.min_scale = float(cfg["scale_min"])
            self.engine.max_scale = float(cfg["scale_max"])
            self.engine.scale_step = float(cfg.get("scale_step", "0.05"))
            self.engine.enable_grayscale = bool(cfg.get("gray_en", True))
            self.engine.dodge_x1 = int(cfg["dodge_x1"])
            self.engine.dodge_y1 = int(cfg["dodge_y1"])
            self.engine.dodge_x2 = int(cfg["dodge_x2"])
            self.engine.dodge_y2 = int(cfg["dodge_y2"])
            self.engine.move_duration = float(cfg["move_spd"])
            self.engine.click_hold = float(cfg["click_hld"])
            self.engine.settlement_wait = float(cfg["settle"])
            self.engine.timeout_val = float(cfg["timeout"])
            self.engine.timeout_stop = config_bool(cfg.get("timeout_stop", False))
            self.engine.confidence = float(cfg["conf"])
            self.engine.detect_delay = float(cfg["detect_delay"]) 
            self.engine.adaptive_backoff = config_bool(cfg.get("adaptive_backoff", True))
            self.engine.use_native_core = config_bool(cfg.get("native_core_en", True))
            if SLIM_BUILD:
                self.engine.min_scale = 1.0
                self.engine.max_scale = 1.0
                self.engine.scale_step = 0.05
                self.engine.enable_grayscale = False
                self.engine.use_native_core = False
            self.engine.show_click_indicator = config_bool(cfg.get("click_indicator", True))
            self.engine.use_fast_screenshot = True
            self.engine.playback_speed = float(cfg.get("playback_speed", "1.0"))
            self.engine.start_step_index = max(0, int(float(cfg.get("start_step", "1"))) - 1)
            self.engine.loop_start_round = max(1, int(float(cfg.get("loop_start_round", "1"))))
            self.engine.loop_end_round = max(0, int(float(cfg.get("loop_end_round", "0"))))
            self.engine.multi_target_mode = cfg.get("multi_target_mode", "最佳一个")
            self.engine.multi_target_order = cfg.get("multi_target_order", "从上到下")
            
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
            multi_info = cfg.get("multi_target_mode", "最佳一个")
            if multi_info == "全部匹配":
                multi_info = f"{multi_info}/{cfg.get('multi_target_order', '从上到下')}"
            start_step = int(float(cfg.get("start_step", "1")))
            loop_start_round = int(float(cfg.get("loop_start_round", "1")))
            loop_end_round = int(float(cfg.get("loop_end_round", "0")))
            loop_range_info = f"循环范围: 第{loop_start_round}次起" + (f" 至第{loop_end_round}次" if loop_end_round > 0 else "")
            timeout_mode = "超时急停" if cfg.get("timeout_stop", False) else "超时按失败处理"
            self.append_log(f"<hr><b><font color='blue'>>>> 引擎启动 ({start_key}启动 / {stop_key}停止) - 方案: {self.current_profile_name} - 日志: {self.log_level_combo.currentText()} - 循环: {self.loop_combo.currentText()} - {loop_range_info} - 起始步: {start_step} - 多目标: {multi_info} - {timeout_mode}</font></b>")
            
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        if self.mini_chk.isChecked(): self.showMinimized()

        if cfg.get("run_status_tip", True):
            self.show_running_status_overlay(cfg.get("run_status_pos", "右上角"))
        else:
            self.hide_running_status_overlay()
        
        self.worker = WorkerThread(self.engine, tasks)
        self.worker.log_signal.connect(self.append_log)
        self.worker.status_signal.connect(self.update_running_status_overlay)
        self.worker.click_signal.connect(self.show_click_indicator_overlay)
        self.worker.finished_signal.connect(self.on_finish)
        self.worker.start()

    def stop_task(self):
        self.engine.stop()
        
    def on_finish(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.hide_running_status_overlay()
        self.showNormal()
        self.activateWindow()
        if GLOBAL_CONFIG["log_to_ui"]:
            self.append_log("<b><font color='blue'>引擎运行结束</font></b>")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = RPAWindow()
    win.show()
    sys.exit(app.exec())
