"""Tests for POST /api/studio/article-plan (Phase 3b-5).

Covers:
1. Authentication: 401 when unauthenticated, 403 when using personal access token (hwt_).
2. Rate limiting: 30 requests/day per user returns 429 with Chinese message.
3. Empty body: when blocks has no body elements, returns only cover and illustrations: [].
4. Template fallback: returns source: "template" with expected anchors (2, 4, 6 on Article F1).
5. Model validation robustness (Acceptance B8):
   - Out-of-bounds block indices discarded
   - Duplicate block indices deduplicated
   - > 6 illustrations capped at 6
   - Nonexistent layout codes reset to ""
   - Missing cover completed via template
6. Block truncation: > 200 blocks truncated with "blocks_truncated" warning.
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

F1_BLOCKS = [
    {"idx": 0, "kind": "h1", "text": "留白工作法"},
    {"idx": 1, "kind": "p", "text": "当我们把日历塞满会议时，大脑失去了呼吸缝隙。"},
    {"idx": 2, "kind": "h2", "text": "一、塞满的日程表"},
    {"idx": 3, "kind": "p", "text": "现代职场最大的幻觉，是把响应速度当成产出质量。"},
    {"idx": 4, "kind": "h2", "text": "二、像画水彩一样管理精力"},
    {"idx": 5, "kind": "p", "text": "桑贝的画里总有大片空白。"},
    {"idx": 6, "kind": "h2", "text": "三、每日微停顿仪式"},
    {"idx": 7, "kind": "p", "text": "离开屏幕，下楼走两条街。"},
]


class ArticlePlanRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "article_plan_test.db"
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_AI_CONFIG": str(root / "absent-ai-service.json"),
                "HANDRAW_AI_API_KEY": "",  # Unconfigured by default
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

        self.user, token = register_user(self.db, "article_planner", "Pass123456")
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
        self.thread.join(timeout=2.0)
        self.db.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def _post(self, path: str, payload: dict, cookie: str | None = None, token: str | None = None) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base}{path}", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Origin", "http://trusted.test")
        if cookie:
            req.add_header("Cookie", cookie)
        if token:
            req.add_header("Authorization", f"Bearer {token}")

        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def test_auth_and_token_scope_denied(self) -> None:
        payload = {"title": "测试文章", "blocks": F1_BLOCKS}

        # 1. Unauthenticated -> 401
        status, body = self._post("/api/studio/article-plan", payload)
        self.assertEqual(status, 401)
        self.assertEqual(body.get("code"), "login_required")

        # 2. Token auth (hwt_ token) -> 403 token_disallowed / token_scope_denied
        hwt_token = self._create_token(self.user["id"], ["studio:write"])
        status, body = self._post("/api/studio/article-plan", payload, token=hwt_token)
        self.assertEqual(status, 403)
        self.assertIn(body.get("code"), ("token_disallowed", "token_scope_denied"))

        # Direct service call with token user raises token_disallowed
        from backend.article_plan_routes import execute_article_plan
        from backend.services import ServiceError
        with self.assertRaises(ServiceError) as ctx:
            execute_article_plan(
                self.db,
                {"id": self.user["id"], "_auth_kind": "token"},
                article_id="art_1",
                title="测试文章",
                blocks=F1_BLOCKS
            )
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "token_disallowed")

    def test_rate_limiting_30_per_day(self) -> None:
        payload = {"title": "留白工作法", "blocks": F1_BLOCKS}

        # First 30 calls must succeed (status 200)
        for i in range(30):
            status, body = self._post("/api/studio/article-plan", payload, cookie=self.cookie)
            self.assertEqual(status, 200, f"Call {i+1} should succeed")
            self.assertTrue(body.get("ok"))

        # 31st call must be 429
        status, body = self._post("/api/studio/article-plan", payload, cookie=self.cookie)
        self.assertEqual(status, 429)
        self.assertEqual(body.get("code"), "rate_limited")
        self.assertIn("今日文章规划次数已达上限（30 次/天）", body.get("error", ""))

    def test_empty_body_only_returns_cover(self) -> None:
        # Title only, blocks has only h1
        payload = {
            "title": "仅有标题的文章",
            "blocks": [{"idx": 0, "kind": "h1", "text": "仅有标题的文章"}],
            "includeCover": True
        }
        status, body = self._post("/api/studio/article-plan", payload, cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertIsNotNone(body.get("cover"))
        self.assertEqual(body.get("illustrations"), [])

    def test_template_fallback_on_unconfigured_model(self) -> None:
        payload = {
            "title": "留白工作法",
            "blocks": F1_BLOCKS,
            "charCount": 2400,
            "includeCover": True
        }
        status, body = self._post("/api/studio/article-plan", payload, cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("source"), "template")
        self.assertIsNotNone(body.get("cover"))
        self.assertIn("《留白工作法》", body["cover"]["subject"])

        ills = body.get("illustrations", [])
        self.assertGreaterEqual(len(ills), 3)
        # Check anchors: F1 h2 blocks are at idx 2, 4, 6
        self.assertEqual([item["afterBlockIdx"] for item in ills[:3]], [2, 4, 6])
        self.assertEqual(ills[0]["anchorText"], "一、塞满的日程表")

    def test_model_validation_robustness(self) -> None:
        """Test B8: out-of-bounds discarded, duplicates deduped, >6 capped, invalid layout reset to '', missing cover filled."""
        fake_ai_output = json.dumps({
            "articleType": "narrative",
            # Cover deliberately missing to test template fill
            "illustrations": [
                # 1. Valid item
                {"afterBlockIdx": 2, "subject": "插图A", "purpose": "阐释1", "layout": "SC-001", "imageType": "concept"},
                # 2. Duplicate afterBlockIdx (2) -> must be deduplicated
                {"afterBlockIdx": 2, "subject": "插图A重复", "purpose": "阐释1重复", "layout": "SC-001"},
                # 3. Out-of-bounds idx (99, -1, 500) -> must be discarded
                {"afterBlockIdx": 99, "subject": "越界图99", "layout": "SC-001"},
                {"afterBlockIdx": -1, "subject": "越界图-1", "layout": "SC-001"},
                # 4. Invalid layout ("FAKE-999") -> layout must be reset to ""
                {"afterBlockIdx": 4, "subject": "插图B", "purpose": "阐释2", "layout": "FAKE-999", "imageType": "process"},
                # 5. More items to exceed 6 total
                {"afterBlockIdx": 1, "subject": "插图C", "layout": "SC-006"},
                {"afterBlockIdx": 3, "subject": "插图D", "layout": "SC-020"},
                {"afterBlockIdx": 5, "subject": "插图E", "layout": "SC-021"},
                {"afterBlockIdx": 6, "subject": "插图F", "layout": "SC-023"},
                {"afterBlockIdx": 7, "subject": "插图G", "layout": "IG-001"},  # 7th valid item -> must be capped
            ]
        })

        with patch("backend.article_plan_routes.load_skill_prompts", return_value="MOCK SKILL PROMPTS"), \
             patch("backend.article_plan_routes.chat", return_value=(fake_ai_output, {"ok": True})):

            payload = {
                "title": "留白工作法",
                "blocks": F1_BLOCKS,
                "includeCover": True
            }
            status, body = self._post("/api/studio/article-plan", payload, cookie=self.cookie)
            self.assertEqual(status, 200)
            self.assertTrue(body.get("ok"))
            self.assertEqual(body.get("source"), "model")
            self.assertEqual(body.get("articleType"), "narrative")

            # Missing cover was completed by template
            self.assertIsNotNone(body.get("cover"))
            self.assertIn("留白工作法", body["cover"]["subject"])

            ills = body.get("illustrations", [])
            # 7 items produced, but max 6 illustrations allowed
            self.assertEqual(len(ills), 6)

            # Deduplication: block 2 only appears once
            indices = [it["afterBlockIdx"] for it in ills]
            self.assertEqual(len(indices), len(set(indices)), "Block indices must be unique")
            self.assertNotIn(99, indices, "Out-of-bounds block 99 must be discarded")
            self.assertNotIn(-1, indices, "Out-of-bounds block -1 must be discarded")

            # Ascending sort verified
            self.assertEqual(indices, sorted(indices), "Illustrations must be sorted ascending by block index")

            # Nonexistent layout FAKE-999 on block 4 reset to ""
            item4 = next(it for it in ills if it["afterBlockIdx"] == 4)
            self.assertEqual(item4["layout"], "", "Invalid layout must be reset to empty string")

            # anchorText must be re-extracted from genuine blocks
            item2 = next(it for it in ills if it["afterBlockIdx"] == 2)
            self.assertEqual(item2["anchorText"], "一、塞满的日程表")

    def test_block_truncation_warning(self) -> None:
        many_blocks = [{"idx": i, "kind": "p", "text": f"段落内容 {i}"} for i in range(250)]
        payload = {"title": "超长文章", "blocks": many_blocks}
        status, body = self._post("/api/studio/article-plan", payload, cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertIn("blocks_truncated", body.get("warnings", []))


if __name__ == "__main__":
    unittest.main()
