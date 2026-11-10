"""#132: 17 D-level environment cases never certify themselves as real."""
from __future__ import annotations

from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest

from ops.studio_d_environment_assertions_132 import GATES,ORIGINS,evaluate,main
from ops.studio_release_d_attestation_112 import GROUPS

WEB="a"*40
SKILL="b"*40
NOW=datetime(2026,11,10,0,0,tzinfo=timezone.utc)


def sample():
    return {
        "schemaVersion":1,"environment":"preproduction",
        "deployedSha":WEB,"skillSha":SKILL,
        "cases":[{
            "caseId":g,"status":"PASS","origin":ORIGINS[g],
            "evidenceDigestSha256":format(i+1,"064x"),
            "evidenceId":f"synthetic-witness-{i+1:03d}",
            "environmentId":"test-only-not-real",
            "deployedSha":WEB,"skillSha":SKILL,
            "observedAtUtc":"2026-11-09T23:00:00Z",
            "operator":"synthetic-operator","reviewer":"synthetic-reviewer",
            "isSimulation":False,"physicalOrRealProviderClaim":True,
        } for i,g in enumerate(GATES)],
    }


class RealEnvironmentAssertionContractTests(unittest.TestCase):
    def test_missing_all_cannot_go(self):
        out=evaluate(None,web_sha=WEB,skill_sha=SKILL,now=NOW)
        self.assertEqual(len(GATES),17)
        self.assertIn("editorial_ff019",GROUPS[11])
        self.assertEqual(out["claimedPassCount"],0)
        self.assertEqual(out["statusByCase"]["editorial_ff019"],"MISSING")
        self.assertEqual(out["decision"],"NO-GO")

    def test_even_all_self_claimed_real_is_unverified_no_go(self):
        out=evaluate(sample(),web_sha=WEB,skill_sha=SKILL,now=NOW)
        self.assertEqual(out["claimedPassCount"],17)
        self.assertTrue(out["allCasesClaimPass"])
        self.assertTrue(out["readyForIndependentOnSiteReview"])
        self.assertFalse(out["independentEvidenceAuthenticityVerified"])
        self.assertFalse(out["physicalProviderActuallyConnectedByTool"])
        self.assertFalse(out["autoReleaseAuthorized"])
        self.assertFalse(out["issueClosureAuthorized"])
        self.assertEqual(out["decision"],"NO-GO")
        self.assertNotIn("synthetic-witness",json.dumps(out))
        self.assertNotIn("synthetic-operator",json.dumps(out))

    def test_mock_provider_and_inaccurate_claims_fail_closed(self):
        for field,value in [
            ("origin","moto-s3"),
            ("isSimulation",True),
            ("physicalOrRealProviderClaim",False),
            ("deployedSha","c"*40),
            ("skillSha","c"*40),
            ("evidenceDigestSha256","fake"),
            ("reviewer","synthetic-operator"),
            ("observedAtUtc","2025-01-01T00:00:00Z"),
        ]:
            data=sample()
            data["cases"][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate(data,web_sha=WEB,skill_sha=SKILL,now=NOW)

    def test_duplicate_or_unknown_gate_and_bearer_field_fail_closed(self):
        data=sample()
        data["cases"][0]["caseId"]=data["cases"][1]["caseId"]
        with self.assertRaises(ValueError):
            evaluate(data,web_sha=WEB,skill_sha=SKILL,now=NOW)
        data=sample()
        data["cases"][0]["bearer"]="CANARY_SECRET"
        with self.assertRaises(ValueError):
            evaluate(data,web_sha=WEB,skill_sha=SKILL,now=NOW)
        data=sample()
        data["cases"][0]["evidenceId"]=data["cases"][1]["evidenceId"]
        with self.assertRaises(ValueError):
            evaluate(data,web_sha=WEB,skill_sha=SKILL,now=NOW)

    def test_each_of_17_origin_claims_fail_closed_individually(self):
        self.assertEqual(len(GATES),17)
        self.assertEqual(len(ORIGINS),17)
        for i,gate in enumerate(GATES):
            with self.subTest(gate=gate):
                for field,bad in (
                    ("origin","ci-moto-simulated"),
                    ("isSimulation",True),
                    ("physicalOrRealProviderClaim",False),
                    ("status","UNVERIFIED"),
                    ("deployedSha","f"*40),
                    ("reviewer","synthetic-operator"),
                ):
                    case=sample()
                    case["cases"][i][field]=bad
                    with self.subTest(gate=gate,field=field),self.assertRaises(ValueError):
                        evaluate(case,web_sha=WEB,skill_sha=SKILL,now=NOW)

    def test_reusing_same_private_evidence_bytes_for_distinct_gates_is_blocked(self):
        case=sample()
        case["cases"][1]["evidenceDigestSha256"]=case["cases"][0]["evidenceDigestSha256"]
        with self.assertRaisesRegex(ValueError,"digest"):
            evaluate(case,web_sha=WEB,skill_sha=SKILL,now=NOW)

    def test_partial_inputs_cannot_be_marked_complete(self):
        data=sample()
        data["cases"]=data["cases"][:-4]
        out=evaluate(data,web_sha=WEB,skill_sha=SKILL,now=NOW)
        self.assertEqual(out["claimedPassCount"],13)
        self.assertFalse(out["allCasesClaimPass"])
        self.assertEqual(out["decision"],"NO-GO")

    def test_cli_no_claims_write_only_new_restricted_redacted_file(self):
        with tempfile.TemporaryDirectory() as root:
            report=Path(root)/"external-no-go.json"
            args=["--web-sha",WEB,"--skill-sha",SKILL,"--report",str(report)]
            self.assertEqual(main(args),0)
            self.assertEqual(json.loads(report.read_text())["decision"],"NO-GO")
            self.assertEqual(main(args),2)


if __name__=="__main__":
    unittest.main()
