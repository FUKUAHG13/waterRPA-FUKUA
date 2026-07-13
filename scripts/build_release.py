"""Build complete fukuaRPA releases; onedir is the safe default."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fukua_rpa.constants import (  # noqa: E402
    APP_VERSION,
    BUILD_NAME,
    ONEFILE_BUILD_NAME,
)


def run(command):
    print(">", subprocess.list2cmdline([str(value) for value in command]), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def write_checksums(paths, output):
    command = [
        sys.executable,
        "scripts/create_release_checksums.py",
        *[str(path) for path in paths],
        "--output",
        str(output),
    ]
    run(command)
    run([*command, "--check"])


def build_onedir(skip_quality=False):
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "fukuaRPA_onedir.spec",
        ]
    )
    release_dir = ROOT / "dist" / BUILD_NAME
    closure_path = release_dir / "RUNTIME_CLOSURE.json"
    run(
        [
            sys.executable,
            "scripts/audit_runtime_closure.py",
            str(release_dir),
            "--output",
            str(closure_path),
        ]
    )
    run(
        [
            sys.executable,
            "scripts/audit_runtime_closure.py",
            str(release_dir),
            "--output",
            str(closure_path),
            "--check",
        ]
    )
    run([sys.executable, "scripts/create_build_record.py", str(release_dir)])
    run(
        [
            sys.executable,
            "scripts/create_sbom.py",
            str(release_dir),
            "--app-version",
            APP_VERSION,
            "--build-name",
            BUILD_NAME,
        ]
    )
    run([sys.executable, "scripts/create_release_readme.py", str(release_dir)])
    run(
        [
            sys.executable,
            "scripts/create_release_info.py",
            str(release_dir),
            "--build-name",
            BUILD_NAME,
        ]
    )
    run([sys.executable, "scripts/create_payload_hashes.py", str(release_dir)])
    run(
        [
            sys.executable,
            "scripts/create_payload_hashes.py",
            str(release_dir),
            "--check",
        ]
    )
    if not skip_quality:
        run(
            [
                sys.executable,
                "scripts/verify_release.py",
                "--skip-source",
                "--dist",
                str(release_dir),
            ]
        )

    manifest_path = ROOT / "dist" / f"{BUILD_NAME}_manifest.json"
    manifest_command = [
        sys.executable,
        "scripts/create_release_manifest.py",
        str(release_dir),
        "--output",
        str(manifest_path),
    ]
    run(manifest_command)
    run([*manifest_command, "--check"])

    archive_path = ROOT / "dist" / f"{BUILD_NAME}_portable.zip"
    archive_command = [
        sys.executable,
        "scripts/create_release_archive.py",
        str(release_dir),
        "--manifest",
        str(manifest_path),
        "--output",
        str(archive_path),
    ]
    run(archive_command)
    run([*archive_command, "--check"])

    checksums_path = ROOT / "dist" / f"{BUILD_NAME}_SHA256SUMS.txt"
    write_checksums([archive_path, manifest_path], checksums_path)
    print(f"Onedir release ready: {release_dir}")
    return [archive_path, manifest_path]


def build_onefile(skip_quality=False):
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "fukuaRPA_onefile.spec",
        ]
    )
    executable = ROOT / "dist" / f"{ONEFILE_BUILD_NAME}.exe"
    if not executable.is_file():
        raise RuntimeError(f"Onefile build was not created: {executable}")
    if not skip_quality:
        run(
            [
                sys.executable,
                "scripts/verify_release.py",
                "--skip-source",
                "--onefile",
                str(executable),
            ]
        )
    checksums_path = ROOT / "dist" / f"{ONEFILE_BUILD_NAME}_SHA256SUMS.txt"
    write_checksums([executable], checksums_path)
    print(f"Onefile release ready: {executable}")
    return [executable]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--format",
        choices=("all", "onedir", "onefile"),
        default="onedir",
        help="Build complete onedir by default; onefile requires an explicit format.",
    )
    parser.add_argument(
        "--skip-quality",
        action="store_true",
        help="Skip tests/benchmarks/package smokes only for local packaging experiments.",
    )
    args = parser.parse_args()

    run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "native_core/build_native_core.ps1",
        ]
    )
    if not args.skip_quality:
        run([sys.executable, "scripts/verify_release.py"])

    artifacts = []
    if args.format in ("all", "onedir"):
        artifacts.extend(build_onedir(skip_quality=args.skip_quality))
    if args.format in ("all", "onefile"):
        artifacts.extend(build_onefile(skip_quality=args.skip_quality))
    if args.format == "all":
        combined = ROOT / "dist" / f"{BUILD_NAME}_all_SHA256SUMS.txt"
        write_checksums(artifacts, combined)
        print(f"Combined checksums: {combined}")


if __name__ == "__main__":
    main()
