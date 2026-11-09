"""Phase24 #132: join 17 D-level CLAIMS, 3 detailed receipts, PG/S3/Redis
field packet and five externally SHA-pinned reports (OFFLINE, NO-GO).

This verifies cross-document consistency only. It cannot authenticate real
devices, operators, website rights, provider invoices or authorize release.
Use preproduction private 0600 files; no network access or billing requests.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from ops.studio_d_environment_assertions_132 import (
    GATES, evaluate as verify_claims,
)
from ops.studio_d_receipt_contract_132 import (
    GATES as DETAIL_GATES, evaluate as verify_details,
)
from ops.studio_phase22_field_receipts_132 import evaluate as verify_fields
from ops.studio_phase22_witness_chain_132 import (
    CASE_IDS, SOURCES, _private, evaluate as verify_witness,
)

REQUIRED_KINDS=frozenset(SOURCES)


def evaluate(claims,receipts,field_dossier,registry,proofs,*,
             trust_sha,web_sha,skill_sha,now=None):
    """Join *claims*, not real hardware or supplier origin: never GO."""
    now=now or datetime.now(timezone.utc)
    matrix=verify_claims(claims,web_sha=web_sha,skill_sha=skill_sha,now=now)
    details=verify_details(receipts,claims,web_sha=web_sha,
                           skill_sha=skill_sha,now=now)
    field=verify_fields(field_dossier,web_sha=web_sha,
                        skill_sha=skill_sha,now=now)
    witness=verify_witness(registry,proofs,trust_sha=trust_sha,
                           web_sha=web_sha,skill_sha=skill_sha,now=now)
    if (not isinstance(claims,dict)
        or claims.get("environment")!="preproduction"
        or not matrix["allCasesClaimPass"]
        or matrix["schemaValidClaimCount"]!=len(GATES)
        or details["linkedDetailedCases"]!=len(DETAIL_GATES)
        or set(witness["witnessStates"])!=REQUIRED_KINDS
        or witness["pinnedWitnessCount"]!=len(REQUIRED_KINDS)):
        raise ValueError("17-case/three-detail/five-witness proof chain incomplete")
    if any(state!="STRUCTURALLY_CONSISTENT_CLAIM"
           for state in witness["witnessStates"].values()):
        raise ValueError("one or more witness statements incomplete")

    by_case={item["caseId"]:item for item in claims["cases"]}
    by_kind={item["kind"]:item for item in registry["records"]}
    by_detail={item["kind"]:item["details"] for item in receipts["receipts"]}
    if set(by_kind)!=REQUIRED_KINDS or set(by_detail)!=set(DETAIL_GATES):
        raise ValueError("missing independent witness or detailed receipt")

    # A pinned report must identify exactly the same case's ID, people and
    # observed UTC as the corresponding 17-case matrix row. No interchange.
    for kind,case_id in CASE_IDS.items():
        entry=by_kind[kind]
        claim=by_case[case_id]
        for left,right in (
            ("evidenceId","evidenceId"),
            ("operatorId","operator"),
            ("independentReviewerId","reviewer"),
            ("observedAtUtc","observedAtUtc"),
        ):
            if entry[left]!=claim[right]:
                raise ValueError("independent witness and D case identity/UTC drift")
        if claim["status"]!="PASS":
            raise ValueError("witness cannot bind blocked D claim")

    # PG restore summary (manifest) and detailed physical evidence refer to
    # different original files, but their wallet/RPO/RTO observations must
    # agree exactly, not merely remain below budgets independently.
    pg_detail=by_detail["postgres"]
    pg_field=field_dossier["postgres"]
    for name in ("walletLedgerBeforeSha256","walletLedgerAfterSha256",
                 "rpoMeasuredSeconds","rpoBudgetSeconds",
                 "rtoMeasuredSeconds","rtoBudgetSeconds"):
        if pg_detail[name]!=pg_field[name]:
            raise ValueError("PG17 wallet/RPO/RTO evidence drift")

    s3_detail=by_detail["storage"]
    s3_field=field_dossier["storage"]
    for name in ("bucketPolicySha256","cdnPolicySha256"):
        if s3_detail[name]!=s3_field[name]:
            raise ValueError("storage/CDN policy evidence drift")
    for claim_flag,field_flag in (
        ("anonymousDenied","anonymousDenied"),
        ("crossTenantReadDeniedBothDirections","crossTenantReadDeniedBothDirections"),
        ("crossTenantWriteDeniedBothDirections","crossTenantWriteDeniedBothDirections"),
        ("expiredSignedUrlDenied","expiredUrlDenied"),
        ("revokedSignedUrlDenied","revokedUrlDenied"),
        ("cdnOldUrlInvalidated","cdnTombstoneDenied"),
        ("publicGrantOnlyForPublishedAssets","publishedPublicGrantOnly"),
    ):
        if s3_detail[claim_flag] is not True or s3_field[field_flag] is not True:
            raise ValueError("storage claim/field scenario drift")
    # Distinct reports and D claim digests have intentionally different
    # meanings: witness digest = report bytes; D digest = detailed receipt.
    # Never equate them or silently accept a reused evidenceId instead.
    return {
        "issue":132,"phase":24,
        "requiredDCaseCount":len(GATES),
        "structurallyJoinedDClaimCount":len(GATES),
        "detailedReceiptsBound":len(DETAIL_GATES),
        "witnessReportsBound":len(REQUIRED_KINDS),
        "sourceAuthenticityEstablished":False,
        "humanDCaseVerificationPerformed":False,
        "verifiedRealDPassCount":0,
        "officialApprovalGranted":False,
        "productionReleaseAuthorized":False,
        "issueClosureAuthorized":False,
        "decision":"NO-GO",
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claims",type=Path,required=True)
    ap.add_argument("--receipts",type=Path,required=True)
    ap.add_argument("--field-dossier",type=Path,required=True)
    ap.add_argument("--registry",type=Path,required=True)
    ap.add_argument("--proof-dir",type=Path,required=True)
    ap.add_argument("--web-sha",required=True)
    ap.add_argument("--skill-sha",required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        inputs=(args.claims,args.receipts,args.field_dossier,args.registry)
        if (args.report.exists() or args.report.is_symlink()
            or not args.report.parent.is_dir() or args.proof_dir.is_symlink()
            or not args.proof_dir.is_dir()
            or len(set(p.resolve(strict=True) for p in inputs))!=len(inputs)):
            raise ValueError("unsafe/duplicated private evidence paths")
        claims=_private(args.claims)[0]
        receipts=_private(args.receipts)[0]
        field_dossier=_private(args.field_dossier)[0]
        registry=_private(args.registry)[0]
        proofs={}
        for kind in SOURCES:
            proof=args.proof_dir/(kind+".json")
            if not proof.is_file() or proof.is_symlink():
                raise ValueError("missing independent proof")
            proofs[kind]=_private(proof)
        result=evaluate(claims,receipts,field_dossier,registry,proofs,
                        trust_sha=os.environ.get("HANDRAW_PHASE22_TRUST_SHA256",""),
                        web_sha=args.web_sha,skill_sha=args.skill_sha)
        fd=os.open(args.report,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(result,out,ensure_ascii=False,indent=2,sort_keys=True)
            out.write("\n")
        print("PHASE24 CROSS-SOURCE "+json.dumps({
            "joinedClaimCount":len(GATES),"sourceAuthenticity":False,"decision":"NO-GO"}))
        return 0
    except Exception:
        print("Phase24 independent D receipt join BLOCKED: incomplete or mismatched provenance",
              file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
