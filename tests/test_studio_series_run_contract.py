"""Issue #123: one V3 Run / one Work for 6 PlanSlots x 2 candidates.

The external billing ledger is authoritative for cost and is intentionally
not replicated in this test. Repeating a successful media callback and a
failed-output retry must not duplicate the public Work or successful media.
"""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from backend.db import Database
from backend.generation_v3 import (record_public_work, get_owned_studio_run,
                                   reserve_skill_run, refresh_run_status)
from backend.services import register_user, ServiceError


class SeriesRunContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "series-run.db")
        self.db.migrate()
        self.addCleanup(self.db.close)
        self.owner, _ = register_user(
            self.db, "series123owner", "SecurePassword123!")
        self.other, _ = register_user(
            self.db, "series123other", "SecurePassword123!")
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO works
                   (id,author_username,author_name,title,prompt,images_json,
                    status,published_at_ms,created_at,updated_at)
                   VALUES (?,?,?,?,?,'[]','published',0,'now','now')""",
                ("work-123", self.owner["username"], "Author", "十二图",
                 "原始冻结的系列主题"),
            )

    def _record_successes(self, positions):
        with self.db.transaction() as tx:
            return record_public_work(
                tx, user_id=int(self.owner["id"]), source="web",
                external_run_id="batch-6x2-123", work_id="work-123",
                ordered_images=[
                    (i * 1000, f"/generated/run123-{i}.webp", "")
                    for i in positions
                ], expected_count=12,
            )

    def test_12_real_outputs_map_to_single_work_with_partial_callbacks(self):
        run_id = self._record_successes([0, 1, 2])
        with self.db.transaction() as tx:
            for pos, status in [(3, "failed"), (4, "failed"),
                                (5, "generating")]:
                tx.execute(
                    """INSERT INTO generation_items
                       (id,run_id,position,status,media_id,error_code,
                        created_at,updated_at)
                       VALUES (?,?,?,?,NULL,?,'now','now')""",
                    (f"item-123-{pos}",run_id,pos*1000,status,
                     "gateway_failed" if status == "failed" else ""),
                )
            refresh_run_status(tx,run_id)
        model = get_owned_studio_run(self.db,self.owner,run_id)
        self.assertEqual(model["run"]["expectedCount"],12)
        self.assertEqual(model["run"]["workId"],"work-123")
        self.assertEqual([x["slotIndex"] for x in model["items"]],[0,1,2,3,4,5])
        self.assertEqual([x["status"] for x in model["items"]],
                         ["success","success","success","failed","failed","generating"])
        self.assertTrue(all(model["items"][n]["mediaId"] for n in range(3)))
        self.assertTrue(all(model["items"][n]["imageUrl"] for n in range(3)))
        conn=self.db.get_conn()
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM works WHERE run_id=?",(run_id,)
        ).fetchone()[0],1)
        with self.assertRaises(ServiceError) as ctx:
            get_owned_studio_run(self.db,self.other,run_id)
        self.assertEqual(ctx.exception.status,404)

        # A retry of only flattened output #3 must keep other output media
        # and the Work identity stable (no second public gallery entry).
        run_retry=self._record_successes([0,1,2,3])
        self.assertEqual(run_retry,run_id)
        after=get_owned_studio_run(self.db,self.owner,run_id)
        self.assertEqual(after["run"]["workId"],"work-123")
        self.assertEqual(after["items"][3]["status"],"success")
        self.assertEqual(after["items"][4]["status"],"failed")
        self.assertEqual(after["items"][5]["status"],"generating")
        self.assertEqual([it["mediaId"] for it in after["items"][:3]],
                         [it["mediaId"] for it in model["items"][:3]])
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM works WHERE run_id=?",(run_id,)
        ).fetchone()[0],1)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM work_media WHERE work_id='work-123'"
        ).fetchone()[0],4)

        # Deliver the SAME successful images again (duplicate callback).
        self._record_successes([0,1,2,3])
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM work_media WHERE work_id='work-123'"
        ).fetchone()[0],4)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM works WHERE run_id=?",(run_id,)
        ).fetchone()[0],1)


if __name__=="__main__":
    unittest.main()
