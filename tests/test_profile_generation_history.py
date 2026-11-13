"""
Integration tests for Phase 1B: Creator Profile Generation History and Global Rename.
"""
from __future__ import annotations
from tests.postgres_support import open_isolated_postgres

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

from backend.server import HandrawRequestHandler
from backend.services import ServiceError, get_user_public_generations, get_user_public_generation_by_id, record_user_studio_history, get_studio_workspace, register_user
from tests.economy_support import prepare_cloud_generation


WHITELIST_FIELDS = {
    "id",
    "author",
    "createdAt",
    "created_at",
    "images",
    "topic",
    "title",
    "subject",
    "ratio",
    "mode",
    "styles",
    "layouts",
    "imageCount",
    "likes",
    "favorites",
    "liked",
    "favorited",
    "fork",
    "runId",
    "workId",
    "originClient",
    "sourceGenerationId",
}

FORBIDDEN_FIELDS = {
    "prompt",
    "raw_prompt",
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


class ProfileGenerationHistoryTests(unittest.TestCase):
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

        self.creator_alice, _ = register_user(self.db, "alice", "SecretPass123!")
        self.creator_bob, _ = register_user(self.db, "bob", "SecretPass123!")

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

    def _insert_generation(
        self,
        user_id: int,
        gen_id: str,
        topic: str = "手绘猫咪",
        status: str = "success",
        visibility: str = "public",
        engine: str = "recraft",
        created_at: str = "2026-11-01T10:00:00Z",
        deleted_at: str = "",
        images: list[str] | None = None,
        styles: list[str] | None = None,
        layouts: list[str] | None = None,
        prompt: str = "A detailed prompt with secrets",
        project: bool = True,
    ):
        if images is None:
            images = ["https://example.com/cat1.webp"]
        items = [{"imageUrl": u} for u in images]
        tags = []
        for s in (styles or ["FA-001"]):
            tags.append(f"#{s}" if not s.startswith("#") else s)
        for l in (layouts or []):
            tags.append(f"#{l}" if not l.startswith("#") else l)
        recipe_summary = " / ".join(tags)

        u_row = self.db.get_conn().execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        uname = u_row["username"] if u_row else "test_user"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, subject, tab_title, mode, mode_label, recipe_summary,
                    status, visibility, engine, created_at, deleted_at,
                    items_json, prompt, prompt_ready
                ) VALUES (?, ?, ?, ?, '1:1', 'preset', '预设', ?, ?, ?, ?, ?, ?, ?, ?, 1)
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
                    json.dumps(items),
                    prompt,
                ),
            )
            if project and status == "success" and visibility == "public" and engine != "demo" and not deleted_at and images:
                from backend.generation_works import project_generation_to_works
                self.assertEqual(len(project_generation_to_works(tx, gen_id)), 1)

    def test_profile_history_collapses_async_slots_to_one_multi_image_run(self):
        uid = self.creator_alice["id"]
        conn = self.db.get_conn()
        for index in (2, 0, 1):
            gid = f"public_batch_{index}"
            self._insert_generation(
                uid, gid, topic="三张小镇插画",
                created_at=f"2026-11-07T10:0{index}:00Z",
                images=[f"/generated/scene_{index}.webp"], project=False,
            )
            conn.execute(
                "UPDATE studio_generations SET batch_id=?,batch_index=?,batch_total=? WHERE id=?",
                ("logical_batch_profile", index, 3, gid),
            )
        conn.commit()
        from backend.generation_works import project_generation_to_works
        with self.db.transaction():
            self.assertEqual(len(project_generation_to_works(conn, "public_batch_2")), 1)
        result = get_user_public_generations(self.db, "alice", limit=1)
        self.assertEqual(result["total"], 1)
        self.assertFalse(result["hasMore"])
        self.assertEqual(len(result["generations"]), 1)
        run = result["generations"][0]
        self.assertEqual(run["imageCount"], 3)
        self.assertEqual(run["sourceGenerationId"], "public_batch_0")
        self.assertTrue(run["workId"].startswith("work_"))
        self.assertEqual(
            run["images"],
            ["/generated/scene_0.webp", "/generated/scene_1.webp",
             "/generated/scene_2.webp"],
        )
        details = get_user_public_generation_by_id(
            self.db, "alice", run["id"]
        )
        self.assertEqual(details["generation"]["images"], run["images"])

    def test_schema_visibility_and_index(self):
        conn = self.db.get_conn()
        columns = [row[1] for row in conn.execute("SELECT ordinal_position-1 AS cid,column_name AS name FROM information_schema.columns WHERE table_schema='public' AND table_name='studio_generations' ORDER BY ordinal_position").fetchall()]
        self.assertIn("visibility", columns)

        indexes = [row[1] for row in conn.execute("SELECT 0 AS seq,indexname AS name FROM pg_indexes WHERE schemaname='public' AND tablename='studio_generations'").fetchall()]
        self.assertIn("pg_idx_studio_gen_user_vis_created", indexes)

    def test_get_user_public_generations_anonymous_whitelist(self):
        self._insert_generation(
            self.creator_alice["id"],
            "gen_alice_1",
            topic="水彩风景",
            created_at="2026-11-01T10:00:00Z",
            images=["https://example.com/img1.webp", "https://example.com/img2.webp"],
            styles=["FB-002"],
        )

        url = f"http://127.0.0.1:{self.server_port}/api/users/alice/generations"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertTrue(data.get("ok"))
        generations = data.get("generations", [])
        self.assertEqual(len(generations), 1)

        item = generations[0]
        self.assertTrue(item["id"].startswith("run_"))
        self.assertEqual(item["sourceGenerationId"], "gen_alice_1")
        self.assertEqual(item["author"], "alice")
        self.assertEqual(item["topic"], "水彩风景")
        self.assertEqual(item["imageCount"], 2)
        self.assertEqual(len(item["images"]), 2)

        # Ensure no forbidden fields leak
        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, item, f"Forbidden field '{forbidden}' leaked in generation item")

        # Ensure all fields are whitelisted
        for k in item.keys():
            self.assertIn(k, WHITELIST_FIELDS, f"Non-whitelisted field '{k}' found in generation item")

    def test_get_user_public_generations_filter_conditions(self):
        # 1. Success, public -> should be included
        self._insert_generation(self.creator_alice["id"], "gen_ok", status="success", visibility="public")
        # 2. Failed -> excluded
        self._insert_generation(self.creator_alice["id"], "gen_fail", status="failed", visibility="public")
        # 3. Demo engine -> excluded
        self._insert_generation(self.creator_alice["id"], "gen_demo", status="success", engine="demo")
        # 4. Deleted -> excluded
        self._insert_generation(
            self.creator_alice["id"], "gen_del", status="success", deleted_at="2026-11-01T12:00:00Z"
        )
        # 5. Private -> excluded
        self._insert_generation(self.creator_alice["id"], "gen_priv", status="success", visibility="private")
        # 6. Empty images -> excluded
        self._insert_generation(self.creator_alice["id"], "gen_noimg", status="success", images=[])

        url = f"http://127.0.0.1:{self.server_port}/api/users/alice/generations"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        generations = data.get("generations", [])
        ids = [g["id"] for g in generations]
        self.assertEqual(len(ids), 1)
        self.assertEqual(generations[0]["sourceGenerationId"], "gen_ok")

    def test_cursor_pagination_and_sorting(self):
        # Insert 15 generations with distinct timestamps
        for i in range(15):
            ts = f"2026-11-01T10:{i:02d}:00Z"
            self._insert_generation(
                self.creator_bob["id"],
                f"gen_bob_{i:02d}",
                topic=f"作品{i:02d}",
                created_at=ts,
            )

        # Page 1: limit 6 -> should get gen_bob_14 down to gen_bob_09 (reverse chronological)
        url1 = f"http://127.0.0.1:{self.server_port}/api/users/bob/generations?limit=6"
        with urllib.request.urlopen(url1) as resp:
            data1 = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(len(data1["generations"]), 6)
        self.assertTrue(data1["hasMore"])
        self.assertEqual(data1["generations"][0]["sourceGenerationId"], "gen_bob_14")
        self.assertEqual(data1["generations"][-1]["sourceGenerationId"], "gen_bob_09")
        cursor1 = data1["nextCursor"]
        self.assertTrue(cursor1)

        # Page 2: with cursor
        url2 = f"http://127.0.0.1:{self.server_port}/api/users/bob/generations?limit=6&cursor={cursor1}"
        with urllib.request.urlopen(url2) as resp:
            data2 = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(len(data2["generations"]), 6)
        self.assertTrue(data2["hasMore"])
        self.assertEqual(data2["generations"][0]["sourceGenerationId"], "gen_bob_08")
        self.assertEqual(data2["generations"][-1]["sourceGenerationId"], "gen_bob_03")

        # Page 3: with cursor
        cursor2 = data2["nextCursor"]
        url3 = f"http://127.0.0.1:{self.server_port}/api/users/bob/generations?limit=6&cursor={cursor2}"
        with urllib.request.urlopen(url3) as resp:
            data3 = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(len(data3["generations"]), 3)
        self.assertFalse(data3["hasMore"])
        self.assertEqual(data3["generations"][0]["sourceGenerationId"], "gen_bob_02")
        self.assertEqual(data3["generations"][-1]["sourceGenerationId"], "gen_bob_00")

    def test_get_user_public_generation_by_id(self):
        self._insert_generation(
            self.creator_alice["id"],
            "gen_alice_detail",
            topic="特写古风插画",
            created_at="2026-11-01T15:00:00Z",
            images=["https://example.com/detail.webp"],
            styles=["FA-001", "FB-002"],
        )

        url = f"http://127.0.0.1:{self.server_port}/api/users/alice/generations/gen_alice_detail"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertTrue(data.get("ok"))
        g = data.get("generation", {})
        self.assertTrue(g["id"].startswith("run_"))
        self.assertEqual(g["sourceGenerationId"], "gen_alice_detail")
        self.assertEqual(g["author"], "alice")
        self.assertEqual(g["topic"], "特写古风插画")
        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, g)

        # 404 for wrong user or non-existent
        url_wrong_user = f"http://127.0.0.1:{self.server_port}/api/users/bob/generations/gen_alice_detail"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url_wrong_user)
        self.assertEqual(ctx.exception.code, 404)

    def test_reject_client_visibility_setting(self):
        # 1. In record_user_studio_history
        with self.assertRaises(ServiceError) as ctx:
            record_user_studio_history(
                self.db,
                self.creator_alice,
                {"id": "gen_test_vis", "visibility": "private", "status": "success"},
            )
        self.assertEqual(ctx.exception.code, "visibility_not_allowed")

        with self.assertRaises(ServiceError) as ctx:
            record_user_studio_history(
                self.db,
                self.creator_alice,
                {"id": "gen_test_vis2", "visibility": "public", "status": "success"},
            )
        self.assertEqual(ctx.exception.code, "visibility_not_allowed")

        # 2. In prepare_cloud_generation
        with self.assertRaises(ServiceError) as ctx:
            prepare_cloud_generation(
                self.db,
                self.creator_alice,
                {"visibility": "private", "topic": "test", "items": [{"imageUrl": "https://example.com/1.png"}]},
            )
        self.assertEqual(ctx.exception.code, "visibility_not_allowed")

    def test_creation_source_is_persisted_for_history_and_cloud_generations(self):
        # Creation entry point is independent of output mode, image ratio or prompt.
        for source in ("quick", "batch", "article", "canvas"):
            record_user_studio_history(self.db, self.creator_alice, {
                "id": f"hist_origin_{source}",
                "tabTitle": "表单生图",
                "mode": "graphic-text",
                "kind": "single",
                "creationSource": source,
                "items": [{"imageUrl": f"/image_{source}.webp"}],
            })
        workspace = get_studio_workspace(self.db, self.creator_alice)
        origins = {x["id"]: x.get("creationSource") for x in workspace["history"]}
        for source in ("quick", "batch", "article", "canvas"):
            self.assertEqual(origins[f"hist_origin_{source}"], source)

        # Cloud requests must persist the source in their own metadata as well.
        result = prepare_cloud_generation(
            self.db, self.creator_alice,
            {"prompt": "手绘树木", "ratio": "3:4", "creationSource": "batch", "confirmCost": True},
        )
        gen_id = result["genId"]
        row = self.db.get_conn().execute(
            "SELECT system_append_json FROM studio_generations WHERE id = ?", (gen_id,)
        ).fetchone()
        self.assertEqual(json.loads(row["system_append_json"])["creationSource"], "batch")
        workspace = get_studio_workspace(self.db, self.creator_alice)
        entries = [x for x in workspace["history"] if x["id"] == gen_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["creationSource"], "batch")

    def test_global_rename_no_lingering_shice_zuopin(self):
        root = Path(__file__).resolve().parent.parent
        files_to_check = [
            root / "backend" / "server.py",
            root / "backend" / "curation.py",
            root / "demo" / "assets" / "shared.js",
            root / "demo" / "assets" / "main-app.js",
            root / "demo" / "assets" / "forum-app.js",
            root / "demo" / "assets" / "studio-app.js",
        ]
        for f in files_to_check:
            self.assertTrue(f.exists(), f"File {f} does not exist")
            content = f.read_text(encoding="utf-8")
            self.assertNotIn("实测作品", content, f"Found lingering '实测作品' in {f.name}")

    def test_legacy_history_route_and_notification_redirects(self):
        root = Path(__file__).resolve().parent.parent

        # 1. Legacy studio history stays in studio; profile history links resolve to works.
        studio_app = (root / "demo" / "assets" / "studio-app.js").read_text(encoding="utf-8")
        main_app = (root / "demo" / "assets" / "main-app.js").read_text(encoding="utf-8")
        self.assertIn('viewParam === "history"', studio_app)
        self.assertIn('CS.stageView = "history"', studio_app)
        self.assertIn('function returnFromHistoryPage()', studio_app)
        self.assertNotIn('ptab: "generations"', studio_app)
        self.assertIn('reqTab === "generations"', main_app)
        self.assertNotIn('data-ptab="generations"', main_app)

        # 2. Notification links retain their old profile URL for compatibility.
        account_tools = (root / "demo" / "assets" / "account-tools.js").read_text(encoding="utf-8")
        self.assertIn('item.target_type==="generation"', account_tools)
        self.assertIn('ptab: "generations"', account_tools)
        self.assertNotIn('{view:"history"}', account_tools)

        # 3. The profile router canonicalizes old notification links to works.
        messaging = (root / "demo" / "assets" / "messaging.js").read_text(encoding="utf-8")
        self.assertIn('n.target_type === "generation"', messaging)
        self.assertIn('ptab: "generations"', messaging)


if __name__ == "__main__":
    unittest.main()
