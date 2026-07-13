"""Write a reproducible source/dependency record into an onedir release."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import struct
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fukua_rpa.constants import APP_VERSION, BUILD_NAME, SUPPORTED_WINDOWS_TEXT
from fukua_rpa.vision import NativeVisionCore


SOURCE_ROOTS = (
    Path("fukuaRPA.py"),
    Path("fukuaRPA_onedir.spec"),
    Path("fukuaRPA_onefile.spec"),
    Path("requirements.txt"),
    Path("fukua_rpa"),
    Path("native_core/fukua_rpa_core.cpp"),
    Path("native_core/build_native_core.ps1"),
    Path("assets/version_info.txt"),
    Path("assets/version_info_onefile.txt"),
    Path("assets/fukuaRPA.ico"),
    Path("assets/fukuaRPA.svg"),
    Path("scripts"),
    Path("tests"),
    Path("docs"),
    Path("README.md"),
    Path("ARCHITECTURE.md"),
    Path("ROADMAP.md"),
    Path("CHANGELOG.md"),
    Path("CONTEXT.md"),
    Path("AGENTS.md"),
)

DEPENDENCIES = (
    "PySide6",
    "opencv-python",
    "numpy",
    "Pillow",
    "PyAutoGUI",
    "mss",
    "psutil",
    "pyperclip",
    "PyInstaller",
    "uiautomation",
    "comtypes",
    "packaging",
    "pefile",
)


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files():
    paths = []
    for item in SOURCE_ROOTS:
        absolute = ROOT / item
        if absolute.is_file():
            paths.append(absolute)
        elif absolute.is_dir():
            paths.extend(
                path
                for path in absolute.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix.lower() not in {".pyc", ".obj", ".lib", ".exp", ".dll"}
            )
    return sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix().casefold())


def source_fingerprint():
    aggregate = hashlib.sha256()
    entries = []
    for path in source_files():
        relative = path.relative_to(ROOT).as_posix()
        checksum = hash_file(path)
        size = path.stat().st_size
        entries.append({"path": relative, "size": size, "sha256": checksum})
        aggregate.update(f"{checksum}  {relative}\n".encode("utf-8"))
    return aggregate.hexdigest(), entries


def dependency_versions():
    versions = {}
    for distribution in DEPENDENCIES:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = "not-installed"
    return versions


def atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dir", type=Path)
    args = parser.parse_args()
    release_dir = args.release_dir.resolve()
    if not release_dir.is_dir():
        raise SystemExit(f"Release directory not found: {release_dir}")
    source_sha256, sources = source_fingerprint()
    native = NativeVisionCore(base_dir=str(ROOT))
    native_health = native.health_snapshot()
    dll_path = ROOT / "fukua_rpa_core.dll"
    report = {
        "format": "fukuaRPA_build_record",
        "format_version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "application_version": APP_VERSION,
        "build_name": BUILD_NAME,
        "supported_windows": SUPPORTED_WINDOWS_TEXT,
        "target": "Windows x64 onedir portable",
        "unsigned": True,
        "network_on_startup": False,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "bits": struct.calcsize("P") * 8,
            "executable": os.path.basename(sys.executable),
        },
        "platform": platform.platform(),
        "dependencies": dependency_versions(),
        "native_core": {
            "api_version": native.version if native.available else 0,
            "available": native.available,
            "capabilities": native.capabilities() if native.available else {},
            "abi": native_health.get("abi", {}),
            "sha256": hash_file(dll_path) if dll_path.is_file() else "",
            "runtime": "MSVC C++17 /O2 /MT",
        },
        "source_sha256": source_sha256,
        "source_file_count": len(sources),
        "sources": sources,
    }
    output = release_dir / "BUILD_INFO.json"
    atomic_write_json(output, report)
    print(
        json.dumps(
            {
                "output": str(output),
                "build_name": BUILD_NAME,
                "source_sha256": source_sha256,
                "source_file_count": len(sources),
                "native_api": report["native_core"]["api_version"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
