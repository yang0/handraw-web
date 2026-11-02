"""Unit and integration tests for tipping works and free topics.

Covers Codex requirements:
1. Work tipping success: author receives 100%, works.tips and works.cheers increment.
2. Free topic tipping success: author receives 2 credits, tipper deducted 2 credits, ledgers aggregated.
3. Paid topic rejected: price > 0 returns 400 (paid_topic_no_tip).
4. Self-tipping rejected: author tipping own work/topic returns 400, admin/operator has no exception.
5. Inaccessible targets rejected: non-existent/unpublished target returns 404; invalid amount returns 400.
6. Idempotent request_id: duplicate submission does not double deduct or double credit.
7. tip_in notification sent exactly once: author gets notification, duplicate does not re-notify.
8. Attached like: tipping attaches a like if not liked; does not increment if already liked; repeat tip does not re-add like.
9. Bound work/resource topics: server determines binding; frontend action bar only has one tip button.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
import unittest

from backend.db import Database
from backend.server import init_database
from backend.services import (
    ServiceError,
    apply_wallet_delta,
    build_boot_payload,
    register_user,
    send_encourage_tip,
    toggle_user_like,
)


class TestEncourageTips(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tips.db"
        self.db = init_database(self.db_path)

        # Register users
        self.u_author, _ = register_user(self.db, "author_user", "Pass123!Safe")
        self.u_tipper, _ = register_user(self.db, "tipper_user", "Pass123!Safe")
        self.u_admin, _ = register_user(self.db, "admin_user", "Pass123!Safe")

        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.u_admin["id"],))
            # Give tipper and admin plenty of credits
            apply_wallet_delta(tx, int(self.u_tipper["id"]), 100, "recharge", "Initial test credits")
            apply_wallet_delta(tx, int(self.u_admin["id"]), 100, "recharge", "Initial test credits")

            now_iso = "2026-11-02T00:00:00Z"
            # Create test work
            tx.execute(
                """
                INSERT INTO works (id, title, author_username, author_name, prompt, styles_json, status, likes, favorites, cheers, tips, price, published_at_ms, created_at, updated_at)
                VALUES ('w_test_01', '测试作品一', 'author_user', '作者名', '真实作品提示词', '["FA-001"]', 'published', 5, 2, 10, 0, 0, 1700000000000, ?, ?)
                """,
                (now_iso, now_iso),
            )

            # Create free topic
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, status, likes, favorites, published_at_ms, images_json, styles_json, summary, created_at, updated_at)
                VALUES ('t_free_01', 'tuning', '技术调优', '免费讨论帖', 'author_user', '作者名', 0, 'published', 3, 1, 1700000000000, '[]', '[]', '免费帖摘要', ?, ?)
                """,
                (now_iso, now_iso),
            )

            # Create paid topic
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, status, likes, favorites, published_at_ms, images_json, styles_json, summary, created_at, updated_at)
                VALUES ('t_paid_01', 'experience', '经验分享', '干货付费帖', 'author_user', '作者名', 15, 'published', 2, 0, 1700000000000, '[]', '[]', '付费帖摘要', ?, ?)
                """,
                (now_iso, now_iso),
            )

            # Create unpublished topic
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, status, likes, favorites, published_at_ms, images_json, styles_json, summary, created_at, updated_at)
                VALUES ('t_draft_01', 'tuning', '技术调优', '草稿帖', 'author_user', '作者名', 0, 'draft', 0, 0, 1700000000000, '[]', '[]', '草稿帖摘要', ?, ?)
                """,
                (now_iso, now_iso),
            )

            # Create bound work topic
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, status, likes, favorites, published_at_ms, images_json, styles_json, work_id, summary, created_at, updated_at)
                VALUES ('t_work_mapped_01', 'assets', '资源交流', '绑定作品的讨论帖', 'author_user', '作者名', 0, 'published', 5, 2, 1700000000000, '[]', '[]', 'w_test_01', '绑定作品帖摘要', ?, ?)
                """,
                (now_iso, now_iso),
            )
            tx.execute(
                """
                INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
                VALUES ('work', 'w_test_01', 't_work_mapped_01', 'submission', '2026-11-02T00:00:00Z')
                """
            )

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_01_work_tip_success(self):
        """1. Works can be tipped, author receives 100%, works.tips and cheers increment."""
        tipper = dict(self.u_tipper)
        author = dict(self.u_author)

        conn = self.db.get_conn()
        tipper_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (tipper["id"],)).fetchone()["balance"])
        author_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (author["id"],)).fetchone()["balance"])

        res = send_encourage_tip(self.db, tipper, "work", "w_test_01", amount=5)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("amount"), 5)

        tipper_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (tipper["id"],)).fetchone()["balance"])
        author_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (author["id"],)).fetchone()["balance"])
        self.assertEqual(tipper_bal_before - tipper_bal_after, 5)
        self.assertEqual(author_bal_after - author_bal_before, 5)

        w_row = conn.execute("SELECT tips, cheers, likes FROM works WHERE id = 'w_test_01'").fetchone()
        self.assertEqual(int(w_row["tips"]), 5)
        self.assertEqual(int(w_row["cheers"]), 10 + 3)
        self.assertEqual(int(w_row["likes"]), 5 + 1)  # Attached like

    def test_02_free_topic_tip_success(self):
        """2. Free topic tip fixed at 2 credits, 100% to author, tips aggregated from ledgers."""
        tipper = dict(self.u_tipper)
        author = dict(self.u_author)

        conn = self.db.get_conn()
        tipper_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (tipper["id"],)).fetchone()["balance"])
        author_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (author["id"],)).fetchone()["balance"])

        res = send_encourage_tip(self.db, tipper, "topic", "t_free_01", amount=2)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("amount"), 2)

        tipper_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (tipper["id"],)).fetchone()["balance"])
        author_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (author["id"],)).fetchone()["balance"])
        self.assertEqual(tipper_bal_before - tipper_bal_after, 2)
        self.assertEqual(author_bal_after - author_bal_before, 2)

        # Check attached like
        t_row = conn.execute("SELECT likes FROM forum_topics WHERE id = 't_free_01'").fetchone()
        self.assertEqual(int(t_row["likes"]), 3 + 1)

        # Check ledger aggregation
        ledger_sum = conn.execute(
            "SELECT COALESCE(SUM(delta), 0) FROM ledgers WHERE kind = 'tip_in' AND ref_type = 'topic' AND ref_id = 't_free_01'"
        ).fetchone()[0]
        self.assertEqual(int(ledger_sum), 2)

        # Check boot payload topic serialization
        boot = build_boot_payload(self.db, None)
        serialized = next((t for t in boot["topics"] if t["id"] == "t_free_01"), None)
        self.assertIsNotNone(serialized)
        self.assertEqual(serialized["tips"], 2)

    def test_03_paid_topic_rejected(self):
        """3. Paid topics (price > 0) cannot be tipped and return 400."""
        with self.assertRaises(ServiceError) as ctx:
            send_encourage_tip(self.db, self.u_tipper, "topic", "t_paid_01", amount=2)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "paid_topic_no_tip")

    def test_04_self_tip_rejected_admin_no_exception(self):
        """4. Authors cannot tip themselves; admin/operator has no exception."""
        # Normal author self-tip
        with self.assertRaises(ServiceError) as ctx:
            send_encourage_tip(self.db, self.u_author, "topic", "t_free_01", amount=2)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "self_tip_not_allowed")

        with self.assertRaises(ServiceError) as ctx:
            send_encourage_tip(self.db, self.u_author, "work", "w_test_01", amount=2)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "self_tip_not_allowed")

        # Admin self-tip on their own post
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, status, likes, favorites, published_at_ms, images_json, styles_json, summary, created_at, updated_at)
                VALUES ('t_admin_01', 'tuning', '技术调优', '管理员的帖子', 'admin_user', '管理员', 0, 'published', 0, 0, 1700000000000, '[]', '[]', '管理员帖子摘要', '2026-11-02T00:00:00Z', '2026-11-02T00:00:00Z')
                """
            )
        with self.assertRaises(ServiceError) as ctx:
            send_encourage_tip(self.db, self.u_admin, "topic", "t_admin_01", amount=2)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "self_tip_not_allowed")

    def test_05_inaccessible_target_and_invalid_amount(self):
        """5. Inaccessible targets return 404; non-2 amount for topics returns 400."""
        # Non-existent target
        with self.assertRaises(ServiceError) as ctx:
            send_encourage_tip(self.db, self.u_tipper, "topic", "t_non_existent", amount=2)
        self.assertEqual(ctx.exception.status, 404)

        # Unpublished topic
        with self.assertRaises(ServiceError) as ctx:
            send_encourage_tip(self.db, self.u_tipper, "topic", "t_draft_01", amount=2)
        self.assertEqual(ctx.exception.status, 404)

        # Invalid amount for topic (must be 2)
        with self.assertRaises(ServiceError) as ctx:
            send_encourage_tip(self.db, self.u_tipper, "topic", "t_free_01", amount=5)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "invalid_tip_amount")

    def test_06_idempotent_request_id(self):
        """6. Repeated request with identical request_id only settles once."""
        conn = self.db.get_conn()
        tipper_bal_start = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.u_tipper["id"],)).fetchone()["balance"])
        author_bal_start = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.u_author["id"],)).fetchone()["balance"])

        req_id = "req_tip_test_unique_12345"

        # First attempt -> succeeds
        res1 = send_encourage_tip(self.db, self.u_tipper, "topic", "t_free_01", amount=2, request_id=req_id)
        self.assertTrue(res1.get("ok"))
        self.assertFalse(res1.get("duplicate", False))

        tipper_bal_mid = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.u_tipper["id"],)).fetchone()["balance"])
        author_bal_mid = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.u_author["id"],)).fetchone()["balance"])
        self.assertEqual(tipper_bal_start - tipper_bal_mid, 2)
        self.assertEqual(author_bal_mid - author_bal_start, 2)

        # Second attempt with same request_id -> returns duplicate without second deduction/credit
        res2 = send_encourage_tip(self.db, self.u_tipper, "topic", "t_free_01", amount=2, request_id=req_id)
        self.assertTrue(res2.get("ok"))
        self.assertTrue(res2.get("duplicate"))

        tipper_bal_end = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.u_tipper["id"],)).fetchone()["balance"])
        author_bal_end = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.u_author["id"],)).fetchone()["balance"])
        self.assertEqual(tipper_bal_end, tipper_bal_mid)
        self.assertEqual(author_bal_end, author_bal_mid)

    def test_07_tip_in_notification_sent_only_once(self):
        """7. Successful tip creates tip_in notification; duplicate submission does not re-notify."""
        conn = self.db.get_conn()
        author_id = int(self.u_author["id"])

        notif_before = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (author_id,)).fetchone()[0]

        req_id = "req_tip_notif_test_7788"
        send_encourage_tip(self.db, self.u_tipper, "topic", "t_free_01", amount=2, request_id=req_id)

        notifs_mid = conn.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC", (author_id,)).fetchall()
        self.assertEqual(len(notifs_mid) - notif_before, 1)
        latest_notif = dict(notifs_mid[0])
        self.assertEqual(latest_notif["kind"], "wallet")
        self.assertIn("赞赏鼓励", latest_notif["title"])

        # Repeat same request_id
        send_encourage_tip(self.db, self.u_tipper, "topic", "t_free_01", amount=2, request_id=req_id)
        notifs_end = conn.execute("SELECT * FROM notifications WHERE user_id = ?", (author_id,)).fetchall()
        self.assertEqual(len(notifs_end), len(notifs_mid))  # No new notification

    def test_08_attached_like_deduplication(self):
        """8. Attached like does not double count if already liked or on subsequent tips."""
        conn = self.db.get_conn()

        # Step 1: User explicitly likes the topic first
        toggle_user_like(self.db, self.u_tipper, "topic", "t_free_01")
        likes_after_user_like = int(conn.execute("SELECT likes FROM forum_topics WHERE id = 't_free_01'").fetchone()["likes"])
        self.assertEqual(likes_after_user_like, 4)  # Started at 3, toggled to 4

        # Step 2: User tips the topic
        send_encourage_tip(self.db, self.u_tipper, "topic", "t_free_01", amount=2, request_id="tip_step2")
        likes_after_tip = int(conn.execute("SELECT likes FROM forum_topics WHERE id = 't_free_01'").fetchone()["likes"])
        # Should NOT increment because already liked!
        self.assertEqual(likes_after_tip, 4)

        # Step 3: User tips again with different request_id
        send_encourage_tip(self.db, self.u_tipper, "topic", "t_free_01", amount=2, request_id="tip_step3")
        likes_after_tip2 = int(conn.execute("SELECT likes FROM forum_topics WHERE id = 't_free_01'").fetchone()["likes"])
        self.assertEqual(likes_after_tip2, 4)

    def test_09_bound_topic_routes_to_work_target(self):
        """9. Topic bound in curation_resource_topics automatically resolves to work target."""
        conn = self.db.get_conn()
        work_tips_before = int(conn.execute("SELECT tips FROM works WHERE id = 'w_test_01'").fetchone()["tips"])

        # Tip target_type='topic', target_id='t_work_mapped_01'
        res = send_encourage_tip(self.db, self.u_tipper, "topic", "t_work_mapped_01", amount=2)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("targetType"), "work")
        self.assertEqual(res.get("targetId"), "w_test_01")

        work_tips_after = int(conn.execute("SELECT tips FROM works WHERE id = 'w_test_01'").fetchone()["tips"])
        self.assertEqual(work_tips_after - work_tips_before, 2)


if __name__ == "__main__":
    unittest.main()
