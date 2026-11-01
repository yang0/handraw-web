"""Tests for /api/studio/parse-article endpoint and document parser:
- Authentication requirement (401)
- Rate limiting per user: 20/day (429)
- Payload size limit: 10MB (413)
- AI status and fallback reporting (aiUsed, fallbackReason, truncated)
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from backend.document_parser import parse_article_file
from backend.server import HandrawRequestHandler, init_database
from backend.services import register_user


class StudioArticleParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "parse_test.db"
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                # These tests assert the no-key fallback path, so they must not
                # pick up a real ai-service.json sitting in the repo root.
                "HANDRAW_AI_CONFIG": str(root / "absent-ai-service.json"),
                "HANDRAW_IMAGE_CONFIG": str(root / "absent-image-service.json"),
            },
        )
        self.env.start()
        self.db = init_database(self.db_path)
        register_user(self.db, "parse_tester", "password123")

        self.httpd = urllib.request.http.server.ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)  # type: ignore[attr-defined]
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close_thread_conn()
        self.db.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, headers: dict[str, str] | None = None):
        req_headers = {"Accept": "application/json", "Origin": "http://trusted.test"}
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

    def login(self, username: str = "parse_tester") -> str:
        status, headers, body_bytes = self.request(
            "POST",
            "/api/auth/login",
            {"account": username, "password": "password123"},
        )
        self.assertEqual(status, 200, f"Login failed: {body_bytes.decode('utf-8', errors='ignore')}")
        return headers.get("Set-Cookie", "").split(";", 1)[0]

    def test_unauthenticated_request_returns_401(self):
        status, _, raw = self.request(
            "POST",
            "/api/studio/parse-article",
            {"text": "Hello world", "fileName": "test.txt"},
        )
        self.assertEqual(status, 401)
        data = json.loads(raw.decode("utf-8"))
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("code"), "login_required")

    def test_authenticated_request_succeeds_without_ai_key(self):
        cookie = self.login()
        status, _, raw = self.request(
            "POST",
            "/api/studio/parse-article",
            {"text": "# 我的设计草案\n\n这是正文内容测试。", "fileName": "design.md"},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("title"), "我的设计草案")
        self.assertIn("这是正文内容测试", data.get("markdown", ""))
        self.assertIs(data.get("aiUsed"), False)
        self.assertEqual(data.get("fallbackReason"), "no_key")

    def test_payload_too_large_returns_413(self):
        cookie = self.login()
        # Create data exceeding 10MB
        oversized = "A" * (10 * 1024 * 1024 + 1024)
        status, _, raw = self.request(
            "POST",
            "/api/studio/parse-article",
            {"text": oversized, "fileName": "huge.txt"},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 413)
        data = json.loads(raw.decode("utf-8"))
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("code"), "payload_too_large")

    def test_user_rate_limit_exceeded_returns_429(self):
        user_a, _ = register_user(self.db, "rate_user_a", "password123")
        cookie_a = self.login("rate_user_a")
        # Send 20 requests that succeed (the limit is 20 per day)
        for i in range(20):
            status, _, raw = self.request(
                "POST",
                "/api/studio/parse-article",
                {"text": f"# 文章第 {i} 篇\n\n正文内容测试。", "fileName": f"doc_{i}.txt"},
                headers={"Cookie": cookie_a},
            )
            self.assertEqual(status, 200, f"Request {i+1} should succeed, got status {status}")

        # The 21st request should be rate-limited (429)
        status, _, raw = self.request(
            "POST",
            "/api/studio/parse-article",
            {"text": "# 第 21 篇\n\n正文", "fileName": "doc_21.txt"},
            headers={"Cookie": cookie_a},
        )
        self.assertEqual(status, 429)
        data = json.loads(raw.decode("utf-8"))
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("code"), "rate_limited")

        # 另一个用户不受影响
        register_user(self.db, "rate_user_b", "password123")
        cookie_b = self.login("rate_user_b")
        status_b, _, _ = self.request(
            "POST",
            "/api/studio/parse-article",
            {"text": "# 用户B文章\n\n正文", "fileName": "user_b.txt"},
            headers={"Cookie": cookie_b},
        )
        self.assertEqual(status_b, 200, "Another user should not be affected by user A's limit")

        # 服务重启（新建 Database 实例）后用户 A 的计数仍然持久化存在
        from backend.db import Database
        from backend.services import consume_daily_usage
        restarted_db = Database(self.db_path)
        try:
            allowed = consume_daily_usage(restarted_db, user_a["id"], "parse", 20)
            self.assertFalse(allowed, "Count should persist in DB across server restarts")
        finally:
            restarted_db.close_thread_conn()
            restarted_db.close()

        # 换日期（monkeypatch local_today_str）后用户 A 又能使用
        with patch("backend.services.local_today_str", return_value="2099-12-31"):
            status_new_day, _, _ = self.request(
                "POST",
                "/api/studio/parse-article",
                {"text": "# 新日期文章\n\n正文", "fileName": "doc_new_day.txt"},
                headers={"Cookie": cookie_a},
            )
            self.assertEqual(status_new_day, 200, "User should be able to parse again on a new day")

    def test_truncation_sets_truncated_flag(self):
        long_text = "# 超长文章\n\n" + ("很长的文本内容段落。" * 4000)
        res = parse_article_file(long_text.encode("utf-8"), "long.md")
        self.assertTrue(res.get("truncated"))
        self.assertIn("[正文文本过长，已截断]", res.get("markdown", ""))


if __name__ == "__main__":
    unittest.main()
