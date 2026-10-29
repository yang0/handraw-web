"""Operational scripts: legacy comment convergence and counter reconciliation."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server
from backend.services import (
    publish_user_work,
    register_user,
    toggle_user_collection,
    toggle_user_like,
)

sys_path_ok = True
try:
    from ops import converge_work_comments, reconcile_social_counters
except ImportError:  # pragma: no cover - repo layout fallback
    sys_path_ok = False

IMG = "/images/individual/FA/FA-013.webp"


@unittest.skipUnless(sys_path_ok, "ops package not importable")
class CounterReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "reconcile.db"
        self.db = server.init_database(self.path)
        self.author, _ = register_user(self.db, "rec_author", "password-a")
        self.reader, _ = register_user(self.db, "rec_reader", "password-b")
        published = publish_user_work(
            self.db, self.author, {"title": "对账作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )
        self.work_id = published["workId"]

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_clean_database_reports_no_drift(self):
        toggle_user_like(self.db, self.reader, "work", self.work_id)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            drift = reconcile_social_counters.compute(conn)
        finally:
            conn.close()
        self.assertEqual(drift["works"], [])
        self.assertEqual(drift["topics"], [])

    def test_drift_is_detected_and_repaired(self):
        toggle_user_like(self.db, self.reader, "work", self.work_id)
        toggle_user_collection(self.db, self.reader, "works", self.work_id)
        # Inject the historical bug: a stale cache that over-reports.
        self.db.get_conn().execute(
            "UPDATE works SET likes = 99, favorites = 42, cheers = 7 WHERE id = ?", (self.work_id,)
        )
        self.db.get_conn().commit()

        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            drift = reconcile_social_counters.compute(conn)
            self.assertEqual(len(drift["works"]), 1)
            self.assertEqual(drift["works"][0]["true_likes"], 1)
            reconcile_social_counters.apply(conn, drift)
            after = conn.execute("SELECT likes, favorites, cheers FROM works WHERE id = ?", (self.work_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(int(after["likes"]), 1)
        self.assertEqual(int(after["favorites"]), 1)
        self.assertEqual(int(after["cheers"]), 0)


@unittest.skipUnless(sys_path_ok, "ops package not importable")
class ConvergeCommentsTests(unittest.TestCase):
    def setUp(self):
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
            copied = converge_work_comments.apply(conn, todo)
            self.assertEqual(copied, 1)
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
