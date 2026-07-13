"""Bounded Win32 application and top-level window actions."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes

from .win32_api import WNDENUMPROC, user32


WM_CLOSE = 0x0010
SW_RESTORE = 9
MAX_WINDOW_QUERY_LENGTH = 500


def normalize_window_query(value) -> tuple[str, bool]:
    text = str(value or "").strip()
    if not text:
        raise ValueError("窗口标题不能为空")
    if len(text) > MAX_WINDOW_QUERY_LENGTH:
        raise ValueError(f"窗口标题不能超过 {MAX_WINDOW_QUERY_LENGTH} 个字符")
    exact = text.startswith("=")
    return (text[1:].strip() if exact else text), exact


def _window_title(hwnd) -> str:
    length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def find_window(query) -> int:
    expected, exact = normalize_window_query(query)
    folded = expected.casefold()
    matches: list[int] = []

    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            title = _window_title(hwnd)
            if title and (
                title.casefold() == folded if exact else folded in title.casefold()
            ):
                matches.append(int(hwnd))
                return False
        except Exception:
            pass
        return True

    enum_proc = WNDENUMPROC(callback)
    user32.EnumWindows(enum_proc, 0)
    return matches[0] if matches else 0


def window_title_at_point(x: int, y: int) -> str:
    from .win32_api import GA_ROOT, POINT

    hwnd = user32.WindowFromPoint(POINT(int(x), int(y)))
    root_hwnd = user32.GetAncestor(hwnd, GA_ROOT) if hwnd else 0
    title = _window_title(root_hwnd or hwnd) if (root_hwnd or hwnd) else ""
    if not title.strip():
        raise ValueError("所选窗口没有可用标题，请改为手动输入窗口标题。")
    return title.strip()


def wait_for_window(query, timeout, stop_requested=lambda: False) -> int:
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        hwnd = find_window(query)
        if hwnd:
            return hwnd
        if stop_requested() or time.monotonic() >= deadline:
            return 0
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def activate_window(query) -> bool:
    hwnd = find_window(query)
    if not hwnd:
        return False
    user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
    return bool(user32.SetForegroundWindow(wintypes.HWND(hwnd)))


def close_window(query) -> bool:
    hwnd = find_window(query)
    return bool(hwnd and user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def launch_application(command) -> int:
    text = str(command or "").strip()
    if not text:
        raise ValueError("程序路径或启动命令不能为空")
    if len(text) > 32_768:
        raise ValueError("启动命令过长")
    if os.path.isfile(text):
        process = subprocess.Popen([os.path.abspath(text)])
    else:
        process = subprocess.Popen(text)
    return int(process.pid)
