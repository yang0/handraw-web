"""Home scenario query and cache contracts in an isolated PostgreSQL database."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

from backend import home_scenarios as scenarios
from backend.home_scenarios import get_public_home_scenarios, invalidate_scenarios_cache
from tests.postgres_support import isolated_pg_dsn


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL staging URL not provided")
class TestHomeScenariosPostgres(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("HANDRAW_REDIS_URL"), "Isolated Redis URL not provided")
    def test_shared_payload_reuses_postgres_result_across_processes(self):
        from backend.postgres_db import PostgresDatabase

        dsn = self.enterContext(isolated_pg_dsn())
        db = PostgresDatabase(dsn)
        self.addCleanup(db.close)
        conn = db.get_conn()
        prefix = f"handraw:scenario-test:{uuid.uuid4().hex}"
        self.enterContext(patch.dict(os.environ, {
            "HANDRAW_REDIS_PREFIX": prefix, "HANDRAW_DATABASE_URL": dsn, "HANDRAW_DEMO_MODE": "0",
        }))
        redis = scenarios._scenario_redis_client(os.environ["HANDRAW_REDIS_URL"])
        def clear_redis():
            keys = list(redis.scan_iter(match=prefix + ":*"))
            if keys:
                redis.delete(*keys)
        self.addCleanup(clear_redis)
        for order in range(2):
            work_id = f"shared-sample-{order}"
            conn.execute("""
                INSERT INTO works(id, author_username, author_name, title, prompt, images_json,
                                  published_at_ms, created_at, updated_at)
                VALUES (?, 'author', 'Author', ?, '', '["/images/example.webp"]', 0, '', '')
            """, (work_id, work_id))
            conn.execute("""
                INSERT INTO scenario_pinned_works(scenario_key, work_id, sort_order, created_at)
                VALUES ('ip_character', ?, ?, '')
            """, (work_id, order))

        date = "2026-11-12"
        with patch.object(conn, "execute", wraps=conn.execute) as execute:
            first, etag = get_public_home_scenarios(db, date, 1)
            self.assertEqual(execute.call_count, 9)
        child = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", """
import json
import os
from unittest.mock import patch
from backend.home_scenarios import get_public_home_scenarios
from backend.postgres_db import PostgresDatabase
db = PostgresDatabase(os.environ["HANDRAW_DATABASE_URL"])
try:
    conn = db.get_conn()
    with patch.object(conn, "execute", wraps=conn.execute) as execute:
        payload, etag = get_public_home_scenarios(db, "2026-11-12", 1)
    print(json.dumps([payload, etag, execute.call_count], ensure_ascii=False))
finally:
    db.close()
"""],
            check=True, capture_output=True, encoding="utf-8", timeout=15,
        )
        self.assertEqual(json.loads(child.stdout), [first, etag, 1])

        def first_card(payload):
            return next(item for item in payload["items"] if item["key"] == "ip_character")["samples"][0]["id"]

        peer = PostgresDatabase(dsn)
        self.addCleanup(peer.close)
        self.assertEqual(first_card(first), "shared-sample-0")
        conn.execute("UPDATE scenario_pinned_works SET sort_order = -1 WHERE work_id = 'shared-sample-1'")
        invalidate_scenarios_cache()
        reordered, _ = get_public_home_scenarios(peer, date, 1)
        self.assertEqual(first_card(reordered), "shared-sample-1")
        conn.execute("UPDATE works SET status = 'hidden' WHERE id = 'shared-sample-1'")
        safe, _ = get_public_home_scenarios(db, date, 1)
        self.assertEqual(first_card(safe), "shared-sample-0")

        _, _, key = scenarios._scenario_cache_keys(date, conn, 1, False)
        redis.set(key, '{"ok":true,"dateKey":"2026-11-12","total":1,"items":[{"samples":[{}]}]}', ex=120)
        with patch.object(peer.get_conn(), "execute", wraps=peer.get_conn().execute) as execute:
            self.assertEqual(get_public_home_scenarios(peer, date, 1)[0], safe)
            self.assertEqual(execute.call_count, 9)
        redis.pexpire(key, 0)
        with patch.object(conn, "execute", wraps=conn.execute) as execute:
            self.assertEqual(get_public_home_scenarios(db, date, 1)[0], safe)
            self.assertEqual(execute.call_count, 9)
        with patch.object(redis, "get", side_effect=ConnectionError("isolated Redis failure")):
            with patch.object(conn, "execute", wraps=conn.execute) as execute:
                self.assertEqual(get_public_home_scenarios(db, date, 1)[0], safe)
                self.assertEqual(execute.call_count, 9)

        another_db = PostgresDatabase(self.enterContext(isolated_pg_dsn()))
        self.addCleanup(another_db.close)
        _, _, other_key = scenarios._scenario_cache_keys(date, another_db.get_conn(), 1, False)
        _, _, other_date = scenarios._scenario_cache_keys("2026-11-13", conn, 1, False)
        _, _, other_limit = scenarios._scenario_cache_keys(date, conn, 2, False)
        _, _, demo_key = scenarios._scenario_cache_keys(date, conn, 1, True)
        self.assertEqual(len({key, other_key, other_date, other_limit, demo_key}), 5)
        isolated, _ = get_public_home_scenarios(another_db, date, 1)
        self.assertTrue(all(not item["samples"] for item in isolated["items"]))

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
