"""#132 Phase22: bind RAW website published DB rows to signed Web/Skill approval.

Phase21 verifies actual two-role Ed25519 signatures + strict Web/Skill
catalog diff in an isolated operator environment. Here we ALSO bind the
source row snapshot to the Website exporter output, and verify a local clean
Skill checkout is pinned to a full SHA, never a mutable branch name.
Neither script independently proves website rights or actually publishes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if __package__ in (None,""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from ops.studio_official_approval_132 import sha
from ops.studio_phase21_official_web_export_132 import transform
from ops.studio_phase21_official_gate_132 import evaluate_chain,_read

SHA=re.compile(r"^[0-9a-f]{40}$")


def check_skill_checkout(directory,expected_sha,runner=subprocess.run):
    if not isinstance(expected_sha,str) or not SHA.fullmatch(expected_sha):
        raise ValueError("full Skill SHA required")
    root=Path(directory)
    if not root.is_dir() or root.is_symlink() or not (root/".git").exists():
        raise ValueError("local pinned Skill checkout missing")
    # No shell, no network and no credential logging. Use fixed args and
    # never print stdout/stderr to public Actions.
    def git(*a):
        out=runner(["git","-C",str(root),*a],capture_output=True,
                   text=True,timeout=8,check=False)
        if out.returncode!=0:
            raise ValueError("git Skill checkout verification failed")
        return out.stdout.strip()
    observed=git("rev-parse","--verify","HEAD")
    if observed!=expected_sha:
        raise ValueError("local Skill checkout SHA drift")
    if git("status","--porcelain","--untracked-files=all")!="":
        raise ValueError("modified/untracked Skill checkout cannot supply official source")
    return {"pinnedSkillSha":observed,"checkoutClean":True}


def evaluate(*,raw_web_rows,published_styles,published_layouts,source_receipt,
             skill_checkout_sha,expected_skill_sha,
             catalog,skill_styles,skill_layouts,pending_before,pending_after,
             approvals,rights_reviews,trust_registry,trust_sha,deployed_sha,
             now=None):
    if skill_checkout_sha!=expected_skill_sha or not SHA.fullmatch(expected_skill_sha):
        raise ValueError("untrusted Skill source commit")
    styles,layouts,raw_sha=transform(raw_web_rows)
    if styles!=published_styles or layouts!=published_layouts:
        raise ValueError("raw website PG published records do not map to signed export")
    if (not isinstance(source_receipt,dict) or
        source_receipt.get("sourceRowsSha256")!=raw_sha or
        source_receipt.get("publishedStylesSha256")!=sha(styles) or
        source_receipt.get("publishedLayoutsSha256")!=sha(layouts)):
        raise ValueError("read-only Website DB raw/source SHA mismatch")
    result=evaluate_chain(catalog=catalog,skill_styles=skill_styles,
        skill_layouts=skill_layouts,pending_before=pending_before,
        pending_after=pending_after,published_styles=styles,
        published_layouts=layouts,approvals=approvals,rights_reviews=rights_reviews,
        trust_registry=trust_registry,trust_sha=trust_sha,
        deployed_sha=deployed_sha,source_receipt=source_receipt,now=now)
    # This report can show a **consistent signed claim**, never genuine
    # official publication, license authenticity or production D-level GO.
    return {"phase":22,"issue":132,"scope":"official-website-and-skill",
        "phase21SignedCandidateClaims":result["signedCandidateClaims"],
        "phase21Stage":result["stage"],
        "rawWebsiteRowsMatchReadOnlyExport":True,
        "pinnedSkillSourceShaMatch":True,
        "signedStrictParityDryRunPassed":result["strictParityDryRunPassed"],
        "websiteLiveDatabaseOriginIndependentlyAuthenticated":False,
        "actualCommercialRightsIndependentlyAuthenticated":False,
        "skillMainMutated":False,"websiteResourcesMutated":False,
        "websitePromotionAuthorized":False,
        "productionReleaseAuthorized":False,"decision":"NO-GO"}


def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--raw-web-rows",type=Path,required=True)
    a.add_argument("--skill-checkout",type=Path,required=True)
    a.add_argument("--skill-sha",required=True)
    a.add_argument("--catalog",type=Path,required=True)
    a.add_argument("--skill-styles",type=Path,required=True)
    a.add_argument("--skill-layouts",type=Path,required=True)
    a.add_argument("--pending-before",type=Path,required=True)
    a.add_argument("--pending-after",type=Path,required=True)
    a.add_argument("--published-styles",type=Path,required=True)
    a.add_argument("--published-layouts",type=Path,required=True)
    a.add_argument("--approvals",type=Path,required=True)
    a.add_argument("--rights",type=Path,required=True)
    a.add_argument("--trust-registry",type=Path,required=True)
    a.add_argument("--source-receipt",type=Path,required=True)
    a.add_argument("--deployed-sha",required=True)
    a.add_argument("--report",type=Path,required=True)
    args=a.parse_args(argv)
    try:
        if args.report.exists() or args.report.is_symlink() or not args.report.parent.is_dir():
            raise ValueError("new audit file required")
        observed=check_skill_checkout(args.skill_checkout,args.skill_sha)
        inputs={
            "raw_web_rows":_read(args.raw_web_rows,private=True),
            "published_styles":_read(args.published_styles,private=True),
            "published_layouts":_read(args.published_layouts,private=True),
            "source_receipt":_read(args.source_receipt,private=True),
            "skill_checkout_sha":observed["pinnedSkillSha"],
            "expected_skill_sha":args.skill_sha,
            "catalog":_read(args.catalog),
            "skill_styles":_read(args.skill_styles),
            "skill_layouts":_read(args.skill_layouts),
            "pending_before":_read(args.pending_before),
            "pending_after":_read(args.pending_after),
            "approvals":_read(args.approvals,private=True),
            "rights_reviews":_read(args.rights,private=True),
            "trust_registry":_read(args.trust_registry,private=True),
            "trust_sha":os.environ.get("HANDRAW_OFFICIAL_TRUST_SHA256",""),
            "deployed_sha":args.deployed_sha,
        }
        result=evaluate(**inputs)
        fd=os.open(args.report,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as fp:
            json.dump(result,fp,ensure_ascii=False,indent=2)
            fp.write("\n")
        print("PHASE22 OFFICIAL "+json.dumps({
            "signedClaims":result["phase21SignedCandidateClaims"],
            "decision":"NO-GO","publishAttempted":False}))
        return 0
    except Exception:
        print("Phase22 Website Skill official provenance BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
