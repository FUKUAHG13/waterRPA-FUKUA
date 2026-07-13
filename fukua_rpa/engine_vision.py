"""Screenshot, template preprocessing and target matching implementation."""

import os
import random
import time

from PIL import Image

try:
    import mss
    HAS_MSS = True
except ImportError:
    mss = None
    HAS_MSS = False

from .constants import (
    MAX_SINGLE_TEMPLATE_CACHE_BYTES,
    MAX_TEMPLATE_CACHE_BYTES,
    MAX_TEMPLATE_SOURCE_PIXELS,
    TASK_TYPE_UNTIL,
)
from .logging_service import write_log
from .log_policy import (
    LOG_ADAPTIVE,
    LOG_BACKEND,
    LOG_CRITICAL,
    LOG_RECOGNITION,
)
from .pyautogui_runtime import pyautogui
from .task_model import config_bool, parse_region_text
from .scale_memory import ScaleMemoryPolicy
from .scene_wake import (
    SceneSignature,
    compare_scene_sets,
    make_scene_signature,
    normalize_sensitivity,
)
from .vision import (
    NATIVE_RESULT_WORK_BUDGET,
    build_scale_values,
    estimate_template_cache_bytes,
    template_detail_status,
)

class VisionExecutionMixin:
    def create_mss_instance(self):
        factory = getattr(mss, "MSS", None) or mss.mss
        return factory()

    def recognition_key(self, img_path, step_info):
        step = step_info.get("step", 0) if step_info else 0
        return (step, os.path.abspath(str(img_path)))

    def record_recognition_miss(self, img_path, step_info):
        key = self.recognition_key(img_path, step_info)
        self.miss_streaks[key] = self.miss_streaks.get(key, 0) + 1
        return self.miss_streaks[key]

    def reset_recognition_miss(self, img_path, step_info):
        self.miss_streaks.pop(self.recognition_key(img_path, step_info), None)

    def adaptive_extra_delay(self, img_path, step_info):
        if not self.adaptive_backoff:
            return 0.0
        miss_count = self.miss_streaks.get(self.recognition_key(img_path, step_info), 0)
        if miss_count < 3:
            return 0.0
        return min(0.8, 0.05 * (miss_count - 2))

    def as_bool(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "启用", "是")
        return bool(value)

    def normalized_regions(self, regions):
        result = []
        for region in regions or []:
            try:
                x, y, w, h = [int(float(v)) for v in region]
                if w > 0 and h > 0:
                    result.append((x, y, w, h))
            except Exception:
                continue
        return result

    def capture_screenshot(self, region=None):
        total_started_ns = time.perf_counter_ns()
        try:
            if (
                self.use_fast_screenshot
                and HAS_MSS
                and not getattr(self, "_mss_disabled_for_run", False)
            ):
                backend_started_ns = time.perf_counter_ns()
                try:
                    if self._mss_instance is None:
                        self._mss_instance = self.create_mss_instance()
                    if region:
                        x, y, w, h = [int(v) for v in region]
                        monitor = {"left": x, "top": y, "width": w, "height": h}
                        offset_x, offset_y = x, y
                    else:
                        monitor = self._mss_instance.monitors[0]
                        offset_x = int(monitor.get("left", 0))
                        offset_y = int(monitor.get("top", 0))
                    shot = self._mss_instance.grab(monitor)
                    image = Image.frombytes("RGB", shot.size, shot.rgb)
                    self.performance.observe_since("screenshot.mss", backend_started_ns)
                    self.performance.increment("screenshot.mss_calls")
                    self.performance.increment("screenshot.pixels", image.width * image.height)
                    return image, offset_x, offset_y
                except Exception as error:
                    self.performance.observe_since("screenshot.mss_failed", backend_started_ns)
                    self.performance.increment("screenshot.mss_failures")
                    self.performance.increment("screenshot.fallbacks")
                    self._mss_disabled_for_run = True
                    if self.verbose_log_enabled(LOG_BACKEND) and not self._mss_failure_logged:
                        self._mss_failure_logged = True
                        self.log(
                            "<font color='orange'>    [截图] mss快速截图失败，"
                            f"本次运行将持续回退到pyautogui: {error}</font>",
                            LOG_BACKEND,
                        )
                    self.close_screenshot_backend()

            backend_started_ns = time.perf_counter_ns()
            screenshot_pil = pyautogui.screenshot(region=region)
            self.performance.observe_since("screenshot.pyautogui", backend_started_ns)
            self.performance.increment("screenshot.pyautogui_calls")
            self.performance.increment(
                "screenshot.pixels", screenshot_pil.width * screenshot_pil.height
            )
            offset_x = region[0] if region else 0
            offset_y = region[1] if region else 0
            return screenshot_pil, offset_x, offset_y
        finally:
            self.performance.observe_since("screenshot.total", total_started_ns)

    def region_bounding_rect(self, regions):
        left = min(r[0] for r in regions)
        top = min(r[1] for r in regions)
        right = max(r[0] + r[2] for r in regions)
        bottom = max(r[1] + r[3] for r in regions)
        return (left, top, right - left, bottom - top)

    def screen_bounds(self):
        if HAS_MSS and not getattr(self, "_mss_disabled_for_run", False):
            try:
                if self._mss_instance is None:
                    self._mss_instance = self.create_mss_instance()
                monitor = self._mss_instance.monitors[0]
                return (int(monitor.get("left", 0)), int(monitor.get("top", 0)), int(monitor["width"]), int(monitor["height"]))
            except Exception:
                self.performance.increment("screenshot.mss_bounds_failures")
                self._mss_disabled_for_run = True
                self.close_screenshot_backend()
        w, h = pyautogui.size()
        return (0, 0, int(w), int(h))

    def clip_region_to_bounds(self, region, bounds):
        x, y, w, h = [int(v) for v in region]
        bx, by, bw, bh = [int(v) for v in bounds]
        left = max(x, bx)
        top = max(y, by)
        right = min(x + w, bx + bw)
        bottom = min(y + h, by + bh)
        if right <= left or bottom <= top:
            return None
        return (left, top, right - left, bottom - top)

    def should_batch_regions(self, regions):
        if len(regions) < 2:
            return False
        total_area = sum(w * h for _x, _y, w, h in regions)
        _bx, _by, bw, bh = self.region_bounding_rect(regions)
        bbox_area = bw * bh
        return bbox_area <= max(total_area * 3, total_area + 50000)

    def effective_search_regions(self, search_regions=None):
        explicit_regions = self.normalized_regions(search_regions)
        if explicit_regions:
            return explicit_regions
        active_regions = self.normalized_regions(getattr(self, "scan_regions", []))
        if active_regions:
            return active_regions
        if self.scan_region:
            return self.normalized_regions([self.scan_region])
        return []

    def iter_search_screenshots(self, search_regions=None):
        active_regions = self.effective_search_regions(search_regions)
        if not active_regions:
            yield self.capture_screenshot(None)
            return

        if self.should_batch_regions(active_regions):
            bbox = self.region_bounding_rect(active_regions)
            try:
                screenshot_pil, offset_x, offset_y = self.capture_screenshot(bbox)
                for x, y, w, h in active_regions:
                    crop_started_ns = time.perf_counter_ns()
                    crop_box = (x - offset_x, y - offset_y, x - offset_x + w, y - offset_y + h)
                    cropped = screenshot_pil.crop(crop_box)
                    self.performance.observe_since("screenshot.region_crop", crop_started_ns)
                    self.performance.increment("screenshot.region_crops")
                    yield cropped, x, y
                return
            except Exception as e:
                if self.verbose_log_enabled(LOG_BACKEND):
                    self.log(f"<font color='orange'>    [截图] 多区域合并截图失败，改为逐区域截图: {e}</font>", LOG_BACKEND)

        for region in active_regions:
            if self.check_stop_flag():
                return
            yield self.capture_screenshot(region)

    def target_position_key(self, img_path, cache_key, task_conf, use_gray):
        return (os.path.abspath(str(img_path)), str(cache_key), float(task_conf), bool(use_gray))

    def scale_memory_policy(self):
        return ScaleMemoryPolicy(
            enabled=bool(getattr(self, "use_native_scale_hint", True)),
            tier=str(getattr(self, "scale_memory_tier", "balanced")),
            manual_scales=tuple(getattr(self, "scale_memory_manual", ()) or ()),
            custom_enabled=bool(
                getattr(self, "scale_memory_custom_enabled", False)
            ),
            preferred_limit=int(
                getattr(self, "scale_memory_preferred_limit", 3)
            ),
            history_limit=int(
                getattr(self, "scale_memory_history_limit", 64)
            ),
        ).normalized()

    def scale_memory_context(self, img_path, cache_key, use_gray):
        path = os.path.abspath(str(img_path or ""))
        s_min, s_max, s_step = self.scale_options_for(cache_key)
        try:
            stat = os.stat(path)
            generation = (int(stat.st_mtime_ns), int(stat.st_size))
            valid_scales = (1.0, *build_scale_values(s_min, s_max, s_step))
        except (OSError, TypeError, ValueError):
            return None
        # Scale bounds are search parameters, not template identity. Keeping
        # them out of the key lets one image retain useful observations when
        # the user adjusts its current range. Generation resets stale history
        # when the file at this path is actually replaced.
        key = (path, bool(use_gray))
        return (
            key,
            generation,
            os.path.basename(path) or "图片",
            valid_scales,
        )

    def preferred_scales_for(self, img_path, cache_key, use_gray):
        context = self.scale_memory_context(img_path, cache_key, use_gray)
        if context is None:
            return (), None
        key, generation, label, valid_scales = context
        return self.scale_memory_store.preferred_scales(
            key,
            label,
            valid_scales,
            self.scale_memory_policy(),
            generation=generation,
        )

    def record_scale_match(self, img_path, cache_key, use_gray, scale, score=1.0):
        context = self.scale_memory_context(img_path, cache_key, use_gray)
        if context is None:
            return None
        key, generation, label, valid_scales = context
        summary, changed = self.scale_memory_store.record(
            key,
            label,
            valid_scales,
            scale,
            score,
            self.scale_memory_policy(),
            generation=generation,
        )
        if changed and summary is not None and self.verbose_log_enabled(LOG_ADAPTIVE):
            self.log(
                "<font color='gray'>    [缩放记忆] "
                f"{summary.status_text()}</font>",
                LOG_ADAPTIVE,
            )
        return summary

    def scale_memory_summaries(self, maximum=8):
        return self.scale_memory_store.summaries(
            self.scale_memory_policy(), maximum=maximum
        )

    def recognition_wake_context(
        self,
        img_path,
        cache_key,
        task_conf,
        use_gray,
        search_regions=None,
        *,
        allow_fast_probe=True,
    ):
        if not bool(getattr(self, "scene_wake_enabled", True)):
            return None
        path = os.path.abspath(str(img_path or ""))
        if not path or "," in path or not os.path.exists(path):
            return None
        key = self.fast_match_key(
            path,
            cache_key,
            task_conf,
            use_gray,
            search_regions,
        )
        return {
            "key": key,
            "img_path": path,
            "cache_key": cache_key,
            "task_conf": float(task_conf),
            "use_gray": bool(use_gray),
            "search_regions": search_regions,
            "allow_fast_probe": bool(allow_fast_probe),
        }

    def fast_match_key(
        self,
        img_path,
        cache_key,
        task_conf,
        use_gray,
        search_regions=None,
    ):
        regions = tuple(
            tuple(int(value) for value in region)
            for region in self.native_search_regions(
                search_regions=search_regions
            )
        )
        return (
            os.path.abspath(str(img_path or "")),
            str(cache_key),
            float(task_conf),
            bool(use_gray),
            regions,
        )

    def capture_scene_signatures(self, search_regions=None):
        started_ns = time.perf_counter_ns()
        signatures = []
        try:
            native = getattr(self, "native_core", None)
            use_native_fingerprint = bool(
                getattr(self, "use_native_core", True)
                and not getattr(self, "_native_disabled_for_run", False)
                and native
                and native.available
                and getattr(native, "has_scene_fingerprint", False)
            )
            if use_native_fingerprint:
                regions = self.effective_search_regions(search_regions)
                if not regions:
                    regions = [self.screen_bounds()]
                for region in regions:
                    raw = native.capture_scene_signature(region)
                    if raw is None:
                        signatures.clear()
                        self.performance.increment(
                            "wake.native_scene_capture_failures"
                        )
                        break
                    width, height, pixels = raw
                    signatures.append(
                        SceneSignature(width, height, pixels)
                    )
                if signatures:
                    self.performance.increment("wake.scene_captures")
                    self.performance.increment(
                        "wake.native_scene_captures", len(signatures)
                    )
                    return tuple(signatures)

            for screenshot_pil, _offset_x, _offset_y in self.iter_search_screenshots(
                search_regions
            ):
                if self.check_stop_flag():
                    return ()
                signature = make_scene_signature(screenshot_pil)
                if signature is not None:
                    signatures.append(signature)
            self.performance.increment("wake.scene_captures")
            return tuple(signatures)
        except Exception:
            self.performance.increment("wake.scene_capture_failures")
            return ()
        finally:
            self.performance.observe_since("wake.scene_capture", started_ns)

    def begin_scene_monitor(self, context):
        native = getattr(self, "native_core", None)
        use_dxgi = bool(
            getattr(self, "use_native_core", True)
            and not getattr(self, "_native_disabled_for_run", False)
            and native
            and native.available
            and getattr(native, "has_dxgi_scene_change", False)
            and getattr(native, "dxgi_scene_usable", True)
        )
        if use_dxgi:
            regions = self.effective_search_regions(
                context.get("search_regions")
            )
            cache = getattr(self, "scene_signature_cache", None)
            if cache is None:
                self.scene_signature_cache = {}
                cache = self.scene_signature_cache
            signatures = tuple(cache.get(context.get("key"), ()) or ())
            changed = native.poll_desktop_change(
                regions,
                reset_baseline=not bool(signatures),
            )
            if changed is not None:
                if not signatures:
                    signatures = self.capture_scene_signatures(
                        context.get("search_regions")
                    )
                    if signatures:
                        cache[context.get("key")] = signatures
                self.performance.increment("wake.dxgi_baselines")
                return {
                    "mode": "dxgi",
                    "regions": regions,
                    "signatures": signatures,
                    "initial_dirty": bool(changed),
                }
            self.performance.increment("wake.dxgi_fallbacks")
        return {
            "mode": "fingerprint",
            "signatures": self.capture_scene_signatures(
                context.get("search_regions")
            ),
        }

    def wake_probe_scales(self, context):
        memory_context = self.scale_memory_context(
            context["img_path"],
            context["cache_key"],
            context["use_gray"],
        )
        if memory_context is None:
            return ()
        _key, _generation, _label, valid_scales = memory_context
        valid = tuple(dict.fromkeys(float(scale) for scale in valid_scales))
        preferred, _summary = self.preferred_scales_for(
            context["img_path"],
            context["cache_key"],
            context["use_gray"],
        )
        if not preferred:
            return ()
        selected = list(preferred[:8])
        remaining = [scale for scale in valid if scale not in selected]
        sensitivity = normalize_sensitivity(
            getattr(self, "scene_wake_sensitivity", "balanced")
        )
        batch_size = {
            "conservative": 1,
            "balanced": 2,
            "sensitive": 3,
        }[sensitivity]
        if remaining:
            cursors = getattr(self, "scene_probe_cursors", None)
            if cursors is None:
                self.scene_probe_cursors = {}
                cursors = self.scene_probe_cursors
            cursor = int(cursors.get(context["key"], 0)) % len(remaining)
            for offset in range(min(batch_size, len(remaining))):
                selected.append(remaining[(cursor + offset) % len(remaining)])
            cursors[context["key"]] = (cursor + batch_size) % len(remaining)
        return tuple(selected[:16])

    def find_target_scales_only(
        self,
        img_path,
        cache_key,
        task_conf,
        use_gray,
        scales,
        search_regions=None,
    ):
        allowed_scales = tuple(
            dict.fromkeys(float(round(float(scale), 8)) for scale in scales)
        )
        if not allowed_scales or self.check_stop_flag():
            return None
        position_key = self.target_position_key(
            img_path, cache_key, task_conf, use_gray
        )
        native_found = self.native_find_targets(
            img_path,
            cache_key,
            task_conf,
            use_gray,
            find_all=False,
            search_regions=search_regions,
            explicit_scales=allowed_scales,
        )
        if native_found is not None:
            if not native_found:
                return None
            found = native_found[0]
            self.remember_target_result(
                position_key, found, img_path, cache_key, use_gray
            )
            return found

        try:
            for screenshot_pil, offset_x, offset_y in self.iter_search_screenshots(
                search_regions
            ):
                if self.check_stop_flag():
                    return None
                found = self.find_target_in_screenshot(
                    img_path,
                    cache_key,
                    task_conf,
                    use_gray,
                    screenshot_pil,
                    offset_x,
                    offset_y,
                    allowed_scales=allowed_scales,
                )
                if found:
                    self.remember_target_result(
                        position_key, found, img_path, cache_key, use_gray
                    )
                    return found
        except Exception:
            return None
        return None

    def probe_recognition_wake(self, context):
        if not context or not context.get("allow_fast_probe", True):
            return None
        scales = self.wake_probe_scales(context)
        if not scales:
            return None
        self.performance.increment("wake.scale_probes")
        self.performance.increment("wake.scale_variants", len(scales))
        started_ns = time.perf_counter_ns()
        try:
            found = self.find_target_scales_only(
                context["img_path"],
                context["cache_key"],
                context["task_conf"],
                context["use_gray"],
                scales,
                context.get("search_regions"),
            )
        finally:
            self.performance.observe_since("wake.scale_probe", started_ns)
        if found:
            pending = getattr(self, "pending_fast_matches", None)
            if pending is None:
                self.pending_fast_matches = {}
                pending = self.pending_fast_matches
            pending[context["key"]] = found
            self.performance.increment("wake.scale_probe_hits")
            if self.verbose_log_enabled(LOG_ADAPTIVE):
                self.log(
                    "<font color='gray'>    [画面唤醒] 常用/轮换倍率快速探测命中，"
                    f"倍率 {found[2]:g}x。</font>",
                    LOG_ADAPTIVE,
                )
        return found

    def wait_adaptive_scene(self, extra_delay, context, baseline=()):
        duration = max(0.0, float(extra_delay or 0.0))
        if duration <= 0.0 or not context:
            return not self.check_stop_flag()
        sensitivity = normalize_sensitivity(
            getattr(self, "scene_wake_sensitivity", "balanced")
        )
        interval = {
            "conservative": 0.14,
            "balanced": 0.10,
            "sensitive": 0.07,
        }[sensitivity]
        dxgi_mode = bool(
            isinstance(baseline, dict)
            and baseline.get("mode") == "dxgi"
        )
        dxgi_regions = baseline.get("regions", []) if dxgi_mode else []
        dxgi_dirty_pending = (
            bool(baseline.get("initial_dirty", False)) if dxgi_mode else False
        )
        dxgi_next_confirmation = 0.0
        dxgi_confirmation_interval = {
            "conservative": 0.30,
            "balanced": 0.18,
            "sensitive": 0.08,
        }[sensitivity]
        if dxgi_mode:
            interval = {
                "conservative": 0.10,
                "balanced": 0.06,
                "sensitive": 0.03,
            }[sensitivity]
        native = getattr(self, "native_core", None)
        if not dxgi_mode and not (
            getattr(self, "use_native_core", True)
            and native
            and native.available
            and getattr(native, "has_scene_fingerprint", False)
        ):
            interval = max(interval, 0.25)
        if isinstance(baseline, dict):
            anchor = tuple(baseline.get("signatures", ()) or ())
        else:
            anchor = tuple(baseline or ())
        previous = anchor
        deadline = time.monotonic() + duration

        first_check = True
        while time.monotonic() < deadline:
            if self.check_stop_flag():
                return False
            if not first_check:
                remaining = deadline - time.monotonic()
                time.sleep(min(interval, max(0.0, remaining)))
            first_check = False
            if self.check_stop_flag():
                return False
            if dxgi_mode:
                changed = native.poll_desktop_change(dxgi_regions)
                self.performance.increment("wake.scene_checks")
                self.performance.increment("wake.dxgi_polls")
                if changed is None:
                    self.performance.increment("wake.dxgi_fallbacks")
                    dxgi_mode = False
                    anchor = self.capture_scene_signatures(
                        context.get("search_regions")
                    )
                    previous = anchor
                    interval = max(interval, 0.25)
                    continue
                if changed:
                    self.performance.increment("wake.dxgi_dirty_events")
                    dxgi_dirty_pending = True
                if (
                    dxgi_dirty_pending
                    and time.monotonic() >= dxgi_next_confirmation
                ):
                    dxgi_dirty_pending = False
                    dxgi_next_confirmation = (
                        time.monotonic() + dxgi_confirmation_interval
                    )
                    current = self.capture_scene_signatures(
                        context.get("search_regions")
                    )
                    if not current:
                        dxgi_mode = False
                        anchor = ()
                        previous = ()
                        interval = max(interval, 0.25)
                        continue
                    comparisons = []
                    if anchor:
                        comparisons.append(
                            compare_scene_sets(
                                anchor, current, sensitivity=sensitivity
                            )
                        )
                    if previous and previous is not anchor:
                        comparisons.append(
                            compare_scene_sets(
                                previous, current, sensitivity=sensitivity
                            )
                        )
                    confirmed = next(
                        (
                            result
                            for result in comparisons
                            if result.changed
                        ),
                        None,
                    )
                    if context.get("key") is not None:
                        self.scene_signature_cache[context.get("key")] = current
                    previous = current
                    if confirmed is not None:
                        self.performance.increment("wake.scene_triggers")
                        self.performance.increment(
                            "wake.dxgi_confirmed_changes"
                        )
                        if self.verbose_log_enabled(LOG_ADAPTIVE):
                            self.log(
                                "<font color='gray'>    [画面唤醒] DXGI 通知并经分块指纹确认变化，"
                                f"提前结束自适应等待（局部 {confirmed.peak_percent:.2f}%，"
                                f"整体 {confirmed.global_percent:.2f}%）。</font>",
                                LOG_ADAPTIVE,
                            )
                        self.probe_recognition_wake(context)
                        return not self.check_stop_flag()
                continue
            current = self.capture_scene_signatures(
                context.get("search_regions")
            )
            if not current:
                continue
            self.performance.increment("wake.scene_checks")
            comparisons = []
            if anchor:
                comparisons.append(
                    compare_scene_sets(
                        anchor, current, sensitivity=sensitivity
                    )
                )
            if previous and previous is not anchor:
                comparisons.append(
                    compare_scene_sets(
                        previous, current, sensitivity=sensitivity
                    )
                )
            changed = next(
                (result for result in comparisons if result.changed), None
            )
            if changed is not None:
                self.performance.increment("wake.scene_triggers")
                if self.verbose_log_enabled(LOG_ADAPTIVE):
                    self.log(
                        "<font color='gray'>    [画面唤醒] 检测到识别区域变化，"
                        f"提前结束自适应等待（局部 {changed.peak_percent:.2f}%，"
                        f"整体 {changed.global_percent:.2f}%）。</font>",
                        LOG_ADAPTIVE,
                    )
                self.probe_recognition_wake(context)
                return not self.check_stop_flag()
            previous = current
        return not self.check_stop_flag()

    def remember_target_result(
        self,
        position_key,
        found,
        img_path=None,
        cache_key=None,
        use_gray=True,
    ):
        self.last_target_positions[position_key] = (found[0], found[1])
        try:
            scale = float(found[2])
        except (IndexError, TypeError, ValueError):
            return
        if scale > 0.0:
            if img_path is not None and cache_key is not None:
                score = found[3] if len(found) > 3 else 1.0
                self.record_scale_match(
                    img_path, cache_key, use_gray, scale, score
                )

    def template_dimensions(self, img_path):
        try:
            if img_path not in self.img_cache and os.path.exists(img_path):
                img = Image.open(img_path)
                img.load()
                self.img_cache[img_path] = img
            img = self.img_cache.get(img_path)
            if img:
                return img.size
        except Exception:
            pass
        return (80, 80)

    def matching_template_status(self, img_path, use_gray):
        path = os.path.abspath(str(img_path or ""))
        try:
            stat = os.stat(path)
            signature = (path, bool(use_gray), int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            return False, "图片不存在"
        cached = self.template_validation_cache.get(signature)
        if cached is None:
            cached = template_detail_status(path, use_gray)
            self.template_validation_cache[signature] = cached
        valid, reason = cached
        if not valid and signature not in self.template_validation_reported:
            self.template_validation_reported.add(signature)
            if self.log_enabled(LOG_CRITICAL, critical=True):
                self.log(f"<font color='red'>模板无法安全识别：{os.path.basename(path)}；{reason}</font>", LOG_CRITICAL, critical=True)
        return valid, reason

    def image_click_point_options(self, task):
        if not task or not self.as_bool(task.get("image_click_point_en", False)):
            return None
        rx = max(0.0, min(1.0, self.parse_float_value(task.get("image_click_point_rx", 0.5), 0.5)))
        ry = max(0.0, min(1.0, self.parse_float_value(task.get("image_click_point_ry", 0.5), 0.5)))
        return {"rx": rx, "ry": ry}

    def step_search_regions(self, task, cmd, val):
        if cmd not in [1.0, 2.0, 3.0, 8.0]:
            return None
        if self.parse_coordinate(val):
            return None
        if not self.as_bool((task or {}).get("step_region_en", False)):
            return None
        region = parse_region_text((task or {}).get("step_region", ""))
        return [region] if region else None

    def adjusted_image_click_point(self, img_path, location_tuple, image_click_config):
        x, y, scale, _score = location_tuple
        if not image_click_config:
            return x, y
        tpl_w, tpl_h = self.template_dimensions(img_path)
        matched_w = tpl_w * max(0.01, float(scale))
        matched_h = tpl_h * max(0.01, float(scale))
        rx = image_click_config.get("rx", 0.5)
        ry = image_click_config.get("ry", 0.5)
        click_x = x + (rx - 0.5) * matched_w
        click_y = y + (ry - 0.5) * matched_h
        return click_x, click_y

    def point_in_search_regions(self, x, y, search_regions):
        regions = self.normalized_regions(search_regions)
        if not regions:
            return True
        px, py = float(x), float(y)
        for rx, ry, rw, rh in regions:
            if rx <= px < rx + rw and ry <= py < ry + rh:
                return True
        return False

    def quick_search_region(self, img_path, cache_key, task_conf, use_gray, search_regions=None):
        if search_regions is not None:
            return None
        if self.normalized_regions(getattr(self, "scan_regions", [])):
            return None
        key = self.target_position_key(img_path, cache_key, task_conf, use_gray)
        last = self.last_target_positions.get(key)
        if not last:
            return None

        tpl_w, tpl_h = self.template_dimensions(img_path)
        radius = max(120, int(max(tpl_w, tpl_h) * 3))
        x = int(last[0] - radius)
        y = int(last[1] - radius)
        region = (x, y, radius * 2, radius * 2)
        bounds = self.scan_region if self.scan_region else self.screen_bounds()
        return self.clip_region_to_bounds(region, bounds)

    def scale_options_for(self, cache_key):
        return self.scale_options_cache.get(str(cache_key), (self.min_scale, self.max_scale, self.scale_step))

    def native_search_regions(self, quick_region=None, search_regions=None):
        if quick_region:
            return [quick_region]
        explicit_regions = self.normalized_regions(search_regions)
        if explicit_regions:
            return explicit_regions
        active_regions = self.normalized_regions(getattr(self, "scan_regions", []))
        if active_regions:
            return active_regions
        if self.scan_region:
            return [self.scan_region]
        return []

    def native_find_targets(
        self,
        img_path,
        cache_key,
        task_conf,
        use_gray,
        find_all=False,
        quick_region=None,
        search_regions=None,
        explicit_scales=None,
    ):
        if not self.use_native_core:
            return None
        if getattr(self, "_native_disabled_for_run", False):
            self.performance.increment("match.native_circuit_breaker_hits")
            return None
        if not getattr(self, "native_core", None) or not self.native_core.available:
            return None
        path = str(img_path)
        if not path or ',' in path or not os.path.exists(path):
            return None
        valid, _reason = self.matching_template_status(path, use_gray)
        if not valid:
            return []
        if self.check_stop_flag():
            return None

        s_min, s_max, s_step = self.scale_options_for(cache_key)
        max_matches = 1024 if find_all else 1
        native_regions = self.native_search_regions(quick_region, search_regions)
        explicit_scales = tuple(
            dict.fromkeys(float(scale) for scale in (explicit_scales or ()))
        )
        if explicit_scales and not getattr(
            self.native_core, "has_explicit_scale_only", False
        ):
            return None
        preferred_scales = explicit_scales
        if not find_all and not explicit_scales:
            preferred_scales, _memory_summary = self.preferred_scales_for(
                img_path, cache_key, use_gray
            )
        rejection_key = (
            os.path.abspath(path),
            tuple(tuple(int(value) for value in region) for region in native_regions),
            float(s_min),
            float(s_max),
            float(s_step),
            bool(use_gray),
            bool(find_all),
            explicit_scales,
        )
        if rejection_key in self.native_rejection_cache:
            self.performance.increment("match.native_rejection_cache_hits")
            return None
        native_started_ns = time.perf_counter_ns()
        try:
            matches = self.native_core.find_template(
                path,
                native_regions,
                s_min,
                s_max,
                s_step,
                use_gray,
                task_conf,
                find_all=find_all,
                max_matches=max_matches,
                parallel_mode=getattr(self, "native_parallel_mode", "auto"),
                preferred_scales=preferred_scales,
                explicit_scale_only=bool(explicit_scales),
            )
        finally:
            self.performance.observe_since("match.native", native_started_ns)
            self.performance.increment("match.native_calls")
        if matches is None:
            self.performance.increment("match.native_fallbacks")
            native_error = str(self.native_core.load_error or "")
            try:
                native_result_code = int(self.native_core.last_result_code)
            except (AttributeError, TypeError, ValueError):
                native_result_code = 0
            if (
                native_result_code == NATIVE_RESULT_WORK_BUDGET
                or "work budget exceeded" in native_error.lower()
            ):
                self.native_rejection_cache.add(rejection_key)
                self.performance.increment("match.native_rejections_cached")
            else:
                self.native_failure_streak = int(
                    getattr(self, "native_failure_streak", 0)
                ) + 1
                if self.native_failure_streak >= 3:
                    self._native_disabled_for_run = True
                    self._native_disable_reason = native_error or "连续原生调用失败"
                    self.performance.increment("match.native_circuit_breaker_trips")
                    if self.log_enabled(LOG_CRITICAL, critical=True):
                        self.log(
                            "<font color='orange'>原生识别连续失败 3 次，本次运行已自动停用 DLL "
                            "并改用 OpenCV；下次启动脚本会重新尝试。</font>",
                            LOG_CRITICAL,
                            critical=True,
                        )
            if self.verbose_log_enabled(LOG_BACKEND) and self.native_core.load_error:
                self.log(f"<font color='gray'>    [native] fallback: {self.native_core.load_error}</font>", LOG_BACKEND)
            return None
        self.native_failure_streak = 0
        if preferred_scales and not explicit_scales:
            if matches and any(
                abs(float(matches[0][2]) - float(scale)) <= 1e-7
                for scale in preferred_scales
            ):
                self.performance.increment("match.native_scale_hint_hits")
            else:
                self.performance.increment("match.native_scale_hint_fallbacks")
        if matches:
            self.performance.increment("match.native_hits")
        else:
            self.performance.increment("match.native_misses")
        return [(x, y, scale, score) for x, y, scale, score, _radius in matches]

    def load_and_precompute(self, tasks):
        if not self.opencv_available:
            return True

        import cv2
        import numpy as np

        errors = []
        write_log("正在预加载资源...")

        def load_source_image(path):
            if path in self.img_cache:
                self.performance.increment("template.source_cache_hits")
                return self.img_cache[path]
            self.performance.increment("template.source_cache_misses")
            load_started_ns = time.perf_counter_ns()
            with Image.open(path) as source:
                width, height = source.size
                if width * height > MAX_TEMPLATE_SOURCE_PIXELS:
                    raise ValueError(f"图片像素过多，最多允许 {MAX_TEMPLATE_SOURCE_PIXELS:,} 像素")
                image = source.copy()
                image.load()
            self.img_cache[path] = image
            self.performance.observe_since("template.source_load", load_started_ns)
            return image

        def preload_one(path, cache_key, s_min, s_max, s_step, use_gray):
            started_ns = time.perf_counter_ns()
            try:
                return preload_one_impl(
                    path, cache_key, s_min, s_max, s_step, use_gray
                )
            finally:
                self.performance.observe_since("template.precompute_one", started_ns)

        def preload_one_impl(path, cache_key, s_min, s_max, s_step, use_gray):
            if not path or not os.path.exists(path) or ',' in path:
                return
            valid, reason = self.matching_template_status(path, use_gray)
            if not valid:
                raise ValueError(reason)

            scale_values = build_scale_values(s_min, s_max, s_step)
            estimated = estimate_template_cache_bytes(path, use_gray, scale_values)
            if estimated > MAX_SINGLE_TEMPLATE_CACHE_BYTES:
                raise ValueError(
                    f"该图片预计占用 {estimated / 1024 / 1024:.1f} MB 模板缓存，"
                    f"单图上限为 {MAX_SINGLE_TEMPLATE_CACHE_BYTES / 1024 / 1024:.0f} MB"
                )
            if cache_key in self.scaled_templates_cache:
                self.performance.increment("template.scaled_cache_hits")
                self.scale_options_cache[str(cache_key)] = (s_min, s_max, s_step)
                return
            self.performance.increment("template.scaled_cache_misses")
            if self.scaled_template_cache_bytes + estimated > MAX_TEMPLATE_CACHE_BYTES:
                raise ValueError(
                    f"全部模板预计超过 {MAX_TEMPLATE_CACHE_BYTES / 1024 / 1024:.0f} MB 缓存上限，"
                    "请减少图片、缩放范围或缩放档位"
                )

            image = load_source_image(path)
            self.scale_options_cache[str(cache_key)] = (s_min, s_max, s_step)
            work_img = image.convert('L' if use_gray else 'RGB')
            template = np.array(work_img)
            if not use_gray:
                template = cv2.cvtColor(template, cv2.COLOR_RGB2BGR)
            self.base_templates_cache[cache_key] = template

            templates_list = []
            actual_bytes = int(template.nbytes)
            for scale in scale_values:
                if self.check_stop_flag():
                    raise RuntimeError("资源预加载已停止")
                rw = max(1, int(round(template.shape[1] * scale)))
                rh = max(1, int(round(template.shape[0] * scale)))
                interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
                resized_tpl = cv2.resize(template, (rw, rh), interpolation=interpolation)
                actual_bytes += int(resized_tpl.nbytes)
                templates_list.append((float(scale), resized_tpl))
            self.scaled_templates_cache[cache_key] = templates_list
            self.scaled_template_cache_bytes += actual_bytes
            self.performance.increment("template.scale_variants", len(templates_list))
            self.performance.set_gauge(
                "template.cache_bytes", self.scaled_template_cache_bytes
            )

        for task_idx, task in enumerate(tasks, 1):
            if self.check_stop_flag():
                return False
            cmd = task.get("type")
            try:
                if cmd in [1.0, 2.0, 3.0, 8.0]:
                    path = str(task.get("value", ""))
                    if not path or not os.path.exists(path) or ',' in path:
                        continue
                    if config_bool(task.get("custom_en", False)):
                        s_min = float(task.get("custom_scale_min", self.min_scale))
                        s_max = float(task.get("custom_scale_max", self.max_scale))
                        s_step = float(task.get("custom_scale_step", self.scale_step))
                        use_gray = config_bool(task.get("custom_gray", self.enable_grayscale))
                    else:
                        s_min, s_max, s_step = self.min_scale, self.max_scale, self.scale_step
                        use_gray = self.enable_grayscale

                    cache_key = f"{path}_{s_min}_{s_max}_{s_step}_{use_gray}"
                    task['cache_key'] = cache_key
                    preload_one(path, cache_key, s_min, s_max, s_step, use_gray)
                elif cmd == TASK_TYPE_UNTIL:
                    for cond in self.until_conditions_from_task(task):
                        mode = cond.get("mode")
                        if mode == "区域发生变化":
                            continue
                        path = str(cond.get("image", "")).strip()
                        if not path or not os.path.exists(path):
                            continue
                        if mode == "区域变成指定图片":
                            load_source_image(path)
                            continue
                        conf = self.condition_confidence(cond)
                        use_gray = self.enable_grayscale
                        cache_key = self.condition_cache_key(path, cond.get("index", 0), conf, use_gray)
                        task[f"until_cond{cond.get('index')}_cache_key"] = cache_key
                        preload_one(path, cache_key, self.min_scale, self.max_scale, self.scale_step, use_gray)
            except Exception as e:
                errors.append(f"第 {task_idx} 步：{e}")

        if errors:
            for error in errors[:20]:
                write_log(f"预计算失败: {error}")
            if len(errors) > 20:
                write_log(f"预计算失败: 另有 {len(errors) - 20} 条错误未显示")
            return False
        write_log("资源预加载完成。")
        return True

    def find_target_in_screenshot(
        self,
        img_path,
        cache_key,
        task_conf,
        use_gray,
        screenshot_pil,
        offset_x,
        offset_y,
        allowed_scales=None,
    ):
        started_ns = time.perf_counter_ns()
        try:
            return self._find_target_in_screenshot_impl(
                img_path,
                cache_key,
                task_conf,
                use_gray,
                screenshot_pil,
                offset_x,
                offset_y,
                allowed_scales,
            )
        finally:
            self.performance.observe_since("match.opencv", started_ns)
            self.performance.increment("match.opencv_calls")

    def _find_target_in_screenshot_impl(
        self,
        img_path,
        cache_key,
        task_conf,
        use_gray,
        screenshot_pil,
        offset_x,
        offset_y,
        allowed_scales=None,
    ):
        valid, _reason = self.matching_template_status(img_path, use_gray)
        if not valid:
            return None
        allowed_scale_set = None
        if allowed_scales is not None:
            allowed_scale_set = {
                float(round(float(scale), 8)) for scale in allowed_scales
            }
            if not allowed_scale_set:
                return None
        if not self.opencv_available:
            if allowed_scale_set is not None and 1.0 not in allowed_scale_set:
                return None
            if img_path in self.img_cache:
                try: 
                    res = pyautogui.locate(self.img_cache[img_path], screenshot_pil, confidence=task_conf, grayscale=use_gray)
                    if res: return (res.left + (res.width / 2) + offset_x, res.top + (res.height / 2) + offset_y, 1.0, 1.0)
                except Exception: pass
            elif os.path.exists(img_path):
                 try:
                    res = pyautogui.locate(img_path, screenshot_pil, confidence=task_conf, grayscale=use_gray)
                    if res: return (res.left + (res.width / 2) + offset_x, res.top + (res.height / 2) + offset_y, 1.0, 1.0)
                 except Exception: pass
            return None

        import cv2
        import numpy as np
        
        screen_np = np.array(screenshot_pil)
        if use_gray:
            screen_img = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
        else:
            screen_img = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)
        
        if img_path not in self.img_cache:
            if os.path.exists(img_path):
                try:
                    img = Image.open(img_path)
                    img.load()
                    self.img_cache[img_path] = img
                except Exception: return None
            else: return None
        
        variants = []
        try:
            tpl_img = self.base_templates_cache.get(cache_key)
            if tpl_img is None:
                self.performance.increment("template.base_cache_misses")
                pil_template = self.img_cache[img_path]
                if use_gray:
                    if pil_template.mode != 'L':
                        pil_template = pil_template.convert('L')
                    tpl_img = np.array(pil_template)
                else:
                    if pil_template.mode != 'RGB':
                        pil_template = pil_template.convert('RGB')
                    tpl_img = cv2.cvtColor(np.array(pil_template), cv2.COLOR_RGB2BGR)
                self.base_templates_cache[cache_key] = tpl_img
            else:
                self.performance.increment("template.base_cache_hits")
            variants.append((1.0, tpl_img))
        except Exception:
            pass

        if cache_key in self.scaled_templates_cache:
            variants.extend(self.scaled_templates_cache[cache_key])

        if allowed_scale_set is not None:
            variants = [
                item
                for item in variants
                if float(round(float(item[0]), 8)) in allowed_scale_set
            ]

        preferred_scales, _summary = self.preferred_scales_for(
            img_path, cache_key, use_gray
        )
        preferred_order = {
            float(scale): index for index, scale in enumerate(preferred_scales)
        }
        variants = sorted(
            enumerate(variants),
            key=lambda item: (
                preferred_order.get(float(item[1][0]), len(preferred_order)),
                item[0],
            ),
        )
        for _original_index, (scale, resized_tpl) in variants:
            if self.check_stop_flag():
                return None
            try:
                if (
                    resized_tpl.shape[0] > screen_img.shape[0]
                    or resized_tpl.shape[1] > screen_img.shape[1]
                ):
                    continue
                res = cv2.matchTemplate(
                    screen_img, resized_tpl, cv2.TM_CCOEFF_NORMED
                )
                _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res)
                if max_v >= task_conf:
                    h, w = resized_tpl.shape[:2]
                    return (
                        max_l[0] + w // 2 + offset_x,
                        max_l[1] + h // 2 + offset_y,
                        float(scale),
                        float(max_v),
                    )
            except Exception:
                continue
        return None

    def find_target_optimized(self, img_path, cache_key, task_conf, use_gray, search_regions=None):
        started_ns = time.perf_counter_ns()
        try:
            return self._find_target_optimized_impl(
                img_path, cache_key, task_conf, use_gray, search_regions
            )
        finally:
            self.performance.observe_since("vision.search", started_ns)
            self.performance.increment("vision.search_calls")

    def _find_target_optimized_impl(self, img_path, cache_key, task_conf, use_gray, search_regions=None):
        pending_key = self.fast_match_key(
            img_path,
            cache_key,
            task_conf,
            use_gray,
            search_regions,
        )
        pending = getattr(self, "pending_fast_matches", {}).pop(
            pending_key, None
        )
        if pending is not None:
            self.performance.increment("wake.pending_hits_consumed")
            return pending
        position_key = self.target_position_key(img_path, cache_key, task_conf, use_gray)
        quick_region = self.quick_search_region(img_path, cache_key, task_conf, use_gray, search_regions)
        if quick_region:
            native_found = self.native_find_targets(img_path, cache_key, task_conf, use_gray, find_all=False, quick_region=quick_region)
            if native_found is not None:
                if native_found:
                    found = native_found[0]
                    self.remember_target_result(
                        position_key, found, img_path, cache_key, use_gray
                    )
                    return found
            else:
                try:
                    screenshot_pil, offset_x, offset_y = self.capture_screenshot(quick_region)
                    found = self.find_target_in_screenshot(img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y)
                    if found:
                        self.remember_target_result(
                            position_key, found, img_path, cache_key, use_gray
                        )
                        return found
                except Exception:
                    pass
            self.last_target_positions.pop(position_key, None)

        native_found = self.native_find_targets(img_path, cache_key, task_conf, use_gray, find_all=False, search_regions=search_regions)
        if native_found is not None:
            if native_found:
                found = native_found[0]
                self.remember_target_result(
                    position_key, found, img_path, cache_key, use_gray
                )
                return found
            return None

        try:
            for screenshot_pil, offset_x, offset_y in self.iter_search_screenshots(search_regions):
                if self.check_stop_flag():
                    return None
                found = self.find_target_in_screenshot(img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y)
                if found:
                    self.remember_target_result(
                        position_key, found, img_path, cache_key, use_gray
                    )
                    return found
        except Exception:
            return None
        return None

    def _collect_template_matches(self, screen_img, tpl_img, task_conf, offset_x, offset_y, scale):
        import cv2
        import numpy as np

        if tpl_img.shape[0] > screen_img.shape[0] or tpl_img.shape[1] > screen_img.shape[1]:
            return []

        res = cv2.matchTemplate(screen_img, tpl_img, cv2.TM_CCOEFF_NORMED)
        h, w = tpl_img.shape[:2]
        kernel_w = max(3, int(w * 0.6))
        kernel_h = max(3, int(h * 0.6))
        peak_map = cv2.dilate(res, np.ones((kernel_h, kernel_w), dtype=np.uint8))
        ys, xs = np.where((res >= task_conf) & (res == peak_map))
        if len(xs) == 0:
            return []

        scores = res[ys, xs]
        if len(xs) > 2000:
            keep = np.argpartition(scores, -2000)[-2000:]
            xs, ys, scores = xs[keep], ys[keep], scores[keep]

        matches = []
        for x, y, score in zip(xs, ys, scores, strict=False):
            matches.append({
                "x": float(x + w // 2 + offset_x),
                "y": float(y + h // 2 + offset_y),
                "scale": float(scale),
                "score": float(score),
                "radius": max(4.0, min(w, h) * 0.55)
            })
        return matches

    def _dedupe_targets(self, matches):
        accepted = []
        for match in sorted(matches, key=lambda m: m["score"], reverse=True):
            too_close = False
            for item in accepted:
                dx = match["x"] - item["x"]
                dy = match["y"] - item["y"]
                radius = max(match["radius"], item["radius"])
                if dx * dx + dy * dy <= radius * radius:
                    too_close = True
                    break
            if not too_close:
                accepted.append(match)
        return accepted

    def _sort_targets_for_click(self, targets):
        order = self.multi_target_order
        if order == "随机顺序":
            random.shuffle(targets)
            return targets
        if order == "距离鼠标最近优先":
            try:
                mx, my = pyautogui.position()
                targets.sort(key=lambda p: ((p["x"] - mx) ** 2 + (p["y"] - my) ** 2, p["y"], p["x"]))
            except Exception:
                targets.sort(key=lambda p: (p["y"], p["x"]))
            return targets
        if order == "从左到右":
            targets.sort(key=lambda p: (p["x"], p["y"]))
        elif order == "从右到左":
            targets.sort(key=lambda p: (-p["x"], p["y"]))
        else:
            targets.sort(key=lambda p: (p["y"], p["x"]))
        return targets

    def _point_limit_key(self, step_info, img_path, x, y):
        step = step_info.get("step", 0) if step_info else 0
        bucket_x = int(round(float(x) / 8.0) * 8)
        bucket_y = int(round(float(y) / 8.0) * 8)
        return (step, os.path.abspath(str(img_path)), bucket_x, bucket_y)

    def _filter_point_limit_targets(self, locations, img_path, step_info, point_limit_en, point_limit_count):
        if not point_limit_en or point_limit_count <= 0:
            return locations

        filtered = []
        skipped = 0
        for location_tuple in locations:
            x, y = location_tuple[0], location_tuple[1]
            key = self._point_limit_key(step_info, img_path, x, y)
            if self.point_click_counts.get(key, 0) >= point_limit_count:
                skipped += 1
                continue
            filtered.append(location_tuple)

        if skipped and self.log_level >= 1:
            self.log(f"    -> 同点点击上限已过滤 {skipped} 个已达上限的点位", LOG_RECOGNITION)
        return filtered

    def _record_point_click(self, img_path, step_info, x, y):
        key = self._point_limit_key(step_info, img_path, x, y)
        self.point_click_counts[key] = self.point_click_counts.get(key, 0) + 1
        return self.point_click_counts[key]

    def find_all_targets_in_screenshot(self, img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y, search_regions=None):
        started_ns = time.perf_counter_ns()
        try:
            return self._find_all_targets_in_screenshot_impl(
                img_path,
                cache_key,
                task_conf,
                use_gray,
                screenshot_pil,
                offset_x,
                offset_y,
                search_regions,
            )
        finally:
            self.performance.observe_since("match.opencv", started_ns)
            self.performance.increment("match.opencv_calls")

    def _find_all_targets_in_screenshot_impl(self, img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y, search_regions=None):
        valid, _reason = self.matching_template_status(img_path, use_gray)
        if not valid:
            return []
        if not self.opencv_available:
            try:
                target = self.img_cache.get(img_path, img_path)
                boxes = list(pyautogui.locateAll(target, screenshot_pil, confidence=task_conf, grayscale=use_gray))
                matches = [{
                    "x": box.left + (box.width / 2) + offset_x,
                    "y": box.top + (box.height / 2) + offset_y,
                    "scale": 1.0,
                    "score": 1.0,
                    "radius": max(4.0, min(box.width, box.height) * 0.55)
                } for box in boxes]
                return [(p["x"], p["y"], p["scale"], p["score"]) for p in self._sort_targets_for_click(self._dedupe_targets(matches))]
            except Exception:
                one = self.find_target_optimized(img_path, cache_key, task_conf, use_gray, search_regions)
                return [(one[0], one[1], one[2], task_conf)] if one else []

        import cv2
        import numpy as np

        screen_np = np.array(screenshot_pil)
        if use_gray:
            screen_img = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
        else:
            screen_img = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)

        if img_path not in self.img_cache:
            if os.path.exists(img_path):
                try:
                    img = Image.open(img_path)
                    img.load()
                    self.img_cache[img_path] = img
                except Exception: return []
            else: return []

        matches = []
        try:
            tpl_img = self.base_templates_cache.get(cache_key)
            if tpl_img is None:
                self.performance.increment("template.base_cache_misses")
                pil_template = self.img_cache[img_path]
                if use_gray:
                    if pil_template.mode != 'L':
                        pil_template = pil_template.convert('L')
                    tpl_img = np.array(pil_template)
                else:
                    if pil_template.mode != 'RGB':
                        pil_template = pil_template.convert('RGB')
                    tpl_img = cv2.cvtColor(np.array(pil_template), cv2.COLOR_RGB2BGR)
                self.base_templates_cache[cache_key] = tpl_img
            else:
                self.performance.increment("template.base_cache_hits")

            matches.extend(self._collect_template_matches(screen_img, tpl_img, task_conf, offset_x, offset_y, 1.0))
        except Exception: pass

        if cache_key in self.scaled_templates_cache:
            for scale, resized_tpl in self.scaled_templates_cache[cache_key]:
                if self.check_stop_flag(): return []
                try:
                    matches.extend(self._collect_template_matches(screen_img, resized_tpl, task_conf, offset_x, offset_y, scale))
                except Exception: continue

        targets = self._sort_targets_for_click(self._dedupe_targets(matches))
        return [(p["x"], p["y"], p["scale"], p["score"]) for p in targets]

    def find_all_targets_optimized(self, img_path, cache_key, task_conf, use_gray, search_regions=None):
        started_ns = time.perf_counter_ns()
        try:
            return self._find_all_targets_optimized_impl(
                img_path, cache_key, task_conf, use_gray, search_regions
            )
        finally:
            self.performance.observe_since("vision.search", started_ns)
            self.performance.increment("vision.search_calls")

    def _find_all_targets_optimized_impl(self, img_path, cache_key, task_conf, use_gray, search_regions=None):
        native_targets = self.native_find_targets(img_path, cache_key, task_conf, use_gray, find_all=True, search_regions=search_regions)
        if native_targets is not None:
            target_dicts = [{
                "x": float(x),
                "y": float(y),
                "scale": float(scale),
                "score": float(score),
                "radius": 8.0
            } for x, y, scale, score in native_targets]
            targets = self._sort_targets_for_click(self._dedupe_targets(target_dicts))
            for target in targets:
                self.record_scale_match(
                    img_path,
                    cache_key,
                    use_gray,
                    target["scale"],
                    target["score"],
                )
            return [(p["x"], p["y"], p["scale"], p["score"]) for p in targets]

        all_targets = []
        try:
            for screenshot_pil, offset_x, offset_y in self.iter_search_screenshots(search_regions):
                if self.check_stop_flag():
                    return []
                all_targets.extend(self.find_all_targets_in_screenshot(img_path, cache_key, task_conf, use_gray, screenshot_pil, offset_x, offset_y, search_regions))
        except Exception:
            return []

        target_dicts = [{
            "x": float(x),
            "y": float(y),
            "scale": float(scale),
            "score": float(score),
            "radius": 8.0
        } for x, y, scale, score in all_targets]
        targets = self._sort_targets_for_click(self._dedupe_targets(target_dicts))
        for target in targets:
            self.record_scale_match(
                img_path,
                cache_key,
                use_gray,
                target["scale"],
                target["score"],
            )
        return [(p["x"], p["y"], p["scale"], p["score"]) for p in targets]
