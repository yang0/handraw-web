"""Upgrade a populated pre-118 schema without replacing documents or ledgers."""

import json
import unittest
from pathlib import Path

from backend.db import utc_now_iso
from backend.generation_v3 import _stable_id, _upsert_media, ensure_run
from backend.services import register_user, get_studio_workspace
from backend.studio_articles import get_article
from backend.studio_upgrade import upgrade_studio_data
from ops.bootstrap_postgres_v3 import BASELINE_PATH, MIGRATIONS
from tests.postgres_support import open_isolated_postgres


class StudioUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self, initialize=False)
        with self.db.transaction() as tx:
            tx.execute(BASELINE_PATH.read_text(encoding="utf-8"))
            for migration in MIGRATIONS:
                if migration.name != "postgres_118_studio_model.sql":
                    tx.execute(migration.read_text(encoding="utf-8"))
        self.user, _ = register_user(self.db, "upgrade_owner", "FixturePass123!")
        self.card = {
            "id": "cover",
            "role": "cover",
            "prompt": "original prompt",
            "ratio": "16:9",
            "imageUrl": "/images/original.webp",
            "status": "done",
        }
        self.db.get_conn().execute(
            "INSERT INTO studio_articles(id,user_id,article_title,markdown,cards_json,created_at_ms,updated_at_ms) VALUES('original',?,'Original','Original body',?,1,2)",
            (self.user["id"], json.dumps([self.card])),
        )

    def schema(self):
        with self.db.transaction() as tx:
            tx.execute(
                (
                    Path(__file__).resolve().parents[1]
                    / "backend/postgres_118_studio_model.sql"
                ).read_text(encoding="utf-8")
            )

    def test_current_article_identity_media_and_content_survive_dry_run_apply_and_replay(
        self,
    ):
        before = dict(
            self.db.get_conn()
            .execute("SELECT * FROM studio_articles WHERE id='original'")
            .fetchone()
        )
        self.assertFalse(upgrade_studio_data(self.db)["schemaReady"])
        self.schema()
        planned = upgrade_studio_data(self.db)
        self.assertEqual(planned["articles"], 1)
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM article_illustrations")
            .fetchone()[0],
            0,
        )
        applied = upgrade_studio_data(self.db, apply=True)
        self.assertTrue(applied["ok"])
        article = get_article(self.db, self.user, "original")["article"]
        self.assertEqual(article["markdown"], before["markdown"])
        self.assertEqual(article["cards"][0]["imageUrl"], self.card["imageUrl"])
        self.assertEqual(article["coverRatio"], "16:9")
        self.assertEqual(article["updatedAtMs"], before["updated_at_ms"])
        self.assertEqual(upgrade_studio_data(self.db, apply=True)["articles"], 0)
        self.schema()
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM article_illustrations")
            .fetchone()[0],
            1,
        )

    def test_unresolved_media_and_active_article_jobs_are_preserved_for_review(self):
        self.schema()
        self.db.get_conn().execute(
            "UPDATE studio_articles SET cards_json=? WHERE id='original'",
            (json.dumps([{**self.card, "imageUrl": "/uploads/unowned.webp"}]),),
        )
        result = upgrade_studio_data(self.db, apply=True)
        self.assertEqual(result["issues"][0]["reason"], "unresolved_legacy_media_owner")
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM article_illustrations")
            .fetchone()[0],
            0,
        )
        self.db.get_conn().execute(
            "INSERT INTO studio_generations(id,user_id,username,status,created_at) VALUES('active',?,?,'running',?)",
            (self.user["id"], self.user["username"], utc_now_iso()),
        )
        self.db.get_conn().execute(
            "UPDATE studio_articles SET cards_json=? WHERE id='original'",
            (json.dumps([{**self.card, "genId": "active", "status": "generating"}]),),
        )
        result = upgrade_studio_data(self.db, apply=True)
        self.assertEqual(
            result["issues"][0]["reason"], "wait_for_inflight_article_generation"
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT status FROM studio_generations WHERE id='active'")
            .fetchone()[0],
            "running",
        )

    def test_terminal_legacy_media_becomes_one_task_and_separate_attempt_outputs(self):
        now = utc_now_iso()
        with self.db.transaction() as tx:
            rid = ensure_run(
                tx,
                user_id=self.user["id"],
                source="web",
                external_run_id="legacy",
                expected_count=1,
            )
            tx.execute(
                "INSERT INTO studio_generations(id,user_id,username,engine,status,items_json,created_at,visible_prompt) VALUES('legacy',?,?,'live','success',?,?,'public theme')",
                (
                    self.user["id"],
                    self.user["username"],
                    json.dumps(["/images/first.webp", "/images/second.webp"]),
                    now,
                ),
            )
            for position, url in enumerate(
                ("/images/first.webp", "/images/second.webp")
            ):
                mid = _upsert_media(tx, owner_id=self.user["id"], url=url)
                tx.execute(
                    "INSERT INTO generation_items(id,run_id,position,status,media_id,created_at,updated_at) VALUES(?,?,?,'success',?,?,?)",
                    (_stable_id("item", rid, position), rid, position, mid, now, now),
                )
        self.schema()
        wallet = dict(
            self.db.get_conn()
            .execute("SELECT * FROM wallets WHERE user_id=?", (self.user["id"],))
            .fetchone()
        )
        result = upgrade_studio_data(self.db, apply=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT COUNT(*) FROM generation_items WHERE run_id=? AND retired_at IS NULL",
                (rid,),
            )
            .fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM generation_attempt_media")
            .fetchone()[0],
            2,
        )
        history = get_studio_workspace(self.db, self.user)["history"]
        entry = next(item for item in history if item.get("runId") == rid)
        self.assertEqual(entry["imageCount"], 2)
        self.assertEqual(len(entry["outputSlots"]), 1)
        self.assertEqual(
            dict(
                self.db.get_conn()
                .execute("SELECT * FROM wallets WHERE user_id=?", (self.user["id"],))
                .fetchone()
            ),
            wallet,
        )
        self.assertEqual(upgrade_studio_data(self.db, apply=True)["attempts"], 0)
