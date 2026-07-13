"""Write hashes and real Authenticode status for an onedir release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, data: dict) -> None:
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


def authenticode_status(executable: Path) -> dict:
    script = (
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
        "$p=[Environment]::GetEnvironmentVariable('FUKUA_RELEASE_EXE');"
        "$s=Get-AuthenticodeSignature -LiteralPath $p;"
        "[pscustomobject]@{status=[string]$s.Status;"
        "message=[string]$s.StatusMessage;"
        "subject=[string]$s.SignerCertificate.Subject;"
        "thumbprint=[string]$s.SignerCertificate.Thumbprint}|ConvertTo-Json -Compress"
    )
    try:
        environment = os.environ.copy()
        environment["FUKUA_RELEASE_EXE"] = str(executable)
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=environment,
        )
        result = json.loads(completed.stdout.strip())
        return {
            "status": str(result.get("status") or "Unknown"),
            "message": str(result.get("message") or ""),
            "signer_subject": str(result.get("subject") or ""),
            "signer_thumbprint": str(result.get("thumbprint") or ""),
        }
    except Exception as error:
        return {
            "status": "Unavailable",
            "message": str(error),
            "signer_subject": "",
            "signer_thumbprint": "",
        }


def build_release_info(release_dir: Path, build_name: str) -> dict:
    executable = release_dir / f"{build_name}.exe"
    build_info = release_dir / "BUILD_INFO.json"
    sbom = release_dir / "SBOM.cdx.json"
    for path in (executable, build_info, sbom):
        if not path.is_file():
            raise RuntimeError(f"Required release file not found: {path}")
    build_data = json.loads(build_info.read_text(encoding="utf-8"))
    code_paths = (
        ("main_executable", executable),
        ("native_core", release_dir / "_internal" / "fukua_rpa_core.dll"),
        (
            "uia_bitmap_helper",
            release_dir
            / "_internal"
            / "uiautomation"
            / "bin"
            / "UIAutomationClient_VC140_X64.dll",
        ),
    )
    code_payloads = []
    for role, path in code_paths:
        if not path.is_file():
            continue
        code_payloads.append(
            {
                "role": role,
                "path": path.relative_to(release_dir).as_posix(),
                "size": path.stat().st_size,
                "sha256": hash_file(path),
                "authenticode": authenticode_status(path),
            }
        )
    executable_record = code_payloads[0]
    runtime_closure = release_dir / "RUNTIME_CLOSURE.json"
    return {
        "format": "fukuaRPA_release_info",
        "format_version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "application_version": build_data.get("application_version", ""),
        "build_name": build_name,
        "target": build_data.get("target", "Windows x64 onedir portable"),
        "supported_windows": build_data.get("supported_windows", ""),
        "network_on_startup": False,
        "automatic_update_check": False,
        "update_channel": "manual GitHub releases",
        "update_url": "https://github.com/FUKUAHG13/waterRPA-FUKUA/releases",
        "executable": {
            "path": executable.name,
            "size": executable.stat().st_size,
            "sha256": executable_record["sha256"],
            "authenticode": executable_record["authenticode"],
        },
        "code_payloads": code_payloads,
        "build_record": {
            "path": build_info.name,
            "sha256": hash_file(build_info),
            "source_sha256": build_data.get("source_sha256", ""),
        },
        "sbom": {"path": sbom.name, "sha256": hash_file(sbom)},
        "runtime_closure": (
            {"path": runtime_closure.name, "sha256": hash_file(runtime_closure)}
            if runtime_closure.is_file()
            else {}
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("--build-name", required=True)
    args = parser.parse_args()
    release_dir = args.release_dir.resolve()
    report = build_release_info(release_dir, args.build_name)
    output = release_dir / "RELEASE_INFO.json"
    atomic_write_json(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
