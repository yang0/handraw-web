"""V3 contract: one multi-image generation is one public work in every feed mode."""
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
        self.assertEqual(len(self.batch_wids), 1)

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

    def test_plaza_displays_one_multi_image_work_not_four_cards(self):
        feed = get_works_feed(self.db, {"sort": "newest"})
        self.assertTrue(feed["ok"])
        self.assertEqual(feed["total"], 3)  # batch, single, direct work
        self.assertEqual(len(feed["items"]), 3)
        rep = next(x for x in feed["items"] if x["id"] == self.batch_wids[0])
        self.assertEqual(len(rep["images"]), 4)
        self.assertEqual(rep["images"][0], "/img/pup1.png")
        self.assertEqual(rep["batchTotal"], 1)

    def test_search_returns_one_multi_image_work(self):
        feed = get_works_feed(self.db, {"q": "batch generation cute puppies"})
        self.assertTrue(feed["ok"])
        self.assertEqual(feed["total"], 1)
        self.assertEqual([it["id"] for it in feed["items"]], self.batch_wids)
        self.assertEqual(len(feed["items"][0]["images"]), 4)

    def test_paginated_feed_never_duplicates_the_run(self):
        first = get_works_feed(self.db, {"sort": "newest", "limit": 2})
        self.assertEqual(first["total"], 3)
        self.assertEqual(len(first["items"]), 2)
        self.assertTrue(first["hasMore"])
        second = get_works_feed(self.db, {
            "sort": "newest", "limit": 2, "cursor": first["nextCursor"],
        })
        self.assertEqual(len(second["items"]), 1)
        ids = [w["id"] for w in first["items"] + second["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids.count(self.batch_wids[0]), 1)

    def test_moderator_hidden_run_is_not_repromoted(self):
        work_id = self.batch_wids[0]
        res = admin_moderate_work(self.db, self.admin, work_id, "delete")
        self.assertTrue(res["ok"])
        # Replaying a generation cannot recreate a deleted/hidden work.
        project_generation_to_works(self.conn, "gen_batch_4img")
        feed = get_works_feed(self.db, {"sort": "newest"})
        self.assertNotIn(work_id, [row["id"] for row in feed["items"]])
        self.assertEqual(feed["total"], 2)
        gen = self.conn.execute(
            "SELECT 1 FROM studio_generations WHERE id='gen_batch_4img'"
        ).fetchone()
        self.assertIsNotNone(gen)


if __name__ == "__main__":
    unittest.main()
