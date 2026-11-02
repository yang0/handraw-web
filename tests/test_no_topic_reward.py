"""Tests for Issue #46: Cancel normal topic publish credit rewards.

Verifies:
1. Normal topic publish produces NO publish_topic ledger entry; wallet balance remains unchanged.
2. Bounty topic (bounty > 0) still escrows credits via bounty_escrow ledger entry, deducting balance.
3. Reply reward is untouched: +2 credits per reply, respecting reply_daily_cap (5).
4. Migration 075 idempotently sets site_settings.economy.topic_publish_credits to 0 on existing databases.
5. Admin settings update for economy enforces topic_publish_credits == 0.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server as server_module
from backend.admin_services import admin_update_settings
from backend.services import get_site_settings, publish_forum_reply_post, publish_forum_topic_post, register_user
from backend.work_schema import ZERO_TOPIC_PUBLISH_CREDITS_SQL, zero_topic_publish_credits_hook


class NoTopicRewardTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server_module.init_database(Path(self.temp.name) / "test_no_reward.db")
        self.author, _ = register_user(self.db, "test_author", "password123")
        self.admin, _ = register_user(self.db, "test_admin", "password123")

        conn = self.db.get_conn()
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin["id"],))
        conn.execute("UPDATE wallets SET balance = 100 WHERE user_id = ?", (self.author["id"],))
        conn.commit()
        self.admin["role"] = "admin"

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_01_normal_topic_publish_no_reward_no_ledger(self):
        """1. Publishing normal topic produces no publish_topic ledger entry, balance unchanged."""
        initial_balance = 100
        res = publish_forum_topic_post(
            self.db,
            self.author,
            {
                "title": "普通交流帖测试标题",
                "category": "tuning",
                "body": "这里是一篇用于测试的普通交流帖正文内容，没有任何积分奖励。",
                "bounty": 0,
                "price": 0,
            },
        )
        self.assertTrue(res.get("ok"))
        topic_id = res.get("topicId")
        self.assertTrue(topic_id)
        self.assertEqual(res.get("credits"), initial_balance)

        # Check wallet balance remains 100
        conn = self.db.get_conn()
        w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()
        self.assertEqual(int(w["balance"]), initial_balance)

        # Check ledgers: strictly NO publish_topic ledger entry
        ledgers = conn.execute(
            "SELECT * FROM ledgers WHERE user_id = ? AND kind = 'publish_topic'",
            (self.author["id"],),
        ).fetchall()
        self.assertEqual(len(ledgers), 0)

        # Check topic created in DB
        topic = conn.execute("SELECT * FROM forum_topics WHERE id = ?", (topic_id,)).fetchone()
        self.assertIsNotNone(topic)
        self.assertEqual(topic["bounty_status"], "none")
        self.assertEqual(topic["bounty"], 0)

    def test_02_bounty_topic_escrow_deducted_normally(self):
        """2. Publishing bounty topic deducts balance and creates bounty_escrow ledger entry."""
        initial_balance = 100
        bounty = 20
        res = publish_forum_topic_post(
            self.db,
            self.author,
            {
                "title": "悬赏求调优交流帖标题",
                "category": "tuning",
                "body": "悬赏求大家帮忙优化水彩风格参数，赏金 20 积分已托管。",
                "bounty": bounty,
                "price": 0,
            },
        )
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("credits"), initial_balance - bounty)
        self.assertEqual(res.get("bounty"), bounty)

        # Check wallet balance
        conn = self.db.get_conn()
        w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()
        self.assertEqual(int(w["balance"]), initial_balance - bounty)

        # Check ledger: bounty_escrow
        escrow = conn.execute(
            "SELECT * FROM ledgers WHERE user_id = ? AND kind = 'bounty_escrow'",
            (self.author["id"],),
        ).fetchone()
        self.assertIsNotNone(escrow)
        self.assertEqual(escrow["delta"], -bounty)
        self.assertEqual(escrow["balance_after"], initial_balance - bounty)

        # Check topic status
        topic = conn.execute("SELECT * FROM forum_topics WHERE id = ?", (res["topicId"],)).fetchone()
        self.assertEqual(topic["bounty_status"], "open")
        self.assertEqual(topic["bounty"], bounty)

    def test_03_reply_reward_still_granted_up_to_daily_cap(self):
        """3. Reply rewards (+2 credits) are untouched and respect the daily cap of 5."""
        # Create a topic to reply to
        res_topic = publish_forum_topic_post(
            self.db,
            self.author,
            {
                "title": "用于测试回复的主题帖标题",
                "category": "tuning",
                "body": "这是一篇用于测试回复奖励的主题帖正文内容。",
            },
        )
        topic_id = res_topic["topicId"]

        # Register a replier
        replier, _ = register_user(self.db, "test_replier", "password123")
        conn = self.db.get_conn()
        conn.execute("UPDATE wallets SET balance = 10 WHERE user_id = ?", (replier["id"],))
        conn.commit()

        # Send 5 replies: each should grant +2 credits
        expected_balance = 10
        for i in range(1, 6):
            expected_balance += 2
            res = publish_forum_reply_post(
                self.db,
                replier,
                topic_id,
                f"第 {i} 条有效测试回复内容，讨论画风技巧",
                direct=True,
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["rewarded"], 2)
            self.assertEqual(res["credits"], expected_balance)

        # 6th reply on the same day: cap reached, 0 reward
        res6 = publish_forum_reply_post(
            self.db,
            replier,
            topic_id,
            "第 6 条测试回复，今日奖励已达上限",
            direct=True,
        )
        self.assertTrue(res6["ok"])
        self.assertEqual(res6["rewarded"], 0)
        self.assertEqual(res6["credits"], expected_balance)

        # Verify ledger count is exactly 5
        ledger_count = conn.execute(
            "SELECT COUNT(*) FROM ledgers WHERE user_id = ? AND kind = 'publish_reply'",
            (replier["id"],),
        ).fetchone()[0]
        self.assertEqual(ledger_count, 5)

    def test_04_migration_075_idempotent_zeroes_existing_settings(self):
        """4. Migration 075 sets topic_publish_credits to 0 in site_settings.economy idempotently."""
        conn = self.db.get_conn()

        # Simulate legacy site_settings with topic_publish_credits = 5
        legacy_economy = {
            "welcome_credits": 20,
            "topic_publish_credits": 5,
            "reply_publish_credits": 2,
        }
        conn.execute(
            "UPDATE site_settings SET value_json = ? WHERE key = 'economy'",
            (json.dumps(legacy_economy),),
        )
        conn.commit()

        # Verify legacy value is 5 before migration
        row = conn.execute("SELECT value_json FROM site_settings WHERE key = 'economy'").fetchone()
        self.assertEqual(json.loads(row["value_json"])["topic_publish_credits"], 5)

        # Run migration 075 SQL
        conn.executescript(ZERO_TOPIC_PUBLISH_CREDITS_SQL)
        conn.commit()

        # Verify value is now 0
        row = conn.execute("SELECT value_json FROM site_settings WHERE key = 'economy'").fetchone()
        self.assertEqual(json.loads(row["value_json"])["topic_publish_credits"], 0)

        # Run migration 075 hook (repeatable / idempotent)
        zero_topic_publish_credits_hook(conn)
        row = conn.execute("SELECT value_json FROM site_settings WHERE key = 'economy'").fetchone()
        self.assertEqual(json.loads(row["value_json"])["topic_publish_credits"], 0)

        # get_site_settings also returns 0
        settings = get_site_settings(conn)
        self.assertEqual(settings["economy"]["topic_publish_credits"], 0)

    def test_05_admin_settings_update_enforces_zero_credits(self):
        """5. Admin updating economy settings cannot re-enable topic_publish_credits."""
        admin_update_settings(
            self.db,
            self.admin,
            section="economy",
            values={"welcome_credits": 25, "topic_publish_credits": 10},
            reason="尝试修改发帖奖励",
        )
        conn = self.db.get_conn()
        settings = get_site_settings(conn)
        self.assertEqual(settings["economy"]["welcome_credits"], 25)
        self.assertEqual(settings["economy"]["topic_publish_credits"], 0)


if __name__ == "__main__":
    unittest.main()
