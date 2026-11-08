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

    def test_03_ai_invalid_layout_rejected_without_fallback(self) -> None:
        """Invalid AI layout must fail rather than silently adopting fixedLayout."""
        fake_ai_response = json.dumps({"items": [
            {"subject": "晨光推开咖啡馆木门", "layout": "SC-021"},
            {"subject": "手冲咖啡的水流与香气", "layout": "NON_EXISTENT_LAYOUT_XYZ"},
            {"subject": "午后窗边翻阅旧画册", "layout": "IG-003"},
        ]})
        with patch("backend.batch_plan_routes.chat", return_value=(fake_ai_response, {"ok": True})):
            st, res = self._req("POST", "/api/studio/batch-plan", {
                "seed": "咖啡馆的一天", "count": 3,
                "layoutMode": "ai", "fixedLayout": "SC-021",
            }, cookie=self.cookie)
        self.assertEqual(st, 502)
        self.assertEqual(res.get("code"), "batch_plan_ai_invalid")

    def test_04_no_ai_fallback_on_unconfigured_model(self) -> None:
        """Without model there is no pretend recommendation or default SC layout."""
        st, res = self._req("POST", "/api/studio/batch-plan", {
            "seed": "胡同里的手艺人", "count": 6,
            "layoutMode": "ai", "layoutRequirement": "前两张分镜，后面图鉴",
        }, cookie=self.cookie)
        self.assertEqual(st, 503)
        self.assertEqual(res.get("code"), "batch_plan_ai_unavailable")

    def test_06_all_layouts_available_without_few_shot(self) -> None:
        """Every actual catalog entry, including beyond 40, is supplied to the model."""
        layouts = {f"USR-L{i:03d}": f"自定义图型{i}" for i in range(75)}
        response = json.dumps({"items": [{"subject": "显微镜下的叶片脉络", "layout": "USR-L074"}]})
        captured = []

        def fake_chat(messages, **kwargs):
            captured.extend(messages)
            return response, {"ok": True}

        with patch("backend.batch_plan_routes.get_valid_layout_map", return_value=layouts), \
             patch("backend.batch_plan_routes.chat", side_effect=fake_chat):
            st, res = self._req("POST", "/api/studio/batch-plan", {
                "seed": "植物显微观察", "count": 1, "layoutMode": "ai",
            }, cookie=self.cookie)
        self.assertEqual(st, 200)
        self.assertEqual(res["items"][0]["layout"], "USR-L074")
        self.assertEqual(len(captured), 2)
        self.assertIn("USR-L074", captured[1]["content"])
        self.assertIn("USR-L000", captured[1]["content"])
        self.assertNotIn("SC-001", captured[1]["content"])
        self.assertNotIn("SC-006", captured[1]["content"])
        self.assertNotIn("例如", captured[1]["content"])
        self.assertNotIn('{"items":', captured[1]["content"])

    def test_07_ai_incomplete_response_does_not_pad_templates(self) -> None:
        response = json.dumps({"items": [{"subject": "第一张", "layout": "SC-021"}]})
        with patch("backend.batch_plan_routes.chat", return_value=(response, {"ok": True})):
            st, res = self._req("POST", "/api/studio/batch-plan", {
                "seed": "两张不同主题", "count": 2, "layoutMode": "ai",
            }, cookie=self.cookie)
        self.assertEqual(st, 502)
        self.assertEqual(res.get("code"), "batch_plan_ai_invalid")

    def test_gateway_escape_envelope_is_validated_as_model_plan(self) -> None:
        payload = json.dumps({"items": [{"subject": "秋日咖啡香", "layout": "SC-021"}]})
        for response in (payload, f"```json\n{payload}\n```", f"<escape>{payload}</escape>",
                         f"<escape>```json\n{payload}\n```</escape>"):
            with self.subTest(response=response), patch(
                "backend.batch_plan_routes.chat", return_value=(response, {"ok": True})
            ) as model:
                st, res = self._req("POST", "/api/studio/batch-plan", {
                    "seed": "秋日咖啡", "count": 1, "layoutMode": "ai",
                }, cookie=self.cookie)
                self.assertEqual(st, 200)
                self.assertEqual(res["source"], "model")
                self.assertEqual(res["items"], json.loads(payload)["items"])
                self.assertTrue(model.call_args.kwargs["json_mode"])

    def test_wrapped_invalid_layout_still_fails(self) -> None:
        response = '<escape>{"items":[{"subject":"秋日咖啡香","layout":"NOT_A_LAYOUT"}]}</escape>'
        with patch("backend.batch_plan_routes.chat", return_value=(response, {"ok": True})), \
             self.assertLogs("backend.batch_plan_routes", level="WARNING") as logs:
            st, res = self._req("POST", "/api/studio/batch-plan", {
                "seed": "秋日咖啡", "count": 1, "layoutMode": "ai",
            }, cookie=self.cookie)
        self.assertEqual(st, 502)
        self.assertEqual(res["code"], "batch_plan_ai_invalid")
        self.assertIn("stage=invalid_items", "\n".join(logs.output))
        self.assertNotIn("NOT_A_LAYOUT", "\n".join(logs.output))

    def test_catalog_label_requires_matching_code_and_name(self) -> None:
        catalog = {"USR-L074": "生活方式场景图"}
        for label, expected in (("USR-L074：生活方式场景图", 200),
                                ("usr-l074: 生活方式场景图", 200),
                                ("USR-L074：另一个图型的名字", 502),
                                ("UNKNOWN：生活方式场景图", 502)):
            response = "<escape>" + json.dumps({"items": [{"subject": "咖啡馆", "layout": label}]}) + "</escape>"
            with self.subTest(label=label), patch("backend.batch_plan_routes.get_valid_layout_map", return_value=catalog), \
                 patch("backend.batch_plan_routes.chat", return_value=(response, {"ok": True})):
                st, res = self._req("POST", "/api/studio/batch-plan", {
                    "seed": "秋日咖啡", "count": 1, "layoutMode": "ai",
                }, cookie=self.cookie)
                self.assertEqual(st, expected)
                if st == 200:
                    self.assertEqual(res["items"][0]["layout"], "USR-L074")

    def test_malformed_output_logs_stage_without_private_content(self) -> None:
        response = "private-model-response-do-not-log"
        with patch("backend.batch_plan_routes.chat", return_value=(response, {"ok": True})), \
             self.assertLogs("backend.batch_plan_routes", level="WARNING") as logs:
            st, res = self._req("POST", "/api/studio/batch-plan", {
                "seed": "private-input-do-not-log", "count": 1, "layoutMode": "ai",
            }, cookie=self.cookie)
        self.assertEqual(st, 502)
        self.assertIn("格式无法解析", res["error"])
        self.assertTrue(res.get("requestId"))
        logged = "\n".join(logs.output)
        self.assertIn("stage=invalid_json", logged)
        self.assertNotIn(response, logged)
        self.assertNotIn("private-input-do-not-log", logged)

    def test_upstream_timeout_has_distinct_message(self) -> None:
        with patch("backend.batch_plan_routes.chat", return_value=("", {"ok": False, "reason": "timeout"})), \
             self.assertLogs("backend.batch_plan_routes", level="WARNING") as logs:
            st, res = self._req("POST", "/api/studio/batch-plan", {
                "seed": "秋日咖啡", "count": 1, "layoutMode": "ai",
            }, cookie=self.cookie)
        self.assertEqual(st, 503)
        self.assertEqual(res["code"], "batch_plan_ai_unavailable")
        self.assertIn("响应超时", res["error"])
        self.assertIn("stage=upstream reason=timeout", "\n".join(logs.output))

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


    def test_08_ai_distinct_themes_choose_distant_catalog_items_no_first_n_bias(self) -> None:
        """#88: replay distinct subjects on full catalog; don't bias by first N."""
        allowed = {f"USR-L{i:03d}": f"主题图型 {i}" for i in range(91)}
        choices = [("植物显微图鉴", "USR-L090"), ("都市街头分镜", "USR-L071")]
        prompts = []

        def model(messages, **kwargs):
            self.assertTrue(kwargs["json_mode"])
            self.assertEqual(len(messages), 2, "No few-shot examples allowed")
            text = messages[1]["content"]
            prompts.append(text)
            self.assertIn("USR-L000", text)
            self.assertIn("USR-L090", text)
            self.assertNotIn('{"items":', text)
            expected = next(code for subject, code in choices if subject in text)
            return json.dumps({"items": [
                {"subject": "分镜主题: " + expected, "layout": expected}
            ]}), {"ok": True}

        with patch("backend.batch_plan_routes.get_valid_layout_map", return_value=allowed), \
             patch("backend.batch_plan_routes.get_layout_descriptions", return_value={}), \
             patch("backend.batch_plan_routes.chat", side_effect=model):
            results = []
            for subject, code in choices:
                status, result = self._req("POST", "/api/studio/batch-plan", {
                    "seed": subject, "count": 1, "layoutMode": "ai",
                }, cookie=self.cookie)
                self.assertEqual(status, 200, result)
                self.assertEqual(result["source"], "model")
                self.assertEqual(result["items"][0]["layout"], code)
                results.append(result["items"][0]["layout"])
        self.assertEqual(results, ["USR-L090", "USR-L071"])
        self.assertEqual(len(prompts), 2)
        for prompt in prompts:
            self.assertNotIn("SC-001", prompt)
            self.assertNotIn("SC-006", prompt)

    def test_09_ai_gateway_errors_do_not_impersonate_success(self) -> None:
        """#90: upstream HTTP 502, non-JSON and invalid items remain explicit."""
        from backend.batch_plan_routes import parse_batch_plan_response

        for response in ("前言 {\"items\": []} 后记",
                         '{"items": []}{"items": []}',
                         '{"items": [', ""):
            with self.subTest(response=response), self.assertRaises(
                (json.JSONDecodeError, ValueError)
            ):
                parse_batch_plan_response(response)
        cases = [
            ("", {"ok": False, "reason": "http_502"}, 503, "batch_plan_ai_unavailable"),
            ("", {"ok": False, "reason": "network"}, 503, "batch_plan_ai_unavailable"),
            ("", {"ok": False, "reason": "timeout"}, 503, "batch_plan_ai_unavailable"),
            ("unexpected model prose", {"ok": True}, 502, "batch_plan_ai_invalid"),
            ('{"items":[{"subject":"古街","layout":"NON_EXISTENT"}]}',
             {"ok": True}, 502, "batch_plan_ai_invalid"),
        ]
        for model_body, meta, code, name in cases:
            with self.subTest(reason=meta.get("reason") or model_body[:24]), \
                 patch("backend.batch_plan_routes.chat", return_value=(model_body, meta)) as model, \
                 self.assertLogs("backend.batch_plan_routes", level="WARNING") as records:
                status, result = self._req("POST", "/api/studio/batch-plan", {
                    "seed": "sensitive-client-prompt-not-to-log",
                    "count": 1, "layoutMode": "ai",
                }, cookie=self.cookie)
                self.assertEqual(status, code, result)
                self.assertEqual(result.get("code"), name)
                self.assertTrue(result.get("requestId"))
                self.assertTrue(model.call_args.kwargs["json_mode"])
                logged = "\n".join(records.output)
                self.assertIn("event=batch_plan_failed", logged)
                self.assertNotIn("sensitive-client-prompt-not-to-log", logged)
                self.assertNotIn("unexpected model prose", logged)
        conn = self.db.get_conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM generation_runs").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM works").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
