"""#132 detailed D receipt contract regressions. All evidence here is synthetic."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from ops.studio_d_environment_assertions_132 import GATES, ORIGINS
from ops.studio_d_receipt_contract_132 import GATES as DETAIL_GATES
from ops.studio_d_receipt_contract_132 import digest, evaluate, main

WEB = "a"*40
SKILL = "b"*40
NOW = datetime(2026,11,10,tzinfo=timezone.utc)
HASH = lambda n: format(n, "064x")


def samples():
    details = {
        "provider": {
            "providerStatementSha256":HASH(1),
            "webRunItemAttemptSha256":HASH(2),
            "walletLedgerSha256":HASH(3),
            "freeQuotaLedgerSha256":HASH(4),
            "reconciliationReportSha256":HASH(5),
            "currency":"USD", "paidAttemptCount":6, "refundCount":2,
            "unmatchedProviderEntryCount":0, "unmatchedWalletEntryCount":0,
            "netChargeDeltaMinor":0, "netRefundDeltaMinor":0,
            "duplicateCallbackCasesChecked":2, "throttled429CasesChecked":1,
            "upstream502CasesChecked":1, "unknownRecoveryCasesChecked":1,
            "lateSuccessCasesChecked":1,
        },
        "postgres": {
            "pgMajorVersion":17, "basebackupManifestSha256":HASH(6),
            "walArchiveManifestSha256":HASH(7),
            "sourceClusterIdSha256":HASH(8),
            "restoreClusterIdSha256":HASH(9),
            "schemaFingerprintBeforeSha256":HASH(10),
            "schemaFingerprintAfterSha256":HASH(10),
            "walletLedgerBeforeSha256":HASH(11),
            "walletLedgerAfterSha256":HASH(11),
            "mediaManifestBeforeSha256":HASH(12),
            "mediaManifestAfterSha256":HASH(12),
            "independentHostClaim":True, "restoreCompleted":True,
            "pitrTargetReached":True, "rollbackDrilled":True,
            "rpoMeasuredSeconds":12, "rpoBudgetSeconds":60,
            "rtoMeasuredSeconds":120, "rtoBudgetSeconds":300,
        },
        "storage": {
            "providerKind":"r2",
            "bucketPolicySha256":HASH(13), "cdnPolicySha256":HASH(14),
            "uploadDownloadManifestSha256":HASH(15),
            "tenantOneRef":"synthetic-tenant-one",
            "tenantTwoRef":"synthetic-tenant-two",
            "anonymousDenied":True, "crossTenantReadDeniedBothDirections":True,
            "crossTenantWriteDeniedBothDirections":True,
            "expiredSignedUrlDenied":True, "revokedSignedUrlDenied":True,
            "cdnOldUrlInvalidated":True, "restoredMediaBytesMatched":True,
            "publicGrantOnlyForPublishedAssets":True,
        },
    }
    claims = {
        "schemaVersion":1, "environment":"preproduction",
        "deployedSha":WEB, "skillSha":SKILL,
        "cases":[{
            "caseId":g, "status":"PASS", "origin":ORIGINS[g],
            "evidenceDigestSha256":HASH(i+100),
            "evidenceId":f"fake-private-{i:03d}",
            "environmentId":"fake-preprod",
            "deployedSha":WEB, "skillSha":SKILL,
            "observedAtUtc":"2026-11-09T23:00:00Z",
            "operator":"fake-operator", "reviewer":"fake-reviewer",
            "isSimulation":False, "physicalOrRealProviderClaim":True,
        } for i,g in enumerate(GATES)],
    }
    rows = []
    for kind, case in DETAIL_GATES.items():
        fingerprint=digest(details[kind])
        rows.append({"kind":kind, "caseId":case,
                     "evidenceDigestSha256":fingerprint, "details":details[kind]})
        for item in claims["cases"]:
            if item["caseId"] == case:
                item["evidenceDigestSha256"] = fingerprint
                break
    packet = {"schemaVersion":1, "deployedSha":WEB,
              "skillSha":SKILL, "receipts":rows}
    return packet,claims


def rebind(packet,claims):
    for receipt in packet["receipts"]:
        h=digest(receipt["details"])
        receipt["evidenceDigestSha256"]=h
        for case in claims["cases"]:
            if case["caseId"] == receipt["caseId"]:
                case["evidenceDigestSha256"]=h
                break


class DetailedReceiptsTest(unittest.TestCase):
    def test_three_detailed_receipts_are_bound_to_17_case_matrix_but_never_go(self):
        pack,claims=samples()
        out=evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)
        self.assertEqual(out["linkedDetailedCases"],3)
        self.assertEqual(out["missingDetailedCases"],[])
        self.assertTrue(out["all17CasesClaimPass"])
        self.assertFalse(out["externalSourceAuthenticityVerified"])
        self.assertFalse(out["physicalPitrActuallyPerformed"])
        self.assertFalse(out["vendorStatementActuallyRetrieved"])
        self.assertFalse(out["privateS3ActuallyTested"])
        self.assertEqual(out["decision"],"NO-GO")
        self.assertNotIn("fake-operator",json.dumps(out))
        self.assertNotIn("fake-private",json.dumps(out))

    def test_vendor_charges_refunds_unknown_429_502_and_late_cases_fail_closed(self):
        for field,bad in (
            ("unmatchedProviderEntryCount",1), ("unmatchedWalletEntryCount",1),
            ("netChargeDeltaMinor",1), ("netRefundDeltaMinor",8),
            ("duplicateCallbackCasesChecked",0), ("throttled429CasesChecked",0),
            ("upstream502CasesChecked",0), ("unknownRecoveryCasesChecked",0),
            ("lateSuccessCasesChecked",0), ("paidAttemptCount",0),
            ("providerStatementSha256","bad"), ("currency","FAKE"),
        ):
            pack,claims=samples()
            pack["receipts"][0]["details"][field]=bad
            rebind(pack,claims)
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)

    def test_independent_pg17_physical_restore_wal_pitr_rollback_fails_closed(self):
        for field,bad in (
            ("pgMajorVersion",16), ("restoreClusterIdSha256",HASH(8)),
            ("schemaFingerprintAfterSha256",HASH(80)),
            ("walletLedgerAfterSha256",HASH(81)),
            ("mediaManifestAfterSha256",HASH(82)),
            ("independentHostClaim",False), ("pitrTargetReached",False),
            ("restoreCompleted",False), ("rollbackDrilled",False),
            ("basebackupManifestSha256","broken"),
            ("rpoMeasuredSeconds",61), ("rtoMeasuredSeconds",301),
        ):
            pack,claims=samples()
            pack["receipts"][1]["details"][field]=bad
            rebind(pack,claims)
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)

    def test_private_s3_bucket_cross_owner_expiry_and_cdn_fail_closed(self):
        for field,bad in (
            ("providerKind","moto"), ("tenantTwoRef","synthetic-tenant-one"),
            ("bucketPolicySha256","bad"), ("anonymousDenied",False),
            ("crossTenantReadDeniedBothDirections",False),
            ("crossTenantWriteDeniedBothDirections",False),
            ("expiredSignedUrlDenied",False), ("revokedSignedUrlDenied",False),
            ("cdnOldUrlInvalidated",False), ("restoredMediaBytesMatched",False),
            ("publicGrantOnlyForPublishedAssets",False),
        ):
            pack,claims=samples()
            pack["receipts"][2]["details"][field]=bad
            rebind(pack,claims)
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)

    def test_swapped_receipt_or_d_case_digest_or_deployment_is_refused(self):
        pack,claims=samples()
        pack["receipts"][1]["details"]["walletLedgerBeforeSha256"]=HASH(88)
        with self.assertRaisesRegex(ValueError,"mismatch|swapped"):
            evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)
        pack,claims=samples()
        claims["cases"][0]["origin"]="moto"
        with self.assertRaises(ValueError):
            evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)
        pack,claims=samples()
        pack["receipts"][1]["caseId"]=DETAIL_GATES["provider"]
        with self.assertRaises(ValueError):
            evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)
        pack,claims=samples()
        pack["skillSha"]="f"*40
        with self.assertRaises(ValueError):
            evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)
        pack,claims=samples()
        claims["cases"][0]["reviewer"]=claims["cases"][0]["operator"]
        with self.assertRaises(ValueError):
            evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)

    def test_missing_one_detail_never_mistaken_for_complete_release(self):
        pack,claims=samples()
        pack["receipts"].pop()
        out=evaluate(pack,claims,web_sha=WEB,skill_sha=SKILL,now=NOW)
        self.assertEqual(out["linkedDetailedCases"],2)
        self.assertEqual(out["missingDetailedCases"],[DETAIL_GATES["storage"]])
        self.assertEqual(out["decision"],"NO-GO")

    def test_cli_private_0600_non_overwrite_reports_only_aggregates(self):
        pack,claims=samples()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            packet=root/"receipt.json"
            manifest=root/"claims.json"
            report=root/"summary.json"
            for path,data in ((packet,pack),(manifest,claims)):
                path.write_text(json.dumps(data),encoding="utf-8")
                path.chmod(0o600)
            args=["--claims",str(manifest), "--receipts",str(packet),
                  "--web-sha",WEB, "--skill-sha",SKILL, "--report",str(report)]
            # Date-sensitive CLI checks are covered by the fixed-clock pure tests;
            # the signed evidence timestamp is within today's Phase20 date.
            self.assertEqual(main(args),0)
            self.assertEqual(main(args),2)
            self.assertEqual(json.loads(report.read_text())["decision"],"NO-GO")
            self.assertNotIn("fake-private",report.read_text())


if __name__=="__main__":
    unittest.main()
