"""Tests for POST /api/studio/batch-plan (Phase 3b-4).

Covers:
1. Authentication: 401 when unauthenticated, 403 when using personal access token (hwt_).
2. Fixed mode layout consistency: all returned items have layout == fixedLayout; invalid fixedLayout returns 400.
3. AI layout sanitation: invalid layout codes returned by model are discarded (fallback to fixedLayout or empty).
4. Deterministic template fallback: returns source: "template" and exact count items when AI model is unconfigured/fails.
5. Rate limiting: 50 requests/day per user returns 429.
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

from backend.server import SESSION_COOKIE_NAME, HandrawRequestHandler, init_database
from backend.services import register_user


class BatchPlanRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "batch_plan_test.db"
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_AI_CONFIG": str(root / "absent-ai-service.json"),
                "HANDRAW_IMAGE_CONFIG": str(root / "absent-image-service.json"),
            },
        )
        self.env.start()
        self.db = init_database(self.db_path)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

        self.user, token = register_user(self.db, "batch_planner", "Pass123456")
        self.cookie = f"{SESSION_COOKIE_NAME}={token}"

    def _create_token(self, user_id: int, scopes: list[str]) -> str:
        raw_token = f"hwt_test_{hashlib.sha256(os.urandom(16)).hexdigest()}"
        tok_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        tok_id = f"tok_{os.urandom(8).hex()}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO api_tokens (id, user_id, name, scopes, token_hash, created_at, last_used_at, revoked_at)
                VALUES (?, ?, 'Test', ?, ?, '2026-10-31T00:00:00Z', '', '')
                """,
                (tok_id, user_id, json.dumps(scopes), tok_hash),
            )
        return raw_token

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _req(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        cookie: str | None = None,
        token: str | None = None,
    ) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Content-Type": "application/json",
            "Origin": "http://trusted.test",
        }
        if cookie:
            headers["Cookie"] = cookie
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(f"{self.base}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
                return status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                body_dict = json.loads(raw)
            except Exception:
                body_dict = {"raw": raw}
            return exc.code, body_dict

    def test_01_auth_checks(self) -> None:
        """1. Login required (401), hwt_ personal token rejected (403)."""
        # Unauthenticated -> 401
        st, res = self._req("POST", "/api/studio/batch-plan", {"seed": "都市慢生活"})
        self.assertEqual(st, 401)

        # Token auth -> 403
        hwt_token = self._create_token(self.user["id"], ["studio:create"])
        st, res = self._req("POST", "/api/studio/batch-plan", {"seed": "都市慢生活"}, token=hwt_token)
        self.assertEqual(st, 403)
        self.assertIn(res.get("code"), ("token_disallowed", "token_scope_denied"))

        # Direct service call with token user raises token_disallowed
        from backend.batch_plan_routes import execute_batch_plan
        from backend.services import ServiceError
        with self.assertRaises(ServiceError) as ctx:
            execute_batch_plan(self.db, {"id": self.user["id"], "_auth_kind": "token"}, seed="测试母题")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "token_disallowed")

    def test_02_fixed_mode_layout(self) -> None:
        """2. layoutMode: 'fixed' enforces layout == fixedLayout; invalid fixedLayout returns 400."""
        # Valid fixedLayout SC-021
        st, res = self._req(
            "POST",
            "/api/studio/batch-plan",
            {
                "seed": "治愈咖啡馆的一天",
                "count": 5,
                "layoutMode": "fixed",
                "fixedLayout": "SC-021",
                "styleId": "FA-001",
            },
            cookie=self.cookie,
        )
        self.assertEqual(st, 200)
        self.assertTrue(res.get("ok"))
        items = res.get("items", [])
        self.assertEqual(len(items), 5)
        for it in items:
            self.assertEqual(it["layout"], "SC-021")

        # Invalid fixedLayout -> 400
        st, res = self._req(
            "POST",
            "/api/studio/batch-plan",
            {
                "seed": "治愈咖啡馆的一天",
                "count": 4,
                "layoutMode": "fixed",
                "fixedLayout": "INVALID_LAYOUT_999",
            },
            cookie=self.cookie,
        )
        self.assertEqual(st, 400)
        self.assertEqual(res.get("code"), "invalid_fixed_layout")

        # Unselected / empty fixedLayout in fixed mode -> 200 with defaultLayoutUsed: true
        st, res = self._req(
            "POST",
            "/api/studio/batch-plan",
            {
                "seed": "治愈咖啡馆的一天",
                "count": 4,
                "layoutMode": "fixed",
                "fixedLayout": "",
            },
            cookie=self.cookie,
        )
        self.assertEqual(st, 200)
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("defaultLayoutUsed"))
        items_def = res.get("items", [])
        self.assertEqual(len(items_def), 4)
        def_code = items_def[0]["layout"]
        self.assertTrue(def_code, "Default layout code must not be empty")
        for it in items_def:
            self.assertEqual(it["layout"], def_code)

    def test_03_ai_invalid_layout_sanitized(self) -> None:
        """3. AI returned invalid layout codes are discarded and fall back cleanly."""
        fake_ai_response = json.dumps({
            "items": [
                {"subject": "晨光推开咖啡馆木门", "layout": "SC-021"},  # valid
                {"subject": "手冲咖啡的水流与香气", "layout": "NON_EXISTENT_LAYOUT_XYZ"},  # invalid -> fallback
                {"subject": "午后窗边翻阅旧画册", "layout": "IG-003"},  # valid
            ]
        })

        with patch("backend.batch_plan_routes.chat", return_value=(fake_ai_response, {"ok": True})):
            st, res = self._req(
                "POST",
                "/api/studio/batch-plan",
                {
                    "seed": "咖啡馆的一天",
                    "count": 3,
                    "layoutMode": "ai",
                    "fixedLayout": "SC-021",
                },
                cookie=self.cookie,
            )
            self.assertEqual(st, 200)
            self.assertEqual(res.get("source"), "model")
            items = res.get("items", [])
            self.assertEqual(len(items), 3)
            self.assertEqual(items[0]["layout"], "SC-021")
            # Invalid was sanitized to fixedLayout (SC-021) or empty
            self.assertIn(items[1]["layout"], ("SC-021", ""))
            self.assertNotEqual(items[1]["layout"], "NON_EXISTENT_LAYOUT_XYZ")
            self.assertEqual(items[2]["layout"], "IG-003")

    def test_04_template_fallback_on_unconfigured_model(self) -> None:
        """4. Fallback to deterministic template generator returning source: 'template' and exact count."""
        st, res = self._req(
            "POST",
            "/api/studio/batch-plan",
            {
                "seed": "胡同里的手艺人",
                "count": 6,
                "layoutMode": "ai",
                "layoutRequirement": "前两张分镜，后面图鉴",
            },
            cookie=self.cookie,
        )
        self.assertEqual(st, 200)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("source"), "template")
        items = res.get("items", [])
        self.assertEqual(len(items), 6)
        # Non-empty subjects, valid layout strings
        for it in items:
            self.assertTrue(it["subject"])
            self.assertTrue(it["layout"])

    def test_05_daily_quota_limit(self) -> None:
        """5. Daily quota limit 50 requests/day per user triggers 429."""
        from backend.db import local_today_str
        # Exhaust 50 requests via direct DB manipulation
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO daily_usage (user_id, scope, usage_date, count)
                VALUES (?, 'batch_plan', ?, 50)
                ON CONFLICT(user_id, scope, usage_date) DO UPDATE SET count = 50
                """,
                (self.user["id"], local_today_str()),
            )

        st, res = self._req(
            "POST",
            "/api/studio/batch-plan",
            {
                "seed": "都市慢生活",
                "count": 6,
                "layoutMode": "fixed",
                "fixedLayout": "SC-021",
            },
            cookie=self.cookie,
        )
        self.assertEqual(st, 429)
        self.assertEqual(res.get("code"), "rate_limited")


if __name__ == "__main__":
    unittest.main()
