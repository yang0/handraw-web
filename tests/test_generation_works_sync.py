from __future__ import annotations

import concurrent.futures
import json
import os
from unittest.mock import patch
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any
import unittest

from backend.db import Database
from backend.server import init_database
from backend.generation_works import (
    derive_item_key,
    project_generation_to_works,
    sync_generation_visibility,
    backfill_historical_generations,
    get_work_generation_provenance,
)
from backend.resource_discussions import comment
from backend.services import (
    register_user,
    record_user_studio_history,
    delete_user_studio_history,
    delete_all_user_studio_history,
    toggle_user_like,
    toggle_user_collection,
    publish_forum_topic_post,
    ServiceError,
)
from backend.works_feed import get_works_feed, get_work_by_id


class TestGenerationWorksSync(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_gen_works.db"
        self.db = init_database(self.db_path)
        self.user_author, self.token_author = register_user(self.db, "author_yang", "Pass1234!", display_name="杨凌")
        self.user_reader, self.token_reader = register_user(self.db, "reader_lin", "Pass1234!", display_name="小林")
        self.user_other, self.token_other = register_user(self.db, "reader_other", "Pass1234!", display_name="路人")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_idempotent_projection_and_backfill(self):
        """同一成功结果重复同步、回填各执行三次，每个图片项始终只有一个作品"""
        conn = self.db.get_conn()
        now_iso = "2026-10-01T10:00:00Z"
        gen_id = "gen_test_idempotent_01"
        items = [
            {"id": "it_01", "imageUrl": "/uploads/art_01.webp", "ratio": "3:4", "title": "成图 #1"},
            {"id": "it_02", "imageUrl": "/uploads/art_02.webp", "ratio": "3:4", "title": "成图 #2"},
        ]
        conn.execute(
            """
            INSERT INTO studio_generations (
                id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                prompt, visible_prompt, prompt_masked, markdown, items_json, engine, cost_type,
                credits_spent, status, created_at, request_id, subject, visibility
            ) VALUES (?, ?, ?, '图文模式', 'graphic-text', '图文创作', 'single', '画风 #FA-001 · 3:4',
                      '暖黄灯光', '暖黄灯光', 0, '', ?, 'live', 'free', 0, 'success', ?, 'req_01', '书店一隅', 'public')
            """,
            (gen_id, self.user_author["id"], self.user_author["username"], json.dumps(items), now_iso),
        )
        conn.commit()

        # Step 1: project_generation_to_works 3 times
        wids_1 = project_generation_to_works(conn, gen_id)
        wids_2 = project_generation_to_works(conn, gen_id)
        wids_3 = project_generation_to_works(conn, gen_id)

        self.assertEqual(len(wids_1), 2)
        self.assertEqual(wids_1, wids_2)
        self.assertEqual(wids_2, wids_3)

        # Check mapping table count
        m_count = conn.execute("SELECT COUNT(*) FROM generation_works WHERE generation_id = ?", (gen_id,)).fetchone()[0]
        self.assertEqual(m_count, 2)

        # Check works table count
        w_count = conn.execute("SELECT COUNT(*) FROM works WHERE origin = 'generation'").fetchone()[0]
        self.assertEqual(w_count, 2)

        # Verify title does not leak tabTitle '图文模式'
        work_rows = conn.execute("SELECT id, title, subject, published_at_ms FROM works WHERE origin = 'generation'").fetchall()
        for w in work_rows:
            self.assertEqual(w["title"], "书店一隅")
            self.assertEqual(w["subject"], "书店一隅")

        # Step 2: backfill_historical_generations 3 times
        b1 = backfill_historical_generations(conn)
        b2 = backfill_historical_generations(conn)
        b3 = backfill_historical_generations(conn)

        self.assertEqual(b1["projected"], 2)
        self.assertEqual(b2["projected"], 2)
        self.assertEqual(b3["projected"], 2)

        # Still strictly 2 works in works table and generation_works
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM generation_works WHERE generation_id = ?", (gen_id,)).fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM works WHERE origin = 'generation'").fetchone()[0], 2)

    def test_a_shared_picture_is_not_projected_twice(self):
        """A picture shared before the projection existed is adopted, not copied.

        This is the reported bug: generate a picture, share it (which creates a
        work), and the projection then created a second work for the same file,
        so the square showed that picture twice.
        """
        conn = self.db.get_conn()
        uname = self.user_author["username"]
        image = "/generated/shared_once.png"

        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, prompt, images_json,
                               status, origin, published_at_ms, created_at, updated_at)
            VALUES ('work_shared', ?, ?, '开始工作了', 'p', ?, 'published', 'web', 1000, '刚刚', '刚刚')
            """,
            (uname, uname, json.dumps([image])),
        )
        conn.execute(
            """
            INSERT INTO studio_generations (
                id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                prompt, visible_prompt, prompt_masked, markdown, items_json, engine, cost_type,
                credits_spent, status, created_at, request_id, subject, visibility
            ) VALUES ('gen_shared', ?, ?, '图文模式', 'graphic-text', '图文创作', 'single', '画风 #FA-001',
                      'p', 'p', 0, '', ?, 'live', 'free', 0, 'success', '2026-10-01T10:00:00Z', 'req_s', '', 'public')
            """,
            (self.user_author["id"], uname, json.dumps([{"id": "it_s", "imageUrl": image}])),
        )
        conn.commit()

        project_generation_to_works(conn, "gen_shared")
        conn.commit()

        rows = conn.execute(
            "SELECT id FROM works WHERE status='published' AND images_json LIKE ?", (f"%{image}%",)
        ).fetchall()
        self.assertEqual(len(rows), 1, f"one picture must be one work, got {[r['id'] for r in rows]}")
        self.assertEqual(rows[0]["id"], "work_shared", "the existing work is adopted, not replaced")

    def test_invisibility_of_failed_private_and_deleted_results(self):
        """失败、无图、私密、软删除结果公开接口均不可见；直接访问和互动入口同样检查权限"""
        conn = self.db.get_conn()
        now_iso = "2026-10-02T10:00:00Z"

        # 1. Failed generation -> not projected
        conn.execute(
            """
            INSERT INTO studio_generations (id, user_id, username, tab_title, mode, prompt, items_json, status, created_at, visibility)
            VALUES ('gen_failed', ?, 'author_yang', '图文模式', 'mode', 'prompt', '["/img1.webp"]', 'error', ?, 'public')
            """,
            (self.user_author["id"], now_iso),
        )
        self.assertEqual(project_generation_to_works(conn, "gen_failed"), [])

        # 2. Empty items generation -> not projected
        conn.execute(
            """
            INSERT INTO studio_generations (id, user_id, username, tab_title, mode, prompt, items_json, status, created_at, visibility)
            VALUES ('gen_no_items', ?, 'author_yang', '图文模式', 'mode', 'prompt', '[]', 'success', ?, 'public')
            """,
            (self.user_author["id"], now_iso),
        )
        self.assertEqual(project_generation_to_works(conn, "gen_no_items"), [])

        # 3. Private generation -> not projected
        conn.execute(
            """
            INSERT INTO studio_generations (id, user_id, username, tab_title, mode, prompt, items_json, status, created_at, visibility)
            VALUES ('gen_private', ?, 'author_yang', '图文模式', 'mode', 'prompt', '["/secret.webp"]', 'success', ?, 'private')
            """,
            (self.user_author["id"], now_iso),
        )
        self.assertEqual(project_generation_to_works(conn, "gen_private"), [])

        # 4. Public generation projected, then made private / deleted
        conn.execute(
            """
            INSERT INTO studio_generations (id, user_id, username, tab_title, mode, prompt, items_json, status, created_at, visibility)
            VALUES ('gen_pub_then_del', ?, 'author_yang', '图文模式', 'mode', 'prompt', '["/pub_del.webp"]', 'success', ?, 'public')
            """,
            (self.user_author["id"], now_iso),
        )
        wids = project_generation_to_works(conn, "gen_pub_then_del")
        self.assertEqual(len(wids), 1)
        wid = wids[0]

        # Verify visible before delete
        w_before = get_work_by_id(self.db, wid, current_user=self.user_reader)
        self.assertIsNotNone(w_before)

        # Soft delete the generation
        delete_user_studio_history(self.db, self.user_author, "gen_pub_then_del")

        # Now work is hidden
        w_after = get_work_by_id(self.db, wid, current_user=self.user_reader)
        self.assertIsNone(w_after, "Deleted generation work must return 404 / None in get_work_by_id")

        # Like and collect should fail on hidden work
        with self.assertRaises(ServiceError) as ctx_like:
            toggle_user_like(self.db, self.user_reader, "work", wid, "like")
        self.assertEqual(ctx_like.exception.status, 404)

        with self.assertRaises(ServiceError) as ctx_col:
            toggle_user_collection(self.db, self.user_reader, "works", wid, "add")
        self.assertEqual(ctx_col.exception.status, 404)

        with self.assertRaises(ServiceError) as ctx_cmt:
            comment(self.db, self.user_reader, "work", wid, "读者评论")
        self.assertEqual(ctx_cmt.exception.status, 404)

    def test_history_deletion_and_public_work_sync_are_atomic(self):
        """Single and bulk history deletion roll back on projected-work sync failures."""
        conn = self.db.get_conn()
        for index in (1, 2):
            gen_id = f"gen_atomic_{index}"
            conn.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, prompt,
                    items_json, status, created_at, visibility
                ) VALUES (?, ?, 'author_yang', '图文', 'graphic-text', 'p',
                          ?, 'success', ?, 'public')
                """,
                (
                    gen_id,
                    self.user_author["id"],
                    json.dumps([{"id": f"atomic_image_{index}", "imageUrl": f"/atomic_{index}.webp"}]),
                    f"2026-11-01T10:00:0{index}Z",
                ),
            )
            self.assertEqual(len(project_generation_to_works(conn, gen_id)), 1)
        conn.commit()

        with self.assertRaises(ServiceError) as unauthorized:
            delete_user_studio_history(self.db, self.user_other, "gen_atomic_1")
        self.assertEqual(unauthorized.exception.status, 403)

        with patch("backend.generation_works.sync_generation_visibility", side_effect=RuntimeError("sync failed")):
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                delete_user_studio_history(self.db, self.user_author, "gen_atomic_1")
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                delete_all_user_studio_history(self.db, self.user_author)

        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM studio_generations WHERE id LIKE 'gen_atomic_%' AND deleted_at IS NULL"
            ).fetchone()[0],
            2,
            "History deletion must roll back on sync failure",
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM generation_works gw JOIN works w ON w.id = gw.work_id "
                "WHERE gw.generation_id LIKE 'gen_atomic_%' AND w.status = 'published'"
            ).fetchone()[0],
            2,
            "Linked public works must remain visible after a rolled-back delete",
        )

        delete_user_studio_history(self.db, self.user_author, "gen_atomic_1")
        self.assertIsNotNone(
            conn.execute("SELECT deleted_at FROM studio_generations WHERE id = 'gen_atomic_1'").fetchone()[0]
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM generation_works gw JOIN works w ON w.id = gw.work_id "
                "WHERE gw.generation_id = 'gen_atomic_1' AND w.status = 'published'"
            ).fetchone()[0],
            0,
        )

    def test_identical_timestamp_keyset_traversal(self):
        """含相同时间戳的 100 件作品以每页 7 件遍历，无重复、无遗漏"""
        conn = self.db.get_conn()
        fixed_ms = 1700000000000
        now_iso = "2026-10-03T12:00:00Z"

        for i in range(100):
            conn.execute(
                """
                INSERT INTO works (
                    id, author_username, author_name, title, images_json, styles_json,
                    layout_code, color_code, tone_code, ratio, mode, mood, price,
                    prompt, prompt_has_secret, notes, status, featured, is_new_release,
                    pioneer_rewarded, cheers, likes, favorites, forks, tips, views,
                    stamp_counts_json, published_at_ms, created_label, created_at, updated_at,
                    origin, request_id, forked_from_id, subject
                ) VALUES (
                    ?, 'author_yang', '杨凌', ?, '["/img.webp"]', '["FA-001"]',
                    'SC-001', 'C-15', 'T-01', '3:4', 'graphic-text', '治愈', 0,
                    'prompt', 0, '', 'published', 0, 1,
                    0, 0, 0, 0, 0, 0, 0,
                    '{}', ?, '刚刚', ?, ?,
                    'generation', '', '', '测试相同时间戳'
                )
                """,
                (f"work_same_time_{i:03d}", f"测试作品 #{i}", fixed_ms, now_iso, now_iso),
            )
        conn.commit()

        # Traverse feed with limit = 7 using keyset pagination
        seen_ids: list[str] = []
        cursor = ""
        while True:
            feed = get_works_feed(self.db, {"limit": 7, "cursor": cursor, "sort": "newest"})
            items = feed["items"]
            for it in items:
                seen_ids.append(it["id"])
            if not feed["hasMore"] or not feed.get("nextCursor"):
                break
            cursor = feed["nextCursor"]

        # Filter to only the 100 test works
        test_seen = [x for x in seen_ids if x.startswith("work_same_time_")]
        self.assertEqual(len(test_seen), 100, "Must visit all 100 items")
        self.assertEqual(len(set(test_seen)), 100, "No duplicate items allowed in traversal")

    def test_popular_frozen_session_and_dynamic_exclusion(self):
        """热门分页中改变点赞不改变冻结顺序；中途隐藏作品后不再返回"""
        conn = self.db.get_conn()
        now_iso = "2026-10-04T12:00:00Z"

        # Create 10 works with descending likes: 10, 9, 8, ..., 1
        for i in range(10):
            conn.execute(
                """
                INSERT INTO works (
                    id, author_username, author_name, title, images_json, styles_json,
                    layout_code, color_code, tone_code, ratio, mode, mood, price,
                    prompt, prompt_has_secret, notes, status, featured, is_new_release,
                    pioneer_rewarded, cheers, likes, favorites, forks, tips, views,
                    stamp_counts_json, published_at_ms, created_label, created_at, updated_at,
                    origin, request_id, forked_from_id, subject
                ) VALUES (
                    ?, 'author_yang', '杨凌', ?, '["/img.webp"]', '["FA-001"]',
                    'SC-001', 'C-15', 'T-01', '3:4', 'graphic-text', '治愈', 0,
                    'prompt', 0, '', 'published', 0, 1,
                    0, 0, ?, 0, 0, 0, 0,
                    '{}', ?, '刚刚', ?, ?,
                    'generation', '', '', '热门排序测试'
                )
                """,
                (f"work_pop_{i}", f"热门作品 #{i}", 10 - i, 1700000000000 + i * 1000, now_iso, now_iso),
            )
        conn.commit()

        # Page 1 (limit=4)
        p1 = get_works_feed(self.db, {"sort": "popular", "limit": 4}, current_user=self.user_reader)
        self.assertTrue(p1["ok"])
        p1_ids = [w["id"] for w in p1["items"]]
        self.assertEqual(p1_ids, ["work_pop_0", "work_pop_1", "work_pop_2", "work_pop_3"])

        # Dynamically change likes on work_pop_9 (from 1 to 9999) - should NOT affect frozen session!
        conn.execute("UPDATE works SET likes = 9999 WHERE id = 'work_pop_9'")
        # Also dynamically hide work_pop_5 (moderator hide)
        from backend.services import set_work_visibility
        set_work_visibility(conn, "work_pop_5", "hidden", now_iso, source="moderator")
        conn.commit()

        # Page 2 (limit=4) using cursor from Page 1
        p2 = get_works_feed(self.db, {"sort": "popular", "limit": 4, "cursor": p1["nextCursor"]}, current_user=self.user_reader)
        p2_ids = [w["id"] for w in p2["items"]]

        # Order must remain frozen (work_pop_9 did NOT jump to page 2)
        # work_pop_5 was hidden, so it is excluded from page 2!
        self.assertNotIn("work_pop_5", p2_ids, "Hidden work must be immediately excluded from next page")
        self.assertNotIn("work_pop_9", p2_ids, "Likes increase must not alter frozen session ordering")
        self.assertIn("work_pop_4", p2_ids)
        self.assertIn("work_pop_6", p2_ids)

    def test_first_comment_topic_creation_and_author_guard(self):
        """别人的首条有效评论触发建帖；作者自己评论不触发；并发首评只产生一个关联讨论帖"""
        conn = self.db.get_conn()
        now_iso = "2026-10-05T12:00:00Z"
        wid = "work_first_comment_test"

        conn.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, images_json, styles_json,
                layout_code, color_code, tone_code, ratio, mode, mood, price,
                prompt, prompt_has_secret, notes, status, featured, is_new_release,
                pioneer_rewarded, cheers, likes, favorites, forks, tips, views,
                stamp_counts_json, published_at_ms, created_label, created_at, updated_at,
                origin, request_id, forked_from_id, subject
            ) VALUES (
                ?, 'author_yang', '杨凌', '初秋红叶', '["/leaves.webp"]', '["FA-001"]',
                'SC-001', 'C-15', 'T-01', '3:4', 'graphic-text', '治愈', 0,
                '枫叶飘落', 0, '', 'published', 0, 1,
                0, 0, 0, 0, 0, 0, 0,
                '{}', 1700000000000, '刚刚', ?, ?,
                'generation', '', '', '秋天'
            )
            """,
            (wid, now_iso, now_iso),
        )
        conn.commit()

        # 1. Author comments on own work with no topic -> succeeds! Atomically creates topic and lists it
        res_author = comment(self.db, self.user_author, "work", wid, "作者自己写心得")
        self.assertTrue(res_author["ok"])
        tid = res_author["topicId"]
        self.assertTrue(tid.startswith("topic_"))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM forum_topics WHERE work_id = ?", (wid,)).fetchone()[0], 1)

        # 2. Non-author comments -> attaches to same topic
        res_reader = comment(self.db, self.user_reader, "work", wid, "好美的画面！")
        self.assertTrue(res_reader["ok"])
        self.assertEqual(res_reader["topicId"], tid)

        # Verify topic exists in forum_topics and curation_resource_topics
        t_row = conn.execute("SELECT * FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertIsNotNone(t_row)
        self.assertEqual(t_row["work_id"], wid)
        self.assertEqual(t_row["author_username"], "author_yang")

        m_row = conn.execute("SELECT * FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (wid,)).fetchone()
        self.assertIsNotNone(m_row)
        self.assertEqual(m_row["topic_id"], tid)

        # 3. Now that topic exists, author CAN reply to this topic!
        res_author_reply = comment(self.db, self.user_author, "work", wid, "谢谢小林鼓励！")
        self.assertTrue(res_author_reply["ok"])
        self.assertEqual(res_author_reply["topicId"], tid)

        # 4. Concurrent 20 comments by different readers: only ONE topic exists!
        def post_comment(i: int):
            user = dict(self.user_other)
            user["username"] = f"other_{i}"
            user["display_name"] = f"路人{i}"
            return comment(self.db, user, "work", wid, f"第 {i} 条并发评论")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(post_comment, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(results), 20)
        for r in results:
            self.assertEqual(r["topicId"], tid)

        # Exactly 1 topic row for this work in forum_topics and curation_resource_topics
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM forum_topics WHERE work_id = ?", (wid,)).fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (wid,)).fetchone()[0], 1)

        # Exactly 22 replies total (1 reader + 1 author + 20 concurrent)
        rep_count = conn.execute("SELECT COUNT(*) FROM forum_replies WHERE topic_id = ?", (tid,)).fetchone()[0]
        self.assertEqual(rep_count, 23)


if __name__ == "__main__":
    unittest.main()
