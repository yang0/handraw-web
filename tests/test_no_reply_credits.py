"""Tests for Issue #51: Cancel forum reply credit rewards.

Verifies:
1. Normal reply to another user's topic produces NO publish_reply ledger entry; wallet balance remains unchanged.
2. Reply to author's own topic produces NO publish_reply ledger entry; wallet balance remains unchanged.
3. Multiple consecutive replies produce NO rewards and 0 publish_reply ledgers (daily cap is inactive).
4. Bounty settlement via accept_forum_bounty_reply remains fully intact and awards bounty_win credits.
5. Historical publish_reply ledgers and user balances are NOT retroactively deducted.
6. Migration 077 idempotently sets site_settings.economy.reply_publish_credits and reply_daily_cap to 0.
7. Admin settings update for economy enforces reply_publish_credits == 0 and reply_daily_cap == 0.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server as server_module
from backend.admin_services import admin_update_settings
from backend.services import (
    accept_forum_bounty_reply,
    apply_wallet_delta,
    get_site_settings,
    publish_forum_reply_post,
    publish_forum_topic_post,
    register_user,
)
from backend.work_schema import ZERO_REPLY_PUBLISH_CREDITS_SQL, zero_reply_publish_credits_hook


class NoReplyCreditsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server_module.init_database(Path(self.temp.name) / "test_no_reply_credits.db")
        self.author, _ = register_user(self.db, "test_author", "password123")
        self.replier, _ = register_user(self.db, "test_replier", "password123")
        self.admin, _ = register_user(self.db, "test_admin", "password123")

        conn = self.db.get_conn()
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin["id"],))
        conn.execute("UPDATE wallets SET balance = 100 WHERE user_id = ?", (self.author["id"],))
        conn.execute("UPDATE wallets SET balance = 50 WHERE user_id = ?", (self.replier["id"],))
        conn.commit()
        self.admin["role"] = "admin"

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_01_normal_reply_no_reward_no_ledger(self):
        """1. Replying to someone else's topic produces 0 reward, balance unchanged, no ledger."""
        topic_res = publish_forum_topic_post(
            self.db,
            self.author,
            {
                "title": "测试讨论画风技巧主题帖",
                "category": "tuning",
                "body": "欢迎大家讨论水彩与水墨的混合使用技巧。",
                "bounty": 0,
                "price": 0,
            },
        )
        self.assertTrue(topic_res["ok"])
        topic_id = topic_res["topicId"]

        initial_balance = 50
        reply_res = publish_forum_reply_post(
            self.db,
            self.replier,
            topic_id,
            "这是一条热心回复，分享水墨笔刷参数设置。",
            direct=True,
        )
        self.assertTrue(reply_res["ok"])
        self.assertEqual(reply_res.get("rewarded"), 0)
        self.assertEqual(reply_res.get("credits"), initial_balance)

        # Check wallet balance
        conn = self.db.get_conn()
        w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.replier["id"],)).fetchone()
        self.assertEqual(int(w["balance"]), initial_balance)

        # Check ledgers: strictly NO publish_reply ledger entry
        ledgers = conn.execute(
            "SELECT * FROM ledgers WHERE user_id = ? AND kind = 'publish_reply'",
            (self.replier["id"],),
        ).fetchall()
        self.assertEqual(len(ledgers), 0)

    def test_02_reply_to_own_topic_no_reward_no_ledger(self):
        """2. Replying to author's own topic produces 0 reward, balance unchanged, no ledger."""
        topic_res = publish_forum_topic_post(
            self.db,
            self.author,
            {
                "title": "楼主自建测试主题帖",
                "category": "tuning",
                "body": "楼主本人在下方追加补充说明。",
                "bounty": 0,
                "price": 0,
            },
        )
        topic_id = topic_res["topicId"]

        initial_balance = 100
        reply_res = publish_forum_reply_post(
            self.db,
            self.author,
            topic_id,
            "这是楼主本人回复自己的补充说明，不应奖励积分。",
            direct=True,
        )
        self.assertTrue(reply_res["ok"])
        self.assertEqual(reply_res.get("rewarded"), 0)
        self.assertEqual(reply_res.get("credits"), initial_balance)

        conn = self.db.get_conn()
        w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()
        self.assertEqual(int(w["balance"]), initial_balance)

        ledgers = conn.execute(
            "SELECT * FROM ledgers WHERE user_id = ? AND kind = 'publish_reply'",
            (self.author["id"],),
        ).fetchall()
        self.assertEqual(len(ledgers), 0)

    def test_03_multiple_replies_produce_zero_rewards(self):
        """3. Multiple replies (even exceeding old daily cap of 5) produce 0 rewards and 0 ledgers."""
        topic_res = publish_forum_topic_post(
            self.db,
            self.author,
            {
                "title": "多条回复测试帖",
                "category": "tuning",
                "body": "测试连续发送多条回复。",
            },
        )
        topic_id = topic_res["topicId"]

        initial_balance = 50
        for i in range(1, 10):
            res = publish_forum_reply_post(
                self.db,
                self.replier,
                topic_id,
                f"这是第 {i} 条连续回复内容。",
                direct=True,
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["rewarded"], 0)
            self.assertEqual(res["credits"], initial_balance)

        conn = self.db.get_conn()
        w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.replier["id"],)).fetchone()
        self.assertEqual(int(w["balance"]), initial_balance)

        ledgers = conn.execute(
            "SELECT * FROM ledgers WHERE user_id = ? AND kind = 'publish_reply'",
            (self.replier["id"],),
        ).fetchall()
        self.assertEqual(len(ledgers), 0)

    def test_04_bounty_win_settlement_intact(self):
        """4. Bounty settlement via accept_forum_bounty_reply remains fully intact and awards bounty_win credits."""
        bounty = 30
        topic_res = publish_forum_topic_post(
            self.db,
            self.author,
            {
                "title": "悬赏求调优高精细节帖",
                "category": "tuning",
                "body": "提供最佳方案者将获得 30 积分悬赏！",
                "bounty": bounty,
                "price": 0,
            },
        )
        topic_id = topic_res["topicId"]

        # Replier posts a solution
        reply_res = publish_forum_reply_post(
            self.db,
            self.replier,
            topic_id,
            "这是精准调优方案：调整采样步数为 32，提示词增强。",
            direct=True,
        )
        reply_id = reply_res["replyId"]

        # Replier gets 0 reply reward
        self.assertEqual(reply_res.get("rewarded"), 0)

        # Author accepts replier's solution
        accept_res = accept_forum_bounty_reply(
            self.db,
            self.author,
            topic_id,
            reply_id,
        )
        self.assertTrue(accept_res["ok"])
        self.assertEqual(accept_res["bounty"], bounty)

        # Winner receives the bounty_win delta
        conn = self.db.get_conn()
        w_replier = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.replier["id"],)).fetchone()
        self.assertEqual(int(w_replier["balance"]), 50 + bounty)

        bounty_ledger = conn.execute(
            "SELECT * FROM ledgers WHERE user_id = ? AND kind = 'bounty_win'",
            (self.replier["id"],),
        ).fetchone()
        self.assertIsNotNone(bounty_ledger)
        self.assertEqual(bounty_ledger["delta"], bounty)

    def test_05_historical_rewards_not_retroactively_deducted(self):
        """5. Historical publish_reply ledgers and balances are not retroactively deducted or purged."""
        conn = self.db.get_conn()
        # Seed an old historical ledger and balance
        apply_wallet_delta(
            conn,
            int(self.replier["id"]),
            2,
            "publish_reply",
            "历史回复奖励",
            event_key="pub_reply_hist_1",
            ref_type="reply",
            ref_id="rep_hist_1",
        )
        conn.commit()

        w_before = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.replier["id"],)).fetchone()
        self.assertEqual(int(w_before["balance"]), 52)

        # Run migration hook
        zero_reply_publish_credits_hook(conn)
        conn.commit()

        # Balance remains 52 and historical ledger exists
        w_after = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.replier["id"],)).fetchone()
        self.assertEqual(int(w_after["balance"]), 52)

        hist_ledgers = conn.execute(
            "SELECT * FROM ledgers WHERE user_id = ? AND kind = 'publish_reply'",
            (self.replier["id"],),
        ).fetchall()
        self.assertEqual(len(hist_ledgers), 1)

    def test_06_migration_077_idempotent_zeroes_existing_settings(self):
        """6. Migration 077 sets reply_publish_credits and reply_daily_cap to 0 idempotently."""
        conn = self.db.get_conn()

        # Simulate legacy site_settings with reply_publish_credits = 2, reply_daily_cap = 5
        legacy_economy = {
            "welcome_credits": 20,
            "topic_publish_credits": 0,
            "reply_publish_credits": 2,
            "reply_daily_cap": 5,
        }
        conn.execute(
            "UPDATE site_settings SET value_json = ? WHERE key = 'economy'",
            (json.dumps(legacy_economy),),
        )
        conn.commit()

        # Verify legacy values before migration
        row = conn.execute("SELECT value_json FROM site_settings WHERE key = 'economy'").fetchone()
        data = json.loads(row["value_json"])
        self.assertEqual(data["reply_publish_credits"], 2)
        self.assertEqual(data["reply_daily_cap"], 5)

        # Run migration 077 SQL
        conn.executescript(ZERO_REPLY_PUBLISH_CREDITS_SQL)
        conn.commit()

        # Verify values are now 0
        row = conn.execute("SELECT value_json FROM site_settings WHERE key = 'economy'").fetchone()
        data = json.loads(row["value_json"])
        self.assertEqual(data["reply_publish_credits"], 0)
        self.assertEqual(data["reply_daily_cap"], 0)

        # Run migration 077 hook (repeatable / idempotent)
        zero_reply_publish_credits_hook(conn)
        row = conn.execute("SELECT value_json FROM site_settings WHERE key = 'economy'").fetchone()
        data = json.loads(row["value_json"])
        self.assertEqual(data["reply_publish_credits"], 0)
        self.assertEqual(data["reply_daily_cap"], 0)

        # get_site_settings also returns 0
        settings = get_site_settings(conn)
        self.assertEqual(settings["economy"]["reply_publish_credits"], 0)
        self.assertEqual(settings["economy"]["reply_daily_cap"], 0)

    def test_07_admin_settings_update_enforces_zero_reply_credits(self):
        """7. Admin updating economy settings cannot re-enable reply_publish_credits or reply_daily_cap."""
        admin_update_settings(
            self.db,
            self.admin,
            section="economy",
            values={"welcome_credits": 30, "reply_publish_credits": 5, "reply_daily_cap": 10},
            reason="尝试修改回复奖励与上限",
        )
        conn = self.db.get_conn()
        settings = get_site_settings(conn)
        self.assertEqual(settings["economy"]["welcome_credits"], 30)
        self.assertEqual(settings["economy"]["reply_publish_credits"], 0)
        self.assertEqual(settings["economy"]["reply_daily_cap"], 0)


if __name__ == "__main__":
    unittest.main()
