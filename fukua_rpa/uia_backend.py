"""Bounded UI Automation probing and background control activation."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

try:
    import uiautomation as auto

    HAS_UI_AUTOMATION = True
    UI_AUTOMATION_IMPORT_ERROR = ""
except Exception as error:  # pragma: no cover - exercised by frozen self-test
    auto = None
    HAS_UI_AUTOMATION = False
    UI_AUTOMATION_IMPORT_ERROR = str(error)


MAX_UIA_NODES = 384
MAX_UIA_DEPTH = 12
UIA_REQUEST_TIMEOUT_SECONDS = 2.5
UIA_TREE_BUDGET_SECONDS = 1.5


def _bounded_text(value: Any, limit: int = 160) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _point_in_rect(rect: Any, x: int, y: int) -> bool:
    try:
        return (
            float(rect.left) <= int(x) < float(rect.right)
            and float(rect.top) <= int(y) < float(rect.bottom)
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _rect_area(rect: Any) -> float:
    try:
        return max(0.0, float(rect.right) - float(rect.left)) * max(
            0.0, float(rect.bottom) - float(rect.top)
        )
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _control_details(control: Any, action: str, depth: int) -> dict[str, Any]:
    def read(name: str, default: Any = "") -> Any:
        try:
            return getattr(control, name)
        except Exception:
            return default

    rect = read("BoundingRectangle", None)
    bounds = None
    if rect is not None:
        try:
            bounds = [
                int(rect.left),
                int(rect.top),
                int(rect.right),
                int(rect.bottom),
            ]
        except (AttributeError, TypeError, ValueError):
            bounds = None
    return {
        "name": _bounded_text(read("Name")),
        "automation_id": _bounded_text(read("AutomationId")),
        "class": _bounded_text(read("ClassName")),
        "framework": _bounded_text(read("FrameworkId")),
        "control_type": _bounded_text(read("ControlTypeName", "未知")),
        "enabled": bool(read("IsEnabled", False)),
        "offscreen": bool(read("IsOffscreen", False)),
        "native_hwnd": int(read("NativeWindowHandle", 0) or 0),
        "bounds": bounds,
        "depth": int(depth),
        "action": str(action),
    }


def _pattern_candidates(
    control: Any, operation: str = "activate"
) -> list[tuple[int, str, Any]]:
    candidates = []
    if operation in ("set_value", "read_value"):
        for priority, action, pattern_id in (
            (60, "Value", auto.PatternId.ValuePattern),
            (20, "LegacyValue", auto.PatternId.LegacyIAccessiblePattern),
        ):
            try:
                pattern = control.GetPattern(pattern_id)
                if operation == "set_value" and action == "Value" and pattern.IsReadOnly:
                    pattern = None
            except Exception:
                pattern = None
            if pattern is not None:
                candidates.append((priority, action, pattern))
        return candidates
    for priority, action, pattern_id in (
        (40, "Invoke", auto.PatternId.InvokePattern),
        (30, "Selection", auto.PatternId.SelectionItemPattern),
        (20, "Toggle", auto.PatternId.TogglePattern),
        (10, "DefaultAction", auto.PatternId.LegacyIAccessiblePattern),
    ):
        try:
            pattern = control.GetPattern(pattern_id)
        except Exception:
            pattern = None
        if pattern is not None:
            candidates.append((priority, action, pattern))
    return candidates


def _candidate_score(
    *,
    depth: int,
    area: float,
    action_priority: int,
    native_hwnd: int,
    preferred_hwnd: int,
    root_hwnd: int,
) -> tuple[int, int, float, int]:
    exact_bound_control = int(
        preferred_hwnd
        and preferred_hwnd != root_hwnd
        and native_hwnd == preferred_hwnd
    )
    return (
        exact_bound_control,
        int(depth),
        -max(0.0, float(area)),
        int(action_priority),
    )


def _find_actionable_control(
    root_hwnd: int,
    x: int,
    y: int,
    cancelled: threading.Event | None = None,
    preferred_hwnd: int = 0,
    operation: str = "activate",
) -> dict[str, Any]:
    if cancelled is not None and cancelled.is_set():
        return {
            "available": True,
            "actionable": False,
            "cancelled": True,
            "error": "UI Automation 请求已取消。",
        }
    root = auto.ControlFromHandle(int(root_hwnd))
    if root is None:
        return {"available": True, "actionable": False, "error": "无法读取绑定根窗口的 UI Automation 树。"}

    started = time.monotonic()
    scanned = 0
    candidate_controls = 0
    truncated = False
    matches = []
    try:
        iterator = auto.WalkControl(root, includeTop=True, maxDepth=MAX_UIA_DEPTH)
        for control, depth in iterator:
            if cancelled is not None and cancelled.is_set():
                return {
                    "available": True,
                    "actionable": False,
                    "cancelled": True,
                    "nodes_scanned": scanned,
                    "tree_truncated": truncated,
                    "error": "UI Automation 请求已取消。",
                }
            scanned += 1
            if scanned > MAX_UIA_NODES or time.monotonic() - started > UIA_TREE_BUDGET_SECONDS:
                truncated = True
                break
            try:
                rect = control.BoundingRectangle
            except Exception:
                continue
            if not _point_in_rect(rect, x, y):
                continue
            try:
                if not control.IsEnabled:
                    continue
                if control.IsOffscreen:
                    continue
            except Exception:
                pass
            patterns = _pattern_candidates(control, operation)
            if not patterns:
                continue
            candidate_controls += 1
            try:
                native_hwnd = int(control.NativeWindowHandle or 0)
            except Exception:
                native_hwnd = 0
            for priority, action, pattern in patterns:
                # An explicitly bound child HWND wins. Otherwise the deepest,
                # smallest control at the coordinate is safer than an ancestor.
                score = _candidate_score(
                    depth=int(depth),
                    area=_rect_area(rect),
                    action_priority=priority,
                    native_hwnd=native_hwnd,
                    preferred_hwnd=int(preferred_hwnd or 0),
                    root_hwnd=int(root_hwnd),
                )
                matches.append(
                    (score, control, action, pattern, int(depth), native_hwnd)
                )
    except Exception as error:
        return {
            "available": True,
            "actionable": False,
            "nodes_scanned": scanned,
            "candidate_controls": candidate_controls,
            "tree_truncated": truncated,
            "error": _bounded_text(error, 240),
        }

    if not matches:
        return {
            "available": True,
            "actionable": False,
            "nodes_scanned": scanned,
            "candidate_controls": candidate_controls,
            "tree_truncated": truncated,
            "error": (
                "坐标处没有发现可读取或设置文本的控件。"
                if operation in ("set_value", "read_value")
                else "坐标处没有发现支持 Invoke、Selection、Toggle 或默认动作的控件。"
            ),
        }
    matches.sort(key=lambda item: item[0], reverse=True)
    _score, control, action, pattern, depth, native_hwnd = matches[0]
    matched_bound_hwnd = bool(
        preferred_hwnd
        and preferred_hwnd != root_hwnd
        and native_hwnd == preferred_hwnd
    )
    return {
        "available": True,
        "actionable": True,
        "nodes_scanned": scanned,
        "candidate_controls": candidate_controls,
        "tree_truncated": truncated,
        "selection": "bound_hwnd" if matched_bound_hwnd else "deepest_control",
        "matched_bound_hwnd": matched_bound_hwnd,
        "control": _control_details(control, action, depth),
        "_pattern": pattern,
        "_action": action,
    }


def _run_pattern(pattern: Any, action: str) -> bool:
    try:
        if action == "Invoke":
            return bool(pattern.Invoke(waitTime=0))
        if action == "Selection":
            return bool(pattern.Select(waitTime=0))
        if action == "Toggle":
            return bool(pattern.Toggle(waitTime=0))
        if action == "DefaultAction":
            return bool(pattern.DoDefaultAction(waitTime=0))
    except Exception:
        return False
    return False


def _perform_uia_job(
    operation: str,
    payload: dict[str, Any],
    cancelled: threading.Event | None = None,
) -> dict[str, Any]:
    result = _find_actionable_control(
        int(payload.get("root_hwnd", 0)),
        int(payload.get("x", 0)),
        int(payload.get("y", 0)),
        cancelled,
        int(payload.get("preferred_hwnd", 0)),
        operation,
    )
    pattern = result.pop("_pattern", None)
    action = result.pop("_action", "")
    if operation == "probe" or not result.get("actionable"):
        return result
    if pattern is None:
        return {**result, "success": False, "error": "未知的 UI Automation 操作。"}
    if cancelled is not None and cancelled.is_set():
        return {
            **result,
            "success": False,
            "cancelled": True,
            "error": "UI Automation 请求已取消，未执行控件动作。",
        }
    if operation == "activate":
        success = _run_pattern(pattern, action)
        value = None
    elif operation == "set_value":
        try:
            success = bool(pattern.SetValue(str(payload.get("value", "")), waitTime=0))
        except TypeError:
            success = bool(pattern.SetValue(str(payload.get("value", ""))))
        value = None
    elif operation == "read_value":
        try:
            value = str(pattern.Value)
            success = True
        except Exception:
            value = ""
            success = False
    else:
        success = False
        value = None
    return {
        **result,
        "success": success,
        "method": f"UI Automation {action}",
        "value": value,
        "error": "" if success else f"控件声明支持 {action}，但调用没有成功。",
    }


class _UIAutomationService:
    """Keep all COM objects in one bounded worker apartment."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue(maxsize=16)
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._startup_error = UI_AUTOMATION_IMPORT_ERROR
        self._closing = False

    @property
    def available(self) -> bool:
        return HAS_UI_AUTOMATION and not self._closing

    def _ensure_started(self) -> bool:
        if not self.available:
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._worker,
                daemon=True,
                name="fukuaRPA-uia",
            )
            self._thread.start()
        self._ready.wait(2.0)
        return bool(self._thread and self._thread.is_alive() and not self._startup_error)

    def _worker(self) -> None:
        initializer = None
        try:
            initializer = auto.UIAutomationInitializerInThread()
            auto.SetGlobalSearchTimeout(1.0)
            # Instantiate the COM client in this apartment before accepting work.
            auto.GetRootControl()
            self._startup_error = ""
        except Exception as error:
            self._startup_error = _bounded_text(error, 240)
        finally:
            self._ready.set()
        if self._startup_error:
            if initializer is not None:
                initializer.Uninitialize()
            return

        while True:
            item = self._queue.get()
            if item is None:
                break
            operation, payload, completed, cancelled, holder = item
            try:
                holder["result"] = _perform_uia_job(operation, payload, cancelled)
            except Exception as error:
                holder["result"] = {
                    "available": True,
                    "actionable": False,
                    "success": False,
                    "error": _bounded_text(error, 240),
                }
            finally:
                completed.set()
        if initializer is not None:
            initializer.Uninitialize()

    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._ensure_started():
            return {
                "available": False,
                "actionable": False,
                "success": False,
                "error": self._startup_error or "UI Automation 不可用。",
            }
        completed = threading.Event()
        cancelled = threading.Event()
        holder: dict[str, Any] = {}
        try:
            self._queue.put_nowait(
                (operation, dict(payload), completed, cancelled, holder)
            )
        except queue.Full:
            return {
                "available": True,
                "actionable": False,
                "success": False,
                "error": "UI Automation 请求队列繁忙。",
            }
        if not completed.wait(UIA_REQUEST_TIMEOUT_SECONDS):
            cancelled.set()
            return {
                "available": True,
                "actionable": False,
                "success": False,
                "timed_out": True,
                "outcome_unknown": operation in ("activate", "set_value"),
                "error": "UI Automation 控件响应超时，动作结果未知。",
            }
        return dict(holder.get("result", {}))

    def close(self) -> None:
        self._closing = True
        thread = self._thread
        if not thread or not thread.is_alive():
            return
        deadline = time.monotonic() + 1.0
        while thread.is_alive():
            try:
                self._queue.put(None, timeout=0.1)
                break
            except queue.Full:
                if time.monotonic() >= deadline:
                    return
        thread.join(timeout=1.0)


