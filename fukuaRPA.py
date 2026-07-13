"""fukuaRPA v1.0.11 application entry point.

Implementation lives in the ``fukua_rpa`` package. This file intentionally keeps
only process setup, a small compatibility export surface, and application startup.
"""

import ctypes
import importlib
import json
import multiprocessing
import os
import sys
import tempfile
import threading
import time
from typing import TYPE_CHECKING

_PYTHON_START_TIME = time.perf_counter()

# Configure DPI handling before importing Qt widgets.
try:
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from fukua_rpa.constants import (
    APP_VERSION,
    BUILD_NAME,
    NATIVE_CORE_MIN_VERSION,
    PRODUCT_NAME,
    SUPPORTED_WINDOWS_TEXT,
)
from fukua_rpa.paths import get_base_dir, get_resource_path
from fukua_rpa.session import SingleInstanceGuard

if TYPE_CHECKING:
    from fukua_rpa.engine import RPAEngine
    from fukua_rpa.ui.input_tools import RecorderUI
    from fukua_rpa.ui.main_window import RPAWindow
    from fukua_rpa.vision import (
        NativeVisionCore,
        build_scale_values,
        template_detail_status,
    )

__all__ = [
    "APP_VERSION",
    "BUILD_NAME",
    "NATIVE_CORE_MIN_VERSION",
    "NativeVisionCore",
    "PRODUCT_NAME",
    "RPAEngine",
    "RPAWindow",
    "RecorderUI",
    "SUPPORTED_WINDOWS_TEXT",
    "build_scale_values",
    "template_detail_status",
]

_LAZY_EXPORTS = {
    "NativeVisionCore": ("fukua_rpa.vision", "NativeVisionCore"),
    "RPAEngine": ("fukua_rpa.engine", "RPAEngine"),
    "RPAWindow": ("fukua_rpa.ui.main_window", "RPAWindow"),
    "RecorderUI": ("fukua_rpa.ui.input_tools", "RecorderUI"),
    "build_scale_values": ("fukua_rpa.vision", "build_scale_values"),
    "template_detail_status": ("fukua_rpa.vision", "template_detail_status"),
}


def __getattr__(name):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module = importlib.import_module(target[0])
    value = getattr(module, target[1])
    globals()[name] = value
    return value


class StartupLoadBridge(QObject):
    loaded = Signal(object, float)
    failed = Signal(str)


