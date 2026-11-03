"""Tests for Issue #21 (Part 1): Unified Style/Layout Definition Visibility Rules.

Matrix rows covered:
1. Free published (official / community): anyone canRead=True, canUse=True, hiddenBy=None, inject=None
2. Free pending (pending / changes_requested): anyone (incl. anonymous) canRead=True, logged-in canUse=True, unlogged canUse=False, hiddenBy=None, inject=None
3. Paid (published & pending): author / staff canRead=True, canUse=True, hiddenBy=None, inject=None
4. Paid published: settled buyer canRead=False, canUse=True, hiddenBy="paid", inject="definition"
5. Paid published: unpaid user canRead=False, canUse=False, hiddenBy="locked", inject=None
6. Paid pending: other logged-in user canRead=False, canUse=True, hiddenBy="pending", inject="definition"
7. Paid pending: anonymous user canRead=False, canUse=False, hiddenBy="pending", inject=None
8. Exclusive / withdrawn / private: behavior preserved

Dispatch endpoints checked:
- resource_registry.resolve
- boot payload (pending_resources, catalog assets)
- GET /api/resources/<code>
- GET /api/forum/resources/<kind>/<target>
- POST /api/unlocks (unlockedContent is "")
- Skill content endpoint build_skill_asset_content
- Generation prompt injection
"""
import json
import os
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import TestCase
from unittest.mock import patch

from backend.db import Database
from backend.server import SESSION_COOKIE_NAME, HandrawRequestHandler, init_database
from backend import resource_registry
from backend import services as S
from backend.services import ServiceError


