"""#91: real HTTP private-gallery upload and retry regression (temporary SQLite).

Existing application fixes cover Base64 body headroom and progressive UI; this
suite verifies PNG/JPEG/WebP bytes, permission, no orphan on storage failure,
idempotency and CAS without relying on a paid image provider.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.config import SESSION_COOKIE_NAME
from backend.server import create_channel_server, init_database
from backend.services import register_user


def image_data(fmt: str, rgb: tuple[int, int, int]) -> tuple[str, bytes]:
    out = io.BytesIO()
    Image.new("RGB", (32, 20), rgb).save(out, fmt)
    raw = out.getvalue()
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt]
    return "data:" + mime + ";base64," + base64.b64encode(raw).decode(), raw


class P0GalleryHTTP91(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.uploads = root / "uploads"
        self.env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "gallery91.sqlite"),
            "HANDRAW_UPLOADS_DIR": str(self.uploads),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_ENABLE_RECHARGE": "0",
            "HANDRAW_DEMO_MODE": "1",
        })
        self.env.start()
        self.db = init_database(root / "gallery91.sqlite")
        _, token_a = register_user(self.db, "qa91_alice", "Pass12345!")
        _, token_b = register_user(self.db, "qa91_bob", "Pass12345!")
        self.alice = f"{SESSION_COOKIE_NAME}={token_a}"
        self.bob = f"{SESSION_COOKIE_NAME}={token_b}"
        self.httpd = create_channel_server(0, "main", self.db)
        self.httpd.allow_demo_routes = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.httpd.server_port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    def request(self, method, path, body=None, cookie=None):
        headers = {"Origin": "http://trusted.test"}
        if cookie:
            headers["Cookie"] = cookie
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, method=method,
                                     data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if
                    "application/json" in response.headers.get("Content-Type", "") else raw)
        except urllib.error.HTTPError as error:
            raw = error.read()
            return error.code, (json.loads(raw) if
                "application/json" in error.headers.get("Content-Type", "") else raw)

    def test_upload_three_real_formats_retry_and_private_owner_get(self):
        ids = []
        for i, fmt in enumerate(("PNG", "JPEG", "WEBP")):
            with self.subTest(fmt=fmt):
                data_url, payload = image_data(fmt, (40 + i * 40, 60, 120))
                uid = str(uuid.uuid4())
                ids.append(uid)
                name = "PNG 主图" if fmt == "PNG" else "新素材-" + fmt
                category = ("characters", "props", "scenes")[i]
                request = {"uid": uid, "name": name, "cat": category,
                           "dataUrl": data_url, "origin": "web",
                           "sha256": hashlib.sha256(payload).hexdigest()}
                status, result = self.request("PUT", "/api/library/assets/" + uid,
                                              request, self.alice)
                self.assertEqual(status, 201, result)
                self.assertEqual(result["uid"], uid)
                self.assertEqual(result["cat"], category)
                self.assertEqual(result["name"], name)
                self.assertEqual(result["revision"], 1)
                self.assertNotIn("data:", json.dumps(result))
                url = "/api/library/assets/" + uid + "/image"
                image_status, content = self.request("GET", url, cookie=self.alice)
                self.assertEqual(image_status, 200, content)
                self.assertEqual(content, payload)
                self.assertIn(self.request("GET", url, cookie=self.bob)[0], (403, 404))
                self.assertIn(self.request("GET", url)[0], (401, 403))
                # Browser may not see a committed response after network drop:
                # same UID and exact bytes must be safe to retry.
                retry_status, retried = self.request(
                    "PUT", "/api/library/assets/" + uid, request, self.alice)
                self.assertEqual(retry_status, 200, retried)
                self.assertEqual(retried["revision"], 1)
                self.assertEqual(retried["uid"], uid)
        status, listing = self.request("GET", "/api/library/assets?limit=20",
                                       cookie=self.alice)
        self.assertEqual(status, 200)
        self.assertEqual({r["uid"] for r in listing["items"]}, set(ids))
        row = self.db.get_conn().execute(
            "SELECT COUNT(*) FROM user_uploads WHERE user_id=(SELECT id FROM users WHERE username='qa91_alice')"
        ).fetchone()
        self.assertEqual(row[0], 3, "Retries must not create duplicate rows")
        self.assertEqual(len(list(self.uploads.glob("UPL-*"))), 3)

    def test_invalid_image_bad_hash_conflict_and_private_listing(self):
        uid = str(uuid.uuid4())
        path = "/api/library/assets/" + uid
        data_url, _ = image_data("PNG", (85, 12, 205))
        for body, code in [
            ({"name": "no image"}, "missing_data_url"),
            ({"name": "truncated", "dataUrl": "data:image/png;base64,AA=="}, "invalid_image"),
            ({"name": "wrong sha", "dataUrl": data_url, "sha256": "0" * 64}, "sha256_mismatch"),
        ]:
            with self.subTest(case=body["name"]):
                status, err = self.request("PUT", path, body, self.alice)
                self.assertEqual(status, 400, err)
                self.assertEqual(err.get("code"), code, err)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM user_uploads").fetchone()[0], 0)
        status, created = self.request("PUT", path,
            {"name": "source", "cat": "other", "dataUrl": data_url}, self.alice)
        self.assertEqual(status, 201, created)
        status, no_rev = self.request("PUT", path,
            {"name": "should fail update"}, self.alice)
        self.assertEqual(status, 400, no_rev)
        self.assertEqual(no_rev.get("code"), "missing_base_revision")
        status, updated = self.request("PUT", path,
            {"name": "renamed", "baseRevision": 1}, self.alice)
        self.assertEqual(status, 200, updated)
        status, stale = self.request("PUT", path,
            {"name": "stale", "baseRevision": 1}, self.alice)
        self.assertEqual(status, 409, stale)
        self.assertEqual(stale["code"], "conflict")
        self.assertEqual(stale["current"]["revision"], 2)
        status, foreign = self.request("GET", path, cookie=self.bob)
        self.assertIn(status, (403, 404))
        self.assertEqual(self.request("GET", "/api/library/assets",
                                      cookie=self.bob)[1]["items"], [])
        self.assertEqual(self.request("GET", "/api/library/assets",
                                      cookie=self.alice)[1]["items"][0]["name"], "renamed")

    def test_storage_failure_returns_503_no_db_row_and_same_uid_retry(self):
        data_url, _ = image_data("WEBP", (5, 40, 95))
        uid = str(uuid.uuid4())
        path = "/api/library/assets/" + uid
        body = {"name": "Retry after storage outage", "cat": "scenes",
                "dataUrl": data_url, "origin": "web"}
        with patch("backend.user_library._persist_library_image",
                   side_effect=OSError("simulated storage outage")):
            status, failed = self.request("PUT", path, body, self.alice)
        self.assertEqual(status, 503, failed)
        self.assertEqual(failed.get("code"), "library_storage_unavailable")
        self.assertNotIn(data_url, json.dumps(failed))
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM user_uploads").fetchone()[0], 0)
        status, created = self.request("PUT", path, body, self.alice)
        self.assertEqual(status, 201, created)
        self.assertEqual(created["uid"], uid)
        self.assertEqual(len(list(self.uploads.glob("UPL-*"))), 1)


if __name__ == "__main__":
    unittest.main()
