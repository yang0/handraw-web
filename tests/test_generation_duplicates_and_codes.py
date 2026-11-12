"""
Tests for Issue #39:
1. De-duplicating studio generation history (idempotent cleanup of hist_/gen_ pairs).
2. Idempotent write via requestId in record_user_studio_history.
3. Ensuring styles & layouts adhere strictly to [{code, name}] format with valid code regex.
4. Rejection of malformed shapes on new writes.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend.db import utc_now_iso
from backend.services import (
    ServiceError,
    get_user_public_generations,
    get_user_public_generation_by_id,
    record_user_studio_history,
    serialize_public_generation_history,
    register_user,
)
from tests.postgres_maintenance import deduplicate_generation_history

CODE_RE = re.compile(r"^(?:USR-)?[A-Z]{1,4}-[A-Z0-9]+$")


class GenerationDuplicatesAndCodesTests(unittest.TestCase):
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

        conn = self.db.get_conn()
        # Clean any seeded generations for test users to have clean baselines
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM studio_generations")
        self.user_su = dict(conn.execute("SELECT * FROM users WHERE username = 'su_editorial'").fetchone())
        self.user_momo = dict(conn.execute("SELECT * FROM users WHERE username = 'momo_design'").fetchone())

    def tearDown(self) -> None:
        try:
            self.db.close()
            self.env.stop()
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_deduplicate_identical_image_sets_between_hist_and_gen_pairs(self) -> None:
        """Reproduce the 4 duplicate pairs reported by users and verify only gen_ rows remain."""
        uid = int(self.user_su["id"])
        now = utc_now_iso()

        pairs = [
            ("hist_mvyh2i1e_332", "gen_1793576355465_4a0f68", ["/generated/44fc-95f6-1.png"], "水墨荷塘", "#FA-001"),
            ("hist_mvyga05q_328", "gen_1793575032179_540c33", ["/generated/4d1e-b98f-2.png"], "秋日山景", "#FA-002 #SC-001"),
            ("hist_mvyg8ekn_326", "gen_1793574938881_315ab1", ["/generated/454f-94b5-3.png"], "城市速写", "#FA-003"),
            ("hist_mvxek8hr_326", "gen_1793511683689_813d65", ["/generated/477e-b07f-4.png"], "复古海报", "#FA-004"),
        ]

        with self.db.transaction() as tx:
            for hist_id, gen_id, urls, subj, recipe in pairs:
                # 1. Insert hist_ record (engine=sample as written by old studioApiPost)
                tx.execute(
                    """
                    INSERT INTO studio_generations (
                        id, user_id, username, subject, recipe_summary, items_json, engine, status, visibility, created_at
                    ) VALUES (?, ?, 'su_editorial', ?, ?, ?, 'sample', 'success', 'public', ?)
                    """,
                    (hist_id, uid, subj, recipe, json.dumps([{"imageUrl": u} for u in urls]), now),
                )
                # 2. Insert gen_ record (engine=live, cloud generation, missing subject initially)
                tx.execute(
                    """
                    INSERT INTO studio_generations (
                        id, user_id, username, subject, recipe_summary, items_json, engine, status, visibility, created_at
                    ) VALUES (?, ?, 'su_editorial', '', '', ?, 'live', 'success', 'public', ?)
                    """,
                    (gen_id, uid, json.dumps(urls), now),
                )

        conn = self.db.get_conn()
        total_before = conn.execute("SELECT COUNT(*) FROM studio_generations WHERE user_id = ? AND COALESCE(deleted_at, '') = ''", (uid,)).fetchone()[0]
        self.assertEqual(total_before, 8)

        # Run deduplication
        with self.db.transaction() as tx:
            deleted_count = deduplicate_generation_history(tx, user_id=uid)

        self.assertEqual(deleted_count, 4)

        # Verify only the 4 gen_ rows are active
        active_rows = conn.execute(
            "SELECT id, subject, recipe_summary, deleted_at FROM studio_generations WHERE user_id = ? AND COALESCE(deleted_at, '') = '' ORDER BY id",
            (uid,),
        ).fetchall()
        self.assertEqual(len(active_rows), 4)

        for r in active_rows:
            self.assertTrue(r["id"].startswith("gen_"), f"Kept row should start with gen_, got {r['id']}")
            # Verify subject and recipe_summary were backfilled from hist_ row
            self.assertTrue(bool(r["subject"]), f"Subject should be backfilled for {r['id']}")
            self.assertTrue(bool(r["recipe_summary"]), f"Recipe summary should be backfilled for {r['id']}")

        # Verify soft delete: the 4 hist_ rows have non-empty deleted_at
        deleted_hist = conn.execute(
            "SELECT id, deleted_at FROM studio_generations WHERE user_id = ? AND id LIKE 'hist_%'",
            (uid,),
        ).fetchall()
        self.assertEqual(len(deleted_hist), 4)
        for r in deleted_hist:
            self.assertTrue(bool(r["deleted_at"]), f"hist row {r['id']} should have deleted_at set")

        # Verify idempotency: re-running does nothing
        with self.db.transaction() as tx:
            deleted_second = deduplicate_generation_history(tx, user_id=uid)
        self.assertEqual(deleted_second, 0)

    def test_deduplicate_by_request_id(self) -> None:
        """When legacy rows share identical request_id, keep gen_ row and soft delete hist_ row."""
        uid = int(self.user_momo["id"])
        now = utc_now_iso()
        req_id = "req_batch_sync_001"

        with self.db.transaction() as tx:
            # Temporarily drop partial index to simulate pre-index duplicate rows
            tx.execute("DROP INDEX IF EXISTS pg_idx_studio_gen_user_request")
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, request_id, items_json, engine, status, visibility, created_at
                ) VALUES ('hist_dup_req_1', ?, 'momo_design', ?, '["/img/1.png"]', 'sample', 'success', 'public', ?)
                """,
                (uid, req_id, now),
            )
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, request_id, items_json, engine, status, visibility, created_at
                ) VALUES ('gen_dup_req_1', ?, 'momo_design', ?, '["/img/1.png"]', 'live', 'success', 'public', ?)
                """,
                (uid, req_id, now),
            )

        with self.db.transaction() as tx:
            del_cnt = deduplicate_generation_history(tx, user_id=uid)

        self.assertEqual(del_cnt, 1)

        conn = self.db.get_conn()
        active = conn.execute(
            "SELECT id FROM studio_generations WHERE user_id = ? AND request_id = ? AND COALESCE(deleted_at, '') = ''",
            (uid, req_id),
        ).fetchall()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], "gen_dup_req_1")

        # Re-create unique index cleanly now that duplicates are resolved
        with self.db.transaction() as tx:
            tx.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS pg_idx_studio_gen_user_request
                    ON studio_generations(user_id, request_id)
                    WHERE request_id <> ''
                """
            )

    def test_record_user_studio_history_idempotent_with_request_id(self) -> None:
        """Calling record_user_studio_history with an existing requestId updates instead of duplicating."""
        uid = int(self.user_su["id"])
        req_id = "req_live_idem_99"

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, request_id, prompt, tab_title, engine, status, credits_spent, created_at
                ) VALUES ('gen_server_99', ?, 'su_editorial', ?, 'Original cloud prompt', '3:4', 'live', 'success', 2, ?)
                """,
                (uid, req_id, utc_now_iso()),
            )

        # Frontend calls record_user_studio_history with same requestId but custom id
        entry = {
            "id": "hist_browser_99",
            "requestId": req_id,
            "prompt": "Client updated prompt",
            "tabTitle": "4:3",
            "items": [{"imageUrl": "/generated/final.png"}],
        }
        res = record_user_studio_history(self.db, self.user_su, entry)
        self.assertTrue(res["ok"])
        # Should return the target id (gen_server_99) rather than creating a new row
        self.assertEqual(res["id"], "gen_server_99")

        conn = self.db.get_conn()
        rows = conn.execute("SELECT * FROM studio_generations WHERE request_id = ?", (req_id,)).fetchall()
        self.assertEqual(len(rows), 1, "Must remain exactly 1 row, no duplicates")
        row = rows[0]
        self.assertEqual(row["id"], "gen_server_99")
        self.assertEqual(row["engine"], "live")  # Immutable server accounting preserved
        self.assertEqual(row["credits_spent"], 2)  # Immutable server accounting preserved
        self.assertEqual(row["tab_title"], "4:3")  # Presentation updated

    def test_different_image_sets_are_never_merged(self) -> None:
        """Two generations by the same user with different images must never be deduplicated."""
        uid = int(self.user_su["id"])
        now = utc_now_iso()

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, items_json, engine, status, visibility, created_at
                ) VALUES ('gen_diff_1', ?, 'su_editorial', '["/img/cat.png"]', 'live', 'success', 'public', ?)
                """,
                (uid, now),
            )
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, items_json, engine, status, visibility, created_at
                ) VALUES ('gen_diff_2', ?, 'su_editorial', '["/img/dog.png"]', 'live', 'success', 'public', ?)
                """,
                (uid, now),
            )

        with self.db.transaction() as tx:
            cnt = deduplicate_generation_history(tx, user_id=uid)
        self.assertEqual(cnt, 0)

        conn = self.db.get_conn()
        rows = conn.execute("SELECT id FROM studio_generations WHERE id IN ('gen_diff_1', 'gen_diff_2') AND COALESCE(deleted_at, '') = ''").fetchall()
        self.assertEqual(len(rows), 2)

    def test_field_uniformity_and_strict_code_regex(self) -> None:
        """serialize_public_generation_history must enforce [{code, name}] format with CODE_RE."""
        # Row with valid codes
        row_valid = {
            "id": "gen_valid_1",
            "username": "alice",
            "created_at": "2026-11-01T12:00:00Z",
            "subject": "猫咪",
            "items_json": json.dumps(["/img/cat.webp"]),
            "recipe_summary": "#FA-001 #SC-021",
            "system_append_json": json.dumps({"recipeSnapshot": {"style1": "FA-001", "layout": "SC-021"}}),
        }
        res = serialize_public_generation_history(row_valid, conn=self.db.get_conn())
        self.assertIsInstance(res["styles"], list)
        self.assertIsInstance(res["layouts"], list)
        self.assertEqual(len(res["styles"]), 1)
        self.assertEqual(len(res["layouts"]), 1)
        self.assertEqual(res["styles"][0]["code"], "FA-001")
        self.assertTrue(bool(res["styles"][0]["name"]))
        self.assertEqual(res["layouts"][0]["code"], "SC-021")

        # Row with Python repr / [object Object] / garbage text in recipe_summary
        row_garbage = {
            "id": "gen_garbage_1",
            "username": "alice",
            "created_at": "2026-11-01T12:00:00Z",
            "subject": "坏数据",
            "items_json": json.dumps(["/img/art.webp"]),
            "recipe_summary": "[{'code': 'FA-001', 'name': 'something'}] · [object Object] · 画风:FA-001",
            "system_append_json": "",  # no snapshot
        }
        res_garbage = serialize_public_generation_history(row_garbage, conn=self.db.get_conn())
        # Should not eval or parse repr or guess; codes should be empty and not leak python repr
        self.assertEqual(res_garbage["styles"], [])
        self.assertEqual(res_garbage["layouts"], [])
        # But images and topic are preserved
        self.assertEqual(res_garbage["images"], ["/img/art.webp"])
        self.assertEqual(res_garbage["topic"], "坏数据")

        # Row with garbage in recipe_summary BUT valid trusted snapshot in system_append_json
        row_with_snap = {
            "id": "gen_with_snap_1",
            "username": "alice",
            "created_at": "2026-11-01T12:00:00Z",
            "subject": "快照修复",
            "items_json": json.dumps(["/img/art2.webp"]),
            "recipe_summary": "[object Object] · 垃圾文本",
            "system_append_json": json.dumps({"recipeSnapshot": {"style1": "FA-022", "layout": "SC-001"}}),
        }
        res_snap = serialize_public_generation_history(row_with_snap, conn=self.db.get_conn())
        # Should cleanly reconstruct from trusted snapshot
        self.assertEqual([s["code"] for s in res_snap["styles"]], ["FA-022"])
        self.assertEqual([l["code"] for l in res_snap["layouts"]], ["SC-001"])

    def test_record_user_studio_history_rejects_malformed_shapes_and_codes(self) -> None:
        """New writes with malformed styles/layouts/recipeSnapshot must be rejected with 400."""
        # Non-list styles
        with self.assertRaises(ServiceError) as ctx:
            record_user_studio_history(self.db, self.user_su, {"id": "test_err_1", "styles": "not-a-list"})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "invalid_resource_shape")

        # Invalid code pattern in styles
        with self.assertRaises(ServiceError) as ctx:
            record_user_studio_history(self.db, self.user_su, {"id": "test_err_2", "styles": [{"code": "not a valid code!"}]})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "invalid_resource_code")

        # Invalid code in recipeSnapshot
        with self.assertRaises(ServiceError) as ctx:
            record_user_studio_history(self.db, self.user_su, {"id": "test_err_3", "recipeSnapshot": {"style1": "bad_code_123"}})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "invalid_resource_code")

    def test_get_user_public_generations_auto_cleans_and_paginates_hole_free(self) -> None:
        """get_user_public_generations runs deduplication before pagination and returns exact counts."""
        uid = int(self.user_su["id"])
        now = utc_now_iso()

        # Seed 3 duplicates (6 rows total for 3 distinct generations)
        with self.db.transaction() as tx:
            for i in range(3):
                img = [f"/generated/unique_img_{i}.png"]
                tx.execute(
                    """
                    INSERT INTO studio_generations (
                        id, user_id, username, subject, items_json, engine, status, visibility, created_at
                    ) VALUES (?, ?, 'su_editorial', '测试画作', ?, 'sample', 'success', 'public', ?)
                    """,
                    (f"hist_seed_{i}", uid, json.dumps([{"imageUrl": img[0]}]), now),
                )
                tx.execute(
                    """
                    INSERT INTO studio_generations (
                        id, user_id, username, subject, items_json, engine, status, visibility, created_at
                    ) VALUES (?, ?, 'su_editorial', '测试画作', ?, 'live', 'success', 'public', ?)
                    """,
                    (f"gen_seed_{i}", uid, json.dumps(img), now),
                )
            # A gateway execution is not a public V3 work until projection.
            # Three live runs generate three works; sample ledgers are excluded.
            from backend.generation_works import project_generation_to_works
            for i in range(3):
                self.assertEqual(len(project_generation_to_works(tx, f"gen_seed_{i}")), 1)

        data = get_user_public_generations(self.db, "su_editorial", limit=10)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["generations"]), 3)
        self.assertEqual(data["total"], 3)
        self.assertEqual(
            {g["sourceGenerationId"] for g in data["generations"]},
            {"gen_seed_0", "gen_seed_1", "gen_seed_2"},
        )
        for g in data["generations"]:
            self.assertTrue(g["id"].startswith("run_"))
            self.assertTrue(g["workId"].startswith("work_"))
            # styles and layouts are lists of dicts
            for s in g["styles"]:
                self.assertTrue(CODE_RE.match(s["code"]))
            for l in g["layouts"]:
                self.assertTrue(CODE_RE.match(l["code"]))

    def test_different_requests_with_same_images_are_never_merged(self) -> None:
        """Two distinct requests with different non-empty request_ids but same images must NOT be merged."""
        uid = int(self.user_su["id"])
        now = utc_now_iso()
        img_urls = ["/generated/same_output.png"]

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, request_id, subject, items_json, engine, status, visibility, created_at
                ) VALUES ('gen_req_A', ?, 'su_editorial', 'req_alpha', '第一次请求', ?, 'live', 'success', 'public', ?)
                """,
                (uid, json.dumps(img_urls), now),
            )
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, request_id, subject, items_json, engine, status, visibility, created_at
                ) VALUES ('hist_req_B', ?, 'su_editorial', 'req_beta', '第二次请求', ?, 'sample', 'success', 'public', ?)
                """,
                (uid, json.dumps([{"imageUrl": img_urls[0]}]), now),
            )

        with self.db.transaction() as tx:
            del_cnt = deduplicate_generation_history(tx, user_id=uid)

        self.assertEqual(del_cnt, 0, "Distinct requests with different request_ids must not be merged")

        conn = self.db.get_conn()
        active = conn.execute(
            "SELECT id FROM studio_generations WHERE user_id = ? AND id IN ('gen_req_A', 'hist_req_B') AND COALESCE(deleted_at, '') = ''",
            (uid,),
        ).fetchall()
        self.assertEqual(len(active), 2, "Both records must remain active")

    def test_sample_generations_with_same_images_are_never_merged(self) -> None:
        """Multiple sample/demo generations by the same user with identical images must remain distinct."""
        uid = int(self.user_momo["id"])
        now = utc_now_iso()
        img_urls = ["/generated/fallback_sample.png"]

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, subject, items_json, engine, status, visibility, created_at
                ) VALUES ('hist_sample_1', ?, 'momo_design', '样本1', ?, 'sample', 'success', 'public', ?)
                """,
                (uid, json.dumps([{"imageUrl": img_urls[0]}]), now),
            )
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, subject, items_json, engine, status, visibility, created_at
                ) VALUES ('hist_sample_2', ?, 'momo_design', '样本2', ?, 'sample', 'success', 'public', ?)
                """,
                (uid, json.dumps([{"imageUrl": img_urls[0]}]), now),
            )

        with self.db.transaction() as tx:
            del_cnt = deduplicate_generation_history(tx, user_id=uid)

        self.assertEqual(del_cnt, 0, "Two separate sample generations must not be merged")

        conn = self.db.get_conn()
        active = conn.execute(
            "SELECT id FROM studio_generations WHERE user_id = ? AND id IN ('hist_sample_1', 'hist_sample_2') AND COALESCE(deleted_at, '') = ''",
            (uid,),
        ).fetchall()
        self.assertEqual(len(active), 2)

    def test_deduplication_never_touches_wallets_or_credits(self) -> None:
        """Deduplication only marks duplicate history deleted_at and leaves wallets, credits, quotas untouched."""
        uid = int(self.user_su["id"])
        conn = self.db.get_conn()
        wallet_before = conn.execute("SELECT balance, free_quota_used FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        ledgers_before = conn.execute("SELECT COUNT(*) FROM ledgers WHERE user_id = ?", (uid,)).fetchone()[0]

        with self.db.transaction() as tx:
            deduplicate_generation_history(tx)

        wallet_after = conn.execute("SELECT balance, free_quota_used FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        ledgers_after = conn.execute("SELECT COUNT(*) FROM ledgers WHERE user_id = ?", (uid,)).fetchone()[0]
        if wallet_before and wallet_after:
            self.assertEqual(wallet_before["balance"], wallet_after["balance"])
            self.assertEqual(wallet_before["free_quota_used"], wallet_after["free_quota_used"])
        self.assertEqual(ledgers_before, ledgers_after)


if __name__ == "__main__":
    unittest.main()
