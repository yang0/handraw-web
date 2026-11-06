"""One work, one set of counters.

A work's discussion topic is a view of the work.  Liking or favouriting that
topic must record against the work, and the serialized topic must report the
work's numbers, so the square and the forum never disagree.
"""
from __future__ import annotations

import unittest
import os
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server
from backend.services import (
    build_boot_payload,
    publish_user_work,
    publish_forum_reply_post,
    register_user,
    toggle_user_collection,
    toggle_user_like,
)

IMG = "/images/individual/FA/FA-013.webp"


class WorkCounterTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "counts.db")
        self.author, _ = register_user(self.db, "cnt_author", "password-a")
        self.reader, _ = register_user(self.db, "cnt_reader", "password-b")
        self.published = publish_user_work(
            self.db,
            self.author,
            {"title": "计数作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]},
        )
        self.work_id = self.published["workId"]
        self.topic_id = self.published["topicId"]

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _work(self, column):
        return int(
            self.db.get_conn().execute(f"SELECT {column} FROM works WHERE id = ?", (self.work_id,)).fetchone()[column]
        )

    def _topic(self, column):
        return int(
            self.db.get_conn()
            .execute(f"SELECT {column} FROM forum_topics WHERE id = ?", (self.topic_id,)).fetchone()[column]
        )

    def test_liking_the_topic_records_on_the_work(self):
        toggle_user_like(self.db, self.reader, "topic", self.topic_id)
        self.assertEqual(self._work("likes"), 1)
        self.assertEqual(self._topic("likes"), 0, "the topic's own column must not be used for a work")
        record = self.db.get_conn().execute(
            "SELECT target_type, target_id FROM interactions WHERE user_id = ?", (self.reader["id"],)
        ).fetchone()
        self.assertEqual(record["target_type"], "like_work")
        self.assertEqual(record["target_id"], self.work_id)

    def test_favouriting_the_topic_records_on_the_work(self):
        toggle_user_collection(self.db, self.reader, "topics", self.topic_id)
        self.assertEqual(self._work("favorites"), 1)
        bucket = self.db.get_conn().execute(
            "SELECT bucket FROM collections WHERE user_id = ? AND target_id = ?", (self.reader["id"], self.work_id)
        ).fetchone()
        self.assertIsNotNone(bucket, "collection must be filed under the work")
        self.assertEqual(bucket["bucket"], "works")

    def test_boot_reports_the_same_numbers_in_both_views(self):
        toggle_user_like(self.db, self.reader, "topic", self.topic_id)
        toggle_user_collection(self.db, self.reader, "topics", self.topic_id)
        # Work discussions are listed after the first public reply, not upon
        # publication. Make the topic visible before comparing boot views.
        publish_forum_reply_post(self.db, self.author, self.topic_id, "第一条公开讨论")

        boot = build_boot_payload(self.db, None)
        work = next(w for w in boot["works"] if w["id"] == self.work_id)
        topic = next(t for t in boot["topics"] if t["id"] == self.topic_id)

        self.assertEqual(topic["likes"], work["likes"])
        self.assertEqual(topic["favorites"], work["favorites"])
        self.assertEqual(topic["likes"], 1)
        self.assertEqual(topic["favorites"], 1)
        self.assertEqual(topic.get("workId"), self.work_id)

    def test_unliking_the_topic_decrements_the_work(self):
        toggle_user_like(self.db, self.reader, "topic", self.topic_id)
        toggle_user_like(self.db, self.reader, "topic", self.topic_id)
        self.assertEqual(self._work("likes"), 0)

    def test_plain_topics_keep_their_own_counters(self):
        from backend.services import publish_forum_topic_post

        topic = publish_forum_topic_post(
            self.db,
            self.author,
            {"category": "tools", "title": "普通帖子", "summary": "只是讨论"},
        )
        new_id = topic["topicId"]
        toggle_user_like(self.db, self.reader, "topic", new_id)
        likes = int(
            self.db.get_conn().execute("SELECT likes FROM forum_topics WHERE id = ?", (new_id,)).fetchone()["likes"]
        )
        self.assertEqual(likes, 1, "a topic without a work still counts its own likes")


if __name__ == "__main__":
    unittest.main()
