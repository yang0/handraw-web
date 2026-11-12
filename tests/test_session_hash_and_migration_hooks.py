import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.config import SESSION_COOKIE_NAME
from tests.legacy_database import Database
from tests.legacy_migrations import MIGRATIONS, POST_MIGRATION_HOOKS
from backend.security import hash_session_token
from tests.legacy_database import init_legacy_database
from backend.server import HandrawRequestHandler
from backend.services import (
    authenticate_request,
    create_session_for_user,
    login_user,
    logout_session,
    register_user,
)


class SessionHashUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.db = Database(self.db_path)
        self.db.migrate()

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.close()
        self.tmp.cleanup()

    def test_session_token_stored_as_sha256_and_auth_succeeds(self):
        conn = self.db.get_conn()
        user, _ = register_user(self.db, "testuser", "password123")
        user_row, raw_token = login_user(self.db, "testuser", "password123")

        self.assertTrue(raw_token.startswith("hws_"))
        expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        # 1. DB sessions.token stores SHA-256 hash, NOT raw token
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (expected_hash,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["token"], expected_hash)
        self.assertNotEqual(row["token"], raw_token)

        # 2. Authentication via Cookie passes with raw token
        headers = {"Cookie": f"{SESSION_COOKIE_NAME}={raw_token}"}
        auth_user = authenticate_request(self.db, headers)
        self.assertIsNotNone(auth_user)
        self.assertEqual(auth_user["id"], user["id"])
        self.assertEqual(auth_user["_session_token"], raw_token)

        # 3. Authentication via Authorization Bearer header passes with raw token
        headers_bearer = {"Authorization": f"Bearer {raw_token}"}
        auth_user_bearer = authenticate_request(self.db, headers_bearer)
        self.assertIsNotNone(auth_user_bearer)
        self.assertEqual(auth_user_bearer["id"], user["id"])
        self.assertEqual(auth_user_bearer["_session_token"], raw_token)

        # 4. Authentication via X-Handraw-Token passes with raw token
        headers_x = {"X-Handraw-Token": raw_token}
        auth_user_x = authenticate_request(self.db, headers_x)
        self.assertIsNotNone(auth_user_x)
        self.assertEqual(auth_user_x["id"], user["id"])

        # 5. Logout deletes session by hash
        logout_session(self.db, raw_token)
        remaining = conn.execute("SELECT COUNT(*) FROM sessions WHERE token = ?", (expected_hash,)).fetchone()[0]
        self.assertEqual(remaining, 0)

        # 6. Subsequent auth fails
        self.assertIsNone(authenticate_request(self.db, headers))
        self.assertIsNone(authenticate_request(self.db, headers_bearer))

    def test_raw_token_inserted_directly_is_rejected(self):
        conn = self.db.get_conn()
        user, _ = register_user(self.db, "rawuser", "password123")

        # Manually insert plain-text token
        raw_token = "hws_raw_unhashed_token_value_12345"
        now_ts = int(time.time())
        conn.execute(
            "INSERT INTO sessions (token, user_id, user_agent, ip_addr, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (raw_token, user["id"], "ua", "127.0.0.1", now_ts + 3600, "2026-11-03T00:00:00Z"),
        )

        # Trying to authenticate with this token must be rejected because server looks up sha256(raw_token)
        headers = {"Cookie": f"{SESSION_COOKIE_NAME}={raw_token}"}
        auth_user = authenticate_request(self.db, headers)
        self.assertIsNone(auth_user)

        headers_bearer = {"Authorization": f"Bearer {raw_token}"}
        self.assertIsNone(authenticate_request(self.db, headers_bearer))

    def test_migration_084_clears_legacy_plaintext_sessions(self):
        # Create a database migrating only up to 083
        with TemporaryDirectory() as tmp_legacy:
            db_path = Path(tmp_legacy) / "legacy.db"
            conn = sqlite3.connect(str(db_path), isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                """
            )
            # Apply all migrations up to 83
            for v, name, ddl in MIGRATIONS:
                if v <= 83:
                    conn.executescript(
                        f"BEGIN IMMEDIATE;\n{ddl}\n;\nINSERT INTO schema_migrations VALUES ({v}, '{name}', '2026-11-03T00:00:00Z');\nCOMMIT;"
                    )

            # Insert legacy sessions
            conn.execute(
                "INSERT INTO users (id, username, display_name, password_hash, invite_code, created_at) VALUES (1, 'u1', 'User 1', 'h', 'inv1', '2026-11-03T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO sessions (token, user_id, user_agent, ip_addr, expires_at, created_at) VALUES ('tok1', 1, '', '', 9999999999, '2026-11-03T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO sessions (token, user_id, user_agent, ip_addr, expires_at, created_at) VALUES ('tok2', 1, '', '', 9999999999, '2026-11-03T00:00:00Z')"
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 2)
            conn.close()

            # Now run migrate() on this DB
            db = Database(db_path)
            applied = db.migrate()
            self.assertIn("084_clear_legacy_plaintext_sessions", applied)

            # Verify sessions table is empty
            count = db.get_conn().execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            self.assertEqual(count, 0)
            db.close_thread_conn()
            db.close()


class MigrationHooksUnitTests(unittest.TestCase):
    def test_migration_hook_failure_rollback_and_retry(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "hooks.db"
            db = Database(db_path)

            test_version = 9999
            hook_calls = []

            def flaky_hook(conn: sqlite3.Connection):
                hook_calls.append("called")
                if len(hook_calls) == 1:
                    conn.execute("CREATE TABLE IF NOT EXISTS test_mut (id INT);")
                    conn.execute("INSERT INTO test_mut VALUES (1);")
                    raise RuntimeError("simulated hook failure on attempt 1")
                else:
                    conn.execute("CREATE TABLE IF NOT EXISTS test_mut (id INT);")
                    conn.execute("INSERT INTO test_mut VALUES (2);")

            # Temporarily register hook
            POST_MIGRATION_HOOKS[test_version] = flaky_hook
            try:
                # First run: initial migrations
                db.migrate()

                # Add dummy migration in schema_migrations
                conn = db.get_conn()
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (test_version, "9999_test_dummy", "2026-11-03T00:00:00Z"),
                )

                # Attempt 1: flaky_hook fails
                with self.assertRaises(RuntimeError) as cm:
                    db.migrate()
                self.assertIn("simulated hook failure", str(cm.exception))
                self.assertEqual(len(hook_calls), 1)

                # Check schema_migration_hooks has NO record of test_version
                hook_row = conn.execute(
                    "SELECT * FROM schema_migration_hooks WHERE version = ?", (test_version,)
                ).fetchone()
                self.assertIsNone(hook_row)

                # Verify hook mutations were rolled back
                mut_exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'test_mut'"
                ).fetchone()
                if mut_exists:
                    count = conn.execute("SELECT COUNT(*) FROM test_mut").fetchone()[0]
                    self.assertEqual(count, 0)

                # Attempt 2: flaky_hook succeeds
                db.migrate()
                self.assertEqual(len(hook_calls), 2)

                # Check schema_migration_hooks has record of test_version
                hook_row = conn.execute(
                    "SELECT * FROM schema_migration_hooks WHERE version = ?", (test_version,)
                ).fetchone()
                self.assertIsNotNone(hook_row)

                # Attempt 3: flaky_hook is NOT called again
                db.migrate()
                self.assertEqual(len(hook_calls), 2)
            finally:
                POST_MIGRATION_HOOKS.pop(test_version, None)
                db.close_thread_conn()
                db.close()

    def test_legacy_database_baseline_does_not_rerun_hooks(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy_baseline.db"
            db = Database(db_path)
            # Fully migrate to apply all schema
            db.migrate()

            conn = db.get_conn()
            # Drop schema_migration_hooks table to simulate an upgraded legacy DB
            conn.execute("DROP TABLE schema_migration_hooks;")

            # Mock all hooks to track calls
            hook_calls = {}
            orig_hooks = dict(POST_MIGRATION_HOOKS)
            try:
                # V3 removed retired hooks (including 079), so only compare
                # versions registered by the current fresh-schema code.
                hook_versions = tuple(sorted(orig_hooks))
                for v in hook_versions:
                    def make_tracker(version):
                        def _tracker(c):
                            hook_calls[version] = hook_calls.get(version, 0) + 1
                        return _tracker
                    POST_MIGRATION_HOOKS[v] = make_tracker(v)

                # Migrate again: must detect missing hooks table on existing DB and baseline
                db.migrate()

                # None of the baselined hooks should have been called!
                self.assertEqual(hook_calls, {}, "Baselined hooks must not be executed during upgrade")

                # schema_migration_hooks must contain all baselined versions
                recorded_versions = {
                    int(r["version"])
                    for r in conn.execute("SELECT version FROM schema_migration_hooks").fetchall()
                }
                for v in hook_versions:
                    self.assertIn(v, recorded_versions)
            finally:
                POST_MIGRATION_HOOKS.clear()
                POST_MIGRATION_HOOKS.update(orig_hooks)
                db.close_thread_conn()
                db.close()

    def test_fresh_database_executes_each_hook_exactly_once(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fresh.db"
            db = Database(db_path)
            db.migrate()

            conn = db.get_conn()
            completed = {
                int(r["version"])
                for r in conn.execute("SELECT version FROM schema_migration_hooks").fetchall()
            }
            # All registered hooks should be completed
            for v in POST_MIGRATION_HOOKS:
                self.assertIn(v, completed)

            # Subsequent migrate runs 0 hooks
            dummy_calls = []
            orig_hooks = dict(POST_MIGRATION_HOOKS)
            try:
                for v in POST_MIGRATION_HOOKS:
                    def make_tracker(version):
                        def _tracker(c):
                            dummy_calls.append(version)
                        return _tracker
                    POST_MIGRATION_HOOKS[v] = make_tracker(v)

                db.migrate()
                self.assertEqual(dummy_calls, [])
            finally:
                POST_MIGRATION_HOOKS.clear()
                POST_MIGRATION_HOOKS.update(orig_hooks)
                db.close_thread_conn()
                db.close()

    def test_migration_and_hook_interleaved_execution_order(self):
        from tests import legacy_migrations as migrations_module

        orig_migrations = list(migrations_module.MIGRATIONS)
        orig_hooks = dict(migrations_module.POST_MIGRATION_HOOKS)

        try:
            # ----------------------------------------------------
            # Scenario 1: Fresh DB interleaved execution:
            # Migration A -> Hook A -> Migration B -> Hook B
            # ----------------------------------------------------
            with TemporaryDirectory() as tmp1:
                db_path1 = Path(tmp1) / "interleaved_fresh.db"
                events1 = []

                fake_migrations = [
                    (
                        10,
                        "010_fake_a",
                        "CREATE TABLE IF NOT EXISTS event_log (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT); "
                        "INSERT INTO event_log (item) VALUES ('migration_a');",
                    ),
                    (
                        20,
                        "020_fake_b",
                        "CREATE TABLE IF NOT EXISTS fake_b (id INT); "
                        "INSERT INTO event_log (item) VALUES ('migration_b');",
                    ),
                ]

                def hook_a(conn):
                    events1.append("hook_a")
                    conn.execute("INSERT INTO event_log (item) VALUES ('hook_a');")

                def hook_b(conn):
                    events1.append("hook_b")
                    conn.execute("INSERT INTO event_log (item) VALUES ('hook_b');")

                migrations_module.MIGRATIONS.clear()
                migrations_module.MIGRATIONS.extend(fake_migrations)
                migrations_module.POST_MIGRATION_HOOKS.clear()
                migrations_module.POST_MIGRATION_HOOKS.update({10: hook_a, 20: hook_b})

                db1 = Database(db_path1)
                db1.migrate()

                self.assertEqual(events1, ["hook_a", "hook_b"])
                db_events1 = [
                    r[0]
                    for r in db1.get_conn().execute("SELECT item FROM event_log ORDER BY id").fetchall()
                ]
                self.assertEqual(
                    db_events1,
                    ["migration_a", "hook_a", "migration_b", "hook_b"],
                    "Execution order on fresh DB must be Migration A -> Hook A -> Migration B -> Hook B",
                )
                db1.close_thread_conn()
                db1.close()

            # ----------------------------------------------------
            # Scenario 2: Hook A fails on attempt 1:
            # - Attempt 1: Migration B does not execute.
            # - Attempt 2: Order is Hook A -> Migration B -> Hook B.
            # ----------------------------------------------------
            with TemporaryDirectory() as tmp2:
                db_path2 = Path(tmp2) / "interleaved_retry.db"
                events2 = []
                hook_a_should_fail = True

                def flaky_hook_a(conn):
                    events2.append("hook_a")
                    if hook_a_should_fail:
                        raise RuntimeError("simulated hook_a failure")
                    conn.execute("INSERT INTO event_log (item) VALUES ('hook_a');")

                def hook_b2(conn):
                    events2.append("hook_b")
                    conn.execute("INSERT INTO event_log (item) VALUES ('hook_b');")

                migrations_module.MIGRATIONS.clear()
                migrations_module.MIGRATIONS.extend(fake_migrations)
                migrations_module.POST_MIGRATION_HOOKS.clear()
                migrations_module.POST_MIGRATION_HOOKS.update({10: flaky_hook_a, 20: hook_b2})

                db2 = Database(db_path2)

                # Attempt 1: Hook A fails
                with self.assertRaises(RuntimeError) as cm:
                    db2.migrate()
                self.assertIn("simulated hook_a failure", str(cm.exception))

                conn2 = db2.get_conn()
                applied_v = [r[0] for r in conn2.execute("SELECT version FROM schema_migrations").fetchall()]
                self.assertEqual(applied_v, [10], "Only Migration A should be recorded in schema_migrations")

                hooks_v = [r[0] for r in conn2.execute("SELECT version FROM schema_migration_hooks").fetchall()]
                self.assertEqual(hooks_v, [], "Hook A must not be recorded in schema_migration_hooks upon failure")

                has_fake_b = conn2.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'fake_b'"
                ).fetchone()
                self.assertIsNone(has_fake_b, "Migration B must not have executed when Hook A failed")

                # Attempt 2: Hook A succeeds
                hook_a_should_fail = False
                events2.clear()

                db2.migrate()

                self.assertEqual(events2, ["hook_a", "hook_b"])
                db_events2 = [
                    r[0]
                    for r in conn2.execute("SELECT item FROM event_log ORDER BY id").fetchall()
                ]
                self.assertEqual(
                    db_events2,
                    ["migration_a", "hook_a", "migration_b", "hook_b"],
                    "On rerun after failure, sequence must be Hook A -> Migration B -> Hook B",
                )

                self.assertEqual(
                    [r[0] for r in conn2.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()],
                    [10, 20],
                )
                self.assertEqual(
                    [r[0] for r in conn2.execute("SELECT version FROM schema_migration_hooks ORDER BY version").fetchall()],
                    [10, 20],
                )

                db2.close_thread_conn()
                db2.close()

        finally:
            migrations_module.MIGRATIONS.clear()
            migrations_module.MIGRATIONS.extend(orig_migrations)
            migrations_module.POST_MIGRATION_HOOKS.clear()
            migrations_module.POST_MIGRATION_HOOKS.update(orig_hooks)


class SessionHashHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(root / "http_test.db"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            },
        )
        self.env.start()
        self.db = init_legacy_database(root / "http_test.db")
        register_user(self.db, "http_user", "Pass123456", display_name="HTTP User")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close_thread_conn()
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()

    def _request(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):
        hdrs = {"Origin": "http://trusted.test"}
        if headers:
            hdrs.update(headers)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                ct = resp.headers.get("Content-Type", "")
                cookie = resp.headers.get("Set-Cookie", "")
                parsed = json.loads(raw.decode("utf-8")) if "json" in ct else raw.decode("utf-8")
                return resp.status, parsed, cookie
        except urllib.error.HTTPError as err:
            raw = err.read()
            ct = err.headers.get("Content-Type", "")
            parsed = json.loads(raw.decode("utf-8")) if "json" in ct else raw.decode("utf-8")
            return err.code, parsed, ""

    def test_http_login_stores_hash_allows_me_and_logout_invalidates(self):
        # 1. Login
        status, data, cookie_hdr = self._request(
            "POST", "/api/auth/login", {"account": "http_user", "password": "Pass123456"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        raw_token = data.get("token")
        self.assertTrue(raw_token and raw_token.startswith("hws_"))
        self.assertIn("handraw_sid=", cookie_hdr)

        # 2. Check DB sessions: token column has sha256, NOT raw_token
        expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        conn = self.db.get_conn()
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (expected_hash,)).fetchone()
        self.assertIsNotNone(row)
        raw_match = conn.execute("SELECT * FROM sessions WHERE token = ?", (raw_token,)).fetchone()
        self.assertIsNone(raw_match)

        # 3. GET /api/auth/me with Cookie
        cookie_val = f"handraw_sid={raw_token}"
        me_st, me_data, _ = self._request("GET", "/api/auth/me", headers={"Cookie": cookie_val})
        self.assertEqual(me_st, 200)
        self.assertTrue(me_data.get("ok"))
        self.assertEqual(me_data["username"], "http_user")

        # 4. POST /api/auth/logout
        lo_st, lo_data, _ = self._request("POST", "/api/auth/logout", headers={"Cookie": cookie_val})
        self.assertEqual(lo_st, 200)

        # 5. Session row deleted
        row_after = conn.execute("SELECT * FROM sessions WHERE token = ?", (expected_hash,)).fetchone()
        self.assertIsNone(row_after)

        # 6. Subsequent /api/auth/me returns 401
        me2_st, me2_data, _ = self._request("GET", "/api/auth/me", headers={"Cookie": cookie_val})
        self.assertEqual(me2_st, 401)