def _atomic_write_text(target, text):
    target = os.path.abspath(target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(target)}.",
        suffix=".tmp",
        dir=os.path.dirname(target),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def main():
    multiprocessing.freeze_support()
    native_smoke_target = None
    native_smoke_requested = "--native-smoke" in sys.argv
    if "--native-smoke-file" in sys.argv:
        native_smoke_requested = True
        index = sys.argv.index("--native-smoke-file")
        if index + 1 >= len(sys.argv):
            return 2
        native_smoke_target = os.path.abspath(sys.argv[index + 1])
    if native_smoke_requested:
        from fukua_rpa.native_smoke import run_native_smoke

        report = run_native_smoke(get_base_dir())
        serialized = json.dumps(report, ensure_ascii=False, indent=2)
        if native_smoke_target:
            _atomic_write_text(native_smoke_target, serialized)
        else:
            print(serialized)
        return 0 if report.get("ok") else 1

    uia_smoke_target = None
    uia_smoke_requested = "--uia-smoke" in sys.argv
    if "--uia-smoke-file" in sys.argv:
        uia_smoke_requested = True
        index = sys.argv.index("--uia-smoke-file")
        if index + 1 >= len(sys.argv):
            return 2
        uia_smoke_target = os.path.abspath(sys.argv[index + 1])
    if uia_smoke_requested:
        from fukua_rpa.uia_smoke import run_uia_smoke

        report = run_uia_smoke()
        serialized = json.dumps(report, ensure_ascii=False, indent=2)
        if uia_smoke_target:
            _atomic_write_text(uia_smoke_target, serialized)
        else:
            print(serialized)
        return 0 if report.get("ok") else 1

    self_test_target = None
    self_test_requested = "--self-test" in sys.argv
    if "--self-test-file" in sys.argv:
        self_test_requested = True
        index = sys.argv.index("--self-test-file")
        if index + 1 >= len(sys.argv):
            return 2
        self_test_target = os.path.abspath(sys.argv[index + 1])
    if self_test_requested:
        from fukua_rpa.diagnostics import run_runtime_diagnostics

        report = run_runtime_diagnostics()
        serialized = json.dumps(report, ensure_ascii=False, indent=2)
        if self_test_target:
            _atomic_write_text(self_test_target, serialized)
        else:
            print(serialized)
        return 0 if report["ok"] else 1

    startup_smoke_target = None
    startup_runtime_dir = get_base_dir()
    if "--startup-smoke-file" in sys.argv:
        index = sys.argv.index("--startup-smoke-file")
        if index + 1 >= len(sys.argv):
            return 2
        startup_smoke_target = os.path.abspath(sys.argv[index + 1])
    if "--startup-runtime-dir" in sys.argv:
        index = sys.argv.index("--startup-runtime-dir")
        if index + 1 >= len(sys.argv):
            return 2
        startup_runtime_dir = os.path.abspath(sys.argv[index + 1])
        os.makedirs(startup_runtime_dir, exist_ok=True)

    instance_guard = SingleInstanceGuard(startup_runtime_dir)
    if not instance_guard.acquire():
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "当前解压目录中的 fukuaRPA 已经在运行。\n\n"
                "如任务栏中没有窗口，请先在任务管理器中结束旧进程后再启动。",
                "fukuaRPA 已在运行",
                0x00000040,
            )
        except Exception:
            pass
        return 3
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FUKUA.fukuaRPA.v1")
    except Exception:
        pass
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName(PRODUCT_NAME)
        app.setApplicationDisplayName(f"{PRODUCT_NAME} {APP_VERSION}")
        icon = QIcon(get_resource_path(os.path.join("assets", "fukuaRPA.ico")))
        if not icon.isNull():
            app.setWindowIcon(icon)
        from fukua_rpa.ui.startup import StartupShell

        shell = StartupShell()
        if not icon.isNull():
            shell.setWindowIcon(icon)
        shell.show()
        app._fukua_startup_shell = shell
        app._fukua_main_window = None
        app._fukua_startup_cancelled = False
        bridge = StartupLoadBridge(app)
        app._fukua_startup_bridge = bridge
        startup_started = time.perf_counter()
        startup_metrics = {
            "python_to_shell_first_paint_ms": None,
            "workspace_import_ms": None,
            "workspace_visible_ms": None,
            "runtime_ready_ms": None,
            "runtime_backend_ms": None,
        }
        app._fukua_startup_metrics = startup_metrics

        def write_startup_smoke(ok, error=""):
            if not startup_smoke_target:
                return
            report = {
                "format": "fukuaRPA_startup_smoke",
                "application_version": APP_VERSION,
                "build_name": BUILD_NAME,
                "ok": bool(ok),
                **startup_metrics,
                "error": str(error or ""),
            }
            _atomic_write_text(
                startup_smoke_target,
                json.dumps(report, ensure_ascii=False, indent=2),
            )

        def cancel_startup():
            app._fukua_startup_cancelled = True
            app.quit()

        shell.cancelled.connect(cancel_startup)

        def workspace_loaded(window_class, import_ms):
            if app._fukua_startup_cancelled:
                return
            try:
                window = window_class(
                    base_dir=startup_runtime_dir, defer_runtime=True
                )
                if not icon.isNull():
                    window.setWindowIcon(icon)
                app._fukua_main_window = window
                window.show()
                startup_metrics["workspace_import_ms"] = round(import_ms, 3)
                startup_metrics["workspace_visible_ms"] = round(
                    (time.perf_counter() - _PYTHON_START_TIME) * 1000.0, 3
                )

                def runtime_initialized(ok, error, backend_ms):
                    startup_metrics["runtime_backend_ms"] = round(
                        float(backend_ms), 3
                    )
                    startup_metrics["runtime_ready_ms"] = round(
                        (time.perf_counter() - _PYTHON_START_TIME) * 1000.0, 3
                    )
                    write_startup_smoke(ok, error)
                    if startup_smoke_target:
                        QTimer.singleShot(50, app.quit)

                window.runtime_init_bridge.completed.connect(runtime_initialized)
                shell.handoff()
                from fukua_rpa.logging_service import write_log

                write_log(
                    f"启动首帧后加载：工作区导入 {import_ms:.1f} ms，"
                    f"主窗口可见共 {(time.perf_counter() - startup_started) * 1000.0:.1f} ms。"
                )
            except Exception as error:
                workspace_failed(str(error))

        def workspace_failed(message):
            if app._fukua_startup_cancelled:
                return
            shell.status_label.setText("工作区加载失败")
            write_startup_smoke(False, message)
            QMessageBox.critical(shell, "启动失败", message)
            app.exit(1)

        bridge.loaded.connect(workspace_loaded)
        bridge.failed.connect(workspace_failed)

        def load_workspace():
            started = time.perf_counter()
            try:
                from fukua_rpa.ui.main_window import RPAWindow

                bridge.loaded.emit(
                    RPAWindow, (time.perf_counter() - started) * 1000.0
                )
            except Exception as error:
                bridge.failed.emit(str(error))

        def begin_workspace_load():
            loader = threading.Thread(
                target=load_workspace,
                daemon=True,
                name="fukuaRPA-workspace-loader",
            )
            app._fukua_workspace_loader = loader
            loader.start()

        def shell_first_painted(painted_at):
            startup_metrics["python_to_shell_first_paint_ms"] = round(
                (float(painted_at) - _PYTHON_START_TIME) * 1000.0, 3
            )
            QTimer.singleShot(0, begin_workspace_load)

        shell.first_painted.connect(shell_first_painted)
        return app.exec()
    finally:
        from fukua_rpa.logging_service import flush_logs

        flush_logs()
        instance_guard.release()


if __name__ == "__main__":
    sys.exit(main())
