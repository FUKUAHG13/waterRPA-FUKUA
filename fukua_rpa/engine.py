"""Automation execution engine; this module must not access Qt widgets directly."""

import ctypes
import os
import threading
import time

from .constants import TASK_TYPE_EXPRESSION, TASK_TYPE_UNTIL
from .commands import command_name
from .debug_session import DebugSession
from .engine_actions import ActionExecutionMixin
from .engine_conditions import UntilConditionMixin
from .engine_coordinates import CoordinatePathMixin
from .engine_expressions import ExpressionExecutionMixin
from .engine_vision import VisionExecutionMixin
from .logging_service import write_log
from .log_telemetry import (
    complete_step_timing_payload,
    format_complete_payload,
)
from .log_policy import (
    DEFAULT_CUSTOM_LOG_CATEGORIES,
    LOG_ACTION,
    LOG_BACKEND,
    LOG_CRITICAL,
    LOG_FLOW,
    LOG_MODE_CUSTOM,
    LOG_MODE_LEVELS,
    LOG_MODE_SIMPLE,
    LOG_PARAMETERS,
    LOG_RECOGNITION,
    LOG_RUN,
    LOG_STEP,
    LOG_TIMING,
    LogPolicy,
    log_mode_from_level,
    normalize_log_categories,
    normalize_log_mode,
)
from .opencv_runtime import configure_opencv_threads
from .performance import PerformanceMetrics, concise_performance_summary
from .runtime_state import RunLifecycle, RunState
from .runtime_trace import RunTrace
from .scheduler import (
    is_wait_command as scheduler_is_wait_command,
    loop_number_allowed as scheduler_loop_number_allowed,
    next_runnable_loop as scheduler_next_runnable_loop,
    non_negative_int,
    positive_int,
    task_active_in_loop as scheduler_task_active_in_loop,
)
from .scale_memory import ScaleMemoryStore
from .task_model import (
    format_region_text,
    parse_coordinate_sequence,
    parse_coordinate_text,
    parse_float_text,
)
from .vision import NativeVisionCore

