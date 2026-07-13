"""Worker thread bridge and emergency-stop watchdog."""

import ctypes
import threading
import time
import traceback

from PySide6.QtCore import QThread, Signal

from .logging_service import GLOBAL_CONFIG, write_log
from .log_policy import LOG_CRITICAL
from .pyautogui_runtime import pyautogui
from .win32_api import GetAsyncKeyState

class FailsafeWatchdog(threading.Thread):
    def __init__(self, engine):
        super().__init__(daemon=True, name="fukuaRPA-failsafe")
        self.engine = engine
        self.stop_event = threading.Event()

    def run(self):
        write_log(">>> 看门狗线程启动")
        next_task_manager_check = 0.0
        while not self.stop_event.is_set():
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
                    w, _h = pyautogui.size()
                    if x > (w - 10) and y < 10:
                        self.trigger_stop("检测到鼠标【右上角急停】")
                        return

                now = time.monotonic()
                if self.engine.enable_tm_stop and now >= next_task_manager_check:
                    next_task_manager_check = now + 0.1
                    hwnd = ctypes.windll.user32.GetForegroundWindow()
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                        if "任务管理器" in buff.value or "Task Manager" in buff.value:
                            self.trigger_stop("检测到【任务管理器】前台")
                            return
                self.stop_event.wait(0.02)
            except Exception as error:
                write_log(f"看门狗检查异常，稍后重试: {error}")
                self.stop_event.wait(1.0)

    def trigger_stop(self, reason):
        if not self.engine.stop_requested:
            write_log(f">>> 看门狗触发: {reason}")
            self.engine.log(
                f"<font color='red'><b>!!! {reason} -> 停止 !!!</b></font>",
                LOG_CRITICAL,
                critical=True,
            )
            self.engine.stop() 
            try: ctypes.windll.user32.MessageBeep(0xFFFFFFFF)
            except Exception: pass

    def kill(self):
        self.stop_event.set()

class WorkerThread(QThread):
    log_signal = Signal(str)
    status_signal = Signal(dict)
    click_signal = Signal(dict)
    debug_signal = Signal(dict)
    error_signal = Signal(str)
    def __init__(self, engine, tasks, run_id):
        super().__init__()
        self.engine = engine
        self.tasks = tasks
        self.run_id = run_id

    def run(self):
        self.watchdog = None
        try:
            self.watchdog = FailsafeWatchdog(self.engine)
            self.watchdog.start()
            self.engine.run_tasks(
                self.tasks,
                self.log_callback,
                self.status_callback,
                self.click_callback,
                self.debug_callback,
                self.run_id,
            )
        except Exception as error:
            details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            write_log(f"WorkerThread 未处理异常: {details}")
            self.error_signal.emit(str(error))
            self.engine.finish_run(self.run_id, "worker_error", details)
        finally:
            if self.watchdog:
                self.watchdog.kill()
                self.watchdog.join(timeout=1.0)
            if self.engine.active_run_matches(self.run_id):
                self.engine.finish_run(self.run_id)

    def log_callback(self, msg): 
        if GLOBAL_CONFIG["log_to_ui"]:
            self.log_signal.emit(msg)

    def status_callback(self, data):
        self.status_signal.emit(data)

    def click_callback(self, data):
        self.click_signal.emit(data)

    def debug_callback(self, data):
        self.debug_signal.emit(data)
