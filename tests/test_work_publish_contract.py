"""Skill share contract: POST /api/entries publishes a work immediately.

``community-share`` sends ``{"entry": {...}}`` and expects ``id`` plus
``kind == "work"`` back.  This test pins that contract so a change to the
browser payload cannot silently break the Skill's publishing path.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.legacy_database import init_legacy_database
from backend import server as server_module
from backend.config import SESSION_COOKIE_NAME
from backend.server import create_channel_server
from backend.services import register_user

IMG = "/images/individual/FA/FA-013.webp"


class EntryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.db = init_legacy_database(Path(cls.temp.name) / "entry.db")
        register_user(cls.db, "skill_user", "password-1")
        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.token = None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.db.get_conn().close()
        cls.db.close()
        cls.temp.cleanup()

    def _request(self, path, body=None, token=None, api_key=None, omit_origin=False):
        headers = {}
        if not omit_origin:
            headers["Origin"] = "http://trusted.test"
        if token:
            headers["Cookie"] = f"{SESSION_COOKIE_NAME}={token}"
        if api_key:
            headers["Api-Key"] = api_key
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def _create_api_token(self, scopes: list[str]) -> str:
        user_row = self.db.get_conn().execute("SELECT id FROM users WHERE username = 'skill_user'").fetchone()
        raw_token = f"hwt_test_{hashlib.sha256(os.urandom(16)).hexdigest()}"
        tok_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        tok_id = f"tok_{os.urandom(8).hex()}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO api_tokens (id, user_id, name, scopes, token_hash, created_at, last_used_at, revoked_at)
                VALUES (?, ?, 'SkillToken', ?, ?, '2026-10-31T00:00:00Z', '', '')
                """,
                (tok_id, user_row["id"], json.dumps(scopes), tok_hash),
            )
        return raw_token

    def _login(self):
        if self.token:
            return self.token
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, payload = self._request(
                "/api/auth/login", {"account": "skill_user", "password": "password-1"}
            )
        self.assertEqual(status, 200, payload)
        type(self).token = payload["token"]
        return self.token

    def _entry(self, request_id, **overrides):
        entry = {
            "title": "Skill 分享的作品",
            "prompt": "手绘风提示词正文",
            "originalRequest": "用户原始请求【画风：FA-013】",
            "images": [IMG],
            "styleIds": ["FA-013"],
            "layoutId": "SC-001",
            "requestId": request_id,
        }
        entry.update(overrides)
        return entry

    def test_entry_publishes_a_work_immediately(self):
        token = self._login()
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, result = self._request(
                "/api/entries", {"entry": self._entry("skill-req-1")}, token
            )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["kind"], "work", "Skill requires kind == 'work'")
        self.assertTrue(result["id"])
        self.assertEqual(result["status"], "published")
        self.assertIn(result["id"], result["url"])

    def test_entry_is_idempotent_on_request_id(self):
        token = self._login()
        entry = self._entry("skill-req-dup")
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            _, first = self._request("/api/entries", {"entry": entry}, token)
            _, second = self._request("/api/entries", {"entry": entry}, token)
        self.assertEqual(first["id"], second["id"], "replaying a request must not duplicate the work")
        count = int(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM works WHERE request_id = ?", ("skill-req-dup",))
            .fetchone()[0]
        )
        self.assertEqual(count, 1)

    def test_entry_accepts_the_real_community_share_payload(self):
        """The Skill does not send flat fields; it sends ``content`` + ``assets``.

        This shape comes from ``community_share.work_payload`` and must publish
        without any adapter, otherwise the Skill's real share is rejected.
        """
        token = self._login()
        real_payload = {
            "kind": "work",
            "title": "由真实 Skill 载荷发布",
            "summary": "由手绘风 Skill 生成的作品。",
            "cover_url": IMG,
            "price": 0,
            "paid_opt_in": False,
            "content": {
                "prompt": "原始提示词正文\n【画风：FA-013】【图型：SC-021】",
                "parameters": {"style_ids": ["FA-013"], "layout_ids": ["SC-021"]},
                "examples": [{"theme": "作品2", "image": "/images/individual/FB/FB-001.webp"}],
            },
            "assets": [
                {"ref": "official:FA-013", "role": "style"},
                {"ref": "official:SC-021", "role": "layout"},
            ],
        }
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, result = self._request("/api/entries", {"entry": real_payload}, token)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["kind"], "work")

        row = self.db.get_conn().execute("SELECT * FROM works WHERE id = ?", (result["id"],)).fetchone()
        self.assertEqual(row["origin"], "skill")
        self.assertEqual(row["title"], "由真实 Skill 载荷发布")
        self.assertIn("原始提示词正文", row["prompt"], "content.prompt must be stored verbatim")
        self.assertEqual(json.loads(row["styles_json"]), ["FA-013"])
        self.assertEqual(row["layout_code"], "SC-021")
        images = json.loads(row["images_json"])
        self.assertEqual(images[0], IMG, "cover_url becomes the first image")
        self.assertIn("/images/individual/FB/FB-001.webp", images, "content.examples become attachments")

    def test_entry_maps_skill_vocabulary_and_records_origin(self):
        token = self._login()
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            _, result = self._request(
                "/api/entries",
                {"entry": self._entry("skill-req-vocab", styleIds=["FA-013", "FB-001"])},
                token,
            )
        row = self.db.get_conn().execute("SELECT * FROM works WHERE id = ?", (result["id"],)).fetchone()
        self.assertEqual(row["origin"], "skill")
        self.assertEqual(json.loads(row["styles_json"]), ["FA-013", "FB-001"])
        self.assertEqual(row["layout_code"], "SC-001")
        self.assertIn("用户原始请求", row["notes"])

    def test_missing_entry_object_is_rejected(self):
        token = self._login()
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, payload = self._request("/api/entries", {}, token)
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("code"), "entry_required")

    def test_entry_requires_login(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, _ = self._request("/api/entries", {"entry": self._entry("skill-req-anon")})
        self.assertEqual(status, 401)

    def test_entry_rejects_too_many_images(self):
        token = self._login()
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, payload = self._request(
                "/api/entries",
                {"entry": self._entry("skill-req-many", images=[IMG] * 13)},
                token,
            )
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload.get("code"), "too_many_images")

    def test_entry_publishes_with_api_key_only_no_cookie_no_origin(self):
        api_token = self._create_api_token(["publish"])
        status, result = self._request(
            "/api/entries",
            {"entry": self._entry("skill-req-apikey-ok")},
            api_key=api_token,
            omit_origin=True,
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["kind"], "work")
        self.assertTrue(result["id"])
        self.assertEqual(result["status"], "published")
        self.assertIn(result["id"], result["url"])

    def test_entry_rejects_api_key_without_publish_scope(self):
        lib_token = self._create_api_token(["library"])
        status, payload = self._request(
            "/api/entries",
            {"entry": self._entry("skill-req-lib-denied")},
            api_key=lib_token,
            omit_origin=True,
        )
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload.get("code"), "token_scope_denied")

    def test_entry_rejects_invalid_api_key_no_fallback(self):
        status, payload = self._request(
            "/api/entries",
            {"entry": self._entry("skill-req-invalid")},
            api_key="hwt_nonexistent_token",
            omit_origin=True,
        )
        self.assertEqual(status, 401, payload)


if __name__ == "__main__":
    unittest.main()
