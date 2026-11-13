"""Tests for GitHub Issues #10 and #11: Official Assets Management.

Covers:
1. Admin creates official asset with empty code -> assigns next sequential code in series (e.g. FE-069, FE-070).
2. Code conflict & validation: FE-001 -> 409 code_taken; FE-080 -> 200; XX-001 -> 400.
3. Name conflict: duplicate name -> 409 name_taken with existingCode.
4. RBAC: reviewer -> 403; anon -> 401; legacy POST /api/admin/catalog on official asset -> 409.
5. Image validation: evil URL, foreign media, invalid ext -> 400. Non-square valid image -> 200 with warnings.
6. Unlock cost: 20 -> tier='credit'; -1 or 501 -> 400.
7. Boot payload: officialResources contains asset, officialOverrides does not. status='hidden' excludes it.
8. Channel & Studio resolution: prepare_cloud_generation resolves FE-069 with prompt and definition.
9. /t/{code} 302 redirect: 0 replies -> not in forum list; 1 reply -> in forum list.
10. Skill library: official asset in 'official' bucket with official license; delete protection when referenced.
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PIL import Image

from tests.postgres_support import open_isolated_postgres
from backend import resource_registry
from backend import services as S
from backend.server import SESSION_COOKIE_NAME, HandrawRequestHandler

from tests.economy_support import prepare_cloud_generation


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_test_image_bytes(width: int = 400, height: int = 400, fmt: str = "WEBP") -> bytes:
    img = Image.new("RGB", (width, height), color=(130, 160, 210))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def make_test_data_url(width: int = 400, height: int = 400, fmt: str = "PNG") -> str:
    raw = make_test_image_bytes(width, height, fmt)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/{fmt.lower()};base64,{b64}"


class TestOfficialAssets(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.uploads_dir = self.root / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir = self.root / "generated"
        self.generated_dir.mkdir(parents=True, exist_ok=True)

        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_UPLOADS_DIR": str(self.uploads_dir),
                "HANDRAW_GENERATED_DIR": str(self.generated_dir),
                "HANDRAW_DATA_DIR": str(self.root),
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

        # Users: admin, reviewer, regular visitor
        self.admin_user, self.admin_token = S.register_user(self.db, "admin_user", "AdminPass123", display_name="Admin One")
        self.reviewer_user, self.reviewer_token = S.register_user(self.db, "rev_user", "RevPass123", display_name="Rev One")
        self.visitor_user, self.visitor_token = S.register_user(self.db, "visitor_user", "VisPass123", display_name="Visitor One")

        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin_user["id"],))
            tx.execute("UPDATE users SET role = 'reviewer' WHERE id = ?", (self.reviewer_user["id"],))
        self.admin_user["role"] = "admin"
        self.reviewer_user["role"] = "reviewer"

        self.cookie_admin = f"{SESSION_COOKIE_NAME}={self.admin_token}"
        self.cookie_rev = f"{SESSION_COOKIE_NAME}={self.reviewer_token}"
        self.cookie_visitor = f"{SESSION_COOKIE_NAME}={self.visitor_token}"

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

    def test_01_admin_create_official_asset_auto_code(self) -> None:
        """1. Admin creates official asset with empty code -> gets FE-069, then FE-070.
        SQL check verifies source_type='official' and author_username=''."""
        payload1 = {
            "series": "FE",
            "code": "",
            "name": "新宋锦实验画风",
            "description": "测试官方画风描述",
            "definition": "测试官方画风定义完整内容",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
            "unlockCost": 0,
        }
        status1, res1 = self._req("POST", "/api/admin/catalog/official", payload1, cookie=self.cookie_admin)
        self.assertEqual(status1, 200, res1)
        self.assertTrue(res1.get("ok"))
        self.assertEqual(res1.get("code"), "FE-069")

        # Second creation auto-allocates next code FE-070
        payload2 = {
            "series": "FE",
            "code": "",
            "name": "新宋锦进阶画风",
            "description": "第二项描述",
            "definition": "第二项定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-070.webp",
            "unlockCost": 0,
        }
        status2, res2 = self._req("POST", "/api/admin/catalog/official", payload2, cookie=self.cookie_admin)
        self.assertEqual(status2, 200, res2)
        self.assertEqual(res2.get("code"), "FE-070")

        # Verify SQL row
        conn = self.db.get_conn()
        row = conn.execute(
            "SELECT source_type, author_username FROM catalog_assets WHERE code = 'FE-069'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["source_type"], "official")
        self.assertEqual(row["author_username"], "")

    def test_02_code_validations_and_conflicts(self) -> None:
        """2. Code conflict: FE-001 -> 409 code_taken; FE-080 -> 200; XX-001 -> 400."""
        # 2a: Existing code in catalog.json
        payload_dup = {
            "series": "FE",
            "code": "FE-001",
            "name": "企图冲突的画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-001.webp",
            "unlockCost": 0,
        }
        st_dup, res_dup = self._req("POST", "/api/admin/catalog/official", payload_dup, cookie=self.cookie_admin)
        self.assertEqual(st_dup, 409)
        self.assertEqual(res_dup.get("code"), "code_taken")

        # 2b: Explicit non-conflicting code
        payload_ok = {
            "series": "FE",
            "code": "FE-080",
            "name": "显式指定编号画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-080.webp",
            "unlockCost": 0,
        }
        st_ok, res_ok = self._req("POST", "/api/admin/catalog/official", payload_ok, cookie=self.cookie_admin)
        self.assertEqual(st_ok, 200, res_ok)
        self.assertEqual(res_ok.get("code"), "FE-080")

        # 2c: Invalid series prefix in code
        payload_bad = {
            "series": "FE",
            "code": "XX-001",
            "name": "错误前缀画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-080.webp",
            "unlockCost": 0,
        }
        st_bad, _ = self._req("POST", "/api/admin/catalog/official", payload_bad, cookie=self.cookie_admin)
        self.assertEqual(st_bad, 400)

        # 2d: Unknown series
        payload_bad_series = {
            "series": "ZZ",
            "code": "",
            "name": "不存在的系列",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-080.webp",
            "unlockCost": 0,
        }
        st_bs, _ = self._req("POST", "/api/admin/catalog/official", payload_bad_series, cookie=self.cookie_admin)
        self.assertEqual(st_bs, 400)

    def test_03_name_taken(self) -> None:
        """3. Name conflict with FE-001 -> 409 name_taken, response includes existingCode."""
        conn = self.db.get_conn()
        res = resource_registry.resolve(conn, "FE-001", viewer=None)
        existing_name = res["name"] if res else "Playful Deadpan Doodle"

        payload = {
            "series": "FE",
            "code": "",
            "name": existing_name,
            "description": "重复同名描述",
            "definition": "重复同名定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
            "unlockCost": 0,
        }
        st, res_data = self._req("POST", "/api/admin/catalog/official", payload, cookie=self.cookie_admin)
        self.assertEqual(st, 409)
        self.assertEqual(res_data.get("code"), "name_taken")
        self.assertEqual(res_data.get("existingCode"), "FE-001")

    def test_04_rbac_and_legacy_guard(self) -> None:
        """4. Reviewer -> 403; anon -> 401; old POST /api/admin/catalog on official asset -> 409."""
        payload = {
            "series": "FE",
            "code": "",
            "name": "RBAC测试画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
            "unlockCost": 0,
        }
        # Reviewer calling official creation -> 403
        st_rev, _ = self._req("POST", "/api/admin/catalog/official", payload, cookie=self.cookie_rev)
        self.assertEqual(st_rev, 403)

        # Anonymous calling official creation -> 401
        st_anon, _ = self._req("POST", "/api/admin/catalog/official", payload)
        self.assertEqual(st_anon, 401)

        # Create official asset first
        st_create, res_create = self._req("POST", "/api/admin/catalog/official", payload, cookie=self.cookie_admin)
        self.assertEqual(st_create, 200)
        off_code = res_create["code"]

        # Call legacy POST /api/admin/catalog on this official code -> 409
        legacy_payload = {
            "code": off_code,
            "name": "企图通过旧接口覆盖",
            "description": "旧接口描述",
            "definition": "旧接口定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
        }
        st_legacy, res_legacy = self._req("POST", "/api/admin/catalog", legacy_payload, cookie=self.cookie_admin)
        self.assertEqual(st_legacy, 409)
        self.assertEqual(res_legacy.get("code"), "cannot_override_official")

    def test_05_image_validation(self) -> None:
        """5. image validation: evil URL, foreign media, invalid ext -> 400. 1200x900 valid -> 200 with warnings."""
        # 5a: Evil URL
        p_evil = {
            "series": "FE",
            "code": "",
            "name": "邪恶外链画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://evil.example/x.webp",
            "unlockCost": 0,
        }
        st_evil, _ = self._req("POST", "/api/admin/catalog/official", p_evil, cookie=self.cookie_admin)
        self.assertEqual(st_evil, 400)

        # 5b: Foreign upload (uploaded by visitor, tried by admin)
        data_url_vis = make_test_data_url(400, 400, "PNG")
        st_up_v, res_up_v = self._req("POST", "/api/uploads", {"dataUrl": data_url_vis, "nameZh": "访客上传"}, cookie=self.cookie_visitor)
        self.assertEqual(st_up_v, 200)
        foreign_url = res_up_v["url"]

        p_foreign = {
            "series": "FE",
            "code": "",
            "name": "盗用他人图片画风",
            "description": "描述",
            "definition": "定义",
            "image": foreign_url,
            "unlockCost": 0,
        }
        st_for, _ = self._req("POST", "/api/admin/catalog/official", p_foreign, cookie=self.cookie_admin)
        self.assertEqual(st_for, 400)

        # 5c: Invalid extension (.gif)
        p_gif = {
            "series": "FE",
            "code": "",
            "name": "动图画风",
            "description": "描述",
            "definition": "定义",
            "image": "/uploads/test.gif",
            "unlockCost": 0,
        }
        st_gif, _ = self._req("POST", "/api/admin/catalog/official", p_gif, cookie=self.cookie_admin)
        self.assertEqual(st_gif, 400)

        # 5d: Corrupted image file
        corrupt_name = "corrupt_test.webp"
        corrupt_path = self.uploads_dir / corrupt_name
        corrupt_path.write_bytes(b"NOT_A_VALID_IMAGE_BYTES")
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO user_uploads (id, user_id, image_url, file_path, name_zh, cat, sha256, created_at, updated_at) VALUES ('corrupt-upload', ?, ?, ?, '损坏图', 'other', 'dummy_sha', '2026-11-03', '2026-11-03')",
                (self.admin_user["id"], f"/uploads/{corrupt_name}", str(corrupt_path)),
            )
        p_corrupt = {
            "series": "FE",
            "code": "",
            "name": "损坏图片画风",
            "description": "描述",
            "definition": "定义",
            "image": f"/uploads/{corrupt_name}",
            "unlockCost": 0,
        }
        st_cor, _ = self._req("POST", "/api/admin/catalog/official", p_corrupt, cookie=self.cookie_admin)
        self.assertEqual(st_cor, 400)

        # 5e: Valid 1200x900 image uploaded by admin -> 200, warnings length 1
        data_url_rect = make_test_data_url(1200, 900, "PNG")
        st_up_adm, res_up_adm = self._req("POST", "/api/uploads", {"dataUrl": data_url_rect, "nameZh": "长方形封面"}, cookie=self.cookie_admin)
        self.assertEqual(st_up_adm, 200)
        rect_url = res_up_adm["url"]

        p_rect = {
            "series": "FE",
            "code": "",
            "name": "长方形封面画风",
            "description": "描述",
            "definition": "定义",
            "image": rect_url,
            "unlockCost": 0,
        }
        st_rect, res_rect = self._req("POST", "/api/admin/catalog/official", p_rect, cookie=self.cookie_admin)
        self.assertEqual(st_rect, 200, res_rect)
        warnings = res_rect.get("warnings") or []
        self.assertEqual(len(warnings), 1)
        self.assertIn("1200", warnings[0])
        self.assertIn("900", warnings[0])

    def test_06_unlock_cost_and_tier(self) -> None:
        """6. unlockCost: 20 -> tier='credit'; unlockCost: -1 or 501 -> 400."""
        # 6a: unlockCost 20 -> tier='credit'
        p_paid = {
            "series": "FE",
            "code": "",
            "name": "付费官方画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
            "unlockCost": 20,
        }
        st_paid, res_paid = self._req("POST", "/api/admin/catalog/official", p_paid, cookie=self.cookie_admin)
        self.assertEqual(st_paid, 200, res_paid)
        code = res_paid["code"]
        row = self.db.get_conn().execute("SELECT tier, unlock_cost FROM catalog_assets WHERE code = ?", (code,)).fetchone()
        self.assertEqual(row["tier"], "credit")
        self.assertEqual(row["unlock_cost"], 20)

        # 6b: unlockCost: -1 -> 400
        p_neg = {**p_paid, "name": "负数代价", "unlockCost": -1}
        st_neg, _ = self._req("POST", "/api/admin/catalog/official", p_neg, cookie=self.cookie_admin)
        self.assertEqual(st_neg, 400)

        # 6c: unlockCost: 501 -> 400
        p_high = {**p_paid, "name": "过高代价", "unlockCost": 501}
        st_high, _ = self._req("POST", "/api/admin/catalog/official", p_high, cookie=self.cookie_admin)
        self.assertEqual(st_high, 400)

    def test_07_boot_payload_and_hidden(self) -> None:
        """7. Anonymous GET /api/boot has FE-069 in officialResources, not officialOverrides;
        status='hidden' hides it from both."""
        p_pub = {
            "series": "FE",
            "code": "FE-069",
            "name": "上线画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
            "unlockCost": 0,
        }
        st, res = self._req("POST", "/api/admin/catalog/official", p_pub, cookie=self.cookie_admin)
        self.assertEqual(st, 200, res)

        # Anonymous GET /api/boot
        st_boot, boot_data = self._req("GET", "/api/boot")
        self.assertEqual(st_boot, 200)
        off_res = boot_data.get("officialResources") or []
        off_over = boot_data.get("officialOverrides") or []
        self.assertTrue(any(r.get("code") == "FE-069" or r.get("id") == "FE-069" for r in off_res))
        self.assertFalse(any(r.get("code") == "FE-069" or r.get("id") == "FE-069" for r in off_over))

        # Admin updates FE-069 to status='hidden'
        st_upd, _ = self._req("POST", "/api/admin/catalog/official/FE-069", {
            "name": "上线画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
            "status": "hidden",
            "unlockCost": 0,
        }, cookie=self.cookie_admin)
        self.assertEqual(st_upd, 200)

        # GET /api/boot again: neither should contain FE-069
        st_boot2, boot_data2 = self._req("GET", "/api/boot")
        self.assertEqual(st_boot2, 200)
        off_res2 = boot_data2.get("officialResources") or []
        off_over2 = boot_data2.get("officialOverrides") or []
        self.assertFalse(any(r.get("code") == "FE-069" or r.get("id") == "FE-069" for r in off_res2))
        self.assertFalse(any(r.get("code") == "FE-069" or r.get("id") == "FE-069" for r in off_over2))

    def test_08_channel_and_studio_resolution(self) -> None:
        """8. Studio / Channel resolution: prepare_cloud_generation resolves FE-069 with style1."""
        p = {
            "series": "FE",
            "code": "FE-069",
            "name": "宋锦纹样测试版",
            "description": "宋锦描述",
            "definition": "特选宋锦几何纹样提示词核心定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
            "unlockCost": 0,
        }
        st, res = self._req("POST", "/api/admin/catalog/official", p, cookie=self.cookie_admin)
        self.assertEqual(st, 200, res)

        # Visitor prepares cloud generation with style1='FE-069'
        with patch("backend.skill_prompt.skill_available", return_value=True), \
             patch("backend.skill_prompt.compose_prompt", return_value={"prompt": "特选宋锦几何纹样核心提示词"}):
            prep = prepare_cloud_generation(self.db, self.visitor_user, {
                "prompt": "一只奔跑的猫",
                "style1": "FE-069",
                "ratio": "1:1",
            })
            self.assertIsNotNone(prep)
            gen_id = prep.get("genId")
            self.assertTrue(gen_id)
            row = self.db.get_conn().execute("SELECT * FROM studio_generations WHERE id = ?", (gen_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertIn("FE-069", row["recipe_summary"])
            self.assertIn("特选宋锦几何纹样", row["prompt"])

    def test_09_t_redirect_and_forum_replies(self) -> None:
        """9. /t/FE-069 302 redirects to topic page; 0 replies -> not listed in forum list; 1 reply -> listed."""
        p = {
            "series": "FE",
            "code": "FE-069",
            "name": "论坛测试官方画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
            "unlockCost": 0,
        }
        st, res = self._req("POST", "/api/admin/catalog/official", p, cookie=self.cookie_admin)
        self.assertEqual(st, 200, res)

        # GET /t/FE-069 with NoRedirect
        req = urllib.request.Request(f"{self.base}/t/FE-069")
        opener = urllib.request.build_opener(NoRedirectHandler)
        try:
            resp = opener.open(req)
            resp_code = resp.status
            loc = resp.headers.get("Location")
        except urllib.error.HTTPError as e:
            resp_code = e.code
            loc = e.headers.get("Location")

        self.assertEqual(resp_code, 302)
        self.assertTrue(loc and "id=topic_" in loc, f"Unexpected redirect target: {loc}")
        parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
        topic_id = parsed_q.get("id", [""])[0]
        self.assertTrue(topic_id)

        # Check forum topics list (0 replies): topic should not be in published list
        st_boot, boot_data = self._req("GET", "/api/boot")
        self.assertEqual(st_boot, 200)
        f_topics = boot_data.get("topics") or []
        self.assertFalse(any(t.get("id") == topic_id for t in f_topics))

        # Visitor posts a reply to this topic
        st_rep, res_rep = self._req("POST", f"/api/posts/{topic_id}/replies", {
            "text": "这个画风太好看了，支持官方新增！"
        }, cookie=self.cookie_visitor)
        self.assertEqual(st_rep, 200, res_rep)

        # Now forum topics list should include this topic
        st_boot2, boot_data2 = self._req("GET", "/api/boot")
        self.assertEqual(st_boot2, 200)
        f_topics2 = boot_data2.get("topics") or []
        self.assertTrue(any(t.get("id") == topic_id for t in f_topics2))

    def test_10_skill_library_and_delete_protection(self) -> None:
        """10. Skill library: official asset in official bucket with official license.
        Delete protection: referenced in works.styles_json -> 409 asset_in_use; unreferenced -> 200."""
        # 10a: Create free official asset FE-069
        p1 = {
            "series": "FE",
            "code": "FE-069",
            "name": "收藏测试画风",
            "description": "描述",
            "definition": "公开官方定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-069.webp",
            "unlockCost": 0,
        }
        st1, _ = self._req("POST", "/api/admin/catalog/official", p1, cookie=self.cookie_admin)
        self.assertEqual(st1, 200)

        # Visitor favorites FE-069
        st_fav, _ = self._req("POST", "/api/collections/toggle", {
            "bucket": "styles",
            "id": "FE-069",
        }, cookie=self.cookie_visitor)
        self.assertEqual(st_fav, 200)

        # GET /api/skill/library
        st_lib, lib_data = self._req("GET", "/api/skill/library", cookie=self.cookie_visitor)
        self.assertEqual(st_lib, 200)
        official_items = lib_data.get("official") or []
        match_item = next((it for it in official_items if it.get("ref") == "FE-069"), None)
        self.assertIsNotNone(match_item)
        content_url = match_item.get("content_url")
        self.assertIsNotNone(content_url)

        # GET content_url verifies license
        st_cnt, cnt_data = self._req("GET", content_url, cookie=self.cookie_visitor)
        self.assertEqual(st_cnt, 200)
        res_info = cnt_data.get("resource") or {}
        self.assertEqual(res_info.get("license"), "Handraw Official Reference License 1.0")
        self.assertEqual(res_info.get("prompt_zh"), "公开官方定义")

        # 10b: Referenced deletion protection
        # Insert a work referencing FE-069 in styles_json
        now = "2026-11-03T12:00:00Z"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, notes, prompt, images_json, styles_json, published_at_ms, created_at, updated_at)
                VALUES ('work_ref_test', ?, '测试用户', '引用测试作品', '作品说明文字超过八个字', '测试提示词', '[\"/uploads/test.png\"]', '[\"FE-069\"]', 1000, ?, ?)
                """,
                (self.visitor_user["username"], now, now),
            )

        # Attempt to delete FE-069 -> 409 asset_in_use
        st_del, res_del = self._req("POST", "/api/admin/catalog/official/FE-069/delete", {}, cookie=self.cookie_admin)
        self.assertEqual(st_del, 409)
        self.assertEqual(res_del.get("code"), "asset_in_use")

        # 10c: Unreferenced asset deletion
        p2 = {
            "series": "FE",
            "code": "FE-071",
            "name": "未被引用画风",
            "description": "描述",
            "definition": "定义",
            "image": "https://img.handraw-style.com/images/individual/FE/FE-071.webp",
            "unlockCost": 0,
        }
        st2, _ = self._req("POST", "/api/admin/catalog/official", p2, cookie=self.cookie_admin)
        self.assertEqual(st2, 200)

        st_del_ok, res_del_ok = self._req("POST", "/api/admin/catalog/official/FE-071/delete", {}, cookie=self.cookie_admin)
        self.assertEqual(st_del_ok, 200)
        self.assertTrue(res_del_ok.get("ok"))
        row_del = self.db.get_conn().execute("SELECT code FROM catalog_assets WHERE code = 'FE-071'").fetchone()
        self.assertIsNone(row_del)

    def test_13_concurrent_official_code_allocation(self) -> None:
        """13. Concurrency test: Two threads concurrently create FE series official assets.
        Both must return 200, receive different auto-allocated codes (e.g. FE-069 and FE-070),
        and neither crashes with 500 or code collision.
        """
        img_url = "https://img.handraw-style.com/images/individual/FE/FE-069.webp"
        results: list[tuple[int, dict]] = []
        barrier = threading.Barrier(2)

        def worker(idx: int) -> None:
            payload = {
                "series": "FE",
                "code": "",
                "name": f"并发测试官方画风_{idx}",
                "description": f"并发画风描述_{idx}",
                "definition": f"并发画风定义完整内容_{idx}",
                "image": img_url,
                "unlockCost": 0,
            }
            # Synchronize threads so both make request at the exact same moment
            try:
                barrier.wait(timeout=5)
            except Exception:
                pass
            status, res = self._req("POST", "/api/admin/catalog/official", payload, cookie=self.cookie_admin)
            results.append((status, res))

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(len(results), 2)
        status1, res1 = results[0]
        status2, res2 = results[1]

        self.assertEqual(status1, 200, f"Thread 1 failed with {status1}: {res1}")
        self.assertEqual(status2, 200, f"Thread 2 failed with {status2}: {res2}")
        self.assertTrue(res1.get("ok"))
        self.assertTrue(res2.get("ok"))

        code1 = res1.get("code")
        code2 = res2.get("code")
        self.assertNotEqual(code1, code2, f"Both threads allocated the same code: {code1}")
        self.assertEqual({code1, code2}, {"FE-069", "FE-070"})



if __name__ == "__main__":
    unittest.main()
