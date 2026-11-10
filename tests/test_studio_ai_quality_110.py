"""Issue #110: reproducible *offline* AI planning quality gate.

The mock chooses labelled resources and gives deterministic legal responses.
The scorer is also tested with tampered, biased and inconsistent replays.
This cannot establish actual recommendation quality of a live AI model.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import Database
from backend.services import register_user
from backend.studio_ai_plan import _user_catalog, execute_ai_plan
from ops.eval_studio_ai_quality_110 import DEFAULT_CORPUS, evaluate

CORPUS = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))


class AIQuality110Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "quality110.sqlite")
        self.db.migrate()
        self.user, _ = register_user(self.db, "quality110_qa_user", "Pass12345!")
        self.allowed = _user_catalog(self.db, self.user)
        self.assertGreater(len(self.allowed["style"]), 6)
        self.assertGreater(len(self.allowed["layout"]), 6)
        self.records = []

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def replay(self):
        cases = CORPUS["cases"]
        self.assertEqual(len(cases), 6)
        self.assertEqual({c["kind"] for c in cases},
                         {"image", "series", "article"})
        for case in cases:
            for trial in (1, 2):
                # This input is a user-authored fixture.  No model API call,
                # generation/credit mutation or external service is involved.
                request = {"kind": case["kind"], "subject": case["subject"],
                           "baseRevision": 0, "count": case["count"],
                           "current": {}, "lockedFields": []}
                if case["kind"] in ("series", "article"):
                    request["planRevision"] = 1
                    request["currentSlots"] = [
                        {"slotId": f"fixed-{case['id']}-{i}"}
                        for i in range(case["count"])]
                if case["kind"] == "article":
                    request["blocks"] = case["blocks"]

                def model(messages, **kwargs):
                    self.assertTrue(kwargs["json_mode"])
                    prompt = json.loads(messages[-1]["content"])
                    allowed_styles = {s["id"] for s in prompt["allowedStyles"]}
                    allowed_layouts = {s["id"] for s in prompt["allowedLayouts"]}
                    style = case["expectedStyleIds"][0]
                    layout = case["expectedLayoutIds"][0]
                    self.assertIn(style, allowed_styles)
                    self.assertIn(layout, allowed_layouts)
                    response = {
                        "styleId": style, "layoutId": layout,
                        "ratio": case["ratio"],
                        "reasons": {
                            "style": "场景主题匹配",
                            "layout": "结构和阅读节奏匹配",
                            "ratio": "契合使用场景",
                        },
                        "slots": [],
                    }
                    for idx in range(case["count"] if case["kind"] != "image" else 0):
                        item = {"subject": f"{case['subject']} · {idx+1}",
                                "layoutId": layout, "ratio": case["ratio"],
                                "reason": f"第{idx+1}张场景构图说明"}
                        if case["kind"] == "article":
                            item["role"] = "cover" if idx == 0 else "illustration"
                            item["afterBlockIdx"] = -1 if idx == 0 else \
                                case["blocks"][idx-1]["idx"]
                        response["slots"].append(item)
                    return json.dumps(response, ensure_ascii=False), {"ok": True}

                with patch("backend.studio_ai_plan.chat", side_effect=model):
                    result = execute_ai_plan(self.db, self.user, request)
                self.records.append({
                    "caseId": case["id"], "trial": trial, "response": result,
                })
        return self.records

    def test_six_scenarios_offline_positive_and_nonbilling(self):
        outputs = self.replay()
        result = evaluate(CORPUS, outputs, self.allowed)
        self.assertTrue(result["ok"], result)
        metrics = result["metrics"]
        self.assertEqual(metrics["cases"], 6)
        self.assertEqual(metrics["validResponses"], 12)
        self.assertEqual(metrics["editorialFit"], 1.0)
        self.assertEqual(metrics["diversity"], 1.0)
        self.assertEqual(metrics["consistency"], 1.0)
        self.assertTrue(result["notLiveModelEvidence"])
        conn = self.db.get_conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM generation_runs").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM generation_items").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM works").fetchone()[0], 0)
        report = Path("artifacts/ai-110-offline-eval.json")
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({
            "source": "mock_gateway_handlabelled_fixture",
            "realModelQualityVerified": False, **result
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_replay_rejects_bias_and_inconsistent_layout(self):
        outputs = self.replay()
        repeated = copy.deepcopy(outputs)
        common = repeated[0]["response"]["creationSpecPatch"]["changes"]["style"]
        for row in repeated:
            row["response"]["creationSpecPatch"]["changes"]["style"] = common
        result = evaluate(CORPUS, repeated, self.allowed)
        self.assertFalse(result["ok"])
        self.assertLess(result["metrics"]["diversity"], .65)
        self.assertLess(result["metrics"]["editorialFit"], .85)
        # One changed trial among six independent themes is visible as drift.
        inconsistent = copy.deepcopy(outputs)
        first = inconsistent[0]["response"]["creationSpecPatch"]["changes"]
        first["layout"] = inconsistent[2]["response"]["creationSpecPatch"]["changes"]["layout"]
        result = evaluate(CORPUS, inconsistent, self.allowed)
        self.assertFalse(result["ok"])
        self.assertLess(result["metrics"]["consistency"], .90)

    def test_replay_rejects_unknown_alternative_invalid_json_and_missing_trial(self):
        outputs = self.replay()
        cases = [
            # Unknown IDs cannot masquerade as authorized selections.
            (lambda x: x[0]["response"]["creationSpecPatch"]["changes"]
             .update({"style": {"id": "FA-ILLEGAL-999"}})),
            # Model may not return a duplicate or fabricated alternative.
            (lambda x: x[0]["response"]["creationSpecPatch"]["candidates"]
             ["layout"].append({"id": "UNAUTHORIZED", "type": "layout"})),
            # Rejected malformed normalization / non-JSON fallback.
            (lambda x: x[0].update({"response": {"error": "upstream_502"}})),
        ]
        for tamper in cases:
            modified = copy.deepcopy(outputs)
            tamper(modified)
            self.assertFalse(evaluate(CORPUS, modified, self.allowed)["ok"])
        self.assertFalse(evaluate(CORPUS, outputs[:-1], self.allowed)["ok"])
        broken = copy.deepcopy(outputs)
        broken[0]["response"]["creationSpecPatch"]["reasons"].pop("layout")
        self.assertFalse(evaluate(CORPUS, broken, self.allowed)["ok"])

    def test_corpus_references_current_real_catalog_not_hardcoded_fallback(self):
        for case in CORPUS["cases"]:
            self.assertTrue(set(case["expectedStyleIds"]).issubset(
                {s["id"] for s in self.allowed["style"]}))
            self.assertTrue(set(case["expectedLayoutIds"]).issubset(
                {s["id"] for s in self.allowed["layout"]}))
        all_style_labels = [c["expectedStyleIds"][0] for c in CORPUS["cases"]]
        self.assertEqual(len(set(all_style_labels)), len(all_style_labels),
                         "benchmark needs distinct expected styles across scenarios")


if __name__ == "__main__":
    unittest.main()
