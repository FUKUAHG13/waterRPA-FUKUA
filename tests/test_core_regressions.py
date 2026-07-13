import os
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QThread, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from shiboken6 import isValid

import fukuaRPA as wrpa
import fukua_rpa.engine_vision as engine_vision_module
from fukua_rpa.constants import NATIVE_CORE_RELEASE_VERSION


class CoreRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.priority_patch = mock.patch.object(wrpa.RPAEngine, "set_high_priority", lambda _self: None)
        self.priority_patch.start()

    def tearDown(self):
        self.priority_patch.stop()
        self.app.processEvents()

    def test_native_core_api_version(self):
        core = wrpa.NativeVisionCore()
        self.assertTrue(core.available, core.load_error)
        self.assertGreaterEqual(core.version, NATIVE_CORE_RELEASE_VERSION)

    def test_native_core_declares_required_capabilities(self):
        core = wrpa.NativeVisionCore()
        self.assertTrue(core.available, core.load_error)
        capabilities = core.capabilities()
        for name in (
            "gdi_capture",
            "multi_region",
            "multi_scale",
            "grayscale",
            "color",
            "find_all",
            "work_budget",
            "single_capture_per_region",
            "abi_metadata",
            "bounded_job_pool",
            "preferred_scale_fallback",
            "preferred_scale_list",
            "explicit_scale_only",
            "low_res_scene_fingerprint",
            "dxgi_scene_change",
        ):
            self.assertTrue(capabilities.get(name), name)
        self.assertTrue(core.has_extended_search)
        self.assertTrue(core.has_preferred_scale_list)
        self.assertTrue(core.has_explicit_scale_only)
        self.assertTrue(core.has_scene_fingerprint)
        self.assertTrue(core.has_dxgi_scene_change)

    def test_native_core_abi_and_static_runtime_contract(self):
        core = wrpa.NativeVisionCore()
        self.assertTrue(core.available, core.load_error)
        abi = core.abi_snapshot()
        self.assertTrue(abi["metadata_available"])
        self.assertTrue(abi["compatible"])
        self.assertEqual(abi["pointer_bits"], 64)
        self.assertEqual(abi["struct_sizes"], abi["python_struct_sizes"])
        for flag in ("x64", "static_crt", "cpp17", "windows10_target", "msvc"):
            self.assertTrue(abi["build_flags"].get(flag), flag)

    def test_native_multiscale_search_captures_each_region_once_and_caches_template(self):
        core = wrpa.NativeVisionCore()
        if not core.available or core.version < 10500:
            self.skipTest(core.load_error or "native performance API unavailable")
        pixels = [
            ((x * 47 + y * 19) % 255, (x * 11 + y * 61) % 255, (x * 73 + y * 7) % 255)
            for y in range(6)
            for x in range(6)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "native_template.png")
            image = Image.new("RGB", (6, 6))
            image.putdata(pixels)
            image.save(path)

            core.reset_performance_stats()
            first = core.find_template(
                path, [(0, 0, 48, 48)], 0.8, 1.2, 0.05, True, 0.99
            )
            first_stats = core.performance_stats()
            second = core.find_template(
                path, [(0, 0, 48, 48)], 0.8, 1.2, 0.05, True, 0.99
            )
            second_stats = core.performance_stats()

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first_stats["captures"], 1)
        self.assertEqual(first_stats["integral_builds"], 1)
        self.assertEqual(first_stats["template_cache_misses"], 1)
        self.assertEqual(second_stats["captures"], 2)
        self.assertEqual(second_stats["integral_builds"], 2)
        self.assertGreaterEqual(second_stats["template_cache_hits"], 1)

    def test_native_budget_fallback_happens_before_screen_capture(self):
        core = wrpa.NativeVisionCore()
        if not core.available or core.version < 10500:
            self.skipTest(core.load_error or "native performance API unavailable")
        rng_pixels = [
            ((x * 17 + y * 31) % 255, (x * 43 + y * 11) % 255, (x * 29 + y * 47) % 255)
            for y in range(50)
            for x in range(50)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "large_template.png")
            image = Image.new("RGB", (50, 50))
            image.putdata(rng_pixels)
            image.save(path)
            core.reset_performance_stats()
            result = core.find_template(
                path, [(0, 0, 1920, 1080)], 1.0, 1.0, 0.05, True, 0.8
            )
            stats = core.performance_stats()

        self.assertIsNone(result)
        self.assertIn("work budget exceeded", core.load_error)
        self.assertEqual(stats["captures"], 0)
        self.assertEqual(stats["integral_builds"], 0)
        self.assertEqual(stats["work_budget_fallbacks"], 1)

    def test_flat_template_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "flat.png")
            Image.new("RGB", (8, 8), (80, 80, 80)).save(path)
            valid, reason = wrpa.template_detail_status(path, True)
            self.assertFalse(valid)
            self.assertTrue(reason)

    def test_scale_variant_limit_is_enforced(self):
        values = wrpa.build_scale_values(0.8, 1.2, 0.05)
        self.assertEqual(len(values) + 1, 9)
        with self.assertRaises(ValueError):
            wrpa.build_scale_values(0.1, 2.0, 0.01)

    def test_native_empty_result_does_not_repeat_python_search(self):
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        engine.native_find_targets = lambda *args, **kwargs: []
        engine.quick_search_region = lambda *args, **kwargs: None
        calls = {"fallback": 0}

        def fallback(*args, **kwargs):
            calls["fallback"] += 1
            return None

        engine.find_target_in_screenshot = fallback
        engine.iter_search_screenshots = lambda *args, **kwargs: iter(
            [(Image.new("RGB", (4, 4)), 0, 0)]
        )
        self.assertIsNone(engine.find_target_optimized("missing.png", "cache", 0.8, True))
        self.assertEqual(calls["fallback"], 0)

    def test_fast_search_remembers_and_reuses_the_successful_native_scale(self):
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        engine.min_scale = 0.8
        engine.max_scale = 1.2
        engine.scale_step = 0.05
        engine.quick_search_region = lambda *args, **kwargs: None
        fake_native = mock.Mock()
        fake_native.available = True
        fake_native.load_error = ""
        fake_native.last_result_code = 1
        fake_native.find_template.return_value = [
            (120.0, 80.0, 1.15, 0.96, 8.0)
        ]
        engine.native_core = fake_native
        pixels = [
            ((x * 31 + y * 7) % 255, (x * 13 + y * 17) % 255, (x * 19 + y * 23) % 255)
            for y in range(8)
            for x in range(8)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "template.png")
            image = Image.new("RGB", (8, 8))
            image.putdata(pixels)
            image.save(path)
            first = engine.find_target_optimized(path, "cache", 0.8, True)
            second = engine.find_target_optimized(path, "cache", 0.8, True)

        self.assertEqual(first[2], 1.15)
        self.assertEqual(second[2], 1.15)
        first_call = fake_native.find_template.call_args_list[0]
        second_call = fake_native.find_template.call_args_list[1]
        self.assertEqual(first_call.kwargs["preferred_scales"], ())
        self.assertEqual(second_call.kwargs["preferred_scales"], (1.15,))
        self.assertEqual(second_call.kwargs["parallel_mode"], "auto")
        counters = engine.performance.snapshot()["counters"]
        self.assertEqual(counters["match.native_scale_hint_hits"], 1)

    def test_time_limit_stops_an_inner_self_jump(self):
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        # Keep the source ASCII-only so Windows shell encoding cannot corrupt the mode.
        engine.loop_mode = "\u6307\u5b9a\u65f6\u95f4(\u79d2)"
        engine.loop_val = 0.03
        engine.loop_start_round = 1
        engine.start_step_index = 0
        engine.settlement_wait = 0
        engine.detect_delay = 0
        engine.load_and_precompute = lambda tasks: True
        executions = {"count": 0}

        def execute(*args, **kwargs):
            executions["count"] += 1
            time.sleep(0.005)
            return "success"

        engine.execute_task_once = execute
        worker = threading.Thread(
            target=engine.run_tasks,
            args=([{"type": 4.0, "value": "x", "success_jump": "1"}],),
            daemon=True,
        )
        worker.start()
        worker.join(0.2)
        if worker.is_alive():
            engine.stop()
            worker.join(1.0)
        self.assertFalse(worker.is_alive())
        self.assertLess(executions["count"], 20)

    def test_screenshot_failure_returns_error(self):
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        engine.capture_screenshot = lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("capture failed")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            status = engine.execute_task_once(
                9.0,
                os.path.join(temp_dir, "shot.png"),
                1,
                {"loop": 1, "step": 1},
                "",
                0.8,
                True,
            )
        self.assertEqual(status, "error")

    def test_mss_failure_is_circuit_broken_for_the_current_run(self):
        class FailingMssInstance:
            monitors = [{"left": 0, "top": 0, "width": 32, "height": 32}]

            def __init__(self):
                self.grab_calls = 0

            def grab(self, _monitor):
                self.grab_calls += 1
                raise OSError("simulated mss failure")

            def close(self):
                pass

        instance = FailingMssInstance()
        fake_mss_module = mock.Mock()
        fake_mss_module.MSS = None
        fake_mss_module.mss.return_value = instance
        fallback = Image.new("RGB", (32, 32), "white")
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        engine.performance.reset()
        with mock.patch.object(engine_vision_module, "HAS_MSS", True), \
             mock.patch.object(engine_vision_module, "mss", fake_mss_module), \
             mock.patch.object(engine_vision_module.pyautogui, "screenshot", return_value=fallback):
            engine.capture_screenshot(None)
            engine.capture_screenshot(None)

        report = engine.performance.snapshot()
        self.assertEqual(instance.grab_calls, 1)
        self.assertEqual(fake_mss_module.mss.call_count, 1)
        self.assertEqual(report["counters"]["screenshot.fallbacks"], 1)
        self.assertEqual(report["counters"]["screenshot.pyautogui_calls"], 2)

    def test_opencv_base_template_conversion_is_reused(self):
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        engine.use_native_core = False
        pixels = [
            ((x * 31 + y * 17) % 255, (x * 13 + y * 29) % 255, (x * 7 + y * 43) % 255)
            for y in range(6)
            for x in range(6)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "template.png")
            template = Image.new("RGB", (6, 6))
            template.putdata(pixels)
            template.save(path)
            task = {"type": 1.0, "value": path}
            self.assertTrue(engine.load_and_precompute([task]))
            screenshot = Image.new("RGB", (20, 20), "black")
            screenshot.paste(template, (7, 8))
            engine.performance.reset()
            for _index in range(2):
                found = engine.find_target_in_screenshot(
                    path, task["cache_key"], 0.8, True, screenshot, 0, 0
                )
                self.assertIsNotNone(found)

        counters = engine.performance.snapshot()["counters"]
        self.assertEqual(counters.get("template.base_cache_misses", 0), 0)
        self.assertEqual(counters["template.base_cache_hits"], 2)

    def test_engine_persists_a_bounded_performance_report_after_run(self):
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        engine.settlement_wait = 0
        engine.run_tasks([{"type": 5.0, "value": "0"}])
        report = engine.last_performance_report
        self.assertEqual(report["gauges"]["run.outcome"], "finished")
        self.assertEqual(report["timings"]["action.total"]["count"], 1)
        self.assertLessEqual(
            report["timings"]["action.total"]["sampled_count"],
            report["sample_limit"],
        )
        trace_events = engine.last_run_trace["events"]
        self.assertEqual(trace_events[0]["event"], "run_started")
        self.assertTrue(
            any(event["event"] == "step_result" for event in trace_events)
        )
        self.assertEqual(trace_events[-1]["event"], "run_finished")

    def test_until_conditions_share_one_snapshot_for_the_same_region(self):
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        pixels = [
            ((x * 41 + y * 17) % 255, (x * 23 + y * 37) % 255, (x * 53 + y * 11) % 255)
            for y in range(20)
            for x in range(20)
        ]
        image = Image.new("RGB", (20, 20))
        image.putdata(pixels)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "condition.png")
            image.save(path)
            capture = mock.Mock(return_value=(image.copy(), 10, 20))
            engine.capture_screenshot = capture
            task = {
                "until_logic": "全部满足",
                "until_cond1_en": True,
                "until_cond1_mode": "区域变成指定图片",
                "until_cond1_image": path,
                "until_cond1_region": "10,20,20,20",
                "until_cond1_similarity": "99",
                "until_cond2_en": True,
                "until_cond2_mode": "区域变成指定图片",
                "until_cond2_image": path,
                "until_cond2_region": "10,20,20,20",
                "until_cond2_similarity": "99",
            }
            status = engine.execute_until_conditions(
                task, {"step": 1, "loop": 1}, True
            )

        self.assertEqual(status, "condition_true")
        self.assertEqual(capture.call_count, 1)
        counters = engine.performance.snapshot()["counters"]
        self.assertEqual(counters["condition.screenshot_cache_misses"], 1)
        self.assertEqual(counters["condition.screenshot_cache_hits"], 1)

    def test_duplicate_status_payload_does_not_refresh_the_ui_twice(self):
        engine = wrpa.RPAEngine()
        updates = []
        engine.callback_status = updates.append
        engine.report_status(2, 3, 8, "左键单击")
        engine.report_status(2, 3, 8, "左键单击")
        engine.report_status(2, 4, 8, "等待")

        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[-1]["step"], 4)
        counters = engine.performance.snapshot()["counters"]
        self.assertEqual(counters["status.duplicate_updates_skipped"], 1)

    def test_native_work_budget_fallback_is_cached_for_the_run(self):
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        fake_native = mock.Mock()
        fake_native.available = True
        fake_native.load_error = ""
        fake_native.last_result_code = 0

        def reject(*_args, **_kwargs):
            fake_native.load_error = "预算已超限"
            fake_native.last_result_code = -2
            return None

        fake_native.find_template.side_effect = reject
        engine.native_core = fake_native
        pixels = [
            ((x * 31 + y * 7) % 255, (x * 13 + y * 17) % 255, (x * 19 + y * 23) % 255)
            for y in range(8)
            for x in range(8)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "template.png")
            image = Image.new("RGB", (8, 8))
            image.putdata(pixels)
            image.save(path)
            first = engine.native_find_targets(path, "key", 0.8, True)
            second = engine.native_find_targets(path, "key", 0.8, True)

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(fake_native.find_template.call_count, 1)
        counters = engine.performance.snapshot()["counters"]
        self.assertEqual(counters["match.native_rejections_cached"], 1)
        self.assertEqual(counters["match.native_rejection_cache_hits"], 1)

    def test_repeated_native_failures_trip_run_local_circuit_breaker(self):
        engine = wrpa.RPAEngine()
        engine.log_level = -1
        fake_native = mock.Mock()
        fake_native.available = True
        fake_native.load_error = "capture failed"
        fake_native.last_result_code = -1
        fake_native.find_template.return_value = None
        engine.native_core = fake_native
        pixels = [
            ((x * 29 + y * 5) % 255, (x * 7 + y * 31) % 255, (x * 11 + y * 17) % 255)
            for y in range(8)
            for x in range(8)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "template.png")
            image = Image.new("RGB", (8, 8))
            image.putdata(pixels)
            image.save(path)
            for _index in range(4):
                self.assertIsNone(
                    engine.native_find_targets(path, "key", 0.8, True)
                )

        self.assertEqual(fake_native.find_template.call_count, 3)
        self.assertTrue(engine._native_disabled_for_run)
        counters = engine.performance.snapshot()["counters"]
        self.assertEqual(counters["match.native_circuit_breaker_trips"], 1)
        self.assertEqual(counters["match.native_circuit_breaker_hits"], 1)

    def test_deleting_step_closes_its_settings_dialog(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             mock.patch.object(wrpa.RPAWindow, "register_global_hotkeys", lambda _self: True), \
             mock.patch.object(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok):
            window = wrpa.RPAWindow(base_dir=temp_dir)
            window.add_row({"type": 1.0, "value": "10,10"})
            row = window.task_list.itemWidget(window.task_list.item(0))
            row.open_custom_config()
            self.app.processEvents()
            dialog = row.config_dialog
            self.assertEqual(
                os.path.abspath(dialog.dialog_settings.fileName()),
                os.path.abspath(os.path.join(temp_dir, "config.ini")),
            )
            window.del_row(row)
            self.app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
            with self.assertRaises(RuntimeError):
                dialog.isVisible()
            self.assertFalse(isValid(row))
            self.assertFalse(window.task_config_dialogs)
            window.close()

    def test_corrupt_main_config_recovers_from_atomic_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             mock.patch.object(wrpa.RPAWindow, "register_global_hotkeys", lambda _self: True), \
             mock.patch.object(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok):
            first = wrpa.RPAWindow(base_dir=temp_dir)
            first.add_row({"type": 1.0, "value": "10,10"})
            self.assertTrue(first.persist_profiles_state(force=True))
            first.close()
            self.app.processEvents()

            settings = QSettings(os.path.join(temp_dir, "config.ini"), QSettings.IniFormat)
            settings.setValue("profiles_json", "{broken")
            settings.sync()

            recovered = wrpa.RPAWindow(base_dir=temp_dir)
            self.assertTrue(recovered._config_recovery_message)
            self.assertEqual(recovered.task_list.count(), 1)
            self.assertTrue(os.path.isfile(recovered.profile_backup_path))
            recovered.close()

    def test_recording_abort_discards_events(self):
        class FakeMain(QWidget):
            def __init__(self):
                super().__init__()
                self.rows = []

            def add_row(self, task):
                self.rows.append(task)

            def append_log(self, _text):
                pass

        class FakeHook(QThread):
            finished_signal = Signal(list)

            def __init__(self):
                super().__init__()
                self.stop_event = threading.Event()
                self.ready_event = threading.Event()

            def run(self):
                self.ready_event.set()
                self.stop_event.wait()
                self.finished_signal.emit([(time.monotonic(), "left", (11, 22))])

            def stop(self):
                self.stop_event.set()

        main = FakeMain()
        recorder = wrpa.RecorderUI(main)
        hook = FakeHook()
        hook.finished_signal.connect(recorder.on_recorded)
        recorder.hook_thread = hook
        hook.start()
        self.assertTrue(hook.ready_event.wait(1.0))
        recorder.abort()
        self.app.processEvents()
        self.assertEqual(main.rows, [])


if __name__ == "__main__":
    unittest.main()
