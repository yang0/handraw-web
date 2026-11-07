"""First-visit topic creation, including real PostgreSQL transaction boundaries."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from unittest.mock import patch

from backend import resource_discussions
from backend.db import Database
from backend.server import create_channel_server


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RedirectCases:
    def request(self, path):
        opener = urllib.request.build_opener(NoRedirect)
        try:
            response = opener.open(self.base + path, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.code, response.headers, response.read()

    def test_first_resource_visit_and_repeat(self):
        for code, kind in (("FA-002", "style"), ("SC-021", "layout")):
            with self.subTest(code=code):
                self.assertIsNone(self.db.get_conn().execute(
                    "SELECT topic_id FROM curation_resource_topics WHERE kind=? AND target_id=?", (kind, code)
                ).fetchone())
                status, headers, _ = self.request("/t/" + code + "?focus=comment")
                self.assertEqual(status, 302)
                destination = headers["Location"]
                topic_id = urllib.parse.parse_qs(urllib.parse.urlsplit(destination).query)["id"][0]
                self.assertIn("focus=comment", destination)
                self.assertEqual(self.request("/t/" + code)[1]["Location"], "/forum/?view=topic&id=" + topic_id)
                self.assertEqual(self.request(destination)[0], 200)
                status, _, body = self.request("/api/posts/" + topic_id)
                self.assertEqual(status, 200, body)
                self.assertEqual(self.db.get_conn().execute(
                    "SELECT COUNT(*) FROM curation_resource_topics WHERE kind=? AND target_id=?", (kind, code)
                ).fetchone()[0], 1)

    def test_first_work_visit_uses_transaction(self):
        work_id = "work_redirect_transaction"
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO works
                (id,author_username,author_name,title,prompt,published_at_ms,created_at,updated_at,status)
                VALUES (?,?,?,?,?,1,?,?,'published')""",
                (work_id, "redirect_author", "测试作者", "事务测试作品", "", "2026-11-07T00:00:00Z", "2026-11-07T00:00:00Z"))
        status, headers, _ = self.request("/t/work-" + work_id)
        self.assertEqual(status, 302)
        self.assertTrue(headers["Location"].startswith("/forum/?view=topic&id=topic_"))
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM forum_topics WHERE work_id=?", (work_id,)
        ).fetchone()[0], 1)

    def test_failed_creation_rolls_back_both_rows(self):
        original = resource_discussions.ensure_topic
        before = self.db.get_conn().execute("SELECT COUNT(*) FROM forum_topics").fetchone()[0]
        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected transaction failure")
        with patch.object(resource_discussions, "ensure_topic", side_effect=fail_after_insert):
            status, _, body = self.request("/t/FA-003")
        self.assertEqual(status, 500)
        self.assertNotIn(b"injected transaction failure", body)
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM forum_topics").fetchone()[0], before)
        self.assertIsNone(self.db.get_conn().execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind='style' AND target_id='FA-003'"
        ).fetchone())
        self.assertEqual(self.request("/t/FA-003")[0], 302, "Rolled-back first visit must be retryable")

    def test_unknown_reference_remains_404(self):
        self.assertEqual(self.request("/t/NOT-A-REAL-RESOURCE")[0], 404)

    @classmethod
    def start_server(cls):
        cls.server = create_channel_server(0, "main", cls.db, host="127.0.0.1", demo_mode=False)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def stop_server(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.db.close()


class SQLiteRedirectTests(RedirectCases, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"})
        cls.environment.start()
        cls.temp = tempfile.TemporaryDirectory()
        cls.db = Database(Path(cls.temp.name) / "redirect.db")
        cls.db.migrate()
        cls.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        cls.temp.cleanup()
        cls.environment.stop()


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL admin URL not provided")
class PostgresRedirectTests(RedirectCases, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from backend.postgres_db import PostgresDatabase
        from ops.bootstrap_postgres_v3 import bootstrap
        cls.admin_dsn = os.environ["HANDRAW_PG_STAGING_URL"]
        cls.database_name = "handraw_redirect_test_" + uuid.uuid4().hex[:12]
        with psycopg.connect(cls.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database_name)))
        cls.addClassCleanup(cls.drop_database)
        dsn = make_conninfo(cls.admin_dsn, dbname=cls.database_name)
        cls.environment = patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0", "HANDRAW_ALLOW_PG_BOOTSTRAP": "YES"})
        cls.environment.start()
        cls.addClassCleanup(cls.environment.stop)
        bootstrap(dsn=dsn, apply=True)
        cls.db = PostgresDatabase(dsn)
        cls.addClassCleanup(cls.db.close)
        cls.db.migrate()
        cls.start_server()
        cls.addClassCleanup(cls.stop_server)

    @classmethod
    def drop_database(cls):
        import psycopg
        from psycopg import sql
        # Only the explicitly created, random test database may be removed.
        assert cls.database_name.startswith("handraw_redirect_test_")
        with psycopg.connect(cls.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.database_name)))

    def test_concurrent_creation_preserves_callers_transaction(self):
        barrier = threading.Barrier(2)
        resource = resource_discussions.resolve_resource(self.db.get_conn(), "style", "FA-004")
        class SynchronizedConnection:
            def __init__(self, conn):
                self.conn = conn
                self.first = True
            def execute(self, query, params=()):
                cursor = self.conn.execute(query, params)
                if self.first and query.startswith("SELECT topic_id, origin FROM curation_resource_topics"):
                    self.first = False
                    barrier.wait(5)  # Both initial lookups must observe no mapping.
                return cursor
        def create(index):
            try:
                with self.db.transaction() as tx:
                    tx.execute("INSERT INTO site_settings (key,value_json,updated_at) VALUES (?,?,?)",
                               ("redirect_outer_" + str(index), "{}", "2026-11-07T00:00:00Z"))
                    return resource_discussions.ensure_topic(SynchronizedConnection(tx), "style", "FA-004", resource)
            finally:
                self.db.close_thread_conn()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            topics = list(pool.map(create, (1, 2)))
        self.assertEqual(topics[0], topics[1])
        conn = self.db.get_conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM forum_topics WHERE styles_json=?", ('["FA-004"]',)).fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM site_settings WHERE key IN (?,?)",
                                      ("redirect_outer_1", "redirect_outer_2")).fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM curation_resource_topics WHERE target_id='FA-004'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
