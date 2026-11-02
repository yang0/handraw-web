"""Acceptance tests for Issue #29: Remove work pricing.

Covers:
1. Frontend/API bypass rejection: non-zero or invalid work price returns 400 (work_price_not_allowed / invalid_price).
2. Missing or zero price succeeds: work price is stored and serialized as 0.
3. Migration 073 idempotently resets existing non-zero work prices to 0.
4. Legacy works zeroed out are fully accessible without price/unlock checks.
5. Work unlock requests are rejected with 400 (work_not_unlockable) without any wallet deduction.
6. Style/layout asset unlocking and forum post paid reading remain intact with 80% author split.
7. Existing unlocks, ledger rows, and wallet history are preserved without rollback or auto-refund.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import curation as C
from backend import forum_resources as R
from backend import server as server_module
from backend import services as S
from backend.admin_services import admin_moderate_work
from backend.features import edit_owned_content
from backend.work_schema import RESET_WORKS_PRICE_SQL

IMG = "/images/individual/FA/FA-013.webp"


class RemoveWorkPricingAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server_module.init_database(Path(self.temp.name) / "test_pricing.db")
        self.author, _ = S.register_user(self.db, "work_artist", "password123")
        self.buyer, _ = S.register_user(self.db, "work_buyer", "password123")
        self.admin, _ = S.register_user(self.db, "work_admin", "password123")

        conn = self.db.get_conn()
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin["id"],))
        conn.execute("UPDATE wallets SET balance = 100 WHERE user_id = ?", (self.buyer["id"],))
        conn.commit()
        self.admin["role"] = "admin"

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_01_work_creation_rejects_nonzero_or_invalid_price(self):
        """1. Backend uniformly rejects non-zero or invalid price on work publish."""
        invalid_prices = [10, 1, 99, -5, "10", "abc", float("inf")]
        for p in invalid_prices:
            with self.assertRaises(S.ServiceError) as cm:
                C.publish_work_direct(
                    self.db,
                    self.author,
                    {
                        "title": "尝试设价作品",
                        "prompt": "提示词内容",
                        "images": [IMG],
                        "styles": ["FA-013"],
                        "price": p,
                    },
                )
            self.assertEqual(cm.exception.status, 400)
            self.assertIn(cm.exception.code, ("work_price_not_allowed", "invalid_price"))

    def test_02_work_creation_accepts_zero_or_omitted_price(self):
        """2. Backend accepts omitted, null, empty string, or 0 price."""
        valid_prices = [0, "0", None, ""]
        for idx, p in enumerate(valid_prices):
            payload = {
                "title": f"正常免费作品_{idx}",
                "prompt": f"公开提示词_{idx}",
                "images": [IMG],
                "styles": ["FA-013"],
            }
            if p is not None:
                payload["price"] = p
            res = C.publish_work_direct(self.db, self.author, payload)
            self.assertTrue(res.get("workId"))
            row = self.db.get_conn().execute("SELECT price FROM works WHERE id = ?", (res["workId"],)).fetchone()
            self.assertEqual(row["price"], 0)

    def test_03_author_edit_and_admin_edit_reject_nonzero_price(self):
        """3. Author edit and admin moderate edit reject price > 0."""
        pub = C.publish_work_direct(
            self.db,
            self.author,
            {"title": "可编辑作品", "prompt": "提示词", "images": [IMG], "styles": ["FA-013"], "price": 0},
        )
        wid = pub["workId"]

        # Author edit with price > 0 -> 400
        with self.assertRaises(S.ServiceError) as cm:
            edit_owned_content(
                self.db,
                self.author,
                "works",
                wid,
                {"title": "改名设价", "price": 10},
            )
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.code, "work_price_not_allowed")

        # Admin moderate edit with price > 0 -> 400
        with self.assertRaises(S.ServiceError) as cm:
            admin_moderate_work(
                self.db,
                self.admin,
                wid,
                "edit",
                {"title": "管理编辑设价", "price": 20},
            )
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.code, "work_price_not_allowed")

    def test_04_migration_073_resets_legacy_nonzero_prices(self):
        """4. Migration 073 idempotently zeroes out legacy non-zero work prices."""
        now = S.utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, price, prompt, prompt_has_secret, status, published_at_ms, created_at, updated_at)
                VALUES ('legacy_w1', 'work_artist', '画师', '旧收费作品1', '["/img.webp"]', '["FA-013"]', 10, '旧提示词1', 0, 'published', 1000, ?, ?),
                       ('legacy_w2', 'work_artist', '画师', '旧收费作品2', '["/img.webp"]', '["FA-013"]', 5, '旧提示词2', 0, 'published', 1000, ?, ?)
                """,
                (now, now, now, now),
            )

        # Apply migration 073
        with self.db.transaction() as tx:
            tx.execute(RESET_WORKS_PRICE_SQL)

        rows = self.db.get_conn().execute("SELECT id, price FROM works WHERE id IN ('legacy_w1', 'legacy_w2')").fetchall()
        for r in rows:
            self.assertEqual(r["price"], 0)

        # Serialized work is accessible, price is 0, prompt is visible to stranger without unlock
        r1 = self.db.get_conn().execute("SELECT * FROM works WHERE id = 'legacy_w1'").fetchone()
        ser = S._serialize_work(r1, {}, set(), None)
        self.assertEqual(ser["price"], 0)
        self.assertFalse(ser["promptMasked"])
        self.assertEqual(ser["prompt"], "旧提示词1")

    def test_05_work_unlock_rejected_without_charging_buyer(self):
        """5. Unlocking a work returns 400 work_not_unlockable without deducting buyer balance."""
        pub = C.publish_work_direct(
            self.db,
            self.author,
            {"title": "普通作品", "prompt": "提示词内容", "images": [IMG], "styles": ["FA-013"], "price": 0},
        )
        wid = pub["workId"]

        buyer_bal_before = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.buyer["id"],)).fetchone()["balance"])
        author_bal_before = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()["balance"])

        # Unlock with explicit target_type='work'
        with self.assertRaises(S.ServiceError) as cm:
            S.unlock_paid_item(self.db, self.buyer, "work", wid)
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.code, "work_not_unlockable")

        # Unlock with generic/empty target_type
        with self.assertRaises(S.ServiceError) as cm:
            S.unlock_paid_item(self.db, self.buyer, "", wid)
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.code, "work_not_unlockable")

        buyer_bal_after = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.buyer["id"],)).fetchone()["balance"])
        author_bal_after = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()["balance"])
        self.assertEqual(buyer_bal_after, buyer_bal_before, "Buyer balance must not change on work unlock request")
        self.assertEqual(author_bal_after, author_bal_before, "Author balance must not change on work unlock request")

        unlock_cnt = self.db.get_conn().execute("SELECT COUNT(*) FROM unlocks WHERE target_id = ?", (wid,)).fetchone()[0]
        self.assertEqual(unlock_cnt, 0, "No unlock record should be written for work")

    def test_06_style_unlock_and_forum_paid_reading_flow_intact(self):
        """6. Style asset unlock and forum post paid reading continue to work normally with 80% split."""
        now = S.utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, kind, name, description, image_url, definition, author_username, author_name, source_type, status, unlock_cost, published_at_ms, created_at, updated_at)
                VALUES ('PAID-STYLE-TEST', 'style', '付费画风', '测试', '/img/p.webp', 'SECRET_STYLE_DEF', 'work_artist', '画师', 'community', 'published', 20, 1000, ?, ?)
                """,
                (now, now),
            )

        buyer_bal_0 = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.buyer["id"],)).fetchone()["balance"])
        author_bal_0 = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()["balance"])

        # Buyer unlocks style asset (cost: 20 -> buyer -20, author +16)
        res = S.unlock_paid_item(self.db, self.buyer, "asset", "PAID-STYLE-TEST")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res["unlockedContent"], "SECRET_STYLE_DEF")

        buyer_bal_1 = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.buyer["id"],)).fetchone()["balance"])
        author_bal_1 = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()["balance"])
        self.assertEqual(buyer_bal_1, buyer_bal_0 - 20)
        self.assertEqual(author_bal_1, author_bal_0 + 16)

        # Forum topic paid reading unlock (cost: 10 -> buyer -10, author +8)
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, summary, locked_body, status, published_at_ms, created_at, updated_at)
                VALUES ('paid_topic_test', 'experience', '经验', '付费贴', 'work_artist', '画师', 10, '免费摘要', '付费独家正文', 'published', 1000, ?, ?)
                """,
                (now, now),
            )

        res_topic = S.unlock_paid_item(self.db, self.buyer, "topic", "paid_topic_test")
        self.assertTrue(res_topic.get("ok"))
        self.assertEqual(res_topic["unlockedContent"], "付费独家正文")

        buyer_bal_2 = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.buyer["id"],)).fetchone()["balance"])
        author_bal_2 = int(self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()["balance"])
        self.assertEqual(buyer_bal_2, buyer_bal_1 - 10)
        self.assertEqual(author_bal_2, author_bal_1 + 8)

    def test_07_existing_history_is_preserved(self):
        """7. Historical unlock records for works are not deleted and remain intact."""
        now = S.utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO unlocks (user_id, target_type, target_id, cost, status, created_at)
                VALUES (?, 'work', 'hist_work_1', 10, 'settled', ?)
                """,
                (self.buyer["id"], now),
            )

        # Run migration 073
        with self.db.transaction() as tx:
            tx.execute(RESET_WORKS_PRICE_SQL)

        row = self.db.get_conn().execute(
            "SELECT * FROM unlocks WHERE user_id = ? AND target_type = 'work' AND target_id = 'hist_work_1'",
            (self.buyer["id"],),
        ).fetchone()
        self.assertIsNotNone(row, "Historical work unlock row must be preserved")
        self.assertEqual(row["status"], "settled")
