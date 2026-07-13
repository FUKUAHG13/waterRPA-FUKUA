"""Small crash marker used to distinguish clean and interrupted shutdowns."""

from __future__ import annotations

import json
import ctypes
import hashlib
import os
import time
import uuid
from dataclasses import dataclass

from .config_store import atomic_write_json


ERROR_ALREADY_EXISTS = 183


class SingleInstanceGuard:
    """Per-portable-directory named mutex held for the lifetime of the process."""

    def __init__(self, base_dir):
        normalized = os.path.normcase(os.path.abspath(base_dir))
        digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()[:20]
        self.name = f"Local\\FUKUA_fukuaRPA_{digest}"
        self.handle = None

    def acquire(self):
        if self.handle:
            return True
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, True, self.name)
        error = int(kernel32.GetLastError())
        if not handle:
            return False
        if error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self.handle = handle
        return True

    def release(self):
        if not self.handle:
            return
        try:
            ctypes.windll.kernel32.ReleaseMutex(self.handle)
        finally:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("fukuaRPA 已在当前目录运行")
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.release()


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
        except Exception:
            pass
    return False


@dataclass
class ApplicationSession:
    base_dir: str
    marker_name: str = ".fukuaRPA_session.json"

    def __post_init__(self):
        self.base_dir = os.path.abspath(self.base_dir)
        self.path = os.path.join(self.base_dir, self.marker_name)
        self.token = uuid.uuid4().hex
        self.previous_unclean = False
        self.previous_details: dict = {}
        self.started = False

    def start(self) -> "ApplicationSession":
        previous = self._read_marker()
        if previous:
            previous_pid = int(previous.get("pid", 0) or 0)
            self.previous_unclean = previous_pid != os.getpid() and not _pid_is_running(previous_pid)
            self.previous_details = previous
        atomic_write_json(
            self.path,
            {
                "format": "fukuaRPA_session",
                "pid": os.getpid(),
                "token": self.token,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        self.started = True
        return self

    def _read_marker(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def close(self) -> bool:
        if not self.started:
            return True
        current = self._read_marker()
        if current.get("token") != self.token:
            return False
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        self.started = False
        return True

    def __enter__(self) -> "ApplicationSession":
        return self.start()

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()
