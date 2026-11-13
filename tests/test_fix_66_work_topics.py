"""Verification tests for Issue #66.

1. Hidden or deleted work topics do not leak topic IDs in anonymous /api/boot payload serialization.
2. Unlisted published work topics remain accessible in boot discussions mapping for detail page view.
3. Active work publish (/api/works / publish_work_direct) sets listed_at_ms and lists in forum topics;
   idempotent replay does not refresh listed_at_ms.
4. Automatic projection from cloud generation creates an unlisted work topic (listed_at_ms IS NULL).
"""
from __future__ import annotations

import json
import time
import unittest
import os
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.postgres_support import open_isolated_postgres
from backend import server, services
from backend.curation import publish_work_direct
from backend.resource_discussions import ensure_topic

from tests.economy_support import prepare_cloud_generation


class Fix66WorkTopicsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.temp = TemporaryDirectory()
        self.db = open_isolated_postgres(self, seed=True)
        self.author, _ = services.register_user(self.db, "test_author", "Pass1234!")
        self.admin, _ = services.register_user(self.db, "test_admin", "Pass1234!")
        conn = self.db.get_conn()
        conn.execute("UPDATE users SET role = 'admin' WHERE username = 'test_admin'")
        conn.commit()
        self.admin = dict(conn.execute("SELECT * FROM users WHERE username = 'test_admin'").fetchone())

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_hidden_or_deleted_work_topic_absent_from_anonymous_boot_serialization(self):
        """Hidden or deleted work topics must never expose topic ID in serialized anonymous boot."""
        # 1. Publish a work actively
        pub = services.publish_user_work(
            self.db,
            self.author,
            {
                "title": "公开作品",
                "prompt": "a nice prompt",
                "images": ["/images/individual/FA/FA-013.webp"],
                "styles": ["FA-013"],
            },
        )
        wid = pub["workId"]
        tid = pub["topicId"]

        # Initially visible
        boot_initial = services.build_boot_payload(self.db, None)
        self.assertIn(tid, json.dumps(boot_initial, ensure_ascii=False))

        # Hide the topic via moderator action
        services.forum_moderator_action(self.db, self.admin, {"topicId": tid, "action": "hide"})
        boot_hidden = services.build_boot_payload(self.db, None)
        self.assertNotIn(tid, json.dumps(boot_hidden, ensure_ascii=False))
        self.assertNotIn(wid, boot_hidden.get("discussions", {}))

        # Delete the topic
        services.forum_moderator_action(self.db, self.admin, {"topicId": tid, "action": "delete"})
        boot_deleted = services.build_boot_payload(self.db, None)
        self.assertNotIn(tid, json.dumps(boot_deleted, ensure_ascii=False))
        self.assertNotIn(wid, boot_deleted.get("discussions", {}))

    def test_unlisted_published_work_topic_present_in_boot_discussions(self):
        """Unlisted published works must not appear in forum list, but must appear in boot discussions."""
        conn = self.db.get_conn()
        wid = "work_unlisted_demo"
        now = services.utc_now_iso()
        conn.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, prompt, styles_json,
                layout_code, images_json, status, published_at_ms, created_at, updated_at
            ) VALUES (?, 'test_author', '作者', '未入列作品', 'prompt', '["FA-013"]',
                     '', '["/images/individual/FA/FA-013.webp"]', 'published', 1000, ?, ?)
            """,
            (wid, now, now),
        )
        with self.db.transaction():
            tid = ensure_topic(
                conn,
                "work",
                wid,
                {"title": "未入列作品", "images_json": '["/images/individual/FA/FA-013.webp"]'},
                initial_origin="submission",
                listed_at_ms=None,
            )
        conn.commit()

        # Check DB state
        t_row = conn.execute("SELECT status, listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertEqual(t_row["status"], "published")
        self.assertIsNone(t_row["listed_at_ms"])

        boot = services.build_boot_payload(self.db, None)
        boot_tids = {t["id"] for t in boot.get("topics", [])}
        # Must NOT be in forum topic list
        self.assertNotIn(tid, boot_tids)
        # MUST be in discussions mapping so the work detail can navigate to discussion
        self.assertIn(wid, boot.get("discussions", {}))
        self.assertEqual(boot["discussions"][wid]["topicId"], tid)

    def test_publish_work_direct_sets_listed_at_ms_and_idempotent_replay(self):
        """Active work publishes stay unlisted until first reply; replay preserves listing time."""
        req_id = "req_publish_test_123"
        receipt = services.publish_user_work(
            self.db,
            self.author,
            {
                "requestId": req_id,
                "title": "主动晒图作品",
                "prompt": "direct publish prompt",
                "images": ["/images/individual/FA/FA-013.webp"],
                "styles": ["FA-013"],
            },
        )
        tid = receipt["topicId"]
        conn = self.db.get_conn()
        row = conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNone(row["listed_at_ms"], "Work discussions start unlisted")
        pre_boot = services.build_boot_payload(self.db, None)
        self.assertNotIn(tid, {t["id"] for t in pre_boot.get("topics", [])})

        # A real first reply lists the discussion exactly once.
        services.publish_forum_reply_post(self.db, self.author, tid, "第一条公开回复")
        row = conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNotNone(row["listed_at_ms"])
        first_listed = int(row["listed_at_ms"])
        self.assertGreater(first_listed, 0)
        boot = services.build_boot_payload(self.db, None)
        self.assertIn(tid, {t["id"] for t in boot.get("topics", [])})

        # Replay with same requestId
        time.sleep(0.01)
        receipt_replay = services.publish_user_work(
            self.db,
            self.author,
            {
                "requestId": req_id,
                "title": "主动晒图作品",
                "prompt": "direct publish prompt",
                "images": ["/images/individual/FA/FA-013.webp"],
                "styles": ["FA-013"],
            },
        )
        self.assertTrue(receipt_replay.get("deduplicated"))
        row_replay = conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertEqual(int(row_replay["listed_at_ms"]), first_listed, "Replay must not refresh listed_at_ms")

    def test_auto_projected_generation_work_is_not_listed(self):
        """Works auto-projected from generation completions must remain unlisted."""
        prepared = prepare_cloud_generation(
            self.db,
            self.author,
            {"requestId": "gen-auto-test", "prompt": "auto projection"},
        )
        img_url = "/generated/auto_proj_test.webp"
        services.complete_cloud_generation(self.db, prepared["genId"], "task-proj-1", [img_url])

        conn = self.db.get_conn()
        row = conn.execute(
            """SELECT w.id FROM works w JOIN generation_runs r ON r.id=w.run_id
               WHERE r.source='web' AND r.external_run_id=?""",
            (prepared["genId"],),
        ).fetchone()
        self.assertIsNotNone(row, "Generation must have a canonical work")
        projected_wid = row["id"]

        t_row = conn.execute("SELECT id, listed_at_ms FROM forum_topics WHERE work_id = ?", (projected_wid,)).fetchone()
        self.assertIsNotNone(t_row, "Prebuilt topic must exist for projected work")
        self.assertIsNone(t_row["listed_at_ms"], "Projected work topic must have listed_at_ms IS NULL")

        boot = services.build_boot_payload(self.db, None)
        boot_tids = {t["id"] for t in boot.get("topics", [])}
        self.assertNotIn(t_row["id"], boot_tids, "Projected work must not appear in forum list")
        self.assertIn(projected_wid, boot.get("discussions", {}), "Projected work must appear in discussions mapping")

    def test_publish_work_direct_body_listed_cannot_override_server_listed_false(self):
        """Client body with 'listed': True must not force listed_at_ms when server listed=False."""
        res = publish_work_direct(
            self.db,
            self.author,
            {
                "title": "客户端试图强制入列作品",
                "prompt": "prompt with client listed attempt",
                "images": ["/images/individual/FA/FA-013.webp"],
                "styles": ["FA-013"],
                "listed": True,
            },
            listed=False,
        )
        tid = res["topicId"]
        conn = self.db.get_conn()
        row = conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row["listed_at_ms"], "Topic listed_at_ms must remain None when server listed=False")


if __name__ == "__main__":
    unittest.main()
