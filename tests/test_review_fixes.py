"""Holes the final review found that the earlier suite missed.

Each test pins one specific way the implementation could accept or leak
something it should not.
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server
from backend.ranking import work_popular_sql
from backend.services import build_boot_payload, publish_user_work, register_user

IMG = "/images/individual/FA/FA-013.webp"


class PaidPromptTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "paid.db")
        self.author, _ = register_user(self.db, "pay_author", "password-a")
        self.reader, _ = register_user(self.db, "pay_reader", "password-b")
        self.work = publish_user_work(
            self.db,
            self.author,
            {
                "title": "付费作品",
                "prompt": "SECRET-PROMPT-CONTENT-abcdefghijklmnop",
                "images": [IMG],
                "styles": ["FA-013"],
                "price": 10,
            },
        )

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_locked_prompt_is_empty_not_a_teaser(self):
        boot = build_boot_payload(self.db, self.reader)
        work = next(w for w in boot["works"] if w["id"] == self.work["workId"])
        self.assertEqual(work["prompt"], "", "a locked work must not leak any prompt text")

    def test_author_still_reads_own_prompt(self):
        boot = build_boot_payload(self.db, self.author)
        work = next(w for w in boot["works"] if w["id"] == self.work["workId"])
        self.assertIn("SECRET-PROMPT", work["prompt"])

    def test_anonymous_sees_no_prompt(self):
        boot = build_boot_payload(self.db, None)
        work = next(w for w in boot["works"] if w["id"] == self.work["workId"])
        self.assertEqual(work["prompt"], "")


class PopularIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "idx.db")

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_expression_index_exists(self):
        # Migration 048 rebuilt the index for the fork-weight change, so the
        # live name is v2; the old one is dropped.
        names = [
            row[0]
            for row in self.db.get_conn().execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_works_popular%'"
            )
        ]
        self.assertIn("idx_works_popular_v2", names, "the popularity expression index must exist")
        self.assertNotIn("idx_works_popular", names, "the superseded index must be gone")

    def test_query_planner_uses_the_index(self):
        # The ORDER BY must match the index expression textually for SQLite to
        # use it, so this guards against someone editing one and not the other.
        expr = work_popular_sql("")
        plan = self.db.get_conn().execute(
            f"EXPLAIN QUERY PLAN SELECT id FROM works WHERE status='published' "
            f"ORDER BY {expr} DESC, published_at_ms DESC LIMIT 10"
        ).fetchall()
        details = " ".join(str(row["detail"]) for row in plan)
        self.assertIn("idx_works_popular", details, details)


class ConvergeAllStatusesTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "conv.db"
        self.db = server.init_database(self.path)
        self.author, _ = register_user(self.db, "conv_all", "password-a")
        published = publish_user_work(
            self.db, self.author, {"title": "收敛作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )
        self.work_id = published["workId"]
        conn = self.db.get_conn()
        for cid, status, text in (
            ("wc_pub", "published", "公开评论"),
            ("wc_hid", "hidden", "被隐藏的评论"),
        ):
            conn.execute(
                """INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at)
                   VALUES (?, ?, 'conv_all', '作者', ?, ?, '刚刚', '2026-01-01T00:00:00Z')""",
                (cid, self.work_id, text, status),
            )
        conn.execute(
            "UPDATE curation_resource_topics SET origin='legacy' WHERE kind='work' AND target_id=?",
            (self.work_id,),
        )
        conn.commit()
        self.db.close_thread_conn()

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_hidden_comments_are_copied_with_their_status(self):
        from ops import converge_work_comments

        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            todo = converge_work_comments.plan(conn)
            self.assertEqual(len(todo), 2, "hidden comments must not be dropped by the migration")
            converge_work_comments.apply(conn, todo)
            rows = {
                row["legacy_source"]: row["status"]
                for row in conn.execute("SELECT legacy_source, status FROM forum_replies").fetchall()
            }
        finally:
            conn.close()
        self.assertEqual(rows.get("work_comments:wc_hid"), "hidden")
        self.assertEqual(rows.get("work_comments:wc_pub"), "published")


class StarterCredentialTests(unittest.TestCase):
    def test_no_shared_password_constant(self):
        from ops import seed_starter_library

        self.assertFalse(
            hasattr(seed_starter_library, "STARTER_PASSWORD"),
            "starter accounts must not share a hard-coded password",
        )

    def test_passwords_are_random_per_run(self):
        from ops import seed_starter_library

        first = seed_starter_library._random_password()
        second = seed_starter_library._random_password()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 24)


if __name__ == "__main__":
    unittest.main()
