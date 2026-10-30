"""Round-6 review fixes.

Covers the remaining blocking items from the fifth review: an unmatched API path
must 404 instead of serving the SPA shell, a topic paused by reports must record
its cause so a dismissal can restore it, author edits keep the prompt verbatim,
and the report sweep is documented as always settling the target.
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
from backend.admin_services import admin_moderate_topic, admin_resolve_report
from backend.server import create_channel_server
from backend.services import publish_user_work, register_user, submit_abuse_report

IMG = "/images/individual/FA/FA-013.webp"


class UnknownApiPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.db = server_module.init_database(Path(cls.temp.name) / "api404.db")
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
        cls.temp.cleanup()

    def _get(self, path):
        request = urllib.request.Request(self.base + path, headers={"Origin": "http://trusted.test"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.headers.get("Content-Type", ""), response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("Content-Type", ""), error.read()

    def test_missing_api_path_is_404_json_not_the_spa(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, content_type, body = self._get("/api/definitely-not-a-route")
        self.assertEqual(status, 404)
        self.assertIn("application/json", content_type)
        payload = json.loads(body)
        self.assertEqual(payload.get("code"), "not_found")

    def test_bare_and_uppercase_api_paths_are_404_json(self):
        for path in ("/api", "/API/boot", "/Api/not-a-route"):
            with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
                status, content_type, body = self._get(path)
            self.assertEqual(status, 404, path)
            self.assertIn("application/json", content_type, path)
            self.assertNotIn(b"<html", body.lower(), path)

    def test_missing_resource_route_also_404s(self):
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            status, _, body = self._get("/api/entries/00000000-0000-0000-0000-000000000000")
        self.assertEqual(status, 404)
        self.assertNotIn(b"<html", body.lower())


class TopicPauseProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server_module.init_database(Path(self.temp.name) / "tp.db")
        self.author, _ = register_user(self.db, "tp_author", "password-a")
        register_user(self.db, "tp_admin", "password-admin")
        self.db.get_conn().execute("UPDATE users SET role = 'admin' WHERE username = 'tp_admin'")
        self.db.get_conn().commit()
        self.admin = dict(
            self.db.get_conn().execute("SELECT * FROM users WHERE username = 'tp_admin'").fetchone()
        )
        self.work = publish_user_work(
            self.db, self.author, {"title": "主帖来源", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _topic(self):
        row = self.db.get_conn().execute(
            "SELECT status, status_source FROM forum_topics WHERE id = ?", (self.work["topicId"],)
        ).fetchone()
        self.db.close_thread_conn()
        return (row["status"], row["status_source"]) if row else (None, None)

    def _report(self, times=1, target_type="topic"):
        # One open report per account counts, so the threshold needs distinct
        # reporters.
        target = self.work["topicId"] if target_type == "topic" else self.work["workId"]
        for i in range(times):
            reporter, _ = register_user(self.db, f"tp_rep{target_type}{i}", "password-r")
            submit_abuse_report(
                self.db, reporter, {"targetType": target_type, "targetId": target, "reason": "垃圾内容"}
            )

    def test_auto_paused_topic_records_the_report_source(self):
        self._report(times=3, target_type="topic")
        self.assertEqual(self._topic()[1], "report", "an automatic pause must record its cause")

    def test_dismissing_reports_restores_an_auto_paused_topic(self):
        self._report(times=3, target_type="topic")
        reports = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'topic' AND status = 'open'"
        ).fetchall()
        self.db.close_thread_conn()
        for report in reports:
            admin_resolve_report(self.db, self.admin, report["id"], "dismissed", auto_action=False)
        self.assertEqual(self._topic(), ("published", ""), "a dismissed report restores its own pause")

    def test_moderator_hidden_topic_stays_hidden_after_dismissal(self):
        admin_moderate_topic(self.db, self.admin, self.work["topicId"], "hide")
        self._report()
        reports = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'topic' AND status = 'open'"
        ).fetchall()
        self.db.close_thread_conn()
        for report in reports:
            admin_resolve_report(self.db, self.admin, report["id"], "dismissed", auto_action=False)
        self.assertEqual(self._topic(), ("hidden", "moderator"))


class AuthorEditKeepsPromptTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server_module.init_database(Path(self.temp.name) / "ae.db")
        self.author, _ = register_user(self.db, "ae_author", "password-a")

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_author_edit_preserves_leading_and_trailing_space(self):
        from backend.features import edit_owned_content

        padded = "  前后都有空格  "
        work = publish_user_work(
            self.db, self.author, {"title": "原样标题", "prompt": padded, "images": [IMG], "styles": ["FA-013"]}
        )
        edit_owned_content(self.db, self.author, "works", work["workId"], {"title": "改过的标题"})
        stored = self.db.get_conn().execute(
            "SELECT prompt FROM works WHERE id = ?", (work["workId"],)
        ).fetchone()["prompt"]
        self.assertEqual(stored, padded, "an author edit must not trim the prompt")


if __name__ == "__main__":
    unittest.main()
