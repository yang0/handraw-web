"""#132 Phase22 detailed physical PG / S3+CDN / Redis failover field receipts.

Validates *claims* about independent live evidence, not raw evidence origin.
Must be bound to out-of-band hash-pinned private witness bytes by
studio_phase22_witness_chain_132.py before external human D-level review.
Never creates GO or upgrades any of the 17 release cases.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from ops.studio_d_receipt_contract_132 import digest

HEX=re.compile(r"^[a-f0-9]{64}$")
SHA=re.compile(r"^[a-f0-9]{40}$")
IDENT=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
FIELDS={"schemaVersion","environment","webSha","skillSha","postgres",
        "storage","redis"}
PG={"physicalBasebackupSha256","walArchiveSha256","sourcePhysicalHostSha256",
    "recoveryPhysicalHostSha256","targetUtc","recoveredReplayLsn",
    "businessFingerprintBeforeSha256","businessFingerprintAfterSha256",
    "walletLedgerBeforeSha256","walletLedgerAfterSha256",
    "mediaIndexBeforeSha256","mediaIndexAfterSha256",
    "pg17PhysicalBackupVerified","pg17WalReplayAtTarget","rollbackDrilled",
    "rpoBudgetSeconds","rpoMeasuredSeconds",
    "rtoBudgetSeconds","rtoMeasuredSeconds"}
ST={"bucketPolicySha256","cdnPolicySha256","tenantOneScopeSha256",
    "tenantTwoScopeSha256","sourceObjectBytesSha256",
    "restoredObjectBytesSha256","anonymousDenied",
    "crossTenantReadDeniedBothDirections",
    "crossTenantWriteDeniedBothDirections",
    "expiredUrlDenied","revokedUrlDenied","cdnTombstoneDenied",
    "publishedPublicGrantOnly"}
REDIS={"clusterTopologyBeforeSha256","clusterTopologyAfterSha256",
       "fencedLeaderEpochBefore","fencedLeaderEpochAfter",
       "sharedLockOwnerSha256","recoveredLockOwnerSha256",
       "tenantAclBeforeSha256","tenantAclAfterSha256",
       "twoPhysicalInstanceWitnesses","failoverPerformed",
       "oldLeaderWritesRejected","newLeaderResumed",
       "noDuplicateRunExecution","crossTenantKeysDenied"}


def _hash(v):
    if not isinstance(v,str) or not HEX.fullmatch(v):
        raise ValueError("missing independently sourced private witness SHA")


def _yes(v):
    if v is not True:
        raise ValueError("required field observation not affirmative")


def _count(v,*,positive=False):
    if type(v) is not int or not (0<v<=10**12 if positive else 0<=v<=10**12):
        raise ValueError("invalid measured value")


def _stamp(v,*,now=None):
    if (not isinstance(v,str) or
        not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ",v)):
        raise ValueError("precise PITR UTC required")
    try:
        when=datetime.strptime(v,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError("invalid PITR calendar date") from None
    now=now or datetime.now(timezone.utc)
    if (now.tzinfo is None or now.utcoffset()!=timedelta(0)
        or when>now+timedelta(minutes=5)
        or now-when>timedelta(days=30)):
        raise ValueError("future, stale or non-UTC PITR target")
    return when


def evaluate(dossier,*,web_sha,skill_sha,now=None):
    if (not isinstance(web_sha,str) or not SHA.fullmatch(web_sha)
        or not isinstance(skill_sha,str) or not SHA.fullmatch(skill_sha)):
        raise ValueError("full Web and Skill SHAs required")
    if (not isinstance(dossier,dict) or set(dossier)!=FIELDS or
        dossier["schemaVersion"]!=1 or dossier["environment"]!="preproduction"
        or dossier["webSha"]!=web_sha or dossier["skillSha"]!=skill_sha):
        raise ValueError("invalid/mismatched independent D field receipt")
    pg,st,rd=(dossier.get(k) for k in ("postgres","storage","redis"))
    if not isinstance(pg,dict) or set(pg)!=PG or not isinstance(st,dict) or set(st)!=ST or not isinstance(rd,dict) or set(rd)!=REDIS:
        raise ValueError("missing/extra field receipt keys")
    for field in (k for k in PG if k.endswith("Sha256")):
        _hash(pg[field])
    if pg["sourcePhysicalHostSha256"]==pg["recoveryPhysicalHostSha256"]:
        raise ValueError("same physical source and restore host")
    for stem in ("businessFingerprint","walletLedger","mediaIndex"):
        if pg[stem+"BeforeSha256"]!=pg[stem+"AfterSha256"]:
            raise ValueError("PITR business snapshot mismatch")
    _stamp(pg["targetUtc"],now=now)
    lsn=pg["recoveredReplayLsn"]
    if not isinstance(lsn,str) or not re.fullmatch(r"[0-9A-F]{1,8}/[0-9A-F]{1,8}",lsn):
        raise ValueError("real WAL replay LSN missing")
    high,low=(int(part,16) for part in lsn.split("/"))
    if not (high or low):
        raise ValueError("zero WAL replay LSN cannot prove physical PITR")
    for f in ("pg17PhysicalBackupVerified","pg17WalReplayAtTarget","rollbackDrilled"):
        _yes(pg[f])
    for f in ("rpoBudgetSeconds","rpoMeasuredSeconds","rtoBudgetSeconds","rtoMeasuredSeconds"):
        _count(pg[f],positive="Budget" in f)
    if pg["rpoMeasuredSeconds"]>pg["rpoBudgetSeconds"] or pg["rtoMeasuredSeconds"]>pg["rtoBudgetSeconds"]:
        raise ValueError("actual PITR exceeds RPO/RTO budget")
    for field in (k for k in ST if k.endswith("Sha256")):
        _hash(st[field])
    if st["tenantOneScopeSha256"]==st["tenantTwoScopeSha256"]:
        raise ValueError("tenant ACL scopes not distinct")
    if st["sourceObjectBytesSha256"]!=st["restoredObjectBytesSha256"]:
        raise ValueError("restored media bytes differ")
    for f in (ST-{k for k in ST if k.endswith("Sha256")}):
        _yes(st[f])
    for field in (k for k in REDIS if k.endswith("Sha256")):
        _hash(rd[field])
    for f in ("fencedLeaderEpochBefore","fencedLeaderEpochAfter"):
        _count(rd[f],positive=True)
    if rd["fencedLeaderEpochAfter"]<=rd["fencedLeaderEpochBefore"]:
        raise ValueError("Redis failover did not advance fencing generation")
    for f in (REDIS-{k for k in REDIS if k.endswith("Sha256")}-
               {"fencedLeaderEpochBefore","fencedLeaderEpochAfter"}):
        _yes(rd[f])
    # A real failover need not retain the same lock owner: recovery MUST
    # reject old writers and prove no duplicate work, not require key equality.
    return {"issue":132,"phase":22,"scope":"pg17-s3-cdn-redis",
            "claimShapeAndCrossRecordInvariants":True,
            "privateDossierSha256":digest(dossier),
            "independentOriginalBytesVerifiedHere":False,
            "physicalHardwareOrProviderAuthenticatedHere":False,
            "realDCasePassGranted":0,
            "productionReleaseAuthorized":False,"decision":"NO-GO"}


def _private(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<1024*1024:
        raise ValueError("private field dossier missing/unsafe")
    if os.name=="posix" and stat.S_IMODE(p.stat().st_mode)&0o077:
        raise ValueError("private field dossier must be owner only")
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dossier",type=Path,required=True)
    ap.add_argument("--web-sha",required=True)
    ap.add_argument("--skill-sha",required=True)
    ap.add_argument("--report",type=Path,required=True)
    a=ap.parse_args(argv)
    try:
        if a.report.is_symlink() or a.report.exists() or not a.report.parent.is_dir():
            raise ValueError("new restricted audit output required")
        result=evaluate(_private(a.dossier),web_sha=a.web_sha,skill_sha=a.skill_sha)
        fd=os.open(a.report,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as fp:
            json.dump(result,fp,ensure_ascii=False,indent=2)
            fp.write("\n")
        print("PHASE22 FIELD "+json.dumps({"scope":result["scope"],"decision":"NO-GO","realDPass":0}))
        return 0
    except Exception:
        print("Phase22 D field receipt BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
