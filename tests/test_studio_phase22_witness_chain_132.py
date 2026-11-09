"""Phase22: externally anchored five-way witness bytes, no real D acceptance."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.studio_official_approval_132 import CODES
from ops.studio_phase22_witness_chain_132 import (
    SOURCES,CASE_IDS,evaluate,main,
)

NOW=datetime.now(timezone.utc)
WEB="a"*40
SKILL="b"*40
DT=(NOW-timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(obj):
    return hashlib.sha256(json.dumps(
        obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,
        allow_nan=False).encode()).hexdigest()


def reports():
    return {
        "official":{"decision":"NO-GO","signedCandidateClaims":3,
            "candidateCodes":list(CODES),"strictParityDryRunPassed":True,
            "automaticPromotionAuthorized":False,
            "websiteDbOriginIndependentlyProven":False},
        "postgres":{"decision":"NO-GO",
            "mode":"isolated-postgres17-pitr-readonly-verified",
            "pg17ReplayPausedAndRowsMatched":True,
            "productionReleaseAuthorized":False},
        "storage":{"decision":"NO-GO",
            "observed":{f:True for f in (
                "ownBytesMatched","crossTenantReadDeniedBothDirections",
                "crossTenantWriteDeniedBothDirections","anonymousDenied",
                "expiredSignedUrlDenied")},
            "cdnOldUrlInvalidated":True,
            "revokedSignedUrlDenied":True,"restoredMediaBytesMatched":True},
        "redis":{"decision":"NO-GO",
            "crossClientAtomicNxObserved":True,
            "redisTenantAclDeniedBothDirections":True,
            "twoPhysicalWebInstancesIndependentlyProven":True,
            "automaticFailoverVerified":True},
        "provider":{"decision":"NO-GO","result":"NO_AUTOMATED_ANOMALIES",
            "anomalies":[],"currencyUnitsSeparated":True,
            "externalStatementsAuthenticated":False},
    }


def payload():
    artifacts=reports()
    proofs={}
    reg={"schemaVersion":1,"issuer":"phase22-independent-auditor",
         "webSha":WEB,"skillSha":SKILL,"environment":"preproduction",
         "records":[]}
    for i,(k,doc) in enumerate(artifacts.items(),start=1):
        body=json.dumps(doc,sort_keys=True).encode("utf-8")
        digest=hashlib.sha256(body).hexdigest()
        proofs[k]=(doc,digest)
        reg["records"].append({"kind":k,"caseId":CASE_IDS[k],
            "artifactSha256":digest,"sourceOrigin":SOURCES[k],
            "operatorId":f"operator-{i}","independentReviewerId":f"reviewer-{i}",
            "evidenceId":f"mock-evidence-{i}","observedAtUtc":DT,
            "webSha":WEB,"skillSha":SKILL})
    return reg,proofs,canonical(reg)


class Phase22WitnessTest(unittest.TestCase):
    def test_all_five_pinned_claims_still_never_grant_d_or_go(self):
        registry,proofs,anchor=payload()
        out=evaluate(registry,proofs,trust_sha=anchor,
                     web_sha=WEB,skill_sha=SKILL,now=NOW)
        self.assertEqual(out["pinnedWitnessCount"],5)
        self.assertEqual(out["realDPassCountVerifiedByThisTool"],0)
        self.assertFalse(out["sourceAuthenticityIndependentlyEstablished"])
        self.assertFalse(out["websiteApprovalGranted"])
        self.assertFalse(out["releaseAuthorized"])
        self.assertEqual(out["decision"],"NO-GO")
        self.assertNotIn("mock-evidence",json.dumps(out))

    def test_no_proof_defaults_all_five_missing(self):
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/"r.json"
            args=["--web-sha",WEB,"--skill-sha",SKILL,"--report",str(report)]
            self.assertEqual(main(args),0)
            self.assertEqual(main(args),2)
            out=json.loads(report.read_text())
            self.assertEqual(out["pinnedWitnessCount"],0)
            self.assertEqual(set(out["witnessStates"].values()),{"MISSING"})
            self.assertEqual(out["decision"],"NO-GO")

    def test_unpinned_registry_or_replay_missing_case_blocked(self):
        reg,proofs,anchor=payload()
        with self.assertRaises(ValueError):
            evaluate(reg,proofs,trust_sha="f"*64,web_sha=WEB,
                     skill_sha=SKILL,now=NOW)
        a=deepcopy(reg)
        a["records"][1]["evidenceId"]=a["records"][0]["evidenceId"]
        with self.assertRaises(ValueError):
            evaluate(a,proofs,trust_sha=canonical(a),web_sha=WEB,
                     skill_sha=SKILL,now=NOW)
        a=deepcopy(reg)
        a["records"][0]["caseId"]=CASE_IDS["postgres"]
        with self.assertRaises(ValueError):
            evaluate(a,proofs,trust_sha=canonical(a),web_sha=WEB,
                     skill_sha=SKILL,now=NOW)
        a=deepcopy(reg)
        a["records"][0]["operatorId"]=a["records"][0]["independentReviewerId"]
        with self.assertRaises(ValueError):
            evaluate(a,proofs,trust_sha=canonical(a),web_sha=WEB,
                     skill_sha=SKILL,now=NOW)

    def test_mismatched_report_sha_deployment_future_and_stale_refused(self):
        reg,proofs,anchor=payload()
        changed=deepcopy(proofs)
        changed["provider"]=(dict(changed["provider"][0]),"0"*64)
        with self.assertRaises(ValueError):
            evaluate(reg,changed,trust_sha=anchor,web_sha=WEB,
                     skill_sha=SKILL,now=NOW)
        for name,bad in (("webSha","f"*40),
                         ("observedAtUtc","2020-01-01T00:00:00Z")):
            a=deepcopy(reg)
            a["records"][0][name]=bad
            with self.subTest(name=name),self.assertRaises(ValueError):
                evaluate(a,proofs,trust_sha=canonical(a),web_sha=WEB,
                         skill_sha=SKILL,now=NOW)

    def test_incomplete_reports_never_structurally_pass(self):
        for kind,field in (
            ("official","signedCandidateClaims"),
            ("postgres","pg17ReplayPausedAndRowsMatched"),
            ("storage","cdnOldUrlInvalidated"),
            ("redis","automaticFailoverVerified"),
            ("provider","result"),
        ):
            reg,proofs,_=payload()
            report=deepcopy(proofs[kind][0])
            report[field]=False
            body=json.dumps(report).encode()
            proofhash=hashlib.sha256(body).hexdigest()
            proofs[kind]=(report,proofhash)
            next(x for x in reg["records"] if x["kind"]==kind)["artifactSha256"]=proofhash
            out=evaluate(reg,proofs,trust_sha=canonical(reg),web_sha=WEB,
                         skill_sha=SKILL,now=NOW)
            self.assertEqual(out["witnessStates"][kind],"INCOMPLETE_CLAIM")
            self.assertEqual(out["realDPassCountVerifiedByThisTool"],0)

    def test_private_permissions_and_valid_cli_likewise_no_go(self):
        reg,proofs,anchor=payload()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            private=root/"proofs"
            private.mkdir()
            registry=root/"registry.json"
            registry.write_text(json.dumps(reg),encoding="utf-8")
            registry.chmod(0o600)
            for kind,(data,_) in proofs.items():
                path=private/(kind+".json")
                path.write_text(json.dumps(data,sort_keys=True),encoding="utf-8")
                path.chmod(0o600)
            report=root/"result.json"
            args=["--registry",str(registry),"--proof-dir",str(private),
                  "--web-sha",WEB,"--skill-sha",SKILL,"--report",str(report)]
            with patch.dict(os.environ,{"HANDRAW_PHASE22_TRUST_SHA256":anchor}):
                self.assertEqual(main(args),0)
            self.assertEqual(json.loads(report.read_text())["pinnedWitnessCount"],5)
            report.unlink()
            registry.chmod(0o644)
            with patch.dict(os.environ,{"HANDRAW_PHASE22_TRUST_SHA256":anchor}):
                self.assertEqual(main(args),2)


if __name__=="__main__":
    unittest.main()
