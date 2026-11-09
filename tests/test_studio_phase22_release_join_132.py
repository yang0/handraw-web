"""Phase22 offline D receipt-to-field crosswalk: no test credentials or real D PASS."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from ops.studio_official_approval_132 import sha
from ops.studio_d_environment_assertions_132 import ORIGINS
from ops.studio_d_receipt_contract_132 import digest
from ops.studio_phase22_release_join_132 import evaluate_join,main
from test_studio_phase22_field_matrix_132 import event_packet,provider_sample,WEB,SKILL,NOW,ISO


def sample():
    records={kind:event_packet(kind) for kind in ("postgres","storage","redis","provider")}
    pg=records["postgres"]["measurements"]
    store=records["storage"]["measurements"]
    pay=records["provider"]["measurements"]
    # Synthetic identifiers must be hashed and tied to field protocol tokens.
    store["tenantASha256"]=sha("fixture-owner-a")
    store["tenantBSha256"]=sha("fixture-owner-b")
    pg_detail={"pgMajorVersion":17,
       "basebackupManifestSha256":pg["basebackupManifestSha256"],
       "walArchiveManifestSha256":pg["walArchiveManifestSha256"],
       "sourceClusterIdSha256":pg["sourceClusterSha256"],
       "restoreClusterIdSha256":pg["restoreClusterSha256"],
       "schemaFingerprintBeforeSha256":pg["schemaBeforeSha256"],
       "schemaFingerprintAfterSha256":pg["schemaAfterSha256"],
       "walletLedgerBeforeSha256":pg["walletBeforeSha256"],
       "walletLedgerAfterSha256":pg["walletAfterSha256"],
       "mediaManifestBeforeSha256":pg["mediaBeforeSha256"],
       "mediaManifestAfterSha256":pg["mediaAfterSha256"],
       "independentHostClaim":True,"restoreCompleted":True,
       "pitrTargetReached":True,"rollbackDrilled":True,
       "rpoMeasuredSeconds":pg["rpoMeasuredSeconds"],
       "rpoBudgetSeconds":pg["rpoBudgetSeconds"],
       "rtoMeasuredSeconds":pg["rtoMeasuredSeconds"],
       "rtoBudgetSeconds":pg["rtoBudgetSeconds"]}
    storage_detail={"providerKind":store["providerKind"],
       "bucketPolicySha256":store["bucketPolicySha256"],
       "cdnPolicySha256":store["cdnPolicySha256"],
       "uploadDownloadManifestSha256":store["mediaBeforeSha256"],
       "tenantOneRef":"fixture-owner-a","tenantTwoRef":"fixture-owner-b",
       "anonymousDenied":True,
       "crossTenantReadDeniedBothDirections":True,
       "crossTenantWriteDeniedBothDirections":True,
       "expiredSignedUrlDenied":True,
       "revokedSignedUrlDenied":True,
       "cdnOldUrlInvalidated":True,
       "restoredMediaBytesMatched":True,
       "publicGrantOnlyForPublishedAssets":True}
    # The phase22 anomaly scenario trace belongs only to signed field evidence;
    # the existing immutable D receipt schema has no scenarioTraceSha256 field.
    provider_detail={k:pay[k] for k in pay if k!="scenarioTraceSha256"}
    recs=[{"kind":kind,"caseId":case,"evidenceDigestSha256":digest(detail),
           "details":detail}
          for kind,case,detail in (
              ("postgres","pg17_offline_backup_restore_rollback",pg_detail),
              ("storage","real_object_bucket_and_expired_url",storage_detail),
              ("provider","real_provider_charge_refund_ledger",provider_detail))]
    record_map={x["caseId"]:x["evidenceDigestSha256"] for x in recs}
    record_map["redis_multi_instance_failover"]=sha(records["redis"])
    cases=[]
    for i,(case,origin) in enumerate(ORIGINS.items(),start=1):
        cases.append({"caseId":case,
          "status":"PASS" if case in record_map else "PENDING",
          "origin":origin,
          "evidenceDigestSha256":record_map.get(case,sha({"other":case})),
          "evidenceId":f"mock-field-{i:03d}",
          "environmentId":"preprod-mock-fixture",
          "deployedSha":WEB,"skillSha":SKILL,
          "observedAtUtc":ISO(NOW),"operator":"mock-operator",
          "reviewer":"mock-separate-reviewer",
          "isSimulation":False,"physicalOrRealProviderClaim":True})
    master={"schemaVersion":1,"environment":"preproduction",
         "deployedSha":WEB,"skillSha":SKILL,"cases":cases}
    critical={"schemaVersion":1,"deployedSha":WEB,"skillSha":SKILL,"receipts":recs}
    return master,critical,records


class Phase22DCrosswalkTests(unittest.TestCase):
    def setUp(self):
        self.master,self.critical,self.records=sample()
        self.p,self.h=provider_sample()

    def check(self,master=None,critical=None,records=None,with_sources=True):
        return evaluate_join(master=self.master if master is None else master,
           critical=self.critical if critical is None else critical,
           field_records=self.records if records is None else records,
           web_sha=WEB,skill_sha=SKILL,
           provider=self.p if with_sources else None,
           handraw=self.h if with_sources else None,now=NOW)

    def test_17_case_structural_crosswalk_never_calls_it_true_D_pass(self):
        out=self.check()
        self.assertEqual(out["linkedCriticalReceipts"],3)
        self.assertTrue(out["redisFailoverFieldDigestBound"])
        self.assertTrue(out["criticalDetailsBoundToPhysicalEvents"])
        self.assertTrue(out["providerRawExportsReconciled"])
        self.assertTrue(out["all17ClaimsPresent"])
        self.assertEqual(out["structuralClaimPassCount"],4)
        self.assertFalse(out["externalRealWorldDPassProven"])
        self.assertFalse(out["releaseAuthorized"])
        self.assertEqual(out["decision"],"NO-GO")
        self.assertNotIn("mock-operator",json.dumps(out))

    def test_missing_field_packet_and_missing_detailed_receipt_fail_closed(self):
        r=deepcopy(self.records)
        r.pop("redis")
        with self.assertRaises(ValueError):self.check(records=r)
        c=deepcopy(self.critical)
        c["receipts"].pop()
        with self.assertRaises(ValueError):self.check(critical=c)

    def test_cannot_disagree_with_real_pg17_restore_wallet_and_rto(self):
        for k,v in (("rpoMeasuredSeconds",42),
                    ("basebackupManifestSha256","f"*64),
                    ("walletLedgerAfterSha256","f"*64),
                    ("restoreClusterIdSha256","f"*64)):
            c=deepcopy(self.critical)
            row=next(x["details"] for x in c["receipts"] if x["kind"]=="postgres")
            row[k]=v
            if k in ("rpoMeasuredSeconds","restoreClusterIdSha256"):
                pass # still structurally valid, crosswalk must detect drift
            case=next(x for x in self.master["cases"] if x["caseId"]=="pg17_offline_backup_restore_rollback")
            master=deepcopy(self.master)
            next(x for x in master["cases"] if x["caseId"]=="pg17_offline_backup_restore_rollback")[
                 "evidenceDigestSha256"]=digest(row)
            next(x for x in c["receipts"] if x["kind"]=="postgres")["evidenceDigestSha256"]=digest(row)
            with self.subTest(key=k),self.assertRaises(ValueError):
                self.check(master=master,critical=c)

    def test_storage_tenant_snapshot_and_cdn_must_match(self):
        for k,v in (("tenantOneRef","different-owner"),
                    ("cdnPolicySha256","f"*64),
                    ("uploadDownloadManifestSha256","f"*64),
                    ("revokedSignedUrlDenied",False)):
            c=deepcopy(self.critical)
            row=next(x["details"] for x in c["receipts"] if x["kind"]=="storage")
            row[k]=v
            master=deepcopy(self.master)
            next(x for x in master["cases"] if x["caseId"]=="real_object_bucket_and_expired_url")[
                "evidenceDigestSha256"]=digest(row)
            next(x for x in c["receipts"] if x["kind"]=="storage")["evidenceDigestSha256"]=digest(row)
            with self.subTest(key=k),self.assertRaises(ValueError):
                self.check(master=master,critical=c)

    def test_provider_mismatch_and_redis_failover_hash_not_reused(self):
        r=deepcopy(self.records)
        r["provider"]["measurements"]["refundCount"]=0
        with self.assertRaises(ValueError):self.check(records=r)
        m=deepcopy(self.master)
        next(x for x in m["cases"] if x["caseId"]=="redis_multi_instance_failover")[
            "evidenceDigestSha256"]="f"*64
        with self.assertRaises(ValueError):self.check(master=m)
        r=deepcopy(self.records)
        r["redis"]["measurements"]["noDuplicateWorkOrCharge"]=False
        with self.assertRaises(ValueError):self.check(records=r)

    def test_provider_source_missing_remains_unverified_without_real_provider(self):
        out=self.check(with_sources=False)
        self.assertFalse(out["providerRawExportsReconciled"])
        self.assertEqual(out["decision"],"NO-GO")

    def test_cli_rejects_missing_private_inputs_and_never_writes_fake_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=Path(tmp)/"out.json"
            args=["--master",str(Path(tmp)/"no-master.json"),
                  "--critical",str(Path(tmp)/"no-critical.json"),
                  "--field-records",str(Path(tmp)/"no-field.json"),
                  "--web-sha",WEB,"--skill-sha",SKILL,"--report",str(report)]
            self.assertEqual(main(args),2)
            self.assertFalse(report.exists())


if __name__=="__main__":
    unittest.main()
