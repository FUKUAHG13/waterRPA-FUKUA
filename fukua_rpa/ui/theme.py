"""Shared visual system for the desktop interface without external assets."""

import re

from PySide6.QtGui import QColor, QFont, QPalette


APP_STYLESHEET = r"""
QWidget {
    color: #172033;
    font-family: "Microsoft YaHei UI", "Segoe UI";
}
QMainWindow, QDialog {
    background: #F4F6F8;
}
QWidget#appRoot, QWidget#settingsBody, QWidget#dialogBody {
    background: #F4F6F8;
}
QFrame#profileBar, QFrame#commandBar, QFrame#runBar, QFrame#statusBar {
    background: #FFFFFF;
    border: 1px solid #D7DCE3;
    border-radius: 7px;
}
QFrame#workspacePanel {
    background: #FFFFFF;
    border: 1px solid #D7DCE3;
    border-radius: 7px;
}
QFrame#onboardingNotice {
    background: #EEF5FF;
    border: 1px solid #AFC9EE;
    border-radius: 6px;
}
QFrame#onboardingNotice QLabel {
    color: #234E87;
}
QLabel[role="title"] {
    color: #101828;
    font-size: 12pt;
    font-weight: 700;
}
QLabel[role="sectionTitle"] {
    color: #344054;
    font-size: 10pt;
    font-weight: 650;
}
QLabel[role="muted"] {
    color: #667085;
}
QLabel[role="statusGood"] {
    color: #137A42;
    font-weight: 600;
}
QLabel[role="statusInfo"] {
    color: #2459A9;
    font-weight: 600;
}
QLabel#manualMark {
    color: #FFFFFF;
    background: #7C3AED;
    border: none;
    border-radius: 4px;
    font-size: 8pt;
    font-weight: 700;
}
QLabel#breakpointMark {
    color: #FFFFFF;
    background: #C9362B;
    border: none;
    border-radius: 4px;
    font-size: 8pt;
    font-weight: 700;
}
QPushButton {
    min-height: 28px;
    padding: 0 12px;
    color: #344054;
    background: #FFFFFF;
    border: 1px solid #C9D0DA;
    border-radius: 5px;
    font-weight: 550;
}
QPushButton:hover {
    color: #1D4ED8;
    background: #F7FAFF;
    border-color: #7EA6E8;
}
QPushButton:pressed {
    background: #EAF1FD;
    border-color: #3B73C8;
}
QPushButton:focus {
    border: 1px solid #3B82F6;
}
QPushButton:disabled {
    color: #98A2B3;
    background: #F2F4F7;
    border-color: #E2E6EC;
}
QPushButton[variant="primary"] {
    color: #FFFFFF;
    background: #2563EB;
    border-color: #2563EB;
    font-weight: 650;
}
QPushButton[variant="primary"]:hover {
    background: #1D4ED8;
    border-color: #1D4ED8;
}
QPushButton[variant="tonal"] {
    color: #1E4F91;
    background: #EAF2FF;
    border-color: #B8CFF2;
}
QPushButton[variant="tonal"]:hover {
    background: #DCEAFF;
    border-color: #8FB2E8;
}
QPushButton[variant="success"] {
    color: #FFFFFF;
    background: #16803C;
    border-color: #16803C;
    font-weight: 700;
}
QPushButton[variant="success"]:hover {
    background: #116A32;
    border-color: #116A32;
}
QPushButton[variant="danger"] {
    color: #FFFFFF;
    background: #C9362B;
    border-color: #C9362B;
    font-weight: 700;
}
QPushButton[variant="danger"]:hover {
    background: #AA2D25;
    border-color: #AA2D25;
}
QPushButton[variant="ghost"] {
    color: #475467;
    background: transparent;
    border-color: transparent;
}
QPushButton[variant="ghost"]:hover {
    color: #1D4ED8;
    background: #EEF4FF;
    border-color: #D6E4FA;
}
QPushButton[variant="dangerGhost"] {
    color: #B42318;
    background: transparent;
    border-color: transparent;
}
QPushButton[variant="dangerGhost"]:hover {
    color: #8F2017;
    background: #FEECEB;
    border-color: #FACBC7;
}
QPushButton[variant="dangerGhost"][syntheticHover="true"] {
    color: #8F2017;
    background: #FEECEB;
    border-color: #FACBC7;
}
QPushButton[bound="true"] {
    color: #137A42;
    background: #ECF8F0;
    border-color: #A9D8B8;
    font-weight: 650;
}
QPushButton[iconOnly="true"] {
    min-width: 30px;
    max-width: 30px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
}
QPushButton[compactText="true"] {
    min-width: 30px;
    padding: 0 6px;
}
QPushButton#helpButton {
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    padding: 0;
    color: #2459A9;
    background: #EAF2FF;
    border: 1px solid #B8CFF2;
    border-radius: 10px;
    font-size: 8pt;
    font-weight: 700;
}
QPushButton#helpButton:hover {
    color: #FFFFFF;
    background: #2563EB;
    border-color: #2563EB;
}
QPushButton#sectionToggle {
    min-height: 34px;
    padding: 0 12px;
    text-align: left;
    color: #344054;
    background: #F7F9FC;
    border: 1px solid #D7DCE3;
    border-radius: 6px;
    font-weight: 650;
}
QPushButton#sectionToggle:hover {
    color: #1E4F91;
    background: #F0F5FD;
    border-color: #AFC5E8;
}
QPushButton#sectionToggle:checked {
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
}
QFrame#sectionContent {
    background: #FFFFFF;
    border: 1px solid #D7DCE3;
    border-top: none;
    border-bottom-left-radius: 6px;
    border-bottom-right-radius: 6px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 28px;
    padding: 0 8px;
    color: #172033;
    background: #FFFFFF;
    border: 1px solid #C9D0DA;
    border-radius: 5px;
    selection-background-color: #BFD4F6;
    selection-color: #172033;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #8FA4BF;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #3B82F6;
    background: #FFFFFF;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #98A2B3;
    background: #F2F4F7;
    border-color: #E2E6EC;
}
QComboBox {
    padding-right: 24px;
}
QComboBox::drop-down {
    width: 22px;
    border: none;
}
QComboBox QAbstractItemView {
    color: #172033;
    background: #FFFFFF;
    border: 1px solid #C9D0DA;
    selection-color: #172033;
    selection-background-color: #DCEAFF;
    outline: 0;
}
QCheckBox {
    min-height: 28px;
    spacing: 7px;
    color: #344054;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QCheckBox:disabled {
    color: #98A2B3;
}
QCheckBox[emphasis="true"] {
    color: #1E4F91;
    font-weight: 650;
}
QWidget[responsiveGroup="true"] {
    min-height: 30px;
}
QWidget[responsiveGroup="true"] QLabel,
QWidget[responsiveGroup="true"] QCheckBox {
    min-height: 28px;
}
QTextEdit, QListWidget {
    color: #172033;
    background: #FFFFFF;
    border: 1px solid #D7DCE3;
    border-radius: 5px;
    selection-background-color: #DCEAFF;
    selection-color: #172033;
    outline: 0;
}
QListWidget#taskList {
    background: #F8FAFC;
    border: none;
    border-radius: 0;
    padding: 5px;
}
QListWidget#taskList::item {
    margin: 2px 0;
}
QListWidget#taskList::item:selected {
    background: transparent;
}
QTextEdit#logView {
    color: #344054;
    background: #F8FAFC;
    border-color: #D7DCE3;
    font-family: "Cascadia Mono", "Microsoft YaHei UI";
    font-size: 9pt;
    padding: 7px;
}
QFrame#taskRow {
    background: #FFFFFF;
    border: 1px solid #D7DCE3;
    border-radius: 6px;
}
QFrame#taskRow[selected="true"] {
    background: #EFF5FF;
    border: 2px solid #3B82F6;
}
QFrame#taskRow[debugPaused="true"] {
    background: #FFF7E8;
    border: 2px solid #D97706;
}
QFrame#taskRow QLabel#stepIndex {
    color: #667085;
    font-weight: 700;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    width: 10px;
    margin: 2px;
    background: transparent;
}
QScrollBar::handle:vertical {
    min-height: 28px;
    background: #BCC5D2;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #8F9BAD;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    height: 0;
    background: transparent;
}
QScrollBar:horizontal {
    height: 10px;
    margin: 2px;
    background: transparent;
}
QScrollBar::handle:horizontal {
    min-width: 28px;
    background: #BCC5D2;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #8F9BAD;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    width: 0;
    background: transparent;
}
QSplitter::handle {
    background: #E4E7EC;
}
QSplitter::handle:hover {
    background: #AFC5E8;
}
QSplitter::handle:vertical {
    height: 5px;
}
QGroupBox {
    margin-top: 12px;
    padding-top: 8px;
    border: 1px solid #D7DCE3;
    border-radius: 6px;
    font-weight: 650;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #344054;
    background: #FFFFFF;
}
QMenu {
    color: #172033;
    background: #FFFFFF;
    border: 1px solid #D7DCE3;
    padding: 4px;
}
QMenu::item {
    min-height: 26px;
    padding: 2px 22px 2px 10px;
    border-radius: 4px;
}
QMenu::item:selected {
    color: #172033;
    background: #DCEAFF;
}
QToolTip {
    color: #FFFFFF;
    background: #263241;
    border: 1px solid #465568;
    border-radius: 4px;
    padding: 6px 8px;
}
"""


