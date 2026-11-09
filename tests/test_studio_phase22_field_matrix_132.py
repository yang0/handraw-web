"""#132 Phase22: no fake D PASS; strict physical/protocol evidence claims."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest

from ops.studio_official_approval_132 import sha
from ops.reconcile_provider_statement_112 import reconcile
from ops.studio_phase22_field_matrix_132 import (
    EVENTS,PG_FIELDS,STORAGE_FIELDS,REDIS_FIELDS,PROVIDER_FIELDS,
    evaluate_record,main,
)

WEB="a"*40
SKILL="b"*40
NOW=datetime(2026,11,10,3,0,0,tzinfo=timezone.utc)
ISO=lambda x: x.strftime("%Y-%m-%dT%H:%M:%SZ")


def provider_sample():
    start="2026-11-01T00:00:00Z"
    end="2026-11-02T00:00:00Z"
    when="2026-11-01T12:00:00Z"
    tasks=[]
    events=[]
    attempts=[]
    ledger=[]
    callbacks=[]
    for i,kind in ((1,"succeeded"),(2,"failed")):
        base={"owner_key":"qa-operator","request_id":f"request-{i}","attempt":1}
        task=f"task-{i}"
        tasks.append({**base,"provider_task_id":task,"state":kind})
        events.append({**base,"event_id":f"charge-{i}","provider_task_id":task,
             "kind":"charge","currency":"USD","amount_minor":125,
             "occurred_at_utc":when})
        attempts.append({**base,"run_id":f"run-{i}","item_id":f"item-{i}",
            "slot_key":"slot-1","provider_task_id":task,
            "submitted":True,"status":"success" if i==1 else "refunded",
            "cost_type":"credits"})
        ledger.append({**base,"event_key":f"wallet-charge-{i}",
            "kind":"studio_gen","delta_credits":-3,"occurred_at_utc":when})
        callbacks.append({**base,"callback_event_id":f"callback-{i}",
             "provider_task_id":task,"state":kind,"occurred_at_utc":when})
        if i==2:
            events.append({**base,"event_id":"refund-2","provider_task_id":task,
                 "kind":"refund","currency":"USD","amount_minor":125,
                 "occurred_at_utc":when})
            ledger.append({**base,"event_key":"wallet-refund-2",
                 "kind":"studio_refund","delta_credits":3,
                 "occurred_at_utc":when})
    p={"schema_version":1,"source":"provider_export","environment":"preproduction",
       "release_sha":WEB,"window":{"start_utc":start,"end_utc":end,
       "exported_at_utc":"2026-11-04T00:00:00Z",
       "settlement_grace_minutes":1440,"invoice_final":True},
       "currency":"USD","tasks":tasks,"events":events}
    h={"schema_version":1,"source":"handraw_export",
       "environment":"preproduction","release_sha":WEB,
       "window":{"start_utc":start,"end_utc":end},
       "attempts":attempts,"ledger_events":ledger,"callbacks":callbacks}
    return p,h


def event_packet(kind):
    base={"schemaVersion":1,"kind":kind,"environment":"preproduction",
       "webSha":WEB,"skillSha":SKILL,"sessionId":"preprod-field-session-22",
       "operatorId":"qa-operator-22","reviewerId":"qa-independent-auditor-22",
       "events":[{"step":step,"status":"OBSERVED",
                  "observedAtUtc":ISO(NOW-timedelta(minutes=1)),
                  "evidenceSha256":sha({"kind":kind,"step":step})}
                 for step in EVENTS[kind]]}
    def dig(x):return sha({"field":kind,"key":x})
    if kind=="postgres":
        m={k:dig(k) for k in PG_FIELDS if k.endswith("Sha256")}
        for label in ("schema","wallet","media"):
            m[label+"AfterSha256"]=m[label+"BeforeSha256"]
        m.update({"pgMajorVersion":17,
                  "pitrTargetUtc":ISO(NOW-timedelta(minutes=4)),
                  "pitrReachedUtc":ISO(NOW-timedelta(minutes=3)),
                  "rpoMeasuredSeconds":30,"rpoBudgetSeconds":60,
                  "rtoMeasuredSeconds":100,"rtoBudgetSeconds":300,
                  "rollbackSuccessful":True})
    elif kind=="storage":
        m={k:dig(k) for k in STORAGE_FIELDS if k.endswith("Sha256")}
        m["mediaAfterSha256"]=m["mediaBeforeSha256"]
        m["providerKind"]="r2"
        for key in STORAGE_FIELDS-set(m):
            m[key]=True
    elif kind=="redis":
        m={k:dig(k) for k in REDIS_FIELDS if k.endswith("Sha256")}
        m.update({"faultStartedAtUtc":ISO(NOW-timedelta(minutes=5)),
                  "serviceRestoredAtUtc":ISO(NOW-timedelta(minutes=4)),
                  "rtoBudgetSeconds":180,
                  "sharedNxLockAtomic":True,
                  "tenantAclDeniedBothDirections":True,
                  "lockFenceAfterFailover":True,
                  "noDuplicateWorkOrCharge":True})
    else:
        p,h=provider_sample()
        report=reconcile(p,h)
        assert report["anomalies"]==[]
        m={k:dig(k) for k in PROVIDER_FIELDS if k.endswith("Sha256")}
        m["providerStatementSha256"]=sha(p)
        m["webRunItemAttemptSha256"]=sha(h)
        m["reconciliationReportSha256"]=sha(report)
        m.update({"currency":"USD","paidAttemptCount":2,"refundCount":1,
            "freeQuotaCasesChecked":1,"duplicateCallbackCasesChecked":1,
            "throttled429CasesChecked":1,"upstream502CasesChecked":1,
            "unknownRecoveryCasesChecked":1,"lateSuccessCasesChecked":1,
            "unmatchedProviderEntryCount":0,"unmatchedWalletEntryCount":0,
            "netChargeDeltaMinor":0,"netRefundDeltaMinor":0})
    base["measurements"]=m
    return base


class Phase22DFieldMatrixTests(unittest.TestCase):
    def check(self,record,provider=None,handraw=None):
        return evaluate_record(record,web_sha=WEB,skill_sha=SKILL,
            provider=provider,handraw=handraw,now=NOW)

    def test_four_field_protocols_never_automatically_certify_grade_d(self):
        for kind in EVENTS:
            packet=event_packet(kind)
            with self.subTest(kind=kind):
                p,h=provider_sample() if kind=="provider" else (None,None)
                out=self.check(packet,provider=p,handraw=h)
                self.assertEqual(out["observedEventContracts"],len(EVENTS[kind]))
                self.assertEqual(out["decision"],"NO-GO")
                self.assertFalse(out["dGradePassed"])
                self.assertFalse(out["externalSourceAuthenticityProven"])
                self.assertEqual(out["recordSha256"],sha(packet))
                self.assertEqual(out["paidProviderSourceReconciliationChecked"],
                                 kind=="provider")
                self.assertNotIn("qa-operator",json.dumps(out))

    def test_missing_reordered_duplicate_and_replayed_events_all_block(self):
        for kind in EVENTS:
            with self.subTest(kind=kind):
                r=event_packet(kind)
                r["events"].pop()
                with self.assertRaises(ValueError):self.check(r)
                r=event_packet(kind)
                r["events"][0]["step"]="something-else"
                with self.assertRaises(ValueError):self.check(r)
                r=event_packet(kind)
                r["events"][1]["evidenceSha256"]=r["events"][0]["evidenceSha256"]
                with self.assertRaises(ValueError):self.check(r)
                r=event_packet(kind)
                r["events"][0]["status"]="PASS"  # a self-reported PASS is not proof
                with self.assertRaises(ValueError):self.check(r)
                r=event_packet(kind)
                r["events"][0]["observedAtUtc"]="2025-01-01T00:00:00Z"
                with self.assertRaises(ValueError):self.check(r)

    def test_invalid_source_and_same_signer_preprod_identity_refuse(self):
        for field,value in (("environment","production"),
                            ("webSha","c"*40),
                            ("skillSha","d"*40),
                            ("reviewerId","qa-operator-22")):
            r=event_packet("storage")
            r[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.check(r)
        r=event_packet("storage")
        r["measurements"]["rawAwsSecret"]="never-allowed"
        with self.assertRaises(ValueError):self.check(r)

    def test_pg17_host_identity_pitr_ledger_and_rpo_all_guarded(self):
        for field,value in (
            ("pgMajorVersion",16),
            ("sourceHostSha256",event_packet("postgres")["measurements"]["restoreHostSha256"]),
            ("walletAfterSha256","e"*64),
            ("rpoMeasuredSeconds",61),
            ("rtoMeasuredSeconds",301),
            ("rollbackSuccessful",False),
            ("pitrReachedUtc",ISO(NOW-timedelta(minutes=6))),
        ):
            r=event_packet("postgres")
            r["measurements"][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.check(r)

    def test_storage_real_ownership_cdn_revoke_and_byte_restore_guarded(self):
        for field,value in (
            ("providerKind","moto"),
            ("tenantBSha256",event_packet("storage")["measurements"]["tenantASha256"]),
            ("expiredSignedUrlDenied",False),
            ("cdnOldUrlInvalidated",False),
            ("revokedSignedUrlDenied",False),
            ("mediaAfterSha256","0"*64),
        ):
            r=event_packet("storage")
            r["measurements"][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.check(r)

    def test_redis_actual_different_instances_failover_and_fence(self):
        for field,value in (
            ("instanceBSha256",event_packet("redis")["measurements"]["instanceASha256"]),
            ("lockFenceAfterFailover",False),
            ("noDuplicateWorkOrCharge",False),
            ("rtoBudgetSeconds",5),
            ("serviceRestoredAtUtc",ISO(NOW-timedelta(minutes=6))),
        ):
            r=event_packet("redis")
            r["measurements"][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.check(r)

    def test_provider_final_statement_must_match_wallet_and_external_refunds(self):
        p,h=provider_sample()
        r=event_packet("provider")
        self.assertTrue(self.check(r,p,h)["paidProviderSourceReconciliationChecked"])
        for key,value in (
            ("providerStatementSha256","f"*64),
            ("refundCount",0),
            ("paidAttemptCount",3),
            ("currency","EUR"),
            ("reconciliationReportSha256","f"*64),
            ("unknownRecoveryCasesChecked",0),
            ("freeQuotaCasesChecked",0),
        ):
            mutated=deepcopy(r)
            mutated["measurements"][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.check(mutated,p,h)
        bad=deepcopy(h)
        bad["attempts"][0]["status"]="refunded"  # mismatch without provider refund
        r2=deepcopy(r)
        r2["measurements"]["webRunItemAttemptSha256"]=sha(bad)
        with self.assertRaises(ValueError):self.check(r2,p,bad)
        with self.assertRaises(ValueError):self.check(r,provider=p,handraw=None)

    def test_private_cli_fail_closed_never_overwrites_or_prints_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            report=d/"report.json"
            args=["--record",str(d/"unavailable.json"),
                  "--web-sha",WEB,"--skill-sha",SKILL,"--report",str(report)]
            self.assertEqual(main(args),2)
            r=d/"record.json"
            # CLI uses the runner's real UTC clock rather than the test-only
            # frozen NOW used by evaluate_record pure unit tests.
            current=datetime.now(timezone.utc)
            packet=event_packet("redis")
            for row in packet["events"]:
                row["observedAtUtc"]=ISO(current-timedelta(minutes=1))
            packet["measurements"]["faultStartedAtUtc"]=ISO(current-timedelta(minutes=3))
            packet["measurements"]["serviceRestoredAtUtc"]=ISO(current-timedelta(minutes=2))
            r.write_text(json.dumps(packet),encoding="utf-8")
            r.chmod(0o600)
            args[1]=str(r)
            self.assertEqual(main(args),0)
            self.assertEqual(json.loads(report.read_text())["decision"],"NO-GO")
            self.assertEqual(main(args),2)


if __name__=="__main__":
    unittest.main()
