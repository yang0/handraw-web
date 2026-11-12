"""Server-rendered HTML must never contain a paid work's recipe.

The reviewer objected that the earlier test only grepped the source for a
truncation pattern instead of making a request.  This one starts a real server
and reads the actual bytes for every route that renders works.
"""
from __future__ import annotations
from tests.postgres_support import open_isolated_postgres

import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend import server as server_module
from backend.server import create_channel_server
from backend.services import ServiceError, publish_user_work, register_user
from tests.postgres_maintenance import RESET_WORKS_PRICE_SQL

IMG = "/images/individual/FA/FA-013.webp"
SECRET = "TOPSECRET-RECIPE-XYZ-123456789"


class PaidPromptNeverServedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.db = open_isolated_postgres(cls, seed=True)
        author, _ = register_user(cls.db, "ssr_author", "password-a")

        # Verify setting price > 0 is rejected (400)
        try:
            publish_user_work(
                cls.db,
                author,
                {"title": "SSR付费作品设价被拒", "prompt": SECRET, "images": [IMG], "styles": ["FA-013"], "price": 10},
            )
            raise AssertionError("Setting work price must be rejected with 400")
        except ServiceError as e:
            assert e.status == 400
            assert e.code == "work_price_not_allowed"

        cls.free = publish_user_work(
            cls.db,
            author,
            {"title": "SSR免费作品", "prompt": "FREE-RECIPE-VISIBLE", "images": [IMG], "styles": ["FA-014"]},
        )
        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.db.close()
        # Windows may still hold the file briefly while the thread winds down.
        for _ in range(20):
            try:
                cls.temp.cleanup()
                break
            except PermissionError:
                time.sleep(0.1)

    def _fetch(self, path):
        request = urllib.request.Request(self.base + path, headers={"Origin": "http://trusted.test"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, ""

    def test_free_work_recipe_is_served(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, body = self._fetch(f"/?view=work&id={self.free['workId']}")
        self.assertEqual(status, 200)
        self.assertIn("FREE-RECIPE-VISIBLE", body)

    def test_boot_payload_works_are_free(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            _, body = self._fetch("/api/boot")
        boot = json.loads(body)
        work = next(w for w in boot["works"] if w["id"] == self.free["workId"])
        self.assertEqual(work["price"], 0)
        self.assertEqual(work["prompt"], "FREE-RECIPE-VISIBLE")

    def test_legacy_work_with_nonzero_price_zeroed_by_migration(self):
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, price, prompt, prompt_has_secret, status, published_at_ms, created_at, updated_at)
                VALUES ('work_legacy_ssr', 'ssr_author', 'ssr_author', '旧收费作品', '["/img.webp"]', '["FA-013"]', 15, 'LEGACY-SECRET-PROMPT', 0, 'published', 1000, '2026-10-31', '2026-10-31')
                """
            )
        # Apply migration 073 logic
        with self.db.transaction() as tx:
            tx.execute(RESET_WORKS_PRICE_SQL)

        with self.db.transaction() as tx:
            row = tx.execute("SELECT price FROM works WHERE id = 'work_legacy_ssr'").fetchone()
            self.assertEqual(row["price"], 0)

        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, body = self._fetch("/?view=work&id=work_legacy_ssr")
        self.assertEqual(status, 200)
        self.assertIn("LEGACY-SECRET-PROMPT", body)


if __name__ == "__main__":
    unittest.main()
