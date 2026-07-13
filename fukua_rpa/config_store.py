"""Validated, recoverable profile persistence independent from the main window."""

import hashlib
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QSettings

from .constants import (
    APP_VERSION,
    LEGACY_PROFILE_BACKUP_FORMAT,
    MAX_KEY_MAPPINGS,
    MAX_KEY_MAPPING_FIELDS,
    MAX_PROFILES,
    MAX_PROFILE_JSON_BYTES,
    MAX_PROFILE_NAME_LENGTH,
    MAX_PROFILE_TOP_LEVEL_FIELDS,
    MAX_TASK_FIELDS,
    MAX_TASKS_PER_PROFILE,
    PROFILE_BACKUP_VERSION,
    PROFILE_BACKUP_FORMAT,
    PROFILE_HISTORY_LIMIT,
    PROFILE_HISTORY_MIN_INTERVAL_SECONDS,
)
from .config_schema import UnsupportedProfileVersion, migrate_profiles


@dataclass(frozen=True)
class ProfilesLoadResult:
    profiles: dict
    current_profile: str
    recovery_message: str = ""
    migrated: bool = False
    source: str = "settings"
    persistence_blocked: bool = False


UNSUPPORTED_PROFILE_PREFIX = "方案版本不受支持："


def _unsupported_profile_message(error):
    return f"{UNSUPPORTED_PROFILE_PREFIX}{error}"


def _is_unsupported_profile_message(message):
    return str(message or "").startswith(UNSUPPORTED_PROFILE_PREFIX)


