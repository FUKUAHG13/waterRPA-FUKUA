"""Run source checks and smoke-test complete onedir/onefile builds."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fukua_rpa.constants import (  # noqa: E402
    BUILD_NAME,
    NATIVE_CORE_RELEASE_VERSION,
    ONEFILE_BUILD_NAME,
)


def run(command, env=None):
    print(">", subprocess.list2cmdline([str(value) for value in command]))
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def verify_source():
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], env)
    run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "fukuaRPA.py",
            "fukua_rpa",
            "tests",
            "scripts",
            "--select",
            "F,E9,E722",
        ],
        env,
    )
    with tempfile.TemporaryDirectory() as performance_dir:
        performance_dir = Path(performance_dir)
        core_report = performance_dir / "core.json"
        vision_report = performance_dir / "vision.json"
        native_report = performance_dir / "native.json"
        startup_report = performance_dir / "startup.json"
        run(
            [
                sys.executable,
                "scripts/benchmark_core.py",
                "--rounds",
                "10",
                "--output",
                str(core_report),
                "--assert-limits",
            ],
            env,
        )
        run(
            [
                sys.executable,
                "scripts/benchmark_vision.py",
                "--rounds",
                "10",
                "--output",
                str(vision_report),
                "--assert-limits",
            ],
            env,
        )
        run(
            [
                sys.executable,
                "scripts/benchmark_native_scheduler.py",
                "--rounds",
                "10",
                "--output",
                str(native_report),
                "--assert-limits",
            ],
            env,
        )
        run(
            [
                sys.executable,
                "scripts/smoke_startup.py",
                "--assert-limits",
                "--output",
                str(startup_report),
            ],
            env,
        )
        run(
            [
                sys.executable,
                "scripts/compare_performance.py",
                "--baseline",
                "docs/PERFORMANCE_BASELINE.json",
                "--report",
                f"core={core_report}",
                "--report",
                f"vision={vision_report}",
                "--report",
                f"native={native_report}",
                "--report",
                f"startup={startup_report}",
            ],
            env,
        )
    run(
        [
            sys.executable,
            "scripts/soak_runtime.py",
            "--rounds",
            "20000",
            "--assert-limits",
        ],
        env,
    )
    run([sys.executable, "scripts/smoke_native_vision.py"], env)
    run([sys.executable, "scripts/smoke_uia_control.py"], env)
    required = [
        ROOT / "fukua_rpa_core.dll",
        ROOT / "assets" / "fukuaRPA.ico",
        ROOT / "assets" / "version_info.txt",
        ROOT / "assets" / "version_info_onefile.txt",
        ROOT / "fukuaRPA_onedir.spec",
        ROOT / "fukuaRPA_onefile.spec",
        ROOT / "scripts" / "build_release.py",
        ROOT / "scripts" / "audit_runtime_closure.py",
        ROOT / "scripts" / "create_build_record.py",
        ROOT / "scripts" / "create_sbom.py",
        ROOT / "scripts" / "create_release_info.py",
        ROOT / "scripts" / "create_payload_hashes.py",
        ROOT / "scripts" / "create_release_manifest.py",
        ROOT / "scripts" / "create_release_readme.py",
        ROOT / "scripts" / "create_release_archive.py",
        ROOT / "scripts" / "create_release_checksums.py",
        ROOT / "scripts" / "benchmark_native_scheduler.py",
        ROOT / "scripts" / "runtime_pruning.py",
        ROOT / "scripts" / "smoke_startup.py",
        ROOT / "scripts" / "compare_performance.py",
        ROOT / "docs" / "PERFORMANCE_BASELINE.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing release files: {missing}")
    for spec_name in ("fukuaRPA_onedir.spec", "fukuaRPA_onefile.spec"):
        spec = (ROOT / spec_name).read_text(encoding="utf-8")
        if "upx=False" not in spec:
            raise RuntimeError(f"Release spec must keep UPX disabled: {spec_name}")


def verify_packaged_smokes(executable: Path, cwd: Path, timeout=120):
    from scripts.smoke_startup import run_startup_smoke

    startup_report = run_startup_smoke(
        executable, timeout=timeout, assert_limits=True
    )
    print(json.dumps(startup_report, ensure_ascii=False, indent=2))
    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "self-test.json"
        subprocess.run(
            [str(executable), "--self-test-file", str(report_path)],
            cwd=cwd,
            check=True,
            timeout=timeout,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        failures = [item for item in report["checks"] if not item["ok"]]
        if not report.get("ok") or failures:
            raise RuntimeError(f"Packaged self-test failed: {failures}")
        if report.get("build_name") != BUILD_NAME:
            raise RuntimeError(f"Packaged build identity mismatch: {report}")
        print(json.dumps(report, ensure_ascii=False, indent=2))

        uia_report_path = Path(temp_dir) / "uia-smoke.json"
        subprocess.run(
            [str(executable), "--uia-smoke-file", str(uia_report_path)],
            cwd=cwd,
            check=True,
            timeout=timeout,
        )
        uia_report = json.loads(uia_report_path.read_text(encoding="utf-8"))
        if not uia_report.get("ok") or not uia_report.get(
            "foreground_unchanged"
        ):
            raise RuntimeError(f"Packaged UIA smoke failed: {uia_report}")
        if not uia_report.get("matched_bound_hwnd"):
            raise RuntimeError(
                f"Packaged UIA did not select the bound control: {uia_report}"
            )
        if not uia_report.get("set_value_ok") or not uia_report.get(
            "read_value_ok"
        ):
            raise RuntimeError(
                f"Packaged UIA text round trip failed: {uia_report}"
            )
        print(json.dumps(uia_report, ensure_ascii=False, indent=2))

        native_report_path = Path(temp_dir) / "native-smoke.json"
        subprocess.run(
            [str(executable), "--native-smoke-file", str(native_report_path)],
            cwd=cwd,
            check=True,
            timeout=timeout,
        )
        native_report = json.loads(native_report_path.read_text(encoding="utf-8"))
        if not native_report.get("ok") or not native_report.get("parity", {}).get(
            "within_tolerance"
        ):
            raise RuntimeError(f"Packaged native smoke failed: {native_report}")
        print(json.dumps(native_report, ensure_ascii=False, indent=2))
        return report


def verify_dist(dist_dir: Path):
    from scripts.runtime_pruning import find_prunable_runtime_paths

    executable = dist_dir / f"{BUILD_NAME}.exe"
    if not executable.is_file():
        raise RuntimeError(f"Packaged executable not found: {executable}")
    unexpected_payloads = find_prunable_runtime_paths(dist_dir)
    if unexpected_payloads:
        raise RuntimeError(
            f"Pruned runtime payloads reappeared: {unexpected_payloads}"
        )
    build_info_path = dist_dir / "BUILD_INFO.json"
    if not build_info_path.is_file():
        raise RuntimeError(f"Build record not found: {build_info_path}")
    build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
    if build_info.get("build_name") != BUILD_NAME:
        raise RuntimeError(f"Build record identity mismatch: {build_info}")
    if int(build_info.get("native_core", {}).get("api_version", 0)) < NATIVE_CORE_RELEASE_VERSION:
        raise RuntimeError(f"Native core API is too old: {build_info}")
    native_abi = build_info.get("native_core", {}).get("abi", {})
    build_flags = native_abi.get("build_flags", {})
    if not native_abi.get("compatible") or native_abi.get("pointer_bits") != 64:
        raise RuntimeError(f"Native core ABI contract failed: {native_abi}")
    for flag in ("x64", "static_crt", "cpp17", "windows10_target", "msvc"):
        if not build_flags.get(flag):
            raise RuntimeError(f"Native core build flag is missing: {flag}")
    if not build_info.get("source_sha256"):
        raise RuntimeError("Build record has no source fingerprint")
    required_materials = [
        dist_dir / "LICENSE",
        dist_dir / "SBOM.cdx.json",
        dist_dir / "THIRD_PARTY_NOTICES.txt",
        dist_dir / "THIRD_PARTY_LICENSES.txt",
        dist_dir / "RELEASE_INFO.json",
        dist_dir / "PAYLOAD_HASHES.json",
        dist_dir / "README_RELEASE.txt",
        dist_dir / "RUNTIME_CLOSURE.json",
    ]
    missing_materials = [str(path) for path in required_materials if not path.is_file()]
    if missing_materials:
        raise RuntimeError(f"Release trust materials are missing: {missing_materials}")
    run(
        [
            sys.executable,
            "scripts/audit_runtime_closure.py",
            str(dist_dir),
            "--output",
            str(dist_dir / "RUNTIME_CLOSURE.json"),
            "--check",
        ]
    )
    sbom = json.loads((dist_dir / "SBOM.cdx.json").read_text(encoding="utf-8"))
    component_names = {
        str(item.get("name", "")).casefold() for item in sbom.get("components", [])
    }
    for required_name in ("uiautomation", "comtypes", "pyside6", "opencv-python"):
        if required_name.casefold() not in component_names:
            raise RuntimeError(f"SBOM is missing runtime dependency: {required_name}")
    release_info = json.loads(
        (dist_dir / "RELEASE_INFO.json").read_text(encoding="utf-8")
    )
    if release_info.get("build_name") != BUILD_NAME:
        raise RuntimeError(f"Release info identity mismatch: {release_info}")
    from scripts.create_release_info import hash_file

    if release_info.get("executable", {}).get("sha256") != hash_file(executable):
        raise RuntimeError("Release info executable hash mismatch")
    if release_info.get("sbom", {}).get("sha256") != hash_file(
        dist_dir / "SBOM.cdx.json"
    ):
        raise RuntimeError("Release info SBOM hash mismatch")
    if release_info.get("runtime_closure", {}).get("sha256") != hash_file(
        dist_dir / "RUNTIME_CLOSURE.json"
    ):
        raise RuntimeError("Release info runtime closure hash mismatch")
    code_payloads = {
        str(item.get("role")): item
        for item in release_info.get("code_payloads", [])
        if isinstance(item, dict)
    }
    for role in ("main_executable", "native_core", "uia_bitmap_helper"):
        item = code_payloads.get(role)
        if not item:
            raise RuntimeError(f"Release info is missing code payload: {role}")
        relative = PurePosixPath(str(item.get("path", "")))
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or any(":" in part for part in relative.parts)
        ):
            raise RuntimeError(f"Release info has unsafe code payload path: {role}")
        payload_path = dist_dir.joinpath(*relative.parts).resolve()
        try:
            payload_path.relative_to(dist_dir.resolve())
        except ValueError as error:
            raise RuntimeError(
                f"Release info code payload escapes release directory: {role}"
            ) from error
        if not payload_path.is_file() or item.get("sha256") != hash_file(payload_path):
            raise RuntimeError(f"Release code payload hash mismatch: {role}")
    from fukua_rpa.integrity import verify_payload

    payload_report = verify_payload(dist_dir)
    if not payload_report.get("ok"):
        raise RuntimeError(f"Packaged payload verification failed: {payload_report}")
    verify_packaged_smokes(executable, dist_dir)


def verify_onefile(executable: Path):
    executable = executable.resolve()
    if not executable.is_file():
        raise RuntimeError(f"Packaged onefile executable not found: {executable}")
    if executable.name.casefold() != f"{ONEFILE_BUILD_NAME}.exe".casefold():
        raise RuntimeError(f"Unexpected onefile executable name: {executable.name}")

    from scripts.audit_runtime_closure import (
        AMD64_MACHINE,
        classify_dependency,
        pe_imports,
        system_dll_names,
    )

    machine, imports = pe_imports(executable)
    if machine != AMD64_MACHINE:
        raise RuntimeError(f"Onefile bootloader is not AMD64: 0x{machine:04X}")
    package_index = {executable.name.casefold(): [executable.name]}
    system_names = system_dll_names()
    unresolved = [
        dependency
        for dependency in imports
        if classify_dependency(
            dependency,
            package_index,
            system_names,
        )
        == "unresolved"
    ]
    if unresolved:
        raise RuntimeError(
            f"Onefile bootloader has unresolved imports: {sorted(unresolved)}"
        )

    report = verify_packaged_smokes(executable, executable.parent, timeout=180)
    expected_base = os.path.normcase(str(executable.parent))
    actual_base = os.path.normcase(os.path.abspath(str(report.get("base_dir", ""))))
    if actual_base != expected_base:
        raise RuntimeError(
            "Onefile writable data path escaped the executable directory: "
            f"expected={expected_base}, actual={actual_base}"
        )
    if not report.get("frozen"):
        raise RuntimeError("Onefile diagnostics did not report a frozen runtime")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dist", type=Path, help=f"Path to the built {BUILD_NAME} directory"
    )
    parser.add_argument(
        "--onefile",
        type=Path,
        help=f"Path to the built {ONEFILE_BUILD_NAME}.exe",
    )
    parser.add_argument(
        "--skip-source",
        action="store_true",
        help="Skip source quality gates when they already ran in this build job.",
    )
    args = parser.parse_args()
    if not args.skip_source:
        verify_source()
    if args.dist:
        verify_dist(args.dist.resolve())
    if args.onefile:
        verify_onefile(args.onefile.resolve())
    print("Release verification passed.")


if __name__ == "__main__":
    main()
