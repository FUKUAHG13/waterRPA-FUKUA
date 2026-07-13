"""Reusable settings widgets and the per-step settings dialog."""

import os
import re

from PySide6.QtCore import QEvent, QPoint, QRect, QSettings, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..constants import UNTIL_CONDITION_LOGICS, UNTIL_CONDITION_MODES, UNTIL_LIMIT_ACTIONS
from ..paths import get_base_dir
from ..task_model import (
    build_coord_step_positions,
    config_bool,
    format_region_text,
    parse_coord_step_manual_points,
    parse_coordinate_sequence,
    parse_coordinate_text,
    parse_float_text,
    serialize_coord_step_manual_points,
    serialize_coordinate_sequence,
    until_condition_defaults,
)
from .input_tools import CoordinatePickerUI, MultiPointPickerUI, RegionWindow
from .overlays import CoordinateStepPreviewOverlay


class FlowLayout(QLayout):
    """Lay out compact setting groups left-to-right and wrap as width changes."""

    def __init__(self, parent=None, margin=0, horizontal_spacing=10, vertical_spacing=7):
        super().__init__(parent)
        self._items = []
        self._horizontal_spacing = horizontal_spacing
        self._vertical_spacing = vertical_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def horizontalSpacing(self):
        return self._horizontal_spacing

    def verticalSpacing(self):
        return self._vertical_spacing

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        available_width = max(0, effective.width())
        lines = []
        line = []
        line_width = 0
        line_height = 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint().expandedTo(item.minimumSize())
            required_width = hint.width() + (self._horizontal_spacing if line else 0)
            if line and line_width + required_width > available_width:
                lines.append((line, line_height))
                line = []
                line_width = 0
                line_height = 0
                required_width = hint.width()
            line.append((item, hint))
            line_width += required_width
            line_height = max(line_height, hint.height())
        if line:
            lines.append((line, line_height))

        if not lines:
            return margins.top() + margins.bottom()

        y = effective.y()
        for line_index, (line_items, current_line_height) in enumerate(lines):
            x = effective.x()
            for item_index, (item, hint) in enumerate(line_items):
                if not test_only:
                    widget = item.widget()
                    if (
                        widget is not None
                        and widget.property("flowTrailing")
                        and item_index == len(line_items) - 1
                    ):
                        x = max(
                            x,
                            effective.x() + available_width - hint.width(),
                        )
                    centered_y = y + max(0, (current_line_height - hint.height()) // 2)
                    item.setGeometry(QRect(QPoint(x, centered_y), hint))
                x += hint.width() + self._horizontal_spacing
            y += current_line_height
            if line_index < len(lines) - 1:
                y += self._vertical_spacing
        return y - rect.y() + margins.bottom()


class ResponsiveRow(QWidget):
    """A row of indivisible control groups that reflows at group boundaries."""

    def __init__(
        self,
        parent=None,
        horizontal_spacing=10,
        vertical_spacing=7,
        group_spacing=None,
    ):
        super().__init__(parent)
        self.setObjectName("responsiveRow")
        self._group_spacing = (
            int(horizontal_spacing) if group_spacing is None else int(group_spacing)
        )
        self._height_sync_pending = False
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.flow_layout = FlowLayout(
            self,
            horizontal_spacing=horizontal_spacing,
            vertical_spacing=vertical_spacing,
        )

    def add_group(self, *parts):
        group = QWidget(self)
        group.setProperty("responsiveGroup", True)
        group.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self._group_spacing)
        layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for part in parts:
            if part is None:
                continue
            if isinstance(part, str):
                label = QLabel(part)
                label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                layout.addWidget(label)
            else:
                layout.addWidget(part, 0, Qt.AlignVCenter)
        self.flow_layout.addWidget(group)
        self._schedule_height_sync()
        return group

    def add_trailing_group(self, *parts):
        """Add a final group that uses spare row width to stay right-aligned."""

        group = self.add_group(*parts)
        group.setProperty("flowTrailing", True)
        return group

    def add_widget(self, widget):
        self.flow_layout.addWidget(widget)
        self._schedule_height_sync()
        return widget

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.flow_layout.heightForWidth(max(1, int(width)))

    def sizeHint(self):
        width = max(1, self.contentsRect().width())
        minimum = self.flow_layout.minimumSize()
        return QSize(minimum.width(), self.heightForWidth(width))

    def minimumSizeHint(self):
        return self.flow_layout.minimumSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self.flow_layout.invalidate()
            self._schedule_height_sync()

    def event(self, event):
        result = super().event(event)
        if event.type() in (
            QEvent.LayoutRequest,
            QEvent.FontChange,
            QEvent.StyleChange,
        ):
            self._schedule_height_sync()
        return result

    def _schedule_height_sync(self):
        if self._height_sync_pending:
            return
        self._height_sync_pending = True
        QTimer.singleShot(0, self._sync_height)

    def _sync_height(self):
        self._height_sync_pending = False
        width = max(1, self.contentsRect().width())
        target = max(0, self.flow_layout.heightForWidth(width))
        if self.minimumHeight() == target and self.maximumHeight() == target:
            return
        self.setMinimumHeight(target)
        self.setMaximumHeight(target)
        self.updateGeometry()


class NoWheelComboBox(QComboBox):
    """Change options by direct selection, never by scrolling a closed box."""

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
            return
        event.ignore()


class NoWheelSpinBox(QSpinBox):
    """Allow wheel changes only after the user explicitly focuses the editor."""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class PersistentActionMenu(QMenu):
    """Keep option menus open while actions are toggled or presets are applied."""

    def _trigger_action_without_closing(self, action):
        if action is None or not action.isEnabled() or action.isSeparator():
            return False
        action.trigger()
        self.setActiveAction(action)
        return True

    def mouseReleaseEvent(self, event):
        position = (
            event.position().toPoint()
            if hasattr(event, "position")
            else event.pos()
        )
        if self._trigger_action_without_closing(self.actionAt(position)):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if self._trigger_action_without_closing(self.activeAction()):
                event.accept()
                return
        super().keyPressEvent(event)


def fit_combo_to_contents(combo, minimum_width=0):
    """Keep every combo item readable without pinning the control to one width."""

    combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    combo.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    combo.setMaximumWidth(16777215)
    if minimum_width:
        combo.setMinimumWidth(minimum_width)
    return combo


def fit_text_button(button, minimum_width=64):
    """Let translated button text grow with the active font/UI scale."""

    button.setProperty("fitText", True)
    button.setMaximumWidth(16777215)
    button.setMinimumWidth(minimum_width)
    button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    return button


def fit_compact_text_button(button, minimum_width=30):
    """Keep one-character utility buttons compact without clipping their text."""

    button.setProperty("compactText", True)
    button.setMinimumWidth(minimum_width)
    button.setMaximumWidth(16777215)
    button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    return button

class CollapsibleSection(QWidget):
    def __init__(self, title, parent=None, expanded=True):
        super().__init__(parent)
        self.title = title
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 8)
        self.main_layout.setSpacing(0)
        
        self.toggle_btn = QPushButton(f"▼ {self.title}")
        self.toggle_btn.setObjectName("sectionToggle")
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(bool(expanded))
        self.toggle_btn.clicked.connect(self.on_toggle)
        
        self.content_widget = QFrame()
        self.content_widget.setObjectName("sectionContent")
        self.main_layout.addWidget(self.toggle_btn)
        self.main_layout.addWidget(self.content_widget)
        self.content_widget.setVisible(bool(expanded))
        self.on_toggle(bool(expanded))
        
    def set_content_layout(self, layout):
        layout.setContentsMargins(14, 12, 14, 12)
        self.content_widget.setLayout(layout)
        
    def on_toggle(self, checked):
        self.content_widget.setVisible(checked)
        self.toggle_btn.setText(f"▼ {self.title}" if checked else f"▶ {self.title}")
        self.updateGeometry()
        if self.parentWidget() is not None:
            self.parentWidget().updateGeometry()

class HelpBtn(QPushButton):
    def __init__(self, tip_text):
        super().__init__("?")
        self.setObjectName("helpButton")
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("帮助")
        self.tip_text = tip_text
        self.setToolTip(tip_text)
        self.setToolTipDuration(8000)
        self.clicked.connect(self.show_tip)

    def show_tip(self):
        QToolTip.showText(QCursor.pos(), self.tip_text, self, QRect(), 8000)

class ImageClickPointWidget(QWidget):
    point_changed = Signal(float, float)

    def __init__(self, pixmap, rx=0.5, ry=0.5, scale=2.0, selectable=True):
        super().__init__()
        self.pixmap = pixmap
        self.rx = max(0.0, min(1.0, float(rx)))
        self.ry = max(0.0, min(1.0, float(ry)))
        self.selectable = selectable
        self.display_scale = max(0.2, float(scale))
        self.setFixedSize(
            max(1, int(self.pixmap.width() * self.display_scale)),
            max(1, int(self.pixmap.height() * self.display_scale))
        )
        self.setCursor(Qt.CrossCursor if selectable else Qt.ArrowCursor)

    def set_point(self, rx, ry):
        self.rx = max(0.0, min(1.0, float(rx)))
        self.ry = max(0.0, min(1.0, float(ry)))
        self.point_changed.emit(self.rx, self.ry)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self.rect(), self.pixmap)

        px = int(self.rx * self.width())
        py = int(self.ry * self.height())
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(0, 0, 0, 210), 5, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(px - 18, py, px + 18, py)
        painter.drawLine(px, py - 18, px, py + 18)
        painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(px - 18, py, px + 18, py)
        painter.drawLine(px, py - 18, px, py + 18)
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawEllipse(QPoint(px, py), 5, 5)

    def mousePressEvent(self, event):
        if self.selectable and event.button() == Qt.LeftButton:
            pos = event.position() if hasattr(event, "position") else event.pos()
            self.set_point(pos.x() / max(1, self.width()), pos.y() / max(1, self.height()))
            event.accept()
            return
        super().mousePressEvent(event)

