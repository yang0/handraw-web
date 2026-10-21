import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("personal_library", Path(__file__).parents[1] / "skill-addon/scripts/personal_library.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = module.Library(self.root / "private-library")

    def bundle(self, name="resource.zip", extra=None):
        path = self.root / name
        resource = {"id": "original-001", "kind": "style", "name": "纸感水彩", "version": "1.0.0",
                    "prompt_zh": "纯视觉语言，柔和水彩晕染。", "prompt_en": "Soft watercolor washes.", "license": "允许个人与商业创作。"}
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"schema_version": 1, "resource": resource}))
            for entry, value in (extra or {}).items():
                archive.writestr(entry, value)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_import_is_idempotent_and_available_after_network_is_gone(self):
        path, digest = self.bundle()
        first = self.library.import_bundle(path, digest, "community-001")
        second = self.library.import_bundle(path, digest, "community-001")
        path.unlink()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.library.index()["resources"]), 1)
        self.assertEqual(self.library.get(first["id"])["prompt_en"], "Soft watercolor washes.")
        self.assertTrue((self.library.root / first["path"] / "manifest.json").is_file())

    def test_bad_checksum_and_traversal_leave_the_library_unchanged(self):
        path, digest = self.bundle()
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.library.import_bundle(path, "0" * 64)
        malicious, digest = self.bundle("malicious.zip", {"../outside.txt": "unsafe"})
        with self.assertRaisesRegex(ValueError, "不安全"):
            self.library.import_bundle(malicious, digest)
        self.assertFalse((self.root / "outside.txt").exists())
        self.assertEqual(self.library.index()["resources"], [])

    def test_fork_keeps_source_and_does_not_mutate_collected_definition(self):
        path, digest = self.bundle()
        collected = self.library.import_bundle(path, digest, "community-001")
        fork = self.library.fork(collected["id"], "我的改编")
        self.assertEqual(fork["section"], "owned")
        self.assertEqual(fork["origin"]["parent_id"], collected["id"])
        self.assertEqual(self.library.get(collected["id"])["name"], "纸感水彩")

    def test_same_name_different_sources_do_not_overwrite_each_other(self):
        path, digest = self.bundle()
        self.library.import_bundle(path, digest, "community-001")
        self.library.import_bundle(path, digest, "community-002")
        self.assertEqual(len(self.library.index()["resources"]), 2)

    def test_owned_export_can_be_imported_without_installing_into_official_library(self):
        owned = self.library.create("layout", "对照图型", "左右对照布局。", "Two-column comparison.", "允许个人与商业创作。")
        output = self.library.export(owned["id"], self.root / "layout.zip")
        other = module.Library(self.root / "another-user")
        imported = other.import_bundle(output["path"], output["sha256"])
        self.assertEqual(imported["kind"], "layout")
        self.assertEqual(imported["section"], "collected")
        self.assertEqual(self.library.get(owned["id"])["section"], "owned")


if __name__ == "__main__":
    unittest.main()
