import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.runtime_pruning import (
    PYINSTALLER_EXCLUDES,
    apply_runtime_pruning,
    find_prunable_runtime_paths,
    pruning_group,
)


class _FakeAnalysis:
    def __init__(self, binaries, datas):
        self.binaries = list(binaries)
        self.datas = list(datas)


class RuntimePruningTests(unittest.TestCase):
    def test_high_confidence_payloads_are_classified(self):
        cases = {
            "cv2/opencv_videoio_ffmpeg4130_64.dll": "opencv_ffmpeg",
            "PySide6/Qt6Quick.dll": "qt_quick_qml_pdf_virtual_keyboard",
            "PySide6/plugins/imageformats/qpdf.dll": (
                "qt_quick_qml_pdf_virtual_keyboard"
            ),
            "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll": (
                "qt_quick_qml_pdf_virtual_keyboard"
            ),
            "PySide6/translations/qtbase_de.qm": "non_chinese_qt_translations",
            "PIL/_avif.cp314-win_amd64.pyd": "pillow_optional_extensions",
            "PIL/_imagingft.cp314-win_amd64.pyd": "pillow_optional_extensions",
            "_tkinter.pyd": "tcl_tk",
            "_tcl_data/tcl8.6/init.tcl": "tcl_tk",
        }
        for destination, expected in cases.items():
            with self.subTest(destination=destination):
                self.assertEqual(
                    pruning_group((destination, "source", "BINARY")), expected
                )

    def test_required_and_compatibility_payloads_are_retained(self):
        retained = (
            "PySide6/Qt6Core.dll",
            "PySide6/Qt6Gui.dll",
            "PySide6/Qt6Widgets.dll",
            "PySide6/opengl32sw.dll",
            "PySide6/plugins/platforms/qwindows.dll",
            "PySide6/plugins/platforms/qoffscreen.dll",
            "PySide6/plugins/imageformats/qjpeg.dll",
            "PySide6/translations/qtbase_zh_CN.qm",
            "PySide6/translations/qtbase_zh_TW.qm",
            "PIL/_imaging.cp314-win_amd64.pyd",
        )
        for destination in retained:
            with self.subTest(destination=destination):
                self.assertIsNone(
                    pruning_group((destination, "source", "BINARY"))
                )

    def test_analysis_payloads_are_pruned_without_reordering_survivors(self):
        analysis = _FakeAnalysis(
            [
                ("PySide6/Qt6Core.dll", "core", "BINARY"),
                ("PySide6/Qt6Pdf.dll", "pdf", "BINARY"),
                ("_tkinter.pyd", "tk", "BINARY"),
                ("PySide6/plugins/platforms/qwindows.dll", "win", "BINARY"),
            ],
            [
                ("PySide6/translations/qtbase_fr.qm", "fr", "DATA"),
                ("PySide6/translations/qtbase_zh_CN.qm", "zh", "DATA"),
                ("_tk_data/tk.tcl", "tk-data", "DATA"),
            ],
        )
        summary = apply_runtime_pruning(analysis)
        self.assertEqual(
            [entry[0] for entry in analysis.binaries],
            ["PySide6/Qt6Core.dll", "PySide6/plugins/platforms/qwindows.dll"],
        )
        self.assertEqual(
            [entry[0] for entry in analysis.datas],
            ["PySide6/translations/qtbase_zh_CN.qm"],
        )
        self.assertEqual(summary["qt_quick_qml_pdf_virtual_keyboard"], 1)
        self.assertEqual(summary["non_chinese_qt_translations"], 1)
        self.assertEqual(summary["tcl_tk"], 2)

    def test_tk_helpers_are_excluded_at_analysis_time(self):
        self.assertTrue(
            {"_tkinter", "mouseinfo", "pymsgbox", "tkinter"}.issubset(
                PYINSTALLER_EXCLUDES
            )
        )
        # PyScreeze imports ImageDraw -> ImageText -> ImageFont even when no
        # font rendering is requested. The optional _imagingft binary can still
        # be removed because ImageFont handles its absence gracefully.
        self.assertNotIn("PIL.ImageFont", PYINSTALLER_EXCLUDES)

    def test_frozen_directory_guard_finds_reintroduced_payloads(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            retained = root / "_internal" / "PySide6" / "plugins" / "platforms"
            retained.mkdir(parents=True)
            (retained / "qwindows.dll").write_bytes(b"required")
            removed = root / "_internal" / "cv2"
            removed.mkdir(parents=True)
            (removed / "opencv_videoio_ffmpeg4130_64.dll").write_bytes(b"unused")
            self.assertEqual(
                find_prunable_runtime_paths(root),
                ["_internal/cv2/opencv_videoio_ffmpeg4130_64.dll"],
            )


if __name__ == "__main__":
    unittest.main()
