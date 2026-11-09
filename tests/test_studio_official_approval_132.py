"""#132: real Ed25519 test keys are ephemeral and NEVER leave this test run."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ops.studio_official_approval_132 import (
    evaluate, main, sha, canon, CODES,
)

ROOT=Path(__file__).resolve().parents[1]
DEPLOY_SHA="a"*40
NOW=datetime(2026,11,10,0,0,0,tzinfo=timezone.utc)


def test_fixture():
    pending=json.loads((ROOT/"ops/official_catalog_pending_11.json").read_text(encoding="utf-8"))
    keys={}
    registrations=[]
    for role, kid in (("website_editor","web-editor-1"),
                      ("independent_reviewer","web-reviewer-2")):
        key=Ed25519PrivateKey.generate()
        keys[role]=(kid,key)
        public=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        registrations.append({"role":role,"keyId":kid,
            "publicKeyBase64":base64.b64encode(public).decode("ascii")})
    registry={"schemaVersion":1,"issuer":"handraw-website-ops",
              "keys":registrations}
    approval_rows=[]
    styles=[]
    for candidate in pending["pendingSkillOnly"]:
        code=candidate["code"]
        row={"number":code,"group":"offline-test-only",
             "generation_name":candidate["name"],"traits":"TEST-NONPRODUCTION"}
        styles.append(row)
        payload={"schemaVersion":1,"candidateCode":code,
            "skillSourceSha256":candidate["sha256"],
            "webDbPublishedRowSha256":sha(row),
            "deployedSha":DEPLOY_SHA,
            "websiteActionId":"mock-web-action-001",
            "rightsReviewEvidenceId":"mock-rights-001",
            "reviewedAtUtc":"2026-11-09T23:00:00Z",
            "result":"website_published_and_reviewed"}
        approvals=[]
        for role in ("website_editor","independent_reviewer"):
            kid,key=keys[role]
            signed=base64.b64encode(key.sign(canon(payload))).decode("ascii")
            approvals.append({"role":role,"keyId":kid,
                              "signatureBase64":signed})
        approval_rows.append({"payload":payload,"signatures":approvals})
    return pending,registry,{"schemaVersion":1,"approvals":approval_rows},styles


class OfficialApprovalSignatureTests(unittest.TestCase):
    def setUp(self):
        self.pending,self.registry,self.bundle,self.db=test_fixture()
        self.trust_sha=sha(self.registry)

    def evaluate(self,bundle=None,registry=None,db=None,trust=None,deploy=DEPLOY_SHA):
        return evaluate(self.bundle if bundle is None else bundle,
                        self.registry if registry is None else registry,
                        self.pending,
                        self.db if db is None else db,
                        trusted_sha=self.trust_sha if trust is None else trust,
                        expected_deployed_sha=deploy,now=NOW)

    def test_real_two_role_signatures_only_grant_claim_intake_never_website_publication(self):
        out=self.evaluate()
        self.assertEqual(out["signedClaimCount"],3)
        self.assertEqual(tuple(out["checkedCodes"]),CODES)
        self.assertTrue(all(x.startswith("SIGNED_") for x in out["candidateStates"].values()))
        self.assertFalse(out["automaticWebsiteApprovalGranted"])
        self.assertFalse(out["publishedDbOriginIndependentlyProven"])
        self.assertFalse(out["releaseGatePassed"])
        self.assertEqual(out["decision"],"NO-GO")
        self.assertNotIn("mock-web-action",json.dumps(out))
        self.assertNotIn("mock-rights",json.dumps(out))

    def test_no_authorized_claims_is_three_missing(self):
        out=evaluate(None,None,self.pending,None,
                     trusted_sha="",expected_deployed_sha=DEPLOY_SHA,now=NOW)
        self.assertEqual(out["signedClaimCount"],0)
        self.assertEqual(set(out["candidateStates"].values()),{"MISSING"})
        self.assertEqual(out["decision"],"NO-GO")

    def test_forged_signature_and_tampered_approval_record_refused(self):
        bundle=json.loads(json.dumps(self.bundle))
        bundle["approvals"][0]["payload"]["websiteActionId"]="forged-approval"
        with self.assertRaisesRegex(ValueError,"signature"):
            self.evaluate(bundle=bundle)
        bundle=json.loads(json.dumps(self.bundle))
        bundle["approvals"][0]["signatures"][0]["signatureBase64"] = (
            bundle["approvals"][1]["signatures"][0]["signatureBase64"])
        with self.assertRaisesRegex(ValueError,"signature"):
            self.evaluate(bundle=bundle)
        bundle=json.loads(json.dumps(self.bundle))
        bundle["approvals"][0]["payload"]["result"]="pending"
        with self.assertRaises(ValueError):
            self.evaluate(bundle=bundle)

    def test_unpinned_self_signed_registry_and_wrong_key_role_refused(self):
        fake=json.loads(json.dumps(self.registry))
        fake["keys"][0]["keyId"]="attacker-key"
        with self.assertRaisesRegex(ValueError,"anchor"):
            self.evaluate(registry=fake)
        with self.assertRaises(ValueError):
            self.evaluate(trust="f"*64)
        bad=json.loads(json.dumps(self.bundle))
        bad["approvals"][0]["signatures"][1]["keyId"]=bad["approvals"][0]["signatures"][0]["keyId"]
        with self.assertRaises(ValueError):
            self.evaluate(bundle=bad)

    def test_missing_or_wrong_published_db_and_wrong_deployed_sha_refused(self):
        with self.assertRaises(ValueError):
            evaluate(self.bundle,self.registry,self.pending,None,
                     trusted_sha=self.trust_sha,expected_deployed_sha=DEPLOY_SHA,now=NOW)
        with self.assertRaises(ValueError):
            self.evaluate(db=self.db[1:])
        with self.assertRaises(ValueError):
            self.evaluate(deploy="b"*40)
        with self.assertRaises(ValueError):
            self.evaluate(db=self.db+[dict(self.db[0])])
        stale=json.loads(json.dumps(self.bundle))
        stale["approvals"][0]["payload"]["reviewedAtUtc"]="2025-01-01T00:00:00Z"
        with self.assertRaises(ValueError):
            self.evaluate(bundle=stale)

    def test_manifest_mutation_refused_and_new_fourth_code_fail_closed(self):
        bad=json.loads(json.dumps(self.pending))
        bad["pendingSkillOnly"].append({"code":"FA-001"})
        with self.assertRaises(ValueError):
            evaluate(None,None,bad,None,trusted_sha="",
                     expected_deployed_sha=DEPLOY_SHA,now=NOW)
        bad=json.loads(json.dumps(self.pending))
        bad["pendingSkillOnly"][0]["state"]="approved"
        with self.assertRaises(ValueError):
            evaluate(None,None,bad,None,trusted_sha="",
                     expected_deployed_sha=DEPLOY_SHA,now=NOW)

    def test_cli_missing_claims_generates_redacted_no_go_and_wont_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            out=Path(root)/"no-go.json"
            args=["--deployed-sha",DEPLOY_SHA,"--report",str(out)]
            self.assertEqual(main(args),0)
            report=json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["decision"],"NO-GO")
            self.assertEqual(main(args),2)
            self.assertNotIn("signatureBase64",out.read_text())


if __name__=="__main__":
    unittest.main()
