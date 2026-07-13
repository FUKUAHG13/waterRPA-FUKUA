"""Versioned profile defaults and forward-only configuration migrations."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from .constants import (
    DEFAULT_KEY_MAPPING_COUNT,
    MIN_SUPPORTED_PROFILE_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
)
from .commands import COMMAND_BY_CODE
from .log_policy import (
    DEFAULT_CUSTOM_LOG_CATEGORIES,
    LOG_MODE_LEVELS,
    LOG_MODE_SIMPLE,
    normalize_log_categories,
    normalize_log_mode,
)
from .workflow_document import normalize_workflow_tasks


class UnsupportedProfileVersion(ValueError):
    """Raised when a profile was written by a newer, unsupported application."""


@dataclass(frozen=True)
class MigrationResult:
    value: dict[str, Any]
    changed: bool
    source_version: int
    target_version: int = PROFILE_SCHEMA_VERSION


def default_profile_config() -> dict[str, Any]:
    """Return a fresh, fully populated profile configuration."""

    return {
        "_schema_version": PROFILE_SCHEMA_VERSION,
        "conf": "0.8",
        "scale_min": "0.8",
        "scale_max": "1.2",
        "scale_step": "0.05",
        "gray_en": True,
        "native_core_en": True,
        "native_parallel_mode": "auto",
        "native_scale_hint_en": True,
        "scale_memory_tier": "balanced",
        "scale_memory_manual": "",
        "scale_memory_custom_en": False,
        "scale_memory_preferred_limit": 3,
        "scale_memory_history_limit": 64,
        "dodge_x1": "100",
        "dodge_y1": "100",
        "dodge_x2": "200",
        "dodge_y2": "100",
        "dodge_en": False,
        "dbl_dodge": False,
        "dbl_wait": "0.015",
        "dodge_click_action": "none",
        "move_spd": "0.0",
        "click_hld": "0.04",
        "settle": "0.5",
        "timeout": "0.0",
        "timeout_stop": False,
        "detect_delay": "0.1",
        "adaptive_backoff": True,
        "scene_wake_en": True,
        "scene_wake_sensitivity": "balanced",
        "playback_speed": "1.0",
        "multi_target_mode": "快速一个",
        "multi_target_order": "从上到下",
        "hotkey_start": "F9",
        "hotkey_stop": "F10",
        "log_level": 0,
        "log_mode": LOG_MODE_SIMPLE,
        "log_custom_categories": list(DEFAULT_CUSTOM_LOG_CATEGORIES),
        "tm_fs": True,
        "tr_fs": True,
        "key_fs": True,
        "log_f": False,
        "log_ui": True,
        "mini": False,
        "top": False,
        "run_status_tip": True,
        "run_status_pos": "右上角",
        "click_indicator": True,
        "start_step": "1",
        "loop_start_round": "1",
        "loop_end_round": "0",
        "low_power_ui": True,
        "cpu_refresh_interval": "auto",
        "ui_scale": "100",
        "loop_mode": "单次",
        "loop_val": "10",
        "scan_region": None,
        "scan_regions": [],
        "mapping_mode_enabled": False,
        "mapping_click_mode": "真实鼠标点击",
        "key_mapping_count": DEFAULT_KEY_MAPPING_COUNT,
        "key_mappings": [],
        "tasks": [],
    }


def _profile_version(config: Mapping[str, Any]) -> int:
    raw = config.get("_schema_version", 0)
    try:
        version = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"方案版本号无效：{raw}") from error
    if version < 0:
        raise ValueError(f"方案版本号不能小于 0：{version}")
    if version < MIN_SUPPORTED_PROFILE_SCHEMA_VERSION:
        raise UnsupportedProfileVersion(
            f"方案版本 {version} 低于本程序支持的最低版本 "
            f"{MIN_SUPPORTED_PROFILE_SCHEMA_VERSION}。请使用对应旧版导出，"
            "或使用提供转换功能的新版本处理。"
        )
    if version > PROFILE_SCHEMA_VERSION:
        raise UnsupportedProfileVersion(
            f"方案版本 {version} 高于本程序支持的版本 {PROFILE_SCHEMA_VERSION}，"
            "请使用更新版本的 fukuaRPA 打开，以免配置丢失。"
        )
    return version


def migrate_profile_config(config: Mapping[str, Any]) -> MigrationResult:
    """Migrate one profile without discarding fields unknown to this version."""

    if not isinstance(config, Mapping):
        raise ValueError("方案不是有效的配置对象")
    source_version = _profile_version(config)
    migrated = copy.deepcopy(dict(config))
    changed = source_version != PROFILE_SCHEMA_VERSION

    # Version 0 is every profile written before an explicit schema existed.
    if source_version == 0:
        if migrated.get("multi_target_mode") == "最佳一个":
            migrated["multi_target_mode"] = "快速一个"
        if "scan_regions" not in migrated:
            region = migrated.get("scan_region")
            migrated["scan_regions"] = [region] if region else []

    if source_version < 2:
        migrated["log_mode"] = normalize_log_mode(
            migrated.get("log_mode"), migrated.get("log_level", 0)
        )
        migrated.setdefault(
            "log_custom_categories", list(DEFAULT_CUSTOM_LOG_CATEGORIES)
        )

    defaults = default_profile_config()
    for key, value in defaults.items():
        if key not in migrated:
            migrated[key] = copy.deepcopy(value)
            changed = True

    normalized_log_mode = normalize_log_mode(
        migrated.get("log_mode"), migrated.get("log_level", 0)
    )
    normalized_log_categories = list(
        normalize_log_categories(migrated.get("log_custom_categories"))
    )
    if migrated.get("log_mode") != normalized_log_mode:
        migrated["log_mode"] = normalized_log_mode
        changed = True
    if migrated.get("log_custom_categories") != normalized_log_categories:
        migrated["log_custom_categories"] = normalized_log_categories
        changed = True
    expected_log_level = LOG_MODE_LEVELS[normalized_log_mode]
    if migrated.get("log_level") != expected_log_level:
        migrated["log_level"] = expected_log_level
        changed = True

    # Containers are normalized only after their type has been checked by the
    # caller.  Copying here prevents UI edits from mutating imported payloads.
    if isinstance(migrated.get("tasks"), list):
        migrated["tasks"] = copy.deepcopy(migrated["tasks"])
        for task in migrated["tasks"]:
            if not isinstance(task, dict):
                continue
            try:
                command = float(task.get("type"))
            except (TypeError, ValueError):
                continue
            if command in COMMAND_BY_CODE and task.get("type") != command:
                task["type"] = command
                changed = True
        normalized_tasks = normalize_workflow_tasks(migrated["tasks"])
        if normalized_tasks != migrated["tasks"]:
            migrated["tasks"] = normalized_tasks
            changed = True
    if isinstance(migrated.get("key_mappings"), list):
        migrated["key_mappings"] = copy.deepcopy(migrated["key_mappings"])
    if isinstance(migrated.get("scan_regions"), list):
        migrated["scan_regions"] = copy.deepcopy(migrated["scan_regions"])

    if migrated.get("_schema_version") != PROFILE_SCHEMA_VERSION:
        migrated["_schema_version"] = PROFILE_SCHEMA_VERSION
        changed = True
    return MigrationResult(migrated, changed, source_version)


def migrate_profiles(profiles: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], bool]:
    if not isinstance(profiles, Mapping):
        raise ValueError("方案集合为空或格式错误")
    result: dict[str, dict[str, Any]] = {}
    changed = False
    for name, config in profiles.items():
        migration = migrate_profile_config(config)
        result[str(name)] = migration.value
        changed = changed or migration.changed or not isinstance(name, str)
    return result, changed
