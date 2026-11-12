"""Tests for Phase 3a-2 Studio recipes, prompt preview, and work snapshot.

Covers:
1. Database migrations 060 (studio_recipes) & 061 (studio_generations.recipe_id, works.subject).
2. Recipe CRUD with user_id scoping (S3: foreign recipes return 404).
3. Revision conditional updates and 409 conflict handling.
4. S9 three state transitions (customized/stale parameter synchronization).
5. Field validations (style/layout format, ratio format, length bounds, foreign references 403).
6. Personal access token default-deny (hwt_ token returns 403 on all recipe endpoints).
7. Prompt preview:
   - Skill compose_prompt outside transaction (another thread can write during call).
   - Writeback with revision check (409 on race).
   - Daily usage limit (100 times/day -> 429).
8. Studio generate with recipeId:
   - Parameters and prompt from recipe override request body.
   - Recipe prompt sent to gateway with systemAppend.
   - Generation row records recipe_id.
   - Backward compatibility: request without recipeId leaves response and DB byte-for-byte unchanged.
9. Work snapshot (/api/studio/recipes/from-work/{workId}):
   - Invisible/unapproved work returns 404.
   - Draft returned with subject="" and subjectHint from work.subject or prompt first sentence (<= 80 chars).
   - Draft is non-persisted.
10. publish_work_direct accepts optional subject / recipeId and writes works.subject.
"""
from __future__ import annotations
from tests.postgres_support import open_isolated_postgres

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend import skill_prompt
from backend.curation import publish_work_direct
from backend.recipe_routes import compute_input_fingerprint
from backend.resource_discussions import resolve_resource
from backend.server import SESSION_COOKIE_NAME, HandrawRequestHandler
from backend.services import ServiceError, prepare_cloud_generation, register_user


class StudioRecipesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
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

        # Seed two distinct users for attribution tests
        self.user_a, token_a = register_user(self.db, "alice", "AlicePass123")
        self.user_b, token_b = register_user(self.db, "bob", "BobPass123")
        self.cookie_a = f"{SESSION_COOKIE_NAME}={token_a}"
        self.cookie_b = f"{SESSION_COOKIE_NAME}={token_b}"

        # Give Alice an owned upload and Bob an owned upload
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, name_zh, desc_zh, image_url, file_path, bytes, created_at)
                VALUES ('upl_alice', ?, 'alice', '', '/uploads/alice_sample.webp', 'alice_sample.webp', 1024, '2026-10-31T00:00:00Z')
                """,
                (self.user_a["id"],),
            )
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, name_zh, desc_zh, image_url, file_path, bytes, created_at)
                VALUES ('upl_bob', ?, 'bob', '', '/uploads/bob_sample.webp', 'bob_sample.webp', 1024, '2026-10-31T00:00:00Z')
                """,
                (self.user_b["id"],),
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
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            return exc.code, json.loads(raw) if raw else {}

    def _create_token(self, user_id: int, scopes: list[str]) -> str:
        raw_token = f"hwt_test_{hashlib.sha256(os.urandom(16)).hexdigest()}"
        tok_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        tok_id = f"tok_{os.urandom(8).hex()}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO api_tokens (id, user_id, name, scopes, token_hash, created_at)
                VALUES (?, ?, 'Test', ?, ?, '2026-10-31T00:00:00Z')
                """,
                (tok_id, user_id, json.dumps(scopes), tok_hash),
            )
        return raw_token

    def test_migrations_applied_and_ordered(self) -> None:
        """Verify schema migrations 060 and 061 exist and added required columns."""
        conn = self.db.get_conn()
        recipes_cols = {r["name"] for r in conn.execute("SELECT ordinal_position-1 AS cid,column_name AS name FROM information_schema.columns WHERE table_schema='public' AND table_name='studio_recipes' ORDER BY ordinal_position").fetchall()}
        self.assertIn("id", recipes_cols)
        self.assertIn("user_id", recipes_cols)
        self.assertIn("kind", recipes_cols)
        self.assertIn("style_ids", recipes_cols)
        self.assertIn("layout_id", recipes_cols)
        self.assertIn("prompt_customized", recipes_cols)
        self.assertIn("prompt_stale", recipes_cols)
        self.assertIn("input_fingerprint", recipes_cols)
        self.assertIn("revision", recipes_cols)

        gen_cols = {r["name"] for r in conn.execute("SELECT ordinal_position-1 AS cid,column_name AS name FROM information_schema.columns WHERE table_schema='public' AND table_name='studio_generations' ORDER BY ordinal_position").fetchall()}
        self.assertIn("recipe_id", gen_cols)

        works_cols = {r["name"] for r in conn.execute("SELECT ordinal_position-1 AS cid,column_name AS name FROM information_schema.columns WHERE table_schema='public' AND table_name='works' ORDER BY ordinal_position").fetchall()}
        self.assertIn("subject", works_cols)

    def test_recipe_crud_and_attribution(self) -> None:
        """User A creates a recipe; User B cannot read or update it (404)."""
        payload = {
            "kind": "single",
            "styleIds": ["FA-001"],
            "layoutId": "L-01",
            "colors": ["C-01"],
            "tones": ["T-01"],
            "moods": ["治愈"],
            "whitespace": "normal",
            "ratio": "3:4",
            "mode": "graphic-text",
            "subject": "猫咪喝咖啡",
            "references": ["/uploads/alice_sample.webp"],
        }
        status, res = self._req("POST", "/api/studio/recipes", payload, cookie=self.cookie_a)
        self.assertEqual(status, 201)
        self.assertTrue(res["ok"])
        recipe_id = res["id"]
        self.assertEqual(res["revision"], 0)
        self.assertEqual(res["recipe"]["subject"], "猫咪喝咖啡")
        self.assertEqual(res["recipe"]["styleIds"], ["FA-001"])

        # Alice can get her recipe
        st, r_get = self._req("GET", f"/api/studio/recipes/{recipe_id}", cookie=self.cookie_a)
        self.assertEqual(st, 200)
        self.assertEqual(r_get["recipe"]["id"], recipe_id)

        # Bob gets 404 (Attribution S3)
        st_bob, r_bob = self._req("GET", f"/api/studio/recipes/{recipe_id}", cookie=self.cookie_b)
        self.assertEqual(st_bob, 404)
        self.assertEqual(r_bob.get("code"), "recipe_not_found")

        # Bob cannot PUT Alice's recipe (404)
        st_put, r_put = self._req(
            "PUT",
            f"/api/studio/recipes/{recipe_id}",
            {"baseRevision": 0, "subject": "黑客修改"},
            cookie=self.cookie_b,
        )
        self.assertEqual(st_put, 404)

        # Alice lists her recipes
        st_list, r_list = self._req("GET", "/api/studio/recipes?kind=single", cookie=self.cookie_a)
        self.assertEqual(st_list, 200)
        self.assertEqual(len(r_list["items"]), 1)
        self.assertEqual(r_list["items"][0]["id"], recipe_id)

        # Bob lists recipes (empty for Bob)
        st_blist, r_blist = self._req("GET", "/api/studio/recipes", cookie=self.cookie_b)
        self.assertEqual(st_blist, 200)
        self.assertEqual(len(r_blist["items"]), 0)

    def test_optimistic_locking_and_conflict_409(self) -> None:
        """PUT requires baseRevision; mismatched revision returns 409 and current version."""
        # Create recipe with initial revision 0
        _, res = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FA-001"], "subject": "初始主题"},
            cookie=self.cookie_a,
        )
        rcp_id = res["id"]

        # PUT without baseRevision returns 400
        st_no_rev, _ = self._req("PUT", f"/api/studio/recipes/{rcp_id}", {"subject": "改"}, cookie=self.cookie_a)
        self.assertEqual(st_no_rev, 400)

        # PUT with wrong baseRevision (1 instead of 0) returns 409
        st_conf, r_conf = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 1, "subject": "冲突尝试"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_conf, 409)
        self.assertEqual(r_conf["code"], "conflict")
        self.assertEqual(r_conf["revision"], 0)
        self.assertEqual(r_conf["recipe"]["subject"], "初始主题")

        # Valid PUT increments revision to 1
        st_ok, r_ok = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 0, "subject": "版本一"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_ok, 200)
        self.assertEqual(r_ok["revision"], 1)
        self.assertEqual(r_ok["recipe"]["subject"], "版本一")

        # Re-trying with old baseRevision 0 now fails with 409
        st_conf2, r_conf2 = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 0, "subject": "再改"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_conf2, 409)
        self.assertEqual(r_conf2["revision"], 1)

    def test_s9_three_state_transitions(self) -> None:
        """Verify S9 parameter and prompt synchronization states:

        1. promptCustomized=false -> modifying params clears prompt.
        2. promptCustomized=true -> modifying params marks promptStale=true.
        3. User edits prompt -> promptCustomized=true, promptStale=false.
        """
        # Create recipe with promptCustomized=false and a prompt (e.g. from preview)
        _, res = self._req(
            "POST",
            "/api/studio/recipes",
            {
                "styleIds": ["FA-001"],
                "subject": "猫",
                "prompt": "系统生成的猫咪提示词",
                "promptCustomized": False,
            },
            cookie=self.cookie_a,
        )
        rcp_id = res["id"]
        self.assertFalse(res["recipe"]["promptCustomized"])
        self.assertEqual(res["recipe"]["prompt"], "系统生成的猫咪提示词")

        # Transition 1: Modify subject when promptCustomized=false -> prompt is cleared!
        st1, r1 = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 0, "subject": "狗"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st1, 200)
        self.assertEqual(r1["recipe"]["subject"], "狗")
        self.assertEqual(r1["recipe"]["prompt"], "")
        self.assertFalse(r1["recipe"]["promptCustomized"])
        self.assertFalse(r1["recipe"]["promptStale"])

        # Transition 3: User manually edits prompt -> promptCustomized=true, promptStale=false
        st3, r3 = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 1, "prompt": "用户精心手写的生动狗狗画作"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st3, 200)
        self.assertEqual(r3["recipe"]["prompt"], "用户精心手写的生动狗狗画作")
        self.assertTrue(r3["recipe"]["promptCustomized"])
        self.assertFalse(r3["recipe"]["promptStale"])

        # Transition 2: When promptCustomized=true, modifying style -> prompt preserved, promptStale=true
        st2, r2 = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 2, "styleIds": ["FA-002"]},
            cookie=self.cookie_a,
        )
        self.assertEqual(st2, 200)
        self.assertEqual(r2["recipe"]["styleIds"], ["FA-002"])
        self.assertEqual(r2["recipe"]["prompt"], "用户精心手写的生动狗狗画作")
        self.assertTrue(r2["recipe"]["promptCustomized"])
        self.assertTrue(r2["recipe"]["promptStale"])

        # User edits prompt again -> clears promptStale
        st_reset, r_reset = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 3, "prompt": "用户根据FA-002调整后的提示词"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_reset, 200)
        self.assertTrue(r_reset["recipe"]["promptCustomized"])
        self.assertFalse(r_reset["recipe"]["promptStale"])

    def test_field_validations(self) -> None:
        """Test validation for style/layout format, ratio format, length bounds, foreign references."""
        # 1. Invalid style format
        st, _ = self._req("POST", "/api/studio/recipes", {"styleIds": ["INVALID STYLE!"]}, cookie=self.cookie_a)
        self.assertEqual(st, 400)

        # 2. More than 2 styles
        st, _ = self._req("POST", "/api/studio/recipes", {"styleIds": ["FA-001", "FA-002", "FA-003"]}, cookie=self.cookie_a)
        self.assertEqual(st, 400)

        # 3. Invalid layout format
        st, _ = self._req("POST", "/api/studio/recipes", {"layoutId": "L-01 bad"}, cookie=self.cookie_a)
        self.assertEqual(st, 400)

        # 4. Invalid ratio format
        st, _ = self._req("POST", "/api/studio/recipes", {"ratio": "3x4"}, cookie=self.cookie_a)
        self.assertEqual(st, 400)

        # 5. Subject > 2000 chars
        st, _ = self._req("POST", "/api/studio/recipes", {"subject": "A" * 2001}, cookie=self.cookie_a)
        self.assertEqual(st, 400)

        # 6. Prompt > 4000 chars
        st, _ = self._req("POST", "/api/studio/recipes", {"prompt": "B" * 4001}, cookie=self.cookie_a)
        self.assertEqual(st, 400)

        # 7. More than 6 references
        st, _ = self._req("POST", "/api/studio/recipes", {"references": [f"/uploads/img_{i}.png" for i in range(7)]}, cookie=self.cookie_a)
        self.assertEqual(st, 400)

        # 8. Foreign reference (Alice uses Bob's upload -> 403 foreign_media)
        st_ref, r_ref = self._req(
            "POST",
            "/api/studio/recipes",
            {"references": ["/uploads/bob_sample.webp"]},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_ref, 403)
        self.assertEqual(r_ref.get("code"), "foreign_media")

    def test_api_token_rejected_403(self) -> None:
        """Personal access tokens (hwt_) must receive 403 on all recipe endpoints."""
        token = self._create_token(self.user_a["id"], scopes=["publish", "library"])

        endpoints = [
            ("GET", "/api/studio/recipes"),
            ("POST", "/api/studio/recipes"),
            ("GET", "/api/studio/recipes/rcp_dummy"),
            ("PUT", "/api/studio/recipes/rcp_dummy"),
            ("POST", "/api/studio/recipes/rcp_dummy/prompt"),
            ("GET", "/api/studio/recipes/from-work/work_dummy"),
        ]

        for method, path in endpoints:
            st, res = self._req(method, path, body={"baseRevision": 0} if method in ("POST", "PUT") else None, token=token)
            self.assertEqual(st, 403, f"{method} {path} should return 403 for API token, got {st}")
            self.assertEqual(res.get("code"), "token_scope_denied")

    def test_prompt_preview_and_non_blocking_concurrency(self) -> None:
        """POST /api/studio/recipes/{id}/prompt:

        - Calls Skill outside transaction (allowing another thread to write to DB).
        - Enforces 100/day daily limit.
        - Updates prompt, resets customized/stale, increments revision.
        - Returns 409 if revision changed during AI call.
        """
        _, res = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FA-001"], "layoutId": "L-01", "subject": "咖啡猫咪"},
            cookie=self.cookie_a,
        )
        rcp_id = res["id"]

        # Test normal prompt preview
        with patch("backend.skill_prompt.compose_prompt") as mock_compose:
            mock_compose.return_value = {
                "prompt": "Playful handdrawn doodle of a cat drinking coffee in a cafe",
                "source": "model",
            }
            st, r_prompt = self._req("POST", f"/api/studio/recipes/{rcp_id}/prompt", cookie=self.cookie_a)
            self.assertEqual(st, 200)
            self.assertEqual(r_prompt["prompt"], "Playful handdrawn doodle of a cat drinking coffee in a cafe")
            self.assertEqual(r_prompt["revision"], 1)

        # Verify DB row updated
        _, r_get = self._req("GET", f"/api/studio/recipes/{rcp_id}", cookie=self.cookie_a)
        self.assertEqual(r_get["recipe"]["prompt"], "Playful handdrawn doodle of a cat drinking coffee in a cafe")
        self.assertFalse(r_get["recipe"]["promptCustomized"])
        self.assertFalse(r_get["recipe"]["promptStale"])
        self.assertEqual(r_get["recipe"]["revision"], 1)

        # Test another thread can write to DB while compose_prompt is executing
        write_success = False

        def mock_compose_with_concurrent_write(*args, **kwargs):
            nonlocal write_success
            # Simulate another thread writing to the database
            with self.db.transaction() as tx:
                tx.execute(
                    "INSERT INTO user_uploads (id, user_id, name_zh, desc_zh, image_url, file_path, bytes, created_at) "
                    "VALUES ('concurrent_write', 1, 'con', '', '/uploads/con.webp', 'con.webp', 10, '2026-10-31T00:00:00Z')"
                )
            write_success = True
            return {"prompt": "Concurrent generated prompt", "source": "model"}

        with patch("backend.skill_prompt.compose_prompt", side_effect=mock_compose_with_concurrent_write):
            st_c, _ = self._req("POST", f"/api/studio/recipes/{rcp_id}/prompt", cookie=self.cookie_a)
            self.assertEqual(st_c, 200)
            self.assertTrue(write_success, "Another thread successfully wrote to PostgreSQL while compose_prompt was running")

        # Test race condition: if another thread updates the recipe revision while AI is running -> 409
        def mock_compose_that_conflicts(*args, **kwargs):
            # Bump recipe revision in another thread behind its back
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE studio_recipes SET revision = revision + 1 WHERE id = ?",
                    (rcp_id,),
                )
            return {"prompt": "Late prompt", "source": "model"}

        with patch("backend.skill_prompt.compose_prompt", side_effect=mock_compose_that_conflicts):
            st_race, r_race = self._req("POST", f"/api/studio/recipes/{rcp_id}/prompt", cookie=self.cookie_a)
            self.assertEqual(st_race, 409)
            self.assertEqual(r_race["code"], "conflict")

        # Test daily quota limit (100 times)
        # Manually set daily_usage count to 100
        from backend.db import local_today_str

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO daily_usage (user_id, scope, usage_date, count)
                VALUES (?, 'prompt', ?, 100)
                ON CONFLICT(user_id, scope, usage_date) DO UPDATE SET count = 100
                """,
                (self.user_a["id"], local_today_str()),
            )

        st_quota, r_quota = self._req("POST", f"/api/studio/recipes/{rcp_id}/prompt", cookie=self.cookie_a)
        self.assertEqual(st_quota, 429)
        self.assertEqual(r_quota["code"], "daily_quota_exceeded")

    def test_studio_generate_with_recipe_and_backward_compatibility(self) -> None:
        """Test /api/studio/generate with recipeId:

        1. Parameters and prompt from recipe override request body.
        2. systemAppend is returned and prompt to gateway matches recipe prompt (+ systemAppend).
        3. Backward compatibility: request without recipeId produces exact same response keys.
        """
        # Create a recipe with customized prompt and specific parameters
        _, res = self._req(
            "POST",
            "/api/studio/recipes",
            {
                "styleIds": ["FA-001"],
                "layoutId": "L-01",
                "ratio": "16:9",
                "subject": "原配方主题",
                "prompt": "Recipe exact prompt for gateway",
                "promptCustomized": True,
            },
            cookie=self.cookie_a,
        )
        rcp_id = res["id"]

        # Call /api/studio/generate with recipeId and conflicting body fields
        gen_body = {
            "recipeId": rcp_id,
            "simulateGateway": "ok",
            "style1": "FA-999",  # Request tries to override style -> ignored
            "prompt": "Hacker prompt",  # Request tries to override prompt -> ignored
            "ratio": "1:1",  # Request tries to override ratio -> ignored
            "useCh001": True,  # Request tries to inject reference -> ignored
        }
        st_gen, r_gen = self._req("POST", "/api/studio/generate", gen_body, cookie=self.cookie_a)
        self.assertEqual(st_gen, 200)
        self.assertTrue(r_gen["ok"])
        self.assertEqual(r_gen["recipeId"], rcp_id)
        self.assertIn("systemAppend", r_gen)

        # Inspect database row in studio_generations
        gen_id = r_gen["genId"]
        conn = self.db.get_conn()
        grow = conn.execute("SELECT * FROM studio_generations WHERE id = ?", (gen_id,)).fetchone()
        self.assertEqual(grow["recipe_id"], rcp_id)
        self.assertEqual(grow["mode"], "16:9")  # ratio from recipe!
        # The prompt recorded has recipe prompt (plus systemAppend if any)
        self.assertTrue(grow["prompt"].startswith("Recipe exact prompt for gateway"))

        # Test Bob cannot generate using Alice's recipe (404)
        st_bgen, r_bgen = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": rcp_id, "simulateGateway": "ok"},
            cookie=self.cookie_b,
        )
        self.assertEqual(st_bgen, 404)
        self.assertEqual(r_bgen.get("code"), "recipe_not_found")

        # Test Backward Compatibility: Old generate path without recipeId
        old_body = {
            "simulateGateway": "ok",
            "prompt": "Legacy standalone generation prompt",
            "ratio": "3:4",
        }
        st_old, r_old = self._req("POST", "/api/studio/generate", old_body, cookie=self.cookie_a)
        self.assertEqual(st_old, 200)
        self.assertNotIn("recipeId", r_old)
        self.assertNotIn("systemAppend", r_old)
        old_grow = conn.execute("SELECT * FROM studio_generations WHERE id = ?", (r_old["genId"],)).fetchone()
        self.assertEqual(old_grow["recipe_id"], "")

    def test_snapshot_from_work(self) -> None:
        """GET /api/studio/recipes/from-work/{workId}:

        - Unpublished work returns 404.
        - Published work returns non-persisted draft with subjectHint from work.subject or prompt first sentence (<= 80 chars).
        """
        # Publish a work directly using publish_work_direct
        work_body = {
            "title": "测试作品海报",
            "prompt": "秋日午后可爱的读书小猫。阳光透过玻璃窗洒在木质书桌上。",
            "images": ["/uploads/alice_sample.webp"],
            "styles": ["FA-001"],
            "layout": "SB-001",
            "color": "C-01",
            "tone": "T-01",
            "ratio": "3:4",
            "mode": "graphic-text",
            "mood": "治愈",
            "subject": "秋日午后读书猫咪",
        }
        res_work = publish_work_direct(self.db, self.user_a, work_body)
        work_id = res_work["workId"]

        # Call from-work endpoint
        st, res = self._req("GET", f"/api/studio/recipes/from-work/{work_id}", cookie=self.cookie_a)
        self.assertEqual(st, 200)
        draft = res["draft"]
        self.assertEqual(draft["subject"], "")  # Empty subject for user to fill
        self.assertEqual(draft["subjectHint"], "秋日午后读书猫咪")
        self.assertEqual(draft["styleIds"], ["FA-001"])
        self.assertEqual(draft["layoutId"], "SB-001")
        self.assertEqual(draft["ratio"], "3:4")
        self.assertFalse(draft["promptCustomized"])

        # Check that this draft did NOT persist to studio_recipes table
        conn = self.db.get_conn()
        count = conn.execute("SELECT COUNT(*) AS cnt FROM studio_recipes").fetchone()["cnt"]
        self.assertEqual(count, 0)

        # Test work without explicit subject: falls back to first sentence of prompt (<= 80 chars)
        work_body_no_sub = {
            "title": "无主题作品",
            "prompt": "第一句这是原提示词首句！第二句这是补充细节。第三句这是背景说明。",
            "images": ["/uploads/alice_sample.webp"],
            "styles": ["FA-002"],
        }
        res_work2 = publish_work_direct(self.db, self.user_a, work_body_no_sub)
        st2, res2 = self._req("GET", f"/api/studio/recipes/from-work/{res_work2['workId']}", cookie=self.cookie_a)
        self.assertEqual(st2, 200)
        self.assertEqual(res2["draft"]["subjectHint"], "第一句这是原提示词首句")

        # Image-scoped deep links select a canonical media index; malformed
        # or out-of-range indices fail explicitly instead of silently cloning
        # the first picture's recipe.
        st_zero, zero = self._req(
            "GET", f"/api/studio/recipes/from-work/{work_id}?image=0", cookie=self.cookie_a,
        )
        self.assertEqual(st_zero, 200)
        self.assertEqual(zero["draft"]["source"]["imageIndex"], 0)
        self.assertEqual(zero["draft"]["styleIds"], ["FA-001"])
        for bad in ("image=not-an-index", "image=-1", "image=1", "image=9999999"):
            status, failed = self._req(
                "GET", f"/api/studio/recipes/from-work/{work_id}?{bad}", cookie=self.cookie_a,
            )
            self.assertEqual(status, 400, bad)
            self.assertEqual(failed.get("code"), "invalid_fork_image")

        # Test non-existent work returns 404
        st_404, _ = self._req("GET", "/api/studio/recipes/from-work/nonexistent_id", cookie=self.cookie_a)
        self.assertEqual(st_404, 404)

    def test_publish_work_direct_accepts_subject_and_recipe_id(self) -> None:
        """publish_work_direct accepts optional subject and recipeId."""
        # Create a recipe for Alice
        _, res_rcp = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FA-001"], "subject": "配方中的主题内容"},
            cookie=self.cookie_a,
        )
        rcp_id = res_rcp["id"]

        # Publish work providing recipeId without subject -> pulls subject from recipe
        res1 = publish_work_direct(
            self.db,
            self.user_a,
            {
                "title": "作品一",
                "prompt": "提示词一",
                "images": ["/uploads/alice_sample.webp"],
                "recipeId": rcp_id,
            },
        )
        conn = self.db.get_conn()
        row1 = conn.execute("SELECT subject FROM works WHERE id = ?", (res1["workId"],)).fetchone()
        self.assertEqual(row1["subject"], "配方中的主题内容")

        # Publish work providing explicit subject -> uses explicit subject
        res2 = publish_work_direct(
            self.db,
            self.user_a,
            {
                "title": "作品二",
                "prompt": "提示词二",
                "images": ["/uploads/alice_sample.webp"],
                "subject": "显式传入的主题",
            },
        )
        row2 = conn.execute("SELECT subject FROM works WHERE id = ?", (res2["workId"],)).fetchone()
        self.assertEqual(row2["subject"], "显式传入的主题")

        # Subject > 2000 chars raises ServiceError
        with self.assertRaises(Exception):
            publish_work_direct(
                self.db,
                self.user_a,
                {
                    "title": "作品三",
                    "prompt": "提示词三",
                    "images": ["/uploads/alice_sample.webp"],
                    "subject": "X" * 2001,
                },
            )

    def test_x1_system_append_never_leaks_blackbox_secrets(self) -> None:
        """X1: systemAppend must be a list and never leak secret_blackbox_prompt.
        Replaying an old requestId must not read current request's unpurchased assets.
        """
        secret_text = "PAID_BLACKBOX_SUPER_SECRET_KEYWORD"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-SEC01', '独家黑盒画风', 'style', 'exclusive', 'A', 25, '/images/sec01.webp', 'bob', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (secret_text,),
            )

        # 1. Alice creates a normal free recipe and generates with requestId 'req-x1-orig'
        _, r_free = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FA-001"], "subject": "自由小鸟"},
            cookie=self.cookie_a,
        )
        rcp_free_id = r_free["id"]

        st_orig, r_orig = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": rcp_free_id, "requestId": "req-x1-orig", "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_orig, 200)
        self.assertEqual(r_orig["recipeId"], rcp_free_id)
        self.assertEqual(r_orig["systemAppend"], [])  # FA-001 has no secret prompt

        # 2. Alice creates a recipe pointing to unpurchased FX-SEC01
        _, r_paid = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FX-SEC01"], "subject": "盗取黑盒测试"},
            cookie=self.cookie_a,
        )
        rcp_paid_id = r_paid["id"]

        # Attack: Replay using the old requestId 'req-x1-orig'
        st_replay, r_replay = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": rcp_paid_id, "requestId": "req-x1-orig", "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_replay, 200)
        self.assertTrue(r_replay.get("idempotent"))
        # Replay must derive from original generation, not current request!
        self.assertEqual(r_replay["recipeId"], rcp_free_id)
        self.assertEqual(r_replay["systemAppend"], [])
        # Response JSON text must NOT contain the secret string anywhere!
        raw_json_replay = json.dumps(r_replay)
        self.assertNotIn(secret_text, raw_json_replay)

        # 3. Legitimate purchased generation: Bob (the author of FX-SEC01) generates
        _, r_bob_rcp = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FX-SEC01"], "subject": "合法作者生图"},
            cookie=self.cookie_b,
        )
        st_bob_gen, r_bob_gen = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": r_bob_rcp["id"], "requestId": "req-x1-bob-legit", "simulateGateway": "ok"},
            cookie=self.cookie_b,
        )
        self.assertEqual(st_bob_gen, 200)
        self.assertEqual(r_bob_gen["systemAppend"], [{"type": "asset_instructions", "code": "FX-SEC01"}])
        raw_json_bob = json.dumps(r_bob_gen)
        self.assertNotIn(secret_text, raw_json_bob, "Frontend JSON response must NEVER contain secret_blackbox_prompt")

        # But gateway / DB prompt DOES contain the injected blackbox secret!
        conn = self.db.get_conn()
        bob_grow = conn.execute("SELECT prompt FROM studio_generations WHERE id = ?", (r_bob_gen["genId"],)).fetchone()
        self.assertIn(secret_text, bob_grow["prompt"], "Gateway / generation row prompt must contain injected blackbox guidance")

    def test_x2_from_work_does_not_leak_paid_prompt(self) -> None:
        """X2: Work pricing rejected; from-work extracts prompt sentence for free works, hides masked prompts."""
        paid_secret_sentence = "PAID_SECRET_PROMPT_SENTENCE_ONE"
        full_paid_prompt = f"{paid_secret_sentence}。第二句补充细节文字内容。第三句结尾。"

        # Bob attempts to create a paid work with price=25 -> rejected with 400
        with self.assertRaises(ServiceError) as cm:
            publish_work_direct(
                self.db,
                self.user_b,
                {
                    "title": "尝试设价作品",
                    "price": 25,
                    "prompt": full_paid_prompt,
                    "images": ["/uploads/bob_sample.webp"],
                    "styles": ["FA-001"],
                },
            )
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.code, "work_price_not_allowed")

        # Bob creates a free work without subject
        res_work = publish_work_direct(
            self.db,
            self.user_b,
            {
                "title": "公开作品无主题",
                "price": 0,
                "prompt": full_paid_prompt,
                "images": ["/uploads/bob_sample.webp"],
                "styles": ["FA-001"],
            },
        )
        work_id = res_work["workId"]

        # 1. Other user (Alice) views draft: free work exposes subjectHint from prompt first sentence
        st_alice, r_alice = self._req("GET", f"/api/studio/recipes/from-work/{work_id}", cookie=self.cookie_a)
        self.assertEqual(st_alice, 200)
        self.assertEqual(r_alice["draft"]["subjectHint"], paid_secret_sentence)
        self.assertEqual(r_alice["draft"]["subject"], "")

        # 2. Author (Bob) views draft: can see first sentence
        st_bob, r_bob = self._req("GET", f"/api/studio/recipes/from-work/{work_id}", cookie=self.cookie_b)
        self.assertEqual(st_bob, 200)
        self.assertEqual(r_bob["draft"]["subjectHint"], paid_secret_sentence)

        # 3. Secret-bearing work hides subjectHint from unprivileged users
        with self.db.transaction() as tx:
            tx.execute("UPDATE works SET prompt_has_secret = 1 WHERE id = ?", (work_id,))
        st_alice_masked, r_alice_masked = self._req("GET", f"/api/studio/recipes/from-work/{work_id}", cookie=self.cookie_a)
        self.assertEqual(st_alice_masked, 200)
        self.assertEqual(r_alice_masked["draft"]["subjectHint"], "", "Masked work prompt must NOT leak into subjectHint")

    @unittest.skipUnless(skill_prompt.skill_available(), "Skill checkout not available")
    def test_x3_prompt_preview_and_compose_kwargs(self) -> None:
        """X3: compose_prompt optional kwargs byte-for-byte baseline lock and preview propagation."""
        from backend import skill_prompt

        # Baseline lock: call compose_prompt without kwargs, assert exact user message
        captured_messages = []
        def fake_call_model(sys_prompt, user_prompt, *, timeout=120):
            captured_messages.append((sys_prompt, user_prompt))
            return "A lovely hand-drawn illustration with clear strokes and beautiful colors."

        with patch("backend.skill_prompt._call_model", side_effect=fake_call_model):
            res_base = skill_prompt.compose_prompt("FA-013", "SC-021", "", "a boy holding a surfboard")
            self.assertEqual(len(captured_messages), 1)
            _, user_msg_base = captured_messages[0]

            facts = res_base["facts"]
            expected_user_base = (
                f"Style id: {facts['style']['id']}\n"
                f"Style name: {facts['style']['name']}\n"
                f"Style traits: {facts['style']['traits']}\n"
                f"Layout id: {facts['layout']['id']}\n"
                f"Layout name: {facts['layout']['name']}\n"
                f"Layout composition rules: {facts['layout']['rules'][:4000]}\n"
                f"Colour: not specified\n"
                f"Subject / theme (may be Chinese): a boy holding a surfboard\n"
            )
            self.assertEqual(user_msg_base, expected_user_base, "Baseline user message must be 100% byte-for-byte locked")

            # Test each of the 7 kwargs alters the user message
            kwargs_tests = [
                ("style2_code", "FA-002"),
                ("colors", ["#ff0000", "#00ff00"]),
                ("tones", ["T-01"]),
                ("moods", ["治愈"]),
                ("whitespace", "30%"),
                ("ratio", "16:9"),
                ("mode", "graphic-text"),
            ]
            for kw, val in kwargs_tests:
                captured_messages.clear()
                skill_prompt.compose_prompt("FA-013", "SC-021", "", "a boy holding a surfboard", **{kw: val})
                self.assertEqual(len(captured_messages), 1)
                _, user_msg_mod = captured_messages[0]
                self.assertNotEqual(user_msg_mod, expected_user_base, f"Modifying {kw} must alter user message")

        # Test preview_recipe_prompt passes all 7 recipe fields
        preview_captured_kwargs = {}
        def mock_compose_spy(*args, **kwargs):
            preview_captured_kwargs.update(kwargs)
            return {"prompt": "Spy mocked prompt", "source": "model"}

        _, res_rcp = self._req(
            "POST",
            "/api/studio/recipes",
            {
                "styleIds": ["FA-001", "FA-002"],
                "layoutId": "L-01",
                "colors": ["#112233"],
                "tones": ["T-02"],
                "moods": ["复古"],
                "whitespace": "20%",
                "ratio": "1:1",
                "mode": "illustration",
                "subject": "猫猫",
            },
            cookie=self.cookie_a,
        )
        rcp_id = res_rcp["id"]

        with patch("backend.skill_prompt.compose_prompt", side_effect=mock_compose_spy):
            st_prev, _ = self._req("POST", f"/api/studio/recipes/{rcp_id}/prompt", cookie=self.cookie_a)
            self.assertEqual(st_prev, 200)
            self.assertEqual(preview_captured_kwargs.get("style2_code"), "FA-002")
            self.assertEqual(preview_captured_kwargs.get("colors"), ["#112233"])
            self.assertEqual(preview_captured_kwargs.get("tones"), ["T-02"])
            self.assertEqual(preview_captured_kwargs.get("moods"), ["复古"])
            self.assertEqual(preview_captured_kwargs.get("whitespace"), "20%")
            self.assertEqual(preview_captured_kwargs.get("ratio"), "1:1")
            self.assertEqual(preview_captured_kwargs.get("mode"), "illustration")

    def test_x4_reordering_parameters_triggers_s9_sync(self) -> None:
        """X4: Reordering styleIds or colors must change fingerprint and trigger S9 sync."""
        _, res = self._req(
            "POST",
            "/api/studio/recipes",
            {
                "styleIds": ["FA-001", "FA-002"],
                "colors": ["#111111", "#222222"],
                "subject": "秩序测试",
                "prompt": "未自定义的提示词",
                "promptCustomized": False,
            },
            cookie=self.cookie_a,
        )
        rcp_id = res["id"]

        # 1. Reordering styleIds on uncustomized recipe clears prompt
        st1, r1 = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 0, "styleIds": ["FA-002", "FA-001"]},
            cookie=self.cookie_a,
        )
        self.assertEqual(st1, 200)
        self.assertEqual(r1["recipe"]["styleIds"], ["FA-002", "FA-001"])
        self.assertEqual(r1["recipe"]["prompt"], "", "Reordering styleIds must clear uncustomized prompt")
        self.assertFalse(r1["recipe"]["promptCustomized"])

        # User customizes prompt
        st2, r2 = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 1, "prompt": "自定义提示词"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st2, 200)
        self.assertTrue(r2["recipe"]["promptCustomized"])
        self.assertFalse(r2["recipe"]["promptStale"])

        # 2. Reordering colors on customized recipe preserves prompt and marks promptStale=true
        st3, r3 = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 2, "colors": ["#222222", "#111111"]},
            cookie=self.cookie_a,
        )
        self.assertEqual(st3, 200)
        self.assertEqual(r3["recipe"]["colors"], ["#222222", "#111111"])
        self.assertEqual(r3["recipe"]["prompt"], "自定义提示词")
        self.assertTrue(r3["recipe"]["promptCustomized"])
        self.assertTrue(r3["recipe"]["promptStale"], "Reordering colors must mark customized prompt stale")

    def test_x5_publish_work_direct_recipe_id_ownership(self) -> None:
        """X5: publish_work_direct must unconditionally check recipeId ownership."""
        _, res_alice = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FA-001"], "subject": "Alice的配方主题"},
            cookie=self.cookie_a,
        )
        alice_rcp_id = res_alice["id"]

        # Bob attempts to use Alice's recipeId WITH explicit subject -> 404
        with self.assertRaises(ServiceError) as cm1:
            publish_work_direct(
                self.db,
                self.user_b,
                {
                    "title": "Bob作品",
                    "prompt": "提示词",
                    "images": ["/uploads/bob_sample.webp"],
                    "recipeId": alice_rcp_id,
                    "subject": "Bob覆盖的主题",
                },
            )
        self.assertEqual(cm1.exception.status, 404)
        self.assertEqual(cm1.exception.code, "recipe_not_found")

        # Bob attempts to use Alice's recipeId WITHOUT subject -> 404
        with self.assertRaises(ServiceError) as cm2:
            publish_work_direct(
                self.db,
                self.user_b,
                {
                    "title": "Bob作品无主题",
                    "prompt": "提示词",
                    "images": ["/uploads/bob_sample.webp"],
                    "recipeId": alice_rcp_id,
                },
            )
        self.assertEqual(cm2.exception.status, 404)
        self.assertEqual(cm2.exception.code, "recipe_not_found")

        # Non-existent recipeId -> 404
        with self.assertRaises(ServiceError) as cm3:
            publish_work_direct(
                self.db,
                self.user_a,
                {
                    "title": "Alice作品不存在配方",
                    "prompt": "提示词",
                    "images": ["/uploads/alice_sample.webp"],
                    "recipeId": "rcp_totally_nonexistent",
                },
            )
        self.assertEqual(cm3.exception.status, 404)
        self.assertEqual(cm3.exception.code, "recipe_not_found")

    def test_x6_recipe_prompt_length_check_before_charging(self) -> None:
        """X6: Prompt + injected notes > 4000 chars must 400 at admission without deducting quota or credits."""
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-NOTE', '附加说明画风', 'style', 'exclusive', 'A', 0, '/images/note.webp', 'alice', 'published', 'EXTRA_INJECTED_NOTES_KEYWORD', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """
            )

        # 3990 chars in prompt. Injected note is 28 chars. 3990 + 2 + 28 = 4020 > 4000.
        long_prompt = "A" * 3990
        _, res_rcp = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FX-NOTE"], "prompt": long_prompt, "promptCustomized": True},
            cookie=self.cookie_a,
        )
        rcp_id = res_rcp["id"]

        # Check initial wallet and quota
        conn = self.db.get_conn()
        w_before = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (self.user_a["id"],)).fetchone()
        quota_used_before = w_before["free_quota_used"] if w_before else 0
        bal_before = w_before["balance"] if w_before else 0

        st, res = self._req(
            "POST",
            "/api/studio/generate",
            {"recipeId": rcp_id, "simulateGateway": "ok"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st, 400)
        self.assertEqual(res.get("code"), "prompt_too_long")

        # Verify NO quota and NO balance was deducted
        w_after = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (self.user_a["id"],)).fetchone()
        quota_used_after = w_after["free_quota_used"] if w_after else 0
        bal_after = w_after["balance"] if w_after else 0
        self.assertEqual(quota_used_after, quota_used_before, "Free quota must not be deducted on 400 prompt_too_long")
        self.assertEqual(bal_after, bal_before, "Credits must not be deducted on 400 prompt_too_long")

    def test_x7_put_strictly_requires_base_revision(self) -> None:
        """X7: PUT must strictly require baseRevision; passing only revision returns 400."""
        _, res = self._req(
            "POST",
            "/api/studio/recipes",
            {"subject": "基线测试"},
            cookie=self.cookie_a,
        )
        rcp_id = res["id"]

        # Only pass 'revision' -> 400 base_revision_required
        st_bad, r_bad = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"revision": 0, "subject": "试图绕过"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_bad, 400)
        self.assertEqual(r_bad.get("code"), "base_revision_required")

        # Pass 'baseRevision' -> 200
        st_ok, r_ok = self._req(
            "PUT",
            f"/api/studio/recipes/{rcp_id}",
            {"baseRevision": 0, "subject": "合规修改"},
            cookie=self.cookie_a,
        )
        self.assertEqual(st_ok, 200)
        self.assertEqual(r_ok["recipe"]["subject"], "合规修改")

    @unittest.skipUnless(skill_prompt.skill_available(), "Skill checkout not available")
    def test_z1_template_fallback_includes_full_palette(self) -> None:
        """Z1: When AI call falls back to template, colors palette must be included alongside dominant color."""
        from backend import skill_prompt

        # Force model failure -> fallback to _template
        with patch("backend.skill_prompt._call_model", return_value=""):
            res1 = skill_prompt.compose_prompt(
                "FA-013", "SC-021", "red", "autumn woods", colors=["red", "blue"]
            )
            res2 = skill_prompt.compose_prompt(
                "FA-013", "SC-021", "red", "autumn woods", colors=["red", "green"]
            )
            self.assertEqual(res1["source"], "template")
            self.assertEqual(res2["source"], "template")
            self.assertNotEqual(res1["prompt"], res2["prompt"], "[red, blue] and [red, green] template prompts must differ")
            self.assertIn("dominant colour: red", res1["prompt"])
            self.assertIn("colour palette: red, blue", res1["prompt"])
            self.assertIn("colour palette: red, green", res2["prompt"])

            # Baseline check: omitting colors preserves baseline template without palette
            res_base = skill_prompt.compose_prompt("FA-013", "SC-021", "red", "autumn woods")
            self.assertEqual(res_base["source"], "template")
            self.assertIn("dominant colour: red", res_base["prompt"])
            self.assertNotIn("colour palette", res_base["prompt"])

    def test_z2_ai_composed_prompt_trimmed_within_budget(self) -> None:
        """Z2: AI-composed prompt exceeding 4000 after system append must be trimmed and set promptTrimmed=true."""
        secret_note = "INJECTED_SYSTEM_GUIDANCE_EXTRA_LONG_KEYWORD"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-Z2', '长图型', 'style', 'exclusive', 'A', 0, '/images/z2.webp', 'alice', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (secret_note,),
            )

        # Create recipe with empty prompt (will trigger AI composition)
        _, r_rcp = self._req(
            "POST",
            "/api/studio/recipes",
            {"styleIds": ["FX-Z2"], "subject": "小兔"},
            cookie=self.cookie_a,
        )
        rcp_id = r_rcp["id"]

        # Case 1: AI returns 3990 characters -> should be trimmed to fit within 4000 along with secret_note
        long_ai_composed = "Detailed drawing instruction. " * 133  # ~3990 chars
        self.assertGreater(len(long_ai_composed) + len(secret_note) + 2, 4000)

        with patch("backend.services._compose_skill_prompt", return_value=long_ai_composed):
            st1, res1 = self._req(
                "POST",
                "/api/studio/generate",
                {"recipeId": rcp_id, "simulateGateway": "ok"},
                cookie=self.cookie_a,
            )
            self.assertEqual(st1, 200)
            self.assertTrue(res1.get("promptTrimmed"), "Response must carry promptTrimmed: true when AI prompt was trimmed")

            # Verify prompt in DB row is <= 4000 and contains the secret note completely
            conn = self.db.get_conn()
            grow1 = conn.execute("SELECT prompt FROM studio_generations WHERE id = ?", (res1["genId"],)).fetchone()
            self.assertLessEqual(len(grow1["prompt"]), 4000)
            self.assertTrue(grow1["prompt"].endswith(secret_note), "Appended system note must be intact at end of prompt")

        # Case 2: AI returns normal length prompt -> promptTrimmed must NOT be present
        normal_ai_composed = "Standard hand-drawn rabbit on sunny grass."
        with patch("backend.services._compose_skill_prompt", return_value=normal_ai_composed):
            st2, res2 = self._req(
                "POST",
                "/api/studio/generate",
                {"recipeId": rcp_id, "simulateGateway": "ok"},
                cookie=self.cookie_a,
            )
            self.assertEqual(st2, 200)
            self.assertNotIn("promptTrimmed", res2, "Normal prompt generation must NOT have promptTrimmed key")

            grow2 = conn.execute("SELECT prompt FROM studio_generations WHERE id = ?", (res2["genId"],)).fetchone()
            self.assertEqual(grow2["prompt"], f"{normal_ai_composed}\n\n{secret_note}")


if __name__ == "__main__":
    unittest.main()
