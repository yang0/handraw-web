"""#132 Phase22 offline final evidence intake (NEVER authorizes production).

Requires all inputs as private owner-only JSON, externally supplied official
and independent trust-pins, real paid-provider + Handraw export, and the full
field protocol packet. All work read-only, no external service connections.
Valid *signatures* establish signed claims, NOT real-world D verification.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

if __package__ in (None,""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops.studio_phase22_field_matrix_132 import _private_json
from ops.studio_phase22_signed_custody_132 import evaluate_linked
from ops.studio_phase22_release_join_132 import evaluate_join

OFFICIAL_KEYS={"catalog","skill_styles","skill_layouts","pending_before",
    "pending_after","published_styles","published_layouts","approvals",
    "rights_reviews","trust_registry","source_receipt","deployed_sha"}
PIN=re.compile(r"^[a-f0-9]{64}$")


def evaluate_all(*,official_inputs,field_records,witnesses,witness_registry,
                 master,critical,provider,handraw,official_pin,field_pin,
                 web_sha,skill_sha,now=None):
    if not isinstance(official_inputs,dict) or set(official_inputs)!=OFFICIAL_KEYS:
        raise ValueError("unexpected/partial official source inputs")
    if any(not isinstance(pin,str) or not PIN.fullmatch(pin)
           for pin in (official_pin,field_pin)):
        raise ValueError("two externally managed hash-pinned trust roots required")
    inputs={**official_inputs,"trust_sha":official_pin}
    if now is not None:
        inputs["now"]=now
    signed=evaluate_linked(official_inputs=inputs,field_records=field_records,
        packet=witnesses,registry=witness_registry,
        trusted_registry_sha=field_pin,web_sha=web_sha,skill_sha=skill_sha,
        provider=provider,handraw=handraw,now=now)
    joined=evaluate_join(master=master,critical=critical,
        field_records=field_records,web_sha=web_sha,skill_sha=skill_sha,
        provider=provider,handraw=handraw,now=now)
    if signed["signedSourceClaimsValidated"]!=6 or joined["linkedCriticalReceipts"]!=3:
        raise ValueError("Phase22 evidence chain incomplete")
    return {"issue":132,"phase":22,
       "officialApprovalDoubleSignatureClaimsChecked":True,
       "websiteSkillStrictCatalogDryRunChecked":True,
       "externallyPinnedTwoRoleEvidenceSignaturesChecked":True,
       "signedSourceClaimCount":signed["signedSourceClaimsValidated"],
       "physicalProtocolDetailReceiptsLinked":joined["linkedCriticalReceipts"],
       "redisDCaseHashBound":joined["redisFailoverFieldDigestBound"],
       "claimedDCaseCount":joined["structuralDClaimCount"],
       "realPaidProviderRawLedgerReconciledOffline":True,
       "actualWebsiteEditorialAuthorizationIndependentlyEstablished":False,
       "realObjectStorageOrPostgresAccessPerformed":False,
       "productionEnvironmentAccessPerformed":False,
       "independentPhysicalDGradeAuditorApproved":False,
       "autoReleaseOrIssueCloseAuthorized":False,"decision":"NO-GO"}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("official-inputs","field-records","witnesses",
                 "witness-registry","master","critical","provider","handraw"):
        ap.add_argument("--"+name,type=Path,required=True)
    ap.add_argument("--web-sha",required=True)
    ap.add_argument("--skill-sha",required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        if args.report.exists() or args.report.is_symlink():
            raise ValueError("private report cannot be overwritten")
        out=evaluate_all(official_inputs=_private_json(args.official_inputs),
            field_records=_private_json(args.field_records),
            witnesses=_private_json(args.witnesses),
            witness_registry=_private_json(args.witness_registry),
            master=_private_json(args.master),
            critical=_private_json(args.critical),
            provider=_private_json(args.provider),
            handraw=_private_json(args.handraw),
            official_pin=os.environ.get("HANDRAW_OFFICIAL_TRUST_SHA256",""),
            field_pin=os.environ.get("HANDRAW_PHASE22_TRUST_SHA256",""),
            web_sha=args.web_sha,skill_sha=args.skill_sha)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out_file:
            json.dump(out,out_file,ensure_ascii=False,indent=2,sort_keys=True)
            out_file.write("\n")
        print("PHASE22 FULL CHAIN "+json.dumps({
             "signedSources":6,"linkedDReceipts":3,
             "decision":"NO-GO","rawEvidenceOrSecretsEmitted":False}))
        return 0
    except Exception:
        print("Phase22 full official/D witness chain BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
