"""Tests for unified reply storage, moderation, and ops scripts (Phase 1a)."""
from __future__ import annotations

import json
import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend import admin_services, resource_discussions, server, services
from ops import converge_asset_comments, converge_work_comments, ensure_resource_topics

IMG = "/images/individual/FA/FA-013.webp"


class UnifiedRepliesTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        self._env = patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test", "HANDRAW_DEMO_MODE": "0"})
        self._env.start()
        self.db = server.init_database(self.path)
        self.author, _ = services.register_user(self.db, "uni_author", "password-author")
        self.reader, _ = services.register_user(self.db, "uni_reader", "password-reader")
        self.admin, _ = services.register_user(self.db, "uni_admin", "password-admin")
        self.operator, _ = services.register_user(self.db, "uni_operator", "password-operator")
        self.db.get_conn().execute("UPDATE users SET role = 'admin' WHERE username = 'uni_admin'")
        self.db.get_conn().execute("UPDATE users SET role = 'operator' WHERE username = 'uni_operator'")
        self.db.get_conn().commit()
        self.admin = dict(self.db.get_conn().execute("SELECT * FROM users WHERE username = 'uni_admin'").fetchone())
        self.operator = dict(self.db.get_conn().execute("SELECT * FROM users WHERE username = 'uni_operator'").fetchone())

        # Publish a work
        published = services.publish_user_work(
            self.db,
            self.author,
            {"title": "测试作品", "prompt": "a prompt", "images": [IMG], "styles": ["FA-013"]},
        )
        self.work_id = published["workId"]
        self.work_topic_id = published["topicId"]

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self._env.stop()
        self.temp.cleanup()

    def test_comment_on_official_style_and_work_stored_in_forum_replies(self):
        """1. Comments on styles and works go to forum_replies, old tables unchanged."""
        conn = self.db.get_conn()
        ac_before = conn.execute("SELECT COUNT(*) FROM asset_comments").fetchone()[0]
        wc_before = conn.execute("SELECT COUNT(*) FROM work_comments").fetchone()[0]
        fr_before = conn.execute("SELECT COUNT(*) FROM forum_replies").fetchone()[0]

        # Comment on official style
        res_style = resource_discussions.comment(self.db, self.reader, "style", "FB-041", "画风很好用！")
        self.assertTrue(res_style["ok"])
        self.assertEqual(res_style["assetCode"], "FB-041")
        self.assertEqual(res_style["assetKind"], "style")
        self.assertEqual(res_style["comment"]["text"], "画风很好用！")
        self.assertEqual(res_style["comment"]["user"], self.reader["username"])
        self.assertIn("topicId", res_style)
        self.assertIn("replyId", res_style)

        # Comment on work
        res_work = resource_discussions.comment(self.db, self.reader, "work", self.work_id, "作品很赞！")
        self.assertTrue(res_work["ok"])
        self.assertIsNone(res_work["assetCode"])
        self.assertEqual(res_work["assetKind"], "work")
        self.assertEqual(res_work["comment"]["text"], "作品很赞！")
        self.assertEqual(res_work["comment"]["user"], self.reader["username"])
        self.assertEqual(res_work["topicId"], self.work_topic_id)

        # Check counts
        ac_after = conn.execute("SELECT COUNT(*) FROM asset_comments").fetchone()[0]
        wc_after = conn.execute("SELECT COUNT(*) FROM work_comments").fetchone()[0]
        fr_after = conn.execute("SELECT COUNT(*) FROM forum_replies").fetchone()[0]

        self.assertEqual(ac_before, ac_after, "asset_comments row count must not change")
        self.assertEqual(wc_before, wc_after, "work_comments row count must not change")
        self.assertEqual(fr_after, fr_before + 2, "forum_replies must contain both new comments")

        # Verify mapping is submission
        m_style = conn.execute(
            "SELECT origin FROM curation_resource_topics WHERE kind = 'style' AND target_id = 'FB-041'"
        ).fetchone()
        self.assertIsNotNone(m_style)
        self.assertEqual(m_style["origin"], "submission")

    def test_moderate_resource_replies_hide_and_delete(self):
        """2. Moderation can hide and delete resource topic replies in forum_replies."""
        res = resource_discussions.comment(self.db, self.reader, "style", "FB-041", "待审核内容")
        topic_id = res["topicId"]
        reply_id = res["replyId"]

        conn = self.db.get_conn()
        reply_row = conn.execute(
            "SELECT * FROM forum_replies WHERE id = ?", (reply_id,)
        ).fetchone()
        self.assertIsNotNone(reply_row)
        self.assertEqual(reply_row["status"], "published")

        # Hide reply via moderation
        mod_hide = services.forum_moderator_action(
            self.db,
            self.admin,
            {"topicId": topic_id, "replyId": reply_id, "action": "hide_reply", "reason": "违规隐藏"},
        )
        self.assertTrue(mod_hide["ok"])
        hidden_row = conn.execute(
            "SELECT status FROM forum_replies WHERE id = ?", (reply_id,)
        ).fetchone()
        self.assertEqual(hidden_row["status"], "hidden")

        # Delete reply via moderation
        mod_del = services.forum_moderator_action(
            self.db,
            self.admin,
            {"topicId": topic_id, "replyId": reply_id, "action": "delete_reply", "reason": "删除"},
        )
        self.assertTrue(mod_del["ok"])
        deleted_row = conn.execute(
            "SELECT 1 FROM forum_replies WHERE id = ?", (reply_id,)
        ).fetchone()
        self.assertIsNone(deleted_row)

    def test_converge_asset_comments_script(self):
        """3. converge_asset_comments: dry-run, apply, notification check, idempotency, failure handling."""
        conn = self.db.get_conn()
        tid = "topic_legacy_fa013"
        conn.execute(
            "INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES (?,'assets','画风与图型专区','FA-013·画风讨论','','资源讨论','', '[]', '[\"FA-013\"]', '', '', 'published', 1000, '刚刚', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (tid,),
        )
        conn.execute(
            "INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'FA-013', ?, 'official', '2026-01-01T00:00:00Z')",
            (tid,),
        )
        conn.execute(
            "INSERT INTO asset_comments (id, asset_code, asset_kind, author_username, author_name, text, status, time_label, created_at, status_actor_role) VALUES ('ac_legacy_1', 'FA-013', 'style', 'uni_reader', '读者', '旧评论1', 'published', '刚刚', '2026-01-01T00:00:00Z', '')"
        )
        conn.execute(
            "INSERT INTO asset_comments (id, asset_code, asset_kind, author_username, author_name, text, status, time_label, created_at, status_actor_role) VALUES ('ac_legacy_2', 'FA-013', 'style', 'uni_reader', '读者', '旧评论2(隐藏)', 'hidden', '刚刚', '2026-01-01T01:00:00Z', 'admin')"
        )
        conn.commit()

        # Dry run
        conn_raw = sqlite3.connect(str(self.path))
        conn_raw.row_factory = sqlite3.Row
        try:
            asset_todo, unmapped, work_todo, skipped = converge_asset_comments.plan(conn_raw)
            self.assertEqual(len(asset_todo), 2)
            cnt = conn_raw.execute("SELECT COUNT(*) FROM forum_replies WHERE legacy_source LIKE 'asset_comments:%'").fetchone()[0]
            self.assertEqual(cnt, 0)
        finally:
            conn_raw.close()

        # Check notifications count before apply
        notif_before = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]

        # Run apply
        ret = converge_asset_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Check notifications count after apply (must not trigger new notifications)
        notif_after = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        self.assertEqual(notif_before, notif_after, "Migration must not fire notification triggers")

        # Check forum_replies content, status, and status_actor_role (J4)
        r1 = conn.execute("SELECT * FROM forum_replies WHERE legacy_source = 'asset_comments:ac_legacy_1'").fetchone()
        self.assertIsNotNone(r1)
        self.assertEqual(r1["text"], "旧评论1")
        self.assertEqual(r1["status"], "published")
        self.assertEqual(r1["topic_id"], tid)

        r2 = conn.execute("SELECT * FROM forum_replies WHERE legacy_source = 'asset_comments:ac_legacy_2'").fetchone()
        self.assertIsNotNone(r2)
        self.assertEqual(r2["text"], "旧评论2(隐藏)")
        self.assertEqual(r2["status"], "hidden")
        self.assertEqual(r2["status_actor_role"], "admin")

        # Verify J4 governance: operator cannot re-publish admin-hidden comment
        with self.assertRaises(services.ServiceError):
            admin_services.admin_moderate_comment(
                self.db,
                self.operator,
                "asset_comment",
                r2["id"],
                "publish",
                "尝试恢复",
            )

        # Check origin flipped to submission
        origin = conn.execute("SELECT origin FROM curation_resource_topics WHERE kind = 'style' AND target_id = 'FA-013'").fetchone()["origin"]
        self.assertEqual(origin, "submission")

        # Run apply again: idempotent, no duplicates
        ret2 = converge_asset_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret2, 0)
        cnt2 = conn.execute("SELECT COUNT(*) FROM forum_replies WHERE legacy_source LIKE 'asset_comments:%'").fetchone()[0]
        self.assertEqual(cnt2, 2)

    def test_ensure_resource_topics_script(self):
        """4. ensure_resource_topics: all catalog items mapped, boot and stats unchanged."""
        boot_before = services.build_boot_payload(self.db, None)
        topics_count_before = len(boot_before["topics"])

        overview_before = admin_services.admin_get_dashboard(self.db, self.admin)
        admin_topics_total_before = overview_before["kpis"]["topicsTotal"]
        admin_topics_pub_before = overview_before["kpis"]["topicsPublished"]

        _, _, _, creators_before = services.compute_public_asset_counts_and_creators(self.db.get_conn())
        creator_stats_len_before = len(creators_before)

        # Dry run
        conn_raw = sqlite3.connect(str(self.path))
        conn_raw.row_factory = sqlite3.Row
        try:
            needed_assets, needed_works = ensure_resource_topics.plan(conn_raw)
            self.assertGreater(len(needed_assets), 500)
        finally:
            conn_raw.close()

        # Apply
        ret = ensure_resource_topics.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Verify all catalog resources have mapping
        catalog = resource_discussions.static_catalog()
        conn = self.db.get_conn()
        for code, item in list(catalog.items())[:20]:
            row = conn.execute(
                "SELECT origin FROM curation_resource_topics WHERE kind = ? AND (target_id = ? OR UPPER(target_id) = ?)",
                (item["kind"], code, code),
            ).fetchone()
            self.assertIsNotNone(row, f"Missing mapping for {code}")
            self.assertEqual(row["origin"], "submission")

        # Verify /api/boot topics count is unchanged (zero-reply resource topics are hidden)
        boot_after = services.build_boot_payload(self.db, None)
        self.assertEqual(len(boot_after["topics"]), topics_count_before)

        # Verify admin overview stats are unchanged
        overview_after = admin_services.admin_get_dashboard(self.db, self.admin)
        self.assertEqual(overview_after["kpis"]["topicsTotal"], admin_topics_total_before)
        self.assertEqual(overview_after["kpis"]["topicsPublished"], admin_topics_pub_before)

        # Verify creator stats are unchanged
        _, _, _, creators_after = services.compute_public_asset_counts_and_creators(conn)
        self.assertEqual(len(creators_after), creator_stats_len_before)

        # Second run: idempotent, creates 0
        ret2 = ensure_resource_topics.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret2, 0)

    def test_j2_dedup_and_author_deleted_work_retention(self):
        """J2: Works reuse existing topic; author-deleted work status is preserved; case-normalized."""
        conn = self.db.get_conn()

        # 1. Author-deleted work post
        del_work_id = "work_del_author_1"
        del_topic_id = "topic_del_author_1"
        now = services.utc_now_iso()
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', '已被作者删除的作品', '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'published', 1000, '刚刚', ?, ?)
            """,
            (del_work_id, now, now),
        )
        conn.execute(
            """
            INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, status_source, status_actor_role, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'showcase', '🎨 晒作品', '已被作者删除的作品', 'uni_author', '作者', '', '[]', '[]', '', ?, 'deleted', 'author', 'author', 1000, '刚刚', ?, ?)
            """,
            (del_topic_id, del_work_id, now, now),
        )
        conn.commit()

        # Run ensure_resource_topics
        ret = ensure_resource_topics.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Verify only ONE topic exists for this work
        topic_rows = conn.execute("SELECT * FROM forum_topics WHERE work_id = ?", (del_work_id,)).fetchall()
        self.assertEqual(len(topic_rows), 1)
        self.assertEqual(topic_rows[0]["id"], del_topic_id)
        # Verify status, status_source, status_actor_role remain deleted / author
        self.assertEqual(topic_rows[0]["status"], "deleted")
        self.assertEqual(topic_rows[0]["status_source"], "author")
        self.assertEqual(topic_rows[0]["status_actor_role"], "author")

        # 2. Case normalization: fb-041 and FB-041 only create 1 topic and 1 mapping
        conn.execute("INSERT OR IGNORE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'FB-041', 'topic_fb041_test', 'official', ?)", (now,))
        conn.commit()
        tid1 = resource_discussions.ensure_topic(conn, "style", "fb-041", {"name": "FB-041", "description": "test"})
        tid2 = resource_discussions.ensure_topic(conn, "style", "FB-041", {"name": "FB-041", "description": "test"})
        self.assertEqual(tid1, tid2)
        mappings = conn.execute("SELECT * FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'FB-041'").fetchall()
        self.assertEqual(len(mappings), 1)

    def test_j3_savepoint_and_partial_failure_recovery(self):
        """J3: Existing mapping origin is not flipped early; partial failure keeps origin unchanged until full fix."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        # Create an official mapping
        conn.execute(
            "INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'TST-999', 'topic_tst999', 'official', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES ('topic_tst999','assets','画风与图型专区','TST-999','','资源讨论','', '[]', '[\"TST-999\"]', '', '', 'published', 1000, '刚刚', ?, ?)",
            (now, now),
        )
        # Ensure topic call must not flip origin to submission
        tid = resource_discussions.ensure_topic(conn, "style", "TST-999", {"name": "TST-999"})
        self.assertEqual(tid, "topic_tst999")
        m_row = conn.execute("SELECT origin FROM curation_resource_topics WHERE target_id = 'TST-999'").fetchone()
        self.assertEqual(m_row["origin"], "official", "ensure_topic must NOT flip existing origin")

        # Insert 3 comments into asset_comments
        conn.execute("INSERT INTO asset_comments (id, asset_code, asset_kind, author_username, author_name, text, status, time_label, created_at) VALUES ('ac_tst_1', 'TST-999', 'style', 'uni_reader', '读者', '文本1', 'published', '刚刚', ?)", (now,))
        conn.execute("INSERT INTO asset_comments (id, asset_code, asset_kind, author_username, author_name, text, status, time_label, created_at) VALUES ('ac_tst_2', 'TST-999', 'style', 'uni_reader', '读者', '文本2', 'published', '刚刚', ?)", (now,))
        conn.execute("INSERT INTO asset_comments (id, asset_code, asset_kind, author_username, author_name, text, status, time_label, created_at) VALUES ('ac_tst_3', 'TST-999', 'style', 'uni_reader', '读者', '文本3', 'published', '刚刚', ?)", (now,))
        conn.commit()

        # Inject failure on comment 2 by inserting a duplicate reply id or triggering a mock error in apply
        todo, unmapped, work_todo, skipped = converge_asset_comments.plan(conn)
        self.assertEqual(len(todo), 3)

        # Pre-insert a colliding forum_replies record with invalid data or let's corrupt ac_tst_2 in todo
        corrupted_todo = [dict(t) for t in todo]
        # Make item 1 fail by pointing to a nonexistent topic_id with foreign key enabled
        corrupted_todo[1]["topicId"] = "nonexistent_topic_foreign_key_fail"

        copied, failures = converge_asset_comments.apply(conn, corrupted_todo, unmapped, work_todo)
        self.assertEqual(copied, 2)
        self.assertEqual(len(failures), 1)

        # Because 1 failed, mapping origin must still be 'official'!
        m_check = conn.execute("SELECT origin FROM curation_resource_topics WHERE target_id = 'TST-999'").fetchone()
        self.assertEqual(m_check["origin"], "official")

        # Now fix the failure and rerun
        copied2, failures2 = converge_asset_comments.apply(conn, todo, unmapped, work_todo)
        self.assertEqual(copied2, 1)  # only the remaining 1 copied
        self.assertEqual(len(failures2), 0)

        # Now origin must be flipped to 'submission'!
        m_fixed = conn.execute("SELECT origin FROM curation_resource_topics WHERE target_id = 'TST-999'").fetchone()
        self.assertEqual(m_fixed["origin"], "submission")

    def test_j5_wal_backup_verification(self):
        """J5: SQLite Backup API accurately captures uncheckpointed WAL data and verifies."""
        conn = self.db.get_conn()
        conn.execute("PRAGMA journal_mode=WAL")
        wal_tid = "topic_wal_uncheckpointed_1"
        now = services.utc_now_iso()
        conn.execute(
            "INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES (?,'assets','画风与图型专区','WAL测试','','资源讨论','', '[]', '[]', '', '', 'published', 1000, '刚刚', ?, ?)",
            (wal_tid, now, now),
        )
        conn.commit()

        # Backup through backup function
        bak_file = converge_asset_comments.backup(conn, self.path)
        self.assertTrue(bak_file.is_file())

        # Verify uncheckpointed data exists in backup
        verify_conn = sqlite3.connect(str(bak_file))
        try:
            row = verify_conn.execute("SELECT id FROM forum_topics WHERE id = ?", (wal_tid,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], wal_tid)
        finally:
            verify_conn.close()
            bak_file.unlink(missing_ok=True)

    def test_j12_community_vs_official_notifications(self):
        """J12: Community asset replies notify asset author (+1); official asset replies send 0 notifications."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()

        # Create a community style
        conn.execute(
            """
            INSERT INTO catalog_assets (code, kind, name, description, image_url, author_username, author_name, source_type, status, unlock_cost, published_at_ms, created_at, updated_at)
            VALUES ('CMM-001', 'style', '社区自定义画风', '描述', '/images/test.webp', 'uni_author', '作者', 'community', 'published', 0, 1000, ?, ?)
            """,
            (now, now),
        )
        conn.commit()

        notif_author_before = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (self.author["id"],)).fetchone()[0]

        # Reader comments on community style
        res_cmm = resource_discussions.comment(self.db, self.reader, "style", "CMM-001", "很棒的社区画风！")
        self.assertTrue(res_cmm["ok"])

        notif_author_after = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (self.author["id"],)).fetchone()[0]
        self.assertEqual(notif_author_after, notif_author_before + 1, "Community asset author must receive +1 notification")

        # Reader comments on official style FB-041
        notif_all_before = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        res_off = resource_discussions.comment(self.db, self.reader, "style", "FB-041", "官方画风测试")
        self.assertTrue(res_off["ok"])
        notif_all_after = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        self.assertEqual(notif_all_after, notif_all_before, "Official asset comment must not generate notifications")

    def test_k2_migrated_status_and_delete_idempotency(self):
        """K2: Migrated comments marked status='migrated'; deleted reply does not re-publish or appear in admin."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        conn.execute("INSERT OR IGNORE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'MIG-01', 'topic_mig01', 'official', ?)", (now,))
        conn.execute("INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES ('topic_mig01','assets','画风与图型专区','MIG-01','','资源讨论','', '[]', '[\"MIG-01\"]', '', '', 'published', 1000, '刚刚', ?, ?)", (now, now))
        conn.execute("INSERT INTO asset_comments (id, asset_code, asset_kind, author_username, author_name, text, status, time_label, created_at) VALUES ('ac_mig_1', 'MIG-01', 'style', 'uni_reader', '读者', '即将迁移的内容', 'published', '刚刚', ?)", (now,))
        conn.commit()

        # Run migration
        ret = converge_asset_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Verify old row status is 'migrated'
        old_st = conn.execute("SELECT status FROM asset_comments WHERE id = 'ac_mig_1'").fetchone()[0]
        self.assertEqual(old_st, "migrated")

        # Now simulate admin physically deleting this reply from forum_replies
        rep = conn.execute("SELECT id FROM forum_replies WHERE legacy_source = 'asset_comments:ac_mig_1'").fetchone()
        self.assertIsNotNone(rep)
        conn.execute("DELETE FROM forum_replies WHERE id = ?", (rep[0],))
        conn.commit()

        # Re-run migration script
        ret2 = converge_asset_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret2, 0)

        # Assert no new reply was created
        rep_again = conn.execute("SELECT COUNT(*) FROM forum_replies WHERE legacy_source = 'asset_comments:ac_mig_1'").fetchone()[0]
        self.assertEqual(rep_again, 0, "Deleted migrated comment must not be re-published")

        # Assert old comment does not appear in admin moderation comments list
        comments_list = admin_services.admin_list_comments(self.db, self.admin)
        mig_in_admin = [c for c in comments_list["items"] if c["id"] == "ac_mig_1"]
        self.assertEqual(len(mig_in_admin), 0, "Migrated old comment must not appear in admin list")

    def test_k3_unmapped_work_comment_migration(self):
        """K3: Works without mapping migrate unmigrated comments by matching topic or creating one."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        wid = "work_unmapped_k3"
        tid = "topic_work_k3_existing"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', '无映射有讨论帖作品', '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'published', 1000, '刚刚', ?, ?)
            """,
            (wid, now, now),
        )
        conn.execute(
            """
            INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'showcase', '🎨 晒作品', '无映射有讨论帖作品', 'uni_author', '作者', '', '[]', '[]', '', ?, 'published', 1000, '刚刚', ?, ?)
            """,
            (tid, wid, now, now),
        )
        conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES ('wc_k3_1', ?, 'uni_reader', '读者', '旧评论K3', 'published', '刚刚', ?)", (wid, now))
        conn.commit()

        # Run work migration
        ret = converge_work_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Comment must be in forum_replies mapped to tid
        rep = conn.execute("SELECT * FROM forum_replies WHERE legacy_source = 'work_comments:wc_k3_1'").fetchone()
        self.assertIsNotNone(rep)
        self.assertEqual(rep["topic_id"], tid)
        self.assertEqual(rep["text"], "旧评论K3")

        # Mapping must be created and set to submission
        m = conn.execute("SELECT origin, topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (wid,)).fetchone()
        self.assertIsNotNone(m)
        self.assertEqual(m["origin"], "submission")
        self.assertEqual(m["topic_id"], tid)

    def test_k4_lowercase_mapping_new_comment_no_dup(self):
        """K4: Pre-existing lowercase mapping queried with uppercase comment reuses topic without duplicate."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        tid = "topic_k4_lower"
        conn.execute(
            """
            INSERT INTO catalog_assets (code, kind, name, description, image_url, author_username, author_name, source_type, status, unlock_cost, published_at_ms, created_at, updated_at)
            VALUES ('K4-001', 'style', '画风K4', '', '/images/test.webp', '', '', 'official', 'published', 0, 1000, ?, ?)
            """,
            (now, now),
        )
        conn.execute("INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES (?,'assets','画风与图型专区','K4-001','','资源讨论','', '[]', '[\"K4-001\"]', '', '', 'published', 1000, '刚刚', ?, ?)", (tid, now, now))
        conn.execute("INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'k4-001', ?, 'submission', ?)", (tid, now))
        conn.commit()

        # Comment on uppercase K4-001
        res = resource_discussions.comment(self.db, self.reader, "style", "K4-001", "测试大小写复用")
        self.assertEqual(res["topicId"], tid)

        # Assert only 1 mapping exists
        mappings = conn.execute("SELECT * FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'K4-001'").fetchall()
        self.assertEqual(len(mappings), 1)

    def test_k5_failure_exit_code_and_origin(self):
        """K5: Migration returns non-zero exit code when failures occur; mapping remains non-submission."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        conn.execute("INSERT OR IGNORE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'FAIL-01', 'topic_fail01', 'official', ?)", (now,))
        conn.execute("INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES ('topic_fail01','assets','画风与图型专区','FAIL-01','','资源讨论','', '[]', '[\"FAIL-01\"]', '', '', 'published', 1000, '刚刚', ?, ?)", (now, now))
        conn.execute("INSERT INTO asset_comments (id, asset_code, asset_kind, author_username, author_name, text, status, time_label, created_at) VALUES ('ac_fail_1', 'FAIL-01', 'style', 'uni_reader', '读者', '文本', 'published', '刚刚', ?)", (now,))
        conn.commit()

        todo, unmapped, work_todo, _ = converge_asset_comments.plan(conn)
        item_fail = [t for t in todo if t["legacySource"] == "asset_comments:ac_fail_1"][0]
        # Make it point to an invalid foreign key topic
        item_fail["topicId"] = "invalid_fk_topic"

        copied, failures = converge_asset_comments.apply(conn, [item_fail], unmapped, [])
        self.assertEqual(copied, 0)
        self.assertGreater(len(failures), 0)

        # Origin must remain 'official'
        m = conn.execute("SELECT origin FROM curation_resource_topics WHERE target_id = 'FAIL-01'").fetchone()
        self.assertEqual(m["origin"], "official")

    def test_k6_non_submission_mapping_comments_read(self):
        """K6: resource_comments and _thread_block read forum_replies for any mapped topic regardless of origin."""
        from backend import forum_resources
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        tid = "topic_k6_off"
        conn.execute(
            """
            INSERT INTO catalog_assets (code, kind, name, description, image_url, author_username, author_name, source_type, status, unlock_cost, published_at_ms, created_at, updated_at)
            VALUES ('K6-001', 'style', '画风K6', '', '/images/test.webp', '', '', 'official', 'published', 0, 1000, ?, ?)
            """,
            (now, now),
        )
        conn.execute("INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES (?,'assets','画风与图型专区','K6-001','','资源讨论','', '[]', '[\"K6-001\"]', '', '', 'published', 1000, '刚刚', ?, ?)", (tid, now, now))
        conn.execute("INSERT OR IGNORE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'K6-001', ?, 'official', ?)", (tid, now))
        conn.execute("INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, mounted_style, mounted_layout, likes, accepted, status, time_label, created_at) VALUES ('rep_k6_1', ?, 'uni_reader', '读者', '非submission回复', '', '', 0, 0, 'published', '刚刚', ?)", (tid, now))
        conn.commit()

        # 1. resource_comments
        res = forum_resources.resource_comments(self.db, self.reader, "style", "K6-001")
        self.assertEqual(res["total"], 1)
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(res["items"][0]["text"], "非submission回复")

        # 2. _thread_block
        t_row = conn.execute("SELECT * FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        block, _ = forum_resources._thread_block(conn, dict(t_row), "style", "K6-001")
        self.assertEqual(block["commentCount"], 1)

    def test_k7_resource_placeholder_vs_curation_submission_visibility(self):
        """K7: Placeholder topics hidden when 0 replies; appear in admin if hidden replies exist; submissions unaffected."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()

        # 1. Resource placeholder with 0 replies
        tid_ph = "topic_k7_placeholder"
        conn.execute(
            """
            INSERT INTO catalog_assets (code, kind, name, description, image_url, author_username, author_name, source_type, status, unlock_cost, published_at_ms, created_at, updated_at)
            VALUES ('PLC-01', 'style', '画风PLC', '', '/images/test.webp', '', '', 'official', 'published', 0, 1000, ?, ?)
            """,
            (now, now),
        )
        conn.execute("INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES (?,'assets','画风与图型专区','PLC-01','','资源讨论','', '[]', '[\"PLC-01\"]', '', '', 'published', 1000, '刚刚', ?, ?)", (tid_ph, now, now))
        conn.execute("INSERT OR IGNORE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'PLC-01', ?, 'submission', ?)", (tid_ph, now))
        conn.commit()

        # In boot: hidden
        boot = services.build_boot_payload(self.db, None)
        self.assertNotIn(tid_ph, [t["id"] for t in boot["topics"]])

        # In admin list: hidden (0 replies)
        adm_topics = admin_services.admin_list_topics(self.db, self.admin)
        self.assertNotIn(tid_ph, [t["id"] for t in adm_topics["items"]])

        # 2. Add 1 hidden reply to placeholder
        conn.execute("INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, mounted_style, mounted_layout, likes, accepted, status, time_label, created_at) VALUES ('rep_k7_hid', ?, 'uni_reader', '读者', '隐藏内容', '', '', 0, 0, 'hidden', '刚刚', ?)", (tid_ph, now))
        conn.commit()

        # In boot: still hidden (no published replies)
        boot2 = services.build_boot_payload(self.db, None)
        self.assertNotIn(tid_ph, [t["id"] for t in boot2["topics"]])

        # In admin list: visible (has replies for governance)
        adm_topics2 = admin_services.admin_list_topics(self.db, self.admin)
        self.assertIn(tid_ph, [t["id"] for t in adm_topics2["items"]])

        # 3. Add 1 published reply to placeholder
        conn.execute("INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, mounted_style, mounted_layout, likes, accepted, status, time_label, created_at) VALUES ('rep_k7_pub', ?, 'uni_reader', '读者', '公开内容', '', '', 0, 0, 'published', '刚刚', ?)", (tid_ph, now))
        conn.commit()

        # In boot: now visible!
        boot3 = services.build_boot_payload(self.db, None)
        self.assertIn(tid_ph, [t["id"] for t in boot3["topics"]])

        # 4. User curation submission topic (has curation_submissions row): 0 replies is visible
        tid_sub = "topic_k7_submission"
        conn.execute("INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES (?,'assets','画风与图型专区','SUB-01','uni_author','作者','', '[]', '[\"SUB-01\"]', '', '', 'published', 1000, '刚刚', ?, ?)", (tid_sub, now, now))
        conn.execute("INSERT OR IGNORE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'SUB-01', ?, 'submission', ?)", (tid_sub, now))
        conn.execute("INSERT INTO curation_submissions (id, topic_id, owner_username, owner_user_id, kind, target_id, status, current_revision, request_id, created_at, updated_at) VALUES ('sub_k7_1', ?, 'uni_author', 1, 'style', 'SUB-01', 'pending', 1, 'req_1', ?, ?)", (tid_sub, now, now))
        conn.execute("INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at) VALUES ('ver_k7_1', 'sub_k7_1', 1, '{}', ?)", (now,))
        conn.commit()

        boot4 = services.build_boot_payload(self.db, None)
        self.assertIn(tid_sub, [t["id"] for t in boot4["topics"]], "User submission topic must be visible even with 0 replies")

    def test_l1_legacy_comment_report_and_moderation(self):
        """L1: Reporting/moderating/deleting migrated comment by legacy ID affects forum_replies; legacy stays migrated."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        wid = "work_l1_test"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', 'L1作品', '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'published', 1000, '刚刚', ?, ?)
            """,
            (wid, now, now),
        )
        conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES ('wc_l1_1', ?, 'uni_reader', '读者', '旧评论L1', 'published', '刚刚', ?)", (wid, now))
        # File a report on this comment prior to migration
        conn.execute(
            """
            INSERT INTO reports (reporter_id, reporter_username, target_type, target_id, target_title, reason, detail, status, created_at)
            VALUES (?, ?, 'comment', 'wc_l1_1', '旧评论L1', '违规内容', '详情', 'open', ?)
            """,
            (self.reader["id"], self.reader["username"], now),
        )
        conn.commit()
        rep_id = conn.execute("SELECT id FROM reports WHERE target_id = 'wc_l1_1'").fetchone()[0]

        # Migrate
        ret = converge_work_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # After migration: old row is migrated, reply is published in forum_replies
        old_st = conn.execute("SELECT status FROM work_comments WHERE id = 'wc_l1_1'").fetchone()[0]
        self.assertEqual(old_st, "migrated")
        reply = conn.execute("SELECT id, status FROM forum_replies WHERE legacy_source = 'work_comments:wc_l1_1'").fetchone()
        self.assertIsNotNone(reply)
        self.assertEqual(reply["status"], "published")
        reply_id = reply["id"]

        # Admin resolves report with confirmed
        res_rep = admin_services.admin_resolve_report(self.db, self.admin, rep_id, "confirmed", "确认违规")
        self.assertTrue(res_rep["ok"])

        # 1. forum_replies row must become hidden with status_actor_role='admin'
        rep_after = conn.execute("SELECT status, status_actor_role FROM forum_replies WHERE id = ?", (reply_id,)).fetchone()
        self.assertEqual(rep_after["status"], "hidden")
        self.assertEqual(rep_after["status_actor_role"], "admin")

        # 2. work_comments row must remain 'migrated'
        old_st_after = conn.execute("SELECT status FROM work_comments WHERE id = 'wc_l1_1'").fetchone()[0]
        self.assertEqual(old_st_after, "migrated")

        # 3. Admin moderates by old ID to publish
        res_mod = admin_services.admin_moderate_comment(self.db, self.admin, "work_comment", "wc_l1_1", "publish", "误判恢复")
        self.assertTrue(res_mod["ok"])
        rep_pub = conn.execute("SELECT status, status_actor_role FROM forum_replies WHERE id = ?", (reply_id,)).fetchone()
        self.assertEqual(rep_pub["status"], "published")
        self.assertEqual(conn.execute("SELECT status FROM work_comments WHERE id = 'wc_l1_1'").fetchone()[0], "migrated")

        # 4. Author deletes by old ID
        res_del = admin_services.admin_moderate_comment(self.db, self.reader, "work_comment", "wc_l1_1", "delete", "作者删除")
        self.assertTrue(res_del["ok"])
        # Reply is deleted from forum_replies
        self.assertIsNone(conn.execute("SELECT id FROM forum_replies WHERE id = ?", (reply_id,)).fetchone())
        # Old row remains 'migrated'
        self.assertEqual(conn.execute("SELECT status FROM work_comments WHERE id = 'wc_l1_1'").fetchone()[0], "migrated")

    def test_l2_hidden_paused_deleted_works_inherit_governance_in_migration(self):
        """L2: Migrating works in hidden/paused/deleted without topics creates topics inheriting status and governance."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        works_data = [
            ("work_l2_hid", "hidden", "moderator", "admin", "违规隐藏"),
            ("work_l2_pau", "paused", "report", "moderator", "举报自动暂停"),
            ("work_l2_del", "deleted", "author", "author", "作者删除"),
        ]
        for wid, st, src, act, rsn in works_data:
            conn.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, status_source, status_actor_role, status_reason, published_at_ms, created_label, created_at, updated_at)
                VALUES (?, 'uni_author', '作者', ?, '[\"/images/l2_secret.webp\"]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'secret prompt', '', ?, ?, ?, ?, 1000, '刚刚', ?, ?)
                """,
                (wid, f"标题_{wid}", st, src, act, rsn, now, now),
            )
            conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES (?, ?, 'uni_reader', '读者', '旧评论', 'published', '刚刚', ?)", (f"wc_{wid}", wid, now))
        conn.commit()

        # Migrate
        ret = converge_work_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Verify created topics inherit governance
        for wid, st, src, act, rsn in works_data:
            m = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (wid,)).fetchone()
            self.assertIsNotNone(m)
            tid = m["topic_id"]
            tp = conn.execute("SELECT status, status_source, status_actor_role, status_reason FROM forum_topics WHERE id = ?", (tid,)).fetchone()
            self.assertEqual(tp["status"], st, f"{wid} topic status must match work status")
            self.assertEqual(tp["status_source"], "work")
            self.assertEqual(tp["status_actor_role"], act)

        # Anonymous boot must NOT contain any of these topics or secret images
        boot = services.build_boot_payload(self.db, None)
        boot_topic_ids = [t["id"] for t in boot["topics"]]
        for wid, _, _, _, _ in works_data:
            m = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (wid,)).fetchone()
            self.assertNotIn(m["topic_id"], boot_topic_ids)

        # Verify images don't leak in anonymous boot
        boot_images = json.dumps([t.get("images", []) for t in boot["topics"]])
        self.assertNotIn("/images/l2_secret.webp", boot_images)

    def test_l3_parity_and_community_asset_author_notification(self):
        """L3: Parity between ensure_resource_topics and converge_asset_comments; community assets notify author."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()

        # 1. Community asset without topic
        conn.execute(
            """
            INSERT INTO catalog_assets (code, kind, name, description, image_url, author_username, author_name, source_type, status, unlock_cost, published_at_ms, created_at, updated_at)
            VALUES ('CMM-L3', 'style', '社区画风L3', '清新淡雅', '/images/test.webp', 'uni_author', '社区作者', 'community', 'published', 0, 1000, ?, ?)
            """,
            (now, now),
        )
        conn.execute("INSERT INTO asset_comments (id, asset_code, asset_kind, author_username, author_name, text, status, time_label, created_at) VALUES ('ac_l3_1', 'CMM-L3', 'style', 'uni_reader', '读者', '旧评论', 'published', '刚刚', ?)", (now,))
        conn.commit()

        # Migrate asset comments first
        ret = converge_asset_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Check created topic author
        m = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'CMM-L3'").fetchone()
        self.assertIsNotNone(m)
        tid = m["topic_id"]
        tp = conn.execute("SELECT author_username, author_name FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertEqual(tp["author_username"], "uni_author")
        self.assertEqual(tp["author_name"], "社区作者")

        # Reader adds new comment on CMM-L3 -> author must receive notification +1
        notifs_before = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (self.author["id"],)).fetchone()[0]
        res_cm = resource_discussions.comment(self.db, self.reader, "style", "CMM-L3", "新回帖通知测试")
        self.assertTrue(res_cm["ok"])
        notifs_after = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (self.author["id"],)).fetchone()[0]
        self.assertEqual(notifs_after, notifs_before + 1)

    def test_l4_lowercase_only_normalization_and_read_parity(self):
        """L4: Normalization runs when only lowercase mappings remain; /t/, by-ref, and boot match."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()

        # Run ensure_resource_topics once to map everything
        ensure_resource_topics.main(["--db", str(self.path), "--apply"])

        # Now artificially inject a single lowercase-only mapping for FB-041
        tid_fb = "topic_fb041_test"
        conn.execute("DELETE FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'FB-041'")
        conn.execute("INSERT OR REPLACE INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES (?, 'assets', '画风与图型专区', 'FB-041讨论', '', '资源讨论', '', '[]', '[\"FB-041\"]', '', '', 'published', 1000, '刚刚', ?, ?)", (tid_fb, now, now))
        conn.execute("INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'fb-041', ?, 'submission', ?)", (tid_fb, now))
        conn.commit()

        # Run ensure_resource_topics: must not exit early, must normalize fb-041 to FB-041
        ret = ensure_resource_topics.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)
        row = conn.execute("SELECT target_id FROM curation_resource_topics WHERE kind = 'style' AND topic_id = ?", (tid_fb,)).fetchone()
        self.assertEqual(row["target_id"], "FB-041", "Mapping must be normalized to uppercase FB-041")

        # Add a published reply to topic
        conn.execute("INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, mounted_style, mounted_layout, likes, accepted, status, time_label, created_at) VALUES ('rep_l4_pub', ?, 'uni_reader', '读者', 'FB-041回复', '', '', 0, 0, 'published', '刚刚', ?)", (tid_fb, now))
        conn.commit()

        # Test read consistency across /t/, by-ref, and boot
        # 1. By-ref
        from backend.post_routes import _resolve_ref_to_topic_id
        resolved_t = _resolve_ref_to_topic_id(conn, "style-FB-041", None)
        self.assertEqual(resolved_t, tid_fb)

        # 2. Direct topic /t/
        resolved_direct = _resolve_ref_to_topic_id(conn, tid_fb, None)
        self.assertEqual(resolved_direct, tid_fb)

        # 3. Boot includes the topic and discussion
        boot = services.build_boot_payload(self.db, None)
        self.assertIn(tid_fb, [t["id"] for t in boot["topics"]])
        self.assertIn("FB-041", boot["discussions"])
        self.assertEqual(boot["discussions"]["FB-041"]["topicId"], tid_fb)

    def test_l5_official_resource_discussion_no_empty_username_creator(self):
        """L5: Official resource topic with public replies does not generate empty username creator."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        tid = "topic_l5_off"
        conn.execute("INSERT OR REPLACE INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES (?, 'assets', '画风与图型专区', '官方讨论', '', '资源讨论', '', '[]', '[\"FB-041\"]', '', '', 'published', 1000, '刚刚', ?, ?)", (tid, now, now))
        conn.execute("INSERT OR REPLACE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'FB-041', ?, 'submission', ?)", (tid, now))
        conn.execute("INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, mounted_style, mounted_layout, likes, accepted, status, time_label, created_at) VALUES ('rep_l5_pub', ?, 'uni_reader', '读者', '公开讨论内容', '', '', 0, 0, 'published', '刚刚', ?)", (tid, now))
        conn.commit()

        _, _, _, creators = services.compute_public_asset_counts_and_creators(conn)
        usernames = [c["username"] for c in creators]
        self.assertNotIn("", usernames, "Empty username must not appear in creator stats")

    def test_l6_admin_list_works_counts_migrated_and_forum_replies(self):
        """L6: admin_list_works correctly computes commentsCount for migrated works from forum_replies."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        wid = "work_l6_test"
        tid = "topic_l6_test"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', 'L6作品', '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'published', 1000, '刚刚', ?, ?)
            """,
            (wid, now, now),
        )
        conn.execute("INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, published_at_ms, created_label, created_at, updated_at) VALUES (?, 'showcase', '🎨 晒作品', 'L6作品', 'uni_author', '作者', '', '[]', '[]', '', ?, 'published', 1000, '刚刚', ?, ?)", (tid, wid, now, now))
        conn.execute("INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('work', ?, ?, 'submission', ?)", (wid, tid, now))
        # 3 published replies in forum_replies
        for i in range(3):
            conn.execute("INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, mounted_style, mounted_layout, likes, accepted, status, time_label, created_at) VALUES (?, ?, 'uni_reader', '读者', ?, '', '', 0, 0, 'published', '刚刚', ?)", (f"rep_l6_{i}", tid, f"回复_{i}", now))
        # 1 hidden reply in forum_replies (not counted)
        conn.execute("INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, mounted_style, mounted_layout, likes, accepted, status, time_label, created_at) VALUES ('rep_l6_hid', ?, 'uni_reader', '读者', '隐藏', '', '', 0, 0, 'hidden', '刚刚', ?)", (tid, now))
        conn.commit()

        res = admin_services.admin_list_works(self.db, self.admin)
        work_item = [w for w in res["items"] if w["id"] == wid][0]
        self.assertEqual(work_item["commentsCount"], 3, "Work commentsCount must count published forum_replies")

    def test_l7_plain_tuple_return_and_failure_list(self):
        """L7: converge_work_comments.apply returns a plain tuple (copied, failures)."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        wid = "work_l7_test"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', 'L7作品', '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'published', 1000, '刚刚', ?, ?)
            """,
            (wid, now, now),
        )
        conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES ('wc_l7_1', ?, 'uni_reader', '读者', '旧评论', 'published', '刚刚', ?)", (wid, now))
        conn.commit()

        todo = converge_work_comments.plan(conn)
        todo_item = [t for t in todo if t["workId"] == wid][0]
        res = converge_work_comments.apply(conn, [todo_item])

        # Assert res is exact tuple, not int subclass
        self.assertIs(type(res), tuple)
        self.assertEqual(len(res), 2)
        copied, failures = res
        self.assertEqual(copied, 1)
        self.assertEqual(failures, [])

    def test_m1_work_comment_deleted_reply_guard(self):
        """M1: Work comment where current reply in forum_replies was deleted cannot be republished or resurrected."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        wid = "work_m1_wc"
        cid = "wc_m1_1"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', 'M1作品', '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'published', 1000, '刚刚', ?, ?)
            """,
            (wid, now, now),
        )
        conn.execute(
            "INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES (?, ?, 'uni_reader', '读者', 'M1待删评论', 'published', '刚刚', ?)",
            (cid, wid, now),
        )
        conn.commit()

        # Migrate comment
        ret = converge_work_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Verify migrated in work_comments and reply created
        w_row = conn.execute("SELECT status FROM work_comments WHERE id = ?", (cid,)).fetchone()
        self.assertEqual(w_row["status"], "migrated")
        reply = conn.execute("SELECT id FROM forum_replies WHERE legacy_source = ?", (f"work_comments:{cid}",)).fetchone()
        self.assertIsNotNone(reply)
        reply_id = str(reply["id"])

        # Admin deletes the reply in forum_replies
        admin_services.admin_moderate_comment(self.db, self.admin, "forum_reply", reply_id, "delete")
        self.assertIsNone(conn.execute("SELECT 1 FROM forum_replies WHERE id = ?", (reply_id,)).fetchone())

        # Operator tries to publish using the legacy comment ID -> rejected with 409 comment_deleted
        with self.assertRaises(services.ServiceError) as cm:
            admin_services.admin_moderate_comment(self.db, self.operator, "work_comment", cid, "publish")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(getattr(cm.exception, "code", ""), "comment_deleted")

        # Admin also rejected if trying to publish
        with self.assertRaises(services.ServiceError) as cm:
            admin_services.admin_moderate_comment(self.db, self.admin, "work_comment", cid, "publish")
        self.assertEqual(cm.exception.status, 409)

        # Legacy row remains 'migrated'
        w_row_after = conn.execute("SELECT status FROM work_comments WHERE id = ?", (cid,)).fetchone()
        self.assertEqual(w_row_after["status"], "migrated")

        # Re-running migration must NOT resurrect it
        ret = converge_work_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)
        self.assertIsNone(conn.execute("SELECT 1 FROM forum_replies WHERE legacy_source = ?", (f"work_comments:{cid}",)).fetchone())

        # Calling hide or delete via legacy ID is idempotent and does not alter legacy row status
        h_res = admin_services.admin_moderate_comment(self.db, self.operator, "work_comment", cid, "hide")
        self.assertTrue(h_res.get("ok"))
        self.assertEqual(conn.execute("SELECT status FROM work_comments WHERE id = ?", (cid,)).fetchone()["status"], "migrated")

        d_res = admin_services.admin_moderate_comment(self.db, self.operator, "work_comment", cid, "delete")
        self.assertTrue(d_res.get("ok"))
        self.assertEqual(conn.execute("SELECT status FROM work_comments WHERE id = ?", (cid,)).fetchone()["status"], "migrated")

    def test_m1_asset_comment_deleted_reply_guard(self):
        """M1: Asset comment where current reply in forum_replies was deleted cannot be republished or resurrected."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        acode = "FB-M1AC"
        cid = "ac_m1_1"
        conn.execute(
            """
            INSERT INTO catalog_assets (code, kind, source_type, author_username, name, description, image_url, status, unlock_cost, published_at_ms, created_at, updated_at)
            VALUES (?, 'style', 'community', 'uni_author', 'M1画风', '测试', '/covers/m1.webp', 'published', 0, 1000, ?, ?)
            """,
            (acode, now, now),
        )
        conn.execute(
            "INSERT INTO asset_comments (id, asset_kind, asset_code, author_username, author_name, text, status, time_label, created_at) VALUES (?, 'style', ?, 'uni_reader', '读者', 'M1待删资源评论', 'published', '刚刚', ?)",
            (cid, acode, now),
        )
        conn.commit()

        # Migrate comment
        ret = converge_asset_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Verify migrated in asset_comments and reply created
        a_row = conn.execute("SELECT status FROM asset_comments WHERE id = ?", (cid,)).fetchone()
        self.assertEqual(a_row["status"], "migrated")
        reply = conn.execute("SELECT id FROM forum_replies WHERE legacy_source = ?", (f"asset_comments:{cid}",)).fetchone()
        self.assertIsNotNone(reply)
        reply_id = str(reply["id"])

        # Admin deletes reply in forum_replies
        admin_services.admin_moderate_comment(self.db, self.admin, "forum_reply", reply_id, "delete")
        self.assertIsNone(conn.execute("SELECT 1 FROM forum_replies WHERE id = ?", (reply_id,)).fetchone())

        # Operator tries to publish using legacy comment ID -> rejected with 409 comment_deleted
        with self.assertRaises(services.ServiceError) as cm:
            admin_services.admin_moderate_comment(self.db, self.operator, "asset_comment", cid, "publish")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(getattr(cm.exception, "code", ""), "comment_deleted")

        # Admin also rejected
        with self.assertRaises(services.ServiceError) as cm:
            admin_services.admin_moderate_comment(self.db, self.admin, "asset_comment", cid, "publish")
        self.assertEqual(cm.exception.status, 409)

        # Legacy row remains 'migrated'
        self.assertEqual(conn.execute("SELECT status FROM asset_comments WHERE id = ?", (cid,)).fetchone()["status"], "migrated")

        # Re-run migration: must NOT resurrect
        ret = converge_asset_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)
        self.assertIsNone(conn.execute("SELECT 1 FROM forum_replies WHERE legacy_source = ?", (f"asset_comments:{cid}",)).fetchone())

        # Hide and delete idempotent, legacy row stays migrated
        h_res = admin_services.admin_moderate_comment(self.db, self.operator, "asset_comment", cid, "hide")
        self.assertTrue(h_res.get("ok"))
        self.assertEqual(conn.execute("SELECT status FROM asset_comments WHERE id = ?", (cid,)).fetchone()["status"], "migrated")

        d_res = admin_services.admin_moderate_comment(self.db, self.operator, "asset_comment", cid, "delete")
        self.assertTrue(d_res.get("ok"))
        self.assertEqual(conn.execute("SELECT status FROM asset_comments WHERE id = ?", (cid,)).fetchone()["status"], "migrated")

    def test_m1_report_resolution_on_deleted_migrated_comment(self):
        """M1: Reports on migrated comments whose current reply was deleted can be resolved (confirmed/dismissed) without altering legacy row."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        wid = "work_m1_rep"
        cid1 = "wc_m1_rep1"
        cid2 = "wc_m1_rep2"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', 'M1举报测试', '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'published', 1000, '刚刚', ?, ?)
            """,
            (wid, now, now),
        )
        conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES (?, ?, 'uni_author', '作者', '举报评论1', 'published', '刚刚', ?)", (cid1, wid, now))
        conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES (?, ?, 'uni_author', '作者', '举报评论2', 'published', '刚刚', ?)", (cid2, wid, now))

        # Open reports before migration
        conn.execute(
            "INSERT INTO reports (reporter_id, reporter_username, target_type, target_id, target_title, reason, detail, status, created_at) VALUES (?, ?, 'comment', ?, '评论1', 'spam', '垃圾信息', 'open', ?)",
            (int(self.reader["id"]), self.reader["username"], cid1, now),
        )
        rep1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            "INSERT INTO reports (reporter_id, reporter_username, target_type, target_id, target_title, reason, detail, status, created_at) VALUES (?, ?, 'comment', ?, '评论2', 'spam', '垃圾信息', 'open', ?)",
            (int(self.reader["id"]), self.reader["username"], cid2, now),
        )
        rep2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        # Migrate
        ret = converge_work_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Delete the replies in forum_replies
        for cid in (cid1, cid2):
            conn.execute("DELETE FROM forum_replies WHERE legacy_source = ?", (f"work_comments:{cid}",))
        conn.commit()

        # Both legacy comments are 'migrated'
        self.assertEqual(conn.execute("SELECT status FROM work_comments WHERE id = ?", (cid1,)).fetchone()["status"], "migrated")
        self.assertEqual(conn.execute("SELECT status FROM work_comments WHERE id = ?", (cid2,)).fetchone()["status"], "migrated")

        # Resolve rep1 as confirmed
        res1 = admin_services.admin_resolve_report(self.db, self.admin, rep1_id, "confirmed", note="已核实")
        self.assertTrue(res1.get("ok"))
        self.assertEqual(res1.get("status"), "confirmed")
        # Legacy row MUST remain 'migrated'
        self.assertEqual(conn.execute("SELECT status FROM work_comments WHERE id = ?", (cid1,)).fetchone()["status"], "migrated")

        # Resolve rep2 as dismissed
        res2 = admin_services.admin_resolve_report(self.db, self.admin, rep2_id, "dismissed", note="无违规")
        self.assertTrue(res2.get("ok"))
        self.assertEqual(res2.get("status"), "dismissed")
        # Legacy row MUST remain 'migrated'
        self.assertEqual(conn.execute("SELECT status FROM work_comments WHERE id = ?", (cid2,)).fetchone()["status"], "migrated")

        # Re-running migration copies 0
        ret = converge_work_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM forum_replies WHERE legacy_source IN (?, ?)", (f"work_comments:{cid1}", f"work_comments:{cid2}")).fetchone()[0], 0)

    def test_m2_work_topic_mirror_semantics_and_lifecycle(self):
        """M2: Created topics for invisible works use status_source='work' mirror semantics and follow work restoration."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()

        # 1. Hidden work by admin: hidden/moderator/admin
        w_hid = "work_m2_hid"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, status_source, status_actor_role, status_reason, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', 'M2隐藏作品', '[\"/images/m2_hid.webp\"]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'hidden', 'moderator', 'admin', '运营违规隐藏', 1000, '刚刚', ?, ?)
            """,
            (w_hid, now, now),
        )
        conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES ('wc_m2_hid', ?, 'uni_reader', '读者', '旧评', 'published', '刚刚', ?)", (w_hid, now))

        # 2. Paused work by report/moderator: paused/report/moderator
        w_pau = "work_m2_pau"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, status_source, status_actor_role, status_reason, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', 'M2暂停作品', '[\"/images/m2_pau.webp\"]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'paused', 'report', 'moderator', '举报暂停', 1000, '刚刚', ?, ?)
            """,
            (w_pau, now, now),
        )
        conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES ('wc_m2_pau', ?, 'uni_reader', '读者', '旧评', 'published', '刚刚', ?)", (w_pau, now))

        # 3. Control 1: Pre-existing topic deleted by author: deleted/author
        w_del_ctrl = "work_m2_del_ctrl"
        t_del_ctrl = "topic_m2_del_ctrl"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, status_source, status_actor_role, status_reason, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', 'M2作者删除帖作品', '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'hidden', 'moderator', 'admin', '隐藏', 1000, '刚刚', ?, ?)
            """,
            (w_del_ctrl, now, now),
        )
        conn.execute(
            """
            INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, status_source, status_actor_role, status_reason, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'experience', '经验', '已删帖子', 'uni_author', '作者', '', '[]', '[]', '', ?, 'deleted', 'author', 'author', '作者删除', 1000, '刚刚', ?, ?)
            """,
            (t_del_ctrl, w_del_ctrl, now, now),
        )
        conn.execute("INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('work', ?, ?, 'work_mirror', ?)", (w_del_ctrl, t_del_ctrl, now))
        conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES ('wc_m2_del_ctrl', ?, 'uni_reader', '读者', '旧评', 'published', '刚刚', ?)", (w_del_ctrl, now))

        # 4. Control 2: Pre-existing topic independently hidden by moderator: hidden/moderator
        w_mod_ctrl = "work_m2_mod_ctrl"
        t_mod_ctrl = "topic_m2_mod_ctrl"
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status, status_source, status_actor_role, status_reason, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'uni_author', '作者', 'M2独立版主隐藏帖作品', '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'default', 0, 'prompt', '', 'hidden', 'moderator', 'admin', '隐藏', 1000, '刚刚', ?, ?)
            """,
            (w_mod_ctrl, now, now),
        )
        conn.execute(
            """
            INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, images_json, styles_json, layout_code, work_id, status, status_source, status_actor_role, status_reason, published_at_ms, created_label, created_at, updated_at)
            VALUES (?, 'experience', '经验', '独立版主隐藏帖子', 'uni_author', '作者', '', '[]', '[]', '', ?, 'hidden', 'moderator', 'operator', '帖子单聊违规', 1000, '刚刚', ?, ?)
            """,
            (t_mod_ctrl, w_mod_ctrl, now, now),
        )
        conn.execute("INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('work', ?, ?, 'work_mirror', ?)", (w_mod_ctrl, t_mod_ctrl, now))
        conn.execute("INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at) VALUES ('wc_m2_mod_ctrl', ?, 'uni_reader', '读者', '旧评', 'published', '刚刚', ?)", (w_mod_ctrl, now))

        conn.commit()

        # Run migration for w_hid and w_pau
        ret = converge_work_comments.main(["--db", str(self.path), "--apply"])
        self.assertEqual(ret, 0)

        # Check newly created topic for w_hid: status='hidden', status_source='work'
        m_hid = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (w_hid,)).fetchone()
        self.assertIsNotNone(m_hid)
        t_hid = m_hid["topic_id"]
        row_hid = conn.execute("SELECT status, status_source, status_actor_role, status_reason FROM forum_topics WHERE id = ?", (t_hid,)).fetchone()
        self.assertEqual(row_hid["status"], "hidden")
        self.assertEqual(row_hid["status_source"], "work")
        self.assertEqual(row_hid["status_actor_role"], "admin")
        self.assertEqual(row_hid["status_reason"], "运营违规隐藏")

        # Check newly created topic for w_pau: status='paused', status_source='work'
        m_pau = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (w_pau,)).fetchone()
        self.assertIsNotNone(m_pau)
        t_pau = m_pau["topic_id"]
        row_pau = conn.execute("SELECT status, status_source, status_actor_role, status_reason FROM forum_topics WHERE id = ?", (t_pau,)).fetchone()
        self.assertEqual(row_pau["status"], "paused")
        self.assertEqual(row_pau["status_source"], "work")

        # Verify not in anonymous boot
        boot_before = services.build_boot_payload(self.db, None)
        boot_topic_ids_before = {t["id"] for t in boot_before["topics"]}
        self.assertNotIn(t_hid, boot_topic_ids_before)
        self.assertNotIn(t_pau, boot_topic_ids_before)

        # Restore w_hid via admin_moderate_work("publish")
        admin_services.admin_moderate_work(self.db, self.admin, w_hid, "publish")
        # Topic status must follow to published!
        row_hid_restored = conn.execute("SELECT status, status_source FROM forum_topics WHERE id = ?", (t_hid,)).fetchone()
        self.assertEqual(row_hid_restored["status"], "published")
        self.assertEqual(row_hid_restored["status_source"], "")

        # Restore w_pau via admin_moderate_work("publish")
        admin_services.admin_moderate_work(self.db, self.admin, w_pau, "publish")
        row_pau_restored = conn.execute("SELECT status, status_source FROM forum_topics WHERE id = ?", (t_pau,)).fetchone()
        self.assertEqual(row_pau_restored["status"], "published")
        self.assertEqual(row_pau_restored["status_source"], "")

        # Under #60: unlisted restored works are reachable via discussions mapping,
        # but do not enter the forum list until listed_at_ms is set.
        boot_after = services.build_boot_payload(self.db, None)
        boot_topic_ids_after = {t["id"] for t in boot_after["topics"]}
        self.assertNotIn(t_hid, boot_topic_ids_after)
        self.assertNotIn(t_pau, boot_topic_ids_after)
        self.assertEqual(boot_after.get("discussions", {}).get(w_hid, {}).get("topicId"), t_hid)
        self.assertEqual(boot_after.get("discussions", {}).get(w_pau, {}).get("topicId"), t_pau)

        # Controls verification:
        # Restore w_del_ctrl:
        admin_services.admin_moderate_work(self.db, self.admin, w_del_ctrl, "publish")
        # Control 1 topic MUST stay deleted!
        row_del_ctrl = conn.execute("SELECT status, status_source FROM forum_topics WHERE id = ?", (t_del_ctrl,)).fetchone()
        self.assertEqual(row_del_ctrl["status"], "deleted")
        self.assertEqual(row_del_ctrl["status_source"], "author")

        # Restore w_mod_ctrl:
        admin_services.admin_moderate_work(self.db, self.admin, w_mod_ctrl, "publish")
        # Control 2 topic MUST stay hidden!
        row_mod_ctrl = conn.execute("SELECT status, status_source FROM forum_topics WHERE id = ?", (t_mod_ctrl,)).fetchone()
        self.assertEqual(row_mod_ctrl["status"], "hidden")
        self.assertEqual(row_mod_ctrl["status_source"], "moderator")


if __name__ == "__main__":
    unittest.main()
