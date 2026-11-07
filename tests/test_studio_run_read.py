"""Owner-scoped Studio V3 Run read model and Web batch slot projection."""
import tempfile
import unittest
from pathlib import Path
from backend.db import Database
from backend.services import ServiceError, register_user
from backend.generation_v3 import ensure_run, get_owned_studio_run


class StudioRunReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "runs.db")
        self.db.migrate()
        self.alice, _ = register_user(self.db, "runreader_a", "Pass12345!", "runreader-a@example.com", "Alice", "invite-a")
        self.bob, _ = register_user(self.db, "runreader_b", "Pass12345!", "runreader-b@example.com", "Bob", "invite-b")
        with self.db.transaction() as tx:
            self.run_id = ensure_run(tx, user_id=self.alice["id"], source="web",
                                     external_run_id="b-test", expected_count=3)
            for position, status in ((0, "failed"), (1000, "cancelled"), (2000, "pending")):
                tx.execute(
                    """INSERT INTO generation_items
                       (id,run_id,position,status,media_id,error_code,created_at,updated_at)
                       VALUES (?,?,?,?,NULL,'','2026-11-08','2026-11-08')""",
                    (f"item-{position}", self.run_id, position, status),
                )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_read_uses_real_v3_status_and_logical_slot_indices(self):
        response = get_owned_studio_run(self.db, self.alice, self.run_id)
        self.assertEqual(response["run"]["expectedCount"], 3)
        self.assertEqual([x["position"] for x in response["items"]], [0,1000,2000])
        self.assertEqual([x["slotIndex"] for x in response["items"]], [0,1,2])
        self.assertEqual([x["imageIndex"] for x in response["items"]], [0,0,0])
        self.assertEqual(response["items"][0]["status"], "failed")
        self.assertEqual(response["run"]["workId"], "")

    def test_cannot_read_other_users_run(self):
        with self.assertRaises(ServiceError) as ctx:
            get_owned_studio_run(self.db, self.bob, self.run_id)
        self.assertEqual(ctx.exception.code, "run_not_found")
        self.assertEqual(ctx.exception.status, 404)


if __name__=="__main__":
    unittest.main()
