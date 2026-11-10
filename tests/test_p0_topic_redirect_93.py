"""#93: first-visit /t/FA-002 lazy topic creation on actual SQLite and PG.

Uses real HTTP handlers, a fresh isolated PostgreSQL 17 database when
HANDRAW_PG_STAGING_URL is provided. Never uses development/production data.
"""
from __future__ import annotations

import concurrent.futures
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import patch

from backend.server import create_channel_server, init_database


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _RedirectChecks:
    def setup_http(self):
        self.server = create_channel_server(0, "main", self.db,
                                            host="127.0.0.1")
        self.server.allow_demo_routes = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(_NoRedirect)

    def stop_http(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get_redirect(self, path):
        req = urllib.request.Request(self.base + path,
                                     headers={"Origin": "http://trusted.test"})
        try:
            with self.opener.open(req, timeout=25) as resp:
                return resp.status, resp.headers.get("Location", "")
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("Location", "")

    def stats(self, code):
        with self.db.transaction() as tx:
            mappings = tx.execute(
                "SELECT topic_id FROM curation_resource_topics WHERE kind='style' "
                "AND target_id=?", (code,)).fetchall()
            orphan = tx.execute(
                "SELECT COUNT(*) FROM forum_topics "
                "WHERE id NOT IN (SELECT topic_id FROM curation_resource_topics) "
                "AND title LIKE ?", ("%画风讨论%",)).fetchone()[0]
        return [x["topic_id"] for x in mappings], orphan

    def test_first_visit_and_repeat_redirect_without_savepoint_500(self):
        before, orphan_before = self.stats("FA-002")
        self.assertEqual(before, [], "Fresh isolated test database must not have this mapping")
        status, location = self.get_redirect("/t/FA-002")
        self.assertEqual(status, 302, (status, location))
        self.assertTrue(location.startswith("/forum/?view=topic&id="), location)
        again_status, again = self.get_redirect("/t/FA-002")
        self.assertEqual((again_status, again), (302, location))
        topics, orphans = self.stats("FA-002")
        self.assertEqual(len(topics), 1)
        self.assertIn(topics[0], location)
        self.assertEqual(orphans, orphan_before)
        self.assertEqual(self.get_redirect("/t/ST-INVALID-P0-93")[0], 404)

    def test_first_visit_concurrency_has_one_mapping_no_orphans(self):
        before, orphan_before = self.stats("FB-041")
        self.assertEqual(before, [])
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(
                self.get_redirect, ["/t/FB-041"] * 8))
        self.assertTrue(all(s == 302 for s, _ in responses), responses)
        self.assertEqual(len({target for _, target in responses}), 1, responses)
        topics, orphans = self.stats("FB-041")
        self.assertEqual(len(topics), 1)
        self.assertEqual(orphans, orphan_before)

    def test_transaction_rolls_back_topic_insert_on_failure_after_write(self):
        from backend import resource_discussions
        before, orphan_before = self.stats("FA-001")
        self.assertEqual(before, [])
        native = resource_discussions.ensure_topic
        def fail_after_insert(tx, *args, **kwargs):
            result = native(tx, *args, **kwargs)
            raise RuntimeError("P0-93 injected failure AFTER forum topic write")
        with patch.object(resource_discussions, "ensure_topic",
                          side_effect=fail_after_insert):
            status, _ = self.get_redirect("/t/FA-001")
        self.assertEqual(status, 500)
        mapping, orphan_after = self.stats("FA-001")
        self.assertEqual(mapping, [], "The transaction must roll back on failure")
        self.assertEqual(orphan_after, orphan_before,
                         "Failed redirect must leave no orphan topic")
        status, loc = self.get_redirect("/t/FA-001")
        self.assertEqual(status, 302, loc)
        self.assertEqual(len(self.stats("FA-001")[0]), 1)


class SQLiteTopicRedirect93(_RedirectChecks, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "redirect93.sqlite"),
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_DEMO_MODE": "1",
        })
        self.env.start()
        self.db = init_database(root / "redirect93.sqlite")
        self.setup_http()

    def tearDown(self):
        self.stop_http()
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"),
                     "Only isolated PostgreSQL CI environment runs live PG checks")
class PostgreSQLTopicRedirect93(_RedirectChecks, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from backend.postgres_db import PostgresDatabase
        from ops.bootstrap_postgres_v3 import bootstrap

        cls.admin_dsn = os.environ["HANDRAW_PG_STAGING_URL"]
        cls.database_name = "handraw_topic_p0_93_" + uuid.uuid4().hex[:10]
        with psycopg.connect(cls.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(cls.database_name)))
        cls.addClassCleanup(cls.drop_database)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        cls.env = patch.dict(os.environ, {
            "HANDRAW_DEMO_MODE": "0",
            "HANDRAW_ALLOW_PG_BOOTSTRAP": "YES",
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_OBJECT_BUCKET": "",
            "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_REDIS_REQUIRED": "0",
        })
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        dsn = make_conninfo(cls.admin_dsn, dbname=cls.database_name)
        bootstrap(dsn=dsn, apply=True)
        cls.db = PostgresDatabase(dsn)
        cls.db.migrate()
        cls.addClassCleanup(cls.db.close)
        cls.server = create_channel_server(0, "main", cls.db,
                                           host="127.0.0.1", demo_mode=False)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = urllib.request.build_opener(_NoRedirect)
        def close_server():
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(timeout=5)
        cls.addClassCleanup(close_server)

    @classmethod
    def drop_database(cls):
        import psycopg
        from psycopg import sql
        assert cls.database_name.startswith("handraw_topic_p0_93_")
        with psycopg.connect(cls.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                sql.Identifier(cls.database_name)))


if __name__ == "__main__":
    unittest.main()
