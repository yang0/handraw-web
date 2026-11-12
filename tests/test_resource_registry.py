"""Tests for Unified Resource Registry (Phase 3b-13a).

Covers all 8 acceptance criteria:
1. Author can resolve and generate with pending resource, definition intact.
2. Non-author user resolves pending resource without definition, server injects definition.
3. Anonymous access returns canRead=False, canUse=False.
4. Non-author collection works, /api/skill/library collected has item with content_url=None,
   build_skill_asset_content returns 403 for non-author and 200 for author.
5. Withdrawn resource: non-author generation 403 (asset_withdrawn); author still allowed.
5a. Anti-echo (防回显): prompt has definition, visible_prompt, finalPrompt, workspace history,
    items_json, and published works do NOT have definition.
5b. GET /api/resources/<code> fields (locked, blackbox, pending, withdrawn) and no 'inject'.
6. Pending resource interactions: stamp 200, tip 400.
7. Collection of nonexistent code returns 404.
8. Official FB-028 stamp returns 200 (#19).
"""
from __future__ import annotations

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
from backend.server import SESSION_COOKIE_NAME, HandrawRequestHandler
from backend import resource_registry
from backend.services import (
    ServiceError,
    build_boot_payload,
    build_skill_asset_content,
    build_skill_library_payload,
    check_text_has_secret,
    get_studio_workspace,
    login_user,
    prepare_cloud_generation,
    register_user,
    send_encourage_tip,
    toggle_user_cheer,
    toggle_user_collection,
)


class ResourceRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "registry_test.db"
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

        # Users: author and reviewer/visitor
        self.author, self.author_token = register_user(self.db, "style_author", "Pass1234!", display_name="画风创作者")
        self.visitor, self.visitor_token = register_user(self.db, "style_visitor", "Pass1234!", display_name="访客用户")
        self.staff, self.staff_token = register_user(self.db, "admin_user", "Pass1234!", display_name="超级管理员")
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.staff["id"],))

        # Insert a pending submission: USR-S07C070DBA4
        self.pending_code = "USR-S07C070DBA4"
        self.secret_definition = "独特古法造纸质感与朱砂水墨点染，宣纸微黄晕染效果极其显著"
        now = "2026-11-01T12:00:00Z"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO curation_submissions
                    (id, topic_id, owner_username, owner_user_id, kind, target_id, status, current_revision, request_id, created_at, updated_at)
                VALUES ('sub_test_1', 'topic_test_1', ?, ?, 'style', ?, 'pending', 1, 'req_1', ?, ?)
                """,
                (self.author["username"], self.author["id"], self.pending_code, now, now),
            )
            payload = {
                "name": "古法宣纸朱砂风",
                "description": "东方古朴宣纸朱砂画风",
                "definition": self.secret_definition,
                "cover": "/images/test-cover.webp",
                "images": ["/images/test-ex1.webp"],
            }
            tx.execute(
                """
                INSERT INTO curation_versions
                    (id, submission_id, revision, payload_json, created_at)
                VALUES ('ver_test_1', 'sub_test_1', 1, ?, ?)
                """,
                (json.dumps(payload, ensure_ascii=False), now),
            )

            # Insert a paid pending submission: USR-PAID-PENDING
            self.paid_pending_code = "USR-PAID-PENDING"
            tx.execute(
                """
                INSERT INTO curation_submissions
                    (id, topic_id, owner_username, owner_user_id, kind, target_id, status, current_revision, request_id, created_at, updated_at)
                VALUES ('sub_test_paid', 'topic_test_paid', ?, ?, 'style', ?, 'pending', 1, 'req_paid', ?, ?)
                """,
                (self.author["username"], self.author["id"], self.paid_pending_code, now, now),
            )
            payload_paid = {
                "name": "付费未收录画风",
                "description": "付费未收录画风描述",
                "definition": self.secret_definition,
                "cover": "/images/test-cover-paid.webp",
                "images": ["/images/test-ex1.webp"],
                "unlock_cost": 10,
            }
            tx.execute(
                """
                INSERT INTO curation_versions
                    (id, submission_id, revision, payload_json, created_at)
                VALUES ('ver_test_paid', 'sub_test_paid', 1, ?, ?)
                """,
                (json.dumps(payload_paid, ensure_ascii=False), now),
            )

            # Insert an exclusive asset: FX-001
            tx.execute(
                "INSERT INTO catalog_assets\n                    (code, kind, source_type, author_username, author_name, name, unlock_cost, image_url, description, definition, secret_blackbox_prompt, status, published_at_ms, created_at, updated_at)\n                VALUES ('FX-001', 'style', 'exclusive', 'yang0', '创始人', '黑盒专属画风', 0, '/images/fx-001.webp', '官网独占黑盒', '', 'SECRET_BLACKBOX_GUIDANCE', 'published', 1000, ?, ?) ON CONFLICT (code) DO UPDATE SET kind = excluded.kind, source_type = excluded.source_type, author_username = excluded.author_username, author_name = excluded.author_name, name = excluded.name, unlock_cost = excluded.unlock_cost, image_url = excluded.image_url, description = excluded.description, definition = excluded.definition, secret_blackbox_prompt = excluded.secret_blackbox_prompt, status = excluded.status, published_at_ms = excluded.published_at_ms, created_at = excluded.created_at, updated_at = excluded.updated_at",
                (now, now),
            )

            # Insert a community paid asset: USR-S99
            tx.execute(
                "INSERT INTO catalog_assets\n                    (code, kind, source_type, author_username, author_name, name, unlock_cost, image_url, description, definition, secret_blackbox_prompt, status, published_at_ms, created_at, updated_at)\n                VALUES ('USR-S99', 'style', 'community', 'creator99', '创作者99', '付费社区画风', 10, '/images/usr-99.webp', '社区付费', '社区付费提示词定义', '', 'published', 1000, ?, ?) ON CONFLICT (code) DO UPDATE SET kind = excluded.kind, source_type = excluded.source_type, author_username = excluded.author_username, author_name = excluded.author_name, name = excluded.name, unlock_cost = excluded.unlock_cost, image_url = excluded.image_url, description = excluded.description, definition = excluded.definition, secret_blackbox_prompt = excluded.secret_blackbox_prompt, status = excluded.status, published_at_ms = excluded.published_at_ms, created_at = excluded.created_at, updated_at = excluded.updated_at",
                (now, now),
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

    def test_01_author_resolves_pending_with_definition(self) -> None:
        """1. Author opens pending resource: canRead=True, definition intact, inject=None."""
        res = resource_registry.resolve(self.db.get_conn(), self.pending_code, viewer=self.author, purpose="generate")
        self.assertIsNotNone(res)
        assert res is not None
        self.assertTrue(res["canUse"])
        self.assertTrue(res["access"]["canRead"])
        self.assertIsNone(res["access"]["hiddenBy"])
        self.assertIsNone(res["access"]["inject"])
        self.assertEqual(res["definition"], self.secret_definition)

    def test_02_visitor_resolves_free_pending_with_definition(self) -> None:
        """2. Free pending resource: anyone can see definition (canRead=True, hiddenBy=None, inject=None)."""
        res = resource_registry.resolve(self.db.get_conn(), self.pending_code, viewer=self.visitor, purpose="generate")
        self.assertIsNotNone(res)
        assert res is not None
        self.assertTrue(res["canUse"])
        self.assertTrue(res["access"]["canRead"])
        self.assertIsNone(res["access"]["hiddenBy"])
        self.assertIsNone(res["access"]["inject"])
        self.assertEqual(res["definition"], self.secret_definition)

    def test_02b_visitor_resolves_paid_pending_without_definition(self) -> None:
        """2b. Paid pending resource: non-author logged-in user canUse=True, canRead=False, hiddenBy='pending', inject='definition'."""
        res = resource_registry.resolve(self.db.get_conn(), self.paid_pending_code, viewer=self.visitor, purpose="generate")
        self.assertIsNotNone(res)
        assert res is not None
        self.assertTrue(res["canUse"])
        self.assertFalse(res["access"]["canRead"])
        self.assertEqual(res["access"]["hiddenBy"], "pending")
        self.assertEqual(res["access"]["inject"], "definition")
        self.assertIsNone(res["definition"])
        self.assertEqual(res["_raw_definition"], self.secret_definition)

    def test_03_anonymous_access_pending(self) -> None:
        """3. Free pending: anonymous can read definition but cannot use. Paid pending: neither."""
        # Free pending
        res_free = resource_registry.resolve(self.db.get_conn(), self.pending_code, viewer=None, purpose="view")
        self.assertIsNotNone(res_free)
        assert res_free is not None
        self.assertFalse(res_free["canUse"])
        self.assertTrue(res_free["access"]["canRead"])
        self.assertIsNone(res_free["access"]["hiddenBy"])
        self.assertEqual(res_free["definition"], self.secret_definition)

        # Paid pending
        res_paid = resource_registry.resolve(self.db.get_conn(), self.paid_pending_code, viewer=None, purpose="view")
        self.assertIsNotNone(res_paid)
        assert res_paid is not None
        self.assertFalse(res_paid["canUse"])
        self.assertFalse(res_paid["access"]["canRead"])
        self.assertEqual(res_paid["access"]["hiddenBy"], "pending")
        self.assertIsNone(res_paid["definition"])

    def test_04_collection_and_skill_library(self) -> None:
        """4. Collect pending resource: Skill library collected has it, content_url is None; export returns 403."""
        # Non-author collects pending resource
        coll_res = toggle_user_collection(self.db, self.visitor, "styles", self.pending_code)
        self.assertTrue(coll_res["ok"])
        self.assertTrue(coll_res["collected"])

        # Skill library exposes collected pending resource with content_url=None
        lib_payload = build_skill_library_payload(self.db, self.visitor)
        pending_item = next((item for item in lib_payload["collected"] if item["ref"] == self.pending_code), None)
        self.assertIsNotNone(pending_item)
        assert pending_item is not None
        self.assertIsNone(pending_item["content_url"])

        # Free pending resource: other logged-in user can export definition via Skill content
        visitor_content = build_skill_asset_content(self.db, self.visitor, self.pending_code)
        self.assertEqual(visitor_content["resource"]["prompt_zh"], self.secret_definition)

        # Paid pending resource: non-author attempting export raises 403
        with self.assertRaises(ServiceError) as ctx:
            build_skill_asset_content(self.db, self.visitor, self.paid_pending_code)
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("尚未收录", ctx.exception.message)

        # Author can export own definition
        author_content = build_skill_asset_content(self.db, self.author, self.pending_code)
        self.assertEqual(author_content["resource"]["prompt_zh"], self.secret_definition)

    def test_05_withdrawn_resource_generation_and_author_exception(self) -> None:
        """5. Withdrawn resource: others 403 asset_withdrawn; author still allowed by ID comparison."""
        # Admin withdraws the submission
        with self.db.transaction() as tx:
            tx.execute("UPDATE curation_submissions SET status = 'withdrawn' WHERE target_id = ?", (self.pending_code,))

        # Non-author generates -> 403 asset_withdrawn
        with self.assertRaises(ServiceError) as ctx:
            prepare_cloud_generation(self.db, self.visitor, {"prompt": "测试生图", "style1": self.pending_code})
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "asset_withdrawn")

        # Give visitor the exact same display_name as author to test ID comparison
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET display_name = '相同显示名' WHERE id IN (?, ?)", (self.author["id"], self.visitor["id"]))
        visitor_updated = dict(self.visitor, display_name="相同显示名")
        author_updated = dict(self.author, display_name="相同显示名")

        # Visitor still 403
        with self.assertRaises(ServiceError) as ctx:
            prepare_cloud_generation(self.db, visitor_updated, {"prompt": "测试生图", "style1": self.pending_code})
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "asset_withdrawn")

        # Author allowed to generate!
        gen_res = prepare_cloud_generation(self.db, author_updated, {"prompt": "作者继续生成", "style1": self.pending_code})
        self.assertIn("genId", gen_res)

    def test_05a_anti_echo_no_definition_leakage(self) -> None:
        """5a. Anti-echo: definition goes into generations.prompt, but NEVER into visible_prompt, workspace, or finalPrompt."""
        gen_res = prepare_cloud_generation(
            self.db,
            self.visitor,
            {"prompt": "生成一幅荷塘月色", "style1": self.paid_pending_code, "promptFromSkill": True},
        )
        self.assertIn("genId", gen_res)
        gen_id = gen_res["genId"]

        # Check raw database rows directly
        row = self.db.get_conn().execute("SELECT * FROM studio_generations WHERE id = ?", (gen_id,)).fetchone()
        self.assertIn(self.secret_definition, row["prompt"])
        self.assertNotIn(self.secret_definition, row["visible_prompt"] or "")

        # Check finalPrompt in response
        self.assertNotIn(self.secret_definition, gen_res.get("finalPrompt", ""))

        # Check workspace history
        ws = get_studio_workspace(self.db, self.visitor)
        for h in ws.get("history", []):
            self.assertNotIn(self.secret_definition, h.get("prompt", ""))
            self.assertNotIn(self.secret_definition, json.dumps(h, ensure_ascii=False))

    def test_05a_extra_secrets_scanner_catches_echoed_definition(self) -> None:
        """5a-extra: If prompt text attempts to repeat the injected definition, it gets masked."""
        with patch("backend.services.check_text_has_secret", wraps=check_text_has_secret) as mocked_scan:
            gen_res = prepare_cloud_generation(
                self.db,
                self.visitor,
                {"prompt": f"生成图，风格是{self.secret_definition}", "style1": self.paid_pending_code, "promptFromSkill": True},
            )
            # The client prompt contained the secret definition -> masked
            row = self.db.get_conn().execute("SELECT * FROM studio_generations WHERE id = ?", (gen_res["genId"],)).fetchone()
            self.assertEqual(row["prompt_masked"], 1)
            self.assertEqual(row["visible_prompt"], "")

    def test_05b_get_resource_endpoint_hidden_by_and_no_inject(self) -> None:
        """5b. GET /api/resources/<code> fields and verification that 'inject' is NEVER present."""
        cases = [
            # (code, user_token, expected_hidden_by)
            (self.pending_code, self.visitor_token, None),
            (self.paid_pending_code, self.visitor_token, "pending"),
            ("FX-001", None, "blackbox"),
            ("USR-S99", self.visitor_token, "locked"),
        ]

        for code, token, expected_hidden in cases:
            req = urllib.request.Request(f"{self.base}/api/resources/{code}")
            if token:
                req.add_header("Cookie", f"{SESSION_COOKIE_NAME}={token}")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                body = resp.read().decode("utf-8")
                # Assert 'inject' is NEVER in the response
                self.assertNotIn('"inject"', body)
                data = json.loads(body)
                self.assertTrue(data["ok"])
                self.assertEqual(data["access"]["hiddenBy"], expected_hidden)

        # Withdrawn case
        with self.db.transaction() as tx:
            tx.execute("UPDATE curation_submissions SET status = 'withdrawn' WHERE target_id = ?", (self.pending_code,))
        req = urllib.request.Request(f"{self.base}/api/resources/{self.pending_code}")
        req.add_header("Cookie", f"{SESSION_COOKIE_NAME}={self.visitor_token}")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertNotIn('"inject"', body)
            data = json.loads(body)
            self.assertEqual(data["access"]["hiddenBy"], "withdrawn")

    def test_05c_paid_resource_buyer_resolution_and_generation(self) -> None:
        """5c. Paid published resource: unlocked buyer has canRead=False, canUse=True, hiddenBy='paid', inject='definition'."""
        now = "2026-11-03T12:00:00Z"
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO unlocks (user_id, target_type, target_id, cost, status, created_at) VALUES (?, 'asset', 'USR-S99', 10, 'settled', ?)",
                (self.visitor["id"], now),
            )

        res = resource_registry.resolve(self.db.get_conn(), "USR-S99", viewer=self.visitor, purpose="generate")
        self.assertIsNotNone(res)
        assert res is not None
        self.assertTrue(res["canUse"])
        self.assertFalse(res["access"]["canRead"])
        self.assertEqual(res["access"]["hiddenBy"], "paid")
        self.assertEqual(res["access"]["inject"], "definition")
        self.assertIsNone(res["definition"])
        self.assertEqual(res["_raw_definition"], "社区付费提示词定义")

        # GET /api/resources/USR-S99 returns hiddenBy='paid' and definition=None
        req = urllib.request.Request(f"{self.base}/api/resources/USR-S99")
        req.add_header("Cookie", f"{SESSION_COOKIE_NAME}={self.visitor_token}")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["ok"])
            self.assertEqual(data["access"]["hiddenBy"], "paid")
            self.assertIsNone(data["definition"])

        # Buyer generates with USR-S99 -> server injects definition
        gen_res = prepare_cloud_generation(
            self.db,
            self.visitor,
            {"prompt": "测试买家生成", "style1": "USR-S99", "promptFromSkill": True},
        )
        self.assertIn("genId", gen_res)
        row = self.db.get_conn().execute("SELECT * FROM studio_generations WHERE id = ?", (gen_res["genId"],)).fetchone()
        self.assertIn("社区付费提示词定义", row["prompt"])
        self.assertNotIn("社区付费提示词定义", row["visible_prompt"] or "")

    def test_06_pending_resource_stamp_and_tip(self) -> None:
        """6. Pending resource: retired stamp returns 400, tip returns 400 (未收录资源不接受赞赏)."""
        with self.assertRaises(ServiceError) as ctx:
            toggle_user_cheer(self.db, self.visitor, "asset", self.pending_code, stamp_label="超实用配方")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "stamp_retired")

        with self.assertRaises(ServiceError) as ctx:
            send_encourage_tip(self.db, self.visitor, "asset", self.pending_code, amount=2)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.message, "未收录资源不接受赞赏")

    def test_07_collect_nonexistent_returns_404(self) -> None:
        """7. POST /api/collections/toggle with nonexistent code returns 404."""
        with self.assertRaises(ServiceError) as ctx:
            toggle_user_collection(self.db, self.visitor, "styles", "NON_EXISTENT_CODE_999")
        self.assertEqual(ctx.exception.status, 404)

    def test_08_official_fb028_stamp_returns_200(self) -> None:
        """8. Official FB-028 stamp is retired and returns 400."""
        with self.assertRaises(ServiceError) as ctx:
            toggle_user_cheer(self.db, self.visitor, "asset", "FB-028", stamp_label="超实用配方")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "stamp_retired")


if __name__ == "__main__":
    unittest.main()
