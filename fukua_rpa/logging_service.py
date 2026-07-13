"""Non-blocking file/UI logging and the process-level exception hook."""

import queue
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass

from .paths import get_log_path


GLOBAL_CONFIG = {"log_to_file": False, "log_to_ui": True}
LOG_QUEUE = queue.Queue()
_LOG_BASE_DIR = None
_LOG_WRITE_LOCK = threading.Lock()
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3


@dataclass(frozen=True)
class LogRecord:
    message: str
    callback: object
    event_time_ns: int
    ui_timestamp: bool = False


def format_local_timestamp(event_time_ns=None):
    """Format the local wall-clock time captured when an event occurred."""
    timestamp_ns = time.time_ns() if event_time_ns is None else int(event_time_ns)
    seconds = timestamp_ns // 1_000_000_000
    milliseconds = (timestamp_ns // 1_000_000) % 1000
    return f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(seconds))}.{milliseconds:03d}"


def set_log_base_dir(base_dir):
    global _LOG_BASE_DIR
    _LOG_BASE_DIR = os.path.abspath(base_dir) if base_dir else None


def current_log_path():
    return get_log_path(_LOG_BASE_DIR)


def _rotate_log(path):
    try:
        if not os.path.isfile(path) or os.path.getsize(path) < MAX_LOG_BYTES:
            return
        for index in range(LOG_BACKUP_COUNT, 0, -1):
            source = f"{path}.{index}"
            if index == LOG_BACKUP_COUNT and os.path.exists(source):
                os.remove(source)
            elif os.path.exists(source):
                os.replace(source, f"{path}.{index + 1}")
        os.replace(path, f"{path}.1")
    except OSError:
        pass


def _append_direct(formatted):
    path = current_log_path()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with _LOG_WRITE_LOCK:
            _rotate_log(path)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(formatted + "\n")
    except OSError:
        pass


def _log_worker():
    while True:
        try:
            item = LOG_QUEUE.get()
            if item is None:
                return
            record = item
            timestamp = format_local_timestamp(record.event_time_ns)
            formatted = f"[{timestamp}] {record.message}"
            if GLOBAL_CONFIG["log_to_file"]:
                _append_direct(formatted)
            if record.callback and GLOBAL_CONFIG["log_to_ui"]:
                display_message = record.message
                if record.ui_timestamp:
                    display_message = f"[{timestamp}] {display_message}"
                record.callback(display_message)
        except Exception:
            # Logging must never crash the automation or recursively log itself.
            pass
        finally:
            LOG_QUEUE.task_done()


LOG_THREAD = threading.Thread(target=_log_worker, daemon=True, name="fukuaRPA-log")
LOG_THREAD.start()


def write_log(
    message,
    callback=None,
    *,
    ui_timestamp=False,
    event_time_ns=None,
):
    LOG_QUEUE.put(
        LogRecord(
            message=str(message),
            callback=callback,
            event_time_ns=(
                time.time_ns() if event_time_ns is None else int(event_time_ns)
            ),
            ui_timestamp=bool(ui_timestamp),
        )
    )


def flush_logs(timeout=2.0):
    deadline = time.monotonic() + max(0.0, float(timeout))
    while LOG_QUEUE.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    return LOG_QUEUE.unfinished_tasks == 0


def global_exception_handler(exception_type, value, traceback_object):
    details = "".join(traceback.format_exception(exception_type, value, traceback_object))
    message = f"!!! 严重崩溃 !!! {value}\n{details}"
    formatted = f"[{format_local_timestamp()}] {message}"
    _append_direct(formatted)
    sys.__excepthook__(exception_type, value, traceback_object)


def threading_exception_handler(args):
    global_exception_handler(args.exc_type, args.exc_value, args.exc_traceback)


def install_global_exception_handler():
    sys.excepthook = global_exception_handler
    threading.excepthook = threading_exception_handler


install_global_exception_handler()
