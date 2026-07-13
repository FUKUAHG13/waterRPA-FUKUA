import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fukua_rpa.constants import APP_VERSION, BUILD_NAME, ONEFILE_BUILD_NAME
from scripts.audit_runtime_closure import build_runtime_closure
from scripts.create_build_record import source_fingerprint
from scripts.create_release_archive import build_archive, verify_archive
from scripts.create_release_checksums import build_checksums, verify_checksums
from scripts.create_release_info import build_release_info, hash_file
from scripts.create_release_manifest import build_manifest, verify_manifest
from scripts.create_release_readme import release_readme_text
from scripts.create_sbom import build_sbom


ROOT = Path(__file__).resolve().parents[1]


class ReleaseToolingTests(unittest.TestCase):
    def test_source_fingerprint_is_deterministic_and_covers_runtime_core(self):
        first_hash, first_entries = source_fingerprint()
        second_hash, second_entries = source_fingerprint()
        paths = {entry["path"] for entry in first_entries}
        self.assertEqual(first_hash, second_hash)
        self.assertEqual(first_entries, second_entries)
        self.assertEqual(len(first_hash), 64)
        self.assertIn("fukua_rpa/engine.py", paths)
        self.assertIn("native_core/fukua_rpa_core.cpp", paths)
        self.assertIn("fukuaRPA_onedir.spec", paths)
        self.assertIn("fukuaRPA_onefile.spec", paths)
        self.assertIn("assets/version_info_onefile.txt", paths)
        self.assertIn("tests/test_release_tooling.py", paths)
        self.assertIn("docs/adr/0015-native-abi-and-frozen-parity.md", paths)
        self.assertIn("docs/adr/0017-bounded-native-multiscale-scheduler.md", paths)
        self.assertIn("AGENTS.md", paths)
        self.assertIn("assets/fukuaRPA.svg", paths)

    def test_version_identity_is_consistent_in_spec_and_windows_resource(self):
        spec = (ROOT / "fukuaRPA_onedir.spec").read_text(encoding="utf-8")
        onefile_spec = (ROOT / "fukuaRPA_onefile.spec").read_text(
            encoding="utf-8"
        )
        version_info = (ROOT / "assets" / "version_info.txt").read_text(
            encoding="utf-8"
        )
        onefile_version_info = (
            ROOT / "assets" / "version_info_onefile.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("from fukua_rpa.constants import BUILD_NAME", spec)
        self.assertIn('collect_dynamic_libs("uiautomation")', spec)
        self.assertIn("UIAutomationClient_VC140_X64.dll", spec)
        self.assertIn('"pyautogui"', spec)
        self.assertIn("apply_runtime_pruning(a)", spec)
        self.assertIn("name=BUILD_NAME", spec)
        self.assertIn(
            "from fukua_rpa.constants import ONEFILE_BUILD_NAME", onefile_spec
        )
        self.assertIn("a.binaries", onefile_spec)
        self.assertIn("a.datas", onefile_spec)
        self.assertIn("name=ONEFILE_BUILD_NAME", onefile_spec)
        self.assertIn('"pyautogui"', onefile_spec)
        self.assertIn("apply_runtime_pruning(a)", onefile_spec)
        self.assertNotIn("COLLECT(", onefile_spec)
        self.assertIn(f"{APP_VERSION.removeprefix('v')}.0", version_info)
        self.assertIn(f"{BUILD_NAME}.exe", version_info)
        self.assertIn(f"{ONEFILE_BUILD_NAME}.exe", onefile_version_info)
        self.assertEqual(APP_VERSION, "v1.0.12")

    def test_release_builder_defaults_to_complete_onedir(self):
        script = (ROOT / "scripts" / "build_release.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('choices=("all", "onedir", "onefile")', script)
        self.assertIn('default="onedir"', script)
        self.assertIn("build_onedir", script)
        self.assertIn("build_onefile", script)
        self.assertNotIn("lite.spec", script)
        guard = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("没有明确要求单文件版时，只构建完整版多文件版", guard)

    def test_native_build_enforces_static_runtime_and_x64_pe(self):
        build_script = (ROOT / "native_core" / "build_native_core.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("/MT", build_script)
        self.assertIn("/W4", build_script)
        self.assertIn("dumpbin /nologo /dependents", build_script)
        self.assertIn("VCRUNTIME|MSVCP|UCRTBASE|api-ms-win-crt", build_script)
        self.assertIn("8664 machine", build_script)

    def test_build_record_can_target_an_empty_release_directory(self):
        # The script performs only local reads/writes; the actual executable is
        # verified later by verify_release.py after PyInstaller has run.
        with tempfile.TemporaryDirectory() as temp_dir:
            release_dir = Path(temp_dir) / BUILD_NAME
            release_dir.mkdir()
            command = [
                sys.executable,
                str(ROOT / "scripts" / "create_build_record.py"),
                str(release_dir),
            ]
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
            self.assertTrue((release_dir / "BUILD_INFO.json").is_file())

    def test_sbom_contains_new_runtime_and_build_scopes(self):
        sbom, components = build_sbom(APP_VERSION, BUILD_NAME)
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertIn("uiautomation", components)
        self.assertIn("comtypes", components)
        self.assertEqual(components["uiautomation"]["scope"], "runtime")
        self.assertEqual(components["pyinstaller"]["scope"], "build")
        self.assertEqual(components["pefile"]["scope"], "build")
        self.assertFalse(
            any(item.get("missing") for item in components.values())
        )

    def test_release_info_hashes_executable_build_record_and_sbom(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release = Path(temp_dir)
            executable = release / f"{BUILD_NAME}.exe"
            executable.write_bytes(b"portable-executable")
            native_core = release / "_internal" / "fukua_rpa_core.dll"
            uia_helper = (
                release
                / "_internal"
                / "uiautomation"
                / "bin"
                / "UIAutomationClient_VC140_X64.dll"
            )
            native_core.parent.mkdir(parents=True)
            uia_helper.parent.mkdir(parents=True)
            native_core.write_bytes(b"native-core")
            uia_helper.write_bytes(b"uia-helper")
            (release / "BUILD_INFO.json").write_text(
                json.dumps(
                    {
                        "application_version": APP_VERSION,
                        "build_name": BUILD_NAME,
                        "source_sha256": "a" * 64,
                        "target": "Windows x64 onedir portable",
                    }
                ),
                encoding="utf-8",
            )
            (release / "SBOM.cdx.json").write_text("{}\n", encoding="utf-8")
            runtime_closure = release / "RUNTIME_CLOSURE.json"
            runtime_closure.write_text('{"ok": true}\n', encoding="utf-8")
            with mock.patch(
                "scripts.create_release_info.authenticode_status",
                return_value={"status": "NotSigned"},
            ):
                report = build_release_info(release, BUILD_NAME)
            self.assertEqual(report["executable"]["sha256"], hash_file(executable))
            self.assertEqual(report["executable"]["authenticode"]["status"], "NotSigned")
            self.assertFalse(report["network_on_startup"])
            self.assertFalse(report["automatic_update_check"])
            self.assertEqual(
                report["runtime_closure"]["sha256"], hash_file(runtime_closure)
            )
            payloads = {item["role"]: item for item in report["code_payloads"]}
            self.assertEqual(
                set(payloads),
                {"main_executable", "native_core", "uia_bitmap_helper"},
            )
            self.assertEqual(payloads["native_core"]["sha256"], hash_file(native_core))
            self.assertEqual(
                payloads["uia_bitmap_helper"]["sha256"], hash_file(uia_helper)
            )

    def test_manifest_check_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release = Path(temp_dir) / BUILD_NAME
            release.mkdir()
            payload = release / "payload.bin"
            payload.write_bytes(b"original")
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest = build_manifest(release)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(
                verify_manifest(release, manifest_path)["directory_sha256"],
                manifest["directory_sha256"],
            )
            payload.write_bytes(b"tampered")
            with self.assertRaises(RuntimeError):
                verify_manifest(release, manifest_path)

    def test_portable_archive_roundtrip_and_extra_member_rejection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            release = root / BUILD_NAME
            release.mkdir()
            (release / f"{BUILD_NAME}.exe").write_bytes(b"exe")
            internal = release / "_internal"
            internal.mkdir()
            (internal / "payload.bin").write_bytes(b"payload")
            manifest_path = root / f"{BUILD_NAME}_manifest.json"
            manifest_path.write_text(
                json.dumps(build_manifest(release)), encoding="utf-8"
            )
            archive_path = root / f"{BUILD_NAME}_portable.zip"
            build_report = build_archive(release, archive_path)
            verify_report = verify_archive(archive_path, manifest_path)
            self.assertEqual(build_report["file_count"], 2)
            self.assertTrue(verify_report["verified"])
            with zipfile.ZipFile(archive_path, "a") as archive:
                archive.writestr(f"{BUILD_NAME}/unexpected.bin", b"extra")
            with self.assertRaisesRegex(ValueError, "清单外文件"):
                verify_archive(archive_path, manifest_path)

    def test_portable_archive_rejects_noncanonical_member_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            release = root / BUILD_NAME
            release.mkdir()
            payload = release / "payload.bin"
            payload.write_bytes(b"payload")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(build_manifest(release)), encoding="utf-8"
            )
            archive_path = root / "noncanonical.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(f"{BUILD_NAME}/./payload.bin", b"payload")
            with self.assertRaisesRegex(ValueError, "非规范路径"):
                verify_archive(archive_path, manifest_path)

    def test_external_checksums_detect_tampering_and_reject_extra_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "portable.zip"
            manifest = root / "manifest.json"
            archive.write_bytes(b"archive")
            manifest.write_bytes(b"manifest")
            paths = [archive, manifest]
            checksums = build_checksums(paths)
            self.assertTrue(verify_checksums(paths, checksums)["verified"])
            archive.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "校验失败"):
                verify_checksums(paths, checksums)
            with self.assertRaisesRegex(ValueError, "文件列表"):
                verify_checksums(paths, checksums + f"{'0' * 64}  extra.bin\n")

    def test_release_readme_explains_portable_runtime_and_trust_boundary(self):
        text = release_readme_text()
        self.assertIn(BUILD_NAME, text)
        self.assertIn("完整解压", text)
        self.assertIn("启动时不联网", text)
        self.assertIn("不能单独证明发布者身份", text)

    def test_runtime_closure_accepts_x64_static_native_core(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            release = Path(temp_dir) / BUILD_NAME
            release.mkdir()
            shutil.copy2(ROOT / "fukua_rpa_core.dll", release / "fukua_rpa_core.dll")
            report = build_runtime_closure(release)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["pe_file_count"], 1)
            self.assertEqual(report["unresolved_references"], [])
            self.assertEqual(report["wrong_architecture"], [])


if __name__ == "__main__":
    unittest.main()
