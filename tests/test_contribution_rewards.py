"""Contribution identity and risk locks on isolated PostgreSQL."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from backend import economy, points
from backend.services import (
    register_user,
    prepare_cloud_generation,
    complete_cloud_generation,
)
from tests.postgres_support import open_isolated_postgres


class ContributionGuardTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self)
        self.user, _ = register_user(self.db, "reward_owner", "FixturePass123!")
        self.admin = {**self.user, "role": "admin"}
        self.uid = self.user["id"]

    def topic(self, tid, body="Original tutorial", owner=None):
        owner = owner or self.user
        self.db.get_conn().execute(
            "INSERT INTO forum_topics(id,category,category_label,title,author_username,author_name,summary,published_at_ms,created_at,updated_at) VALUES(?,'tutorial','教程',?,?,?, ?,1,CURRENT_TIMESTAMP::text,CURRENT_TIMESTAMP::text)",
            (tid, tid, owner["username"], owner["username"], body),
        )

    def test_locked_wallet_pauses_rewards_and_verification_but_cash_generation_continues(
        self,
    ):
        tx = self.db.get_conn()
        tx.execute("UPDATE wallets SET locked=1 WHERE user_id=?", (self.uid,))
        tx.execute(
            "INSERT INTO verified_emails(user_id,email,verified_at) VALUES(?,?,CURRENT_TIMESTAMP::text)",
            (self.uid, "reward@example.test"),
        )
        with self.db.transaction() as tx:
            self.assertEqual(
                points.reward(tx, self.uid, "checkin", str(self.uid) + ":day"), 0
            )
            self.assertEqual(points.reward(tx, self.uid, "verified", str(self.uid)), 0)
            economy.cash_delta(tx, self.uid, 100, 0, "recharge", "cash-fixture")
        self.topic("locked-tutorial")
        self.assertEqual(
            points.admin_reward(
                self.db,
                self.admin,
                {"kind": "quality_topic", "targetId": "locked-tutorial"},
            )["rewarded"],
            0,
        )
        tx.execute("UPDATE generation_specs SET verified=true,price_cents=25")
        tx.execute("UPDATE generation_quota_policy SET base_units=0")
        quote = economy.create_quote(self.db, self.user, [{"ratio": "3:4"}])
        result = prepare_cloud_generation(
            self.db,
            self.user,
            {
                "prompt": "cash unaffected",
                "requestId": "cash-while-locked",
                "quoteId": quote["quoteId"],
                "confirmCost": True,
            },
        )
        complete_cloud_generation(
            self.db,
            result["genId"],
            "task",
            ["/images/poster-demo-autumn-equinox.webp"],
        )
        self.assertEqual(
            economy.cash(tx, self.uid), {"balanceCents": 75, "heldCents": 0}
        )
        self.assertEqual(
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=?", (self.uid,)
            ).fetchone()[0],
            0,
        )
        tx.execute("UPDATE wallets SET locked=0 WHERE user_id=?", (self.uid,))
        with self.db.transaction() as tx:
            self.assertEqual(points.reward(tx, self.uid, "verified", str(self.uid)), 20)
            self.assertEqual(points.reward(tx, self.uid, "verified", str(self.uid)), 0)
        self.assertEqual(
            points.admin_reward(
                self.db,
                self.admin,
                {"kind": "quality_topic", "targetId": "locked-tutorial"},
            )["rewarded"],
            10,
        )
        self.assertTrue(economy.reconcile(tx)["ok"])

    def test_reposts_edits_and_deletion_restore_cannot_repeat_tutorial_rewards(self):
        self.topic("original", "One original lesson")
        self.topic("repost", "One  original\nlesson")
        self.assertEqual(
            points.admin_reward(
                self.db, self.admin, {"kind": "quality_topic", "targetId": "original"}
            )["rewarded"],
            10,
        )
        self.db.get_conn().execute(
            "UPDATE forum_topics SET summary='Changed content',status='deleted' WHERE id='original'"
        )
        self.assertEqual(
            points.admin_reward(
                self.db, self.admin, {"kind": "quality_topic", "targetId": "repost"}
            )["rewarded"],
            0,
        )
        self.db.get_conn().execute(
            "UPDATE forum_topics SET status='published' WHERE id='original'"
        )
        self.assertEqual(
            points.admin_reward(
                self.db, self.admin, {"kind": "quality_topic", "targetId": "original"}
            )["rewarded"],
            0,
        )
        for i in range(12):
            tid = f"unique-{i}"
            self.topic(tid, f"Distinct tutorial number {i}")
            value = points.admin_reward(
                self.db, self.admin, {"kind": "quality_topic", "targetId": tid}
            )["rewarded"]
            self.assertEqual(value, 10 if i < 9 else 0)
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT balance FROM wallets WHERE user_id=?", (self.uid,))
            .fetchone()[0],
            100,
        )

    def test_same_content_cannot_reward_two_authors_concurrently(self):
        other, _ = register_user(self.db, "other_reward_owner", "FixturePass123!")
        self.topic("owner-copy", owner=self.user)
        self.topic("other-copy", owner=other)

        def award(tid):
            try:
                return points.admin_reward(
                    self.db, self.admin, {"kind": "quality_topic", "targetId": tid}
                )["rewarded"]
            finally:
                self.db.close_thread_conn()

        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(
                list(pool.map(award, ["owner-copy", "other-copy"])), [10, 0]
            )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT count(*) FROM contribution_reward_content")
            .fetchone()[0],
            1,
        )

    def test_work_and_resource_fingerprints_survive_identity_changes_and_migration_reapply(
        self,
    ):
        tx = self.db.get_conn()
        for target in ("work-a", "work-b"):
            tx.execute(
                "INSERT INTO works(id,author_username,author_name,title,prompt,images_json,published_at_ms,created_at,updated_at) VALUES(?,?,?,'Title','Original drawing','[\"/images/same.webp\"]',1,CURRENT_TIMESTAMP::text,CURRENT_TIMESTAMP::text)",
                (target, self.user["username"], self.user["username"]),
            )
        self.assertEqual(
            points.admin_reward(
                self.db, self.admin, {"kind": "quality_work", "targetId": "work-a"}
            )["rewarded"],
            5,
        )
        self.assertEqual(
            points.admin_reward(
                self.db, self.admin, {"kind": "quality_work", "targetId": "work-b"}
            )["rewarded"],
            0,
        )
        from backend.generation_v3 import _upsert_media

        with self.db.transaction() as tx:
            _upsert_media(
                tx, owner_id=self.uid, url="/uploads/copy-a.webp", sha256="a" * 64
            )
            _upsert_media(
                tx, owner_id=self.uid, url="/uploads/copy-b.webp", sha256="a" * 64
            )
        tx.execute(
            "UPDATE works SET images_json='[\"/uploads/copy-a.webp\"]' WHERE id='work-a'"
        )
        self.db.get_conn().execute(
            "UPDATE works SET images_json='[\"/uploads/copy-b.webp\"]',prompt='Edited copy prompt' WHERE id='work-b'"
        )
        # Another image set earns once; changing upload URL and prompt does not.
        with self.db.transaction() as tx:
            first = points.reward(tx, self.uid, "quality_work", "work-b")
        self.assertEqual(first, 5)
        tx.execute(
            "INSERT INTO works(id,author_username,author_name,title,prompt,images_json,published_at_ms,created_at,updated_at) VALUES('work-c',?,?,'New title','Other prompt','[\"/uploads/copy-a.webp\"]',1,CURRENT_TIMESTAMP::text,CURRENT_TIMESTAMP::text)",
            (self.user["username"], self.user["username"]),
        )
        self.assertEqual(
            points.admin_reward(
                self.db, self.admin, {"kind": "quality_work", "targetId": "work-c"}
            )["rewarded"],
            0,
        )
        for code in ("USR-S-A", "USR-S-B"):
            tx.execute(
                "INSERT INTO catalog_assets(code,kind,source_type,author_username,author_name,name,definition,image_url,published_at_ms,created_at,updated_at) VALUES(?,'style','community',?,?,'Original style','Same original definition','/images/same.webp',1,CURRENT_TIMESTAMP::text,CURRENT_TIMESTAMP::text)",
                (code, self.user["username"], self.user["username"]),
            )
        with self.db.transaction() as tx:
            self.assertEqual(points.reward(tx, self.uid, "asset", "USR-S-A"), 20)
            self.assertEqual(points.reward(tx, self.uid, "asset", "USR-S-B"), 0)
        with self.db.transaction() as tx:
            tx.execute(
                (
                    Path(__file__).resolve().parents[1]
                    / "backend/postgres_120_contribution_guards.sql"
                ).read_text(encoding="utf-8")
            )
        self.assertEqual(
            tx.execute("SELECT count(*) FROM contribution_reward_content").fetchone()[
                0
            ],
            3,
        )
        self.assertEqual(
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=?", (self.uid,)
            ).fetchone()[0],
            30,
        )
