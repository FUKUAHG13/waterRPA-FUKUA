import threading
import unittest
from unittest import mock

from fukua_rpa.uia_backend import (
    UIAutomationBackend,
    _candidate_score,
    _perform_uia_job,
    _point_in_rect,
    _rect_area,
)


class _Rect:
    left = 10
    top = 20
    right = 110
    bottom = 70


class UIAutomationBackendTests(unittest.TestCase):
    def test_point_and_area_helpers_reject_edges_consistently(self):
        rect = _Rect()
        self.assertTrue(_point_in_rect(rect, 10, 20))
        self.assertTrue(_point_in_rect(rect, 109, 69))
        self.assertFalse(_point_in_rect(rect, 110, 69))
        self.assertEqual(_rect_area(rect), 5000.0)

    def test_backend_sends_only_plain_values_to_worker(self):
        service = mock.Mock()
        service.available = True
        service.request.return_value = {"available": True, "actionable": True}
        backend = UIAutomationBackend(service=service)

        report = backend.probe(123, 45, 67)

        self.assertTrue(report["actionable"])
        service.request.assert_called_once_with(
            "probe",
            {"root_hwnd": 123, "x": 45, "y": 67, "preferred_hwnd": 0},
        )

    def test_set_and_read_value_send_plain_payloads(self):
        service = mock.Mock()
        service.available = True
        service.request.return_value = {"available": True, "actionable": True}
        backend = UIAutomationBackend(service=service)

        backend.set_value(10, 20, 30, "text", preferred_hwnd=40)
        backend.read_value(11, 21, 31, preferred_hwnd=41)

        first, second = service.request.call_args_list
        self.assertEqual(first.args[0], "set_value")
        self.assertEqual(first.args[1]["value"], "text")
        self.assertEqual(second.args[0], "read_value")
        self.assertNotIn("value", second.args[1])

    def test_candidate_score_prefers_bound_hwnd_then_deepest_control(self):
        bound = _candidate_score(
            depth=2,
            area=5000,
            action_priority=10,
            native_hwnd=222,
            preferred_hwnd=222,
            root_hwnd=111,
        )
        deep_unbound = _candidate_score(
            depth=8,
            area=100,
            action_priority=40,
            native_hwnd=0,
            preferred_hwnd=222,
            root_hwnd=111,
        )
        self.assertGreater(bound, deep_unbound)

        deep_toggle = _candidate_score(
            depth=5,
            area=100,
            action_priority=20,
            native_hwnd=0,
            preferred_hwnd=111,
            root_hwnd=111,
        )
        shallow_invoke = _candidate_score(
            depth=2,
            area=1000,
            action_priority=40,
            native_hwnd=111,
            preferred_hwnd=111,
            root_hwnd=111,
        )
        self.assertGreater(deep_toggle, shallow_invoke)

    def test_backend_close_is_forwarded(self):
        service = mock.Mock()
        service.available = True
        backend = UIAutomationBackend(service=service)
        backend.close()
        service.close.assert_called_once_with()

    def test_cancelled_job_never_enters_uia_tree_or_action(self):
        cancelled = threading.Event()
        cancelled.set()

        result = _perform_uia_job(
            "activate",
            {"root_hwnd": 123, "x": 45, "y": 67},
            cancelled,
        )

        self.assertTrue(result["cancelled"])
        self.assertFalse(result.get("success", False))


if __name__ == "__main__":
    unittest.main()
