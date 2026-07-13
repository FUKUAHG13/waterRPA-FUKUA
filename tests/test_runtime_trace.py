import unittest

from fukua_rpa.runtime_trace import RunTrace


class RunTraceTests(unittest.TestCase):
    def test_trace_is_bounded_and_keeps_recent_transitions(self):
        trace = RunTrace(max_events=100)
        trace.reset(task_count=3)
        for index in range(250):
            trace.record(
                "step_result",
                loop=index // 3 + 1,
                step=index % 3 + 1,
                command="左键单击",
                status="success",
                next_step=(index + 1) % 3 + 1,
            )
        report = trace.snapshot()
        self.assertEqual(report["task_count"], 3)
        self.assertEqual(report["total_events"], 250)
        self.assertEqual(report["dropped_events"], 150)
        self.assertEqual(len(report["events"]), 100)
        self.assertEqual(report["events"][-1]["event"], "step_result")

    def test_trace_does_not_have_a_field_for_task_values(self):
        trace = RunTrace()
        trace.record("step_result", loop=1, step=2, command="图片点击")
        event = trace.snapshot()["events"][0]
        self.assertNotIn("value", event)
        self.assertNotIn("path", event)


if __name__ == "__main__":
    unittest.main()
