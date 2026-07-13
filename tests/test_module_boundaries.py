import importlib
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fukua_rpa.config_store import atomic_write_json, load_profiles_backup
from fukua_rpa.constants import (
    APP_VERSION,
    BUILD_NAME,
    LEGACY_PROFILE_BACKUP_FORMAT,
    PRODUCT_NAME,
    PROFILE_BACKUP_FORMAT,
    PROFILE_SCHEMA_VERSION,
)
from fukua_rpa.engine import RPAEngine
from fukua_rpa.logging_service import current_log_path, set_log_base_dir
from fukua_rpa.win32_api import (
    hotkey_text_from_pressed_vks,
    parse_hotkey_text,
    pressed_hotkey_display_text,
)


class ModuleBoundaryTests(unittest.TestCase):
    def test_all_architecture_modules_import_without_cycles(self):
        names = [
            "fukua_rpa.constants",
            "fukua_rpa.commands",
            "fukua_rpa.paths",
            "fukua_rpa.config_schema",
            "fukua_rpa.config_store",
            "fukua_rpa.profile_model",
            "fukua_rpa.profile_package",
            "fukua_rpa.preview_model",
            "fukua_rpa.mapping_backend",
            "fukua_rpa.opencv_runtime",
            "fukua_rpa.pyautogui_runtime",
            "fukua_rpa.performance",
            "fukua_rpa.scale_memory",
            "fukua_rpa.debug_session",
            "fukua_rpa.expressions",
            "fukua_rpa.integrity",
            "fukua_rpa.uia_backend",
            "fukua_rpa.uia_smoke",
            "fukua_rpa.native_smoke",
            "fukua_rpa.window_diagnostics",
            "fukua_rpa.runtime_state",
            "fukua_rpa.runtime_trace",
            "fukua_rpa.run_config",
            "fukua_rpa.scheduler",
            "fukua_rpa.session",
            "fukua_rpa.task_model",
            "fukua_rpa.validation",
            "fukua_rpa.workflow_analysis",
            "fukua_rpa.win32_api",
            "fukua_rpa.coordinates",
            "fukua_rpa.vision",
            "fukua_rpa.engine",
            "fukua_rpa.engine_actions",
            "fukua_rpa.engine_conditions",
            "fukua_rpa.engine_coordinates",
            "fukua_rpa.engine_expressions",
            "fukua_rpa.engine_vision",
            "fukua_rpa.worker",
            "fukua_rpa.ui.components",
            "fukua_rpa.ui.input_tools",
            "fukua_rpa.ui.overlays",
            "fukua_rpa.ui.startup",
            "fukua_rpa.ui.task_row",
            "fukua_rpa.ui.controllers.run_controller",
            "fukua_rpa.ui.main_window",
        ]
        for name in names:
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(name))

    def test_product_identity_is_consistent(self):
        self.assertEqual(PRODUCT_NAME, "fukuaRPA")
        self.assertEqual(APP_VERSION, "v1.0.12")
        self.assertEqual(BUILD_NAME, "fukuaRPA_v1.0.12")

    def test_config_store_reads_new_and_legacy_backup_formats(self):
        profile = {"默认方案": {"tasks": [], "key_mappings": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "profiles_backup.json")
            for format_name in (PROFILE_BACKUP_FORMAT, LEGACY_PROFILE_BACKUP_FORMAT):
                atomic_write_json(path, {
                    "format": format_name,
                    "profiles": profile,
                    "current_profile": "默认方案",
                })
                loaded, current, error = load_profiles_backup(path)
                self.assertEqual(error, "")
                self.assertEqual(loaded["默认方案"]["tasks"], [])
                self.assertEqual(loaded["默认方案"]["key_mappings"], [])
                self.assertEqual(
                    loaded["默认方案"]["_schema_version"], PROFILE_SCHEMA_VERSION
                )
                self.assertEqual(current, "默认方案")

    def test_engine_uses_its_injected_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = RPAEngine(base_dir=temp_dir)
            self.assertEqual(engine.base_dir, os.path.abspath(temp_dir))
            self.assertFalse(engine.native_core.available)
            self.assertIn("fukua_rpa_core.dll", engine.native_core.load_error)

    def test_log_path_follows_injected_runtime_directory(self):
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                set_log_base_dir(temp_dir)
                self.assertEqual(current_log_path(), os.path.join(temp_dir, "rpa_debug_log.txt"))
        finally:
            set_log_base_dir(None)

    def test_hotkey_parser_accepts_bare_letter_for_mapping_mode(self):
        parsed = parse_hotkey_text("A")
        self.assertEqual(parsed["text"], "a")
        self.assertTrue(parsed["bare"])

    def test_hook_key_state_builds_all_modifier_combinations(self):
        letter_a = 0x41
        combinations = {
            frozenset((0xA2, letter_a)): "ctrl+a",
            frozenset((0xA4, letter_a)): "alt+a",
            frozenset((0xA2, 0xA0, letter_a)): "ctrl+shift+a",
            frozenset((0xA2, 0xA4, letter_a)): "ctrl+alt+a",
            frozenset((0xA2, 0xA0, 0xA4, letter_a)): "ctrl+alt+shift+a",
        }
        for pressed_vks, expected in combinations.items():
            self.assertEqual(
                hotkey_text_from_pressed_vks(letter_a, pressed_vks), expected
            )

    def test_hook_key_state_can_render_modifier_only_progress(self):
        self.assertEqual(pressed_hotkey_display_text({0xA2}), "Ctrl")
        self.assertEqual(
            pressed_hotkey_display_text({0xA2, 0xA0, 0xA4, 0x41}),
            "Ctrl+Alt+Shift+A",
        )


if __name__ == "__main__":
    unittest.main()