class TestDefinitionVisibility(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "test_def_vis.db"
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DATA_DIR": str(root),
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

        # Users: author, buyer, visitor, staff
        self.author, self.author_token = S.register_user(self.db, "author_user", "pass123", display_name="Author One")
        self.buyer, self.buyer_token = S.register_user(self.db, "buyer_user", "pass123", display_name="Buyer One")
        self.visitor, self.visitor_token = S.register_user(self.db, "visitor_user", "pass123", display_name="Visitor One")
        self.staff, self.staff_token = S.register_user(self.db, "staff_user", "pass123", display_name="Staff One")
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'reviewer' WHERE id = ?", (self.staff["id"],))
            # Give buyer credits
            tx.execute("UPDATE wallets SET balance = 500 WHERE user_id = ?", (self.buyer["id"],))
        self.staff["role"] = "reviewer"

        self.free_pending_def = "这是免费未收录画风的公开定义提示词"
        self.paid_pending_def = "这是付费未收录画风的机密定义提示词"
        self.paid_published_def = "这是付费已收录画风的机密定义提示词"
        self.free_published_def = "这是免费已收录画风的公开定义提示词"

        now = "2026-11-03T12:00:00Z"
        with self.db.transaction() as tx:
            # 1. Free pending submission
            self.free_pending_code = "USR-S-FREE-PEND"
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, summary, status, published_at_ms, created_at, updated_at)
                VALUES ('t_free_pend', 'style', '画风', '免费待审画风帖', ?, ?, 0, '摘要', 'published', 1000, ?, ?)
                """,
                (self.author["username"], self.author["display_name"], now, now),
            )
            tx.execute(
                """
                INSERT INTO curation_submissions
                    (id, topic_id, owner_username, owner_user_id, kind, target_id, status, current_revision, request_id, created_at, updated_at)
                VALUES ('sub_free_pend', 't_free_pend', ?, ?, 'style', ?, 'pending', 1, 'req_free', ?, ?)
                """,
                (self.author["username"], self.author["id"], self.free_pending_code, now, now),
            )
            tx.execute(
                """
                INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
                VALUES ('style', ?, 't_free_pend', 'submission', ?)
                """,
                (self.free_pending_code, now),
            )
            tx.execute(
                """
                INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at)
                VALUES ('ver_free_pend', 'sub_free_pend', 1, ?, ?)
                """,
                (
                    json.dumps({
                        "name": "免费未收录画风",
                        "description": "免费待审描述",
                        "definition": self.free_pending_def,
                        "unlock_cost": 0,
                        "cover": "/img/free-pend.webp",
                    }, ensure_ascii=False),
                    now,
                ),
            )

            # 2. Paid pending submission
            self.paid_pending_code = "USR-S-PAID-PEND"
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, summary, status, published_at_ms, created_at, updated_at)
                VALUES ('t_paid_pend', 'style', '画风', '付费待审画风帖', ?, ?, 0, '摘要', 'published', 1000, ?, ?)
                """,
                (self.author["username"], self.author["display_name"], now, now),
            )
            tx.execute(
                """
                INSERT INTO curation_submissions
                    (id, topic_id, owner_username, owner_user_id, kind, target_id, status, current_revision, request_id, created_at, updated_at)
                VALUES ('sub_paid_pend', 't_paid_pend', ?, ?, 'style', ?, 'pending', 1, 'req_paid', ?, ?)
                """,
                (self.author["username"], self.author["id"], self.paid_pending_code, now, now),
            )
            tx.execute(
                """
                INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
                VALUES ('style', ?, 't_paid_pend', 'submission', ?)
                """,
                (self.paid_pending_code, now),
            )
            tx.execute(
                """
                INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at)
                VALUES ('ver_paid_pend', 'sub_paid_pend', 1, ?, ?)
                """,
                (
                    json.dumps({
                        "name": "付费未收录画风",
                        "description": "付费待审描述",
                        "definition": self.paid_pending_def,
                        "unlock_cost": 15,
                        "cover": "/img/paid-pend.webp",
                    }, ensure_ascii=False),
                    now,
                ),
            )

            # 3. Paid published community asset
            self.paid_pub_code = "USR-S-PAID-PUB"
            tx.execute(
                """
                INSERT INTO catalog_assets
                    (code, kind, source_type, author_username, author_name, name, unlock_cost, image_url, description, definition, status, published_at_ms, created_at, updated_at)
                VALUES (?, 'style', 'community', ?, ?, '付费已收录画风', 20, '/img/paid-pub.webp', '付费已收录描述', ?, 'published', 1000, ?, ?)
                """,
                (self.paid_pub_code, self.author["username"], self.author["display_name"], self.paid_published_def, now, now),
            )
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, summary, status, published_at_ms, created_at, updated_at)
                VALUES ('t_paid_pub', 'style', '画风', '付费已收录帖', ?, ?, 0, '摘要', 'published', 1000, ?, ?)
                """,
                (self.author["username"], self.author["display_name"], now, now),
            )
            tx.execute(
                """
                INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
                VALUES ('style', ?, 't_paid_pub', 'catalog', ?)
                """,
                (self.paid_pub_code, now),
            )

            # 4. Free published community asset
            self.free_pub_code = "USR-S-FREE-PUB"
            tx.execute(
                """
                INSERT INTO catalog_assets
                    (code, kind, source_type, author_username, author_name, name, unlock_cost, image_url, description, definition, status, published_at_ms, created_at, updated_at)
                VALUES (?, 'style', 'community', ?, ?, '免费已收录画风', 0, '/img/free-pub.webp', '免费已收录描述', ?, 'published', 1000, ?, ?)
                """,
                (self.free_pub_code, self.author["username"], self.author["display_name"], self.free_published_def, now, now),
            )
            tx.execute(
                """
                INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
                VALUES ('style', ?, 't_free_pub', 'catalog', ?)
                """,
                (self.free_pub_code, now),
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

    # ========================== MATRIX ROW TESTS ==========================

    def test_row1_free_published_anyone_reads_and_uses(self) -> None:
        """Row 1: Free published: Anyone (visitor, anonymous) canRead=True, canUse=True."""
        conn = self.db.get_conn()
        # Logged-in visitor
        res_v = resource_registry.resolve(conn, self.free_pub_code, viewer=self.visitor)
        self.assertTrue(res_v["access"]["canRead"])
        self.assertTrue(res_v["access"]["canUse"])
        self.assertIsNone(res_v["access"]["hiddenBy"])
        self.assertEqual(res_v["definition"], self.free_published_def)

        # Anonymous
        res_a = resource_registry.resolve(conn, self.free_pub_code, viewer=None)
        self.assertTrue(res_a["access"]["canRead"])
        self.assertTrue(res_a["access"]["canUse"])
        self.assertIsNone(res_a["access"]["hiddenBy"])
        self.assertEqual(res_a["definition"], self.free_published_def)

    def test_row2_free_pending_anyone_reads_definition(self) -> None:
        """Row 2: Free pending: Anyone (incl. anonymous) canRead=True, definition intact. Logged-in canUse=True, anon canUse=False."""
        conn = self.db.get_conn()
        # Logged in visitor
        res_v = resource_registry.resolve(conn, self.free_pending_code, viewer=self.visitor)
        self.assertTrue(res_v["access"]["canRead"])
        self.assertTrue(res_v["access"]["canUse"])
        self.assertIsNone(res_v["access"]["hiddenBy"])
        self.assertEqual(res_v["definition"], self.free_pending_def)

        # Anonymous visitor
        res_a = resource_registry.resolve(conn, self.free_pending_code, viewer=None)
        self.assertTrue(res_a["access"]["canRead"])
        self.assertFalse(res_a["access"]["canUse"])
        self.assertIsNone(res_a["access"]["hiddenBy"])
        self.assertEqual(res_a["definition"], self.free_pending_def)

    def test_row3_paid_author_and_staff_see_definition(self) -> None:
        """Row 3: Paid (pending or published): Author and staff canRead=True, canUse=True, hiddenBy=None."""
        conn = self.db.get_conn()
        for code, expected_def in [(self.paid_pending_code, self.paid_pending_def), (self.paid_pub_code, self.paid_published_def)]:
            # Author
            res_author = resource_registry.resolve(conn, code, viewer=self.author)
            self.assertTrue(res_author["access"]["canRead"])
            self.assertTrue(res_author["access"]["canUse"])
            self.assertIsNone(res_author["access"]["hiddenBy"])
            self.assertEqual(res_author["definition"], expected_def)

            # Staff
            res_staff = resource_registry.resolve(conn, code, viewer=self.staff)
            self.assertTrue(res_staff["access"]["canRead"])
            self.assertTrue(res_staff["access"]["canUse"])
            self.assertIsNone(res_staff["access"]["hiddenBy"])
            self.assertEqual(res_staff["definition"], expected_def)

    def test_row4_paid_published_buyer_cannot_read_definition(self) -> None:
        """Row 4: Paid published: Settled buyer has canRead=False, canUse=True, hiddenBy='paid', inject='definition'."""
        conn = self.db.get_conn()
        # Buyer unlocks
        S.unlock_paid_item(self.db, self.buyer, "asset", self.paid_pub_code)

        res_buyer = resource_registry.resolve(conn, self.paid_pub_code, viewer=self.buyer)
        self.assertFalse(res_buyer["access"]["canRead"])
        self.assertTrue(res_buyer["access"]["canUse"])
        self.assertEqual(res_buyer["access"]["hiddenBy"], "paid")
        self.assertEqual(res_buyer["access"]["inject"], "definition")
        self.assertIsNone(res_buyer["definition"])
        self.assertEqual(res_buyer["_raw_definition"], self.paid_published_def)

    def test_row5_paid_published_unpaid_locked(self) -> None:
        """Row 5: Paid published: Unpaid user has canRead=False, canUse=False, hiddenBy='locked', inject=None."""
        conn = self.db.get_conn()
        res_unpaid = resource_registry.resolve(conn, self.paid_pub_code, viewer=self.visitor)
        self.assertFalse(res_unpaid["access"]["canRead"])
        self.assertFalse(res_unpaid["access"]["canUse"])
        self.assertEqual(res_unpaid["access"]["hiddenBy"], "locked")
        self.assertIsNone(res_unpaid["access"]["inject"])
        self.assertIsNone(res_unpaid["definition"])

        # Anonymous
        res_anon = resource_registry.resolve(conn, self.paid_pub_code, viewer=None)
        self.assertFalse(res_anon["access"]["canRead"])
        self.assertFalse(res_anon["access"]["canUse"])
        self.assertEqual(res_anon["access"]["hiddenBy"], "locked")
        self.assertIsNone(res_anon["definition"])

    def test_row6_paid_pending_other_logged_in_user(self) -> None:
        """Row 6: Paid pending: Logged in non-author has canRead=False, canUse=True, hiddenBy='pending', inject='definition'."""
        conn = self.db.get_conn()
        res = resource_registry.resolve(conn, self.paid_pending_code, viewer=self.visitor)
        self.assertFalse(res["access"]["canRead"])
        self.assertTrue(res["access"]["canUse"])
        self.assertEqual(res["access"]["hiddenBy"], "pending")
        self.assertEqual(res["access"]["inject"], "definition")
        self.assertIsNone(res["definition"])
        self.assertEqual(res["_raw_definition"], self.paid_pending_def)

    def test_row7_paid_pending_anonymous(self) -> None:
        """Row 7: Paid pending: Anonymous has canRead=False, canUse=False, hiddenBy='pending', inject=None."""
        conn = self.db.get_conn()
        res = resource_registry.resolve(conn, self.paid_pending_code, viewer=None)
        self.assertFalse(res["access"]["canRead"])
        self.assertFalse(res["access"]["canUse"])
        self.assertEqual(res["access"]["hiddenBy"], "pending")
        self.assertIsNone(res["access"]["inject"])
        self.assertIsNone(res["definition"])

    # ========================== ENDPOINT VERIFICATIONS ==========================

    def test_free_pending_endpoints_expose_definition_to_anyone(self) -> None:
        """Free pending: boot payload, GET /api/resources/<code>, forum resource detail all expose definition."""
        # 1. Boot payload with favorite
        S.toggle_user_collection(self.db, self.visitor, "styles", self.free_pending_code)
        boot = S.build_boot_payload(self.db, self.visitor)
        p_res = next((r for r in boot["pendingResources"] if r["code"] == self.free_pending_code), None)
        self.assertIsNotNone(p_res)
        self.assertEqual(p_res["definition"], self.free_pending_def)
        self.assertTrue(p_res["access"]["canRead"])
        self.assertIsNone(p_res["access"]["hiddenBy"])

        # 2. GET /api/resources/<code> (Anonymous)
        req = urllib.request.Request(f"{self.base}/api/resources/{self.free_pending_code}")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["ok"])
            self.assertEqual(data["resource"]["definition"], self.free_pending_def)
            self.assertTrue(data["resource"]["access"]["canRead"])
            self.assertIsNone(data["resource"]["access"]["hiddenBy"])

        # 3. GET /api/forum/resources/style/<code> (Anonymous)
        req_f = urllib.request.Request(f"{self.base}/api/forum/resources/style/{self.free_pending_code}")
        with urllib.request.urlopen(req_f) as resp:
            data_f = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data_f["ok"])
            self.assertEqual(data_f["resource"]["definition"], self.free_pending_def)

        # 4. Post detail mount (GET /api/posts/t_free_pend)
        req_p = urllib.request.Request(f"{self.base}/api/posts/t_free_pend")
        with urllib.request.urlopen(req_p) as resp:
            data_p = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data_p["ok"])
            self.assertEqual(data_p["mount"]["resource"]["definition"], self.free_pending_def)

    def test_paid_buyer_endpoints_never_leak_definition(self) -> None:
        """Paid asset: buyer gets empty unlockedContent on unlock, no definition in boot/resource/forum/skill."""
        # 1. Unlock endpoint returns unlockedContent = ""
        unlock_res = S.unlock_paid_item(self.db, self.buyer, "asset", self.paid_pub_code)
        self.assertTrue(unlock_res["ok"])
        self.assertEqual(unlock_res["unlockedContent"], "")

        # 2. Boot payload: definition is blackbox placeholder, NOT the raw secret definition
        boot = S.build_boot_payload(self.db, self.buyer)
        buyer_asset = next((r for r in boot["communityResources"] if r["id"] == self.paid_pub_code), None)
        self.assertIsNotNone(buyer_asset)
        self.assertNotIn(self.paid_published_def, buyer_asset["definition"])
        self.assertIn("CLOUD_BLACKBOX", buyer_asset["definition"])

        # 3. GET /api/resources/<code>
        req = urllib.request.Request(f"{self.base}/api/resources/{self.paid_pub_code}")
        req.add_header("Cookie", f"{SESSION_COOKIE_NAME}={self.buyer_token}")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["ok"])
            self.assertIsNone(data["resource"]["definition"])
            self.assertEqual(data["resource"]["access"]["hiddenBy"], "paid")
            self.assertFalse(data["resource"]["access"]["canRead"])
            self.assertTrue(data["resource"]["access"]["canUse"])

        # 4. Forum resource detail GET /api/forum/resources/style/<code>
        req_f = urllib.request.Request(f"{self.base}/api/forum/resources/style/{self.paid_pub_code}")
        req_f.add_header("Cookie", f"{SESSION_COOKIE_NAME}={self.buyer_token}")
        with urllib.request.urlopen(req_f) as resp:
            data_f = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data_f["ok"])
            self.assertEqual(data_f["resource"]["definition"], "")
            self.assertTrue(data_f["resource"]["unlocked"])
            self.assertTrue(data_f["resource"]["canUse"])

        # 5. Skill asset content export raises 403
        with self.assertRaises(ServiceError) as ctx:
            S.build_skill_asset_content(self.db, self.buyer, self.paid_pub_code)
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("付费资产仅支持在线创作台调用", ctx.exception.message)

        # 6. Skill library content_url is None for buyer
        S.toggle_user_collection(self.db, self.buyer, "styles", self.paid_pub_code)
        lib_payload = S.build_skill_library_payload(self.db, self.buyer)
        collected_item = next((it for it in lib_payload["collected"] if it["ref"] == self.paid_pub_code), None)
        self.assertIsNotNone(collected_item)
        self.assertIsNone(collected_item["content_url"])

    def test_buyer_generates_with_paid_asset_injects_definition_into_gateway_prompt(self) -> None:
        """Buyer generating with paid resource: definition injected by server into gateway prompt."""
        # Unlock asset for buyer
        S.unlock_paid_item(self.db, self.buyer, "asset", self.paid_pub_code)

        gen_res = S.prepare_cloud_generation(
            self.db,
            self.buyer,
            {"prompt": "画一只小猫", "style1": self.paid_pub_code, "promptFromSkill": True},
        )

        self.assertIn("genId", gen_res)

        # Check DB row: prompt has injected secret definition, visible_prompt does NOT
        row = self.db.get_conn().execute("SELECT * FROM studio_generations WHERE id = ?", (gen_res["genId"],)).fetchone()
        self.assertIn(self.paid_published_def, row["prompt"])
        self.assertNotIn(self.paid_published_def, row["visible_prompt"] or "")

    def test_author_and_staff_can_read_and_export_paid_definition(self) -> None:
        """Author and staff: can see definition in boot, API, forum detail, and export via Skill content."""
        # 1. Author boot payload
        boot_author = S.build_boot_payload(self.db, self.author)
        author_asset = next((r for r in boot_author["communityResources"] if r["id"] == self.paid_pub_code), None)
        self.assertIsNotNone(author_asset)
        self.assertEqual(author_asset["definition"], self.paid_published_def)

        # 2. Staff GET /api/resources/<code>
        req_staff = urllib.request.Request(f"{self.base}/api/resources/{self.paid_pub_code}")
        req_staff.add_header("Cookie", f"{SESSION_COOKIE_NAME}={self.staff_token}")
        with urllib.request.urlopen(req_staff) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["ok"])
            self.assertEqual(data["resource"]["definition"], self.paid_published_def)
            self.assertTrue(data["resource"]["access"]["canRead"])

        # 3. Author Skill content export succeeds
        author_content = S.build_skill_asset_content(self.db, self.author, self.paid_pub_code)
        self.assertEqual(author_content["resource"]["prompt_zh"], self.paid_published_def)

        # 4. Staff Skill content export succeeds
        staff_content = S.build_skill_asset_content(self.db, self.staff, self.paid_pub_code)
        self.assertEqual(staff_content["resource"]["prompt_zh"], self.paid_published_def)
