import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEAVY_MODULES = ("cv2", "numpy", "pyautogui", "uiautomation")


class StartupArchitectureTests(unittest.TestCase):
    def run_probe(self, source):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", source],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return json.loads(completed.stdout.strip())

    def test_entrypoint_import_keeps_workspace_and_heavy_backends_deferred(self):
        report = self.run_probe(
            "import json,sys; import fukuaRPA; "
            "names=('fukua_rpa.ui.main_window','cv2','numpy','pyautogui','uiautomation'); "
            "print(json.dumps({name: name in sys.modules for name in names}))"
        )
        self.assertFalse(any(report.values()), report)

    def test_workspace_import_does_not_eagerly_load_optional_backends(self):
        report = self.run_probe(
            "import json,sys; import fukua_rpa.ui.main_window; "
            f"names={HEAVY_MODULES!r}; "
            "print(json.dumps({name: name in sys.modules for name in names}))"
        )
        self.assertFalse(any(report.values()), report)

    def test_deferred_engine_construction_does_not_initialize_opencv(self):
        report = self.run_probe(
            "import json,sys; from fukua_rpa.engine import RPAEngine; "
            "engine=RPAEngine(defer_backends=True); "
            "print(json.dumps({'ready':engine.backends_ready,"
            "'cv2':'cv2' in sys.modules,'numpy':'numpy' in sys.modules}))"
        )
        self.assertFalse(report["ready"])
        self.assertFalse(report["cv2"])
        self.assertFalse(report["numpy"])


if __name__ == "__main__":
    unittest.main()
