import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from fukua_rpa.commands import COMMAND_SPECS
from fukua_rpa.credentials import CredentialStore
from fukua_rpa.engine import RPAEngine
from fukua_rpa.engine_actions import StepActionContext, registered_action_codes
from fukua_rpa.text_input import _utf16_units


def context(command, value="", task=None):
    return StepActionContext(
        command=float(command),
        value=value,
        retry=1,
        step_info={"step": 1, "loop": 1},
        cache_key="test",
        confidence=0.8,
        use_gray=True,
        task=task or {},
    )


class CredentialStoreTests(unittest.TestCase):
    def test_store_persists_only_protected_text(self):
        protect = lambda value: "encrypted:" + value[::-1]
        unprotect = lambda value: value.removeprefix("encrypted:")[::-1]
        with tempfile.TemporaryDirectory() as directory:
            store = CredentialStore(directory, protect=protect, unprotect=unprotect)
            store.set("account", "plain-secret")

            with open(store.path, "r", encoding="utf-8") as handle:
                raw = handle.read()
            self.assertNotIn("plain-secret", raw)
            self.assertEqual(store.get("account"), "plain-secret")
            self.assertEqual(store.names(), ["account"])

            payload = json.loads(raw)
            self.assertEqual(payload["credentials"]["account"], "encrypted:terces-nialp")

    def test_unicode_units_keep_supplementary_characters_as_surrogates(self):
        self.assertEqual(_utf16_units("A中"), [65, 0x4E2D])
        self.assertEqual(len(_utf16_units("😀")), 2)


class NewActionTests(unittest.TestCase):
    def setUp(self):
        self.engine = RPAEngine(defer_backends=True)
        self.engine.callback_msg = mock.Mock()
        self.engine.log_level = 2

    def test_every_registered_command_has_an_action_handler(self):
        self.assertEqual(registered_action_codes(), {spec.code for spec in COMMAND_SPECS})

    @mock.patch("fukua_rpa.engine_actions.launch_application", return_value=1234)
    def test_launch_application_action(self, launch):
        result = self.engine._execute_launch_application(context(18, "demo.exe"))
        self.assertEqual(result, "success")
        launch.assert_called_once_with("demo.exe")

    def test_uia_read_stores_a_runtime_variable(self):
        backend = SimpleNamespace(
            uia_control_action=mock.Mock(
                return_value={"success": True, "method": "UIA Value", "value": "result"}
            )
        )
        self.engine._task_window_backend = backend
        self.engine.reset_expression_runtime()

        result = self.engine._execute_uia_read_value(
            context(25, "answer", {"uia_binding": {"root_hwnd": 1}})
        )

        self.assertEqual(result, "success")
        self.assertEqual(self.engine.runtime_variables["answer"], "result")

    @mock.patch("fukua_rpa.engine_actions.send_unicode_text")
    def test_regular_text_log_never_contains_plain_text(self, send):
        self.engine._execute_text(context(4, "private words"))
        send.assert_called_once_with("private words")
        logged = " ".join(str(call.args[0]) for call in self.engine.callback_msg.call_args_list)
        self.assertNotIn("private words", logged)

    @mock.patch("fukua_rpa.engine_actions.send_unicode_text")
    def test_secret_text_resolves_name_without_logging_secret(self, send):
        self.engine._credential_store = SimpleNamespace(get=lambda name: "top-secret")
        self.engine._execute_secret_text(context(22, "account"))
        send.assert_called_once_with("top-secret")
        logged = " ".join(str(call.args[0]) for call in self.engine.callback_msg.call_args_list)
        self.assertNotIn("top-secret", logged)


if __name__ == "__main__":
    unittest.main()
