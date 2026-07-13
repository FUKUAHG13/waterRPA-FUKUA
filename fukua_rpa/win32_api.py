"""Typed Win32 declarations and hotkey helpers used across the application."""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt


GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
try:
    GetCurrentProcessorNumber = ctypes.windll.kernel32.GetCurrentProcessorNumber
    GetCurrentProcessorNumber.restype = ctypes.c_ulong
    HAS_KERNEL_CPU = True
except Exception:
    GetCurrentProcessorNumber = None
    HAS_KERNEL_CPU = False

VK_MAP = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x10: "shift", 0x11: "ctrl",
    0x12: "alt", 0x14: "capslock", 0x1B: "esc", 0x20: "space", 0x21: "pageup",
    0x22: "pagedown", 0x23: "end", 0x24: "home", 0x25: "left", 0x26: "up",
    0x27: "right", 0x28: "down", 0x2C: "printscreen", 0x2D: "insert", 0x2E: "delete",
}
for index in range(65, 91):
    VK_MAP[index] = chr(index).lower()
for index in range(48, 58):
    VK_MAP[index] = chr(index)
for index in range(112, 124):
    VK_MAP[index] = f"f{index - 111}"
for index in range(0x60, 0x6A):
    VK_MAP[index] = str(index - 0x60)
VK_MAP.update({
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
})

HOTKEY_NAME_TO_VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "capslock": 0x14, "esc": 0x1B,
    "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "printscreen": 0x2C,
    "insert": 0x2D, "delete": 0x2E, ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD,
    ".": 0xBE, "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
for index in range(65, 91):
    HOTKEY_NAME_TO_VK[chr(index).lower()] = index
for index in range(48, 58):
    HOTKEY_NAME_TO_VK[chr(index)] = index
for index in range(112, 124):
    HOTKEY_NAME_TO_VK[f"f{index - 111}"] = index
for index in range(0x60, 0x6A):
    HOTKEY_NAME_TO_VK[f"num{index - 0x60}"] = index

HOTKEY_ALIAS = {
    "control": "ctrl", "ctl": "ctrl", "cmd": "win", "command": "win", "meta": "win",
    "windows": "win", "escape": "esc", "return": "enter", "del": "delete",
    "pgup": "pageup", "pgdn": "pagedown", "page down": "pagedown", "page up": "pageup",
    "prtsc": "printscreen", "print": "printscreen", "ins": "insert", "bksp": "backspace",
}
MOD_NAME_TO_MASK = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NAME_TO_VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}
MOD_NAME_TO_VKS = {
    "ctrl": frozenset((0x11, 0xA2, 0xA3)),
    "alt": frozenset((0x12, 0xA4, 0xA5)),
    "shift": frozenset((0x10, 0xA0, 0xA1)),
    "win": frozenset((0x5B, 0x5C)),
}
MODIFIER_VKS = frozenset().union(*MOD_NAME_TO_VKS.values())
MOD_DISPLAY = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
MOD_ORDER = ("ctrl", "alt", "shift", "win")
SAFE_BARE_GLOBAL_KEYS = {f"f{index}" for index in range(1, 13)} | {
    "printscreen", "insert", "delete", "home", "end", "pageup", "pagedown"
}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200
WM_HOTKEY = 0x0312
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_RBUTTONDBLCLK = 0x0206
PM_NOREMOVE = 0x0000
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
GA_ROOT = 2
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
HOTKEY_ID_START = 0x5741
HOTKEY_ID_STOP = 0x5742
HOTKEY_ID_MAPPING_BASE = 0x5800
HOTKEY_MAPPING_COUNT = 5


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM,
)


