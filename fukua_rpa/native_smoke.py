"""Real-screen native/OpenCV parity smoke shared by source and frozen builds."""

from __future__ import annotations

import ctypes
import math
import os
import tempfile
import time
from contextlib import contextmanager
from ctypes import wintypes

import cv2
import mss
import numpy as np
from PIL import Image, ImageStat

from .constants import NATIVE_CORE_RELEASE_VERSION
from .opencv_runtime import configure_opencv_threads
from .paths import get_base_dir
from .vision import NativeVisionCore


WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
SW_SHOWNOACTIVATE = 4
PARITY_TOLERANCE_PIXELS = 3.0

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def _configure_win32() -> None:
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.FillRect.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.HANDLE,
    ]
    user32.FillRect.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.UpdateWindow.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
    gdi32.CreateSolidBrush.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL


def _module_handle():
    kernel32 = ctypes.windll.kernel32
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    return kernel32.GetModuleHandleW(None)


def _colorref(red, green, blue):
    return int(red) | (int(green) << 8) | (int(blue) << 16)


def _fill_rect(device_context, left, top, right, bottom, color) -> None:
    rect = wintypes.RECT(left, top, right, bottom)
    brush = gdi32.CreateSolidBrush(color)
    if not brush:
        raise RuntimeError("CreateSolidBrush failed")
    try:
        if not user32.FillRect(device_context, ctypes.byref(rect), brush):
            raise RuntimeError("FillRect failed")
    finally:
        gdi32.DeleteObject(brush)


