"""Issue #119: server Run/Item authority, attempts and monotonic media."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.db import Database
from backend.generation_v3 import (
    ensure_run, get_owned_studio_run, record_public_work, refresh_run_status,
    work_images,
)
from backend.services import ServiceError, register_user
from backend.studio_runtime_projection import project_studio_run


class RuntimeProjectionTests(unittest.TestCase):
    def test_one_and_six_slots_and_mixed_nonterminal_counters(self):
        now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        one = project_studio_run(
            {"id": "run-1", "status": "running", "source": "web", "expectedCount": 1},
            [{"id": "i1", "position": 0, "status": "success", "mediaId": "media1",
              "imageUrl": "/generated/one.webp"}], [], now=now)
        self.assertEqual(one["projection"]["succeeded"], 1)
        self.assertTrue(one["projection"]["isTerminal"])
        self.assertEqual(one["projection"]["viewStatus"], "success")

        run = {"id": "run-6", "status": "running", "source": "web", "expectedCount": 6}
        items = [
            {"id": f"item-{n}", "position": n * 1000,
             "slotIndex": n, "status": "success",
             "mediaId": f"m{n}", "imageUrl": f"/generated/{n}.webp"}
            for n in range(3)
        ] + [
            {"id": f"item-{n}", "position": n * 1000,
             "slotIndex": n, "status": "failed"}
            for n in (3, 4)
        ]
        gateway = [{
            "id": "gen-running", "batch_index": 5, "request_id": "req-last",
            "task_id": "task-last", "status": "queued",
            "system_append_json": json.dumps({"runtimeSnapshot": {
                "slotId": "plan-slot-6", "slotIndex": 5,
                "expectedCount": 6, "idempotencyKey": "req-last",
            }}),
            "created_at": "2026-11-08T11:59:00Z", "credits_spent": 2,
            "cost_type": "credits",
        }]
        result = project_studio_run(run, items, gateway, now=now)
        p = result["projection"]
        self.assertEqual([p["succeeded"], p["failed"], p["generating"], p["total"]],
                         [3, 2, 1, 6])
        self.assertFalse(p["isTerminal"])
        self.assertEqual(p["viewStatus"], "running")
        self.assertEqual(result["slots"][5]["slotId"], "plan-slot-6")
        self.assertTrue(result["slots"][5]["needsRecheck"])
        self.assertEqual(result["attempts"][0]["idempotencyKey"], "req-last")
        self.assertEqual(result["billing"]["creditsReservedOrCharged"], 2)

        # A failed earlier attempt cannot hide a newer active retry, but it
        # remains in the persisted history and cannot fake a successful image.
        gateway[0]["batch_index"] = 3
        mixed = project_studio_run(run, items, gateway, now=now)
        self.assertEqual(mixed["slots"][3]["viewStatus"], "running")
        self.assertFalse(mixed["slots"][3]["retryAllowed"])
        self.assertEqual(mixed["projection"]["failed"], 1)

    def test_stale_attempt_unknown_is_view_only_and_success_cannot_demote(self):
        now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        attempt = {"id": "g", "batch_index": 0, "status": "queued",
                   "task_id": "upstream", "created_at": "2026-11-08T08:00:00Z"}
        run = {"id": "r", "source": "web", "status": "running", "expectedCount": 1}
        unknown = project_studio_run(run, [], [attempt], now=now)
        self.assertEqual(unknown["slots"][0]["viewStatus"], "unknown")
        self.assertEqual(unknown["projection"]["processed"], 0)
        self.assertEqual(unknown["projection"]["persistedStatus"], "running")
        self.assertTrue(unknown["projection"]["recoveryRequired"])
        success = project_studio_run(run,
            [{"id": "it", "position": 0, "status": "success", "mediaId": "m",
              "imageUrl": "/generated/immutable.webp"}], [attempt], now=now)
        self.assertEqual(success["slots"][0]["viewStatus"], "success")
        self.assertEqual(success["slots"][0]["imageUrl"], "/generated/immutable.webp")
        self.assertEqual(success["projection"]["succeeded"], 1)


class RuntimeDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "studio119.sqlite")
        self.db.migrate()
        self.alice, _ = register_user(self.db, "run119_alice", "Pass12345!")
        self.bob, _ = register_user(self.db, "run119_bob", "Pass12345!")
        self.uid = int(self.alice["id"])
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO works
                   (id,author_username,author_name,title,prompt,images_json,status,
                    published_at_ms,created_at,updated_at)
                   VALUES (?,?,?,'画布图片','示例','[]','published',0,'now','now')""",
                ("work-119", self.alice["username"], "Alice"),
            )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def _make(self, images, expected=6):
        with self.db.transaction() as tx:
            return record_public_work(
                tx, user_id=self.uid, source="web",
                external_run_id="batch-119", expected_count=expected,
                work_id="work-119", ordered_images=images,
            )

    def test_out_of_order_late_success_and_repeat_never_replace_confirmed_media(self):
        run_id = self._make([(1000, "/generated/first-b.webp", "")])
        self._make([(0, "/generated/first-a.webp", ""),
                    (1000, "/generated/first-b.webp", "")])
        # A later success for the same position is still an independently
        # chargeable gateway attempt but must not overwrite the first result.
        self._make([(1000, "/generated/late-replacement.webp", "")])
        self._make([(1000, "/generated/late-replacement.webp", "")])
        self.assertEqual(work_images(self.db.get_conn(), "work-119"),
                         ["/generated/first-a.webp", "/generated/first-b.webp"])
        rows = self.db.get_conn().execute(
            """SELECT i.position,m.storage_key
               FROM generation_items i JOIN media_assets m ON m.id=i.media_id
               WHERE i.run_id=? ORDER BY i.position""", (run_id,),
        ).fetchall()
        self.assertEqual([(r["position"], r["storage_key"]) for r in rows],
                         [(0, "/generated/first-a.webp"),
                          (1000, "/generated/first-b.webp")])
        self.assertEqual(self.db.get_conn().execute(
            "SELECT count(*) FROM works WHERE run_id=?", (run_id,),
        ).fetchone()[0], 1)

    def test_six_slot_owner_endpoint_matches_run_and_real_attempts(self):
        run_id = self._make([(0, "/generated/one.webp", ""),
                             (1000, "/generated/two.webp", ""),
                             (2000, "/generated/three.webp", "")])
        now = "2026-01-01T12:00:00Z"
        with self.db.transaction() as tx:
            for n in (3, 4):
                tx.execute(
                    """INSERT INTO generation_items
                       (id,run_id,position,status,media_id,error_code,created_at,updated_at)
                       VALUES (?,?,?,'failed',NULL,'gateway_failed',?,?)""",
                    (f"failed-{n}", run_id, n * 1000, now, now),
                )
            tx.execute(
                """INSERT INTO studio_generations
                   (id,user_id,username,tab_title,mode,prompt,items_json,engine,
                    status,created_at,batch_id,batch_index,batch_total,
                    task_id,request_id,cost_type,credits_spent,system_append_json)
                   VALUES (?,?,?,?,?,'','[]','live',?,?,?,?,?,?,?, ?,?,?)""",
                ("gen-119-pending", self.uid, "run119_alice", "Canvas", "pure",
                 "queued", now, "batch-119", 5, 6, "task-119", "req-119",
                 "credits", 2, json.dumps({"runtimeSnapshot":{"slotId":"slot-6"}})),
            )
            self.assertEqual(refresh_run_status(tx, run_id), "running")
        data = get_owned_studio_run(self.db, self.alice, run_id)
        self.assertEqual(data["run"]["status"], "running")
        self.assertEqual([data["projection"][k] for k in (
            "total", "succeeded", "failed", "generating")], [6, 3, 2, 0])
        # The known gateway submission is stale by current wall clock,
        # hence *unknown*, never false success. API still reports the six slots.
        self.assertEqual(data["projection"]["unknown"], 1)
        self.assertEqual(len(data["slots"]), 6)
        self.assertEqual(data["slots"][5]["slotId"], "slot-6")
        self.assertEqual(data["attempts"][0]["requestId"], "req-119")
        with self.assertRaises(ServiceError) as denied:
            get_owned_studio_run(self.db, self.bob, run_id)
        self.assertEqual(denied.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
