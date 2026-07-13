"""Template validation, cache estimation, and optional native matching adapter."""

import ctypes
import math
import os
import sys

from PIL import Image, ImageStat

from .constants import (
    MAX_SCALES_PER_TEMPLATE,
    MAX_TEMPLATE_SOURCE_PIXELS,
    NATIVE_CORE_DLL_NAME,
    NATIVE_CORE_MAX_VERSION,
    NATIVE_CORE_MIN_VERSION,
)
from .paths import get_base_dir


NATIVE_CAPABILITY_BITS = {
    "gdi_capture": 1 << 0,
    "multi_region": 1 << 1,
    "multi_scale": 1 << 2,
    "grayscale": 1 << 3,
    "color": 1 << 4,
    "find_all": 1 << 5,
    "template_lru": 1 << 6,
    "performance_counters": 1 << 7,
    "work_budget": 1 << 8,
    "single_capture_per_region": 1 << 9,
    "abi_metadata": 1 << 10,
    "bounded_job_pool": 1 << 11,
    "preferred_scale_fallback": 1 << 12,
    "preferred_scale_list": 1 << 13,
    "explicit_scale_only": 1 << 14,
    "low_res_scene_fingerprint": 1 << 15,
    "dxgi_scene_change": 1 << 16,
}
NATIVE_BUILD_FLAG_BITS = {
    "x64": 1 << 0,
    "static_crt": 1 << 1,
    "cpp17": 1 << 2,
    "windows10_target": 1 << 3,
    "msvc": 1 << 4,
}
NATIVE_STRUCT_IDS = {"rect": 1, "match": 2, "performance": 3}
NATIVE_RESULT_WORK_BUDGET = -2
NATIVE_PARALLEL_MODES = {"off": 0, "auto": 1, "force": 2}


def build_scale_values(min_scale, max_scale, scale_step, max_count=MAX_SCALES_PER_TEMPLATE):
    """Return extra scale variants; the original 1.0 template is searched separately."""
    min_scale = float(min_scale)
    max_scale = float(max_scale)
    scale_step = float(scale_step)
    if not all(math.isfinite(value) for value in (min_scale, max_scale, scale_step)):
        raise ValueError("缩放参数必须是有限数字")
    if min_scale <= 0 or max_scale <= 0:
        raise ValueError("缩放范围必须大于 0")
    if max_scale < min_scale:
        raise ValueError("最大缩放不能小于最小缩放")
    if scale_step <= 0:
        raise ValueError("缩放步长必须大于 0")

    values = []
    scale = min_scale
    guard = 0
    while scale <= max_scale + scale_step * 0.25:
        if not 0.99 < scale < 1.01:
            values.append(float(round(scale, 8)))
        guard += 1
        if 1 + len(values) > max_count or guard > max_count * 2:
            raise ValueError(f"单张图片最多允许 {max_count} 个缩放档位（包含原始 1.0 倍）")
        scale = min_scale + guard * scale_step
    return values


def template_detail_status(image_path, use_gray=True, min_stddev=1.0):
    """Reject tiny or flat templates that make normalized correlation unsafe."""
    try:
        with Image.open(image_path) as source:
            width, height = source.size
            if width < 3 or height < 3:
                return False, "模板尺寸至少需要 3×3 像素"
            if width * height > MAX_TEMPLATE_SOURCE_PIXELS:
                return False, f"模板像素过多，最多允许 {MAX_TEMPLATE_SOURCE_PIXELS:,} 像素"
            sample = source.convert("L" if use_gray else "RGB")
            sample.thumbnail((512, 512))
            standard_deviation = ImageStat.Stat(sample).stddev
            detail = max(float(value) for value in standard_deviation) if standard_deviation else 0.0
            if not math.isfinite(detail) or detail < float(min_stddev):
                return False, "图片几乎是纯色或缺少纹理，无法安全识别；请扩大截图并包含更多独特细节"
            return True, ""
    except Exception as error:
        return False, f"无法读取模板图片：{error}"


