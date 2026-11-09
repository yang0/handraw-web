"""Phase21 #132: SIGNATURE FIRST -> Web DB provenance -> STRICT Skill parity.

No automatic approval, no website DB writes and no Skill publication. All
inputs come from an independent private review vault. The exporter receipt
is a *claim* until a separate operator audits the originating PG connection.
Never mistake a C-grade dry run for actual D-grade authorization.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.studio_official_approval_132 import (
    CODES, evaluate as verify_signatures, sha, _private_json, _public_pending_json,
)
from ops.studio_official_transition_132 import stage_transition

COMMIT=re.compile(r"^[0-9a-f]{40}$")
HASH=re.compile(r"^[0-9a-f]{64}$")
TOKEN=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")


def evaluate_chain(*, catalog, skill_styles, skill_layouts, pending_before,
                   pending_after, published_styles, published_layouts,
                   approvals, rights_reviews, trust_registry,
                   trust_sha, deployed_sha, source_receipt, now=None):
    """Pure, nonpublishing C-level verifier; does not establish DB provenance."""
    if not isinstance(deployed_sha,str) or not COMMIT.fullmatch(deployed_sha):
        raise ValueError("deployed SHA missing")
    results={
        "issue":132,"phase":21,"candidateCodes":list(CODES),
        "signedCandidateClaims":0,"strictParityDryRunPassed":False,
        "websiteDbOriginIndependentlyProven":False,
        "rightsOwnershipIndependentlyProven":False,
        "officialWebsitePublicationMade":False,
        "skillPublicationMade":False,
        "automaticPromotionAuthorized":False,
        "independentHumanSignoffOutstanding":True,
        "decision":"NO-GO",
    }
    # Unapproved/missing evidence returns an explicit block; NEVER synthesize
    # "approved" rows from Skill or from local CI fixtures.
    if approvals is None:
        results["stage"]="MISSING_WEBSITE_APPROVAL"
        return results
    verified=verify_signatures(approvals,trust_registry,pending_before,
                               published_styles,trusted_sha=trust_sha,
                               expected_deployed_sha=deployed_sha,
                               rights_reviews=rights_reviews,now=now)
    results["signedCandidateClaims"]=verified["signedClaimCount"]
    if verified["signedClaimCount"]!=len(CODES):
        results["stage"]="INCOMPLETE_TWO_ROLE_SIGNATURES"
        return results
    if (not isinstance(source_receipt,dict)
        or set(source_receipt)!={"schemaVersion","sourceSystem","sourceRole",
            "webDeployedSha","publishedStylesSha256","publishedLayoutsSha256",
            "sourceRowsSha256","operatorId","independentReviewerId","exportSessionId"}
        or source_receipt["schemaVersion"]!=1
        or source_receipt["sourceSystem"]!="website-postgresql-read-only"
        or source_receipt["sourceRole"]!="readonly-export"
        or source_receipt["webDeployedSha"]!=deployed_sha
        or source_receipt["publishedStylesSha256"]!=sha(published_styles)
        or source_receipt["publishedLayoutsSha256"]!=sha(published_layouts)
        or not isinstance(source_receipt["sourceRowsSha256"],str)
        or not HASH.fullmatch(source_receipt["sourceRowsSha256"])):
        raise ValueError("untrusted/mismatched website published DB origin claim")
    for f in ("operatorId","independentReviewerId","exportSessionId"):
        v=source_receipt[f]
        if not isinstance(v,str) or not TOKEN.fullmatch(v):
            raise ValueError("invalid source witness reference")
    if source_receipt["operatorId"]==source_receipt["independentReviewerId"]:
        raise ValueError("self-attested website DB export")
    staged=stage_transition(
        catalog,skill_styles,skill_layouts,pending_before,pending_after,
        published_styles,published_layouts,
        [e["payload"] for e in approvals["approvals"]],
        deployed_sha=deployed_sha,
    )
    if not staged["strictCatalogParityDryRunPassed"]:
        raise ValueError("Web/Skill strict parity did not pass")
    results["strictParityDryRunPassed"]=True
    results["stage"]="SIGNED_AND_STRICTLY_STAGED_FOR_INDEPENDENT_REVIEW"
    results["sourceReceiptPresentButIndependentlyUnverified"]=True
    return results


def _read(path,*,private=False):
    p=Path(path)
    if private:
        return _private_json(p)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>2_000_000:
        raise ValueError("missing/oversized official snapshot")
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deployed-sha",required=True)
    ap.add_argument("--report",type=Path,required=True)
    ap.add_argument("--catalog",type=Path)
    ap.add_argument("--skill-styles",type=Path)
    ap.add_argument("--skill-layouts",type=Path)
    ap.add_argument("--pending-before",type=Path)
    ap.add_argument("--pending-after",type=Path)
    ap.add_argument("--published-styles",type=Path)
    ap.add_argument("--published-layouts",type=Path)
    ap.add_argument("--approvals",type=Path)
    ap.add_argument("--rights",type=Path)
    ap.add_argument("--trust-registry",type=Path)
    ap.add_argument("--source-receipt",type=Path)
    args=ap.parse_args(argv)
    try:
        if args.report.exists() or args.report.is_symlink():
            raise ValueError("report exists")
        paths=[args.catalog,args.skill_styles,args.skill_layouts,
               args.pending_before,args.pending_after,args.published_styles,
               args.published_layouts,args.approvals,args.rights,
               args.trust_registry,args.source_receipt]
        if any(paths) and not all(paths):
            raise ValueError("partial approval chain forbidden")
        if not any(paths):
            # Intentionally no input = NO-GO. No trust root from submitted data.
            result={"phase":21,"issue":132,"signedCandidateClaims":0,
                    "stage":"MISSING_WEBSITE_APPROVAL",
                    "strictParityDryRunPassed":False,
                    "automaticPromotionAuthorized":False,"decision":"NO-GO"}
        else:
            result=evaluate_chain(
                catalog=_read(args.catalog),
                skill_styles=_read(args.skill_styles),
                skill_layouts=_read(args.skill_layouts),
                pending_before=_read(args.pending_before),
                pending_after=_read(args.pending_after),
                published_styles=_read(args.published_styles,private=True),
                published_layouts=_read(args.published_layouts,private=True),
                approvals=_read(args.approvals,private=True),
                rights_reviews=_read(args.rights,private=True),
                trust_registry=_read(args.trust_registry,private=True),
                source_receipt=_read(args.source_receipt,private=True),
                trust_sha=os.getenv("HANDRAW_OFFICIAL_TRUST_SHA256",""),
                deployed_sha=args.deployed_sha,
            )
        args.report.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as handle:
            json.dump(result,handle,ensure_ascii=False,sort_keys=True,indent=2)
            handle.write("\n")
        print("PHASE21 OFFICIAL CHAIN "+json.dumps({
            "stage":result["stage"],"decision":"NO-GO","privateDataEmitted":False}))
        return 0
    except (ValueError,TypeError,KeyError,OSError,json.JSONDecodeError):
        print("Phase21 official chain BLOCKED: missing/unauthenticated evidence",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
