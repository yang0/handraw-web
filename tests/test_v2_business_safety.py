"""Business-data regression tests for the local Handraw 2.0 service.

These tests use temporary SQLite files only.  Demo fixtures are enabled in the
individual tests that need named users; the production-boot test deliberately
uses the default-safe flag values.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tests.legacy_database import Database
from backend.db import local_today_str
from backend.seed import ensure_seeded
from backend.services import (
    ServiceError,
    build_boot_payload,
    claim_cloud_generation_submission,
    complete_cloud_generation,
    delete_user_studio_history,
    grant_studio_media_public,
    get_studio_workspace,
    get_user_studio_task,
    is_new_release_active,
    login_user,
    prepare_cloud_generation,
    record_user_studio_history,
    refund_failed_cloud_generation,
)
from backend.security import hash_password


@contextmanager
def temporary_database(*, demo: bool):
    with tempfile.TemporaryDirectory(prefix="handraw-business-") as temp_dir:
        with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "1" if demo else "0"}, clear=False):
            db = Database(Path(temp_dir) / "isolated.db")
            ensure_seeded(db)
            try:
                yield db
            finally:
                db.close()


class HandrawBusinessSafetyTests(unittest.TestCase):
    def test_production_boot_has_no_synthetic_content(self) -> None:
        with temporary_database(demo=False) as db:
            conn = db.get_conn()
            for table in (
                "users",
                "works",
                "catalog_assets",
                "forum_topics",
                "interactions",
                "asset_social_seeds",
                "studio_articles",
                "studio_generations",
            ):
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM site_settings").fetchone()[0], 0)

        # Only the explicit documented value enables the fixture loader.
        with temporary_database(demo=True) as db:
            conn = db.get_conn()
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM works").fetchone()[0], 0)

        with tempfile.TemporaryDirectory(prefix="handraw-business-flag-") as temp_dir:
            with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "true"}, clear=False):
                db = Database(Path(temp_dir) / "isolated.db")
                ensure_seeded(db)
                self.assertEqual(db.get_conn().execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
                db.close()

    def test_history_id_is_owner_scoped_and_soft_delete_preserves_accounting(self) -> None:
        with temporary_database(demo=True) as db:
            conn = db.get_conn()
            first = dict(conn.execute("SELECT * FROM users WHERE username = 'su_editorial'").fetchone())
            second = dict(conn.execute("SELECT * FROM users WHERE username = 'momo_design'").fetchone())

            record_user_studio_history(db, first, {"id": "history-owned", "prompt": "first"})
            with self.assertRaisesRegex(ServiceError, "不能覆盖") as conflict:
                record_user_studio_history(db, second, {"id": "history-owned", "prompt": "attacker"})
            self.assertEqual(conflict.exception.status, 409)
            self.assertEqual(conflict.exception.code, "history_conflict")
            self.assertEqual(conn.execute("SELECT prompt FROM studio_generations WHERE id = 'history-owned'").fetchone()[0], "first")

            # Saving with the same owner's id may update presentation fields,
            # but a real generation's cost/status/task ownership is immutable.
            prepared = prepare_cloud_generation(db, first, {"requestId": "history-accounting", "prompt": "real"})
            complete_cloud_generation(db, prepared["genId"], "gateway-task-1", ["/generated/owned.webp"])
            before = dict(conn.execute("SELECT * FROM studio_generations WHERE id = ?", (prepared["genId"],)).fetchone())
            record_user_studio_history(db, first, {"id": prepared["genId"], "prompt": "renamed"})
            after = dict(conn.execute("SELECT * FROM studio_generations WHERE id = ?", (prepared["genId"],)).fetchone())
            for key in ("user_id", "engine", "cost_type", "credits_spent", "task_id", "status"):
                self.assertEqual(after[key], before[key], key)
            self.assertEqual(after["prompt"], "renamed")

            with self.assertRaises(ServiceError) as forbidden:
                delete_user_studio_history(db, second, "history-owned")
            self.assertEqual(forbidden.exception.status, 403)
            self.assertTrue(delete_user_studio_history(db, first, "history-owned")["deleted"])
            self.assertEqual(
                conn.execute("SELECT deleted_at FROM studio_generations WHERE id = 'history-owned'").fetchone()[0] != "",
                True,
            )
            self.assertNotIn("history-owned", {h["id"] for h in get_studio_workspace(db, first)["history"]})

    def test_request_id_is_idempotent_inflight_is_limited_and_refund_uses_original_day(self) -> None:
        with temporary_database(demo=True) as db:
            conn = db.get_conn()
            user = dict(conn.execute("SELECT * FROM users WHERE username = 'su_editorial'").fetchone())
            first = prepare_cloud_generation(db, user, {"requestId": "stable-req", "prompt": "one"})
            pending = get_studio_workspace(db, user)["pendingTasks"]
            self.assertEqual(pending[0]["requestId"], "stable-req")
            self.assertEqual(pending[0]["genId"], first["genId"])
            self.assertEqual(get_user_studio_task(db, user, request_id="stable-req")["genId"], first["genId"])
            self.assertTrue(claim_cloud_generation_submission(db, user, first["genId"])["claimed"])
            self.assertFalse(claim_cloud_generation_submission(db, user, first["genId"])["claimed"])
            wallet_after_first = dict(conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user["id"],)).fetchone())
            retry = prepare_cloud_generation(db, user, {"requestId": "stable-req", "prompt": "changed"})
            self.assertTrue(retry["idempotent"])
            self.assertEqual(retry["genId"], first["genId"])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM studio_generations WHERE user_id = ? AND request_id = 'stable-req'", (user["id"],)).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT free_quota_used FROM wallets WHERE user_id = ?", (user["id"],)).fetchone()[0],
                wallet_after_first["free_quota_used"],
            )

            with self.assertRaises(ServiceError) as inflight:
                prepare_cloud_generation(db, user, {"requestId": "second-req", "prompt": "two"})
            self.assertEqual(inflight.exception.status, 429)
            self.assertEqual(inflight.exception.code, "generation_in_progress")

            refund_failed_cloud_generation(db, first["genId"], "gateway timeout")
            self.assertEqual(
                conn.execute("SELECT free_quota_used FROM wallets WHERE user_id = ?", (user["id"],)).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT status FROM studio_quota_reservations WHERE generation_id = ?", (first["genId"],)).fetchone()[0],
                "released",
            )

            second = prepare_cloud_generation(db, user, {"requestId": "cross-day", "prompt": "three"})
            today = local_today_str()
            conn.execute("UPDATE studio_generations SET reservation_date = '2000-01-01' WHERE id = ?", (second["genId"],))
            conn.execute(
                "UPDATE studio_quota_reservations SET reservation_date = '2000-01-01' WHERE generation_id = ?",
                (second["genId"],),
            )
            conn.execute(
                "UPDATE wallets SET free_quota_date = ?, free_quota_used = 1 WHERE user_id = ?",
                (today, user["id"]),
            )
            refund_failed_cloud_generation(db, second["genId"], "late gateway timeout")
            self.assertEqual(
                conn.execute("SELECT free_quota_used FROM wallets WHERE user_id = ?", (user["id"],)).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT status FROM studio_quota_reservations WHERE generation_id = ?", (second["genId"],)).fetchone()[0],
                "released",
            )

    def test_release_window_is_exactly_72_hours_and_private_media_needs_grant(self) -> None:
        now = int(time.time() * 1000)
        window = 72 * 60 * 60 * 1000
        self.assertTrue(is_new_release_active(now - window + 1, now))
        self.assertFalse(is_new_release_active(now - window, now))
        self.assertFalse(is_new_release_active(now - window - 1, now))

        with temporary_database(demo=True) as db:
            conn = db.get_conn()
            user = dict(conn.execute("SELECT * FROM users WHERE username = 'su_editorial'").fetchone())
            other = dict(conn.execute("SELECT * FROM users WHERE username = 'momo_design'").fetchone())
            row = conn.execute("SELECT id FROM works ORDER BY id LIMIT 1").fetchone()
            self.assertIsNotNone(row)
            old_ms = int(time.time() * 1000) - window - 1
            conn.execute("UPDATE works SET published_at_ms = ?, is_new_release = 1 WHERE id = ?", (old_ms, row["id"]))
            boot = build_boot_payload(db, None)
            old_work = next(w for w in boot["works"] if w["id"] == row["id"])
            self.assertFalse(old_work["isNewRelease"])

            prepared = prepare_cloud_generation(db, user, {"requestId": "grant-test", "prompt": "grant"})
            complete_cloud_generation(db, prepared["genId"], "task-grant", ["/generated/private.webp"])
            granted = grant_studio_media_public(db, user, "/generated/private.webp", "work", row["id"], prepared["genId"])
            self.assertEqual(granted["mediaUrl"], "/generated/private.webp")
            # 594d3b2 added work projection public grant on completion; grant_studio_media_public adds a grant for row["id"].
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM media_public_grants WHERE media_url = '/generated/private.webp' AND target_id = ?", (row["id"],)).fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM media_public_grants WHERE media_url = '/generated/private.webp'").fetchone()[0], 2)
            with self.assertRaises(ServiceError) as forbidden:
                grant_studio_media_public(db, other, "/generated/private.webp", "work", row["id"], prepared["genId"])
            self.assertEqual(forbidden.exception.status, 403)

    def test_existing_seed_rows_are_hidden_in_normal_mode_and_default_seed_login_is_blocked(self) -> None:
        with temporary_database(demo=True) as db:
            with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}, clear=False):
                boot = build_boot_payload(db, None)
                self.assertFalse(boot["demoMode"])
                self.assertEqual(boot["works"], [])
                self.assertEqual(boot["communityResources"], [])
                self.assertEqual(boot["topics"], [])
                seed_user = dict(db.get_conn().execute("SELECT * FROM users WHERE username = 'yang0'").fetchone())
                self.assertEqual(get_studio_workspace(db, seed_user)["history"], [])
                with self.assertRaises(ServiceError) as blocked:
                    login_user(db, "su_editorial", "handraw123")
                self.assertEqual(blocked.exception.code, "seed_credentials_disabled")

                # A seed account that has been explicitly taken over with a
                # new password remains a real account; only the known default
                # credential is blocked.
                with db.transaction() as tx:
                    tx.execute(
                        "UPDATE users SET password_hash = ?, password_algo = 'pbkdf2_sha256' WHERE username = 'su_editorial'",
                        (hash_password("taken-over-1234"),),
                    )
                user, _token = login_user(db, "su_editorial", "taken-over-1234")
                self.assertEqual(user["username"], "su_editorial")


if __name__ == "__main__":
    unittest.main()
