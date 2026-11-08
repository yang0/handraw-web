"""Studio 2.0 Project persistence P0: CAS, idempotency, privacy and authority."""
import tempfile
import unittest
from pathlib import Path

from backend.db import Database
from backend.services import ServiceError, register_user
from backend.studio_projects import (
    create_project, get_project, list_projects, patch_project, copy_project
)


class StudioProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "projects.sqlite3")
        names = self.db.migrate()
        self.assertIn("101_studio_project_drafts", names)
        self.alice, _ = register_user(self.db, "prj_alice", "Pass12345!",
                                      "prj-a@example.com", "Alice", "invite-1")
        self.bob, _ = register_user(self.db, "prj_bob", "Pass12345!",
                                    "prj-b@example.com", "Bob", "invite-2")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def _create(self, ident="project-0001", key="create-key-00001", **extra):
        body = {"projectId": ident, "kind": "image", "authority": "spec",
                "title": "春日海报", "draft": {
                    "creationSpec": {"subject": "杭州春天", "ratio": "3:4"},
                    "plan": {"slots": []}, "activeView": "simple"
                }, "idempotencyKey": key}
        body.update(extra)
        return create_project(self.db, self.alice, body)

    def _patch(self, rev, path="/creationSpec/subject", value="改为秋天", key="patch-key-00001"):
        return patch_project(self.db, self.alice, "project-0001", {
            "baseRevision": rev, "idempotencyKey": key,
            "patch": {"op": "set", "path": path, "value": value},
        })

    def test_create_patch_and_no_implicit_run(self):
        one = self._create()
        self.assertEqual(one["revision"], 1)
        self.assertEqual(one["saveState"], "synced")
        two = self._patch(1)
        self.assertEqual(two["revision"], 2)
        self.assertFalse(two["unchanged"])
        self.assertEqual(get_project(self.db, self.alice, "project-0001")["project"]["draft"]
                         ["creationSpec"]["subject"], "改为秋天")
        self.assertEqual(len(list_projects(self.db, self.alice)["projects"]), 1)
        self.assertNotIn("draft", list_projects(self.db, self.alice)["projects"][0])
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_runs").fetchone()[0], 0)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM works").fetchone()[0], 0)

    def test_repeat_request_is_idempotent_and_different_payload_is_rejected(self):
        one = self._create()
        again = self._create()
        self.assertTrue(again["idempotentReplay"])
        self.assertEqual(again["revision"], one["revision"])
        a = self._patch(1)
        b = self._patch(1)
        self.assertEqual(a["revision"], 2)
        self.assertTrue(b["idempotentReplay"])
        self.assertEqual(b["revision"], 2)
        with self.assertRaises(ServiceError) as err:
            self._patch(1, value="不能用原键覆盖", key="patch-key-00001")
        self.assertEqual(err.exception.code, "idempotency_key_reused")

    def test_stale_update_fails_without_destroying_remote(self):
        self._create()
        self._patch(1, value="标签 A")
        with self.assertRaises(ServiceError) as err:
            self._patch(1, value="标签 B", key="different-key-01")
        self.assertEqual(err.exception.status, 409)
        self.assertEqual(err.exception.code, "project_revision_conflict")
        self.assertEqual(get_project(self.db, self.alice, "project-0001")
                         ["project"]["draft"]["creationSpec"]["subject"], "标签 A")

    def test_unchanged_patch_retains_revision(self):
        self._create()
        result = self._patch(1, value="杭州春天", key="noop-key-00001")
        self.assertTrue(result["unchanged"])
        self.assertEqual(result["revision"], 1)

    def test_graph_authority_does_not_allow_derived_spec_writes(self):
        self._create(kind="series", authority="graph", draft={
            "graph": {"revision": 1, "nodes": [{"id": "n1"}], "edges": []},
            "creationSpec": {"subject": "只读派生"}
        })
        with self.assertRaises(ServiceError) as err:
            self._patch(1, value="偷改")
        self.assertEqual(err.exception.code, "editor_authority_conflict")
        change = self._patch(1, "/graph/nodes", [{"id": "n1"}, {"id": "n2"}],
                             key="graph-key-00001")
        self.assertEqual(change["revision"], 2)
        self.assertEqual(len(get_project(self.db, self.alice, "project-0001")
                             ["project"]["draft"]["graph"]["nodes"]), 2)

    def test_atomic_authority_switch_preserves_complex_graph(self):
        self._create()
        response = patch_project(self.db, self.alice, "project-0001", {
            "baseRevision": 1, "idempotencyKey": "switch-key-00001",
            "patch": [
                {"op": "set", "path": "/authority", "value": "graph"},
                {"op": "set", "path": "/graph", "value": {
                    "revision": 1, "nodes": [{"id": "a"}, {"id": "b"}],
                    "edges": [{"id": "e", "from": "a", "to": "b"}]}},
            ]
        })
        self.assertEqual(response["revision"], 2)
        graph = get_project(self.db, self.alice, "project-0001")["project"]
        self.assertEqual(graph["authority"], "graph")
        self.assertEqual(len(graph["draft"]["graph"]["edges"]), 1)
        self.assertEqual(graph["draft"]["creationSpec"]["subject"], "杭州春天")

    def test_users_cannot_read_patch_or_copy_other_projects(self):
        self._create()
        with self.assertRaises(ServiceError) as err:
            get_project(self.db, self.bob, "project-0001")
        self.assertEqual(err.exception.status, 404)
        self.assertEqual(list_projects(self.db, self.bob)["projects"], [])
        with self.assertRaises(ServiceError) as err:
            patch_project(self.db, self.bob, "project-0001",
                          {"baseRevision": 1, "idempotencyKey": "other-key-00001",
                           "patch": {"op": "set", "path": "/title", "value": "Other"}})
        self.assertEqual(err.exception.status, 404)
        with self.assertRaises(ServiceError) as err:
            copy_project(self.db, self.bob, "project-0001",
                         {"newProjectId": "project-bob-copy",
                          "idempotencyKey": "copy-other-00001"})
        self.assertEqual(err.exception.status, 404)

    def test_conflict_recovery_copy_keeps_original(self):
        self._create()
        self._patch(1)
        local = {"creationSpec": {"subject": "离线文案"}, "activeView": "simple"}
        result = copy_project(self.db, self.alice, "project-0001", {
            "newProjectId": "project-copy1", "idempotencyKey": "copy-key-00001",
            "localDraft": local
        })
        self.assertEqual(result["revision"], 1)
        self.assertEqual(get_project(self.db, self.alice, "project-copy1")
                         ["project"]["draft"]["creationSpec"]["subject"], "离线文案")
        self.assertEqual(get_project(self.db, self.alice, "project-0001")
                         ["project"]["draft"]["creationSpec"]["subject"], "改为秋天")

    def test_private_media_access_and_inline_image_restrictions(self):
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO media_assets
               (id,owner_user_id,storage_key,created_at)
               VALUES ('owned-media',?,'/generated/owned.png','2026-11-08')""",
               (self.alice["id"],))
            tx.execute("""INSERT INTO media_assets
               (id,owner_user_id,storage_key,created_at)
               VALUES ('other-media',?,'/generated/bob.png','2026-11-08')""",
               (self.bob["id"],))
        self._create(draft={"creationSpec": {"referenceMedia":
                                            [{"mediaId": "owned-media", "role": "character"}]}})
        with self.assertRaises(ServiceError) as err:
            patch_project(self.db, self.alice, "project-0001", {
                "baseRevision": 1, "idempotencyKey": "unsafe-key-00001",
                "patch": {"op": "set", "path": "/creationSpec/referenceMedia",
                          "value": [{"mediaId": "other-media", "role": "scene"}]}
            })
        self.assertEqual(err.exception.code, "project_media_forbidden")
        with self.assertRaises(ServiceError) as err:
            patch_project(self.db, self.alice, "project-0001", {
                "baseRevision": 1, "idempotencyKey": "unsafe-key-00002",
                "patch": {"op": "set", "path": "/creationSpec/referenceMedia",
                          "value": [{"dataUrl": "data:image/png;base64,aGVsbG8="}]}
            })
        self.assertEqual(err.exception.code, "project_media_upload_required")
        self.assertEqual(get_project(self.db, self.alice, "project-0001")["project"]["revision"], 1)

    def test_oversized_and_secret_fields_rejected_before_save(self):
        with self.assertRaises(ServiceError) as err:
            self._create(draft={"creationSpec": {"apiKey": "do-not-save"}})
        self.assertEqual(err.exception.code, "invalid_project_draft")
        with self.assertRaises(ServiceError) as err:
            self._create(draft={"creationSpec": {"subject": "a" * 210000}})
        self.assertEqual(err.exception.code, "project_draft_too_large")

    def test_bad_revision_and_unsupported_paths(self):
        self._create()
        for revision in [0, True, "1", None]:
            with self.subTest(revision=revision):
                with self.assertRaises(ServiceError) as err:
                    self._patch(revision)
                self.assertEqual(err.exception.code, "base_revision_required")
        with self.assertRaises(ServiceError) as err:
            self._patch(1, "/__proto__/x", "unsafe")
        self.assertEqual(err.exception.code, "invalid_project_patch")


if __name__ == "__main__":
    unittest.main()
