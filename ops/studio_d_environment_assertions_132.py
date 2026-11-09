"""#132 production D-level *evidence-origin claims* contract (OFFLINE).

No environment connections, no credentials, no provider API calls. Even 17
structurally PASS claims are unverified until independent human audit. No GO.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import stat
import sys

from ops.studio_release_d_attestation_112 import GROUPS

SHA=re.compile(r"^[a-f0-9]{40}$")
DIGEST=re.compile(r"^[a-f0-9]{64}$")
TOKEN=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
GATES=tuple(g for group in GROUPS.values() for g in group)
MAX_BYTES=256_000
ALLOWED={"PASS","FAIL","BLOCKED","PENDING"}
ALLOWED_ENV={"preproduction","production"}

# Source *claims* must identify the real independent environment, NOT CI/Moto.
ORIGINS={g:"real-web-skill-cross-account" for g in GROUPS[84]}
ORIGINS.update({
    "editorial_ff018":"website-published-db-and-editorial",
    "editorial_ff019":"website-published-db-and-editorial",
    "editorial_fg025":"website-published-db-and-editorial",
    "web_db_and_skill_main_strict_parity":"live-approved-db-skill-main",
    "real_object_bucket_and_expired_url":"live-private-r2-s3-cdn",
    "redis_multi_instance_failover":"real-multi-instance-redis",
    "real_provider_charge_refund_ledger":"real-provider-billing-refund",
    "pg17_offline_backup_restore_rollback":"independent-physical-pg17-restore",
    "low_end_physical_browser":"physical-low-end-cpu-gpu-touch",
    "release_owner_rollback_signoff":"independent-dual-signoff-rollback",
})
ORIGINS["cover_moderation_tombstone"]="live-private-r2-s3-cdn"
ORIGINS["cross_user_private_media"]="live-private-r2-s3-cdn"

FIELDS={"caseId","status","origin","evidenceDigestSha256","evidenceId",
        "environmentId","deployedSha","skillSha","observedAtUtc",
        "operator","reviewer","isSimulation","physicalOrRealProviderClaim"}


def _utc(value,now):
    if not isinstance(value,str) or len(value)>35:
        raise ValueError("invalid D evidence time")
    try:
        time=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise ValueError("invalid D evidence time") from None
    if time.tzinfo is None or time.utcoffset()!=timedelta(0):
        raise ValueError("UTC required")
    if time>now+timedelta(minutes=5) or now-time>timedelta(days=30):
        raise ValueError("stale/future D evidence")


def evaluate(claims,*,web_sha,skill_sha,now=None):
    if any(not isinstance(x,str) or not SHA.fullmatch(x)
           for x in (web_sha,skill_sha)):
        raise ValueError("full deployed Web and Skill SHAs required")
    if len(ORIGINS)!=len(GATES) or set(ORIGINS)!=set(GATES):
        raise ValueError("internal D gate origin matrix incomplete")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("aware clock required")
    counts={g:"MISSING" for g in GATES}
    if claims is not None:
        if (not isinstance(claims,dict)
            or set(claims)!={"schemaVersion","environment","deployedSha","skillSha","cases"}
            or claims["schemaVersion"]!=1 or claims["environment"] not in ALLOWED_ENV
            or claims["deployedSha"]!=web_sha or claims["skillSha"]!=skill_sha
            or not isinstance(claims["cases"],list) or len(claims["cases"])>len(GATES)):
            raise ValueError("wrong schema/environment/deployment for D claims")
        witness_ids=set()
        for row in claims["cases"]:
            if not isinstance(row,dict) or set(row)!=FIELDS:
                raise ValueError("invalid or secret-bearing D claim fields")
            code=row["caseId"]
            if not isinstance(code,str) or code not in counts or counts[code]!="MISSING":
                raise ValueError("unknown/duplicate D gate")
            if row["status"] not in ALLOWED or row["origin"]!=ORIGINS[code]:
                raise ValueError("invalid D status/real-world origin category")
            if (type(row["isSimulation"]) is not bool or
                type(row["physicalOrRealProviderClaim"]) is not bool or
                row["isSimulation"] or not row["physicalOrRealProviderClaim"]):
                raise ValueError("CI/Moto/simulated D evidence explicitly refused")
            if row["deployedSha"]!=web_sha or row["skillSha"]!=skill_sha:
                raise ValueError("stale deployed artifacts")
            if (not isinstance(row["evidenceDigestSha256"],str) or
                not DIGEST.fullmatch(row["evidenceDigestSha256"])):
                raise ValueError("missing independent evidence checksum")
            for field in ("evidenceId","environmentId","operator","reviewer"):
                if not isinstance(row[field],str) or not TOKEN.fullmatch(row[field]):
                    raise ValueError("invalid/private D witness token")
            if row["operator"]==row["reviewer"]:
                raise ValueError("self-review not acceptable")
            if row["evidenceId"] in witness_ids:
                raise ValueError("one evidence record cannot impersonate two D gates")
            witness_ids.add(row["evidenceId"])
            _utc(row["observedAtUtc"],now)
            counts[code]=row["status"]
    complete=all(status=="PASS" for status in counts.values())
    return {
        "issue":132,"requiredCaseCount":len(GATES),
        "schemaValidClaimCount":len(GATES)-sum(v=="MISSING" for v in counts.values()),
        "claimedPassCount":sum(v=="PASS" for v in counts.values()),
        "statusByCase":counts,
        "allCasesClaimPass":complete,
        "independentEvidenceAuthenticityVerified":False,
        "physicalProviderActuallyConnectedByTool":False,
        "anyProductionSecretsUsed":False,
        "readyForIndependentOnSiteReview":complete,
        "autoReleaseAuthorized":False,
        "issueClosureAuthorized":False,
        "decision":"NO-GO",
    }


def _private(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise ValueError("missing/oversized private D evidence")
    if os.name=="posix" and stat.S_IMODE(path.stat().st_mode)&0o077:
        raise ValueError("private D evidence must be owner-only")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--claims",type=Path)
    p.add_argument("--web-sha",required=True)
    p.add_argument("--skill-sha",required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        if args.report.exists() or args.report.is_symlink():
            raise ValueError("will not overwrite D-level report")
        summary=evaluate(_private(args.claims) if args.claims else None,
                         web_sha=args.web_sha,skill_sha=args.skill_sha)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(summary,out,indent=2,ensure_ascii=False)
            out.write("\n")
        print("D-REAL-SOURCE "+json.dumps({
            "checked":summary["requiredCaseCount"],
            "claimedPassCount":summary["claimedPassCount"],"decision":"NO-GO",
            "secretsOrEvidenceValuesEmitted":False}))
        return 0
    except (ValueError,KeyError,TypeError,json.JSONDecodeError,OSError):
        print("D external environment evidence refused",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
