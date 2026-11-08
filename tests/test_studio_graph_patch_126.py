"""#126 GraphPatch: secure preview, arbitrary structural edits, CAS, undo."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import Database
from backend.services import ServiceError, register_user
from backend.studio_projects import create_project, get_project, patch_project
from backend.studio_graph_patch import preview, apply, undo


SENTINEL = "PRIVATE_GRAPH_CONTENT_NOT_FOR_MODEL"
PROJECT = "graphpatch-126-project"


def fixture():
    return {
        "revision": 7, "blueprint": "single", "selectedIds": [],
        "nodes": [
            {"id": "gp_text", "type": "text_input", "x": 60, "y": 100,
             "data": {"text": SENTINEL}},
            {"id": "gp_style", "type": "skill_params", "x": 90, "y": 80,
             "data": {"style1": "", "layout": ""}},
            {"id": "gp_control", "type": "output_control", "x": 450, "y": 130,
             "data": {"count": 1, "ratio": "3:4", "mode": "graphic-text"}},
            {"id": "gp_result", "type": "output_display", "x": 870, "y": 130,
             "data": {"items": [{"imageUrl": "/starter/bear-and-bird.webp"}],
                      "runId": "old-run-stable", "status": "success"}},
        ],
        "edges": [
            {"id": "gp_edge_text", "from": "gp_text", "to": "gp_control"},
            {"id": "gp_edge_style", "from": "gp_style", "to": "gp_control"},
            {"id": "gp_edge_result", "from": "gp_control", "to": "gp_result"},
        ],
    }


class GraphPatch126Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "qa126.sqlite")
        self.db.migrate()
        self.user, _ = register_user(self.db, "gp_qa_alice", "Pass12345!")
        self.other, _ = register_user(self.db, "gp_qa_bob", "Pass12345!")
        create_project(self.db, self.user, {
            "projectId": PROJECT, "idempotencyKey": "create-graphpatch-126",
            "kind": "image", "authority": "graph", "title": "QA GraphPatch",
            "draft": {"graph": fixture(), "activeView": "canvas"},
        })

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def call_preview(self, **extra):
        return preview(self.db, self.user, {
            "projectId": PROJECT,
            "baseRevision": 1,
            "graphRevision": 7,
            **extra,
        })

    def test_three_preset_templates_and_review_only(self):
        for preset, added in (("seasons", 8), ("platforms", 3),
                              ("style_compare", 4)):
            params = {"mode": "preset", "preset": preset,
                      "selectedIds": ["gp_result"]}
            if preset == "style_compare":
                params["styleIds"] = ["FA-001", "FA-002"]
            plan = self.call_preview(**params)
            self.assertTrue(plan["canApply"], plan)
            self.assertEqual(plan["phase"], "review")
            self.assertEqual(plan["summary"]["nodesAdded"], added)
            self.assertGreater(plan["costImpact"]["estimatedAdditionalCredits"], 0)
            self.assertFalse(plan["costImpact"]["chargedNow"])
            self.assertEqual(get_project(self.db, self.user, PROJECT)
                             ["project"]["revision"], 1)
            self.assertEqual(len(get_project(self.db, self.user, PROJECT)
                                 ["project"]["draft"]["graph"]["nodes"]), 4)

    def test_apply_and_one_click_undo_idempotent_no_run_mutation(self):
        data = self.call_preview(mode="preset", preset="seasons")
        with self.assertRaises(ServiceError) as ctx:
            apply(self.db, self.user, {"reviewId": data["reviewId"]})
        self.assertEqual(ctx.exception.code, "graphpatch_confirmation_required")
        result = apply(self.db, self.user,
                       {"reviewId": data["reviewId"], "confirmed": True})
        self.assertEqual(result["phase"], "applied")
        self.assertEqual(result["projectRevision"], 2)
        self.assertEqual(len(result["graph"]["nodes"]), 12)
        self.assertEqual(result["graph"]["revision"], 8)
        self.assertEqual(apply(self.db, self.user,
                               {"reviewId": data["reviewId"], "confirmed": True}), result)
        preserved = next(n for n in result["graph"]["nodes"] if n["id"] == "gp_result")
        self.assertEqual(preserved["data"]["runId"], "old-run-stable")
        self.assertEqual(preserved["data"]["items"][0]["imageUrl"],
                         "/starter/bear-and-bird.webp")
        undone = undo(self.db, self.user,
                      {"reviewId": data["reviewId"], "confirmed": True})
        self.assertEqual(undone["projectRevision"], 3)
        self.assertEqual(undone["graphRevision"], 9)
        self.assertEqual(len(undone["graph"]["nodes"]), 4)
        self.assertEqual(next(n for n in undone["graph"]["nodes"] if n["id"] == "gp_result"),
                         fixture()["nodes"][-1])
        self.assertTrue(undo(self.db, self.user, {"reviewId": data["reviewId"],
                                                "confirmed": True})["alreadyReverted"])

    def test_schema_edges_cycle_and_structural_delete(self):
        bad_edges = [
            {"op": "addEdge",
             "edge": {"id": "gp_reverse", "from": "gp_control", "to": "gp_text"}},
            {"op": "addEdge",
             "edge": {"id": "gp_reverse", "from": "gp_result", "to": "gp_control"}},
            {"op": "addNode", "node": {"id": "gp_tamper",
                "type": "output_display", "data": {}}},
            {"op": "setNodeData", "id": "gp_result",
             "field": "items", "value": []},
            {"op": "setNodeData", "id": "gp_control",
             "field": "runId", "value": "tampered"},
        ]
        for op in bad_edges:
            with self.subTest(op=op), self.assertRaises(ServiceError):
                self.call_preview(mode="operations", operations=[op])
        # A true cycle between output controls must be rejected.
        with self.assertRaises(ServiceError) as ctx:
            self.call_preview(mode="operations", operations=[
                {"op": "addNode", "node": {
                    "id": "anotherCtrl", "type": "output_control", "data":
                    {"ratio": "3:4", "count": 1}}},
                {"op": "addEdge", "edge": {"id": "new1",
                 "from": "gp_control", "to": "anotherCtrl"}},
                {"op": "addEdge", "edge": {"id": "new2",
                 "from": "anotherCtrl", "to": "gp_control"}},
            ])
        self.assertEqual(ctx.exception.code, "graphpatch_cycle")

        # Explicitly remove connected edge before removing unused input.
        changes = [
            {"op": "removeEdge", "id": "gp_edge_style"},
            {"op": "removeNode", "id": "gp_style"},
        ]
        plan = self.call_preview(mode="operations", operations=changes)
        self.assertTrue(plan["canApply"])
        saved = apply(self.db, self.user, {"reviewId": plan["reviewId"],
                                          "confirmed": True})
        self.assertFalse(any(n["id"] == "gp_style" for n in saved["graph"]["nodes"]))
        self.assertFalse(any(e["id"] == "gp_edge_style" for e in saved["graph"]["edges"]))

    def test_locked_field_visible_conflict_then_cannot_apply(self):
        with self.db.transaction() as tx:
            old = tx.execute("SELECT draft_json FROM studio_projects WHERE id=?",
                             (PROJECT,)).fetchone()
            draft = json.loads(old["draft_json"])
            draft["graph"]["nodes"][0]["data"]["lockedFields"] = ["subject"]
            tx.execute("UPDATE studio_projects SET draft_json=? WHERE id=?",
                       (json.dumps(draft), PROJECT))
        report = self.call_preview(mode="operations", operations=[
            {"op": "setNodeData", "id": "gp_text", "field": "text",
             "value": "new secret replacement"},
        ])
        self.assertFalse(report["canApply"])
        self.assertEqual(report["conflicts"][0]["code"], "locked_field")
        with self.assertRaises(ServiceError) as ctx:
            apply(self.db, self.user, {"reviewId": report["reviewId"],
                                      "confirmed": True})
        self.assertEqual(ctx.exception.code, "graphpatch_locked_field")

    def test_media_owner_and_resource_auth_no_leak(self):
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO user_uploads
                (id,user_id,cat,name_zh,image_url,created_at,asset_uid)
                VALUES (?,?,?,'PRIVATE','/private/foo.webp','2026-11-08',?)""",
                ("foreign", self.other["id"], "scenes", "private-bob-asset"))
        with self.assertRaises(ServiceError) as ctx:
            self.call_preview(mode="operations", operations=[
                {"op": "addNode", "node": {
                    "id": "gp_private", "type": "asset", "data": {
                        "items": [{"mediaId": "private-bob-asset", "role": "scene"}]}}},
            ])
        self.assertEqual(ctx.exception.code, "project_media_forbidden")
        with self.assertRaises(ServiceError):
            self.call_preview(mode="operations", operations=[
                {"op": "setNodeData", "id": "gp_style",
                 "field": "style1", "value": "INVALID-STYLE"},
            ])
        with self.assertRaises(ServiceError) as forbidden:
            preview(self.db, self.other, {"projectId": PROJECT,
                "baseRevision": 1, "graphRevision": 7,
                "mode": "preset", "preset": "platforms"})
        self.assertEqual(forbidden.exception.status, 404)
        record = self.call_preview(mode="preset", preset="platforms")
        with self.assertRaises(ServiceError) as forbidden:
            apply(self.db, self.other,
                  {"reviewId": record["reviewId"], "confirmed": True})
        self.assertEqual(forbidden.exception.status, 404)

    def test_cas_stale_review_and_undo_cannot_clobber_newer_edit(self):
        plan = self.call_preview(mode="preset", preset="platforms")
        patch_project(self.db, self.user, PROJECT, {
            "baseRevision": 1, "idempotencyKey": "cas-update-before-graphpatch",
            "patch": {"op": "set", "path": "/activeView", "value": "simple"},
        })
        with self.assertRaises(ServiceError) as ctx:
            apply(self.db, self.user,
                  {"reviewId": plan["reviewId"], "confirmed": True})
        self.assertEqual(ctx.exception.code, "project_revision_conflict")

        newer = preview(self.db, self.user, {"projectId": PROJECT,
            "baseRevision": 2, "graphRevision": 7,
            "mode": "preset", "preset": "platforms"})
        result = apply(self.db, self.user, {"reviewId": newer["reviewId"],
                                           "confirmed": True})
        patch_project(self.db, self.user, PROJECT, {
            "baseRevision": result["projectRevision"],
            "idempotencyKey": "cas-edit-after-graphpatch",
            "patch": {"op": "set", "path": "/activeView", "value": "canvas"},
        })
        with self.assertRaises(ServiceError) as ctx:
            undo(self.db, self.user, {"reviewId": newer["reviewId"],
                                     "confirmed": True})
        self.assertEqual(ctx.exception.code, "graphpatch_undo_conflict")

    def test_ai_exposes_only_graph_structure_not_private_source_data(self):
        observed = []
        def chat(messages, **kwargs):
            self.assertFalse(self.db.get_conn().in_transaction,
                             "LLM request must not hold a DB write transaction")
            observed.append(json.dumps(messages, ensure_ascii=False))
            return (json.dumps({"operations": [
                {"op": "addNode", "node": {
                    "id": "gp_ai_input", "type": "text_input", "x": 650, "y": 30,
                    "data": {"text": "新创作场景"}}},
            ]}, ensure_ascii=False), {"ok": True})
        with patch("backend.ai_client.chat", side_effect=chat):
            report = self.call_preview(mode="ai", instruction="为画布增加一条文案输入")
        self.assertTrue(report["canApply"])
        self.assertNotIn(SENTINEL, observed[0])
        self.assertNotIn("old-run-stable", observed[0])
        self.assertNotIn("bear-and-bird.webp", observed[0])
        self.assertIn("authorizedResources", observed[0])
        self.assertIn("FA-001", observed[0])
        self.assertNotIn("secretBlackboxPrompt", observed[0])
        self.assertEqual(get_project(self.db, self.user, PROJECT)
                         ["project"]["revision"], 1)


    def test_ai_stale_result_after_parallel_project_edit_is_rejected(self):
        def chat(messages, **kwargs):
            self.assertFalse(self.db.get_conn().in_transaction)
            patch_project(self.db, self.user, PROJECT, {
                "baseRevision": 1, "idempotencyKey": "ai-midflight-other-editor",
                "patch": {"op": "set", "path": "/activeView", "value": "simple"},
            })
            return (json.dumps({"operations": [{"op": "addNode", "node": {
                "id": "stale_ai_text", "type": "text_input",
                "data": {"text": "stale suggestion"}}}]}), {"ok": True})
        with patch("backend.ai_client.chat", side_effect=chat):
            with self.assertRaises(ServiceError) as error:
                self.call_preview(mode="ai", instruction="添加新的输入节点")
        self.assertEqual(error.exception.code, "project_revision_conflict")
        self.assertEqual(get_project(self.db, self.user, PROJECT)
                         ["project"]["revision"], 2)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM studio_graphpatch_reviews").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
