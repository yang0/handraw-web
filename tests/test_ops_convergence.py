"""Operational script for legacy comment convergence."""
from __future__ import annotations

import sqlite3
import os
from unittest.mock import patch
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server
from backend.services import (
    publish_user_work,
    register_user,
)

sys_path_ok = True
try:
    from ops import converge_work_comments
except ImportError:  # pragma: no cover - repo layout fallback
    sys_path_ok = False

IMG = "/images/individual/FA/FA-013.webp"


@unittest.skipUnless(sys_path_ok, "ops package not importable")
class ConvergeCommentsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "converge.db"
        self.db = server.init_database(self.path)
        self.author, _ = register_user(self.db, "conv_author", "password-a")
        published = publish_user_work(
            self.db, self.author, {"title": "旧评论作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )
        self.work_id = published["workId"]
        self.topic_id = published["topicId"]

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _seed_legacy_comment(self):
        conn = self.db.get_conn()
        conn.execute(
            """INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at)
               VALUES ('wc_1', ?, 'conv_author', '作者', '老评论正文', 'published', '刚刚', '2026-01-01T00:00:00Z')""",
            (self.work_id,),
        )
        # Mark the work as legacy so the script considers it.
        conn.execute(
            "UPDATE curation_resource_topics SET origin = 'legacy' WHERE kind = 'work' AND target_id = ?",
            (self.work_id,),
        )
        conn.commit()

    def test_plan_finds_legacy_comments(self):
        self._seed_legacy_comment()
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            todo = converge_work_comments.plan(conn)
        finally:
            conn.close()
        self.assertEqual(len(todo), 1)
        self.assertEqual(todo[0]["legacySource"], "work_comments:wc_1")

    def test_apply_copies_once_and_flips_mapping(self):
        self._seed_legacy_comment()
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            todo = converge_work_comments.plan(conn)
            copied, failures = converge_work_comments.apply(conn, todo)
            self.assertEqual(copied, 1)
            self.assertEqual(failures, [])
            reply = conn.execute(
                "SELECT * FROM forum_replies WHERE legacy_source = 'work_comments:wc_1'"
            ).fetchone()
            self.assertIsNotNone(reply)
            self.assertEqual(reply["text"], "老评论正文")
            self.assertEqual(reply["status"], "published")
            self.assertEqual(reply["topic_id"], self.topic_id)
            origin = conn.execute(
                "SELECT origin FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?",
                (self.work_id,),
            ).fetchone()["origin"]
            self.assertEqual(origin, "submission")
            # A second run must not duplicate.
            self.assertEqual(converge_work_comments.plan(conn), [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
