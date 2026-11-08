"""Studio #107: Project CAS, scoped graph patches, view-only changes, article authority."""
import copy
import tempfile
import unittest
from pathlib import Path

from backend.db import Database
from backend.services import ServiceError, register_user
from backend.studio_projects import create_project, patch_project, get_project, list_projects


def branch_graph():
    return {"blueprint": "single", "revision": 6, "nodes": [
        {"id": "n-text", "type": "text_input", "data": {"text": "春天"}},
        {"id": "n-style", "type": "skill_params", "data": {}},
        {"id": "output-a", "type": "output_control", "data": {"ratio": "3:4"}},
        {"id": "output-b", "type": "output_control", "data": {"ratio": "9:16"}},
        {"id": "asset-1", "type": "asset", "data": {"items": [{"localId": "hold-1"}]}}
    ], "edges": [
        {"id": "e1", "from": "n-text", "to": "output-a"},
        {"id": "e2", "from": "n-text", "to": "output-b"},
        {"id": "e3", "from": "n-style", "to": "output-a"},
        {"id": "e4", "from": "n-style", "to": "output-b"}
    ], "groups": [{"id": "group-x", "nodes": ["output-a", "output-b"]}]}


class StudioViewAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "issue107.sqlite3")
        self.db.migrate()
        self.user, _ = register_user(self.db, "view_test", "Pass12345!",
                                     "views@example.com", "Views", "invite-1")
        self.other, _ = register_user(self.db, "view_other", "Pass12345!",
                                      "views2@example.com", "Other", "invite-2")
        self.graph = branch_graph()
        create_project(self.db, self.user, {
            "projectId": "project-branch-107", "kind": "image",
            "authority": "graph", "title": "分支项目",
            "draft": {"graph": self.graph, "activeView": "canvas",
                      "editorLayout": {"camera": {"vx": 32, "vy": -5, "vk": .72},
                                       "selectedIds": ["n-text"], "panels": {"shelfOpen": False},
                                       "workflowVersion": "unsaved",
                                       "resultRefs": [{"runId": "run-7"}]}},
            "idempotencyKey": "create-branch-107"
        })

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def apply(self, rev, changes, key):
        return patch_project(self.db, self.user, "project-branch-107",
                             {"baseRevision": rev, "idempotencyKey": key, "patch": changes})

    def project(self):
        return get_project(self.db, self.user, "project-branch-107")["project"]

    def test_ten_switches_and_refresh_preserve_graph_layout_and_run_refs(self):
        initial = copy.deepcopy(self.project()["draft"]["graph"])
        rev = 1
        for i in range(10):
            view = "simple" if i % 2 == 0 else "canvas"
            changed = self.apply(rev, [
                {"op": "set", "path": "/activeView", "value": view},
                {"op": "set", "path": "/editorLayout/camera",
                 "value": {"vx": 32, "vy": -5, "vk": .72}}
            ], f"view-switch-{i:04d}")
            rev = changed["revision"]
            self.assertEqual(self.project()["draft"]["graph"], initial)
        restored = self.project()
        self.assertEqual(restored["draft"]["activeView"], "canvas")
        self.assertEqual(restored["draft"]["editorLayout"]["selectedIds"], ["n-text"])
        self.assertEqual(restored["draft"]["editorLayout"]["resultRefs"], [{"runId": "run-7"}])
        self.assertEqual(len(list_projects(self.db, self.user)["projects"]), 1)
        self.assertEqual(self.db.get_conn().execute("SELECT count(*) FROM generation_runs").fetchone()[0], 0)

    def test_exact_shared_node_patch_preserves_branches_and_media(self):
        before = copy.deepcopy(self.project()["draft"]["graph"])
        changed = self.apply(1, [
            {"op": "set", "path": "/graph/nodesById/n-text/data/text", "value": "新的公共主题"},
            {"op": "set", "path": "/activeView", "value": "simple"},
        ], "node-patch-107")
        self.assertEqual(changed["revision"], 2)
        graph = self.project()["draft"]["graph"]
        self.assertEqual(graph["revision"], 7)
        self.assertEqual(graph["nodes"][0]["data"]["text"], "新的公共主题")
        self.assertEqual(graph["nodes"][3]["data"]["ratio"], "9:16")
        self.assertEqual(graph["edges"], before["edges"])
        self.assertEqual(graph["groups"], before["groups"])
        self.assertEqual(graph["nodes"][4]["data"], before["nodes"][4]["data"])
        replay = self.apply(1, [
            {"op": "set", "path": "/graph/nodesById/n-text/data/text", "value": "新的公共主题"},
            {"op": "set", "path": "/activeView", "value": "simple"},
        ], "node-patch-107")
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(self.project()["revision"], 2)

    def test_branch_output_and_runtime_state_cannot_be_patched_as_simple(self):
        for i, (path, value) in enumerate([
            ("/graph/nodesById/output-a/data/ratio", "1:1"),
            ("/graph/nodesById/n-text/data/status", "running"),
            ("/graph/nodesById/n-text/data/__proto__", {}),
            ("/graph/nodesById/no-such-node/data/text", "bad"),
            ("/graph/nodesById/n-style/data/customMood", "bad"),
        ]):
            with self.subTest(path=path), self.assertRaises(ServiceError):
                self.apply(1, {"op": "set", "path": path, "value": value},
                           f"blocked-edit-{i:04d}")
        self.assertEqual(self.project()["revision"], 1)

    def test_optimistic_conflict_and_authority_lock(self):
        self.apply(1, {"op": "set", "path": "/graph/nodesById/n-text/data/text",
                       "value": "标签 A"}, "tab-A-000107")
        with self.assertRaises(ServiceError) as err:
            self.apply(1, {"op": "set", "path": "/graph/nodesById/n-text/data/text",
                           "value": "标签 B"}, "tab-B-000107")
        self.assertEqual(err.exception.code, "project_revision_conflict")
        with self.assertRaises(ServiceError) as err2:
            self.apply(2, {"op": "set", "path": "/authority", "value": "spec"},
                       "unsafe-downgrade-107")
        self.assertEqual(err2.exception.code, "editor_authority_conflict")
        self.assertEqual(self.project()["draft"]["graph"]["nodes"][0]["data"]["text"], "标签 A")
        with self.assertRaises(ServiceError) as err3:
            patch_project(self.db, self.other, "project-branch-107", {
                "baseRevision": 2, "idempotencyKey": "cross-owner-107",
                "patch": {"op": "set", "path": "/activeView", "value": "canvas"}})
        self.assertEqual(err3.exception.status, 404)

    def test_article_document_anchors_are_not_graph_authority(self):
        created = create_project(self.db, self.user, {
            "projectId": "project-article-107", "kind": "article", "authority": "article",
            "title": "文章配图", "idempotencyKey": "create-article-107",
            "draft": {"article": {"markdown": "# 旅行", "anchors": [
                        {"anchorId": "anchor-one", "offset": 4}]},
                      "plan": {"slots": [{"slotId": "slot-one", "anchorId": "anchor-one"}]},
                      "activeView": "simple"}
        })
        self.assertEqual(created["revision"], 1)
        patch_project(self.db, self.user, "project-article-107", {
            "baseRevision": 1, "idempotencyKey": "article-view-107",
            "patch": {"op": "set", "path": "/editorLayout/panels",
                      "value": {"inspectorOpen": True}}
        })
        result = get_project(self.db, self.user, "project-article-107")["project"]
        self.assertEqual(result["draft"]["article"]["anchors"][0]["anchorId"], "anchor-one")
        self.assertEqual(result["draft"]["plan"]["slots"][0]["anchorId"], "anchor-one")
        with self.assertRaises(ServiceError):
            patch_project(self.db, self.user, "project-article-107", {
                "baseRevision": 2, "idempotencyKey": "article-graph-107",
                "patch": {"op": "set", "path": "/graph", "value": self.graph}
            })


if __name__ == "__main__":
    unittest.main()
