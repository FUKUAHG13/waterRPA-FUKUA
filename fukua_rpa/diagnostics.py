"""Offline runtime checks used by source and packaged-build smoke tests."""

from __future__ import annotations

import importlib
import os
import platform
import struct
import sys
import tempfile
import time
from dataclasses import asdict, dataclass

from .constants import (
    APP_VERSION,
    BUILD_NAME,
    NATIVE_CORE_DLL_NAME,
    NATIVE_CORE_RELEASE_VERSION,
    SUPPORTED_WINDOWS_TEXT,
)
from .paths import get_base_dir
from .opencv_runtime import configure_opencv_threads
from .vision import NativeVisionCore


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    ok: bool
    detail: str


def _windows_support_check():
    if sys.platform != "win32":
        return False, f"当前平台为 {sys.platform}，仅支持 Windows"
    version = sys.getwindowsversion()
    if version.major < 10 or (version.major == 10 and version.build < 17763):
        return False, f"Windows build {version.build} 低于 1809 (17763)"
    return True, f"Windows {version.major}.{version.minor} build {version.build}"


def run_runtime_diagnostics(base_dir=None):
    base = os.path.abspath(base_dir or get_base_dir())
    checks: list[DiagnosticCheck] = []
    bits = struct.calcsize("P") * 8
    checks.append(DiagnosticCheck("architecture", bits == 64, f"{bits}-bit {platform.machine()}"))
    supported, detail = _windows_support_check()
    checks.append(DiagnosticCheck("windows_version", supported, detail))

    for module_name in (
        "PySide6",
        "cv2",
        "numpy",
        "PIL",
        "pyautogui",
        "mss",
        "uiautomation",
        "comtypes",
    ):
        try:
            module = importlib.import_module(module_name)
            version = getattr(module, "__version__", "bundled")
            checks.append(DiagnosticCheck(f"import:{module_name}", True, str(version)))
        except Exception as error:
            checks.append(DiagnosticCheck(f"import:{module_name}", False, str(error)))

    try:
        pyautogui_module = importlib.import_module("pyautogui")
        position = pyautogui_module.position()
        screen_size = pyautogui_module.size()
        input_backend_ok = (
            len(position) == 2
            and len(screen_size) == 2
            and int(screen_size[0]) > 0
            and int(screen_size[1]) > 0
        )
        checks.append(
            DiagnosticCheck(
                "pyautogui_input_backend",
                input_backend_ok,
                f"position={tuple(position)}, screen={tuple(screen_size)}",
            )
        )
    except Exception as error:
        pyautogui_module = None
        checks.append(DiagnosticCheck("pyautogui_input_backend", False, str(error)))

    try:
        if pyautogui_module is None:
            raise RuntimeError("PyAutoGUI input backend is unavailable")
        screenshot = pyautogui_module.screenshot(region=(0, 0, 1, 1))
        screenshot_size = tuple(getattr(screenshot, "size", ()))
        checks.append(
            DiagnosticCheck(
                "pyautogui_screenshot_backend",
                screenshot_size == (1, 1),
                f"size={screenshot_size}",
            )
        )
    except Exception as error:
        checks.append(
            DiagnosticCheck("pyautogui_screenshot_backend", False, str(error))
        )

    try:
        cv2_module = importlib.import_module("cv2")
        opencv_threads = configure_opencv_threads(cv2_module)
        checks.append(
            DiagnosticCheck(
                "opencv_thread_limit",
                opencv_threads <= 2,
                f"threads={opencv_threads}",
            )
        )
    except Exception as error:
        opencv_threads = 0
        checks.append(DiagnosticCheck("opencv_thread_limit", False, str(error)))

    resource_root = os.path.abspath(getattr(sys, "_MEIPASS", base))
    dll_candidates = [
        os.path.join(base, NATIVE_CORE_DLL_NAME),
        os.path.join(resource_root, NATIVE_CORE_DLL_NAME),
    ]
    dll_path = next((path for path in dll_candidates if os.path.isfile(path)), dll_candidates[0])
    checks.append(DiagnosticCheck("native_dll_file", os.path.isfile(dll_path), dll_path))
    native = NativeVisionCore(base_dir=base)
    checks.append(
        DiagnosticCheck(
            "native_dll_api",
            native.available and native.version >= NATIVE_CORE_RELEASE_VERSION,
            f"version={native.version}" if native.available else native.load_error,
        )
    )
    native_performance = native.performance_stats() if native.available else {}
    native_capabilities = native.capabilities() if native.available else {}
    native_abi = native.abi_snapshot()
    checks.append(
        DiagnosticCheck(
            "native_performance_api",
            bool(native_performance),
            (
                f"captures={native_performance.get('captures', 0)}, "
                f"cache_entries={native_performance.get('cache_entries', 0)}"
                if native_performance
                else "performance counters unavailable"
            ),
        )
    )
    required_native_capabilities = (
        "gdi_capture",
        "multi_scale",
        "grayscale",
        "color",
        "abi_metadata",
        "bounded_job_pool",
        "preferred_scale_fallback",
        "preferred_scale_list",
        "explicit_scale_only",
        "low_res_scene_fingerprint",
        "dxgi_scene_change",
    )
    checks.append(
        DiagnosticCheck(
            "native_capabilities",
            bool(native_capabilities)
            and all(native_capabilities.get(name) for name in required_native_capabilities),
            f"mask=0x{native_capabilities.get('mask', 0):X}",
        )
    )
    checks.append(
        DiagnosticCheck(
            "native_abi",
            native.available
            and native_abi.get("compatible", False)
            and native_abi.get("pointer_bits") == 64,
            (
                f"pointer={native_abi.get('pointer_bits', 0)}, "
                f"structs={native_abi.get('struct_sizes', {})}"
            ),
        )
    )
    required_build_flags = ("x64", "static_crt", "cpp17", "windows10_target", "msvc")
    build_flags = native_abi.get("build_flags", {})
    checks.append(
        DiagnosticCheck(
            "native_build_flags",
            native.available
            and all(build_flags.get(name, False) for name in required_build_flags),
            f"mask=0x{int(build_flags.get('mask', 0)):X}",
        )
    )

    writable = False
    write_detail = base
    try:
        descriptor, probe = tempfile.mkstemp(prefix=".fukua_write_probe_", dir=base)
        os.close(descriptor)
        os.remove(probe)
        writable = True
    except OSError as error:
        write_detail = str(error)
    checks.append(DiagnosticCheck("runtime_directory_writable", writable, write_detail))

    if getattr(sys, "frozen", False):
        qt_platform = os.path.join(
            resource_root, "PySide6", "plugins", "platforms", "qwindows.dll"
        )
        checks.append(
            DiagnosticCheck("qt_windows_platform_plugin", os.path.isfile(qt_platform), qt_platform)
        )
        uia_bitmap_helper = os.path.join(
            resource_root,
            "uiautomation",
            "bin",
            "UIAutomationClient_VC140_X64.dll",
        )
        checks.append(
            DiagnosticCheck(
                "uia_bitmap_helper",
                os.path.isfile(uia_bitmap_helper),
                uia_bitmap_helper,
            )
        )

    return {
        "format": "fukuaRPA_runtime_diagnostics",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "application_version": APP_VERSION,
        "build_name": BUILD_NAME,
        "supported_windows": SUPPORTED_WINDOWS_TEXT,
        "base_dir": base,
        "frozen": bool(getattr(sys, "frozen", False)),
        "ok": all(check.ok for check in checks),
        "native_performance": native_performance,
        "opencv_threads": opencv_threads,
        "native_health": native.health_snapshot(),
        "checks": [asdict(check) for check in checks],
    }
