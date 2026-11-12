"""Tests for personal access tokens (T2 / R1):
1. Whitelist routes and table-driven default-deny
2. Bearer and Cookie precedence and fallback prevention
3. Deprecation of legacy Api-Key / User-Api-Key / hwk_ headers
4. Token last_used_at throttled updates
5. Token revocation
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend.server import HandrawRequestHandler
from backend.services import register_user


class ApiTokensTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "tokens_test.db"
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

        # Seed test users: regular user and admin user
        self.user, _ = register_user(self.db, "token_user", "password123")
        self.admin, _ = register_user(self.db, "admin_user", "password123")
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin["id"],))

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def _create_token(self, user_id: int, scopes: list[str], name: str = "TestToken") -> str:
        raw_token = f"hwt_test_{hashlib.sha256(os.urandom(16)).hexdigest()}"
        tok_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        tok_id = f"tok_{os.urandom(8).hex()}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO api_tokens (id, user_id, name, scopes, token_hash, created_at, last_used_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, '2026-10-31T00:00:00Z', '', '')
                """,
                (tok_id, user_id, name, json.dumps(scopes), tok_hash),
            )
        return raw_token

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

    def test_01_token_auth_me_success(self) -> None:
        tok = self._create_token(self.user["id"], ["publish"])
        status, _, raw = self.request("GET", "/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertEqual(data["username"], "token_user")
        self.assertEqual(data["authKind"], "token")
        self.assertEqual(data["scopes"], ["publish"])
        self.assertNotIn("apiKey", data)
        self.assertNotIn("email", data)
        self.assertNotIn("balance", data)

    def test_02_default_deny_table_driven_on_publish_token(self) -> None:
        pub_tok = self._create_token(self.user["id"], ["publish"])
        headers = {"Authorization": f"Bearer {pub_tok}", "Origin": "http://trusted.test"}

        # Table-driven rejection list: all must return 403 token_scope_denied
        denied_endpoints = [
            ("GET", "/api/boot", None),
            ("GET", "/api/studio/workspace", None),
            ("GET", "/api/works", None),
            ("DELETE", "/api/works/FA-001", None),
            ("GET", "/api/auth/profile", None),
            ("POST", "/api/auth/profile", {"bio": "new bio"}),
            ("POST", "/api/wallet/checkin", {}),
            ("POST", "/api/collections/toggle", {"bucket": "styles", "id": "FA-001"}),
            ("GET", "/api/forum/topics", None),
            ("POST", "/api/forum/topics", {"title": "test", "content": "content"}),
            ("GET", "/api/curation/submissions", None),
            ("POST", "/api/studio/generate", {"prompt": "sketch"}),
            ("GET", "/api/admin/users", None),
            ("GET", "/api/forum/resources/style/FA-001", None),  # Pre-router dispatch module
        ]

        for method, path, body in denied_endpoints:
            with self.subTest(method=method, path=path):
                status, _, raw = self.request(method, path, body=body, headers=headers)
                self.assertEqual(status, 403, f"{method} {path} should be 403, got {status}: {raw.decode('utf-8', 'ignore')}")
                data = json.loads(raw)
                self.assertEqual(data.get("code"), "token_scope_denied")

    def test_03_admin_token_cannot_access_admin_endpoints(self) -> None:
        admin_tok = self._create_token(self.admin["id"], ["publish", "library"])
        headers = {"Authorization": f"Bearer {admin_tok}", "Origin": "http://trusted.test"}

        status, _, raw = self.request("GET", "/api/admin/users", headers=headers)
        self.assertEqual(status, 403)
        data = json.loads(raw)
        self.assertEqual(data.get("code"), "token_scope_denied")

    def test_04_scope_separation_publish_vs_library(self) -> None:
        lib_tok = self._create_token(self.user["id"], ["library"])
        pub_tok = self._create_token(self.user["id"], ["publish"])

        # Library token:
        # /studio/api/library allowed
        status, _, raw = self.request("GET", "/studio/api/library", headers={"Authorization": f"Bearer {lib_tok}"})
        self.assertEqual(status, 200)

        # /api/skill/library allowed
        status, _, _ = self.request("GET", "/api/skill/library", headers={"Authorization": f"Bearer {lib_tok}"})
        self.assertEqual(status, 200)

        # /api/uploads NOT allowed with library token -> 403
        status, _, raw = self.request("POST", "/api/uploads", body={"data": "test"}, headers={"Authorization": f"Bearer {lib_tok}"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

        # /api/entries and /api/works NOT allowed with library token -> 403
        status, _, raw = self.request("POST", "/api/entries", body={"entry": {}}, headers={"Authorization": f"Bearer {lib_tok}"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

        status, _, raw = self.request("POST", "/api/works", body={"title": "test"}, headers={"Authorization": f"Bearer {lib_tok}"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

        # Publish token:
        # /studio/api/library NOT allowed -> 403
        status, _, raw = self.request("GET", "/studio/api/library", headers={"Authorization": f"Bearer {pub_tok}"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

    def test_05_bearer_precedence_and_no_fallback_on_invalid_bearer(self) -> None:
        session_cookie = self._login("token_user")

        # When session cookie only, /api/auth/me succeeds with authKind = "session"
        status, _, raw = self.request("GET", "/api/auth/me", headers={"Cookie": session_cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["authKind"], "session")

        # When valid Bearer + valid Cookie are both present: Bearer takes precedence
        tok = self._create_token(self.user["id"], ["publish"])
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {tok}", "Cookie": session_cookie},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["authKind"], "token")

        # When Bearer is invalid + Cookie is valid: must NOT fall back to Cookie!
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": "Bearer hwt_invalid_nonexistent_token", "Cookie": session_cookie},
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw).get("code"), "login_required")

    def test_06_legacy_api_key_deprecation(self) -> None:
        # Legacy Api-Key / User-Api-Key / hwk_ headers cannot authenticate
        legacy_key = "hwk_some_old_secret_key"
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET api_key = ? WHERE id = ?", (legacy_key, self.user["id"]))

        # 1. Api-Key header
        status, _, _ = self.request("GET", "/api/auth/me", headers={"Api-Key": legacy_key})
        self.assertEqual(status, 401)

        # 2. User-Api-Key header
        status, _, _ = self.request("GET", "/api/auth/me", headers={"User-Api-Key": legacy_key})
        self.assertEqual(status, 401)

        # 3. hwk_ Bearer token
        status, _, _ = self.request("GET", "/api/auth/me", headers={"Authorization": f"Bearer {legacy_key}"})
        self.assertEqual(status, 401)

        # 4. hwk_ in X-Handraw-Token
        status, _, _ = self.request("GET", "/api/auth/me", headers={"X-Handraw-Token": legacy_key})
        self.assertEqual(status, 401)

    def test_07_token_revocation(self) -> None:
        tok = self._create_token(self.user["id"], ["publish"])
        status, _, _ = self.request("GET", "/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        self.assertEqual(status, 200)

        # Revoke the token
        with self.db.transaction() as tx:
            tx.execute("UPDATE api_tokens SET revoked_at = '2026-10-31T01:00:00Z' WHERE token_hash = ?", (hashlib.sha256(tok.encode("utf-8")).hexdigest(),))

        # Access with revoked token returns 401
        status, _, raw = self.request("GET", "/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw).get("code"), "login_required")

    def test_08_last_used_at_throttling(self) -> None:
        tok = self._create_token(self.user["id"], ["publish"])
        tok_hash = hashlib.sha256(tok.encode("utf-8")).hexdigest()

        # First request updates last_used_at
        status, _, _ = self.request("GET", "/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        self.assertEqual(status, 200)
        row1 = self.db.get_conn().execute("SELECT last_used_at FROM api_tokens WHERE token_hash = ?", (tok_hash,)).fetchone()
        t1 = row1["last_used_at"]
        self.assertTrue(bool(t1))

        # Immediate second request should NOT update last_used_at (< 5 min)
        status, _, _ = self.request("GET", "/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        self.assertEqual(status, 200)
        row2 = self.db.get_conn().execute("SELECT last_used_at FROM api_tokens WHERE token_hash = ?", (tok_hash,)).fetchone()
        self.assertEqual(row2["last_used_at"], t1)

    def test_09_casing_matrix_and_never_fallback_to_cookie(self) -> None:
        valid_cookie = self._login("token_user")
        pub_tok = self._create_token(self.user["id"], ["publish"])

        # P1 matrix for Authorization header variants
        auth_header_names = ["Authorization", "authorization", "AUTHORIZATION", "aUtHoRiZaTiOn"]
        auth_cases = [
            ("invalid", "Bearer hwt_invalid_nonexistent_token", "unauthenticated"),
            ("valid_restricted", f"Bearer {pub_tok}", "restricted_token"),
            ("empty_bearer_space", "Bearer ", "unauthenticated"),
            ("empty_bearer_only", "Bearer", "unauthenticated"),
            ("empty_string", "", "unauthenticated"),
            ("basic_auth", "Basic dXNlcjpwYXNz", "unauthenticated"),
        ]

        for hdr_name in auth_header_names:
            for case_label, hdr_val, expected_outcome in auth_cases:
                with self.subTest(hdr=hdr_name, case=case_label):
                    headers = {hdr_name: hdr_val, "Cookie": valid_cookie}
                    if expected_outcome == "unauthenticated":
                        # /api/auth/me returns 401
                        status, _, raw = self.request("GET", "/api/auth/me", headers=headers)
                        self.assertEqual(status, 401, f"{hdr_name}: {hdr_val} should be 401, got {status}")
                        # /api/boot returns 200 with loggedIn=false (never falls back to Cookie)
                        status_boot, _, raw_boot = self.request("GET", "/api/boot", headers=headers)
                        self.assertEqual(status_boot, 200)
                        boot_data = json.loads(raw_boot)
                        self.assertFalse(boot_data.get("loggedIn", False), f"Cookie must not be used when {hdr_name} is present")
                    elif expected_outcome == "restricted_token":
                        # /api/auth/me returns 200 with authKind="token"
                        status, _, raw = self.request("GET", "/api/auth/me", headers=headers)
                        self.assertEqual(status, 200)
                        self.assertEqual(json.loads(raw).get("authKind"), "token")
                        # /api/boot returns 403 token_scope_denied (because token identity is used, not Cookie session)
                        status_boot, _, raw_boot = self.request("GET", "/api/boot", headers=headers)
                        self.assertEqual(status_boot, 403, f"{hdr_name}: {hdr_val} should result in 403 on /api/boot")
                        self.assertEqual(json.loads(raw_boot).get("code"), "token_scope_denied")

        # P1 matrix for X-Handraw-Token header variants
        x_header_names = ["X-Handraw-Token", "x-handraw-token", "X-HANDRAW-TOKEN", "x-HaNdRaW-tOkEn"]
        x_cases = [
            ("invalid", "hwt_invalid_nonexistent_token", "unauthenticated"),
            ("valid_restricted", pub_tok, "restricted_token"),
            ("empty_string", "", "unauthenticated"),
        ]

        for hdr_name in x_header_names:
            for case_label, hdr_val, expected_outcome in x_cases:
                with self.subTest(hdr=hdr_name, case=case_label):
                    headers = {hdr_name: hdr_val, "Cookie": valid_cookie}
                    if expected_outcome == "unauthenticated":
                        status, _, raw = self.request("GET", "/api/auth/me", headers=headers)
                        self.assertEqual(status, 401, f"{hdr_name}: {hdr_val} should be 401, got {status}")
                        status_boot, _, raw_boot = self.request("GET", "/api/boot", headers=headers)
                        self.assertEqual(status_boot, 200)
                        self.assertFalse(json.loads(raw_boot).get("loggedIn", False))
                    elif expected_outcome == "restricted_token":
                        status, _, raw = self.request("GET", "/api/auth/me", headers=headers)
                        self.assertEqual(status, 200)
                        self.assertEqual(json.loads(raw).get("authKind"), "token")
                        status_boot, _, raw_boot = self.request("GET", "/api/boot", headers=headers)
                        self.assertEqual(status_boot, 403)
                        self.assertEqual(json.loads(raw_boot).get("code"), "token_scope_denied")

        # P1 matrix for Api-Key header variants
        api_key_header_names = ["Api-Key", "api-key", "API-KEY", "aPi-kEy"]
        api_key_cases = [
            ("invalid", "hwt_invalid_nonexistent_token", "unauthenticated"),
            ("valid_restricted", pub_tok, "restricted_token"),
            ("valid_restricted_bearer", f"Bearer {pub_tok}", "restricted_token"),
            ("empty_string", "", "unauthenticated"),
        ]

        for hdr_name in api_key_header_names:
            for case_label, hdr_val, expected_outcome in api_key_cases:
                with self.subTest(hdr=hdr_name, case=case_label):
                    headers = {hdr_name: hdr_val, "Cookie": valid_cookie}
                    if expected_outcome == "unauthenticated":
                        status, _, raw = self.request("GET", "/api/auth/me", headers=headers)
                        self.assertEqual(status, 401, f"{hdr_name}: {hdr_val} should be 401, got {status}")
                        status_boot, _, raw_boot = self.request("GET", "/api/boot", headers=headers)
                        self.assertEqual(status_boot, 200)
                        self.assertFalse(json.loads(raw_boot).get("loggedIn", False))
                    elif expected_outcome == "restricted_token":
                        status, _, raw = self.request("GET", "/api/auth/me", headers=headers)
                        self.assertEqual(status, 200)
                        self.assertEqual(json.loads(raw).get("authKind"), "token")
                        status_boot, _, raw_boot = self.request("GET", "/api/boot", headers=headers)
                        self.assertEqual(status_boot, 403)
                        self.assertEqual(json.loads(raw_boot).get("code"), "token_scope_denied")

    def test_10_p8_personal_library_client_rejects_legacy_key(self) -> None:
        import sys
        addon_scripts = str(Path(__file__).resolve().parent.parent / "skill-addon" / "scripts")
        if addon_scripts not in sys.path:
            sys.path.insert(0, addon_scripts)
        from personal_library import Client

        profile_dir = Path(self.temp_dir.name) / "skill_profile_p8"
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "community_auth.json").write_text(
            json.dumps({"base_url": "https://handraw-style.com", "username": "test", "api_key": "hwk_old"}),
            encoding="utf-8",
        )
        with patch("personal_library.home", return_value=profile_dir):
            client = Client()
            with self.assertRaises(ValueError) as cm:
                client.fetch("/studio/api/library")
            self.assertIn("同步密钥已停用，请运行 login 重新绑定设备", str(cm.exception))

    def test_11_multi_header_conflict_rejection(self) -> None:
        tok1 = self._create_token(self.user["id"], ["publish"], name="Tok1")
        tok2 = self._create_token(self.user["id"], ["publish"], name="Tok2")

        # 1. Authorization and Api-Key with conflicting tokens -> 401
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {tok1}", "Api-Key": tok2},
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw).get("code"), "login_required")

        # 2. Authorization and X-Handraw-Token with conflicting tokens -> 401
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {tok1}", "X-Handraw-Token": tok2},
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw).get("code"), "login_required")

        # 3. X-Handraw-Token and Api-Key with conflicting tokens -> 401
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"X-Handraw-Token": tok1, "Api-Key": tok2},
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw).get("code"), "login_required")

        # 4. Malformed Authorization (Basic) + valid Api-Key -> 401
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": "Basic dXNlcjpwYXNz", "Api-Key": tok1},
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw).get("code"), "login_required")

        # 5. Empty Authorization + valid Api-Key -> 401
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": "Bearer ", "Api-Key": tok1},
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw).get("code"), "login_required")

        # 6. Valid Authorization + empty Api-Key -> 401
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {tok1}", "Api-Key": ""},
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw).get("code"), "login_required")

        # 7. Agreeing headers (Authorization + Api-Key with identical token) -> 200
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {tok1}", "Api-Key": tok1},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw).get("authKind"), "token")

        # 8. Agreeing headers (Authorization + X-Handraw-Token with identical token) -> 200
        status, _, raw = self.request(
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {tok1}", "X-Handraw-Token": tok1},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw).get("authKind"), "token")

    def test_12_api_key_publish_endpoints_and_scope_enforcement(self) -> None:
        pub_tok = self._create_token(self.user["id"], ["publish"])
        lib_tok = self._create_token(self.user["id"], ["library"])

        # 1. Publish work via POST /api/works with Api-Key only (no cookie, no origin) -> 200
        work_body = {
            "title": "API Key 发布的测试作品",
            "prompt": "一只可爱的橘猫在太阳下打滚",
            "notes": "这是详细的创作说明用于通过字数校验",
            "images": ["/images/individual/FA/FA-013.webp"],
        }
        status, _, raw = self.request(
            "POST",
            "/api/works",
            body=work_body,
            headers={"Api-Key": pub_tok},
        )
        self.assertEqual(status, 200, f"POST /api/works should succeed: {raw.decode('utf-8', 'ignore')}")
        data = json.loads(raw)
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("workId"))

        # 2. Publish entry via POST /api/entries with Api-Key only -> 200
        entry_body = {
            "entry": {
                "title": "Skill 条目作品",
                "prompt": "水墨山水画提示词正文",
                "originalRequest": "画一幅远山近水图画风FA013",
                "images": ["/images/individual/FA/FA-013.webp"],
                "styleIds": ["FA-013"],
                "layoutId": "SC-001",
                "requestId": "skill-req-apikey-1",
            }
        }
        status, _, raw = self.request(
            "POST",
            "/api/entries",
            body=entry_body,
            headers={"Api-Key": pub_tok},
        )
        self.assertEqual(status, 200, f"POST /api/entries should succeed: {raw.decode('utf-8', 'ignore')}")
        data = json.loads(raw)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("kind"), "work")
        self.assertTrue(data.get("id"))

        # 3. Content validation cannot be bypassed: POST /api/works without notes -> 400
        invalid_work = {
            "title": "无创作说明作品",
            "prompt": "提示词",
            "notes": "",
        }
        status, _, raw = self.request(
            "POST",
            "/api/works",
            body=invalid_work,
            headers={"Api-Key": pub_tok},
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw).get("code"), "notes_required")

        # 4. Token without publish scope (library token) -> 403 on POST /api/works and POST /api/entries
        status, _, raw = self.request(
            "POST",
            "/api/works",
            body=work_body,
            headers={"Api-Key": lib_tok},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

        status, _, raw = self.request(
            "POST",
            "/api/entries",
            body=entry_body,
            headers={"Api-Key": lib_tok},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

        # 5. Non-publish methods / admin routes are rejected with 403
        status, _, raw = self.request(
            "GET",
            "/api/works",
            headers={"Api-Key": pub_tok},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

        status, _, raw = self.request(
            "DELETE",
            "/api/works/some-id",
            headers={"Api-Key": pub_tok},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(raw).get("code"), "token_scope_denied")

        # 6. Invalid token returns 401
        status, _, raw = self.request(
            "POST",
            "/api/entries",
            body=entry_body,
            headers={"Api-Key": "hwt_nonexistent_token"},
        )
        self.assertEqual(status, 401)
