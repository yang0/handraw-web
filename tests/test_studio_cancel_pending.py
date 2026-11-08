"""Server cancel-pending must never falsify a submitted gateway attempt."""
import tempfile
import unittest
from pathlib import Path

from backend.db import Database
from backend.generation_v3 import ensure_run, cancel_unsubmitted_web_slots
from backend.services import register_user, ServiceError


class CancelOnlyUnsubmittedSlotsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "cancel.db")
        self.db.migrate()
        self.alice, _ = register_user(self.db, "cancel_owner", "Pass12345!",
                                      "cancel-owner@example.com", "Owner", "invite-1")
        self.bob, _ = register_user(self.db, "cancel_other", "Pass12345!",
                                    "cancel-other@example.com", "Other", "invite-2")
        with self.db.transaction() as tx:
            self.run_id = ensure_run(tx, user_id=self.alice["id"], source="web",
                                     external_run_id="batch-cancel", expected_count=4)
            for i, state in [(0, "pending"), (1, "failed"), (2, "pending")]:
                tx.execute(
                    """INSERT INTO generation_items
                       (id,run_id,position,status,media_id,error_code,created_at,updated_at)
                       VALUES (?,?,?,?,NULL,'','2026-11-08','2026-11-08')""",
                    (f"cancel-item-{i}", self.run_id, i * 1000, state),
                )
            for index, state in [(2, "failed"), (3, "running")]:
                tx.execute(
                    """INSERT INTO studio_generations
                       (id,user_id,username,tab_title,mode,prompt,items_json,engine,
                        status,created_at,batch_id,batch_index,batch_total)
                       VALUES (?,?,?,?,?,'','[]','live',?,'2026-11-08',?,?,4)""",
                    (f"gateway-attempt-{index}", self.alice["id"], "cancel_owner",
                     "Canvas", "pure", state, "batch-cancel", index),
                )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_skip_submitted_failed_and_other_terminal_slots(self):
        result = cancel_unsubmitted_web_slots(self.db, self.alice,
                                               "batch-cancel", [0, 1, 2, 3])
        self.assertEqual(result["cancelledPositions"], [0])
        self.assertEqual(result["alreadySubmittedPositions"], [1, 2, 3])
        self.assertFalse(result["remoteTasksCancelled"])
        rows = self.db.get_conn().execute(
            "SELECT position,status FROM generation_items WHERE run_id=? ORDER BY position",
            (self.run_id,),
        ).fetchall()
        self.assertEqual([(x["position"], x["status"]) for x in rows],
                         [(0, "cancelled"), (1000, "failed"), (2000, "pending")])
        twice = cancel_unsubmitted_web_slots(self.db, self.alice,
                                              "batch-cancel", [0, 1, 2, 3])
        self.assertEqual(twice["cancelledPositions"], [0])
        self.assertEqual(twice["alreadySubmittedPositions"], [1, 2, 3])

    def test_other_owner_and_bool_index_rejected(self):
        with self.assertRaises(ServiceError) as error:
            cancel_unsubmitted_web_slots(self.db, self.bob, "batch-cancel", [0])
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(ServiceError) as invalid:
            cancel_unsubmitted_web_slots(self.db, self.alice, "batch-cancel", [True])
        self.assertEqual(invalid.exception.code, "invalid_cancel_positions")


if __name__ == "__main__":
    unittest.main()
