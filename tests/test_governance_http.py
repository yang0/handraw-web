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

    def test_admin_entry_also_refuses_when_the_work_is_hidden(self):
        # The two entries share set_topic_visibility, so the admin route must
        # reject for the same reason — this is the case that used to slip past.
        token = self._login("hv_admin", "password-admin")
        self._request("POST", f"/api/works/{self.work['workId']}/moderate", {"action": "hide"}, token)
        status, payload = self._request(
            "POST", f"/api/admin/topics/{self.work['topicId']}/moderate",
            {"action": "publish"}, token,
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload.get("code"), "work_not_published")

    def test_confirming_a_report_cannot_downgrade_a_deleted_thread(self):
        # The confirm path must skip a terminal thread silently: it may resolve
        # the report, but it must not turn 'deleted' back into 'hidden', which
        # would reopen it for a later publish.
        token = self._login("hv_admin", "password-admin")
        from backend.services import submit_abuse_report

        submit_abuse_report(
            self.db,
            self.author,
            {"targetType": "work", "targetId": self.work["workId"], "reason": "垃圾内容"},
        )
        status, payload = self._request(
            "POST", f"/api/works/{self.work['workId']}/moderate", {"action": "delete"}, token
        )
        self.assertEqual(status, 200, payload)

        report = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'work' AND status = 'open' LIMIT 1"
        ).fetchone()
        self.db.close_thread_conn()
        self.assertIsNotNone(report, "the report should still be open")
        status, payload = self._request(
            "POST", f"/api/admin/reports/{report['id']}/resolve",
            {"resolution": "confirmed", "autoAction": True}, token,
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(
            self._topic_status(), ("deleted", "moderator"),
            "confirming a report must not resurrect a deleted thread",
        )

    def test_dismissal_does_not_undo_a_moderator_hidden_topic(self):
        # The dismissal runs as the report flow, so the topic-level moderator
        # guard applies and the hide survives.
        token = self._login("hv_admin", "password-admin")
        self._request("POST", f"/api/admin/topics/{self.work['topicId']}/moderate",
                      {"action": "hide"}, token)
        from backend.services import submit_abuse_report

        submit_abuse_report(
            self.db,
            self.author,
            {"targetType": "work", "targetId": self.work["workId"], "reason": "垃圾内容"},
        )
        report = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'work' AND status = 'open' LIMIT 1"
        ).fetchone()
        self.db.close_thread_conn()
        status, payload = self._request(
            "POST", f"/api/admin/reports/{report['id']}/resolve",
            {"resolution": "dismissed"}, token,
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(self._topic_status(), ("hidden", "moderator"))

    def test_deleted_thread_cannot_be_revived_by_either_entry(self):
        token = self._login("hv_admin", "password-admin")
        status, payload = self._request(
            "POST", f"/api/works/{self.work['workId']}/moderate", {"action": "delete"}, token
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(self._topic_status()[0], "deleted")

        # 'deleted' is terminal: neither entry may publish *or* downgrade it to
        # a lesser hidden state, because that would reopen it for a later publish.
        for path, body in (
            ("/api/forum/moderate", {"topicId": self.work["topicId"], "action": "publish"}),
            ("/api/forum/moderate", {"topicId": self.work["topicId"], "action": "hide"}),
            (f"/api/admin/topics/{self.work['topicId']}/moderate", {"action": "publish"}),
            (f"/api/admin/topics/{self.work['topicId']}/moderate", {"action": "hide"}),
        ):
            status, payload = self._request("POST", path, body, token)
            self.assertEqual(status, 409, f"{path} {body}: {payload}")
            self.assertEqual(payload.get("code"), "topic_deleted")
            self.assertEqual(self._topic_status(), ("deleted", "moderator"))


class PageRendersTests(_HttpBase):
    """HTTP-level page checks: the data a page is given and the files it links.

    These do not execute JavaScript, so they cannot tell whether a page
    actually renders; tests/test_browser_render.py does that in Chromium.
    These catch a missing script reference, a missing asset file, or an API
    that stops returning the seeded work.
    """

    WORK_TITLE = "渲染断言用的作品标题"

    def setUp(self):
        self.work = publish_user_work(
            self.db,
            self.author,
            {
                "title": self.WORK_TITLE,
                "prompt": "渲染断言用的提示词",
                "images": [IMG],
                "styles": ["FA-013"],
            },
        )

    def test_home_page_renders_seeded_content(self):
        # The home shell is static, so assert on the data the app is given and
        # the modules that turn it into cards.
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, boot = self._request("GET", "/api/boot")
            page_status, page = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(page_status, 200)
        self.assertTrue(
            any(w["title"] == self.WORK_TITLE for w in boot["works"]),
            "the boot payload carries the seeded work",
        )
        for module in ("discovery.js", "shared.js", "main-app.js", "works-browser.js"):
            self.assertIn(f"/assets/{module}", page, f"home page must load {module}")

    def test_topic_page_names_the_work(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, detail = self._request("GET", f"/api/forum/resources/work/{self.work['workId']}")
            page_status, page = self._request("GET", f"/forum/?view=topic&id={self.work['topicId']}")
        self.assertEqual(status, 200, detail)
        self.assertEqual(page_status, 200)
        self.assertEqual(detail["resource"]["title"], self.WORK_TITLE)
        self.assertEqual(detail["resource"]["prompt"], "渲染断言用的提示词")
        self.assertIn("/assets/forum-app.js", page)

    def test_resource_api_serves_a_work(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, payload = self._request("GET", f"/api/forum/resources/work/{self.work['workId']}")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["resource"]["id"], self.work["workId"])
        self.assertEqual(payload["resource"]["prompt"], "渲染断言用的提示词")

    def test_unknown_api_path_is_json_404(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, payload = self._request("GET", "/api/not-a-real-endpoint")
        self.assertEqual(status, 404)
        self.assertEqual(payload.get("code"), "not_found")

    def test_every_linked_asset_exists_and_is_served(self):
        # A page that links a missing script renders a blank view.  Check both
        # the file on disk and the server response.
        import re

        root = Path("demo")
        for page_name in ("index.html", "studio.html", "forum.html", "admin.html"):
            html = (root / page_name).read_text(encoding="utf-8")
            refs = set(re.findall(r'["\'](/assets/[^"\'\?]+)', html))
            self.assertTrue(refs, f"{page_name} should link assets")
            for ref in refs:
                self.assertTrue((root / ref.lstrip("/")).is_file(), f"{page_name}: missing {ref}")
                with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
                    status, _ = self._request("GET", ref)
                self.assertEqual(status, 200, f"{page_name}: {ref} not served")


if __name__ == "__main__":
    unittest.main()
