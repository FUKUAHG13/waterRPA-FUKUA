"""Minimal first-frame window shown while the full workspace imports."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..constants import APP_VERSION, PRODUCT_NAME


class StartupShell(QMainWindow):
    cancelled = Signal()
    first_painted = Signal(float)

    def __init__(self):
        super().__init__()
        self._handoff = False
        self._first_paint_emitted = False
        self.setWindowTitle(f"{PRODUCT_NAME} {APP_VERSION}")
        self.resize(760, 520)
        self.setMinimumSize(620, 420)

        body = QWidget()
        body.setObjectName("startupBody")
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(54, 46, 54, 46)
        layout.addStretch(3)

        brand = QLabel(PRODUCT_NAME)
        brand.setObjectName("startupBrand")
        brand.setAlignment(Qt.AlignCenter)
        layout.addWidget(brand)

        version = QLabel(APP_VERSION)
        version.setObjectName("startupVersion")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)
        layout.addSpacing(34)

        self.status_label = QLabel("正在准备工作区")
        self.status_label.setObjectName("startupStatus")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        progress = QProgressBar()
        progress.setObjectName("startupProgress")
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedHeight(6)
        layout.addWidget(progress)
        layout.addStretch(4)

        self.setStyleSheet(
            "QWidget#startupBody { background: #F7F9FC; }"
            "QLabel#startupBrand { color: #172033; font-size: 34px; font-weight: 750; }"
            "QLabel#startupVersion { color: #667085; font-size: 13px; }"
            "QLabel#startupStatus { color: #475467; font-size: 14px; padding: 8px; }"
            "QProgressBar#startupProgress { background: #E4E7EC; border: none; border-radius: 3px; }"
            "QProgressBar#startupProgress::chunk { background: #2563EB; border-radius: 3px; }"
        )

    def handoff(self):
        self._handoff = True
        self.close()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._first_paint_emitted:
            self._first_paint_emitted = True
            self.first_painted.emit(time.perf_counter())

    def closeEvent(self, event):
        if not self._handoff:
            self.cancelled.emit()
        super().closeEvent(event)
