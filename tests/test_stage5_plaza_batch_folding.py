"""Tests for Stage 5: Plaza Same-Batch Folding + Search Individual Items (Issue #60)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import Database
from backend.generation_works import project_generation_to_works
from backend.services import register_user, utc_now_iso
from backend.works_feed import get_works_feed, get_work_by_id
from backend.admin_services import admin_moderate_work


class Stage5PlazaBatchFoldingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_stage5.db"
        self._env = patch.dict(
            os.environ,
            {
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_DEMO_MODE": "1",
            },
        )
        self._env.start()
        self.db = Database(self.db_path)
        self.db.migrate()
        self.conn = self.db.get_conn()

        # Seed users
        self.alice, _ = register_user(self.db, "alice", "pass-alice", display_name="Alice")
        self.admin, _ = register_user(self.db, "admin", "pass-admin", display_name="Admin")
        self.admin["role"] = "admin"
        self.conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin["id"],))

        now_iso = utc_now_iso()
        # 1. Create a 4-image generation for Alice
        gen_batch_row = {
            "id": "gen_batch_4img",
            "user_id": self.alice["id"],
            "username": "alice",
            "author_name": "Alice",
            "subject": "batch generation cute puppies",
            "mode": "quick",
            "engine": "dall-e-3",
            "aspect_ratio": "1:1",
            "image_count": 4,
            "items_json": json.dumps([
                {"id": "img_b1", "imageUrl": "/img/pup1.png", "ratio": "1:1", "title": "小狗画作 #1"},
                {"id": "img_b2", "imageUrl": "/img/pup2.png", "ratio": "1:1", "title": "小狗画作 #2"},
                {"id": "img_b3", "imageUrl": "/img/pup3.png", "ratio": "1:1", "title": "小狗画作 #3"},
                {"id": "img_b4", "imageUrl": "/img/pup4.png", "ratio": "1:1", "title": "小狗画作 #4"},
            ]),
            "styles_json": "[]",
            "layout_code": "",
            "reference_images_json": "[]",
            "status": "success",
            "visibility": "public",
            "created_at": now_iso,
            "completed_at": now_iso,
        }
        self.conn.execute(
            """
            INSERT INTO studio_generations (
                id, user_id, username, mode, items_json, engine, status, visibility, created_at, subject
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gen_batch_row["id"], gen_batch_row["user_id"], gen_batch_row["username"],
                gen_batch_row["mode"], gen_batch_row["items_json"], gen_batch_row["engine"],
                gen_batch_row["status"], gen_batch_row["visibility"], gen_batch_row["created_at"],
                gen_batch_row["subject"]
            ),
        )
        self.batch_wids = project_generation_to_works(self.conn, gen_batch_row)
        self.assertEqual(len(self.batch_wids), 4)

        # 2. Create a single-image generation for Alice
        gen_single_row = {
            "id": "gen_single_1img",
            "user_id": self.alice["id"],
            "username": "alice",
            "author_name": "Alice",
            "subject": "single mountain landscape",
            "mode": "quick",
            "engine": "dall-e-3",
            "aspect_ratio": "16:9",
            "image_count": 1,
            "items_json": json.dumps([
                {"id": "img_s1", "imageUrl": "/img/mt1.png", "ratio": "16:9", "title": "高山风光"},
            ]),
            "styles_json": "[]",
            "layout_code": "",
            "reference_images_json": "[]",
            "status": "success",
            "visibility": "public",
            "created_at": now_iso,
            "completed_at": now_iso,
        }
        self.conn.execute(
            """
            INSERT INTO studio_generations (
                id, user_id, username, mode, items_json, engine, status, visibility, created_at, subject
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gen_single_row["id"], gen_single_row["user_id"], gen_single_row["username"],
                gen_single_row["mode"], gen_single_row["items_json"], gen_single_row["engine"],
                gen_single_row["status"], gen_single_row["visibility"], gen_single_row["created_at"],
                gen_single_row["subject"]
            ),
        )
        self.single_wids = project_generation_to_works(self.conn, gen_single_row)
        self.assertEqual(len(self.single_wids), 1)

        # 3. Create a legacy work (no generation)
        self.legacy_wid = "work_legacy_001"
        self.conn.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, images_json, styles_json,
                layout_code, color_code, tone_code, ratio, mode, mood, price,
                prompt, prompt_has_secret, notes, status, featured, is_new_release,
                pioneer_rewarded, cheers, likes, favorites, forks, tips, views,
                stamp_counts_json, published_at_ms, created_label, created_at, updated_at,
                origin, request_id, forked_from_id, subject
            ) VALUES (
                ?, 'alice', 'Alice', '传统手工绘图', '["/img/legacy.png"]', '[]',
                '', 'C-15', 'T-01', '3:4', 'graphic-text', '治愈', 0,
                'hand drawing prompt', 0, '', 'published', 0, 1,
                0, 0, 10, 5, 0, 0, 0,
                '{}', ?, '刚刚', ?, ?,
                'legacy', '', '', '手工水彩画'
            )
            """,
            (self.legacy_wid, int(time.time() * 1000) - 5000, now_iso, now_iso),
        )

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.conn.close()
        self.db.close()
        self._env.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_plaza_feed_collapses_same_batch_to_single_representative(self) -> None:
        """In plaza browsing without search, 4 same-batch works collapse to 1 representative card."""
        feed = get_works_feed(self.db, {"sort": "newest"})
        self.assertTrue(feed["ok"])
        items = feed["items"]

        # Exactly 3 items in feed: 1 representative from batch, 1 single, 1 legacy
        self.assertEqual(feed["total"], 3)
        self.assertEqual(len(items), 3)

        rep_item = next((it for it in items if it["id"] == self.batch_wids[0]), None)
        self.assertIsNotNone(rep_item, "First work in batch must be representative")
        self.assertEqual(rep_item["batchTotal"], 4)
        self.assertEqual(rep_item["batchIndex"], 1)

        # Other 3 sibling works must NOT appear in plaza feed
        for sibling_id in self.batch_wids[1:]:
            self.assertNotIn(sibling_id, [it["id"] for it in items])

        # Single work has batchTotal = 1
        single_item = next((it for it in items if it["id"] == self.single_wids[0]), None)
        self.assertIsNotNone(single_item)
        self.assertEqual(single_item["batchTotal"], 1)

    def test_search_mode_returns_all_individual_items_with_indices(self) -> None:
        """In search mode, works are NOT collapsed: 4 batch works return as 4 cards with batch index."""
        feed = get_works_feed(self.db, {"q": "小狗"})
        self.assertTrue(feed["ok"])
        items = feed["items"]

        # 4 cards returned for search matching '小狗'
        self.assertEqual(feed["total"], 4)
        self.assertEqual(len(items), 4)

        returned_ids = [it["id"] for it in items]
        self.assertEqual(set(returned_ids), set(self.batch_wids))

        # Check batch metadata on search items
        for it in items:
            self.assertEqual(it["batchTotal"], 4)
            idx = self.batch_wids.index(it["id"]) + 1
            self.assertEqual(it["batchIndex"], idx)

    def test_pagination_folds_first_then_slices(self) -> None:
        """Pagination must fold by batch first, then count and slice so page limits and totals are exact."""
        # Page 1 with limit = 2
        p1 = get_works_feed(self.db, {"sort": "newest", "limit": 2})
        self.assertEqual(p1["total"], 3)
        self.assertEqual(len(p1["items"]), 2)
        self.assertTrue(p1["hasMore"])
        self.assertIsNotNone(p1["nextCursor"])

        # Page 2
        p2 = get_works_feed(self.db, {"sort": "newest", "limit": 2, "cursor": p1["nextCursor"]})
        self.assertEqual(len(p2["items"]), 1)
        self.assertFalse(p2["hasMore"])

        all_ids = [it["id"] for it in p1["items"]] + [it["id"] for it in p2["items"]]
        self.assertEqual(len(all_ids), 3)
        self.assertEqual(len(set(all_ids)), 3)

    def test_representative_deletion_automatically_promotes_next_item(self) -> None:
        """Deleting representative work automatically advances the representative to the next sibling."""
        rep_id = self.batch_wids[0]
        next_rep_id = self.batch_wids[1]

        # Admin deletes first representative
        res = admin_moderate_work(self.db, self.admin, rep_id, "delete")
        self.assertTrue(res["ok"])

        # Feed must now show next_rep_id as representative with batchTotal = 3
        feed = get_works_feed(self.db, {"sort": "newest"})
        items = feed["items"]
        self.assertEqual(feed["total"], 3)

        new_rep = next((it for it in items if it["id"] == next_rep_id), None)
        self.assertIsNotNone(new_rep, "Next work in batch must become representative")
        self.assertEqual(new_rep["batchTotal"], 3)
        self.assertEqual(new_rep["batchIndex"], 1)

        # Delete remaining 3 works
        for wid in self.batch_wids[1:]:
            admin_moderate_work(self.db, self.admin, wid, "delete")

        # Now the batch has completely disappeared from plaza
        feed_after = get_works_feed(self.db, {"sort": "newest"})
        self.assertEqual(feed_after["total"], 2)  # Only single + legacy
        for wid in self.batch_wids:
            self.assertNotIn(wid, [it["id"] for it in feed_after["items"]])

        # Studio generation record is still preserved
        gen_exists = self.conn.execute("SELECT 1 FROM studio_generations WHERE id = 'gen_batch_4img'").fetchone()
        self.assertIsNotNone(gen_exists, "studio_generations record must be preserved")


if __name__ == "__main__":
    unittest.main()