def _configure_function_signatures():
    try:
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.WindowFromPoint.argtypes = [POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
        user32.ScreenToClient.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        user32.GetClientRect.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        user32.IsWindowEnabled.restype = wintypes.BOOL
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
        user32.ClientToScreen.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
        user32.GetDlgCtrlID.restype = ctypes.c_int
        user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetDlgItem.restype = wintypes.HWND
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
        user32.EnumChildWindows.restype = wintypes.BOOL
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p]
        user32.CallNextHookEx.restype = LRESULT
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = LRESULT
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostThreadMessageW.restype = wintypes.BOOL
        user32.EnumDisplayMonitors.argtypes = [
            wintypes.HDC, ctypes.POINTER(RECT), MONITORENUMPROC, wintypes.LPARAM
        ]
        user32.EnumDisplayMonitors.restype = wintypes.BOOL
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFOEXW)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    except Exception:
        # Individual APIs are checked again where failure can be recovered.
        pass


_configure_function_signatures()


def key_event_to_hotkey_text(event):
    key = event.key()
    modifiers = event.modifiers()
    modifier_flags = Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier
    if key == Qt.Key_Escape and not (modifiers & modifier_flags):
        return ""

    parts = []
    if modifiers & Qt.ControlModifier and key != Qt.Key_Control:
        parts.append("ctrl")
    if modifiers & Qt.AltModifier and key != Qt.Key_Alt:
        parts.append("alt")
    if modifiers & Qt.ShiftModifier and key != Qt.Key_Shift:
        parts.append("shift")
    if modifiers & Qt.MetaModifier and key != Qt.Key_Meta:
        parts.append("win")

    special = {
        Qt.Key_Backspace: "backspace", Qt.Key_Tab: "tab", Qt.Key_Return: "enter",
        Qt.Key_Enter: "enter", Qt.Key_Escape: "esc", Qt.Key_Space: "space",
        Qt.Key_PageUp: "pageup", Qt.Key_PageDown: "pagedown", Qt.Key_End: "end",
        Qt.Key_Home: "home", Qt.Key_Left: "left", Qt.Key_Up: "up", Qt.Key_Right: "right",
        Qt.Key_Down: "down", Qt.Key_Print: "printscreen", Qt.Key_Insert: "insert",
        Qt.Key_Delete: "delete", Qt.Key_Control: "ctrl", Qt.Key_Alt: "alt",
        Qt.Key_Shift: "shift", Qt.Key_Meta: "win",
    }
    for index in range(1, 13):
        special[getattr(Qt, f"Key_F{index}")] = f"f{index}"

    if key in special:
        key_text = special[key]
    else:
        text = event.text()
        key_text = text.lower() if text and text.strip() else ""
        if not key_text and Qt.Key_A <= key <= Qt.Key_Z:
            key_text = chr(ord("a") + key - Qt.Key_A)
        elif not key_text and Qt.Key_0 <= key <= Qt.Key_9:
            key_text = chr(ord("0") + key - Qt.Key_0)
    if not key_text:
        return ""
    if key_text not in parts:
        parts.append(key_text)
    return "+".join(parts)


def normalize_hotkey_token(token):
    token = str(token or "").strip().lower().replace("＋", "+")
    token = HOTKEY_ALIAS.get(token, token)
    if token.startswith("numpad") and token[6:].isdigit():
        token = f"num{token[6:]}"
    return token


def hotkey_display_text(text):
    raw = str(text or "").strip().replace("＋", "+")
    chunks = [normalize_hotkey_token(part) for part in raw.split("+") if str(part).strip()]
    if not chunks:
        return ""
    display_parts = []
    display_names = {
        "esc": "Esc", "enter": "Enter", "space": "Space", "tab": "Tab",
        "backspace": "Backspace", "capslock": "CapsLock", "pageup": "PageUp",
        "pagedown": "PageDown", "printscreen": "PrintScreen", "insert": "Insert",
        "delete": "Delete", "home": "Home", "end": "End", "left": "Left",
        "right": "Right", "up": "Up", "down": "Down",
    }
    for chunk in chunks:
        if chunk in MOD_DISPLAY:
            display_parts.append(MOD_DISPLAY[chunk])
        elif chunk.startswith("f") and chunk[1:].isdigit():
            display_parts.append(chunk.upper())
        elif chunk.startswith("num") and chunk[3:].isdigit():
            display_parts.append(f"Num{chunk[3:]}")
        elif len(chunk) == 1:
            display_parts.append(chunk.upper())
        else:
            display_parts.append(display_names.get(chunk, chunk))
    return "+".join(display_parts)


