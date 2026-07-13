import threading
import time
import unittest
from unittest import mock

from fukua_rpa.engine import RPAEngine


class EngineSchedulerBoundaryTests(unittest.TestCase):
    def create_engine(self):
        with mock.patch.object(RPAEngine, "set_high_priority", lambda _self: None):
            engine = RPAEngine()
        engine.log_level = -1
        engine.detect_delay = 0
        engine.settlement_wait = 0
        engine.load_and_precompute = lambda _tasks: True
        return engine

    def test_empty_task_list_finishes_without_spinning(self):
        engine = self.create_engine()
        started = time.monotonic()
        engine.run_tasks([])
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertFalse(engine.is_running)
        self.assertEqual(engine.lifecycle.snapshot().last_outcome, "finished")

    def test_future_step_range_jumps_directly_to_first_runnable_loop(self):
        engine = self.create_engine()
        engine.loop_mode = "无限"
        engine.loop_end_round = 100
        loops = []

        def execute(_cmd, _value, _retry, step_info, *_args, **_kwargs):
            loops.append(step_info["loop"])
            return "success"

        engine.execute_task_once = execute
        engine.run_tasks(
            [
                {
                    "type": 4.0,
                    "value": "x",
                    "step_loop_start": "100",
                    "step_loop_end": "100",
                }
            ]
        )
        self.assertEqual(loops, [100])

    def test_step_beyond_global_end_never_executes(self):
        engine = self.create_engine()
        engine.loop_mode = "无限"
        engine.loop_end_round = 20
        engine.execute_task_once = mock.Mock(return_value="success")
        engine.run_tasks(
            [{"type": 4.0, "value": "x", "step_loop_start": "21", "step_loop_end": "30"}]
        )
        engine.execute_task_once.assert_not_called()
        self.assertFalse(engine.is_running)

    def test_run_max_execution_makes_infinite_loop_converge(self):
        engine = self.create_engine()
        engine.loop_mode = "无限"
        engine.execute_task_once = mock.Mock(return_value="success")
        engine.run_tasks(
            [{"type": 4.0, "value": "x", "run_max_executions": "3"}]
        )
        self.assertEqual(engine.execute_task_once.call_count, 3)
        self.assertFalse(engine.is_running)

    def test_stop_interrupts_long_wait_promptly(self):
        engine = self.create_engine()
        status_seen = threading.Event()
        worker = threading.Thread(
            target=engine.run_tasks,
            args=([{"type": 5.0, "value": "30"}],),
            kwargs={"callback_status": lambda _data: status_seen.set()},
            daemon=True,
        )
        worker.start()
        self.assertTrue(status_seen.wait(1.0))
        stop_started = time.monotonic()
        engine.stop()
        worker.join(1.0)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - stop_started, 0.3)
        self.assertEqual(engine.lifecycle.snapshot().last_outcome, "stopped")

    def test_repeated_stop_and_finish_are_idempotent(self):
        engine = self.create_engine()
        run_id = engine.reserve_run()
        self.assertIsNotNone(run_id)
        self.assertTrue(engine.stop())
        self.assertTrue(engine.stop())
        self.assertTrue(engine.finish_run(run_id, "stopped"))
        self.assertFalse(engine.finish_run(run_id, "stopped"))
        self.assertFalse(engine.stop())

    def test_engine_breakpoint_pauses_before_execution(self):
        engine = self.create_engine()
        engine.execute_task_once = mock.Mock(return_value="success")
        paused = threading.Event()
        worker = threading.Thread(
            target=engine.run_tasks,
            args=([{"type": 4.0, "value": "x", "debug_breakpoint": True}],),
            kwargs={
                "callback_debug": lambda event: paused.set()
                if event.get("state") == "paused"
                else None
            },
            daemon=True,
        )
        worker.start()
        self.assertTrue(paused.wait(1.0))
        engine.execute_task_once.assert_not_called()
        self.assertTrue(engine.debug_session.continue_run())
        worker.join(1.0)
        self.assertFalse(worker.is_alive())
        engine.execute_task_once.assert_called_once()

    def test_false_conditional_breakpoint_does_not_pause(self):
        engine = self.create_engine()
        engine.execute_task_once = mock.Mock(return_value="success")
        debug_events = []

        engine.run_tasks(
            [
                {
                    "type": 4.0,
                    "value": "x",
                    "debug_breakpoint": True,
                    "debug_condition": "loop > 1",
                }
            ],
            callback_debug=debug_events.append,
        )

        engine.execute_task_once.assert_called_once()
        self.assertFalse(any(event.get("state") == "paused" for event in debug_events))

    def test_true_conditional_breakpoint_pauses_with_specific_reason(self):
        engine = self.create_engine()
        engine.execute_task_once = mock.Mock(return_value="success")
        paused = threading.Event()
        events = []

        def on_debug(event):
            events.append(event)
            if event.get("state") == "paused":
                paused.set()

        worker = threading.Thread(
            target=engine.run_tasks,
            args=(
                [
                    {
                        "type": 4.0,
                        "value": "x",
                        "debug_breakpoint": True,
                        "debug_condition": "loop == 1 and execution_count == 0",
                    }
                ],
            ),
            kwargs={"callback_debug": on_debug},
            daemon=True,
        )
        worker.start()
        self.assertTrue(paused.wait(1.0))
        self.assertEqual(events[0]["reason"], "conditional_breakpoint")
        self.assertTrue(engine.debug_session.continue_run())
        worker.join(1.0)
        self.assertFalse(worker.is_alive())
        engine.execute_task_once.assert_called_once()

    def test_unset_breakpoint_variable_pauses_instead_of_hiding_error(self):
        engine = self.create_engine()
        engine.execute_task_once = mock.Mock(return_value="success")
        paused = threading.Event()
        events = []

        def on_debug(event):
            events.append(event)
            if event.get("state") == "paused":
                paused.set()

        worker = threading.Thread(
            target=engine.run_tasks,
            args=(
                [
                    {
                        "type": 4.0,
                        "value": "x",
                        "debug_breakpoint": True,
                        "debug_condition": "missing_value > 0",
                    }
                ],
            ),
            kwargs={"callback_debug": on_debug},
            daemon=True,
        )
        worker.start()
        self.assertTrue(paused.wait(1.0))
        self.assertEqual(events[0]["reason"], "breakpoint_condition_error")
        self.assertIn("missing_value", events[0]["detail"])
        engine.debug_session.continue_run()
        worker.join(1.0)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
