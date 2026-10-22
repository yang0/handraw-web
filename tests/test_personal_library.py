import hashlib
import http.cookiejar
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("personal_library", Path(__file__).parents[1] / "skill-addon/scripts/personal_library.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class LibraryTests(unittest.TestCase):
    def test_structured_import_checks_integrity_and_stays_available_offline(self):
        resource = {"id": "community:demo", "kind": "style", "name": "纸感水彩", "version": "1.0.0", "prompt_zh": "纸感与水彩。", "prompt_en": "Paper and watercolor.", "license": "允许用于个人创作。"}
        digest = hashlib.sha256(json.dumps(resource, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, '校验'):
            self.library.import_definition(resource, '0' * 64, 'demo')
        first = self.library.import_definition(resource, digest, 'demo')
        second = self.library.import_definition(resource, digest, 'demo')
        self.assertEqual(first['id'], second['id'])
        reopened = module.Library(self.library.root)
        self.assertEqual(reopened.get(first['id'])['prompt_zh'], '纸感与水彩。')
        self.assertEqual(len(reopened.index()['resources']), 1)

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

    def test_client_reuses_existing_community_share_cookie_format(self):
        (self.root / "community_auth.json").write_text('{}', encoding="utf-8")
        jar = http.cookiejar.LWPCookieJar(str(self.root / "community_cookies.txt"))
        cookie = http.cookiejar.Cookie(0, "_t", "test-session", None, False,
                                       "handraw-style.com", False, False, "/", True,
                                       True, None, True, None, None, {}, False)
        jar.set_cookie(cookie)
        jar.save(ignore_discard=True)
        with patch.dict(module.os.environ, {"HANDRAW_PROFILE_HOME": str(self.root)}):
            client = module.Client()
        processor = next(handler for handler in client.opener.handlers
                         if isinstance(handler, module.urllib.request.HTTPCookieProcessor))
        self.assertEqual([(c.name, c.value) for c in processor.cookiejar], [("_t", "test-session")])

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

    def test_only_owned_definitions_can_be_updated(self):
        owned = self.library.create("style", "纸感水彩", "自然晕染。", "Natural washes.", "允许个人与商业创作。")
        updated = self.library.update(owned["id"], name="我的水彩二版", version="1.1.0")
        self.assertEqual(updated["version"], "1.1.0")
        path, digest = self.bundle()
        collected = self.library.import_bundle(path, digest, "community-001")
        with self.assertRaisesRegex(ValueError, "只能修改"):
            self.library.update(collected["id"], name="冒充原创")


if __name__ == "__main__":
    unittest.main()
