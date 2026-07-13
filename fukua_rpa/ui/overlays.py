"""Full-screen preview, running-status, and click-indicator overlays."""

import time

from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from ..coordinates import ScreenCoordinateMapper
from ..task_model import parse_float_text

class CoordinateStepPreviewOverlay(QWidget):
    def __init__(self, points, options=None, title=None, auto_close_ms=6000, draw_lines=True, editable_indices=None, point_moved_callback=None, detail_text=None, close_on_left_blank=True, marked_indices=None, point_labels=None, line_segments=None):
        super().__init__()
        self.points = [(float(x), float(y)) for x, y in points]
        self.options = options or {}
        self.custom_title = title
        self.detail_text = detail_text
        self.auto_close_ms = auto_close_ms
        self.draw_lines = draw_lines
        self.editable_indices = set(editable_indices or [])
        self.marked_indices = set(marked_indices or [])
        self.point_moved_callback = point_moved_callback
        self.close_on_left_blank = close_on_left_blank
        self.point_labels = list(point_labels or [])
        self.line_segments = list(line_segments or [])
        self.drag_index = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

        self.screen_mapper = ScreenCoordinateMapper()
        self.screen_mapper.apply_to(self)

        if self.auto_close_ms > 0:
            QTimer.singleShot(self.auto_close_ms, self.close)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def to_screen_point(self, x, y):
        return self.screen_mapper.physical_to_local(x, y)

    def set_points(self, points):
        self.points = [(float(x), float(y)) for x, y in points]
        self.update()

    def set_marked_indices(self, marked_indices):
        self.marked_indices = set(marked_indices or [])
        self.update()

    def from_screen_point(self, point):
        return self.screen_mapper.local_to_physical(point)

    def nearest_editable_index(self, pos):
        if not self.editable_indices or not self.points:
            return None
        screen_points = [self.to_screen_point(x, y) for x, y in self.points]
        best_idx = None
        best_dist = 18 * 18
        for idx in self.editable_indices:
            if idx < 0:
                idx = len(screen_points) + idx
            if idx < 0 or idx >= len(screen_points):
                continue
            point = screen_points[idx]
            dist = (point.x() - pos.x()) ** 2 + (point.y() - pos.y()) ** 2
            if dist <= best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if not self.points:
            return

        if self.custom_title:
            title = self.custom_title
        else:
            title = f"坐标步进预览：{len(self.points)} 个可轮到的点位"
            if self.auto_close_ms > 0:
                title += f"，{int(self.auto_close_ms / 1000)} 秒后自动关闭"
        if not self.custom_title and self.options.get("direction") == "移动到新点位":
            max_steps = max(0, int(parse_float_text(self.options.get("max_steps", 0), 0)))
            if max_steps >= 2:
                title += f"；移动上限 {max_steps} = 起点到目标点共 {max_steps} 个点"
            else:
                title += "；移动上限 0 = 起点后直接移动到目标点"
        painter.setFont(QFont("Arial", 13, QFont.Bold))
        fm = painter.fontMetrics()
        max_title_width = max(360, self.width() - 40)
        title = fm.elidedText(title, Qt.ElideRight, max_title_width - 24)
        detail = self.detail_text or ""
        min_title_width = 520 if detail else 0
        title_rect = QRect(20, 24, min(max(fm.horizontalAdvance(title) + 24, min_title_width), max_title_width), 58 if detail else 34)
        title_rect.moveLeft(max(20, (self.width() - title_rect.width()) // 2))
        painter.fillRect(title_rect, QColor(0, 0, 0, 190))
        painter.setPen(QColor(255, 255, 255))
        if detail:
            painter.drawText(QRect(title_rect.x() + 12, title_rect.y() + 5, title_rect.width() - 24, 24), Qt.AlignCenter, title)
            painter.setFont(QFont("Arial", 9))
            dfm = painter.fontMetrics()
            draw_detail = dfm.elidedText(detail, Qt.ElideRight, title_rect.width() - 24)
            painter.drawText(QRect(title_rect.x() + 12, title_rect.y() + 30, title_rect.width() - 24, 22), Qt.AlignCenter, draw_detail)
        else:
            painter.drawText(title_rect, Qt.AlignCenter, title)

        screen_points = [self.to_screen_point(x, y) for x, y in self.points]
        if self.line_segments:
            for segment in self.line_segments:
                try:
                    start_idx, end_idx = int(segment.get("from")), int(segment.get("to"))
                    if start_idx < 0 or end_idx < 0 or start_idx >= len(screen_points) or end_idx >= len(screen_points):
                        continue
                    style = Qt.DashLine if segment.get("style") == "dash" else Qt.SolidLine
                    color = QColor(255, 193, 7, 175) if style == Qt.DashLine else QColor(0, 188, 212, 220)
                    width = 2 if style == Qt.DashLine else 3
                    painter.setPen(QPen(color, width, style, Qt.RoundCap))
                    painter.drawLine(screen_points[start_idx], screen_points[end_idx])
                except Exception:
                    continue
        elif self.draw_lines and len(screen_points) > 1:
            painter.setPen(QPen(QColor(0, 188, 212, 220), 3, Qt.SolidLine, Qt.RoundCap))
            for idx in range(len(screen_points) - 1):
                painter.drawLine(screen_points[idx], screen_points[idx + 1])

        painter.setFont(QFont("Arial", 10, QFont.Bold))
        normalized_editable = set()
        for edit_idx in self.editable_indices:
            normalized_editable.add(len(screen_points) + edit_idx if edit_idx < 0 else edit_idx)
        normalized_marked = set()
        for mark_idx in self.marked_indices:
            normalized_marked.add(len(screen_points) + mark_idx if mark_idx < 0 else mark_idx)
        for idx, point in enumerate(screen_points, 1):
            zero_idx = idx - 1
            if zero_idx in normalized_marked:
                fill = QColor(156, 39, 176, 135)
            elif idx == 1:
                fill = QColor(76, 175, 80, 135)
            elif idx == len(screen_points):
                fill = QColor(244, 67, 54, 135)
            else:
                fill = QColor(255, 193, 7, 125)

            radius = 7 if zero_idx in normalized_marked else (6 if zero_idx in normalized_editable else 5)
            painter.setBrush(fill)
            painter.setPen(QPen(QColor(255, 255, 255, 185), 2 if zero_idx in normalized_editable or zero_idx in normalized_marked else 1))
            painter.drawEllipse(point, radius, radius)
            painter.setBrush(QColor(255, 255, 255, 230))
            painter.setPen(QPen(QColor(0, 0, 0, 180), 1))
            painter.drawEllipse(point, 2, 2)

            label = self.point_labels[zero_idx] if zero_idx < len(self.point_labels) and self.point_labels[zero_idx] else str(idx)
            if zero_idx in normalized_marked and "*" not in label:
                label = f"{label}*"
            label_w = max(48, min(96, painter.fontMetrics().horizontalAdvance(label) + 16))
            label_rect = QRect(point.x() + 8, point.y() - 20, label_w, 22)
            painter.fillRect(label_rect, QColor(0, 0, 0, 155))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(label_rect, Qt.AlignCenter, label)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.close()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            idx = self.nearest_editable_index(event.position().toPoint())
            if idx is not None:
                self.drag_index = idx
                self.setCursor(Qt.SizeAllCursor)
                event.accept()
                return
            if self.close_on_left_blank:
                self.close()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self.drag_index is not None:
            x, y = self.from_screen_point(pos)
            self.points[self.drag_index] = (x, y)
            if self.point_moved_callback:
                try:
                    updated_points = self.point_moved_callback(self.drag_index, int(round(x)), int(round(y)))
                    if updated_points:
                        self.set_points(updated_points)
                except RuntimeError:
                    self.point_moved_callback = None
            self.update()
            event.accept()
            return
        self.setCursor(Qt.SizeAllCursor if self.nearest_editable_index(pos) is not None else Qt.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drag_index is not None:
            idx = self.drag_index
            self.drag_index = None
            self.setCursor(Qt.PointingHandCursor)
            x, y = self.points[idx]
            if self.point_moved_callback:
                try:
                    updated_points = self.point_moved_callback(idx, int(round(x)), int(round(y)))
                    if updated_points:
                        self.set_points(updated_points)
                except RuntimeError:
                    self.point_moved_callback = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

class RunningStatusOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.position_name = "右上角"
        self.start_time = time.time()
        self.status_data = {}
        self.setFixedWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bg = QFrame()
        self.bg.setStyleSheet("background-color: rgba(17, 24, 39, 240); border-radius: 8px; border: 2px solid #3B82F6;")
        layout.addWidget(self.bg)

        inner = QVBoxLayout(self.bg)
        inner.setContentsMargins(12, 8, 12, 8)
        self.label = QLabel()
        self.label.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setFixedWidth(248)
        inner.addWidget(self.label)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_text)

    def start_overlay(self, position_name):
        self.position_name = position_name
        self.start_time = time.time()
        self.status_data = {}
        self.timer.start(500)
        self.refresh_text()
        self.show()
        self.raise_()

    def set_status(self, data):
        self.status_data.update(data)
        self.refresh_text()

    def refresh_text(self):
        elapsed = int(time.time() - self.start_time)
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        elapsed_text = f"{h:02d}:{m:02d}:{s:02d}"
        loop = self.status_data.get("loop", 1)
        step = self.status_data.get("step", 0)
        total = self.status_data.get("total", 0)
        cmd = self.status_data.get("cmd", "")
        step_text = f"步骤 {step}/{total}" if step and total else "准备中"
        if cmd:
            step_text += f" | {cmd}"
        self.label.setText(f"脚本正在执行中\n第 {loop} 次 | {step_text}\n已运行 {elapsed_text}")
        self.adjustSize()
        self.move_to_position()

    def move_to_position(self):
        rect = QApplication.primaryScreen().availableGeometry()
        margin = 18
        x = max(rect.x() + margin, rect.x() + rect.width() - self.width() - margin)
        if self.position_name == "右下角":
            y = rect.y() + rect.height() - self.height() - margin
        else:
            y = rect.y() + margin
        self.move(x, y)

    def stop_overlay(self):
        self.timer.stop()
        self.hide()

class ClickPointOverlay(QWidget):
    def __init__(self, x, y, text="", duration_ms=650):
        super().__init__()
        self.x = float(x)
        self.y = float(y)
        self.text = str(text or "")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.screen_mapper = ScreenCoordinateMapper()
        self.screen_mapper.apply_to(self)
        QTimer.singleShot(max(200, int(duration_ms)), self.close)
        self.show()
        self.raise_()

    def to_screen_point(self):
        return self.screen_mapper.physical_to_local(self.x, self.y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        point = self.to_screen_point()

        painter.setPen(QPen(QColor(255, 255, 255, 235), 4))
        painter.setBrush(QColor(33, 150, 243, 90))
        painter.drawEllipse(point, 18, 18)
        painter.setPen(QPen(QColor(244, 67, 54, 245), 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(point.x() - 24, point.y(), point.x() + 24, point.y())
        painter.drawLine(point.x(), point.y() - 24, point.x(), point.y() + 24)

        if self.text:
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            label = painter.fontMetrics().elidedText(self.text, Qt.ElideRight, 160)
            rect = QRect(point.x() + 24, point.y() - 14, min(170, painter.fontMetrics().horizontalAdvance(label) + 20), 28)
            if rect.right() > self.width() - 8:
                rect.moveRight(point.x() - 24)
            painter.fillRect(rect, QColor(0, 0, 0, 180))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect, Qt.AlignCenter, label)
