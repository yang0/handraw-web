"""
Integration tests for generation history public field whitelist,
safe code-only prompt handling, and catalog definition stripping (#22).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend import skill_prompt

from backend.server import HandrawRequestHandler, load_localized_json
from backend.services import (
    complete_cloud_generation,
    get_public_generation_history,
    get_studio_workspace,
    get_user_studio_task,
    prepare_cloud_generation,
    register_user,
    serialize_public_generation_history,
)

FORBIDDEN_FIELDS = {
    "prompt",
    "definition",
    "system_append_json",
    "systemAppend",
    "recipeSnapshot",
    "workflow",
    "taskId",
    "error",
    "wallet",
    "credits",
    "costType",
}

WHITELIST_FIELDS = {
    "id",
    "author",
    "createdAt",
    "created_at",
    "images",
    "topic",
    "title",
    "ratio",
    "mode",
    "styles",
    "layouts",
    "imageCount",
}


class HistoryBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "history_test.db"
        img_cfg = root / "image-service.json"
        img_cfg.write_text(json.dumps({"key": "mock-test-key", "url": "http://127.0.0.1:9999"}))
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_AI_CONFIG": str(root / "absent-ai-service.json"),
                "HANDRAW_IMAGE_CONFIG": str(img_cfg),
            },
        )
        self.env.start()
        self.db = open_isolated_postgres(self, seed=True)
        self.user, _ = register_user(self.db, "creator_alice", "Password123!")

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
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def login(self, username: str = "creator_alice", password: str = "Password123!") -> str:
        data = json.dumps({"username": username, "password": password}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/api/auth/login",
            data=data,
            headers={"Content-Type": "application/json", "Origin": "http://trusted.test"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            cookie = resp.headers.get("Set-Cookie", "")
            return cookie.split(";")[0] if cookie else ""

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        req_headers = {"Origin": "http://trusted.test"}
        if headers:
            req_headers.update(headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base}{path}", data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                return resp.status, resp_headers, resp.read()
        except urllib.error.HTTPError as exc:
            resp_headers = {k.lower(): v for k, v in exc.headers.items()}
            return exc.code, resp_headers, exc.read()

    def test_catalog_json_has_no_definitions(self):
        """#22: Public catalog.json must never send resource definitions to browsers."""
        status, _, raw = self.request("GET", "/data/catalog.json")
        self.assertEqual(status, 200)
        catalog = json.loads(raw.decode("utf-8"))
        resources = catalog.get("resources", [])
        self.assertTrue(len(resources) > 0, "Catalog should have resources")
        for r in resources:
            self.assertNotIn("definition", r, f"Resource {r.get('id')} contains definition in public catalog")

        # Test backend helper load_localized_json as well
        direct_bytes = load_localized_json("catalog.json")
        direct_catalog = json.loads(direct_bytes.decode("utf-8"))
        for r in direct_catalog.get("resources", []):
            self.assertNotIn("definition", r)

    def test_public_history_whitelist_fields(self):
        """Task A1: Public generation history strictly honors the whitelist and hides sensitive fields."""
        # Create a generation via prepare_cloud_generation
        prep = prepare_cloud_generation(
            self.db,
            self.user,
            {
                "prompt": "【画风】：#FA-001\n【图型】：#SC-021\n【核心画面与文案主题】：森林里的小木屋",
                "style1": "FA-001",
                "layout": "SC-021",
                "subject": "森林里的小木屋",
                "ratio": "3:4",
                "mode": "graphic-text",
            },
        )
        gen_id = prep["genId"]
        complete_cloud_generation(
            self.db,
            gen_id,
            "task_test_123",
            ["/images/generated/cabin_1.webp", "/images/generated/cabin_2.webp"],
        )

        # 1. Fetch via GET /api/studio/history (public, anonymous)
        status, _, raw = self.request("GET", "/api/studio/history")
        self.assertEqual(status, 200)
        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data.get("ok"))
        history_list = data.get("history", [])
        self.assertTrue(len(history_list) >= 1)

        target = next(
            (h for h in history_list if h.get("sourceGenerationId") == gen_id),
            None,
        )
        self.assertIsNotNone(target)

        # Check whitelist fields present
        for field in WHITELIST_FIELDS:
            self.assertIn(field, target, f"Expected whitelist field '{field}' in public history item")

        # Check forbidden fields absent
        for field in FORBIDDEN_FIELDS:
            self.assertNotIn(field, target, f"Forbidden field '{field}' must NOT appear in public history")

        self.assertEqual(target["author"], "creator_alice")
        self.assertEqual(target["topic"], "森林里的小木屋")
        self.assertEqual(target["title"], "森林里的小木屋")
        self.assertEqual(target["imageCount"], 2)
        self.assertEqual(target["ratio"], "3:4")
        self.assertEqual(len(target["styles"]), 1)
        self.assertEqual(target["styles"][0]["code"], "FA-001")
        self.assertEqual(len(target["layouts"]), 1)
        self.assertEqual(target["layouts"][0]["code"], "SC-021")

        # 2. Fetch via GET /api/studio/history?id=<gen_id>
        status_single, _, raw_single = self.request("GET", f"/api/studio/history?id={gen_id}")
        self.assertEqual(status_single, 200)
        data_single = json.loads(raw_single.decode("utf-8"))
        self.assertTrue(data_single.get("ok"))
        single_item = data_single.get("history")
        self.assertEqual(single_item["id"], target["id"])
        self.assertEqual(single_item["workId"], target["workId"])
        for field in FORBIDDEN_FIELDS:
            self.assertNotIn(field, single_item)

    def test_legacy_history_without_subject_uses_neutral_title(self):
        """Legacy generations without subject column must fall back to neutral '手绘创作', never infer from prompt."""
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                    status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                    prompt_ready, subject
                ) VALUES (
                    'gen_legacy_001', ?, ?, '3:4', 'graphic-text', '云端直出', 'single', '#FA-001',
                    '这是一段很长且包含高度私密定义的历史提示词', '', 0, '{}', '', '["/images/legacy.webp"]', 'live', 'free_quota', 0, 't_1',
                    'success', '', 'req_legacy', '2026-01-01', '2026-01-01T00:00:00Z', '', 1, ''
                )
                """,
                (self.user["id"], self.user["username"]),
            )
            # V3 never backfills old rows. Explicitly project the current
            # successful execution into its one canonical run and work.
            from backend.generation_works import project_generation_to_works
            self.assertEqual(len(project_generation_to_works(tx, "gen_legacy_001")), 1)

        item = get_public_generation_history(self.db, "gen_legacy_001")
        self.assertIsNotNone(item)
        self.assertEqual(item["topic"], "未命名作品")
        self.assertEqual(item["title"], "未命名作品")
        self.assertNotIn("这是一段很长", str(item))
        self.assertNotIn("prompt", item)

    def test_paid_resource_not_leaked_to_author_and_allows_online_reuse(self):
        """Paid resource definitions are masked even for the author, and allow online reuse via historyId."""
        # Insert a paid catalog asset
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO catalog_assets (\n                    code, kind, name, description, definition, secret_blackbox_prompt,\n                    unlock_cost, source_type, status, image_url, published_at_ms, created_at, updated_at\n                ) VALUES (\n                    'PAID-01', 'style', '高级水彩私享画风', '独家付费手绘风格', '【绝密水彩画风定义：层叠温润渲染】', '',\n                    15, 'exclusive', 'published', '/images/paid01.webp', 1700000000000, '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z'\n                ) ON CONFLICT (code) DO UPDATE SET kind = excluded.kind, name = excluded.name, description = excluded.description, definition = excluded.definition, secret_blackbox_prompt = excluded.secret_blackbox_prompt, unlock_cost = excluded.unlock_cost, source_type = excluded.source_type, status = excluded.status, image_url = excluded.image_url, published_at_ms = excluded.published_at_ms, created_at = excluded.created_at, updated_at = excluded.updated_at"
            )
            # Give user unlock record for PAID-01
            tx.execute(
                "INSERT INTO unlocks (user_id, target_type, target_id, cost, status, created_at)\n                VALUES (?, 'asset', 'PAID-01', 15, 'settled', '2026-11-01T00:00:00Z') ON CONFLICT (id) DO UPDATE SET user_id = excluded.user_id, target_type = excluded.target_type, target_id = excluded.target_id, cost = excluded.cost, status = excluded.status, created_at = excluded.created_at",
                (self.user["id"],),
            )

        cookie = self.login()

        # Submit generation via /api/studio/generate using simulation
        status, _, raw = self.request(
            "POST",
            "/api/studio/generate",
            {
                "prompt": "【画风】：#PAID-01\n【图型】：#SC-021\n【核心画面与文案主题】：雨后初晴的江南小巷",
                "style1": "PAID-01",
                "layout": "SC-021",
                "subject": "雨后初晴的江南小巷",
                "simulateGateway": "ok",
                "requestId": "req_paid_test_1",
            },
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        res_data = json.loads(raw.decode("utf-8"))
        self.assertTrue(res_data.get("ok"))
        gen_id = res_data["genId"]

        # 1. Check generation response: finalPrompt is empty and definition is NOT echoed
        self.assertEqual(res_data.get("finalPrompt"), "")
        self.assertTrue(res_data.get("promptMasked"))
        self.assertNotIn("绝密水彩画风定义", raw.decode("utf-8"))

        # 2. Check author workspace
        status_ws, _, raw_ws = self.request("GET", "/api/studio/workspace", headers={"Cookie": cookie})
        self.assertEqual(status_ws, 200)
        ws_data = json.loads(raw_ws.decode("utf-8"))
        ws_hist = ws_data.get("history", [])
        author_entry = next((h for h in ws_hist if h["id"] == gen_id), None)
        self.assertIsNotNone(author_entry)
        self.assertEqual(author_entry.get("prompt"), "")
        self.assertTrue(author_entry.get("promptMasked"))
        self.assertEqual(author_entry.get("topic"), "雨后初晴的江南小巷")
        # Check items in workspace have no definition
        for item in author_entry.get("items", []):
            self.assertNotIn("prompt", item)

        # 3. Check public history for this paid work
        pub_item = get_public_generation_history(self.db, gen_id)
        self.assertIsNotNone(pub_item)
        self.assertEqual(pub_item["topic"], "雨后初晴的江南小巷")
        self.assertEqual(pub_item["styles"][0]["code"], "PAID-01")
        for field in FORBIDDEN_FIELDS:
            self.assertNotIn(field, pub_item)
        self.assertNotIn("绝密水彩画风定义", str(pub_item))

        # 4. Author can reuse via historyId
        reuse_prep = prepare_cloud_generation(
            self.db,
            self.user,
            {
                "historyId": gen_id,
                "requestId": "req_paid_reuse_1",
            },
        )
        self.assertIsNotNone(reuse_prep.get("genId"))
        self.assertEqual(reuse_prep.get("finalPrompt"), "")

        # 5. Another user without unlock cannot reuse this paid generation
        other_user, _ = register_user(self.db, "bob_free", "Password123!")
        with self.assertRaises(Exception) as ctx:
            prepare_cloud_generation(
                self.db,
                other_user,
                {
                    "prompt": "主题：新的创作",
                    "style1": "PAID-01",
                    "requestId": "req_bob_hack",
                },
            )
        self.assertIn("尚未解锁付费编号", str(ctx.exception))

    @unittest.skipUnless(skill_prompt.skill_available(), "Skill checkout not available")
    def test_model_receives_injected_definition_while_browser_does_not(self):
        """Gateway model payload receives the resolved definitions, while browser response does not."""
        cookie = self.login()
        sent_payloads: list[dict] = []

        def mock_gateway_request(endpoint, payload=None, timeout=28):
            sent_payloads.append(payload or {})
            return {"id": "mock_gw_task_999", "status": "queued"}

        with patch("backend.server.gateway_request", side_effect=mock_gateway_request):
            status, _, raw = self.request(
                "POST",
                "/api/studio/generate",
                {
                    "prompt": "【画风】：#FA-001\n【图型】：#SC-021\n【核心画面与文案主题】：落日余晖中的古塔",
                    "style1": "FA-001",
                    "layout": "SC-021",
                    "requestId": "req_gw_verify_1",
                },
                headers={"Cookie": cookie},
            )

        self.assertIn(status, (200, 202))
        res_data = json.loads(raw.decode("utf-8"))
        self.assertTrue(res_data.get("ok"))

        # Verify gateway payload was called
        self.assertTrue(len(sent_payloads) == 1)
        model_prompt = sent_payloads[0].get("prompt", "")
        # Model prompt MUST contain definition of FA-001 or SC-021
        self.assertTrue(len(model_prompt) > 0)
        self.assertIn("Playful Deadpan Doodle", model_prompt)
        self.assertIn("松散黑线", model_prompt)
        self.assertIn("Adaptive Split Photo-to-Art Social Card", model_prompt)

        # Browser response must NOT contain the definition or final prompt
        self.assertNotIn("Playful Deadpan Doodle", raw.decode("utf-8"))
        self.assertNotIn("松散黑线", raw.decode("utf-8"))
        self.assertNotIn("Adaptive Split Photo-to-Art Social Card", raw.decode("utf-8"))
        self.assertNotIn("prompt", res_data)
        self.assertFalse(res_data.get("finalPrompt"))


if __name__ == "__main__":
    unittest.main()
