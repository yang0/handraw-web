"""
Comprehensive tests for Issue #40: Social actions (Collect, Like, Fork) for generation history.
"""
from __future__ import annotations
from tests.postgres_support import open_isolated_postgres

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from backend.server import HandrawRequestHandler
from backend.services import (
    register_user,
    login_user,
    build_boot_payload,
    toggle_user_like,
    toggle_user_collection,
    get_user_collected_generations,
    fork_generation_recipe,
    prepare_cloud_generation,
    ServiceError,
)


class GenerationSocialActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
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

        self.alice, _ = register_user(self.db, "alice", "SecretPass123!")
        self.bob, _ = register_user(self.db, "bob", "SecretPass123!")

        # Log in alice and bob to get session tokens
        self.alice, self.alice_token = login_user(self.db, "alice", "SecretPass123!")
        self.bob, self.bob_token = login_user(self.db, "bob", "SecretPass123!")

        from http.server import ThreadingHTTPServer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.server.channel_role = "main"
        self.server.db = self.db
        self.server.allow_demo_routes = True
        self.server_port = self.server.server_address[1]
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self) -> None:
        try:
            self.server.shutdown()
            self.server.server_close()
            self.server_thread.join(timeout=5)
            self.db.close_thread_conn()
            self.db.close()
            self.env.stop()
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _req(
        self,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str = "",
        token: str = "",
    ) -> tuple[int, dict]:
        url = f"http://127.0.0.1:{self.server_port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if cookie:
            req.add_header("Cookie", cookie)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                res_data = json.loads(resp.read().decode("utf-8"))
                return status, res_data
        except urllib.error.HTTPError as e:
            err_data = json.loads(e.read().decode("utf-8"))
            return e.code, err_data

    def _insert_generation(
        self,
        user_id: int,
        gen_id: str,
        topic: str = "手绘猫咪",
        status: str = "success",
        visibility: str = "public",
        engine: str = "live",
        created_at: str = "2026-11-01T10:00:00Z",
        deleted_at: str = "",
        images: list[dict] | None = None,
        styles: list[str] | None = None,
        layouts: list[str] | None = None,
        prompt: str = "A top-secret internal prompt",
        fork_generation_id: str = "",
        fork_item_id: str = "",
    ):
        if images is None:
            images = [{"id": f"{gen_id}_0", "imageUrl": "https://example.com/cat1.webp"}]
        tags = []
        for s in (styles or ["FA-001"]):
            tags.append(f"#{s}" if not s.startswith("#") else s)
        for l in (layouts or []):
            tags.append(f"#{l}" if not l.startswith("#") else l)
        recipe_summary = " / ".join(tags)

        u_row = self.db.get_conn().execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        uname = u_row["username"] if u_row else "test_user"
        snap = {"style1": (styles or ["FA-001"])[0], "layout": (layouts or ["LAY-001"])[0]}

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, subject, tab_title, mode, mode_label, recipe_summary,
                    status, visibility, engine, created_at, deleted_at,
                    items_json, prompt, prompt_ready, system_append_json,
                    fork_generation_id, fork_item_id
                ) VALUES (?, ?, ?, ?, '3:4', 'preset', '预设', ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    gen_id,
                    user_id,
                    uname,
                    topic,
                    recipe_summary,
                    status,
                    visibility,
                    engine,
                    created_at,
                    deleted_at,
                    json.dumps(images),
                    prompt,
                    json.dumps({"recipeSnapshot": snap}),
                    fork_generation_id,
                    fork_item_id,
                ),
            )
            if status == "success" and visibility == "public" and engine != "demo" and not deleted_at and images:
                from backend.generation_works import project_generation_to_works
                self.assertEqual(len(project_generation_to_works(tx, gen_id)), 1)

    def test_migration_and_no_extra_count_columns(self):
        """Verify schema migration 73 added fork columns and NO count columns were added to studio_generations."""
        conn = self.db.get_conn()
        columns = [row[1] for row in conn.execute("SELECT ordinal_position-1 AS cid,column_name AS name FROM information_schema.columns WHERE table_schema='public' AND table_name='studio_generations' ORDER BY ordinal_position").fetchall()]
        self.assertIn("fork_generation_id", columns)
        self.assertIn("fork_item_id", columns)
        # Ensure NO count columns on studio_generations
        self.assertNotIn("likes_count", columns)
        self.assertNotIn("favorites_count", columns)
        self.assertNotIn("like_count", columns)
        self.assertNotIn("favorite_count", columns)

    def test_self_like_forbidden_and_self_collect_allowed(self):
        """Verify self-like is rejected with 403, and self-collect is permitted with 200."""
        self._insert_generation(self.alice["id"], "gen_alice_self", topic="我的自拍猫咪")
        alice_cookie = f"handraw_sid={self.alice_token}"

        # 1. Alice likes her own generation -> 403
        status, res = self._req(
            "/api/interactions/like",
            method="POST",
            body={"targetType": "generation", "id": "gen_alice_self"},
            cookie=alice_cookie,
        )
        self.assertEqual(status, 403)
        self.assertEqual(res.get("code"), "self_like_forbidden")

        # 2. Alice collects her own generation -> 200
        status, res = self._req(
            "/api/collections/toggle",
            method="POST",
            body={"bucket": "generations", "id": "gen_alice_self", "title": "我的自拍猫咪"},
            cookie=alice_cookie,
        )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("collected"))
        self.assertEqual(res.get("rewarded", 0), 0)  # No credit reward for generation collect

    def test_social_actions_two_accounts_and_idempotency(self):
        """Test Bob liking, unliking, collecting, uncollecting Alice's generation with idempotent actions."""
        self._insert_generation(self.alice["id"], "gen_alice_social", topic="秋天海报")
        bob_cookie = f"handraw_sid={self.bob_token}"

        # 1. Bob likes gen_alice_social (action: "set")
        status, res = self._req(
            "/api/interactions/like",
            method="POST",
            body={"targetType": "generation", "id": "gen_alice_social", "action": "set"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("liked"))
        self.assertEqual(res.get("likes"), 1)

        # 2. Idempotent repeat: Bob likes again with action: "set" -> still liked, count stays 1
        status, res = self._req(
            "/api/interactions/like",
            method="POST",
            body={"targetType": "generation", "id": "gen_alice_social", "action": "set"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("liked"))
        self.assertEqual(res.get("likes"), 1)

        # Verify DB interactions count is strictly 1
        conn = self.db.get_conn()
        work_id = conn.execute(
            """SELECT w.id FROM works w JOIN generation_runs r ON r.id=w.run_id
               WHERE r.external_run_id='gen_alice_social'"""
        ).fetchone()[0]
        cnt = conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE target_type='like_work' AND target_id=?",
            (work_id,),
        ).fetchone()[0]
        self.assertEqual(cnt, 1)

        # 3. Bob collects gen_alice_social (action: "set")
        status, res = self._req(
            "/api/collections/toggle",
            method="POST",
            body={"bucket": "generations", "id": "gen_alice_social", "action": "set"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("collected"))
        self.assertEqual(res.get("favorites"), 1)

        # 4. Idempotent repeat: Bob collects again with action: "set" -> still collected, count stays 1
        status, res = self._req(
            "/api/collections/toggle",
            method="POST",
            body={"bucket": "generations", "id": "gen_alice_social", "action": "set"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("collected"))
        self.assertEqual(res.get("favorites"), 1)

        # 5. Bob queries collections endpoint
        status, res = self._req(
            "/api/collections/generations",
            method="GET",
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        gens = res.get("generations", [])
        self.assertEqual(len(gens), 1)
        self.assertTrue(gens[0]["id"].startswith("run_"))
        self.assertEqual(gens[0]["workId"], work_id)
        self.assertEqual(gens[0]["likes"], 1)
        self.assertEqual(gens[0]["favorites"], 1)
        self.assertTrue(gens[0]["liked"])
        self.assertTrue(gens[0]["favorited"])

        # 6. Bob unlikes (action: "unset")
        status, res = self._req(
            "/api/interactions/like",
            method="POST",
            body={"targetType": "generation", "id": "gen_alice_social", "action": "unset"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertFalse(res.get("liked"))
        self.assertEqual(res.get("likes"), 0)

        # Repeat unset -> still 0
        status, res = self._req(
            "/api/interactions/like",
            method="POST",
            body={"targetType": "generation", "id": "gen_alice_social", "action": "unset"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertFalse(res.get("liked"))
        self.assertEqual(res.get("likes"), 0)

        # 7. Bob uncollects (action: "unset")
        status, res = self._req(
            "/api/collections/toggle",
            method="POST",
            body={"bucket": "generations", "id": "gen_alice_social", "action": "unset"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertFalse(res.get("collected"))
        self.assertEqual(res.get("favorites"), 0)

        # Repeat unset -> still 0
        status, res = self._req(
            "/api/collections/toggle",
            method="POST",
            body={"bucket": "generations", "id": "gen_alice_social", "action": "unset"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertFalse(res.get("collected"))
        self.assertEqual(res.get("favorites"), 0)

        # Collections list now empty
        status, res = self._req(
            "/api/collections/generations",
            method="GET",
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(res.get("generations", [])), 0)

    def test_fork_recipe_draft_and_no_definition_leak(self):
        """Test POST /api/studio/generations/{id}/fork returns clean draft without prompts or secrets."""
        self._insert_generation(
            self.alice["id"],
            "gen_alice_fork",
            topic="古风竹林",
            styles=["FA-001"],
            layouts=["LAY-001"],
            prompt="TOP SECRET SYSTEM PROMPT MUST NOT LEAK",
            images=[
                {"id": "item_1", "imageUrl": "https://example.com/bamboo1.webp"},
                {"id": "item_2", "imageUrl": "https://example.com/bamboo2.webp", "layoutId": "LAY-002"},
            ],
        )
        bob_cookie = f"handraw_sid={self.bob_token}"

        # 1. Bob forks gen_alice_fork item 1
        status, res = self._req(
            "/api/studio/generations/gen_alice_fork/fork",
            method="POST",
            body={"itemId": "item_1"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        draft = res.get("draft", {})
        source = res.get("source", {})

        # Verify draft contents
        self.assertEqual(draft.get("styleIds"), ["FA-001"])
        self.assertEqual(draft.get("layoutId"), "LAY-001")
        self.assertEqual(draft.get("subject"), "古风竹林")
        self.assertEqual(draft.get("ratio"), "3:4")
        self.assertEqual(draft.get("prompt"), "")  # Must never leak prompt

        # Verify no secret definition or internal prompt in response JSON
        res_str = json.dumps(res)
        self.assertNotIn("TOP SECRET SYSTEM PROMPT", res_str)
        self.assertNotIn("secret", res_str.lower())
        self.assertNotIn("blackbox", res_str.lower())

        # Verify source info
        self.assertEqual(source.get("generationId"), "gen_alice_fork")
        self.assertEqual(source.get("itemId"), "item_1")
        self.assertEqual(source.get("author"), "alice")

        # 2. Bob forks gen_alice_fork item 2 with layout LAY-002
        status, res2 = self._req(
            "/api/studio/generations/gen_alice_fork/fork",
            method="POST",
            body={"itemId": "item_2"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(res2["draft"]["layoutId"], "LAY-002")
        self.assertEqual(res2["source"]["itemId"], "item_2")

    def test_fork_unrestorable_recipe_rejected(self):
        """Test records without valid recipe parameters return 400 cannot_fork."""
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, subject, status, visibility, engine, created_at,
                    items_json, prompt, prompt_ready
                ) VALUES (?, ?, 'alice', '纯自由图', 'success', 'public', 'live', '2026-11-01T10:00:00Z', ?, 'prompt', 1)
                """,
                ("gen_empty_recipe", self.alice["id"], json.dumps([{"imageUrl": "https://example.com/free.webp"}])),
            )
        bob_cookie = f"handraw_sid={self.bob_token}"
        status, res = self._req(
            "/api/studio/generations/gen_empty_recipe/fork",
            method="POST",
            body={},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 400)
        self.assertEqual(res.get("code"), "cannot_fork")

    def test_private_and_deleted_generation_returns_404_to_others(self):
        """Verify private and deleted generations return 404 to others across detail, like, collect, and fork."""
        # Insert private generation for alice
        self._insert_generation(self.alice["id"], "gen_alice_priv", topic="私人生图", visibility="private")
        # Insert deleted generation for alice
        self._insert_generation(self.alice["id"], "gen_alice_del", topic="已删生图", deleted_at="2026-11-01T11:00:00Z")

        bob_cookie = f"handraw_sid={self.bob_token}"

        # 1. Detail endpoint returns 404
        status, _ = self._req("/api/users/alice/generations/gen_alice_priv", method="GET", cookie=bob_cookie)
        self.assertEqual(status, 404)
        status, _ = self._req("/api/users/alice/generations/gen_alice_del", method="GET", cookie=bob_cookie)
        self.assertEqual(status, 404)

        # 2. Like endpoint returns 404
        status, _ = self._req(
            "/api/interactions/like",
            method="POST",
            body={"targetType": "generation", "id": "gen_alice_priv"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 404)
        status, _ = self._req(
            "/api/interactions/like",
            method="POST",
            body={"targetType": "generation", "id": "gen_alice_del"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 404)

        # 3. Collect endpoint returns 404
        status, _ = self._req(
            "/api/collections/toggle",
            method="POST",
            body={"bucket": "generations", "id": "gen_alice_priv"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 404)
        status, _ = self._req(
            "/api/collections/toggle",
            method="POST",
            body={"bucket": "generations", "id": "gen_alice_del"},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 404)

        # 4. Fork endpoint returns 404
        status, _ = self._req(
            "/api/studio/generations/gen_alice_priv/fork",
            method="POST",
            body={},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 404)
        status, _ = self._req(
            "/api/studio/generations/gen_alice_del/fork",
            method="POST",
            body={},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 404)

    def test_generation_attribution_and_privacy_masking(self):
        """Verify generation attribution is recorded and hidden when source becomes private or deleted."""
        # 1. Alice creates public generation
        self._insert_generation(self.alice["id"], "gen_alice_src", topic="源生图")

        # 2. Bob generates with fork attribution
        with self.db.transaction() as tx:
            # Grant bob wallet balance so generation passes
            tx.execute("UPDATE wallets SET balance = 50 WHERE user_id = ?", (self.bob["id"],))

        bob_cookie = f"handraw_sid={self.bob_token}"
        status, res = self._req(
            "/api/studio/generate",
            method="POST",
            body={
                "prompt": "复刻源生图",
                "style1": "FA-001",
                "forkGenerationId": "gen_alice_src",
                "forkItemId": "gen_alice_src_0",
                "simulateGateway": "ok",
            },
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        bob_gen_id = res.get("genId")
        self.assertTrue(bob_gen_id)

        # Update bob's generation status to success and add image so it shows in public history
        with self.db.transaction() as tx:
            tx.execute(
                """
                UPDATE studio_generations
                SET status = 'success', items_json = ?
                WHERE id = ?
                """,
                (json.dumps([{"imageUrl": "https://example.com/bob_gen.webp"}]), bob_gen_id),
            )

        # 3. Query Bob's public generation history
        status, res = self._req(f"/api/users/bob/generations/{bob_gen_id}", method="GET")
        self.assertEqual(status, 200)
        gen_data = res.get("generation", {})
        self.assertIn("fork", gen_data)
        self.assertTrue(gen_data["fork"]["visible"])
        self.assertEqual(gen_data["fork"]["author"], "alice")
        self.assertEqual(gen_data["fork"]["generationId"], "gen_alice_src")

        # 4. Now Alice makes her source generation private
        with self.db.transaction() as tx:
            tx.execute("UPDATE studio_generations SET visibility = 'private' WHERE id = 'gen_alice_src'")

        # Query Bob's public generation history again -> fork details hidden
        status, res = self._req(f"/api/users/bob/generations/{bob_gen_id}", method="GET")
        self.assertEqual(status, 200)
        gen_data = res.get("generation", {})
        self.assertIn("fork", gen_data)
        self.assertFalse(gen_data["fork"]["visible"])
        self.assertNotIn("author", gen_data["fork"])

        # 5. Alice deletes her generation -> still hidden
        with self.db.transaction() as tx:
            tx.execute("UPDATE studio_generations SET visibility = 'public', deleted_at = '2026-11-01T12:00:00Z' WHERE id = 'gen_alice_src'")
        status, res = self._req(f"/api/users/bob/generations/{bob_gen_id}", method="GET")
        self.assertEqual(status, 200)
        self.assertFalse(res.get("generation", {}).get("fork", {}).get("visible"))

    def test_boot_payload_collections_and_liked_ids(self):
        """Canonical V3 generated works share the works bucket and like IDs."""
        self._insert_generation(self.alice["id"], "gen_alice_boot", topic="引导生图")
        bob_cookie = f"handraw_sid={self.bob_token}"

        # Bob likes and collects
        self._req(
            "/api/interactions/like",
            method="POST",
            body={"targetType": "generation", "id": "gen_alice_boot"},
            cookie=bob_cookie,
        )
        self._req(
            "/api/collections/toggle",
            method="POST",
            body={"bucket": "generations", "id": "gen_alice_boot"},
            cookie=bob_cookie,
        )

        status, boot = self._req("/api/boot", method="GET", cookie=bob_cookie)
        self.assertEqual(status, 200)
        cols = boot.get("collections", {})
        self.assertIn("works", cols)
        w = self.db.get_conn().execute(
            """SELECT w.id FROM works w JOIN generation_runs r ON r.id=w.run_id
               WHERE r.external_run_id='gen_alice_boot'"""
        ).fetchone()[0]
        self.assertIn(w, cols["works"])

        liked_ids = boot.get("likedIds", [])
        self.assertTrue(
            any(w in str(x) for x in liked_ids),
            f"Canonical work like missing from {liked_ids}",
        )

    def test_generation_history_order_preserved(self):
        """Verify generation history ordering remains created_at DESC, id DESC."""
        self._insert_generation(self.alice["id"], "gen_1", created_at="2026-11-01T10:00:00Z")
        self._insert_generation(self.alice["id"], "gen_2", created_at="2026-11-01T11:00:00Z")
        self._insert_generation(self.alice["id"], "gen_3", created_at="2026-11-01T12:00:00Z")

        # Bob likes gen_1 (oldest)
        bob_cookie = f"handraw_sid={self.bob_token}"
        self._req(
            "/api/interactions/like",
            method="POST",
            body={"targetType": "generation", "id": "gen_1"},
            cookie=bob_cookie,
        )

        # Query Alice's generations: order must still be gen_3, gen_2, gen_1 (time desc)
        status, res = self._req("/api/users/alice/generations", method="GET")
        self.assertEqual(status, 200)
        ids = [g["sourceGenerationId"] for g in res.get("generations", [])]
        self.assertEqual(ids, ["gen_3", "gen_2", "gen_1"])

    def test_fork_locked_paid_resource_requires_unlock_on_generation(self):
        """Verify generating from a forked draft with locked paid resource fails with 403 asset_locked."""
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO catalog_assets (\n                    code, name, kind, unlock_cost, status, source_type, image_url,\n                    published_at_ms, created_at, updated_at\n                ) VALUES (\n                    'FA-999', '付费画风', 'style', 30, 'published', 'community', 'https://example.com/asset.webp',\n                    1700000000000, '2026-11-01T10:00:00Z', '2026-11-01T10:00:00Z'\n                ) ON CONFLICT (code) DO UPDATE SET name = excluded.name, kind = excluded.kind, unlock_cost = excluded.unlock_cost, status = excluded.status, source_type = excluded.source_type, image_url = excluded.image_url, published_at_ms = excluded.published_at_ms, created_at = excluded.created_at, updated_at = excluded.updated_at"
            )
        self._insert_generation(
            self.alice["id"],
            "gen_alice_paid",
            topic="付费画风生图",
            styles=["FA-999"],
            layouts=["LAY-001"],
        )
        bob_cookie = f"handraw_sid={self.bob_token}"

        # 1. Bob forks recipe draft successfully (read-only draft preparation)
        status, res = self._req(
            "/api/studio/generations/gen_alice_paid/fork",
            method="POST",
            body={},
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(res["draft"]["styleIds"], ["FA-999"])

        # 2. Bob attempts to generate without unlocking FA-999 -> 403 asset_locked
        status, gen_res = self._req(
            "/api/studio/generate",
            method="POST",
            body={
                "prompt": "复刻付费画风生图",
                "style1": "FA-999",
                "forkGenerationId": "gen_alice_paid",
                "simulateGateway": "ok",
            },
            cookie=bob_cookie,
        )
        self.assertEqual(status, 403)
        self.assertEqual(gen_res.get("code"), "asset_locked")

    def test_generation_idempotency_retry_no_double_spend(self):
        """Verify repeat generation request with same requestId returns existing reservation without recharging."""
        self._insert_generation(self.alice["id"], "gen_alice_base", topic="基础源图")
        with self.db.transaction() as tx:
            # Set bob wallet to 50 balance, 0 free quota
            tx.execute("UPDATE wallets SET balance = 50, free_quota_used = 3, free_quota_date = '2026-11-01' WHERE user_id = ?", (self.bob["id"],))

        bob_cookie = f"handraw_sid={self.bob_token}"
        req_id = "test_req_unique_999"

        # 1. First submission
        status, res1 = self._req(
            "/api/studio/generate",
            method="POST",
            body={
                "prompt": "幂等生图测试",
                "style1": "FA-001",
                "forkGenerationId": "gen_alice_base",
                "requestId": req_id,
                "simulateGateway": "ok",
            },
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        gen_id1 = res1.get("genId")
        credits1 = res1.get("credits")

        # 2. Second submission with identical requestId
        status, res2 = self._req(
            "/api/studio/generate",
            method="POST",
            body={
                "prompt": "幂等生图测试",
                "style1": "FA-001",
                "forkGenerationId": "gen_alice_base",
                "requestId": req_id,
                "simulateGateway": "ok",
            },
            cookie=bob_cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(res2.get("genId"), gen_id1)
        self.assertTrue(res2.get("idempotent"))
        self.assertEqual(res2.get("credits"), credits1)

        # Verify only 1 row was inserted in studio_generations
        conn = self.db.get_conn()
        count = conn.execute("SELECT COUNT(*) FROM studio_generations WHERE request_id = ?", (req_id,)).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
