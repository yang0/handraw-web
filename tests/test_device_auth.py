"""Tests for device authorization flow (T3 / R2 / R8):
1. Full flow: request -> lookup -> approve -> exchange -> auth/me
2. State machine: pending, slow_down, access_denied, expired_token, invalid_grant
3. Concurrency: atomic consumption under concurrent exchange requests
4. Security: unknown scopes, session-only boundaries, cross-user revocation prevention
5. R8 regression: Discourse-migrated legacy accounts login and authorize device
"""
from __future__ import annotations

import concurrent.futures
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
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend.server import HandrawRequestHandler
from backend import device_auth as DA
from backend.services import (
    ServiceError,
    import_discourse_users_batch,
    login_user,
    register_user,
)


class DeviceAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_ENABLE_RECHARGE": "0",
            },
        )
        self.env.start()
        self.db = open_isolated_postgres(self, seed=True)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

        self.user, _ = register_user(self.db, "device_tester", "password123", display_name="设备测试员")
        self.other_user, _ = register_user(self.db, "other_tester", "password123", display_name="其他测试员")
        DA._user_guess_fail_log.clear()
        DA._ip_guess_fail_log.clear()
        DA._ip_create_log.clear()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def _login(self, username: str) -> str:
        status, headers, _ = self.request(
            "POST",
            "/api/auth/login",
            {"account": username, "password": "password123"},
            {"Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 200)
        cookie = headers.get("Set-Cookie", "")
        return cookie.split(";", 1)[0]

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        req_headers = {"Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_01_device_code_full_happy_path(self) -> None:
        # 1. Anonymous request for device code
        status, _, raw = self.request(
            "POST",
            "/api/auth/device",
            {"clientName": "VS Code Skill Plugin", "scopes": ["publish", "library"]},
        )
        self.assertEqual(status, 200)
        init_data = json.loads(raw)
        self.assertTrue(init_data["ok"])
        device_code = init_data["deviceCode"]
        user_code = init_data["userCode"]
        self.assertEqual(init_data["expiresIn"], 600)
        self.assertEqual(init_data["interval"], 5)
        self.assertIn("view=device", init_data["verificationUrl"])
        self.assertIn(user_code, init_data["verificationUrl"])

        # Check DB only stores SHA-256 of deviceCode
        dev_hash = hashlib.sha256(device_code.encode("utf-8")).hexdigest()
        row = self.db.get_conn().execute(
            "SELECT * FROM device_codes WHERE device_code_hash = ?",
            (dev_hash,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["user_code"], user_code)
        self.assertEqual(row["status"], "pending")
        # Ensure raw device code is NOT stored anywhere in the row
        self.assertNotIn(device_code, str(dict(row)))

        # 2. Browser opens lookup page with session cookie
        session_cookie = self._login("device_tester")
        status, _, raw = self.request(
            "GET",
            f"/api/auth/device/lookup?code={user_code}",
            headers={"Cookie": session_cookie},
        )
        self.assertEqual(status, 200)
        lookup_data = json.loads(raw)
        self.assertEqual(lookup_data["clientName"], "VS Code Skill Plugin")
        self.assertEqual(lookup_data["scopes"], ["library", "publish"])
        self.assertEqual(lookup_data["status"], "pending")

        # 3. User approves the device code
        status, _, raw = self.request(
            "POST",
            "/api/auth/device/approve",
            {"code": user_code},
            headers={"Cookie": session_cookie, "Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["ok"])

        # 4. Device polls and exchanges device code for personal token
        status, _, raw = self.request(
            "POST",
            "/api/auth/device/token",
            {"deviceCode": device_code},
        )
        self.assertEqual(status, 200)
        tok_res = json.loads(raw)
        self.assertTrue(tok_res["ok"])
        token = tok_res["token"]
        self.assertTrue(token.startswith("hwt_"))
        self.assertEqual(tok_res["user"]["username"], "device_tester")
        self.assertEqual(tok_res["user"]["displayName"], "设备测试员")

        # 5. Access /api/auth/me with newly issued token
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(status, 200)
        me_data = json.loads(raw)
        self.assertEqual(me_data["username"], "device_tester")
        self.assertEqual(me_data["authKind"], "token")
        self.assertEqual(me_data["scopes"], ["library", "publish"])

    def test_02_device_state_machine_and_polling_throttling(self) -> None:
        # Create device code
        _, _, raw = self.request("POST", "/api/auth/device", {"clientName": "State Test"})
        data = json.loads(raw)
        dev_code = data["deviceCode"]
        user_code = data["userCode"]

        # 1. Pending poll -> 400 authorization_pending
        status, _, raw = self.request("POST", "/api/auth/device/token", {"deviceCode": dev_code})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)["error"], "authorization_pending")

        # 2. Rapid polling (< interval = 5s) -> 400 slow_down and interval increased to 10
        status, _, raw = self.request("POST", "/api/auth/device/token", {"deviceCode": dev_code})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)["error"], "slow_down")

        dev_hash = hashlib.sha256(dev_code.encode("utf-8")).hexdigest()
        row = self.db.get_conn().execute("SELECT interval FROM device_codes WHERE device_code_hash = ?", (dev_hash,)).fetchone()
        self.assertEqual(row["interval"], 10)

        # 3. Denied transition
        session_cookie = self._login("device_tester")
        status, _, raw = self.request(
            "POST",
            "/api/auth/device/deny",
            {"code": user_code},
            headers={"Cookie": session_cookie, "Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 200)

        # Reset last_polled_at to allow immediate poll without slow_down
        with self.db.transaction() as tx:
            tx.execute("UPDATE device_codes SET last_polled_at = '2026-10-31T00:00:00Z' WHERE device_code_hash = ?", (dev_hash,))

        status, _, raw = self.request("POST", "/api/auth/device/token", {"deviceCode": dev_code})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)["error"], "access_denied")

        # 4. Expired token
        _, _, raw_exp = self.request("POST", "/api/auth/device", {})
        dev_exp = json.loads(raw_exp)["deviceCode"]
        exp_hash = hashlib.sha256(dev_exp.encode("utf-8")).hexdigest()
        with self.db.transaction() as tx:
            tx.execute("UPDATE device_codes SET expires_at = '2020-01-01T00:00:00Z' WHERE device_code_hash = ?", (exp_hash,))

        status, _, raw = self.request("POST", "/api/auth/device/token", {"deviceCode": dev_exp})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)["error"], "expired_token")

    def test_03_atomic_concurrency_and_replay_rejection(self) -> None:
        # Create and approve device code
        _, _, raw = self.request("POST", "/api/auth/device", {"clientName": "Concurrency Test"})
        data = json.loads(raw)
        dev_code = data["deviceCode"]
        user_code = data["userCode"]

        session_cookie = self._login("device_tester")
        self.request(
            "POST",
            "/api/auth/device/approve",
            {"code": user_code},
            headers={"Cookie": session_cookie, "Origin": "http://trusted.test"},
        )

        # Reset last_polled_at
        dev_hash = hashlib.sha256(dev_code.encode("utf-8")).hexdigest()
        with self.db.transaction() as tx:
            tx.execute("UPDATE device_codes SET last_polled_at = '' WHERE device_code_hash = ?", (dev_hash,))

        # Concurrent exchange: two threads racing to exchange the same approved device code
        def exchange():
            return self.request("POST", "/api/auth/device/token", {"deviceCode": dev_code})

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(exchange)
            fut2 = executor.submit(exchange)
            res1 = fut1.result()
            res2 = fut2.result()

        results = [res1, res2]
        statuses = [r[0] for r in results]
        # Exactly one must succeed (200), and the other must fail (400)
        self.assertIn(200, statuses)
        self.assertIn(400, statuses)
        success_res = next(r for r in results if r[0] == 200)
        failed_res = next(r for r in results if r[0] == 400)
        self.assertTrue(json.loads(success_res[2])["ok"])
        self.assertIn(json.loads(failed_res[2])["error"], ("invalid_grant", "slow_down"))

        # Further exchange attempt on consumed device code returns invalid_grant
        with self.db.transaction() as tx:
            tx.execute("UPDATE device_codes SET last_polled_at = '' WHERE device_code_hash = ?", (dev_hash,))
        status, _, raw = self.request("POST", "/api/auth/device/token", {"deviceCode": dev_code})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)["error"], "invalid_grant")

    def test_04_scope_validation_and_token_boundary(self) -> None:
        # Unknown scope rejected at creation with 400
        status, _, raw = self.request(
            "POST",
            "/api/auth/device",
            {"clientName": "Hacker", "scopes": ["admin", "publish"]},
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw).get("code"), "invalid_scope")

        # Lookup and approve endpoints require session cookie; token access blocked with 403
        tok_session = self._login("device_tester")
        _, _, raw_dev = self.request("POST", "/api/auth/device", {})
        u_code = json.loads(raw_dev)["userCode"]

        # Valid token
        tok_raw = "hwt_tester_token_scope_check"
        tok_hash = hashlib.sha256(tok_raw.encode("utf-8")).hexdigest()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO api_tokens (id, user_id, name, scopes, token_hash, created_at) "
                "VALUES ('tok_scope_chk', ?, 'Test', '[\"publish\",\"library\"]', ?, '2026-10-31T00:00:00Z')",
                (self.user["id"], tok_hash),
            )

        # Lookup using token -> 403 token_scope_denied
        status, _, raw = self.request(
            "GET",
            f"/api/auth/device/lookup?code={u_code}",
            headers={"Authorization": f"Bearer {tok_raw}"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

        # Approve using token -> 403 token_scope_denied
        status, _, raw = self.request(
            "POST",
            "/api/auth/device/approve",
            {"code": u_code},
            headers={"Authorization": f"Bearer {tok_raw}", "Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

    def test_05_tokens_list_and_cross_user_revocation_prevention(self) -> None:
        cookie_user = self._login("device_tester")
        cookie_other = self._login("other_tester")

        # Create token for device_tester and other_tester
        t1_hash = hashlib.sha256(b"tok_user1").hexdigest()
        t2_hash = hashlib.sha256(b"tok_user2").hexdigest()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO api_tokens (id, user_id, name, scopes, token_hash, created_at) VALUES ('tok_u1', ?, 'U1 Laptop', '[\"publish\"]', ?, '2026-10-31T00:00:00Z')",
                (self.user["id"], t1_hash),
            )
            tx.execute(
                "INSERT INTO api_tokens (id, user_id, name, scopes, token_hash, created_at) VALUES ('tok_u2', ?, 'U2 Desktop', '[\"library\"]', ?, '2026-10-31T00:00:00Z')",
                (self.other_user["id"], t2_hash),
            )

        # device_tester lists tokens
        status, _, raw = self.request("GET", "/api/auth/tokens", headers={"Cookie": cookie_user})
        self.assertEqual(status, 200)
        tokens = json.loads(raw)["tokens"]
        self.assertTrue(any(t["id"] == "tok_u1" for t in tokens))
        self.assertFalse(any(t["id"] == "tok_u2" for t in tokens))

        # other_tester attempts to revoke device_tester's token -> 404
        status, _, raw = self.request(
            "POST",
            "/api/auth/tokens/tok_u1/revoke",
            {},
            headers={"Cookie": cookie_other, "Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 404)

        # device_tester successfully revokes own token
        status, _, raw = self.request(
            "POST",
            "/api/auth/tokens/tok_u1/revoke",
            {},
            headers={"Cookie": cookie_user, "Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["ok"])

    def test_06_r8_discourse_imported_account_device_authorization(self) -> None:
        # Import legacy Discourse PBKDF2 account
        password = "my_discourse_legacy_password"
        salt = "disc_salt_9876543210"
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 64000, dklen=32)
        disc_hash = dk.hex()

        rec = {
            "username": "legacy_disc_user",
            "email": "legacy_disc@example.com",
            "password_hash": disc_hash,
            "salt": salt,
        }
        res = import_discourse_users_batch(self.db, None, [rec])
        self.assertEqual(res["imported"], 1)

        # Verify password fields were set properly and not corrupted
        row = self.db.get_conn().execute(
            "SELECT password_hash, password_algo, discourse_salt, api_key FROM users WHERE username = 'legacy_disc_user'"
        ).fetchone()
        self.assertEqual(row["password_algo"], "discourse_pbkdf2")
        self.assertEqual(row["discourse_salt"], salt)
        self.assertEqual(row["password_hash"], disc_hash)
        self.assertFalse(bool(row["api_key"]))  # api_key is None / empty for imported user

        # Login with original password via HTTP API
        status, headers, raw = self.request(
            "POST",
            "/api/auth/login",
            {"account": "legacy_disc_user", "password": password},
            {"Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 200)
        disc_cookie = headers.get("Set-Cookie", "").split(";", 1)[0]

        # Algorithm upgraded transparently to pbkdf2_sha256
        row_after = self.db.get_conn().execute(
            "SELECT password_algo FROM users WHERE username = 'legacy_disc_user'"
        ).fetchone()
        self.assertEqual(row_after["password_algo"], "pbkdf2_sha256")

        # Now complete a device authorization as the legacy user
        _, _, raw_dev = self.request("POST", "/api/auth/device", {"clientName": "Legacy User Machine"})
        dev_info = json.loads(raw_dev)
        u_code = dev_info["userCode"]
        d_code = dev_info["deviceCode"]

        status, _, _ = self.request(
            "POST",
            "/api/auth/device/approve",
            {"code": u_code},
            headers={"Cookie": disc_cookie, "Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 200)

        # Exchange token
        status, _, raw_tok = self.request("POST", "/api/auth/device/token", {"deviceCode": d_code})
        self.assertEqual(status, 200)
        tok_data = json.loads(raw_tok)
        self.assertEqual(tok_data["user"]["username"], "legacy_disc_user")
        hwt_token = tok_data["token"]

        # Call /api/auth/me
        status, _, raw_me = self.request("GET", "/api/auth/me", headers={"Authorization": f"Bearer {hwt_token}"})
        self.assertEqual(status, 200)
        me_json = json.loads(raw_me)
        self.assertEqual(me_json["username"], "legacy_disc_user")
        self.assertEqual(me_json["authKind"], "token")

    def test_07_p2_lock_wait_expiration_fails_expired_token(self) -> None:
        # Create a code that is about to expire
        res = DA.create_device_code(self.db, "127.0.0.1", {"clientName": "P2 Test Device"})
        u_code = res["userCode"]
        d_code = res["deviceCode"]

        # 1. Test approve_device_code: simulated time inside tx is past expiration
        user_sess = {"id": self.user["id"], "_auth_kind": "session"}
        with patch("backend.device_auth.utc_now_iso", return_value="2099-01-01T00:00:00Z"):
            with self.assertRaises(ServiceError) as cm:
                DA.approve_device_code(self.db, user_sess, u_code, "127.0.0.1")
            self.assertEqual(cm.exception.code, "expired_token")

        # 2. Test exchange_device_token: approve code normally first
        DA.approve_device_code(self.db, user_sess, u_code, "127.0.0.1")
        # Then inside exchange transaction, time is past expiration
        with patch("backend.device_auth.utc_now_iso", return_value="2099-01-01T00:00:00Z"):
            with self.assertRaises(ServiceError) as cm:
                DA.exchange_device_token(self.db, {"deviceCode": d_code})
            self.assertEqual(cm.exception.code, "expired_token")

    def test_08_p3_concurrency_pending_cap_500(self) -> None:
        # Seed 499 active pending codes
        with self.db.transaction() as tx:
            for i in range(499):
                tx.execute(
                    """
                    INSERT INTO device_codes (
                        device_code_hash, user_code, client_name, scopes,
                        user_id, status, created_at, expires_at, approved_at, last_polled_at, interval
                    ) VALUES (?, ?, 'Cap Test', '["publish"]', NULL, 'pending', '2026-10-31T00:00:00Z', '2099-01-01T00:00:00Z', '', '', 5)
                    """,
                    (f"hash_cap_{i}", f"CP{i:02d}-{i:04d}"),
                )

        results = []
        errors = []

        def worker(idx: int) -> None:
            try:
                # Use distinct fake IPs so IP rate limit does not trigger
                r = DA.create_device_code(self.db, f"192.168.1.{idx + 1}", {"clientName": f"Worker {idx}"})
                results.append(r)
            except ServiceError as e:
                errors.append(e)
            finally:
                self.db.close_thread_conn()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 1 thread must succeed (bringing pending to 500), 5 threads must get 503 service_busy
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 5)
        for err in errors:
            self.assertEqual(err.status, 503)
            self.assertEqual(err.code, "service_busy")

        # Verify pending count in DB is exactly 500
        count = self.db.get_conn().execute(
            "SELECT COUNT(*) FROM device_codes WHERE status = 'pending' AND expires_at > '2020-01-01T00:00:00Z'"
        ).fetchone()[0]
        self.assertEqual(count, 500)

    def test_09_p4_dual_dimension_guess_rate_limiting(self) -> None:
        sess_a = self._login("device_tester")
        sess_b = self._login("other_tester")

        ip1 = "203.0.113.10"
        ip2 = "203.0.113.20"

        # 1. 20 failed guesses with user A from IP 1
        for i in range(20):
            status, _, raw = self.request(
                "GET",
                f"/api/auth/device/lookup?code=FAIL{i:04d}",
                headers={"Cookie": sess_a, "X-Forwarded-For": ip1},
            )
            self.assertEqual(status, 404, f"Attempt {i} should be 404, got {status}")

        # 2. Attempt 21 from IP 2 (different IP, same user A) -> 429 rate_limited
        status, _, raw = self.request(
            "GET",
            "/api/auth/device/lookup?code=FAIL9999",
            headers={"Cookie": sess_a, "X-Forwarded-For": ip2},
        )
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(raw).get("code"), "rate_limited")

        # 3. Attempt from IP 1 with user B (different user, same IP 1) -> 429 rate_limited
        status, _, raw = self.request(
            "GET",
            "/api/auth/device/lookup?code=FAIL9999",
            headers={"Cookie": sess_b, "X-Forwarded-For": ip1},
        )
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(raw).get("code"), "rate_limited")

        # 4. approve and deny also blocked when rate limited
        status, _, raw = self.request(
            "POST",
            "/api/auth/device/approve",
            {"code": "FAIL9999"},
            headers={"Cookie": sess_a, "Origin": "http://trusted.test", "X-Forwarded-For": ip2},
        )
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(raw).get("code"), "rate_limited")

        status, _, raw = self.request(
            "POST",
            "/api/auth/device/deny",
            {"code": "FAIL9999"},
            headers={"Cookie": sess_a, "Origin": "http://trusted.test", "X-Forwarded-For": ip2},
        )
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(raw).get("code"), "rate_limited")

    def test_10_p7_client_name_not_double_escaped(self) -> None:
        raw_name = '<Skill "Client" & Test>\x00\x08\x1b'
        res = DA.create_device_code(self.db, "127.0.0.1", {"clientName": raw_name})
        u_code = res["userCode"]

        row = self.db.get_conn().execute("SELECT client_name FROM device_codes WHERE user_code = ?", (u_code,)).fetchone()
        # Control characters stripped, HTML special characters preserved unescaped
        self.assertEqual(row["client_name"], '<Skill "Client" & Test>')

        user_sess = {"id": self.user["id"], "_auth_kind": "session"}
        info = DA.lookup_device_code(self.db, user_sess, "127.0.0.1", u_code)
        self.assertEqual(info["clientName"], '<Skill "Client" & Test>')

    def test_11_t2_concurrent_guess_budget_barrier_max_20_failures(self) -> None:
        DA._user_guess_fail_log.clear()
        DA._ip_guess_fail_log.clear()
        user_sess = {"id": self.user["id"], "_auth_kind": "session"}
        ip = "192.0.2.55"

        barrier = threading.Barrier(24)
        results = []
        errors = []

        def worker(idx: int) -> None:
            barrier.wait()
            try:
                DA.lookup_device_code(self.db, user_sess, ip, f"BAD{idx:04d}")
                results.append("ok")
            except ServiceError as e:
                results.append(e.code)
            except Exception as e:
                errors.append(e)
            finally:
                self.db.close_thread_conn()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 24 responses: at most 20 not_found (404), rest rate_limited (429)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 24)
        not_found_count = results.count("not_found")
        rate_limited_count = results.count("rate_limited")
        self.assertLessEqual(not_found_count, 20)
        self.assertGreaterEqual(rate_limited_count, 4)
        self.assertEqual(not_found_count + rate_limited_count, 24)

    def test_12_t2_cleanup_after_5000_ips_and_successful_query_leaves_no_keys(self) -> None:
        DA._user_guess_fail_log.clear()
        DA._ip_guess_fail_log.clear()
        DA._last_global_cleanup = 0.0

        user_sess = {"id": self.user["id"], "_auth_kind": "session"}

        # 1. Successful query must not retain keys
        res = DA.create_device_code(self.db, "127.0.0.1", {"clientName": "Test Device"})
        u_code = res["userCode"]
        info = DA.lookup_device_code(self.db, user_sess, "198.51.100.99", u_code)
        self.assertEqual(info["ok"], True)
        self.assertNotIn("198.51.100.99", DA._ip_guess_fail_log)
        self.assertNotIn(str(self.user["id"]), DA._user_guess_fail_log)

        # 2. Insert 5000 old IP keys (> 1 hour old, e.g. 2 hours ago)
        now = time.time()
        two_hours_ago = now - 7200.0
        with DA._guess_rate_lock:
            for i in range(5000):
                DA._ip_guess_fail_log[f"10.200.{i // 256}.{i % 256}"] = [two_hours_ago]
            # Simulating 2 hours later: last global cleanup was also in the past (> 60s ago)
            DA._last_global_cleanup = now - 7200.0

        self.assertEqual(len(DA._ip_guess_fail_log), 5000)

        # Trigger cleanup via a reservation on a new IP
        try:
            DA.lookup_device_code(self.db, user_sess, "10.0.0.1", "NONEXISTENT")
        except ServiceError:
            pass

        # All 5000 old keys were pruned; only at most 1 key remains
        self.assertLessEqual(len(DA._ip_guess_fail_log), 1)
