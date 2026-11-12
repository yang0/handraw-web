"""Tests for Stage 2: Unified topic creation, author self-comment, atomic listing & concurrency."""
from __future__ import annotations

import concurrent.futures
import json
import tempfile
import time
import unittest
from pathlib import Path

from tests.postgres_support import open_isolated_postgres
from backend.curation import publish_work_direct
from backend.generation_works import project_generation_to_works
from backend.resource_discussions import comment
from backend.services import publish_forum_reply_post, register_user, ServiceError


class Stage2TopicWritesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_stage2.db"
        self.db = open_isolated_postgres(self, seed=True)
        self.author, _ = register_user(self.db, "test_author", "pass-author-123")
        self.commenter, _ = register_user(self.db, "test_commenter", "pass-comment-123")

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp_dir.cleanup()

    def test_direct_work_upload_prebuilds_topic_and_replay_is_idempotent(self) -> None:
        """Uploading a work directly creates a pre-built topic with listed_at_ms=NULL."""
        body = {
            "title": "直接上传测试",
            "prompt": "prompt for direct work",
            "images": ["/images/test1.png"],
            "requestId": "req_upload_001",
        }
        res = publish_work_direct(self.db, self.author, body)
        self.assertTrue(res["ok"])
        work_id = res["workId"]
        topic_id = res["topicId"]
        self.assertTrue(topic_id)

        conn = self.db.get_conn()
        topic = conn.execute("SELECT * FROM forum_topics WHERE id = ?", (topic_id,)).fetchone()
        self.assertIsNotNone(topic)
        self.assertEqual(topic["work_id"], work_id)
        self.assertIsNone(topic["listed_at_ms"])

        # Replay with same requestId
        replay_res = publish_work_direct(self.db, self.author, body)
        self.assertEqual(replay_res["workId"], work_id)
        self.assertEqual(replay_res["topicId"], topic_id)
        self.assertTrue(replay_res["deduplicated"])

        # Topic count for this work is strictly 1
        topic_cnt = conn.execute("SELECT COUNT(*) FROM forum_topics WHERE work_id = ?", (work_id,)).fetchone()[0]
        self.assertEqual(topic_cnt, 1)

    def test_generation_projection_prebuilds_topic_per_image_and_replay_is_idempotent(self) -> None:
        """Two public images form ONE work and ONE prebuilt discussion topic."""
        conn = self.db.get_conn()
        gen_id = "gen_test_batch_2"
        now_iso = "2026-11-01T10:00:00Z"
        items = [
            {"id": "it_1", "imageUrl": "/gen/img1.png", "title": "图1"},
            {"id": "it_2", "imageUrl": "/gen/img2.png", "title": "图2"},
        ]
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, engine, prompt, items_json, status, visibility, created_at
                ) VALUES (?, ?, ?, 'sdxl', 'a beautiful scenery', ?, 'success', 'public', ?)
                """,
                (gen_id, self.author["id"], self.author["username"], json.dumps(items), now_iso),
            )

        with self.db.transaction() as tx:
            wids = project_generation_to_works(tx, gen_id)

        self.assertEqual(len(wids), 1)
        for wid in wids:
            t = conn.execute("SELECT * FROM forum_topics WHERE work_id = ?", (wid,)).fetchone()
            self.assertIsNotNone(t, f"Work {wid} must have a pre-built topic")
            self.assertIsNone(t["listed_at_ms"], "Prebuilt topic must have listed_at_ms = NULL")

        # Replay projection
        with self.db.transaction() as tx:
            wids_replay = project_generation_to_works(tx, gen_id)
        self.assertEqual(wids_replay, wids)

        # Still strictly 1 topic per work
        for wid in wids:
            cnt = conn.execute("SELECT COUNT(*) FROM forum_topics WHERE work_id = ?", (wid,)).fetchone()[0]
            self.assertEqual(cnt, 1)

    def test_author_self_comment_allowed_and_lists_topic(self) -> None:
        """Author commenting on own work succeeds (no 400) and triggers listed_at_ms."""
        res = publish_work_direct(self.db, self.author, {
            "title": "自评测试作品",
            "prompt": "prompt self comment",
            "images": ["/images/self.png"],
        })
        wid = res["workId"]
        tid = res["topicId"]

        conn = self.db.get_conn()
        t_before = conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNone(t_before["listed_at_ms"])

        # Author comments on own work
        c_res = comment(self.db, self.author, "work", wid, "作者自己的第一条评论！")
        self.assertTrue(c_res["ok"])
        self.assertEqual(c_res["topicId"], tid)

        # Topic listed_at_ms is now set
        t_after = conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNotNone(t_after["listed_at_ms"])
        first_listed_ms = t_after["listed_at_ms"]
        self.assertGreater(first_listed_ms, 0)

        # Second comment by another user must NOT overwrite listed_at_ms
        time.sleep(0.01)
        c_res2 = comment(self.db, self.commenter, "work", wid, "别人的第二条评论")
        self.assertTrue(c_res2["ok"])

        t_after2 = conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertEqual(t_after2["listed_at_ms"], first_listed_ms, "listed_at_ms must not be refreshed on subsequent comments")

    def test_publish_forum_reply_post_lists_topic_atomically(self) -> None:
        """Replying via publish_forum_reply_post also sets listed_at_ms atomically."""
        res = publish_work_direct(self.db, self.author, {
            "title": "回帖入列测试",
            "prompt": "prompt reply list",
            "images": ["/images/reply_list.png"],
        })
        tid = res["topicId"]

        # Directly reply via topic_id
        rep_res = publish_forum_reply_post(self.db, self.commenter, tid, "通过论坛回复接口发表评论")
        self.assertTrue(rep_res["ok"])

        conn = self.db.get_conn()
        t = conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNotNone(t["listed_at_ms"])

    def test_atomic_rollback_on_failed_reply(self) -> None:
        """If a comment fails inside transaction, neither reply nor listed_at_ms is committed."""
        res = publish_work_direct(self.db, self.author, {
            "title": "回滚测试",
            "prompt": "prompt rollback",
            "images": ["/images/rollback.png"],
        })
        wid = res["workId"]
        tid = res["topicId"]

        # Empty text raises ServiceError
        with self.assertRaises(ServiceError):
            comment(self.db, self.commenter, "work", wid, "   ")

        conn = self.db.get_conn()
        t = conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNone(t["listed_at_ms"])
        replies = conn.execute("SELECT COUNT(*) FROM forum_replies WHERE topic_id = ?", (tid,)).fetchone()[0]
        self.assertEqual(replies, 0)

    def test_concurrent_first_comment_creates_exactly_one_topic(self) -> None:
        """When multiple threads comment on a work with NO pre-existing topic, exactly 1 topic is created."""
        conn = self.db.get_conn()
        wid = "work_concurrent_raw"
        now_iso = "2026-11-01T11:00:00Z"
        # Seed raw work without topic
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (
                    id, author_username, author_name, title, images_json, styles_json,
                    layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes,
                    prompt_has_secret, status, published_at_ms, created_label, created_at, updated_at
                ) VALUES (
                    ?, 'alice', 'Alice', '并发原作品', '["/img.png"]', '[]', '', 'C-15', 'T-01', '3:4',
                    'graphic-text', '治愈', 0, 'p', '', 0, 'published', 1000, '刚刚', ?, ?
                )
                """,
                (wid, now_iso, now_iso),
            )

        def _do_comment(idx: int) -> dict:
            user = self.author if idx % 2 == 0 else self.commenter
            return comment(self.db, user, "work", wid, f"并发评论 {idx}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_do_comment, i) for i in range(4)]
            results = [f.result() for f in futures]

        topic_ids = {r["topicId"] for r in results}
        self.assertEqual(len(topic_ids), 1, f"Expected 1 unique topicId across concurrent comments, got: {topic_ids}")

        tid = list(topic_ids)[0]
        t_row = conn.execute("SELECT * FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNotNone(t_row)
        self.assertEqual(t_row["work_id"], wid)
        self.assertIsNotNone(t_row["listed_at_ms"])

        # Check total replies
        replies_cnt = conn.execute("SELECT COUNT(*) FROM forum_replies WHERE topic_id = ?", (tid,)).fetchone()[0]
        self.assertEqual(replies_cnt, 4)


if __name__ == "__main__":
    unittest.main()
