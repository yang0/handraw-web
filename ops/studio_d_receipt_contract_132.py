"""#132: OFFLINE detail receipts for the three hardest external D gates.

This validates shape, cross-document SHA binding, accounting invariants and
required scenario claims. It NEVER verifies actual provider/PG/R2 access or
releases production. Raw proof stays with independent auditors in a private
0600 evidence vault and must never be uploaded to Actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from ops.studio_d_environment_assertions_132 import evaluate as check_claims

GATES = {
    "provider": "real_provider_charge_refund_ledger",
    "postgres": "pg17_offline_backup_restore_rollback",
    "storage": "real_object_bucket_and_expired_url",
}
HEX = re.compile(r"^[a-f0-9]{64}$")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
MAX_BYTES = 256_000
PROVIDER_FIELDS = {
    "providerStatementSha256", "webRunItemAttemptSha256",
    "walletLedgerSha256", "freeQuotaLedgerSha256",
    "reconciliationReportSha256", "currency", "paidAttemptCount",
    "refundCount", "freeQuotaCasesChecked", "unmatchedProviderEntryCount",
    "unmatchedWalletEntryCount", "netChargeDeltaMinor",
    "netRefundDeltaMinor", "duplicateCallbackCasesChecked",
    "throttled429CasesChecked", "upstream502CasesChecked",
    "unknownRecoveryCasesChecked", "lateSuccessCasesChecked",
}
PG_FIELDS = {
    "pgMajorVersion", "basebackupManifestSha256", "walArchiveManifestSha256",
    "sourceClusterIdSha256", "restoreClusterIdSha256",
    "schemaFingerprintBeforeSha256", "schemaFingerprintAfterSha256",
    "walletLedgerBeforeSha256", "walletLedgerAfterSha256",
    "mediaManifestBeforeSha256", "mediaManifestAfterSha256",
    "independentHostClaim", "restoreCompleted", "pitrTargetReached",
    "rollbackDrilled", "rpoMeasuredSeconds", "rpoBudgetSeconds",
    "rtoMeasuredSeconds", "rtoBudgetSeconds",
}
STORAGE_FIELDS = {
    "providerKind", "bucketPolicySha256", "cdnPolicySha256",
    "uploadDownloadManifestSha256", "tenantOneRef", "tenantTwoRef",
    "anonymousDenied", "crossTenantReadDeniedBothDirections",
    "crossTenantWriteDeniedBothDirections", "expiredSignedUrlDenied",
    "revokedSignedUrlDenied", "cdnOldUrlInvalidated",
    "restoredMediaBytesMatched", "publicGrantOnlyForPublishedAssets",
}
BOOL_STORAGE = STORAGE_FIELDS - {
    "providerKind", "bucketPolicySha256", "cdnPolicySha256",
    "uploadDownloadManifestSha256", "tenantOneRef", "tenantTwoRef",
}
COUNT_PROVIDER = {
    "paidAttemptCount", "refundCount", "freeQuotaCasesChecked",
    "unmatchedProviderEntryCount", "unmatchedWalletEntryCount", "netChargeDeltaMinor", "netRefundDeltaMinor",
    "duplicateCallbackCasesChecked", "throttled429CasesChecked",
    "upstream502CasesChecked", "unknownRecoveryCasesChecked",
    "lateSuccessCasesChecked",
}
HASH_PROVIDER = PROVIDER_FIELDS - COUNT_PROVIDER - {"currency"}
HASH_PG = {x for x in PG_FIELDS if x.endswith("Sha256")}


def digest(obj):
    return hashlib.sha256(json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _sha(value):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError("missing/invalid private original evidence SHA256")


def _number(value, *, minimum=0):
    if type(value) is not int or not minimum <= value <= 10**12:
        raise ValueError("invalid measured D gate count/amount")


def _details(kind, data):
    allowed = {"provider": PROVIDER_FIELDS,
               "postgres": PG_FIELDS, "storage": STORAGE_FIELDS}[kind]
    if not isinstance(data, dict) or set(data) != allowed:
        raise ValueError("missing or unexpected D receipt details")
    if kind == "provider":
        for f in HASH_PROVIDER:
            _sha(data[f])
        if not isinstance(data["currency"], str) or not CURRENCY.fullmatch(data["currency"]):
            raise ValueError("invalid reconciled currency")
        for f in COUNT_PROVIDER:
            _number(data[f], minimum=1 if f in {
                "paidAttemptCount", "refundCount", "freeQuotaCasesChecked",
                "duplicateCallbackCasesChecked", "throttled429CasesChecked", "upstream502CasesChecked",
                "unknownRecoveryCasesChecked", "lateSuccessCasesChecked",
            } else 0)
        for f in ("unmatchedProviderEntryCount", "unmatchedWalletEntryCount",
                  "netChargeDeltaMinor", "netRefundDeltaMinor"):
            if data[f] != 0:
                raise ValueError("provider-to-wallet mismatch")
    elif kind == "postgres":
        if data["pgMajorVersion"] != 17 or type(data["pgMajorVersion"]) is not int:
            raise ValueError("physical restore must use PG17")
        for f in HASH_PG:
            _sha(data[f])
        if data["sourceClusterIdSha256"] == data["restoreClusterIdSha256"]:
            raise ValueError("source and physical restore cluster are not independently identified")
        for prefix in ("schemaFingerprint", "walletLedger", "mediaManifest"):
            if data[prefix+"BeforeSha256"] != data[prefix+"AfterSha256"]:
                raise ValueError("PG17 recovered business ledger/media fingerprint mismatch")
        for f in ("independentHostClaim", "restoreCompleted", "pitrTargetReached",
                  "rollbackDrilled"):
            if data[f] is not True:
                raise ValueError("physical PITR/rollback/independent host missing")
        for f in ("rpoMeasuredSeconds", "rpoBudgetSeconds",
                  "rtoMeasuredSeconds", "rtoBudgetSeconds"):
            _number(data[f], minimum=1 if "Budget" in f else 0)
        for p in ("rpo", "rto"):
            if data[p+"MeasuredSeconds"] > data[p+"BudgetSeconds"]:
                raise ValueError("measured restore exceeded RPO/RTO budget")
    else:
        if data["providerKind"] not in ("r2", "s3", "minio"):
            raise ValueError("not a real object storage provider")
        for f in ("bucketPolicySha256", "cdnPolicySha256",
                  "uploadDownloadManifestSha256"):
            _sha(data[f])
        for f in ("tenantOneRef", "tenantTwoRef"):
            if not isinstance(data[f], str) or not TOKEN.fullmatch(data[f]):
                raise ValueError("unbounded tenant witness ref")
        if data["tenantOneRef"] == data["tenantTwoRef"]:
            raise ValueError("cross-tenant test requires two independent owners")
        for f in BOOL_STORAGE:
            if data[f] is not True:
                raise ValueError("private bucket/cross-tenant CDN protection failed")


def evaluate(receipts, claims, *, web_sha, skill_sha, now=None):
    """No external witness authenticity is provable by a submitted JSON file."""
    checked = check_claims(claims, web_sha=web_sha, skill_sha=skill_sha, now=now)
    if (not isinstance(receipts, dict) or set(receipts) !=
            {"schemaVersion", "deployedSha", "skillSha", "receipts"}
            or type(receipts["schemaVersion"]) is not int
            or receipts["schemaVersion"] != 1
            or receipts["deployedSha"] != web_sha
            or receipts["skillSha"] != skill_sha
            or not isinstance(receipts["receipts"], list)
            or len(receipts["receipts"]) > len(GATES)):
        raise ValueError("invalid/mismatched private receipts packet")
    cases = {row["caseId"]: row for row in claims["cases"]} if claims else {}
    seen = set()
    for row in receipts["receipts"]:
        if not isinstance(row, dict) or set(row) != {
                "kind", "caseId", "evidenceDigestSha256", "details"}:
            raise ValueError("invalid detailed receipt")
        kind = row["kind"]
        if kind not in GATES or kind in seen or row["caseId"] != GATES[kind]:
            raise ValueError("wrong/duplicate detailed D gate")
        seen.add(kind)
        claim = cases.get(row["caseId"])
        if claim is None or claim["status"] != "PASS":
            raise ValueError("detailed receipt has no matching D claim")
        _details(kind, row["details"])
        if (row["evidenceDigestSha256"] != claim["evidenceDigestSha256"]
                or row["evidenceDigestSha256"] != digest(row["details"])):
            raise ValueError("detailed receipt hash does not match 17-case manifest")
    return {
        "issue": 132, "requiredDetailedCases": len(GATES),
        "linkedDetailedCases": len(seen),
        "missingDetailedCases": [GATES[k] for k in GATES if k not in seen],
        "all17CasesClaimPass": checked["allCasesClaimPass"],
        "privateDataEmitted": False,
        "externalSourceAuthenticityVerified": False,
        "physicalPitrActuallyPerformed": False,
        "vendorStatementActuallyRetrieved": False,
        "privateS3ActuallyTested": False,
        "autoReleaseAuthorized": False, "decision": "NO-GO",
    }


def _private(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("invalid/oversized private receipt file")
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("private receipt must be owner-only 0600")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claims", type=Path, required=True)
    ap.add_argument("--receipts", type=Path, required=True)
    ap.add_argument("--web-sha", required=True)
    ap.add_argument("--skill-sha", required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.report.exists() or args.report.is_symlink():
            raise ValueError("cannot overwrite a private audit report")
        result = evaluate(_private(args.receipts), _private(args.claims),
                          web_sha=args.web_sha, skill_sha=args.skill_sha)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
            out.write("\n")
        print("D-RECEIPTS " + json.dumps({
            "linked": result["linkedDetailedCases"], "decision": "NO-GO",
            "privateDataEmitted": False,
        }))
        return 0
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
        print("D receipt integrity BLOCKED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
