"""Fresh V3 schema and canonical one-run/one-work media invariants."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import Database
from backend.generation_v3 import (
    ensure_run, record_public_work, reserve_skill_run,
    record_skill_uploaded_item, uploaded_skill_images, work_images,
)
from backend.services import register_user


class GenerationV3Tests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "v3.db")
        self.db.migrate()
        self.addCleanup(self.db.close)
        self.creator, _ = register_user(self.db, "v3_creator", "SecurePassword123!")
        self.stranger, _ = register_user(self.db, "v3_stranger", "SecurePassword123!")
        self.owner_id = int(self.creator["id"])

    def _new_work(self, work_id: str = "work_v3") -> str:
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (
                    id,author_username,author_name,title,prompt,images_json,
                    status,published_at_ms,created_at,updated_at
                ) VALUES (?,?,?,'五张春日小镇','画春日小镇','[]','published',0,'now','now')
                """,
                (work_id, self.creator["username"], "创作者"),
            )
        return work_id

    def test_fresh_schema_excludes_legacy_skill_history_tables(self):
        conn = self.db.get_conn()
        names = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue({"generation_runs", "generation_items",
                         "media_assets", "work_media", "works"} <= names)
        self.assertNotIn("skill_generation_runs", names)
        self.assertNotIn("skill_generation_work_items", names)
        self.assertNotIn("skill_history_publications", names)
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_out_of_order_batch_has_one_work_and_first_successful_cover(self):
        wid = self._new_work()
        uid = self.owner_id
        with self.db.transaction() as tx:
            first = record_public_work(
                tx, user_id=uid, source="web", external_run_id="canvas_batch",
                work_id=wid, ordered_images=[(1000, "/generated/second.webp", "")],
                expected_count=2,
            )
        self.assertEqual(self.db.get_conn().execute(
            "SELECT status FROM generation_runs WHERE id=?", (first,)
        ).fetchone()[0], "partial")
        with self.db.transaction() as tx:
            second = record_public_work(
                tx, user_id=uid, source="web", external_run_id="canvas_batch",
                work_id=wid,
                ordered_images=[(0, "/generated/first.webp", ""),
                                (1000, "/generated/second.webp", "")],
                expected_count=2,
            )
        self.assertEqual(first, second)
        conn = self.db.get_conn()
        self.assertEqual(work_images(conn, wid),
                         ["/generated/first.webp", "/generated/second.webp"])
        self.assertEqual(json.loads(conn.execute(
            "SELECT images_json FROM works WHERE id=?", (wid,)
        ).fetchone()[0]), work_images(conn, wid))
        self.assertEqual(conn.execute(
            "SELECT status FROM generation_runs WHERE id=?", (first,)
        ).fetchone()[0], "success")
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM works WHERE run_id=?", (first,)
        ).fetchone()[0], 1)
        cover = conn.execute(
            "SELECT cover_media_id FROM works WHERE id=?", (wid,)
        ).fetchone()[0]
        linked = conn.execute(
            "SELECT media_id FROM work_media WHERE work_id=? ORDER BY position LIMIT 1",
            (wid,),
        ).fetchone()[0]
        self.assertEqual(cover, linked)

        # Repeat to verify idempotency with no orphan media or duplicate works.
        with self.db.transaction() as tx:
            record_public_work(
                tx, user_id=uid, source="web", external_run_id="canvas_batch",
                work_id=wid,
                ordered_images=[(0, "/generated/first.webp", ""),
                                (1000, "/generated/second.webp", "")],
                expected_count=2,
            )
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM generation_items WHERE run_id=?", (first,)
        ).fetchone()[0], 2)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM media_assets WHERE owner_user_id=?", (uid,)
        ).fetchone()[0], 2)

    def test_unique_work_per_run_and_owner_guard(self):
        wid = self._new_work()
        other = self._new_work("work_v3_duplicate")
        with self.db.transaction() as tx:
            record_public_work(
                tx, user_id=self.owner_id, source="web",
                external_run_id="one_job", work_id=wid,
                ordered_images=[(0, "/generated/one.png", "")],
                expected_count=1,
            )
        with self.assertRaises(ValueError):
            with self.db.transaction() as tx:
                record_public_work(
                    tx, user_id=self.owner_id, source="web",
                    external_run_id="one_job", work_id=other,
                    ordered_images=[(0, "/generated/one.png", "")],
                    expected_count=1,
                )
        with self.assertRaises(ValueError):
            with self.db.transaction() as tx:
                record_public_work(
                    tx, user_id=int(self.stranger["id"]), source="web",
                    external_run_id="evil_job", work_id=wid,
                    ordered_images=[(0, "/generated/one.png", "")],
                    expected_count=1,
                )

    def test_cover_cannot_reference_unlinked_media(self):
        wid = self._new_work()
        with self.db.transaction() as tx:
            record_public_work(
                tx, user_id=self.owner_id, source="web",
                external_run_id="one", work_id=wid,
                ordered_images=[(0, "/generated/one.png", "")],
                expected_count=1,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE works SET cover_media_id=? WHERE id=?",
                    ("missing_media", wid),
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction() as tx:
                tx.execute(
                    "DELETE FROM work_media WHERE work_id=?", (wid,),
                )

    def test_skill_upload_partial_and_request_conflict(self):
        user_id = self.owner_id
        hash_a = "a" * 64
        with self.db.transaction() as tx:
            rid = reserve_skill_run(
                tx, user_id=user_id, external_run_id="skill_run_1",
                request_id="skill_request_1", request_hash=hash_a,
                original_request="两张图", expected_count=2,
            )
            record_skill_uploaded_item(
                tx, run_id=rid, user_id=user_id, position=0,
                url="/uploads/a.png", sha256=hash_a,
            )
        self.assertEqual(len(uploaded_skill_images(self.db.get_conn(), rid)), 1)
        with self.assertRaises(ValueError):
            with self.db.transaction() as tx:
                reserve_skill_run(
                    tx, user_id=user_id, external_run_id="skill_run_1",
                    request_id="skill_request_1", request_hash="b" * 64,
                    original_request="修改了原始请求", expected_count=2,
                )
        with self.db.transaction() as tx:
            reserve_skill_run(
                tx, user_id=user_id, external_run_id="skill_run_1",
                request_id="skill_request_1", request_hash=hash_a,
                original_request="两张图", expected_count=2,
            )
            record_skill_uploaded_item(
                tx, run_id=rid, user_id=user_id, position=1,
                url="/uploads/b.png", sha256="b" * 64,
            )
        self.assertEqual(len(uploaded_skill_images(self.db.get_conn(), rid)), 2)

    def test_partial_success_retains_failed_slots_and_history(self):
        from backend.skill_web_bridge import list_history
        uid = self.owner_id
        wid = self._new_work()
        with self.db.transaction() as tx:
            run_id = ensure_run(
                tx, user_id=uid, source="web",
                external_run_id="partial_batch", expected_count=5,
                request_id="partial_batch",
            )
            for position in (3000, 4000):
                tx.execute(
                    """
                    INSERT INTO generation_items
                      (id,run_id,position,status,error_code,created_at,updated_at)
                    VALUES (?,?,?,'failed','gateway_failed','now','now')
                    """,
                    (f"failed_item_{position}", run_id, position),
                )
            record_public_work(
                tx, user_id=uid, source="web",
                external_run_id="partial_batch",
                work_id=wid, expected_count=5,
                ordered_images=[
                    (0, "/generated/one.webp", ""),
                    (1000, "/generated/two.webp", ""),
                    (2000, "/generated/three.webp", ""),
                ],
            )
        conn = self.db.get_conn()
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM generation_items WHERE run_id=?", (run_id,),
        ).fetchone()[0], 5)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM generation_items WHERE run_id=? AND status='failed'",
            (run_id,),
        ).fetchone()[0], 2)
        self.assertEqual(conn.execute(
            "SELECT status FROM generation_runs WHERE id=?", (run_id,),
        ).fetchone()[0], "partial")
        history = list_history(self.db, self.creator, {})
        run = next(item for item in history["items"] if item["id"] == run_id)
        self.assertEqual(run["imageCount"], 3)
        self.assertEqual(len(run["items"]), 5)
        self.assertEqual(run["workIds"], [wid])
        self.assertEqual(len([i for i in run["items"] if i["status"] == "failed"]), 2)

    def test_generated_work_cache_cannot_disagree_with_canonical_media(self):
        wid = self._new_work()
        with self.db.transaction() as tx:
            record_public_work(
                tx, user_id=self.owner_id, source="web",
                external_run_id="cache_guard", work_id=wid,
                ordered_images=[(0, "/generated/one.webp", "")],
                expected_count=1,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE works SET images_json=? WHERE id=?",
                    (json.dumps(["/generated/unlinked.webp"]), wid),
                )

    def test_empty_work_must_not_publish(self):
        wid = self._new_work()
        with self.assertRaises(ValueError):
            with self.db.transaction() as tx:
                record_public_work(
                    tx, user_id=self.owner_id, source="web",
                    external_run_id="no_images", work_id=wid,
                    ordered_images=[], expected_count=1,
                )
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_runs"
        ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
