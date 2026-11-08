"""Studio #124: ArticleDocument CAS, Graph semantic safety and private media."""
import copy
import tempfile
import unittest
from pathlib import Path

from backend.db import Database
from backend.services import ServiceError, register_user
from backend.studio_projects import create_project, get_project, patch_project


class ArticleCanvasIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "studio124.sqlite3")
        self.db.migrate()
        self.owner, _ = register_user(self.db, "article_canvas124", "Pass12345!",
                                      "article124@example.com", "Article", "invite-a")
        self.stranger, _ = register_user(self.db, "article_stranger124", "Pass12345!",
                                         "stranger124@example.com", "Stranger", "invite-b")
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO media_assets
                (id, owner_user_id,storage_key,created_at)
                VALUES ('owned124',?,'/generated/owned124.png','2026-11-08')""",
                (self.owner["id"],))
            tx.execute("""INSERT INTO media_assets
                (id, owner_user_id,storage_key,created_at)
                VALUES ('foreign124',?,'/generated/foreign124.png','2026-11-08')""",
                (self.stranger["id"],))
        self.body = {
            "projectId": "issue124-article", "kind": "article", "authority": "article",
            "title": "浙江春天", "idempotencyKey": "create-article-124",
            "draft": {
                "article": {
                    "documentId": "doc-124", "revision": 4,
                    "markdown": "# 春天\n\n西湖龙井。",
                    "anchors": [
                        {"anchorId": "cover", "kind": "cover"},
                        {"anchorId": "paragraph-1", "offset": 11},
                    ]
                },
                "plan": {
                    "kind": "article", "planId": "plan-124", "revision": 1,
                    "documentId": "doc-124", "documentRevision": 4,
                    "slots": [
                        {"slotId": "cover-124", "anchorId": "cover", "overrides": {}},
                        {"slotId": "inline-124", "anchorId": "paragraph-1",
                         "referenceMedia": [{"mediaId": "owned124", "role": "scene"}],
                         "overrides": {}},
                    ]
                },
                "activeView": "simple",
                "editorLayout": {"runRefs": [{"runId": "run-124"}]},
            },
        }
        create_project(self.db, self.owner, copy.deepcopy(self.body))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def article(self):
        return get_project(self.db, self.owner, "issue124-article")["project"]

    def patch(self, rev, changes, key):
        return patch_project(self.db, self.owner, "issue124-article", {
            "baseRevision": rev, "idempotencyKey": key, "patch": changes})

    def expect_error(self, code, action):
        with self.assertRaises(ServiceError) as err:
            action()
        self.assertEqual(err.exception.code, code)

    def test_ten_canvas_switches_do_not_edit_article_anchor_plan_or_run(self):
        original = copy.deepcopy(self.article()["draft"])
        revision = 1
        for i in range(10):
            status = self.patch(revision, {"op": "set", "path": "/activeView",
                "value": "canvas" if i % 2 == 0 else "simple"},
                f"switch-article-{i:04d}")
            revision = status["revision"]
            current = self.article()["draft"]
            self.assertEqual(current["article"], original["article"])
            self.assertEqual(current["plan"], original["plan"])
            self.assertEqual(current["editorLayout"]["runRefs"],
                             original["editorLayout"]["runRefs"])
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_runs").fetchone()[0], 0)

    def test_outdated_planner_and_missing_anchor_fail_atomically(self):
        self.expect_error("article_revision_conflict", lambda: self.patch(1, {
            "op": "set", "path": "/plan/documentRevision", "value": 3},
            "old-plan-124"))
        self.expect_error("article_anchor_invalid", lambda: self.patch(1, {
            "op": "set", "path": "/plan/slots", "value": [
                {"slotId": "wrong-anchor", "anchorId": "absent"}]},
            "bad-anchor-124"))
        self.assertEqual(self.article()["revision"], 1)
        self.assertEqual(self.article()["draft"], self.body["draft"])

    def test_new_document_revision_and_plan_must_be_one_cas_batch(self):
        revised = copy.deepcopy(self.body["draft"]["article"])
        revised["revision"] = 5
        revised["markdown"] = "# 新文稿\n\n西湖的秋天。"
        self.expect_error("article_revision_conflict", lambda: self.patch(1, {
            "op": "set", "path": "/article", "value": revised},
            "partial-text-124"))
        good = self.patch(1, [
            {"op": "set", "path": "/article", "value": revised},
            {"op": "set", "path": "/plan/documentRevision", "value": 5},
        ], "atomic-article-124")
        self.assertEqual(good["revision"], 2)
        self.assertEqual(self.article()["draft"]["article"]["markdown"],
                         revised["markdown"])
        self.assertEqual(self.article()["draft"]["plan"]["documentRevision"], 5)
        self.expect_error("project_revision_conflict", lambda: self.patch(1, {
            "op": "set", "path": "/plan/documentRevision", "value": 3},
            "old-other-tab-124"))

    def test_foreign_media_does_not_become_project_or_public(self):
        self.expect_error("project_media_forbidden", lambda: self.patch(1, {
            "op": "set", "path": "/plan/slots", "value": [
                {"slotId": "inline-124", "anchorId": "paragraph-1",
                 "referenceMedia": [{"mediaId": "foreign124", "role": "scene"}]}]},
            "foreign-media-124"))
        original = self.article()["draft"]
        self.assertEqual(original["plan"]["slots"][1]["referenceMedia"][0]["mediaId"],
                         "owned124")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM works").fetchone()[0], 0)

    def test_complex_graph_ports_and_run_refs_are_not_simple_editable(self):
        graph = {
            "revision": 7, "blueprint": "custom", "nodes": [
                {"id": "text", "type": "text_input", "data": {"text": "正文"}},
                {"id": "skill", "type": "skill_params", "data": {"style1": "FA-001"}},
                {"id": "note", "type": "sticky_note", "data": {"text": "说明"}},
                {"id": "bridge", "type": "bridge", "data": {}},
                {"id": "loop", "type": "loop", "data": {"studio2SlotIds": ["s1"]}},
                {"id": "out1", "type": "output_control", "data": {"ratio": "3:4"}},
                {"id": "out2", "type": "output_control", "data": {"ratio": "9:16"}},
            ],
            "edges": [
                {"id": "typed-a", "from": "text", "to": "bridge",
                 "fromPort": "text", "toPort": "input"},
                {"id": "typed-b", "from": "bridge", "to": "out1",
                 "fromPort": "out", "toPort": "text"},
                {"id": "typed-c", "from": "loop", "to": "out2",
                 "fromPort": "item", "toPort": "prompt"},
            ],
            "groups": [{"id": "nested", "nodes": ["out1", "out2"]}],
            "runRefs": [{"runId": "run-a", "nodeId": "out1"}],
        }
        create_project(self.db, self.owner, {
            "projectId": "issue124-graph", "kind": "series", "authority": "graph",
            "idempotencyKey": "create-graph-124",
            "draft": {"graph": graph, "activeView": "canvas"}})
        def graph_patch():
            return patch_project(self.db, self.owner, "issue124-graph", {
                "baseRevision": 1, "idempotencyKey": "bad-graph-edit-124",
                "patch": {"op": "set", "path": "/graph/nodesById/text/data/text",
                          "value": "破坏了"}})
        self.expect_error("graph_field_read_only", graph_patch)
        project = get_project(self.db, self.owner, "issue124-graph")["project"]
        self.assertEqual(project["draft"]["graph"], graph)
        self.assertEqual(project["revision"], 1)


if __name__ == "__main__":
    unittest.main()
