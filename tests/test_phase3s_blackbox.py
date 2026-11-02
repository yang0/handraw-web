"""Tests for Phase 3s: stop returning resource black-box prompts to clients (Round 2 redesign).

Covers:
1. Grep test across all client-facing endpoints (generate, recipe generate, sim,
   replay, poll, workspace/boot, work publish, work read): response JSON never
   contains seeded secret strings.
2. Gateway prompt receives full prompt with secret, byte-identical to baseline.
3. Legacy rows and backfill: fail-closed behavior before backfill, correct extraction
   during backfill, and database original prompt preservation.
4. Exit inventory test across all roles (anonymous, ordinary, author, reviewer, operator,
   admin on public endpoints) and all exits (JSON and SSR HTML): zero secret leaks.
   Staff check on /api/admin/works: only admin role gets full prompt.
5. Fail-closed and cache behavior: clearing a secret doesn't unmask flagged rows until
   backfill; user text is never mangled by common word secrets (e.g. 'cat').
6. Upstream gateway error bodies never echo to responses, error_msg, workspace, or polling.
7. Replay snapshot vs legacy replay behavior when system_append_json is NULL.
8. Migration 063 repeatable and preserves existing data.
9. Recipe prompt_too_long message names real cause when system instructions alone fill budget.
10. Performance benchmark on review dataset: fast O(1) column access on boot and workspace.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.db import Database
from backend.server import SESSION_COOKIE_NAME, HandrawRequestHandler, init_database
from backend.services import (
    ServiceError,
    _cloud_generation_result,
    _serialize_work,
    build_boot_payload,
    get_generation_visible_prompt,
    get_studio_workspace,
    get_work_client_prompt,
    prepare_cloud_generation,
    register_user,
    run_blackbox_backfill,
)


class Phase3sBlackboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "p3s_test.db"
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_ENABLE_RECHARGE": "0",
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

        # Seed users
        self.user_alice, token_a = register_user(self.db, "alice", "AlicePass123")
        self.user_bob, token_b = register_user(self.db, "bob", "BobPass123")
        self.user_reviewer, token_rev = register_user(self.db, "rev_user", "RevPass123")
        self.user_operator, token_op = register_user(self.db, "op_user", "OpPass123")
        self.user_admin, token_admin = register_user(self.db, "superadmin", "AdminPass123")

        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'reviewer' WHERE id = ?", (self.user_reviewer["id"],))
            tx.execute("UPDATE users SET role = 'operator' WHERE id = ?", (self.user_operator["id"],))
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.user_admin["id"],))

        self.cookie_a = f"{SESSION_COOKIE_NAME}={token_a}"
        self.cookie_b = f"{SESSION_COOKIE_NAME}={token_b}"
        self.cookie_rev = f"{SESSION_COOKIE_NAME}={token_rev}"
        self.cookie_op = f"{SESSION_COOKIE_NAME}={token_op}"
        self.cookie_admin = f"{SESSION_COOKIE_NAME}={token_admin}"

        # Seed two test assets: one paid unlocked, one free
        self.paid_secret = "PAID_TOP_SECRET_BLACKBOX_KEYWORD_2026"
        self.free_secret = "FREE_TOP_SECRET_BLACKBOX_GUIDANCE_2026"

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-P3S-PAID', '付费黑盒画风', 'style', 'exclusive', 'A', 20, '/images/p3s_paid.webp', 'bob', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (self.paid_secret,),
            )
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-P3S-FREE', '免费黑盒画风', 'style', 'exclusive', 'free', 0, '/images/p3s_free.webp', 'bob', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (self.free_secret,),
            )
            # Unlock the paid asset for Alice
            tx.execute(
                """
                INSERT INTO unlocks (user_id, target_type, target_id, cost, status, created_at)
                VALUES (?, 'asset', 'FX-P3S-PAID', 20, 'settled', '2026-10-31T00:00:00Z')
                """,
                (self.user_alice["id"],),
            )

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
    ) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Content-Type": "application/json",
            "Origin": "http://trusted.test",
        }
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
                return status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as he:
            raw = he.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"error": raw}
            return he.code, parsed

    def _req_text(
        self,
        method: str,
        path: str,
        cookie: str | None = None,
    ) -> tuple[int, str]:
        headers = {
            "Origin": "http://trusted.test",
        }
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(self.base + path, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as he:
            return he.code, he.read().decode("utf-8")

    def test_client_endpoints_never_leak_blackbox_secrets(self) -> None:
        """1. Grep test: no client-facing endpoint response contains seeded secrets."""
        # A. Non-recipe generation (simulateGateway=ok)
        st_gen, r_gen = self._req(
            "POST",
            "/api/studio/generate",
            {
                "prompt": "自由绘制小松鼠",
                "style1": "FX-P3S-PAID",
                "style2": "FX-P3S-FREE",
                "requestId": "req-p3s-norecipe-1",
                "simulateGateway": "ok",
            },
            cookie=self.cookie_a,
        )
        self.assertEqual(st_gen, 200)
        raw_gen_json = json.dumps(r_gen, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_gen_json)
        self.assertNotIn(self.free_secret, raw_gen_json)

        # Verify DB row has both prompt (with secrets) and visible_prompt (without secrets)
        row_gen = self.db.get_conn().execute(
            "SELECT prompt, visible_prompt, prompt_masked, system_append_json FROM studio_generations WHERE id = ?",
            (r_gen["genId"],),
        ).fetchone()
        self.assertIn(self.paid_secret, row_gen["prompt"])
        self.assertIn(self.free_secret, row_gen["prompt"])
        self.assertNotIn(self.paid_secret, row_gen["visible_prompt"])
        self.assertNotIn(self.free_secret, row_gen["visible_prompt"])
        self.assertEqual(row_gen["visible_prompt"], "立即生成图片：\n自由绘制小松鼠\n\n请直接调用画图工具立即生成图片，不要输出任何询问文字、选项或确认反问。")
        self.assertEqual(row_gen["prompt_masked"], 0)

        # B. Recipe generation (simulateGateway=ok)
        st_rcp, r_rcp = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FX-P3S-PAID", "FX-P3S-FREE"], "subject": "配方松鼠"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_rcp, 201)
        rcp_id = r_rcp["id"]

        st_rcp_gen, r_rcp_gen = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": rcp_id, "requestId": "req-p3s-recipe-1", "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_rcp_gen, 200)
        raw_rcp_gen_json = json.dumps(r_rcp_gen, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_rcp_gen_json)
        self.assertNotIn(self.free_secret, raw_rcp_gen_json)
        self.assertEqual(
            r_rcp_gen["systemAppend"],
            [
                {"type": "asset_instructions", "code": "FX-P3S-PAID"},
                {"type": "asset_instructions", "code": "FX-P3S-FREE"},
            ],
        )

        # C. Replay (same requestId)
        st_replay, r_replay = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": rcp_id, "requestId": "req-p3s-recipe-1", "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_replay, 200)
        self.assertTrue(r_replay.get("idempotent"))
        raw_replay_json = json.dumps(r_replay, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_replay_json)
        self.assertNotIn(self.free_secret, raw_replay_json)

        # D. Polling (/api/studio/tasks)
        st_poll, r_poll = self._req(
            "GET",
            f"/api/studio/tasks?requestId=req-p3s-recipe-1",
            cookie=self.cookie_a,
        )
        self.assertEqual(st_poll, 200)
        raw_poll_json = json.dumps(r_poll, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_poll_json)
        self.assertNotIn(self.free_secret, raw_poll_json)

        # E. Workspace (/api/studio/workspace)
        st_ws, r_ws = self._req(
            "GET",
            "/api/studio/workspace",
            cookie=self.cookie_a,
        )
        self.assertEqual(st_ws, 200)
        raw_ws_json = json.dumps(r_ws, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_ws_json)
        self.assertNotIn(self.free_secret, raw_ws_json)

        for h in r_ws["history"]:
            self.assertNotIn(self.paid_secret, h.get("prompt", ""))
            self.assertNotIn(self.free_secret, h.get("prompt", ""))
            for it in h.get("items", []):
                self.assertNotIn(self.paid_secret, it.get("prompt", ""))
                self.assertNotIn(self.free_secret, it.get("prompt", ""))

        # F. Work publish with secret prompt
        # Alice publishes a work containing the secret in prompt
        st_pub, r_pub = self._req(
            "POST",
            "/api/works",
            {
                "title": "公开作品测试松鼠",
                "prompt": f"我的公开提示词\n\n{self.paid_secret}\n\n{self.free_secret}",
                "images": ["/images/poster-demo-autumn-equinox.webp"],
                "styles": ["FX-P3S-PAID"],
                "notes": "这是用于黑盒测试作品发布的创作说明记录",
                "price": 0,
            },
            cookie=self.cookie_a,
        )
        self.assertEqual(st_pub, 200)
        work_id = r_pub["workId"]

        # Check DB flag
        w_row = self.db.get_conn().execute("SELECT prompt, prompt_has_secret FROM works WHERE id = ?", (work_id,)).fetchone()
        self.assertEqual(w_row["prompt_has_secret"], 1)
        self.assertIn(self.paid_secret, w_row["prompt"])

        # Bob reads boot (/api/boot) -> masked fail-closed
        st_boot, r_boot = self._req("GET", "/api/boot", cookie=self.cookie_b)
        self.assertEqual(st_boot, 200)
        raw_boot_bob = json.dumps(r_boot, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_boot_bob)
        self.assertNotIn(self.free_secret, raw_boot_bob)
        bob_work = next(w for w in r_boot["works"] if w["id"] == work_id)
        self.assertEqual(bob_work["prompt"], "")
        self.assertTrue(bob_work["promptMasked"])

        # Alice (author) reads boot -> also masked on public endpoint
        st_boot_a, r_boot_a = self._req("GET", "/api/boot", cookie=self.cookie_a)
        alice_work = next(w for w in r_boot_a["works"] if w["id"] == work_id)
        self.assertEqual(alice_work["prompt"], "")
        self.assertTrue(alice_work["promptMasked"])

        # Bob reads work detail (/api/posts/by-ref/work/{work_id})
        st_ref_b, r_ref_b = self._req("GET", f"/api/posts/by-ref/work/{work_id}", cookie=self.cookie_b)
        self.assertEqual(st_ref_b, 200)
        raw_ref_b = json.dumps(r_ref_b, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_ref_b)
        self.assertNotIn(self.free_secret, raw_ref_b)
        if "work" in r_ref_b:
            self.assertEqual(r_ref_b["work"]["prompt"], "")
            self.assertTrue(r_ref_b["work"]["promptMasked"])

        # Admin reads works in admin panel (/api/admin/works) -> admin gets full prompt
        st_admin, r_admin = self._req("GET", "/api/admin/works", cookie=self.cookie_admin)
        self.assertEqual(st_admin, 200)
        admin_work = next(w for w in r_admin["items"] if w["id"] == work_id)
        self.assertIn(self.paid_secret, admin_work["prompt"])

    def test_gateway_receives_secret_byte_identical(self) -> None:
        """2. Gateway prompt receives full prompt with secret, byte-identical to baseline."""
        captured_payloads = []

        def fake_gw_request(endpoint: str, payload: dict | None = None, timeout: int = 28):
            if payload:
                captured_payloads.append(dict(payload))
            return {"id": "fake_task_live_123", "status": "queued"}

        with patch("backend.server.gateway_request", side_effect=fake_gw_request):
            with patch("backend.server.load_image_service_config", return_value={"enabled": True}):
                st, res = self._req(
                    "POST",
                    "/api/studio/generate",
                    {
                        "prompt": "画一只小狐狸",
                        "style1": "FX-P3S-PAID",
                        "requestId": "req-live-gw-1",
                    },
                    cookie=self.cookie_a,
                )
        self.assertEqual(st, 200)
        self.assertEqual(len(captured_payloads), 1)
        gw_p = captured_payloads[0]["prompt"]

        expected_gw_prompt = (
            f"立即生成图片：\n画一只小狐狸\n\n{self.paid_secret}\n\n"
            f"请直接调用画图工具立即生成图片，不要输出任何询问文字、选项或确认反问。"
        )
        self.assertEqual(gw_p, expected_gw_prompt)

    def test_legacy_data_backfill_and_fail_closed(self) -> None:
        """3. Legacy rows: fail-closed before backfill; correctly backfilled afterwards."""
        secret = self.paid_secret
        with self.db.transaction() as tx:
            # 1. Legacy generation row with visible_prompt = NULL
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                    status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                    prompt_ready, recipe_id
                ) VALUES ('gen_legacy_1', ?, 'alice', '测试', '3:4', '云端直出', 'single', 'FX-P3S-PAID',
                          ?, NULL, 0, NULL, '', '["/images/poster-demo-autumn-equinox.webp"]', 'live', 'free_quota', 0, 't1',
                          'success', '', 'req-legacy-1', '2026-10-31', '2026-10-31T01:00:00Z', '', 1, '')
                """,
                (self.user_alice["id"], f"旧提示词内容\n\n{secret}"),
            )

            # 2. Legacy work with prompt_has_secret = NULL
            tx.execute(
                """
                INSERT INTO works (
                    id, author_username, author_name, title, images_json, styles_json, layout_code,
                    price, prompt, prompt_has_secret, notes, status, published_at_ms, created_at, updated_at
                ) VALUES ('work_legacy_1', 'bob', 'Bob', '旧作品', '["/images/poster-demo-autumn-equinox.webp"]',
                          '["FX-P3S-PAID"]', '', 0, ?, NULL, '', 'published', 1700000000000,
                          '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (f"旧作品描述提示词\n\n{secret}",),
            )

        # Before backfill: read accessors must FAIL CLOSED (return empty prompt + masked)
        row1 = self.db.get_conn().execute("SELECT * FROM studio_generations WHERE id = 'gen_legacy_1'").fetchone()
        vis, masked = get_generation_visible_prompt(row1)
        self.assertEqual(vis, "")
        self.assertTrue(masked)

        wrow1 = self.db.get_conn().execute("SELECT * FROM works WHERE id = 'work_legacy_1'").fetchone()
        wvis, wmasked = get_work_client_prompt(wrow1, is_admin_route=False)
        self.assertEqual(wvis, "")
        self.assertTrue(wmasked)

        # Run backfill
        counts = run_blackbox_backfill(self.db, force=True)
        self.assertGreaterEqual(counts["generations"], 1)
        self.assertGreaterEqual(counts["works"], 1)

        # After backfill:
        # Generation: injection suffix was removed cleanly -> visible_prompt is "旧提示词内容"
        row1_after = self.db.get_conn().execute("SELECT visible_prompt, prompt_masked, prompt FROM studio_generations WHERE id = 'gen_legacy_1'").fetchone()
        self.assertEqual(row1_after["visible_prompt"], "旧提示词内容")
        self.assertEqual(row1_after["prompt_masked"], 0)
        self.assertIn(secret, row1_after["prompt"])  # original prompt unchanged

        # Work: contains secret -> prompt_has_secret = 1
        wrow1_after = self.db.get_conn().execute("SELECT prompt, prompt_has_secret FROM works WHERE id = 'work_legacy_1'").fetchone()
        self.assertEqual(wrow1_after["prompt_has_secret"], 1)
        self.assertIn(secret, wrow1_after["prompt"])  # original prompt unchanged

        # Read after backfill
        wvis_after, wmasked_after = get_work_client_prompt(wrow1_after, is_admin_route=False)
        self.assertEqual(wvis_after, "")
        self.assertTrue(wmasked_after)

    def test_exit_inventory_all_roles_and_endpoints(self) -> None:
        """4. Round 2 exit inventory: test every JSON and SSR exit across all roles."""
        secret = "UNIQUE_EXIT_TEST_SECRET_ABC_12345"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-EXIT', '出口测试画风', 'style', 'exclusive', 'A', 10, '/images/exit.webp', 'alice', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (secret,),
            )

        # Alice publishes a work containing secret
        st_w_pub, r_w_pub = self._req(
            "POST",
            "/api/works",
            {
                "title": "出口测试作品",
                "styles": ["FX-EXIT"],
                "images": ["/images/poster-demo-autumn-equinox.webp"],
                "notes": "这是实测笔记摘要记录详情",
                "prompt": f"作品提示词附带秘密：{secret}",
            },
            cookie=self.cookie_a,
        )
        self.assertEqual(st_w_pub, 200)
        work_exit_id = r_w_pub["workId"]

        # Alice publishes a forum topic containing secret in recipe
        st_t_pub, r_t_pub = self._req(
            "POST",
            "/api/forum/topics",
            {
                "title": "出口帖子",
                "category": "assets",
                "recipe": {"prompt": f"配方秘密：{secret}"},
            },
            cookie=self.cookie_a,
        )
        self.assertEqual(st_t_pub, 200)
        topic_exit_id = r_t_pub["topicId"]

        # 20-char window of secret
        sec_chunk = secret[:20]

        roles = [
            ("anonymous", None),
            ("ordinary_bob", self.cookie_b),
            ("author_alice", self.cookie_a),
            ("reviewer", self.cookie_rev),
            ("operator", self.cookie_op),
            ("admin_public", self.cookie_admin),
        ]

        endpoints = [
            ("GET", "/"),
            ("GET", f"/?view=work&id={work_exit_id}"),
            ("GET", "/?view=works"),
            ("GET", "/?view=rankings"),
            ("GET", "/api/boot"),
            ("GET", f"/api/posts/by-ref/work/{work_exit_id}"),
            ("GET", f"/api/posts/{topic_exit_id}"),
        ]

        for role_name, cookie in roles:
            for method, path in endpoints:
                st, body = self._req_text(method, path, cookie=cookie)
                self.assertEqual(st, 200, f"Role {role_name} on {path} returned HTTP {st}")
                self.assertNotIn(secret, body, f"Role {role_name} on {path} leaked full secret!")
                self.assertNotIn(sec_chunk, body, f"Role {role_name} on {path} leaked 20-char secret snippet!")

        # Check /api/admin/works:
        # Admin gets full secret
        st_adm, r_adm = self._req("GET", "/api/admin/works", cookie=self.cookie_admin)
        self.assertEqual(st_adm, 200)
        item_adm = next(w for w in r_adm["items"] if w["id"] == work_exit_id)
        self.assertIn(secret, item_adm["prompt"])

        # Reviewer gets masked prompt on /api/admin/works
        st_rev, r_rev = self._req("GET", "/api/admin/works", cookie=self.cookie_rev)
        self.assertEqual(st_rev, 200)
        item_rev = next(w for w in r_rev["items"] if w["id"] == work_exit_id)
        self.assertEqual(item_rev["prompt"], "")
        self.assertTrue(item_rev.get("promptMasked"))

        # Operator gets masked prompt on /api/admin/works
        st_op, r_op = self._req("GET", "/api/admin/works", cookie=self.cookie_op)
        self.assertEqual(st_op, 200)
        item_op = next(w for w in r_op["items"] if w["id"] == work_exit_id)
        self.assertEqual(item_op["prompt"], "")
        self.assertTrue(item_op.get("promptMasked"))

        # Test POST /api/unlocks by Bob on the work -> rejected with 400
        st_unl, r_unl = self._req(
            "POST",
            "/api/unlocks",
            {"targetType": "work", "targetId": work_exit_id},
            cookie=self.cookie_b,
        )
        self.assertEqual(st_unl, 400)
        self.assertEqual(r_unl.get("code"), "work_not_unlockable")

    def test_fail_closed_and_cache_behavior(self) -> None:
        """5. Clearing a secret doesn't unmask previously flagged rows; user text is never mangled."""
        secret = "SECRET_DISAPPEARING_POOF_999"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-POOF', '消失画风', 'style', 'exclusive', 'A', 10, '/images/poof.webp', 'alice', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (secret,),
            )
            # Create a work with this secret
            tx.execute(
                """
                INSERT INTO works (
                    id, author_username, author_name, title, images_json, styles_json, layout_code,
                    price, prompt, prompt_has_secret, notes, status, published_at_ms, created_at, updated_at
                ) VALUES ('work_poof', 'alice', 'Alice', '消失作品', '[]', '["FX-POOF"]', '', 0, ?, 1, '',
                          'published', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (f"提示词：{secret}",),
            )

        # Clear the secret from catalog_assets
        with self.db.transaction() as tx:
            tx.execute("UPDATE catalog_assets SET secret_blackbox_prompt = '' WHERE code = 'FX-POOF'")

        # Reading the work MUST STILL BE MASKED because reads check prompt_has_secret flag!
        wrow = self.db.get_conn().execute("SELECT * FROM works WHERE id = 'work_poof'").fetchone()
        p, masked = get_work_client_prompt(wrow, is_admin_route=False)
        self.assertEqual(p, "")
        self.assertTrue(masked)

        # Common word secret test: secret = "cat"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-CAT', '猫猫画风', 'style', 'exclusive', 'free', 0, '/images/cat.webp', 'alice', 'published', 'cat', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
            )

        user_text = "a catapult and a cat"
        st_cat_pub, r_cat_pub = self._req(
            "POST",
            "/api/works",
            {
                "title": "投石机与猫作品",
                "prompt": user_text,
                "images": ["/images/cat.webp"],
                "notes": "投石机与猫作品的完整创作说明记录",
                "price": 0,
            },
            cookie=self.cookie_a,
        )
        self.assertEqual(st_cat_pub, 200)
        cat_wid = r_cat_pub["workId"]

        # Check DB: original user text must NOT be mangled to "a apult and a "!
        cat_wrow = self.db.get_conn().execute("SELECT prompt, prompt_has_secret FROM works WHERE id = ?", (cat_wid,)).fetchone()
        self.assertEqual(cat_wrow["prompt"], "a catapult and a cat")
        self.assertEqual(cat_wrow["prompt_has_secret"], 1)

        # Client reading gets masked
        st_ref, r_ref = self._req("GET", f"/api/posts/by-ref/work/{cat_wid}", cookie=self.cookie_b)
        self.assertEqual(st_ref, 200)
        tid = r_ref["topicId"]

        st_detail, r_detail = self._req("GET", f"/api/posts/{tid}", cookie=self.cookie_b)
        self.assertEqual(st_detail, 200)
        target_work = r_detail.get("mount", {}).get("work", {})
        self.assertEqual(target_work.get("prompt"), "")
        self.assertTrue(target_work.get("promptMasked"))

        # Also verify in /api/boot
        st_boot, r_boot = self._req("GET", "/api/boot", cookie=self.cookie_b)
        self.assertEqual(st_boot, 200)
        w_in_boot = next(w for w in r_boot["works"] if w["id"] == cat_wid)
        self.assertEqual(w_in_boot["prompt"], "")
        self.assertTrue(w_in_boot["promptMasked"])

    def test_upstream_gateway_error_echo_masked(self) -> None:
        """6. Gateway error bodies never appear in responses, error_msg, workspace or polling."""
        leak_in_err = f"Upstream rejected prompt with secret: {self.paid_secret}"

        class FakeHTTPError(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("http://gw.test", 400, "Bad Request", {}, None)

            def read(self):
                return leak_in_err.encode("utf-8")

        def fake_gw_fail(endpoint: str, payload: dict | None = None, timeout: int = 28):
            raise FakeHTTPError()

        with patch("backend.server.gateway_request", side_effect=fake_gw_fail):
            with patch("backend.server.load_image_service_config", return_value={"enabled": True}):
                st, res = self._req(
                    "POST",
                    "/api/studio/generate",
                    {
                        "prompt": "生成失败测试",
                        "style1": "FX-P3S-PAID",
                        "requestId": "req-gw-err-1",
                    },
                    cookie=self.cookie_a,
                )
        self.assertEqual(st, 502)
        raw_res = json.dumps(res, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_res)
        self.assertNotIn("Upstream rejected prompt", raw_res)
        self.assertIn("网关请求失败 (HTTP 400)", res["error"])

        # Check error_msg in studio_generations
        gen_row = self.db.get_conn().execute(
            "SELECT error_msg FROM studio_generations WHERE user_id = ? AND request_id = 'req-gw-err-1'",
            (self.user_alice["id"],),
        ).fetchone()
        self.assertNotIn(self.paid_secret, gen_row["error_msg"])
        self.assertEqual(gen_row["error_msg"], "网关请求失败 (HTTP 400)")

        # Check polling /api/studio/tasks
        st_poll, r_poll = self._req(
            "GET",
            "/api/studio/tasks?requestId=req-gw-err-1",
            cookie=self.cookie_a,
        )
        self.assertEqual(st_poll, 200)
        self.assertNotIn(self.paid_secret, json.dumps(r_poll, ensure_ascii=False))

    def test_replay_legacy_null_snapshot_and_new_snapshot(self) -> None:
        """7. Legacy row with NULL system_append_json keeps old replay behavior; new row restores snapshot."""
        # 1. New row with snapshot:
        st_rcp, r_rcp = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FX-P3S-PAID"], "subject": "快照测试"},
            cookie=self.cookie_a,
        )
        rcp_id = r_rcp["id"]
        st_gen, r_gen = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": rcp_id, "requestId": "req-snap-test-1", "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_gen, 200)

        # Clear secret and archive in catalog
        with self.db.transaction() as tx:
            tx.execute("UPDATE catalog_assets SET secret_blackbox_prompt = '', status = 'archived' WHERE code = 'FX-P3S-PAID'")

        # Replay new row -> restored from snapshot!
        st_rep1, r_rep1 = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": rcp_id, "requestId": "req-snap-test-1", "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_rep1, 200)
        self.assertTrue(r_rep1["idempotent"])
        self.assertEqual(r_rep1["systemAppend"], [{"type": "asset_instructions", "code": "FX-P3S-PAID"}])

        # 2. Legacy row with system_append_json = NULL:
        # Re-publish FX-P3S-FREE with secret
        with self.db.transaction() as tx:
            tx.execute("UPDATE catalog_assets SET secret_blackbox_prompt = 'FREE_REPLAY_SEC', status = 'published' WHERE code = 'FX-P3S-FREE'")
            tx.execute(
                """
                INSERT INTO studio_recipes (
                    id, user_id, kind, style_ids, layout_id, subject, prompt, created_at, updated_at
                ) VALUES ('rcp_legacy', ?, 'single', '["FX-P3S-FREE"]', '', '旧配方', '', '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (self.user_alice["id"],),
            )
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                    status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                    prompt_ready, recipe_id
                ) VALUES ('gen_legacy_replay', ?, 'alice', '测试', '3:4', '云端直出', 'single', 'FX-P3S-FREE',
                          'gateway prompt', 'visible prompt', 0, NULL, '', '[]', 'live', 'free_quota', 0, 't_leg',
                          'success', '', 'req-legacy-replay-1', '2026-10-31', '2026-10-31T03:00:00Z', '', 1, 'rcp_legacy')
                """,
                (self.user_alice["id"],),
            )

        # Replay legacy row -> queries catalog_assets!
        st_leg_rep, r_leg_rep = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": "rcp_legacy", "requestId": "req-legacy-replay-1", "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_leg_rep, 200)
        self.assertTrue(r_leg_rep["idempotent"])
        self.assertEqual(r_leg_rep["systemAppend"], [{"type": "asset_instructions", "code": "FX-P3S-FREE"}])

    def test_migration_063_repeatable_and_preserves_old_data(self) -> None:
        """8. Migration 063 repeatable and preserves existing data."""
        applied = self.db.migrate()
        self.assertEqual(applied, [])

        cols_gen = [r["name"] for r in self.db.get_conn().execute("PRAGMA table_info(studio_generations)").fetchall()]
        self.assertIn("visible_prompt", cols_gen)
        self.assertIn("prompt_masked", cols_gen)
        self.assertIn("system_append_json", cols_gen)

        cols_work = [r["name"] for r in self.db.get_conn().execute("PRAGMA table_info(works)").fetchall()]
        self.assertIn("prompt_has_secret", cols_work)

        cols_top = [r["name"] for r in self.db.get_conn().execute("PRAGMA table_info(forum_topics)").fetchall()]
        self.assertIn("recipe_has_secret", cols_top)

    def test_recipe_prompt_too_long_cause_clarification(self) -> None:
        """9. Recipe prompt_too_long message clarifies cause when only system instructions exceed limit."""
        huge_secret = "超长黑盒视觉注入指令" * 450  # ~4500 chars
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-HUGE', '超长画风', 'style', 'exclusive', 'free', 0, '/images/huge.webp', 'bob', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (huge_secret,),
            )

        st_rcp_no_p, r_rcp_no_p = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FX-HUGE"], "subject": ""},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_rcp_no_p, 201)

        st_fail1, r_fail1 = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": r_rcp_no_p["id"], "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_fail1, 400)
        self.assertEqual(r_fail1["code"], "prompt_too_long")
        self.assertIn("所选资源系统说明超过 4000 字上限，请精简所选资源", r_fail1["error"])

        st_rcp_with_p, r_rcp_with_p = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FX-HUGE"], "prompt": "用户手写的提示词内容"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_rcp_with_p, 201)

        st_fail2, r_fail2 = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": r_rcp_with_p["id"], "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_fail2, 400)
        self.assertEqual(r_fail2["code"], "prompt_too_long")
        self.assertIn("提示词加上系统说明后超过 4000 字上限，请精简提示词", r_fail2["error"])

    def test_performance_boot_and_workspace(self) -> None:
        """10. Performance benchmark: 500 works, 200 history rows, 50 catalog secrets."""
        # Insert 50 secrets of 400 characters
        with self.db.transaction() as tx:
            for i in range(50):
                sec = f"SECRET_STYLE_{i:03d}_" + ("X" * 380)
                tx.execute(
                    """
                    INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                    VALUES (?, ?, 'style', 'exclusive', 'A', 5, '/img.webp', 'alice', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                    """,
                    (f"PERF-{i:03d}", f"画风{i}", sec),
                )

            # Insert 500 works with prompt_has_secret = 0
            for i in range(500):
                tx.execute(
                    """
                    INSERT INTO works (
                        id, author_username, author_name, title, images_json, styles_json, layout_code,
                        price, prompt, prompt_has_secret, notes, status, published_at_ms, created_at, updated_at
                    ) VALUES (?, 'bob', 'Bob', ?, '["/images/poster-demo-autumn-equinox.webp"]',
                              '["PERF-001"]', '', 0, '正常实测提示词', 0, '', 'published', ?,
                              '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                    """,
                    (f"perf_work_{i}", f"性能作品{i}", 1700000000000 + i),
                )

            # Insert 200 history rows with visible_prompt set
            for i in range(200):
                tx.execute(
                    """
                    INSERT INTO studio_generations (
                        id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                        prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                        status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                        prompt_ready, recipe_id
                    ) VALUES (?, ?, 'alice', '标题', '3:4', '直出', 'single', 'PERF-001',
                              'full prompt', 'visible prompt', 0, '[]', '', '[]', 'live', 'free_quota', 0, 't',
                              'success', '', ?, '2026-10-31', '2026-10-31T00:00:00Z', '', 1, '')
                    """,
                    (f"perf_gen_{i}", self.user_alice["id"], f"req_perf_{i}"),
                )

        t0 = time.perf_counter()
        st_boot, r_boot = self._req("GET", "/api/boot", cookie=self.cookie_a)
        t_boot = time.perf_counter() - t0
        self.assertEqual(st_boot, 200)

        t0 = time.perf_counter()
        st_ws, r_ws = self._req("GET", "/api/studio/workspace", cookie=self.cookie_a)
        t_ws = time.perf_counter() - t0
        self.assertEqual(st_ws, 200)
        print(f"\n[BENCHMARK] /api/boot: {t_boot*1000:.2f}ms, /api/studio/workspace: {t_ws*1000:.2f}ms")

        # Boot with 500 works and Workspace with 200 rows must run well under 1.5s
        self.assertLess(t_boot, 1.5, f"/api/boot took too long: {t_boot:.3f}s")
        self.assertLess(t_ws, 1.5, f"/api/studio/workspace took too long: {t_ws:.3f}s")

    def test_round3_g1_scan_failure_fails_closed(self) -> None:
        """G1: Secrets query failure stores NULL (never 0) and backfill aborts."""
        from backend.services import SecretsScanError, check_text_has_secret
        with patch("backend.services.get_secrets_cache", side_effect=SecretsScanError("DB lock")):
            # Writer must store prompt_has_secret = NULL
            wid = f"work_g1_fail_{int(time.time()*1000)}"
            st, res = self._req(
                "POST",
                "/api/works",
                {"title": "扫库失败作品", "notes": "扫库失败作品的完整创作说明记录", "prompt": "公开用户提示词", "images": ["/images/poster-demo-autumn-equinox.webp"], "price": 0},
                cookie=self.cookie_a,
            )
            self.assertEqual(st, 200)
            work_id = res["workId"]

            row = self.db.get_conn().execute("SELECT prompt, prompt_has_secret FROM works WHERE id = ?", (work_id,)).fetchone()
            self.assertIsNone(row["prompt_has_secret"], "Must store NULL on scan failure, never 0")

            # Reading a NULL row fails closed (masked)
            w_prompt, masked = get_work_client_prompt(row, is_admin_route=False)
            self.assertEqual(w_prompt, "")
            self.assertTrue(masked)

            # Backfill aborts and modifies nothing
            counts = run_blackbox_backfill(self.db)
            self.assertEqual(counts["works"], 0)
            row_after = self.db.get_conn().execute("SELECT prompt_has_secret FROM works WHERE id = ?", (work_id,)).fetchone()
            self.assertIsNone(row_after["prompt_has_secret"], "Must remain NULL when scan fails")

    def test_round3_g2_rescan_persisted_in_site_settings(self) -> None:
        """G2: Scanned secrets hash is persisted in site_settings and rescan triggers on hash change."""
        # Initial run persists hash
        run_blackbox_backfill(self.db)
        row = self.db.get_conn().execute("SELECT value_json FROM site_settings WHERE key = 'blackbox_secrets_hash'").fetchone()
        self.assertIsNotNone(row)
        stored_hash = json.loads(row["value_json"])["hash"]
        self.assertTrue(len(stored_hash) > 10)

        # Insert a new secret into catalog_assets
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-G2-NEW', '新画风', 'style', 'exclusive', 'A', 0, '/img.webp', 'alice', 'published', 'UNIQUE_G2_SECRET_STRING_XYZ_999', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """
            )

        # run_blackbox_backfill detects hash mismatch and updates persisted hash
        run_blackbox_backfill(self.db)
        row2 = self.db.get_conn().execute("SELECT value_json FROM site_settings WHERE key = 'blackbox_secrets_hash'").fetchone()
        new_hash = json.loads(row2["value_json"])["hash"]
        self.assertNotEqual(stored_hash, new_hash, "Hash in site_settings must be updated upon secret changes")

    def test_round3_g3_conditional_writes_avoid_clobbering_concurrent_edits(self) -> None:
        """G3: Backfill conditional writes use WHERE id = ? AND prompt = ? to avoid overwriting edits."""
        wid = f"work_g3_{int(time.time()*1000)}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, price, prompt, prompt_has_secret, notes, status, published_at_ms, created_at, updated_at)
                VALUES (?, 'alice', 'Alice', '并发测试', '[]', '[]', '', 0, '旧未扫描提示词', NULL, '', 'published', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (wid,),
            )

        # Simulate concurrent edit changing prompt right before backfill write
        with self.db.transaction() as tx:
            tx.execute("UPDATE works SET prompt = '用户并发保存的新提示词', prompt_has_secret = 0 WHERE id = ?", (wid,))

        # Run backfill: conditional write WHERE prompt = '旧未扫描提示词' will not match
        run_blackbox_backfill(self.db)
        row = self.db.get_conn().execute("SELECT prompt, prompt_has_secret FROM works WHERE id = ?", (wid,)).fetchone()
        self.assertEqual(row["prompt"], "用户并发保存的新提示词")
        self.assertEqual(row["prompt_has_secret"], 0)

    def test_round3_g4_and_g14_content_edit_author_flows(self) -> None:
        """G4 & G14: Topic edit returns masked recipe_json; work edit omitting prompt preserves stored text."""
        # 1. Topic edit (G4)
        tid = f"topic_g4_{int(time.time()*1000)}"
        recipe_with_secret = {"styles": ["FX-P3S-PAID"], "prompt": f"包含秘密：{self.paid_secret}", "theme": "松鼠"}
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, pinned, featured, title, author_username, author_name, views, likes, favorites, price, bounty, bounty_status, solved, accepted_reply_id, images_json, styles_json, layout_code, work_id, recipe_json, recipe_has_secret, summary, locked_body, status, published_at_ms, created_label, created_at, updated_at)
                VALUES (?, 'assets', '专区', 0, 0, '帖子标题', 'alice', 'Alice', 10, 0, 0, 0, 0, 'none', 0, '', '[]', '[]', '', '', ?, 1, '摘要', '', 'published', 1700000000000, '刚刚', '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (tid, json.dumps(recipe_with_secret)),
            )

        st_top_edit, r_top_edit = self._req("GET", f"/api/content/topics/{tid}/edit", cookie=self.cookie_a)
        self.assertEqual(st_top_edit, 200)
        top_item = r_top_edit.get("item", {})
        self.assertTrue(top_item.get("promptMasked"))
        raw_top_json = top_item.get("recipe_json", "")
        self.assertNotIn(self.paid_secret, raw_top_json)

        # 2. Masked work edit title only (G14)
        wid = f"work_g14_{int(time.time()*1000)}"
        secret_prompt = f"我的私人作品提示词包含秘密：{self.paid_secret}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, price, prompt, prompt_has_secret, notes, status, published_at_ms, created_at, updated_at)
                VALUES (?, 'alice', 'Alice', '旧标题', '[]', '[]', '', 0, ?, 1, '', 'published', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (wid, secret_prompt),
            )

        # Author edits only title (omitting prompt) -> MUST succeed 200 and NOT fail with 400
        st_edit, r_edit = self._req(
            "POST",
            f"/api/content/works/{wid}/edit",
            {"title": "更新后的新标题"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_edit, 200, f"Omitting prompt on masked work must succeed: {r_edit}")

        # Check DB: title is updated, stored prompt and flag are preserved
        row_w = self.db.get_conn().execute("SELECT title, prompt, prompt_has_secret FROM works WHERE id = ?", (wid,)).fetchone()
        self.assertEqual(row_w["title"], "更新后的新标题")
        self.assertEqual(row_w["prompt"], secret_prompt)
        self.assertEqual(row_w["prompt_has_secret"], 1)

    def test_round3_g5_recipe_structure_only_and_escaped_secrets(self) -> None:
        """G5: Flagged recipe keeps only structure (theme, cards[].prompt stripped); secrets with newlines/quotes detected."""
        # Insert secret containing newline and double quotes
        escaped_secret = "Line1\nLine2 \"SpecialQuote\" \\Backslash"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-G5-ESC', '转义画风', 'style', 'exclusive', 'A', 0, '/img.webp', 'alice', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (escaped_secret,),
            )

        # Post topic with recipe containing that secret in a card
        recipe_data = {
            "styleIds": ["FX-G5-ESC"],
            "layoutId": "LX-001",
            "ratio": "3:4",
            "mode": "graphic-text",
            "theme": "这是敏感主题",
            "prompt": "自由提示词",
            "cards": [
                {"prompt": f"嵌套卡片敏感提示词: {escaped_secret}", "styleIds": ["FX-G5-ESC"], "ratio": "16:9"}
            ],
        }

        st_post, r_post = self._req(
            "POST",
            "/api/forum/topics",
            {
                "category": "experience",
                "title": "测试复杂配方脱敏",
                "content": "正文内容",
                "recipe": recipe_data,
            },
            cookie=self.cookie_a,
        )
        self.assertEqual(st_post, 200)
        tid = r_post["topicId"]

        # Check database: recipe_has_secret must be 1
        top_row = self.db.get_conn().execute("SELECT recipe_has_secret FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertEqual(top_row["recipe_has_secret"], 1, "Decoded strings scan must detect escaped secrets")

        # Client read
        st_get, r_get = self._req("GET", f"/api/posts/{tid}", cookie=self.cookie_b)
        self.assertEqual(st_get, 200)
        rec = r_get.get("topic", {}).get("recipe", {})
        self.assertTrue(rec.get("promptMasked"))
        self.assertEqual(rec.get("prompt"), "")
        self.assertNotIn("theme", rec, "theme must be stripped from masked recipe")
        self.assertEqual(rec.get("layoutId"), "LX-001", "structural fields must be kept")
        cards = rec.get("cards") or []
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].get("prompt"), "")
        self.assertTrue(cards[0].get("promptMasked"))
        self.assertEqual(cards[0].get("ratio"), "16:9")

    def test_round3_g6_and_g7_curation_approval_and_payload_sanitization(self) -> None:
        """G6 & G7: Curation approval computes prompt_has_secret; curation endpoints mask submission payloads."""
        # 1. Curation payload masking (G7)
        sub_id = f"sub_g7_{int(time.time()*1000)}"
        secret_payload = {
            "kind": "work",
            "title": "投稿含黑盒作品",
            "prompt": f"用户投稿文字\n\n{self.paid_secret}",
            "styles": ["FX-P3S-PAID"],
            "images": ["/images/poster-demo-autumn-equinox.webp"],
            "price": 0,
        }
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO curation_submissions (id, owner_user_id, owner_username, kind, target_id, current_revision, status, topic_id, created_at, updated_at)
                VALUES (?, ?, 'alice', 'work', ?, 1, 'pending', 'topic_sub_g7', '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (sub_id, self.user_alice["id"], f"work_{sub_id}"),
            )
            tx.execute(
                """
                INSERT INTO curation_versions (submission_id, revision, payload_json, created_at)
                VALUES (?, 1, ?, '2026-10-31T00:00:00Z')
                """,
                (sub_id, json.dumps(secret_payload, ensure_ascii=False)),
            )

        # GET /api/curation/mine (author view)
        st_mine, r_mine = self._req("GET", "/api/curation/mine", cookie=self.cookie_a)
        self.assertEqual(st_mine, 200)
        raw_mine = json.dumps(r_mine, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_mine)
        sub_mine = next(s for s in r_mine.get("submissions", r_mine.get("items", [])) if s["id"] == sub_id)
        self.assertEqual(sub_mine["payload"]["prompt"], "[包含资源专属指令，已隐藏]")

        # GET /api/curation/admin (admin overview)
        st_adm_cur, r_adm_cur = self._req("GET", "/api/curation/admin", cookie=self.cookie_admin)
        self.assertEqual(st_adm_cur, 200)
        raw_adm_cur = json.dumps(r_adm_cur, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_adm_cur)
        pending_sub = next(s for s in r_adm_cur["pending"] if s["id"] == sub_id)
        self.assertEqual(pending_sub["payload"]["prompt"], "[包含资源专属指令，已隐藏]")

        # 2. Curation approval computes flag (G6)
        from backend.curation import _publish_approved
        target_work_id = f"work_{sub_id}"
        with self.db.transaction() as tx:
            sub_row = dict(tx.execute("SELECT * FROM curation_submissions WHERE id = ?", (sub_id,)).fetchone())
            _publish_approved(tx, sub_row, 1)

        approved_work = self.db.get_conn().execute(
            "SELECT prompt, prompt_has_secret FROM works WHERE id = ?", (target_work_id,)
        ).fetchone()
        self.assertIsNotNone(approved_work)
        self.assertEqual(approved_work["prompt_has_secret"], 1, "Approved work containing secret must have flag 1")

    def test_round3_g8_reconciler_and_polling_generic_error(self) -> None:
        """G8: Polling and reconciler errors keep generic message, never leaking upstream body."""
        # Check reconciler error storage
        gid = f"gen_g8_{int(time.time()*1000)}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                    status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                    prompt_ready, recipe_id
                ) VALUES (?, ?, 'alice', '标题', '3:4', '直出', 'single', '',
                          'prompt', 'visible', 0, '[]', '', '[]', 'live', 'free_quota', 0, 'tid_g8',
                          'running', '', 'req_g8', '2026-10-31', '2026-10-31T00:00:00Z', '', 1, '')
                """,
                (gid, self.user_alice["id"]),
            )

        # Mock gateway response with sensitive error body
        sensitive_error = f"Gateway rejected prompt containing {self.paid_secret}"
        mock_item = {"id": "tid_g8", "status": "failed", "error": sensitive_error}

        from backend.server import GenerationReconciler
        reconciler = GenerationReconciler(self.db)
        with patch("backend.server.gateway_request", return_value={"items": [mock_item]}):
            reconciler.reconcile_once()

        row = self.db.get_conn().execute("SELECT status, error_msg FROM studio_generations WHERE id = ?", (gid,)).fetchone()
        self.assertEqual(row["status"], "refunded")
        self.assertNotIn(self.paid_secret, row["error_msg"])
        self.assertEqual(row["error_msg"], "云端任务失败 (failed)")

    def test_round3_g9_client_submitted_prompt_with_secret_is_masked(self) -> None:
        """G9: Submitting a prompt containing a known secret sets prompt_masked = 1 and returns empty finalPrompt."""
        st_gen, r_gen = self._req(
            "POST",
            "/api/studio/generate",
            {
                "prompt": f"用户直接输入盗取来的黑盒指令: {self.paid_secret}",
                "requestId": f"req_g9_{int(time.time()*1000)}",
                "simulateGateway": "ok",
            },
            cookie=self.cookie_a,
        )
        self.assertEqual(st_gen, 200)
        self.assertTrue(r_gen.get("promptMasked"))
        self.assertEqual(r_gen.get("finalPrompt"), "")
        self.assertNotIn(self.paid_secret, json.dumps(r_gen, ensure_ascii=False))

        row = self.db.get_conn().execute("SELECT prompt, visible_prompt, prompt_masked FROM studio_generations WHERE id = ?", (r_gen["genId"],)).fetchone()
        self.assertEqual(row["prompt_masked"], 1)
        self.assertEqual(row["visible_prompt"], "")

    def test_round3_g10_legacy_backfill_suffix_only_stripping(self) -> None:
        """G10: Legacy backfill strips only trailing injected suffix; secrets inside user text are not mangled."""
        gid1 = f"gen_g10_suffix_{int(time.time()*1000)}"
        gid2 = f"gen_g10_embedded_{int(time.time()*1000)}"
        user_text = "画一只猫在飞"

        with self.db.transaction() as tx:
            # 1. Clean suffix: "user text\n\nsecret"
            tx.execute(
                """
                INSERT INTO studio_generations (id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary, prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id, status, error_msg, request_id, reservation_date, created_at, fork_work_id, prompt_ready, recipe_id)
                VALUES (?, ?, 'alice', '标题', '3:4', '直出', 'single', '', ?, NULL, 0, NULL, '', '[]', 'live', 'free_quota', 0, 't1', 'success', '', ?, '2026-10-31', '2026-10-31T00:00:00Z', '', 1, '')
                """,
                (gid1, self.user_alice["id"], f"{user_text}\n\n{self.paid_secret}", f"req_{gid1}"),
            )
            # 2. Embedded in user text: "user text secret more text"
            tx.execute(
                """
                INSERT INTO studio_generations (id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary, prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id, status, error_msg, request_id, reservation_date, created_at, fork_work_id, prompt_ready, recipe_id)
                VALUES (?, ?, 'alice', '标题', '3:4', '直出', 'single', '', ?, NULL, 0, NULL, '', '[]', 'live', 'free_quota', 0, 't2', 'success', '', ?, '2026-10-31', '2026-10-31T00:00:00Z', '', 1, '')
                """,
                (gid2, self.user_alice["id"], f"{user_text} {self.paid_secret} 其它内容", f"req_{gid2}"),
            )

        run_blackbox_backfill(self.db)

        # Row 1 (suffix): clean prefix restored
        r1 = self.db.get_conn().execute("SELECT prompt, visible_prompt, prompt_masked FROM studio_generations WHERE id = ?", (gid1,)).fetchone()
        self.assertEqual(r1["visible_prompt"], user_text)
        self.assertEqual(r1["prompt_masked"], 0)

        # Row 2 (embedded): prompt not mangled, visible_prompt masked to empty string
        r2 = self.db.get_conn().execute("SELECT prompt, visible_prompt, prompt_masked FROM studio_generations WHERE id = ?", (gid2,)).fetchone()
        self.assertEqual(r2["prompt"], f"{user_text} {self.paid_secret} 其它内容", "Original prompt must never be mangled")
        self.assertEqual(r2["visible_prompt"], "")
        self.assertEqual(r2["prompt_masked"], 1)

    def test_round3_g12_polling_images_list_of_url_strings(self) -> None:
        """G12: Polling /api/studio/tasks returns images as a list of URL strings, compatible with studio-app.js."""
        gid = f"gen_g12_{int(time.time()*1000)}"
        image_urls = ["/generated/test_image_1.webp", "/generated/test_image_2.webp"]
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                    status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                    prompt_ready, recipe_id
                ) VALUES (?, ?, 'alice', '标题', '3:4', '直出', 'single', '',
                          'prompt', 'visible', 0, '[]', '', ?, 'live', 'free_quota', 0, 'tid_g12',
                          'success', '', 'req_g12', '2026-10-31', '2026-10-31T00:00:00Z', '', 1, '')
                """,
                (gid, self.user_alice["id"], json.dumps(image_urls)),
            )

        st_poll, r_poll = self._req("GET", "/api/studio/tasks?requestId=req_g12", cookie=self.cookie_a)
        self.assertEqual(st_poll, 200)
        images = r_poll.get("images")
        self.assertIsInstance(images, list)
        self.assertEqual(images, image_urls, "Polling images must be a list of URL strings")
        self.assertIsInstance(images[0], str)

    def test_round4_h1_structured_recipe_shapes_and_strict_typed_rebuild(self) -> None:
        """H1: Recipe rebuild from typed fields; handles string, string array, nested dict, cards, sharedCard."""
        from backend.services import mask_recipe_data
        # 1. String recipe
        r_str = f"秘密配方字符串: {self.paid_secret}"
        m_str = mask_recipe_data(r_str)
        self.assertEqual(m_str["prompt"], "")
        self.assertTrue(m_str["promptMasked"])
        self.assertNotIn(self.paid_secret, json.dumps(m_str, ensure_ascii=False))

        # 2. String array recipe
        r_arr = ["FX-P3S-PAID", f"secret string in array: {self.paid_secret}"]
        m_arr = mask_recipe_data(r_arr)
        self.assertEqual(m_arr["prompt"], "")
        self.assertTrue(m_arr["promptMasked"])
        self.assertNotIn(self.paid_secret, json.dumps(m_arr, ensure_ascii=False))

        # 3. Rich nested dict with various shapes
        r_dict = {
            "id": "RCP-001",
            "kind": "single",
            "styleIds": ["FX-P3S-PAID", {"prompt": f"nested secret {self.paid_secret}"}, "INVALID!@#CODE"],
            "layoutId": "LX-001",
            "colors": ["#FF0000", "C-01"],
            "tones": ["T-01"],
            "moods": ["治愈"],
            "whitespace": "ample",
            "ratio": "3:4",
            "mode": "graphic-text",
            "count": 3,
            "theme": f"free text theme {self.paid_secret}",
            "subject": f"free text subject {self.paid_secret}",
            "description": f"free text description {self.paid_secret}",
            "cards": [
                f"raw string card with secret {self.paid_secret}",
                12345,
                {
                    "styleIds": ["FX-P3S-PAID", {"bad": "object"}],
                    "layoutId": "LX-002",
                    "prompt": f"card secret prompt {self.paid_secret}",
                    "unknown_field": "some text",
                },
            ],
            "sharedCard": {
                "layoutId": "LX-001",
                "references": [
                    "/images/valid.webp",
                    {"prompt": f"nested reference secret {self.paid_secret}"},
                ],
            },
        }

        m_dict = mask_recipe_data(r_dict)
        raw_m_dict = json.dumps(m_dict, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_m_dict, "Masked recipe must not contain secret anywhere!")
        self.assertEqual(m_dict["prompt"], "")
        self.assertTrue(m_dict["promptMasked"])
        self.assertNotIn("theme", m_dict)
        self.assertNotIn("subject", m_dict)
        self.assertNotIn("description", m_dict)

        # In styleIds, dict and invalid code were dropped
        self.assertEqual(m_dict["styleIds"], ["FX-P3S-PAID"])
        # Real catalog codes kept; invalid color code dropped
        self.assertEqual(m_dict["colors"], ["C-01"])
        self.assertEqual(m_dict["tones"], ["T-01"])
        self.assertEqual(m_dict["layoutId"], "LX-001")
        # J1/J2: moods, whitespace, references are entirely omitted
        self.assertNotIn("moods", m_dict)
        self.assertNotIn("whitespace", m_dict)
        self.assertNotIn("references", m_dict)

        # In cards, non-dict items were dropped; valid card was rebuilt with prompt stripped
        self.assertEqual(len(m_dict["cards"]), 1)
        self.assertEqual(m_dict["cards"][0]["styleIds"], ["FX-P3S-PAID"])
        self.assertEqual(m_dict["cards"][0]["layoutId"], "LX-002")
        self.assertEqual(m_dict["cards"][0]["prompt"], "")
        self.assertTrue(m_dict["cards"][0]["promptMasked"])
        self.assertNotIn("unknown_field", m_dict["cards"][0])

        # In sharedCard, references is omitted and layoutId kept
        self.assertEqual(m_dict["sharedCard"]["layoutId"], "LX-001")
        self.assertNotIn("references", m_dict["sharedCard"])

    def test_round4_h2_h5_h6_scan_failure_recovery_and_catchup_scan(self) -> None:
        """H2, H5, H6: Scan failure -> stores visible_prompt=NULL -> recovery -> catch-up rescan."""
        from backend.services import SecretsScanError

        # 1. H6: Scan failure during generation upload stores visible_prompt = NULL
        with patch("backend.services.check_text_has_secret", side_effect=SecretsScanError("DB lock")):
            st_hist, r_hist = self._req(
                "POST",
                "/api/studio/history",
                {
                    "id": f"hist_fail_{int(time.time()*1000)}",
                    "prompt": "正常用户文字内容无秘密",
                    "tabTitle": "测试历史",
                },
                cookie=self.cookie_a,
            )
            self.assertEqual(st_hist, 200)
            hid = r_hist.get("id") or r_hist.get("item", {}).get("id") or f"hist_fail_{int(time.time()*1000)}"

        # Verify DB row has visible_prompt = NULL
        row_fail = self.db.get_conn().execute(
            "SELECT visible_prompt, prompt_masked FROM studio_generations WHERE id = ?", (hid,)
        ).fetchone()
        self.assertIsNotNone(row_fail)
        self.assertIsNone(row_fail["visible_prompt"], "Scan failure must store visible_prompt = NULL (H6)")
        self.assertEqual(row_fail["prompt_masked"], 0)

        # Read time fails closed (H6)
        vis, masked = get_generation_visible_prompt(row_fail)
        self.assertEqual(vis, "")
        self.assertTrue(masked)

        # 2. H2: If scan fails during backfill, row is skipped and scan hash is NOT saved
        with patch("backend.services.check_text_has_secret", side_effect=SecretsScanError("DB lock")):
            run_blackbox_backfill(self.db, force=True)

        # Verify row is still NULL
        row_still_null = self.db.get_conn().execute(
            "SELECT visible_prompt FROM studio_generations WHERE id = ?", (hid,)
        ).fetchone()
        self.assertIsNone(row_still_null["visible_prompt"])

        # 3. Recovery (H2, H6): Secrets query works again, backfill recovers row
        counts = run_blackbox_backfill(self.db, force=True)
        self.assertGreaterEqual(counts["generations"], 1)

        row_recovered = self.db.get_conn().execute(
            "SELECT visible_prompt, prompt_masked FROM studio_generations WHERE id = ?", (hid,)
        ).fetchone()
        self.assertEqual(row_recovered["visible_prompt"], "正常用户文字内容无秘密")
        self.assertEqual(row_recovered["prompt_masked"], 0)

        # Verify hash was persisted in site_settings (H2)
        st_row = self.db.get_conn().execute(
            "SELECT value_json FROM site_settings WHERE key = 'blackbox_secrets_hash'"
        ).fetchone()
        self.assertIsNotNone(st_row)

        # 4. H5: Secret set changes -> rescans generations already having visible_prompt
        new_secret = "BRAND_NEW_CATALOG_SECRET_2026_XYZ"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-NEW-2026', '新画风', 'style', 'exclusive', 'free', 0, '/img.webp', 'alice', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (new_secret,),
            )
            # Create a generation that has visible_prompt containing new_secret
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                    status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                    prompt_ready, recipe_id
                ) VALUES ('gen_h5_test', ?, 'alice', '标题', '3:4', '直出', 'single', '',
                          ?, ?, 0, '[]', '', '[]', 'live', 'free_quota', 0, 't_h5',
                          'success', '', 'req_h5', '2026-10-31', '2026-10-31T00:00:00Z', '', 1, '')
                """,
                (self.user_alice["id"], f"提示词含新秘密 {new_secret}", f"提示词含新秘密 {new_secret}"),
            )

        # Run backfill: it detects hash change and rescans existing visible_prompt
        run_blackbox_backfill(self.db)

        row_h5_after = self.db.get_conn().execute(
            "SELECT visible_prompt, prompt_masked FROM studio_generations WHERE id = 'gen_h5_test'"
        ).fetchone()
        self.assertEqual(row_h5_after["visible_prompt"], "")
        self.assertEqual(row_h5_after["prompt_masked"], 1, "Generation with visible_prompt containing new secret must be masked (H5)")

    def test_round4_h3_curation_title_only_edit_sanitized(self) -> None:
        """H3: Editing work with curation submission returns sanitized payload on revise."""
        sub_id = f"sub_h3_{int(time.time()*1000)}"
        work_id = f"work_{sub_id}"
        secret_payload = {
            "kind": "work",
            "title": "旧作品标题",
            "prompt": f"用户投稿文字\n\n{self.paid_secret}",
            "styles": ["FX-P3S-PAID"],
            "images": ["/images/poster-demo-autumn-equinox.webp"],
            "price": 0,
        }
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO curation_submissions (id, owner_user_id, owner_username, kind, target_id, current_revision, status, topic_id, created_at, updated_at)
                VALUES (?, ?, 'alice', 'work', ?, 1, 'pending', 'topic_h3', '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (sub_id, self.user_alice["id"], work_id),
            )
            tx.execute(
                """
                INSERT INTO curation_versions (submission_id, revision, payload_json, created_at)
                VALUES (?, 1, ?, '2026-10-31T00:00:00Z')
                """,
                (sub_id, json.dumps(secret_payload, ensure_ascii=False)),
            )
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, price, prompt, prompt_has_secret, notes, status, published_at_ms, created_at, updated_at)
                VALUES (?, 'alice', 'Alice', '旧作品标题', '["/images/poster-demo-autumn-equinox.webp"]', '["FX-P3S-PAID"]', '', 0, ?, 1, '', 'published', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (work_id, secret_payload["prompt"]),
            )

        # Alice edits only title via /api/content/works/{work_id}/edit
        st_edit, r_edit = self._req(
            "POST",
            f"/api/content/works/{work_id}/edit",
            {"title": "新修改的作品标题"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_edit, 200)
        raw_res = json.dumps(r_edit, ensure_ascii=False)
        self.assertNotIn(self.paid_secret, raw_res, "Title-only curation edit must never leak secret in revise response (H3)")
        self.assertEqual(r_edit["payload"]["prompt"], "[包含资源专属指令，已隐藏]")

    def test_round4_h4_stored_error_text_mapped_to_generic(self) -> None:
        """H4: Stored error text in legacy generations mapped to generic status/code, never leaked."""
        gid = f"gen_h4_{int(time.time()*1000)}"
        leak_msg = f"Upstream HTTP 400 error body containing leaked secret: {self.paid_secret}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                    status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                    prompt_ready, recipe_id
                ) VALUES (?, ?, 'alice', '标题', '3:4', '直出', 'single', '',
                          'prompt', 'vis', 0, '[]', '', '[]', 'live', 'free_quota', 0, 't_h4',
                          'failed', ?, 'req_h4', '2026-10-31', '2026-10-31T00:00:00Z', '', 1, '')
                """,
                (gid, self.user_alice["id"], leak_msg),
            )

        # Check /api/studio/workspace
        st_ws, r_ws = self._req("GET", "/api/studio/workspace", cookie=self.cookie_a)
        self.assertEqual(st_ws, 200)
        self.assertNotIn(self.paid_secret, json.dumps(r_ws, ensure_ascii=False))
        h4_entry = next(h for h in r_ws["history"] if h["id"] == gid)
        self.assertEqual(h4_entry["error"], "网关请求失败 (HTTP 400)")

        # Check /api/studio/tasks
        st_task, r_task = self._req("GET", "/api/studio/tasks?requestId=req_h4", cookie=self.cookie_a)
        self.assertEqual(st_task, 200)
        self.assertNotIn(self.paid_secret, json.dumps(r_task, ensure_ascii=False))
        self.assertEqual(r_task["error"], "网关请求失败 (HTTP 400)")

    def test_round4_h7_legacy_strip_only_matches_double_newline_suffix(self) -> None:
        """H7: Legacy suffix stripping only matches double-newline suffix, never single-newline mid-text."""
        gid = f"gen_h7_{int(time.time()*1000)}"
        prompt_with_single_nl = f"pets:\n{self.free_secret}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                    status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                    prompt_ready, recipe_id
                ) VALUES (?, ?, 'alice', '标题', '3:4', '直出', 'single', '',
                          ?, NULL, 0, '[]', '', '[]', 'live', 'free_quota', 0, 't_h7',
                          'success', '', 'req_h7', '2026-10-31', '2026-10-31T00:00:00Z', '', 1, '')
                """,
                (gid, self.user_alice["id"], prompt_with_single_nl),
            )

        run_blackbox_backfill(self.db)

        r_after = self.db.get_conn().execute(
            "SELECT prompt, visible_prompt, prompt_masked FROM studio_generations WHERE id = ?", (gid,)
        ).fetchone()
        self.assertEqual(r_after["prompt"], prompt_with_single_nl, "Prompt must remain untouched")
        # Because it's single newline, it must NOT strip to "pets:"; it must mask instead!
        self.assertEqual(r_after["visible_prompt"], "")
        self.assertEqual(r_after["prompt_masked"], 1)

    def test_round4_h8_single_secrets_query_per_backfill_round(self) -> None:
        """H8: Secrets cache is loaded once per backfill round."""
        import backend.services as services
        orig_get_cache = services.get_secrets_cache
        query_count = 0

        def counted_get_cache(conn=None, force=False):
            nonlocal query_count
            query_count += 1
            return orig_get_cache(conn, force=force)

        with patch.object(services, "get_secrets_cache", side_effect=counted_get_cache):
            services.run_blackbox_backfill(self.db, force=True)

        self.assertEqual(query_count, 1, f"Expected exactly 1 get_secrets_cache call per backfill, got {query_count}")

    def test_round4_h9_gateway_exception_logs_only_type(self) -> None:
        """H9: Generic gateway exception logs only type, never secret text."""
        import logging

        class LeakException(Exception):
            def __str__(self):
                return f"Exception containing secret {self.paid_secret}"

        with self.assertLogs("backend.server", level="WARNING") as cm:
            with patch("backend.server.gateway_request", side_effect=LeakException()):
                with patch("backend.server.load_image_service_config", return_value={"enabled": True}):
                    self._req(
                        "POST",
                        "/api/studio/generate",
                        {"prompt": "生图", "style1": "FX-P3S-PAID", "requestId": f"req_h9_{int(time.time()*1000)}"},
                        cookie=self.cookie_a,
                    )

        log_output = "\n".join(cm.output)
        self.assertNotIn(self.paid_secret, log_output, "Server logs must never contain secret text (H9)")
        self.assertIn("Gateway exception: LeakException", log_output)

    def test_round4_j1_j2_j3_strict_hiding_and_code_validation(self) -> None:
        """J1-J3: Strict whole-item hiding for moods/whitespace/references, real catalog code validation, and unmasked preservation."""
        from backend.services import mask_recipe_data, get_topic_client_recipe_json

        short_secret = "cat"
        long_secret = self.paid_secret  # "PAID_TOP_SECRET_BLACKBOX_KEYWORD_2026"
        secret_20 = long_secret[:20]

        # Ensure short_secret is in catalog_assets for this test so it is detected as secret
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT OR IGNORE INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-SHORT-SEC', '短词画风', 'style', 'exclusive', 'A', 10, '/img.webp', 'alice', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (short_secret,),
            )

        # 1. J1 reproduction: moods and whitespace containing secret / 20-char snippet
        # Must be completely omitted (整项隐藏) from root, cards, and sharedCard
        r_j1 = {
            "kind": "single",
            "styleIds": ["FX-P3S-PAID"],
            "layoutId": "LX-001",
            "moods": [f"mood_{secret_20}", "治愈"],
            "whitespace": f"ws_{secret_20}",
            "cards": [
                {
                    "styleIds": ["FX-P3S-PAID"],
                    "layoutId": "LX-002",
                    "moods": [f"card_mood_{secret_20}"],
                    "whitespace": f"card_ws_{secret_20}",
                }
            ],
            "sharedCard": {
                "layoutId": "LX-001",
                "moods": [f"shared_mood_{secret_20}"],
                "whitespace": f"shared_ws_{secret_20}",
            },
        }
        m_j1 = mask_recipe_data(r_j1, conn=self.db.get_conn())
        raw_j1 = json.dumps(m_j1, ensure_ascii=False)
        self.assertNotIn(secret_20, raw_j1, "J1: 20-char secret snippet must not appear in masked recipe JSON")
        self.assertNotIn("moods", m_j1)
        self.assertNotIn("whitespace", m_j1)
        self.assertNotIn("moods", m_j1["cards"][0])
        self.assertNotIn("whitespace", m_j1["cards"][0])
        self.assertNotIn("moods", m_j1["sharedCard"])
        self.assertNotIn("whitespace", m_j1["sharedCard"])

        # 2. J2 reproduction: references containing /images/<full_secret>.webp
        # Must be completely omitted (整项隐藏) from root, cards, and sharedCard
        ref_leak_url = f"/images/{long_secret}.webp"
        r_j2 = {
            "kind": "single",
            "styleIds": ["FX-P3S-PAID"],
            "layoutId": "LX-001",
            "references": [ref_leak_url],
            "cards": [
                {
                    "styleIds": ["FX-P3S-PAID"],
                    "references": [ref_leak_url],
                }
            ],
            "sharedCard": {
                "layoutId": "LX-001",
                "references": [ref_leak_url],
            },
        }
        m_j2 = mask_recipe_data(r_j2, conn=self.db.get_conn())
        raw_j2 = json.dumps(m_j2, ensure_ascii=False)
        self.assertNotIn(long_secret, raw_j2, "J2: Full secret in references URL must not appear anywhere")
        self.assertNotIn("references", m_j2)
        self.assertNotIn("references", m_j2["cards"][0])
        self.assertNotIn("references", m_j2["sharedCard"])

        # Also test Bob requesting GET /api/posts/{tid} for a topic with masked recipe
        tid_j2 = f"top_j2_{int(time.time()*1000)}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO forum_topics (id, author_username, author_name, category, category_label, title, summary, locked_body, recipe_json, recipe_has_secret, price, status, published_at_ms, created_at, updated_at)
                VALUES (?, 'alice', 'Alice', 'showcase', '作品', 'J2泄露复现帖', '测试摘要', '', ?, 1, 0, 'published', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (tid_j2, json.dumps(r_j2, ensure_ascii=False)),
            )
        st_post, r_post = self._req("GET", f"/api/posts/{tid_j2}", cookie=self.cookie_b)
        self.assertEqual(st_post, 200)
        raw_post = json.dumps(r_post, ensure_ascii=False)
        self.assertNotIn(long_secret, raw_post, "GET /api/posts/{tid} must not leak secret from references to Bob")
        rec_post = r_post["topic"]["recipe"]
        self.assertNotIn("references", rec_post)
        if "sharedCard" in rec_post and rec_post["sharedCard"]:
            self.assertNotIn("references", rec_post["sharedCard"])

        # 3. J3 reproduction: Short English word secret (e.g. 'cat') as code in styleIds, layoutId, colors, tones
        # Non-catalog codes must be dropped! Real catalog codes must be kept.
        r_j3 = {
            "kind": "single",
            "styleIds": [short_secret, "FX-P3S-PAID"],
            "layoutId": short_secret,
            "colors": [short_secret, "C-01"],
            "tones": [short_secret, "T-01"],
            "cards": [
                {
                    "styleIds": [short_secret, "FX-P3S-PAID"],
                    "layoutId": short_secret,
                    "colors": [short_secret, "C-01"],
                    "tones": [short_secret, "T-01"],
                }
            ],
            "sharedCard": {
                "id": short_secret,
                "layoutId": short_secret,
            },
        }
        m_j3 = mask_recipe_data(r_j3, conn=self.db.get_conn())
        raw_j3 = json.dumps(m_j3, ensure_ascii=False)
        self.assertNotIn(f'"{short_secret}"', raw_j3, "J3: Short English word secret must not pass through code fields")
        self.assertEqual(m_j3["styleIds"], ["FX-P3S-PAID"])
        self.assertNotIn("layoutId", m_j3)
        self.assertEqual(m_j3["colors"], ["C-01"])
        self.assertEqual(m_j3["tones"], ["T-01"])
        self.assertEqual(m_j3["cards"][0]["styleIds"], ["FX-P3S-PAID"])
        self.assertNotIn("layoutId", m_j3["cards"][0])
        self.assertEqual(m_j3["cards"][0]["colors"], ["C-01"])
        self.assertEqual(m_j3["cards"][0]["tones"], ["T-01"])
        self.assertNotIn("id", m_j3["sharedCard"])
        self.assertNotIn("layoutId", m_j3["sharedCard"])

        # 4. Preservation of unmasked recipes (recipe_has_secret == 0)
        # Must retain moods, whitespace, references, and codes untouched
        clean_recipe = {
            "kind": "single",
            "styleIds": ["FA-001"],
            "layoutId": "SB-001",
            "colors": ["C-15"],
            "tones": ["T-01"],
            "moods": ["治愈", "童趣"],
            "whitespace": "ample",
            "references": ["/images/legit_ref.webp"],
            "cards": [
                {
                    "styleIds": ["FA-001"],
                    "moods": ["松弛"],
                    "whitespace": "compact",
                    "references": ["/images/legit_card_ref.webp"],
                }
            ],
            "sharedCard": {
                "layoutId": "LX-001",
                "references": ["/images/legit_shared_ref.webp"],
            },
        }
        tid_clean = f"top_clean_{int(time.time()*1000)}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO forum_topics (id, author_username, author_name, category, category_label, title, summary, locked_body, recipe_json, recipe_has_secret, price, status, published_at_ms, created_at, updated_at)
                VALUES (?, 'alice', 'Alice', 'showcase', '作品', '正常未标记配方帖', '测试摘要', '', ?, 0, 0, 'published', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (tid_clean, json.dumps(clean_recipe, ensure_ascii=False)),
            )
        st_clean, r_clean = self._req("GET", f"/api/posts/{tid_clean}", cookie=self.cookie_b)
        self.assertEqual(st_clean, 200)
        unmasked_out = r_clean["topic"]["recipe"]
        self.assertEqual(unmasked_out["moods"], ["治愈", "童趣"])
        self.assertEqual(unmasked_out["whitespace"], "ample")
        self.assertEqual(unmasked_out["references"], ["/images/legit_ref.webp"])
        self.assertEqual(unmasked_out["cards"][0]["moods"], ["松弛"])
        self.assertEqual(unmasked_out["cards"][0]["references"], ["/images/legit_card_ref.webp"])
        self.assertEqual(unmasked_out["sharedCard"]["references"], ["/images/legit_shared_ref.webp"])
        self.assertEqual(unmasked_out["styleIds"], ["FA-001"])
        self.assertEqual(unmasked_out["layoutId"], "SB-001")
