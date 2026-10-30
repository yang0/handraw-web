"""Governance through the HTTP layer, plus the pages a user actually opens.

The sixth review's core criticism was that the governance fixes had no tests:
reverting any of them left the suite green.  These cases drive the real
endpoints and the real rendered pages.
"""
from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend import server as server_module
from backend.config import SESSION_COOKIE_NAME
from backend.server import create_channel_server
from backend.services import publish_user_work, register_user

IMG = "/images/individual/FA/FA-013.webp"


class _HttpBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The origin guard is enforced per request, so the allow-list must be in
        # place for the whole class, not just inside individual test bodies.
        cls._env = patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"})
        cls._env.start()
        cls.temp = TemporaryDirectory()
        cls.db = server_module.init_database(Path(cls.temp.name) / "http.db")
        cls.author, _ = register_user(cls.db, "hv_author", "password-a")
        register_user(cls.db, "hv_admin", "password-admin")
        cls.db.get_conn().execute("UPDATE users SET role = 'admin' WHERE username = 'hv_admin'")
        cls.db.get_conn().commit()
        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.tokens = {}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.db.close_thread_conn()
        cls.db.get_conn().close()
        cls.db.close()
        cls.temp.cleanup()
        cls._env.stop()

    def _login(self, username, password):
        if username in self.tokens:
            return self.tokens[username]
        status, payload = self._request(
            "POST", "/api/auth/login", {"account": username, "password": password}
        )
        self.assertEqual(status, 200, payload)
        self.tokens[username] = payload["token"]
        return payload["token"]

    def _request(self, method, path, body=None, token=None):
        headers = {"Origin": "http://trusted.test"}
        if token:
            headers["Cookie"] = f"{SESSION_COOKIE_NAME}={token}"
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, self._decode(response)
        except urllib.error.HTTPError as error:
            return error.code, self._decode(error)

    @staticmethod
    def _decode(response):
        raw = response.read()
        ctype = response.headers.get("Content-Type", "")
        if "json" in ctype:
            return json.loads(raw)
        return raw.decode("utf-8", "replace")


class ForumModerateEndpointTests(_HttpBase):
    def setUp(self):
        self.work = publish_user_work(
            self.db,
            self.author,
            {"title": "前台治理", "prompt": "p", "images": [IMG], "styles": ["FA-013"]},
        )

    def _topic_status(self):
        row = self.db.get_conn().execute(
            "SELECT status, status_source FROM forum_topics WHERE id = ?", (self.work["topicId"],)
        ).fetchone()
        self.db.close_thread_conn()
        return (row["status"], row["status_source"])

    def test_frontend_hide_records_a_moderator_source(self):
        token = self._login("hv_admin", "password-admin")
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, payload = self._request(
                "POST", "/api/forum/moderate",
                {"topicId": self.work["topicId"], "action": "hide"}, token,
            )
        self.assertEqual(status, 200, payload)
        self.assertEqual(self._topic_status(), ("hidden", "moderator"))

    def test_frontend_cannot_publish_a_thread_whose_work_is_hidden(self):
        token = self._login("hv_admin", "password-admin")
        self._request("POST", "/api/forum/moderate",
                      {"topicId": self.work["topicId"], "action": "hide"}, token)
        status, payload = self._request(
            "POST", f"/api/works/{self.work['workId']}/moderate",
            {"action": "hide"}, token,
        )
        self.assertEqual(status, 200, payload)
        status, payload = self._request(
            "POST", "/api/forum/moderate",
            {"topicId": self.work["topicId"], "action": "publish"}, token,
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload.get("code"), "work_not_published")
        self.assertEqual(self._topic_status()[0], "hidden")


class PageRendersTests(_HttpBase):
    """The pages a user opens must contain content, not an error or a spinner."""

    def test_home_page_renders(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("hw-", body, "the shell must contain the app markup")
        self.assertNotIn("发现页正在加载", body.replace("\n", ""))

    def test_topic_page_renders_for_a_published_work(self):
        work = publish_user_work(
            self.db, self.author, {"title": "可打开的帖子", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, body = self._request("GET", f"/forum/?view=topic&id={work['topicId']}")
        self.assertEqual(status, 200)
        self.assertIn("forum", body.lower())

    def test_resource_api_serves_a_work(self):
        work = publish_user_work(
            self.db, self.author, {"title": "回读目标", "prompt": "提示词原文", "images": [IMG], "styles": ["FA-013"]}
        )
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, payload = self._request("GET", f"/api/forum/resources/work/{work['workId']}")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["resource"]["id"], work["workId"])
        self.assertEqual(payload["resource"]["prompt"], "提示词原文")

    def test_unknown_api_path_is_json_404(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, payload = self._request("GET", "/api/not-a-real-endpoint")
        self.assertEqual(status, 404)
        self.assertEqual(payload.get("code"), "not_found")

    def test_every_linked_asset_exists(self):
        # A page that links a missing script renders a blank view, which no
        # server-side assertion would otherwise catch.
        import re

        root = Path("demo")
        for page in ("index.html", "studio.html", "forum.html", "admin.html"):
            html = (root / page).read_text(encoding="utf-8")
            refs = set(re.findall(r'["\'](/assets/[^"\'\?]+)', html))
            missing = [ref for ref in refs if not (root / ref.lstrip("/")).is_file()]
            self.assertEqual(missing, [], f"{page} links missing assets")


if __name__ == "__main__":
    unittest.main()
