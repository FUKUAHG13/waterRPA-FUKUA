"""Main fukuaRPA window and profile/UI orchestration."""

import hashlib
import html
import json
import os
import re
import subprocess
import threading
import time
import webbrowser
from dataclasses import asdict
from ctypes import wintypes

import pyperclip
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

from PySide6.QtCore import QObject, QSettings, QTimer, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..config_store import (
    archive_existing_backup,
    atomic_write_json,
    load_profiles_backup as load_profiles_backup_file,
    load_profiles_state,
    persist_profiles,
    preserve_corrupt_config as preserve_corrupt_config_file,
    profiles_backup_payload as build_profiles_backup_payload,
    profiles_signature,
    validate_profile_config_data as validate_profile_data,
    validate_profiles_payload as validate_profiles_data,
)
from ..config_schema import default_profile_config, migrate_profile_config
from ..constants import (
    APP_VERSION,
    BUILD_NAME,
    LEGACY_TASK_CLIPBOARD_KEY,
    MAX_CLICK_INDICATOR_OVERLAYS,
    MAX_KEY_MAPPINGS,
    MAX_PROFILES,
    NATIVE_CORE_DLL_NAME,
    PRODUCT_NAME,
    SUPPORTED_WINDOWS_TEXT,
    TASK_TYPE_SECRET_TEXT,
    TASK_CLIPBOARD_KEY,
)
from ..credentials import CredentialStore, CredentialStoreError
from ..diagnostics import run_runtime_diagnostics
from ..engine import RPAEngine
from ..integrity import PAYLOAD_MANIFEST_NAME
from ..logging_service import (
    GLOBAL_CONFIG,
    format_local_timestamp,
    set_log_base_dir,
    write_log,
)
from ..log_policy import (
    DEFAULT_CUSTOM_LOG_CATEGORIES,
    LOG_APPLICATION,
    LOG_CATEGORY_SPECS,
    LOG_CRITICAL,
    LOG_MODE_COMPLETE,
    LOG_MODE_CUSTOM,
    LOG_MODE_DETAILED,
    LOG_MODE_LABELS,
    LOG_MODE_SIMPLE,
    LOG_RUN,
    LogPolicy,
    categories_for_mode,
    normalize_log_categories,
    normalize_log_mode,
)
from ..mapping_backend import WindowBindingError, WindowMappingBackend
from ..paths import get_base_dir, get_log_path, runtime_path_info
from ..performance import PerformanceMetrics
from ..profile_model import ProfileCollection
from ..preview_model import (
    build_coordinate_preview,
    build_preview_line_segments,
    coordinate_preview_options,
)
from ..profile_package import (
    MissingPackageAssetsError,
    asset_export_name as package_asset_export_name,
    collect_profile_image_paths as package_collect_image_paths,
    export_full_package,
    import_full_package,
    rewrite_profile_image_paths as package_rewrite_image_paths,
    safe_extract_full_package as package_safe_extract,
)
from ..run_config import EngineRunConfig, RunConfigError, RunRequest
from ..scale_memory import (
    ScaleMemoryPolicy,
    format_manual_scales,
    parse_manual_scales,
)
from ..session import ApplicationSession
from ..task_model import (
    config_bool,
    parse_coordinate_text,
    parse_float_text,
)
from ..task_model import until_condition_list_from_data
from ..validation import validate_task_list
from ..window_diagnostics import format_window_inspection
from ..workflow_analysis import (
    analyze_loop_risks as analyze_workflow_loop_risks,
    analyze_workflow_structure,
)
from ..workflow_document import (
    REFERENCE_FIELDS,
    apply_numeric_reference_edits,
    clone_task_for_insert,
    normalize_workflow_tasks,
    references_to_step,
    remove_task_and_clear_references,
)
from ..win32_api import (
    HOTKEY_ID_MAPPING_BASE,
    HOTKEY_ID_START,
    HOTKEY_ID_STOP,
    HOTKEY_MAPPING_COUNT,
    HWND_NOTOPMOST,
    HWND_TOPMOST,
    MOD_NOREPEAT,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOOWNERZORDER,
    SWP_NOSIZE,
    SWP_SHOWWINDOW,
    WM_HOTKEY,
    hotkey_display_text,
    hotkey_is_down,
    hotkey_signature,
    is_safe_global_hotkey,
    kernel32,
    parse_hotkey_text,
    user32,
)
from .components import (
    CollapsibleSection,
    FloatingSettingsDialog,
    HelpBtn,
    NoWheelComboBox,
    NoWheelSpinBox,
    PersistentActionMenu,
    ResponsiveRow,
    fit_combo_to_contents,
    fit_text_button,
)
from .controllers import RunController
from .input_tools import (
    CoordinatePickerUI,
    KeyCaptureDialog,
    KeyMappingHookThread,
    RecorderUI,
    RegionWindow,
)
from .integrity_worker import PayloadVerificationThread
from .overlays import ClickPointOverlay, CoordinateStepPreviewOverlay, RunningStatusOverlay
from .task_row import DraggableListWidget, TaskRow
from .theme import apply_modern_theme


class RuntimeInitBridge(QObject):
    completed = Signal(bool, str, float)


