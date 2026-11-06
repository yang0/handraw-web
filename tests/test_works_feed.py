"""Unit and isolation tests for works feed: admission, keyset pagination, frozen popular session, and media dimensions."""
from __future__ import annotations

import json
import os
from unittest.mock import patch
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any
import unittest

from backend import server
from backend.services import (
    _seed_filter,
    publish_user_work,
    register_user,
)
from backend.works_feed import (
    decode_cursor,
    encode_cursor,
    enrich_dimensions,
    get_work_by_id,
    get_works_feed,
    is_valid_work_row,
)


def _insert_work(
    conn: sqlite3.Connection,
    *,
    wid: str,
    title: str = "测试作品",
    author: str = "author_alice",
    status: str = "published",
    prompt: str = "画一只猫",
    images: list[Any] | None = None,
    styles: list[str] | None = None,
    layout: str = "",
    price: int = 0,
    likes: int = 0,
    cheers: int = 0,
    favorites: int = 0,
    forks: int = 0,
    published_at_ms: int = 1000,
    ratio: str = "3:4",
    prompt_has_secret: int = 0,
) -> None:
    if images is None:
        images = ["/images/test_1.png"]
    images_json = json.dumps(images)
    styles_json = json.dumps(styles or [])
    now_iso = "2026-11-02T10:00:00Z"

    conn.execute(
        """
        INSERT INTO works (
            id, title, author_username, author_name, status, prompt,
            prompt_has_secret, images_json, styles_json, layout_code, price, likes, cheers,
            favorites, forks, published_at_ms, ratio, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            wid,
            title,
            author,
            author,
            status,
            prompt,
            prompt_has_secret,
            images_json,
            styles_json,
            layout,
            price,
            likes,
            cheers,
            favorites,
            forks,
            published_at_ms,
            ratio,
            now_iso,
            now_iso,
        ),
    )


class TestWorksFeed(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_db = server.init_database(Path(self.tmp_dir.name) / "feed_test.db")
        # Insert test users
        with self.test_db.transaction() as tx:
            tx.execute(
                "INSERT OR IGNORE INTO users (id, username, display_name, role, status) VALUES (1, 'author_alice', '爱丽丝', 'user', 'active')"
            )
            tx.execute(
                "INSERT OR IGNORE INTO users (id, username, display_name, role, status) VALUES (2, 'author_bob', '鲍勃', 'user', 'active')"
            )
            tx.execute(
                "INSERT OR IGNORE INTO users (id, username, display_name, role, status) VALUES (3, 'admin_yang', '小杨', 'admin', 'active')"
            )

    def tearDown(self):
        self.test_db.close()
        self.tmp_dir.cleanup()

    def test_admission_rules(self):
        conn = self.test_db.get_conn()

        # 1. Normal work with prompt & style
        _insert_work(conn, wid="w_normal", title="标准作品", prompt="水墨竹子", styles=["FA-001"], published_at_ms=100)

        # 2. Work with EMPTY prompt (should be admitted, Issue #50)
        _insert_work(conn, wid="w_empty_prompt", title="无提示词自由作画", prompt="", styles=[], published_at_ms=200)

        # 3. Work with whitespace prompt (should be admitted, Issue #50)
        _insert_work(conn, wid="w_ws_prompt", title="空格提示词", prompt="   \n\t  ", styles=[], published_at_ms=300)

        # 4. Multi-image work (should be admitted)
        _insert_work(conn, wid="w_multi", title="四格分镜", prompt="四格日常", images=["/img1.png", "/img2.png", "/img3.png"], published_at_ms=400)

        # 5. Draft work (status='draft', NOT published, should NOT be admitted)
        _insert_work(conn, wid="w_draft", title="草稿", status="draft", published_at_ms=500)

        # 6. Work with empty images_json [] (invalid images, should NOT be admitted)
        _insert_work(conn, wid="w_no_img", title="无图作品", images=[], published_at_ms=600)

        # 7. Catalog asset record (should NOT be mixed into works feed)
        conn.execute(
            """
            INSERT INTO catalog_assets (
                code, name, kind, group_name, author_username, author_name,
                status, source_type, unlock_cost, image_url, description, definition, published_at_ms,
                created_at, updated_at
            ) VALUES (
                'FA-999', '假画风', 'style', 'test', 'author_alice', '爱丽丝',
                'published', 'community', 0, '/images/catalog_cover.png', 'desc', 'def', 1000,
                '2026-11-02T10:00:00Z', '2026-11-02T10:00:00Z'
            )
            """
        )
        conn.commit()

        feed = get_works_feed(self.test_db, {"sort": "newest", "limit": 20})
        self.assertTrue(feed["ok"])
        feed_ids = {item["id"] for item in feed["items"]}

        # w_normal, w_empty_prompt, w_ws_prompt, w_multi must be present
        self.assertIn("w_normal", feed_ids)
        self.assertIn("w_empty_prompt", feed_ids)
        self.assertIn("w_ws_prompt", feed_ids)
        self.assertIn("w_multi", feed_ids)

        # w_draft, w_no_img, FA-999 must NOT be present
        self.assertNotIn("w_draft", feed_ids)
        self.assertNotIn("w_no_img", feed_ids)
        self.assertNotIn("FA-999", feed_ids)

        # Check format counts
        self.assertGreaterEqual(feed["counts"]["all"], 4)
        self.assertGreaterEqual(feed["counts"]["single"], 3)
        self.assertGreaterEqual(feed["counts"]["multi"], 1)

    def test_keyset_cursor_pagination_zero_omission_zero_duplication(self):
        conn = self.test_db.get_conn()
        total_works = 55

        for i in range(total_works):
            _insert_work(
                conn,
                wid=f"work_pg_{i:03d}",
                title=f"作品 {i}",
                published_at_ms=1000 + i * 10,
                images=[f"/img_{i}.png"],
            )
        conn.commit()

        all_fetched_ids: list[str] = []
        cursor = None

        while True:
            params: dict[str, Any] = {"sort": "newest", "limit": 12, "author": "author_alice"}
            if cursor:
                params["cursor"] = cursor
            res = get_works_feed(self.test_db, params)
            self.assertTrue(res["ok"])
            items = res["items"]
            if not items:
                break
            all_fetched_ids.extend([item["id"] for item in items])
            cursor = res["nextCursor"]
            if not res["hasMore"]:
                break

        inserted_ids = {f"work_pg_{i:03d}" for i in range(total_works)}
        fetched_pg_ids = [wid for wid in all_fetched_ids if wid.startswith("work_pg_")]

        # 1. Total count matches
        self.assertEqual(len(fetched_pg_ids), total_works)

        # 2. No duplicates: len == len(set)
        self.assertEqual(len(set(fetched_pg_ids)), total_works, "Duplicates detected in keyset pagination!")

        # 3. No omissions: set difference is empty
        omissions = inserted_ids - set(fetched_pg_ids)
        self.assertEqual(len(omissions), 0, f"Omissions detected: {omissions}")

        # 4. Strict reverse chronological ordering
        expected_ordered = [f"work_pg_{i:03d}" for i in reversed(range(total_works))]
        self.assertEqual(fetched_pg_ids, expected_ordered)

    def test_popular_frozen_session_stability_under_concurrent_mutations(self):
        conn = self.test_db.get_conn()

        for i in range(30):
            _insert_work(
                conn,
                wid=f"pop_{i:02d}",
                title=f"热门作品 {i}",
                author="author_bob",
                published_at_ms=1000 + i,
                likes=i * 2,
                favorites=i,
                cheers=i * 3,
            )
        conn.commit()

        # First page: initialize frozen popular session
        page1 = get_works_feed(self.test_db, {"sort": "popular", "limit": 10, "author": "author_bob"})
        self.assertTrue(page1["ok"])
        session_id = page1["sessionId"]
        next_cursor = page1["nextCursor"]
        page1_ids = [it["id"] for it in page1["items"]]
        self.assertEqual(len(page1_ids), 10)

        # Simulate concurrent mutations: another user likes/favorites items in page 2 and page 3
        conn.execute("UPDATE works SET likes = likes + 1000, favorites = favorites + 500 WHERE id = 'pop_05'")
        conn.execute("UPDATE works SET likes = likes + 2000, favorites = favorites + 800 WHERE id = 'pop_15'")
        conn.commit()

        # Second page: should read from frozen session with cursor, immune to live score changes
        page2 = get_works_feed(self.test_db, {"sort": "popular", "limit": 10, "author": "author_bob", "cursor": next_cursor})
        self.assertTrue(page2["ok"])
        page2_ids = [it["id"] for it in page2["items"]]
        self.assertEqual(len(page2_ids), 10)

        # Third page
        page3 = get_works_feed(self.test_db, {"sort": "popular", "limit": 10, "author": "author_bob", "cursor": page2["nextCursor"]})
        self.assertTrue(page3["ok"])
        page3_ids = [it["id"] for it in page3["items"]]
        self.assertEqual(len(page3_ids), 10)

        all_pop_ids = page1_ids + page2_ids + page3_ids
        self.assertEqual(len(all_pop_ids), 30)
        self.assertEqual(len(set(all_pop_ids)), 30, "Duplicate items found across pages despite frozen session!")

    def test_filters_and_facets(self):
        conn = self.test_db.get_conn()
        _insert_work(conn, wid="w_f1", title="猫咪单图", author="author_alice", prompt="猫咪", images=["/cat.png"], styles=["FA-001"], price=0, published_at_ms=10)
        _insert_work(conn, wid="w_f2", title="猫咪多图", author="author_alice", prompt="猫咪", images=["/cat1.png", "/cat2.png"], layout="SC-001", price=5, published_at_ms=20)
        _insert_work(conn, wid="w_f3", title="小狗单图", author="author_bob", prompt="小狗", images=["/dog.png"], styles=["FA-002"], price=0, published_at_ms=30)
        conn.commit()

        # Format filter
        single_res = get_works_feed(self.test_db, {"format": "single", "author": "author_alice"})
        self.assertEqual({it["id"] for it in single_res["items"]}, {"w_f1"})
        multi_res = get_works_feed(self.test_db, {"format": "multi", "author": "author_alice"})
        self.assertEqual({it["id"] for it in multi_res["items"]}, {"w_f2"})

        # Access filter
        free_res = get_works_feed(self.test_db, {"access": "free", "author": "author_alice"})
        self.assertEqual({it["id"] for it in free_res["items"]}, {"w_f1"})
        paid_res = get_works_feed(self.test_db, {"access": "paid", "author": "author_alice"})
        self.assertEqual({it["id"] for it in paid_res["items"]}, {"w_f2"})

        # Asset code filter
        asset_res = get_works_feed(self.test_db, {"asset": "FA-001"})
        self.assertEqual({it["id"] for it in asset_res["items"]}, {"w_f1"})
        layout_res = get_works_feed(self.test_db, {"asset": "SC-001"})
        self.assertEqual({it["id"] for it in layout_res["items"]}, {"w_f2"})

        # Search keyword filter
        search_res = get_works_feed(self.test_db, {"q": "小狗"})
        self.assertEqual({it["id"] for it in search_res["items"]}, {"w_f3"})

        # Explicit IDs filter
        ids_res = get_works_feed(self.test_db, {"ids": "w_f1,w_f3"})
        self.assertEqual({it["id"] for it in ids_res["items"]}, {"w_f1", "w_f3"})

    def test_publish_user_work_rejects_empty_prompt(self):
        """A work always carries a prompt; blank or whitespace-only is refused.

        The plaza used to hide prompt-less rows in the query, which made a missing
        prompt look like a display problem. The rule belongs at the write path.
        """
        author, _ = register_user(self.test_db, "author_creator", "password-pwd")

        for blank in ("", "   ", "\n\t "):
            with self.assertRaises(Exception) as excinfo:
                publish_user_work(
                    self.test_db,
                    author,
                    {
                        "title": "无配方画作",
                        "prompt": blank,
                        "images": ["/images/individual/FA/FA-013.webp"],
                    },
                )
            self.assertIn("提示词", str(excinfo.exception))

        # Nothing was written for any of the refused attempts.
        conn = self.test_db.get_conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM works WHERE title = ?", ("无配方画作",)).fetchone()[0], 0)

    def test_publish_user_work_with_prompt_is_in_feed(self):
        author, _ = register_user(self.test_db, "author_creator2", "password-pwd")
        res = publish_user_work(
            self.test_db,
            author,
            {
                "title": "有配方的画作",
                "prompt": "#FA-013 画风：自由小鸟",
                "images": ["/images/individual/FA/FA-013.webp"],
            },
        )
        self.assertTrue(res.get("ok"))
        detail = get_work_by_id(self.test_db, res["workId"], current_user=author)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["title"], "有配方的画作")
        self.assertTrue(detail["prompt"])

    def test_dimensions_enrichment(self):
        conn = self.test_db.get_conn()
        _insert_work(conn, wid="w_dims", title="比例作品", ratio="16:9", images=["/uploads/nonexistent_dummy.png"])
        conn.commit()

        res = get_works_feed(self.test_db, {"ids": "w_dims"})
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["items"]), 1)
        item = res["items"][0]

        # Ratio fallback
        self.assertEqual(item["coverWidth"], 1280)
        self.assertEqual(item["coverHeight"], 720)
        self.assertEqual(item["aspectRatio"], 1.7778)
        self.assertEqual(len(item["imageDimensions"]), 1)
        self.assertEqual(item["imageDimensions"][0]["width"], 1280)
        self.assertEqual(item["imageDimensions"][0]["height"], 720)

    def test_get_work_by_id(self):
        conn = self.test_db.get_conn()
        _insert_work(conn, wid="w_single_detail", title="单件作品", prompt="细节描述", price=0, prompt_has_secret=0)
        conn.commit()

        # Published work found
        detail = get_work_by_id(self.test_db, "w_single_detail")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["id"], "w_single_detail")
        self.assertEqual(detail["title"], "单件作品")
        self.assertEqual(detail["prompt"], "细节描述")
        self.assertIn("coverWidth", detail)
        self.assertIn("coverHeight", detail)

        # Nonexistent work returns None
        self.assertIsNone(get_work_by_id(self.test_db, "w_nonexistent"))


if __name__ == "__main__":
    unittest.main()
