"""Render deterministic source UI screenshots for layout review."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea  # noqa: E402

from fukua_rpa.ui.components import TaskConfigDialog  # noqa: E402
from fukua_rpa.ui.main_window import RPAWindow  # noqa: E402


def capture(app: QApplication, widget, output: Path) -> None:
    widget.show()
    app.processEvents()
    QTest.qWait(80)
    app.processEvents()
    image = widget.grab()
    if image.isNull() or not image.save(str(output), "PNG"):
        raise RuntimeError(f"无法保存界面截图：{output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".scratch" / "ui-review-v1.0.12",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])

    with tempfile.TemporaryDirectory() as runtime_dir, mock.patch.object(
        RPAWindow, "register_global_hotkeys", lambda _self: True
    ), mock.patch.object(
        QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok
    ):
        window = RPAWindow(base_dir=runtime_dir)
        window.add_row({"type": 1.0, "value": "320,240", "debug_breakpoint": True})
        window.add_row({"type": 16.0, "value": "counter = 1"})
        window.add_row({"type": 17.0, "value": "counter < 10"})

        window.apply_ui_scale(1.0)
        window.resize(1040, 760)
        capture(app, window, output_dir / "main-100-1040x760.png")

        window.settings_dialog.resize(920, 700)
        window.show_settings_dialog()
        capture(
            app,
            window.settings_dialog,
            output_dir / "settings-onboarding-100-920x700.png",
        )
        window.dismiss_fast_response_tip()
        capture(app, window.settings_dialog, output_dir / "settings-100-920x700.png")

        window.scale_memory_section.toggle_btn.setChecked(True)
        window.scale_memory_section.on_toggle(True)
        settings_scroll = window.settings_dialog.findChild(QScrollArea)
        settings_scroll.ensureWidgetVisible(window.scale_memory_section)
        capture(
            app,
            window.settings_dialog,
            output_dir / "settings-scale-memory-100-920x700.png",
        )

        settings_scroll.ensureWidgetVisible(window.dodge_section)
        capture(
            app,
            window.settings_dialog,
            output_dir / "settings-dodge-100-920x700.png",
        )
        settings_scroll.ensureWidgetVisible(window.system_settings_row)
        capture(
            app,
            window.settings_dialog,
            output_dir / "settings-system-100-920x700.png",
        )
        window.settings_dialog.hide()

        window.apply_ui_scale(1.5)
        window.resize(760, 620)
        capture(app, window, output_dir / "main-150-760x620.png")

        window.settings_dialog.resize(720, 520)
        capture(app, window.settings_dialog, output_dir / "settings-150-720x520.png")
        window.settings_dialog.hide()

        task_dialog = TaskConfigDialog(
            window,
            {
                "debug_breakpoint": True,
                "repeat_mode": "重复指定次数",
                "repeat_count": 3,
                "coord_step_en": True,
                "coord_step_direction": "移动到新点位",
                "coord_step_point": "640,480",
                "coord_step_max_steps": 6,
            },
            image_settings_available=True,
            point_limit_available=True,
            coordinate_step_available=True,
            image_click_point_available=True,
            base_coordinate=(320, 240),
            base_dir=runtime_dir,
        )
        task_dialog.resize(720, 560)
        capture(app, task_dialog, output_dir / "step-settings-150-720x560.png")
        task_dialog.close()
        window.close()

    print(f"UI review screenshots: {output_dir}")


if __name__ == "__main__":
    main()