_STYLE_LENGTH_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>px|pt)")


def build_modern_stylesheet(scale=1.0):
    """Scale concrete Qt stylesheet metrics from the immutable 100% theme."""

    scale = max(0.75, min(1.8, float(scale)))

    def replace_length(match):
        value = float(match.group("value")) * scale
        if match.group("unit") == "px":
            return f"{max(1, int(round(value)))}px"
        text = f"{max(1.0, value):.2f}".rstrip("0").rstrip(".")
        return f"{text}pt"

    return _STYLE_LENGTH_PATTERN.sub(replace_length, APP_STYLESHEET)


def apply_modern_theme(application, scale=1.0):
    scale = max(0.75, min(1.8, float(scale)))
    application.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI")
    font.setPointSizeF(9.0 * scale)
    application.setFont(font)

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#F4F6F8"))
    palette.setColor(QPalette.WindowText, QColor("#172033"))
    palette.setColor(QPalette.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.AlternateBase, QColor("#F8FAFC"))
    palette.setColor(QPalette.Text, QColor("#172033"))
    palette.setColor(QPalette.Button, QColor("#FFFFFF"))
    palette.setColor(QPalette.ButtonText, QColor("#344054"))
    palette.setColor(QPalette.Highlight, QColor("#DCEAFF"))
    palette.setColor(QPalette.HighlightedText, QColor("#172033"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#98A2B3"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#98A2B3"))
    application.setPalette(palette)
    application.setStyleSheet(build_modern_stylesheet(scale))
    application.setProperty("_fukua_modern_theme", True)
    application.setProperty("_fukua_ui_scale", scale)