class RPAWindow(QMainWindow):
    @property
    def profiles_data(self):
        return self.profile_model.profiles

    @profiles_data.setter
    def profiles_data(self, value):
        self.profile_model.profiles = value

    @property
    def current_profile_name(self):
        return self.profile_model.current_name

    @current_profile_name.setter
    def current_profile_name(self, value):
        self.profile_model.current_name = str(value)

    @property
    def worker(self):
        controller = getattr(self, "run_controller", None)
        return controller.worker if controller else None

    def __init__(self, base_dir=None, defer_runtime=False):
        super().__init__()
        application = QApplication.instance()
        current_theme_scale = (
            float(application.property("_fukua_ui_scale") or 1.0)
            if application is not None
            else 1.0
        )
        if application is not None and (
            not application.property("_fukua_modern_theme")
            or abs(current_theme_scale - 1.0) > 0.001
        ):
            apply_modern_theme(application, 1.0)
        self.base_dir = os.path.abspath(base_dir or get_base_dir())
        self.credentials = CredentialStore(self.base_dir)
        set_log_base_dir(self.base_dir)
        self.session_guard = ApplicationSession(self.base_dir).start()
        self.setWindowTitle(f"{PRODUCT_NAME} {APP_VERSION}")
        self.resize(1040, 760)
        self.setMinimumSize(760, 620)
        self.defer_runtime = bool(defer_runtime)
        self.runtime_ready = not self.defer_runtime
        self.runtime_init_in_progress = False
        self.runtime_init_bridge = RuntimeInitBridge(self)
        self.runtime_init_bridge.completed.connect(self.on_runtime_initialized)
        self._runtime_init_thread = None
        self.delete_hover_timer = QTimer(self)
        self.delete_hover_timer.setSingleShot(True)
        self.delete_hover_timer.timeout.connect(
            self.refresh_task_list_delete_hover
        )
        self.engine = RPAEngine(
            base_dir=self.base_dir, defer_backends=self.defer_runtime
        )
        self.ui_performance = PerformanceMetrics()
        self.mapping_backend = None
        self.run_controller = RunController(self.engine, self)
        self.run_controller.completed.connect(self.on_finish)
        self.run_controller.failed.connect(self.on_worker_error)
        
        self.config_path = os.path.join(self.base_dir, "config.ini")
        self.profile_backup_path = os.path.join(self.base_dir, "profiles_backup.json")
        self.settings = QSettings(self.config_path, QSettings.IniFormat)
        self._profiles_save_signature = ""
        self._profiles_save_in_progress = False
        self._profiles_persistence_blocked = False
        self._profiles_block_warning_logged = False
        self._config_recovery_message = (
            "检测到上一次程序没有正常退出。方案会从自动保存内容继续加载；"
            "如有异常，可从配置目录中的历史备份恢复。"
            if self.session_guard.previous_unclean
            else ""
        )
        self.ui_scale = 1.0
        self.recorder_ui = None
        self.all_points_preview = None
        self.click_indicator_overlays = []
        
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        self.profile_model = ProfileCollection()
        self.is_switching_profile = True 
        
        self.hotkey_start_parsed = parse_hotkey_text("F9")
        self.hotkey_stop_parsed = parse_hotkey_text("F10")
        self.hotkey_start_vk = self.hotkey_start_parsed["vk"]
        self.hotkey_stop_vk = self.hotkey_stop_parsed["vk"]
        self.global_hotkeys_registered = False
        self.hotkey_poll_pressed = set()
        self.current_process = None
        self.running_overlay = None
        self.task_clipboard = None
        self.undo_stack = []
        self.redo_stack = []
        self.restoring_history = False
        self.advanced_setting_widgets = []
        self.mapping_hotkey_ids = {}
        self.mapping_poll_pressed = set()
        self.key_mapping_hook = None
        self.mapping_hook_hotkeys = set()
        self.mapping_pickers = {}
        self.dodge_pickers = {}
        self.mapping_inspector_dialogs = set()
        self._bulk_mapping_update = False
        self.start_in_progress = False
        self.debug_paused_step = 0
        self.debug_variable_values = {}
        self.integrity_worker = None
        self._close_after_worker = False
        self._close_state_saved = False
        self.task_config_dialogs = set()
        if HAS_PSUTIL:
            try:
                self.current_process = psutil.Process()
                psutil.cpu_percent(interval=None)
                self.current_process.cpu_percent(interval=None)
            except Exception:
                self.current_process = None
            
        central = QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)
        
        # ================= 顶部方案管理 =================
        profile_bar = QFrame()
        profile_bar.setObjectName("profileBar")
        profile_layout = QHBoxLayout(profile_bar)
        profile_layout.setContentsMargins(10, 6, 8, 6)
        profile_layout.setSpacing(6)

        brand_label = QLabel(PRODUCT_NAME)
        brand_label.setProperty("role", "title")
        profile_layout.addWidget(brand_label)
        profile_layout.addSpacing(10)
        profile_caption = QLabel("方案")
        profile_caption.setProperty("role", "muted")
        profile_layout.addWidget(profile_caption)
        self.profile_combo = NoWheelComboBox()
        self.profile_combo.setMinimumWidth(170)
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        profile_layout.addWidget(self.profile_combo)
        
        new_prof_btn = QPushButton("新建")
        new_prof_btn.setProperty("variant", "tonal")
        new_prof_btn.clicked.connect(self.create_new_profile)
        profile_layout.addWidget(new_prof_btn)
        
        rename_prof_btn = QPushButton("重命名")
        rename_prof_btn.setProperty("variant", "ghost")
        rename_prof_btn.clicked.connect(self.rename_current_profile)
        profile_layout.addWidget(rename_prof_btn)
        
        del_prof_btn = QPushButton("删除")
        del_prof_btn.setProperty("variant", "dangerGhost")
        del_prof_btn.clicked.connect(self.delete_current_profile)
        profile_layout.addWidget(del_prof_btn)
        
        prof_up_btn = QPushButton("")
        prof_up_btn.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
        prof_up_btn.setProperty("iconOnly", True)
        prof_up_btn.setProperty("variant", "ghost")
        prof_up_btn.setToolTip("方案上移")
        prof_up_btn.clicked.connect(self.move_profile_up)
        profile_layout.addWidget(prof_up_btn)
        
        prof_down_btn = QPushButton("")
        prof_down_btn.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        prof_down_btn.setProperty("iconOnly", True)
        prof_down_btn.setProperty("variant", "ghost")
        prof_down_btn.setToolTip("方案下移")
        prof_down_btn.clicked.connect(self.move_profile_down)
        profile_layout.addWidget(prof_down_btn)
        
        profile_layout.addStretch()

        settings_btn = QPushButton("设置")
        settings_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        settings_btn.setProperty("variant", "ghost")
        settings_btn.setToolTip("打开全局设置、方案导入导出和配置目录")
        settings_btn.clicked.connect(self.show_settings_dialog)
        profile_layout.addWidget(settings_btn)
        
        main_layout.addWidget(profile_bar)
        
        command_bar = QFrame()
        command_bar.setObjectName("commandBar")
        top_bar = QHBoxLayout(command_bar)
        top_bar.setContentsMargins(8, 6, 8, 6)
        top_bar.setSpacing(6)
        add_btn = QPushButton("新增步骤")
        add_btn.setProperty("variant", "primary")
        add_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        add_btn.clicked.connect(lambda: self.add_row())
        top_bar.addWidget(add_btn)

        insert_btn = QPushButton("插入步骤")
        insert_btn.setProperty("variant", "ghost")
        insert_btn.setToolTip("在当前选中步骤前插入一条新指令")
        insert_btn.clicked.connect(self.insert_row_before_selected)
        top_bar.addWidget(insert_btn)

        redo_btn = QPushButton("重做")
        redo_btn.setIcon(self.style().standardIcon(QStyle.SP_ArrowForward))
        redo_btn.setProperty("variant", "ghost")
        redo_btn.setToolTip("恢复刚撤销的步骤列表操作 (Ctrl+Y)")
        redo_btn.clicked.connect(self.redo_task_change)
        top_bar.addWidget(redo_btn)
        
        record_btn = QPushButton("● 操作录制")
        record_btn.setProperty("variant", "tonal")
        record_btn.clicked.connect(self.start_recording)
        top_bar.addWidget(record_btn)
        
        self.region_btn = QPushButton("识别区域")
        self.region_btn.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        self.region_btn.setProperty("variant", "tonal")
        self.region_btn.clicked.connect(self.open_region_selector)
        top_bar.addWidget(self.region_btn)

        self.region_help_btn = HelpBtn("【设定识别区域】\n如CPU占用较高，务必使用此功能。\n左键拖拽框选一个或多个区域，右键完成。\n多区域适合目标分散在几个相距较远的小区域，且这些区域总面积只占屏幕很小一部分的情况。\n如果几个区域相隔很近，通常框成一个较大的单区域更快、更稳定。")
        self.region_help_btn.setProperty("helpFor", "recognitionRegion")
        top_bar.addWidget(self.region_help_btn)

        self.preview_points_btn = QPushButton("预览坐标点")
        self.preview_points_btn.setProperty("variant", "ghost")
        self.preview_points_btn.setToolTip("在屏幕上预览当前脚本中所有直接坐标点击点；仅统计坐标点击，不识别图片。")
        self.preview_points_btn.clicked.connect(self.show_all_coordinate_click_preview)
        top_bar.addWidget(self.preview_points_btn)
        script_check_btn = QPushButton("")
        script_check_btn.setIcon(
            self.style().standardIcon(QStyle.SP_DialogApplyButton)
        )
        script_check_btn.setFixedWidth(34)
        script_check_btn.setProperty("iconOnly", True)
        script_check_btn.setProperty("variant", "ghost")
        script_check_btn.setToolTip("检查步骤语法、不可到达步骤和潜在循环，不执行脚本")
        script_check_btn.clicked.connect(self.show_script_check_report)
        top_bar.addWidget(script_check_btn)
        self.breakpoint_toggle_btn = QPushButton("")
        self.breakpoint_toggle_btn.setIcon(
            self.style().standardIcon(QStyle.SP_DialogNoButton)
        )
        self.breakpoint_toggle_btn.setFixedWidth(34)
        self.breakpoint_toggle_btn.setProperty("iconOnly", True)
        self.breakpoint_toggle_btn.setProperty("variant", "ghost")
        self.breakpoint_toggle_btn.setToolTip(
            "为当前选中步骤添加或清除调试断点 (F8)"
        )
        self.breakpoint_toggle_btn.clicked.connect(self.toggle_selected_breakpoint)
        top_bar.addWidget(self.breakpoint_toggle_btn)
        self.single_step_btn = QPushButton("")
        self.single_step_btn.setIcon(
            self.style().standardIcon(QStyle.SP_MediaSkipForward)
        )
        self.single_step_btn.setFixedWidth(34)
        self.single_step_btn.setProperty("iconOnly", True)
        self.single_step_btn.setProperty("variant", "ghost")
        self.single_step_btn.setToolTip("只执行当前选中步骤一次，不执行循环和跳转")
        self.single_step_btn.clicked.connect(self.run_selected_step_once)
        top_bar.addWidget(self.single_step_btn)
        top_bar.addStretch()
        main_layout.addWidget(command_bar)

        # ================= 设置窗口 =================
        self.settings_dialog = FloatingSettingsDialog(
            self.settings, "settings_dialog_geometry", f"{PRODUCT_NAME} 设置", (920, 700)
        )
        settings_outer = QVBoxLayout(self.settings_dialog)
        settings_outer.setContentsMargins(12, 12, 12, 12)
        settings_outer.setSpacing(8)

        settings_actions = QFrame()
        settings_actions.setObjectName("commandBar")
        settings_action_bar = QVBoxLayout(settings_actions)
        settings_action_bar.setContentsMargins(8, 6, 8, 6)
        settings_action_bar.setSpacing(0)
        self.settings_action_row = ResponsiveRow(
            horizontal_spacing=6,
            vertical_spacing=6,
        )
        save_btn = fit_text_button(QPushButton("导出方案"), 76)
        save_btn.setProperty("variant", "primary")
        save_btn.clicked.connect(self.save)
        self.settings_action_row.add_widget(save_btn)
        full_save_btn = fit_text_button(QPushButton("全量导出"), 76)
        full_save_btn.setProperty("variant", "tonal")
        full_save_btn.setToolTip("导出当前方案和其中引用的图片，生成可迁移的zip包。")
        full_save_btn.clicked.connect(self.save_full_package)
        self.settings_action_row.add_widget(full_save_btn)
        load_btn = fit_text_button(QPushButton("导入方案"), 76)
        load_btn.setProperty("variant", "ghost")
        load_btn.clicked.connect(self.load)
        self.settings_action_row.add_widget(load_btn)
        open_dir_btn = fit_text_button(QPushButton("打开配置目录"), 104)
        open_dir_btn.setProperty("variant", "ghost")
        open_dir_btn.clicked.connect(self.open_config_dir)
        self.settings_action_row.add_widget(open_dir_btn)
        diagnostic_btn = fit_text_button(QPushButton("导出诊断"), 76)
        diagnostic_btn.setProperty("variant", "ghost")
        diagnostic_btn.setToolTip(
            "离线导出系统依赖、最近一次运行耗时和界面刷新统计；不会联网，也不导出脚本内容。"
        )
        diagnostic_btn.clicked.connect(self.export_diagnostic_report)
        self.settings_action_row.add_widget(diagnostic_btn)
        self.integrity_btn = fit_text_button(QPushButton("校验程序"), 76)
        self.integrity_btn.setProperty("variant", "ghost")
        self.integrity_btn.setToolTip(
            "后台核对发布包文件是否缺失或损坏；此功能不联网，也不能代替作者数字签名。"
        )
        self.integrity_btn.clicked.connect(self.verify_installed_payload)
        self.settings_action_row.add_widget(self.integrity_btn)
        settings_action_bar.addWidget(self.settings_action_row)
        settings_outer.addWidget(settings_actions)

        settings_mode_row = QHBoxLayout()
        settings_mode_row.setContentsMargins(2, 0, 2, 0)
        settings_mode_row.addWidget(QLabel("设置视图:"))
        self.settings_mode_combo = NoWheelComboBox()
        self.settings_mode_combo.addItem("简易模式（推荐）", "simple")
        self.settings_mode_combo.addItem("高级模式", "advanced")
        saved_settings_mode = str(
            self.settings.value("settings_view_mode", "simple") or "simple"
        )
        mode_index = self.settings_mode_combo.findData(saved_settings_mode)
        self.settings_mode_combo.setCurrentIndex(max(0, mode_index))
        fit_combo_to_contents(self.settings_mode_combo)
        self.settings_mode_combo.currentIndexChanged.connect(
            self.apply_settings_mode
        )
        settings_mode_row.addWidget(self.settings_mode_combo)
        self.advanced_settings_notice = QLabel("")
        self.advanced_settings_notice.setProperty("role", "statusWarn")
        settings_mode_row.addWidget(self.advanced_settings_notice)
        settings_mode_row.addStretch()
        settings_outer.addLayout(settings_mode_row)

        self.fast_response_tip = QFrame()
        self.fast_response_tip.setObjectName("onboardingNotice")
        fast_response_layout = QHBoxLayout(self.fast_response_tip)
        fast_response_layout.setContentsMargins(12, 8, 8, 8)
        fast_response_layout.setSpacing(10)
        fast_response_text = QLabel(
            "快速反应提示：用于抢答、打地鼠等场景时，可尝试将“间隔”设为 0，"
            "并适当降低“识别频率”；如果目标长时间未出现后响应变慢，可关闭"
            "“自适应降频”。数值越低，CPU 占用可能越高。"
        )
        fast_response_text.setWordWrap(True)
        fast_response_layout.addWidget(fast_response_text, 1)
        fast_response_dismiss = fit_text_button(QPushButton("知道了"), 68)
        fast_response_dismiss.setProperty("variant", "ghost")
        fast_response_dismiss.clicked.connect(self.dismiss_fast_response_tip)
        fast_response_layout.addWidget(fast_response_dismiss)
        self.fast_response_tip.hide()
        settings_outer.addWidget(self.fast_response_tip)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_body = QWidget()
        settings_body.setObjectName("settingsBody")
        settings_content_layout = QVBoxLayout(settings_body)
        settings_content_layout.setContentsMargins(2, 2, 2, 2)
        settings_content_layout.setSpacing(4)
        settings_scroll.setWidget(settings_body)
        settings_outer.addWidget(settings_scroll)

        settings_close_btns = QDialogButtonBox(QDialogButtonBox.Close)
        settings_close_btns.button(QDialogButtonBox.Close).setText("关闭")
        settings_close_btns.rejected.connect(self.close_settings_dialog)
        settings_close_btns.button(QDialogButtonBox.Close).clicked.connect(self.close_settings_dialog)
        settings_outer.addWidget(settings_close_btns)

        # ================= 核心折叠设置区 =================
        # 1. 识别配置
        g1 = CollapsibleSection("全局识别配置")
        gl1_wrap = QVBoxLayout()
        recognition_settings_row = ResponsiveRow()
        self.conf_edit = QLineEdit("0.8"); self.conf_edit.setFixedWidth(70)
        recognition_settings_row.add_group(
            "相似度:", self.conf_edit,
            HelpBtn("【相似度 (0.1 - 1.0)】\n数值越低：越容易匹配，但极易导致乱点误触。\n数值越高：越精确。")
        )
        self.gray_chk = QCheckBox("全局灰度匹配 (极速)"); self.gray_chk.setChecked(True)
        recognition_settings_row.add_group(
            self.gray_chk,
            HelpBtn("【灰度匹配】\n开启后极快且省CPU。如果两张图形状一样颜色不同，请关闭！")
        )
        self.scale_min = QLineEdit("0.8"); self.scale_min.setFixedWidth(70)
        self.scale_max = QLineEdit("1.2"); self.scale_max.setFixedWidth(70)
        recognition_settings_row.add_group(
            "缩放范围:", self.scale_min, "至", self.scale_max,
            HelpBtn("【缩放范围】\n程序启动时会预先生成缩放模板缓存。建议不要超过 0.8 - 2.0。\n为防止内存耗尽，单张图片最多生成 61 个缩放档位，缩放值最高为 5.0。")
        )
        self.scale_step = QLineEdit("0.05"); self.scale_step.setFixedWidth(70)
        recognition_settings_row.add_group(
            "步长:", self.scale_step,
            HelpBtn("【缩放步长】\n默认值 0.05，调低会增加CPU压力。")
        )
        self.native_core_chk = QCheckBox("启用DLL原生识别")
        self.native_core_chk.setChecked(True)
        self.native_core_chk.setToolTip(
            f"开启后优先使用内置 {NATIVE_CORE_DLL_NAME} 做图片识别；"
            "不可用或不适合时自动回退到 OpenCV/Python 识别。"
        )
        native_core_group = recognition_settings_row.add_group(
            self.native_core_chk,
            HelpBtn("【DLL原生识别】\n开启后，图片点击/悬停会优先尝试使用内置 C++ DLL 识别核心，通常可降低部分识别场景的 CPU 压力并提高速度。\n如果遇到兼容性问题、识别结果异常，或想对比旧版效果，可以关闭；关闭后完全使用原来的 OpenCV/Python 识别路径。\nDLL 加载失败时会自动回退，不会影响脚本启动。")
        )
        self.advanced_setting_widgets.append(native_core_group)
        self.native_parallel_combo = NoWheelComboBox()
        self.native_parallel_combo.addItem("自动（推荐）", "auto")
        self.native_parallel_combo.addItem("关闭（单线程）", "off")
        self.native_parallel_combo.addItem("强制多核", "force")
        fit_combo_to_contents(self.native_parallel_combo)
        native_parallel_width = self.native_parallel_combo.sizeHint().width()
        self.native_parallel_combo.setMinimumWidth(native_parallel_width)
        self.native_parallel_combo.setMaximumWidth(native_parallel_width)
        native_parallel_group = recognition_settings_row.add_group(
            "原生多核:", self.native_parallel_combo,
            HelpBtn("【原生多核】\n仅在启用 DLL 原生识别时生效。\n自动（推荐）：根据缩放档位、识别区域和计算量动态使用最多 8 个线程，避免 CPU 长时间满载。\n关闭（单线程）：最省调度开销，适合很小的识别区域或排查兼容问题。\n强制多核：始终尽量使用多核，可能加快大范围、多缩放识别，也可能提高瞬时 CPU 占用。")
        )
        self.advanced_setting_widgets.append(native_parallel_group)
        self.native_scale_hint_chk = QCheckBox("启用缩放记忆")
        self.native_scale_hint_chk.setChecked(True)
        native_scale_hint_group = recognition_settings_row.add_group(
            self.native_scale_hint_chk,
            HelpBtn("【缩放记忆】\n仅对“快速一个”模式的搜索顺序生效。程序会统计同一图片在本次软件启动期间成功命中的倍率，并优先检查常用倍率；优先倍率未命中时仍会在同一截图上搜索完整范围。\n“全部匹配”始终搜索全部缩放档位。关闭软件后自动学习记录会清空。")
        )
        self.advanced_setting_widgets.append(native_scale_hint_group)
        gl1_wrap.addWidget(recognition_settings_row)
        g1.set_content_layout(gl1_wrap)
        settings_content_layout.addWidget(g1)

        self.scale_memory_section = CollapsibleSection(
            "缩放记忆（图片识别加速）", expanded=False
        )
        g_scale_memory = self.scale_memory_section
        scale_memory_rows = QVBoxLayout()
        scale_memory_row = ResponsiveRow()
        self.scale_memory_tier_combo = NoWheelComboBox()
        self.scale_memory_tier_combo.addItem("稳妥", "conservative")
        self.scale_memory_tier_combo.addItem("均衡（推荐）", "balanced")
        self.scale_memory_tier_combo.addItem("积极", "aggressive")
        fit_combo_to_contents(self.scale_memory_tier_combo)
        scale_memory_row.add_group(
            "自动策略:", self.scale_memory_tier_combo,
            HelpBtn("【自动策略】\n三个档位不会对应固定数量，而是影响算法选择历史容量和优先倍率数量的倾向。\n稳妥：更少的优先倍率、更短的历史；均衡：兼顾速度与适应变化；积极：保留更多历史并覆盖更多常见倍率。")
        )
        self.scale_memory_manual_edit = QLineEdit()
        self.scale_memory_manual_edit.setPlaceholderText("例如 0.8, 1.0, 1.2")
        self.scale_memory_manual_edit.setMinimumWidth(180)
        scale_memory_row.add_group(
            "手动优先倍率:", self.scale_memory_manual_edit,
            HelpBtn("【手动优先倍率】\n可填写多个倍率，用逗号或空格分隔，最多 12 个。手动倍率会排在自动学习结果之前；不在当前步骤缩放范围/步长中的值会自动忽略。\n图片点击的详细或完全日志会显示本次命中的准确缩放倍率，可直接参考日志填写。")
        )
        scale_memory_rows.addWidget(scale_memory_row)

        custom_memory_row = ResponsiveRow()
        self.scale_memory_custom_chk = QCheckBox("自定义记忆容量")
        custom_memory_row.add_group(
            self.scale_memory_custom_chk,
            HelpBtn("【自定义记忆容量】\n默认关闭，由算法根据缩放档位数量、已观察倍率和所选策略动态决定。\n只有熟悉脚本行为时再开启；开启后才能手动修改下面两项。")
        )
        self.scale_memory_preferred_spin = NoWheelSpinBox()
        self.scale_memory_preferred_spin.setRange(1, 12)
        self.scale_memory_preferred_spin.setValue(3)
        self.scale_memory_preferred_spin.setSuffix(" 个")
        custom_memory_row.add_group(
            "学习优先倍率上限:", self.scale_memory_preferred_spin,
            HelpBtn("只限制算法从历史中选出的倍率数量，不包含手动优先倍率。")
        )
        self.scale_memory_history_spin = NoWheelSpinBox()
        self.scale_memory_history_spin.setRange(8, 512)
        self.scale_memory_history_spin.setValue(64)
        self.scale_memory_history_spin.setSuffix(" 次")
        custom_memory_row.add_group(
            "历史记录上限:", self.scale_memory_history_spin,
            HelpBtn("最多保留多少次成功命中记录。记录只保存在本次软件启动期间，不写入磁盘。")
        )
        self.scale_memory_clear_btn = QPushButton("清除本次记忆")
        fit_text_button(self.scale_memory_clear_btn, 104)
        self.scale_memory_clear_btn.setProperty("variant", "ghost")
        self.scale_memory_clear_btn.setToolTip("清空本次软件启动期间自动学习到的缩放倍率；手动设置不会被清除。")
        custom_memory_row.add_group(self.scale_memory_clear_btn)
        scale_memory_rows.addWidget(custom_memory_row)

        self.scale_memory_status_label = QLabel(
            "本次启动尚未学习到缩放倍率；首次成功识别后会显示当前优先倍率和算法历史上限。"
        )
        self.scale_memory_status_label.setWordWrap(True)
        self.scale_memory_status_label.setProperty("role", "muted")
        scale_memory_rows.addWidget(self.scale_memory_status_label)
        g_scale_memory.set_content_layout(scale_memory_rows)
        settings_content_layout.addWidget(g_scale_memory)
        self.advanced_setting_widgets.append(g_scale_memory)
        
        # 2. 避让设置
        self.dodge_section = CollapsibleSection("避让设置")
        g_dodge = self.dodge_section
        dodge_rows = QVBoxLayout()
        dodge_settings_row = ResponsiveRow()
        self.dodge_x1 = QLineEdit("100"); self.dodge_x1.setFixedWidth(70)
        self.dodge_y1 = QLineEdit("100"); self.dodge_y1.setFixedWidth(70)
        self.dodge_pick1_btn = fit_text_button(QPushButton("取点"), 64)
        self.dodge_pick1_btn.setProperty("variant", "tonal")
        self.dodge_pick1_btn.setToolTip("左键单击屏幕位置，直接填入避让坐标1；右键取消。")
        self.dodge_pick1_btn.clicked.connect(
            lambda: self.start_dodge_point_pick(1)
        )
        dodge_settings_row.add_group(
            "坐标1 X:", self.dodge_x1, "Y:", self.dodge_y1,
            self.dodge_pick1_btn,
        )
        self.dodge_x2 = QLineEdit("200"); self.dodge_x2.setFixedWidth(70)
        self.dodge_y2 = QLineEdit("100"); self.dodge_y2.setFixedWidth(70)
        self.dodge_pick2_btn = fit_text_button(QPushButton("取点"), 64)
        self.dodge_pick2_btn.setProperty("variant", "tonal")
        self.dodge_pick2_btn.setToolTip("左键单击屏幕位置，直接填入避让坐标2；右键取消。")
        self.dodge_pick2_btn.clicked.connect(
            lambda: self.start_dodge_point_pick(2)
        )
        dodge_settings_row.add_group(
            "坐标2 X:", self.dodge_x2, "Y:", self.dodge_y2,
            self.dodge_pick2_btn,
        )
        self.dodge_chk = QCheckBox("启用避让")
        self.double_dodge_chk = QCheckBox("二段避让")
        dodge_settings_row.add_group(self.dodge_chk, self.double_dodge_chk)
        self.dbl_wait = QLineEdit("0.015"); self.dbl_wait.setFixedWidth(70)
        dodge_settings_row.add_group(
            "二段间隔:", self.dbl_wait,
            HelpBtn("【二段避让间隔】\n间隔时间，单位：秒")
        )
        self.dodge_click_combo = NoWheelComboBox()
        self.dodge_click_combo.addItem("仅移动（默认）", "none")
        self.dodge_click_combo.addItem("最终点左键单击", "left")
        self.dodge_click_combo.addItem("最终点右键单击", "right")
        fit_combo_to_contents(self.dodge_click_combo)
        dodge_settings_row.add_group(
            "避让后操作:", self.dodge_click_combo,
            HelpBtn(
                "【避让后操作】\n默认只移动鼠标。选择单击后，程序会在完成避让移动后，"
                "在最终避让点额外点击一次。\n启用二段避让时只点击坐标2，否则点击坐标1。"
                "请把避让点放在点击不会产生副作用的安全位置。"
            ),
        )
        dodge_rows.addWidget(dodge_settings_row)
        g_dodge.set_content_layout(dodge_rows)
        settings_content_layout.addWidget(g_dodge)
        
        # 3. 速度控制
        g2 = CollapsibleSection("速度控制 (0为极速)")
        speed_rows = QVBoxLayout()
        speed_settings_row = ResponsiveRow()
        self.move_spd = QLineEdit("0.0"); self.move_spd.setFixedWidth(70)
        speed_settings_row.add_group(
            "移动(s):", self.move_spd, HelpBtn("【移动耗时】 0.0=瞬移")
        )
        self.click_hld = QLineEdit("0.04"); self.click_hld.setFixedWidth(70)
        speed_settings_row.add_group(
            "按住(s):", self.click_hld,
            HelpBtn("【按住时长】 建议0.04-0.08模拟真人点击")
        )
        self.settle = QLineEdit("0.5"); self.settle.setFixedWidth(70)
        speed_settings_row.add_group(
            "间隔(s):", self.settle,
            HelpBtn("【步间隔】\n每一步执行完毕后等待多久再进入下一步；0 表示立刻执行下一步。\n优先级低于“等待”指令：如果当前步骤是等待，或下一步实际要执行的是等待，程序会自动屏蔽等待指令前后的全局间隔。\n例如：第1步点击、第2步等待3秒、第3步点击，则第1步后不会额外加间隔，第2步后也不会额外加间隔，确保第1步后准确等待3秒再执行第3步。")
        )
        self.timeout = QLineEdit("0.0"); self.timeout.setFixedWidth(70)
        speed_settings_row.add_group(
            "单步超时(s):", self.timeout,
            HelpBtn("【单步超时】\n0 表示不设置等待上限。\n未开启“超时急停”时：达到超时会把本步骤视为失败，再按小齿轮里的失败跳过/跳至规则处理。\n开启“超时急停”时：达到超时会立即停止整个脚本和后续循环。")
        )
        self.timeout_stop_chk = QCheckBox("超时急停")
        self.timeout_stop_chk.setToolTip("开启后，任意步骤达到单步超时都会立即停止全部循环，不再执行后续步骤。")
        speed_settings_row.add_group(
            self.timeout_stop_chk,
            HelpBtn("【超时急停】\n开启后，任意步骤达到单步超时都会立即停止全部循环，不再执行后续步骤。")
        )
        self.detect_delay = QLineEdit("0.1"); self.detect_delay.setFixedWidth(70)
        speed_settings_row.add_group(
            "识别频率(s):", self.detect_delay,
            HelpBtn("【识别频率】\n每次执行识别/重试前先等待这么多秒，用于降低CPU占用。\n0 表示不额外等待，速度最快但CPU压力更高。")
        )
        self.adaptive_backoff_chk = QCheckBox("自适应降频")
        self.adaptive_backoff_chk.setChecked(True)
        self.adaptive_backoff_chk.setToolTip("连续找不到同一目标时自动逐步放慢重试；找到目标后自动恢复。")
        speed_settings_row.add_group(
            self.adaptive_backoff_chk,
            HelpBtn("【自适应降频】\n开启后，如果某张图连续多次找不到，程序会在识别频率之外额外等待一点时间，避免CPU一直满速空转。\n找到目标后会自动清零恢复速度。")
        )
        self.scene_wake_chk = QCheckBox("画面变化唤醒")
        self.scene_wake_chk.setChecked(True)
        self.scene_wake_sensitivity_combo = NoWheelComboBox()
        self.scene_wake_sensitivity_combo.addItem("稳妥", "conservative")
        self.scene_wake_sensitivity_combo.addItem("均衡（推荐）", "balanced")
        self.scene_wake_sensitivity_combo.addItem("灵敏", "sensitive")
        fit_combo_to_contents(self.scene_wake_sensitivity_combo)
        scene_wake_group = speed_settings_row.add_group(
            self.scene_wake_chk,
            self.scene_wake_sensitivity_combo,
            HelpBtn(
                "【画面变化唤醒】\n仅在“自适应降频”产生的额外等待期间生效。"
                "程序优先使用 DLL 的 DXGI 变化通知，不复制整张屏幕；环境不支持时自动回退到低分辨率分块指纹。"
                "发现变化后，会优先探测常用倍率和少量轮换倍率，"
                "随后仍保留原本的完整范围识别，因此不会因为开启本功能而漏掉其他倍率。\n"
                "“灵敏”响应更积极，也更容易被动画或状态提示唤醒；不适用于“全部匹配”和同点点击上限。"
            ),
        )
        self.advanced_setting_widgets.append(scene_wake_group)
        self.playback_speed = QLineEdit("1.0"); self.playback_speed.setFixedWidth(70)
        speed_settings_row.add_group(
            "播放倍速:", self.playback_speed,
            HelpBtn("【播放倍速】 用于缩放录制脚本中的等待时间，> 1 为加速，< 1 为减速")
        )
        speed_rows.addWidget(speed_settings_row)
        g2.set_content_layout(speed_rows)
        settings_content_layout.addWidget(g2)

        # 4. 多目标点击
        g_multi = CollapsibleSection("多目标点击")
        multi_settings_row = ResponsiveRow()
        self.multi_mode_combo = NoWheelComboBox()
        self.multi_mode_combo.addItems(["快速一个", "全部匹配"])
        fit_combo_to_contents(self.multi_mode_combo)
        self.multi_mode_combo.currentTextChanged.connect(self.update_multi_target_ui)
        multi_settings_row.add_group(
            "目标模式:", self.multi_mode_combo,
            HelpBtn("【目标模式】\n快速一个：走最快路径，找到第一个达到相似度阈值的位置后立即点击；不保证它是全屏及全部缩放结果中相似度最高的位置，适合普通单目标脚本。\n全部匹配：执行更完整的峰值搜索，一次找出所有超过相似度阈值的目标并逐个点击，CPU压力更高。")
        )
        self.multi_order_combo = NoWheelComboBox()
        self.multi_order_combo.addItems(["从上到下", "从左到右", "从右到左", "距离鼠标最近优先", "随机顺序"])
        fit_combo_to_contents(self.multi_order_combo)
        multi_settings_row.add_group(
            "点击顺序:", self.multi_order_combo,
            HelpBtn("【点击顺序】\n仅在目标模式为“全部匹配”时生效。程序会先识别本轮截图中的全部目标，再按此顺序点击。")
        )
        multi_layout = QVBoxLayout()
        multi_layout.addWidget(multi_settings_row)
        g_multi.set_content_layout(multi_layout)
        settings_content_layout.addWidget(g_multi)
        
        # 5. 系统设置
        g3 = CollapsibleSection("系统设置")
        gl3_main = QVBoxLayout()
        system_settings_row = ResponsiveRow()
        system_settings_row.setProperty("rowRole", "systemSettings")
        self.system_settings_row = system_settings_row

        self.hotkey_start_edit = QLineEdit("F9")
        self.hotkey_start_edit.setMinimumWidth(120)
        self.hotkey_start_edit.setToolTip("可输入 F9、Ctrl+F9、Ctrl+Alt+S 等；启动/停止不允许使用裸字母或裸数字。")
        self.hotkey_start_edit.editingFinished.connect(self.update_hotkeys)
        self.start_key_btn = fit_text_button(QPushButton("录入"), 68)
        self.start_key_btn.clicked.connect(self.capture_start_hotkey)

        self.hotkey_stop_edit = QLineEdit("F10")
        self.hotkey_stop_edit.setMinimumWidth(120)
        self.hotkey_stop_edit.setToolTip("可输入 F10、Ctrl+F10、Ctrl+Alt+Q 等；停止热键建议使用不易误触的组合键。")
        self.hotkey_stop_edit.editingFinished.connect(self.update_hotkeys)
        self.stop_key_btn = fit_text_button(QPushButton("录入"), 68)
        self.stop_key_btn.clicked.connect(self.capture_stop_hotkey)
        hotkey_help = "【启动/停止热键】\n可以直接点“录入”后按下想用的按键或组合键。\n为避免打字时误启动脚本，启动/停止不接受裸字母、裸数字、空格、回车这类容易误触的单键；需要用 Ctrl/Alt/Shift/Win 组合，或使用 F1-F12 等功能键。\n裸字母/数字建议只用于下方“按键映射模式”。"
        system_settings_row.add_group(
            "启动热键:", self.hotkey_start_edit, self.start_key_btn, HelpBtn(hotkey_help)
        )
        system_settings_row.add_group(
            "停止热键:", self.hotkey_stop_edit, self.stop_key_btn, HelpBtn(hotkey_help)
        )

        self.tm_failsafe = QCheckBox("任务管理器急停"); self.tm_failsafe.setChecked(True)
        self.tr_failsafe = QCheckBox("右上角急停"); self.tr_failsafe.setChecked(True)
        self.key_failsafe = QCheckBox("ESC/中键急停"); self.key_failsafe.setChecked(True)
        system_settings_row.add_group(
            self.tm_failsafe, self.tr_failsafe, self.key_failsafe,
            HelpBtn("【急停方式】\n可同时启用多种急停方式。任务管理器急停用于窗口失去响应时辅助停止；右上角和 ESC/中键用于运行期间快速中止。")
        )

        self.log_level_combo = NoWheelComboBox()
        for mode in (
            LOG_MODE_SIMPLE,
            LOG_MODE_DETAILED,
            LOG_MODE_COMPLETE,
            LOG_MODE_CUSTOM,
        ):
            self.log_level_combo.addItem(LOG_MODE_LABELS[mode], mode)
        fit_combo_to_contents(self.log_level_combo)
        self._log_control_sync = False
        self._custom_log_categories = set(DEFAULT_CUSTOM_LOG_CATEGORIES)
        self.log_content_menu = PersistentActionMenu(self)
        self.log_content_menu.setToolTipsVisible(True)
        self.log_critical_action = self.log_content_menu.addAction(
            "错误、急停和严重警告（始终输出）"
        )
        self.log_critical_action.setCheckable(True)
        self.log_critical_action.setChecked(True)
        self.log_critical_action.setEnabled(False)
        self.log_category_actions = {}
        for spec in LOG_CATEGORY_SPECS:
            action = self.log_content_menu.addAction(spec.label)
            action.setCheckable(True)
            action.setToolTip(spec.description)
            action.toggled.connect(
                lambda _checked, key=spec.key: self.on_log_category_toggled(key)
            )
            self.log_category_actions[spec.key] = action
        self.log_content_menu.addSeparator()
        for mode in (
            LOG_MODE_SIMPLE,
            LOG_MODE_DETAILED,
            LOG_MODE_COMPLETE,
        ):
            action = self.log_content_menu.addAction(
                f"恢复为{LOG_MODE_LABELS[mode]}预设"
            )
            action.triggered.connect(
                lambda _checked=False, selected=mode: self.select_log_preset(selected)
            )
        self.log_content_btn = fit_text_button(QPushButton("内容..."), 78)
        self.log_content_btn.setMenu(self.log_content_menu)
        self.log_level_combo.currentIndexChanged.connect(
            self.on_log_mode_selected
        )
        self.apply_log_controls(
            LOG_MODE_SIMPLE, DEFAULT_CUSTOM_LOG_CATEGORIES
        )
        self.log_file_chk = QCheckBox("写入文件日志")
        self.log_ui_chk = QCheckBox("界面日志"); self.log_ui_chk.setChecked(True)
        system_settings_row.add_group(
            "日志级别:", self.log_level_combo, self.log_content_btn,
            self.log_file_chk, self.log_ui_chk,
            HelpBtn(
                "【日志输出】\n"
                "简易：只保留运行进度、步骤结果、分支、停止原因和错误，适合日常使用。\n"
                "详细：在简易内容上增加本地时间、目标/动作细节、等待信息和性能摘要，适合排查流程。\n"
                "完全：再记录运行与步骤参数、识别/截图/匹配/点击等阶段耗时、缓存与回退统计，主要用于软件调试。\n"
                "内容：逐项勾选后自动切换为自定义；菜单底部可恢复任一预设。错误、急停和严重警告始终输出。\n"
                "写入文件与界面显示可以分别关闭；完全日志信息量和界面刷新开销最大。"
            )
        )

        self.mini_chk = QCheckBox("启动时最小化")
        self.top_chk = QCheckBox("窗口置顶"); self.top_chk.stateChanged.connect(self.toggle_top_window)

        self.run_status_chk = QCheckBox("运行状态提示")
        self.run_status_chk.setChecked(True)
        self.run_status_pos_combo = NoWheelComboBox()
        self.run_status_pos_combo.addItems(["右上角", "右下角"])
        fit_combo_to_contents(self.run_status_pos_combo)
        system_settings_row.add_group(
            self.run_status_chk, "提示位置:", self.run_status_pos_combo,
            HelpBtn("【运行状态提示】\n脚本运行时在屏幕角落显示“脚本正在执行中”、当前循环、当前步骤和已运行时间。")
        )
        self.click_indicator_chk = QCheckBox("点击位置提示")
        self.click_indicator_chk.setChecked(True)
        self.click_indicator_chk.setToolTip("脚本执行点击、拖拽或悬停时，在屏幕上短暂标出实际位置。")
        system_settings_row.add_group(
            self.click_indicator_chk,
            HelpBtn("【点击位置提示】\n开启后，脚本每次点击、拖拽结束或鼠标悬停时，会在屏幕上短暂显示一个定位标记，方便确认刚刚操作了哪里。\n关闭后不显示定位标记，脚本执行逻辑不变。")
        )
        self.start_step_edit = QLineEdit("1")
        self.start_step_edit.setFixedWidth(60)
        system_settings_row.add_group(
            "从第", self.start_step_edit, "步开始",
            HelpBtn("【从第X步开始执行】\n默认 1。启动脚本后每轮循环都从这里开始；成功/失败跳至仍按列表中的实际步号计算。")
        )

        self.loop_start_round_edit = QLineEdit("1")
        self.loop_start_round_edit.setFixedWidth(60)
        self.loop_end_round_edit = QLineEdit("0")
        self.loop_end_round_edit.setFixedWidth(60)
        system_settings_row.add_group(
            "脚本从第", self.loop_start_round_edit, "次循环开始", "到第",
            self.loop_end_round_edit, "次循环停止",
            HelpBtn("【全局循环范围】\n从第几次循环开始真正执行步骤；前面的循环轮次会直接跳过。\n停止循环填 0 表示不限；填 5 表示执行到第 5 次循环后结束。\n这个设置和“从第X步开始”不同：它控制第几轮循环生效。")
        )

        self.low_power_ui_chk = QCheckBox("省电UI模式")
        self.low_power_ui_chk.setChecked(True)
        self.low_power_ui_chk.setToolTip("降低主窗口空闲刷新频率：快捷键轮询约 250ms，CPU显示约 3秒刷新一次。可减轻拖动窗口和空闲时的单核占用。")
        self.low_power_ui_chk.stateChanged.connect(self.apply_ui_performance_mode)
        system_settings_row.add_group(
            self.low_power_ui_chk,
            HelpBtn("【省电UI模式】\n只影响界面刷新和热键轮询频率，不改变脚本识别逻辑。\n资源监测选择“跟随省电模式”时，也会在 1 秒和 3 秒刷新之间切换。\n如果你感觉热键响应慢，可以关闭。")
        )
        self.cpu_refresh_combo = NoWheelComboBox()
        self.cpu_refresh_combo.addItem("跟随省电模式", "auto")
        self.cpu_refresh_combo.addItem("0.5 秒", 500)
        self.cpu_refresh_combo.addItem("1 秒", 1000)
        self.cpu_refresh_combo.addItem("2 秒", 2000)
        self.cpu_refresh_combo.addItem("3 秒", 3000)
        self.cpu_refresh_combo.addItem("5 秒", 5000)
        self.cpu_refresh_combo.addItem("关闭", 0)
        fit_combo_to_contents(self.cpu_refresh_combo)
        self.cpu_refresh_combo.currentIndexChanged.connect(
            self.apply_ui_performance_mode
        )
        cpu_refresh_group = system_settings_row.add_group(
            "资源监测:",
            self.cpu_refresh_combo,
            HelpBtn(
                "【资源监测刷新】\n控制主界面右下角 CPU 信息的刷新频率。"
                "采样使用非阻塞接口，不会等待一个完整统计周期。\n"
                "“跟随省电模式”表示普通模式每 1 秒刷新，省电模式每 3 秒刷新；"
                "选择“关闭”会停止监测定时器。"
            ),
        )
        self.advanced_setting_widgets.append(cpu_refresh_group)
        self.ui_scale_edit = QLineEdit("100")
        self.ui_scale_edit.setFixedWidth(60)
        self.ui_scale_edit.setToolTip("调整主界面、设置窗口和小齿轮窗口的字体与控件尺寸，建议范围 75-180。")
        system_settings_row.add_group(
            "界面倍率(%):", self.ui_scale_edit,
            HelpBtn("【界面倍率】\n用于适配不同分辨率或缩放习惯的显示屏。\n100 表示原始大小；例如 125 会把字体和多数按钮/输入框放大到 125%。\n倍率过大时窗口内容需要更多空间，可以手动拉大窗口。")
        )

        gl3_main.addWidget(system_settings_row)
        g3.set_content_layout(gl3_main)
        settings_content_layout.addWidget(g3)

        credential_section = CollapsibleSection("凭据库")
        credential_layout = QVBoxLayout()
        credential_row = ResponsiveRow()
        self.credential_combo = NoWheelComboBox()
        self.credential_combo.setMinimumWidth(220)
        credential_row.add_group("凭据名称:", self.credential_combo)
        credential_set_btn = QPushButton("新增 / 修改")
        credential_set_btn.setProperty("variant", "tonal")
        credential_set_btn.clicked.connect(self.edit_credential)
        credential_delete_btn = QPushButton("删除")
        credential_delete_btn.setProperty("variant", "dangerGhost")
        credential_delete_btn.clicked.connect(self.delete_credential)
        credential_row.add_group(
            credential_set_btn,
            credential_delete_btn,
            HelpBtn(
                "【凭据库】\n用于“输入秘密文本”步骤。秘密内容由 Windows DPAPI 按当前用户加密，"
                "不会写入脚本方案、全量导出包或日志。\n脚本中只保存凭据名称；换电脑后需要在新电脑重新创建同名凭据。"
            ),
        )
        credential_layout.addWidget(credential_row)
        credential_note = QLabel(
            "凭据只在当前 Windows 用户下可解密；程序不会显示或导出现有秘密内容。"
        )
        credential_note.setWordWrap(True)
        credential_note.setProperty("role", "muted")
        credential_layout.addWidget(credential_note)
        credential_section.set_content_layout(credential_layout)
        settings_content_layout.addWidget(credential_section)
        self.refresh_credential_names()

        g_map = CollapsibleSection("按键映射")
        map_main = QVBoxLayout()
        map_options_row = ResponsiveRow()
        self.mapping_mode_chk = QCheckBox("启用按键映射模式")
        self.mapping_mode_chk.setChecked(False)
        self.mapping_mode_chk.setToolTip("开启后，映射里的裸字母、裸数字、空格等单键才会被软件接管。关闭后这些裸键不会生效，也不会影响正常打字。")
        self.mapping_mode_chk.stateChanged.connect(self.refresh_hotkey_backend)
        map_options_row.add_group(
            self.mapping_mode_chk,
            HelpBtn("【按键映射模式】\n用于把 A、1、Space 这类任意单键映射成鼠标点击。\n开启后，已启用的裸键映射会在全局生效：即使软件在后台，按下该键也会替你点击并拦截这次按键。\n因此裸键只建议在专门执行映射时开启；普通启动/停止快捷键仍建议使用 Ctrl/Alt/Shift 组合或 F 键。")
        )

        self.mapping_click_mode_combo = NoWheelComboBox()
        self.mapping_click_mode_combo.addItems(["真实鼠标点击", "点击后返回原位", "后台窗口点击(实验)"])
        fit_combo_to_contents(self.mapping_click_mode_combo)
        self.mapping_click_mode_combo.currentTextChanged.connect(
            self.refresh_mapping_binding_controls
        )
        map_options_row.add_group(
            "点击方式:", self.mapping_click_mode_combo,
            HelpBtn("【映射点击方式】\n真实鼠标点击：兼容性最好，会把鼠标移动到目标点。\n点击后返回原位：先移动到目标点点击，再立刻回到触发前的鼠标位置；实际鼠标仍会瞬间移动。\n后台窗口点击(实验)：不移动鼠标，只向槽位绑定的目标窗口/控件发送点击消息。先用“取点”确定实际点击坐标，再点“选择窗口”，按提示亲自单击一次目标程序窗口中的任意位置。选窗功能只在本模式可用。目标失效时不会回退真实鼠标点击，以免误点前台窗口。\n只对部分普通窗口/控件有效；游戏、浏览器画布、DirectX 或权限更高的窗口可能无效。若权限不同，请尝试以管理员身份运行本软件。")
        )
        map_main.addWidget(map_options_row)
        self.key_mapping_rows = []
        mapping_tools_row = QHBoxLayout()
        add_mapping_btn = QPushButton("+ 添加映射")
        add_mapping_btn.setProperty("variant", "tonal")
        add_mapping_btn.clicked.connect(lambda: self.add_key_mapping_row(refresh=True))
        mapping_tools_row.addWidget(add_mapping_btn)
        mapping_tools_row.addStretch()
        map_main.addLayout(mapping_tools_row)
        self.mapping_rows_layout = QVBoxLayout()
        self.mapping_rows_layout.setSpacing(7)
        map_main.addLayout(self.mapping_rows_layout)
        for _ in range(HOTKEY_MAPPING_COUNT):
            self.add_key_mapping_row(refresh=False)
        self.refresh_mapping_binding_controls()
        map_note = QLabel("按下映射热键后，软件会替你点击指定坐标。脚本正在运行时默认忽略映射，避免打断自动化流程。带 Ctrl/Alt/Shift 的组合键可直接全局生效；裸字母、裸数字、Space 等单键需要开启“按键映射模式”。")
        map_note.setWordWrap(True)
        map_note.setProperty("role", "muted")
        map_main.addWidget(map_note)
        g_map.set_content_layout(map_main)
        settings_content_layout.addWidget(g_map)

        links_row = QHBoxLayout()
        platform_label = QLabel("支持 Windows 10 / 11 x64")
        platform_label.setProperty("role", "muted")
        platform_label.setToolTip(
            f"系统支持：{SUPPORTED_WINDOWS_TEXT}\n当前版本按 64 位 Python、Qt 和原生 DLL 构建。"
        )
        links_row.addWidget(platform_label)
        links_row.addStretch()
        bilibili_btn = QPushButton("作者B站主页")
        bilibili_btn.setProperty("variant", "ghost")
        bilibili_btn.clicked.connect(lambda: self.open_web_url("https://space.bilibili.com/95794432/dynamic"))
        links_row.addWidget(bilibili_btn)
        github_btn = QPushButton("GitHub下载页")
        github_btn.setProperty("variant", "ghost")
        github_btn.clicked.connect(lambda: self.open_web_url("https://github.com/FUKUAHG13/waterRPA-FUKUA/releases"))
        links_row.addWidget(github_btn)
        settings_content_layout.addLayout(links_row)
        settings_content_layout.addStretch()

        # ================= 任务列表与日志分屏 =================
        self.splitter = QSplitter(Qt.Vertical)

        task_panel = QFrame()
        task_panel.setObjectName("workspacePanel")
        task_panel_layout = QVBoxLayout(task_panel)
        task_panel_layout.setContentsMargins(0, 0, 0, 0)
        task_panel_layout.setSpacing(0)
        task_header = QHBoxLayout()
        task_header.setContentsMargins(12, 8, 10, 7)
        task_title = QLabel("脚本步骤")
        task_title.setProperty("role", "sectionTitle")
        task_header.addWidget(task_title)
        task_header.addStretch()
        self.task_count_label = QLabel("0 步")
        self.task_count_label.setProperty("role", "muted")
        task_header.addWidget(self.task_count_label)
        task_panel_layout.addLayout(task_header)

        self.task_list = DraggableListWidget()
        self.task_list.setObjectName("taskList")
        self.task_list.itemSelectionChanged.connect(self.update_selection_highlight)
        task_panel_layout.addWidget(self.task_list, 1)
        self.splitter.addWidget(task_panel)
        
        bottom_widget = QFrame()
        bottom_widget.setObjectName("workspacePanel")
        bottom_vbox = QVBoxLayout(bottom_widget)
        bottom_vbox.setContentsMargins(10, 8, 10, 10)
        bottom_vbox.setSpacing(7)
        
        # 底部运行控制区
        bot_layout = QHBoxLayout()
        bot_layout.setContentsMargins(0, 0, 0, 0)
        loop_caption = QLabel("循环")
        loop_caption.setProperty("role", "muted")
        bot_layout.addWidget(loop_caption)
        self.loop_combo = NoWheelComboBox()
        self.loop_combo.addItems(["单次", "无限", "指定次数", "指定时间(时)", "指定时间(分)", "指定时间(秒)"])
        self.loop_combo.currentTextChanged.connect(self.update_loop_ui)
        bot_layout.addWidget(self.loop_combo)
        
        self.loop_val_edit = QLineEdit("10"); self.loop_val_edit.setFixedWidth(50)
        bot_layout.addWidget(self.loop_val_edit)
        self.update_loop_ui(self.loop_combo.currentText())
        
        bot_layout.addStretch()
        bot_layout.addWidget(self.mini_chk)
        bot_layout.addWidget(self.top_chk)
        bot_layout.addSpacing(10)
        
        self.start_btn = QPushButton("启动"); self.start_btn.clicked.connect(self.start_task)
        self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.start_btn.setProperty("variant", "success")
        self.start_btn.setMinimumSize(112, 32)
        bot_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止"); self.stop_btn.clicked.connect(self.stop_task)
        self.stop_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setMinimumSize(112, 32)
        self.stop_btn.setEnabled(False)
        bot_layout.addWidget(self.stop_btn)

        debug_layout = QHBoxLayout()
        debug_layout.setContentsMargins(0, 0, 0, 0)
        debug_layout.setSpacing(6)
        debug_caption = QLabel("调试")
        self.debug_layout = debug_layout
        self.debug_caption = debug_caption
        debug_caption.setProperty("role", "muted")
        debug_layout.addStretch()
        debug_layout.addWidget(debug_caption)

        self.debug_pause_btn = QPushButton("")
        self.debug_pause_btn.setIcon(
            self.style().standardIcon(QStyle.SP_MediaPause)
        )
        self.debug_pause_btn.setFixedSize(34, 32)
        self.debug_pause_btn.setProperty("iconOnly", True)
        self.debug_pause_btn.setProperty("variant", "ghost")
        self.debug_pause_btn.setToolTip("完成当前步骤后，在下一个步骤执行前暂停")
        self.debug_pause_btn.clicked.connect(self.pause_debug_run)
        self.debug_pause_btn.setEnabled(False)
        debug_layout.addWidget(self.debug_pause_btn)

        self.debug_continue_btn = QPushButton("")
        self.debug_continue_btn.setIcon(
            self.style().standardIcon(QStyle.SP_MediaPlay)
        )
        self.debug_continue_btn.setFixedSize(34, 32)
        self.debug_continue_btn.setProperty("iconOnly", True)
        self.debug_continue_btn.setProperty("variant", "tonal")
        self.debug_continue_btn.setToolTip("从暂停位置继续运行到下一个断点")
        self.debug_continue_btn.clicked.connect(self.continue_debug_run)
        self.debug_continue_btn.setEnabled(False)
        debug_layout.addWidget(self.debug_continue_btn)

        self.debug_next_btn = QPushButton("")
        self.debug_next_btn.setIcon(
            self.style().standardIcon(QStyle.SP_MediaSkipForward)
        )
        self.debug_next_btn.setFixedSize(34, 32)
        self.debug_next_btn.setProperty("iconOnly", True)
        self.debug_next_btn.setProperty("variant", "tonal")
        self.debug_next_btn.setToolTip("执行当前暂停步骤，并在下一个实际步骤前再次暂停")
        self.debug_next_btn.clicked.connect(self.step_over_debug_run)
        self.debug_next_btn.setEnabled(False)
        debug_layout.addWidget(self.debug_next_btn)

        self.debug_variables_btn = QPushButton("")
        self.debug_variables_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogInfoView)
        )
        self.debug_variables_btn.setFixedSize(34, 32)
        self.debug_variables_btn.setProperty("iconOnly", True)
        self.debug_variables_btn.setProperty("variant", "ghost")
        self.debug_variables_btn.setToolTip("查看当前暂停位置的运行变量")
        self.debug_variables_btn.clicked.connect(self.show_debug_variables)
        self.debug_variables_btn.setEnabled(False)
        debug_layout.addWidget(self.debug_variables_btn)
        
        bottom_vbox.addLayout(bot_layout)
        bottom_vbox.addLayout(debug_layout)

        log_header = QHBoxLayout()
        log_title = QLabel("运行日志")
        log_title.setProperty("role", "sectionTitle")
        log_header.addWidget(log_title)
        log_header.addStretch()
        bottom_vbox.addLayout(log_header)

        self.log_text = QTextEdit()
        self.log_text.setObjectName("logView")
        self.log_text.setReadOnly(True)
        self.log_text.document().setMaximumBlockCount(500)
        bottom_vbox.addWidget(self.log_text)
        
        self.splitter.addWidget(bottom_widget)
        self.splitter.setSizes([480, 230])
        main_layout.addWidget(self.splitter)
        
        # 状态栏
        status_bar = QFrame()
        status_bar.setObjectName("statusBar")
        self.status_layout = QHBoxLayout(status_bar)
        self.status_layout.setContentsMargins(10, 5, 10, 5)
        self.status_layout.setSpacing(12)
        log_path = get_log_path(self.base_dir)
        self.log_path_label = QLabel(f"日志: {os.path.basename(log_path)}")
        self.log_path_label.setProperty("role", "muted")
        self.log_path_label.setToolTip(log_path)
        self.status_layout.addWidget(self.log_path_label)
        self.region_label = QLabel("范围: 全屏")
        self.region_label.setProperty("role", "statusGood")
        self.status_layout.addWidget(self.region_label)
        self.status_layout.addStretch()
        self.cpu_label = QLabel("逻辑处理器: -- | 系统 CPU: -- | 本程序 CPU: --")
        self.cpu_label.setProperty("role", "statusInfo")
        self.status_layout.addWidget(self.cpu_label)
        main_layout.addWidget(status_bar)
        
        # 初始化定时器与全局配置
        self.cpu_timer = QTimer()
        self.cpu_timer.timeout.connect(self.update_cpu_info)
        self.cpu_timer.start(self.current_cpu_interval())
        
        self.hotkey_timer = QTimer()
        self.hotkey_timer.timeout.connect(self.check_hotkey)
        self.hotkey_timer.setInterval(self.current_hotkey_interval())
        
        self.init_profiles()
        self.bind_setting_logs()
        self.update_hotkeys()
        if self.defer_runtime:
            self.start_btn.setEnabled(False)
            self.single_step_btn.setEnabled(False)
            self.start_btn.setToolTip("识别运行库正在后台准备")
            QTimer.singleShot(0, self.initialize_runtime_async)
        self.profiles_autosave_timer = QTimer(self)
        self.profiles_autosave_timer.timeout.connect(self.autosave_profiles_if_changed)
        self.profiles_autosave_timer.start(3000)
        if self._config_recovery_message:
            QTimer.singleShot(0, self.show_config_recovery_message)
        if runtime_path_info().mode == "local_app_data" and not self.settings.value(
            "local_data_location_notice", False, type=bool
        ):
            QTimer.singleShot(0, self.show_local_data_location_notice)
        self.apply_settings_mode()

    def advanced_settings_are_non_default(self):
        return any(
            (
                not self.native_core_chk.isChecked(),
                self.native_parallel_combo.currentData() != "auto",
                not self.native_scale_hint_chk.isChecked(),
                self.scale_memory_tier_combo.currentData() != "balanced",
                bool(self.scale_memory_manual_edit.text().strip()),
                self.scale_memory_custom_chk.isChecked(),
                not self.scene_wake_chk.isChecked(),
                self.scene_wake_sensitivity_combo.currentData() != "balanced",
                self.cpu_refresh_combo.currentData() != "auto",
            )
        )

    def apply_settings_mode(self, _index=None):
        combo = getattr(self, "settings_mode_combo", None)
        if combo is None:
            return
        advanced = combo.currentData() == "advanced"
        self.settings.setValue(
            "settings_view_mode", "advanced" if advanced else "simple"
        )
        for widget in getattr(self, "advanced_setting_widgets", []):
            widget.setVisible(advanced)
        notice = getattr(self, "advanced_settings_notice", None)
        if notice is not None:
            notice.setText(
                "部分高级设置仍在生效"
                if not advanced and self.advanced_settings_are_non_default()
                else ""
            )
            notice.setToolTip(
                "切换到高级模式可查看；简易模式不会重置或停用这些设置。"
            )

    def show_local_data_location_notice(self):
        self.settings.setValue("local_data_location_notice", True)
        QMessageBox.information(
            self,
            "配置已保存到用户目录",
            "当前程序所在目录不可写，因此方案、日志、导入图片和凭据已自动保存到：\n\n"
            f"{self.base_dir}\n\n"
            "程序功能不受影响；设置中的“打开配置目录”会直接打开此位置。",
        )

    def initialize_runtime_async(self):
        if self.runtime_ready or self.runtime_init_in_progress:
            return
        self.runtime_init_in_progress = True
        started = time.perf_counter()

        def initialize():
            try:
                self.engine.initialize_backends()
                result = (True, "")
            except Exception as error:
                result = (False, str(error))
            try:
                self.runtime_init_bridge.completed.emit(
                    result[0],
                    result[1],
                    (time.perf_counter() - started) * 1000.0,
                )
            except RuntimeError:
                pass

        self._runtime_init_thread = threading.Thread(
            target=initialize,
            daemon=True,
            name="fukuaRPA-runtime-init",
        )
        self._runtime_init_thread.start()

    def on_runtime_initialized(self, ok, error, elapsed_ms):
        self.runtime_init_in_progress = False
        self.runtime_ready = bool(ok)
        if ok:
            if not self.run_controller.is_active:
                self.start_btn.setEnabled(True)
                self.single_step_btn.setEnabled(True)
            self.start_btn.setToolTip("")
            write_log(f"运行库后台初始化完成，用时 {elapsed_ms:.1f} ms。")
            return
        self.start_btn.setEnabled(False)
        self.single_step_btn.setEnabled(False)
        self.start_btn.setToolTip("识别运行库初始化失败")
        write_log(f"运行库后台初始化失败：{error}")

    def show_config_recovery_message(self):
        """Show recovery details only while the main window is still in use."""
        if not self._config_recovery_message or not self.isVisible():
            return
        QMessageBox.warning(self, "配置恢复提示", self._config_recovery_message)

    def refresh_credential_names(self, selected=""):
        combo = getattr(self, "credential_combo", None)
        if combo is None:
            return
        current = str(selected or combo.currentText()).strip()
        try:
            names = self.credentials.names()
        except CredentialStoreError as error:
            names = []
            QMessageBox.warning(self, "凭据库读取失败", str(error))
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        if current in names:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    def edit_credential(self):
        current = str(self.credential_combo.currentText()).strip()
        name, accepted = QInputDialog.getText(
            self.settings,
            "新增或修改凭据",
            "凭据名称（脚本步骤中填写此名称）:",
            QLineEdit.Normal,
            current,
        )
        if not accepted:
            return
        secret, accepted = QInputDialog.getText(
            self.settings,
            "输入秘密内容",
            "秘密内容将使用当前 Windows 用户的 DPAPI 加密保存:",
            QLineEdit.Password,
        )
        if not accepted:
            return
        try:
            self.credentials.set(name, secret)
        except CredentialStoreError as error:
            QMessageBox.warning(self.settings, "保存凭据失败", str(error))
            return
        self.refresh_credential_names(str(name).strip())
        QMessageBox.information(
            self.settings,
            "凭据已保存",
            "凭据已加密保存。脚本方案只会记录凭据名称。",
        )

    def delete_credential(self):
        name = str(self.credential_combo.currentText()).strip()
        if not name:
            return
        answer = QMessageBox.question(
            self.settings,
            "删除凭据",
            f"确定删除凭据“{name}”吗？引用它的脚本步骤之后会执行失败。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.credentials.delete(name)
        except CredentialStoreError as error:
            QMessageBox.warning(self.settings, "删除凭据失败", str(error))
            return
        self.refresh_credential_names()

    def open_config_dir(self):
        try:
            config_dir = os.path.normpath(self.base_dir)
            if not os.path.isdir(config_dir):
                config_dir = os.path.dirname(os.path.abspath(self.config_path))
            subprocess.Popen(["explorer.exe", config_dir])
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开配置目录: {e}")

    def open_web_url(self, url):
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开网页: {e}")

    def collect_diagnostic_report(self):
        report = run_runtime_diagnostics(self.base_dir)
        lifecycle = asdict(self.engine.lifecycle.snapshot())
        lifecycle_state = lifecycle.get("state", "idle")
        lifecycle["state"] = getattr(lifecycle_state, "value", str(lifecycle_state))
        screens = []
        for screen in QApplication.screens():
            geometry = screen.geometry()
            screens.append(
                {
                    "name": screen.name(),
                    "geometry": [
                        geometry.x(), geometry.y(), geometry.width(), geometry.height()
                    ],
                    "device_pixel_ratio": screen.devicePixelRatio(),
                    "logical_dpi": round(screen.logicalDotsPerInch(), 2),
                }
            )
        current_config = self.get_current_ui_config()
        log_policy = self.current_log_policy()
        report.update(
            {
                "application": {
                    "version": APP_VERSION,
                    "build_name": BUILD_NAME,
                    "ui_scale_percent": round(self.ui_scale * 100.0, 1),
                    "log_level": self.log_level_combo.currentText(),
                    "log_mode": log_policy.mode,
                    "log_categories": list(log_policy.enabled_categories),
                    "task_count": len(current_config.get("tasks", [])),
                    "mapping_count": len(current_config.get("key_mappings", [])),
                },
                "screens": screens,
                "lifecycle": lifecycle,
                "performance": {
                    "engine_last_run": dict(self.engine.last_performance_report),
                    "engine_current": self.engine.performance_snapshot(),
                    "ui": self.ui_performance.snapshot(),
                },
                "runtime_trace": {
                    "last_run": dict(self.engine.last_run_trace),
                    "current": self.engine.run_trace.snapshot(),
                },
            }
        )
        return report

    def export_diagnostic_report(self):
        default_name = f"{BUILD_NAME}_diagnostics_{time.strftime('%Y%m%d_%H%M%S')}.json"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self.settings_interaction_parent(),
            "导出离线诊断",
            os.path.join(self.base_dir, default_name),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            atomic_write_json(path, self.collect_diagnostic_report())
            QMessageBox.information(
                self.settings_interaction_parent(),
                "导出完成",
                "诊断报告已保存。报告不会联网，也不包含脚本步骤、图片路径或按键映射坐标。",
            )
        except Exception as error:
            QMessageBox.warning(
                self.settings_interaction_parent(), "导出失败", str(error)
            )

    def verify_installed_payload(self):
        manifest_path = os.path.join(self.base_dir, PAYLOAD_MANIFEST_NAME)
        if not os.path.isfile(manifest_path):
            QMessageBox.information(
                self.settings_interaction_parent(),
                "没有发布清单",
                "当前目录不是带完整性清单的正式发布包，无法执行程序文件校验。",
            )
            return
        worker = getattr(self, "integrity_worker", None)
        if worker and worker.isRunning():
            return
        self.integrity_btn.setEnabled(False)
        self.integrity_btn.setText("校验中…")
        worker = PayloadVerificationThread(self.base_dir, self)
        self.integrity_worker = worker
        worker.report_ready.connect(self.on_integrity_report)
        worker.finished.connect(self.on_integrity_worker_finished)
        worker.start()

    def on_integrity_worker_finished(self):
        worker = self.integrity_worker
        self.integrity_worker = None
        self.integrity_btn.setEnabled(True)
        self.integrity_btn.setText("校验程序")
        if worker:
            worker.deleteLater()

    def on_integrity_report(self, report):
        if report.get("cancelled"):
            return
        missing = list(report.get("missing", []))
        mismatched = list(report.get("mismatched", []))
        suspicious = list(report.get("suspicious_unexpected", []))
        unexpected = list(report.get("unexpected", []))
        details = []
        if missing:
            details.append("缺失文件：\n" + "\n".join(missing))
        if mismatched:
            details.append("内容不一致：\n" + "\n".join(mismatched))
        if suspicious:
            details.append("清单外可执行文件：\n" + "\n".join(suspicious))
        if unexpected:
            details.append("其他清单外文件（通常是运行配置/日志）：\n" + "\n".join(unexpected))
        message = QMessageBox(self.settings_interaction_parent())
        message.setWindowTitle("程序文件校验")
        message.setStandardButtons(QMessageBox.Ok)
        if report.get("ok"):
            message.setIcon(QMessageBox.Information)
            message.setText(
                f"已核对 {report.get('checked', 0)} 个发布文件，没有发现缺失或损坏。"
            )
            message.setInformativeText(
                "内部哈希用于发现意外损坏；当前版本没有作者数字签名，不能据此证明发布者身份。"
            )
        else:
            message.setIcon(QMessageBox.Warning)
            message.setText("程序文件校验未通过。")
            message.setInformativeText(
                str(report.get("error") or "发现文件缺失、内容变化或额外可执行文件。")
            )
        if details:
            message.setDetailedText("\n\n".join(details))
        message.exec()

    def current_hotkey_interval(self):
        return 250 if getattr(self, "low_power_ui_chk", None) and self.low_power_ui_chk.isChecked() else 100

    def current_cpu_interval(self):
        combo = getattr(self, "cpu_refresh_combo", None)
        selected = combo.currentData() if combo is not None else "auto"
        if selected != "auto":
            try:
                return max(0, int(selected))
            except (TypeError, ValueError):
                pass
        return 3000 if getattr(self, "low_power_ui_chk", None) and self.low_power_ui_chk.isChecked() else 1000

    def apply_ui_performance_mode(self, *_):
        if getattr(self, "hotkey_timer", None):
            self.hotkey_timer.setInterval(self.current_hotkey_interval())
        if getattr(self, "cpu_timer", None):
            interval = self.current_cpu_interval()
            if interval <= 0:
                self.cpu_timer.stop()
                self.cpu_label.setText("资源监测: 已关闭")
            else:
                self.cpu_timer.setInterval(interval)
                if not self.cpu_timer.isActive():
                    self.cpu_timer.start()

    def parse_ui_scale_percent(self):
        raw = str(getattr(self, "ui_scale_edit", QLineEdit("100")).text()).strip().replace("%", "")
        value = parse_float_text(raw, 100.0)
        value = max(75.0, min(180.0, value))
        if abs(value - round(value)) < 0.01:
            text = str(int(round(value)))
        else:
            text = f"{value:.1f}".rstrip("0").rstrip(".")
        if getattr(self, "ui_scale_edit", None) and self.ui_scale_edit.text().strip().replace("%", "") != text:
            self.ui_scale_edit.setText(text)
        return value

    def apply_ui_scale_from_edit(self, *_):
        percent = self.parse_ui_scale_percent()
        self.apply_ui_scale(percent / 100.0)
        if not self.is_switching_profile:
            self.log_setting_change("界面倍率(%)", self.ui_scale_edit.text())

    def apply_ui_scale_to_widgets(self, widgets, scale):
        qwidget_max = 16777215
        for widget in widgets:
            if widget is None:
                continue
            try:
                if not widget.property("_ui_scale_base_saved"):
                    widget.setProperty("_ui_scale_base_saved", True)
                    widget.setProperty("_ui_base_min_w", widget.minimumWidth())
                    widget.setProperty("_ui_base_min_h", widget.minimumHeight())
                    widget.setProperty("_ui_base_max_w", widget.maximumWidth())
                    widget.setProperty("_ui_base_max_h", widget.maximumHeight())

                min_w = int(widget.property("_ui_base_min_w") or 0)
                min_h = int(widget.property("_ui_base_min_h") or 0)
                max_w = int(widget.property("_ui_base_max_w") or qwidget_max)
                max_h = int(widget.property("_ui_base_max_h") or qwidget_max)

                is_scalable_text_button = (
                    isinstance(widget, QPushButton)
                    and bool(widget.text().strip())
                    and not bool(widget.property("iconOnly"))
                    and widget.objectName() != "helpButton"
                    and max_w >= qwidget_max
                )
                if is_scalable_text_button:
                    base_text_width = widget.property("_ui_base_text_button_w")
                    if base_text_width is None:
                        widget.ensurePolished()
                        # The active theme has already been scaled. Convert its
                        # content-aware hint back to the stable 100% baseline.
                        base_text_width = max(
                            1,
                            int(round(widget.sizeHint().width() / scale)),
                        )
                        widget.setProperty(
                            "_ui_base_text_button_w", base_text_width
                        )
                    min_w = max(min_w, int(base_text_width))

                if min_w > 0:
                    widget.setMinimumWidth(max(1, int(round(min_w * scale))))
                    if is_scalable_text_button:
                        # Font glyphs, icons and stylesheet padding round at
                        # the active DPI. Honor the final content hint after
                        # applying the linear baseline so the last glyph is
                        # never clipped by a few pixels.
                        content_width = widget.sizeHint().width()
                        if content_width > widget.minimumWidth():
                            widget.setMinimumWidth(content_width)
                if min_h > 0:
                    widget.setMinimumHeight(max(1, int(round(min_h * scale))))
                if 0 < max_w < qwidget_max:
                    widget.setMaximumWidth(max(1, int(round(max_w * scale))))
                if 0 < max_h < qwidget_max:
                    widget.setMaximumHeight(max(1, int(round(max_h * scale))))
            except RuntimeError:
                continue
            except Exception:
                continue

    def apply_ui_scale_to_widget(self, widget):
        if not widget:
            return
        scale = float(getattr(self, "ui_scale", 1.0))
        widgets = [widget] + widget.findChildren(QWidget)
        self.apply_ui_scale_to_widgets(widgets, scale)

    def apply_ui_scale(self, scale):
        scale = max(0.75, min(1.8, float(scale)))
        self.ui_scale = scale
        application = QApplication.instance()
        current_theme_scale = (
            float(application.property("_fukua_ui_scale") or 1.0)
            if application is not None
            else scale
        )
        if application is not None and abs(current_theme_scale - scale) > 0.001:
            apply_modern_theme(application, scale)
        try:
            self.apply_ui_scale_to_widgets(QApplication.allWidgets(), scale)
            self.updateGeometry()
            if getattr(self, "settings_dialog", None):
                self.settings_dialog.updateGeometry()
            for i in range(self.task_list.count()):
                item = self.task_list.item(i)
                widget = self.task_list.itemWidget(item)
                if widget:
                    item.setSizeHint(widget.sizeHint())
        except Exception:
            pass

    def show_settings_dialog(self):
        self.refresh_scale_memory_status()
        self.show_fast_response_tip_once()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def show_fast_response_tip_once(self):
        tip = getattr(self, "fast_response_tip", None)
        if tip is None:
            return
        key = "onboarding/fast_response_tip_v1_seen"
        if config_bool(self.settings.value(key, False)):
            tip.hide()
            return
        self.settings.setValue(key, True)
        self.settings.sync()
        tip.show()

    def dismiss_fast_response_tip(self):
        tip = getattr(self, "fast_response_tip", None)
        if tip is not None:
            tip.hide()

    def close_settings_dialog(self):
        self.settings_dialog.save_dialog_geometry()
        self.dismiss_fast_response_tip()
        self.settings_dialog.hide()

    def start_dodge_point_pick(self, point_index):
        point_index = 2 if int(point_index) == 2 else 1
        previous = self.dodge_pickers.pop(point_index, None)
        if previous is not None:
            try:
                previous.close()
            except RuntimeError:
                pass
        picker = CoordinatePickerUI(
            "point",
            lambda value, index=point_index: self.on_dodge_point_picked(
                index, value
            ),
        )
        self.dodge_pickers[point_index] = picker
        picker.destroyed.connect(
            lambda *_args, index=point_index: self.dodge_pickers.pop(
                index, None
            )
        )

    def on_dodge_point_picked(self, point_index, value):
        point = parse_coordinate_text(value)
        if point is None:
            return
        x_edit, y_edit = (
            (self.dodge_x2, self.dodge_y2)
            if int(point_index) == 2
            else (self.dodge_x1, self.dodge_y1)
        )
        x_edit.setText(str(point[0]))
        y_edit.setText(str(point[1]))
        self.log_setting_change(
            f"避让坐标{2 if int(point_index) == 2 else 1}",
            f"{point[0]},{point[1]}",
        )
        self.restore_settings_dialog_focus()

    def register_task_config_dialog(self, dialog):
        if not dialog:
            return
        self.task_config_dialogs.add(dialog)
        dialog.destroyed.connect(lambda *_args, d=dialog: self.task_config_dialogs.discard(d))

    def unregister_task_config_dialog(self, dialog):
        self.task_config_dialogs.discard(dialog)

    def close_all_task_config_dialogs(self):
        for dialog in list(getattr(self, "task_config_dialogs", set())):
            try:
                dialog.close()
            except RuntimeError:
                self.task_config_dialogs.discard(dialog)

    def show_running_status_overlay(self, position_name):
        if self.running_overlay is None:
            self.running_overlay = RunningStatusOverlay()
        self.running_overlay.start_overlay(position_name)

    def update_running_status_overlay(self, data):
        if self.running_overlay and self.running_overlay.isVisible():
            self.running_overlay.set_status(data)

    def hide_running_status_overlay(self):
        if self.running_overlay:
            self.running_overlay.stop_overlay()

    def show_click_indicator_overlay(self, data):
        try:
            if not hasattr(self, "click_indicator_overlays"):
                self.click_indicator_overlays = []
            while len(self.click_indicator_overlays) >= MAX_CLICK_INDICATOR_OVERLAYS:
                oldest = self.click_indicator_overlays.pop(0)
                try:
                    oldest.close()
                except RuntimeError:
                    pass
            overlay = ClickPointOverlay(data.get("x", 0), data.get("y", 0), data.get("text", ""))
            self.click_indicator_overlays.append(overlay)
            overlay.destroyed.connect(lambda *_args, o=overlay: self.click_indicator_overlays.remove(o) if o in self.click_indicator_overlays else None)
        except Exception as e:
            write_log(f"显示点击位置提示失败: {e}")

    def coordinate_preview_options_from_task(self, task):
        return coordinate_preview_options(task)

    def add_key_mapping_row(self, data=None, refresh=True):
        idx = len(getattr(self, "key_mapping_rows", []))
        container = ResponsiveRow(horizontal_spacing=10, vertical_spacing=7)
        container.setProperty("rowRole", "keyMapping")

        en = QCheckBox()
        hotkey = QLineEdit(f"F{idx + 1}")
        hotkey.setPlaceholderText("A / Ctrl+A / F1")
        hotkey.setMinimumWidth(125)

        key_btn = fit_text_button(QPushButton("录键"), 64)
        key_btn.setProperty("variant", "ghost")
        key_btn.setToolTip("录入映射热键；完成后焦点会回到设置窗口")
        container.add_group(en, "热键:", hotkey, key_btn)

        coord = QLineEdit("")
        coord.setPlaceholderText("例如 960,540")
        coord.setMinimumWidth(150)

        pick = fit_text_button(QPushButton("取点"), 64)
        pick.setProperty("variant", "tonal")
        pick.setToolTip("选取点击坐标")

        bind_window = fit_text_button(QPushButton("选择窗口"), 96)
        bind_window.setProperty("variant", "ghost")
        bind_window.setToolTip(
            "仅用于后台窗口点击：先填写或取点，再点此按钮并亲自单击目标程序窗口"
        )
        container.add_group("坐标:", coord, pick)

        binding_status = QLabel("未绑定目标窗口")
        binding_status.setProperty("role", "muted")
        binding_status.setMinimumWidth(110)
        binding_status.setMaximumWidth(520)
        container.add_group(bind_window)

        action = NoWheelComboBox()
        action.addItems(["左键单击", "左键双击", "右键单击"])
        fit_combo_to_contents(action)

        delete_btn = QPushButton("")
        delete_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        delete_btn.setFixedWidth(34)
        delete_btn.setProperty("iconOnly", True)
        delete_btn.setProperty("variant", "dangerGhost")
        inspect_btn = QPushButton("")
        inspect_btn.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        inspect_btn.setFixedWidth(34)
        inspect_btn.setProperty("iconOnly", True)
        inspect_btn.setProperty("variant", "ghost")
        inspect_btn.setToolTip("检查已绑定窗口、目标控件和权限兼容性")
        container.add_group(action, inspect_btn, delete_btn)
        binding_group = container.add_trailing_group(binding_status)

        row_data = {
            "container": container, "enabled": en, "hotkey": hotkey, "key_btn": key_btn,
            "coord": coord, "pick": pick, "bind_window": bind_window, "action": action,
            "binding_status": binding_status, "binding_group": binding_group,
            "inspect_btn": inspect_btn, "delete_btn": delete_btn, "window_binding": {}
        }

        key_btn.clicked.connect(lambda _=False, r=row_data: self.capture_mapping_hotkey_by_row(r))
        pick.clicked.connect(lambda _=False, r=row_data: self.start_mapping_coordinate_pick_by_row(r))
        bind_window.clicked.connect(lambda _=False, r=row_data: self.bind_mapping_window_by_row(r))
        inspect_btn.clicked.connect(
            lambda _=False, r=row_data: self.show_mapping_window_inspector(r)
        )
        delete_btn.clicked.connect(lambda _=False, r=row_data: self.remove_key_mapping_row(r))
        coord.textChanged.connect(lambda _text, r=row_data: self.clear_mapping_window_binding(r))
        for widget in [en, hotkey, coord, action]:
            if isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self.refresh_hotkey_backend)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.refresh_hotkey_backend)
            else:
                widget.stateChanged.connect(self.refresh_hotkey_backend)

        self.key_mapping_rows.append(row_data)
        self.mapping_rows_layout.addWidget(container)
        if data is not None:
            self.apply_key_mapping_row_data(row_data, data, idx)
        else:
            self.update_mapping_window_binding_ui(row_data)
        self.refresh_mapping_row_labels()
        if refresh:
            self.refresh_hotkey_backend()
        if abs(float(getattr(self, "ui_scale", 1.0)) - 1.0) > 0.001:
            self.apply_ui_scale_to_widget(container)
        return row_data

    def apply_key_mapping_row_data(self, row, data, idx=0):
        data = data if isinstance(data, dict) else {}
        row["enabled"].setChecked(config_bool(data.get("enabled", False)))
        parsed = parse_hotkey_text(data.get("hotkey", f"F{idx + 1}"))
        row["hotkey"].setText(parsed["display"] if parsed else str(data.get("hotkey", f"F{idx + 1}")))
        row["coord"].setText(str(data.get("coord", "")))
        binding = data.get("window_binding", {})
        row["window_binding"] = dict(binding) if isinstance(binding, dict) else {}
        self.update_mapping_window_binding_ui(row)
        row["action"].setCurrentText(str(data.get("action", "左键单击")))

    def clear_key_mapping_rows(self):
        for row in list(getattr(self, "key_mapping_rows", [])):
            container = row.get("container")
            if container:
                try:
                    self.mapping_rows_layout.removeWidget(container)
                    container.setParent(None)
                    container.deleteLater()
                except Exception:
                    pass
        self.key_mapping_rows = []

    def refresh_mapping_row_labels(self):
        for idx, row in enumerate(getattr(self, "key_mapping_rows", [])):
            try:
                row["enabled"].setText(f"映射{idx + 1}")
                row["delete_btn"].setToolTip(f"删除映射{idx + 1}")
            except Exception:
                pass

    def mapping_row_index(self, row_data):
        try:
            return self.key_mapping_rows.index(row_data)
        except ValueError:
            return -1

    def remove_key_mapping_row(self, row_data):
        idx = self.mapping_row_index(row_data)
        if idx < 0:
            return
        container = row_data.get("container")
        self.key_mapping_rows.pop(idx)
        if container:
            try:
                self.mapping_rows_layout.removeWidget(container)
                container.setParent(None)
                container.deleteLater()
            except Exception:
                pass
        self.refresh_mapping_row_labels()
        self.refresh_hotkey_backend()

    def get_key_mappings_config(self):
        mappings = []
        for row in getattr(self, "key_mapping_rows", []):
            mappings.append({
                "enabled": row["enabled"].isChecked(),
                "hotkey": row["hotkey"].text().strip(),
                "coord": row["coord"].text().strip(),
                "action": row["action"].currentText(),
                "window_binding": dict(row.get("window_binding", {})),
            })
        return mappings

    def apply_key_mappings_config(self, mappings, desired_count=None):
        mappings = mappings if isinstance(mappings, list) else []
        if len(mappings) > MAX_KEY_MAPPINGS:
            write_log(f"按键映射数量超过上限 {MAX_KEY_MAPPINGS}，多余内容已忽略。")
            mappings = mappings[:MAX_KEY_MAPPINGS]
        try:
            count = int(float(desired_count)) if desired_count is not None else (len(mappings) if mappings else HOTKEY_MAPPING_COUNT)
        except Exception:
            count = len(mappings) if mappings else HOTKEY_MAPPING_COUNT
        count = min(MAX_KEY_MAPPINGS, max(0, max(count, len(mappings))))
        self._bulk_mapping_update = True
        try:
            self.clear_key_mapping_rows()
            for idx in range(count):
                data = mappings[idx] if idx < len(mappings) and isinstance(mappings[idx], dict) else None
                self.add_key_mapping_row(data=data, refresh=False)
            self.refresh_mapping_row_labels()
        finally:
            self._bulk_mapping_update = False
        self.refresh_mapping_binding_controls()
        self.refresh_hotkey_backend()

    def settings_interaction_parent(self):
        dialog = getattr(self, "settings_dialog", None)
        return dialog if dialog is not None and dialog.isVisible() else self

    def restore_settings_dialog_focus(self):
        dialog = getattr(self, "settings_dialog", None)
        if dialog is None or not dialog.isVisible():
            return
        dialog.raise_()
        dialog.activateWindow()

    def capture_hotkey_text(self, title):
        parent = self.settings_interaction_parent()
        dialog = KeyCaptureDialog(parent, title)
        accepted = dialog.exec() == QDialog.Accepted
        captured = hotkey_display_text(dialog.captured_text) if accepted else ""
        if parent is getattr(self, "settings_dialog", None):
            self.restore_settings_dialog_focus()
            QTimer.singleShot(0, self.restore_settings_dialog_focus)
        return captured

    def capture_start_hotkey(self):
        captured = self.capture_hotkey_text("录入启动热键")
        if captured:
            self.hotkey_start_edit.setText(captured)
            self.update_hotkeys()
            self.hotkey_start_edit.setFocus(Qt.OtherFocusReason)

    def capture_stop_hotkey(self):
        captured = self.capture_hotkey_text("录入停止热键")
        if captured:
            self.hotkey_stop_edit.setText(captured)
            self.update_hotkeys()
            self.hotkey_stop_edit.setFocus(Qt.OtherFocusReason)

    def capture_mapping_hotkey(self, map_idx):
        if map_idx < 0 or map_idx >= len(self.key_mapping_rows):
            return
        captured = self.capture_hotkey_text(f"录入映射{map_idx + 1}热键")
        if captured:
            row = self.key_mapping_rows[map_idx]
            row["hotkey"].setText(captured)
            row["enabled"].setChecked(True)
            self.refresh_hotkey_backend()
            self.restore_settings_dialog_focus()
            row["hotkey"].setFocus(Qt.OtherFocusReason)

    def capture_mapping_hotkey_by_row(self, row_data):
        self.capture_mapping_hotkey(self.mapping_row_index(row_data))

    def start_mapping_coordinate_pick(self, map_idx):
        if map_idx < 0 or map_idx >= len(self.key_mapping_rows):
            return
        row_data = self.key_mapping_rows[map_idx]
        self.store_mapping_picker(
            row_data,
            "coordinate",
            CoordinatePickerUI(
                "point",
                lambda value, r=row_data: self.on_mapping_coordinate_picked_by_row(r, value),
            ),
        )

    def start_mapping_coordinate_pick_by_row(self, row_data):
        self.start_mapping_coordinate_pick(self.mapping_row_index(row_data))

    def on_mapping_coordinate_picked(self, map_idx, value):
        if map_idx < 0 or map_idx >= len(self.key_mapping_rows):
            return
        row = self.key_mapping_rows[map_idx]
        row["coord"].setText(value)
        row["enabled"].setChecked(True)
        self.refresh_hotkey_backend()

    def on_mapping_coordinate_picked_by_row(self, row_data, value):
        self.on_mapping_coordinate_picked(self.mapping_row_index(row_data), value)

    def store_mapping_picker(self, row_data, purpose, picker):
        key = (id(row_data), str(purpose))
        previous = self.mapping_pickers.pop(key, None)
        if previous is not None:
            try:
                previous.close()
            except RuntimeError:
                pass
        self.mapping_pickers[key] = picker
        picker.destroyed.connect(
            lambda *_args, k=key: self.mapping_pickers.pop(k, None)
        )
        return picker

    def clear_mapping_window_binding(self, row_data):
        row_data["window_binding"] = {}
        self.update_mapping_window_binding_ui(row_data)

    def update_mapping_window_binding_ui(self, row_data):
        button = row_data.get("bind_window")
        if not button:
            return
        status = row_data.get("binding_status")
        inspect_button = row_data.get("inspect_btn")
        binding = row_data.get("window_binding", {})
        background_mode = self.current_mapping_click_mode() == "后台窗口点击(实验)"
        button.setEnabled(background_mode)
        if inspect_button is not None:
            inspect_button.setEnabled(bool(background_mode and binding))
        if status is not None:
            status.setEnabled(background_mode)
        if binding:
            title = str(binding.get("root_title", "")).strip()
            class_name = str(binding.get("root_class", "")).strip()
            target_text = title or class_name or "目标窗口"
            button.setProperty("bound", True)
            button.setToolTip(
                f"已绑定：{target_text}\n点击后可重新手动选择目标程序窗口"
                if background_mode
                else "切换到“后台窗口点击(实验)”后才可重新选择目标窗口"
            )
            if status is not None:
                status.setText(f"已绑定：{target_text}")
                status.setToolTip(f"已绑定：{target_text}")
                status.setProperty("role", "statusGood")
        else:
            button.setProperty("bound", False)
            button.setToolTip(
                "先填写或取点，再点此按钮并亲自单击目标程序窗口"
                if background_mode
                else "仅“后台窗口点击(实验)”模式需要并允许选择目标窗口"
            )
            if status is not None:
                status.setText("未绑定目标窗口")
                status.setToolTip("后台窗口点击前需要绑定目标窗口")
                status.setProperty("role", "muted")
        button.style().unpolish(button)
        button.style().polish(button)
        if status is not None:
            status.style().unpolish(status)
            status.style().polish(status)

    def show_mapping_window_inspector(self, row_data):
        binding = dict(row_data.get("window_binding", {}))
        if not binding:
            QMessageBox.information(
                self.settings_interaction_parent(),
                "尚未绑定",
                "请先切换到后台窗口点击，并使用“选择窗口”绑定目标程序。",
            )
            return

        dialog = QDialog(None)
        dialog.setAttribute(Qt.WA_QuitOnClose, False)
        dialog.setWindowFlag(Qt.Window, True)
        dialog.setWindowModality(Qt.NonModal)
        row_index = self.mapping_row_index(row_data)
        dialog.setWindowTitle(f"映射{row_index + 1} 窗口检查")
        dialog.setMinimumSize(720, 520)
        dialog.resize(860, 640)
        layout = QVBoxLayout(dialog)
        summary = QLabel()
        summary.setProperty("role", "sectionTitle")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        report_view = QTextEdit()
        report_view.setReadOnly(True)
        layout.addWidget(report_view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        refresh_button = buttons.addButton("刷新", QDialogButtonBox.ActionRole)
        copy_button = buttons.addButton("复制报告", QDialogButtonBox.ActionRole)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(dialog.close)
        buttons.button(QDialogButtonBox.Close).clicked.connect(dialog.close)
        layout.addWidget(buttons)

        def refresh_report():
            current_binding = dict(row_data.get("window_binding", {}))
            report = self.ensure_mapping_backend().inspect_binding(current_binding)
            text = format_window_inspection(report)
            report_view.setPlainText(text)
            compatibility = report.get("compatibility", {}).get(
                "classification", "目标窗口已失效"
            )
            summary.setText(f"当前判断：{compatibility}")
            dialog.setProperty("inspectionText", text)

        def copy_report():
            pyperclip.copy(str(dialog.property("inspectionText") or ""))
            QToolTip.showText(QCursor.pos(), "检查报告已复制", copy_button)

        refresh_button.clicked.connect(refresh_report)
        copy_button.clicked.connect(copy_report)
        refresh_report()
        self.mapping_inspector_dialogs.add(dialog)
        dialog.destroyed.connect(
            lambda *_args, d=dialog: self.mapping_inspector_dialogs.discard(d)
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def refresh_mapping_binding_controls(self, *_):
        for row in getattr(self, "key_mapping_rows", []):
            self.update_mapping_window_binding_ui(row)

    def ensure_mapping_backend(self):
        if self.mapping_backend is None:
            self.mapping_backend = WindowMappingBackend()
        return self.mapping_backend

    def hwnd_class_name(self, hwnd):
        return self.ensure_mapping_backend().class_name(hwnd)

    def hwnd_title(self, hwnd):
        return self.ensure_mapping_backend().title(hwnd)

    def hwnd_process_info(self, hwnd):
        return self.ensure_mapping_backend().process_info(hwnd)

    def hwnd_belongs_to_current_process(self, hwnd):
        return self.ensure_mapping_backend().belongs_to_current_process(hwnd)

    def hwnd_screen_area_at_point(self, hwnd, x, y):
        return self.ensure_mapping_backend().screen_area_at_point(hwnd, x, y)

    def top_level_window_at_point(self, x, y, exclude_current_process=False):
        return self.ensure_mapping_backend().top_level_window_at_point(
            x, y, exclude_current_process=exclude_current_process
        )

    def bind_mapping_window_by_row(self, row_data, show_message=True):
        message_parent = self.settings_interaction_parent()
        if self.current_mapping_click_mode() != "后台窗口点击(实验)":
            if show_message:
                QMessageBox.information(
                    message_parent,
                    "无需选择窗口",
                    "“选择窗口”只用于后台窗口点击。请先把映射点击方式切换为“后台窗口点击(实验)”。",
                )
            return False
        coord = parse_coordinate_text(row_data.get("coord").text() if row_data.get("coord") else "")
        if not coord:
            if show_message:
                QMessageBox.warning(
                    message_parent, "无法绑定窗口", "请先填写坐标，或点击“取点”选择目标位置。"
                )
            return False
        picker = CoordinatePickerUI(
            "window",
            lambda value, r=row_data: self.on_mapping_window_picked_by_row(r, value),
        )
        self.store_mapping_picker(row_data, "window", picker)
        return True

    def on_mapping_window_picked_by_row(self, row_data, selection_value):
        if self.mapping_row_index(row_data) < 0:
            return False
        message_parent = self.settings_interaction_parent()
        if self.current_mapping_click_mode() != "后台窗口点击(实验)":
            return False
        coord = parse_coordinate_text(
            row_data.get("coord").text() if row_data.get("coord") else ""
        )
        selection = parse_coordinate_text(selection_value)
        if not coord or not selection:
            QMessageBox.warning(message_parent, "无法绑定窗口", "坐标无效，请重新取点。")
            return False
        try:
            binding = self.ensure_mapping_backend().create_binding_for_window_at_point(
                selection[0], selection[1], coord[0], coord[1]
            )
        except WindowBindingError as error:
            QMessageBox.warning(message_parent, "无法绑定窗口", str(error))
            self.restore_settings_dialog_focus()
            return False
        row_data["window_binding"] = binding
        self.update_mapping_window_binding_ui(row_data)
        target_text = binding.get("root_title") or binding.get("root_class") or "目标窗口"
        QToolTip.showText(QCursor.pos(), f"已绑定：{target_text}", row_data.get("bind_window"))
        if GLOBAL_CONFIG["log_to_ui"]:
            self.append_application_log(
                f"<font color='green'>按键映射已绑定：{target_text}；后台点击将只发送给该目标。</font>"
            )
        self.restore_settings_dialog_focus()
        return True

    def active_key_mappings(self):
        mappings = []
        for idx, row in enumerate(getattr(self, "key_mapping_rows", [])):
            if not row["enabled"].isChecked():
                continue
            coord = parse_coordinate_text(row["coord"].text())
            if not coord:
                continue
            parsed = parse_hotkey_text(row["hotkey"].text())
            if not parsed:
                continue
            mappings.append({
                "index": idx,
                "id": HOTKEY_ID_MAPPING_BASE + idx,
                "hotkey": parsed["display"],
                "normalized": parsed["text"],
                "vk": parsed["vk"],
                "modifiers": parsed["modifiers"],
                "bare": parsed["bare"],
                "safe_global": is_safe_global_hotkey(parsed),
                "coord": coord,
                "action": row["action"].currentText(),
                "window_binding": dict(row.get("window_binding", {})),
            })
        return mappings

    def execute_key_mapping_by_hotkey(self, hotkey_text):
        parsed = parse_hotkey_text(hotkey_text)
        if not parsed:
            return
        for item in self.active_key_mappings():
            if item.get("normalized") == parsed["text"]:
                self.execute_key_mapping(item["index"])
                return

    def current_mapping_click_mode(self):
        combo = getattr(self, "mapping_click_mode_combo", None)
        if not combo:
            return "真实鼠标点击"
        text = combo.currentText()
        return text if text else "真实鼠标点击"

    def perform_mapping_mouse_click(self, x, y, button, click_times, restore_position=False):
        return self.ensure_mapping_backend().foreground_click(
            x, y, button, click_times, restore_position=restore_position
        )

    def background_click_target_hwnd(
        self, x, y, expected_root=None, exclude_current_process=False
    ):
        return self.ensure_mapping_backend().background_click_target(
            x,
            y,
            expected_root=expected_root,
            exclude_current_process=exclude_current_process,
            belongs_callback=self.hwnd_belongs_to_current_process,
            top_level_callback=self.top_level_window_at_point,
            area_callback=self.hwnd_screen_area_at_point,
        )

    def window_matches_binding(self, hwnd, binding):
        return self.ensure_mapping_backend().matches_binding(hwnd, binding)

    def resolve_mapping_window_binding(self, binding):
        return self.ensure_mapping_backend().resolve_binding(binding)

    def perform_mapping_background_click(self, binding, button, click_times):
        return self.ensure_mapping_backend().background_click(binding, button, click_times)

    def perform_key_mapping_click(self, x, y, button, click_times, window_binding=None):
        mode = self.current_mapping_click_mode()
        if mode == "点击后返回原位":
            self.perform_mapping_mouse_click(x, y, button, click_times, restore_position=True)
            return mode
        if mode == "后台窗口点击(实验)":
            if self.perform_mapping_background_click(window_binding, button, click_times):
                method = str(
                    self.ensure_mapping_backend().last_background_method
                    or "窗口消息"
                )
                return f"{mode} · {method}"
            return f"{mode}失败，未执行点击"
        self.perform_mapping_mouse_click(x, y, button, click_times, restore_position=False)
        return mode

    def execute_key_mapping(self, map_idx):
        if self.engine.is_running:
            if GLOBAL_CONFIG["log_to_ui"]:
                self.append_application_log("<font color='gray'>脚本正在运行，已忽略按键映射，避免打断自动化流程。</font>")
            return
        mapping = None
        for item in self.active_key_mappings():
            if item["index"] == map_idx:
                mapping = item
                break
        if not mapping:
            return
        x, y = mapping["coord"]
        action = mapping["action"]
        button = "right" if "右键" in action else "left"
        click_times = 2 if "双击" in action else 1
        try:
            click_mode = self.perform_key_mapping_click(x, y, button, click_times, mapping.get("window_binding"))
            if "失败" in click_mode:
                if GLOBAL_CONFIG["log_to_ui"]:
                    self.append_application_log(f"<font color='orange'>按键映射{map_idx + 1} 后台点击失败，未执行任何点击；请重新绑定目标窗口或改用其他点击方式。</font>")
                QToolTip.showText(QCursor.pos(), "后台点击失败，未执行点击")
                return
            if getattr(self, "click_indicator_chk", None) is None or self.click_indicator_chk.isChecked():
                self.show_click_indicator_overlay({"x": x, "y": y, "text": f"映射{map_idx + 1}"})
            if GLOBAL_CONFIG["log_to_ui"]:
                self.append_application_log(f"<font color='gray'>按键映射{map_idx + 1} 已执行：{action} ({x},{y}) - {click_mode}</font>")
        except Exception as e:
            write_log(f"执行按键映射失败: {e}")

    def collect_coordinate_click_preview_points(self, max_points=800):
        tasks = self.get_current_ui_config().get("tasks", [])
        plan = build_coordinate_preview(tasks, max_points=max_points)
        return list(plan.points), plan.truncated, list(plan.labels), list(plan.line_segments)

    def preview_line_segments(self, step_groups, internal_segments=None):
        return build_preview_line_segments(step_groups, internal_segments)

    def show_all_coordinate_click_preview(self):
        points, truncated, labels, line_segments = self.collect_coordinate_click_preview_points()
        if not points:
            QMessageBox.information(self, "无法预览", "当前脚本没有可静态预览的坐标步骤。\n图片识别点击不会参与此预览。")
            return
        self.close_all_coordinate_click_preview()
        suffix = "，已截断前 800 个" if truncated else ""
        title = f"坐标总预览：{len(points)} 个点位{suffix}；左键/右键/Esc 可关闭"
        self.all_points_preview = CoordinateStepPreviewOverlay(
            points,
            {"direction": "全部坐标点击"},
            title=title,
            auto_close_ms=15000,
            draw_lines=True,
            detail_text="显示直接坐标点击、悬停、拖拽起终点和点位序列；图片识别点击需运行时识别后才知道位置。",
            point_labels=labels,
            line_segments=line_segments
        )
        self.all_points_preview.destroyed.connect(self.clear_all_coordinate_click_preview)

    def clear_all_coordinate_click_preview(self, *_):
        self.all_points_preview = None

    def close_all_coordinate_click_preview(self):
        preview = getattr(self, "all_points_preview", None)
        if preview:
            try:
                preview.close()
            except RuntimeError:
                pass
            self.all_points_preview = None

    def append_log(self, msg):
        started_ns = time.perf_counter_ns()
        try:
            scrollbar = self.log_text.verticalScrollBar()
            is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 5
            old_val = scrollbar.value()
            self.log_text.append(msg)
            if not is_at_bottom:
                scrollbar.setValue(old_val)
            else:
                scrollbar.setValue(scrollbar.maximum())
        finally:
            self.ui_performance.observe_since("ui.log_append", started_ns)
            self.ui_performance.increment("ui.log_messages")

    def current_log_mode(self):
        combo = getattr(self, "log_level_combo", None)
        value = combo.currentData() if combo is not None else LOG_MODE_SIMPLE
        return normalize_log_mode(value)

    def current_custom_log_categories(self):
        return normalize_log_categories(
            getattr(self, "_custom_log_categories", DEFAULT_CUSTOM_LOG_CATEGORIES)
        )

    def current_log_policy(self):
        return LogPolicy.create(
            self.current_log_mode(), self.current_custom_log_categories()
        )

    def _sync_log_category_actions(self, categories):
        selected = set(categories)
        self._log_control_sync = True
        try:
            for key, action in self.log_category_actions.items():
                action.setChecked(key in selected)
        finally:
            self._log_control_sync = False
        self.refresh_log_content_button()

    def refresh_log_content_button(self):
        if not getattr(self, "log_content_btn", None):
            return
        policy = self.current_log_policy()
        labels = policy.enabled_labels()
        self.log_content_btn.setText("内容...")
        self.log_content_btn.setToolTip(
            f"当前为{LOG_MODE_LABELS[policy.mode]}日志，共启用 {len(labels)} 项。\n"
            + ("、".join(labels) if labels else "仅输出错误、急停和严重警告")
        )

    def apply_log_controls(self, mode, custom_categories=None):
        normalized_mode = normalize_log_mode(mode)
        self._custom_log_categories = set(
            normalize_log_categories(
                custom_categories
                if custom_categories is not None
                else getattr(
                    self,
                    "_custom_log_categories",
                    DEFAULT_CUSTOM_LOG_CATEGORIES,
                )
            )
        )
        self._log_control_sync = True
        try:
            index = self.log_level_combo.findData(normalized_mode)
            self.log_level_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self._log_control_sync = False
        self._sync_log_category_actions(
            categories_for_mode(
                normalized_mode, self.current_custom_log_categories()
            )
        )

    def on_log_mode_selected(self, _index=None):
        if getattr(self, "_log_control_sync", False):
            return
        mode = self.current_log_mode()
        self._sync_log_category_actions(
            categories_for_mode(mode, self.current_custom_log_categories())
        )

    def on_log_category_toggled(self, _category=None):
        if getattr(self, "_log_control_sync", False):
            return
        self._custom_log_categories = {
            key
            for key, action in self.log_category_actions.items()
            if action.isChecked()
        }
        if self.current_log_mode() != LOG_MODE_CUSTOM:
            self._log_control_sync = True
            try:
                self.log_level_combo.setCurrentIndex(
                    self.log_level_combo.findData(LOG_MODE_CUSTOM)
                )
            finally:
                self._log_control_sync = False
        self.refresh_log_content_button()
        self.log_setting_change(
            "日志内容",
            f"自定义启用 {len(self._custom_log_categories)} 项",
        )

    def select_log_preset(self, mode):
        normalized_mode = normalize_log_mode(mode)
        index = self.log_level_combo.findData(normalized_mode)
        if index >= 0:
            self.log_level_combo.setCurrentIndex(index)
            if self.current_log_mode() == normalized_mode:
                self.on_log_mode_selected(index)

    def append_application_log(
        self, msg, category=LOG_APPLICATION, *, critical=False
    ):
        """Append a GUI-originated event using the active log policy."""
        policy = self.current_log_policy()
        if not policy.allows(
            category, critical=critical, message=msg
        ):
            return False
        if policy.timestamp_enabled:
            msg = f"[{format_local_timestamp()}] {msg}"
        self.append_log(msg)
        return True

    def validate_profile_config_data(self, cfg, label="方案"):
        return validate_profile_data(cfg, label)

    def validate_profiles_payload(self, profiles):
        return validate_profiles_data(profiles)

    def preserve_corrupt_config(self):
        try:
            return preserve_corrupt_config_file(self.config_path)
        except Exception as e:
            write_log(f"保存损坏配置副本失败: {e}")
            return ""

    def load_profiles_backup(self):
        return load_profiles_backup_file(self.profile_backup_path)

    def profiles_backup_payload(self):
        return build_profiles_backup_payload(self.profiles_data, self.current_profile_name)

    def persist_profiles_state(self, force=False):
        if getattr(self, "_profiles_persistence_blocked", False):
            if not self._profiles_block_warning_logged:
                write_log(
                    "方案自动保存处于只读保护状态：检测到不支持的方案版本，"
                    "未覆盖原配置或自动备份。"
                )
                self._profiles_block_warning_logged = True
            return True
        if self._profiles_save_in_progress or self.is_switching_profile:
            return True
        self._profiles_save_in_progress = True
        try:
            if self.current_profile_name and hasattr(self, "task_list"):
                self.profiles_data[self.current_profile_name] = self.get_current_ui_config()
            _payload_text, signature = profiles_signature(
                self.profiles_data, self.current_profile_name
            )
            if not force and signature == self._profiles_save_signature:
                return True

            self._profiles_save_signature = persist_profiles(
                self.settings,
                self.profile_backup_path,
                self.profiles_data,
                self.current_profile_name,
            )
            return True
        except Exception as e:
            write_log(f"自动保存配置失败: {e}")
            return False
        finally:
            self._profiles_save_in_progress = False

    def autosave_profiles_if_changed(self):
        if getattr(self, "_close_state_saved", False):
            return
        self.persist_profiles_state(force=False)

    def init_profiles(self):
        result = load_profiles_state(self.settings, self.config_path, self.profile_backup_path)
        self._profiles_persistence_blocked = bool(result.persistence_blocked)
        previous_message = self._config_recovery_message
        migrated = self.profile_model.replace(result.profiles, result.current_profile)
        archived_migration_backup = ""
        if (
            (migrated or result.migrated)
            and not self._profiles_persistence_blocked
        ):
            try:
                archived_migration_backup = archive_existing_backup(
                    self.profile_backup_path,
                    min_interval=0,
                )
            except Exception as error:
                write_log(f"升级方案前保存历史备份失败: {error}")
        if result.recovery_message:
            self._config_recovery_message = (
                f"{previous_message}\n\n{result.recovery_message}"
                if previous_message
                else result.recovery_message
            )
        elif previous_message:
            self._config_recovery_message = previous_message
        if archived_migration_backup:
            migration_message = (
                "方案格式已兼容升级；升级前的自动备份已保留在：\n"
                f"{archived_migration_backup}"
            )
            self._config_recovery_message = (
                f"{self._config_recovery_message}\n\n{migration_message}"
                if self._config_recovery_message
                else migration_message
            )
             
        self.profile_combo.addItems(list(self.profiles_data.keys()))
        last_prof = self.profile_model.current_name
        if last_prof in self.profiles_data:
            self.profile_combo.setCurrentText(last_prof)
        else:
            self.profile_combo.setCurrentIndex(0)
            
        self.is_switching_profile = False
        self.current_profile_name = self.profile_combo.currentText()
        self.apply_ui_config(self.profiles_data[self.current_profile_name])
        try:
            if self._config_recovery_message or migrated or result.migrated:
                self._profiles_save_signature = ""
                return
            _payload_text, self._profiles_save_signature = profiles_signature(
                self.profiles_data, self.current_profile_name
            )
        except Exception:
            self._profiles_save_signature = ""

    def get_default_config_dict(self):
        return default_profile_config()

    def get_current_ui_config(self):
        tasks = self.snapshot_tasks()
            
        log_policy = self.current_log_policy()
        config = dict(self.profiles_data.get(self.current_profile_name, {}))
        config.update({
            "_schema_version": default_profile_config()["_schema_version"],
            "conf": self.conf_edit.text(), "scale_min": self.scale_min.text(), "scale_max": self.scale_max.text(), "scale_step": self.scale_step.text(), "gray_en": self.gray_chk.isChecked(), "native_core_en": self.native_core_chk.isChecked(), "native_parallel_mode": self.native_parallel_combo.currentData() or "auto", "native_scale_hint_en": self.native_scale_hint_chk.isChecked(), "scale_memory_tier": self.scale_memory_tier_combo.currentData() or "balanced", "scale_memory_manual": self.scale_memory_manual_edit.text(), "scale_memory_custom_en": self.scale_memory_custom_chk.isChecked(), "scale_memory_preferred_limit": self.scale_memory_preferred_spin.value(), "scale_memory_history_limit": self.scale_memory_history_spin.value(),
            "dodge_x1": self.dodge_x1.text(), "dodge_y1": self.dodge_y1.text(), "dodge_x2": self.dodge_x2.text(), "dodge_y2": self.dodge_y2.text(),
            "dodge_en": self.dodge_chk.isChecked(), "dbl_dodge": self.double_dodge_chk.isChecked(), "dbl_wait": self.dbl_wait.text(), "dodge_click_action": self.dodge_click_combo.currentData() or "none",
            "move_spd": self.move_spd.text(), "click_hld": self.click_hld.text(), "settle": self.settle.text(), "timeout": self.timeout.text(), "timeout_stop": self.timeout_stop_chk.isChecked(), "detect_delay": self.detect_delay.text(), "adaptive_backoff": self.adaptive_backoff_chk.isChecked(), "scene_wake_en": self.scene_wake_chk.isChecked(), "scene_wake_sensitivity": self.scene_wake_sensitivity_combo.currentData() or "balanced", "playback_speed": self.playback_speed.text(),
            "multi_target_mode": self.multi_mode_combo.currentText(), "multi_target_order": self.multi_order_combo.currentText(),
            "hotkey_start": self.hotkey_start_edit.text().strip(), "hotkey_stop": self.hotkey_stop_edit.text().strip(), "log_level": log_policy.generation_level, "log_mode": log_policy.mode, "log_custom_categories": list(self.current_custom_log_categories()),
            "tm_fs": self.tm_failsafe.isChecked(), "tr_fs": self.tr_failsafe.isChecked(), "key_fs": self.key_failsafe.isChecked(),
            "log_f": self.log_file_chk.isChecked(), "log_ui": self.log_ui_chk.isChecked(), "mini": self.mini_chk.isChecked(), "top": self.top_chk.isChecked(),
            "run_status_tip": self.run_status_chk.isChecked(), "run_status_pos": self.run_status_pos_combo.currentText(), "click_indicator": self.click_indicator_chk.isChecked(), "start_step": self.start_step_edit.text(), "loop_start_round": self.loop_start_round_edit.text(), "loop_end_round": self.loop_end_round_edit.text(), "low_power_ui": self.low_power_ui_chk.isChecked(), "cpu_refresh_interval": self.cpu_refresh_combo.currentData(), "ui_scale": self.ui_scale_edit.text(),
            "loop_mode": self.loop_combo.currentText(), "loop_val": self.loop_val_edit.text(),
            "scan_region": self.engine.scan_region, "scan_regions": self.engine.scan_regions,
            "mapping_mode_enabled": self.mapping_mode_chk.isChecked(), "mapping_click_mode": self.mapping_click_mode_combo.currentText(), "key_mapping_count": len(getattr(self, "key_mapping_rows", [])), "key_mappings": self.get_key_mappings_config(),
            "tasks": tasks
        })
        return migrate_profile_config(config).value

    def apply_ui_config(self, cfg):
        try:
            cfg = migrate_profile_config(cfg).value
            self.conf_edit.setText(str(cfg.get("conf", "0.8")))
            self.scale_min.setText(str(cfg.get("scale_min", "0.8")))
            self.scale_max.setText(str(cfg.get("scale_max", "1.2")))
            self.scale_step.setText(str(cfg.get("scale_step", "0.05")))
            self.gray_chk.setChecked(config_bool(cfg.get("gray_en", True)))
            self.native_core_chk.setChecked(config_bool(cfg.get("native_core_en", True)))
            native_parallel_mode = str(cfg.get("native_parallel_mode", "auto"))
            native_parallel_index = self.native_parallel_combo.findData(
                native_parallel_mode
            )
            self.native_parallel_combo.setCurrentIndex(
                native_parallel_index if native_parallel_index >= 0 else 0
            )
            self.native_scale_hint_chk.setChecked(
                config_bool(cfg.get("native_scale_hint_en", True))
            )
            scale_memory_tier = str(cfg.get("scale_memory_tier", "balanced"))
            scale_memory_tier_index = self.scale_memory_tier_combo.findData(
                scale_memory_tier
            )
            self.scale_memory_tier_combo.setCurrentIndex(
                scale_memory_tier_index if scale_memory_tier_index >= 0 else 1
            )
            self.scale_memory_manual_edit.setText(
                str(cfg.get("scale_memory_manual", ""))
            )
            self.scale_memory_custom_chk.setChecked(
                config_bool(cfg.get("scale_memory_custom_en", False))
            )
            self.scale_memory_preferred_spin.setValue(
                int(cfg.get("scale_memory_preferred_limit", 3))
            )
            self.scale_memory_history_spin.setValue(
                int(cfg.get("scale_memory_history_limit", 64))
            )
            self.update_scale_memory_custom_ui()
            self.update_native_optimization_ui()
            self.dodge_x1.setText(str(cfg.get("dodge_x1", "100")))
            self.dodge_y1.setText(str(cfg.get("dodge_y1", "100")))
            self.dodge_x2.setText(str(cfg.get("dodge_x2", "200")))
            self.dodge_y2.setText(str(cfg.get("dodge_y2", "100")))
            self.dodge_chk.setChecked(config_bool(cfg.get("dodge_en", False)))
            self.double_dodge_chk.setChecked(config_bool(cfg.get("dbl_dodge", False)))
            self.dbl_wait.setText(str(cfg.get("dbl_wait", "0.015")))
            dodge_click_action = str(cfg.get("dodge_click_action", "none"))
            dodge_click_index = self.dodge_click_combo.findData(
                dodge_click_action
            )
            self.dodge_click_combo.setCurrentIndex(
                dodge_click_index if dodge_click_index >= 0 else 0
            )
            
            self.move_spd.setText(str(cfg.get("move_spd", "0.0")))
            self.click_hld.setText(str(cfg.get("click_hld", "0.04")))
            self.settle.setText(str(cfg.get("settle", "0.5")))
            self.timeout.setText(str(cfg.get("timeout", "0.0")))
            self.timeout_stop_chk.setChecked(config_bool(cfg.get("timeout_stop", False)))
            self.detect_delay.setText(str(cfg.get("detect_delay", "0.1")))
            self.adaptive_backoff_chk.setChecked(config_bool(cfg.get("adaptive_backoff", True)))
            self.scene_wake_chk.setChecked(
                config_bool(cfg.get("scene_wake_en", True))
            )
            scene_wake_sensitivity = str(
                cfg.get("scene_wake_sensitivity", "balanced")
            )
            scene_wake_index = self.scene_wake_sensitivity_combo.findData(
                scene_wake_sensitivity
            )
            self.scene_wake_sensitivity_combo.setCurrentIndex(
                scene_wake_index if scene_wake_index >= 0 else 1
            )
            self.scene_wake_sensitivity_combo.setEnabled(
                self.scene_wake_chk.isChecked()
            )
            self.playback_speed.setText(str(cfg.get("playback_speed", "1.0")))
            multi_target_mode = str(cfg.get("multi_target_mode", "快速一个"))
            if multi_target_mode == "最佳一个":
                multi_target_mode = "快速一个"
            if self.multi_mode_combo.findText(multi_target_mode) < 0:
                multi_target_mode = "快速一个"
            self.multi_mode_combo.setCurrentText(multi_target_mode)
            self.multi_order_combo.setCurrentText(str(cfg.get("multi_target_order", "从上到下")))
            self.update_multi_target_ui()
            
            start_parsed = parse_hotkey_text(cfg.get("hotkey_start", "F9"))
            stop_parsed = parse_hotkey_text(cfg.get("hotkey_stop", "F10"))
            self.hotkey_start_edit.setText(start_parsed["display"] if start_parsed else str(cfg.get("hotkey_start", "F9")))
            self.hotkey_stop_edit.setText(stop_parsed["display"] if stop_parsed else str(cfg.get("hotkey_stop", "F10")))
            self.apply_log_controls(
                normalize_log_mode(
                    cfg.get("log_mode"), cfg.get("log_level", 0)
                ),
                cfg.get(
                    "log_custom_categories", DEFAULT_CUSTOM_LOG_CATEGORIES
                ),
            )
            
            self.tm_failsafe.setChecked(config_bool(cfg.get("tm_fs", True)))
            self.tr_failsafe.setChecked(config_bool(cfg.get("tr_fs", True)))
            self.key_failsafe.setChecked(config_bool(cfg.get("key_fs", True)))
            
            self.log_file_chk.setChecked(config_bool(cfg.get("log_f", False)))
            self.log_ui_chk.setChecked(config_bool(cfg.get("log_ui", True)))
            self.mini_chk.setChecked(config_bool(cfg.get("mini", False)))
            self.top_chk.setChecked(config_bool(cfg.get("top", False)))
            self.run_status_chk.setChecked(config_bool(cfg.get("run_status_tip", True)))
            self.run_status_pos_combo.setCurrentText(str(cfg.get("run_status_pos", "右上角")))
            self.click_indicator_chk.setChecked(config_bool(cfg.get("click_indicator", True)))
            self.start_step_edit.setText(str(cfg.get("start_step", "1")))
            self.loop_start_round_edit.setText(str(cfg.get("loop_start_round", "1")))
            self.loop_end_round_edit.setText(str(cfg.get("loop_end_round", "0")))
            self.low_power_ui_chk.setChecked(config_bool(cfg.get("low_power_ui", True)))
            cpu_refresh = cfg.get("cpu_refresh_interval", "auto")
            cpu_refresh_index = self.cpu_refresh_combo.findData(cpu_refresh)
            if cpu_refresh_index < 0:
                try:
                    cpu_refresh_index = self.cpu_refresh_combo.findData(
                        int(cpu_refresh)
                    )
                except (TypeError, ValueError):
                    cpu_refresh_index = -1
            self.cpu_refresh_combo.setCurrentIndex(
                cpu_refresh_index if cpu_refresh_index >= 0 else 0
            )
            self.ui_scale_edit.setText(str(cfg.get("ui_scale", "100")))
            self.apply_ui_performance_mode()
            
            self.loop_combo.setCurrentText(str(cfg.get("loop_mode", "单次")))
            self.loop_val_edit.setText(str(cfg.get("loop_val", "10")))
            self.apply_scan_region_config(cfg.get("scan_region"), cfg.get("scan_regions"))
            self.mapping_mode_chk.setChecked(config_bool(cfg.get("mapping_mode_enabled", False)))
            self.mapping_click_mode_combo.setCurrentText(str(cfg.get("mapping_click_mode", "真实鼠标点击")))
            self.apply_key_mappings_config(cfg.get("key_mappings", []), cfg.get("key_mapping_count", None))
            
            self.close_all_task_config_dialogs()
            self.task_list.clear()
            tasks = cfg.get("tasks", [])
            for d in tasks: self.add_row(d)
            
            self.update_log_config()
            self.update_hotkeys()
            self.apply_ui_scale(self.parse_ui_scale_percent() / 100.0)
        except Exception as e:
            write_log(f"应用配置失败: {e}")

    def on_profile_changed(self, new_name):
        if self.is_switching_profile: return
        old_name = self.current_profile_name
        self.profiles_data[old_name] = self.get_current_ui_config()
        
        self.is_switching_profile = True
        selected = self.profile_model.select(new_name)
        self.apply_ui_config(selected)
        self.is_switching_profile = False
        
        if GLOBAL_CONFIG["log_to_ui"]:
            self.append_application_log(f"<b><font color='purple'>>>> 已切换至配置方案: {new_name}</font></b>")

    def create_new_profile(self):
        if len(self.profiles_data) >= MAX_PROFILES:
            QMessageBox.warning(self, "无法新建", f"方案数量已达到上限 {MAX_PROFILES}。")
            return
        text, ok = QInputDialog.getText(self, "新建方案", "请输入新方案名称:")
        if ok and text:
            if text in self.profiles_data:
                QMessageBox.warning(self, "错误", "方案名称已存在！")
                return
            self.profiles_data[self.current_profile_name] = self.get_current_ui_config()
            created = self.profile_model.create(text)
            self.is_switching_profile = True
            self.profile_combo.addItem(text)
            self.profile_combo.setCurrentText(text)
            self.apply_ui_config(created)
            self.is_switching_profile = False
            
    def rename_current_profile(self):
        old_name = self.current_profile_name
        text, ok = QInputDialog.getText(self, "重命名方案", "请输入新的方案名称:", QLineEdit.Normal, old_name)
        if ok and text and text != old_name:
            if text in self.profiles_data:
                QMessageBox.warning(self, "错误", "方案名称已存在！")
                return
            self.profiles_data[old_name] = self.get_current_ui_config()
            self.profile_model.rename(text)
            self.is_switching_profile = True
            idx = self.profile_combo.findText(old_name)
            if idx >= 0: self.profile_combo.setItemText(idx, text)
            self.is_switching_profile = False
            if GLOBAL_CONFIG["log_to_ui"]:
                self.append_application_log(f"<font color='#FF9800'><b>>>> 方案已重命名: {old_name} -> {text}</b></font>")

    def delete_current_profile(self):
        if len(self.profiles_data) <= 1:
            QMessageBox.warning(self, "错误", "至少需要保留一个方案！")
            return
        del_name = self.current_profile_name
        self.profile_model.delete_current()
        
        self.is_switching_profile = True
        idx = self.profile_combo.findText(del_name)
        if idx >= 0: self.profile_combo.removeItem(idx)
            
        self.profile_combo.setCurrentText(self.current_profile_name)
            
        self.apply_ui_config(self.profiles_data[self.current_profile_name])
        self.is_switching_profile = False

    def move_profile_up(self):
        idx = self.profile_combo.currentIndex()
        if idx > 0:
            target = self.profile_model.move_current(-1)
            keys = list(self.profiles_data.keys())
            self.is_switching_profile = True
            self.profile_combo.clear()
            self.profile_combo.addItems(keys)
            self.profile_combo.setCurrentIndex(target)
            self.is_switching_profile = False

    def move_profile_down(self):
        idx = self.profile_combo.currentIndex()
        keys = list(self.profiles_data.keys())
        if idx < len(keys) - 1:
            target = self.profile_model.move_current(1)
            keys = list(self.profiles_data.keys())
            self.is_switching_profile = True
            self.profile_combo.clear()
            self.profile_combo.addItems(keys)
            self.profile_combo.setCurrentIndex(target)
            self.is_switching_profile = False

    def start_recording(self):
        if getattr(self, "recorder_ui", None):
            try:
                self.recorder_ui.close()
            except RuntimeError:
                pass
        self.showMinimized()
        self.recorder_ui = RecorderUI(self)
        recorder = self.recorder_ui
        recorder.destroyed.connect(
            lambda *_args, r=recorder: setattr(self, "recorder_ui", None)
            if getattr(self, "recorder_ui", None) is r else None
        )

    def bind_setting_logs(self):
        self.conf_edit.editingFinished.connect(lambda: self.log_setting_change("相似度", self.conf_edit.text()))
        self.scale_min.editingFinished.connect(lambda: self.log_setting_change("最小缩放", self.scale_min.text()))
        self.scale_max.editingFinished.connect(lambda: self.log_setting_change("最大缩放", self.scale_max.text()))
        self.scale_step.editingFinished.connect(lambda: self.log_setting_change("缩放步长", self.scale_step.text()))
        self.dodge_x1.editingFinished.connect(lambda: self.log_setting_change("避让坐标1 X", self.dodge_x1.text()))
        self.dodge_y1.editingFinished.connect(lambda: self.log_setting_change("避让坐标1 Y", self.dodge_y1.text()))
        self.dodge_x2.editingFinished.connect(lambda: self.log_setting_change("避让坐标2 X", self.dodge_x2.text()))
        self.dodge_y2.editingFinished.connect(lambda: self.log_setting_change("避让坐标2 Y", self.dodge_y2.text()))
        self.dbl_wait.editingFinished.connect(lambda: self.log_setting_change("二段避让间隔(s)", self.dbl_wait.text()))
        self.move_spd.editingFinished.connect(lambda: self.log_setting_change("移动耗时(s)", self.move_spd.text()))
        self.click_hld.editingFinished.connect(lambda: self.log_setting_change("按住时长(s)", self.click_hld.text()))
        self.settle.editingFinished.connect(lambda: self.log_setting_change("步间隔(s)", self.settle.text()))
        self.timeout.editingFinished.connect(lambda: self.log_setting_change("单步超时(s)", self.timeout.text()))
        self.detect_delay.editingFinished.connect(lambda: self.log_setting_change("识别频率(s)", self.detect_delay.text()))
        self.playback_speed.editingFinished.connect(lambda: self.log_setting_change("倍速执行", self.playback_speed.text()))
        self.loop_val_edit.editingFinished.connect(lambda: self.log_setting_change("循环参数", self.loop_val_edit.text()))
        self.start_step_edit.editingFinished.connect(lambda: self.log_setting_change("从第X步开始", self.start_step_edit.text()))
        self.loop_start_round_edit.editingFinished.connect(lambda: self.log_setting_change("脚本起始循环", self.loop_start_round_edit.text()))
        self.loop_end_round_edit.editingFinished.connect(lambda: self.log_setting_change("脚本停止循环", self.loop_end_round_edit.text()))
        self.ui_scale_edit.editingFinished.connect(self.apply_ui_scale_from_edit)

        self.gray_chk.stateChanged.connect(lambda s: self.log_setting_change("灰度匹配", "开启" if s else "关闭"))
        self.native_core_chk.stateChanged.connect(lambda s: self.log_setting_change("DLL原生识别", "开启" if s else "关闭"))
        self.native_core_chk.toggled.connect(self.update_native_optimization_ui)
        self.native_parallel_combo.currentTextChanged.connect(
            lambda text: self.log_setting_change("原生多核", text)
        )
        self.native_scale_hint_chk.stateChanged.connect(
            lambda state: self.log_setting_change(
                "缩放记忆", "开启" if state else "关闭"
            )
        )
        self.native_scale_hint_chk.toggled.connect(self.refresh_scale_memory_status)
        self.scale_memory_tier_combo.currentTextChanged.connect(
            lambda text: self.log_setting_change("缩放记忆策略", text)
        )
        self.scale_memory_tier_combo.currentIndexChanged.connect(
            self.refresh_scale_memory_status
        )
        self.scale_memory_manual_edit.editingFinished.connect(
            lambda: self.log_setting_change(
                "手动优先倍率", self.scale_memory_manual_edit.text() or "未设置"
            )
        )
        self.scale_memory_manual_edit.editingFinished.connect(
            self.refresh_scale_memory_status
        )
        self.scale_memory_custom_chk.toggled.connect(
            self.update_scale_memory_custom_ui
        )
        self.scale_memory_custom_chk.toggled.connect(
            self.refresh_scale_memory_status
        )
        self.scale_memory_custom_chk.stateChanged.connect(
            lambda state: self.log_setting_change(
                "自定义记忆容量", "开启" if state else "关闭"
            )
        )
        self.scale_memory_preferred_spin.valueChanged.connect(
            lambda value: self.log_setting_change("学习优先倍率上限", value)
        )
        self.scale_memory_preferred_spin.valueChanged.connect(
            self.refresh_scale_memory_status
        )
        self.scale_memory_history_spin.valueChanged.connect(
            lambda value: self.log_setting_change("缩放历史记录上限", value)
        )
        self.scale_memory_history_spin.valueChanged.connect(
            self.refresh_scale_memory_status
        )
        self.scale_memory_clear_btn.clicked.connect(self.clear_scale_memory_session)
        self.dodge_chk.stateChanged.connect(lambda s: self.log_setting_change("启用避让", "开启" if s else "关闭"))
        self.double_dodge_chk.stateChanged.connect(lambda s: self.log_setting_change("二段避让", "开启" if s else "关闭"))
        self.dodge_click_combo.currentTextChanged.connect(
            lambda text: self.log_setting_change("避让后操作", text)
        )
        self.tm_failsafe.stateChanged.connect(lambda s: self.log_setting_change("任务管理器急停", "开启" if s else "关闭"))
        self.tr_failsafe.stateChanged.connect(lambda s: self.log_setting_change("右上角急停", "开启" if s else "关闭"))
        self.key_failsafe.stateChanged.connect(lambda s: self.log_setting_change("ESC/中键急停", "开启" if s else "关闭"))
        self.log_file_chk.stateChanged.connect(lambda s: self.log_setting_change("写入文件日志", "开启" if s else "关闭"))
        self.log_ui_chk.stateChanged.connect(lambda s: self.log_setting_change("显示界面日志", "开启" if s else "关闭"))
        self.mini_chk.stateChanged.connect(lambda s: self.log_setting_change("启动时最小化", "开启" if s else "关闭"))
        self.top_chk.stateChanged.connect(lambda s: self.log_setting_change("窗口置顶", "开启" if s else "关闭"))
        self.run_status_chk.stateChanged.connect(lambda s: self.log_setting_change("运行状态提示", "开启" if s else "关闭"))
        self.click_indicator_chk.stateChanged.connect(lambda s: self.log_setting_change("点击位置提示", "开启" if s else "关闭"))
        self.timeout_stop_chk.stateChanged.connect(lambda s: self.log_setting_change("超时急停", "开启" if s else "关闭"))
        self.low_power_ui_chk.stateChanged.connect(lambda s: self.log_setting_change("省电UI模式", "开启" if s else "关闭"))
        self.cpu_refresh_combo.currentTextChanged.connect(
            lambda text: self.log_setting_change("资源监测刷新", text)
        )
        self.adaptive_backoff_chk.stateChanged.connect(lambda s: self.log_setting_change("自适应降频", "开启" if s else "关闭"))
        self.scene_wake_chk.stateChanged.connect(
            lambda state: self.log_setting_change(
                "画面变化唤醒", "开启" if state else "关闭"
            )
        )
        self.scene_wake_chk.toggled.connect(
            self.scene_wake_sensitivity_combo.setEnabled
        )
        self.scene_wake_sensitivity_combo.currentTextChanged.connect(
            lambda text: self.log_setting_change("画面变化灵敏度", text)
        )
        self.mapping_mode_chk.stateChanged.connect(lambda s: self.log_setting_change("按键映射模式", "开启" if s else "关闭"))
        self.mapping_click_mode_combo.currentTextChanged.connect(lambda t: self.log_setting_change("映射点击方式", t))
        
        self.hotkey_start_edit.editingFinished.connect(lambda: self.log_setting_change("启动热键", self.hotkey_start_edit.text()))
        self.hotkey_stop_edit.editingFinished.connect(lambda: self.log_setting_change("停止热键", self.hotkey_stop_edit.text()))
        self.log_level_combo.currentTextChanged.connect(lambda t: self.log_setting_change("日志级别", t))
        self.log_level_combo.currentTextChanged.connect(self.warn_heavy_log_level)
        self.loop_combo.currentTextChanged.connect(lambda t: self.log_setting_change("循环模式", t))
        self.multi_mode_combo.currentTextChanged.connect(lambda t: self.log_setting_change("多目标模式", t))
        self.multi_order_combo.currentTextChanged.connect(lambda t: self.log_setting_change("多目标顺序", t))
        self.run_status_pos_combo.currentTextChanged.connect(lambda t: self.log_setting_change("运行提示位置", t))

    def log_setting_change(self, name, value):
        if GLOBAL_CONFIG["log_to_ui"] and not self.is_switching_profile:
            self.append_application_log(f"<font color='#FF9800'><b>设置已生效：</b>{name} -> {value}</font>")

    def warn_heavy_log_level(self, text):
        if self.is_switching_profile or text == "简易":
            return
        if self.settings.value("ack_heavy_log_warning", "") == "1":
            return
        QMessageBox.warning(
            self,
            "日志性能提示",
            "“详细”会记录带本地时间的流程细节；“完全”还会逐步记录运行参数、"
            "各阶段耗时和底层统计；“自定义”的开销取决于勾选项目。"
            "这些模式会更频繁地刷新界面，尤其是启用完整调试内容时。\n\n"
            "如果运行时感觉卡顿，可以切回“简易”，或者关闭“界面日志”。"
        )
        self.settings.setValue("ack_heavy_log_warning", "1")

    def update_loop_ui(self, text):
        if text in ["指定次数", "指定时间(时)", "指定时间(分)", "指定时间(秒)"]:
            self.loop_val_edit.show()
        else:
            self.loop_val_edit.hide()

    def update_multi_target_ui(self, _=None):
        self.multi_order_combo.setEnabled(self.multi_mode_combo.currentText() == "全部匹配")

    def update_native_optimization_ui(self, _=None):
        enabled = self.native_core_chk.isChecked()
        self.native_parallel_combo.setEnabled(enabled)

    def update_scale_memory_custom_ui(self, _=None):
        enabled = self.scale_memory_custom_chk.isChecked()
        self.scale_memory_preferred_spin.setEnabled(enabled)
        self.scale_memory_history_spin.setEnabled(enabled)

    def current_scale_memory_policy(self):
        try:
            manual_scales = parse_manual_scales(
                self.scale_memory_manual_edit.text()
            )
        except ValueError:
            manual_scales = ()
        return ScaleMemoryPolicy(
            enabled=self.native_scale_hint_chk.isChecked(),
            tier=self.scale_memory_tier_combo.currentData() or "balanced",
            manual_scales=manual_scales,
            custom_enabled=self.scale_memory_custom_chk.isChecked(),
            preferred_limit=self.scale_memory_preferred_spin.value(),
            history_limit=self.scale_memory_history_spin.value(),
        ).normalized()

    def refresh_scale_memory_status(self):
        if not getattr(self, "scale_memory_status_label", None):
            return
        policy = self.current_scale_memory_policy()
        if not policy.enabled:
            self.scale_memory_status_label.setText(
                "缩放记忆已关闭；本次启动中已有的学习记录会保留，但不会参与搜索。"
            )
            return
        summaries = self.engine.scale_memory_store.summaries(policy, maximum=6)
        if not summaries:
            manual = format_manual_scales(policy.manual_scales)
            suffix = f"；手动优先倍率：[{manual}]" if manual else ""
            self.scale_memory_status_label.setText(
                "本次启动尚未学习到缩放倍率；首次成功识别后会显示当前优先倍率和算法历史上限"
                f"{suffix}。"
            )
            return
        self.scale_memory_status_label.setText(
            "\n".join(summary.status_text() for summary in summaries)
        )

    def clear_scale_memory_session(self):
        self.engine.scale_memory_store.clear()
        self.refresh_scale_memory_status()
        self.log_setting_change("缩放记忆", "已清除本次自动学习记录")

    def normalize_region_list(self, regions):
        normalized = []
        for region in regions or []:
            try:
                x, y, w, h = [int(float(v)) for v in region]
                if w > 0 and h > 0:
                    normalized.append((x, y, w, h))
            except Exception:
                continue
        return normalized

    def update_region_label(self):
        regions = self.normalize_region_list(getattr(self.engine, "scan_regions", []))
        if regions:
            self.region_label.setText(f"范围: 多区域 {len(regions)} 个")
            return
        if self.engine.scan_region:
            self.region_label.setText(f"范围(物理): {self.engine.scan_region}")
        else:
            self.region_label.setText("范围: 全屏")

    def apply_scan_region_config(self, scan_region=None, scan_regions=None):
        regions = self.normalize_region_list(scan_regions)
        if regions:
            self.engine.scan_regions = regions
            self.engine.scan_region = regions[0] if len(regions) == 1 else None
            self.update_region_label()
            return

        single = self.normalize_region_list([scan_region])
        self.engine.scan_regions = []
        self.engine.scan_region = single[0] if single else None
        self.update_region_label()

    def hotkey_hwnd(self):
        return wintypes.HWND(int(self.winId()))

    def validate_control_hotkey(self, text, default_text, label):
        parsed = parse_hotkey_text(text)
        if parsed and is_safe_global_hotkey(parsed):
            return parsed
        fallback = parse_hotkey_text(default_text)
        if not getattr(self, "is_switching_profile", False):
            QMessageBox.warning(
                self,
                "热键设置无效",
                f"{label}不能使用裸字母、裸数字、空格或回车这类容易误触的单键。\n"
                f"请使用 Ctrl/Alt/Shift/Win 组合键，或 F1-F12 等功能键。\n"
                f"已临时恢复为 {fallback['display']}。"
            )
        return fallback

    def stop_key_mapping_hook(self):
        hook = getattr(self, "key_mapping_hook", None)
        if hook and hook.isRunning():
            hook.stop()
            if not hook.wait(1500):
                write_log("按键映射钩子未能在限定时间内停止，暂不创建新的钩子。")
                return False
        self.key_mapping_hook = None
        self.mapping_hook_hotkeys = set()
        return True

    def refresh_mapping_mode_hook(self):
        if getattr(self, "_bulk_mapping_update", False):
            return
        if not getattr(self, "mapping_mode_chk", None):
            return
        wanted = set()
        if self.mapping_mode_chk.isChecked():
            for mapping in self.active_key_mappings():
                if mapping.get("bare") and not mapping.get("safe_global"):
                    wanted.add(mapping.get("normalized"))
        wanted.discard(None)

        if not wanted:
            self.stop_key_mapping_hook()
            return
        if getattr(self, "key_mapping_hook", None) and self.key_mapping_hook.isRunning() and wanted == getattr(self, "mapping_hook_hotkeys", set()):
            return
        if not self.stop_key_mapping_hook():
            return
        self.mapping_hook_hotkeys = set(wanted)
        self.key_mapping_hook = KeyMappingHookThread(self.mapping_hook_hotkeys)
        self.key_mapping_hook.triggered.connect(self.execute_key_mapping_by_hotkey)
        self.key_mapping_hook.start()

    def unregister_global_hotkeys(self):
        hwnd = self.hotkey_hwnd()
        hotkey_ids = [HOTKEY_ID_START, HOTKEY_ID_STOP] + list(getattr(self, "mapping_hotkey_ids", {}).keys())
        for hotkey_id in hotkey_ids:
            try:
                user32.UnregisterHotKey(hwnd, hotkey_id)
            except Exception:
                pass
        self.mapping_hotkey_ids = {}
        self.global_hotkeys_registered = False

    def register_global_hotkeys(self):
        try:
            self.unregister_global_hotkeys()
            hwnd = self.hotkey_hwnd()
            start_ok = bool(user32.RegisterHotKey(
                hwnd, HOTKEY_ID_START,
                self.hotkey_start_parsed["modifiers"] | MOD_NOREPEAT,
                self.hotkey_start_parsed["vk"]
            ))
            stop_ok = bool(user32.RegisterHotKey(
                hwnd, HOTKEY_ID_STOP,
                self.hotkey_stop_parsed["modifiers"] | MOD_NOREPEAT,
                self.hotkey_stop_parsed["vk"]
            ))
            if start_ok and stop_ok:
                self.mapping_hotkey_ids = {}
                used_hotkeys = {hotkey_signature(self.hotkey_start_parsed), hotkey_signature(self.hotkey_stop_parsed)}
                for mapping in self.active_key_mappings():
                    sig = (mapping["modifiers"], mapping["vk"])
                    if sig in used_hotkeys:
                        write_log(f"按键映射{mapping['index'] + 1}热键 {mapping['hotkey']} 与启动/停止热键冲突，已跳过。")
                        continue
                    if not mapping.get("safe_global"):
                        if not getattr(self, "mapping_mode_chk", None) or not self.mapping_mode_chk.isChecked():
                            write_log(f"按键映射{mapping['index'] + 1}热键 {mapping['hotkey']} 是裸键，需要开启按键映射模式后才会生效。")
                        continue
                    ok = bool(user32.RegisterHotKey(hwnd, mapping["id"], mapping["modifiers"] | MOD_NOREPEAT, mapping["vk"]))
                    if ok:
                        self.mapping_hotkey_ids[mapping["id"]] = mapping["index"]
                        used_hotkeys.add(sig)
                    else:
                        write_log(f"按键映射{mapping['index'] + 1}热键 {mapping['hotkey']} 注册失败，可能已被占用。")
                self.global_hotkeys_registered = True
                return True
            write_log("注册全局热键失败，可能热键已被其他程序占用，回退到轮询模式。")
            self.unregister_global_hotkeys()
        except Exception as e:
            write_log(f"注册全局热键失败，回退到轮询模式: {e}")
        self.global_hotkeys_registered = False
        return False

    def refresh_hotkey_backend(self):
        if getattr(self, "_bulk_mapping_update", False):
            return
        if not getattr(self, "hotkey_timer", None):
            return
        if self.register_global_hotkeys():
            self.hotkey_timer.stop()
        else:
            self.hotkey_timer.start(self.current_hotkey_interval())
        self.refresh_mapping_mode_hook()

    def nativeEvent(self, eventType, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_ID_START and not self.engine.is_running:
                    QTimer.singleShot(0, self.start_task)
                    return True, 0
                if msg.wParam == HOTKEY_ID_STOP and self.engine.is_running:
                    QTimer.singleShot(0, self.stop_task)
                    return True, 0
                map_idx = self.mapping_hotkey_ids.get(int(msg.wParam))
                if map_idx is not None:
                    QTimer.singleShot(0, lambda i=map_idx: self.execute_key_mapping(i))
                    return True, 0
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

    def update_hotkeys(self, _=None):
        try:
            start_parsed = self.validate_control_hotkey(self.hotkey_start_edit.text(), "F9", "启动热键")
            stop_parsed = self.validate_control_hotkey(self.hotkey_stop_edit.text(), "F10", "停止热键")
            if hotkey_signature(start_parsed) == hotkey_signature(stop_parsed):
                if not getattr(self, "is_switching_profile", False):
                    QMessageBox.warning(self, "热键冲突", "启动热键和停止热键不能相同，停止热键已恢复为 F10。")
                stop_parsed = parse_hotkey_text("F10")
                if hotkey_signature(start_parsed) == hotkey_signature(stop_parsed):
                    stop_parsed = parse_hotkey_text("F9")
            self.hotkey_start_parsed = start_parsed
            self.hotkey_stop_parsed = stop_parsed
            self.hotkey_start_vk = start_parsed["vk"]
            self.hotkey_stop_vk = stop_parsed["vk"]
            self.hotkey_start_edit.setText(start_parsed["display"])
            self.hotkey_stop_edit.setText(stop_parsed["display"])
            self.start_btn.setText(f"启动 ({start_parsed['display']})")
            self.stop_btn.setText(f"停止 ({stop_parsed['display']})")
            self.refresh_hotkey_backend()
        except Exception as e:
            write_log(f"更新热键失败: {e}")

    def toggle_top_window(self):
        """使用 Win32 API 切换置顶，避免 setWindowFlags 重建窗口导致标题栏异常。"""
        should_be_top = self.top_chk.isChecked()
        hwnd = wintypes.HWND(int(self.winId()))
        insert_after = HWND_TOPMOST if should_be_top else HWND_NOTOPMOST
        swp_flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER

        if self.isVisible():
            swp_flags |= SWP_SHOWWINDOW

        if not user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, swp_flags):
            err = kernel32.GetLastError()
            write_log(f"切换窗口置顶失败: WinError {err}")

    def check_hotkey(self):
        pressed_now = set()
        if hotkey_is_down(getattr(self, "hotkey_start_parsed", None)):
            pressed_now.add("start")
        if hotkey_is_down(getattr(self, "hotkey_stop_parsed", None)):
            pressed_now.add("stop")

        mapping_pressed = set()
        mapping_to_execute = None
        if not self.engine.is_running:
            seen_mappings = set()
            for mapping in self.active_key_mappings():
                normalized = mapping.get("normalized")
                if not normalized or normalized in seen_mappings:
                    continue
                seen_mappings.add(normalized)
                if not mapping.get("safe_global"):
                    continue
                parsed = parse_hotkey_text(normalized)
                if hotkey_is_down(parsed):
                    mapping_pressed.add(normalized)
                    if normalized not in self.mapping_poll_pressed and mapping_to_execute is None:
                        mapping_to_execute = mapping["index"]

        if "start" in pressed_now and "start" not in self.hotkey_poll_pressed and not self.engine.is_running:
            self.start_task()
            self.hotkey_poll_pressed = pressed_now
            self.mapping_poll_pressed = mapping_pressed
            return

        if "stop" in pressed_now and "stop" not in self.hotkey_poll_pressed and self.engine.is_running:
            self.stop_task()
            self.hotkey_poll_pressed = pressed_now
            self.mapping_poll_pressed = mapping_pressed
            return

        if mapping_to_execute is not None:
            self.execute_key_mapping(mapping_to_execute)
            self.hotkey_poll_pressed = pressed_now
            self.mapping_poll_pressed = mapping_pressed
            return
        self.hotkey_poll_pressed = pressed_now
        self.mapping_poll_pressed = mapping_pressed

    def open_region_selector(self):
        self.region_win = RegionWindow(multi=True)
        self.region_win.regions_selected.connect(self.on_regions_selected)

    def open_multi_region_selector(self):
        self.open_region_selector()

    def on_region_selected(self, rect_tuple):
        self.engine.scan_region = rect_tuple
        self.engine.scan_regions = []
        self.update_region_label()
        self.append_application_log(f"已锁定游戏区域(物理): {rect_tuple} (速度+++)")

    def on_regions_selected(self, rects):
        regions = self.normalize_region_list(rects)
        if not regions:
            return
        self.engine.scan_regions = regions
        self.engine.scan_region = regions[0] if len(regions) == 1 else None
        self.update_region_label()
        self.append_application_log(f"已锁定 {len(regions)} 个识别区域(物理)，只在这些区域内找图 (速度+++)") 

    def closeEvent(self, event):
        try:
            integrity_worker = getattr(self, "integrity_worker", None)
            if integrity_worker and integrity_worker.isRunning():
                integrity_worker.requestInterruption()
                if not integrity_worker.wait(1500):
                    event.ignore()
                    QTimer.singleShot(100, self.close)
                    return
            if not self._close_state_saved:
                if getattr(self, "profiles_autosave_timer", None):
                    self.profiles_autosave_timer.stop()
                if not self.stop_key_mapping_hook():
                    event.ignore()
                    QTimer.singleShot(100, self.close)
                    return
                self.unregister_global_hotkeys()
                self.settings.setValue("window_geometry", self.saveGeometry())
                if getattr(self, "settings_dialog", None):
                    self.settings_dialog.save_dialog_geometry()
                self._shutdown_save_ok = self.persist_profiles_state(force=True)
                self.settings.sync()
                self._close_state_saved = True

            if getattr(self, "recorder_ui", None):
                self.recorder_ui.close()
            if getattr(self, "region_win", None):
                self.region_win.close()
            if getattr(self, "settings_dialog", None):
                self.settings_dialog.close()
            self.close_all_task_config_dialogs()
            for picker in list(getattr(self, "mapping_pickers", {}).values()):
                try:
                    picker.close()
                except RuntimeError:
                    pass
            for picker in list(getattr(self, "dodge_pickers", {}).values()):
                try:
                    picker.close()
                except RuntimeError:
                    pass
            for inspector in list(
                getattr(self, "mapping_inspector_dialogs", set())
            ):
                try:
                    inspector.close()
                except RuntimeError:
                    pass

            self.close_all_coordinate_click_preview()
            for overlay in list(getattr(self, "click_indicator_overlays", [])):
                try:
                    overlay.close()
                except RuntimeError:
                    pass
            
            if getattr(self, 'worker', None) and self.worker.isRunning():
                self._close_after_worker = True
                self.engine.stop()
                self.centralWidget().setEnabled(False)
                self.setWindowTitle(f"{PRODUCT_NAME} {APP_VERSION} - 正在安全停止脚本…")
                event.ignore()
                return
            if self.running_overlay:
                self.running_overlay.close()
            self.close_all_coordinate_click_preview()
            if self.mapping_backend is not None:
                self.mapping_backend.close()
        except Exception as e:
            write_log(f"退出前保存异常: {e}")
        if getattr(self, "_shutdown_save_ok", True):
            try:
                self.session_guard.close()
            except Exception as error:
                write_log(f"清理会话标记失败: {error}")
        event.accept()

    def update_log_config(self):
        GLOBAL_CONFIG["log_to_file"] = self.log_file_chk.isChecked()
        GLOBAL_CONFIG["log_to_ui"] = self.log_ui_chk.isChecked()

    def update_cpu_info(self):
        logical_count = os.cpu_count() or 0
        sys_usage = "--"
        proc_usage = "--"
        if HAS_PSUTIL and self.current_process:
            try:
                logical_count = psutil.cpu_count(logical=True) or logical_count
                sys_usage = f"{psutil.cpu_percent(interval=None):.1f}"
                raw_usage = self.current_process.cpu_percent(interval=None)
                proc_usage = f"{raw_usage:.1f}"
            except Exception: pass
        self.cpu_label.setText(
            f"逻辑处理器: {logical_count or '--'} | 系统 CPU: {sys_usage}% | "
            f"本程序 CPU: {proc_usage}%"
        )

    def update_indexes(self):
        if getattr(self, "task_count_label", None):
            self.task_count_label.setText(f"{self.task_list.count()} 步")
        entries = []
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            widget = self.task_list.itemWidget(item)
            if widget is None:
                data = item.data(Qt.UserRole)
                if data:
                    self.restore_row_widget(item, data)
                    widget = self.task_list.itemWidget(item)
            entries.append((item, widget))

        normalized = normalize_workflow_tasks(
            [
                widget.get_data() if widget else item.data(Qt.UserRole)
                for item, widget in entries
            ]
        )
        reference_keys = {"step_id"}
        for jump_field, target_field, _label in REFERENCE_FIELDS:
            reference_keys.update((jump_field, target_field))
        for index, ((item, widget), normalized_data) in enumerate(
            zip(entries, normalized)
        ):
            if widget:
                widget.custom_data.update(
                    {
                        key: normalized_data.get(key, "")
                        for key in reference_keys
                    }
                )
            if widget and hasattr(widget, 'set_index'):
                widget.set_index(index + 1)
                item.setData(Qt.UserRole, widget.get_data())
                if hasattr(widget, 'drag_summary'):
                    item.setData(Qt.UserRole + 1, widget.drag_summary())
                item.setText("")
        self.update_selection_highlight()

    def selected_row_index(self):
        row = self.task_list.currentRow()
        return row if row >= 0 else None

    def snapshot_tasks(self):
        tasks = []
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            widget = self.task_list.itemWidget(item)
            if widget:
                tasks.append(widget.get_data())
            else:
                tasks.append(item.data(Qt.UserRole))
        normalized = normalize_workflow_tasks(tasks)
        return json.loads(json.dumps(normalized, ensure_ascii=False))

    def resolve_task_reference_edits(self, row_widget, updated):
        tasks = self.snapshot_tasks()
        row_index = None
        for index in range(self.task_list.count()):
            item = self.task_list.item(index)
            if self.task_list.itemWidget(item) is row_widget:
                row_index = index
                break
        if row_index is None:
            return updated
        current_id = str(tasks[row_index].get("step_id", ""))
        edited = dict(updated)
        edited["step_id"] = current_id
        tasks[row_index] = edited
        return apply_numeric_reference_edits(edited, tasks)

    def push_undo_state(self):
        if self.restoring_history or self.is_switching_profile:
            return
        self.undo_stack.append(self.snapshot_tasks())
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def push_undo_snapshot(self, tasks):
        if self.restoring_history or self.is_switching_profile or tasks is None:
            return
        snapshot = json.loads(json.dumps(tasks, ensure_ascii=False))
        if snapshot == self.snapshot_tasks():
            return
        if not self.undo_stack or self.undo_stack[-1] != snapshot:
            self.undo_stack.append(snapshot)
            if len(self.undo_stack) > 50:
                self.undo_stack.pop(0)
        self.redo_stack.clear()

    def restore_task_snapshot(self, tasks):
        self.restoring_history = True
        try:
            self.close_all_task_config_dialogs()
            self.task_list.clear()
            for data in tasks:
                self.add_row(data, record_undo=False, select=False)
            self.update_indexes()
        finally:
            self.restoring_history = False

    def restore_row_widget(self, item, data):
        row_widget = TaskRow(delete_callback=self.del_row)
        if data:
            row_widget.set_data(data)
        item.setSizeHint(row_widget.sizeHint())
        self.task_list.setItemWidget(item, row_widget)
        row_widget.set_parent_item(item)
        item.setData(Qt.UserRole, row_widget.get_data())
        item.setData(Qt.UserRole + 1, row_widget.drag_summary())
        item.setText("")

    def update_selection_highlight(self):
        current = self.task_list.currentItem()
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            widget = self.task_list.itemWidget(item)
            if widget and hasattr(widget, "set_selected"):
                widget.set_selected(item is current)

    def add_row(self, data=None, index=None, record_undo=True, select=True):
        if record_undo:
            self.push_undo_state()
        row_widget = TaskRow(delete_callback=self.del_row)
        if data: row_widget.set_data(data)
        item = QListWidgetItem()
        item.setSizeHint(row_widget.sizeHint())
        if index is None:
            self.task_list.addItem(item)
        else:
            self.task_list.insertItem(max(0, min(index, self.task_list.count())), item)
        self.task_list.setItemWidget(item, row_widget)
        row_widget.set_parent_item(item)
        item.setData(Qt.UserRole, row_widget.get_data())
        item.setData(Qt.UserRole + 1, row_widget.drag_summary())
        item.setText("")
        if select:
            self.task_list.setCurrentItem(item)
        self.update_indexes()

    def del_row(self, row_widget):
        tasks = self.snapshot_tasks()
        target_id = str(row_widget.get_data().get("step_id", ""))
        references = [
            reference
            for reference in references_to_step(tasks, target_id)
            if reference.source_id != target_id
        ]
        if references:
            preview = "\n".join(
                f"第 {reference.source_index} 步：{reference.label}"
                for reference in references[:12]
            )
            if len(references) > 12:
                preview += f"\n……另有 {len(references) - 12} 处引用"
            answer = QMessageBox.question(
                self,
                "删除被引用步骤",
                "其他步骤仍然跳转到当前步骤：\n\n"
                f"{preview}\n\n删除后，这些跳转会被关闭并改为顺序执行。是否继续？",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return
        self.push_undo_state()
        repaired = remove_task_and_clear_references(tasks, target_id)
        repaired_by_id = {
            str(task.get("step_id", "")): task for task in repaired
        }
        if hasattr(row_widget, "close_config_dialog"):
            row_widget.close_config_dialog()
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if self.task_list.itemWidget(item) == row_widget:
                self.task_list.removeItemWidget(item)
                self.task_list.takeItem(i)
                row_widget.hide()
                row_widget.deleteLater()
                break
        for index in range(self.task_list.count()):
            item = self.task_list.item(index)
            widget = self.task_list.itemWidget(item)
            if not widget:
                continue
            step_id = str(widget.get_data().get("step_id", ""))
            repaired_data = repaired_by_id.get(step_id)
            if not repaired_data:
                continue
            for jump_field, target_field, _label in REFERENCE_FIELDS:
                widget.custom_data[jump_field] = repaired_data[jump_field]
                widget.custom_data[target_field] = repaired_data[target_field]
        self.update_indexes()
        QToolTip.hideText()
        self.task_list.viewport().update()
        self.delete_hover_timer.start(25)

    def refresh_task_list_delete_hover(self):
        for button in self.task_list.findChildren(QPushButton):
            refresh = getattr(button, "set_synthetic_hover", None)
            if callable(refresh):
                refresh(False)
        target = QApplication.widgetAt(QCursor.pos())
        if target is None or not self.task_list.isAncestorOf(target):
            return
        refresh = getattr(target, "set_synthetic_hover", None)
        if callable(refresh) and target.property("variant") == "dangerGhost":
            refresh(True)

    def insert_row_before_selected(self):
        row = self.selected_row_index()
        self.add_row(index=(row if row is not None else self.task_list.count()))

    def copy_selected_row(self):
        row = self.selected_row_index()
        if row is None:
            return
        item = self.task_list.item(row)
        widget = self.task_list.itemWidget(item)
        if not widget:
            return
        self.task_clipboard = widget.get_data()
        try:
            pyperclip.copy(json.dumps({TASK_CLIPBOARD_KEY: self.task_clipboard}, ensure_ascii=False))
        except Exception:
            pass
        if GLOBAL_CONFIG["log_to_ui"]:
            self.append_application_log(f"<font color='gray'>已复制第 {row + 1} 步。</font>")

    def paste_row_after_selected(self):
        data = self.task_clipboard
        if data is None:
            try:
                clip = json.loads(pyperclip.paste())
                if isinstance(clip, dict):
                    data = clip.get(TASK_CLIPBOARD_KEY, clip.get(LEGACY_TASK_CLIPBOARD_KEY))
            except Exception:
                data = None
        if not isinstance(data, dict):
            return
        row = self.selected_row_index()
        insert_at = self.task_list.count() if row is None else row + 1
        self.add_row(clone_task_for_insert(data), index=insert_at)

    def undo_task_change(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.snapshot_tasks())
        tasks = self.undo_stack.pop()
        self.restore_task_snapshot(tasks)

    def redo_task_change(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.snapshot_tasks())
        tasks = self.redo_stack.pop()
        self.restore_task_snapshot(tasks)

    def toggle_selected_breakpoint(self):
        row = self.selected_row_index()
        if row is None:
            QToolTip.showText(QCursor.pos(), "请先选中一个步骤", self)
            return False
        item = self.task_list.item(row)
        widget = self.task_list.itemWidget(item) if item else None
        if not widget or not hasattr(widget, "set_breakpoint"):
            return False
        self.push_undo_state()
        enabled = not widget.has_breakpoint()
        widget.set_breakpoint(enabled)
        QToolTip.showText(
            QCursor.pos(),
            f"第 {row + 1} 步断点已{'添加' if enabled else '清除'}",
            self.breakpoint_toggle_btn,
        )
        return True

    def keyPressEvent(self, event):
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)):
            return super().keyPressEvent(event)
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_C:
                self.copy_selected_row(); return
            if event.key() == Qt.Key_V:
                self.paste_row_after_selected(); return
            if event.key() == Qt.Key_Z:
                self.undo_task_change(); return
            if event.key() == Qt.Key_Y:
                self.redo_task_change(); return
            if event.key() == Qt.Key_D:
                self.insert_row_before_selected(); return
        if event.key() == Qt.Key_Insert:
            self.insert_row_before_selected(); return
        if event.key() == Qt.Key_F8:
            self.toggle_selected_breakpoint(); return
        return super().keyPressEvent(event)

    def asset_export_name(self, path):
        return package_asset_export_name(path)

    def rewrite_profile_image_paths(self, cfg, mapper):
        return package_rewrite_image_paths(cfg, mapper)

    def collect_profile_image_paths(self, cfg):
        return package_collect_image_paths(cfg)

    def save(self):
        data = self.get_current_ui_config()
        path, _ = QFileDialog.getSaveFileName(self, "导出方案", filter="JSON (*.json)")
        if path:
            try:
                atomic_write_json(path, data)
                if GLOBAL_CONFIG["log_to_ui"]:
                    self.append_application_log(f"<font color='green'><b>>>> 方案已成功导出至: {path}</b></font>")
            except Exception as error:
                QMessageBox.warning(self, "导出失败", str(error))

    def save_full_package(self):
        data = self.get_current_ui_config()
        default_name = f"{self.current_profile_name}_全量导出.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, "全量导出方案", default_name, filter=f"{PRODUCT_NAME} 全量包 (*.zip)"
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            result = export_full_package(data, self.current_profile_name, path)
            if GLOBAL_CONFIG["log_to_ui"]:
                self.append_application_log(
                    f"<font color='green'><b>>>> 全量方案已成功导出至: {result.path}</b></font>"
                )
        except MissingPackageAssetsError as error:
            preview = "\n".join(error.paths[:8])
            if len(error.paths) > 8:
                preview += f"\n……另有 {len(error.paths) - 8} 项"
            QMessageBox.warning(
                self,
                "全量导出已取消",
                f"有 {len(error.paths)} 个图片路径不存在。为避免生成换电脑后无法运行的残缺包，"
                f"本次没有导出。\n\n{preview}",
            )
        except Exception as error:
            QMessageBox.warning(self, "全量导出失败", str(error))

    def safe_extract_full_package(self, zip_path, target_dir):
        return package_safe_extract(zip_path, target_dir)

    def load_full_package(self, path):
        result = import_full_package(path, self.base_dir)
        return result.profile, result.suggested_name

    def load(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入方案",
            filter=f"{PRODUCT_NAME} 方案 (*.json *.zip);;JSON (*.json);;全量包 (*.zip)",
        )
        if path:
            try:
                if len(self.profiles_data) >= MAX_PROFILES:
                    raise ValueError(f"方案数量已达到上限 {MAX_PROFILES}，请先删除不再需要的方案")
                if path.lower().endswith(".zip"):
                    data, base_name = self.load_full_package(path)
                else:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    base_name = os.path.splitext(os.path.basename(path))[0]
                    
                new_name = base_name
                counter = 1
                while new_name in self.profiles_data:
                    new_name = f"{base_name}_{counter}"
                    counter += 1
                    
                if isinstance(data, list):
                    new_profile_data = self.get_default_config_dict()
                    new_profile_data["tasks"] = data
                elif isinstance(data, dict):
                    new_profile_data = migrate_profile_config(data).value
                else:
                    raise ValueError("无法识别的配置文件格式")

                profile_error = self.validate_profile_config_data(new_profile_data, "导入方案")
                if profile_error:
                    raise ValueError(profile_error)

                self.profiles_data[self.current_profile_name] = self.get_current_ui_config()
                new_profile_data = self.profile_model.create(new_name, new_profile_data)
                
                self.is_switching_profile = True
                self.profile_combo.addItem(new_name)
                self.profile_combo.setCurrentText(new_name)
                self.apply_ui_config(new_profile_data)
                self.is_switching_profile = False
                
                if GLOBAL_CONFIG["log_to_ui"]:
                    self.append_application_log(f"<font color='green'><b>>>> 成功导入并创建新方案: {new_name}</b></font>")
            except Exception as e:
                QMessageBox.warning(self, "导入失败", str(e))

    def validate_global_settings(self, cfg=None):
        cfg = cfg or self.get_current_ui_config()
        try:
            EngineRunConfig.from_mapping(cfg)
        except RunConfigError as error:
            return str(error)
        return None

    def validate_tasks(self, tasks, cfg=None):
        error = validate_task_list(tasks, cfg or self.get_current_ui_config())
        if error:
            return error
        credential_steps = []
        for index, task in enumerate(tasks):
            try:
                is_secret = float(task.get("type", 0)) == TASK_TYPE_SECRET_TEXT
            except (TypeError, ValueError):
                is_secret = False
            if is_secret:
                credential_steps.append((index + 1, str(task.get("value", "")).strip()))
        if not credential_steps:
            return None
        try:
            available = set(self.credentials.names())
        except CredentialStoreError as store_error:
            return f"凭据库无法读取：{store_error}"
        for step_no, name in credential_steps:
            if name not in available:
                return (
                    f"第 {step_no} 步引用的凭据“{name}”不存在。\n"
                    "请在设置 -> 凭据库中创建同名凭据后再运行。"
                )
        return None

    def script_check_report(self, tasks, cfg):
        syntax_error = self.validate_tasks(tasks, cfg)
        try:
            start_step = max(1, int(float(cfg.get("start_step", 1))))
        except (TypeError, ValueError):
            start_step = 1
        structure = analyze_workflow_structure(tasks, start_step=start_step)
        risks = self.analyze_loop_risks(tasks, cfg) if not syntax_error else []
        return {
            "syntax_error": syntax_error or "",
            "structure": [
                {
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                    "step": issue.step,
                }
                for issue in structure
            ],
            "loop_risks": list(risks),
        }

    def show_script_check_report(self):
        cfg = self.get_current_ui_config()
        tasks = cfg.get("tasks", [])
        if not tasks:
            QMessageBox.information(self, "脚本检查", "当前方案没有步骤。")
            return
        report = self.script_check_report(tasks, cfg)
        findings = []
        if report["syntax_error"]:
            match = re.search(r"第\s*(\d+)\s*步", report["syntax_error"])
            findings.append(
                {
                    "severity": "error",
                    "message": report["syntax_error"],
                    "step": int(match.group(1)) if match else None,
                }
            )
        findings.extend(report["structure"])
        for risk in report["loop_risks"]:
            match = re.search(r"第\s*(\d+)\s*步", risk)
            findings.append(
                {
                    "severity": "warning",
                    "message": risk,
                    "step": int(match.group(1)) if match else None,
                }
            )
        if not findings:
            QMessageBox.information(
                self,
                "脚本检查通过",
                f"已检查 {len(tasks)} 个步骤，未发现语法错误、不可到达步骤或明显循环风险。",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("脚本检查结果")
        dialog.resize(780, 460)
        layout = QVBoxLayout(dialog)
        error_count = sum(item.get("severity") == "error" for item in findings)
        summary = QLabel(
            f"共发现 {len(findings)} 项，其中 {error_count} 项会阻止运行。"
            "双击带步号的项目可直接定位。"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        finding_list = QListWidget()
        finding_list.setAlternatingRowColors(True)
        layout.addWidget(finding_list, 1)
        detail = QLabel("")
        detail.setWordWrap(True)
        detail.setProperty("role", "muted")
        layout.addWidget(detail)

        for finding in findings:
            severity = "错误" if finding.get("severity") == "error" else "提示"
            step = finding.get("step")
            location = f"第 {step} 步" if step else "全局"
            item = QListWidgetItem(
                f"[{severity}] [{location}] {finding.get('message', '')}"
            )
            item.setData(Qt.UserRole, step or 0)
            item.setToolTip("双击定位到该步骤" if step else "此项涉及整个脚本")
            finding_list.addItem(item)

        def show_finding_detail(item):
            detail.setText(item.text() if item else "")

        def locate_finding(item=None):
            selected = item or finding_list.currentItem()
            step = int(selected.data(Qt.UserRole) or 0) if selected else 0
            if not 1 <= step <= self.task_list.count():
                return
            target = self.task_list.item(step - 1)
            self.task_list.setCurrentItem(target)
            self.task_list.scrollToItem(target)
            self.raise_()
            self.activateWindow()
            dialog.accept()

        finding_list.currentItemChanged.connect(
            lambda current, _previous: show_finding_detail(current)
        )
        finding_list.itemDoubleClicked.connect(locate_finding)
        if finding_list.count():
            finding_list.setCurrentRow(0)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        locate_button = buttons.addButton("定位到步骤", QDialogButtonBox.ActionRole)
        locate_button.clicked.connect(lambda: locate_finding())
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def analyze_loop_risks(self, tasks, cfg):
        return analyze_workflow_loop_risks(tasks, cfg, self.engine.get_cmd_name)

    def confirm_loop_risks(self, tasks, cfg):
        risks = self.analyze_loop_risks(tasks, cfg)
        if not risks:
            return True

        signature_src = json.dumps({
            "loop_mode": cfg.get("loop_mode"),
            "loop_start_round": cfg.get("loop_start_round"),
            "loop_end_round": cfg.get("loop_end_round"),
            "risks": risks,
            "tasks": [
                {
                    "type": task.get("type"),
                    "repeat_mode": task.get("repeat_mode"),
                    "step_loop_start": task.get("step_loop_start"),
                    "step_loop_end": task.get("step_loop_end"),
                    "no_skip_wait": task.get("no_skip_wait"),
                    "coord_step_en": task.get("coord_step_en"),
                    "coord_step_reset_after": task.get("coord_step_reset_after"),
                    "success_jump": task.get("success_jump"),
                    "fail_jump": task.get("fail_jump"),
                    "until_false_jump": task.get("until_false_jump"),
                    "until_true_jump": task.get("until_true_jump"),
                    "until_max_checks": task.get("until_max_checks"),
                    "until_max_seconds": task.get("until_max_seconds"),
                    "until_on_limit": task.get("until_on_limit"),
                    "until_logic": task.get("until_logic"),
                    "until_conditions": until_condition_list_from_data(task)
                } for task in tasks
            ]
        }, ensure_ascii=False, sort_keys=True)
        signature = hashlib.sha256(signature_src.encode("utf-8")).hexdigest()
        if self.settings.value("ack_loop_risk_signature", "") == signature:
            return True

        preview = "\n".join(risks[:8])
        if len(risks) > 8:
            preview += f"\n……另有 {len(risks) - 8} 条风险未显示。"

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("可能存在无限循环/等待")
        msg.setText("检测到当前方案可能长时间停在某一步或循环执行。")
        msg.setInformativeText(preview)
        msg.setDetailedText("\n".join(risks))
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.button(QMessageBox.Ok).setText("我知道了，继续运行")
        msg.button(QMessageBox.Cancel).setText("取消运行")
        if msg.exec() != QMessageBox.Ok:
            return False
        self.settings.setValue("ack_loop_risk_signature", signature)
        return True

    def clear_debug_pause_highlight(self):
        self.debug_paused_step = 0
        for index in range(self.task_list.count()):
            item = self.task_list.item(index)
            widget = self.task_list.itemWidget(item)
            if widget and hasattr(widget, "set_debug_paused"):
                widget.set_debug_paused(False)

    def show_debug_variables(self):
        values = dict(self.debug_variable_values or {})
        lines = []
        for name in sorted(values):
            rendered = repr(values[name])
            if len(rendered) > 180:
                rendered = rendered[:177] + "..."
            lines.append(f"{name} = {rendered}")
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Information)
        message.setWindowTitle("运行变量")
        message.setText(
            f"当前暂停在第 {self.debug_paused_step} 步，共 {len(values)} 个可用变量。"
        )
        message.setInformativeText("内置变量和脚本自定义变量均为本次运行的即时快照。")
        message.setDetailedText("\n".join(lines) if lines else "暂无变量")
        message.setStandardButtons(QMessageBox.Ok)
        message.exec()

    def pause_debug_run(self):
        if self.run_controller.pause_at_next_step():
            self.debug_pause_btn.setEnabled(False)
            QToolTip.showText(
                QCursor.pos(), "将在下一个实际执行步骤前暂停", self.debug_pause_btn
            )

    def continue_debug_run(self):
        if self.run_controller.continue_run():
            self.debug_continue_btn.setEnabled(False)
            self.debug_next_btn.setEnabled(False)
            self.debug_variables_btn.setEnabled(False)

    def step_over_debug_run(self):
        if self.run_controller.step_over():
            self.debug_continue_btn.setEnabled(False)
            self.debug_next_btn.setEnabled(False)
            self.debug_variables_btn.setEnabled(False)

    def handle_debug_event(self, data):
        state = str(data.get("state", ""))
        step = max(0, int(data.get("step", 0) or 0))
        loop = max(0, int(data.get("loop", 0) or 0))
        command = str(data.get("command", "") or "")
        reason_text = {
            "breakpoint": "命中断点",
            "conditional_breakpoint": "条件断点成立",
            "breakpoint_condition_error": "断点条件无法求值",
            "pause_requested": "用户请求暂停",
            "step_over": "单步完成",
        }.get(str(data.get("reason", "")), "调试暂停")
        if state == "paused":
            self.clear_debug_pause_highlight()
            self.debug_paused_step = step
            variables = data.get("variables", {})
            self.debug_variable_values = (
                dict(variables) if isinstance(variables, dict) else {}
            )
            if 1 <= step <= self.task_list.count():
                item = self.task_list.item(step - 1)
                widget = self.task_list.itemWidget(item)
                if widget and hasattr(widget, "set_debug_paused"):
                    widget.set_debug_paused(True)
                self.task_list.setCurrentItem(item)
                self.task_list.scrollToItem(item)
            self.debug_pause_btn.setEnabled(False)
            self.debug_continue_btn.setEnabled(True)
            self.debug_next_btn.setEnabled(True)
            self.debug_variables_btn.setEnabled(True)
            self.update_running_status_overlay(
                {
                    "loop": loop,
                    "step": step,
                    "total": self.task_list.count(),
                    "cmd": f"已暂停 · {command}",
                }
            )
            if GLOBAL_CONFIG["log_to_ui"]:
                detail = html.escape(str(data.get("detail", "") or ""))
                detail_text = (
                    f"<br><span style='color:#92400E'>原因：{detail}</span>"
                    if detail
                    else ""
                )
                self.append_application_log(
                    f"<font color='#D97706'><b>调试暂停：循环 #{loop} 第 {step} 步 "
                    f"({command})，{reason_text}。</b>{detail_text}</font>"
                )
        elif state in ("resumed", "cancelled"):
            self.clear_debug_pause_highlight()
            self.debug_continue_btn.setEnabled(False)
            self.debug_next_btn.setEnabled(False)
            self.debug_variables_btn.setEnabled(False)
            self.debug_pause_btn.setEnabled(
                state == "resumed" and self.run_controller.is_active
            )

    def start_task(self):
        if not self.runtime_ready:
            QToolTip.showText(
                QCursor.pos(), "识别运行库仍在准备，请稍候", self.start_btn
            )
            return
        if self.start_in_progress or self.run_controller.is_active:
            return
        self.start_in_progress = True
        try:
            self._start_task_impl()
        finally:
            self.start_in_progress = False

    def _start_task_impl(self):
        cfg = self.get_current_ui_config()
        tasks = cfg.get("tasks", [])
        if not tasks: return
        
        err_msg = self.validate_tasks(tasks, cfg)
        if err_msg:
            QMessageBox.critical(self, "指令语法错误", err_msg)
            return

        if not self.confirm_loop_risks(tasks, cfg):
            return
            
        try:
            run_request = RunRequest.create(tasks, cfg, self.current_profile_name)
            run_request.config.apply_to(self.engine)
            tasks = run_request.mutable_tasks()
        except RunConfigError as error:
            QMessageBox.warning(self, "错误", str(error))
            return

        self._launch_prepared_tasks(tasks, cfg, "引擎启动")

    def build_single_step_request(self, task, cfg):
        single_task = json.loads(json.dumps(task, ensure_ascii=False))
        single_task.update(
            {
                "retry": 1,
                "repeat_mode": "执行一次",
                "repeat_count": "1",
                "no_skip_wait": False,
                "fail_limit": "1",
                "run_max_executions": "1",
                "step_loop_start": "1",
                "step_loop_end": "0",
                "success_skip": "0",
                "success_jump": "0",
                "success_target_id": "",
                "fail_skip": "0",
                "fail_jump": "0",
                "fail_target_id": "",
                "until_false_jump": "0",
                "until_false_target_id": "",
                "until_true_jump": "0",
                "until_true_target_id": "",
                "until_max_checks": "1",
                "until_on_limit": "继续下一步",
                "debug_breakpoint": False,
            }
        )
        single_cfg = json.loads(json.dumps(cfg, ensure_ascii=False))
        single_cfg.update(
            {
                "loop_mode": "单次",
                "loop_val": "1",
                "start_step": "1",
                "loop_start_round": "1",
                "loop_end_round": "0",
            }
        )
        return [single_task], single_cfg

    def run_selected_step_once(self):
        if not self.runtime_ready:
            QToolTip.showText(
                QCursor.pos(), "识别运行库仍在准备，请稍候", self.single_step_btn
            )
            return
        if self.start_in_progress or self.run_controller.is_active:
            return
        selected_index = self.selected_row_index()
        if selected_index is None:
            QMessageBox.information(self, "执行一步", "请先在步骤列表中选中一个步骤。")
            return
        self.start_in_progress = True
        try:
            cfg = self.get_current_ui_config()
            tasks = cfg.get("tasks", [])
            if not 0 <= selected_index < len(tasks):
                return
            single_tasks, single_cfg = self.build_single_step_request(
                tasks[selected_index], cfg
            )
            error_message = self.validate_tasks(single_tasks, single_cfg)
            if error_message:
                QMessageBox.critical(self, "当前步骤无法执行", error_message)
                return
            try:
                run_request = RunRequest.create(
                    single_tasks,
                    single_cfg,
                    f"{self.current_profile_name} / 第{selected_index + 1}步",
                )
                run_request.config.apply_to(self.engine)
                prepared_tasks = run_request.mutable_tasks()
            except RunConfigError as error:
                QMessageBox.warning(self, "错误", str(error))
                return
            command_name = self.engine.get_cmd_name(single_tasks[0].get("type"))
            self._launch_prepared_tasks(
                prepared_tasks,
                single_cfg,
                f"单步执行：原第 {selected_index + 1} 步 {command_name}",
            )
        finally:
            self.start_in_progress = False

    def _launch_prepared_tasks(self, tasks, cfg, run_label):
        self.ui_performance.reset()
        log_policy = self.current_log_policy()
        if GLOBAL_CONFIG["log_to_ui"] and log_policy.allows(LOG_RUN):
            start_key = cfg["hotkey_start"]
            stop_key = cfg["hotkey_stop"]
            multi_info = cfg.get("multi_target_mode", "快速一个")
            if multi_info == "全部匹配":
                multi_info = f"{multi_info}/{cfg.get('multi_target_order', '从上到下')}"
            start_step = int(float(cfg.get("start_step", "1")))
            loop_start_round = int(float(cfg.get("loop_start_round", "1")))
            loop_end_round = int(float(cfg.get("loop_end_round", "0")))
            loop_range_info = f"循环范围: 第{loop_start_round}次起" + (f" 至第{loop_end_round}次" if loop_end_round > 0 else "")
            timeout_mode = "超时急停" if cfg.get("timeout_stop", False) else "超时按失败处理"
            timestamp = (
                f"[{format_local_timestamp()}] "
                if log_policy.timestamp_enabled
                else ""
            )
            self.append_log(f"<hr><b><font color='blue'>{timestamp}>>> {run_label} ({start_key}启动 / {stop_key}停止) - 方案: {self.current_profile_name} - 日志: {self.log_level_combo.currentText()} - 循环: {cfg.get('loop_mode', '单次')} - {loop_range_info} - 起始步: {start_step} - 多目标: {multi_info} - {timeout_mode}</font></b>")
            
        try:
            self.start_btn.setEnabled(False)
            self.single_step_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.clear_debug_pause_highlight()
            self.debug_pause_btn.setEnabled(True)
            self.debug_continue_btn.setEnabled(False)
            self.debug_next_btn.setEnabled(False)
            self.debug_variables_btn.setEnabled(False)
            if self.mini_chk.isChecked(): self.showMinimized()

            if cfg.get("run_status_tip", True):
                self.show_running_status_overlay(cfg.get("run_status_pos", "右上角"))
            else:
                self.hide_running_status_overlay()
            
            started, error = self.run_controller.start(
                tasks,
                self.append_log,
                self.update_running_status_overlay,
                self.show_click_indicator_overlay,
                self.handle_debug_event,
            )
            if not started:
                raise RuntimeError(error or "执行引擎未能启动")
        except Exception as e:
            self.start_btn.setEnabled(True)
            self.single_step_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.debug_pause_btn.setEnabled(False)
            self.debug_continue_btn.setEnabled(False)
            self.debug_next_btn.setEnabled(False)
            self.debug_variables_btn.setEnabled(False)
            self.clear_debug_pause_highlight()
            self.hide_running_status_overlay()
            QMessageBox.critical(self, "启动失败", str(e))

    def stop_task(self):
        self.run_controller.stop()
        self.stop_btn.setEnabled(False)
        self.debug_pause_btn.setEnabled(False)
        self.debug_continue_btn.setEnabled(False)
        self.debug_next_btn.setEnabled(False)
        self.debug_variables_btn.setEnabled(False)

    def on_worker_error(self, message):
        self.append_application_log(
            f"<font color='red'><b>执行线程异常：{message}</b></font>",
            LOG_CRITICAL,
            critical=True,
        )
        QMessageBox.critical(self, "执行线程异常", str(message))
        
    def on_finish(self):
        self.start_btn.setEnabled(True)
        self.single_step_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.debug_pause_btn.setEnabled(False)
        self.debug_continue_btn.setEnabled(False)
        self.debug_next_btn.setEnabled(False)
        self.debug_variables_btn.setEnabled(False)
        self.debug_variable_values = {}
        self.clear_debug_pause_highlight()
        self.hide_running_status_overlay()
        self.refresh_scale_memory_status()
        if self._close_after_worker:
            QTimer.singleShot(0, self.close)
            return
        self.showNormal()
        self.activateWindow()
        if GLOBAL_CONFIG["log_to_ui"]:
            self.append_application_log(
                "<b><font color='blue'>引擎运行结束</font></b>", LOG_RUN
            )
