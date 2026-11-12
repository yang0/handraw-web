"""Regression contract: work discussions appear in forum only after first comment."""
from __future__ import annotations

import unittest

from backend import resource_discussions, services
from backend.seed import ensure_seeded
from tests.postgres_support import open_isolated_postgres

IMG = "/images/individual/FA/FA-013.webp"


class CommentLedForumTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self)
        ensure_seeded(self.db)
        self.author, _ = services.register_user(self.db, "comment_author", "password-author")
        self.reader, _ = services.register_user(self.db, "comment_reader", "password-reader")

    def _work(self, request_id):
        return services.publish_user_work(
            self.db,
            self.author,
            {
                "title": "手绘测试作品",
                "prompt": "watercolor illustration of a cozy cafe",
                "images": [IMG],
                "requestId": request_id,
            },
            listed=True,  # Explicit legacy flag cannot bypass first-comment rule.
        )

    def test_first_comment_lists_once_in_same_transaction(self):
        published = self._work("req_first")
        wid, tid = published["workId"], published["topicId"]
        conn = self.db.get_conn()
        row = conn.execute(
            "SELECT listed_at_ms, status FROM forum_topics WHERE id=?", (tid,)
        ).fetchone()
        self.assertEqual(row["status"], "published")
        self.assertIsNone(row["listed_at_ms"])

        first = resource_discussions.comment(
            self.db, self.reader, "work", wid, "构图很好，喜欢这个画风"
        )
        self.assertEqual(first["topicId"], tid)
        first_stamp = conn.execute(
            "SELECT listed_at_ms FROM forum_topics WHERE id=?", (tid,)
        ).fetchone()["listed_at_ms"]
        self.assertIsNotNone(first_stamp)

        second = resource_discussions.comment(
            self.db, self.author, "work", wid, "谢谢关注，欢迎复刻这套配方"
        )
        self.assertEqual(second["topicId"], tid)
        self.assertEqual(
            conn.execute(
                "SELECT listed_at_ms FROM forum_topics WHERE id=?", (tid,)
            ).fetchone()["listed_at_ms"],
            first_stamp,
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM forum_topics WHERE work_id=?", (wid,)
            ).fetchone()[0],
            1,
        )

    def test_uncommented_work_not_listed_by_standalone_forum_post(self):
        published = self._work("req_standalone")
        wid, canonical_tid = published["workId"], published["topicId"]
        post = services.publish_forum_topic_post(
            self.db,
            self.author,
            {
                "category": "experience",
                "title": "我的水彩创作经验分享",
                "body": "分享我的创作过程和画风组合。",
                "workId": wid,
                "sharedCard": {"kind": "work", "id": wid},
            },
        )
        self.assertNotEqual(post["topicId"], canonical_tid)
        conn = self.db.get_conn()
        self.assertIsNone(conn.execute(
            "SELECT listed_at_ms FROM forum_topics WHERE id=?", (canonical_tid,)
        ).fetchone()["listed_at_ms"])
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM forum_topics WHERE work_id=?", (wid,)
        ).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
