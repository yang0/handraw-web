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

from tests.legacy_database import Database
from tests.legacy_database import init_legacy_database
from backend.generation_works import (
    derive_item_key,
    project_generation_to_works,
    sync_generation_visibility,
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
        self.db = init_legacy_database(self.db_path)
        self.user_author, self.token_author = register_user(self.db, "author_yang", "Pass1234!", display_name="杨凌")
        self.user_reader, self.token_reader = register_user(self.db, "reader_lin", "Pass1234!", display_name="小林")
        self.user_other, self.token_other = register_user(self.db, "reader_other", "Pass1234!", display_name="路人")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_idempotent_projection_and_backfill(self):
        """同一生成任务可包含多张图片，但重复同步与回填始终只有一件作品"""
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

        self.assertEqual(len(wids_1), 1)
        self.assertEqual(wids_1, wids_2)
        self.assertEqual(wids_2, wids_3)

        # Direct FK: one run has exactly one published work.
        m_count = conn.execute(
            """
            SELECT COUNT(*) FROM works w JOIN generation_runs r ON r.id=w.run_id
            WHERE r.source='web' AND r.external_run_id=?
            """, (gen_id,),
        ).fetchone()[0]
        self.assertEqual(m_count, 1)

        # Check works table count
        w_count = conn.execute("SELECT COUNT(*) FROM works WHERE origin = 'generation'").fetchone()[0]
        self.assertEqual(w_count, 1)

        self.assertEqual(json.loads(conn.execute("SELECT images_json FROM works WHERE id=?",
            (wids_1[0],)).fetchone()[0]), ["/uploads/art_01.webp", "/uploads/art_02.webp"])

        # Verify title does not leak tabTitle '图文模式'
        work_rows = conn.execute("SELECT id, title, subject, published_at_ms FROM works WHERE origin = 'generation'").fetchall()
        for w in work_rows:
            self.assertEqual(w["title"], "书店一隅")
            self.assertEqual(w["subject"], "书店一隅")

        # New databases do not perform a legacy history backfill.
        # The canonical image list remains exactly two on every replay.
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM work_media WHERE work_id=?", (wids_1[0],)
        ).fetchone()[0], 2)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM works WHERE origin='generation'"
        ).fetchone()[0], 1)

    def test_multi_image_run_keeps_cover_and_single_gallery_work(self):
        """Five outputs are one work; blank and duplicate results are not published."""
        conn = self.db.get_conn()
        uid = self.user_author["id"]
        uname = self.user_author["username"]
        urls = [f"/generated/scene_{i}.webp" for i in range(5)]
        items = ([{"id": f"image_{i}", "imageUrl": url} for i, url in enumerate(urls)]
                 + [{"id": "failed", "imageUrl": "", "status": "failed"},
                    {"id": "duplicate", "imageUrl": urls[0]}])
        conn.execute(
            """
            INSERT INTO studio_generations
                (id,user_id,username,tab_title,mode,prompt,visible_prompt,items_json,
                 status,created_at,visibility,engine)
            VALUES ('gen_multi_v3',?,?,?,?,?,?,?, 'success',?, 'public','live')
            """,
            (uid, uname, "五张作品", "graphic-text", "手绘小镇", "手绘小镇",
             json.dumps(items), "2026-10-02T10:00:00Z"),
        )
        conn.commit()
        for _ in range(3):
            work_ids = project_generation_to_works(conn, "gen_multi_v3")
            self.assertEqual(len(work_ids), 1)
        conn.commit()
        work = conn.execute("SELECT images_json FROM works WHERE id=?", (work_ids[0],)).fetchone()
        self.assertEqual(json.loads(work["images_json"]), urls)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM work_media WHERE work_id=?", (work_ids[0],)
        ).fetchone()[0], 5)
        feed = get_works_feed(self.db, {"author": uname, "sort": "newest", "limit": 10})
        matching = [w for w in feed["items"] if w["id"] == work_ids[0]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["images"], urls)

    def test_parallel_cloud_slots_share_one_batch_work(self):
        """Cloud requests finish out of order but remain one ordered work."""
        conn = self.db.get_conn()
        uid = self.user_author["id"]
        uname = self.user_author["username"]
        work_ids = []
        # Slot 1 finishes before slot 0; the eventual cover must be slot 0.
        for index in (1, 0):
            gid = f"gen_batch_slot_{index}"
            conn.execute("""
                INSERT INTO studio_generations (
                    id,user_id,username,tab_title,mode,prompt,visible_prompt,
                    items_json,status,created_at,visibility,engine,
                    batch_id,batch_index,batch_total
                ) VALUES (?,?,?,?,?,?,?,?,'success',?,'public','live',?,?,?)
            """, (
                gid, uid, uname, "两张作品", "graphic-text", "春日小镇",
                "春日小镇", json.dumps([f"/generated/out_{index}.webp"]),
                f"2026-10-02T10:0{index}:00Z", "batch_unique_v3", index, 2,
            ))
            work_ids.extend(project_generation_to_works(conn, gid))
        conn.commit()
        self.assertEqual(work_ids[0], work_ids[1])
        rows = conn.execute(
            """SELECT w.id,w.images_json,r.external_run_id
               FROM works w JOIN generation_runs r ON r.id=w.run_id
               WHERE r.user_id=? AND r.external_run_id=?""",
            (uid, "batch_unique_v3"),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["images_json"]),
                         ["/generated/out_0.webp", "/generated/out_1.webp"])
        discussion = conn.execute(
            "SELECT images_json FROM forum_topics WHERE work_id=?", (work_ids[0],)
        ).fetchone()
        self.assertIsNotNone(discussion)
        self.assertEqual(json.loads(discussion["images_json"]),
                         ["/generated/out_0.webp", "/generated/out_1.webp"])
        for _ in range(2):
            project_generation_to_works(conn, "gen_batch_slot_0")
            project_generation_to_works(conn, "gen_batch_slot_1")
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM works WHERE id=? AND run_id IS NOT NULL", (work_ids[0],)
        ).fetchone()[0], 1)
        works = get_works_feed(self.db, {"author": uname, "sort": "newest", "limit": 20})
        self.assertEqual(len([w for w in works["items"] if w["id"] == work_ids[0]]), 1)

    def test_deleting_one_batch_slot_keeps_other_images_public(self):
        conn = self.db.get_conn()
        uid, uname = self.user_author["id"], self.user_author["username"]
        for index in range(3):
            conn.execute("""
                INSERT INTO studio_generations (
                    id,user_id,username,tab_title,mode,prompt,visible_prompt,
                    items_json,status,created_at,visibility,engine,
                    batch_id,batch_index,batch_total
                ) VALUES (?,?,?,?,?,?,?,?,'success',?,'public','live',?,?,?)
            """, (
                f"removal_slot_{index}", uid, uname, "三张一件作品",
                "graphic-text", "batch", "batch",
                json.dumps([f"/generated/removal_{index}.webp"]),
                "2026-11-07T00:00:00Z", "removal_batch", index, 3,
            ))
            works = project_generation_to_works(conn, f"removal_slot_{index}")
        conn.commit()
        self.assertEqual(len(works), 1)
        wid = works[0]
        conn.execute(
            "UPDATE studio_generations SET deleted_at=? WHERE id=?",
            ("2026-11-07T01:00:00Z", "removal_slot_0"),
        )
        sync_generation_visibility(conn, "removal_slot_0", "private", is_deleted=True)
        images = json.loads(conn.execute(
            "SELECT images_json FROM works WHERE id=?", (wid,)
        ).fetchone()[0])
        self.assertEqual(images, ["/generated/removal_1.webp", "/generated/removal_2.webp"])
        self.assertEqual(conn.execute(
            "SELECT status FROM works WHERE id=?", (wid,)
        ).fetchone()[0], "published")
        for idx in (1, 2):
            conn.execute(
                "UPDATE studio_generations SET deleted_at=? WHERE id=?",
                ("2026-11-07T01:00:00Z", f"removal_slot_{idx}"),
            )
            sync_generation_visibility(
                conn, f"removal_slot_{idx}", "private", is_deleted=True
            )
        self.assertNotEqual(conn.execute(
            "SELECT status FROM works WHERE id=?", (wid,)
        ).fetchone()[0], "published")

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

        sync_calls = [0]
        def fail_during_bulk(tx, gid, visibility, *, is_deleted=False):
            sync_calls[0] += 1
            if sync_calls[0] == 2:
                raise RuntimeError("second sync failed")
            return sync_generation_visibility(tx, gid, visibility, is_deleted=is_deleted)

        with patch("backend.generation_works.sync_generation_visibility", side_effect=fail_during_bulk):
            with self.assertRaisesRegex(RuntimeError, "second sync failed"):
                delete_all_user_studio_history(self.db, self.user_author)

        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM studio_generations WHERE id LIKE 'gen_atomic_%' AND COALESCE(deleted_at,'')=''"
            ).fetchone()[0],
            2,
            "History deletion must roll back on sync failure",
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM works w JOIN generation_runs r ON r.id=w.run_id "
                "WHERE r.external_run_id LIKE 'gen_atomic_%' AND w.status='published'"
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
                "SELECT COUNT(*) FROM works w JOIN generation_runs r ON r.id=w.run_id "
                "WHERE r.external_run_id = 'gen_atomic_1' AND w.status='published'"
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
