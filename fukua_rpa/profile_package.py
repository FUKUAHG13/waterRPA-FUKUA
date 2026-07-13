"""Validated full-profile package import/export independent from Qt dialogs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .config_schema import migrate_profile_config
from .constants import (
    APP_VERSION,
    FULL_PACKAGE_FORMAT,
    LEGACY_FULL_PACKAGE_FORMAT,
    MAX_PACKAGE_FILES,
    MAX_PACKAGE_FILE_BYTES,
    MAX_PACKAGE_TOTAL_BYTES,
    SUPPORTED_WINDOWS_TEXT,
)
from .task_model import parse_coordinate_text


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}
PACKAGE_VERSION = 3


@dataclass(frozen=True)
class PackageExportResult:
    path: str
    asset_count: int
    missing_images: tuple[str, ...]


@dataclass(frozen=True)
class PackageImportResult:
    profile: dict[str, Any]
    suggested_name: str
    package_dir: str


class MissingPackageAssetsError(ValueError):
    def __init__(self, paths):
        self.paths = tuple(str(path) for path in paths)
        super().__init__(f"有 {len(self.paths)} 个图片路径不存在，未生成全量包。")


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset_export_name(path: str) -> str:
    absolute = os.path.abspath(path)
    digest = hashlib.sha1(absolute.encode("utf-8", errors="ignore")).hexdigest()[:12]
    base = os.path.basename(absolute)
    safe_base = "".join(character if character not in '<>:"/\\|?*' else "_" for character in base)
    return f"{digest}_{safe_base.strip() or 'image'}"


def rewrite_profile_image_paths(
    config: Mapping[str, Any], mapper: Callable[[str], str | None]
) -> dict[str, Any]:
    data = migrate_profile_config(config).value

    def rewrite(path):
        text = str(path or "").strip()
        if not text:
            return path
        mapped = mapper(text)
        return mapped if mapped else path

    for task in data.get("tasks", []):
        try:
            command = float(task.get("type", 0))
        except (TypeError, ValueError):
            command = 0
        value = str(task.get("value", "")).strip()
        if (
            command in (1.0, 2.0, 3.0, 8.0)
            and value
            and not parse_coordinate_text(value)
        ):
            task["value"] = rewrite(value)
        for condition_index in range(1, 4):
            key = f"until_cond{condition_index}_image"
            if key in task:
                task[key] = rewrite(task.get(key, ""))
    return data


def collect_profile_image_paths(config: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for task in config.get("tasks", []):
        try:
            command = float(task.get("type", 0))
        except (TypeError, ValueError):
            command = 0
        value = str(task.get("value", "")).strip()
        if command in (1.0, 2.0, 3.0, 8.0) and value and not parse_coordinate_text(value):
            paths.append(value)
        for condition_index in range(1, 4):
            image = str(task.get(f"until_cond{condition_index}_image", "")).strip()
            if image:
                paths.append(image)
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized not in seen:
            seen.add(normalized)
            result.append(path)
    return result


def export_full_package(
    config: Mapping[str, Any], profile_name: str, destination: str
) -> PackageExportResult:
    destination = os.path.abspath(destination)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    asset_map: dict[str, str] = {}
    asset_metadata: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for image_path in collect_profile_image_paths(config):
        if not os.path.isfile(image_path):
            missing.append(image_path)
            continue
        absolute = os.path.abspath(image_path)
        relative = f"assets/{asset_export_name(absolute)}"
        asset_map[absolute] = relative
        asset_metadata[relative] = {
            "sha256": _file_sha256(absolute),
            "size": os.path.getsize(absolute),
        }

    if missing:
        raise MissingPackageAssetsError(missing)

    packaged = rewrite_profile_image_paths(
        config, lambda source: asset_map.get(os.path.abspath(source))
    )
    manifest = {
        "format": FULL_PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "app_version": APP_VERSION,
        "supported_windows": SUPPORTED_WINDOWS_TEXT,
        "profile_name": str(profile_name),
        "asset_count": len(asset_map),
        "missing_images": missing,
        "assets": asset_metadata,
    }

    descriptor, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(destination)}.", suffix=".tmp", dir=os.path.dirname(destination)
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("profile.json", json.dumps(packaged, ensure_ascii=False, indent=2))
            for absolute, relative in asset_map.items():
                archive.write(absolute, relative)
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return PackageExportResult(destination, len(asset_map), tuple(missing))


def _safe_member_name(raw_name: str) -> str:
    name = str(raw_name).replace("\\", "/")
    parts = name.split("/")
    reserved_names = {"CON", "PRN", "AUX", "NUL"}
    reserved_names.update(f"COM{index}" for index in range(1, 10))
    reserved_names.update(f"LPT{index}" for index in range(1, 10))
    unsafe_windows_name = any(
        ":" in part
        or part.rstrip(" .") != part
        or part.split(".", 1)[0].upper() in reserved_names
        for part in parts
    )
    if (
        not name
        or name.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
        or unsafe_windows_name
    ):
        raise ValueError(f"压缩包包含不安全路径：{raw_name}")
    return name


def safe_extract_full_package(zip_path: str, target_dir: str) -> None:
    target = os.path.abspath(target_dir)
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        members = archive.infolist()
        if len(members) > MAX_PACKAGE_FILES:
            raise ValueError(f"压缩包文件数量超过上限 {MAX_PACKAGE_FILES}")
        declared_total = sum(max(0, int(member.file_size)) for member in members if not member.is_dir())
        if declared_total > MAX_PACKAGE_TOTAL_BYTES:
            raise ValueError(
                f"压缩包解压后预计超过 {MAX_PACKAGE_TOTAL_BYTES / 1024 / 1024:.0f} MB 上限"
            )
        seen: set[str] = set()
        actual_total = 0
        for member in members:
            if member.is_dir():
                continue
            name = _safe_member_name(member.filename)
            if name not in ("profile.json", "manifest.json") and not name.startswith("assets/"):
                continue
            folded = name.casefold()
            if folded in seen:
                raise ValueError(f"压缩包包含重复路径：{member.filename}")
            seen.add(folded)
            if member.file_size > MAX_PACKAGE_FILE_BYTES:
                raise ValueError(
                    f"压缩包中的文件过大：{member.filename}（单文件上限 "
                    f"{MAX_PACKAGE_FILE_BYTES / 1024 / 1024:.0f} MB）"
                )
            destination = os.path.abspath(os.path.join(target, *name.split("/")))
            if not (destination == target or destination.startswith(target + os.sep)):
                raise ValueError(f"压缩包路径越界：{member.filename}")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with archive.open(member) as source, open(destination, "wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    actual_total += len(chunk)
                    if actual_total > MAX_PACKAGE_TOTAL_BYTES:
                        raise ValueError("压缩包实际解压大小超过安全上限")
                    output.write(chunk)


def _verify_assets(package_dir: str, manifest: Mapping[str, Any]) -> None:
    metadata = manifest.get("assets", {})
    if not isinstance(metadata, Mapping):
        raise ValueError("全量包资产清单格式错误")
    for relative, expected in metadata.items():
        if not isinstance(expected, Mapping):
            raise ValueError(f"全量包资产记录格式错误：{relative}")
        name = _safe_member_name(str(relative))
        if not name.startswith("assets/"):
            raise ValueError(f"全量包资产路径无效：{relative}")
        path = os.path.abspath(os.path.join(package_dir, *name.split("/")))
        if not os.path.isfile(path):
            raise ValueError(f"全量包缺少资产：{relative}")
        expected_size = int(expected.get("size", -1))
        if expected_size != os.path.getsize(path):
            raise ValueError(f"全量包资产大小校验失败：{relative}")
        expected_hash = str(expected.get("sha256", "")).lower()
        if len(expected_hash) != 64 or _file_sha256(path).lower() != expected_hash:
            raise ValueError(f"全量包资产完整性校验失败：{relative}")


def import_full_package(zip_path: str, base_dir: str) -> PackageImportResult:
    base_name = os.path.splitext(os.path.basename(zip_path))[0]
    import_root = os.path.join(os.path.abspath(base_dir), "imported_assets")
    os.makedirs(import_root, exist_ok=True)
    package_dir = os.path.join(import_root, base_name)
    counter = 1
    while os.path.exists(package_dir):
        package_dir = os.path.join(import_root, f"{base_name}_{counter}")
        counter += 1
    staging = f"{package_dir}.__extracting"
    if os.path.exists(staging):
        shutil.rmtree(staging)
    try:
        safe_extract_full_package(zip_path, staging)
        profile_path = os.path.join(staging, "profile.json")
        manifest_path = os.path.join(staging, "manifest.json")
        if not os.path.isfile(profile_path):
            raise ValueError("全量包缺少 profile.json")
        manifest: dict[str, Any] = {}
        if os.path.isfile(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            accepted = {FULL_PACKAGE_FORMAT, LEGACY_FULL_PACKAGE_FORMAT}
            if not isinstance(manifest, dict) or manifest.get("format") not in accepted:
                raise ValueError("无法识别的全量包格式")
            if int(manifest.get("version", 0) or 0) >= PACKAGE_VERSION:
                _verify_assets(staging, manifest)
        with open(profile_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        def import_mapper(source):
            text = str(source or "").strip().replace("\\", "/")
            if not text.startswith("assets/"):
                return None
            safe_name = _safe_member_name(text)
            candidate = os.path.abspath(os.path.join(package_dir, *safe_name.split("/")))
            assets_root = os.path.abspath(os.path.join(package_dir, "assets"))
            if not candidate.startswith(assets_root + os.sep):
                raise ValueError(f"全量包引用了无效图片路径：{text}")
            staging_candidate = os.path.abspath(os.path.join(staging, *safe_name.split("/")))
            if not os.path.isfile(staging_candidate):
                raise ValueError(f"全量包引用了不存在的图片：{text}")
            return candidate

        profile = rewrite_profile_image_paths(data, import_mapper)
        os.replace(staging, package_dir)
        suggested = str(manifest.get("profile_name", "")).strip() or base_name
        return PackageImportResult(profile, suggested, package_dir)
    except Exception:
        if os.path.exists(staging):
            shutil.rmtree(staging, ignore_errors=True)
        raise
