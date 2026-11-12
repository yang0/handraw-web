from tests.postgres_support import open_isolated_postgres
import hashlib
import json
import os
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
from backend.security import hash_session_token
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
        self.db = open_isolated_postgres(self)
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





class SessionHashHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            },
        )
        self.env.start()
        self.db = open_isolated_postgres(self, seed=True)
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
