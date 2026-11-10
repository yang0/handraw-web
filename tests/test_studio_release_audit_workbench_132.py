"""#132 unified audit workbench: synthetic/empty inputs NEVER authorize release."""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.studio_d_environment_assertions_132 import GATES
from ops.studio_release_audit_workbench_132 import (
    evaluate, main, render_html,
)
from test_studio_phase24_release_join_132 import (
    WEB, SKILL, fixture,
)


class StudioReleaseAuditWorkbenchTest(unittest.TestCase):
    def test_empty_evidence_makes_17_case_private_no_go_dashboard(self):
        report=evaluate(web_sha=WEB, skill_sha=SKILL)
        self.assertEqual(report["decision"], "NO-GO")
        self.assertFalse(report["releaseAuthorized"])
        self.assertFalse(report["sourceAuthenticityIndependentlyVerified"])
        self.assertEqual(report["verifiedRealDPassCount"], 0)
        self.assertEqual(report["claimedPassCount"], 0)
        self.assertEqual(report["requiredDCaseCount"], 17)
        self.assertEqual(len(report["dCaseStates"]), len(GATES))
        self.assertEqual(set(report["dCaseStates"].values()), {"MISSING"})
        self.assertEqual(len(report["detailedReceiptCoverage"]), 3)
        self.assertEqual(len(report["independentWitnessCoverage"]), 5)
        self.assertEqual(len(report["officialCandidateApproval"]), 3)
        self.assertEqual(len(report["missingInputs"]), 6)
        html=render_html(report)
        self.assertEqual(html.count("<td>MISSING</td>"), 25)
        self.assertIn("FF-019",html)
        self.assertIn("NO-GO",html)
        self.assertIn("Content-Security-Policy",html)
        self.assertNotIn("<script",html)
        self.assertNotIn("http://",html)
        self.assertNotIn("https://",html)

    def test_all_claims_are_never_real_d_pass_without_external_authenticity(self):
        claims,receipts,field,registry,proofs,anchor,now=fixture()
        report=evaluate(claims, web_sha=WEB, skill_sha=SKILL, now=now)
        self.assertEqual(report["claimedPassCount"],17)
        self.assertEqual(set(report["dCaseStates"].values()),
                         {"CLAIMED_PASS_UNVERIFIED"})
        self.assertEqual(report["evidenceStructure"],"INCOMPLETE")
        self.assertEqual(report["verifiedRealDPassCount"],0)
        self.assertFalse(report["humanDualApprovalPerformed"])
        self.assertIn("proof-dir",report["missingInputs"])

        complete=evaluate(claims,receipts,field,registry,proofs,
                          trust_sha=anchor,web_sha=WEB,skill_sha=SKILL,now=now)
        self.assertEqual(complete["evidenceStructure"],
                         "STRUCTURALLY_CONSISTENT_UNVERIFIED")
        self.assertEqual(complete["missingInputs"],[])
        self.assertEqual(set(complete["independentWitnessCoverage"].values()),
                         {"SUBMITTED_UNVERIFIED"})
        self.assertEqual(set(complete["detailedReceiptCoverage"].values()),
                         {"SUBMITTED_UNVERIFIED"})
        self.assertEqual(complete["verifiedRealDPassCount"],0)
        self.assertFalse(complete["releaseAuthorized"])
        self.assertEqual(complete["decision"],"NO-GO")
        serial=json.dumps(complete)
        for secret_like in ("mock-operator","mock-reviewer","qa-mock-tenant",
                            "mock-case"):
            self.assertNotIn(secret_like,serial)

    def test_inconsistent_physical_restore_cluster_is_rejected_by_shared_bundle(self):
        claims,receipts,field,registry,proofs,anchor,now=fixture()
        changed=deepcopy(receipts)
        pg=next(r for r in changed["receipts"] if r["kind"]=="postgres")
        pg["details"]["restoreClusterIdSha256"]="f"*64
        with self.assertRaises(ValueError):
            evaluate(claims,changed,field,registry,proofs,
                     trust_sha=anchor,web_sha=WEB,skill_sha=SKILL,now=now)
        with self.assertRaises(ValueError):
            evaluate(claims,receipts,field,registry,proofs,
                     trust_sha="a"*64,web_sha=WEB,skill_sha=SKILL,now=now)

    def test_static_workbench_escapes_even_unexpected_display_values(self):
        report=evaluate(web_sha=WEB,skill_sha=SKILL)
        report["dCaseStates"]={"<script>alert('hi')</script>":"x&y"}
        html=render_html(report)
        self.assertNotIn("<script>",html)
        self.assertIn("&lt;script&gt;",html)
        self.assertIn("x&amp;y",html)
        self.assertNotIn("<iframe",html)
        self.assertNotIn("<form",html)

    def test_cli_writes_0600_static_review_and_never_go(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/"audit"
            output.mkdir(mode=0o700)
            args=["--web-sha",WEB,"--skill-sha",SKILL,
                  "--out-dir",str(output)]
            self.assertEqual(main(args),2)
            data=json.loads((output/"release-audit.json").read_text())
            self.assertEqual(data["decision"],"NO-GO")
            self.assertEqual(data["verifiedRealDPassCount"],0)
            self.assertIn("FF-018",(output/"review.html").read_text())
            if os.name=="posix":
                self.assertEqual((output/"review.html").stat().st_mode & 0o077,0)
                self.assertEqual((output/"release-audit.json").stat().st_mode & 0o077,0)
            self.assertEqual(main(args),2)
            self.assertEqual(data,json.loads((output/"release-audit.json").read_text()))

            another=Path(temp)/"audit-only"
            another.mkdir(mode=0o700)
            self.assertEqual(main(args[:-1]+[str(another),"--mode","audit"]),0)
            self.assertEqual(json.loads((another/"release-audit.json").read_text())["decision"],
                             "NO-GO")

    def test_cli_refuses_untrusted_private_input_without_writing_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            output=root/"audit"
            output.mkdir(mode=0o700)
            claims=root/"private-claim.json"
            claims.write_text('{"secret":"DO-NOT-LEAK"}')
            claims.chmod(0o600)
            args=["--web-sha",WEB,"--skill-sha",SKILL,
                  "--claims",str(claims),"--out-dir",str(output),
                  "--mode","audit"]
            self.assertEqual(main(args),2)
            self.assertFalse((output/"release-audit.json").exists())
            self.assertFalse((output/"review.html").exists())
            claims.unlink()
            claims.write_text("{}")
            claims.chmod(0o644)
            if os.name=="posix":
                self.assertEqual(main(args),2)
                self.assertFalse((output/"release-audit.json").exists())

    def test_cli_complete_structurally_consistent_synthetic_packet_stays_no_go(self):
        claims,receipts,field,registry,proofs,anchor,now=fixture()
        # Fixture timestamp comes from the real UTC clock; no network or PG.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            folder=root/"audit"
            folder.mkdir(mode=0o700)
            proofdir=root/"proofs"
            proofdir.mkdir(mode=0o700)
            files={}
            for key,doc in (("claims",claims),("receipts",receipts),
                            ("field",field),("registry",registry)):
                p=root/(key+".json")
                p.write_text(json.dumps(doc))
                p.chmod(0o600)
                files[key]=p
            for kind,(doc,_) in proofs.items():
                p=proofdir/(kind+".json")
                p.write_text(json.dumps(doc,sort_keys=True))
                p.chmod(0o600)
            args=["--web-sha",WEB,"--skill-sha",SKILL,
                  "--claims",str(files["claims"]),
                  "--receipts",str(files["receipts"]),
                  "--field-dossier",str(files["field"]),
                  "--registry",str(files["registry"]),
                  "--proof-dir",str(proofdir),
                  "--trust-sha",anchor,
                  "--out-dir",str(folder),"--mode","audit"]
            self.assertEqual(main(args),0)
            result=json.loads((folder/"release-audit.json").read_text())
            self.assertEqual(result["evidenceStructure"],
                             "STRUCTURALLY_CONSISTENT_UNVERIFIED")
            self.assertEqual(result["verifiedRealDPassCount"],0)
            self.assertFalse(result["releaseAuthorized"])
            self.assertNotIn("mock-operator",(folder/"review.html").read_text())


if __name__=="__main__":
    unittest.main()