def estimate_template_cache_bytes(image_path, use_gray, scale_values):
    try:
        with Image.open(image_path) as source:
            width, height = source.size
    except Exception as error:
        raise ValueError(f"无法读取模板图片：{error}") from error
    if width * height > MAX_TEMPLATE_SOURCE_PIXELS:
        raise ValueError(f"模板像素过多，最多允许 {MAX_TEMPLATE_SOURCE_PIXELS:,} 像素")
    channels = 1 if use_gray else 3
    estimated = width * height * channels
    for scale in scale_values:
        estimated += max(1, int(round(width * scale))) * max(1, int(round(height * scale))) * channels
    return int(estimated)


class NativeRect(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("w", ctypes.c_int),
        ("h", ctypes.c_int),
    ]


class NativeMatch(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("scale", ctypes.c_double),
        ("score", ctypes.c_double),
        ("radius", ctypes.c_double),
    ]


class NativePerfStats(ctypes.Structure):
    _fields_ = [
        ("calls", ctypes.c_int64),
        ("captures", ctypes.c_int64),
        ("integral_builds", ctypes.c_int64),
        ("template_cache_hits", ctypes.c_int64),
        ("template_cache_misses", ctypes.c_int64),
        ("template_variants_built", ctypes.c_int64),
        ("work_budget_fallbacks", ctypes.c_int64),
        ("capture_microseconds", ctypes.c_int64),
        ("template_microseconds", ctypes.c_int64),
        ("match_microseconds", ctypes.c_int64),
        ("cache_bytes", ctypes.c_int64),
        ("cache_entries", ctypes.c_int64),
    ]


