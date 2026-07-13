"""Screen region picking, coordinate picking, hotkey capture, and operation recording."""

import ctypes
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..coordinates import ScreenCoordinateMapper
from ..logging_service import write_log
from ..pyautogui_runtime import pyautogui
from ..recording_model import recorded_events_to_tasks
from ..win32_api import (
    GetAsyncKeyState,
    HOOKPROC,
    KBDLLHOOKSTRUCT,
    MSLLHOOKSTRUCT,
    PM_NOREMOVE,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_QUIT,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
    hotkey_text_from_pressed_vks,
    kernel32,
    key_event_to_hotkey_text,
    MODIFIER_VKS,
    parse_hotkey_text,
    pressed_hotkey_display_text,
    user32,
)

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
        
        self.screen_mapper = ScreenCoordinateMapper()
        self.screen_mapper.apply_to(self)
        
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
        return self.screen_mapper.local_rect_to_physical(rect)

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
                _real_x, _real_y, real_w, real_h = self.physical_rect(rect)
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
                hint = "左键拖拽添加多个小区域 | 右键完成 | 区域相近时建议框成一个大矩形"
            else:
                hint = "请框选区域 | 右键取消"
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

class MultiPointPickerUI(QWidget):
    def __init__(self, point_callback, finish_callback=None):
        super().__init__()
        self.point_callback = point_callback
        self.finish_callback = finish_callback
        self.points = []
        self.current_pos = QPoint(0, 0)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        self.screen_mapper = ScreenCoordinateMapper()
        self.screen_mapper.apply_to(self)
        self.show()
        self.raise_()
        self.activateWindow()

    def logical_to_physical(self, point):
        return self.screen_mapper.local_to_physical(point)

    def physical_to_logical(self, x, y):
        return self.screen_mapper.physical_to_local(x, y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 85))

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 15, QFont.Bold))
        hint = f"左键连续添加点位 | 右键/Esc完成 | 已添加 {len(self.points)} 个点"
        fm = painter.fontMetrics()
        painter.drawText((self.width() - fm.horizontalAdvance(hint)) // 2, 80, hint)

        painter.setFont(QFont("Arial", 10, QFont.Bold))
        for idx, (x, y) in enumerate(self.points, 1):
            p = self.physical_to_logical(x, y)
            painter.setBrush(QColor(255, 193, 7, 235))
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawEllipse(p, 8, 8)
            label_rect = QRect(p.x() + 10, p.y() - 20, 44, 20)
            painter.fillRect(label_rect, QColor(0, 0, 0, 165))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(label_rect, Qt.AlignCenter, str(idx))

        x, y = self.logical_to_physical(self.current_pos)
        painter.setPen(QColor(255, 255, 0))
        painter.setFont(QFont("Arial", 10))
        painter.drawText(self.current_pos.x() + 18, self.current_pos.y() + 28, f"Pos: {x},{y}")

    def mouseMoveEvent(self, event):
        self.current_pos = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x, y = self.logical_to_physical(event.position().toPoint())
            self.points.append((x, y))
            if self.point_callback:
                self.point_callback(f"{x},{y}")
            self.update()
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self.close()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.finish_callback:
            self.finish_callback(self.points)
        super().closeEvent(event)

class HotkeyCaptureHookThread(QThread):
    """Capture one complete combination before Qt can consume Alt/Ctrl events."""

    captured = Signal(str)
    cancelled = Signal()
    progress = Signal(str)

    def __init__(self):
        super().__init__()
        self.thread_id = None
        self.keyboard_hook = None
        self.pressed_vks = set()
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.install_error = ""
        self.completed = False

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        if self.stop_event.is_set():
            self.ready_event.set()
            return
        try:
            self.kb_pointer = HOOKPROC(self.keyboard_handler)
            self.keyboard_hook = user32.SetWindowsHookExW(
                13, self.kb_pointer, kernel32.GetModuleHandleW(None), 0
            )
            if not self.keyboard_hook:
                self.install_error = "无法启用底层键盘录入，已切换到兼容模式。"
                return
            self.ready_event.set()
            while (
                not self.stop_event.is_set()
                and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0
            ):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self.ready_event.set()
            if getattr(self, "keyboard_hook", None):
                user32.UnhookWindowsHookEx(self.keyboard_hook)
                self.keyboard_hook = None

    def stop(self):
        self.stop_event.set()
        if getattr(self, "thread_id", None):
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    def keyboard_handler(self, nCode, wParam, lParam):
        if self.stop_event.is_set():
            return user32.CallNextHookEx(None, nCode, wParam, lParam)
        if nCode < 0:
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        event = int(wParam)
        struct = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = int(struct.vkCode)
        if event in (WM_KEYDOWN, WM_SYSKEYDOWN):
            self.pressed_vks.add(vk)
            if not self.completed:
                self.progress.emit(pressed_hotkey_display_text(self.pressed_vks))
            if not self.completed and vk not in MODIFIER_VKS:
                hotkey_text = hotkey_text_from_pressed_vks(vk, self.pressed_vks)
                parsed = parse_hotkey_text(hotkey_text)
                if parsed:
                    self.completed = True
                    if parsed["bare"] and parsed["key"] == "esc":
                        self.cancelled.emit()
                    else:
                        self.captured.emit(parsed["text"])
            return 1
        if event in (WM_KEYUP, WM_SYSKEYUP):
            self.pressed_vks.discard(vk)
            if not self.completed:
                self.progress.emit(pressed_hotkey_display_text(self.pressed_vks))
            return 1
        return user32.CallNextHookEx(None, nCode, wParam, lParam)


class KeyCaptureDialog(QDialog):
    def __init__(self, parent=None, title="录入按键"):
        super().__init__(parent)
        self.captured_text = ""
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(360, 150)
        layout = QVBoxLayout(self)
        info = QLabel(
            "请直接按下要录入的按键或组合键。\n"
            "例如：A、Enter、Alt+A、Ctrl+Shift+S、Ctrl+Alt+Shift+A。\n"
            "按 Esc 取消。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self.preview_label = QLabel("正在准备底层按键录入...")
        self.preview_label.setAlignment(Qt.AlignCenter)
        preview_font = QFont(self.preview_label.font())
        preview_font.setPointSizeF(max(13.0, QApplication.font().pointSizeF() * 1.65))
        preview_font.setBold(True)
        self.preview_label.setFont(preview_font)
        self.preview_label.setStyleSheet("color: #2563EB;")
        layout.addWidget(self.preview_label)
        btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.capture_thread = HotkeyCaptureHookThread()
        self.capture_thread.captured.connect(self.on_native_captured)
        self.capture_thread.cancelled.connect(self.reject)
        self.capture_thread.progress.connect(self.on_native_progress)
        self.capture_thread.start()
        self.capture_thread.ready_event.wait(0.8)
        if self.capture_thread.keyboard_hook:
            self.preview_label.setText("等待按键...")
        else:
            self.preview_label.setText(
                self.capture_thread.install_error or "底层录入启动较慢，请直接按键"
            )

    def on_native_progress(self, text):
        if self.captured_text:
            return
        self.preview_label.setText(f"当前按下：{text}" if text else "等待按键...")

    def on_native_captured(self, text):
        parsed = parse_hotkey_text(text)
        if not parsed:
            self.preview_label.setText("请再按一个非修饰键")
            return
        self.captured_text = parsed["text"]
        self.preview_label.setText(f"已录入：{parsed['display']}")
        QTimer.singleShot(220, self.accept)

    def keyPressEvent(self, event):
        if getattr(self, "capture_thread", None) and self.capture_thread.keyboard_hook:
            event.accept()
            return
        text = key_event_to_hotkey_text(event)
        if not text:
            self.reject()
            return
        parsed = parse_hotkey_text(text)
        if not parsed:
            self.preview_label.setText("请再按一个非修饰键")
            return
        self.captured_text = parsed["text"]
        self.preview_label.setText(f"已录入：{parsed['display']}")
        QTimer.singleShot(220, self.accept)

    def done(self, result):
        thread = getattr(self, "capture_thread", None)
        if thread and thread.isRunning():
            thread.stop()
            if not thread.wait(1500):
                write_log("热键录入钩子仍在停止中。")
        super().done(result)

class KeyMappingHookThread(QThread):
    triggered = Signal(str)

    def __init__(self, hotkey_texts=None):
        super().__init__()
        self.hotkey_texts = set(hotkey_texts or [])
        self.is_active = False
        self.thread_id = None
        self.keyboard_hook = None
        self.pressed_vks = set()
        self.triggered_vks = set()
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        if self.stop_event.is_set():
            self.ready_event.set()
            return

        try:
            self.kb_pointer = HOOKPROC(self.keyboard_handler)
            self.keyboard_hook = user32.SetWindowsHookExW(13, self.kb_pointer, kernel32.GetModuleHandleW(None), 0)
            if not self.keyboard_hook:
                return
            self.is_active = True
            self.ready_event.set()
            while not self.stop_event.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self.is_active = False
            self.ready_event.set()
            if getattr(self, "keyboard_hook", None):
                user32.UnhookWindowsHookEx(self.keyboard_hook)
                self.keyboard_hook = None

    def stop(self):
        self.stop_event.set()
        self.is_active = False
        if getattr(self, "thread_id", None):
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    def keyboard_handler(self, nCode, wParam, lParam):
        if self.stop_event.is_set():
            return user32.CallNextHookEx(None, nCode, wParam, lParam)
        if nCode >= 0:
            struct = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(struct.vkCode)
            event = int(wParam)
            if event in (WM_KEYDOWN, WM_SYSKEYDOWN):
                self.pressed_vks.add(vk)
                hotkey_text = hotkey_text_from_pressed_vks(vk, self.pressed_vks)
                if hotkey_text in self.hotkey_texts:
                    if vk not in self.triggered_vks:
                        self.triggered_vks.add(vk)
                        self.triggered.emit(hotkey_text)
                    return 1
            elif event in (WM_KEYUP, WM_SYSKEYUP):
                self.pressed_vks.discard(vk)
                if vk in self.triggered_vks:
                    self.triggered_vks.discard(vk)
                    return 1
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

class HookThread(QThread):
    finished_signal = Signal(list)

    def __init__(self):
        super().__init__()
        self.stop_event = threading.Event()
        self.thread_id = None
        self.is_active = False
        self.mouse_hook = None
        self.keyboard_hook = None
    
    def run(self):
        self.events = []
        self.l_down_pos = None
        self.r_down_pos = None
        self.l_down_time = 0
        self.r_down_time = 0
        self.pressed_vks = set()
        
        self.thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        if self.stop_event.is_set():
            self.finished_signal.emit(self.events)
            return
        try:
            self.mouse_pointer = HOOKPROC(self.mouse_handler)
            self.mouse_hook = user32.SetWindowsHookExW(14, self.mouse_pointer, kernel32.GetModuleHandleW(None), 0)
            self.kb_pointer = HOOKPROC(self.keyboard_handler)
            self.keyboard_hook = user32.SetWindowsHookExW(13, self.kb_pointer, kernel32.GetModuleHandleW(None), 0)
            if not self.mouse_hook or not self.keyboard_hook:
                return
            self.is_active = True
            while not self.stop_event.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self.is_active = False
            if getattr(self, 'mouse_hook', None):
                user32.UnhookWindowsHookEx(self.mouse_hook)
                self.mouse_hook = None
            if getattr(self, 'keyboard_hook', None):
                user32.UnhookWindowsHookEx(self.keyboard_hook)
                self.keyboard_hook = None
            self.finished_signal.emit(self.events)

    def stop(self):
        self.stop_event.set()
        self.is_active = False
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    def mouse_handler(self, nCode, wParam, lParam):
        if self.stop_event.is_set():
            return user32.CallNextHookEx(None, nCode, wParam, lParam)
        if nCode >= 0:
            struct = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = struct.pt.x, struct.pt.y
            
            if wParam == 0x0201: # WM_LBUTTONDOWN
                self.l_down_pos = (x, y)
                self.l_down_time = time.monotonic()
            elif wParam == 0x0202: # WM_LBUTTONUP
                if getattr(self, 'l_down_pos', None):
                    dx = abs(x - self.l_down_pos[0])
                    dy = abs(y - self.l_down_pos[1])
                    if dx > 10 or dy > 10:
                        self.events.append((self.l_down_time, 'left_drag', (*self.l_down_pos, x, y), time.monotonic()))
                    else:
                        self.events.append((self.l_down_time, 'left', (x, y), time.monotonic()))
                    self.l_down_pos = None
            elif wParam == 0x0204: # WM_RBUTTONDOWN
                self.r_down_pos = (x, y)
                self.r_down_time = time.monotonic()
            elif wParam == 0x0205: # WM_RBUTTONUP
                if getattr(self, 'r_down_pos', None):
                    dx = abs(x - self.r_down_pos[0])
                    dy = abs(y - self.r_down_pos[1])
                    if dx > 10 or dy > 10:
                        self.events.append((self.r_down_time, 'right_drag', (*self.r_down_pos, x, y), time.monotonic()))
                    else:
                        self.events.append((self.r_down_time, 'right', (x, y), time.monotonic()))
                    self.r_down_pos = None
            elif wParam == 0x020A: # WM_MOUSEWHEEL
                delta = ctypes.c_short(struct.mouseData >> 16).value
                now = time.monotonic()
                self.events.append((now, 'scroll', delta, now))
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def keyboard_handler(self, nCode, wParam, lParam):
        if self.stop_event.is_set():
            return user32.CallNextHookEx(None, nCode, wParam, lParam)
        if nCode >= 0:
            struct = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(struct.vkCode)
            if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                repeated = vk in self.pressed_vks
                self.pressed_vks.add(vk)
                if not repeated and vk not in (0x77, 0x1B) and vk not in MODIFIER_VKS:
                    hotkey = hotkey_text_from_pressed_vks(vk, self.pressed_vks)
                    if hotkey:
                        now = time.monotonic()
                        self.events.append((now, 'hotkey', hotkey, now))
            elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                self.pressed_vks.discard(vk)
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

class RecorderUI(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(320, 80)
        
        rect = QApplication.primaryScreen().geometry()
        self.move((rect.width() - 320) // 2, 40)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.bg = QFrame()
        self.bg.setStyleSheet("background-color: rgba(17, 24, 39, 238); border-radius: 8px; border: 2px solid #3B82F6;")
        self.layout.addWidget(self.bg)
        
        inner = QVBoxLayout(self.bg)
        self.label = QLabel("准备录制\nF8 开始 | Esc 取消")
        self.label.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        self.label.setAlignment(Qt.AlignCenter)
        inner.addWidget(self.label)
        
        self.state = 0 
        self.hook_thread = None
        self.f8_pressed = False
        self.esc_pressed = False
        self.cancelled = False
        self.result_handled = False
        
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
        self.cancelled = False
        self.result_handled = False
        self.state = 1
        self.label.setText("正在录制键鼠操作\nF8 停止并生成 | Esc 放弃")
        self.bg.setStyleSheet("background-color: rgba(48, 20, 22, 240); border-radius: 8px; border: 2px solid #EF4444;")
        self.hook_thread = HookThread()
        self.hook_thread.finished_signal.connect(self.on_recorded)
        self.hook_thread.start()

    def stop_recording(self):
        self.state = 2
        self.label.setText("⏳ 正在生成指令轴...")
        if self.hook_thread:
            self.hook_thread.stop()
            
    def abort(self):
        self.cancelled = True
        self.result_handled = True
        if self.hook_thread:
            self.hook_thread.stop()
            self.hook_thread.wait(1500)
        self.main_window.showNormal()
        self.close()

    def on_recorded(self, events):
        if self.cancelled or self.result_handled:
            return
        self.result_handled = True
        double_click_seconds = max(0.1, user32.GetDoubleClickTime() / 1000.0)
        tasks = recorded_events_to_tasks(
            events, double_click_seconds=double_click_seconds
        )
                
        for task in tasks:
            self.main_window.add_row(task)
            
        if tasks:
            self.main_window.append_log(f"<font color='#E91E63'><b>>>> 成功捕捉全息动作，生成了 {len(tasks)} 步指令序列。</b></font>")
        else:
            self.main_window.append_log("<font color='gray'><b>>>> 未录制到任何动作。</b></font>")
            
        self.main_window.showNormal()
        self.close()

    def closeEvent(self, event):
        self.timer.stop()
        if self.state != 2 and not self.result_handled:
            self.cancelled = True
            self.result_handled = True
        if self.hook_thread and self.hook_thread.isRunning():
            self.hook_thread.stop()
            if not self.hook_thread.wait(1500):
                write_log("录制钩子仍在停止中，暂缓关闭录制窗口。")
                event.ignore()
                QTimer.singleShot(100, self.close)
                return
        event.accept()

class CoordinatePickThread(QThread):
    pos_signal = Signal(int, int)
    done_signal = Signal(str)
    cancelled_signal = Signal()

    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.is_active = False
        self.down_pos = None
        self.thread_id = None
        self.mouse_hook = None
        self.stop_event = threading.Event()

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        if self.stop_event.is_set():
            return
        try:
            self.mouse_pointer = HOOKPROC(self.mouse_handler)
            self.mouse_hook = user32.SetWindowsHookExW(14, self.mouse_pointer, kernel32.GetModuleHandleW(None), 0)
            if not self.mouse_hook:
                return
            self.is_active = True
            while not self.stop_event.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self.is_active = False
            if getattr(self, 'mouse_hook', None):
                user32.UnhookWindowsHookEx(self.mouse_hook)
                self.mouse_hook = None

    def stop(self):
        self.stop_event.set()
        self.is_active = False
        if getattr(self, 'thread_id', None):
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    def finish_with_value(self, value):
        self.done_signal.emit(value)
        self.stop()

    def cancel(self):
        self.cancelled_signal.emit()
        self.stop()

    def mouse_handler(self, nCode, wParam, lParam):
        if self.stop_event.is_set():
            return user32.CallNextHookEx(None, nCode, wParam, lParam)
        if nCode >= 0:
            struct = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = struct.pt.x, struct.pt.y
            self.pos_signal.emit(x, y)

            if wParam == 0x0204:  # WM_RBUTTONDOWN
                self.cancel()
                return 1

            if self.mode in ("point", "window"):
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
        self.setAttribute(Qt.WA_DeleteOnClose)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bg = QFrame()
        self.bg.setStyleSheet("background-color: rgba(17, 24, 39, 240); border-radius: 8px; border: 2px solid #3B82F6;")
        layout.addWidget(self.bg)

        inner = QVBoxLayout(self.bg)
        inner.setContentsMargins(12, 10, 12, 10)
        hint = self.hint_text()
        self.label = QLabel(f"{hint}\n当前鼠标位置: --,--\n右键取消")
        self.label.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
        self.label.setAlignment(Qt.AlignCenter)
        inner.addWidget(self.label)
        try:
            px, py = pyautogui.position()
            self.update_pos(px, py)
        except Exception: pass

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
        hint = self.hint_text()
        self.label.setText(f"{hint}\n当前鼠标位置: {x},{y}\n右键取消")

    def hint_text(self):
        if self.mode == "window":
            return "请左键单击目标程序窗口中的任意位置"
        if self.mode == "point":
            return "左键单击选取坐标"
        return "按住左键拖动，松开后选取轨迹"

    def finish_pick(self, value):
        self.callback(value)
        self.close()

    def cancel_pick(self):
        self.close()

    def closeEvent(self, event):
        if getattr(self, 'pick_thread', None) and self.pick_thread.isRunning():
            self.pick_thread.stop()
            if not self.pick_thread.wait(1500):
                write_log("坐标选取钩子仍在停止中，暂缓关闭选取窗口。")
                event.ignore()
                QTimer.singleShot(100, self.close)
                return
        event.accept()
