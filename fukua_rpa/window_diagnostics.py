"""Read-only Win32 target inspection for background-click diagnostics."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

from .win32_api import GA_ROOT, RECT, WNDENUMPROC, kernel32, user32


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25

INTEGRITY_LEVELS = (
    (0x0000, "不受信任"),
    (0x1000, "低"),
    (0x2000, "中"),
    (0x3000, "高（管理员）"),
    (0x4000, "系统"),
    (0x5000, "受保护进程"),
)

STANDARD_CONTROL_CLASSES = {
    "button",
    "edit",
    "static",
    "combobox",
    "comboboxex32",
    "listbox",
    "syslistview32",
    "systreeview32",
    "msctls_trackbar32",
    "msctls_progress32",
    "toolbarwindow32",
    "rebarwindow32",
}

CUSTOM_SURFACE_MARKERS = (
    "chrome_renderwidgethosthwnd",
    "cef",
    "qt",
    "unreal",
    "unity",
    "directui",
    "windows.ui.core",
)


class SIDAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


class TokenMandatoryLabel(ctypes.Structure):
    _fields_ = [("label", SIDAndAttributes)]


def integrity_label_from_rid(rid):
    rid = max(0, int(rid or 0))
    label = INTEGRITY_LEVELS[0][1]
    for threshold, candidate in INTEGRITY_LEVELS:
        if rid < threshold:
            break
        label = candidate
    return label


def integrity_rank(rid):
    rid = max(0, int(rid or 0))
    rank = 0
    for index, (threshold, _label) in enumerate(INTEGRITY_LEVELS):
        if rid < threshold:
            break
        rank = index
    return rank


def classify_control(class_name, permission_blocked=False):
    normalized = str(class_name or "").strip().lower()
    standard = normalized in STANDARD_CONTROL_CLASSES or normalized.startswith(
        "windowsforms"
    )
    custom_surface = any(marker in normalized for marker in CUSTOM_SURFACE_MARKERS)
    if permission_blocked:
        level = "可能被权限阻止"
    elif standard:
        level = "消息点击较可能有效"
    elif custom_surface:
        level = "自绘/画布控件，兼容性较低"
    else:
        level = "实验性，需要实际测试"
    return {
        "classification": level,
        "standard_win32_control": standard,
        "custom_surface": custom_surface,
    }


def _configure_security_apis():
    advapi32 = ctypes.windll.advapi32
    try:
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    except Exception:
        pass
    return advapi32


def process_integrity(pid):
    advapi32 = _configure_security_apis()
    process_handle = None
    token_handle = wintypes.HANDLE()
    try:
        process_handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not process_handle:
            return {"available": False, "rid": 0, "label": "无法读取"}
        if not advapi32.OpenProcessToken(
            process_handle, TOKEN_QUERY, ctypes.byref(token_handle)
        ):
            return {"available": False, "rid": 0, "label": "无法读取"}
        required = wintypes.DWORD(0)
        advapi32.GetTokenInformation(
            token_handle,
            TOKEN_INTEGRITY_LEVEL,
            None,
            0,
            ctypes.byref(required),
        )
        if required.value <= 0:
            return {"available": False, "rid": 0, "label": "无法读取"}
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token_handle,
            TOKEN_INTEGRITY_LEVEL,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            return {"available": False, "rid": 0, "label": "无法读取"}
        label = ctypes.cast(
            buffer, ctypes.POINTER(TokenMandatoryLabel)
        ).contents
        sid = label.label.sid
        count_pointer = advapi32.GetSidSubAuthorityCount(sid)
        if not count_pointer or count_pointer.contents.value <= 0:
            return {"available": False, "rid": 0, "label": "无法读取"}
        rid_pointer = advapi32.GetSidSubAuthority(
            sid, count_pointer.contents.value - 1
        )
        if not rid_pointer:
            return {"available": False, "rid": 0, "label": "无法读取"}
        rid = int(rid_pointer.contents.value)
        return {
            "available": True,
            "rid": rid,
            "rank": integrity_rank(rid),
            "label": integrity_label_from_rid(rid),
        }
    except Exception as error:
        return {
            "available": False,
            "rid": 0,
            "label": "无法读取",
            "error": str(error),
        }
    finally:
        if token_handle:
            try:
                kernel32.CloseHandle(token_handle)
            except Exception:
                pass
        if process_handle:
            try:
                kernel32.CloseHandle(process_handle)
            except Exception:
                pass


class WindowInspector:
    def __init__(self, process_id=None):
        self.process_id = int(process_id or os.getpid())

    @staticmethod
    def class_name(hwnd):
        buffer = ctypes.create_unicode_buffer(256)
        try:
            length = int(user32.GetClassNameW(hwnd, buffer, len(buffer)))
            return buffer.value[:length] if length > 0 else ""
        except Exception:
            return ""

    @staticmethod
    def title(hwnd):
        try:
            length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            return buffer.value
        except Exception:
            return ""

    @staticmethod
    def process_info(hwnd):
        pid = wintypes.DWORD(0)
        try:
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        except Exception:
            return {"pid": 0, "name": "", "path": ""}
        name = ""
        path = ""
        if HAS_PSUTIL and pid.value:
            try:
                process = psutil.Process(pid.value)
                name = process.name()
                path = os.path.normpath(process.exe())
            except Exception:
                pass
        return {"pid": int(pid.value), "name": name, "path": path}

    @staticmethod
    def _rect(hwnd, client=False):
        rect = RECT()
        try:
            ok = (
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                if client
                else user32.GetWindowRect(hwnd, ctypes.byref(rect))
            )
            if not ok:
                return None
            return [
                int(rect.left),
                int(rect.top),
                int(rect.right),
                int(rect.bottom),
            ]
        except Exception:
            return None

    def window_info(self, hwnd, root_hwnd=None):
        try:
            parent = int(user32.GetParent(hwnd) or 0)
        except Exception:
            parent = 0
        depth = 0
        current = parent
        while current and root_hwnd and current != int(root_hwnd) and depth < 16:
            depth += 1
            try:
                current = int(user32.GetParent(current) or 0)
            except Exception:
                break
        try:
            control_id = max(0, int(user32.GetDlgCtrlID(hwnd)))
        except Exception:
            control_id = 0
        return {
            "hwnd": int(hwnd),
            "parent_hwnd": parent,
            "depth": depth,
            "class": self.class_name(hwnd),
            "title": self.title(hwnd),
            "control_id": control_id,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "enabled": bool(user32.IsWindowEnabled(hwnd)),
            "window_rect": self._rect(hwnd),
            "client_rect": self._rect(hwnd, client=True),
        }

    def enumerate_children(self, root_hwnd, max_items=128):
        children = []

        def enum_proc(hwnd, _lparam):
            if len(children) >= max_items:
                return False
            children.append(self.window_info(hwnd, root_hwnd=root_hwnd))
            return True

        try:
            callback = WNDENUMPROC(enum_proc)
            user32.EnumChildWindows(root_hwnd, callback, 0)
        except Exception:
            pass
        return children

    def inspect(self, root_hwnd, target_hwnd, binding=None, uia_report=None):
        root_hwnd = int(user32.GetAncestor(root_hwnd, GA_ROOT) or root_hwnd)
        target_hwnd = int(target_hwnd or root_hwnd)
        process = self.process_info(root_hwnd)
        current_integrity = process_integrity(self.process_id)
        target_integrity = process_integrity(process.get("pid", 0))
        permission_blocked = bool(
            current_integrity.get("available")
            and target_integrity.get("available")
            and target_integrity.get("rank", 0) > current_integrity.get("rank", 0)
        )
        target = self.window_info(target_hwnd, root_hwnd=root_hwnd)
        compatibility = classify_control(
            target.get("class", ""), permission_blocked=permission_blocked
        )
        uia_report = dict(uia_report or {})
        if uia_report.get("actionable") and not permission_blocked:
            compatibility["classification"] = "UI Automation 可直接操作"
        warnings = []
        if permission_blocked:
            warnings.append(
                "目标程序权限高于 fukuaRPA，Windows UIPI 可能阻止后台消息；可尝试以管理员身份运行。"
            )
        if not target.get("visible", False):
            warnings.append("目标控件当前不可见或窗口已最小化。")
        if compatibility["custom_surface"] and not uia_report.get("actionable"):
            warnings.append(
                "目标看起来是自绘、浏览器画布或游戏表面，PostMessage 可能被忽略。"
            )
        children = self.enumerate_children(root_hwnd)
        return {
            "valid": bool(user32.IsWindow(root_hwnd) and user32.IsWindow(target_hwnd)),
            "root": self.window_info(root_hwnd, root_hwnd=root_hwnd),
            "target": target,
            "process": process,
            "integrity": {
                "fukuaRPA": current_integrity,
                "target": target_integrity,
                "target_higher": permission_blocked,
            },
            "compatibility": {
                **compatibility,
                "post_message_available": not permission_blocked,
                "ui_automation_status": (
                    "可用"
                    if uia_report.get("actionable")
                    else ("未找到可操作控件" if uia_report.get("available") else "不可用")
                ),
            },
            "ui_automation": uia_report,
            "binding": dict(binding or {}),
            "child_count": len(children),
            "children_truncated": len(children) >= 128,
            "children": children,
            "warnings": warnings,
        }


def format_window_inspection(report):
    if not isinstance(report, dict) or not report.get("valid"):
        return "目标窗口已经失效，请重新选择窗口。"
    root = report.get("root", {})
    target = report.get("target", {})
    process = report.get("process", {})
    integrity = report.get("integrity", {})
    compatibility = report.get("compatibility", {})
    uia = report.get("ui_automation", {})
    uia_control = uia.get("control", {})
    if not uia.get("actionable"):
        uia_selection = "未选择"
    elif uia.get("matched_bound_hwnd"):
        uia_selection = "已绑定控件"
    else:
        uia_selection = "坐标处最深控件"
    lines = [
        f"兼容性判断：{compatibility.get('classification', '未知')}",
        f"进程：{process.get('name') or '未知'}  PID {process.get('pid', 0)}",
        f"路径：{process.get('path') or '无法读取'}",
        f"根窗口：HWND {root.get('hwnd', 0)}  类 {root.get('class') or '未知'}",
        f"标题：{root.get('title') or '（无标题）'}",
        f"目标控件：HWND {target.get('hwnd', 0)}  类 {target.get('class') or '未知'}  ID {target.get('control_id', 0)}",
        f"目标客户区：{target.get('client_rect')}",
        "UI Automation："
        f"{compatibility.get('ui_automation_status', '未知')}"
        + (
            f"，{uia_control.get('control_type', '控件')} / {uia_control.get('action', '动作')}"
            if uia.get("actionable")
            else ""
        ),
        f"UIA 控件：{uia_control.get('name') or '（无名称）'}  "
        f"框架 {uia_control.get('framework') or '未知'}  "
        f"扫描 {uia.get('nodes_scanned', 0)} 项 / 候选 {uia.get('candidate_controls', 0)} 项  "
        f"选择 {uia_selection}",
        "权限：fukuaRPA "
        f"{integrity.get('fukuaRPA', {}).get('label', '未知')} / 目标 "
        f"{integrity.get('target', {}).get('label', '未知')}",
        f"枚举到子控件：{report.get('child_count', 0)} 个",
    ]
    for warning in report.get("warnings", []):
        lines.append(f"警告：{warning}")
    if uia.get("error") and not uia.get("actionable"):
        lines.append(f"UIA 说明：{uia.get('error')}")
    lines.append("")
    lines.append("子控件（最多 128 项）：")
    for child in report.get("children", []):
        indent = "  " * min(8, int(child.get("depth", 0)) + 1)
        title = str(child.get("title", "")).replace("\r", " ").replace("\n", " ")
        lines.append(
            f"{indent}HWND {child.get('hwnd', 0)} | {child.get('class') or '未知'} | "
            f"ID {child.get('control_id', 0)} | {title or '（无文本）'}"
        )
    if report.get("children_truncated"):
        lines.append("……子控件数量超过上限，报告已截断。")
    return "\n".join(lines)
