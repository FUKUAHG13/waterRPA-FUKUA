import os
import json
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolTip,
)
from fukua_rpa.ui.components import (
    HelpBtn,
    NoWheelComboBox,
    ResponsiveRow,
    TaskConfigDialog,
)
from fukua_rpa.ui.input_tools import KeyCaptureDialog
from fukua_rpa.ui.main_window import RPAWindow, user32
from fukua_rpa.paths import get_resource_path
from fukua_rpa.config_schema import default_profile_config
from fukua_rpa.config_store import profiles_signature
from fukua_rpa.constants import PROFILE_SCHEMA_VERSION
from fukua_rpa.log_policy import (
    LOG_ACTION,
    LOG_MODE_CUSTOM,
    LOG_MODE_DETAILED,
    LOG_RECOGNITION,
    LOG_TIMESTAMP,
)


class ModernUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def create_window(self, base_dir):
        hotkeys = mock.patch.object(RPAWindow, "register_global_hotkeys", lambda _self: True)
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

    def test_main_workspace_uses_modern_design_roles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            self.assertTrue(self.app.property("_fukua_modern_theme"))
            self.assertIn('QPushButton[variant="primary"]', self.app.styleSheet())
            self.assertEqual(window.centralWidget().objectName(), "appRoot")
            self.assertEqual(window.task_list.objectName(), "taskList")
            self.assertEqual(window.log_text.objectName(), "logView")
            self.assertEqual(window.start_btn.property("variant"), "success")
            self.assertEqual(window.stop_btn.property("variant"), "danger")
            self.assertGreaterEqual(window.minimumWidth(), 760)
            self.assertGreaterEqual(window.minimumHeight(), 620)

    def test_simple_settings_mode_hides_only_advanced_controls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            self.assertEqual(window.settings_mode_combo.currentData(), "simple")
            self.assertTrue(all(widget.isHidden() for widget in window.advanced_setting_widgets))

            window.native_core_chk.setChecked(False)
            window.apply_settings_mode()
            self.assertIn("高级设置", window.advanced_settings_notice.text())

            window.settings_mode_combo.setCurrentIndex(
                window.settings_mode_combo.findData("advanced")
            )
            self.app.processEvents()
            self.assertTrue(all(not widget.isHidden() for widget in window.advanced_setting_widgets))

    def test_requested_settings_groups_are_advanced_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            advanced_widgets = (
                window.dodge_section,
                window.multi_target_section,
                window.credential_section,
                window.start_step_group,
                window.loop_range_group,
                window.low_power_group,
            )
            self.assertTrue(all(widget.isHidden() for widget in advanced_widgets))

            window.settings_mode_combo.setCurrentIndex(
                window.settings_mode_combo.findData("advanced")
            )
            self.app.processEvents()
            self.assertTrue(all(not widget.isHidden() for widget in advanced_widgets))

    def test_command_picker_filters_advanced_actions_without_changing_old_steps(self):
        advanced_commands = {
            "右键拖拽",
            "鼠标悬停",
            "设置变量",
            "判断表达式",
            "等待窗口",
            "激活窗口",
            "关闭窗口",
            "输入秘密文本",
            "点击窗口控件",
            "设置控件文本",
            "读取控件文本",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.add_row({"type": 1.0, "value": "10,20"})
            simple_row = window.task_list.itemWidget(window.task_list.item(0))
            simple_options = {
                simple_row.type_combo.itemText(index)
                for index in range(simple_row.type_combo.count())
            }
            self.assertTrue(advanced_commands.isdisjoint(simple_options))
            self.assertIn("启动程序", simple_options)
            self.assertIn("直到条件成立", simple_options)

            window.add_row({"type": 16.0, "value": "count = 1"})
            existing_row = window.task_list.itemWidget(window.task_list.item(1))
            self.assertEqual(existing_row.type_combo.currentText(), "设置变量")
            self.assertEqual(existing_row.get_data()["type"], 16.0)
            preserved_options = {
                existing_row.type_combo.itemText(index)
                for index in range(existing_row.type_combo.count())
            }
            self.assertIn("设置变量", preserved_options)
            self.assertNotIn("判断表达式", preserved_options)

            window.settings_mode_combo.setCurrentIndex(
                window.settings_mode_combo.findData("advanced")
            )
            self.app.processEvents()
            advanced_options = {
                existing_row.type_combo.itemText(index)
                for index in range(existing_row.type_combo.count())
            }
            self.assertTrue(advanced_commands.issubset(advanced_options))

            window.settings_mode_combo.setCurrentIndex(
                window.settings_mode_combo.findData("simple")
            )
            self.app.processEvents()
            self.assertEqual(existing_row.type_combo.currentText(), "设置变量")
            self.assertEqual(existing_row.get_data()["type"], 16.0)

    def test_step_dialog_moves_requested_controls_to_advanced_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dialog = TaskConfigDialog(
                None,
                {
                    "coord_step_en": True,
                    "coord_step_direction": "向下",
                },
                coordinate_step_available=True,
                base_coordinate=(100, 100),
                base_dir=temp_dir,
                settings_mode="simple",
            )
            self.addCleanup(dialog.close)
            self.assertFalse(dialog.control_form.isRowVisible(dialog.step_loop_row))
            self.assertFalse(dialog.control_form.isRowVisible(dialog.coord_reset_row))
            self.assertFalse(dialog.control_form.isRowVisible(dialog.run_max_row))
            self.assertEqual(dialog.coord_step_direction_combo.currentText(), "向下")
            self.assertFalse(dialog.coord_step_direction_combo.isEnabled())
            self.assertEqual(
                dialog.control_form.labelForField(dialog.coord_sequence_box).text(),
                "自定义点位:",
            )

            dialog.apply_settings_mode("advanced")
            self.assertTrue(dialog.control_form.isRowVisible(dialog.step_loop_row))
            self.assertTrue(dialog.control_form.isRowVisible(dialog.coord_reset_row))
            self.assertTrue(dialog.control_form.isRowVisible(dialog.run_max_row))
            directions = {
                dialog.coord_step_direction_combo.itemText(index)
                for index in range(dialog.coord_step_direction_combo.count())
            }
            self.assertEqual(directions, set(TaskConfigDialog.COORD_STEP_DIRECTIONS))
            self.assertTrue(dialog.coord_step_direction_combo.isEnabled())

            dialog.coord_step_chk.setChecked(False)
            dialog.apply_settings_mode("simple")
            self.assertEqual(dialog.coord_step_direction_combo.count(), 1)
            self.assertEqual(
                dialog.coord_step_direction_combo.currentText(), "移动到新点位"
            )

    def test_task_value_edit_participates_in_undo_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.add_row({"type": 1.0, "value": "10,10"})
            window.undo_stack.clear()
            window.redo_stack.clear()
            row = window.task_list.itemWidget(window.task_list.item(0))
            window.show()
            row.value_input.setFocus()
            self.app.processEvents()
            row.value_input.selectAll()
            QTest.keyClicks(row.value_input, "20,20")
            QTest.keyClick(row.value_input, Qt.Key_Return)
            self.app.processEvents()

            self.assertEqual(row.value_input.text(), "20,20")
            self.assertEqual(len(window.undo_stack), 1)
            window.undo_task_change()
            restored = window.task_list.itemWidget(window.task_list.item(0))
            self.assertEqual(restored.value_input.text(), "10,10")

    def test_secret_text_requires_an_existing_local_credential(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            task = {"type": 22.0, "value": "account"}
            cfg = window.get_current_ui_config()
            self.assertIn("不存在", window.validate_tasks([task], cfg))

            window.credentials.set("account", "secret")
            self.assertIsNone(window.validate_tasks([task], cfg))

    def test_task_rows_keep_content_and_selection_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.add_row({"type": 1.0, "value": "100,200"})
            row = window.task_list.itemWidget(window.task_list.item(0))
            self.assertEqual(row.objectName(), "taskRow")
            self.assertEqual(row.value_input.text(), "100,200")
            row.set_selected(True)
            self.assertTrue(row.property("selected"))
            self.assertFalse(row.cfg_btn.icon().isNull())
            self.assertFalse(row.del_btn.icon().isNull())
            self.assertEqual(window.task_count_label.text(), "1 步")

    def test_breakpoint_and_expression_controls_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.add_row(
                {
                    "type": 16.0,
                    "value": "count = 1",
                    "debug_breakpoint": True,
                    "debug_condition": "loop >= 2",
                }
            )
            item = window.task_list.item(0)
            row = window.task_list.itemWidget(item)
            self.assertEqual(row.type_combo.currentText(), "设置变量")
            self.assertTrue(row.has_breakpoint())
            self.assertFalse(row.breakpoint_mark_label.isHidden())
            self.assertTrue(row.get_data()["debug_breakpoint"])
            self.assertEqual(row.get_data()["debug_condition"], "loop >= 2")
            self.assertIn("loop >= 2", row.breakpoint_mark_label.toolTip())

            window.task_list.setCurrentItem(item)
            self.assertTrue(window.toggle_selected_breakpoint())
            self.assertFalse(row.has_breakpoint())
            self.assertTrue(row.breakpoint_mark_label.isHidden())
            self.assertFalse(row.get_data()["debug_breakpoint"])
            self.assertEqual(row.get_data()["debug_condition"], "loop >= 2")

            single_tasks, _config = window.build_single_step_request(
                {"type": 17.0, "value": "loop == 1", "debug_breakpoint": True},
                window.get_current_ui_config(),
            )
            self.assertFalse(single_tasks[0]["debug_breakpoint"])
            self.assertFalse(window.debug_pause_btn.isEnabled())
            self.assertFalse(window.debug_continue_btn.isEnabled())
            self.assertFalse(window.debug_next_btn.isEnabled())

    def test_worker_breakpoint_flow_updates_real_debug_controls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.add_row(
                {
                    "type": 16.0,
                    "value": "counter = 1",
                    "debug_breakpoint": True,
                }
            )
            window.start_task()
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and not window.debug_continue_btn.isEnabled():
                self.app.processEvents()
                QTest.qWait(10)
            self.assertTrue(window.debug_continue_btn.isEnabled())
            self.assertTrue(window.debug_next_btn.isEnabled())
            self.assertEqual(window.debug_paused_step, 1)
            self.assertEqual(window.debug_variable_values.get("step"), 1)
            row = window.task_list.itemWidget(window.task_list.item(0))
            self.assertTrue(row.property("debugPaused"))

            window.continue_debug_run()
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and window.run_controller.is_active:
                self.app.processEvents()
                QTest.qWait(10)
            self.app.processEvents()
            self.assertFalse(window.run_controller.is_active)
            self.assertEqual(window.engine.runtime_variables.get("counter"), 1)
            self.assertFalse(row.property("debugPaused"))

    def test_settings_and_ui_scaling_remain_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            self.assertGreaterEqual(window.settings_dialog.minimumWidth(), 720)
            self.assertGreaterEqual(window.settings_dialog.minimumHeight(), 520)
            window.settings_dialog.resize(720, 520)
            window.settings_dialog.show()
            self.app.processEvents()
            scroll = window.settings_dialog.findChild(QScrollArea)
            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
            base_font = window.ui_scale_edit.font().pointSizeF()
            base_height = window.ui_scale_edit.sizeHint().height()
            window.apply_ui_scale(1.5)
            self.app.processEvents()
            self.assertAlmostEqual(window.ui_scale, 1.5)
            self.assertGreater(window.ui_scale_edit.font().pointSizeF(), base_font * 1.4)
            self.assertGreater(window.ui_scale_edit.sizeHint().height(), base_height * 1.4)
            window.apply_ui_scale(1.0)
            self.app.processEvents()
            self.assertAlmostEqual(window.ui_scale_edit.font().pointSizeF(), base_font)
            self.assertEqual(window.ui_scale_edit.sizeHint().height(), base_height)

    def test_settings_actions_reflow_without_clipping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.apply_ui_scale(1.5)
            window.settings_dialog.resize(720, 520)
            window.settings_dialog.show()
            self.app.processEvents()

            row = window.settings_action_row
            action_widgets = [
                row.flow_layout.itemAt(index).widget()
                for index in range(row.flow_layout.count())
            ]
            self.assertEqual(len(action_widgets), 6)
            self.assertTrue(all(widget.isVisible() for widget in action_widgets))
            self.assertTrue(
                all(
                    widget.geometry().right() <= row.contentsRect().right()
                    for widget in action_widgets
                )
            )

            row.resize(360, row.height())
            row.flow_layout.setGeometry(row.rect())
            self.assertGreater(
                len({widget.geometry().top() for widget in action_widgets}),
                1,
            )

    def test_region_help_and_help_behavior_are_consistent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            toolbar_layout = window.region_btn.parentWidget().layout()
            region_index = toolbar_layout.indexOf(window.region_btn)
            self.assertEqual(toolbar_layout.indexOf(window.region_help_btn), region_index + 1)
            self.assertEqual(toolbar_layout.indexOf(window.preview_points_btn), region_index + 2)
            self.assertEqual(window.region_help_btn.toolTip(), window.region_help_btn.tip_text)
            self.assertEqual(window.region_help_btn.accessibleName(), "帮助")
            self.assertTrue(
                all(button.toolTip() for button in window.findChildren(HelpBtn))
            )

    def test_text_controls_grow_and_setting_rows_reflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            self.assertGreaterEqual(window.start_key_btn.minimumWidth(), 68)
            self.assertGreaterEqual(window.stop_key_btn.minimumWidth(), 68)
            self.assertEqual(
                window.run_status_pos_combo.sizeAdjustPolicy(),
                QComboBox.AdjustToContents,
            )
            mapping_action = window.key_mapping_rows[0]["action"]
            self.assertEqual(mapping_action.minimumWidth(), 0)
            self.assertLess(mapping_action.sizeHint().width(), 130)
            self.assertEqual(mapping_action.sizeAdjustPolicy(), QComboBox.AdjustToContents)
            self.assertEqual(window.run_status_pos_combo.minimumWidth(), 0)
            self.assertLess(window.run_status_pos_combo.sizeHint().width(), 120)
            row = window.system_settings_row
            self.assertIsInstance(row, ResponsiveRow)
            self.assertGreater(
                row.flow_layout.heightForWidth(420),
                row.flow_layout.heightForWidth(1600),
            )
            window.apply_ui_scale(1.8)
            self.assertGreaterEqual(window.start_key_btn.minimumWidth(), 122)
            self.assertEqual(mapping_action.minimumWidth(), 0)
            self.assertGreater(mapping_action.sizeHint().width(), 130)

    def test_settings_rows_use_one_vertical_spacing_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            self.assertEqual(window.system_settings_row.flow_layout._vertical_spacing, 7)
            self.assertEqual(
                window.key_mapping_rows[0]["container"].flow_layout._vertical_spacing,
                7,
            )
            self.assertEqual(window.mapping_rows_layout.spacing(), 7)

    def test_responsive_rows_propagate_height_to_settings_scrollbar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            dialog = window.settings_dialog
            dialog.show()
            scroll = dialog.findChild(QScrollArea)
            measurements = []
            for width in (720, 1400):
                dialog.resize(width, 700)
                for _ in range(3):
                    self.app.processEvents()
                    QTest.qWait(5)
                measurements.append(
                    (scroll.widget().height(), scroll.verticalScrollBar().maximum())
                )
            self.assertGreater(measurements[0][0], measurements[1][0])
            self.assertGreater(measurements[0][1], measurements[1][1])

    def test_responsive_groups_share_spacing_and_vertical_centers(self):
        row = ResponsiveRow()
        checkbox = QCheckBox("自适应降频")
        edit = QLineEdit("1.0")
        group = row.add_group("播放倍速:", edit, checkbox)
        self.addCleanup(row.close)
        row.resize(500, 80)
        row.show()
        self.app.processEvents()
        self.assertEqual(
            group.layout().spacing(), row.flow_layout.horizontalSpacing()
        )
        children = (
            group.findChildren(QLabel)
            + group.findChildren(QLineEdit)
            + group.findChildren(QCheckBox)
        )
        centers = [
            child.geometry().center().y() for child in children if child.isVisible()
        ]
        self.assertGreaterEqual(len(centers), 3)
        self.assertLessEqual(max(centers) - min(centers), 1)

    def test_unfocused_combo_ignores_mouse_wheel(self):
        combo = NoWheelComboBox()
        self.addCleanup(combo.close)
        combo.addItems(["一", "二"])
        event = mock.Mock()
        combo.clearFocus()
        combo.wheelEvent(event)
        event.ignore.assert_called_once_with()

    def test_resource_monitor_interval_round_trips_and_can_stop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            self.assertEqual(window.current_cpu_interval(), 3000)
            self.assertEqual(
                window.get_current_ui_config()["cpu_refresh_interval"], "auto"
            )

            window.cpu_refresh_combo.setCurrentIndex(
                window.cpu_refresh_combo.findData(2000)
            )
            self.assertEqual(window.current_cpu_interval(), 2000)
            self.assertEqual(window.cpu_timer.interval(), 2000)
            self.assertTrue(window.cpu_timer.isActive())
            self.assertEqual(
                window.get_current_ui_config()["cpu_refresh_interval"], 2000
            )

            config = window.get_current_ui_config()
            config["cpu_refresh_interval"] = "0"
            window.apply_ui_config(config)
            self.assertFalse(window.cpu_timer.isActive())
            self.assertEqual(window.cpu_label.text(), "资源监测: 已关闭")

    def test_resource_monitor_labels_system_and_whole_process_usage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            process = mock.Mock()
            process.cpu_percent.return_value = 6.25
            window.current_process = process
            with mock.patch("fukua_rpa.ui.main_window.HAS_PSUTIL", True), mock.patch(
                "fukua_rpa.ui.main_window.psutil.cpu_count", return_value=16
            ), mock.patch(
                "fukua_rpa.ui.main_window.psutil.cpu_percent", return_value=12.5
            ):
                window.update_cpu_info()

            self.assertEqual(
                window.cpu_label.text(),
                "逻辑处理器: 16 | 系统 CPU: 12.5% | 本程序 CPU: 6.2%",
            )

    def test_application_events_follow_active_timestamp_policy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.log_level_combo.setCurrentIndex(1)
            window.log_text.clear()
            window.append_application_log("<b>application-event</b>")
            self.assertRegex(
                window.log_text.toPlainText(),
                r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] application-event$",
            )

            window.log_level_combo.setCurrentIndex(0)
            window.log_text.clear()
            window.append_application_log("simple-application-event")
            self.assertEqual(
                window.log_text.toPlainText(), "simple-application-event"
            )

    def test_custom_log_menu_round_trips_without_losing_custom_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            self.assertFalse(window.log_critical_action.isEnabled())
            self.assertTrue(window.log_critical_action.isChecked())
            self.assertFalse(window.log_category_actions[LOG_ACTION].isChecked())

            window.log_category_actions[LOG_ACTION].setChecked(True)
            self.assertEqual(window.current_log_mode(), LOG_MODE_CUSTOM)
            custom_categories = set(window.current_custom_log_categories())
            self.assertIn(LOG_ACTION, custom_categories)
            self.assertNotIn(LOG_TIMESTAMP, custom_categories)

            window.select_log_preset(LOG_MODE_DETAILED)
            self.assertEqual(window.current_log_mode(), LOG_MODE_DETAILED)
            self.assertTrue(window.log_category_actions[LOG_TIMESTAMP].isChecked())
            window.log_level_combo.setCurrentIndex(
                window.log_level_combo.findData(LOG_MODE_CUSTOM)
            )
            self.assertEqual(
                set(window.current_log_policy().enabled_categories),
                custom_categories,
            )

            saved = window.get_current_ui_config()
            self.assertEqual(saved["log_mode"], LOG_MODE_CUSTOM)
            self.assertEqual(saved["log_level"], 2)
            self.assertEqual(
                set(saved["log_custom_categories"]), custom_categories
            )

            saved["log_custom_categories"] = [LOG_RECOGNITION, LOG_TIMESTAMP]
            window.apply_ui_config(saved)
            self.assertEqual(window.current_log_mode(), LOG_MODE_CUSTOM)
            self.assertEqual(
                set(window.current_custom_log_categories()),
                {LOG_RECOGNITION, LOG_TIMESTAMP},
            )
            self.assertTrue(
                window.log_category_actions[LOG_RECOGNITION].isChecked()
            )
            self.assertTrue(window.log_category_actions[LOG_TIMESTAMP].isChecked())

    def test_log_content_menu_stays_open_for_multiple_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.show()
            menu = window.log_content_menu
            menu.popup(window.mapToGlobal(QPoint(40, 40)))
            self.app.processEvents()

            action = window.log_category_actions[LOG_ACTION]
            QTest.mouseClick(
                menu,
                Qt.LeftButton,
                pos=menu.actionGeometry(action).center(),
            )
            self.app.processEvents()
            self.assertTrue(action.isChecked())
            self.assertTrue(menu.isVisible())

            recognition = window.log_category_actions[LOG_RECOGNITION]
            QTest.mouseClick(
                menu,
                Qt.LeftButton,
                pos=menu.actionGeometry(recognition).center(),
            )
            self.app.processEvents()
            self.assertTrue(recognition.isChecked())
            self.assertTrue(menu.isVisible())

            QTest.keyClick(menu, Qt.Key_Escape)
            self.app.processEvents()
            self.assertFalse(menu.isVisible())

    def test_180_percent_scale_keeps_main_command_text_visible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.show()
            window.apply_ui_scale(1.8)
            for _index in range(3):
                self.app.processEvents()
                QTest.qWait(5)

            for text in ("新增步骤", "● 操作录制", "识别区域"):
                button = next(
                    item
                    for item in window.findChildren(QPushButton)
                    if item.text() == text
                )
                with self.subTest(text=text):
                    self.assertGreater(
                        int(button.property("_ui_base_text_button_w") or 0), 0
                    )
                    self.assertGreaterEqual(
                        button.minimumWidth(), button.sizeHint().width()
                    )
                    self.assertGreaterEqual(button.width(), button.sizeHint().width())

    def test_unsupported_startup_profile_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "config.ini")
            settings = QSettings(config_path, QSettings.IniFormat)
            profile = default_profile_config()
            profile["_schema_version"] = PROFILE_SCHEMA_VERSION + 1
            profiles = {"Future": profile}
            serialized = json.dumps(profiles, ensure_ascii=False)
            settings.setValue("profiles_json", serialized)
            settings.setValue("current_profile", "Future")
            settings.setValue(
                "profiles_signature", profiles_signature(profiles, "Future")[1]
            )
            settings.sync()

            window = self.create_window(temp_dir)
            self.assertTrue(window._profiles_persistence_blocked)
            window.add_row({"type": 5.0, "value": "1"})
            self.assertTrue(window.persist_profiles_state(force=True))

            reloaded = QSettings(config_path, QSettings.IniFormat)
            self.assertEqual(reloaded.value("profiles_json"), serialized)

    def test_step_dialog_uses_compact_buttons_and_progressive_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            dialog = TaskConfigDialog(
                window,
                {},
                image_settings_available=True,
                point_limit_available=True,
                coordinate_step_available=True,
                base_coordinate=(100, 100),
                base_dir=temp_dir,
            )
            self.addCleanup(dialog.close)
            dialog.show()
            self.app.processEvents()
            compact_buttons = [dialog.coord_step_pick_btn]
            compact_buttons.extend(
                widgets[key]
                for widgets in dialog.until_condition_widgets.values()
                for key in ("image_btn", "region_btn")
            )
            for button in compact_buttons:
                self.assertTrue(button.property("compactText"))
                required = button.fontMetrics().horizontalAdvance(button.text()) + 12
                self.assertGreaterEqual(button.width(), required)
            self.assertTrue(dialog.coord_sequence_details.isHidden())
            dialog.coord_sequence_chk.setChecked(True)
            self.app.processEvents()
            self.assertTrue(dialog.coord_sequence_details.isVisible())
            self.assertFalse(dialog.debug_section.toggle_btn.isChecked())
            self.assertTrue(dialog.debug_section.content_widget.isHidden())

    def test_debug_presets_preserve_existing_and_advanced_conditions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            dialog = TaskConfigDialog(
                window,
                {"debug_breakpoint": True, "debug_condition": "loop >= 2"},
                base_dir=temp_dir,
            )
            self.addCleanup(dialog.close)
            self.assertEqual(
                dialog.debug_preset_combo.currentText(),
                "从第 N 次循环开始",
            )
            self.assertEqual(dialog.debug_preset_value_edit.text(), "2")
            self.assertEqual(dialog.get_data()["debug_condition"], "loop >= 2")
            dialog.debug_preset_combo.setCurrentText("本步骤执行 N 次后")
            dialog.debug_preset_value_edit.setText("3")
            self.assertEqual(
                dialog.get_data()["debug_condition"],
                "execution_count >= 3",
            )
            dialog.debug_preset_combo.setCurrentText("高级表达式")
            dialog.debug_condition_edit.setText("counter > 10")
            dialog.remember_debug_custom_expression("counter > 10")
            dialog.debug_preset_combo.setCurrentText("每次经过都暂停")
            dialog.debug_preset_combo.setCurrentText("高级表达式")
            self.assertEqual(dialog.debug_condition_edit.text(), "counter > 10")

    def test_open_step_dialog_refreshes_only_unedited_jump_numbers(self):
        dialog = TaskConfigDialog(
            None,
            {"success_jump": "3", "fail_jump": "2"},
            False,
            False,
            False,
            None,
            "",
            False,
            None,
            2,
            "等待(秒)",
            None,
        )
        self.addCleanup(dialog.close)
        dialog.refresh_reference_numbers(
            {"success_jump": "1", "fail_jump": "4"}
        )
        self.assertEqual(dialog.success_jump_edit.text(), "1")
        self.assertEqual(dialog.fail_jump_edit.text(), "4")

        dialog.success_jump_edit.setText("2")
        dialog.success_jump_edit.textEdited.emit("2")
        dialog.refresh_reference_numbers(
            {"success_jump": "5", "fail_jump": "1"}
        )
        self.assertEqual(dialog.success_jump_edit.text(), "2")
        self.assertEqual(dialog.fail_jump_edit.text(), "1")

    def test_mapping_status_is_the_rightmost_expandable_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.settings_dialog.resize(1500, 760)
            window.settings_dialog.show()
            self.app.processEvents()
            row_data = window.key_mapping_rows[0]
            row = row_data["container"]
            trailing = row.flow_layout.itemAt(row.flow_layout.count() - 1).widget()
            self.assertIs(trailing, row_data["binding_group"])
            self.assertTrue(trailing.property("flowTrailing"))
            self.assertLessEqual(
                abs(trailing.geometry().right() - row.contentsRect().right()), 1
            )
            row_data["window_binding"] = {
                "root_title": "完整显示的目标程序窗口名称",
            }
            window.mapping_click_mode_combo.setCurrentText("后台窗口点击(实验)")
            window.update_mapping_window_binding_ui(row_data)
            self.assertEqual(
                row_data["binding_status"].text(),
                "已绑定：完整显示的目标程序窗口名称",
            )

    def test_debug_toolbar_and_playback_label_use_new_layout_terms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.resize(1100, 760)
            window.show()
            self.app.processEvents()
            self.assertGreater(
                window.debug_caption.mapTo(window, window.debug_caption.rect().topLeft()).x(),
                window.width() // 2,
            )
            labels = [label.text() for label in window.settings_dialog.findChildren(QLabel)]
            self.assertIn("播放倍速:", labels)
            self.assertNotIn("录制倍速:", labels)

    def test_enter_in_ui_scale_does_not_activate_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.settings_dialog.show()
            self.app.processEvents()
            export_button = next(
                button
                for button in window.settings_dialog.findChildren(QPushButton)
                if button.property("variant") == "primary"
            )
            clicks = []
            export_button.clicked.connect(lambda: clicks.append(True))
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
                window.ui_scale_edit.setFocus()
                window.ui_scale_edit.selectAll()
                QTest.keyClicks(window.ui_scale_edit, "125")
                QTest.keyClick(window.ui_scale_edit, Qt.Key_Return)
                self.app.processEvents()
            self.assertEqual(clicks, [])
            self.assertAlmostEqual(window.ui_scale, 1.25)
            self.assertTrue(
                all(
                    not button.autoDefault()
                    for button in window.settings_dialog.findChildren(QPushButton)
                )
            )

    def test_hotkey_dialog_displays_live_modifier_progress(self):
        fake_thread = mock.Mock()
        fake_thread.keyboard_hook = 1
        fake_thread.isRunning.return_value = False
        with mock.patch(
            "fukua_rpa.ui.input_tools.HotkeyCaptureHookThread",
            return_value=fake_thread,
        ):
            dialog = KeyCaptureDialog(title="测试热键")
        self.addCleanup(dialog.close)
        dialog.on_native_progress("Ctrl+Alt+Shift")
        self.assertEqual(dialog.preview_label.text(), "当前按下：Ctrl+Alt+Shift")
        dialog.on_native_captured("ctrl+alt+shift+a")
        self.assertEqual(dialog.preview_label.text(), "已录入：Ctrl+Alt+Shift+A")

    def test_responsive_setting_groups_are_vertically_centered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.settings_dialog.resize(1180, 780)
            window.settings_dialog.show()
            self.app.processEvents()
            row = window.settings_dialog.findChildren(ResponsiveRow)[0]
            centers = []
            for index in range(row.flow_layout.count()):
                widget = row.flow_layout.itemAt(index).widget()
                if widget is not None and widget.isVisible():
                    centers.append(widget.geometry().center().y())
            self.assertGreater(len(centers), 1)
            self.assertLessEqual(max(centers) - min(centers), 1)

    def test_step_settings_wrap_and_keep_text_buttons_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            dialog = TaskConfigDialog(
                window,
                {},
                image_settings_available=True,
                point_limit_available=True,
                coordinate_step_available=True,
                image_click_point_available=True,
                base_coordinate=(100, 100),
                base_dir=temp_dir,
            )
            self.addCleanup(dialog.close)
            self.assertGreaterEqual(dialog.image_click_point_select_btn.minimumWidth(), 68)
            self.assertGreaterEqual(dialog.image_click_point_preview_btn.minimumWidth(), 68)
            self.assertGreaterEqual(dialog.step_region_pick_btn.minimumWidth(), 68)
            self.assertGreaterEqual(dialog.step_region_clear_btn.minimumWidth(), 68)
            forms = dialog.findChildren(QFormLayout)
            self.assertTrue(forms)
            self.assertTrue(
                all(form.rowWrapPolicy() == QFormLayout.WrapLongRows for form in forms)
            )
            dialog.resize(900, 520)
            dialog.show()
            self.app.processEvents()
            scroll = dialog.findChild(QScrollArea)
            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)

    def test_mapping_hotkey_capture_returns_focus_to_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.settings_dialog.show()
            self.app.processEvents()
            created = {}

            class FakeCaptureDialog:
                captured_text = "F8"

                def __init__(self, parent, title):
                    created["parent"] = parent
                    created["title"] = title

                def exec(self):
                    return QDialog.Accepted

            with mock.patch(
                "fukua_rpa.ui.main_window.KeyCaptureDialog", FakeCaptureDialog
            ), mock.patch.object(window, "refresh_hotkey_backend"):
                window.capture_mapping_hotkey(0)

            self.assertIs(created["parent"], window.settings_dialog)
            self.assertEqual(created["title"], "录入映射1热键")
            self.assertEqual(window.key_mapping_rows[0]["hotkey"].text(), "F8")
            self.assertTrue(window.settings_dialog.isVisible())

    def test_mapping_binding_looks_through_own_windows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            with mock.patch.object(user32, "WindowFromPoint", return_value=101), \
                    mock.patch.object(user32, "GetAncestor", return_value=101), \
                    mock.patch.object(user32, "EnumChildWindows", return_value=True), \
                    mock.patch.object(
                        window,
                        "hwnd_belongs_to_current_process",
                        side_effect=lambda hwnd: int(hwnd) == 101,
                    ), mock.patch.object(
                        window, "top_level_window_at_point", return_value=202
                    ) as find_under, mock.patch.object(
                        window, "hwnd_screen_area_at_point", return_value=120000
                    ):
                target = window.background_click_target_hwnd(
                    400, 300, exclude_current_process=True
                )

            self.assertEqual(int(target), 202)
            find_under.assert_called_once_with(
                400, 300, exclude_current_process=True
            )

    def test_window_selection_is_only_available_in_background_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            row = window.key_mapping_rows[0]
            self.assertFalse(row["bind_window"].isEnabled())
            self.assertFalse(row["inspect_btn"].isEnabled())
            window.mapping_click_mode_combo.setCurrentText("后台窗口点击(实验)")
            self.assertTrue(row["bind_window"].isEnabled())
            self.assertFalse(row["inspect_btn"].isEnabled())
            row["window_binding"] = {"root_hwnd": 700}
            window.update_mapping_window_binding_ui(row)
            self.assertTrue(row["inspect_btn"].isEnabled())
            window.mapping_click_mode_combo.setCurrentText("点击后返回原位")
            self.assertFalse(row["bind_window"].isEnabled())
            self.assertFalse(row["inspect_btn"].isEnabled())

    def test_coordinate_pick_does_not_guess_or_bind_a_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            row = window.key_mapping_rows[0]
            self.assertIsNone(window.mapping_backend)
            window.on_mapping_coordinate_picked_by_row(row, "320,240")
            self.assertEqual(row["coord"].text(), "320,240")
            self.assertEqual(row["window_binding"], {})
            self.assertIsNone(window.mapping_backend)

    def test_manual_window_pick_binds_selection_to_mapping_coordinate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            row = window.key_mapping_rows[0]
            row["coord"].setText("320,240")
            window.mapping_click_mode_combo.setCurrentText("后台窗口点击(实验)")
            binding = {
                "root_hwnd": 700,
                "root_title": "Target application",
                "root_class": "TargetWindow",
            }
            backend = mock.Mock()
            backend.create_binding_for_window_at_point.return_value = binding
            window.mapping_backend = backend
            self.assertTrue(
                window.on_mapping_window_picked_by_row(row, "900,500")
            )
            create_binding = backend.create_binding_for_window_at_point
            create_binding.assert_called_once_with(900, 500, 320, 240)
            self.assertEqual(row["window_binding"], binding)

    def test_background_click_failure_never_moves_the_real_mouse(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.mapping_click_mode_combo.setCurrentText("后台窗口点击(实验)")
            with mock.patch.object(
                window, "perform_mapping_background_click", return_value=False
            ), mock.patch.object(window, "perform_mapping_mouse_click") as foreground:
                result = window.perform_key_mapping_click(
                    100, 200, "left", 1, {"root_hwnd": 700}
                )
            self.assertIn("失败", result)
            foreground.assert_not_called()

    def test_application_icon_assets_are_ready_for_packaging(self):
        icon_path = get_resource_path(os.path.join("assets", "fukuaRPA.ico"))
        self.assertTrue(os.path.isfile(icon_path))
        self.assertFalse(QIcon(icon_path).isNull())
        root = os.path.dirname(os.path.dirname(__file__))
        for spec_name in ("fukuaRPA_onedir.spec", "fukuaRPA_onefile.spec"):
            spec_path = os.path.join(root, spec_name)
            with open(spec_path, "r", encoding="utf-8") as spec_file:
                spec = spec_file.read()
            self.assertIn('icon="assets/fukuaRPA.ico"', spec)
            self.assertIn('("assets/fukuaRPA.ico", "assets")', spec)

    def test_offline_diagnostic_report_excludes_script_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            secret_value = "D:/private/secret-template.png"
            window.add_row({"type": 1.0, "value": secret_value})
            report = window.collect_diagnostic_report()
            serialized = json.dumps(report, ensure_ascii=False)
            buttons = window.settings_dialog.findChildren(QPushButton)

            self.assertTrue(any(button.text() == "导出诊断" for button in buttons))
            self.assertEqual(report["application"]["task_count"], 1)
            self.assertIn("engine_last_run", report["performance"])
            self.assertNotIn(secret_value, serialized)

    def test_native_optimization_controls_round_trip_stable_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.native_parallel_combo.setCurrentIndex(
                window.native_parallel_combo.findData("force")
            )
            window.native_scale_hint_chk.setChecked(False)
            window.scale_memory_tier_combo.setCurrentIndex(
                window.scale_memory_tier_combo.findData("aggressive")
            )
            window.scale_memory_manual_edit.setText("0.8, 1.0, 1.2")
            window.scale_memory_custom_chk.setChecked(True)
            window.scale_memory_preferred_spin.setValue(4)
            window.scale_memory_history_spin.setValue(80)
            config = window.get_current_ui_config()
            self.assertEqual(config["native_parallel_mode"], "force")
            self.assertFalse(config["native_scale_hint_en"])
            self.assertEqual(config["scale_memory_tier"], "aggressive")
            self.assertEqual(config["scale_memory_manual"], "0.8, 1.0, 1.2")
            self.assertTrue(config["scale_memory_custom_en"])
            self.assertEqual(config["scale_memory_preferred_limit"], 4)
            self.assertEqual(config["scale_memory_history_limit"], 80)

            window.apply_ui_config(config)
            self.assertEqual(window.native_parallel_combo.currentData(), "force")
            self.assertFalse(window.native_scale_hint_chk.isChecked())
            self.assertEqual(window.scale_memory_tier_combo.currentData(), "aggressive")
            self.assertTrue(window.scale_memory_preferred_spin.isEnabled())
            window.native_core_chk.setChecked(False)
            self.assertFalse(window.native_parallel_combo.isEnabled())
            self.assertTrue(window.native_scale_hint_chk.isEnabled())

    def test_native_parallel_combo_is_compact_and_keeps_longest_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.settings_dialog.resize(920, 700)
            window.settings_dialog.show()
            self.app.processEvents()
            combo = window.native_parallel_combo
            self.assertEqual(combo.minimumWidth(), combo.maximumWidth())
            self.assertLessEqual(combo.width(), combo.sizeHint().width() + 2)
            self.assertGreater(
                combo.width(), combo.fontMetrics().horizontalAdvance("关闭（单线程）")
            )

    def test_scale_memory_status_exposes_dynamic_decisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            self.assertFalse(window.scale_memory_custom_chk.isChecked())
            self.assertFalse(window.scale_memory_preferred_spin.isEnabled())
            self.assertFalse(window.scale_memory_history_spin.isEnabled())
            policy = window.current_scale_memory_policy()
            key = ("template.png", 1)
            valid_scales = (0.8, 0.9, 1.0, 1.1, 1.2)
            for scale in (1.0, 1.2, 1.0, 0.8, 1.0):
                window.engine.scale_memory_store.record(
                    key,
                    "template.png",
                    valid_scales,
                    scale,
                    0.95,
                    policy,
                )
            window.refresh_scale_memory_status()
            status = window.scale_memory_status_label.text()
            self.assertIn("当前优先", status)
            self.assertIn("[1", status)
            self.assertIn("历史上限", status)

    def test_consecutive_delete_restores_danger_hover_without_tooltip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.add_row({"type": 1.0, "value": "10,10"})
            window.add_row({"type": 1.0, "value": "20,20"})
            first = window.task_list.itemWidget(window.task_list.item(0))
            second = window.task_list.itemWidget(window.task_list.item(1))
            with mock.patch.object(
                QApplication, "widgetAt", return_value=second.del_btn
            ), mock.patch.object(QToolTip, "showText") as show_tooltip:
                window.del_row(first)
                QTest.qWait(40)
                self.app.processEvents()
            self.assertTrue(second.del_btn.property("syntheticHover"))
            show_tooltip.assert_not_called()
            self.assertIn(
                'QPushButton[variant="dangerGhost"][syntheticHover="true"]',
                self.app.styleSheet(),
            )

    def test_script_check_reports_non_exiting_self_jump_without_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            cfg = window.get_current_ui_config()
            tasks = [{"type": 5.0, "value": "0", "success_jump": "1", "fail_jump": "1"}]
            report = window.script_check_report(tasks, cfg)
            buttons = window.findChildren(QPushButton)

            self.assertEqual(report["syntax_error"], "")
            self.assertTrue(
                any(item["code"] == "no_exit_path" for item in report["structure"])
            )
            self.assertTrue(report["loop_risks"])
            self.assertTrue(
                any("检查步骤语法" in button.toolTip() for button in buttons)
            )

    def test_single_step_request_removes_loops_waits_and_branches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            cfg = window.get_current_ui_config()
            tasks, single_cfg = window.build_single_step_request(
                {
                    "type": 5.0,
                    "value": "0",
                    "retry": -1,
                    "repeat_mode": "无限重复",
                    "no_skip_wait": True,
                    "success_jump": "8",
                    "fail_jump": "3",
                },
                cfg,
            )
            task = tasks[0]
            self.assertEqual(task["retry"], 1)
            self.assertEqual(task["repeat_mode"], "执行一次")
            self.assertFalse(task["no_skip_wait"])
            self.assertEqual(task["success_jump"], "0")
            self.assertEqual(task["fail_jump"], "0")
            self.assertEqual(single_cfg["loop_mode"], "单次")
            self.assertEqual(single_cfg["start_step"], "1")

    def test_single_step_button_launches_only_the_selected_step(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window = self.create_window(temp_dir)
            window.add_row(
                {
                    "type": 5.0,
                    "value": "0",
                    "repeat_mode": "无限重复",
                    "success_jump": "1",
                }
            )
            window.task_list.setCurrentRow(0)
            with mock.patch.object(
                window.run_controller, "start", return_value=(True, "")
            ) as start:
                window.run_selected_step_once()

            launched_tasks = start.call_args.args[0]
            self.assertEqual(len(launched_tasks), 1)
            self.assertEqual(launched_tasks[0]["repeat_mode"], "执行一次")
            self.assertEqual(launched_tasks[0]["success_jump"], "0")
            self.assertFalse(window.single_step_btn.isEnabled())
            window.on_finish()
            self.assertTrue(window.single_step_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
