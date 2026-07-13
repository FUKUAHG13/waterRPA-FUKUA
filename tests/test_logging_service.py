import os
import tempfile
import threading
import unittest
from unittest import mock

from fukua_rpa import logging_service


class LoggingServiceTests(unittest.TestCase):
    def setUp(self):
        self.previous_config = dict(logging_service.GLOBAL_CONFIG)

    def tearDown(self):
        logging_service.flush_logs()
        logging_service.GLOBAL_CONFIG.update(self.previous_config)
        logging_service.set_log_base_dir(None)

    def test_callback_failure_does_not_block_following_log_items(self):
        completed = threading.Event()
        logging_service.GLOBAL_CONFIG.update({"log_to_file": False, "log_to_ui": True})

        def broken(_message):
            raise RuntimeError("callback failed")

        logging_service.write_log("first", broken)
        logging_service.write_log("second", lambda _message: completed.set())
        self.assertTrue(completed.wait(1.0))
        self.assertTrue(logging_service.flush_logs())

    def test_file_logging_rotates_and_flushes(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            logging_service, "MAX_LOG_BYTES", 160
        ):
            logging_service.set_log_base_dir(temp_dir)
            logging_service.GLOBAL_CONFIG.update({"log_to_file": True, "log_to_ui": False})
            for index in range(30):
                logging_service.write_log(f"line-{index}-" + "x" * 40)
            self.assertTrue(logging_service.flush_logs())
            path = os.path.join(temp_dir, "rpa_debug_log.txt")
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(os.path.isfile(path + ".1"))
            self.assertLessEqual(
                len([name for name in os.listdir(temp_dir) if name.startswith("rpa_debug_log.txt.")]),
                logging_service.LOG_BACKUP_COUNT,
            )

    def test_event_time_is_shared_by_file_and_timestamped_ui(self):
        event_time_ns = 1_700_000_000_123_000_000
        expected_time = logging_service.format_local_timestamp(event_time_ns)
        received = []
        completed = threading.Event()

        with tempfile.TemporaryDirectory() as temp_dir:
            logging_service.set_log_base_dir(temp_dir)
            logging_service.GLOBAL_CONFIG.update(
                {"log_to_file": True, "log_to_ui": True}
            )

            def callback(message):
                received.append(message)
                completed.set()

            logging_service.write_log(
                "timed-event",
                callback,
                ui_timestamp=True,
                event_time_ns=event_time_ns,
            )
            self.assertTrue(completed.wait(1.0))
            self.assertTrue(logging_service.flush_logs())
            with open(
                os.path.join(temp_dir, "rpa_debug_log.txt"), encoding="utf-8"
            ) as handle:
                text = handle.read()

        self.assertEqual(received, [f"[{expected_time}] timed-event"])
        self.assertIn(f"[{expected_time}] timed-event", text)


if __name__ == "__main__":
    unittest.main()
