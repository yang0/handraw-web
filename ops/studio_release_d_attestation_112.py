"""#11/#84/#112 final D-level evidence intake: OFFLINE and fail-closed.

This validates *structure and coverage*, not authenticity or the reality of
any self-reported result. It cannot close an Issue or change production to GO.
Private manifests stay outside the repository; outputs have only public,
predefined gate IDs and aggregate status, never people, secrets or URLs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys

SHA = re.compile(r"^[a-f0-9]{40}$")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
MAX_BYTES = 256_000
MAX_AGE = timedelta(days=30)
STATUS = {"PASS", "FAIL", "BLOCKED", "PENDING"}
ENV = {"preproduction", "staging", "production"}
FIELDS = {"gate", "status", "evidenceId", "operator", "reviewer", "observedAtUtc"}
GROUPS = {
    11: (
        "editorial_ff018", "editorial_fg025",
        "web_db_and_skill_main_strict_parity",
    ),
    84: (
        "one_run_one_public_work", "five_images_out_of_order",
        "three_success_two_failed", "all_failed_zero_work",
        "skill_explicit_upload_resume_and_gif", "cover_moderation_tombstone",
        "cross_user_private_media",
    ),
    112: (
        "real_object_bucket_and_expired_url", "redis_multi_instance_failover",
        "real_provider_charge_refund_ledger", "pg17_offline_backup_restore_rollback",
        "low_end_physical_browser", "release_owner_rollback_signoff",
    ),
}
GATE_TO_ISSUE = {g: issue for issue, names in GROUPS.items() for g in names}


def _time(value):
    if not isinstance(value, str) or len(value)>35:
        raise ValueError("expected bounded UTC observation timestamp")
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise ValueError("invalid observation date") from None
    if parsed.tzinfo is None or parsed.utcoffset()!=timedelta(0):
        raise ValueError("non-UTC observation timestamp")
    return parsed.astimezone(timezone.utc)


def evaluate(manifest, *, expected_sha, now=None):
    """No witness authenticity claim; evidence IDs must remain private."""
    if not isinstance(expected_sha,str) or not SHA.fullmatch(expected_sha):
        raise ValueError("expected deployed 40-char SHA required")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have UTC timezone")
    observed={}
    if manifest is not None:
        if (not isinstance(manifest,dict)
            or set(manifest)!={"schema_version","environment","release_sha","checks"}
            or type(manifest["schema_version"]) is not int
            or manifest["schema_version"]!=1
            or manifest["environment"] not in ENV
            or manifest["release_sha"]!=expected_sha):
            raise ValueError("unsupported, wrong environment or stale SHA manifest")
        checks=manifest["checks"]
        if not isinstance(checks,list) or len(checks)>len(GATE_TO_ISSUE):
            raise ValueError("oversized or invalid release evidence rows")
        for row in checks:
            if not isinstance(row,dict) or set(row)!=FIELDS:
                raise ValueError("unexpected fields or missing D-level evidence details")
            name=row["gate"]
            if not isinstance(name,str) or name not in GATE_TO_ISSUE or name in observed:
                raise ValueError("unknown/duplicate D-level gate")
            if row["status"] not in STATUS:
                raise ValueError("invalid D-level status")
            for field in ("evidenceId","operator","reviewer"):
                val=row[field]
                if not isinstance(val,str) or not TOKEN.fullmatch(val):
                    raise ValueError("untrusted D-level evidence token")
            if row["operator"]==row["reviewer"]:
                raise ValueError("D-level reviewer must be independent")
            when=_time(row["observedAtUtc"])
            if when>now+timedelta(minutes=5):
                raise ValueError("future-dated evidence")
            valid_age=now-when<=MAX_AGE
            observed[name]={
                "status":row["status"] if valid_age else "STALE",
                "fresh":valid_age,
            }
    pending={}
    by_issue={}
    for issue,names in GROUPS.items():
        summary=[]
        for name in names:
            state=observed.get(name,{"status":"MISSING"})["status"]
            summary.append({"gate":name,"status":state})
        by_issue[str(issue)]={
            "requiredCount":len(summary),
            "pendingOrFailed":[s for s in summary if s["status"]!="PASS"],
            "claimComplete":all(s["status"]=="PASS" for s in summary),
            "sourceAuthenticityVerified":False,
            "realWorldAcceptanceConfirmed":False,
        }
        pending[str(issue)]=[s["gate"] for s in summary if s["status"]!="PASS"]
    counts=dict(sorted(Counter(
        observed.get(g,{"status":"MISSING"})["status"]
        for g in GATE_TO_ISSUE
    ).items()))
    all_claimed=all(e["claimComplete"] for e in by_issue.values())
    return {
        "schemaVersion":1,
        "releaseSha":expected_sha,
        "inputManifestProvided":manifest is not None,
        "claimsComplete":all_claimed,
        "coverageByIssue":by_issue,
        "statusCounts":counts,
        "missingOrUnpassedGates":pending,
        "unverifiedWitnessClaims":True,
        "requiresIndependentAuditOfPrivateEvidence":True,
        "readyForManualAuthenticityReview":all_claimed,
        "issueClosureAuthorized":False,
        "automaticReleaseApproved":False,
        "decision":"NO-GO",
        "privateEvidenceValuesEmitted":False,
    }


def _load_private_manifest(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size>MAX_BYTES:
        raise ValueError("invalid or too-large private D-level manifest")
    if os.name=="posix" and stat.S_IMODE(path.stat().st_mode)&0o077:
        raise ValueError("private D-level manifest must be owner-only 0600")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,help="private 0600 file, never Git or CI artifact")
    p.add_argument("--release-sha",default=os.getenv("GITHUB_SHA",""))
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        if args.report.is_symlink() or args.report.exists():
            raise ValueError("will not overwrite release evidence report")
        manifest=_load_private_manifest(args.manifest) if args.manifest else None
        report=evaluate(manifest,expected_sha=args.release_sha)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,stat.S_IRUSR|stat.S_IWUSR)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(report,out,ensure_ascii=False,indent=2)
            out.write("\n")
        print("D-GATE CLOSEOUT "+json.dumps({
            "checked":sum(x["requiredCount"] for x in report["coverageByIssue"].values()),
            "counts":report["statusCounts"],"decision":"NO-GO",
            "privateEvidenceValuesEmitted":False,
        },ensure_ascii=False),flush=True)
        return 0
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):
        print("D-level closeout refused: invalid or non-private evidence",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
