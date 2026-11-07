"""Production storage preflight tests; no live PostgreSQL/Redis is needed."""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import redis_rate_limit
from backend.runtime_policy import check_auth_rate_limit
from backend.security import hash_password, verify_password


def load_stage_tool():
    file = Path(__file__).resolve().parent.parent / "ops" / "sqlite_to_postgres.py"
    spec = importlib.util.spec_from_file_location("handraw_pg_staging", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DummyRedis:
    def __init__(self):
        self.seen = []
    def eval(self, script, numkeys, key, window, cap):
        self.seen.append((key, window, cap))
        return int(len(self.seen) <= cap)
    def ping(self):
        return True


class RedisRateLimitTests(unittest.TestCase):
    def tearDown(self):
        redis_rate_limit._connect.cache_clear()

    def test_development_without_redis_uses_original_limiter(self):
        with patch.dict(os.environ, {"HANDRAW_REDIS_URL":"", "HANDRAW_REDIS_REQUIRED":"0"}):
            self.assertIsNone(redis_rate_limit.check_limit("login", "local-user"))
            self.assertTrue(check_auth_rate_limit("login", "unique-testing-key"))

    def test_required_redis_never_falls_back_on_missing_url(self):
        with patch.dict(os.environ, {"HANDRAW_REDIS_URL":"", "HANDRAW_REDIS_REQUIRED":"1"}):
            self.assertFalse(redis_rate_limit.check_limit("login", "alice"))
            with self.assertRaises(RuntimeError):
                redis_rate_limit.ensure_ready()

    def test_client_ip_and_account_never_enter_redis_keys(self):
        client = DummyRedis()
        with patch.dict(os.environ, {
            "HANDRAW_REDIS_URL": "redis://localhost:6379/0",
            "HANDRAW_REDIS_PREFIX": "handraw:test",
            "HANDRAW_REDIS_REQUIRED": "1"
        }), patch("backend.redis_rate_limit._connect", return_value=client):
            for _ in range(9):
                allowed = redis_rate_limit.check_limit("login", "198.51.100.9|email@example.com")
            self.assertFalse(allowed)
            self.assertEqual(len(client.seen), 9)
            self.assertEqual(client.seen[0][1:], (300, 8))
            self.assertTrue(client.seen[0][0].startswith("handraw:test:rate:login:"))
            self.assertNotIn("email@example.com", client.seen[0][0])
            self.assertNotIn("198.51.100.9", client.seen[0][0])

    @unittest.skipUnless(os.environ.get("HANDRAW_REDIS_URL"), "Real Redis not configured")
    def test_real_redis_atomic_limit_across_threads(self):
        import concurrent.futures
        import secrets
        url = os.environ["HANDRAW_REDIS_URL"]
        subject = "test-" + secrets.token_hex(16)
        with patch.dict(os.environ, {"HANDRAW_REDIS_PREFIX": "handraw:ci"}):
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                allowed = list(pool.map(
                    lambda _: redis_rate_limit.check_limit("login", subject), range(12)
                ))
        self.assertEqual(allowed.count(True), 8)
        self.assertEqual(allowed.count(False), 4)
        client = redis_rate_limit._connect(url)
        import hashlib
        key = ("handraw:ci:rate:login:" +
               hashlib.sha256(("login:" + subject).encode()).hexdigest())
        self.assertGreater(client.ttl(key), 0)
        self.assertLessEqual(client.ttl(key), 300)
        client.delete(key)

    def test_redis_outage_fails_closed_when_configured(self):
        with patch.dict(os.environ, {
            "HANDRAW_REDIS_URL": "redis://localhost:6379/0",
        }), patch("backend.redis_rate_limit._connect", side_effect=OSError("outage")):
            self.assertFalse(redis_rate_limit.check_limit("login", "alice"))


class PostgresSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "old.db"
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    email TEXT UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL DEFAULT 'Legacy',
                    password_hash TEXT NOT NULL,
                    password_algo TEXT NOT NULL DEFAULT 'pbkdf2_sha256',
                    discourse_salt TEXT NOT NULL DEFAULT '',
                    discourse_user_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'active',
                    role TEXT NOT NULL DEFAULT 'user',
                    last_login_at TEXT
                );
                CREATE TABLE sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    user_agent TEXT NOT NULL DEFAULT '',
                    ip_addr TEXT NOT NULL DEFAULT '',
                    expires_at INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT ''
                );"""
            )
            self.legacy_hash = hash_password("OldUsersPassword!")
            conn.execute(
                "INSERT INTO users(username,email,password_hash) VALUES(?,?,?)",
                ("legacy", "legacy@example.test", self.legacy_hash),
            )
            conn.execute(
                "INSERT INTO sessions(token,user_id) VALUES(?,?)",
                ("persisted-session", 1),
            )
        self.tool = load_stage_tool()

    def tearDown(self):
        import gc
        gc.collect()
        self.tmp.cleanup()

    def test_inspection_preserves_user_hashes_read_only(self):
        result = self.tool.stage(self.path, "", False)
        self.assertTrue(result["dryRun"])
        self.assertTrue(result["sourceReadOnly"])
        self.assertEqual(result["users"], 1)
        self.assertEqual(result["sessions"], 1)
        self.assertTrue(verify_password("OldUsersPassword!", self.legacy_hash))
        snap_conn, _ = self.tool.read_snapshot(self.path)
        try:
            self.assertTrue(self.tool._is_nocase_column(
                snap_conn, "users", "username"
            ))
        finally:
            snap_conn.close()
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute(
                "SELECT password_hash FROM users WHERE username='legacy'"
            ).fetchone()[0], self.legacy_hash)

    def test_missing_or_invalid_snapshot_is_refused(self):
        with self.assertRaises(ValueError):
            self.tool.stage(Path(self.tmp.name)/"missing.db", "", False)
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM users")
        with self.assertRaises(ValueError):
            self.tool.stage(self.path, "", False)

    @unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"),
                         "Isolated PostgreSQL staging URL not provided")
    def test_real_postgres_staging_preserves_login_hashes_and_casefold_uniqueness(self):
        import uuid
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        admin_dsn = os.environ["HANDRAW_PG_STAGING_URL"]
        database_name = "handraw_stage_" + uuid.uuid4().hex[:12]
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        dsn = make_conninfo(admin_dsn, dbname=database_name)
        try:
            result = self.tool.stage(self.path, dsn, True)
            self.assertTrue(result["staged"])
            self.assertEqual(result["users"], 1)
            with psycopg.connect(dsn) as pg:
                with pg.cursor() as cur:
                    cur.execute(
                        "SELECT id, username, email, password_hash FROM users WHERE username = %s",
                        ("LeGaCy",)
                    )
                    row = cur.fetchone()
                    self.assertEqual(row[0], 1)
                    self.assertEqual(row[1], "legacy")
                    self.assertTrue(verify_password("OldUsersPassword!", row[3]))
                    cur.execute("SELECT token, user_id FROM sessions")
                    self.assertEqual(cur.fetchall(), [("persisted-session", 1)])
                    # Imported user can login with their existing password:
                    # PostgreSQL adapter must create a valid session without signup.
                    from backend.postgres_db import PostgresDatabase
                    from backend.services import login_user
                    app_db = PostgresDatabase(dsn)
                    try:
                        user, session = login_user(app_db, "LeGaCy", "OldUsersPassword!")
                        self.assertEqual(user["id"], 1)
                        self.assertEqual(user["username"], "legacy")
                        self.assertTrue(session.startswith("hws_"))
                        self.assertEqual(pg.execute(
                            "SELECT COUNT(*) FROM sessions WHERE user_id=1"
                        ).fetchone()[0], 2)
                    finally:
                        app_db.close()
                    with self.assertRaises(psycopg.errors.UniqueViolation):
                        cur.execute(
                            "INSERT INTO users(username,email,password_hash) VALUES(%s,%s,%s)",
                            ("LeGaCy", "another@example.test", self.legacy_hash)
                        )
        finally:
            with psycopg.connect(admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database_name)))

    @unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL")
                         and os.environ.get("HANDRAW_PG_PARITY_TEST") == "YES",
                         "Full isolated PostgreSQL parity test is not enabled")
    def test_full_v2_schema_and_existing_user_password_on_postgresql(self):
        import uuid
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from backend.db import Database
        from backend.services import register_user, login_user
        from backend.postgres_db import PostgresDatabase

        database_name = "handraw_parity_" + uuid.uuid4().hex[:12]
        admin_dsn = os.environ["HANDRAW_PG_STAGING_URL"]
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        parity_dsn = make_conninfo(admin_dsn, dbname=database_name)
        file = Path(self.tmp.name) / "whole_v2.db"
        original = Database(file)
        try:
            original.migrate()
            account, _ = register_user(original, "existing_user", "ExistingPassword2026!",
                                       "existing-user@example.test", "旧用户昵称")
            original_id = account["id"]
            # Imported forum accounts must retain their historical login secret:
            # no re-registration or forced password change for valid old hashes.
            import hashlib
            historical_password = "OriginalForumPassword2026!"
            historical_salt = "forum-test-salt"
            historical_hash = hashlib.pbkdf2_hmac(
                "sha256", historical_password.encode(), historical_salt.encode(), 64000
            ).hex()
            historical, _ = register_user(
                original, "forum_existing", "TemporaryRegistration2026!",
                "forum-existing@example.test", "历史创作者"
            )
            historical_id = historical["id"]
            with original.transaction() as tx:
                tx.execute(
                    """UPDATE users
                       SET password_hash=?,password_algo='discourse_pbkdf2',
                           discourse_salt=?,discourse_user_id=?
                       WHERE id=?""",
                    (historical_hash, historical_salt, 991100, historical_id)
                )
        finally:
            original.close()
            import gc
            gc.collect()

        info = self.tool.stage(file, parity_dsn, True)
        self.assertTrue(info["staged"])
        self.assertGreater(info["tables"], 40)
        pg = PostgresDatabase(parity_dsn)
        try:
            pg.migrate()
            user, session = login_user(pg, "existing-user@example.test", "ExistingPassword2026!")
            self.assertEqual(user["id"], original_id)
            self.assertEqual(user["display_name"], "旧用户昵称")
            self.assertTrue(session.startswith("hws_"))
            historical_user, historical_session = login_user(
                pg, "FoRuM_ExIsTiNg", historical_password
            )
            self.assertEqual(historical_user["id"], historical_id)
            self.assertEqual(historical_user["display_name"], "历史创作者")
            self.assertTrue(historical_session.startswith("hws_"))
            updated = pg.get_conn().execute(
                "SELECT password_algo,discourse_salt FROM users WHERE id=?",
                (historical_id,)
            ).fetchone()
            self.assertEqual(updated["password_algo"], "pbkdf2_sha256")
            self.assertEqual(updated["discourse_salt"], "")
            # A new user must also be able to register *after* the migration.
            newcomer, token = register_user(pg, "new_pg_user", "BrandNewPassword2026!",
                                           "new-pg-user@example.test", "新用户昵称")
            self.assertNotEqual(newcomer["id"], original_id)
            self.assertTrue(token.startswith("hws_"))
            # Regression: authenticated boot formerly queried sqlite_master,
            # then COLLATE NOCASE, while resolving earned reviewer access.
            from backend.services import build_boot_payload
            from backend.curation import _accepted_kinds_for
            boot = build_boot_payload(pg, newcomer)
            self.assertTrue(boot["loggedIn"])
            self.assertEqual(boot["user"]["reviewAccess"]["kinds"], [])
            with pg.transaction() as tx:
                tx.execute(
                    """INSERT INTO catalog_assets
                       (code,kind,source_type,author_username,name,image_url,published_at_ms,created_at,updated_at)
                       VALUES('pg_review_style','style','community','NeW_Pg_UsEr','Test','',1,'now','now')"""
                )
                tx.execute(
                    """INSERT INTO works
                       (id,author_username,author_name,title,prompt,published_at_ms,created_at,updated_at)
                       VALUES('pg_review_work','NeW_Pg_UsEr','Test','Test','',1,'now','now')"""
                )
                self.assertEqual(_accepted_kinds_for(tx, newcomer["username"]), {"style", "work"})
                tx.execute("CREATE TABLE cold_start_registry(kind TEXT,item_id TEXT)")
                self.assertEqual(_accepted_kinds_for(tx, newcomer["username"]), {"style", "work"})
                tx.execute("INSERT INTO cold_start_registry VALUES('user',?)", (newcomer["username"],))
                self.assertEqual(_accepted_kinds_for(tx, newcomer["username"]), set())
            # Concurrent PG transactions must not overspend a wallet or mint
            # a duplicate ledger entry. Each thread owns a pooled connection.
            from concurrent.futures import ThreadPoolExecutor
            from backend.services import apply_wallet_delta, ServiceError
            initial = int(pg.get_conn().execute(
                "SELECT balance FROM wallets WHERE user_id=?", (newcomer["id"],)
            ).fetchone()["balance"])
            def spend(i):
                try:
                    with pg.transaction() as tx:
                        apply_wallet_delta(
                            tx, newcomer["id"], -1, "pg_parity_spend",
                            "PG concurrent wallet test", event_key=f"pg-parity-{i}"
                        )
                    return True
                except ServiceError as exc:
                    if exc.code == "insufficient_credits":
                        return False
                    raise
                finally:
                    pg.close_thread_conn()
            attempts = initial + 5
            with ThreadPoolExecutor(max_workers=6) as pool:
                verdicts = list(pool.map(spend, range(attempts)))
            self.assertEqual(verdicts.count(True), initial)
            self.assertEqual(verdicts.count(False), 5)
            self.assertEqual(pg.get_conn().execute(
                "SELECT balance FROM wallets WHERE user_id=?", (newcomer["id"],)
            ).fetchone()["balance"], 0)
            self.assertEqual(pg.get_conn().execute(
                "SELECT COUNT(*) FROM ledgers WHERE user_id=? AND kind='pg_parity_spend'",
                (newcomer["id"],)
            ).fetchone()[0], initial)
        finally:
            pg.close()
            with psycopg.connect(admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database_name)))

    @unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL staging URL not provided")
    def test_batch_post_and_work_details_on_postgresql(self):
        import uuid
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from backend.db import Database
        from backend.postgres_db import PostgresDatabase
        from tests.test_batch_detail_order import seed_batch_detail, assert_batch_detail_order
        snapshot = Path(self.tmp.name) / 'batch_detail.db'
        source = Database(snapshot)
        with patch.dict(os.environ, {'HANDRAW_DEMO_MODE': '0'}):
            try:
                source.migrate()
                seed_batch_detail(source)
            finally:
                source.close()
            admin_dsn = os.environ['HANDRAW_PG_STAGING_URL']
            name = 'handraw_batch_' + uuid.uuid4().hex[:12]
            with psycopg.connect(admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            pg = None
            try:
                dsn = make_conninfo(admin_dsn, dbname=name)
                self.tool.stage(snapshot, dsn, True)
                pg = PostgresDatabase(dsn)
                pg.migrate()
                # These routes must remain reads, including on a real PG connection.
                pg.get_conn()._db.execute('SET default_transaction_read_only=on')
                assert_batch_detail_order(self, pg)
            finally:
                if pg:
                    pg.close()
                with psycopg.connect(admin_dsn, autocommit=True) as admin:
                    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

    def test_fk_violations_cannot_migrate(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)", ("orphan", 999))
        with self.assertRaises(ValueError):
            self.tool.stage(self.path, "", False)


if __name__ == "__main__":
    unittest.main()
