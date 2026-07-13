"""Physical Windows desktop to logical Qt coordinate conversion."""

import ctypes

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from .win32_api import MONITORENUMPROC, MONITORINFOEXW, user32


class ScreenCoordinateMapper:
    def __init__(self):
        self.screens = list(QApplication.screens())
        self.virtual_rect = QRect()
        for screen in self.screens:
            rectangle = screen.geometry()
            self.virtual_rect = (
                QRect(rectangle) if self.virtual_rect.isNull() else self.virtual_rect.united(rectangle)
            )
        if self.virtual_rect.isNull():
            self.virtual_rect = QApplication.primaryScreen().virtualGeometry()

        physical_by_name = {item["name"].upper(): item for item in self._physical_monitors()}
        unused = list(physical_by_name.values())
        self.entries = []
        for screen in self.screens:
            name = str(screen.name()).upper()
            physical = physical_by_name.get(name)
            if physical in unused:
                unused.remove(physical)
            if physical is None and unused:
                physical = min(
                    unused,
                    key=lambda item: abs(
                        item["width"] - screen.geometry().width() * screen.devicePixelRatio()
                    ) + abs(item["height"] - screen.geometry().height() * screen.devicePixelRatio()),
                )
                unused.remove(physical)
            if physical is None:
                rectangle = screen.geometry()
                ratio = max(0.01, float(screen.devicePixelRatio()))
                physical = {
                    "name": name,
                    "left": int(round(rectangle.x() * ratio)),
                    "top": int(round(rectangle.y() * ratio)),
                    "width": max(1, int(round(rectangle.width() * ratio))),
                    "height": max(1, int(round(rectangle.height() * ratio))),
                }
            self.entries.append({"logical": QRect(screen.geometry()), "physical": physical})

    def _physical_monitors(self):
        monitors = []

        def enum_proc(hmonitor, _hdc, _rectangle, _data):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                rectangle = info.rcMonitor
                monitors.append({
                    "name": str(info.szDevice),
                    "left": int(rectangle.left),
                    "top": int(rectangle.top),
                    "width": max(1, int(rectangle.right - rectangle.left)),
                    "height": max(1, int(rectangle.bottom - rectangle.top)),
                })
            return True

        try:
            callback = MONITORENUMPROC(enum_proc)
            user32.EnumDisplayMonitors(None, None, callback, 0)
        except Exception:
            return []
        return monitors

    def apply_to(self, widget):
        widget.setGeometry(self.virtual_rect)

    def _entry_for_physical(self, x, y):
        for entry in self.entries:
            rectangle = entry["physical"]
            if (
                rectangle["left"] <= x < rectangle["left"] + rectangle["width"]
                and rectangle["top"] <= y < rectangle["top"] + rectangle["height"]
            ):
                return entry
        return self.entries[0] if self.entries else None

    def _entry_for_logical(self, x, y):
        point = QPoint(int(round(x)), int(round(y)))
        for entry in self.entries:
            if entry["logical"].contains(point):
                return entry
        return self.entries[0] if self.entries else None

    def physical_to_local(self, x, y):
        entry = self._entry_for_physical(float(x), float(y))
        if entry is None:
            return QPoint(int(round(x)), int(round(y)))
        logical = entry["logical"]
        physical = entry["physical"]
        global_x = logical.x() + (float(x) - physical["left"]) * logical.width() / physical["width"]
        global_y = logical.y() + (float(y) - physical["top"]) * logical.height() / physical["height"]
        return QPoint(
            int(round(global_x - self.virtual_rect.x())),
            int(round(global_y - self.virtual_rect.y())),
        )

    def local_to_physical(self, point):
        global_x = float(point.x() + self.virtual_rect.x())
        global_y = float(point.y() + self.virtual_rect.y())
        entry = self._entry_for_logical(global_x, global_y)
        if entry is None:
            return int(round(global_x)), int(round(global_y))
        logical = entry["logical"]
        physical = entry["physical"]
        physical_x = physical["left"] + (
            (global_x - logical.x()) * physical["width"] / max(1, logical.width())
        )
        physical_y = physical["top"] + (
            (global_y - logical.y()) * physical["height"] / max(1, logical.height())
        )
        return int(round(physical_x)), int(round(physical_y))

    def local_rect_to_physical(self, rectangle):
        first = self.local_to_physical(rectangle.topLeft())
        last = self.local_to_physical(
            QPoint(rectangle.x() + rectangle.width(), rectangle.y() + rectangle.height())
        )
        left, right = sorted((first[0], last[0]))
        top, bottom = sorted((first[1], last[1]))
        return left, top, max(1, right - left), max(1, bottom - top)
