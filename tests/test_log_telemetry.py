import unittest

from fukua_rpa.log_telemetry import (
    complete_step_timing_payload,
    format_complete_payload,
    performance_delta,
)


class LogTelemetryTests(unittest.TestCase):
    def test_performance_delta_uses_cumulative_totals_and_counters(self):
        before = {
            "timings": {"vision.search": {"total_ms": 10.0}},
            "counters": {"match.native_calls": 3},
        }
        after = {
            "timings": {
                "vision.search": {"total_ms": 25.5},
                "screenshot.total": {"total_ms": 4.0},
                "condition.evaluate": {"total_ms": 2.5},
            },
            "counters": {"match.native_calls": 5, "match.native_hits": 1},
        }

        delta = performance_delta(before, after)

        self.assertEqual(delta["timings_ms"]["vision.search"], 15.5)
        self.assertEqual(delta["timings_ms"]["screenshot.total"], 4.0)
        self.assertEqual(delta["timings_ms"]["condition.evaluate"], 2.5)
        self.assertEqual(delta["counters"]["match.native_calls"], 2)
        self.assertEqual(delta["counters"]["match.native_hits"], 1)

    def test_complete_step_timing_separates_top_level_and_nested_phases(self):
        before = {"timings": {}, "counters": {}}
        after = {
            "timings": {
                "wait.recognition_base": {"total_ms": 100.0},
                "vision.search": {"total_ms": 80.0},
                "screenshot.total": {"total_ms": 15.0},
                "match.native": {"total_ms": 60.0},
                "action.total": {"total_ms": 120.0},
                "action.mouse_click": {"total_ms": 35.0},
            },
            "counters": {"match.native_calls": 1},
        }

        payload = complete_step_timing_payload(
            before,
            after,
            total_ms=225.0,
            pre_execute_wait_ms=101.0,
            execute_ms=123.0,
        )

        self.assertEqual(payload["top_level"]["pre_execute_wait_ms"], 101.0)
        self.assertEqual(payload["nested_phases_ms"]["vision_search"], 80.0)
        self.assertEqual(payload["nested_phases_ms"]["native_match"], 60.0)
        self.assertEqual(payload["all_timing_changes_ms"]["action.total"], 120.0)
        self.assertEqual(payload["counter_changes"]["match.native_calls"], 1)
        self.assertIn("不能直接相加", payload["note"])

    def test_complete_payload_escapes_html_and_keeps_chinese(self):
        formatted = format_complete_payload("完全<参数>", {"模式": "详细&安全"})
        self.assertIn("完全&lt;参数&gt;", formatted)
        self.assertIn("详细&amp;安全", formatted)
        self.assertNotIn("<参数>", formatted)


if __name__ == "__main__":
    unittest.main()