def parse_hotkey_text(text):
    raw = str(text or "").strip().replace("＋", "+")
    if not raw:
        return None
    chunks = [normalize_hotkey_token(part) for part in raw.split("+") if str(part).strip()]
    if not chunks:
        return None
    modifier_names = []
    key_name = None
    for chunk in chunks:
        if chunk in MOD_NAME_TO_MASK:
            if chunk not in modifier_names:
                modifier_names.append(chunk)
            continue
        if key_name is not None:
            return None
        key_name = chunk
    if not key_name or key_name in MOD_NAME_TO_MASK:
        return None
    if len(key_name) == 1:
        key_name = key_name.lower()
    virtual_key = HOTKEY_NAME_TO_VK.get(key_name)
    if virtual_key is None:
        return None
    ordered_modifiers = [name for name in MOD_ORDER if name in modifier_names]
    modifiers = 0
    for name in ordered_modifiers:
        modifiers |= MOD_NAME_TO_MASK[name]
    canonical = "+".join(ordered_modifiers + [key_name])
    return {
        "text": canonical,
        "display": hotkey_display_text(canonical),
        "key": key_name,
        "vk": virtual_key,
        "modifiers": modifiers,
        "mod_names": ordered_modifiers,
        "bare": modifiers == 0,
    }


def is_safe_global_hotkey(parsed):
    return bool(parsed and ((not parsed.get("bare")) or parsed.get("key") in SAFE_BARE_GLOBAL_KEYS))


def hotkey_signature(parsed):
    if not parsed:
        return None
    return int(parsed.get("modifiers", 0)), int(parsed.get("vk", 0))


def modifier_is_down(name):
    virtual_key = MOD_NAME_TO_VK.get(name)
    return bool(virtual_key and (GetAsyncKeyState(virtual_key) & 0x8000))


def hotkey_is_down(parsed):
    if not parsed:
        return False
    required_modifiers = set(parsed.get("mod_names", []))
    if any(not modifier_is_down(name) for name in required_modifiers):
        return False
    if any(name not in required_modifiers and modifier_is_down(name) for name in MOD_ORDER):
        return False
    return bool(GetAsyncKeyState(parsed["vk"]) & 0x8000)


def current_keyboard_hotkey_text(virtual_key):
    pressed_vks = {int(virtual_key)}
    for name in MOD_ORDER:
        if modifier_is_down(name):
            pressed_vks.update(MOD_NAME_TO_VKS[name])
    return hotkey_text_from_pressed_vks(virtual_key, pressed_vks)


def hotkey_text_from_pressed_vks(virtual_key, pressed_vks):
    """Build a hotkey from Hook-maintained key state, without async-state races."""

    virtual_key = int(virtual_key)
    if virtual_key in MODIFIER_VKS:
        return ""
    key_name = VK_MAP.get(virtual_key)
    if not key_name or key_name in MOD_NAME_TO_MASK:
        return ""
    down = {int(vk) for vk in (pressed_vks or ())}
    parts = [
        name
        for name in MOD_ORDER
        if any(vk in down for vk in MOD_NAME_TO_VKS[name])
    ]
    parts.append(key_name)
    parsed = parse_hotkey_text("+".join(parts))
    return parsed["text"] if parsed else ""


def pressed_hotkey_display_text(pressed_vks):
    """Render the complete Hook-maintained key state, including modifiers only."""

    down = {int(vk) for vk in (pressed_vks or ())}
    parts = [
        name
        for name in MOD_ORDER
        if any(vk in down for vk in MOD_NAME_TO_VKS[name])
    ]
    key_names = [
        VK_MAP[vk]
        for vk in sorted(down)
        if vk not in MODIFIER_VKS and vk in VK_MAP
    ]
    parts.extend(key_names)
    return hotkey_display_text("+".join(parts)) if parts else ""


def make_mouse_lparam(x, y):
    return wintypes.LPARAM(((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF))
