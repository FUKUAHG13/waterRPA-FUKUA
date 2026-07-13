import threading
import time
import unittest

from fukua_rpa.debug_session import DebugSession


class DebugSessionTests(unittest.TestCase):
    def wait_until(self, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def test_breakpoint_blocks_until_continue(self):
        session = DebugSession()
        session.reset()
        result = []
        events = []
        worker = threading.Thread(
            target=lambda: result.append(
                session.before_step(
                    step=2,
                    loop=3,
                    command="左键单击",
                    breakpoint=True,
                    callback=events.append,
                )
            ),
            daemon=True,
        )
        worker.start()
        self.assertTrue(self.wait_until(lambda: session.snapshot().paused))
        self.assertTrue(session.continue_run())
        worker.join(1.0)
        self.assertFalse(worker.is_alive())
        self.assertTrue(result[0][0])
        self.assertEqual(events[0]["state"], "paused")
        self.assertEqual(events[-1]["state"], "resumed")

    def test_step_over_pauses_before_the_following_step(self):
        session = DebugSession()
        session.reset()
        first = threading.Thread(
            target=lambda: session.before_step(
                step=1, loop=1, command="输入文本", breakpoint=True
            ),
            daemon=True,
        )
        first.start()
        self.assertTrue(self.wait_until(lambda: session.snapshot().paused))
        self.assertTrue(session.step_over())
        first.join(1.0)

        second_result = []
        second = threading.Thread(
            target=lambda: second_result.append(
                session.before_step(
                    step=2, loop=1, command="等待", breakpoint=False
                )
            ),
            daemon=True,
        )
        second.start()
        self.assertTrue(self.wait_until(lambda: session.snapshot().paused))
        self.assertEqual(session.snapshot().reason, "step_over")
        session.continue_run()
        second.join(1.0)
        self.assertTrue(second_result[0][0])

    def test_cancel_wakes_a_paused_run(self):
        session = DebugSession()
        session.reset()
        result = []
        worker = threading.Thread(
            target=lambda: result.append(
                session.before_step(
                    step=1, loop=1, command="等待", breakpoint=True
                )
            ),
            daemon=True,
        )
        worker.start()
        self.assertTrue(self.wait_until(lambda: session.snapshot().paused))
        session.cancel()
        worker.join(1.0)
        self.assertEqual(result[0][0], False)


if __name__ == "__main__":
    unittest.main()
