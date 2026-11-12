"""Home scenario query and cache contracts in an isolated PostgreSQL database."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.home_scenarios import get_public_home_scenarios, invalidate_scenarios_cache
from tests.postgres_support import isolated_pg_dsn


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL staging URL not provided")
class TestHomeScenariosPostgres(unittest.TestCase):
    def test_cache_scope_and_authoritative_visibility(self):
        from backend.postgres_db import PostgresDatabase

        self.enterContext(patch.dict(os.environ, {"HANDRAW_REDIS_URL": "", "HANDRAW_DEMO_MODE": "0"}))
        dsn = self.enterContext(isolated_pg_dsn())
        db = PostgresDatabase(dsn)
        self.addCleanup(db.close)
        self.addCleanup(invalidate_scenarios_cache)
        self._check_public_scenarios(db)

    def _check_public_scenarios(self, db):
        db.migrate()
        conn = db.get_conn()
        self.assertEqual(conn.execute("SELECT count(*) FROM schema_migrations WHERE version=110").fetchone()[0], 1)
        for order, work_id in enumerate(("scenario-first", "scenario-second")):
            conn.execute(
                """INSERT INTO works(id,author_username,author_name,title,prompt,images_json,
                                     published_at_ms,created_at,updated_at)
                   VALUES (?, 'author', 'Author', ?, '', '["/images/example.webp"]', 0, '', '')""",
                (work_id, work_id),
            )
            conn.execute(
                "INSERT INTO scenario_pinned_works(scenario_key,work_id,sort_order,created_at) VALUES ('ip_character', ?, ?, '')",
                (work_id, order),
            )

        def samples(payload):
            return next(item["samples"] for item in payload["items"] if item["key"] == "ip_character")

        with patch.object(conn, "execute", wraps=conn.execute) as execute:
            first, etag = get_public_home_scenarios(db, max_samples_per_scenario=1)
            self.assertEqual(len(first["items"]), 8)
            self.assertEqual(execute.call_count, 9)
            execute.reset_mock()
            self.assertEqual(get_public_home_scenarios(db, max_samples_per_scenario=1), (first, etag))
            self.assertEqual(execute.call_count, 1)
        self.assertEqual([sample["id"] for sample in samples(first)], ["scenario-first"])
        second, etag = get_public_home_scenarios(db, max_samples_per_scenario=2)
        self.assertEqual([sample["id"] for sample in samples(second)], ["scenario-first", "scenario-second"])
        conn.execute("UPDATE works SET status='hidden' WHERE id='scenario-first'")
        conn.execute("UPDATE works SET title='Updated title' WHERE id='scenario-second'")
        updated, updated_etag = get_public_home_scenarios(db, max_samples_per_scenario=2)
        self.assertNotEqual(updated_etag, etag)
        self.assertEqual([sample["title"] for sample in samples(updated)], ["Updated title"])