class NativeVisionCore:
    def __init__(self, base_dir=None):
        self.base_dir = os.path.abspath(base_dir or get_base_dir())
        self.dll = None
        self.available = False
        self.load_error = ""
        self.version = 0
        self.capability_mask = 0
        self.abi_bits = 0
        self.build_flag_mask = 0
        self.native_struct_sizes = {}
        self.has_extended_search = False
        self.has_preferred_scale_list = False
        self.has_explicit_scale_only = False
        self.has_scene_fingerprint = False
        self.has_dxgi_scene_change = False
        self.dxgi_scene_usable = True
        self.dll_path = ""
        self.last_result_code = 0
        self.last_scene_error = ""
        self._load()

    def _candidate_paths(self):
        bases = [self.base_dir]
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            bases.append(sys._MEIPASS)
        bases.append(os.path.join(self.base_dir, "native_core"))
        for base in bases:
            yield os.path.join(base, NATIVE_CORE_DLL_NAME)

    def _load(self):
        last_error = ""
        for dll_path in self._candidate_paths():
            if not os.path.exists(dll_path):
                continue
            try:
                dll = ctypes.CDLL(dll_path)
                dll.wrpa_version.argtypes = []
                dll.wrpa_version.restype = ctypes.c_int
                dll.wrpa_find_template.argtypes = [
                    ctypes.POINTER(ctypes.c_wchar),
                    ctypes.POINTER(NativeRect),
                    ctypes.c_int,
                    ctypes.c_double,
                    ctypes.c_double,
                    ctypes.c_double,
                    ctypes.c_int,
                    ctypes.c_double,
                    ctypes.c_int,
                    ctypes.POINTER(NativeMatch),
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.c_wchar_p,
                    ctypes.c_int,
                ]
                dll.wrpa_find_template.restype = ctypes.c_int
                self.version = int(dll.wrpa_version())
                if not NATIVE_CORE_MIN_VERSION <= self.version <= NATIVE_CORE_MAX_VERSION:
                    raise RuntimeError(
                        f"DLL接口版本不兼容：{self.version}，"
                        f"需要 {NATIVE_CORE_MIN_VERSION}-{NATIVE_CORE_MAX_VERSION}"
                    )
                if hasattr(dll, "wrpa_capabilities"):
                    dll.wrpa_capabilities.argtypes = []
                    dll.wrpa_capabilities.restype = ctypes.c_uint64
                    self.capability_mask = int(dll.wrpa_capabilities())
                else:
                    self.capability_mask = self._legacy_capability_mask()
                if self.version >= 10700 and not (
                    self.capability_mask & NATIVE_CAPABILITY_BITS["abi_metadata"]
                ):
                    raise RuntimeError("DLL API 10700+ 未声明 ABI 元数据能力")
                if hasattr(dll, "wrpa_find_template_ex"):
                    dll.wrpa_find_template_ex.argtypes = [
                        ctypes.POINTER(ctypes.c_wchar),
                        ctypes.POINTER(NativeRect),
                        ctypes.c_int,
                        ctypes.c_double,
                        ctypes.c_double,
                        ctypes.c_double,
                        ctypes.c_int,
                        ctypes.c_double,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_double,
                        ctypes.POINTER(NativeMatch),
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_int),
                        ctypes.c_wchar_p,
                        ctypes.c_int,
                    ]
                    dll.wrpa_find_template_ex.restype = ctypes.c_int
                    self.has_extended_search = True
                if hasattr(dll, "wrpa_find_template_ex2"):
                    dll.wrpa_find_template_ex2.argtypes = [
                        ctypes.POINTER(ctypes.c_wchar),
                        ctypes.POINTER(NativeRect),
                        ctypes.c_int,
                        ctypes.c_double,
                        ctypes.c_double,
                        ctypes.c_double,
                        ctypes.c_int,
                        ctypes.c_double,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_double),
                        ctypes.c_int,
                        ctypes.POINTER(NativeMatch),
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_int),
                        ctypes.c_wchar_p,
                        ctypes.c_int,
                    ]
                    dll.wrpa_find_template_ex2.restype = ctypes.c_int
                    self.has_preferred_scale_list = True
                if hasattr(dll, "wrpa_find_template_ex3"):
                    dll.wrpa_find_template_ex3.argtypes = [
                        ctypes.POINTER(ctypes.c_wchar),
                        ctypes.POINTER(NativeRect),
                        ctypes.c_int,
                        ctypes.c_double,
                        ctypes.c_double,
                        ctypes.c_double,
                        ctypes.c_int,
                        ctypes.c_double,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_double),
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.POINTER(NativeMatch),
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_int),
                        ctypes.c_wchar_p,
                        ctypes.c_int,
                    ]
                    dll.wrpa_find_template_ex3.restype = ctypes.c_int
                    self.has_explicit_scale_only = True
                if hasattr(dll, "wrpa_capture_gray_fingerprint"):
                    dll.wrpa_capture_gray_fingerprint.argtypes = [
                        ctypes.POINTER(NativeRect),
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_ubyte),
                        ctypes.c_int,
                        ctypes.c_wchar_p,
                        ctypes.c_int,
                    ]
                    dll.wrpa_capture_gray_fingerprint.restype = ctypes.c_int
                    self.has_scene_fingerprint = True
                if hasattr(dll, "wrpa_poll_desktop_change"):
                    dll.wrpa_poll_desktop_change.argtypes = [
                        ctypes.POINTER(NativeRect),
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_wchar_p,
                        ctypes.c_int,
                    ]
                    dll.wrpa_poll_desktop_change.restype = ctypes.c_int
                    self.has_dxgi_scene_change = True
                if self.version >= 10800:
                    required = (
                        NATIVE_CAPABILITY_BITS["bounded_job_pool"]
                        | NATIVE_CAPABILITY_BITS["preferred_scale_fallback"]
                    )
                    if self.capability_mask & required != required:
                        raise RuntimeError("DLL API 10800+ 未声明多核调度或缩放回退能力")
                    if not self.has_extended_search:
                        raise RuntimeError("DLL API 10800+ 缺少扩展识别接口")
                if self.version >= 10900:
                    if not (
                        self.capability_mask
                        & NATIVE_CAPABILITY_BITS["preferred_scale_list"]
                    ):
                        raise RuntimeError("DLL API 10900+ 未声明多倍率优先能力")
                    if not self.has_preferred_scale_list:
                        raise RuntimeError("DLL API 10900+ 缺少多倍率扩展识别接口")
                if self.version >= 11000:
                    if not (
                        self.capability_mask
                        & NATIVE_CAPABILITY_BITS["explicit_scale_only"]
                    ):
                        raise RuntimeError("DLL API 11000+ 未声明指定倍率专搜能力")
                    if not self.has_explicit_scale_only:
                        raise RuntimeError("DLL API 11000+ 缺少指定倍率专搜接口")
                if self.version >= 11100:
                    if not (
                        self.capability_mask
                        & NATIVE_CAPABILITY_BITS["low_res_scene_fingerprint"]
                    ):
                        raise RuntimeError("DLL API 11100+ 未声明低分辨率画面指纹能力")
                    if not self.has_scene_fingerprint:
                        raise RuntimeError("DLL API 11100+ 缺少低分辨率画面指纹接口")
                if self.version >= 11200:
                    if not (
                        self.capability_mask
                        & NATIVE_CAPABILITY_BITS["dxgi_scene_change"]
                    ):
                        raise RuntimeError("DLL API 11200+ 未声明 DXGI 画面变化能力")
                    if not self.has_dxgi_scene_change:
                        raise RuntimeError("DLL API 11200+ 缺少 DXGI 画面变化接口")
                self._load_abi_metadata(dll)
                if hasattr(dll, "wrpa_get_perf_stats"):
                    dll.wrpa_get_perf_stats.argtypes = [
                        ctypes.POINTER(NativePerfStats)
                    ]
                    dll.wrpa_get_perf_stats.restype = ctypes.c_int
                if hasattr(dll, "wrpa_reset_perf_stats"):
                    dll.wrpa_reset_perf_stats.argtypes = []
                    dll.wrpa_reset_perf_stats.restype = None
                self.dll = dll
                self.dll_path = os.path.abspath(dll_path)
                self.available = True
                self.load_error = ""
                return
            except Exception as error:
                last_error = f"{dll_path}: {error}"
                self.dll = None
                self.available = False
                self.version = 0
                self.capability_mask = 0
                self.abi_bits = 0
                self.build_flag_mask = 0
                self.native_struct_sizes = {}
                self.has_extended_search = False
                self.has_preferred_scale_list = False
                self.has_explicit_scale_only = False
                self.has_scene_fingerprint = False
                self.has_dxgi_scene_change = False
                self.dxgi_scene_usable = True
                self.dll_path = ""
        self.load_error = last_error or f"{NATIVE_CORE_DLL_NAME} not found"

    def _load_abi_metadata(self, dll):
        names = ("wrpa_abi_bits", "wrpa_struct_size", "wrpa_build_flags")
        missing = [name for name in names if not hasattr(dll, name)]
        if missing:
            if self.version >= 10700:
                raise RuntimeError(f"DLL 缺少 ABI 元数据接口：{', '.join(missing)}")
            self.abi_bits = 0
            self.build_flag_mask = 0
            self.native_struct_sizes = {}
            return
        dll.wrpa_abi_bits.argtypes = []
        dll.wrpa_abi_bits.restype = ctypes.c_int
        dll.wrpa_struct_size.argtypes = [ctypes.c_int]
        dll.wrpa_struct_size.restype = ctypes.c_int
        dll.wrpa_build_flags.argtypes = []
        dll.wrpa_build_flags.restype = ctypes.c_uint64
        self.abi_bits = int(dll.wrpa_abi_bits())
        self.build_flag_mask = int(dll.wrpa_build_flags())
        self.native_struct_sizes = {
            name: int(dll.wrpa_struct_size(struct_id))
            for name, struct_id in NATIVE_STRUCT_IDS.items()
        }
        expected_bits = ctypes.sizeof(ctypes.c_void_p) * 8
        expected_sizes = self._expected_struct_sizes()
        if self.abi_bits != expected_bits:
            raise RuntimeError(
                f"DLL 位数不兼容：native={self.abi_bits}, python={expected_bits}"
            )
        mismatches = {
            name: (self.native_struct_sizes.get(name, 0), expected)
            for name, expected in expected_sizes.items()
            if self.native_struct_sizes.get(name, 0) != expected
        }
        if mismatches:
            raise RuntimeError(f"DLL 结构体布局不兼容：{mismatches}")

    @staticmethod
    def _expected_struct_sizes():
        return {
            "rect": ctypes.sizeof(NativeRect),
            "match": ctypes.sizeof(NativeMatch),
            "performance": ctypes.sizeof(NativePerfStats),
        }

    def find_template(
        self,
        image_path,
        regions,
        min_scale,
        max_scale,
        scale_step,
        use_gray,
        threshold,
        find_all=False,
        max_matches=512,
        parallel_mode="auto",
        preferred_scale=None,
        preferred_scales=None,
        explicit_scale_only=False,
    ):
        if not self.available or not self.dll:
            return None
        try:
            clean_regions = []
            for region in regions or []:
                x, y, width, height = [int(float(value)) for value in region]
                if width > 0 and height > 0:
                    clean_regions.append((x, y, width, height))
            rect_array = None
            rect_ptr = None
            if clean_regions:
                rect_array = (NativeRect * len(clean_regions))()
                for index, (x, y, width, height) in enumerate(clean_regions):
                    rect_array[index] = NativeRect(x, y, width, height)
                rect_ptr = rect_array

            max_matches = max(1, min(int(max_matches), 4096))
            out_array = (NativeMatch * max_matches)()
            out_count = ctypes.c_int(0)
            error_buffer = ctypes.create_unicode_buffer(512)
            mode_id = NATIVE_PARALLEL_MODES.get(
                str(parallel_mode or "auto").strip().lower(), 1
            )
            try:
                preferred = float(preferred_scale)
            except (TypeError, ValueError):
                preferred = 0.0
            if find_all or not math.isfinite(preferred) or preferred <= 0.0:
                preferred = 0.0
            clean_preferred = []
            for value in preferred_scales or ():
                try:
                    scale = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(scale) and scale > 0.0 and scale not in clean_preferred:
                    clean_preferred.append(scale)
                if len(clean_preferred) >= 16:
                    break
            if preferred > 0.0 and preferred not in clean_preferred:
                clean_preferred.insert(0, preferred)
            if find_all:
                clean_preferred = []
            explicit_scale_only = bool(explicit_scale_only) and not find_all
            if explicit_scale_only and not clean_preferred:
                self.last_result_code = 0
                self.load_error = ""
                return []
            if explicit_scale_only and not self.has_explicit_scale_only:
                self.last_result_code = 0
                self.load_error = "native explicit-scale search unavailable"
                return None
            preferred_array = None
            preferred_ptr = None
            if clean_preferred:
                preferred_array = (ctypes.c_double * len(clean_preferred))(
                    *clean_preferred
                )
                preferred_ptr = preferred_array

            common_args = (
                os.path.abspath(str(image_path)),
                rect_ptr,
                len(clean_regions),
                float(min_scale),
                float(max_scale),
                float(scale_step),
                1 if use_gray else 0,
                float(threshold),
                1 if find_all else 0,
            )
            if explicit_scale_only:
                result_code = self.dll.wrpa_find_template_ex3(
                    *common_args,
                    mode_id,
                    preferred_ptr,
                    len(clean_preferred),
                    1,
                    out_array,
                    max_matches,
                    ctypes.byref(out_count),
                    error_buffer,
                    len(error_buffer),
                )
            elif self.has_preferred_scale_list:
                result_code = self.dll.wrpa_find_template_ex2(
                    *common_args,
                    mode_id,
                    preferred_ptr,
                    len(clean_preferred),
                    out_array,
                    max_matches,
                    ctypes.byref(out_count),
                    error_buffer,
                    len(error_buffer),
                )
            elif self.has_extended_search:
                result_code = self.dll.wrpa_find_template_ex(
                    *common_args,
                    mode_id,
                    clean_preferred[0] if clean_preferred else 0.0,
                    out_array,
                    max_matches,
                    ctypes.byref(out_count),
                    error_buffer,
                    len(error_buffer),
                )
            else:
                result_code = self.dll.wrpa_find_template(
                    *common_args,
                    out_array,
                    max_matches,
                    ctypes.byref(out_count),
                    error_buffer,
                    len(error_buffer),
                )
            self.last_result_code = int(result_code)
            if result_code < 0:
                self.load_error = error_buffer.value or f"native rc {result_code}"
                return None
            self.load_error = ""
            result = []
            for index in range(max(0, min(out_count.value, max_matches))):
                item = out_array[index]
                result.append((
                    float(item.x),
                    float(item.y),
                    float(item.scale),
                    float(item.score),
                    float(item.radius),
                ))
            return result
        except Exception as error:
            self.last_result_code = -999
            self.load_error = str(error)
            return None

    def _legacy_capability_mask(self):
        names = {
            "gdi_capture",
            "multi_region",
            "multi_scale",
            "grayscale",
            "color",
            "find_all",
        }
        if self.version >= 10500:
            names.update(
                {
                    "template_lru",
                    "performance_counters",
                    "work_budget",
                    "single_capture_per_region",
                }
            )
        return sum(NATIVE_CAPABILITY_BITS[name] for name in names)

    def capture_scene_signature(
        self,
        region,
        *,
        max_width=160,
        max_height=96,
    ):
        """Capture a downscaled grayscale region without copying a full frame."""
        if (
            not self.available
            or not self.dll
            or not self.has_scene_fingerprint
        ):
            return None
        try:
            x, y, width, height = [int(float(value)) for value in region]
            if width <= 0 or height <= 0:
                return None
            scale = min(
                1.0,
                max(8, int(max_width)) / width,
                max(8, int(max_height)) / height,
            )
            target_width = max(1, int(round(width * scale)))
            target_height = max(1, int(round(height * scale)))
            rect = NativeRect(x, y, width, height)
            capacity = target_width * target_height
            out_pixels = (ctypes.c_ubyte * capacity)()
            error_buffer = ctypes.create_unicode_buffer(512)
            result_code = self.dll.wrpa_capture_gray_fingerprint(
                ctypes.byref(rect),
                target_width,
                target_height,
                out_pixels,
                capacity,
                error_buffer,
                len(error_buffer),
            )
            if int(result_code) <= 0:
                self.last_scene_error = (
                    error_buffer.value or f"native scene rc {result_code}"
                )
                return None
            self.last_scene_error = ""
            return target_width, target_height, bytes(out_pixels)
        except Exception as error:
            self.last_scene_error = str(error)
            return None

    def poll_desktop_change(self, regions=None, *, reset_baseline=False):
        """Poll DXGI dirty rectangles; None requests the fingerprint fallback."""
        if (
            not self.available
            or not self.dll
            or not self.has_dxgi_scene_change
            or not self.dxgi_scene_usable
        ):
            return None
        try:
            clean_regions = []
            for region in regions or ():
                x, y, width, height = [int(float(value)) for value in region]
                if width > 0 and height > 0:
                    clean_regions.append((x, y, width, height))
            rect_array = None
            rect_ptr = None
            if clean_regions:
                rect_array = (NativeRect * len(clean_regions))()
                for index, values in enumerate(clean_regions):
                    rect_array[index] = NativeRect(*values)
                rect_ptr = rect_array
            error_buffer = ctypes.create_unicode_buffer(512)
            result_code = self.dll.wrpa_poll_desktop_change(
                rect_ptr,
                len(clean_regions),
                1 if reset_baseline else 0,
                error_buffer,
                len(error_buffer),
            )
            if int(result_code) < 0:
                self.last_scene_error = (
                    error_buffer.value or f"native DXGI rc {result_code}"
                )
                self.dxgi_scene_usable = False
                return None
            self.last_scene_error = ""
            return bool(result_code)
        except Exception as error:
            self.last_scene_error = str(error)
            self.dxgi_scene_usable = False
            return None

    def capabilities(self):
        return {
            "mask": int(self.capability_mask),
            **{
                name: bool(self.capability_mask & bit)
                for name, bit in NATIVE_CAPABILITY_BITS.items()
            },
        }

    def build_flags(self):
        return {
            "mask": int(self.build_flag_mask),
            **{
                name: bool(self.build_flag_mask & bit)
                for name, bit in NATIVE_BUILD_FLAG_BITS.items()
            },
        }

    def abi_snapshot(self):
        expected_bits = ctypes.sizeof(ctypes.c_void_p) * 8
        expected_sizes = self._expected_struct_sizes()
        metadata_available = bool(
            self.abi_bits and self.native_struct_sizes and self.build_flag_mask
        )
        return {
            "metadata_available": metadata_available,
            "compatible": bool(
                metadata_available
                and self.abi_bits == expected_bits
                and self.native_struct_sizes == expected_sizes
            ),
            "pointer_bits": int(self.abi_bits),
            "python_pointer_bits": expected_bits,
            "struct_sizes": dict(self.native_struct_sizes),
            "python_struct_sizes": expected_sizes,
            "build_flags": self.build_flags(),
        }

    def health_snapshot(self):
        return {
            "available": bool(self.available),
            "api_version": int(self.version),
            "dll_path": str(self.dll_path),
            "capabilities": self.capabilities(),
            "abi": self.abi_snapshot(),
            "last_result_code": int(self.last_result_code),
            "last_error": str(self.load_error or ""),
            "scene_error": str(self.last_scene_error or ""),
            "dxgi_scene_usable": bool(self.dxgi_scene_usable),
        }

    def reset_performance_stats(self):
        """Reset optional DLL counters; older compatible DLLs simply have none."""
        function = getattr(self.dll, "wrpa_reset_perf_stats", None) if self.dll else None
        if function is None:
            return False
        try:
            function.argtypes = []
            function.restype = None
            function()
            return True
        except Exception:
            return False

    def performance_stats(self):
        """Return optional native telemetry without making it an API requirement."""
        function = getattr(self.dll, "wrpa_get_perf_stats", None) if self.dll else None
        if function is None:
            return {}
        try:
            stats = NativePerfStats()
            if int(function(ctypes.byref(stats))) != 0:
                return {}
            return {
                "calls": int(stats.calls),
                "captures": int(stats.captures),
                "integral_builds": int(stats.integral_builds),
                "template_cache_hits": int(stats.template_cache_hits),
                "template_cache_misses": int(stats.template_cache_misses),
                "template_variants_built": int(stats.template_variants_built),
                "work_budget_fallbacks": int(stats.work_budget_fallbacks),
                "capture_ms": round(stats.capture_microseconds / 1000.0, 3),
                "template_ms": round(stats.template_microseconds / 1000.0, 3),
                "match_ms": round(stats.match_microseconds / 1000.0, 3),
                "cache_bytes": int(stats.cache_bytes),
                "cache_entries": int(stats.cache_entries),
            }
        except Exception:
            return {}
