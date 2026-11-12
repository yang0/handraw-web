"""Current V3 work-topic creation, forum listing, and comment promotion."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend.resource_discussions import (
    ensure_topic,
    record_atomic_reply_and_listing,
    topic_visibility_sql,
)
from backend.services import (
    build_boot_payload,
    compute_public_asset_counts_and_creators,
    register_user,
    utc_now_iso,
)
from backend.post_routes import _is_topic_visible, _resolve_ref_to_topic_id


class Stage3BackfillAndFilteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self._env = patch.dict(
            os.environ,
            {
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_DEMO_MODE": "1",
            },
        )
        self._env.start()
        self.db = open_isolated_postgres(self)
        self.db.migrate()
        self.conn = self.db.get_conn()

        # Seed standard users
        self.alice, _ = register_user(self.db, "alice", "pass-alice")
        self.bob, _ = register_user(self.db, "bob", "pass-bob")

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.conn.close()
        self.db.close()
        self._env.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_work(self, wid: str, origin: str, pub_ms: int, status: str = "published") -> dict:
        now_iso = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, prompt, notes, status,
                origin, published_at_ms, images_json, styles_json, created_at, updated_at
            ) VALUES (?, 'alice', 'Alice', ?, 'test prompt', 'Notes', ?, ?, ?, '["/img/test.png"]', '[]', ?, ?)
            """,
            (wid, f"Work {wid}", status, origin, pub_ms, now_iso, now_iso),
        )
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM works WHERE id = ?", (wid,)).fetchone())

    def _ensure_current_work_topics(self, *work_ids: str) -> list[str]:
        """Current writes attach topics explicitly; V3 never backfills old data."""
        result = []
        for wid in work_ids:
            row = self.conn.execute(
                "SELECT * FROM works WHERE id=?", (wid,),
            ).fetchone()
            self.assertIsNotNone(row)
            with self.db.transaction():
                result.append(ensure_topic(
                    self.conn, "work", wid, dict(row),
                    initial_origin="submission", listed_at_ms=None,
                ))
        self.conn.commit()
        return result

    def test_ensure_topics_for_63_current_works_is_idempotent(self) -> None:
        """One current public work has at most one discussion topic."""
        now_ms = int(time.time() * 1000)
        for i in range(1, 64):
            wid = f"work_{i:03d}"
            self._create_work(
                wid, "generation" if i <= 20 else "web",
                now_ms - (100 - i) * 1000,
            )
            ids = self._ensure_current_work_topics(wid)
            self.assertEqual(len(ids), 1)
            if i <= 15:
                record_atomic_reply_and_listing(
                    self.conn, ids[0], self.bob, "当前作品下的真实讨论",
                )
            if i in (16, 17):
                self.conn.execute(
                    "UPDATE forum_topics SET status='hidden' WHERE id=?",
                    (ids[0],),
                )
        self.conn.commit()
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM forum_topics WHERE work_id<>''",
        ).fetchone()[0], 63)
        self.assertEqual(self.conn.execute(
            """SELECT COUNT(*) FROM forum_topics
               WHERE work_id BETWEEN 'work_001' AND 'work_015'
                 AND listed_at_ms IS NOT NULL""",
        ).fetchone()[0], 15)
        self.assertEqual(self.conn.execute(
            """SELECT COUNT(*) FROM forum_topics
               WHERE work_id IN ('work_016','work_017')
                 AND listed_at_ms IS NULL""",
        ).fetchone()[0], 2)
        # Idempotent API: no second topic, no promotion of unlisted works.
        for i in range(1, 64):
            self._ensure_current_work_topics(f"work_{i:03d}")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM forum_topics WHERE work_id<>''",
        ).fetchone()[0], 63)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM forum_topics WHERE listed_at_ms IS NULL",
        ).fetchone()[0], 48)

    def test_forum_listing_filters_unlisted_and_shows_listed(self) -> None:
        """Verify forum list only contains listed topics, while discussions map contains all works."""
        now_ms = int(time.time() * 1000)

        # Create 1 listed work and 1 unlisted work
        w_listed = self._create_work("w_listed", "web", now_ms - 2000)
        w_unlisted = self._create_work("w_unlisted", "generation", now_ms - 1000)

        # Attach one discussion to each just-created work.
        self._ensure_current_work_topics("w_listed", "w_unlisted")

        # Set listed work's listed_at_ms
        self.conn.execute("UPDATE forum_topics SET listed_at_ms = ? WHERE work_id = 'w_listed'", (now_ms - 2000,))
        self.conn.commit()

        # Add a regular forum topic (non-work)
        now_iso = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, title, author_username, author_name, summary,
                images_json, status, published_at_ms, created_label, created_at, updated_at, listed_at_ms
            ) VALUES ('top_regular', 'chat', '闲聊', '普通话题', 'bob', 'Bob', '概要',
                      '[]', 'published', ?, '刚刚', ?, ?, ?)
            """,
            (now_ms, now_iso, now_iso, now_ms),
        )
        self.conn.commit()

        # Build boot payload
        payload = build_boot_payload(self.db, None)

        topic_ids = [t["id"] for t in payload.get("topics", [])]
        topic_work_ids = [t.get("workId") for t in payload.get("topics", []) if t.get("workId")]

        # Listed work topic MUST appear in forum topics
        self.assertIn("w_listed", topic_work_ids)

        # Unlisted work topic MUST NOT appear in forum topics
        self.assertNotIn("w_unlisted", topic_work_ids)

        # Regular forum topic MUST appear
        self.assertIn("top_regular", topic_ids)

        # BUT discussions map in boot payload MUST resolve topicId for BOTH works
        discussions = payload.get("discussions", {})
        self.assertIn("w_listed", discussions)
        self.assertIn("w_unlisted", discussions)
        self.assertTrue(discussions["w_unlisted"]["topicId"].startswith("topic_"))

        # Verify public creator statistics share the same listing filter
        _, _, _, creators = compute_public_asset_counts_and_creators(self.conn)
        alice_stats = next((c for c in creators if c["username"] == "alice"), None)
        self.assertIsNotNone(alice_stats)
        # Alice authored 2 works, but only 1 is listed as a topic
        self.assertEqual(alice_stats["topicsCount"], 1)

    def test_unlisted_work_detail_access_and_commenting(self) -> None:
        """Verify unlisted works are accessible directly by ID/ref, and commenting atomically lists them."""
        now_ms = int(time.time() * 1000)
        w = self._create_work("w_secret", "web", now_ms)
        self._ensure_current_work_topics("w_secret")

        # Topic is unlisted
        t_row = self.conn.execute("SELECT * FROM forum_topics WHERE work_id = 'w_secret'").fetchone()
        self.assertIsNotNone(t_row)
        tid = t_row["id"]
        self.assertIsNone(t_row["listed_at_ms"])

        # 1. Detail visibility check: accessible to public
        self.assertTrue(_is_topic_visible(self.conn, t_row, None))

        # 2. Ref resolution check: direct work ID and work- prefix resolve to tid
        self.assertEqual(_resolve_ref_to_topic_id(self.conn, "w_secret", None), tid)
        self.assertEqual(_resolve_ref_to_topic_id(self.conn, "work-w_secret", None), tid)

        # 3. Comment on unlisted work: atomically lists the topic
        rid, bal = record_atomic_reply_and_listing(
            self.conn,
            tid,
            self.bob,
            "太好看了！",
            mounted_style="",
            mounted_layout="",
        )
        self.assertTrue(rid.startswith("rep_"))

        # Check database: listed_at_ms is now set
        t_after = self.conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNotNone(t_after["listed_at_ms"])

        # Check visibility filter: now it IS visible in forum listing
        vis_filter = topic_visibility_sql(reply_filter="1=1", admin=False)
        is_in_forum = self.conn.execute(
            f"SELECT 1 FROM forum_topics WHERE id = ? AND {vis_filter}",
            (tid,),
        ).fetchone()
        self.assertIsNotNone(is_in_forum)

        # 4. Subsequent comment does NOT refresh listed_at_ms
        first_listed_ms = t_after["listed_at_ms"]
        time.sleep(0.01)
        rid2, bal2 = record_atomic_reply_and_listing(
            self.conn,
            tid,
            self.alice,
            "谢谢夸奖！",
            mounted_style="",
            mounted_layout="",
        )
        self.assertTrue(rid2.startswith("rep_"))
        t_after2 = self.conn.execute("SELECT listed_at_ms FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertEqual(t_after2["listed_at_ms"], first_listed_ms)

    def test_forum_sorting_preserves_historical_order_and_floats_new_listings(self) -> None:
        """Verify sorting by COALESCE(listed_at_ms, published_at_ms) DESC preserves old topics and floats new listings."""
        t1_ms = 1000000000000
        t2_ms = 1000000005000
        t3_ms = 1000000010000

        w1 = self._create_work("w_sort_1", "legacy", t1_ms)
        w2 = self._create_work("w_sort_2", "legacy", t2_ms)
        w3 = self._create_work("w_sort_3", "legacy", t3_ms)

        # Each work has its one canonical discussion upon publication.
        self._ensure_current_work_topics("w_sort_1", "w_sort_2", "w_sort_3")

        # Make w1, w2, w3 listed at their published times
        self.conn.execute("UPDATE forum_topics SET listed_at_ms = ? WHERE work_id = 'w_sort_1'", (t1_ms,))
        self.conn.execute("UPDATE forum_topics SET listed_at_ms = ? WHERE work_id = 'w_sort_2'", (t2_ms,))
        self.conn.execute("UPDATE forum_topics SET listed_at_ms = ? WHERE work_id = 'w_sort_3'", (t3_ms,))
        self.conn.commit()

        # Check payload order: w_sort_3 > w_sort_2 > w_sort_1
        payload1 = build_boot_payload(self.db, None)
        work_order = [t.get("workId") for t in payload1.get("topics", []) if t.get("workId") in ("w_sort_1", "w_sort_2", "w_sort_3")]
        self.assertEqual(work_order, ["w_sort_3", "w_sort_2", "w_sort_1"])

        # Now an old unlisted work (published long ago at 5000) gets commented on right now
        w_old = self._create_work("w_sort_old", "generation", 5000)
        self._ensure_current_work_topics("w_sort_old")

        tid_old = self.conn.execute("SELECT id FROM forum_topics WHERE work_id = 'w_sort_old'").fetchone()["id"]
        # Comment triggers listing now
        now_listing_ms = t3_ms + 50000
        with patch("time.time", return_value=now_listing_ms / 1000.0):
            record_atomic_reply_and_listing(self.conn, tid_old, self.bob, "崭新的讨论！")

        # Now w_sort_old floats to the VERY TOP of the forum list because its listed_at_ms is greatest
        payload2 = build_boot_payload(self.db, None)
        work_order2 = [t.get("workId") for t in payload2.get("topics", []) if t.get("workId") in ("w_sort_1", "w_sort_2", "w_sort_3", "w_sort_old")]
        self.assertEqual(work_order2, ["w_sort_old", "w_sort_3", "w_sort_2", "w_sort_1"])


if __name__ == "__main__":
    unittest.main()
