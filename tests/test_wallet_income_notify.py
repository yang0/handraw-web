import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.legacy_database import Database
from backend.services import (
    accept_forum_bounty_reply,
    apply_wallet_delta,
    register_user,
    send_encourage_tip,
    utc_now_iso,
)


class WalletIncomeNotifyMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_income_notify.db"
        self.db = Database(self.db_path)
        self.db.migrate()

        self.user_a, _ = register_user(self.db, "user_a", "Pass1234!", "a@example.com", "User A", "inv_a")
        self.user_b, _ = register_user(self.db, "user_b", "Pass1234!", "b@example.com", "User B", "inv_b")

    def tearDown(self) -> None:
        self.db.close()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_six_new_kinds_create_notifications_on_positive_delta(self) -> None:
        conn = self.db.get_conn()
        uid = int(self.user_a["id"])

        new_kinds = [
            "unlock_royalty",
            "bounty_win",
            "unlock_refund",
            "bounty_admin_award",
            "bounty_admin_refund",
            "admin_grant",
        ]

        for kind in new_kinds:
            notif_before = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid,)
            ).fetchone()[0]

            with self.db.transaction() as tx:
                apply_wallet_delta(
                    tx,
                    uid,
                    15,
                    kind,
                    f"测试收益 {kind}",
                    ref_type="topic",
                    ref_id="t_test_01",
                )

            notif_after = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid,)
            ).fetchone()[0]
            self.assertEqual(
                notif_after - notif_before,
                1,
                f"Kind {kind} with delta > 0 must generate exactly 1 notification",
            )

            latest_notif = conn.execute(
                "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (uid,),
            ).fetchone()
            self.assertEqual(latest_notif["kind"], "wallet")
            self.assertEqual(latest_notif["title"], f"测试收益 {kind}")
            self.assertEqual(latest_notif["target_type"], "topic")
            self.assertEqual(latest_notif["target_id"], "t_test_01")

    def test_02_negative_delta_does_not_create_notification(self) -> None:
        conn = self.db.get_conn()
        uid = int(self.user_a["id"])

        kinds_to_test = [
            "unlock_royalty",
            "bounty_win",
            "unlock_refund",
            "bounty_admin_award",
            "bounty_admin_refund",
            "admin_grant",
            "tip_in",
            "studio_refund",
        ]

        notif_before = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid,)
        ).fetchone()[0]

        for kind in kinds_to_test:
            with self.db.transaction() as tx:
                apply_wallet_delta(
                    tx,
                    uid,
                    -5,
                    kind,
                    f"扣款测试 {kind}",
                    ref_type="test",
                    ref_id="r1",
                    allow_negative=True,
                )

        notif_after = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        self.assertEqual(
            notif_after,
            notif_before,
            "Negative delta must never generate wallet income notifications",
        )

    def test_03_checkin_does_not_create_notification(self) -> None:
        conn = self.db.get_conn()
        uid = int(self.user_a["id"])

        notif_before = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid,)
        ).fetchone()[0]

        with self.db.transaction() as tx:
            apply_wallet_delta(
                tx,
                uid,
                10,
                "checkin",
                "每日签到奖励",
                ref_type="wallet",
                ref_id="daily",
            )

        notif_after = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        self.assertEqual(
            notif_after,
            notif_before,
            "checkin must not trigger wallet income notification",
        )

    def test_04_real_business_flow_bounty_win_notification(self) -> None:
        conn = self.db.get_conn()
        uid_a = int(self.user_a["id"])
        uid_b = int(self.user_b["id"])
        now_iso = utc_now_iso()

        # User A has 100 credits and posts a bounty topic
        with self.db.transaction() as tx:
            apply_wallet_delta(tx, uid_a, 100, "admin_grant", "充值测试积分")
            tx.execute(
                """
                INSERT INTO forum_topics (
                    id, category, category_label, title, author_username, author_name,
                    price, bounty, bounty_status, solved, status, published_at_ms,
                    images_json, styles_json, summary, created_at, updated_at
                ) VALUES (
                    't_bounty_real', 'tuning', '技术调优', '悬赏帖测试', 'user_a', 'User A',
                    0, 20, 'open', 0, 'published', 1700000000000,
                    '[]', '[]', '悬赏摘要', ?, ?
                )
                """,
                (now_iso, now_iso),
            )
            # User B replies
            tx.execute(
                """
                INSERT INTO forum_replies (
                    id, topic_id, author_username, author_name, text,
                    accepted, created_at
                ) VALUES (
                    'rep_bounty_win', 't_bounty_real', 'user_b', 'User B', '方案在此',
                    0, ?
                )
                """,
                (now_iso,),
            )

        notif_before = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND kind = 'wallet'", (uid_b,)
        ).fetchone()[0]

        # User A accepts User B's reply
        res = accept_forum_bounty_reply(self.db, self.user_a, "t_bounty_real", "rep_bounty_win")
        self.assertTrue(res.get("ok"))

        notif_after = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND kind = 'wallet'", (uid_b,)
        ).fetchone()[0]
        self.assertEqual(notif_after - notif_before, 1, "User B must receive a wallet income notification for bounty_win")

        latest = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND kind = 'wallet' ORDER BY id DESC LIMIT 1",
            (uid_b,),
        ).fetchone()
        self.assertEqual(latest["kind"], "wallet")
        self.assertIn("悬赏", latest["title"])
        self.assertEqual(latest["target_type"], "topic")
        self.assertEqual(latest["target_id"], "t_bounty_real")

    def test_05_real_business_flow_tip_in_notification(self) -> None:
        conn = self.db.get_conn()
        uid_a = int(self.user_a["id"])
        uid_b = int(self.user_b["id"])
        now_iso = utc_now_iso()

        with self.db.transaction() as tx:
            apply_wallet_delta(tx, uid_b, 50, "admin_grant", "打赏人测试积分")
            tx.execute(
                """
                INSERT INTO forum_topics (
                    id, category, category_label, title, author_username, author_name,
                    price, status, likes, favorites, published_at_ms,
                    images_json, styles_json, summary, created_at, updated_at
                ) VALUES (
                    't_tip_real', 'experience', '经验分享', '精彩分享', 'user_a', 'User A',
                    0, 'published', 0, 0, 1700000000000,
                    '[]', '[]', '分享摘要', ?, ?
                )
                """,
                (now_iso, now_iso),
            )

        notif_before = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid_a,)
        ).fetchone()[0]

        res = send_encourage_tip(self.db, self.user_b, "topic", "t_tip_real", amount=5, request_id="tip_flow_01")
        self.assertTrue(res.get("ok"))

        notif_after = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid_a,)
        ).fetchone()[0]
        self.assertEqual(notif_after - notif_before, 1)

        latest = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (uid_a,),
        ).fetchone()
        self.assertEqual(latest["kind"], "wallet")
        self.assertIn("赞赏", latest["title"])
