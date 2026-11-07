"""Studio2 workflows must acknowledge cloud saves and protect concurrent edits."""
import json
import tempfile
import unittest
from pathlib import Path
from backend.db import Database
from backend.services import ServiceError, register_user, save_user_studio_workflow, get_studio_workspace


class WorkflowVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "wf.db")
        self.db.migrate()
        self.alice, _ = register_user(self.db, "studio2_alice", "Pass12345!", "studio2-a@example.com", "Alice", "invite-a")
        self.bob, _ = register_user(self.db, "studio2_bob", "Pass12345!", "studio2-b@example.com", "Bob", "invite-b")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def save(self, user, body):
        return save_user_studio_workflow(self.db, user, body)

    def test_create_and_noop_returns_server_revision(self):
        one = self.save(self.alice, {"id":"wf-v1", "title":"A", "graph":{"nodes":[]}, "baseUpdatedAtMs":0})
        self.assertGreater(one["updatedAtMs"], 0)
        same = self.save(self.alice, {"id":"wf-v1", "title":"A", "graph":{"nodes":[]},
                                      "baseUpdatedAtMs":one["updatedAtMs"]})
        self.assertTrue(same["unchanged"])
        self.assertEqual(same["updatedAtMs"], one["updatedAtMs"])
        saved = get_studio_workspace(self.db, self.alice)
        self.assertEqual([w["id"] for w in saved["workflows"] if w["id"]=="wf-v1"], ["wf-v1"])

    def test_stale_version_does_not_overwrite_remote_graph(self):
        first = self.save(self.alice, {"id":"wf-two", "graph":{"nodes":[1]}, "baseUpdatedAtMs":0})
        change = self.save(self.alice, {"id":"wf-two", "graph":{"nodes":[2]}, "baseUpdatedAtMs":first["updatedAtMs"]})
        self.assertGreater(change["updatedAtMs"], first["updatedAtMs"])
        with self.assertRaises(ServiceError) as ctx:
            self.save(self.alice, {"id":"wf-two", "graph":{"nodes":[3]}, "baseUpdatedAtMs":first["updatedAtMs"]})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "workflow_version_conflict")
        row = self.db.get_conn().execute("SELECT graph_json FROM studio_workflows WHERE id='wf-two'").fetchone()
        self.assertEqual(json.loads(row["graph_json"])["nodes"], [2])

    def test_other_user_and_preset_protection(self):
        self.save(self.alice, {"id":"alice-workflow","graph":{},"baseUpdatedAtMs":0})
        with self.assertRaises(ServiceError) as ctx:
            self.save(self.bob, {"id":"alice-workflow","graph":{},"baseUpdatedAtMs":0})
        self.assertEqual(ctx.exception.status,403)

    def test_legacy_save_still_allowed_but_new_client_has_optimistic_lock(self):
        self.save(self.alice, {"id":"wf-old","graph":{"nodes":[]}})
        result = self.save(self.alice, {"id":"wf-old","graph":{"nodes":[4]}})
        self.assertTrue(result["ok"])
        self.assertGreater(result["updatedAtMs"],0)
        with self.assertRaises(ServiceError) as ctx:
            self.save(self.alice, {"id":"wf-old","graph":{"nodes":[]},"baseUpdatedAtMs":0})
        self.assertEqual(ctx.exception.code,"workflow_version_conflict")


if __name__=="__main__":
    unittest.main()
