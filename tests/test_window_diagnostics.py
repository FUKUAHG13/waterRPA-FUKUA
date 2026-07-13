import os
import unittest

from fukua_rpa.window_diagnostics import (
    classify_control,
    integrity_label_from_rid,
    process_integrity,
)


class WindowDiagnosticsTests(unittest.TestCase):
    def test_integrity_rids_have_stable_user_facing_labels(self):
        self.assertEqual(integrity_label_from_rid(0x1000), "低")
        self.assertEqual(integrity_label_from_rid(0x2000), "中")
        self.assertEqual(integrity_label_from_rid(0x3000), "高（管理员）")
        self.assertEqual(integrity_label_from_rid(0x4000), "系统")

    def test_control_compatibility_is_conservative(self):
        standard = classify_control("Button")
        canvas = classify_control("Chrome_RenderWidgetHostHWND")
        elevated = classify_control("Button", permission_blocked=True)
        self.assertTrue(standard["standard_win32_control"])
        self.assertIn("较可能有效", standard["classification"])
        self.assertTrue(canvas["custom_surface"])
        self.assertIn("兼容性较低", canvas["classification"])
        self.assertIn("权限阻止", elevated["classification"])

    def test_current_process_integrity_can_be_read(self):
        report = process_integrity(os.getpid())
        self.assertTrue(report["available"], report)
        self.assertGreaterEqual(report["rid"], 0x1000)
        self.assertTrue(report["label"])


if __name__ == "__main__":
    unittest.main()