def _draw_pattern(hwnd, size=128) -> None:
    device_context = user32.GetDC(hwnd)
    if not device_context:
        raise RuntimeError("GetDC failed")
    try:
        _fill_rect(
            device_context,
            0,
            0,
            size,
            size,
            _colorref(245, 245, 245),
        )
        cell = 16
        for row in range(size // cell):
            for column in range(size // cell):
                seed = row * 8 + column
                red = (37 * seed + 41) % 220 + 20
                green = (83 * seed + 17) % 220 + 20
                blue = (149 * seed + 67) % 220 + 20
                _fill_rect(
                    device_context,
                    column * cell,
                    row * cell,
                    (column + 1) * cell,
                    (row + 1) * cell,
                    _colorref(red, green, blue),
                )
        gdi32.GdiFlush()
    finally:
        user32.ReleaseDC(hwnd, device_context)


def _draw_change_marker(hwnd) -> None:
    device_context = user32.GetDC(hwnd)
    if not device_context:
        raise RuntimeError("GetDC failed")
    try:
        _fill_rect(
            device_context,
            4,
            4,
            20,
            20,
            _colorref(0, 0, 0),
        )
        gdi32.GdiFlush()
    finally:
        user32.ReleaseDC(hwnd, device_context)


@contextmanager
def _generated_pattern_window(x=160, y=140, size=128):
    _configure_win32()
    hwnd = user32.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        "STATIC",
        "fukuaRPA native smoke",
        WS_POPUP | WS_VISIBLE,
        x,
        y,
        size,
        size,
        None,
        None,
        _module_handle(),
        None,
    )
    if not hwnd:
        raise RuntimeError("Unable to create native smoke-test window")
    try:
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.UpdateWindow(hwnd)
        time.sleep(0.05)
        _draw_pattern(hwnd, size)
        try:
            ctypes.windll.dwmapi.DwmFlush()
        except Exception:
            pass
        time.sleep(0.05)
        yield hwnd, (x, y, size, size)
    finally:
        user32.DestroyWindow(hwnd)


def _capture_region(region):
    x, y, width, height = region
    with mss.MSS() as capture:
        shot = capture.grab(
            {"left": x, "top": y, "width": width, "height": height}
        )
        return Image.frombytes("RGB", shot.size, shot.rgb)


def _opencv_match(scene, template, region, use_gray):
    scene_array = np.asarray(scene)
    template_array = np.asarray(template)
    if use_gray:
        scene_array = cv2.cvtColor(scene_array, cv2.COLOR_RGB2GRAY)
        template_array = cv2.cvtColor(template_array, cv2.COLOR_RGB2GRAY)
    else:
        scene_array = cv2.cvtColor(scene_array, cv2.COLOR_RGB2BGR)
        template_array = cv2.cvtColor(template_array, cv2.COLOR_RGB2BGR)
    scores = cv2.matchTemplate(scene_array, template_array, cv2.TM_CCOEFF_NORMED)
    _minimum, maximum, _minimum_location, location = cv2.minMaxLoc(scores)
    x, y, _width, _height = region
    center = (
        float(x + location[0] + template.width / 2.0),
        float(y + location[1] + template.height / 2.0),
    )
    return center, float(maximum)


def _nearest_match(matches, point):
    if not matches:
        raise RuntimeError("Native core returned no matches")
    return min(
        matches,
        key=lambda item: math.hypot(item[0] - point[0], item[1] - point[1]),
    )


def _distance(first, second):
    return float(math.hypot(first[0] - second[0], first[1] - second[1]))


def run_native_smoke(base_dir=None) -> dict:
    """Exercise native matching modes and compare their coordinates with OpenCV."""

    started = time.perf_counter()
    core = NativeVisionCore(base_dir=os.path.abspath(base_dir or get_base_dir()))
    base_report = {
        "format": "fukuaRPA_native_smoke_v2",
        "api_version": core.version,
        "abi": core.abi_snapshot(),
    }
    try:
        if not core.available:
            raise RuntimeError(core.load_error)
        if core.version < NATIVE_CORE_RELEASE_VERSION:
            raise RuntimeError(
                f"Native core API {core.version} is older than release API "
                f"{NATIVE_CORE_RELEASE_VERSION}"
            )
        configure_opencv_threads(cv2)
        foreground_before = int(user32.GetForegroundWindow() or 0)
        with _generated_pattern_window() as (smoke_hwnd, window_region):
            scene = _capture_region(window_region)
            template_box = (32, 32, 80, 80)
            template = scene.crop(template_box)
            detail = float(ImageStat.Stat(template.convert("L")).stddev[0])
            if detail < 3.0:
                raise RuntimeError("Generated native smoke template lacks detail")
            expected = (
                window_region[0] + (template_box[0] + template_box[2]) / 2.0,
                window_region[1] + (template_box[1] + template_box[3]) / 2.0,
            )
            opencv_gray, opencv_gray_score = _opencv_match(
                scene, template, window_region, True
            )
            opencv_color, opencv_color_score = _opencv_match(
                scene, template, window_region, False
            )
            with tempfile.TemporaryDirectory() as temp_dir:
                template_path = os.path.join(temp_dir, "generated_template.png")
                template.save(template_path)
                core.reset_performance_stats()
                native_gray = core.find_template(
                    template_path,
                    [window_region],
                    1.0,
                    1.0,
                    0.05,
                    True,
                    0.9,
                )
                native_color = core.find_template(
                    template_path,
                    [window_region],
                    1.0,
                    1.0,
                    0.05,
                    False,
                    0.9,
                )
                native_multiscale = core.find_template(
                    template_path,
                    [window_region],
                    0.9,
                    1.1,
                    0.1,
                    True,
                    0.9,
                )
                native_single_thread = core.find_template(
                    template_path,
                    [window_region],
                    0.9,
                    1.1,
                    0.1,
                    True,
                    0.9,
                    parallel_mode="off",
                )
                native_forced_multi = core.find_template(
                    template_path,
                    [window_region],
                    0.9,
                    1.1,
                    0.1,
                    True,
                    0.9,
                    parallel_mode="force",
                )
                native_preferred = core.find_template(
                    template_path,
                    [window_region],
                    0.9,
                    1.1,
                    0.1,
                    True,
                    0.99,
                    preferred_scale=1.0,
                )
                native_preferred_fallback = core.find_template(
                    template_path,
                    [window_region],
                    0.9,
                    1.1,
                    0.1,
                    True,
                    0.999,
                    preferred_scale=0.9,
                )
                native_preferred_list = core.find_template(
                    template_path,
                    [window_region],
                    0.9,
                    1.1,
                    0.1,
                    True,
                    0.999,
                    preferred_scales=(0.9, 1.0),
                )
                native_explicit_hit = core.find_template(
                    template_path,
                    [window_region],
                    0.9,
                    1.1,
                    0.1,
                    True,
                    0.999,
                    preferred_scales=(1.0,),
                    explicit_scale_only=True,
                )
                native_explicit_miss = core.find_template(
                    template_path,
                    [window_region],
                    0.9,
                    1.1,
                    0.1,
                    True,
                    0.999,
                    preferred_scales=(0.9,),
                    explicit_scale_only=True,
                )
                native_all = core.find_template(
                    template_path,
                    [window_region],
                    1.0,
                    1.0,
                    0.05,
                    True,
                    0.9,
                    find_all=True,
                    max_matches=32,
                )
                excluded_region = (
                    window_region[0],
                    window_region[1],
                    24,
                    24,
                )
                target_region = (
                    window_region[0] + 24,
                    window_region[1] + 24,
                    80,
                    80,
                )
                excluded = core.find_template(
                    template_path,
                    [excluded_region],
                    1.0,
                    1.0,
                    0.05,
                    True,
                    0.9,
                )
                native_multi_region = core.find_template(
                    template_path,
                    [excluded_region, target_region],
                    1.0,
                    1.0,
                    0.05,
                    True,
                    0.9,
                )
                scene_fingerprint = core.capture_scene_signature(window_region)
                dxgi_baseline = core.poll_desktop_change(
                    [window_region], reset_baseline=True
                )
                _draw_change_marker(smoke_hwnd)
                try:
                    ctypes.windll.dwmapi.DwmFlush()
                except Exception:
                    pass
                dxgi_changed = False
                for _index in range(20):
                    detected = core.poll_desktop_change([window_region])
                    if detected is None:
                        break
                    if detected:
                        dxgi_changed = True
                        break
                    time.sleep(0.01)
        foreground_after = int(user32.GetForegroundWindow() or 0)

        gray_match = _nearest_match(native_gray, expected)
        color_match = _nearest_match(native_color, expected)
        multiscale_match = _nearest_match(native_multiscale, expected)
        single_thread_match = _nearest_match(native_single_thread, expected)
        forced_multi_match = _nearest_match(native_forced_multi, expected)
        preferred_match = _nearest_match(native_preferred, expected)
        preferred_fallback_match = _nearest_match(
            native_preferred_fallback, expected
        )
        preferred_list_match = _nearest_match(native_preferred_list, expected)
        explicit_match = _nearest_match(native_explicit_hit, expected)
        all_match = _nearest_match(native_all, expected)
        multi_region_match = _nearest_match(native_multi_region, expected)
        distances = {
            "native_gray_to_expected": _distance(gray_match, expected),
            "native_color_to_expected": _distance(color_match, expected),
            "native_multiscale_to_expected": _distance(multiscale_match, expected),
            "native_single_thread_to_expected": _distance(
                single_thread_match, expected
            ),
            "native_forced_multi_to_expected": _distance(
                forced_multi_match, expected
            ),
            "native_preferred_to_expected": _distance(preferred_match, expected),
            "native_preferred_fallback_to_expected": _distance(
                preferred_fallback_match, expected
            ),
            "native_preferred_list_to_expected": _distance(
                preferred_list_match, expected
            ),
            "native_explicit_to_expected": _distance(
                explicit_match, expected
            ),
            "native_all_to_expected": _distance(all_match, expected),
            "native_multi_region_to_expected": _distance(
                multi_region_match, expected
            ),
            "native_gray_to_opencv": _distance(gray_match, opencv_gray),
            "native_color_to_opencv": _distance(color_match, opencv_color),
        }
        within_tolerance = all(
            value <= PARITY_TOLERANCE_PIXELS for value in distances.values()
        )
        if excluded != []:
            raise RuntimeError(f"Excluded region did not return an authoritative miss: {excluded}")
        if abs(float(preferred_match[2]) - 1.0) > 1e-7:
            raise RuntimeError(
                f"Preferred scale did not win the fast path: {preferred_match[2]}"
            )
        if abs(float(preferred_fallback_match[2]) - 1.0) > 1e-7:
            raise RuntimeError(
                "Preferred-scale miss did not fall back to the complete range: "
                f"{preferred_fallback_match[2]}"
            )
        if abs(float(preferred_list_match[2]) - 1.0) > 1e-7:
            raise RuntimeError(
                f"Preferred scale list did not find the expected scale: {preferred_list_match[2]}"
            )
        if abs(float(explicit_match[2]) - 1.0) > 1e-7:
            raise RuntimeError(
                f"Explicit-scale search returned the wrong scale: {explicit_match[2]}"
            )
        if native_explicit_miss != []:
            raise RuntimeError(
                "Explicit-scale miss incorrectly fell back to another scale: "
                f"{native_explicit_miss}"
            )
        if not scene_fingerprint or not scene_fingerprint[2]:
            raise RuntimeError(
                f"Low-resolution scene fingerprint failed: {core.last_scene_error}"
            )
        if dxgi_baseline is None or not dxgi_changed:
            raise RuntimeError(
                f"DXGI scene-change smoke failed: {core.last_scene_error}"
            )
        if not within_tolerance:
            raise RuntimeError(f"Native/OpenCV parity drift: {distances}")
        smoke_became_foreground = foreground_after == int(smoke_hwnd)
        if smoke_became_foreground:
            raise RuntimeError(
                f"Smoke window became foreground: {foreground_before} -> {foreground_after}"
            )
        return {
            **base_report,
            "ok": True,
            "template_detail": round(detail, 3),
            "expected_center": [round(value, 3) for value in expected],
            "opencv": {
                "gray_score": round(opencv_gray_score, 6),
                "color_score": round(opencv_color_score, 6),
            },
            "native": {
                "gray_score": round(float(gray_match[3]), 6),
                "color_score": round(float(color_match[3]), 6),
                "multiscale_scale": round(float(multiscale_match[2]), 6),
                "single_thread_found": bool(native_single_thread),
                "forced_multi_found": bool(native_forced_multi),
                "preferred_scale": round(float(preferred_match[2]), 6),
                "preferred_fallback_scale": round(
                    float(preferred_fallback_match[2]), 6
                ),
                "preferred_list_scale": round(
                    float(preferred_list_match[2]), 6
                ),
                "explicit_scale": round(float(explicit_match[2]), 6),
                "explicit_miss_empty": native_explicit_miss == [],
                "all_match_count": len(native_all),
                "excluded_region_empty": excluded == [],
                "multi_region_found": bool(native_multi_region),
                "scene_fingerprint_size": list(scene_fingerprint[:2]),
                "dxgi_change_detected": bool(dxgi_changed),
            },
            "parity": {
                "tolerance_pixels": PARITY_TOLERANCE_PIXELS,
                "distances": {
                    name: round(value, 3) for name, value in distances.items()
                },
                "within_tolerance": True,
            },
            "foreground_unchanged": foreground_before == foreground_after,
            "smoke_window_never_foreground": True,
            "opencv_threads": int(cv2.getNumThreads()),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "native_stats": core.performance_stats(),
            "error": "",
        }
    except Exception as error:
        return {
            **base_report,
            "ok": False,
            "parity": {"within_tolerance": False},
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "native_stats": core.performance_stats() if core.available else {},
            "error": str(error),
        }