def atomic_write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temp_path = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def validate_profile_config_data(config, label="方案"):
    if not isinstance(config, dict):
        return f"{label}不是有效的配置对象"
    if len(config) > MAX_PROFILE_TOP_LEVEL_FIELDS:
        return f"{label}包含过多顶层字段，最多允许 {MAX_PROFILE_TOP_LEVEL_FIELDS} 个"
    tasks = config.get("tasks", [])
    if not isinstance(tasks, list):
        return f"{label}的步骤列表格式错误"
    if len(tasks) > MAX_TASKS_PER_PROFILE:
        return f"{label}包含 {len(tasks)} 个步骤，超过上限 {MAX_TASKS_PER_PROFILE}"
    if any(not isinstance(task, dict) for task in tasks):
        return f"{label}包含格式错误的步骤"
    if any(len(task) > MAX_TASK_FIELDS for task in tasks):
        return f"{label}中的单个步骤字段过多，最多允许 {MAX_TASK_FIELDS} 个"
    if any(any(not isinstance(key, str) for key in task) for task in tasks):
        return f"{label}包含非文本字段名的步骤"

    mappings = config.get("key_mappings", [])
    if not isinstance(mappings, list):
        return f"{label}的按键映射格式错误"
    if len(mappings) > MAX_KEY_MAPPINGS:
        return f"{label}包含 {len(mappings)} 个按键映射，超过上限 {MAX_KEY_MAPPINGS}"
    if any(not isinstance(mapping, dict) for mapping in mappings):
        return f"{label}包含格式错误的按键映射"
    if any(len(mapping) > MAX_KEY_MAPPING_FIELDS for mapping in mappings):
        return f"{label}中的单个按键映射字段过多，最多允许 {MAX_KEY_MAPPING_FIELDS} 个"
    if any(any(not isinstance(key, str) for key in mapping) for mapping in mappings):
        return f"{label}包含非文本字段名的按键映射"
    try:
        desired_mapping_count = int(float(config.get("key_mapping_count", len(mappings))))
    except (TypeError, ValueError):
        return f"{label}的按键映射数量设置无效"
    if not 0 <= desired_mapping_count <= MAX_KEY_MAPPINGS:
        return f"{label}的按键映射槽位数量必须在 0 到 {MAX_KEY_MAPPINGS} 之间"
    try:
        serialized = json.dumps(config, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        return f"{label}包含无法保存的数据：{error}"
    serialized_bytes = len(serialized.encode("utf-8"))
    if serialized_bytes > MAX_PROFILE_JSON_BYTES:
        return (
            f"{label}序列化后大小为 {serialized_bytes / 1024 / 1024:.1f} MB，"
            f"超过 {MAX_PROFILE_JSON_BYTES / 1024 / 1024:.0f} MB 上限"
        )
    return None


def validate_profiles_payload(profiles):
    if not isinstance(profiles, dict) or not profiles:
        return "方案集合为空或格式错误"
    if len(profiles) > MAX_PROFILES:
        return f"方案数量 {len(profiles)} 超过上限 {MAX_PROFILES}"
    for name, config in profiles.items():
        if not isinstance(name, str) or not name.strip():
            return "存在空名称或非文本名称的方案"
        if len(name) > MAX_PROFILE_NAME_LENGTH:
            return f"方案名称“{name[:40]}…”过长，最多允许 {MAX_PROFILE_NAME_LENGTH} 个字符"
        error = validate_profile_config_data(config, f"方案“{name}”")
        if error:
            return error
    return None


def preserve_corrupt_config(config_path):
    if not os.path.isfile(config_path):
        return ""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    target = f"{config_path}.corrupt_{timestamp}.bak"
    shutil.copy2(config_path, target)
    return target


def load_profiles_backup(backup_path):
    if not os.path.isfile(backup_path):
        return None, None, "没有找到自动备份"
    try:
        with open(backup_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        accepted_formats = {PROFILE_BACKUP_FORMAT, LEGACY_PROFILE_BACKUP_FORMAT}
        if isinstance(payload, dict) and payload.get("format") in accepted_formats:
            profiles = payload.get("profiles")
            current_profile = payload.get("current_profile")
            expected_signature = str(payload.get("signature", ""))
        else:
            profiles = payload
            current_profile = None
            expected_signature = ""
        error = validate_profiles_payload(profiles)
        if error:
            return None, None, error
        if expected_signature:
            actual_signature = profiles_signature(profiles, current_profile or "")[1]
            if actual_signature != expected_signature:
                return None, None, "自动备份完整性签名不匹配"
        profiles, _changed = migrate_profiles(profiles)
        return profiles, current_profile, ""
    except UnsupportedProfileVersion as error:
        return None, None, _unsupported_profile_message(error)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        return None, None, str(error)


def profiles_backup_payload(profiles, current_profile):
    profiles, _changed = migrate_profiles(profiles)
    _payload_text, signature = profiles_signature(profiles, current_profile)
    return {
        "format": PROFILE_BACKUP_FORMAT,
        "version": PROFILE_BACKUP_VERSION,
        "app_version": APP_VERSION,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "current_profile": current_profile,
        "signature": signature,
        "profiles": profiles,
    }


def profiles_signature(profiles, current_profile):
    payload_text = json.dumps(profiles, ensure_ascii=False, sort_keys=True)
    signature = hashlib.sha256(f"{current_profile}\n{payload_text}".encode("utf-8")).hexdigest()
    return payload_text, signature


def _history_dir_for(backup_path):
    return os.path.join(os.path.dirname(os.path.abspath(backup_path)), "profiles_history")


def list_profile_history(backup_path):
    history_dir = _history_dir_for(backup_path)
    if not os.path.isdir(history_dir):
        return []
    paths = [
        os.path.join(history_dir, name)
        for name in os.listdir(history_dir)
        if name.startswith("profiles_") and name.endswith(".json")
    ]
    return sorted(paths, key=lambda value: os.path.getmtime(value), reverse=True)


def archive_existing_backup(
    backup_path,
    *,
    limit=PROFILE_HISTORY_LIMIT,
    min_interval=PROFILE_HISTORY_MIN_INTERVAL_SECONDS,
):
    """Copy the previous valid backup into a bounded history directory."""

    if not os.path.isfile(backup_path):
        return ""
    profiles, current, error = load_profiles_backup(backup_path)
    if error or not profiles:
        return ""
    history_dir = _history_dir_for(backup_path)
    os.makedirs(history_dir, exist_ok=True)
    existing = list_profile_history(backup_path)
    if existing and min_interval > 0:
        try:
            if time.time() - os.path.getmtime(existing[0]) < min_interval:
                return ""
        except OSError:
            pass
    stamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = profiles_signature(profiles, current or "")[1][:10]
    target = os.path.join(history_dir, f"profiles_{stamp}_{suffix}.json")
    if not os.path.exists(target):
        temp_target = f"{target}.tmp.{os.getpid()}.{threading.get_ident()}"
        try:
            shutil.copy2(backup_path, temp_target)
            os.replace(temp_target, target)
        finally:
            if os.path.exists(temp_target):
                try:
                    os.remove(temp_target)
                except OSError:
                    pass
    for old_path in list_profile_history(backup_path)[max(1, int(limit)):]:
        try:
            os.remove(old_path)
        except OSError:
            pass
    return target


def load_latest_profile_history(backup_path):
    errors = []
    for history_path in list_profile_history(backup_path):
        profiles, current, error = load_profiles_backup(history_path)
        if profiles is not None:
            return profiles, current, history_path, ""
        errors.append(f"{os.path.basename(history_path)}: {error}")
    return None, None, "", "；".join(errors) if errors else "没有找到历史备份"


def load_profiles_state(settings, config_path, backup_path):
    """Load, migrate and recover profiles without depending on any Qt widget."""

    saved_profiles = settings.value("profiles_json", "{}")
    current = str(settings.value("current_profile", "默认方案"))
    if not settings.contains("profiles_json"):
        return ProfilesLoadResult({}, current, source="empty")

    main_error = ""
    try:
        profiles = json.loads(saved_profiles) if isinstance(saved_profiles, str) else saved_profiles
        main_error = validate_profiles_payload(profiles) or ""
        if not main_error:
            stored_signature = str(settings.value("profiles_signature", ""))
            if stored_signature:
                raw_signature = profiles_signature(profiles, current)[1]
                if stored_signature != raw_signature:
                    main_error = "主配置完整性签名不匹配，可能是上次写入未完成"
            if main_error:
                raise ValueError(main_error)
            profiles, migrated = migrate_profiles(profiles)
            if current not in profiles and profiles:
                current = next(iter(profiles))
            _payload_text, main_signature = profiles_signature(profiles, current)
            if stored_signature:
                backup_profiles, backup_current, backup_error = load_profiles_backup(backup_path)
                if _is_unsupported_profile_message(backup_error):
                    return ProfilesLoadResult(
                        profiles,
                        current,
                        (
                            "检测到自动备份由不兼容的程序版本写入。当前主配置可以只读加载，"
                            "但本版本已禁止自动保存，以免覆盖更新版本的备份。\n\n"
                            f"自动备份问题：{backup_error}"
                        ),
                        migrated=migrated,
                        source="unsupported_backup",
                        persistence_blocked=True,
                    )
                if backup_profiles is not None:
                    backup_name = (
                        backup_current if backup_current in backup_profiles else next(iter(backup_profiles))
                    )
                    backup_signature = profiles_signature(backup_profiles, backup_name)[1]
                    if backup_signature != main_signature:
                        return ProfilesLoadResult(
                            backup_profiles,
                            backup_name,
                            "检测到上次配置写入只完成了原子备份，程序已采用较新的备份内容。",
                            source="pending_backup",
                        )
            return ProfilesLoadResult(profiles, current, migrated=migrated)
    except UnsupportedProfileVersion as error:
        message = (
            "当前方案由不兼容的程序版本写入，本版本已拒绝加载并禁止自动保存，"
            "原配置和自动备份不会被覆盖。\n\n"
            f"具体原因：{error}\n\n"
            "请改用创建该方案的版本，或使用明确提供方案转换功能的新版本。"
        )
        return ProfilesLoadResult(
            {},
            current,
            message,
            source="unsupported",
            persistence_blocked=True,
        )
    except Exception as error:
        main_error = str(error)

    try:
        corrupt_copy = preserve_corrupt_config(config_path)
    except Exception:
        corrupt_copy = ""
    profiles, backup_current, backup_error = load_profiles_backup(backup_path)
    if _is_unsupported_profile_message(backup_error):
        message = (
            "自动备份由不兼容的程序版本写入，本版本已拒绝加载并禁止自动保存，"
            "原配置和自动备份不会被覆盖。\n\n"
            f"主配置问题：{main_error or '格式错误'}\n"
            f"自动备份问题：{backup_error}"
        )
        if corrupt_copy:
            message += f"\n\n原配置副本已保留在：\n{corrupt_copy}"
        return ProfilesLoadResult(
            {},
            current,
            message,
            source="unsupported",
            persistence_blocked=True,
        )
    if profiles is not None:
        current = backup_current if backup_current in profiles else next(iter(profiles))
        message = (
            "主配置无法读取，程序已从自动备份恢复方案。\n\n"
            f"原配置问题：{main_error or '格式错误'}"
        )
        source = "backup"
    else:
        profiles, history_current, history_path, history_error = load_latest_profile_history(backup_path)
        if profiles is not None:
            current = history_current if history_current in profiles else next(iter(profiles))
            message = (
                "主配置和当前自动备份都无法读取，程序已从历史备份恢复方案。\n\n"
                f"主配置问题：{main_error or '格式错误'}\n"
                f"当前备份问题：{backup_error}\n历史备份：{history_path}"
            )
            source = "history"
        else:
            profiles = {}
            message = (
                "主配置、当前自动备份和历史备份都无法读取，程序已创建默认方案。\n\n"
                f"主配置问题：{main_error or '格式错误'}\n"
                f"当前备份问题：{backup_error}\n历史备份问题：{history_error}"
            )
            source = "default"
    if corrupt_copy:
        message += f"\n\n原配置副本已保留在：\n{corrupt_copy}"
    return ProfilesLoadResult(profiles, current, message, source=source)


def persist_profiles(settings, backup_path, profiles, current_profile):
    profiles, _changed = migrate_profiles(profiles)
    error = validate_profiles_payload(profiles)
    if error:
        raise ValueError(error)
    if current_profile not in profiles:
        raise ValueError(f"当前方案不存在：{current_profile}")
    payload_text, signature = profiles_signature(profiles, current_profile)
    existing_profiles, existing_current, existing_error = load_profiles_backup(backup_path)
    if _is_unsupported_profile_message(existing_error):
        raise UnsupportedProfileVersion(
            "自动备份由不兼容的程序版本写入，已拒绝覆盖："
            f"{existing_error.removeprefix(UNSUPPORTED_PROFILE_PREFIX)}"
        )
    if existing_error or existing_profiles is None:
        existing_signature = ""
    else:
        existing_signature = profiles_signature(existing_profiles, existing_current or "")[1]
    if existing_signature and existing_signature != signature:
        archive_existing_backup(backup_path)
    atomic_write_json(backup_path, profiles_backup_payload(profiles, current_profile))
    settings.setValue("profiles_json", payload_text)
    settings.setValue("current_profile", current_profile)
    settings.setValue("profiles_signature", signature)
    settings.sync()
    if settings.status() != QSettings.NoError:
        raise OSError(f"QSettings 写入失败，状态码 {settings.status()}")
    return signature