class RPAEngine(
    VisionExecutionMixin,
    UntilConditionMixin,
    CoordinatePathMixin,
    ExpressionExecutionMixin,
    ActionExecutionMixin,
):
    def __init__(self, base_dir=None, defer_backends=False):
        self.base_dir = os.path.abspath(base_dir) if base_dir else None
        self.lifecycle = RunLifecycle()
        self.performance = PerformanceMetrics()
        self.last_performance_report = {}
        self.run_trace = RunTrace()
        self.last_run_trace = {}
        self.debug_session = DebugSession()
        self.min_scale = 1.0
        self.max_scale = 1.0
        self.scale_step = 0.05
        self.enable_grayscale = True
        self.confidence = 0.8
        self.scan_region = None 
        self.scan_regions = []
        self.dodge_x1 = 100
        self.dodge_y1 = 100
        self.dodge_x2 = 200
        self.dodge_y2 = 100
        self.enable_dodge = False
        self.enable_double_dodge = False
        self.double_dodge_wait = 0.015
        self.dodge_click_action = "none"
        self.move_duration = 0.0
        self.click_hold = 0.04
        self.settlement_wait = 0.0
        self.timeout_val = 0.0
        self.timeout_stop = False
        self.detect_delay = 0.0
        self.adaptive_backoff = True
        self.scene_wake_enabled = True
        self.scene_wake_sensitivity = "balanced"
        self.show_click_indicator = True
        self.use_native_core = True
        self.native_parallel_mode = "auto"
        self.use_native_scale_hint = True
        self.scale_memory_tier = "balanced"
        self.scale_memory_manual = ()
        self.scale_memory_custom_enabled = False
        self.scale_memory_preferred_limit = 3
        self.scale_memory_history_limit = 64
        self.use_fast_screenshot = True
        self.playback_speed = 1.0
        self.start_step_index = 0
        self.loop_start_round = 1
        self.loop_end_round = 0
        self.multi_target_mode = "快速一个"
        self.multi_target_order = "从上到下"
        self.loop_mode = "单次"
        self.loop_val = 1.0
        self.log_level = 0
        self.log_mode = LOG_MODE_SIMPLE
        self.log_custom_categories = tuple(DEFAULT_CUSTOM_LOG_CATEGORIES)
        self._log_policy = LogPolicy.create(
            self.log_mode, self.log_custom_categories
        )
        self._log_policy_key = None
        self.enable_tm_stop = True 
        self.enable_tr_stop = True 
        self.enable_key_stop = True
        
        self.callback_msg = None
        self.callback_status = None
        self.callback_click_indicator = None
        self.callback_debug = None
        self.opencv_available = False 
        self.opencv_threads = 0
        self.native_core = NativeVisionCore(base_dir=self.base_dir)
        self.native_core_logged = False
        self.native_rejection_cache = set()
        self.native_failure_streak = 0
        self._native_disabled_for_run = False
        self._native_disable_reason = ""
        self.img_cache = {} 
        self.base_templates_cache = {}
        self.scaled_templates_cache = {}
        self.scale_options_cache = {}
        self.point_click_counts = {}
        self.coord_step_states = {}
        self.coord_sequence_states = {}
        self.step_execution_counts = {}
        self.until_condition_baselines = {}
        self.until_condition_counts = {}
        self._task_window_backend = None
        self._credential_store = None
        self.until_condition_started_at = {}
        self.miss_streaks = {}
        self.last_target_positions = {}
        self.scale_memory_store = ScaleMemoryStore()
        self.scene_probe_cursors = {}
        self.pending_fast_matches = {}
        self.scene_signature_cache = {}
        self._mss_instance = None
        self._mss_disabled_for_run = False
        self._mss_failure_logged = False
        self.template_validation_cache = {}
        self.template_validation_reported = set()
        self.scaled_template_cache_bytes = 0
        self.global_deadline = None
        self.time_limit_reached = False
        self._last_status_payload = None
        self.reset_expression_runtime()
        self.backends_ready = False
        self._backend_init_lock = threading.Lock()

        if not defer_backends:
            self.initialize_backends()

    def initialize_backends(self):
        if self.backends_ready:
            return True
        with self._backend_init_lock:
            if self.backends_ready:
                return True
            self.check_engine_status()
            self._log_native_core_status()
            self.set_high_priority()
            self.backends_ready = True
        return True

    def set_high_priority(self):
        try:
            pid = os.getpid()
            handle = ctypes.windll.kernel32.OpenProcess(0x0100, True, pid)
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000080)
        except Exception: pass

    def check_engine_status(self):
        try:
            import cv2
            import numpy
            self.opencv_threads = configure_opencv_threads(cv2)
            img = numpy.zeros((10, 10, 3), dtype=numpy.uint8)
            cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            self.opencv_available = True
            write_log(f"OpenCV/NumPy 引擎就绪（最多 {self.opencv_threads} 线程）。")
        except Exception:
            self.opencv_available = False
            self.opencv_threads = 0
            write_log("OpenCV 引擎不可用。")

    def _log_native_core_status(self):
        if self.native_core.available:
            capabilities = self.native_core.capabilities()
            write_log(
                f"Native vision core ready (v{self.native_core.version}, "
                f"capabilities=0x{capabilities.get('mask', 0):X})."
            )
        else:
            write_log(f"Native vision core unavailable, fallback enabled: {self.native_core.load_error}")

    def reserve_run(self):
        return self.lifecycle.reserve()

    def active_run_matches(self, run_id):
        return self.lifecycle.matches(run_id)

    def finish_run(self, run_id, outcome="finished", error=""):
        finished = self.lifecycle.finish(run_id, outcome, error)
        if finished:
            self.global_deadline = None
            self.time_limit_reached = False
        return finished

    def stop(self):
        stopped = self.lifecycle.request_stop()
        if stopped:
            self.debug_session.cancel()
        return stopped

    @property
    def is_running(self):
        return self.lifecycle.is_active

    @property
    def stop_requested(self):
        return self.lifecycle.stop_requested

    @property
    def run_state(self):
        return self.lifecycle.state

    def close_screenshot_backend(self):
        instance = self._mss_instance
        self._mss_instance = None
        if instance is not None:
            try:
                instance.close()
            except Exception:
                pass

    def configure_log_policy(self, mode, custom_categories=None):
        self.log_mode = normalize_log_mode(mode, self.log_level)
        self.log_custom_categories = normalize_log_categories(
            custom_categories
            if custom_categories is not None
            else self.log_custom_categories
        )
        self.log_level = LOG_MODE_LEVELS[self.log_mode]
        self._log_policy_key = None
        return self.current_log_policy()

    def current_log_policy(self):
        if self.log_level < 0:
            return None
        mode = normalize_log_mode(self.log_mode, self.log_level)
        if (
            mode != LOG_MODE_CUSTOM
            and LOG_MODE_LEVELS.get(mode) != int(self.log_level)
        ):
            mode = log_mode_from_level(self.log_level)
        custom_categories = normalize_log_categories(self.log_custom_categories)
        key = (mode, int(self.log_level), custom_categories)
        if key != self._log_policy_key:
            self._log_policy = LogPolicy.create(mode, custom_categories)
            self._log_policy_key = key
        return self._log_policy

    def log_enabled(self, category=LOG_ACTION, *, critical=False, message=""):
        policy = self.current_log_policy()
        return bool(
            policy
            and policy.allows(category, critical=critical, message=message)
        )

    def verbose_log_enabled(
        self, category=LOG_ACTION, *, critical=False, message=""
    ):
        policy = self.current_log_policy()
        return bool(
            policy
            and policy.allows_verbose(
                category, critical=critical, message=message
            )
        )

    def log(self, msg, category=LOG_STEP, *, critical=False):
        policy = self.current_log_policy()
        if not policy or not policy.allows(
            category, critical=critical, message=msg
        ):
            return False
        started_ns = time.perf_counter_ns()
        try:
            write_log(
                msg,
                self.callback_msg,
                ui_timestamp=policy.timestamp_enabled,
            )
        finally:
            self.performance.observe_since("log.dispatch", started_ns)
        return True

    def complete_runtime_parameters(self, task_count):
        policy = self.current_log_policy()
        return {
            "task_count": int(task_count),
            "logging": {
                "mode": policy.mode if policy else "disabled",
                "enabled_categories": (
                    list(policy.enabled_categories) if policy else []
                ),
                "ui_timestamp": bool(policy and policy.timestamp_enabled),
            },
            "recognition": {
                "confidence": self.confidence,
                "scale_min": self.min_scale,
                "scale_max": self.max_scale,
                "scale_step": self.scale_step,
                "grayscale": self.enable_grayscale,
                "detect_delay_seconds": self.detect_delay,
                "adaptive_backoff": self.adaptive_backoff,
                "scene_wake": self.scene_wake_enabled,
                "scene_wake_sensitivity": self.scene_wake_sensitivity,
                "scan_region": self.scan_region,
                "scan_regions": list(self.scan_regions),
            },
            "native": {
                "enabled": self.use_native_core,
                "parallel_mode": self.native_parallel_mode,
                "scale_memory_enabled": self.use_native_scale_hint,
                "scale_memory_tier": self.scale_memory_tier,
                "manual_preferred_scales": list(self.scale_memory_manual),
                "scale_memory_custom": self.scale_memory_custom_enabled,
                "preferred_limit": self.scale_memory_preferred_limit,
                "history_limit": self.scale_memory_history_limit,
                "fast_screenshot": self.use_fast_screenshot,
            },
            "actions": {
                "move_seconds": self.move_duration,
                "click_hold_seconds": self.click_hold,
                "step_interval_seconds": self.settlement_wait,
                "timeout_seconds": self.timeout_val,
                "timeout_emergency_stop": self.timeout_stop,
                "dodge_enabled": self.enable_dodge,
                "double_dodge": self.enable_double_dodge,
                "dodge_points": [
                    [self.dodge_x1, self.dodge_y1],
                    [self.dodge_x2, self.dodge_y2],
                ],
                "dodge_click_action": self.dodge_click_action,
                "playback_speed": self.playback_speed,
            },
            "flow": {
                "start_step": self.start_step_index + 1,
                "loop_start": self.loop_start_round,
                "loop_end": self.loop_end_round,
                "loop_mode": self.loop_mode,
                "loop_value": self.loop_val,
                "multi_target_mode": self.multi_target_mode,
                "multi_target_order": self.multi_target_order,
            },
            "failsafes": {
                "task_manager": self.enable_tm_stop,
                "top_right": self.enable_tr_stop,
                "escape_or_middle_button": self.enable_key_stop,
            },
            "privacy": {
                "step_parameter_payload_omits_raw_task_values": True,
                "external_clipboard_contents_logged": False,
                "command_specific_logs_may_include_action_values": True,
                "command_specific_logs_may_include_output_paths": True,
            },
        }

    def performance_snapshot(self):
        report = self.performance.snapshot()
        native_stats = None
        if getattr(self, "native_core", None):
            native_stats = self.native_core.performance_stats()
        if native_stats:
            report["native"] = native_stats
        return report

    def finalize_performance_report(self, outcome):
        self.performance.set_gauge("run.outcome", str(outcome))
        self.performance.set_gauge(
            "template.cache_bytes", int(getattr(self, "scaled_template_cache_bytes", 0))
        )
        self.last_performance_report = self.performance_snapshot()
        return self.last_performance_report

    def report_status(self, loop_count=1, step=0, total=0, cmd=""):
        payload = {
            "loop": int(loop_count),
            "step": int(step),
            "total": int(total),
            "cmd": str(cmd),
        }
        if payload == self._last_status_payload:
            self.performance.increment("status.duplicate_updates_skipped")
            return
        self._last_status_payload = payload
        started_ns = time.perf_counter_ns()
        if self.callback_status:
            try:
                self.callback_status(payload)
            except Exception: pass
        self.performance.increment("status.updates")
        self.performance.observe_since("status.dispatch", started_ns)

    def report_click_indicator(self, x, y, text=""):
        if not self.show_click_indicator or not self.callback_click_indicator:
            return
        started_ns = time.perf_counter_ns()
        try:
            self.callback_click_indicator({
                "x": int(round(float(x))),
                "y": int(round(float(y))),
                "text": str(text or "")
            })
        except Exception:
            pass
        finally:
            self.performance.observe_since("indicator.dispatch", started_ns)

    def positive_int_value(self, value, default=1):
        return positive_int(value, default)

    def non_negative_int_value(self, value, default=0):
        return non_negative_int(value, default)

    def check_stop_flag(self):
        return self.stop_requested or self.global_time_limit_reached()

    def global_time_limit_reached(self):
        deadline = self.global_deadline
        if deadline is None or time.monotonic() < deadline:
            return False
        if not self.time_limit_reached:
            self.time_limit_reached = True
            if self.log_level >= 0:
                self.log(
                    "<font color='green'>>>> 提示: 已达到指定运行时间，任务正常结束</font>",
                    LOG_RUN,
                )
        return True

    def configure_global_deadline(self):
        units = {
            "指定时间(时)": 3600.0,
            "指定时间(分)": 60.0,
            "指定时间(秒)": 1.0,
        }
        multiplier = units.get(self.loop_mode)
        self.time_limit_reached = False
        if multiplier is None:
            self.global_deadline = None
            return
        duration = max(0.0, float(self.loop_val)) * multiplier
        self.global_deadline = time.monotonic() + duration

    def _wait_interruptibly(self, wait_time):
        wait_time = max(0.0, float(wait_time or 0.0))
        if wait_time <= 0:
            return not self.check_stop_flag()
        end_time = time.monotonic() + wait_time
        while time.monotonic() < end_time:
            if self.check_stop_flag():
                return False
            time.sleep(min(0.05, max(0.0, end_time - time.monotonic())))
        return True

    def wait_recognition_interval(self, extra_delay=0.0, wake_context=None):
        base_delay = max(0.0, float(self.detect_delay or 0.0))
        adaptive_delay = max(0.0, float(extra_delay or 0.0))
        use_scene_wake = bool(
            wake_context
            and adaptive_delay > 0.0
            and getattr(self, "scene_wake_enabled", True)
        )
        baseline = ()
        if use_scene_wake:
            baseline = self.begin_scene_monitor(wake_context)
        base_started_ns = time.perf_counter_ns()
        if not self._wait_interruptibly(base_delay):
            return False
        self.performance.observe_since("wait.recognition_base", base_started_ns)
        if adaptive_delay <= 0.0:
            return True
        adaptive_started_ns = time.perf_counter_ns()
        try:
            if use_scene_wake:
                return self.wait_adaptive_scene(
                    adaptive_delay, wake_context, baseline
                )
            return self._wait_interruptibly(adaptive_delay)
        finally:
            self.performance.observe_since(
                "wait.recognition_adaptive", adaptive_started_ns
            )

    def wait_step_interval(self):
        started_ns = time.perf_counter_ns()
        wait_time = max(0.0, float(self.settlement_wait or 0.0))
        try:
            if wait_time <= 0:
                return not self.check_stop_flag()
            end_time = time.monotonic() + wait_time
            while time.monotonic() < end_time:
                if self.check_stop_flag():
                    return False
                time.sleep(min(0.05, max(0.0, end_time - time.monotonic())))
            return True
        finally:
            self.performance.observe_since("wait.step_interval", started_ns)

    def is_wait_command(self, cmd):
        return scheduler_is_wait_command(cmd)

    def task_active_in_loop(self, task, loop_count):
        return scheduler_task_active_in_loop(task, loop_count)

    def task_exhausted_for_run(self, task, step_no):
        run_max = self.non_negative_int_value(task.get("run_max_executions", 0), 0)
        if run_max > 0 and self.step_execution_counts.get(int(step_no), 0) >= run_max:
            return True

        if self.as_bool(task.get("coord_sequence_en", False)):
            end_action = str(task.get("coord_sequence_end_action", "点完后跳过本步"))
            if end_action == "点完后跳过本步":
                points = parse_coordinate_sequence(task.get("coord_sequence_points", ""))
                state = self.coord_sequence_states.get(int(step_no))
                if points and state and int(state.get("index", 0)) >= len(points):
                    return True
        return False

    def task_runnable_in_loop(self, task, step_no, loop_count):
        return self.task_active_in_loop(task, loop_count) and not self.task_exhausted_for_run(task, step_no)

    def loop_number_allowed(self, loop_count):
        return scheduler_loop_number_allowed(
            loop_count,
            loop_mode=self.loop_mode,
            loop_value=self.loop_val,
            loop_end_round=self.loop_end_round,
        )

    def next_runnable_loop(self, tasks, after_loop):
        return scheduler_next_runnable_loop(
            tasks,
            after_loop,
            start_step_index=self.start_step_index,
            loop_start_round=self.loop_start_round,
            loop_end_round=self.loop_end_round,
            loop_mode=self.loop_mode,
            loop_value=self.loop_val,
            exhausted=self.task_exhausted_for_run,
        )

    def next_interval_task(self, tasks, next_idx, loop_count):
        for look_idx in range(max(0, int(next_idx)), len(tasks)):
            task = tasks[look_idx]
            if self.task_runnable_in_loop(task, look_idx + 1, loop_count):
                return task

        next_loop = loop_count + 1
        if self.loop_mode == "单次":
            return None
        if self.loop_end_round > 0 and next_loop > self.loop_end_round:
            return None
        start_idx = min(max(int(getattr(self, "start_step_index", 0)), 0), max(len(tasks) - 1, 0))
        for look_idx in range(start_idx, len(tasks)):
            task = tasks[look_idx]
            if self.task_runnable_in_loop(task, look_idx + 1, next_loop):
                return task
        return None

    def should_wait_step_interval(self, tasks, current_cmd, next_idx, loop_count):
        if max(0.0, float(self.settlement_wait or 0.0)) <= 0:
            return False
        if self.is_wait_command(current_cmd):
            return False
        next_task = self.next_interval_task(tasks, next_idx, loop_count)
        if not next_task:
            return False
        if self.is_wait_command(next_task.get("type")):
            return False
        return True

    def get_cmd_name(self, cmd_val):
        return command_name(cmd_val)

    def parse_coordinate(self, val):
        return parse_coordinate_text(val)

    def parse_float_value(self, value, default=0.0):
        return parse_float_text(value, default)

    def task_window_backend(self):
        backend = self._task_window_backend
        if backend is None:
            from .mapping_backend import WindowMappingBackend

            backend = WindowMappingBackend()
            self._task_window_backend = backend
        return backend

    def close_task_window_backend(self):
        backend = self._task_window_backend
        self._task_window_backend = None
        if backend is not None:
            backend.close()

    def credential_store(self):
        store = self._credential_store
        if store is None:
            from .credentials import CredentialStore
            from .paths import get_base_dir

            store = CredentialStore(self.base_dir or get_base_dir())
            self._credential_store = store
        return store

    def emit_debug_event(self, payload):
        event = dict(payload or {})
        self.run_trace.record(
            f"debug_{event.get('state', 'event')}",
            loop=event.get("loop", 0),
            step=event.get("step", 0),
            command=event.get("command", ""),
            status=event.get("reason", ""),
            duration_ms=event.get("paused_ms", 0.0),
        )
        if event.get("state") == "paused":
            event["variables"] = self.expression_debug_snapshot(
                event.get("step", 0), event.get("loop", 0)
            )
        if self.callback_debug:
            try:
                self.callback_debug(event)
            except Exception:
                pass

    def run_tasks(
        self,
        tasks,
        callback_msg=None,
        callback_status=None,
        callback_click_indicator=None,
        callback_debug=None,
        run_id=None,
    ):
        if run_id is None:
            run_id = self.reserve_run()
        elif not self.active_run_matches(run_id):
            return
        if run_id is None:
            return
        if not self.lifecycle.mark_running(run_id):
            return

        self.close_screenshot_backend()
        self._mss_disabled_for_run = False
        self._mss_failure_logged = False
        self._last_status_payload = None
        self.performance.reset()
        self.performance.set_gauge("run.task_count", len(tasks))
        self.performance.set_gauge(
            "opencv.threads", int(getattr(self, "opencv_threads", 0))
        )
        self.run_trace.reset(task_count=len(tasks))
        self.run_trace.record("run_started")
        if getattr(self, "native_core", None):
            self.native_core.reset_performance_stats()
        self.callback_msg = callback_msg
        self.callback_status = callback_status
        self.callback_click_indicator = callback_click_indicator
        self.callback_debug = callback_debug
        self.debug_session.reset()
        
        self.img_cache = {}
        self.base_templates_cache = {}
        self.scaled_templates_cache = {}
        self.scale_options_cache = {}
        self.point_click_counts = {}
        self.coord_step_states = {}
        self.coord_sequence_states = {}
        self.step_execution_counts = {}
        self.until_condition_baselines = {}
        self.until_condition_counts = {}
        self.until_condition_started_at = {}
        self.miss_streaks = {}
        self.last_target_positions = {}
        self.scene_probe_cursors = {}
        self.pending_fast_matches = {}
        self.scene_signature_cache = {}
        self.reset_expression_runtime()
        self.native_rejection_cache = set()
        self.native_failure_streak = 0
        self._native_disabled_for_run = False
        self._native_disable_reason = ""
        self.template_validation_cache = {}
        self.template_validation_reported = set()
        self.scaled_template_cache_bytes = 0
        if self.verbose_log_enabled(LOG_PARAMETERS):
            self.log(
                format_complete_payload(
                    "完全/运行参数",
                    self.complete_runtime_parameters(len(tasks)),
                ),
                LOG_PARAMETERS,
            )
        preload_started_ns = time.perf_counter_ns()
        preload_ok = self.load_and_precompute(tasks)
        self.performance.observe_since("template.preload", preload_started_ns)
        preload_elapsed_ms = (
            time.perf_counter_ns() - preload_started_ns
        ) / 1_000_000.0
        if self.verbose_log_enabled(LOG_BACKEND):
            self.log(
                format_complete_payload(
                    "完全/资源预载",
                    {
                        "status": "success" if preload_ok else "failed",
                        "elapsed_ms": round(preload_elapsed_ms, 3),
                        "task_count": len(tasks),
                        "source_template_count": len(self.base_templates_cache),
                        "scaled_template_count": sum(
                            len(items)
                            for items in self.scaled_templates_cache.values()
                        ),
                        "scaled_template_cache_bytes": self.scaled_template_cache_bytes,
                    },
                ),
                LOG_BACKEND,
            )
        if not preload_ok:
            self.run_trace.record(
                "preload_finished",
                status="failed",
                duration_ms=preload_elapsed_ms,
            )
            self.last_run_trace = self.run_trace.snapshot()
            self.close_screenshot_backend()
            self.finalize_performance_report("preload_failed")
            self.callback_msg = None
            self.callback_status = None
            self.callback_click_indicator = None
            self.callback_debug = None
            self.debug_session.finish()
            self.finish_run(run_id, "preload_failed")
            if callback_msg:
                callback_msg("资源预加载失败，运行已取消")
            return
        self.run_trace.record(
            "preload_finished",
            status="success",
            duration_ms=preload_elapsed_ms,
        )

        self.configure_global_deadline()
        loop_count = max(0, int(self.loop_start_round) - 1)

        run_outcome = "finished"
        run_error = ""
        try:
            while True:
                loop_count += 1

                if self.global_time_limit_reached():
                    break
                
                if self.loop_end_round > 0 and loop_count > self.loop_end_round:
                    if self.log_level >= 0:
                        self.log(f"<font color='green'>>>> 提示: 已达到全局循环停止轮次 ({self.loop_end_round})，任务正常结束</font>", LOG_RUN)
                    break

                if self.loop_mode == "单次" and loop_count > 1: break
                elif self.loop_mode == "指定次数" and loop_count > self.loop_val:
                    if self.log_level >= 0: self.log(f"<font color='green'>>>> 提示: 已达到指定循环次数 ({int(self.loop_val)}次)，任务正常结束</font>", LOG_RUN)
                    break

                if loop_count < self.loop_start_round:
                    self.report_status(loop_count, 0, len(tasks), "等待循环范围")
                    if self.log_level >= 1:
                        self.log(f"<font color='gray'>循环 #{loop_count} 低于全局起始循环 {self.loop_start_round}，本轮不执行步骤。</font>", LOG_FLOW)
                    continue

                self.report_status(loop_count, 0, len(tasks), "")

                idx = min(max(int(getattr(self, "start_step_index", 0)), 0), max(len(tasks) - 1, 0))
                has_runnable_task = any(
                    self.task_runnable_in_loop(tasks[task_idx], task_idx + 1, loop_count)
                    for task_idx in range(idx, len(tasks))
                )
                if not has_runnable_task:
                    next_loop = self.next_runnable_loop(tasks, loop_count)
                    if next_loop is not None:
                        if self.log_level >= 1:
                            self.log(f"<font color='gray'>循环 #{loop_count} 没有可执行步骤，直接跳至第 {next_loop} 次循环。</font>", LOG_FLOW)
                        loop_count = next_loop - 1
                        continue
                    if self.log_level >= 0:
                        self.log("<font color='green'>>>> 提示: 本次运行已没有当前或未来可执行的步骤，任务正常结束</font>", LOG_RUN)
                    break

                loop_made_progress = False
                while idx < len(tasks):
                    task = tasks[idx]
                    
                    if self.check_stop_flag():
                        if callback_msg: callback_msg("任务由看门狗终止")
                        return

                    step_loop_start = self.positive_int_value(task.get("step_loop_start", 1), 1)
                    step_loop_end = self.non_negative_int_value(task.get("step_loop_end", 0), 0)
                    if loop_count < step_loop_start:
                        if self.log_level >= 2:
                            self.log(f"<font color='gray'>循环 #{loop_count} 步 {idx+1} 尚未到起始循环 {step_loop_start}，跳过本步。</font>", LOG_FLOW)
                        idx += 1
                        continue
                    if step_loop_end > 0 and loop_count > step_loop_end:
                        if self.log_level >= 2:
                            self.log(f"<font color='gray'>循环 #{loop_count} 步 {idx+1} 已超过结束循环 {step_loop_end}，跳过本步。</font>", LOG_FLOW)
                        idx += 1
                        continue

                    breakpoint_enabled = self.as_bool(
                        task.get("debug_breakpoint", False)
                    )
                    breakpoint_active = breakpoint_enabled
                    breakpoint_reason = "breakpoint"
                    breakpoint_detail = ""
                    if breakpoint_enabled and str(
                        task.get("debug_condition", "") or ""
                    ).strip():
                        breakpoint_active, breakpoint_detail = (
                            self.evaluate_breakpoint_condition(
                                task.get("debug_condition", ""),
                                {
                                    "step": idx + 1,
                                    "loop": loop_count,
                                    "attempt": 1,
                                    "success_count": 0,
                                },
                            )
                        )
                        breakpoint_reason = (
                            "breakpoint_condition_error"
                            if breakpoint_detail
                            else "conditional_breakpoint"
                        )
                    debug_allowed, paused_seconds = self.debug_session.before_step(
                        step=idx + 1,
                        loop=loop_count,
                        command=self.get_cmd_name(task.get("type")),
                        breakpoint=breakpoint_active,
                        breakpoint_reason=breakpoint_reason,
                        breakpoint_detail=breakpoint_detail,
                        stop_requested=lambda: self.lifecycle.stop_requested,
                        callback=self.emit_debug_event,
                    )
                    if self.global_deadline is not None and paused_seconds > 0:
                        self.global_deadline += paused_seconds
                    if not debug_allowed:
                        return

                    cmd = task.get("type")
                    val = task.get("value")
                    retry = task.get("retry", 1)
                    no_skip_wait = self.as_bool(task.get("no_skip_wait", False))
                    try: success_skip = max(0, int(float(task.get("success_skip", 0))))
                    except Exception: success_skip = 0
                    try: success_jump = max(0, int(float(task.get("success_jump", 0))))
                    except Exception: success_jump = 0
                    try: fail_skip = max(0, int(float(task.get("fail_skip", 0))))
                    except Exception: fail_skip = 0
                    try: fail_jump = max(0, int(float(task.get("fail_jump", 0))))
                    except Exception: fail_jump = 0
                    point_limit_en = self.as_bool(task.get("point_limit_en", False)) and cmd in [1.0, 2.0, 3.0] and not self.parse_coordinate(val)
                    try: point_limit_count = max(0, int(float(task.get("point_limit_count", 0))))
                    except Exception: point_limit_count = 0
                    coord_step_config = None
                    if cmd in [1.0, 2.0, 3.0] and self.parse_coordinate(val):
                        coord_step_config = self.coord_step_options(task)
                    coord_sequence_config = None
                    if cmd in [1.0, 2.0, 3.0] and self.parse_coordinate(val):
                        coord_sequence_config = self.coord_sequence_options(task)
                        if coord_sequence_config:
                            coord_step_config = None
                    image_click_config = None
                    if cmd in [1.0, 2.0, 3.0] and not self.parse_coordinate(val):
                        image_click_config = self.image_click_point_options(task)
                    search_regions = self.step_search_regions(task, cmd, val)
                    
                    if task.get("custom_en", False):
                        try: task_conf = float(task.get("custom_conf", self.confidence))
                        except Exception: task_conf = self.confidence
                        use_gray = bool(task.get("custom_gray", self.enable_grayscale))
                    else:
                        task_conf = self.confidence
                        use_gray = self.enable_grayscale
                        
                    cache_key = task.get('cache_key', f"{val}_{self.min_scale}_{self.max_scale}_{self.scale_step}_{use_gray}")

                    cmd_name = self.get_cmd_name(cmd)
                    repeat_mode = str(task.get("repeat_mode", "执行一次"))
                    try: repeat_count = max(1, int(float(task.get("repeat_count", 1))))
                    except Exception: repeat_count = 1
                    try: fail_limit = max(1, int(float(task.get("fail_limit", 1))))
                    except Exception: fail_limit = 1
                    run_max_executions = self.non_negative_int_value(task.get("run_max_executions", 0), 0)
                    step_exec_key = idx + 1

                    target_successes = 1
                    if repeat_mode == "指定次数":
                        target_successes = repeat_count
                    elif repeat_mode == "无限重复":
                        target_successes = None

                    attempt = 0
                    success_count = 0
                    consecutive_failures = 0
                    step_failed_for_branch = False
                    step_skipped_no_branch = False
                    last_status = None
                    step_wall_start = time.monotonic()

                    while target_successes is None or success_count < target_successes:
                        if self.check_stop_flag(): return
                        if run_max_executions > 0 and self.step_execution_counts.get(step_exec_key, 0) >= run_max_executions:
                            step_skipped_no_branch = True
                            if self.log_level >= 0:
                                self.log(f"<font color='gray'>循环 #{loop_count} 步 {idx+1} ({cmd_name}) 已达到本次运行上限 {run_max_executions} 次，跳过本步。</font>", LOG_FLOW)
                            break
                        if no_skip_wait and self.timeout_val > 0 and (time.monotonic() - step_wall_start > self.timeout_val):
                            status = "timeout"
                            step_duration = time.monotonic() - step_wall_start
                            if self.log_level >= 0:
                                self.log(f"<font color='orange'>循环 #{loop_count} 步 {idx+1} ({cmd_name}) 禁止跳过等待超时，耗时: {step_duration:.2f}s</font>", LOG_STEP)
                            if self.timeout_stop:
                                if self.log_enabled(LOG_CRITICAL, critical=True):
                                    self.log(f"<font color='red'><b>    -> [超时急停] 步骤 {idx+1} 达到单步超时，已停止全部循环。</b></font>", LOG_CRITICAL, critical=True)
                                self.stop()
                                return
                            step_failed_for_branch = True
                            break
                        attempt += 1

                        if target_successes is None:
                            attempt_label = f"{attempt}/∞"
                        elif target_successes > 1:
                            attempt_label = f"{success_count + 1}/{target_successes}"
                        else:
                            attempt_label = ""

                        status_cmd_name = f"{cmd_name} {attempt_label}".strip()
                        step_info = {
                            'step': idx + 1,
                            'loop': loop_count,
                            'cmd': status_cmd_name,
                            'attempt': attempt,
                            'success_count': success_count,
                        }
                        step_start_time = time.monotonic()
                        collect_step_timing = self.verbose_log_enabled(LOG_TIMING)
                        step_metrics_before = (
                            self.performance_snapshot()
                            if collect_step_timing
                            else None
                        )
                        self.report_status(loop_count, idx + 1, len(tasks), status_cmd_name)

                        needs_recognition_wait = (cmd in [1.0, 2.0, 3.0, 8.0] and not self.parse_coordinate(val)) or cmd == TASK_TYPE_UNTIL
                        extra_delay = self.adaptive_extra_delay(val, step_info) if (cmd in [1.0, 2.0, 3.0, 8.0] and not self.parse_coordinate(val)) else 0.0
                        wake_context = None
                        if extra_delay > 0.0 and cmd in [1.0, 2.0, 3.0, 8.0] and not self.parse_coordinate(val):
                            wake_context = self.recognition_wake_context(
                                val,
                                cache_key,
                                task_conf,
                                use_gray,
                                search_regions,
                                allow_fast_probe=(
                                    not point_limit_en
                                    and self.multi_target_mode != "全部匹配"
                                ),
                            )
                        if self.verbose_log_enabled(LOG_PARAMETERS):
                            coordinate = self.parse_coordinate(val)
                            is_image_target = (
                                cmd in [1.0, 2.0, 3.0, 8.0]
                                and coordinate is None
                            )
                            target_summary = {
                                "kind": (
                                    "coordinate"
                                    if coordinate is not None
                                    else "image"
                                    if is_image_target
                                    else "redacted_value"
                                ),
                                "coordinate": list(coordinate) if coordinate else None,
                                "image_name": (
                                    os.path.basename(str(val))
                                    if is_image_target
                                    else None
                                ),
                                "raw_value_length": len(str(val or "")),
                            }
                            scale_options = None
                            if is_image_target:
                                scale_options = list(
                                    self.scale_options_for(cache_key)
                                )
                            self.log(
                                format_complete_payload(
                                    "完全/步骤参数",
                                    {
                                        "context": {
                                            "loop": loop_count,
                                            "step": idx + 1,
                                            "command": cmd_name,
                                            "attempt": attempt,
                                            "success_count": success_count,
                                            "total_steps": len(tasks),
                                        },
                                        "target": target_summary,
                                        "recognition": {
                                            "required": needs_recognition_wait,
                                            "confidence": task_conf,
                                            "grayscale": use_gray,
                                            "scale_options": scale_options,
                                            "search_regions": search_regions or [],
                                            "adaptive_extra_delay_seconds": extra_delay,
                                            "scene_wake_eligible": bool(wake_context),
                                            "multi_target_mode": self.multi_target_mode,
                                            "multi_target_order": self.multi_target_order,
                                            "point_limit_enabled": point_limit_en,
                                            "point_limit_count": point_limit_count,
                                            "image_click_point": image_click_config,
                                        },
                                        "execution": {
                                            "retry": retry,
                                            "no_skip_wait": no_skip_wait,
                                            "repeat_mode": repeat_mode,
                                            "repeat_target": target_successes,
                                            "failure_limit": fail_limit,
                                            "run_execution_limit": run_max_executions,
                                            "coordinate_step_enabled": bool(coord_step_config),
                                            "coordinate_sequence_enabled": bool(coord_sequence_config),
                                            "timeout_seconds": self.timeout_val,
                                            "timeout_emergency_stop": self.timeout_stop,
                                        },
                                        "branches": {
                                            "success_skip": success_skip,
                                            "success_jump": success_jump,
                                            "failure_skip": fail_skip,
                                            "failure_jump": fail_jump,
                                        },
                                        "privacy": (
                                            "this step-parameter payload omits raw task values and full paths; "
                                            "command-specific detailed logs remain unchanged"
                                        ),
                                    },
                                ),
                                LOG_PARAMETERS,
                            )
                        pre_wait_started_ns = time.perf_counter_ns()
                        pre_execute_wait_ms = 0.0
                        if needs_recognition_wait or no_skip_wait:
                            if not self.wait_recognition_interval(extra_delay, wake_context):
                                return
                            pre_execute_wait_ms = (
                                time.perf_counter_ns() - pre_wait_started_ns
                            ) / 1_000_000.0
                        if search_regions and self.verbose_log_enabled(LOG_RECOGNITION):
                            self.log(f"    <font color='gray'>本步识别区域: {format_region_text(search_regions[0])}</font>", LOG_RECOGNITION)
                        execute_started_ns = time.perf_counter_ns()
                        status = self.execute_task_once(cmd, val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en, point_limit_count, coord_step_config, image_click_config, task, coord_sequence_config, search_regions)
                        execute_ms = (
                            time.perf_counter_ns() - execute_started_ns
                        ) / 1_000_000.0
                        last_status = status
                        if status != "skipped":
                            self.last_step_success = status in ("success", "condition_true")
                        if status != "skipped":
                            loop_made_progress = True
                            self.step_execution_counts[step_exec_key] = self.step_execution_counts.get(step_exec_key, 0) + 1

                        step_duration = time.monotonic() - step_start_time
                        if collect_step_timing:
                            self.log(
                                format_complete_payload(
                                    "完全/步骤耗时",
                                    complete_step_timing_payload(
                                        step_metrics_before,
                                        self.performance_snapshot(),
                                        total_ms=step_duration * 1000.0,
                                        pre_execute_wait_ms=pre_execute_wait_ms,
                                        execute_ms=execute_ms,
                                    ),
                                ),
                                LOG_TIMING,
                            )
                        self.run_trace.record(
                            "step_result",
                            loop=loop_count,
                            step=idx + 1,
                            command=cmd_name,
                            status=status,
                            duration_ms=step_duration * 1000.0,
                            attempt=attempt,
                        )
                        if self.log_level >= 0:
                            status_str = "完成"
                            color = "gray"
                            if status == "success": status_str = "完成"; color = "gray"
                            elif status == "timeout":
                                status_str = "超时急停" if self.timeout_stop else "超时失败"
                                color = "red" if self.timeout_stop else "orange"
                            elif status == "not_found":
                                status_str = "未找目标，继续等待" if no_skip_wait else "未找目标失败"
                                color = "orange"
                            elif status == "condition_true":
                                status_str = "条件满足"
                                color = "green"
                            elif status == "condition_false":
                                status_str = "条件未满足"
                                color = "orange"
                            elif status == "skipped":
                                status_str = "已跳过"
                                color = "gray"
                            elif status == "error": status_str = "执行异常"; color = "red"
                            elif status == "stopped": status_str = "已停止"; color = "red"

                            repeat_suffix = f" 第{attempt_label}次" if attempt_label else ""
                            self.log(f"<font color='{color}'>循环 #{loop_count} 步 {idx+1} ({cmd_name}){repeat_suffix} {status_str}，耗时: {step_duration:.2f}s</font>", LOG_STEP)

                        if status == "stopped":
                            return
                        if status == "skipped":
                            step_skipped_no_branch = True
                            break

                        if status == "timeout" and self.timeout_stop:
                            if self.log_enabled(LOG_CRITICAL, critical=True):
                                self.log(f"<font color='red'><b>    -> [超时急停] 步骤 {idx+1} 达到单步超时，已停止全部循环。</b></font>", LOG_CRITICAL, critical=True)
                            self.stop()
                            return

                        expression_false = (
                            cmd == TASK_TYPE_EXPRESSION and status == "condition_false"
                        )
                        if status in ["timeout", "not_found", "error"] or expression_false:
                            if no_skip_wait and status != "timeout":
                                if self.log_level >= 1:
                                    self.log("    -> 本步骤已启用禁止跳过，将继续等待本步骤成功。", LOG_FLOW)
                                if not self.is_wait_command(cmd) and not self.wait_step_interval():
                                    return
                                continue
                            consecutive_failures += 1
                            if consecutive_failures >= fail_limit:
                                step_failed_for_branch = True
                                if self.log_level >= 0:
                                    self.log(f"<font color='#9C27B0'><b>    -> [条件分支] 步骤 {idx+1} 连续失败 {consecutive_failures} 次，结束本步。</b></font>", LOG_FLOW)
                                break
                        else:
                            success_count += 1
                            consecutive_failures = 0

                        if target_successes is None or success_count < target_successes:
                            if not self.is_wait_command(cmd) and not self.wait_step_interval():
                                return

                    transition_started_ns = time.perf_counter_ns()
                    next_idx = idx + 1
                    condition_branch_handled = False
                    if step_skipped_no_branch:
                        next_idx = idx + 1
                    elif cmd == TASK_TYPE_UNTIL and not step_failed_for_branch and last_status in ["condition_true", "condition_false"]:
                        condition_branch_handled = True
                        if last_status == "condition_true":
                            self.reset_until_runtime({'step': idx + 1})
                            try: true_jump = max(0, int(float(task.get("until_true_jump", 0))))
                            except Exception: true_jump = 0
                            if true_jump > 0:
                                next_idx = true_jump - 1
                                if self.log_level >= 0:
                                    self.log(f"<font color='#4CAF50'><b>    -> [直到条件成立] 条件满足，跳至第 {true_jump} 步继续执行。</b></font>", LOG_FLOW)
                            else:
                                next_idx = idx + 1
                                if self.log_level >= 1:
                                    self.log("<font color='#4CAF50'>    -> [直到条件成立] 条件满足，继续下一步。</font>", LOG_FLOW)
                        else:
                            reached, reason, false_count, elapsed = self.until_false_runtime(task, {'step': idx + 1})
                            if reached:
                                action = str(task.get("until_on_limit", "继续下一步"))
                                self.reset_until_runtime({'step': idx + 1})
                                if self.log_level >= 0:
                                    self.log(f"<font color='orange'><b>    -> [直到条件成立] {reason}，达到保护上限，处理方式：{action}。</b></font>", LOG_FLOW)
                                if action == "停止脚本":
                                    self.stop()
                                    return
                                if action == "按失败处理":
                                    step_failed_for_branch = True
                                    condition_branch_handled = False
                                else:
                                    next_idx = idx + 1
                            else:
                                try: false_jump = max(0, int(float(task.get("until_false_jump", 1))))
                                except Exception: false_jump = 1
                                if false_jump > 0:
                                    next_idx = false_jump - 1
                                    if self.log_level >= 0:
                                        self.log(f"<font color='#FF9800'><b>    -> [直到条件成立] 条件未满足（第 {false_count} 次，已等待 {elapsed:.1f}s），跳回第 {false_jump} 步。</b></font>", LOG_FLOW)
                                else:
                                    next_idx = idx + 1
                                    self.reset_until_runtime({'step': idx + 1})
                                    if self.log_level >= 1:
                                        self.log("<font color='#FF9800'>    -> [直到条件成立] 条件未满足，但未设置跳回步骤，继续下一步。</font>", LOG_FLOW)

                    if not condition_branch_handled and step_failed_for_branch:
                        if fail_jump > 0:
                            next_idx = fail_jump - 1
                            if self.log_level >= 0:
                                self.log(f"<font color='#9C27B0'><b>    -> [条件分支] 失败后跳至第 {fail_jump} 步继续执行</b></font>", LOG_FLOW)
                        elif fail_skip > 0:
                            next_idx = idx + fail_skip + 1
                            if self.log_level >= 0:
                                self.log(f"<font color='#9C27B0'><b>    -> [条件分支] 失败后跳过后续 {fail_skip} 步指令</b></font>", LOG_FLOW)
                    elif not condition_branch_handled:
                        if success_jump > 0:
                            next_idx = success_jump - 1
                            if self.log_level >= 0:
                                self.log(f"<font color='#4CAF50'><b>    -> [条件分支] 成功后跳至第 {success_jump} 步继续执行</b></font>", LOG_FLOW)
                        elif success_skip > 0:
                            next_idx = idx + success_skip + 1
                            if self.log_level >= 0:
                                self.log(f"<font color='#4CAF50'><b>    -> [条件分支] 成功后跳过后续 {success_skip} 步指令</b></font>", LOG_FLOW)

                    interval_waited = self.should_wait_step_interval(
                        tasks, cmd, next_idx, loop_count
                    )
                    if interval_waited:
                        if not self.wait_step_interval():
                            return

                    if self.verbose_log_enabled(LOG_FLOW):
                        self.log(
                            format_complete_payload(
                                "完全/步骤转移",
                                {
                                    "loop": loop_count,
                                    "step": idx + 1,
                                    "status": str(last_status or ""),
                                    "attempts": attempt,
                                    "success_count": success_count,
                                    "consecutive_failures": consecutive_failures,
                                    "failed_branch": step_failed_for_branch,
                                    "condition_branch_handled": condition_branch_handled,
                                    "next_step": (
                                        next_idx + 1
                                        if 0 <= next_idx < len(tasks)
                                        else 0
                                    ),
                                    "step_interval_applied": interval_waited,
                                    "configured_step_interval_seconds": self.settlement_wait,
                                    "transition_elapsed_ms": round(
                                        (
                                            time.perf_counter_ns()
                                            - transition_started_ns
                                        )
                                        / 1_000_000.0,
                                        3,
                                    ),
                                },
                            ),
                            LOG_FLOW,
                        )

                    self.run_trace.record(
                        "transition",
                        loop=loop_count,
                        step=idx + 1,
                        command=cmd_name,
                        status=str(last_status or ""),
                        next_step=next_idx + 1 if 0 <= next_idx < len(tasks) else 0,
                    )
                    idx = next_idx

                if self.check_stop_flag(): return
                if not loop_made_progress:
                    next_loop = self.next_runnable_loop(tasks, loop_count)
                    if next_loop is not None:
                        if self.log_level >= 1:
                            self.log(f"<font color='gray'>循环 #{loop_count} 的步骤均已永久跳过，直接跳至第 {next_loop} 次循环。</font>", LOG_FLOW)
                        loop_count = next_loop - 1
                        continue
                    if self.log_level >= 0:
                        self.log("<font color='green'>>>> 提示: 所有步骤均已完成或达到本次运行上限，任务正常结束</font>", LOG_RUN)
                    break
                
        except Exception as e:
            run_outcome = "error"
            run_error = str(e)
            self.log(f"<font color='red'>引擎异常: {e}</font>", LOG_CRITICAL, critical=True)
        finally:
            if run_outcome == "finished" and self.lifecycle.state is RunState.STOPPING:
                run_outcome = "stopped"
            self.close_screenshot_backend()
            self.close_task_window_backend()
            self.run_trace.record("run_finished", status=run_outcome)
            self.last_run_trace = self.run_trace.snapshot()
            report = self.finalize_performance_report(run_outcome)
            if self.log_enabled(LOG_TIMING):
                self.log(
                    "<font color='gray'>性能摘要："
                    f"{concise_performance_summary(report)}</font>",
                    LOG_TIMING,
                )
                self.last_performance_report = self.performance_snapshot()
            if self.verbose_log_enabled(LOG_TIMING):
                self.log(
                    format_complete_payload(
                        "完全/运行性能报告",
                        report,
                    ),
                    LOG_TIMING,
                )
            self.callback_msg = None
            self.callback_status = None
            self.callback_click_indicator = None
            self.callback_debug = None
            self.debug_session.finish()
            self.finish_run(run_id, run_outcome, run_error)
            policy = self.current_log_policy()
            if callback_msg and policy and policy.allows(LOG_RUN):
                write_log(
                    "结束",
                    callback_msg,
                    ui_timestamp=policy.timestamp_enabled,
                )
