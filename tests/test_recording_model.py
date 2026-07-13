import unittest

from fukua_rpa.recording_model import recorded_events_to_tasks


class RecordingModelTests(unittest.TestCase):
    def test_same_point_clicks_within_threshold_become_double_click(self):
        tasks = recorded_events_to_tasks(
            [
                (1.0, "left", (100, 200), 1.04),
                (1.22, "left", (102, 199), 1.26),
            ]
        )
        self.assertEqual(tasks, [{"type": 2.0, "value": "102,199"}])

    def test_distant_or_slow_clicks_remain_independent(self):
        tasks = recorded_events_to_tasks(
            [
                (1.0, "left", (10, 10), 1.02),
                (1.7, "left", (10, 10), 1.72),
            ]
        )
        self.assertEqual(tasks[0], {"type": 1.0, "value": "10,10"})
        self.assertEqual(tasks[1], {"type": 5.0, "value": "0.68"})
        self.assertEqual(tasks[2], {"type": 1.0, "value": "10,10"})

    def test_modifier_combination_stays_one_hotkey_task(self):
        tasks = recorded_events_to_tasks([(1.0, "hotkey", "ctrl+shift+a", 1.0)])
        self.assertEqual(tasks, [{"type": 7.0, "value": "ctrl+shift+a"}])

    def test_wheel_events_merge_and_convert_native_delta_to_notches(self):
        tasks = recorded_events_to_tasks(
            [
                (1.0, "scroll", 120, 1.0),
                (1.1, "scroll", 120, 1.1),
                (1.2, "scroll", -120, 1.2),
            ]
        )
        self.assertEqual(tasks, [{"type": 6.0, "value": "1"}])

    def test_drag_preserves_duration_and_wait_uses_previous_end(self):
        tasks = recorded_events_to_tasks(
            [
                (1.0, "left_drag", (1, 2, 30, 40), 1.8),
                (2.0, "hotkey", "ctrl+c", 2.0),
            ]
        )
        self.assertEqual(tasks[0]["type"], 10.0)
        self.assertEqual(tasks[0]["recorded_duration"], 0.8)
        self.assertEqual(tasks[1], {"type": 5.0, "value": "0.20"})
        self.assertEqual(tasks[2], {"type": 7.0, "value": "ctrl+c"})


if __name__ == "__main__":
    unittest.main()
