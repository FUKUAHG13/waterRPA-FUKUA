import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

import fukua_rpa.engine_actions as engine_actions_module
from fukua_rpa.config_schema import default_profile_config
from fukua_rpa.engine import RPAEngine
from fukua_rpa.run_config import EngineRunConfig, RunConfigError
from fukua_rpa.ui.main_window import RPAWindow


class DodgeAndOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def create_window(self, base_dir):
        hotkeys = mock.patch.object(
            RPAWindow, "register_global_hotkeys", lambda _self: True
        )
        warnings = mock.patch.object(
            QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok
        )
        hotkeys.start()
        warnings.start()
        self.addCleanup(hotkeys.stop)
        self.addCleanup(warnings.stop)
        window = RPAWindow(base_dir=base_dir)
        self.addCleanup(window.close)
        return window

    def test_fast_response_tip_is_shown_only_on_first_settings_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            self.assertTrue(window.fast_response_tip.isHidden())

            window.show_settings_dialog()
            self.app.processEvents()
            self.assertTrue(window.fast_response_tip.isVisible())
            self.assertTrue(
                window.settings.value(
                    "onboarding/fast_response_tip_v1_seen", False, type=bool
                )
            )

            window.close_settings_dialog()
            window.show_settings_dialog()
            self.app.processEvents()
            self.assertTrue(window.fast_response_tip.isHidden())

    def test_dodge_pick_buttons_fill_both_coordinate_pairs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            callbacks = []

            def create_picker(mode, callback):
                self.assertEqual(mode, "point")
                callbacks.append(callback)
                return QWidget()

            with mock.patch(
                "fukua_rpa.ui.main_window.CoordinatePickerUI",
                side_effect=create_picker,
            ):
                window.dodge_pick1_btn.click()
                callbacks[-1]("-120,345")
                window.dodge_pick2_btn.click()
                callbacks[-1]("800,900")

            self.assertEqual(window.dodge_x1.text(), "-120")
            self.assertEqual(window.dodge_y1.text(), "345")
            self.assertEqual(window.dodge_x2.text(), "800")
            self.assertEqual(window.dodge_y2.text(), "900")

    def test_dodge_click_action_round_trips_and_reaches_engine(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.dodge_click_combo.setCurrentIndex(
                window.dodge_click_combo.findData("right")
            )
            config = window.get_current_ui_config()
            self.assertEqual(config["dodge_click_action"], "right")

            window.dodge_click_combo.setCurrentIndex(0)
            window.apply_ui_config(config)
            self.assertEqual(window.dodge_click_combo.currentData(), "right")

            runtime = EngineRunConfig.from_mapping(config)
            engine = RPAEngine(defer_backends=True)
            runtime.apply_to(engine)
            self.assertEqual(engine.dodge_click_action, "right")

    def test_double_dodge_clicks_only_once_at_the_final_point(self):
        engine = RPAEngine(defer_backends=True)
        engine.enable_dodge = True
        engine.enable_double_dodge = True
        engine.dodge_x1, engine.dodge_y1 = 100, 200
        engine.dodge_x2, engine.dodge_y2 = 300, 400
        engine.dodge_click_action = "right"
        indicators = []
        engine.callback_click_indicator = indicators.append
        mouse = mock.Mock()

        with mock.patch.object(
            engine_actions_module, "pyautogui", mouse
        ), mock.patch.object(engine_actions_module.time, "sleep"):
            engine._perform_mouse_click_impl(10, 20, 1, "left")

        self.assertEqual(
            mouse.moveTo.call_args_list,
            [
                mock.call(10, 20, duration=0.0),
                mock.call(100, 200, duration=0),
                mock.call(300, 400, duration=0),
            ],
        )
        self.assertEqual(
            mouse.mouseDown.call_args_list,
            [mock.call(button="left"), mock.call(button="right")],
        )
        self.assertEqual(
            mouse.mouseUp.call_args_list,
            [mock.call(button="left"), mock.call(button="right")],
        )
        self.assertEqual(indicators[-1]["x"], 300)
        self.assertEqual(indicators[-1]["y"], 400)
        self.assertEqual(indicators[-1]["text"], "避让后右键单击")
        self.assertEqual(
            engine.performance.snapshot()["counters"]["action.dodge_clicks"],
            1,
        )

    def test_default_dodge_action_keeps_the_existing_move_only_behavior(self):
        engine = RPAEngine(defer_backends=True)
        engine.enable_dodge = True
        engine.dodge_x1, engine.dodge_y1 = 100, 200
        self.assertEqual(engine.dodge_click_action, "none")
        mouse = mock.Mock()

        with mock.patch.object(
            engine_actions_module, "pyautogui", mouse
        ), mock.patch.object(engine_actions_module.time, "sleep"):
            engine._perform_mouse_click_impl(10, 20, 1, "left")

        self.assertEqual(
            mouse.mouseDown.call_args_list,
            [mock.call(button="left")],
        )
        self.assertEqual(
            mouse.moveTo.call_args_list[-1],
            mock.call(100, 200, duration=0),
        )

    def test_invalid_dodge_click_action_is_rejected(self):
        config = default_profile_config()
        config["dodge_click_action"] = "double"
        with self.assertRaises(RunConfigError):
            EngineRunConfig.from_mapping(config)


if __name__ == "__main__":
    unittest.main()
