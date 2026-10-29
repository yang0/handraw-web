"""Server-rendered HTML must never contain a paid work's recipe.

The reviewer objected that the earlier test only grepped the source for a
truncation pattern instead of making a request.  This one starts a real server
and reads the actual bytes for every route that renders works.
"""
from __future__ import annotations

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
from backend.services import publish_user_work, register_user

IMG = "/images/individual/FA/FA-013.webp"
SECRET = "TOPSECRET-RECIPE-XYZ-123456789"


class PaidPromptNeverServedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.db = server_module.init_database(Path(cls.temp.name) / "ssr.db")
        author, _ = register_user(cls.db, "ssr_author", "password-a")
        cls.paid = publish_user_work(
            cls.db,
            author,
            {"title": "SSR付费作品", "prompt": SECRET, "images": [IMG], "styles": ["FA-013"], "price": 10},
        )
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

    def test_no_route_serves_the_paid_recipe(self):
        work_id = self.paid["workId"]
        routes = [
            "/",
            f"/?view=work&id={work_id}",
            f"/forum/?view=resource&kind=work&id={work_id}",
            "/api/boot",
            f"/work/{work_id}",
        ]
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            for route in routes:
                status, body = self._fetch(route)
                self.assertEqual(status, 200, route)
                self.assertNotIn(SECRET, body, f"paid recipe leaked at {route}")

    def test_free_work_recipe_is_served_so_the_probe_is_valid(self):
        # Control: the same routes do render a free work's recipe, which proves
        # the negative assertion above is not vacuous.
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, body = self._fetch(f"/?view=work&id={self.free['workId']}")
        self.assertEqual(status, 200)
        self.assertIn("FREE-RECIPE-VISIBLE", body)

    def test_boot_payload_hides_the_paid_recipe(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            _, body = self._fetch("/api/boot")
        boot = json.loads(body)
        work = next(w for w in boot["works"] if w["id"] == self.paid["workId"])
        self.assertEqual(work["prompt"], "")


if __name__ == "__main__":
    unittest.main()
