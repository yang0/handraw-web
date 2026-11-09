"""#11/#84/#112 Phase12 preflight: no auto approvals or source mutations."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from ops.phase12_release_preflight_112 import (
    prepare, pending_summary, EXPECTED_PENDING, MANUAL_GATES,
)

ROOT=Path(__file__).resolve().parents[1]


class Phase12ReleasePreflight(unittest.TestCase):
    def test_known_skill_only_stays_unapproved(self):
        manifest=json.loads((ROOT/"ops/official_catalog_pending_11.json")
                            .read_text(encoding="utf-8"))
        result=pending_summary(manifest)
        self.assertEqual(set(result),set(EXPECTED_PENDING))
        self.assertTrue(all(x["state"]=="awaiting_website_editorial_review"
                            for x in result.values()))
        for code in result:
            self.assertEqual(result[code]["issue"],11)

    def test_wrong_state_duplicate_or_missing_proposal_fails_closed(self):
        raw=json.loads((ROOT/"ops/official_catalog_pending_11.json")
                       .read_text(encoding="utf-8"))
        raw["pendingSkillOnly"][0]["state"]="approved"
        with self.assertRaises(ValueError):
            pending_summary(raw)
        raw["pendingSkillOnly"][0]["state"]="awaiting_website_editorial_review"
        raw["pendingSkillOnly"].append(dict(raw["pendingSkillOnly"][0]))
        with self.assertRaises(ValueError):
            pending_summary(raw)
        raw["pendingSkillOnly"]=raw["pendingSkillOnly"][:1]
        with self.assertRaises(ValueError):
            pending_summary(raw)

    def test_ci_preflight_does_not_claim_real_external_release(self):
        secret="CANARY_SECRET_DO_NOT_PERSIST"
        with patch.dict(os.environ,{"AWS_SECRET_ACCESS_KEY":secret,
              "HANDRAW_PG_STAGING_URL":"postgresql://foo:"+secret+"@host/db"}):
            report=prepare(ROOT)
        self.assertTrue(report["productionNoGo"])
        self.assertFalse(report["readyForRelease"])
        self.assertFalse(report["catalog"]["strictReleaseParityProven"])
        self.assertFalse(report["existingCi"]["realStorageProviderProven"])
        self.assertFalse(report["existingCi"]["realPaymentRefundProven"])
        self.assertFalse(report["existingCi"]["redisMultiInstanceProven"])
        self.assertEqual(len(report["manualGates"]),len(MANUAL_GATES))
        self.assertNotIn(secret,json.dumps(report))


if __name__=="__main__":
    unittest.main()
