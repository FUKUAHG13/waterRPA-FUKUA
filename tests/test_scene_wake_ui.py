import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from fukua_rpa.ui.main_window import RPAWindow


class SceneWakeUiTests(unittest.TestCase):
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

    def test_scene_wake_settings_round_trip_and_disable_sensitivity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.scene_wake_chk.setChecked(False)
            window.scene_wake_sensitivity_combo.setCurrentIndex(
                window.scene_wake_sensitivity_combo.findData("sensitive")
            )
            config = window.get_current_ui_config()

            self.assertFalse(config["scene_wake_en"])
            self.assertEqual(config["scene_wake_sensitivity"], "sensitive")
            self.assertFalse(window.scene_wake_sensitivity_combo.isEnabled())

            window.scene_wake_chk.setChecked(True)
            window.apply_ui_config(config)

            self.assertFalse(window.scene_wake_chk.isChecked())
            self.assertEqual(
                window.scene_wake_sensitivity_combo.currentData(), "sensitive"
            )
            self.assertFalse(window.scene_wake_sensitivity_combo.isEnabled())


if __name__ == "__main__":
    unittest.main()
