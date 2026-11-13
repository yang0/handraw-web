"""Canvas combinations and frozen plans independent of other authoring forms."""

import copy
import unittest

from backend.canvas_runs import get_canvas_run
from backend.services import ServiceError, register_user
from backend.studio_canvases import (
    compile_canvas,
    save_canvas,
    get_canvas,
    preview_canvas,
    submit_canvas,
)
from backend.studio_execution import apply_source_input
from tests.postgres_support import open_isolated_postgres


def graph(*parameters, mode="cartesian", repeat=1):
    nodes = [
        {"id": name, "type": "parameter", "parameter": name, "values": values}
        for name, values in parameters
    ]
    nodes.append({"id": "out", "type": "output", "mode": mode, "repeat": repeat})
    return {
        "nodes": nodes,
        "edges": [{"from": name, "to": "out"} for name, _ in parameters],
    }


class CanvasCompilerTests(unittest.TestCase):
    def test_cartesian_repeat_and_stable_input_order(self):
        document = graph(
            ("prompt", ["A", "B", "C"]), ("ratio", ["3:4", "16:9"]), repeat=2
        )
        before = copy.deepcopy(document)
        rows = compile_canvas(document)
        self.assertEqual(len(rows), 12)
        self.assertEqual([row["ordinal"] for row in rows], list(range(12)))
        self.assertEqual(
            [row["spec"]["prompt"] for row in rows], ["A"] * 4 + ["B"] * 4 + ["C"] * 4
        )
        self.assertEqual(document, before)

    def test_zip_broadcast_and_mismatched_lengths(self):
        rows = compile_canvas(
            graph(("prompt", ["A", "B"]), ("ratio", ["3:4"]), mode="zip")
        )
        self.assertEqual(len(rows), 2)
        with self.assertRaises(ServiceError):
            compile_canvas(
                graph(
                    ("prompt", ["A", "B"]),
                    ("ratio", ["3:4", "16:9", "1:1"]),
                    mode="zip",
                )
            )

    def test_fusion_and_reference_groups_are_atomic(self):
        rows = compile_canvas(
            graph(
                ("prompt", ["A"]),
                ("style1", [{"style1": "FA-001", "style2": "FB-001"}, "FA-002"]),
                ("refImages", [["/images/a.webp", "/images/b.webp"], []]),
            )
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["spec"]["style2"], "FB-001")
        self.assertEqual(
            rows[0]["spec"]["refImages"], ["/images/a.webp", "/images/b.webp"]
        )

    def test_nested_zip_then_cross_and_multiple_outputs(self):
        document = graph(
            ("prompt", ["A", "B"]), ("layout", ["IG-001", "IG-002"]), mode="zip"
        )
        document["nodes"][-1] = {"id": "paired", "type": "combine", "mode": "zip"}
        for edge in document["edges"]:
            edge["to"] = "paired"
        document["nodes"] += [
            {
                "id": "ratio",
                "type": "parameter",
                "parameter": "ratio",
                "values": ["3:4", "1:1", "16:9"],
            },
            {"id": "out", "type": "output"},
            {"id": "second", "type": "output"},
        ]
        document["edges"] += [
            {"from": "paired", "to": "out"},
            {"from": "ratio", "to": "out"},
            {"from": "paired", "to": "second"},
        ]
        self.assertEqual(len(compile_canvas(document)), 8)

    def test_limits_cycles_conflicts_and_incomplete_plans_are_rejected(self):
        invalid = [
            graph(("prompt", ["A"] * 201)),
            graph(("prompt", ["A"] * 20), ("ratio", ["1:1"] * 11)),
            {"nodes": [], "edges": []},
            graph(("ratio", ["1:1"])),
        ]
        cycle = graph(("prompt", ["A"]))
        cycle["edges"].append({"from": "out", "to": "out"})
        invalid.append(cycle)
        conflict = graph(
            ("prompt", ["A"]),
            ("style1", [{"style1": "FA-001", "style2": "FB-001"}]),
            ("style2", ["FB-002"]),
        )
        invalid.append(conflict)
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(ServiceError):
                compile_canvas(document)


class CanvasPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self)
        self.user, _ = register_user(self.db, "canvas_owner", "FixturePass123!")

    def save(self, document=None, **extra):
        return save_canvas(
            self.db,
            self.user,
            {
                "id": "canvas",
                "graph": document or graph(("prompt", ["A", "B"])),
                **extra,
            },
        )

    def test_incomplete_draft_can_save_but_cannot_execute(self):
        self.save({"nodes": [], "edges": []})
        self.assertEqual(
            get_canvas(self.db, self.user, "canvas")["canvas"]["graph"]["nodes"], []
        )
        with self.assertRaises(ServiceError):
            preview_canvas(self.db, self.user, "canvas")
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM generation_runs")
            .fetchone()[0],
            0,
        )

    def test_owner_and_concurrent_save_guards(self):
        self.save()
        with self.assertRaises(ServiceError):
            self.save(graph(("prompt", ["Changed elsewhere"])))
        other, _ = register_user(self.db, "other_canvas", "FixturePass123!")
        with self.assertRaises(ServiceError):
            get_canvas(self.db, other, "canvas")
        with self.assertRaises(ServiceError):
            self.save(articleId="article", baseWriteSeq=1)
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_articles")
            .fetchone()[0],
            0,
        )

    def test_submit_freezes_selection_and_replays_after_canvas_edit(self):
        self.save()
        preview = preview_canvas(self.db, self.user, "canvas")
        body = {
            "requestId": "canvas_run",
            "planHash": preview["planHash"],
            "ordinals": [1],
        }
        first = submit_canvas(self.db, self.user, "canvas", body)
        self.assertEqual(first["count"], 1)
        self.assertEqual(first["items"][0]["spec"]["prompt"], "B")
        self.save(graph(("prompt", ["Edited"])), baseWriteSeq=1)
        self.assertEqual(submit_canvas(self.db, self.user, "canvas", body), first)
        with self.assertRaises(ServiceError):
            submit_canvas(self.db, self.user, "canvas", {**body, "ordinals": [0]})
        payload = {
            "canvasId": "canvas",
            "creationSource": "canvas",
            "batchId": "canvas_run",
            "batchIndex": 0,
        }
        with self.assertRaises(ServiceError):
            apply_source_input(self.db, self.user, payload)
        self.db.get_conn().execute(
            "UPDATE generation_items SET dispatch_token='fixture',dispatch_until=now()+interval '1 minute' WHERE run_id=?",
            (first["runId"],),
        )
        payload["_canvasDispatchToken"] = "fixture"
        apply_source_input(self.db, self.user, payload)
        self.assertEqual(payload["prompt"], "B")
        with self.assertRaises(ServiceError):
            apply_source_input(self.db, self.user, {**payload, "prompt": "Tampered"})
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM generation_items")
            .fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_generations")
            .fetchone()[0],
            0,
        )

    def test_run_reports_frozen_output_nodes_for_nonconsecutive_selection(self):
        document = graph(("prompt", ["A", "B"]))
        document["nodes"].append({"id": "second", "type": "output"})
        document["edges"].append({"from": "prompt", "to": "second"})
        self.save(document)
        preview = preview_canvas(self.db, self.user, "canvas")
        result = submit_canvas(
            self.db,
            self.user,
            "canvas",
            {
                "requestId": "selected_outputs",
                "planHash": preview["planHash"],
                "ordinals": [1, 3],
            },
        )
        self.save(graph(("prompt", ["Changed"])), baseWriteSeq=1)
        run = get_canvas_run(self.db, self.user, result["runId"])["run"]
        self.assertEqual(
            [
                (item["ordinal"], item["outputNodeId"], item["spec"]["prompt"])
                for item in run["items"]
            ],
            [(0, "out", "B"), (1, "second", "B")],
        )

    def test_changed_preview_rejects_before_tasks_or_billing(self):
        self.save()
        preview = preview_canvas(self.db, self.user, "canvas")
        self.save(graph(("prompt", ["Edited"])), baseWriteSeq=1)
        with self.assertRaises(ServiceError):
            submit_canvas(
                self.db,
                self.user,
                "canvas",
                {"requestId": "stale", "planHash": preview["planHash"]},
            )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM generation_runs")
            .fetchone()[0],
            0,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT free_quota_used FROM wallets WHERE user_id=?",
                (self.user["id"],),
            )
            .fetchone()[0],
            0,
        )