class UIAutomationBackend:
    def __init__(self, service: Any | None = None):
        self._service = service or _UIAutomationService()

    @property
    def available(self) -> bool:
        return bool(getattr(self._service, "available", False))

    def probe(
        self,
        root_hwnd: int,
        x: int,
        y: int,
        preferred_hwnd: int = 0,
    ) -> dict[str, Any]:
        return self._service.request(
            "probe",
            {
                "root_hwnd": int(root_hwnd),
                "x": int(x),
                "y": int(y),
                "preferred_hwnd": int(preferred_hwnd),
            },
        )

    def activate(
        self,
        root_hwnd: int,
        x: int,
        y: int,
        preferred_hwnd: int = 0,
    ) -> dict[str, Any]:
        return self._service.request(
            "activate",
            {
                "root_hwnd": int(root_hwnd),
                "x": int(x),
                "y": int(y),
                "preferred_hwnd": int(preferred_hwnd),
            },
        )

    def set_value(
        self,
        root_hwnd: int,
        x: int,
        y: int,
        value: str,
        preferred_hwnd: int = 0,
    ) -> dict[str, Any]:
        return self._service.request(
            "set_value",
            {
                "root_hwnd": int(root_hwnd),
                "x": int(x),
                "y": int(y),
                "preferred_hwnd": int(preferred_hwnd),
                "value": str(value),
            },
        )

    def read_value(
        self,
        root_hwnd: int,
        x: int,
        y: int,
        preferred_hwnd: int = 0,
    ) -> dict[str, Any]:
        return self._service.request(
            "read_value",
            {
                "root_hwnd": int(root_hwnd),
                "x": int(x),
                "y": int(y),
                "preferred_hwnd": int(preferred_hwnd),
            },
        )

    def close(self) -> None:
        close = getattr(self._service, "close", None)
        if callable(close):
            close()
