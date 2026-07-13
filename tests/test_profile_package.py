import json
import os
import tempfile
import unittest
import zipfile

from fukua_rpa.config_schema import default_profile_config
from fukua_rpa.log_policy import (
    LOG_MODE_CUSTOM,
    LOG_RECOGNITION,
    LOG_TIMESTAMP,
)
from fukua_rpa.profile_package import (
    MissingPackageAssetsError,
    export_full_package,
    import_full_package,
    safe_extract_full_package,
)


class ProfilePackageTests(unittest.TestCase):
    def _profile_with_asset(self, root):
        image_path = os.path.join(root, "target.png")
        with open(image_path, "wb") as handle:
            handle.write(b"not-an-image-but-a-stable-package-asset")
        profile = default_profile_config()
        profile["tasks"] = [{"type": 1.0, "value": image_path}]
        return profile, image_path

    def test_version_three_package_round_trips_and_rewrites_asset_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile, source_asset = self._profile_with_asset(temp_dir)
            package_path = os.path.join(temp_dir, "profile.zip")
            result = export_full_package(profile, "测试方案", package_path)
            self.assertEqual(result.asset_count, 1)
            self.assertFalse(result.missing_images)
            with zipfile.ZipFile(package_path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["version"], 3)
                self.assertEqual(len(manifest["assets"]), 1)

            import_root = os.path.join(temp_dir, "receiver")
            imported = import_full_package(package_path, import_root)
            rewritten = imported.profile["tasks"][0]["value"]
            self.assertEqual(imported.suggested_name, "测试方案")
            self.assertTrue(os.path.isfile(rewritten))
            with open(source_asset, "rb") as source, open(rewritten, "rb") as target:
                self.assertEqual(source.read(), target.read())

    def test_tampered_asset_is_rejected_and_staging_is_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile, _source_asset = self._profile_with_asset(temp_dir)
            package_path = os.path.join(temp_dir, "profile.zip")
            export_full_package(profile, "A", package_path)
            tampered_path = os.path.join(temp_dir, "tampered.zip")
            with zipfile.ZipFile(package_path) as source, zipfile.ZipFile(
                tampered_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as target:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename.startswith("assets/"):
                        data += b"tampered"
                    target.writestr(info.filename, data)

            receiver = os.path.join(temp_dir, "receiver")
            with self.assertRaisesRegex(ValueError, "校验失败"):
                import_full_package(tampered_path, receiver)
            imported_root = os.path.join(receiver, "imported_assets")
            leftovers = os.listdir(imported_root) if os.path.isdir(imported_root) else []
            self.assertFalse(any(name.endswith(".__extracting") for name in leftovers))

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = os.path.join(temp_dir, "unsafe.zip")
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr("profile.json", "{}")
                archive.writestr("../outside.txt", "bad")
            with self.assertRaisesRegex(ValueError, "不安全路径"):
                safe_extract_full_package(package_path, os.path.join(temp_dir, "extract"))
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "outside.txt")))

    def test_windows_ads_and_device_names_are_rejected(self):
        unsafe_names = ["assets/image.png:stream", "assets/NUL.txt", "assets/image.png. "]
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, unsafe_name in enumerate(unsafe_names):
                package_path = os.path.join(temp_dir, f"unsafe_{index}.zip")
                with zipfile.ZipFile(package_path, "w") as archive:
                    archive.writestr("profile.json", "{}")
                    archive.writestr(unsafe_name, "bad")
                with self.subTest(name=unsafe_name), self.assertRaisesRegex(
                    ValueError, "不安全路径"
                ):
                    safe_extract_full_package(
                        package_path, os.path.join(temp_dir, f"extract_{index}")
                    )

    def test_failed_export_does_not_replace_existing_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = os.path.join(temp_dir, "profile.zip")
            with open(destination, "wb") as handle:
                handle.write(b"previous")
            profile = default_profile_config()
            profile["tasks"] = [{"type": 1.0, "value": os.path.join(temp_dir, "missing.png")}]
            with self.assertRaises(MissingPackageAssetsError) as caught:
                export_full_package(profile, "A", destination)
            self.assertEqual(len(caught.exception.paths), 1)
            with open(destination, "rb") as handle:
                self.assertEqual(handle.read(), b"previous")
            temp_files = [name for name in os.listdir(temp_dir) if name.endswith(".tmp")]
            self.assertEqual(temp_files, [])

    def test_custom_log_policy_survives_full_package_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = default_profile_config()
            profile.update(
                {
                    "log_level": 2,
                    "log_mode": LOG_MODE_CUSTOM,
                    "log_custom_categories": [
                        LOG_RECOGNITION,
                        LOG_TIMESTAMP,
                    ],
                }
            )
            package_path = os.path.join(temp_dir, "custom-logging.zip")

            export_full_package(profile, "自定义日志", package_path)
            imported = import_full_package(
                package_path, os.path.join(temp_dir, "receiver")
            )

            self.assertEqual(imported.profile["log_mode"], LOG_MODE_CUSTOM)
            self.assertEqual(
                imported.profile["log_custom_categories"],
                [LOG_RECOGNITION, LOG_TIMESTAMP],
            )

    def test_extensionless_image_reference_is_rewritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "template_without_extension")
            with open(source, "wb") as handle:
                handle.write(b"package-asset")
            profile = default_profile_config()
            profile["tasks"] = [{"type": 1.0, "value": source}]
            package_path = os.path.join(temp_dir, "profile.zip")

            export_full_package(profile, "A", package_path)
            imported = import_full_package(
                package_path, os.path.join(temp_dir, "receiver")
            )

            rewritten = imported.profile["tasks"][0]["value"]
            self.assertNotEqual(rewritten, source)
            self.assertTrue(os.path.isfile(rewritten))


if __name__ == "__main__":
    unittest.main()