class ImageClickPointDialog(QDialog):
    def __init__(self, image_path, rx=0.5, ry=0.5, selectable=True, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.selectable = selectable
        self.pixmap = QPixmap(image_path)
        if self.pixmap.isNull():
            raise ValueError("图片无法打开或格式不受支持")

        self.setWindowTitle("选择图片内点击位置" if selectable else "预览图片内点击位置")
        self.setMinimumSize(520, 420)
        layout = QVBoxLayout(self)

        hint = "左键点击放大图片中的目标位置；保存的是相对位置，缩放识别后仍会点同一处。"
        if not selectable:
            hint = "红色十字即当前将点击的图片内相对位置。"
        hint_label = QLabel(hint)
        hint_label.setProperty("role", "muted")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        screen_rect = QApplication.primaryScreen().availableGeometry()
        max_w = max(360, int(screen_rect.width() * 0.78))
        max_h = max(280, int(screen_rect.height() * 0.68))
        fit_scale = min(max_w / max(1, self.pixmap.width()), max_h / max(1, self.pixmap.height()))
        longest = max(self.pixmap.width(), self.pixmap.height())
        if longest <= 120:
            preferred_scale = 6.0
        elif longest <= 300:
            preferred_scale = 4.0
        elif longest <= 700:
            preferred_scale = 2.0
        else:
            preferred_scale = 1.0
        display_scale = max(0.2, min(preferred_scale, fit_scale))

        self.image_widget = ImageClickPointWidget(self.pixmap, rx, ry, display_scale, selectable)
        self.image_widget.point_changed.connect(self.update_info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setWidget(self.image_widget)
        layout.addWidget(scroll, 1)

        self.info_label = QLabel()
        self.info_label.setProperty("role", "sectionTitle")
        layout.addWidget(self.info_label)
        self.update_info(self.image_widget.rx, self.image_widget.ry)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel) if selectable else QDialogButtonBox(QDialogButtonBox.Close)
        if selectable:
            buttons.button(QDialogButtonBox.Ok).setText("使用此位置")
            buttons.button(QDialogButtonBox.Cancel).setText("取消")
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
        else:
            buttons.rejected.connect(self.reject)
            buttons.button(QDialogButtonBox.Close).setText("关闭")
            buttons.button(QDialogButtonBox.Close).clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(
            min(max_w + 40, self.image_widget.width() + 60),
            min(max_h + 120, self.image_widget.height() + 150)
        )

    def update_info(self, rx, ry):
        img_x = int(round(rx * self.pixmap.width()))
        img_y = int(round(ry * self.pixmap.height()))
        self.info_label.setText(
            f"当前相对位置：X {rx:.3f} / Y {ry:.3f}；原图像素约 ({img_x}, {img_y})"
        )

    def selected_ratio(self):
        return self.image_widget.rx, self.image_widget.ry

class TaskConfigDialog(QDialog):
    COORD_STEP_DIRECTIONS = (
        "向上",
        "向下",
        "向左",
        "向右",
        "自定义偏移",
        "移动到新点位",
    )
    SIMPLE_COORD_STEP_DIRECTIONS = ("移动到新点位",)

    def __init__(
        self,
        parent,
        data,
        image_settings_available=True,
        point_limit_available=False,
        coordinate_step_available=False,
        base_coordinate=None,
        image_path="",
        image_click_point_available=False,
        base_coordinate_changed=None,
        step_index=None,
        step_type="",
        base_dir=None,
        settings_mode=None,
    ):
        super().__init__(None)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowModality(Qt.NonModal)
        self.step_index = step_index
        self.step_type = step_type
        self.image_settings_available = image_settings_available
        self.point_limit_available = point_limit_available
        self.coordinate_step_available = coordinate_step_available
        self.base_coordinate = base_coordinate
        self.image_path = image_path
        self.image_click_point_available = image_click_point_available
        self.base_coordinate_changed = base_coordinate_changed
        self.coord_step_picker = None
        self.coord_sequence_picker = None
        self.coord_step_preview = None
        self.step_region_window = None
        self.until_region_windows = {}
        self.coord_step_manual_points = parse_coord_step_manual_points(data.get("coord_step_manual_points", "{}"))
        self.coord_step_max_steps_initial = str(data.get("coord_step_max_steps", "0"))
        self.coord_step_clearing_due_to_count = False
        settings_dir = os.path.abspath(base_dir or get_base_dir())
        self.dialog_settings = QSettings(os.path.join(settings_dir, "config.ini"), QSettings.IniFormat)
        saved_settings_mode = (
            settings_mode
            if settings_mode is not None
            else self.dialog_settings.value("settings_view_mode", "simple")
        )
        self.settings_mode = (
            "advanced" if str(saved_settings_mode) == "advanced" else "simple"
        )
        self._coord_direction_locked_for_simple = False
        self.update_window_title()
        self.setMinimumSize(900, 520)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(14, 14, 14, 14)
        outer_layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("dialogBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)
        scroll.setWidget(body)
        outer_layout.addWidget(scroll, 1)

        def inline_row(*groups):
            row = ResponsiveRow(horizontal_spacing=10, vertical_spacing=7)
            for group in groups:
                if isinstance(group, (tuple, list)):
                    row.add_group(*group)
                else:
                    row.add_group(group)
            return row
        
        note = QLabel("图片识别设置仅对图片点击/图片悬停生效；直接输入坐标时会自动忽略这些参数。")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.context_note = QLabel("")
        self.context_note.setProperty("role", "muted")
        self.context_note.setWordWrap(True)
        layout.addWidget(self.context_note)

        self.enable_chk = QCheckBox("✓ 为当前图片指令启用独立识别参数")
        self.enable_chk.setChecked(config_bool(data.get("custom_en", False)))
        self.enable_chk.setProperty("emphasis", True)
        layout.addWidget(self.enable_chk)
        
        self.form_widget = QWidget()
        form = QFormLayout(self.form_widget)
        form.setContentsMargins(0, 8, 0, 8)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        self.conf_edit = QLineEdit(str(data.get("custom_conf", "0.8")))
        self.s_min_edit = QLineEdit(str(data.get("custom_scale_min", "1.0")))
        self.s_max_edit = QLineEdit(str(data.get("custom_scale_max", "1.0")))
        self.s_step_edit = QLineEdit(str(data.get("custom_scale_step", "0.05")))
        for edit in [self.conf_edit, self.s_min_edit, self.s_max_edit, self.s_step_edit]:
            edit.setFixedWidth(72)
        self.gray_chk = QCheckBox("灰度匹配 (取消则严格区分颜色)")
        self.gray_chk.setChecked(config_bool(data.get("custom_gray", True)))
        
        form.addRow("识别参数:", inline_row(
            ("相似度", self.conf_edit),
            ("最小", self.s_min_edit),
            ("最大", self.s_max_edit),
            ("步长", self.s_step_edit),
            (self.gray_chk,),
            (HelpBtn("【独立识别参数】\n只对当前步骤的图片识别生效。直接坐标点击会忽略相似度、缩放和灰度设置。"),),
        ))
        
        layout.addWidget(self.form_widget)
        self.enable_chk.setEnabled(self.image_settings_available)
        self.form_widget.setEnabled(self.image_settings_available and self.enable_chk.isChecked())
        self.enable_chk.toggled.connect(self.update_image_settings_enabled)

        until_defaults = until_condition_defaults()
        until_defaults.update(data or {})
        self.until_group = QGroupBox("直到条件成立")
        until_layout = QVBoxLayout(self.until_group)

        until_top_row = ResponsiveRow()
        self.until_logic_combo = NoWheelComboBox()
        self.until_logic_combo.addItems(UNTIL_CONDITION_LOGICS)
        self.until_logic_combo.setCurrentText(str(until_defaults.get("until_logic", "全部满足")))
        fit_combo_to_contents(self.until_logic_combo)
        until_top_row.add_group("条件关系:", self.until_logic_combo)
        self.until_false_jump_edit = QLineEdit(str(until_defaults.get("until_false_jump", "1")))
        self.until_false_jump_edit.setFixedWidth(60)
        until_top_row.add_group("未满足跳回第", self.until_false_jump_edit, "步")
        self.until_true_jump_edit = QLineEdit(str(until_defaults.get("until_true_jump", "0")))
        self.until_true_jump_edit.setFixedWidth(60)
        self.until_true_jump_edit.setToolTip("填 0 表示满足条件后继续下一步；填具体步号表示直接跳到该步。")
        until_top_row.add_group(
            "满足后跳至", self.until_true_jump_edit, "步",
            HelpBtn("【条件跳转】\n条件未满足时跳回指定步骤继续循环；满足后填 0 表示执行下一步，填具体步号则直接跳转。")
        )
        until_layout.addWidget(until_top_row)

        until_limit_row = ResponsiveRow()
        self.until_max_checks_edit = QLineEdit(str(until_defaults.get("until_max_checks", "0")))
        self.until_max_checks_edit.setFixedWidth(60)
        self.until_max_checks_edit.setToolTip("填 0 表示不限次数。每次执行到本步骤且条件仍未满足时计数一次。")
        until_limit_row.add_group("最多检查", self.until_max_checks_edit, "次")
        self.until_max_seconds_edit = QLineEdit(str(until_defaults.get("until_max_seconds", "0")))
        self.until_max_seconds_edit.setFixedWidth(60)
        self.until_max_seconds_edit.setToolTip("填 0 表示不限时间。从本步骤本轮第一次检查开始计时。")
        until_limit_row.add_group("最多等待", self.until_max_seconds_edit, "秒")
        self.until_on_limit_combo = NoWheelComboBox()
        self.until_on_limit_combo.addItems(UNTIL_LIMIT_ACTIONS)
        self.until_on_limit_combo.setCurrentText(str(until_defaults.get("until_on_limit", "继续下一步")))
        fit_combo_to_contents(self.until_on_limit_combo)
        until_limit_row.add_group(
            "达到上限后:", self.until_on_limit_combo,
            HelpBtn("【检查上限】\n次数和时间填 0 表示不限。达到任一已设置的上限后，按右侧选项继续、停止或跳转。")
        )
        until_layout.addWidget(until_limit_row)

        self.until_condition_widgets = {}
        for cond_idx in range(1, 4):
            row = ResponsiveRow(horizontal_spacing=8, vertical_spacing=7)

            en_chk = QCheckBox(f"条件{cond_idx}")
            en_chk.setChecked(config_bool(until_defaults.get(f"until_cond{cond_idx}_en", cond_idx == 1)))

            mode_combo = NoWheelComboBox()
            mode_combo.addItems(UNTIL_CONDITION_MODES)
            mode_combo.setCurrentText(str(until_defaults.get(f"until_cond{cond_idx}_mode", "图片出现")))
            fit_combo_to_contents(mode_combo)
            row.add_group(en_chk, mode_combo)

            image_edit = QLineEdit(str(until_defaults.get(f"until_cond{cond_idx}_image", "")))
            image_edit.setPlaceholderText("图片路径")
            image_edit.setMinimumWidth(170)

            image_btn = QPushButton("图")
            fit_compact_text_button(image_btn)
            image_btn.setToolTip("选择条件要识别或对比的图片。")
            image_btn.clicked.connect(lambda _=False, i=cond_idx: self.select_until_condition_image(i))
            row.add_group(image_edit, image_btn)

            region_edit = QLineEdit(str(until_defaults.get(f"until_cond{cond_idx}_region", "")))
            region_edit.setPlaceholderText("区域 x,y,w,h，可空")
            region_edit.setMinimumWidth(170)

            region_btn = QPushButton("区")
            fit_compact_text_button(region_btn)
            region_btn.setToolTip("框选本条件只检测的屏幕区域。")
            region_btn.clicked.connect(lambda _=False, i=cond_idx: self.start_until_region_pick(i))
            row.add_group(region_edit, region_btn)

            conf_edit = QLineEdit(str(until_defaults.get(f"until_cond{cond_idx}_conf", "0.8")))
            conf_edit.setFixedWidth(52)
            conf_edit.setToolTip("图片出现/消失使用的识别相似度，通常 0.7-0.95。")

            diff_edit = QLineEdit(str(until_defaults.get(f"until_cond{cond_idx}_diff", "8")))
            diff_edit.setFixedWidth(52)
            diff_edit.setToolTip("区域发生变化的阈值，单位约为百分比；数值越小越敏感。")

            similarity_edit = QLineEdit(str(until_defaults.get(f"until_cond{cond_idx}_similarity", "90")))
            similarity_edit.setFixedWidth(52)
            similarity_edit.setToolTip("区域变成指定图片时要求的相似度百分比，通常 85-98。")
            row.add_group(
                "图", conf_edit, "变", diff_edit, "似", similarity_edit,
                HelpBtn("【条件阈值】\n图：图片出现/消失的识别相似度。\n变：区域变化阈值，越小越敏感。\n似：区域变成指定图片时要求的相似度百分比。")
            )

            self.until_condition_widgets[cond_idx] = {
                "row": row,
                "enabled": en_chk,
                "mode": mode_combo,
                "image": image_edit,
                "image_btn": image_btn,
                "region": region_edit,
                "region_btn": region_btn,
                "conf": conf_edit,
                "diff": diff_edit,
                "similarity": similarity_edit,
            }
            en_chk.toggled.connect(self.update_until_condition_ui)
            mode_combo.currentTextChanged.connect(self.update_until_condition_ui)
            until_layout.addWidget(row)

        until_note = QLabel("用法：把需要反复执行的步骤放在前面，最后放本步骤。条件未满足时跳回指定步，条件满足时继续下一步或跳到指定步。区域发生变化会在第一次执行到本步骤时自动记录当前区域作为基准。")
        until_note.setWordWrap(True)
        until_note.setProperty("role", "muted")
        until_layout.addWidget(until_note)
        layout.addWidget(self.until_group)

        control_box = QGroupBox("执行控制 / 条件分支")
        control_form = QFormLayout(control_box)
        control_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        control_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        control_form.setHorizontalSpacing(10)
        control_form.setVerticalSpacing(7)
        control_form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        self.control_form = control_form

        self.repeat_combo = NoWheelComboBox()
        self.repeat_combo.addItems(["执行一次", "指定次数", "无限重复"])
        fit_combo_to_contents(self.repeat_combo)
        self.repeat_combo.setCurrentText(str(data.get("repeat_mode", "执行一次")))
        self.repeat_combo.currentTextChanged.connect(self.update_repeat_ui)

        self.repeat_count_edit = QLineEdit(str(data.get("repeat_count", "1")))
        self.repeat_count_edit.setFixedWidth(90)

        self.step_loop_start_edit = QLineEdit(str(data.get("step_loop_start", "1")))
        self.step_loop_start_edit.setFixedWidth(70)
        self.step_loop_start_edit.setToolTip("本步骤从第几次脚本循环开始执行；默认 1 表示从第一轮就生效。")
        self.step_loop_end_edit = QLineEdit(str(data.get("step_loop_end", "0")))
        self.step_loop_end_edit.setFixedWidth(70)
        self.step_loop_end_edit.setToolTip("本步骤执行到第几次脚本循环后不再执行；填 0 表示不限。填 5 表示第 1-5 轮执行，第 6 轮开始跳过。")

        step_loop_row = ResponsiveRow()
        step_loop_row.add_group("从第", self.step_loop_start_edit, "次循环开始")
        step_loop_row.add_group(
            "到第", self.step_loop_end_edit, "次循环后停止",
            HelpBtn("【本步骤循环范围】\n控制当前步骤在脚本第几轮循环中生效。\n起始循环默认 1；停止循环填 0 表示不限。\n被范围跳过时不会触发成功/失败跳转，只会继续执行下一步。")
        )

        self.point_limit_chk = QCheckBox("图片点击同一点位达到上限后忽略此点位")
        self.point_limit_chk.setChecked(config_bool(data.get("point_limit_en", False)) and self.point_limit_available)
        self.point_limit_chk.setEnabled(self.point_limit_available)
        self.point_limit_chk.setToolTip("仅对图片点击生效。填坐标时自动忽略；达到上限后会尝试点击下一个匹配点位。")
        self.point_limit_chk.toggled.connect(self.update_point_limit_ui)

        self.point_limit_count_edit = QLineEdit(str(data.get("point_limit_count", "0")))
        self.point_limit_count_edit.setFixedWidth(90)
        self.point_limit_count_edit.setToolTip("填 0 表示不限制；例如填 1 表示同一个识别点位只点击一次。")

        self.image_click_point_chk = QCheckBox("命中图片后点击图片内指定位置")
        self.image_click_point_chk.setMinimumWidth(245)
        self.image_click_point_chk.setChecked(config_bool(data.get("image_click_point_en", False)) and self.image_click_point_available)
        self.image_click_point_chk.setEnabled(self.image_click_point_available)
        self.image_click_point_chk.setToolTip("仅对图片路径的左键单击、左键双击、右键单击生效；直接坐标点击会自动忽略。")
        self.image_click_point_chk.toggled.connect(self.update_image_click_point_ui)
        self.image_click_point_rx = str(data.get("image_click_point_rx", "0.5"))
        self.image_click_point_ry = str(data.get("image_click_point_ry", "0.5"))

        image_point_row = ResponsiveRow()
        image_point_row.add_group(
            self.image_click_point_chk,
            HelpBtn("【图片内点击点】\n只对图片路径的左键、双击和右键点击生效。启用后可在放大的模板图片上选择实际点击的相对位置。")
        )
        self.image_click_point_select_btn = QPushButton("选择")
        fit_text_button(self.image_click_point_select_btn, 68)
        self.image_click_point_select_btn.setToolTip("打开放大的模板图片，左键点击要实际点击的位置。")
        self.image_click_point_select_btn.clicked.connect(self.select_image_click_point)
        self.image_click_point_preview_btn = QPushButton("预览")
        fit_text_button(self.image_click_point_preview_btn, 68)
        self.image_click_point_preview_btn.setToolTip("预览当前保存的图片内点击位置。")
        self.image_click_point_preview_btn.clicked.connect(self.preview_image_click_point)
        image_point_row.add_group(
            self.image_click_point_select_btn, self.image_click_point_preview_btn
        )
        self.image_click_point_info = QLabel("")
        self.image_click_point_info.setProperty("role", "muted")
        image_point_row.add_group(self.image_click_point_info)

        self.step_region_chk = QCheckBox("启用本步识别区域")
        self.step_region_chk.setChecked(config_bool(data.get("step_region_en", False)) and self.image_settings_available)
        self.step_region_chk.setEnabled(self.image_settings_available)
        self.step_region_chk.setToolTip("仅对当前步骤的图片点击/图片悬停生效；开启后本步骤只会在该区域内找图，优先级高于全局识别区域。直接坐标点击会自动忽略。")
        self.step_region_chk.toggled.connect(self.update_step_region_ui)
        self.step_region_edit = QLineEdit(str(data.get("step_region", "")))
        self.step_region_edit.setPlaceholderText("区域 x,y,w,h")
        self.step_region_edit.setToolTip("本步骤专用识别区域，格式 x,y,w,h。为空或关闭时使用全局识别区域。")
        self.step_region_pick_btn = QPushButton("框选")
        fit_text_button(self.step_region_pick_btn, 68)
        self.step_region_pick_btn.setToolTip("框选当前步骤专用识别区域。")
        self.step_region_pick_btn.clicked.connect(self.start_step_region_pick)
        self.step_region_clear_btn = QPushButton("清除")
        fit_text_button(self.step_region_clear_btn, 68)
        self.step_region_clear_btn.clicked.connect(self.clear_step_region)
        self.step_region_edit.textChanged.connect(self.update_step_region_ui)
        step_region_edit_group = QWidget()
        step_region_edit_layout = QHBoxLayout(step_region_edit_group)
        step_region_edit_layout.setContentsMargins(0, 0, 0, 0)
        step_region_edit_layout.setSpacing(10)
        self.step_region_edit.setMinimumWidth(220)
        step_region_edit_layout.addWidget(self.step_region_edit)
        step_region_edit_layout.addWidget(self.step_region_pick_btn)
        step_region_edit_layout.addWidget(self.step_region_clear_btn)
        step_region_row = ResponsiveRow()
        step_region_row.add_group(
            self.step_region_chk,
            HelpBtn("【本步识别区域】\n只限制当前这一步的图片识别范围，优先级高于全局识别区域。\n适合屏幕上有多个相似图片，但本步骤只允许点击其中一个区域的场景。\n直接输入坐标时自动忽略。")
        )
        step_region_row.add_widget(step_region_edit_group)

        self.coord_step_chk = QCheckBox("坐标点击启用步进偏移")
        self.coord_step_chk.setChecked(config_bool(data.get("coord_step_en", False)) and self.coordinate_step_available)
        self.coord_step_chk.setEnabled(self.coordinate_step_available)
        self.coord_step_chk.setToolTip("仅对直接输入坐标的点击步骤生效；图片识别点击会自动忽略。")
        self.coord_step_chk.toggled.connect(self.update_coord_step_ui)

        self.coord_step_every_edit = QLineEdit(str(data.get("coord_step_every", "1")))
        self.coord_step_every_edit.setFixedWidth(70)
        self.coord_step_every_edit.setToolTip("每执行本坐标点击步骤多少次后，移动到下一个点击位置。")

        self.coord_step_direction_combo = NoWheelComboBox()
        self.coord_step_direction_combo.addItems(self.COORD_STEP_DIRECTIONS)
        fit_combo_to_contents(self.coord_step_direction_combo)
        self.coord_step_direction_combo.setCurrentText(str(data.get("coord_step_direction", "向下")))
        self.coord_step_direction_combo.currentTextChanged.connect(self.update_coord_step_ui)

        self.coord_step_distance_edit = QLineEdit(str(data.get("coord_step_distance", "0")))
        self.coord_step_distance_edit.setFixedWidth(70)
        self.coord_step_dx_edit = QLineEdit(str(data.get("coord_step_dx", "0")))
        self.coord_step_dx_edit.setFixedWidth(70)
        self.coord_step_dy_edit = QLineEdit(str(data.get("coord_step_dy", "0")))
        self.coord_step_dy_edit.setFixedWidth(70)
        self.coord_step_point_edit = QLineEdit(str(data.get("coord_step_point", "")))
        self.coord_step_point_edit.setPlaceholderText("例如 960,540")

        self.coord_step_max_steps_edit = QLineEdit(str(data.get("coord_step_max_steps", "0")))
        self.coord_step_max_steps_edit.setFixedWidth(70)
        self.coord_step_max_steps_edit.setToolTip("普通方向：最多偏移多少次后不再移动，填 0 表示不限次数。移动到新点位：这里表示起点到目标点之间总共点击多少个点位，例如填 5 会点击起点、3 个中间点、目标点；填 0 表示直接从起点移动到目标点。")
        self.coord_step_max_steps_edit.textChanged.connect(self.on_coord_step_count_changed)
        self.coord_step_max_distance_edit = QLineEdit(str(data.get("coord_step_max_distance", "0")))
        self.coord_step_max_distance_edit.setFixedWidth(70)
        self.coord_step_max_distance_edit.setToolTip("累计偏移距离达到多少像素后不再移动；填 0 表示不限距离。")
        self.coord_step_stop_chk = QCheckBox("达到移动上限后停止脚本")
        self.coord_step_stop_chk.setChecked(config_bool(data.get("coord_step_stop", False)))
        self.coord_step_reset_after_edit = QLineEdit(str(data.get("coord_step_reset_after", "0")))
        self.coord_step_reset_after_edit.setFixedWidth(70)
        self.coord_step_reset_after_edit.setToolTip("本坐标步进成功点击多少次后自动回到起点并重新开始移动；填 0 表示不自动重置。重置触发时优先于“达到移动上限后停止脚本”。左键双击按一次本步骤点击动作计数。")

        coord_every_row = ResponsiveRow()
        coord_every_row.add_group(
            self.coord_step_chk,
            HelpBtn("【坐标步进】\n只对直接输入坐标的点击步骤生效。按设定频率依次移动点击位置，图片识别点击会自动忽略。")
        )
        coord_every_row.add_group("每", self.coord_step_every_edit, "次后移动")

        coord_direction_row = ResponsiveRow()
        coord_direction_row.add_group(self.coord_step_direction_combo)
        coord_direction_row.add_group("距离:", self.coord_step_distance_edit)
        coord_direction_row.add_group("dx:", self.coord_step_dx_edit, "dy:", self.coord_step_dy_edit)

        coord_point_row = ResponsiveRow()
        self.coord_step_point_edit.setMinimumWidth(220)
        self.coord_step_pick_btn = QPushButton("取")
        fit_compact_text_button(self.coord_step_pick_btn)
        self.coord_step_pick_btn.setToolTip("点击后直接进入取点状态，左键选取目标点位，右键取消。")
        self.coord_step_pick_btn.clicked.connect(self.start_coord_step_point_pick)
        self.coord_step_preview_btn = QPushButton("预览")
        fit_text_button(self.coord_step_preview_btn, 68)
        self.coord_step_preview_btn.setToolTip("在屏幕上临时显示本步骤会点击的点位；预览不会执行点击。")
        self.coord_step_preview_btn.clicked.connect(self.show_coord_step_preview)
        coord_point_row.add_group(
            self.coord_step_point_edit, self.coord_step_pick_btn, self.coord_step_preview_btn
        )

        coord_limit_row = ResponsiveRow()
        coord_limit_row.add_group("次数:", self.coord_step_max_steps_edit)
        coord_limit_row.add_group("距离:", self.coord_step_max_distance_edit)
        coord_limit_row.add_group(
            self.coord_step_stop_chk,
            HelpBtn("【移动上限】\n次数和距离填 0 表示不限。移动到新点位时，次数表示起点到终点之间的总点击点数。")
        )

        coord_reset_row = ResponsiveRow()
        coord_reset_row.add_group(
            self.coord_step_reset_after_edit, "次点击后回到起点",
            HelpBtn("【重置循环】\n填 0 表示不自动重置；填具体次数后，路径完成相应点击次数会重新从起点开始。")
        )

        coord_manual_row = ResponsiveRow()
        self.coord_step_manual_info = QLabel("")
        self.coord_step_manual_info.setProperty("role", "statusInfo")
        self.coord_step_clear_manual_btn = QPushButton("清除手动修正点")
        fit_text_button(self.coord_step_clear_manual_btn, 132)
        self.coord_step_clear_manual_btn.setToolTip("清除本步骤预览中拖动中间点产生的手动修正坐标。")
        self.coord_step_clear_manual_btn.clicked.connect(self.clear_coord_step_manual_points)
        coord_manual_row.add_group(
            self.coord_step_manual_info, self.coord_step_clear_manual_btn,
            HelpBtn("【手动修正点】\n预览中单独拖动中间点会保存手动修正。修改路径点数时会自动清除，避免旧坐标错位。")
        )

        self.coord_sequence_chk = QCheckBox("启用自定义点位")
        self.coord_sequence_chk.setChecked(config_bool(data.get("coord_sequence_en", False)) and self.coordinate_step_available)
        self.coord_sequence_chk.setEnabled(self.coordinate_step_available)
        self.coord_sequence_chk.setToolTip("仅对直接输入坐标的点击步骤生效。开启后会按列表中的点位依次点击，坐标步进会自动忽略。")
        self.coord_sequence_chk.toggled.connect(self.update_coord_sequence_ui)
        self.coord_sequence_text = QTextEdit(str(data.get("coord_sequence_points", "")))
        self.coord_sequence_text.setFixedHeight(58)
        self.coord_sequence_text.setPlaceholderText("例如：100,100; 200,180; 350,260")
        self.coord_sequence_text.setToolTip("多个点用分号或换行分隔。执行时每次运行到本步骤会取下一个点。")
        self.coord_sequence_end_combo = NoWheelComboBox()
        self.coord_sequence_end_combo.addItems(["点完后跳过本步", "点完后停在最后一个", "点完后循环"])
        fit_combo_to_contents(self.coord_sequence_end_combo)
        self.coord_sequence_end_combo.setCurrentText(str(data.get("coord_sequence_end_action", "点完后跳过本步")))
        self.coord_sequence_pick_btn = QPushButton("连续取点")
        fit_text_button(self.coord_sequence_pick_btn, 88)
        self.coord_sequence_pick_btn.setToolTip("打开全屏取点层，左键连续添加点位，右键或 Esc 完成。")
        self.coord_sequence_pick_btn.clicked.connect(self.start_coord_sequence_pick)
        self.coord_sequence_preview_btn = QPushButton("预览")
        fit_text_button(self.coord_sequence_preview_btn, 68)
        self.coord_sequence_preview_btn.clicked.connect(self.preview_coord_sequence)
        self.coord_sequence_clear_btn = QPushButton("清空")
        fit_text_button(self.coord_sequence_clear_btn, 68)
        self.coord_sequence_clear_btn.clicked.connect(lambda: self.coord_sequence_text.clear())

        coord_sequence_top = ResponsiveRow()
        coord_sequence_top.add_group(
            self.coord_sequence_chk,
            HelpBtn("【自定义点位】\n只对直接坐标点击生效。每次执行到本步骤时按列表顺序取下一个坐标，坐标步进会自动忽略。")
        )
        coord_sequence_controls = ResponsiveRow()
        coord_sequence_controls.add_group("结束后:", self.coord_sequence_end_combo)
        coord_sequence_controls.add_group(
            self.coord_sequence_pick_btn,
            self.coord_sequence_preview_btn,
            self.coord_sequence_clear_btn,
        )

        self.coord_sequence_details = QWidget()
        coord_sequence_details_layout = QVBoxLayout(self.coord_sequence_details)
        coord_sequence_details_layout.setContentsMargins(0, 0, 0, 0)
        coord_sequence_details_layout.setSpacing(4)
        coord_sequence_details_layout.addWidget(coord_sequence_controls)
        coord_sequence_details_layout.addWidget(self.coord_sequence_text)

        coord_sequence_box = QWidget()
        self.coord_sequence_box = coord_sequence_box
        coord_sequence_box_layout = QVBoxLayout(coord_sequence_box)
        coord_sequence_box_layout.setContentsMargins(0, 0, 0, 0)
        coord_sequence_box_layout.setSpacing(4)
        coord_sequence_box_layout.addWidget(coord_sequence_top)
        coord_sequence_box_layout.addWidget(self.coord_sequence_details)

        self.fail_limit_edit = QLineEdit(str(data.get("fail_limit", "1")))
        self.fail_limit_edit.setFixedWidth(90)
        self.fail_limit_edit.setToolTip("例如填 1 表示失败一次就执行下一步；填 3 表示连续失败三次后才放弃本步。优先级低于“禁止跳过”：开启禁止跳过时，会先一直等待本步骤成功或超时。")

        self.no_skip_wait_chk = QCheckBox("禁止跳过：失败后一直等待本步骤")
        self.no_skip_wait_chk.setChecked(config_bool(data.get("no_skip_wait", False)))
        self.no_skip_wait_chk.setToolTip("开启后，本步骤执行失败不会进入下一步，会按全局“识别频率”反复等待并重试，直到成功或达到单步超时。")

        self.run_max_executions_edit = QLineEdit(str(data.get("run_max_executions", "0")))
        self.run_max_executions_edit.setFixedWidth(90)
        self.run_max_executions_edit.setToolTip("本次启动脚本后，本步骤最多真正执行多少次；填 0 表示不限。达到上限后会跳过本步骤，不触发成功/失败分支；手动停止并重新启动后重新计数。")

        self.debug_breakpoint_chk = QCheckBox("运行到本步骤时暂停")
        self.debug_breakpoint_chk.setChecked(
            config_bool(data.get("debug_breakpoint", False))
        )
        self.debug_breakpoint_chk.setToolTip(
            "调试断点只在完整脚本运行时生效；暂停发生在本步骤执行前。"
            "可选择继续运行到下一个断点，或只执行当前步骤后再次暂停。"
        )
        self.debug_breakpoint_chk.toggled.connect(self.update_debug_breakpoint_ui)
        self.debug_condition_edit = QLineEdit(
            str(data.get("debug_condition", "") or "")
        )
        self.debug_condition_edit.setMinimumWidth(240)
        self.debug_condition_edit.setPlaceholderText(
            "例如：loop >= 5"
        )
        self.debug_condition_edit.setToolTip(
            "条件为真时才命中断点。使用与“判断表达式”相同的安全语法；"
            "本步骤执行前求值，因此只能读取此前已经设置的变量。"
        )

        self.debug_preset_combo = NoWheelComboBox()
        self.debug_preset_combo.addItems(
            [
                "每次经过都暂停",
                "从第 N 次循环开始",
                "本步骤执行 N 次后",
                "上一步成功时",
                "上一步失败时",
                "高级表达式",
            ]
        )
        fit_combo_to_contents(self.debug_preset_combo)
        debug_preset, debug_value = self.infer_debug_preset(
            self.debug_condition_edit.text()
        )
        self.debug_preset_value_edit = QLineEdit(debug_value or "1")
        self.debug_preset_value_edit.setFixedWidth(70)
        self.debug_preset_value_edit.setToolTip("填写大于等于 1 的整数。")
        self._debug_custom_expression = (
            self.debug_condition_edit.text().strip()
            if debug_preset == "高级表达式"
            else ""
        )
        self._debug_preset_mode = debug_preset
        self.debug_preset_combo.setCurrentText(debug_preset)
        self.debug_preset_combo.currentTextChanged.connect(
            self.on_debug_preset_changed
        )
        self.debug_preset_value_edit.textChanged.connect(
            self.sync_debug_condition_from_preset
        )
        self.debug_condition_edit.textEdited.connect(
            self.remember_debug_custom_expression
        )

        self.success_skip_edit = QLineEdit(str(data.get("success_skip", "0")))
        self.success_skip_edit.setFixedWidth(90)
        self.success_skip_edit.setToolTip("本步骤成功后跳过后续 N 步。填 0 表示不跳过。")

        self.success_jump_edit = QLineEdit(str(data.get("success_jump", "0")))
        self.success_jump_edit.setFixedWidth(90)
        self.success_jump_edit.setToolTip("本步骤成功后跳至指定步号继续执行。填 0 表示关闭；步号从 1 开始。")

        self.fail_skip_edit = QLineEdit(str(data.get("fail_skip", "0")))
        self.fail_skip_edit.setFixedWidth(90)
        self.fail_skip_edit.setToolTip("达到连续失败次数后，跳过后续 N 步。填 0 表示直接执行下一步。")

        self.fail_jump_edit = QLineEdit(str(data.get("fail_jump", "0")))
        self.fail_jump_edit.setFixedWidth(90)
        self.fail_jump_edit.setToolTip("达到连续失败次数后跳至指定步号继续执行。填 0 表示关闭；步号从 1 开始。")
        self.reference_fields_dirty = set()
        self.reference_editors = {
            "success_jump": self.success_jump_edit,
            "fail_jump": self.fail_jump_edit,
            "until_false_jump": self.until_false_jump_edit,
            "until_true_jump": self.until_true_jump_edit,
        }
        for reference_name, editor in self.reference_editors.items():
            editor.textEdited.connect(
                lambda _text, name=reference_name: self.reference_fields_dirty.add(name)
            )

        control_form.addRow("本步骤重复:", inline_row(
            (self.repeat_combo,),
            ("次数", self.repeat_count_edit),
            (HelpBtn("【本步骤重复】\n可执行一次、指定次数或无限重复。指定次数时在右侧填写本步骤连续执行的次数。"),),
        ))
        control_form.addRow("循环范围:", step_loop_row)
        self.step_loop_row = step_loop_row
        control_form.addRow("同点点击上限:", inline_row(
            (self.point_limit_chk,),
            ("次数", self.point_limit_count_edit),
            (HelpBtn("【同点点击上限】\n仅对图片点击生效。某个匹配点达到次数上限后会忽略该点，继续尝试其他匹配位置。"),),
        ))
        control_form.addRow("图片内点击点:", image_point_row)
        control_form.addRow("本步识别区域:", step_region_row)
        control_form.addRow("坐标步进:", coord_every_row)
        control_form.addRow("步进方向:", coord_direction_row)
        control_form.addRow("目标点位:", coord_point_row)
        control_form.addRow("移动上限:", coord_limit_row)
        control_form.addRow("重置循环:", coord_reset_row)
        self.coord_reset_row = coord_reset_row
        control_form.addRow("手动修正:", coord_manual_row)
        control_form.addRow("自定义点位:", coord_sequence_box)
        control_form.addRow("失败处理:", inline_row(
            ("连续失败", self.fail_limit_edit),
            (self.no_skip_wait_chk,),
            (HelpBtn("【失败处理】\n连续失败次数决定何时放弃本步骤；开启禁止跳过后，会优先一直重试到成功或单步超时。"),),
        ))
        run_max_row = inline_row(
            (self.run_max_executions_edit, "次后跳过"),
            (HelpBtn("【本次运行最多执行】\n只在当前这次启动脚本期间计数，手动停止并重新启动后清零。\n达到上限后，本步骤视为跳过，不触发成功/失败跳转，也不会执行本步骤内的重复次数。填 0 表示不限。"),),
        )
        control_form.addRow("本次运行上限:", run_max_row)
        self.run_max_row = run_max_row
        control_form.addRow("成功分支:", inline_row(
            ("跳过", self.success_skip_edit), ("跳至", self.success_jump_edit),
            (HelpBtn("【成功分支】\n跳至填 0 表示关闭；同一结果中“跳至”优先于“跳过”。"),),
        ))
        control_form.addRow("失败分支:", inline_row(
            ("跳过", self.fail_skip_edit), ("跳至", self.fail_jump_edit),
            (HelpBtn("【失败分支】\n达到连续失败次数后执行。跳至填 0 表示关闭；“跳至”优先于“跳过”。"),),
        ))

        self.control_note = QLabel("")
        self.control_note.setProperty("role", "muted")
        self.control_note.setWordWrap(True)
        control_form.addRow("", self.control_note)
        layout.addWidget(control_box)

        self.debug_section = CollapsibleSection(
            "高级调试",
            expanded=self.debug_breakpoint_chk.isChecked(),
        )
        debug_form = QFormLayout()
        debug_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        debug_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        debug_form.setHorizontalSpacing(10)
        debug_form.setVerticalSpacing(7)
        debug_form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        debug_form.addRow(
            "步骤前暂停:",
            inline_row(
                (self.debug_breakpoint_chk,),
                (
                    HelpBtn(
                        "【调试断点】\n完整运行脚本时，会在执行本步骤前暂停。暂停后可继续运行或单步越过。\n直接使用主界面的“只执行当前步骤”不会在断点处停住。"
                    ),
                ),
            ),
        )
        debug_preset_row = ResponsiveRow()
        debug_preset_row.add_group(self.debug_preset_combo)
        self.debug_preset_value_group = debug_preset_row.add_group(
            "N:", self.debug_preset_value_edit
        )
        debug_preset_row.add_group(
            HelpBtn(
                "【暂停条件】\n“每次经过”最适合普通排查。\n“从第 N 次循环开始”会从第 N 轮起在每次经过本步骤时暂停。\n“本步骤执行 N 次后”会在已执行 N 次后的每次再次执行前暂停。\n上一执行步骤的成功或失败也可作为条件；脚本刚启动时尚无上一步，失败状态按默认值处理。"
            )
        )
        debug_form.addRow("暂停条件:", debug_preset_row)
        self.debug_expression_label = QLabel("高级表达式:")
        self.debug_expression_row = inline_row(
            (self.debug_condition_edit,),
            (
                HelpBtn(
                    "【高级断点表达式】\n只有条件结果为真时才暂停，例如 loop >= 5 或 counter > 10。\n使用安全表达式语法，不会执行 Python 代码。变量必须在到达本步骤前已经设置；若运行时无法求值，为避免漏过问题会暂停并显示原因。"
                ),
            ),
        )
        debug_form.addRow(self.debug_expression_label, self.debug_expression_row)
        debug_note = QLabel(
            "调试设置不会改变步骤执行结果。没有排查脚本问题时，可保持关闭。"
        )
        debug_note.setProperty("role", "muted")
        debug_note.setWordWrap(True)
        debug_form.addRow("", debug_note)
        self.debug_section.set_content_layout(debug_form)
        layout.addWidget(self.debug_section)
        self.apply_settings_mode(self.settings_mode)

        self.update_repeat_ui()
        self.update_debug_preset_ui()
        self.update_debug_breakpoint_ui()
        self.update_point_limit_ui()
        self.update_image_click_point_ui()
        self.update_step_region_ui()
        self.update_coord_step_ui()
        self.update_coord_step_manual_ui()
        self.update_coord_sequence_ui()
        self.update_until_condition_ui()
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText("保存")
        btn_box.button(QDialogButtonBox.Cancel).setText("取消")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        outer_layout.addWidget(btn_box)

        geometry = self.dialog_settings.value("task_config_dialog_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(980, 650)
        self.update_context_note()

    def apply_settings_mode(self, mode):
        self.settings_mode = (
            "advanced" if str(mode) == "advanced" else "simple"
        )
        advanced = self.settings_mode == "advanced"
        for row in (
            self.step_loop_row,
            self.coord_reset_row,
            self.run_max_row,
        ):
            self.control_form.setRowVisible(row, advanced)
        self._refresh_coord_step_direction_options(advanced)
        self.debug_section.setVisible(
            advanced or self.debug_breakpoint_chk.isChecked()
        )
        self.control_note.setText(
            "跳至填 0 表示关闭；同一结果里“跳至”优先于“跳过”。循环范围只控制本步骤在哪些脚本循环轮次生效，被范围跳过不会触发成功/失败分支。开启禁止跳过后，连续失败次数暂不生效，失败分支会等到成功或超时后再处理。移动到新点位时，“移动上限”表示起点到目标点之间的总点位数；“重置循环”可让本路径点击指定次数后回到起点。"
            if advanced
            else "跳至填 0 表示关闭；同一结果里“跳至”优先于“跳过”。开启禁止跳过后，连续失败次数暂不生效，失败分支会等到成功或超时后再处理。移动到新点位时，“移动上限”表示起点到目标点之间的总点位数。"
        )
        self.update_coord_step_ui()

    def _refresh_coord_step_direction_options(self, advanced):
        combo = self.coord_step_direction_combo
        current = combo.currentText() or "移动到新点位"
        self._coord_direction_locked_for_simple = False
        if advanced:
            options = list(self.COORD_STEP_DIRECTIONS)
        elif (
            current not in self.SIMPLE_COORD_STEP_DIRECTIONS
            and self.coord_step_chk.isChecked()
        ):
            # Existing advanced paths must remain intact when merely viewed in
            # simple mode. The value stays visible but becomes read-only.
            options = [current]
            self._coord_direction_locked_for_simple = True
        else:
            options = list(self.SIMPLE_COORD_STEP_DIRECTIONS)
            current = options[0]
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(options)
        combo.setCurrentText(current if current in options else options[0])
        combo.blockSignals(False)
        combo.setToolTip(
            "当前步骤正在使用高级步进方向；切换到高级模式后才能修改。"
            if self._coord_direction_locked_for_simple
            else ""
        )

    def update_window_title(self):
        if self.step_index:
            title = f"第{self.step_index}步设置"
        else:
            title = "步骤设置"
        if self.step_type:
            title += f" - {self.step_type}"
        self.setWindowTitle(title)

    def update_context_note(self):
        if self.is_until_condition_task():
            text = "当前步骤用于判断条件：不直接点击；条件未满足时按设置跳回，满足后继续或跳至指定步骤。"
        elif self.coordinate_step_available:
            text = "当前参数是屏幕坐标：图片识别相关设置会自动忽略，坐标步进可用。"
        elif self.image_settings_available:
            if self.image_click_point_available:
                text = "当前参数是有效图片路径：图片识别、同点上限和图片内点击点可按需启用。"
            else:
                text = "当前参数按图片识别处理；图片内点击点需要填写存在的图片文件后才可启用。"
        else:
            text = "当前步骤不使用图片识别或坐标步进；这里只保留重复、循环范围和条件分支等通用设置。"
        self.context_note.setText(text)

    def is_until_condition_task(self):
        return str(getattr(self, "step_type", "")) == "直到条件成立"

    def update_step_context(self, image_settings_available=None, point_limit_available=None, coordinate_step_available=None, base_coordinate=None, image_path=None, image_click_point_available=None, step_index=None, step_type=None):
        if step_index is not None:
            self.step_index = step_index
        if step_type is not None:
            self.step_type = step_type
        self.update_window_title()

        if image_settings_available is not None:
            self.image_settings_available = bool(image_settings_available)
        if point_limit_available is not None:
            self.point_limit_available = bool(point_limit_available)
        if coordinate_step_available is not None:
            self.coordinate_step_available = bool(coordinate_step_available)
        if base_coordinate is not None or not self.coordinate_step_available:
            self.base_coordinate = base_coordinate
        if image_path is not None:
            self.image_path = str(image_path)
        if image_click_point_available is not None:
            self.image_click_point_available = bool(image_click_point_available)

        self.enable_chk.setEnabled(self.image_settings_available)
        self.point_limit_chk.setEnabled(self.point_limit_available)
        self.image_click_point_chk.setEnabled(self.image_click_point_available)
        self.step_region_chk.setEnabled(self.image_settings_available)
        self.coord_step_chk.setEnabled(self.coordinate_step_available)
        self.coord_sequence_chk.setEnabled(self.coordinate_step_available)
        if not self.coordinate_step_available:
            self.close_coord_step_preview()

        self.update_image_settings_enabled()
        self.update_point_limit_ui()
        self.update_image_click_point_ui()
        self.update_step_region_ui()
        self.update_coord_step_ui()
        self.update_coord_sequence_ui()
        self.update_until_condition_ui()
        self.update_context_note()
        self.refresh_coord_step_preview_points()

    def refresh_reference_numbers(self, data):
        for name, editor in getattr(self, "reference_editors", {}).items():
            if name not in self.reference_fields_dirty:
                editor.setText(str(data.get(name, "0")))

    def update_until_condition_ui(self, _=None):
        active = self.is_until_condition_task()
        self.until_group.setVisible(active)
        self.until_group.setEnabled(active)
        if not active:
            return
        enabled_count = 0
        for _cond_idx, widgets in self.until_condition_widgets.items():
            checked = widgets["enabled"].isChecked()
            enabled_count += 1 if checked else 0
            mode = widgets["mode"].currentText()
            needs_image = mode in ["图片出现", "图片消失", "区域变成指定图片"]
            needs_region = mode in ["区域发生变化", "区域变成指定图片"]
            widgets["mode"].setEnabled(checked)
            widgets["image"].setEnabled(checked and needs_image)
            widgets["image_btn"].setEnabled(checked and needs_image)
            widgets["region"].setEnabled(checked)
            widgets["region_btn"].setEnabled(checked)
            widgets["conf"].setEnabled(checked and mode in ["图片出现", "图片消失"])
            widgets["diff"].setEnabled(checked and mode == "区域发生变化")
            widgets["similarity"].setEnabled(checked and mode == "区域变成指定图片")
            if needs_region:
                widgets["region"].setPlaceholderText("必填区域 x,y,w,h")
            else:
                widgets["region"].setPlaceholderText("区域 x,y,w,h，可空")
        self.until_logic_combo.setEnabled(enabled_count > 1)

    def select_until_condition_image(self, cond_idx):
        widgets = self.until_condition_widgets.get(cond_idx)
        if not widgets:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择条件图片", filter="Images (*.png *.jpg *.bmp)")
        if path:
            widgets["image"].setText(path)

    def start_until_region_pick(self, cond_idx):
        win = RegionWindow(multi=False)
        self.until_region_windows[cond_idx] = win
        win.region_selected.connect(lambda rect, i=cond_idx: self.on_until_region_selected(i, rect))
        win.destroyed.connect(lambda *_args, i=cond_idx: self.until_region_windows.pop(i, None))

    def on_until_region_selected(self, cond_idx, rect):
        widgets = self.until_condition_widgets.get(cond_idx)
        if widgets:
            widgets["region"].setText(format_region_text(rect))

    def update_image_settings_enabled(self):
        self.form_widget.setEnabled(self.image_settings_available and self.enable_chk.isChecked())

    def update_repeat_ui(self, _=None):
        self.repeat_count_edit.setEnabled(self.repeat_combo.currentText() == "指定次数")

    @staticmethod
    def infer_debug_preset(expression):
        source = str(expression or "").strip()
        if not source:
            return "每次经过都暂停", "1"
        loop_match = re.fullmatch(r"loop\s*>=\s*(\d+)", source)
        if loop_match:
            return "从第 N 次循环开始", loop_match.group(1)
        execution_match = re.fullmatch(
            r"execution_count\s*>=\s*(\d+)", source
        )
        if execution_match:
            return "本步骤执行 N 次后", execution_match.group(1)
        if source == "last_success":
            return "上一步成功时", "1"
        if source == "not last_success":
            return "上一步失败时", "1"
        return "高级表达式", "1"

    def remember_debug_custom_expression(self, text):
        if self.debug_preset_combo.currentText() == "高级表达式":
            self._debug_custom_expression = str(text or "")

    def on_debug_preset_changed(self, mode):
        if self._debug_preset_mode == "高级表达式":
            self._debug_custom_expression = self.debug_condition_edit.text().strip()
        self._debug_preset_mode = str(mode or "")
        if self._debug_preset_mode == "高级表达式":
            self.debug_condition_edit.setText(self._debug_custom_expression)
        else:
            self.sync_debug_condition_from_preset()
        self.update_debug_preset_ui()

    def sync_debug_condition_from_preset(self, _=None):
        mode = self.debug_preset_combo.currentText()
        if mode == "高级表达式":
            return
        value = self.debug_preset_value_edit.text().strip() or "1"
        expressions = {
            "每次经过都暂停": "",
            "从第 N 次循环开始": f"loop >= {value}",
            "本步骤执行 N 次后": f"execution_count >= {value}",
            "上一步成功时": "last_success",
            "上一步失败时": "not last_success",
        }
        self.debug_condition_edit.setText(expressions.get(mode, ""))

    def update_debug_preset_ui(self, _=None):
        mode = self.debug_preset_combo.currentText()
        needs_value = mode in (
            "从第 N 次循环开始",
            "本步骤执行 N 次后",
        )
        advanced = mode == "高级表达式"
        self.debug_preset_value_group.setVisible(needs_value)
        self.debug_expression_label.setVisible(advanced)
        self.debug_expression_row.setVisible(advanced)
        self.update_debug_breakpoint_ui()

    def update_debug_breakpoint_ui(self, _=None):
        enabled = self.debug_breakpoint_chk.isChecked()
        mode = self.debug_preset_combo.currentText()
        self.debug_preset_combo.setEnabled(enabled)
        self.debug_preset_value_edit.setEnabled(
            enabled
            and mode in ("从第 N 次循环开始", "本步骤执行 N 次后")
        )
        self.debug_condition_edit.setEnabled(
            enabled and mode == "高级表达式"
        )

    def update_point_limit_ui(self, _=None):
        self.point_limit_count_edit.setEnabled(self.point_limit_available and self.point_limit_chk.isChecked())

    def update_image_click_point_ui(self, _=None):
        enabled = self.image_click_point_available
        checked = enabled and self.image_click_point_chk.isChecked()
        self.image_click_point_chk.setEnabled(enabled)
        self.image_click_point_select_btn.setEnabled(enabled)
        self.image_click_point_preview_btn.setEnabled(checked)
        if not enabled:
            self.image_click_point_info.setText("请先选择图片路径")
            return
        rx = parse_float_text(self.image_click_point_rx, 0.5)
        ry = parse_float_text(self.image_click_point_ry, 0.5)
        self.image_click_point_info.setText(f"X {rx:.3f}, Y {ry:.3f}" if checked else "默认点击图片中心")

    def update_step_region_ui(self, _=None):
        enabled = self.image_settings_available
        checked = enabled and self.step_region_chk.isChecked()
        self.step_region_chk.setEnabled(enabled)
        self.step_region_edit.setEnabled(checked)
        self.step_region_pick_btn.setEnabled(enabled)
        self.step_region_clear_btn.setEnabled(bool(self.step_region_edit.text().strip()))

    def start_step_region_pick(self):
        if not self.image_settings_available:
            QMessageBox.information(self, "无法框选", "当前步骤不是图片识别步骤。")
            return
        win = RegionWindow(multi=False)
        self.step_region_window = win
        win.region_selected.connect(self.on_step_region_selected)
        win.destroyed.connect(lambda *_args: setattr(self, "step_region_window", None))

    def on_step_region_selected(self, rect):
        self.step_region_edit.setText(format_region_text(rect))
        self.step_region_chk.setChecked(True)
        self.update_step_region_ui()

    def clear_step_region(self):
        self.step_region_edit.clear()
        self.step_region_chk.setChecked(False)
        self.update_step_region_ui()

    def select_image_click_point(self):
        if not self.image_click_point_available:
            QMessageBox.information(self, "无法选择", "当前步骤不是可用的图片点击步骤。请先选择左键/右键点击指令，并填写存在的图片路径。")
            return
        try:
            dialog = ImageClickPointDialog(
                self.image_path,
                parse_float_text(self.image_click_point_rx, 0.5),
                parse_float_text(self.image_click_point_ry, 0.5),
                selectable=True,
                parent=self
            )
        except Exception as e:
            QMessageBox.warning(self, "图片打开失败", str(e))
            return
        if dialog.exec() == QDialog.Accepted:
            rx, ry = dialog.selected_ratio()
            self.image_click_point_rx = f"{rx:.6f}"
            self.image_click_point_ry = f"{ry:.6f}"
            self.image_click_point_chk.setChecked(True)
            self.update_image_click_point_ui()

    def preview_image_click_point(self):
        if not (self.image_click_point_available and self.image_click_point_chk.isChecked()):
            return
        try:
            dialog = ImageClickPointDialog(
                self.image_path,
                parse_float_text(self.image_click_point_rx, 0.5),
                parse_float_text(self.image_click_point_ry, 0.5),
                selectable=False,
                parent=self
            )
        except Exception as e:
            QMessageBox.warning(self, "图片打开失败", str(e))
            return
        dialog.exec()

    def update_coord_step_ui(self, _=None):
        sequence_enabled = getattr(self, "coord_sequence_chk", None) and self.coord_sequence_chk.isChecked()
        enabled = self.coordinate_step_available and self.coord_step_chk.isChecked() and not sequence_enabled
        direction = self.coord_step_direction_combo.currentText()
        for widget in [
            self.coord_step_every_edit, self.coord_step_direction_combo,
            self.coord_step_distance_edit, self.coord_step_dx_edit, self.coord_step_dy_edit,
            self.coord_step_point_edit, self.coord_step_max_steps_edit,
            self.coord_step_max_distance_edit, self.coord_step_stop_chk,
            self.coord_step_reset_after_edit, self.coord_step_pick_btn, self.coord_step_preview_btn
        ]:
            widget.setEnabled(enabled)
        self.coord_step_direction_combo.setEnabled(
            enabled and not self._coord_direction_locked_for_simple
        )
        self.coord_step_distance_edit.setEnabled(enabled and direction in ["向上", "向下", "向左", "向右"])
        self.coord_step_dx_edit.setEnabled(enabled and direction == "自定义偏移")
        self.coord_step_dy_edit.setEnabled(enabled and direction == "自定义偏移")
        self.coord_step_point_edit.setEnabled(enabled and direction == "移动到新点位")
        self.coord_step_pick_btn.setEnabled(enabled and direction == "移动到新点位")
        self.coord_step_preview_btn.setEnabled(enabled and self.base_coordinate is not None)
        self.update_coord_step_manual_ui()

    def update_coord_sequence_ui(self, _=None):
        enabled = self.coordinate_step_available and self.coord_sequence_chk.isChecked()
        self.coord_sequence_chk.setEnabled(self.coordinate_step_available)
        self.coord_sequence_details.setVisible(enabled)
        for widget in [
            self.coord_sequence_text,
            self.coord_sequence_end_combo,
            self.coord_sequence_pick_btn,
            self.coord_sequence_preview_btn,
            self.coord_sequence_clear_btn
        ]:
            widget.setEnabled(enabled)
        if enabled:
            self.coord_step_chk.setToolTip("已启用自定义点位，坐标步进会自动忽略。关闭自定义点位后可继续使用坐标步进。")
        else:
            self.coord_step_chk.setToolTip("仅对直接输入坐标的点击步骤生效；图片识别点击会自动忽略。")
        self.coord_sequence_box.updateGeometry()
        self.form_widget.updateGeometry()
        self.update_coord_step_ui()

    def coord_sequence_points(self):
        return parse_coordinate_sequence(self.coord_sequence_text.toPlainText())

    def append_coord_sequence_point(self, value):
        point = parse_coordinate_text(value)
        if not point:
            return
        points = self.coord_sequence_points()
        points.append(point)
        self.coord_sequence_text.setPlainText(serialize_coordinate_sequence(points))

    def start_coord_sequence_pick(self):
        self.coord_sequence_picker = MultiPointPickerUI(self.append_coord_sequence_point, self.on_coord_sequence_pick_finished)

    def on_coord_sequence_pick_finished(self, points):
        self.coord_sequence_picker = None
        self.update_coord_sequence_ui()

    def preview_coord_sequence(self):
        points = self.coord_sequence_points()
        if not points:
            QMessageBox.information(self, "无法预览", "请先添加至少一个自定义点位。")
            return
        self.close_coord_step_preview()
        labels = [str(i + 1) for i in range(len(points))]
        self.coord_step_preview = CoordinateStepPreviewOverlay(
            points,
            {"direction": "自定义点位"},
            title=f"自定义点位预览：{len(points)} 个点",
            detail_text="实际执行每次只点击当前序号的点；再次执行本步骤才进入下一个点。",
            auto_close_ms=0,
            point_labels=labels
        )
        self.coord_step_preview.destroyed.connect(self.clear_coord_step_preview)

    def coord_step_manual_active(self):
        return self.coord_step_direction_combo.currentText() == "移动到新点位"

    def manual_point_indices(self):
        return sorted(int(idx) for idx in self.coord_step_manual_points.keys())

    def update_coord_step_manual_ui(self):
        active = self.coordinate_step_available and self.coord_step_chk.isChecked() and self.coord_step_manual_active()
        count = len(self.coord_step_manual_points) if active else 0
        if count:
            nums = "、".join(str(idx + 1) for idx in self.manual_point_indices())
            self.coord_step_manual_info.setText(f"已手动修正 {count} 个点：第 {nums} 个")
        else:
            self.coord_step_manual_info.setText("无手动修正点")
        self.coord_step_clear_manual_btn.setEnabled(active and count > 0)

    def current_coord_step_points(self):
        if self.base_coordinate is None:
            return []
        return build_coord_step_positions(self.base_coordinate[0], self.base_coordinate[1], self.current_coord_step_options())

    def refresh_coord_step_preview_points(self):
        preview = getattr(self, "coord_step_preview", None)
        if not preview:
            return
        points = self.current_coord_step_points()
        if points:
            preview.set_points(points)
            if hasattr(preview, "set_marked_indices"):
                preview.set_marked_indices(self.manual_point_indices())

    def clear_coord_step_manual_points(self, silent=False):
        if not self.coord_step_manual_points:
            self.update_coord_step_manual_ui()
            return
        self.coord_step_manual_points = {}
        self.update_coord_step_manual_ui()
        self.refresh_coord_step_preview_points()
        if not silent:
            QToolTip.showText(QCursor.pos(), "已清除本步骤的手动修正点", self, QRect(), 1800)

    def on_coord_step_count_changed(self, text):
        if self.coord_step_clearing_due_to_count:
            return
        if self.coord_step_manual_points and str(text) != str(self.coord_step_max_steps_initial):
            self.coord_step_clearing_due_to_count = True
            try:
                self.clear_coord_step_manual_points(silent=True)
                self.coord_step_max_steps_initial = str(text)
            finally:
                self.coord_step_clearing_due_to_count = False

    def current_coord_step_options(self):
        return {
            "every": max(1, int(parse_float_text(self.coord_step_every_edit.text(), 1))),
            "direction": self.coord_step_direction_combo.currentText(),
            "distance": parse_float_text(self.coord_step_distance_edit.text(), 0.0),
            "dx": parse_float_text(self.coord_step_dx_edit.text(), 0.0),
            "dy": parse_float_text(self.coord_step_dy_edit.text(), 0.0),
            "point": self.coord_step_point_edit.text().strip(),
            "max_steps": max(0, int(parse_float_text(self.coord_step_max_steps_edit.text(), 0.0))),
            "max_distance": max(0.0, parse_float_text(self.coord_step_max_distance_edit.text(), 0.0)),
            "reset_after": max(0, int(parse_float_text(self.coord_step_reset_after_edit.text(), 0.0))),
            "manual_points": dict(self.coord_step_manual_points) if self.coord_step_manual_active() else {}
        }

    def start_coord_step_point_pick(self):
        self.coord_step_picker = CoordinatePickerUI("point", self.on_coord_step_point_picked)

    def on_coord_step_point_picked(self, value):
        self.coord_step_point_edit.setText(value)
        self.update_coord_step_ui()

    def on_coord_step_preview_point_moved(self, index, x, y):
        try:
            direction = self.coord_step_direction_combo.currentText()
            point_count = len(getattr(self.coord_step_preview, "points", []))
            if index < 0:
                index = point_count + index
            if index == 0:
                value = f"{int(x)},{int(y)}"
                self.base_coordinate = (int(x), int(y))
                if self.base_coordinate_changed:
                    self.base_coordinate_changed(value)
            elif direction == "移动到新点位" and point_count > 1 and index == point_count - 1:
                self.coord_step_point_edit.setText(f"{int(x)},{int(y)}")
            elif direction == "移动到新点位" and 0 < index < max(0, point_count - 1):
                self.coord_step_manual_points[int(index)] = (int(x), int(y))
                self.update_coord_step_manual_ui()
                if getattr(self, "coord_step_preview", None) and hasattr(self.coord_step_preview, "set_marked_indices"):
                    self.coord_step_preview.set_marked_indices(self.manual_point_indices())
            options = self.current_coord_step_options()
            if self.base_coordinate is None:
                return None
            return build_coord_step_positions(self.base_coordinate[0], self.base_coordinate[1], options)
        except RuntimeError:
            return None

    def show_coord_step_preview(self):
        if self.base_coordinate is None:
            QMessageBox.information(self, "无法预览", "当前步骤没有可用的起点坐标。请先在步骤参数里直接填写起点坐标，例如 100,200。")
            return
        options = self.current_coord_step_options()
        if options["direction"] == "移动到新点位" and not parse_coordinate_text(options.get("point", "")):
            QMessageBox.information(self, "无法预览", "请先填写或选取目标点位，例如 960,540。")
            return
        points = build_coord_step_positions(self.base_coordinate[0], self.base_coordinate[1], options)
        if len(points) <= 1:
            QMessageBox.information(self, "无法预览", "当前步进设置不会产生新的点击点位，请检查步进方向、距离或目标点位。")
            return
        self.close_coord_step_preview()
        editable = [0]
        drag_text = "可拖动起点，右键或空白处关闭。"
        if options["direction"] == "移动到新点位":
            editable = list(range(len(points)))
            drag_text = "拖起点/终点会重算整条路径；拖中间点只修正该点并显示星号。右键或空白处关闭。"
        self.coord_step_preview = CoordinateStepPreviewOverlay(
            points,
            options,
            title=f"坐标步进预览：{len(points)} 个可轮到的点位",
            detail_text=f"实际执行每次只点当前点；再次执行本步骤才移动到下一个点。{drag_text}",
            editable_indices=editable,
            point_moved_callback=self.on_coord_step_preview_point_moved,
            auto_close_ms=0,
            marked_indices=self.manual_point_indices()
        )
        self.coord_step_preview.destroyed.connect(self.clear_coord_step_preview)

    def clear_coord_step_preview(self, *_):
        self.coord_step_preview = None

    def close_coord_step_preview(self):
        preview = getattr(self, "coord_step_preview", None)
        if preview:
            try:
                if hasattr(preview, "point_moved_callback"):
                    preview.point_moved_callback = None
                preview.close()
            except RuntimeError:
                pass
            self.coord_step_preview = None

    def save_dialog_geometry(self):
        try:
            self.dialog_settings.setValue("task_config_dialog_geometry", self.saveGeometry())
        except Exception:
            pass

    def accept(self):
        self.save_dialog_geometry()
        super().accept()

    def reject(self):
        self.save_dialog_geometry()
        super().reject()

    def closeEvent(self, event):
        if getattr(self, "coord_step_picker", None):
            self.coord_step_picker.close()
        if getattr(self, "coord_sequence_picker", None):
            self.coord_sequence_picker.close()
        if getattr(self, "step_region_window", None):
            try:
                self.step_region_window.close()
            except RuntimeError:
                pass
        for win in list(getattr(self, "until_region_windows", {}).values()):
            try:
                win.close()
            except RuntimeError:
                pass
        self.close_coord_step_preview()
        self.save_dialog_geometry()
        super().closeEvent(event)

    def get_data(self):
        data = {
            "custom_en": self.enable_chk.isChecked() and self.image_settings_available,
            "custom_conf": self.conf_edit.text(),
            "custom_scale_min": self.s_min_edit.text(),
            "custom_scale_max": self.s_max_edit.text(),
            "custom_scale_step": self.s_step_edit.text(),
            "custom_gray": self.gray_chk.isChecked(),
            "repeat_mode": self.repeat_combo.currentText(),
            "repeat_count": self.repeat_count_edit.text(),
            "step_loop_start": self.step_loop_start_edit.text(),
            "step_loop_end": self.step_loop_end_edit.text(),
            "point_limit_en": self.point_limit_chk.isChecked() and self.point_limit_available,
            "point_limit_count": self.point_limit_count_edit.text(),
            "image_click_point_en": self.image_click_point_chk.isChecked() and self.image_click_point_available,
            "image_click_point_rx": self.image_click_point_rx,
            "image_click_point_ry": self.image_click_point_ry,
            "step_region_en": self.step_region_chk.isChecked() and self.image_settings_available,
            "step_region": self.step_region_edit.text().strip(),
            "coord_step_en": self.coord_step_chk.isChecked() and self.coordinate_step_available,
            "coord_step_every": self.coord_step_every_edit.text(),
            "coord_step_direction": self.coord_step_direction_combo.currentText(),
            "coord_step_distance": self.coord_step_distance_edit.text(),
            "coord_step_dx": self.coord_step_dx_edit.text(),
            "coord_step_dy": self.coord_step_dy_edit.text(),
            "coord_step_point": self.coord_step_point_edit.text(),
            "coord_step_max_steps": self.coord_step_max_steps_edit.text(),
            "coord_step_max_distance": self.coord_step_max_distance_edit.text(),
            "coord_step_stop": self.coord_step_stop_chk.isChecked(),
            "coord_step_reset_after": self.coord_step_reset_after_edit.text(),
            "coord_step_manual_points": serialize_coord_step_manual_points(self.coord_step_manual_points if (self.coord_step_chk.isChecked() and self.coordinate_step_available and self.coord_step_manual_active()) else {}),
            "coord_sequence_en": self.coord_sequence_chk.isChecked() and self.coordinate_step_available,
            "coord_sequence_points": serialize_coordinate_sequence(self.coord_sequence_points()),
            "coord_sequence_end_action": self.coord_sequence_end_combo.currentText(),
            "fail_limit": self.fail_limit_edit.text(),
            "no_skip_wait": self.no_skip_wait_chk.isChecked(),
            "run_max_executions": self.run_max_executions_edit.text(),
            "debug_breakpoint": self.debug_breakpoint_chk.isChecked(),
            "debug_condition": self.debug_condition_edit.text().strip(),
            "success_skip": self.success_skip_edit.text(),
            "success_jump": self.success_jump_edit.text(),
            "fail_skip": self.fail_skip_edit.text(),
            "fail_jump": self.fail_jump_edit.text()
        }
        data.update({
            "until_logic": self.until_logic_combo.currentText(),
            "until_false_jump": self.until_false_jump_edit.text(),
            "until_true_jump": self.until_true_jump_edit.text(),
            "until_max_checks": self.until_max_checks_edit.text(),
            "until_max_seconds": self.until_max_seconds_edit.text(),
            "until_on_limit": self.until_on_limit_combo.currentText(),
        })
        for cond_idx, widgets in self.until_condition_widgets.items():
            data.update({
                f"until_cond{cond_idx}_en": widgets["enabled"].isChecked(),
                f"until_cond{cond_idx}_mode": widgets["mode"].currentText(),
                f"until_cond{cond_idx}_image": widgets["image"].text().strip(),
                f"until_cond{cond_idx}_region": widgets["region"].text().strip(),
                f"until_cond{cond_idx}_conf": widgets["conf"].text().strip(),
                f"until_cond{cond_idx}_diff": widgets["diff"].text().strip(),
                f"until_cond{cond_idx}_similarity": widgets["similarity"].text().strip(),
            })
        return data

class FloatingSettingsDialog(QDialog):
    def __init__(self, settings, geometry_key, title, default_size):
        super().__init__(None)
        self.settings = settings
        self.geometry_key = geometry_key
        self.default_size = default_size
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowModality(Qt.NonModal)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 520)

        geometry = self.settings.value(self.geometry_key)
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(*self.default_size)

    def save_dialog_geometry(self):
        try:
            self.settings.setValue(self.geometry_key, self.saveGeometry())
        except Exception:
            pass

    def disable_auto_default_buttons(self):
        """Prevent Enter in an editor from activating an unrelated command."""

        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

    def showEvent(self, event):
        self.disable_auto_default_buttons()
        super().showEvent(event)

    def hideEvent(self, event):
        self.save_dialog_geometry()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.save_dialog_geometry()
        super().closeEvent(event)
