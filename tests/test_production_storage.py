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
                    password_hash TEXT NOT NULL,
                    discourse_salt TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id)
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
        self.tmp.cleanup()

    def test_inspection_preserves_user_hashes_read_only(self):
        result = self.tool.stage(self.path, "", False)
        self.assertTrue(result["dryRun"])
        self.assertTrue(result["sourceReadOnly"])
        self.assertEqual(result["users"], 1)
        self.assertEqual(result["sessions"], 1)
        self.assertTrue(verify_password("OldUsersPassword!", self.legacy_hash))
        self.assertTrue(self.tool._is_nocase_column(
            self.tool.read_snapshot(self.path)[0], "users", "username"
        ))
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
        import psycopg
        dsn = os.environ["HANDRAW_PG_STAGING_URL"]
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
                with self.assertRaises(psycopg.errors.UniqueViolation):
                    cur.execute(
                        "INSERT INTO users(username,email,password_hash) VALUES(%s,%s,%s)",
                        ("LeGaCy", "another@example.test", self.legacy_hash)
                    )

    def test_fk_violations_cannot_migrate(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)", ("orphan", 999))
        with self.assertRaises(ValueError):
            self.tool.stage(self.path, "", False)


if __name__ == "__main__":
    unittest.main()
