"""#11/#84/#112 evidence D-gate is a refusal/review tool, not GO authority."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from ops.studio_release_d_attestation_112 import GROUPS, evaluate, main

SHA="a"*40
NOW=datetime(2026,11,9,12,0,tzinfo=timezone.utc)


def manifest(*,status="PASS"):
    now="2026-11-09T11:00:00Z"
    return {
        "schema_version":1,"environment":"preproduction",
        "release_sha":SHA,
        "checks":[{"gate":g,"status":status,
                   "evidenceId":"private-review-123",
                   "operator":"qa-operator","reviewer":"release-reviewer",
                   "observedAtUtc":now}
                  for gates in GROUPS.values() for g in gates],
    }


class FinalDLevelIntakeTests(unittest.TestCase):
    def test_missing_external_evidence_fails_closed_without_fake_passes(self):
        out=evaluate(None,expected_sha=SHA,now=NOW)
        self.assertEqual(out["decision"],"NO-GO")
        self.assertFalse(out["issueClosureAuthorized"])
        self.assertFalse(out["claimsComplete"])
        self.assertEqual(out["statusCounts"]["MISSING"],16)
        self.assertEqual(set(out["coverageByIssue"]),{"11","84","112"})
        self.assertFalse(out["privateEvidenceValuesEmitted"])

    def test_even_perfect_signed_off_claims_require_external_authentication(self):
        data=manifest()
        out=evaluate(data,expected_sha=SHA,now=NOW)
        self.assertTrue(out["claimsComplete"])
        self.assertTrue(out["readyForManualAuthenticityReview"])
        self.assertEqual(out["statusCounts"],{"PASS":16})
        self.assertEqual(out["decision"],"NO-GO")
        self.assertFalse(out["issueClosureAuthorized"])
        self.assertTrue(out["requiresIndependentAuditOfPrivateEvidence"])
        self.assertFalse(out["coverageByIssue"]["84"]["realWorldAcceptanceConfirmed"])
        self.assertNotIn("private-review-123",json.dumps(out))
        self.assertNotIn("qa-operator",json.dumps(out))

    def test_old_evidence_cannot_make_a_claim_complete(self):
        data=manifest()
        data["checks"][0]["observedAtUtc"]="2025-01-01T00:00:00Z"
        out=evaluate(data,expected_sha=SHA,now=NOW)
        self.assertEqual(out["statusCounts"]["STALE"],1)
        self.assertFalse(out["coverageByIssue"]["11"]["claimComplete"])

    def test_sensitive_extra_fields_and_duplicate_gate_refused(self):
        bad=manifest()
        bad["checks"][0]["bearer"]="CANARY_TOKEN"
        with self.assertRaises(ValueError):
            evaluate(bad,expected_sha=SHA,now=NOW)
        bad=manifest()
        bad["checks"][0]["gate"]=bad["checks"][1]["gate"]
        with self.assertRaises(ValueError):
            evaluate(bad,expected_sha=SHA,now=NOW)

    def test_witness_independence_and_sha_freshness(self):
        bad=manifest()
        bad["checks"][0]["reviewer"]="qa-operator"
        with self.assertRaises(ValueError):
            evaluate(bad,expected_sha=SHA,now=NOW)
        bad=manifest()
        with self.assertRaises(ValueError):
            evaluate(bad,expected_sha="b"*40,now=NOW)
        bad=manifest()
        bad["checks"][0]["observedAtUtc"]="2030-11-09T00:00:00Z"
        with self.assertRaises(ValueError):
            evaluate(bad,expected_sha=SHA,now=NOW)

    def test_blocked_or_partial_cases_never_declare_a_go(self):
        partial=manifest()
        partial["checks"]=partial["checks"][:4]
        partial["checks"][0]["status"]="BLOCKED"
        out=evaluate(partial,expected_sha=SHA,now=NOW)
        self.assertEqual(out["statusCounts"]["BLOCKED"],1)
        self.assertEqual(out["statusCounts"]["MISSING"],12)
        self.assertFalse(out["claimsComplete"])
        self.assertEqual(out["decision"],"NO-GO")

    def test_cli_no_manifest_writes_only_redacted_restricted_report(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"report.json"
            code=main(["--release-sha",SHA,"--report",str(path)])
            self.assertEqual(code,0)
            out=json.loads(path.read_text())
            self.assertEqual(out["decision"],"NO-GO")
            if os.name=="posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            self.assertEqual(main(["--release-sha",SHA,"--report",str(path)]),2)

    def test_private_manifest_permissions_enforced_without_echoing_contents(self):
        if os.name!="posix":self.skipTest("POSIX-only file permission guard")
        with tempfile.TemporaryDirectory() as root:
            private=Path(root)/"private.json"
            private.write_text(json.dumps(manifest()))
            private.chmod(0o644)
            report=Path(root)/"report.json"
            self.assertEqual(main([
                "--release-sha",SHA,"--manifest",str(private),
                "--report",str(report)]),2)
            self.assertFalse(report.exists())
            private.chmod(0o600)
            self.assertEqual(main([
                "--release-sha",SHA,"--manifest",str(private),
                "--report",str(report)]),0)
            contents=report.read_text()
            self.assertNotIn("private-review-123",contents)
            self.assertNotIn("qa-operator",contents)


if __name__=="__main__":
    unittest.main()
