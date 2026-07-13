"""Lazy PyAutoGUI access so OpenCV/NumPy do not block the first UI frame."""

from __future__ import annotations

import importlib
import threading


_module = None
_lock = threading.Lock()


def get_pyautogui():
    global _module
    if _module is not None:
        return _module
    with _lock:
        if _module is None:
            module = importlib.import_module("pyautogui")
            module.FAILSAFE = False
            module.PAUSE = 0
            _module = module
    return _module


class _LazyPyAutoGUI:
    def __getattr__(self, name):
        return getattr(get_pyautogui(), name)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(dir(get_pyautogui())))


pyautogui = _LazyPyAutoGUI()
