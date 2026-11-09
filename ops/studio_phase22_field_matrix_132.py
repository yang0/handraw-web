"""#132 Phase22: OFFLINE, reproducible field-event contract for four D-grade tracks.

Only validates documented observations and binds their evidence fingerprints.
It DOES NOT contact providers, restore databases, inspect source ownership,
grant D PASS or authorize production. All raw records stay in a private vault.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__ in (None,""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops.studio_official_approval_132 import sha
from ops.reconcile_provider_statement_112 import reconcile

SHA40=re.compile(r"^[a-f0-9]{40}$")
SHA64=re.compile(r"^[a-f0-9]{64}$")
TOKEN=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
MAX_BYTES=2_000_000
EVENTS={
 "postgres":("physical_source_and_isolated_host","pg17_basebackup_manifest",
     "pg_verifybackup_succeeded","independent_wal_archive_contiguous",
     "pitr_target_replay_paused","schema_wallet_media_integrity",
     "isolated_rollback_exercised","rpo_rto_measured"),
 "storage":("two_scoped_real_provider_clients","tenant_a_b_own_bytes",
     "cross_tenant_read_denied_both","cross_tenant_write_denied_both",
     "anonymous_read_denied","expired_presigned_url_denied",
     "revoked_and_cdn_old_url_denied","restored_bytes_and_publication_acl"),
 "redis":("two_independent_app_instances","distributed_nx_lock_atomic",
     "tenant_acl_denied_both_directions","failover_fault_injected",
     "lock_owner_fencing_after_failover","recovery_elapsed_measured",
     "no_duplicate_work_or_charge"),
 "provider":("independent_final_provider_statement","web_run_item_attempt_export",
     "wallet_and_free_quota_sources","reconciled_provider_wallet_events",
     "duplicate_callback_replay","429_and_502_failure_paths",
     "unknown_and_late_success_paths","refund_and_free_quota_reconciled"),
}
FIELDS={"schemaVersion","kind","environment","webSha","skillSha","sessionId",
        "operatorId","reviewerId","events","measurements"}
EV_FIELDS={"step","status","observedAtUtc","evidenceSha256"}
PG_FIELDS={"pgMajorVersion","sourceHostSha256","restoreHostSha256",
   "sourceClusterSha256","restoreClusterSha256","basebackupManifestSha256",
   "walArchiveManifestSha256","pitrTargetUtc","pitrReachedUtc",
   "schemaBeforeSha256","schemaAfterSha256","walletBeforeSha256",
   "walletAfterSha256","mediaBeforeSha256","mediaAfterSha256",
   "rpoMeasuredSeconds","rpoBudgetSeconds","rtoMeasuredSeconds",
   "rtoBudgetSeconds","rollbackSuccessful"}
STORAGE_FIELDS={"providerKind","bucketPolicySha256","cdnPolicySha256",
    "mediaBeforeSha256","mediaAfterSha256",
    "tenantASha256","tenantBSha256","anonymousDenied",
    "crossTenantReadDeniedBothDirections","crossTenantWriteDeniedBothDirections",
    "expiredSignedUrlDenied","revokedSignedUrlDenied","cdnOldUrlInvalidated",
    "restoredMediaBytesMatched","publicGrantOnlyForPublishedAssets"}
REDIS_FIELDS={"instanceASha256","instanceBSha256","redisClusterSha256",
    "tenantASha256","tenantBSha256","lockOwnerSha256",
    "faultStartedAtUtc","serviceRestoredAtUtc","rtoBudgetSeconds",
    "sharedNxLockAtomic","tenantAclDeniedBothDirections",
    "lockFenceAfterFailover","noDuplicateWorkOrCharge"}
PROVIDER_FIELDS={"currency","providerStatementSha256",
    "webRunItemAttemptSha256","walletLedgerSha256","freeQuotaLedgerSha256",
    "scenarioTraceSha256","reconciliationReportSha256",
    "paidAttemptCount","refundCount","freeQuotaCasesChecked",
    "duplicateCallbackCasesChecked","throttled429CasesChecked",
    "upstream502CasesChecked","unknownRecoveryCasesChecked",
    "lateSuccessCasesChecked","unmatchedProviderEntryCount",
    "unmatchedWalletEntryCount","netChargeDeltaMinor","netRefundDeltaMinor"}
METRICS={"postgres":PG_FIELDS,"storage":STORAGE_FIELDS,"redis":REDIS_FIELDS,
         "provider":PROVIDER_FIELDS}


def _hash(value):
    if not isinstance(value,str) or not SHA64.fullmatch(value):
        raise ValueError("immutable real-source SHA256 required")


def _token(value):
    if not isinstance(value,str) or not TOKEN.fullmatch(value):
        raise ValueError("bounded non-private witness reference required")


def _stamp(value,now):
    if not isinstance(value,str) or len(value)>35:
        raise ValueError("bounded UTC evidence timestamp required")
    try:
        t=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise ValueError("invalid UTC evidence timestamp") from None
    if t.tzinfo is None or t.utcoffset()!=timedelta(0):
        raise ValueError("UTC evidence timestamp required")
    if t>now+timedelta(minutes=5) or now-t>timedelta(days=30):
        raise ValueError("stale or future evidence timestamp")
    return t


def _int(value,minimum=0):
    if type(value) is not int or not minimum<=value<=10**12:
        raise ValueError("invalid observed nonnegative measurement")


def _measure(kind,m,now):
    if not isinstance(m,dict) or set(m)!=METRICS[kind]:
        raise ValueError("missing/unknown physical event measurements")
    for k,v in m.items():
        if k.endswith("Sha256"):
            _hash(v)
    if kind=="postgres":
        if type(m["pgMajorVersion"]) is not int or m["pgMajorVersion"]!=17:
            raise ValueError("must be PG17 physical")
        for a,b in (("sourceHostSha256","restoreHostSha256"),
                    ("sourceClusterSha256","restoreClusterSha256")):
            if m[a]==m[b]:raise ValueError("same PG physical source and recovery identity")
        for a,b in (("schemaBeforeSha256","schemaAfterSha256"),
                    ("walletBeforeSha256","walletAfterSha256"),
                    ("mediaBeforeSha256","mediaAfterSha256")):
            if m[a]!=m[b]:raise ValueError("PG17 restored business state differs")
        for k in ("rpoMeasuredSeconds","rtoMeasuredSeconds","rpoBudgetSeconds",
                  "rtoBudgetSeconds"):
            _int(m[k],1 if "Budget" in k else 0)
        if (m["rpoMeasuredSeconds"]>m["rpoBudgetSeconds"] or
            m["rtoMeasuredSeconds"]>m["rtoBudgetSeconds"] or
            m["rollbackSuccessful"] is not True):
            raise ValueError("PG17 restore RPO/RTO or rollback failed")
        target=_stamp(m["pitrTargetUtc"],now)
        reached=_stamp(m["pitrReachedUtc"],now)
        if reached<target:
            raise ValueError("PITR observation predates target")
    elif kind=="storage":
        if m["providerKind"] not in ("r2","s3","minio"):
            raise ValueError("not real storage provider")
        if m["tenantASha256"]==m["tenantBSha256"]:
            raise ValueError("same object storage owner")
        if m["mediaBeforeSha256"]!=m["mediaAfterSha256"]:
            raise ValueError("restored media bytes drift")
        for key in STORAGE_FIELDS-{"providerKind"}-{x for x in STORAGE_FIELDS if x.endswith("Sha256")}:
            if m[key] is not True:
                raise ValueError("private object/CDN authorization denial not observed")
    elif kind=="redis":
        if (m["instanceASha256"]==m["instanceBSha256"] or
            m["tenantASha256"]==m["tenantBSha256"]):
            raise ValueError("same Redis app instance or tenant identity")
        start=_stamp(m["faultStartedAtUtc"],now)
        end=_stamp(m["serviceRestoredAtUtc"],now)
        _int(m["rtoBudgetSeconds"],1)
        if end<=start or (end-start).total_seconds()>m["rtoBudgetSeconds"]:
            raise ValueError("Redis failover lacks timed bounded recovery")
        for k in ("sharedNxLockAtomic","tenantAclDeniedBothDirections",
                  "lockFenceAfterFailover","noDuplicateWorkOrCharge"):
            if m[k] is not True:raise ValueError("Redis failover protection not evidenced")
    else:
        if not isinstance(m["currency"],str) or not re.fullmatch(r"[A-Z]{3}",m["currency"]):
            raise ValueError("provider currency absent")
        for k in PROVIDER_FIELDS-{"currency"}-{x for x in PROVIDER_FIELDS if x.endswith("Sha256")}:
            _int(m[k],1 if k in (
                "paidAttemptCount","refundCount","freeQuotaCasesChecked",
                "duplicateCallbackCasesChecked","throttled429CasesChecked",
                "upstream502CasesChecked","unknownRecoveryCasesChecked",
                "lateSuccessCasesChecked") else 0)
        for k in ("unmatchedProviderEntryCount","unmatchedWalletEntryCount",
                  "netChargeDeltaMinor","netRefundDeltaMinor"):
            if m[k]!=0:raise ValueError("provider accounting mismatch")


def evaluate_record(record,*,web_sha,skill_sha,provider=None,handraw=None,now=None):
    """Bound event-source *claims*; provider export comparison runs if supplied."""
    now=now or datetime.now(timezone.utc)
    if (not isinstance(record,dict) or set(record)!=FIELDS or
        type(record["schemaVersion"]) is not int or record["schemaVersion"]!=1):
        raise ValueError("invalid Phase22 field contract")
    kind=record["kind"]
    if kind not in EVENTS or record["environment"]!="preproduction":
        raise ValueError("only explicitly preproduction Phase22 D rehearsals supported")
    if (not isinstance(web_sha,str) or not SHA40.fullmatch(web_sha)
        or not isinstance(skill_sha,str) or not SHA40.fullmatch(skill_sha)
        or record["webSha"]!=web_sha or record["skillSha"]!=skill_sha):
        raise ValueError("field evidence SHA drift")
    for f in ("sessionId","operatorId","reviewerId"):
        _token(record[f])
    if record["operatorId"]==record["reviewerId"]:
        raise ValueError("no self-witnessed field D record")
    events=record["events"]
    if not isinstance(events,list) or len(events)!=len(EVENTS[kind]):
        raise ValueError("missing or extra required D protocol observations")
    seen_hashes=set()
    previous=None
    for event,step in zip(events,EVENTS[kind]):
        if (not isinstance(event,dict) or set(event)!=EV_FIELDS
            or event["step"]!=step or event["status"]!="OBSERVED"):
            raise ValueError("missing/failed/reordered Phase22 physical observation")
        _hash(event["evidenceSha256"])
        if event["evidenceSha256"] in seen_hashes:
            raise ValueError("one screenshot/log cannot certify multiple D observations")
        seen_hashes.add(event["evidenceSha256"])
        stamp=_stamp(event["observedAtUtc"],now)
        if previous and stamp<previous:
            raise ValueError("out-of-order physical evidence")
        previous=stamp
    _measure(kind,record["measurements"],now)
    report=None
    if kind=="provider":
        if (provider is None)!=(handraw is None):
            raise ValueError("partial provider billing sources refused")
        if provider is not None:
            if (sha(provider)!=record["measurements"]["providerStatementSha256"]
                or sha(handraw)!=record["measurements"]["webRunItemAttemptSha256"]):
                raise ValueError("provider ledger input digest drift")
            report=reconcile(provider,handraw)
            observed_refunds=sum(
                x.get("kind")=="refund" for x in provider.get("events",[]))
            wallet_refunds=sum(
                x.get("kind")=="studio_refund" for x in handraw.get("ledger_events",[]))
            if (report["anomalies"] or report["result"]!="NO_AUTOMATED_ANOMALIES"
                or report["counts"]["attempts"]<1
                or report["counts"]["attempts"]!=record["measurements"]["paidAttemptCount"]
                or provider.get("currency")!=record["measurements"]["currency"]
                or observed_refunds!=record["measurements"]["refundCount"]
                or wallet_refunds!=observed_refunds
                or sha(report)!=record["measurements"]["reconciliationReportSha256"]):
                raise ValueError("paid-provider actual-source reconciliation failed")
    return {
        "phase":22,"issue":132,"kind":kind,"recordSha256":sha(record),
        "observedEventContracts":len(events),
        "paidProviderSourceReconciliationChecked":report is not None,
        "fieldRecordIsUnverifiedClaim":True,
        "externalSourceAuthenticityProven":False,
        "independentOnsiteAuditStillRequired":True,
        "dGradePassed":False,"releaseAuthorized":False,"decision":"NO-GO",
    }


def _private_json(path):
    if (path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES
        or (os.name=="posix" and stat.S_IMODE(path.stat().st_mode)&0o077)):
        raise ValueError("private witness must exist, regular and mode 0600")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--record",type=Path,required=True)
    p.add_argument("--web-sha",required=True)
    p.add_argument("--skill-sha",required=True)
    p.add_argument("--provider",type=Path)
    p.add_argument("--handraw",type=Path)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        if args.report.exists() or args.report.is_symlink():
            raise ValueError("refuse report overwrite")
        result=evaluate_record(_private_json(args.record),web_sha=args.web_sha,
            skill_sha=args.skill_sha,
            provider=_private_json(args.provider) if args.provider else None,
            handraw=_private_json(args.handraw) if args.handraw else None)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(result,out,ensure_ascii=False,sort_keys=True,indent=2)
            out.write("\n")
        print("PHASE22 D FIELD "+json.dumps({
            "kind":result["kind"],"decision":"NO-GO","secretsEmitted":False}))
        return 0
    except Exception:
        print("Phase22 field D evidence BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
