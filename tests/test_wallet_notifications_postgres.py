"""Wallet notification behavior in a disposable PostgreSQL database."""
from pathlib import Path
import unittest

from backend.services import apply_wallet_delta, register_user
from tests.postgres_support import open_isolated_postgres


class WalletNotificationTests(unittest.TestCase):
    def test_income_replay_filter_and_rollback(self):
        db = open_isolated_postgres(self)
        user, _ = register_user(db, "wallet_notify", "TestPass123!")
        uid = user["id"]
        ddl = (Path(__file__).resolve().parents[1] / "backend" /
               "postgres_116_wallet_notifications.sql").read_text(encoding="utf-8")
        db.get_conn().execute(ddl)
        db.get_conn().execute(ddl)
        kinds = (
            "unlock_income", "tip_income", "bounty_reward", "studio_refund",
            "refund", "tip_in", "tip_official_in", "unlock_royalty", "bounty_win",
            "unlock_refund", "bounty_admin_award", "bounty_admin_refund", "admin_grant",
        )
        for kind in kinds:
            with db.transaction() as tx:
                _, applied = apply_wallet_delta(
                    tx, uid, 2, kind, kind, event_key=kind, ref_type="topic", ref_id="t1")
                self.assertTrue(applied)
                _, applied = apply_wallet_delta(
                    tx, uid, 2, kind, kind, event_key=kind, ref_type="topic", ref_id="t1")
                self.assertFalse(applied)
        with db.transaction() as tx:
            apply_wallet_delta(tx, uid, -1, "tip_out", "out")
            apply_wallet_delta(tx, uid, 1, "recharge", "recharge")
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with db.transaction() as tx:
                apply_wallet_delta(tx, uid, 1, "tip_in", "rollback")
                raise RuntimeError("rollback")
        rows = db.get_conn().execute(
            "SELECT n.title,n.target_type,n.target_id,n.created_at=l.created_at AS same_time "
            "FROM notifications n JOIN ledgers l ON l.user_id=n.user_id AND l.reason=n.title "
            "WHERE n.user_id=? AND n.kind='wallet'", (uid,)).fetchall()
        self.assertEqual(len(rows), len(kinds))
        self.assertEqual({r["title"] for r in rows}, set(kinds))
        self.assertTrue(all(r["target_type"] == "topic" and r["target_id"] == "t1"
                            and r["same_time"] for r in rows))
