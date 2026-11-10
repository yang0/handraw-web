"""#132: no example/template may pretend to be a signed production D record."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from ops.studio_d_environment_assertions_132 import GATES, ORIGINS, evaluate as validate_d
from ops.studio_d_receipt_contract_132 import (
    GATES as RECEIPT_GATES, PROVIDER_FIELDS, PG_FIELDS, STORAGE_FIELDS,
)
from ops.studio_editorial_rights_132 import CODES, index_reviews

ROOT = Path(__file__).resolve().parents[1]
T = ROOT/"ops/templates"
WEB = "a"*40
SKILL = "b"*40


class Phase20PrivateTemplateContractTest(unittest.TestCase):
    def read(self, name):
        return json.loads((T/name).read_text(encoding="utf-8"))

    def test_d_matrix_has_exactly_17_pending_cases_never_pass_by_copying(self):
        data=self.read("studio_d_real_evidence_132.json")
        self.assertEqual(len(data["cases"]),17)
        self.assertEqual({r["caseId"] for r in data["cases"]},set(GATES))
        self.assertEqual({r["caseId"]:r["origin"] for r in data["cases"]},ORIGINS)
        self.assertTrue(all(r["status"]=="PENDING" for r in data["cases"]))
        self.assertTrue(all(r["isSimulation"] and not r["physicalOrRealProviderClaim"]
                            for r in data["cases"]))
        with self.assertRaises(ValueError):
            validate_d(data,web_sha=WEB,skill_sha=SKILL)

    def test_three_receipt_templates_are_neither_runnable_nor_secret_bearing(self):
        data=self.read("studio_d_critical_receipts_132.json")
        self.assertEqual({r["kind"]:r["caseId"] for r in data["receipts"]},
                         RECEIPT_GATES)
        fields={"provider":PROVIDER_FIELDS,"postgres":PG_FIELDS,
                "storage":STORAGE_FIELDS}
        for row in data["receipts"]:
            self.assertEqual(set(row["details"]),fields[row["kind"]])
            self.assertIn("REPLACE",row["evidenceDigestSha256"])
        self.assertNotIn("Bearer ",json.dumps(data))
        self.assertNotIn("AKIA",json.dumps(data))

    def test_three_rights_templates_stay_pending_and_do_not_auto_approve(self):
        data=self.read("studio_official_rights_review_132.json")
        pending=json.loads((ROOT/"ops/official_catalog_pending_11.json")
                           .read_text(encoding="utf-8"))
        reference={r["code"]:r for r in pending["pendingSkillOnly"]}
        self.assertEqual({r["candidateCode"] for r in data["reviews"]},set(CODES))
        for row in data["reviews"]:
            self.assertEqual(row["skillSourceSha256"],
                             reference[row["candidateCode"]]["sha256"])
            self.assertEqual(row["reviewDecision"],"pending")
            for asset in row["assets"]:
                self.assertFalse(asset["commercialReuseAllowed"])
                self.assertFalse(asset["derivativeUseAllowed"])
                self.assertFalse(asset["officialWebsitePublishAllowed"])
        with self.assertRaises(ValueError):
            index_reviews(data,reference)


if __name__=="__main__":
    unittest.main()
