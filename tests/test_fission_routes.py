"""Tests for POST /api/studio/fission (Phase 3b-2).

Covers:
1. Login required (401 on unauthenticated).
2. Personal access token rejection (403 on hwt_ token).
3. Seed validation (400 on empty seed).
4. Template fallback when AI model is unconfigured or returns ok=False.
5. AI model expansion when chat returns ok=True (line parsing, strip numbering, deduplication).
6. Daily quota enforcement (50/day per user -> 429).
7. Count parameter clamping (1-50, default 10).
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


class FissionRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "fission_test.db"
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

        self.user, token = register_user(self.db, "fission_user", "Pass123456")
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
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode("utf-8"))
                return status, payload
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {"error": str(exc)}
            return exc.code, payload

    def test_login_required(self) -> None:
        status, body = self._req("POST", "/api/studio/fission", {"seed": "都市慢生活"})
        self.assertEqual(status, 401)
        self.assertFalse(body.get("ok"))

    def test_token_denied(self) -> None:
        raw_token = self._create_token(self.user["id"], ["publish", "library"])
        status, body = self._req("POST", "/api/studio/fission", {"seed": "都市慢生活"}, token=raw_token)
        self.assertEqual(status, 403)
        self.assertFalse(body.get("ok"))

    def test_empty_seed_validation(self) -> None:
        status, body = self._req("POST", "/api/studio/fission", {"seed": "   "}, cookie=self.cookie)
        self.assertEqual(status, 400)
        self.assertIn("母题不能为空", body.get("error", ""))

    def test_fallback_to_template_when_no_ai(self) -> None:
        status, body = self._req(
            "POST",
            "/api/studio/fission",
            {"seed": "春日踏青手账", "strategy": "daily_quote", "count": 5},
            cookie=self.cookie,
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("source"), "template")
        items = body.get("items")
        self.assertIsInstance(items, list)
        self.assertEqual(len(items), 5)
        self.assertTrue(all("春日踏青手账" in item for item in items))

    def test_ai_expansion_success(self) -> None:
        mock_ai_output = (
            "1. 街角咖啡馆橱窗前沐浴晨光的慵懒橘猫\n"
            "2. 细雨淅沥的青石板小巷撑油纸伞的背影\n"
            "* 翻开手账本记录今日第一口热可可的微甜\n"
            "4. 街角咖啡馆橱窗前沐浴晨光的慵懒橘猫\n"  # duplicate
            "5. 暮色渐浓时暖黄街灯下的旧书摊寻宝\n"
        )
        with patch("backend.fission_routes.chat", return_value=(mock_ai_output, {"ok": True, "reason": "", "elapsed_ms": 100})):
            status, body = self._req(
                "POST",
                "/api/studio/fission",
                {"seed": "城市角落的温暖记忆", "strategy": "daily_quote", "count": 3},
                cookie=self.cookie,
            )
            self.assertEqual(status, 200)
            self.assertTrue(body.get("ok"))
            self.assertEqual(body.get("source"), "model")
            items = body.get("items")
            self.assertEqual(len(items), 3)
            # Duplicate was filtered and list markers stripped
            self.assertEqual(items[0], "街角咖啡馆橱窗前沐浴晨光的慵懒橘猫")
            self.assertEqual(items[1], "细雨淅沥的青石板小巷撑油纸伞的背影")
            self.assertEqual(items[2], "翻开手账本记录今日第一口热可可的微甜")

    def test_count_clamped(self) -> None:
        status, body = self._req(
            "POST",
            "/api/studio/fission",
            {"seed": "测试母题", "strategy": "story_beats", "count": 999},
            cookie=self.cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(body.get("items")), 50)

    def test_daily_rate_limit_50(self) -> None:
        # User consumes 49 times
        for _ in range(49):
            status, body = self._req(
                "POST",
                "/api/studio/fission",
                {"seed": "测试母题", "strategy": "daily_quote", "count": 1},
                cookie=self.cookie,
            )
            self.assertEqual(status, 200)

        # 50th request succeeds
        status, body = self._req(
            "POST",
            "/api/studio/fission",
            {"seed": "测试母题", "strategy": "daily_quote", "count": 1},
            cookie=self.cookie,
        )
        self.assertEqual(status, 200)

        # 51st request fails with 429
        status, body = self._req(
            "POST",
            "/api/studio/fission",
            {"seed": "测试母题", "strategy": "daily_quote", "count": 1},
            cookie=self.cookie,
        )
        self.assertEqual(status, 429)
        self.assertIn("今日母题裂变次数已达上限", body.get("error", ""))


if __name__ == "__main__":
    unittest.main()
