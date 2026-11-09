"""#132 Phase22 D-master crosswalk: join 17-case manifest to actual field claims.

This is an offline schema/sha crosswalk only. It never grants a D PASS.
Release GO requires real unforgeable source evidence and independent on-site
audit, outside this repository. No credentials or customer data are logged.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

if __package__ in (None,""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops.studio_official_approval_132 import sha
from ops.studio_d_environment_assertions_132 import evaluate as check_master
from ops.studio_d_receipt_contract_132 import evaluate as check_critical,GATES
from ops.studio_phase22_field_matrix_132 import evaluate_record

MAPPING={
 "postgres":{
   "pgMajorVersion":"pgMajorVersion",
   "basebackupManifestSha256":"basebackupManifestSha256",
   "walArchiveManifestSha256":"walArchiveManifestSha256",
   "sourceClusterIdSha256":"sourceClusterSha256",
   "restoreClusterIdSha256":"restoreClusterSha256",
   "schemaFingerprintBeforeSha256":"schemaBeforeSha256",
   "schemaFingerprintAfterSha256":"schemaAfterSha256",
   "walletLedgerBeforeSha256":"walletBeforeSha256",
   "walletLedgerAfterSha256":"walletAfterSha256",
   "mediaManifestBeforeSha256":"mediaBeforeSha256",
   "mediaManifestAfterSha256":"mediaAfterSha256",
   "rollbackDrilled":"rollbackSuccessful",
   "rpoMeasuredSeconds":"rpoMeasuredSeconds",
   "rpoBudgetSeconds":"rpoBudgetSeconds",
   "rtoMeasuredSeconds":"rtoMeasuredSeconds",
   "rtoBudgetSeconds":"rtoBudgetSeconds",
 },
 "storage":{
   "providerKind":"providerKind",
   "bucketPolicySha256":"bucketPolicySha256",
   "cdnPolicySha256":"cdnPolicySha256",
   "anonymousDenied":"anonymousDenied",
   "crossTenantReadDeniedBothDirections":"crossTenantReadDeniedBothDirections",
   "crossTenantWriteDeniedBothDirections":"crossTenantWriteDeniedBothDirections",
   "expiredSignedUrlDenied":"expiredSignedUrlDenied",
   "revokedSignedUrlDenied":"revokedSignedUrlDenied",
   "cdnOldUrlInvalidated":"cdnOldUrlInvalidated",
   "restoredMediaBytesMatched":"restoredMediaBytesMatched",
   "publicGrantOnlyForPublishedAssets":"publicGrantOnlyForPublishedAssets",
 },
 "provider":{
   "providerStatementSha256":"providerStatementSha256",
   "webRunItemAttemptSha256":"webRunItemAttemptSha256",
   "walletLedgerSha256":"walletLedgerSha256",
   "freeQuotaLedgerSha256":"freeQuotaLedgerSha256",
   "reconciliationReportSha256":"reconciliationReportSha256",
   "currency":"currency","paidAttemptCount":"paidAttemptCount",
   "refundCount":"refundCount",
   "freeQuotaCasesChecked":"freeQuotaCasesChecked",
   "duplicateCallbackCasesChecked":"duplicateCallbackCasesChecked",
   "throttled429CasesChecked":"throttled429CasesChecked",
   "upstream502CasesChecked":"upstream502CasesChecked",
   "unknownRecoveryCasesChecked":"unknownRecoveryCasesChecked",
   "lateSuccessCasesChecked":"lateSuccessCasesChecked",
   "unmatchedProviderEntryCount":"unmatchedProviderEntryCount",
   "unmatchedWalletEntryCount":"unmatchedWalletEntryCount",
   "netChargeDeltaMinor":"netChargeDeltaMinor",
   "netRefundDeltaMinor":"netRefundDeltaMinor",
 },
}
MAX_BYTES=2_000_000


def evaluate_join(*,master,critical,field_records,web_sha,skill_sha,
                  provider=None,handraw=None,now=None):
    """Refuse missing links rather than filling invented production evidence."""
    checked=check_master(master,web_sha=web_sha,skill_sha=skill_sha,now=now)
    details=check_critical(critical,master,web_sha=web_sha,skill_sha=skill_sha,now=now)
    if not isinstance(field_records,dict) or set(field_records)!={"postgres","storage","redis","provider"}:
        raise ValueError("four site-level field records required")
    indexed={}
    for item in critical["receipts"]:
        indexed[item["kind"]]=item["details"]
    compared=[]
    field_digests={}
    for kind,record in field_records.items():
        output=evaluate_record(record,web_sha=web_sha,skill_sha=skill_sha,
             provider=provider if kind=="provider" else None,
             handraw=handraw if kind=="provider" else None,now=now)
        field_digests[kind]=output["recordSha256"]
        if kind=="redis":
            continue
        if kind not in indexed:
            raise ValueError("missing detailed D receipts for field evidence")
        actual=indexed[kind]
        measured=record["measurements"]
        for receipt_name,record_name in MAPPING[kind].items():
            if actual[receipt_name]!=measured[record_name]:
                raise ValueError("D critical receipt and field measurement drift")
        if kind=="postgres":
            if actual["independentHostClaim"] is not True or actual["restoreCompleted"] is not True or actual["pitrTargetReached"] is not True:
                raise ValueError("PG17 independent host/PITR record incomplete")
        if kind=="storage":
            if sha(actual["tenantOneRef"])!=measured["tenantASha256"] or sha(actual["tenantTwoRef"])!=measured["tenantBSha256"]:
                raise ValueError("storage tenant identity does not match private field witness")
            if actual["uploadDownloadManifestSha256"]!=measured["mediaBeforeSha256"]:
                raise ValueError("media manifest source mismatch")
        compared.append(kind)
    case={x["caseId"]:x for x in master["cases"]}
    redis_claim=case.get("redis_multi_instance_failover")
    if redis_claim is None or redis_claim["evidenceDigestSha256"]!=field_digests["redis"]:
        raise ValueError("real Redis failover field record not bound to D master case")
    # Other three master evidence hashes are bound to the *critical receipt*
    # canonical details by check_critical(), which are then mapped to field
    # metrics above. Their signed source digests are checked separately.
    return {
        "phase":22,"issue":132,"requiredDCaseCount":checked["requiredCaseCount"],
        "structuralDClaimCount":checked["schemaValidClaimCount"],
        "structuralClaimPassCount":checked["claimedPassCount"],
        "linkedCriticalReceipts":len(compared),
        "redisFailoverFieldDigestBound":True,
        "criticalDetailsBoundToPhysicalEvents":True,
        "providerRawExportsReconciled":provider is not None and handraw is not None,
        "signedFieldSourceAuthenticityVerifiedHere":False,
        "all17ClaimsPresent":checked["schemaValidClaimCount"]==17,
        "externalRealWorldDPassProven":False,
        "automaticIssueClosureAuthorized":False,
        "releaseAuthorized":False,"decision":"NO-GO",
    }


def _private(path):
    if (path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES
        or (os.name=="posix" and stat.S_IMODE(path.stat().st_mode)&0o077)):
        raise ValueError("private D crosswalk input invalid")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--master",type=Path,required=True)
    ap.add_argument("--critical",type=Path,required=True)
    ap.add_argument("--field-records",type=Path,required=True)
    ap.add_argument("--provider",type=Path)
    ap.add_argument("--handraw",type=Path)
    ap.add_argument("--web-sha",required=True)
    ap.add_argument("--skill-sha",required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        if args.report.exists() or args.report.is_symlink():
            raise ValueError("cannot replace prior D evidence result")
        if bool(args.provider)!=bool(args.handraw):
            raise ValueError("partial provider billing sources forbidden")
        result=evaluate_join(master=_private(args.master),
            critical=_private(args.critical),field_records=_private(args.field_records),
            web_sha=args.web_sha,skill_sha=args.skill_sha,
            provider=_private(args.provider) if args.provider else None,
            handraw=_private(args.handraw) if args.handraw else None)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(result,out,indent=2,sort_keys=True,ensure_ascii=False)
            out.write("\n")
        print("PHASE22 D CROSSWALK "+json.dumps({
            "linked":result["linkedCriticalReceipts"],
            "decision":"NO-GO","privateRowContentsEmitted":False}))
        return 0
    except Exception:
        print("Phase22 D field-to-master crosswalk BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
