"""Phase24: independent 17 x 5 x 3 claim JOIN, no live D-level PASS."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.studio_d_environment_assertions_132 import GATES,ORIGINS
from ops.studio_d_receipt_contract_132 import (
    GATES as DETAIL_CASES, PROVIDER_FIELDS,PG_FIELDS,STORAGE_FIELDS,
    COUNT_PROVIDER,BOOL_STORAGE,digest,
)
from ops.studio_phase22_field_receipts_132 import (
    PG,ST,REDIS,
)
from ops.studio_phase22_witness_chain_132 import (
    CASE_IDS,SOURCES,
)
from ops.studio_phase24_release_join_132 import evaluate,main

WEB="a"*40
SKILL="b"*40


def h(n):
    return format(n,"064x")


def canonical(obj):
    return hashlib.sha256(json.dumps(
        obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()


def fixture():
    now=datetime.now(timezone.utc)
    when=(now-timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    claims={
        "schemaVersion":1,"environment":"preproduction",
        "deployedSha":WEB,"skillSha":SKILL,
        "cases":[{
            "caseId":name,"status":"PASS","origin":ORIGINS[name],
            "evidenceDigestSha256":h(i+101),
            "evidenceId":f"mock-case-{i:03d}","environmentId":"qa-mock-tenant",
            "deployedSha":WEB,"skillSha":SKILL,"observedAtUtc":when,
            "operator":"mock-operator","reviewer":"mock-reviewer",
            "isSimulation":False,"physicalOrRealProviderClaim":True,
        } for i,name in enumerate(GATES)],
    }
    provider={k:h(200+i) for i,k in enumerate(sorted(PROVIDER_FIELDS))
              if k.endswith("Sha256")}
    provider.update({k:1 for k in COUNT_PROVIDER})
    provider.update({"currency":"USD",
        "unmatchedProviderEntryCount":0,"unmatchedWalletEntryCount":0,
        "netChargeDeltaMinor":0,"netRefundDeltaMinor":0})
    pg={k:h(300+i) for i,k in enumerate(sorted(PG_FIELDS))
        if k.endswith("Sha256")}
    for prefix in ("schemaFingerprint","walletLedger","mediaManifest"):
        pg[prefix+"AfterSha256"]=pg[prefix+"BeforeSha256"]
    pg["restoreClusterIdSha256"]=h(421)
    pg["sourceClusterIdSha256"]=h(422)
    pg.update({"pgMajorVersion":17,"independentHostClaim":True,
        "restoreCompleted":True,"pitrTargetReached":True,
        "rollbackDrilled":True,"rpoMeasuredSeconds":40,"rpoBudgetSeconds":300,
        "rtoMeasuredSeconds":400,"rtoBudgetSeconds":1200})
    storage={k:h(500+i) for i,k in enumerate(sorted(STORAGE_FIELDS))
             if k.endswith("Sha256")}
    storage.update({k:True for k in BOOL_STORAGE})
    storage.update({"providerKind":"r2","tenantOneRef":"mock-owner-one",
                    "tenantTwoRef":"mock-owner-two"})
    details={"provider":provider,"postgres":pg,"storage":storage}
    receipts={"schemaVersion":1,"deployedSha":WEB,"skillSha":SKILL,
              "receipts":[]}
    by_case={r["caseId"]:r for r in claims["cases"]}
    for kind,case in DETAIL_CASES.items():
        sha=digest(details[kind])
        receipts["receipts"].append({
            "kind":kind,"caseId":case,"details":details[kind],
            "evidenceDigestSha256":sha,
        })
        by_case[case]["evidenceDigestSha256"]=sha
    fp={k:h(600+i) for i,k in enumerate(sorted(PG))
        if k.endswith("Sha256")}
    fp["sourcePhysicalHostSha256"]=h(701)
    fp["recoveryPhysicalHostSha256"]=h(702)
    fp["walletLedgerBeforeSha256"]=pg["walletLedgerBeforeSha256"]
    fp["walletLedgerAfterSha256"]=pg["walletLedgerAfterSha256"]
    fp.update({"targetUtc":when,"recoveredReplayLsn":"0/10000000",
               "pg17PhysicalBackupVerified":True,
               "pg17WalReplayAtTarget":True,"rollbackDrilled":True,
               "rpoMeasuredSeconds":40,"rpoBudgetSeconds":300,
               "rtoMeasuredSeconds":400,"rtoBudgetSeconds":1200})
    fst={k:h(800+i) for i,k in enumerate(sorted(ST))
         if k.endswith("Sha256")}
    fst["tenantOneScopeSha256"]=h(801)
    fst["tenantTwoScopeSha256"]=h(802)
    fst["sourceObjectBytesSha256"]=h(805)
    fst["restoredObjectBytesSha256"]=h(805)
    fst["bucketPolicySha256"]=storage["bucketPolicySha256"]
    fst["cdnPolicySha256"]=storage["cdnPolicySha256"]
    fst.update({k:True for k in ST if not k.endswith("Sha256")})
    fr={k:h(901+i) for i,k in enumerate(sorted(REDIS))
        if k.endswith("Sha256")}
    fr.update({k:True for k in REDIS if not k.endswith("Sha256")
               and not k.startswith("fencedLeaderEpoch")})
    fr["fencedLeaderEpochBefore"]=100
    fr["fencedLeaderEpochAfter"]=101
    field={"schemaVersion":1,"environment":"preproduction",
           "webSha":WEB,"skillSha":SKILL,
           "postgres":fp,"storage":fst,"redis":fr}
    reports={
        "official":{"decision":"NO-GO","signedCandidateClaims":3,
          "candidateCodes":["FF-018","FF-019","FG-025"],
          "strictParityDryRunPassed":True,
          "automaticPromotionAuthorized":False,
          "websiteDbOriginIndependentlyProven":False},
        "postgres":{"decision":"NO-GO",
          "mode":"isolated-postgres17-pitr-readonly-verified",
          "pg17ReplayPausedAndRowsMatched":True,
          "productionReleaseAuthorized":False},
        "storage":{"decision":"NO-GO","observed":{
          k:True for k in ("ownBytesMatched",
            "crossTenantReadDeniedBothDirections",
            "crossTenantWriteDeniedBothDirections",
            "anonymousDenied","expiredSignedUrlDenied")},
          "cdnOldUrlInvalidated":True,"revokedSignedUrlDenied":True,
          "restoredMediaBytesMatched":True},
        "redis":{"decision":"NO-GO","crossClientAtomicNxObserved":True,
          "redisTenantAclDeniedBothDirections":True,
          "twoPhysicalWebInstancesIndependentlyProven":True,
          "automaticFailoverVerified":True},
        "provider":{"decision":"NO-GO",
          "result":"NO_AUTOMATED_ANOMALIES",
          "anomalies":[],"currencyUnitsSeparated":True,
          "externalStatementsAuthenticated":False},
    }
    registry={
        "schemaVersion":1,"issuer":"phase22-independent-auditor",
        "webSha":WEB,"skillSha":SKILL,"environment":"preproduction",
        "records":[],
    }
    proofs={}
    for kind,report in reports.items():
        raw=json.dumps(report,sort_keys=True).encode("utf-8")
        report_hash=hashlib.sha256(raw).hexdigest()
        proofs[kind]=(report,report_hash)
        claim=by_case[CASE_IDS[kind]]
        registry["records"].append({
            "kind":kind,"caseId":CASE_IDS[kind],
            "artifactSha256":report_hash,"sourceOrigin":SOURCES[kind],
            "operatorId":claim["operator"],
            "independentReviewerId":claim["reviewer"],
            "evidenceId":claim["evidenceId"],
            "observedAtUtc":claim["observedAtUtc"],
            "webSha":WEB,"skillSha":SKILL,
        })
    return claims,receipts,field,registry,proofs,canonical(registry),now


def check(payload):
    claims,receipts,field,registry,proofs,anchor,now=payload
    return evaluate(claims,receipts,field,registry,proofs,
        trust_sha=anchor,web_sha=WEB,skill_sha=SKILL,now=now)


class Phase24ReleaseJoinTest(unittest.TestCase):
    def test_complete_synthetic_join_still_cannot_go(self):
        out=check(fixture())
        self.assertEqual(out["structurallyJoinedDClaimCount"],17)
        self.assertEqual(out["witnessReportsBound"],5)
        self.assertEqual(out["detailedReceiptsBound"],3)
        self.assertEqual(out["verifiedRealDPassCount"],0)
        self.assertFalse(out["sourceAuthenticityEstablished"])
        self.assertFalse(out["humanDCaseVerificationPerformed"])
        self.assertFalse(out["officialApprovalGranted"])
        self.assertFalse(out["productionReleaseAuthorized"])
        self.assertEqual(out["decision"],"NO-GO")
        self.assertNotIn("mock-operator",json.dumps(out))

    def test_cross_file_witness_identity_and_utc_mismatch_rejected(self):
        for field,bad in (("evidenceId","wrong-evidence"),
                          ("operatorId","wrong-operator"),
                          ("independentReviewerId","wrong-reviewer"),
                          ("observedAtUtc","2026-11-09T00:00:00Z")):
            d=list(fixture())
            d[3]["records"][0][field]=bad
            d[5]=canonical(d[3])
            with self.subTest(field=field),self.assertRaises(ValueError):
                check(tuple(d))

    def test_pg_wallet_rpo_rto_drift_rejected(self):
        for field,bad in (
            ("walletLedgerBeforeSha256",h(999)),
            ("rpoMeasuredSeconds",50),
            ("rpoBudgetSeconds",301),
            ("rtoMeasuredSeconds",401),
        ):
            d=list(fixture())
            d[2]["postgres"][field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):
                check(tuple(d))

    def test_storage_bucket_cdn_policy_drift_rejected(self):
        for field in ("bucketPolicySha256","cdnPolicySha256"):
            d=list(fixture())
            d[2]["storage"][field]=h(998)
            with self.subTest(field=field),self.assertRaises(ValueError):
                check(tuple(d))

    def test_incomplete_or_tampered_claim_and_witness_rejected(self):
        d=list(fixture())
        d[0]["cases"]=d[0]["cases"][:-1]
        with self.assertRaises(ValueError):check(tuple(d))
        d=list(fixture())
        d[1]["receipts"].pop()
        with self.assertRaises(ValueError):check(tuple(d))
        d=list(fixture())
        d[3]["records"].pop()
        d[5]=canonical(d[3])
        with self.assertRaises(ValueError):check(tuple(d))
        d=list(fixture())
        d[4]["official"]=(d[4]["official"][0],"f"*64)
        with self.assertRaises(ValueError):check(tuple(d))
        d=list(fixture())
        d[0]["cases"][0]["isSimulation"]=True
        with self.assertRaises(ValueError):check(tuple(d))

    def test_private_cli_and_non_overwrite(self):
        claims,receipts,field,registry,proofs,anchor,_=fixture()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            proof_dir=root/"proofs"
            proof_dir.mkdir()
            files={}
            for name,obj in (("claims",claims),("receipts",receipts),
                             ("field",field),("registry",registry)):
                path=root/(name+".json")
                path.write_text(json.dumps(obj),encoding="utf-8")
                path.chmod(0o600)
                files[name]=path
            for kind,(report,_) in proofs.items():
                path=proof_dir/(kind+".json")
                path.write_text(json.dumps(report,sort_keys=True),encoding="utf-8")
                path.chmod(0o600)
            result=root/"result.json"
            args=[
                "--claims",str(files["claims"]),
                "--receipts",str(files["receipts"]),
                "--field-dossier",str(files["field"]),
                "--registry",str(files["registry"]),
                "--proof-dir",str(proof_dir),
                "--web-sha",WEB,"--skill-sha",SKILL,
                "--report",str(result),
            ]
            with patch.dict(os.environ,{"HANDRAW_PHASE22_TRUST_SHA256":anchor}):
                self.assertEqual(main(args),0)
            self.assertEqual(json.loads(result.read_text())["decision"],"NO-GO")
            self.assertNotIn("mock-reviewer",result.read_text())
            with patch.dict(os.environ,{"HANDRAW_PHASE22_TRUST_SHA256":anchor}):
                self.assertEqual(main(args),2)
            result.unlink()
            files["claims"].chmod(0o644)
            with patch.dict(os.environ,{"HANDRAW_PHASE22_TRUST_SHA256":anchor}):
                if os.name=="posix":
                    self.assertEqual(main(args),2)


if __name__=="__main__":
    unittest.main()
