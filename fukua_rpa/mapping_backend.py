"""Win32 window binding and foreground/background click implementation."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Callable

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

from .win32_api import (
    GA_ROOT,
    MK_LBUTTON,
    MK_RBUTTON,
    POINT,
    RECT,
    WM_LBUTTONDBLCLK,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEMOVE,
    WM_RBUTTONDBLCLK,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    WNDENUMPROC,
    make_mouse_lparam,
    user32,
)
from .window_diagnostics import WindowInspector
from .pyautogui_runtime import pyautogui


class WindowBindingError(RuntimeError):
    pass


class WindowMappingBackend:
    def __init__(self, process_id: int | None = None, uia_backend=None):
        self.process_id = int(process_id or os.getpid())
        self.inspector = WindowInspector(self.process_id)
        if uia_backend is None:
            from .uia_backend import UIAutomationBackend

            uia_backend = UIAutomationBackend()
        self.ui_automation = uia_backend
        self.last_background_method = ""
        self.last_background_detail = {}

    def close(self):
        self.ui_automation.close()

    def class_name(self, hwnd):
        if not hwnd:
            return ""
        buffer = ctypes.create_unicode_buffer(256)
        try:
            length = user32.GetClassNameW(hwnd, buffer, len(buffer))
            return buffer.value[:length] if length > 0 else ""
        except Exception:
            return ""

    def title(self, hwnd):
        if not hwnd:
            return ""
        try:
            length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            return buffer.value
        except Exception:
            return ""

    def process_info(self, hwnd):
        pid = wintypes.DWORD(0)
        try:
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        except Exception:
            return 0, ""
        process_path = ""
        if HAS_PSUTIL and pid.value:
            try:
                process_path = os.path.normcase(os.path.abspath(psutil.Process(pid.value).exe()))
            except Exception:
                process_path = ""
        return int(pid.value), process_path

    def belongs_to_current_process(self, hwnd):
        if not hwnd:
            return False
        pid, _path = self.process_info(hwnd)
        return bool(pid and pid == self.process_id)

    @staticmethod
    def screen_area_at_point(hwnd, x, y):
        if not hwnd or not user32.IsWindowVisible(hwnd):
            return None
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        if not (rect.left <= int(x) < rect.right and rect.top <= int(y) < rect.bottom):
            return None
        return (rect.right - rect.left) * (rect.bottom - rect.top)

    def top_level_window_at_point(self, x, y, exclude_current_process=False):
        candidates = []

        def enum_proc(hwnd, _lparam):
            if exclude_current_process and self.belongs_to_current_process(hwnd):
                return True
            if self.screen_area_at_point(hwnd, x, y) is not None:
                candidates.append(int(hwnd))
            return True

        try:
            callback = WNDENUMPROC(enum_proc)
            user32.EnumWindows(callback, 0)
        except Exception:
            return None
        return candidates[0] if candidates else None

    def root_window_at_point(self, x, y, exclude_current_process=False):
        point = POINT(int(x), int(y))
        hwnd = user32.WindowFromPoint(point)
        root_hwnd = user32.GetAncestor(hwnd, GA_ROOT) if hwnd else None
        root_hwnd = root_hwnd or hwnd
        if root_hwnd and exclude_current_process and self.belongs_to_current_process(root_hwnd):
            root_hwnd = self.top_level_window_at_point(
                x, y, exclude_current_process=True
            )
        if not root_hwnd or not user32.IsWindow(root_hwnd):
            return None
        if exclude_current_process and self.belongs_to_current_process(root_hwnd):
            return None
        return int(root_hwnd)

    def background_click_target(
        self,
        x,
        y,
        expected_root=None,
        exclude_current_process=False,
        *,
        belongs_callback: Callable | None = None,
        top_level_callback: Callable | None = None,
        area_callback: Callable | None = None,
    ):
        belongs = belongs_callback or self.belongs_to_current_process
        find_top_level = top_level_callback or self.top_level_window_at_point
        area_at_point = area_callback or self.screen_area_at_point
        if expected_root:
            root_hwnd = int(expected_root)
            if not user32.IsWindow(root_hwnd):
                return None
            base_hwnd = root_hwnd
        else:
            point = POINT(int(x), int(y))
            base_hwnd = user32.WindowFromPoint(point)
            root_hwnd = user32.GetAncestor(base_hwnd, GA_ROOT) if base_hwnd else None
            root_hwnd = root_hwnd or base_hwnd
            if root_hwnd and exclude_current_process and belongs(root_hwnd):
                root_hwnd = find_top_level(x, y, exclude_current_process=True)
                base_hwnd = root_hwnd
            if not root_hwnd:
                return None
        candidates = []

        def add_candidate(hwnd):
            if not hwnd:
                return
            try:
                if exclude_current_process and belongs(hwnd):
                    return
                area = area_at_point(hwnd, x, y)
                if area is not None:
                    candidates.append((area, len(candidates), hwnd))
            except Exception:
                pass

        add_candidate(root_hwnd)
        add_candidate(base_hwnd)

        def enum_proc(hwnd, _lparam):
            add_candidate(hwnd)
            return True

        try:
            callback = WNDENUMPROC(enum_proc)
            user32.EnumChildWindows(root_hwnd, callback, 0)
        except Exception:
            pass
        if not candidates:
            return base_hwnd
        candidates.sort(key=lambda item: (item[0], -item[1]))
        return candidates[0][2]

    def create_binding_for_root(self, root_hwnd: int, x: int, y: int) -> dict:
        root_hwnd = user32.GetAncestor(root_hwnd, GA_ROOT) or root_hwnd
        if not root_hwnd or not user32.IsWindow(root_hwnd):
            raise WindowBindingError("选中的目标窗口已经失效，请重新选择。")
        if self.belongs_to_current_process(root_hwnd):
            raise WindowBindingError("不能绑定 fukuaRPA 自身窗口，请选择其他程序。")
        if self.screen_area_at_point(root_hwnd, x, y) is None:
            raise WindowBindingError(
                "映射的点击坐标不在所选目标窗口范围内。请先用“取点”选择窗口中的点击位置，"
                "再用“选择窗口”点一下同一个目标程序。"
            )
        target_hwnd = self.background_click_target(x, y, expected_root=root_hwnd)
        if not target_hwnd:
            raise WindowBindingError(
                "无法在所选程序内找到点击坐标对应的窗口或控件。请确保目标程序没有最小化。"
            )
        root_point = POINT(int(x), int(y))
        target_point = POINT(int(x), int(y))
        if not user32.ScreenToClient(root_hwnd, ctypes.byref(root_point)) or not user32.ScreenToClient(
            target_hwnd, ctypes.byref(target_point)
        ):
            raise WindowBindingError("无法换算目标窗口的客户区坐标。")
        target_rect = RECT()
        if not user32.GetClientRect(target_hwnd, ctypes.byref(target_rect)) or not (
            target_rect.left <= target_point.x < target_rect.right
            and target_rect.top <= target_point.y < target_rect.bottom
        ):
            raise WindowBindingError(
                "点击坐标不在目标窗口的可点击客户区内，请重新取点。"
            )
        pid, process_path = self.process_info(root_hwnd)
        try:
            control_id = int(user32.GetDlgCtrlID(target_hwnd))
        except Exception:
            control_id = 0
        return {
            "root_hwnd": int(root_hwnd),
            "target_hwnd": int(target_hwnd),
            "pid": pid,
            "process_path": process_path,
            "root_class": self.class_name(root_hwnd),
            "root_title": self.title(root_hwnd),
            "target_class": self.class_name(target_hwnd),
            "target_control_id": control_id if control_id > 0 else 0,
            "root_client_x": int(root_point.x),
            "root_client_y": int(root_point.y),
            "target_client_x": int(target_point.x),
            "target_client_y": int(target_point.y),
        }

    def create_binding_for_window_at_point(
        self, selection_x: int, selection_y: int, click_x: int, click_y: int
    ) -> dict:
        root_hwnd = self.root_window_at_point(
            selection_x, selection_y, exclude_current_process=True
        )
        if not root_hwnd:
            raise WindowBindingError(
                "没有选中其他程序窗口。请在提示出现后，左键单击目标程序窗口中的任意位置。"
            )
        return self.create_binding_for_root(root_hwnd, click_x, click_y)

    def create_binding(self, x: int, y: int) -> dict:
        """Compatibility helper for older callers that selected by click coordinate."""

        root_hwnd = self.root_window_at_point(x, y, exclude_current_process=True)
        if not root_hwnd:
            raise WindowBindingError(
                "当前坐标下没有找到其他程序的可绑定窗口。"
            )
        return self.create_binding_for_root(root_hwnd, x, y)

    def matches_binding(self, hwnd, binding):
        if not hwnd or not user32.IsWindow(hwnd):
            return False
        expected_class = str(binding.get("root_class", "")).strip()
        if expected_class and self.class_name(hwnd) != expected_class:
            return False
        pid, process_path = self.process_info(hwnd)
        expected_path = os.path.normcase(str(binding.get("process_path", "")).strip())
        if expected_path:
            return process_path == expected_path
        expected_title = str(binding.get("root_title", "")).strip()
        if expected_title:
            return self.title(hwnd) == expected_title
        return int(binding.get("pid", 0) or 0) == pid

    def resolve_binding(self, binding):
        if not isinstance(binding, dict) or not binding:
            return None
        try:
            stored_root = int(binding.get("root_hwnd", 0))
        except (TypeError, ValueError):
            stored_root = 0
        root_hwnd = stored_root if stored_root and self.matches_binding(stored_root, binding) else None
        if not root_hwnd:
            candidates = []
            expected_title = str(binding.get("root_title", "")).strip()
            expected_path = os.path.normcase(str(binding.get("process_path", "")).strip())

            def enum_proc(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd) or not self.matches_binding(hwnd, binding):
                    return True
                pid, path = self.process_info(hwnd)
                score = (8 if expected_path and path == expected_path else 0)
                score += 4 if expected_title and self.title(hwnd) == expected_title else 0
                score += 2 if int(binding.get("pid", 0) or 0) == pid else 0
                candidates.append((score, int(hwnd)))
                return True

            try:
                callback = WNDENUMPROC(enum_proc)
                user32.EnumWindows(callback, 0)
            except Exception:
                candidates = []
            if not candidates:
                return None
            candidates.sort(key=lambda item: item[0], reverse=True)
            root_hwnd = candidates[0][1]

        try:
            stored_target = int(binding.get("target_hwnd", 0))
        except (TypeError, ValueError):
            stored_target = 0
        target_class = str(binding.get("target_class", "")).strip()
        target_hwnd = None
        if stored_target and user32.IsWindow(stored_target):
            target_root = user32.GetAncestor(stored_target, GA_ROOT) or stored_target
            if int(target_root) == int(root_hwnd) and (
                not target_class or self.class_name(stored_target) == target_class
            ):
                target_hwnd = stored_target
        if not target_hwnd:
            control_id = int(binding.get("target_control_id", 0) or 0)
            if control_id > 0:
                candidate = user32.GetDlgItem(root_hwnd, control_id)
                if candidate and (not target_class or self.class_name(candidate) == target_class):
                    target_hwnd = candidate
        if target_hwnd:
            client_x = int(binding.get("target_client_x", 0) or 0)
            client_y = int(binding.get("target_client_y", 0) or 0)
        else:
            screen_point = POINT(
                int(binding.get("root_client_x", 0) or 0),
                int(binding.get("root_client_y", 0) or 0),
            )
            if not user32.ClientToScreen(root_hwnd, ctypes.byref(screen_point)):
                return None
            target_hwnd = self.background_click_target(
                screen_point.x, screen_point.y, expected_root=root_hwnd
            )
            if not target_hwnd:
                return None
            target_point = POINT(screen_point.x, screen_point.y)
            if not user32.ScreenToClient(target_hwnd, ctypes.byref(target_point)):
                return None
            client_x, client_y = int(target_point.x), int(target_point.y)
        client_rect = RECT()
        if not user32.GetClientRect(target_hwnd, ctypes.byref(client_rect)):
            return None
        if not (
            client_rect.left <= client_x < client_rect.right
            and client_rect.top <= client_y < client_rect.bottom
        ):
            return None
        return target_hwnd, client_x, client_y

    @staticmethod
    def foreground_click(x, y, button, click_times, restore_position=False):
        old_position = None
        if restore_position:
            try:
                old_position = pyautogui.position()
            except Exception:
                old_position = None
        try:
            pyautogui.moveTo(x, y, duration=0)
            for _index in range(click_times):
                pressed = False
                try:
                    pyautogui.mouseDown(button=button)
                    pressed = True
                    time.sleep(0.04)
                finally:
                    if pressed:
                        pyautogui.mouseUp(button=button)
                if click_times > 1:
                    time.sleep(0.02)
        finally:
            if restore_position and old_position:
                try:
                    pyautogui.moveTo(old_position.x, old_position.y, duration=0)
                except (AttributeError, TypeError):
                    pyautogui.moveTo(old_position[0], old_position[1], duration=0)

    @staticmethod
    def screen_point_for_target(hwnd, client_x, client_y):
        point = POINT(int(client_x), int(client_y))
        if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
            return None
        return int(point.x), int(point.y)

    def background_click(self, binding, button, click_times):
        # UIA and PostMessage report delivery only; a target may still ignore either.
        self.last_background_method = ""
        self.last_background_detail = {}
        resolved = self.resolve_binding(binding)
        if not resolved:
            return False
        hwnd, client_x, client_y = resolved
        root_hwnd = int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
        screen_point = self.screen_point_for_target(hwnd, client_x, client_y)
        if button == "left" and int(click_times) == 1 and screen_point:
            uia_result = self.ui_automation.activate(
                root_hwnd,
                screen_point[0],
                screen_point[1],
                preferred_hwnd=hwnd,
            )
            self.last_background_detail = dict(uia_result)
            if uia_result.get("success"):
                self.last_background_method = str(
                    uia_result.get("method") or "UI Automation"
                )
                return True
            if uia_result.get("outcome_unknown"):
                # A timed-out COM call may still finish after the caller resumes.
                # Do not risk a duplicate action by sending PostMessage as well.
                self.last_background_method = "UI Automation 超时（未重复点击）"
                return False

        lparam = make_mouse_lparam(client_x, client_y)
        if button == "right":
            down_msg, up_msg, double_msg, down_flag = (
                WM_RBUTTONDOWN,
                WM_RBUTTONUP,
                WM_RBUTTONDBLCLK,
                MK_RBUTTON,
            )
        else:
            down_msg, up_msg, double_msg, down_flag = (
                WM_LBUTTONDOWN,
                WM_LBUTTONUP,
                WM_LBUTTONDBLCLK,
                MK_LBUTTON,
            )
        ok = bool(user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam))
        sequence = (
            [(down_msg, down_flag), (up_msg, 0), (double_msg, down_flag), (up_msg, 0)]
            if click_times >= 2
            else [(down_msg, down_flag), (up_msg, 0)]
        )
        for message, parameter in sequence:
            ok = bool(user32.PostMessageW(hwnd, message, parameter, lparam)) and ok
            time.sleep(0.02 if message == up_msg else 0.01)
        if ok:
            self.last_background_method = "PostMessage"
        return ok

    def uia_control_action(self, binding, operation, value=""):
        """Run one UIA action against the control selected by a saved binding."""
        resolved = self.resolve_binding(binding)
        if not resolved:
            return {
                "available": self.ui_automation.available,
                "actionable": False,
                "success": False,
                "error": "目标窗口已经失效，请重新选择控件。",
            }
        hwnd, client_x, client_y = resolved
        root_hwnd = int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
        point = self.screen_point_for_target(hwnd, client_x, client_y)
        if not point:
            return {
                "available": self.ui_automation.available,
                "actionable": False,
                "success": False,
                "error": "无法换算控件坐标。",
            }
        if operation == "activate":
            return self.ui_automation.activate(
                root_hwnd, point[0], point[1], preferred_hwnd=hwnd
            )
        if operation == "set_value":
            return self.ui_automation.set_value(
                root_hwnd,
                point[0],
                point[1],
                str(value),
                preferred_hwnd=hwnd,
            )
        if operation == "read_value":
            return self.ui_automation.read_value(
                root_hwnd, point[0], point[1], preferred_hwnd=hwnd
            )
        raise ValueError(f"不支持的 UI Automation 操作：{operation}")

    def inspect_binding(self, binding):
        resolved = self.resolve_binding(binding)
        if not resolved:
            return {"valid": False, "warnings": ["目标窗口已经失效，请重新选择窗口。"]}
        target_hwnd, client_x, client_y = resolved
        root_hwnd = user32.GetAncestor(target_hwnd, GA_ROOT) or target_hwnd
        point = self.screen_point_for_target(target_hwnd, client_x, client_y)
        uia_report = (
            self.ui_automation.probe(
                root_hwnd,
                point[0],
                point[1],
                preferred_hwnd=target_hwnd,
            )
            if point
            else {
                "available": self.ui_automation.available,
                "actionable": False,
                "error": "无法换算绑定坐标。",
            }
        )
        return self.inspector.inspect(
            root_hwnd,
            target_hwnd,
            binding=binding,
            uia_report=uia_report,
        )
