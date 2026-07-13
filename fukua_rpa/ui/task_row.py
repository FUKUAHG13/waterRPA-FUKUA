"""Task-list row editor and drag-aware list widget."""

import copy
import os

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDrag,
    QFont,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QStyle,
)

from ..constants import TASK_TYPE_LAUNCH_APP, TASK_TYPE_UNTIL
from ..commands import COMMAND_BY_CODE, command_code, command_names
from ..task_model import (
    config_bool,
    parse_coord_step_manual_points,
    parse_coordinate_text,
    until_condition_defaults,
    until_condition_summary,
)
from .components import NoWheelComboBox, TaskConfigDialog
from .input_tools import CoordinatePickerUI, KeyCaptureDialog


class RefreshableHoverButton(QPushButton):
    """Keep a hover highlight when list reflow moves this button under the cursor."""

    def set_synthetic_hover(self, enabled):
        enabled = bool(enabled)
        if bool(self.property("syntheticHover")) == enabled:
            return
        self.setProperty("syntheticHover", enabled)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def enterEvent(self, event):
        self.set_synthetic_hover(False)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.set_synthetic_hover(False)
        super().leaveEvent(event)


class TaskRow(QFrame):
    def __init__(self, delete_callback, settings_mode="simple"):
        super().__init__()
        self.setObjectName("taskRow")
        self.setMinimumHeight(42)
        self.parent_item = None
        self._value_edit_snapshot = None
        self._value_edit_original = ""
        self._type_edit_snapshot = None
        self._type_edit_original = ""
        self.settings_mode = (
            "advanced" if str(settings_mode) == "advanced" else "simple"
        )
        self.custom_data = {
            "step_id": "",
            "custom_en": False,
            "custom_conf": "0.8",
            "custom_scale_min": "1.0",
            "custom_scale_max": "1.0",
            "custom_scale_step": "0.05",
            "custom_gray": True,
            "repeat_mode": "执行一次",
            "repeat_count": "1",
            "step_loop_start": "1",
            "step_loop_end": "0",
            "fail_limit": "1",
            "success_skip": "0",
            "success_jump": "0",
            "success_target_id": "",
            "fail_skip": "0",
            "fail_jump": "0",
            "fail_target_id": "",
            "no_skip_wait": False,
            "point_limit_en": False,
            "point_limit_count": "0",
            "image_click_point_en": False,
            "image_click_point_rx": "0.5",
            "image_click_point_ry": "0.5",
            "step_region_en": False,
            "step_region": "",
            "coord_step_en": False,
            "coord_step_every": "1",
            "coord_step_direction": "向下",
            "coord_step_distance": "0",
            "coord_step_dx": "0",
            "coord_step_dy": "0",
            "coord_step_point": "",
            "coord_step_max_steps": "0",
            "coord_step_max_distance": "0",
            "coord_step_stop": False,
            "coord_step_reset_after": "0",
            "coord_step_manual_points": "{}",
            "coord_sequence_en": False,
            "coord_sequence_points": "",
            "coord_sequence_end_action": "点完后跳过本步",
            "run_max_executions": "0",
            "debug_breakpoint": False,
            "debug_condition": "",
            "recorded_duration": "0",
            "uia_binding": {},
        }
        self.custom_data.update(until_condition_defaults())
        self.custom_data.setdefault("until_false_target_id", "")
        self.custom_data.setdefault("until_true_target_id", "")
        
        self.setFrameShape(QFrame.StyledPanel)
        self.set_selected(False)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(8, 5, 7, 5)
        self.layout.setSpacing(6)
        
        self.index_label = QLabel("1.")
        self.index_label.setObjectName("stepIndex")
        self.index_label.setFixedWidth(32)
        self.index_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.index_label)

        self.manual_mark_label = QLabel("修")
        self.manual_mark_label.setObjectName("manualMark")
        self.manual_mark_label.setFixedSize(20, 20)
        self.manual_mark_label.setAlignment(Qt.AlignCenter)
        self.manual_mark_label.setToolTip("本步骤包含坐标步进手动修正点")
        self.manual_mark_label.hide()
        self.layout.addWidget(self.manual_mark_label)

        self.breakpoint_mark_label = QLabel("断")
        self.breakpoint_mark_label.setObjectName("breakpointMark")
        self.breakpoint_mark_label.setFixedSize(20, 20)
        self.breakpoint_mark_label.setAlignment(Qt.AlignCenter)
        self.breakpoint_mark_label.setToolTip(
            "本步骤已设置调试断点；运行到这里会在执行前暂停"
        )
        self.breakpoint_mark_label.hide()
        self.layout.addWidget(self.breakpoint_mark_label)
        
        self.type_combo = NoWheelComboBox()
        self.type_combo.addItems(
            command_names(include_advanced=self.settings_mode == "advanced")
        )
        self.type_combo.setMinimumWidth(130)
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        self.type_combo.activated.connect(self.finish_type_history)
        self.type_combo.installEventFilter(self)
        self.layout.addWidget(self.type_combo)
        
        self.value_input = QLineEdit()
        self.value_input.textChanged.connect(self.sync_data)
        self.value_input.editingFinished.connect(self.finish_value_history)
        self.value_input.installEventFilter(self)
        self.layout.addWidget(self.value_input)
        
        self.file_btn = QPushButton("图")
        self.file_btn.setFixedWidth(30)
        self.file_btn.setProperty("iconOnly", True)
        self.file_btn.setProperty("variant", "ghost")
        self.file_btn.setToolTip("选择图片文件")
        self.file_btn.clicked.connect(self.select_file)
        self.layout.addWidget(self.file_btn)

        self.pick_btn = QPushButton("取")
        self.pick_btn.setFixedWidth(30)
        self.pick_btn.setProperty("iconOnly", True)
        self.pick_btn.setProperty("variant", "tonal")
        self.pick_btn.setToolTip("选取屏幕坐标\n单击/悬停：左键单击目标位置\n拖拽：按住左键拖动并松开\n右键取消")
        self.pick_btn.clicked.connect(self.handle_pick_button)
        self.layout.addWidget(self.pick_btn)
        
        self.cfg_btn = QPushButton("")
        self.cfg_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.cfg_btn.setFixedWidth(30)
        self.cfg_btn.setProperty("iconOnly", True)
        self.cfg_btn.setProperty("variant", "ghost")
        self.cfg_btn.setToolTip("步骤设置\n包含图片识别参数、重复次数、同点点击上限和条件分支")
        self.cfg_btn.clicked.connect(self.open_custom_config)
        self.layout.addWidget(self.cfg_btn)
        
        self.del_btn = RefreshableHoverButton("")
        self.del_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.del_btn.setFixedWidth(30)
        self.del_btn.setProperty("iconOnly", True)
        self.del_btn.setProperty("variant", "dangerGhost")
        self.del_btn.setToolTip("删除此步骤")
        self.del_btn.clicked.connect(lambda: delete_callback(self))
        self.layout.addWidget(self.del_btn)
        
        self.on_type_changed(self.type_combo.currentText())

    def set_settings_mode(self, mode):
        mode = "advanced" if str(mode) == "advanced" else "simple"
        current_name = self.type_combo.currentText()
        options = command_names(
            include_advanced=mode == "advanced",
            preserve_names=(current_name,),
        )
        self.settings_mode = mode
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItems(options)
        if current_name in options:
            self.type_combo.setCurrentText(current_name)
        self.type_combo.blockSignals(False)
        self.on_type_changed(self.type_combo.currentText())

    def task_snapshot(self):
        main_window = self.window()
        if hasattr(main_window, "snapshot_tasks"):
            return main_window.snapshot_tasks()
        return None

    def commit_task_snapshot(self, snapshot):
        main_window = self.window()
        if snapshot is not None and hasattr(main_window, "push_undo_snapshot"):
            main_window.push_undo_snapshot(snapshot)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "value_input", None) and event.type() == QEvent.FocusIn:
            if self._value_edit_snapshot is None:
                self._value_edit_snapshot = self.task_snapshot()
                self._value_edit_original = self.value_input.text()
        elif watched is getattr(self, "type_combo", None) and event.type() in (
            QEvent.MouseButtonPress,
            QEvent.KeyPress,
        ):
            if self._type_edit_snapshot is None:
                self._type_edit_snapshot = self.task_snapshot()
                self._type_edit_original = self.type_combo.currentText()
        return super().eventFilter(watched, event)

    def finish_value_history(self):
        snapshot = self._value_edit_snapshot
        changed = self.value_input.text() != self._value_edit_original
        self._value_edit_snapshot = None
        if changed:
            self.commit_task_snapshot(snapshot)

    def finish_type_history(self, _index=None):
        snapshot = self._type_edit_snapshot
        changed = self.type_combo.currentText() != self._type_edit_original
        self._type_edit_snapshot = None
        if changed:
            self.commit_task_snapshot(snapshot)

    def push_undo_before_external_edit(self):
        main_window = self.window()
        if hasattr(main_window, "push_undo_state"):
            main_window.push_undo_state()

    def set_parent_item(self, item):
        self.parent_item = item
        self.sync_data() 

    def set_selected(self, selected):
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def sync_data(self):
        text = self.type_combo.currentText()
        coord_mode = self.is_direct_coordinate_value(text)
        self.update_markers()
        if text == "直到条件成立":
            self.cfg_btn.setVisible(True)
            self.cfg_btn.setToolTip("步骤设置\n设置图片出现/消失、区域变化或多条件组合；未满足时可跳回指定步骤。")
        elif "单击" in text or "双击" in text or "悬停" in text:
            self.cfg_btn.setVisible(True)
            if coord_mode:
                self.cfg_btn.setToolTip("步骤设置\n当前参数是屏幕坐标，图片识别参数会自动忽略；重复和条件分支仍然生效")
            else:
                self.cfg_btn.setToolTip("步骤设置\n包含图片识别参数、图片内点击点、重复次数、同点点击上限和条件分支")
        else:
            self.cfg_btn.setVisible(True)
            self.cfg_btn.setToolTip("步骤设置\n包含重复次数和条件分支")

        if text == "系统按键":
            self.pick_btn.setVisible(True)
            self.pick_btn.setText("键")
            self.pick_btn.setToolTip("录入按键或组合键\n点击后直接按下要填写的键，例如 A、Enter、Ctrl+C")
        elif text in ("等待窗口", "激活窗口", "关闭窗口"):
            self.pick_btn.setVisible(True)
            self.pick_btn.setText("窗")
            self.pick_btn.setToolTip("从屏幕上选取目标程序窗口")
        elif text in ("点击窗口控件", "设置控件文本", "读取控件文本"):
            self.pick_btn.setVisible(True)
            self.pick_btn.setText("控")
            self.pick_btn.setToolTip(
                "从屏幕上选取目标控件\n目标程序需保持打开；运行时会按窗口与控件特征重新定位"
            )
        else:
            self.pick_btn.setText("取")
            self.pick_btn.setToolTip("选取屏幕坐标\n单击/悬停：左键单击目标位置\n拖拽：按住左键拖动并松开\n右键取消")
            self.pick_btn.setVisible(self.is_coordinate_pickable(text))
            
        if getattr(self, 'parent_item', None):
            self.parent_item.setData(Qt.UserRole, self.get_data())
            self.parent_item.setData(Qt.UserRole + 1, self.drag_summary())
            self.parent_item.setText("")
        self.refresh_config_dialog_context()

    def drag_summary(self):
        value = self.value_input.text().replace("\n", " ").strip()
        if len(value) > 80:
            value = value[:77] + "..."
        marks = []
        if self.has_breakpoint():
            marks.append("断")
        if self.has_coord_step_manual_points():
            marks.append("修")
        mark = f" [{'|'.join(marks)}]" if marks else ""
        if self.type_combo.currentText() == "直到条件成立":
            value = until_condition_summary(self.custom_data)
        return f"{self.index_label.text()}{mark} {self.type_combo.currentText()} | {value}"

    def has_coord_step_manual_points(self):
        return (
            config_bool(self.custom_data.get("coord_step_en", False))
            and str(self.custom_data.get("coord_step_direction", "")) == "移动到新点位"
            and bool(parse_coord_step_manual_points(self.custom_data.get("coord_step_manual_points", "{}")))
        )

    def update_manual_marker(self):
        self.manual_mark_label.setVisible(self.has_coord_step_manual_points())

    def has_breakpoint(self):
        return config_bool(self.custom_data.get("debug_breakpoint", False))

    def update_markers(self):
        self.update_manual_marker()
        has_breakpoint = self.has_breakpoint()
        condition = str(self.custom_data.get("debug_condition", "") or "").strip()
        self.breakpoint_mark_label.setToolTip(
            f"条件断点：{condition}"
            if has_breakpoint and condition
            else "调试断点：运行到本步骤时会在执行前暂停。按 F8 可切换。"
        )
        self.breakpoint_mark_label.setVisible(has_breakpoint)

    def set_breakpoint(self, enabled):
        self.custom_data["debug_breakpoint"] = bool(enabled)
        self.update_markers()
        self.sync_data()

    def set_debug_paused(self, paused):
        self.setProperty("debugPaused", bool(paused))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def is_coordinate_pickable(self, text=None):
        if text is None:
            text = self.type_combo.currentText()
        return text in ["左键单击", "左键双击", "右键单击", "左键拖拽", "右键拖拽", "鼠标悬停"]

    def parse_direct_coordinate(self, val):
        try:
            parts = str(val).strip().split(',')
            if len(parts) == 2:
                int(parts[0].strip())
                int(parts[1].strip())
                return True
        except Exception: pass
        return False

    def direct_coordinate_tuple(self):
        return parse_coordinate_text(self.value_input.text())

    def is_direct_coordinate_value(self, text=None):
        if text is None:
            text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击", "鼠标悬停"]:
            return False
        return self.parse_direct_coordinate(self.value_input.text())

    def start_coordinate_pick(self):
        text = self.type_combo.currentText()
        if not self.is_coordinate_pickable(text):
            return
        mode = "drag" if "拖拽" in text else "point"
        self.coordinate_picker = CoordinatePickerUI(mode, self.on_coordinate_picked)

    def handle_pick_button(self):
        text = self.type_combo.currentText()
        if text == "系统按键":
            self.start_key_capture()
        elif text in ("等待窗口", "激活窗口", "关闭窗口"):
            self.coordinate_picker = CoordinatePickerUI(
                "window", self.on_window_picked
            )
        elif text in ("点击窗口控件", "设置控件文本", "读取控件文本"):
            self.coordinate_picker = CoordinatePickerUI(
                "window", self.on_uia_control_picked
            )
        else:
            self.start_coordinate_pick()

    def on_window_picked(self, value):
        point = parse_coordinate_text(value)
        if not point:
            return
        try:
            from ..window_actions import window_title_at_point

            self.push_undo_before_external_edit()
            self.value_input.setText(window_title_at_point(*point))
        except Exception as error:
            QMessageBox.warning(self, "窗口选取失败", str(error))

    def on_uia_control_picked(self, value):
        point = parse_coordinate_text(value)
        if not point:
            return
        backend = None
        try:
            from ..mapping_backend import WindowMappingBackend

            backend = WindowMappingBackend()
            binding = backend.create_binding(*point)
            self.push_undo_before_external_edit()
            self.custom_data["uia_binding"] = binding
            title = str(binding.get("root_title") or "目标窗口").strip()
            control_class = str(binding.get("target_class") or "控件").strip()
            if self.type_combo.currentText() == "点击窗口控件":
                self.value_input.setText(f"{title} / {control_class}")
            self.value_input.setToolTip(
                f"已绑定：{title}\n控件类型：{control_class}\n点击“控”可重新选择"
            )
            self.sync_data()
        except Exception as error:
            QMessageBox.warning(self, "控件选取失败", str(error))
        finally:
            if backend is not None:
                backend.close()

    def start_key_capture(self):
        dialog = KeyCaptureDialog(self, "录入系统按键")
        if dialog.exec() == QDialog.Accepted and dialog.captured_text:
            self.push_undo_before_external_edit()
            self.value_input.setText(dialog.captured_text)
            self.sync_data()

    def on_coordinate_picked(self, value):
        self.push_undo_before_external_edit()
        self.value_input.setText(value)
        self.sync_data()

    def open_custom_config(self):
        if getattr(self, "config_dialog", None) and self.config_dialog.isVisible():
            self.refresh_config_dialog_context()
            self.config_dialog.show()
            self.config_dialog.raise_()
            self.config_dialog.activateWindow()
            return

        self._config_dialog_touched_value = False
        self._config_edit_snapshot = self.task_snapshot()
        self._config_value_before_dialog_change = None
        self._config_dialog_last_value = None
        main_window = self.window()
        dialog = TaskConfigDialog(
            None,
            self.custom_data,
            self.image_settings_available(),
            self.point_limit_available(),
            self.coordinate_step_available(),
            self.direct_coordinate_tuple(),
            self.value_input.text().strip(),
            self.image_click_point_available(),
            self.on_config_base_coordinate_changed,
            self.current_step_index(),
            self.type_combo.currentText(),
            getattr(main_window, "base_dir", None),
            settings_mode=(
                main_window.current_settings_mode()
                if hasattr(main_window, "current_settings_mode")
                else "simple"
            ),
        )
        self.config_dialog = dialog
        dialog.accepted.connect(lambda d=dialog: self.apply_custom_config(d))
        dialog.finished.connect(lambda result, d=dialog: self.clear_custom_config_dialog(d, result))
        if hasattr(main_window, "register_task_config_dialog"):
            main_window.register_task_config_dialog(dialog)
        if hasattr(main_window, "apply_ui_scale_to_widget"):
            main_window.apply_ui_scale_to_widget(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def apply_custom_config(self, dialog):
        self.commit_task_snapshot(getattr(self, "_config_edit_snapshot", None))
        updated = dict(self.custom_data)
        updated.update(dialog.get_data())
        main_window = self.window()
        if hasattr(main_window, "resolve_task_reference_edits"):
            updated = main_window.resolve_task_reference_edits(self, updated)
        self.custom_data = updated
        if self.type_combo.currentText() == "直到条件成立":
            self.value_input.setText(until_condition_summary(self.custom_data))
        self.sync_data()

    def current_step_index(self):
        try:
            return int(str(self.index_label.text()).strip().rstrip("."))
        except Exception:
            return None

    def refresh_config_dialog_context(self):
        dialog = getattr(self, "config_dialog", None)
        if not dialog:
            return
        try:
            dialog.update_step_context(
                self.image_settings_available(),
                self.point_limit_available(),
                self.coordinate_step_available(),
                self.direct_coordinate_tuple(),
                self.value_input.text().strip(),
                self.image_click_point_available(),
                self.current_step_index(),
                self.type_combo.currentText()
            )
            if hasattr(dialog, "refresh_reference_numbers"):
                dialog.refresh_reference_numbers(self.custom_data)
        except RuntimeError:
            self.config_dialog = None

    def on_config_base_coordinate_changed(self, value):
        if not getattr(self, "_config_dialog_touched_value", False):
            self._config_value_before_dialog_change = self.value_input.text()
        self._config_dialog_touched_value = True
        self._config_dialog_last_value = str(value)
        self.value_input.setText(str(value))
        if getattr(self, "config_dialog", None):
            self.config_dialog.base_coordinate = parse_coordinate_text(value)
            self.config_dialog.update_coord_step_ui()
        self.sync_data()

    def clear_custom_config_dialog(self, dialog, result=None):
        if result != QDialog.Accepted and getattr(self, "_config_dialog_touched_value", False):
            if self.value_input.text() == str(getattr(self, "_config_dialog_last_value", "")):
                self.value_input.setText(str(getattr(self, "_config_value_before_dialog_change", "") or ""))
                self.sync_data()
        for attr in ["_config_dialog_touched_value", "_config_value_before_dialog_change", "_config_dialog_last_value"]:
            if hasattr(self, attr):
                delattr(self, attr)
        if hasattr(self, "_config_edit_snapshot"):
            del self._config_edit_snapshot
        if getattr(self, "config_dialog", None) is dialog:
            self.config_dialog = None
        main_window = self.window()
        if hasattr(main_window, "unregister_task_config_dialog"):
            main_window.unregister_task_config_dialog(dialog)
        dialog.deleteLater()

    def close_config_dialog(self):
        dialog = getattr(self, "config_dialog", None)
        if dialog:
            try:
                dialog.close()
            except RuntimeError:
                self.config_dialog = None

    def image_settings_available(self):
        text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击", "鼠标悬停"]:
            return False
        return not self.is_direct_coordinate_value(text)

    def point_limit_available(self):
        text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击"]:
            return False
        return not self.is_direct_coordinate_value(text)

    def image_click_point_available(self):
        text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击"]:
            return False
        if self.is_direct_coordinate_value(text):
            return False
        return os.path.isfile(self.value_input.text().strip())

    def coordinate_step_available(self):
        text = self.type_combo.currentText()
        if text not in ["左键单击", "左键双击", "右键单击"]:
            return False
        return self.is_direct_coordinate_value(text)

    def on_type_changed(self, text):
        tips = {
            "左键单击": ("【左键单击】\n识别目标图片并点击其中心，或直接点击指定屏幕坐标。\n参数格式：图片完整路径 或 屏幕坐标，如：100,100", "输入图片路径 或 屏幕坐标，如：960,540"),
            "左键双击": ("【左键双击】\n识别目标图片并双击其中心，或直接双击指定屏幕坐标。\n参数格式：图片完整路径 或 屏幕坐标，如：100,100", "输入图片路径 或 屏幕坐标，如：960,540"),
            "右键单击": ("【右键单击】\n识别目标图片并右击其中心，或直接右击指定屏幕坐标。\n参数格式：图片完整路径 或 屏幕坐标，如：100,100", "输入图片路径 或 屏幕坐标，如：960,540"),
            "输入文本": ("【输入文本】\n模拟键盘自动输入文本内容（支持中文）。\n参数格式：任意想要输入的文字内容", "输入想要发送的文本内容，如：Hello"),
            "等待(秒)": ("【等待(秒)】\n强行让脚本暂停执行一段时间，受倍速设置影响。\n参数格式：纯数字，如：1.5 或 3", "输入等待的秒数，如：1.5"),
            "滚轮滑动": ("【滚轮滑动】\n模拟鼠标滚轮上下滚动。\n参数格式：纯数字（正数向上滚，负数向下滚），如：500 或 -500", "输入滚动距离，如：500 或 -500"),
            "系统按键": ("【系统按键】\n模拟敲击键盘单键或组合快捷键。\n参数格式：单键(如 A, enter, esc) 或 组合键(如 ctrl+c, alt+tab)", "输入按键或组合，如：A、enter 或 ctrl+v"),
            "鼠标悬停": ("【鼠标悬停】\n将鼠标移动到指定图片或坐标上方，不进行点击。\n参数格式：图片完整路径 或 屏幕坐标，如：100,100", "输入图片路径 或 屏幕坐标，如：960,540"),
            "截图保存": ("【截图保存】\n将当前整个屏幕或设定的识别区域截图并保存。\n参数格式：保存的文件夹目录 或 具体的.png文件路径", "输入保存目录，如：D:\\Screenshots"),
            "左键拖拽": ("【左键拖拽】\n按住鼠标左键，从起点拖动到终点。\n参数格式：起点 -> 终点。例如：100,100 -> 500,500", "输入轨迹坐标，如：100,100 -> 500,500"),
            "右键拖拽": ("【右键拖拽】\n按住鼠标右键，从起点拖动到终点。\n参数格式：起点 -> 终点。例如：100,100 -> 500,500", "输入轨迹坐标，如：100,100 -> 500,500"),
            "弹窗提醒": ("【弹窗提醒】\n暂停脚本并弹出一个系统强制定顶提示框，点击确定后继续。\n参数格式：你想提示的文字内容", "输入你想提示的文字，如：任务已完成"),
            "停止运行": ("【停止运行】\n执行到此步时，直接强行停止整个脚本的运行。\n参数格式：停止时的日志备注（可选）", "输入停止备注，如：条件满足，中止运行"),
            "声音提示": ("【声音提示】\n播放系统提示音，并在日志中醒目显示备注，不打断操作。\n参数格式：任意内容（作为日志醒目备注）", "输入大号日志备注，如：发现目标！"),
            "直到条件成立": ("【直到条件成立】\n判断图片出现/消失、区域变化或区域是否变成指定图片。\n条件未满足时跳回指定步骤，满足后继续下一步或跳到指定步骤。", "点小齿轮设置条件；这里会显示条件摘要"),
            "设置变量": ("【设置变量】\n为本次运行保存一个变量，重新启动脚本后自动清空。\n格式：变量名 = 表达式，例如 count = count + 1。首次赋值可写 count = 1。", "例如：count = 1 或 count = count + 1"),
            "判断表达式": ("【判断表达式】\n判断变量和运行状态；结果为真时走成功分支，为假时走失败分支。\n例如：count >= 10 and loop < 3。禁止函数、属性和下标。", "例如：count >= 10 and last_success"),
            "启动程序": ("【启动程序】\n启动一个程序或执行一条不经过命令解释器的启动命令。\n可点击右侧“程”选择可执行文件。", "输入程序路径或启动命令"),
            "等待窗口": ("【等待窗口】\n等待标题包含指定文字的窗口出现；以等号开头可要求完整标题相同。\n超时时间优先使用全局超时，未设置时为 10 秒。", "输入窗口标题，或点击“窗”选取"),
            "激活窗口": ("【激活窗口】\n查找并前置标题匹配的窗口。以等号开头表示完整匹配。", "输入窗口标题，或点击“窗”选取"),
            "关闭窗口": ("【关闭窗口】\n向标题匹配的窗口发送正常关闭请求，不会强制结束进程。", "输入窗口标题，或点击“窗”选取"),
            "输入秘密文本": ("【输入秘密文本】\n输入凭据库中指定名称对应的秘密内容；方案只保存名称，不保存秘密本身。", "输入凭据名称"),
            "点击窗口控件": ("【点击窗口控件】\n通过 Windows UI Automation 激活所选按钮或控件，通常不会移动鼠标。", "点击右侧“控”选取目标控件"),
            "设置控件文本": ("【设置控件文本】\n通过 Windows UI Automation 把文本写入所选输入控件。", "输入要写入控件的文本"),
            "读取控件文本": ("【读取控件文本】\n读取所选控件的文本并保存为本次运行变量。", "输入变量名，例如 result_text"),
        }

        self.value_input.setReadOnly(text == "直到条件成立")
        if text == "直到条件成立":
            self.value_input.setText(until_condition_summary(self.custom_data))

        if text in tips:
            self.type_combo.setToolTip(tips[text][0])
            self.value_input.setToolTip(tips[text][0])
            self.value_input.setPlaceholderText(tips[text][1])

        if text == "启动程序":
            self.file_btn.setVisible(True)
            self.file_btn.setText("程")
            self.file_btn.setToolTip("选择要启动的程序")
        elif "截图" in text:
            self.file_btn.setVisible(True)
            self.file_btn.setText("夹")
            self.file_btn.setToolTip("选择保存截图的文件夹目录")
        elif "单击" in text or "双击" in text or "悬停" in text:
            self.file_btn.setVisible(True)
            self.file_btn.setText("图")
            self.file_btn.setToolTip("选择本地图片\n性能建议：尽量截取小而独特的目标图片，少包含背景，可降低CPU匹配压力并减少误识别。\n安全提示：不要只截纯色或几乎没有纹理的区域，这类图片会被程序拒绝。")
        else:
            self.file_btn.setVisible(False)

        self.sync_data()
            
    def set_data(self, data):
        self.value_input.setText(str(data.get("value", "")))
        
        self.custom_data = {
            "step_id": data.get("step_id", ""),
            "custom_en": data.get("custom_en", False),
            "custom_conf": data.get("custom_conf", "0.8"),
            "custom_scale_min": data.get("custom_scale_min", "1.0"),
            "custom_scale_max": data.get("custom_scale_max", "1.0"),
            "custom_scale_step": data.get("custom_scale_step", "0.05"),
            "custom_gray": data.get("custom_gray", True),
            "repeat_mode": data.get("repeat_mode", "执行一次"),
            "repeat_count": data.get("repeat_count", "1"),
            "step_loop_start": data.get("step_loop_start", "1"),
            "step_loop_end": data.get("step_loop_end", "0"),
            "fail_limit": data.get("fail_limit", "1"),
            "success_skip": data.get("success_skip", "0"),
            "success_jump": data.get("success_jump", "0"),
            "success_target_id": data.get("success_target_id", ""),
            "fail_skip": data.get("fail_skip", "0"),
            "fail_jump": data.get("fail_jump", "0"),
            "fail_target_id": data.get("fail_target_id", ""),
            "no_skip_wait": data.get("no_skip_wait", False),
            "point_limit_en": data.get("point_limit_en", False),
            "point_limit_count": data.get("point_limit_count", "0"),
            "image_click_point_en": data.get("image_click_point_en", False),
            "image_click_point_rx": data.get("image_click_point_rx", "0.5"),
            "image_click_point_ry": data.get("image_click_point_ry", "0.5"),
            "step_region_en": data.get("step_region_en", False),
            "step_region": data.get("step_region", ""),
            "coord_step_en": data.get("coord_step_en", False),
            "coord_step_every": data.get("coord_step_every", "1"),
            "coord_step_direction": data.get("coord_step_direction", "向下"),
            "coord_step_distance": data.get("coord_step_distance", "0"),
            "coord_step_dx": data.get("coord_step_dx", "0"),
            "coord_step_dy": data.get("coord_step_dy", "0"),
            "coord_step_point": data.get("coord_step_point", ""),
            "coord_step_max_steps": data.get("coord_step_max_steps", "0"),
            "coord_step_max_distance": data.get("coord_step_max_distance", "0"),
            "coord_step_stop": data.get("coord_step_stop", False),
            "coord_step_reset_after": data.get("coord_step_reset_after", "0"),
            "coord_step_manual_points": data.get("coord_step_manual_points", "{}"),
            "coord_sequence_en": data.get("coord_sequence_en", False),
            "coord_sequence_points": data.get("coord_sequence_points", ""),
            "coord_sequence_end_action": data.get("coord_sequence_end_action", "点完后跳过本步"),
            "run_max_executions": data.get("run_max_executions", "0"),
            "debug_breakpoint": data.get("debug_breakpoint", False),
            "debug_condition": data.get("debug_condition", ""),
            "recorded_duration": data.get("recorded_duration", "0"),
            "uia_binding": data.get("uia_binding", {}),
        }
        condition_defaults = until_condition_defaults()
        condition_defaults.update({k: data.get(k, v) for k, v in condition_defaults.items()})
        self.custom_data.update(condition_defaults)
        self.custom_data["until_false_target_id"] = data.get(
            "until_false_target_id", ""
        )
        self.custom_data["until_true_target_id"] = data.get(
            "until_true_target_id", ""
        )
        for key, value in data.items():
            if key not in ("type", "value") and key not in self.custom_data:
                self.custom_data[key] = copy.deepcopy(value)
        self.update_markers()
        
        t = data.get("type", 1.0)
        if t in COMMAND_BY_CODE:
            command_name = COMMAND_BY_CODE[t].name
            if self.type_combo.findText(command_name) < 0:
                self.type_combo.blockSignals(True)
                self.type_combo.clear()
                self.type_combo.addItems(
                    command_names(
                        include_advanced=self.settings_mode == "advanced",
                        preserve_names=(command_name,),
                    )
                )
                self.type_combo.blockSignals(False)
            self.type_combo.setCurrentText(command_name)

    def select_file(self):
        cmd_type = self.get_data()["type"]
        if cmd_type == TASK_TYPE_LAUNCH_APP:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择要启动的程序",
                os.getcwd(),
                "程序 (*.exe *.com *.bat *.cmd);;所有文件 (*)",
            )
            if path:
                self.push_undo_before_external_edit()
                self.value_input.setText(path)
        elif cmd_type == 9.0:
            folder = QFileDialog.getExistingDirectory(self, "选择保存文件夹", os.getcwd())
            if folder:
                self.push_undo_before_external_edit()
                self.value_input.setText(folder)
        else: 
            path, _ = QFileDialog.getOpenFileName(self, "选择", filter="Images (*.png *.jpg *.bmp)")
            if path:
                self.push_undo_before_external_edit()
                self.value_input.setText(path)

    def get_data(self):
        val = self.value_input.text()
        t = command_code(self.type_combo.currentText())
        if t in [5.0, 6.0] and not val: val = "0"
        if t == TASK_TYPE_UNTIL:
            val = until_condition_summary(self.custom_data)
        
        data_dict = {"type": t, "value": val}
        data_dict.update(self.custom_data)
        if self.is_direct_coordinate_value(self.type_combo.currentText()):
            data_dict["custom_en"] = False
            data_dict["point_limit_en"] = False
            data_dict["image_click_point_en"] = False
            data_dict["step_region_en"] = False
        else:
            data_dict["coord_step_en"] = False
            data_dict["coord_step_manual_points"] = "{}"
            data_dict["coord_sequence_en"] = False
            if not self.image_settings_available():
                data_dict["step_region_en"] = False
            if not self.image_click_point_available():
                data_dict["image_click_point_en"] = False
        if data_dict.get("coord_sequence_en"):
            data_dict["coord_step_en"] = False
            data_dict["coord_step_manual_points"] = "{}"
        return data_dict

    def set_index(self, index):
        self.index_label.setText(f"{index}.")
        self.refresh_config_dialog_context()

class DraggableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDropIndicatorShown(False)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.drop_line_row = None
        self.drop_line_after = False
        self.drop_hint = QLabel(self.viewport())
        self.drop_hint.setObjectName("dropInsertHint")
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.drop_hint.setStyleSheet(
            "QLabel#dropInsertHint { background: rgba(23, 32, 51, 238); "
            "color: white; border: 1px solid #2563EB; border-radius: 4px; "
            "padding: 4px 9px; font-weight: 600; }"
        )
        self.drop_hint.hide()

    def _event_pos(self, event):
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _update_drop_line(self, event):
        pos = self._event_pos(event)
        item = self.itemAt(pos)
        if item is None:
            self.drop_line_row = self.count() - 1 if self.count() else 0
            self.drop_line_after = True
            self._update_drop_hint()
            self.viewport().update()
            return

        row = self.row(item)
        rect = self.visualItemRect(item)
        self.drop_line_row = row
        self.drop_line_after = pos.y() > rect.center().y()
        self._update_drop_hint()
        self.viewport().update()

    def _insertion_index(self):
        if self.drop_line_row is None:
            return 0
        insertion = self.drop_line_row + (1 if self.drop_line_after else 0)
        source = self.currentRow()
        if 0 <= source < insertion:
            insertion -= 1
        return max(0, min(insertion, max(0, self.count() - 1)))

    def _update_drop_hint(self):
        if self.drop_line_row is None or not self.count():
            self.drop_hint.hide()
            return
        row = max(0, min(self.drop_line_row, self.count() - 1))
        rect = self.visualItemRect(self.item(row))
        y = rect.bottom() + 1 if self.drop_line_after else rect.top()
        self.drop_hint.setText(f"松手后插入为第 {self._insertion_index() + 1} 步")
        self.drop_hint.adjustSize()
        x = max(8, self.viewport().width() - self.drop_hint.width() - 12)
        hint_y = max(4, min(y - self.drop_hint.height() - 5, self.viewport().height() - self.drop_hint.height() - 4))
        self.drop_hint.move(x, hint_y)
        self.drop_hint.show()
        self.drop_hint.raise_()

    def dragEnterEvent(self, event):
        if event.source() is self:
            event.acceptProposedAction()
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        self._update_drop_line(event)
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.drop_line_row = None
        self.drop_hint.hide()
        self.viewport().update()
        super().dragLeaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            font = QFont(self.font())
            font.setPointSizeF(max(10.0, font.pointSizeF() + 1.0))
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(152, 162, 179))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, "暂无步骤")
            return
        if self.drop_line_row is None or self.count() == 0:
            return

        row = max(0, min(self.drop_line_row, self.count() - 1))
        rect = self.visualItemRect(self.item(row))
        y = rect.bottom() + 1 if self.drop_line_after else rect.top()

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QPen(QColor(255, 255, 255), 8, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(6, y, self.viewport().width() - 6, y)
        painter.setPen(QPen(QColor(37, 99, 235), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(6, y, self.viewport().width() - 6, y)
        painter.setBrush(QColor(37, 99, 235))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(
            QPolygon([QPoint(6, y), QPoint(14, y - 6), QPoint(14, y + 6)])
        )
        painter.drawPolygon(
            QPolygon(
                [
                    QPoint(self.viewport().width() - 6, y),
                    QPoint(self.viewport().width() - 14, y - 6),
                    QPoint(self.viewport().width() - 14, y + 6),
                ]
            )
        )

    def _drag_preview_pixmap(self, item):
        widget = self.itemWidget(item)
        if widget:
            pixmap = widget.grab()
            if not pixmap.isNull():
                return pixmap

        summary = item.data(Qt.UserRole + 1) or item.text() or "正在移动步骤"
        preview_width = max(260, min(self.viewport().width() - 12, 900))
        preview_height = max(44, min(item.sizeHint().height(), 72))

        pixmap = QPixmap(preview_width, preview_height)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(255, 255, 255, 248))
        painter.setPen(QPen(QColor(37, 99, 235), 2))
        painter.drawRoundedRect(QRect(1, 1, preview_width - 2, preview_height - 2), 6, 6)

        text_rect = QRect(14, 0, preview_width - 28, preview_height)
        text = painter.fontMetrics().elidedText(summary, Qt.ElideRight, text_rect.width())
        painter.setPen(QColor(23, 32, 51))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.end()
        return pixmap

    def startDrag(self, supported_actions):
        selected_items = self.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(selected_items))

        pixmap = self._drag_preview_pixmap(item)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            rect = self.visualItemRect(item)
            cursor_pos = self.viewport().mapFromGlobal(QCursor.pos())
            if rect.isValid() and rect.contains(cursor_pos):
                hotspot = cursor_pos - rect.topLeft()
                hotspot.setX(max(1, min(hotspot.x(), pixmap.width() - 1)))
                hotspot.setY(max(1, min(hotspot.y(), pixmap.height() - 1)))
            else:
                hotspot = QPoint(min(36, pixmap.width() // 2), pixmap.height() // 2)
            drag.setHotSpot(hotspot)

        drag.exec(Qt.MoveAction)
        self.drop_line_row = None
        self.drop_hint.hide()
        self.viewport().update()

    def dropEvent(self, event):
        if hasattr(self.window(), 'push_undo_state'):
            self.window().push_undo_state()
        super().dropEvent(event)
        self.drop_line_row = None
        self.drop_hint.hide()
        for i in range(self.count()):
            item = self.item(i)
            if self.itemWidget(item) is None:
                data = item.data(Qt.UserRole)
                if data:
                    self.window().restore_row_widget(item, data)
        if hasattr(self.window(), 'update_indexes'):
            self.window().update_indexes()
