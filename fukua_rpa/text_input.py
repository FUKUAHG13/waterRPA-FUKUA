"""Foreground Unicode text input without using or replacing the clipboard."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MAX_INPUT_TEXT_UNITS = 1_000_000


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


SendInput = ctypes.windll.user32.SendInput
SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
SendInput.restype = wintypes.UINT


def _utf16_units(text: str) -> list[int]:
    raw = str(text).encode("utf-16-le", errors="strict")
    units = [int.from_bytes(raw[index : index + 2], "little") for index in range(0, len(raw), 2)]
    if len(units) > MAX_INPUT_TEXT_UNITS:
        raise ValueError("输入文本过长")
    return units


def send_unicode_text(text: str) -> None:
    units = _utf16_units(text)
    if not units:
        return
    # Send in bounded batches so a long text does not require one giant C array.
    for offset in range(0, len(units), 1024):
        batch = units[offset : offset + 1024]
        events = (INPUT * (len(batch) * 2))()
        for index, unit in enumerate(batch):
            events[index * 2] = INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, None),
            )
            events[index * 2 + 1] = INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None),
            )
        sent = int(SendInput(len(events), events, ctypes.sizeof(INPUT)))
        if sent != len(events):
            raise OSError(f"Unicode 键盘输入不完整：计划 {len(events)} 个事件，实际 {sent} 个")
