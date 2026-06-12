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

class TaskConfigDialog(QDialog):
    def __init__(self, parent, data, image_settings_available=True, point_limit_available=False):
        super().__init__(None)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowModality(Qt.NonModal)
        self.image_settings_available = image_settings_available and not SLIM_BUILD
        self.point_limit_available = point_limit_available
        self.dialog_settings = QSettings(os.path.join(get_base_dir(), "config.ini"), QSettings.IniFormat)
        self.setWindowTitle("步骤设置")
        self.setMinimumSize(560, 560)
        layout = QVBoxLayout(self)
        
        note = QLabel("精简版仅支持原图原尺寸精确识别；已去掉相似度、缩放和灰度识别。")
        note.setStyleSheet("color: #666;")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.enable_chk = QCheckBox("✓ 为当前图片指令启用独立识别参数")
        self.enable_chk.setChecked(data.get("custom_en", False))
        self.enable_chk.setStyleSheet("font-weight: bold; color: #E91E63;")
        layout.addWidget(self.enable_chk)
        if SLIM_BUILD:
            self.enable_chk.hide()
        
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
        if SLIM_BUILD:
            self.form_widget.hide()
        self.enable_chk.setEnabled(self.image_settings_available)
        self.form_widget.setEnabled(self.image_settings_available and self.enable_chk.isChecked())
        self.enable_chk.toggled.connect(self.update_image_settings_enabled)

        if not self.image_settings_available:
            disabled_note = QLabel("精简版已移除独立识别参数；图片步骤会按原图原尺寸精确匹配。")
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

        self.point_limit_chk = QCheckBox("图片点击同一点位达到上限后忽略此点位")
        self.point_limit_chk.setChecked(config_bool(data.get("point_limit_en", False)) and self.point_limit_available)
        self.point_limit_chk.setEnabled(self.point_limit_available)
        self.point_limit_chk.setToolTip("仅对图片点击生效。填坐标时自动忽略；达到上限后会尝试点击下一个匹配点位。")
        self.point_limit_chk.toggled.connect(self.update_point_limit_ui)

        self.point_limit_count_edit = QLineEdit(str(data.get("point_limit_count", "0")))
        self.point_limit_count_edit.setFixedWidth(90)
        self.point_limit_count_edit.setToolTip("填 0 表示不限制；例如填 1 表示同一个识别点位只点击一次。")

        self.fail_limit_edit = QLineEdit(str(data.get("fail_limit", "1")))
        self.fail_limit_edit.setFixedWidth(90)
        self.fail_limit_edit.setToolTip("例如填 1 表示失败一次就执行下一步；填 3 表示连续失败三次后才放弃本步。")

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
        control_form.addRow("同点点击上限:", self.point_limit_chk)
        control_form.addRow("上限次数:", self.point_limit_count_edit)
        control_form.addRow("连续失败次数:", self.fail_limit_edit)
        control_form.addRow("禁止跳过:", self.no_skip_wait_chk)
        control_form.addRow("成功后跳过:", self.success_skip_edit)
        control_form.addRow("成功后跳至:", self.success_jump_edit)
        control_form.addRow("失败后跳过:", self.fail_skip_edit)
        control_form.addRow("失败后跳至:", self.fail_jump_edit)

        control_note = QLabel("跳至填 0 表示关闭；同一结果里“跳至”优先于“跳过”。开启禁止跳过后，失败分支会等到成功或超时后再处理。")
        control_note.setStyleSheet("color: #666;")
        control_note.setWordWrap(True)
        control_form.addRow("", control_note)
        layout.addWidget(control_box)
        self.update_repeat_ui()
        self.update_point_limit_ui()
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        geometry = self.dialog_settings.value("task_config_dialog_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(620, 650)

    def update_image_settings_enabled(self):
        self.form_widget.setEnabled(self.image_settings_available and self.enable_chk.isChecked())

    def update_repeat_ui(self, _=None):
        self.repeat_count_edit.setEnabled(self.repeat_combo.currentText() == "指定次数")

    def update_point_limit_ui(self, _=None):
        self.point_limit_count_edit.setEnabled(self.point_limit_available and self.point_limit_chk.isChecked())

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
            "point_limit_en": self.point_limit_chk.isChecked() and self.point_limit_available,
            "point_limit_count": self.point_limit_count_edit.text(),
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
            mask_region = QRegion(self.rect())
            clear_region = QRegion()
            for rect in regions:
                clear_region = clear_region.united(QRegion(rect))
            overlay_region = mask_region.subtracted(clear_region)
            
            painter.setClipRegion(overlay_region)
            painter.fillRect(self.rect(), bg_color)
            painter.setClipping(False)
            
            pen = QPen(QColor(0, 255, 0), 2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
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
                hint = f"左键拖拽添加多个区域 | 右键完成 | 缩放比: {self.scale_x:.2f}"
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
        self.playback_speed = 1.0
        self.start_step_index = 0
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
        self.opencv_available = False 
        self.img_cache = {} 
        self.scaled_templates_cache = {}
        self.point_click_counts = {}

        self.check_engine_status()
        self.set_high_priority()

    def set_high_priority(self):
        try:
            pid = os.getpid()
            handle = ctypes.windll.kernel32.OpenProcess(0x0100, True, pid)
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000080)
        except: pass

    def check_engine_status(self):
        self.opencv_available = False
        write_log("精简版引擎就绪：已移除 OpenCV/NumPy，仅支持原图原尺寸精确匹配。")

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

    def check_stop_flag(self):
        return self.stop_requested

    def wait_recognition_interval(self):
        if self.detect_delay <= 0:
            return True
        end_time = time.time() + self.detect_delay
        while time.time() < end_time:
            if self.check_stop_flag():
                return False
            time.sleep(min(0.05, max(0.0, end_time - time.time())))
        return True

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

    def load_and_precompute(self, tasks):
        try:
            write_log("正在预加载精简版图片资源...")
            for task in tasks:
                path = str(task.get("value", ""))
                if not path or not os.path.exists(path) or ',' in path: continue
                if task.get("type") not in [1.0, 2.0, 3.0, 8.0]: continue
                
                img = Image.open(path)
                img.load()
                self.img_cache[path] = img
                task['cache_key'] = path
            write_log("精简版图片资源预加载完成。")
        except Exception as e:
            write_log(f"预计算失败: {e}")

    def find_target_optimized(self, img_path, cache_key, task_conf, use_gray):
        active_regions = self.normalized_regions(getattr(self, "scan_regions", []))
        if active_regions:
            old_region = self.scan_region
            old_regions = self.scan_regions
            try:
                self.scan_regions = []
                for region in active_regions:
                    if self.check_stop_flag(): return None
                    self.scan_region = region
                    found = self.find_target_optimized(img_path, cache_key, task_conf, use_gray)
                    if found:
                        return found
            finally:
                self.scan_region = old_region
                self.scan_regions = old_regions
            return None

        try: screenshot_pil = pyautogui.screenshot(region=self.scan_region)
        except: return None
        
        offset_x = self.scan_region[0] if self.scan_region else 0
        offset_y = self.scan_region[1] if self.scan_region else 0

        target = self.img_cache.get(img_path, img_path)
        if img_path not in self.img_cache and not os.path.exists(str(img_path)):
            return None
        try:
            res = pyautogui.locate(target, screenshot_pil)
            if res:
                return (res.left + (res.width / 2) + offset_x, res.top + (res.height / 2) + offset_y, 1.0)
        except: pass
        return None

    def _collect_template_matches(self, screen_img, tpl_img, task_conf, offset_x, offset_y, scale):
        return []

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

    def find_all_targets_optimized(self, img_path, cache_key, task_conf, use_gray):
        active_regions = self.normalized_regions(getattr(self, "scan_regions", []))
        if active_regions:
            old_region = self.scan_region
            old_regions = self.scan_regions
            all_targets = []
            try:
                self.scan_regions = []
                for region in active_regions:
                    if self.check_stop_flag(): return []
                    self.scan_region = region
                    all_targets.extend(self.find_all_targets_optimized(img_path, cache_key, task_conf, use_gray))
            finally:
                self.scan_region = old_region
                self.scan_regions = old_regions

            target_dicts = [{
                "x": float(x),
                "y": float(y),
                "scale": float(scale),
                "score": float(score),
                "radius": 8.0
            } for x, y, scale, score in all_targets]
            targets = self._sort_targets_for_click(self._dedupe_targets(target_dicts))
            return [(p["x"], p["y"], p["scale"], p["score"]) for p in targets]

        try: screenshot_pil = pyautogui.screenshot(region=self.scan_region)
        except: return []

        offset_x = self.scan_region[0] if self.scan_region else 0
        offset_y = self.scan_region[1] if self.scan_region else 0

        target = self.img_cache.get(img_path, img_path)
        if img_path not in self.img_cache and not os.path.exists(str(img_path)):
            return []
        try:
            boxes = list(pyautogui.locateAll(target, screenshot_pil))
            matches = [{
                "x": box.left + (box.width / 2) + offset_x,
                "y": box.top + (box.height / 2) + offset_y,
                "scale": 1.0,
                "score": 1.0,
                "radius": max(4.0, min(box.width, box.height) * 0.55)
            } for box in boxes]
        except:
            one = self.find_target_optimized(img_path, cache_key, task_conf, use_gray)
            return [(one[0], one[1], one[2], 1.0)] if one else []

        targets = self._sort_targets_for_click(self._dedupe_targets(matches))
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
        try:
            val_str = str(val).strip()
            if ',' in val_str:
                parts = val_str.split(',')
                if len(parts) == 2:
                    return int(parts[0].strip()), int(parts[1].strip())
        except: pass
        return None

    def perform_mouse_click(self, x, y, clickTimes, lOrR):
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

    def mouseClick(self, clickTimes, lOrR, img_path, reTry, step_info=None, cache_key=None, task_conf=0.8, use_gray=True, point_limit_en=False, point_limit_count=0):
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
                if point_limit_en:
                    locations = self._filter_point_limit_targets(locations, img_path, step_info, point_limit_en, point_limit_count)
                    if not locations:
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
                        self.log(f"    -> 已在坐标 ({int(x)}, {int(y)}) 锁定目标并执行点击")

                    for target_idx, location_tuple in enumerate(click_locations, 1):
                        if self.check_stop_flag(): return "stopped"
                        x, y, scale, score = location_tuple
                        if use_all_targets and self.log_level >= 2:
                            self.log(f"       多目标 {target_idx}/{len(click_locations)} -> ({int(x)}, {int(y)}) 相似度 {score:.3f} 缩放 {scale:.2f}x")
                        self.perform_mouse_click(x, y, clickTimes, lOrR)
                        if point_limit_en:
                            used_count = self._record_point_click(img_path, step_info, x, y)
                            if self.log_level >= 2:
                                self.log(f"       同点位已点击 {used_count}/{point_limit_count} 次")
                            
                except Exception as e: 
                    if self.log_level >= 1: self.log(f"<font color='red'>    [错误] 循环#{step_info['loop']} 步{step_info['step']}: {e}</font>")
                    return "error"
                return "success"
            else:
                if reTry != -1:
                    if self.log_level >= 1:
                        self.log(f"<font color='orange'>    [未找到] 循环#{step_info['loop']} 步{step_info['step']}: 未能识别到目标图片 ({os.path.basename(img_path)})</font>")
                    return "not_found"
                else:
                    if not waiting_logged and self.log_level >= 1:
                        self.log(f"    -> 未发现目标，进入持续监听等待状态...")
                        waiting_logged = True
                    if not self.wait_recognition_interval():
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
        if self.settlement_wait > 0: time.sleep(self.settlement_wait)
        return "success"

    def execute_task_once(self, cmd, val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en=False, point_limit_count=0):
        status = "success"
        try:
            if cmd == 1.0: status = self.mouseClick(1, "left", val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en, point_limit_count)
            elif cmd == 2.0: status = self.mouseClick(2, "left", val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en, point_limit_count)
            elif cmd == 3.0: status = self.mouseClick(1, "right", val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en, point_limit_count)
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

    def run_tasks(self, tasks, callback_msg=None, callback_status=None):
        self.is_running = True
        self.stop_requested = False
        self.callback_msg = callback_msg
        self.callback_status = callback_status
        
        self.img_cache = {}
        self.scaled_templates_cache = {}
        self.point_click_counts = {}
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

                self.report_status(loop_count, 0, len(tasks), "")

                idx = min(max(int(getattr(self, "start_step_index", 0)), 0), max(len(tasks) - 1, 0))
                while idx < len(tasks):
                    task = tasks[idx]
                    
                    if self.check_stop_flag():
                        if callback_msg: callback_msg("任务由看门狗终止")
                        return

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
                        if (needs_recognition_wait or no_skip_wait) and not self.wait_recognition_interval():
                            return
                        status = self.execute_task_once(cmd, val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en, point_limit_count)

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

                    idx = next_idx

                if self.check_stop_flag(): return
                
        except Exception as e:
            self.log(f"<font color='red'>引擎异常: {e}</font>")
        finally:
            self.is_running = False
            self.callback_status = None
            if callback_msg: callback_msg("结束")

# --------------------------
# GUI 界面
# --------------------------
class WorkerThread(QThread):
    log_signal = Signal(str)
    status_signal = Signal(dict)
    finished_signal = Signal()
    def __init__(self, engine, tasks):
        super().__init__()
        self.engine = engine
        self.tasks = tasks

    def run(self):
        self.watchdog = FailsafeWatchdog(self.engine)
        self.watchdog.start()
        self.engine.run_tasks(self.tasks, self.log_callback, self.status_callback)
        if self.watchdog: self.watchdog.kill()
        self.finished_signal.emit()

    def log_callback(self, msg): 
        if GLOBAL_CONFIG["log_to_ui"]:
            self.log_signal.emit(msg)

    def status_callback(self, data):
        self.status_signal.emit(data)

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
            "fail_limit": "1",
            "success_skip": "0",
            "success_jump": "0",
            "fail_skip": "0",
            "fail_jump": "0",
            "no_skip_wait": False,
            "point_limit_en": False,
            "point_limit_count": "0"
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
        if "单击" in text or "双击" in text or "悬停" in text:
            self.cfg_btn.setVisible(True)
            if coord_mode:
                self.cfg_btn.setToolTip("步骤设置\n当前参数是屏幕坐标，图片识别参数会自动忽略；重复和条件分支仍然生效")
            else:
                self.cfg_btn.setToolTip("步骤设置\n包含图片识别参数、重复次数、同点点击上限和条件分支")
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
        return f"{self.index_label.text()} {self.type_combo.currentText()} | {value}"

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

        dialog = TaskConfigDialog(None, self.custom_data, self.image_settings_available(), self.point_limit_available())
        self.config_dialog = dialog
        dialog.accepted.connect(lambda d=dialog: self.apply_custom_config(d))
        dialog.finished.connect(lambda _result, d=dialog: self.clear_custom_config_dialog(d))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def apply_custom_config(self, dialog):
        self.custom_data = dialog.get_data()
        self.sync_data()

    def clear_custom_config_dialog(self, dialog):
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
            "fail_limit": data.get("fail_limit", "1"),
            "success_skip": data.get("success_skip", "0"),
            "success_jump": data.get("success_jump", "0"),
            "fail_skip": data.get("fail_skip", "0"),
            "fail_jump": data.get("fail_jump", "0"),
            "no_skip_wait": data.get("no_skip_wait", False),
            "point_limit_en": data.get("point_limit_en", False),
            "point_limit_count": data.get("point_limit_count", "0")
        }
        
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
        self.setWindowTitle("不高兴就喝水 RPA配置工具(浮夸改v1.3 精简版)")
        self.resize(800, 850)
        self.engine = RPAEngine()
        
        self.config_path = os.path.join(get_base_dir(), "config.ini")
        self.settings = QSettings(self.config_path, QSettings.IniFormat)
        self.recorder_ui = None
        
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        self.profiles_data = {}
        self.current_profile_name = "默认方案"
        self.is_switching_profile = True 
        
        self.hotkey_start_vk = 0x78 
        self.hotkey_stop_vk = 0x79  
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
        
        top_bar.addWidget(HelpBtn("【设定识别区域】\n如CPU占用较高，务必使用此功能！\n左键拖拽框选一个或多个区域，右键完成。\n只画一个区域就是普通用法；连续画多个区域就是高级合并用法。\n搜索范围越小，找图速度越快。"))
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
        g1.set_content_layout(gl1)
        settings_content_layout.addWidget(g1)
        if SLIM_BUILD:
            g1.hide()
            slim_note = QLabel("精简版识别模式：已去掉相似度、缩放识别、灰度识别和 OpenCV/NumPy 运行库，仅按原图原尺寸精确匹配。")
            slim_note.setStyleSheet("color: #666; font-weight: bold;")
            slim_note.setWordWrap(True)
            settings_content_layout.addWidget(slim_note)
        
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
        gl2.addWidget(QLabel("缓冲(s):")); self.settle = QLineEdit("0.0"); self.settle.setFixedWidth(70); gl2.addWidget(self.settle)
        gl2.addWidget(HelpBtn("【结算缓冲】 点击后的等待时间"))
        gl2.addSpacing(15)
        gl2.addWidget(QLabel("超时(s):")); self.timeout = QLineEdit("0.0"); self.timeout.setFixedWidth(70); gl2.addWidget(self.timeout)
        gl2.addWidget(HelpBtn("【单步超时】\n0 表示不设置等待上限。\n未开启“超时急停”时：达到超时会把本步骤视为失败，再按小齿轮里的失败跳过/跳至规则处理。\n开启“超时急停”时：达到超时会立即停止整个脚本和后续循环。"))
        self.timeout_stop_chk = QCheckBox("超时急停")
        self.timeout_stop_chk.setToolTip("开启后，任意步骤达到单步超时都会立即停止全部循环，不再执行后续步骤。")
        gl2.addWidget(self.timeout_stop_chk)
        gl2.addSpacing(15)
        gl2.addWidget(QLabel("识别频率(s):")); self.detect_delay = QLineEdit("0"); self.detect_delay.setFixedWidth(70); gl2.addWidget(self.detect_delay)
        gl2.addWidget(HelpBtn("【识别频率】\n每次执行识别/重试前先等待这么多秒，用于降低CPU占用。\n0 表示不额外等待，速度最快但CPU压力更高。"))
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
        gl_multi.addWidget(HelpBtn("【目标模式】\n最佳一个：沿用原逻辑，只点击相似度最高的目标。\n全部匹配：一次找出所有超过相似度阈值的目标并逐个点击。"))
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
        self.mini_chk = QCheckBox("启动时最小化"); gl3_r2.addWidget(self.mini_chk)
        self.top_chk = QCheckBox("窗口置顶"); self.top_chk.stateChanged.connect(self.toggle_top_window)
        gl3_r2.addWidget(self.top_chk)
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
        gl3_r3.addWidget(QLabel("从第"))
        self.start_step_edit = QLineEdit("1")
        self.start_step_edit.setFixedWidth(60)
        gl3_r3.addWidget(self.start_step_edit)
        gl3_r3.addWidget(QLabel("步开始"))
        gl3_r3.addWidget(HelpBtn("【从第X步开始执行】\n默认 1。启动脚本后每轮循环都从这里开始；成功/失败跳至仍按列表中的实际步号计算。"))
        gl3_r3.addStretch()
        
        gl3_main.addLayout(gl3_r1)
        gl3_main.addLayout(gl3_r2)
        gl3_main.addLayout(gl3_r3)
        g3.set_content_layout(gl3_main)
        settings_content_layout.addWidget(g3)
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
        try:
            config_dir = os.path.normpath(get_base_dir())
            if not os.path.isdir(config_dir):
                config_dir = os.path.dirname(os.path.abspath(self.config_path))
            subprocess.Popen(["explorer.exe", config_dir])
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开配置目录: {e}")

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
            "conf": "0.8", "scale_min": "0.8", "scale_max": "1.2", "scale_step": "0.05", "gray_en": True,
            "dodge_x1": "100", "dodge_y1": "100", "dodge_x2": "200", "dodge_y2": "100",
            "dodge_en": False, "dbl_dodge": False, "dbl_wait": "0.015",
            "move_spd": "0.0", "click_hld": "0.04", "settle": "0.0", "timeout": "0.0", "timeout_stop": False, "detect_delay": "0", "playback_speed": "1.0",
            "multi_target_mode": "最佳一个", "multi_target_order": "从上到下",
            "hotkey_start": "F9", "hotkey_stop": "F10", "log_level": 0,
            "tm_fs": True, "tr_fs": True, "key_fs": True,
            "log_f": False, "log_ui": True, "mini": False, "top": False,
            "run_status_tip": True, "run_status_pos": "右上角", "start_step": "1",
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
            "conf": self.conf_edit.text(), "scale_min": self.scale_min.text(), "scale_max": self.scale_max.text(), "scale_step": self.scale_step.text(), "gray_en": self.gray_chk.isChecked(),
            "dodge_x1": self.dodge_x1.text(), "dodge_y1": self.dodge_y1.text(), "dodge_x2": self.dodge_x2.text(), "dodge_y2": self.dodge_y2.text(),
            "dodge_en": self.dodge_chk.isChecked(), "dbl_dodge": self.double_dodge_chk.isChecked(), "dbl_wait": self.dbl_wait.text(),
            "move_spd": self.move_spd.text(), "click_hld": self.click_hld.text(), "settle": self.settle.text(), "timeout": self.timeout.text(), "timeout_stop": self.timeout_stop_chk.isChecked(), "detect_delay": self.detect_delay.text(), "playback_speed": self.playback_speed.text(),
            "multi_target_mode": self.multi_mode_combo.currentText(), "multi_target_order": self.multi_order_combo.currentText(),
            "hotkey_start": self.hotkey_start_combo.currentText(), "hotkey_stop": self.hotkey_stop_combo.currentText(), "log_level": self.log_level_combo.currentIndex(),
            "tm_fs": self.tm_failsafe.isChecked(), "tr_fs": self.tr_failsafe.isChecked(), "key_fs": self.key_failsafe.isChecked(),
            "log_f": self.log_file_chk.isChecked(), "log_ui": self.log_ui_chk.isChecked(), "mini": self.mini_chk.isChecked(), "top": self.top_chk.isChecked(),
            "run_status_tip": self.run_status_chk.isChecked(), "run_status_pos": self.run_status_pos_combo.currentText(), "start_step": self.start_step_edit.text(),
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
            self.dodge_x1.setText(str(cfg.get("dodge_x1", "100")))
            self.dodge_y1.setText(str(cfg.get("dodge_y1", "100")))
            self.dodge_x2.setText(str(cfg.get("dodge_x2", "200")))
            self.dodge_y2.setText(str(cfg.get("dodge_y2", "100")))
            self.dodge_chk.setChecked(bool(cfg.get("dodge_en", False)))
            self.double_dodge_chk.setChecked(bool(cfg.get("dbl_dodge", False)))
            self.dbl_wait.setText(str(cfg.get("dbl_wait", "0.015")))
            
            self.move_spd.setText(str(cfg.get("move_spd", "0.0")))
            self.click_hld.setText(str(cfg.get("click_hld", "0.04")))
            self.settle.setText(str(cfg.get("settle", "0.0")))
            self.timeout.setText(str(cfg.get("timeout", "0.0")))
            self.timeout_stop_chk.setChecked(config_bool(cfg.get("timeout_stop", False)))
            self.detect_delay.setText(str(cfg.get("detect_delay", "0")))
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
            self.start_step_edit.setText(str(cfg.get("start_step", "1")))
            
            self.loop_combo.setCurrentText(str(cfg.get("loop_mode", "单次")))
            self.loop_val_edit.setText(str(cfg.get("loop_val", "10")))
            self.apply_scan_region_config(cfg.get("scan_region"), cfg.get("scan_regions"))
            
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
        self.settle.editingFinished.connect(lambda: self.log_setting_change("结算缓冲(s)", self.settle.text()))
        self.timeout.editingFinished.connect(lambda: self.log_setting_change("单步超时(s)", self.timeout.text()))
        self.detect_delay.editingFinished.connect(lambda: self.log_setting_change("识别频率(s)", self.detect_delay.text()))
        self.playback_speed.editingFinished.connect(lambda: self.log_setting_change("倍速执行", self.playback_speed.text()))
        self.loop_val_edit.editingFinished.connect(lambda: self.log_setting_change("循环参数", self.loop_val_edit.text()))
        self.start_step_edit.editingFinished.connect(lambda: self.log_setting_change("从第X步开始", self.start_step_edit.text()))

        self.gray_chk.stateChanged.connect(lambda s: self.log_setting_change("灰度匹配", "开启" if s else "关闭"))
        self.dodge_chk.stateChanged.connect(lambda s: self.log_setting_change("启用避让", "开启" if s else "关闭"))
        self.double_dodge_chk.stateChanged.connect(lambda s: self.log_setting_change("二段避让", "开启" if s else "关闭"))
        self.tm_failsafe.stateChanged.connect(lambda s: self.log_setting_change("任务管理器急停", "开启" if s else "关闭"))
        self.tr_failsafe.stateChanged.connect(lambda s: self.log_setting_change("右上角急停", "开启" if s else "关闭"))
        self.key_failsafe.stateChanged.connect(lambda s: self.log_setting_change("ESC/中键急停", "开启" if s else "关闭"))
        self.log_file_chk.stateChanged.connect(lambda s: self.log_setting_change("写入文件日志", "开启" if s else "关闭"))
        self.log_ui_chk.stateChanged.connect(lambda s: self.log_setting_change("显示界面日志", "开启" if s else "关闭"))
        self.mini_chk.stateChanged.connect(lambda s: self.log_setting_change("启动时最小化", "开启" if s else "关闭"))
        self.run_status_chk.stateChanged.connect(lambda s: self.log_setting_change("运行状态提示", "开启" if s else "关闭"))
        self.timeout_stop_chk.stateChanged.connect(lambda s: self.log_setting_change("超时急停", "开启" if s else "关闭"))
        
        self.hotkey_start_combo.currentTextChanged.connect(lambda t: self.log_setting_change("启动热键", t))
        self.hotkey_stop_combo.currentTextChanged.connect(lambda t: self.log_setting_change("停止热键", t))
        self.log_level_combo.currentTextChanged.connect(lambda t: self.log_setting_change("日志级别", t))
        self.loop_combo.currentTextChanged.connect(lambda t: self.log_setting_change("循环模式", t))
        self.multi_mode_combo.currentTextChanged.connect(lambda t: self.log_setting_change("多目标模式", t))
        self.multi_order_combo.currentTextChanged.connect(lambda t: self.log_setting_change("多目标顺序", t))
        self.run_status_pos_combo.currentTextChanged.connect(lambda t: self.log_setting_change("运行提示位置", t))

    def log_setting_change(self, name, value):
        if GLOBAL_CONFIG["log_to_ui"] and not self.is_switching_profile:
            self.append_log(f"<font color='#FF9800'><b>设置已生效：</b>{name} -> {value}</font>")

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
            QTimer.singleShot(500, lambda: self.hotkey_timer.start(100))
            return
            
        if stop_pressed and self.engine.is_running:
            self.stop_task()
            self.hotkey_timer.stop()
            QTimer.singleShot(500, lambda: self.hotkey_timer.start(100))
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
            self.settings.setValue("window_geometry", self.saveGeometry())
            if getattr(self, "settings_dialog", None):
                self.settings_dialog.save_dialog_geometry()
            self.profiles_data[self.current_profile_name] = self.get_current_ui_config()
            self.settings.setValue("profiles_json", json.dumps(self.profiles_data))
            self.settings.setValue("current_profile", self.current_profile_name)
            
            if getattr(self, 'worker', None) and self.worker.isRunning():
                self.engine.stop()
                self.worker.quit()
                self.worker.wait(1000)
            if self.running_overlay:
                self.running_overlay.close()
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

        for i, task in enumerate(tasks):
            t = task.get("type")
            v = str(task.get("value", "")).strip()
            success_skip = str(task.get("success_skip", "0")).strip()
            success_jump = str(task.get("success_jump", "0")).strip()
            fail_skip = str(task.get("fail_skip", "0")).strip()
            fail_jump = str(task.get("fail_jump", "0")).strip()
            repeat_mode = str(task.get("repeat_mode", "执行一次"))
            repeat_count = str(task.get("repeat_count", "1")).strip()
            fail_limit = str(task.get("fail_limit", "1")).strip()
            point_limit_count = str(task.get("point_limit_count", "0")).strip()
            
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
            if point_limit_count and not point_limit_count.isdigit():
                return f"第 {i+1} 步小齿轮里的'同点点击上限'必须是大于等于 0 的整数！\n填入内容: {point_limit_count}"
            
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

    def start_task(self):
        cfg = self.get_current_ui_config()
        tasks = cfg.get("tasks", [])
        if not tasks: return
        
        err_msg = self.validate_tasks(tasks)
        if err_msg:
            QMessageBox.critical(self, "指令语法错误", err_msg)
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
            self.engine.click_hld = float(cfg["click_hld"])
            self.engine.settlement_wait = float(cfg["settle"])
            self.engine.timeout_val = float(cfg["timeout"])
            self.engine.timeout_stop = config_bool(cfg.get("timeout_stop", False))
            self.engine.confidence = float(cfg["conf"])
            self.engine.detect_delay = float(cfg["detect_delay"]) 
            self.engine.playback_speed = float(cfg.get("playback_speed", "1.0"))
            self.engine.start_step_index = max(0, int(float(cfg.get("start_step", "1"))) - 1)
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
            timeout_mode = "超时急停" if cfg.get("timeout_stop", False) else "超时按失败处理"
            self.append_log(f"<hr><b><font color='blue'>>>> 引擎启动 ({start_key}启动 / {stop_key}停止) - 方案: {self.current_profile_name} - 日志: {self.log_level_combo.currentText()} - 循环: {self.loop_combo.currentText()} - 起始步: {start_step} - 多目标: {multi_info} - {timeout_mode}</font></b>")
            
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
