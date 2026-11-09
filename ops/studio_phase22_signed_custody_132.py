"""Phase22 #132 independent two-role Ed25519 *chain-of-custody* verifier.

The externally SHA-pinned public-key registry MUST come from a different,
non-repository admin channel. Submitted witness bundles cannot invent trust.
This only authenticates cryptographic *claims* about reviewed evidence, not
real-world source or permission. NEVER changes Web/Skill or marks D PASS.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__ in (None,""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ops.studio_official_approval_132 import sha,canon,decode64
from ops.studio_phase21_official_gate_132 import evaluate_chain
from ops.studio_phase22_field_matrix_132 import evaluate_record

SHA40=re.compile(r"^[a-f0-9]{40}$")
SHA64=re.compile(r"^[a-f0-9]{64}$")
TOKEN=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
ROLES={"field_operator","independent_reviewer"}
SCOPES={"official_web_export","skill_checkout","postgres","storage","redis","provider"}
PAYLOAD={"schemaVersion","scope","webSha","skillSha","sourceDigestSha256",
         "recordedAtUtc","witnessSessionId","nonce","result"}
REGISTRY={"schemaVersion","issuer","keys"}
MAX_BYTES=2_000_000


def _stamp(s,now):
    if not isinstance(s,str) or len(s)>35:
        raise ValueError("invalid bounded UTC chain observation")
    try:
        t=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError:
        raise ValueError("invalid chain observation UTC") from None
    if t.tzinfo is None or t.utcoffset()!=timedelta(0):
        raise ValueError("non-UTC witness")
    if t>now+timedelta(minutes=5) or now-t>timedelta(days=30):
        raise ValueError("stale/future chain witness")
    return t


def _registry(registry,pin):
    if not isinstance(pin,str) or not SHA64.fullmatch(pin):
        raise ValueError("external SHA-pinned role registry required")
    if (not isinstance(registry,dict) or set(registry)!=REGISTRY or
        type(registry["schemaVersion"]) is not int or registry["schemaVersion"]!=1 or
        registry["issuer"]!="handraw-phase22-independent-audit" or
        sha(registry)!=pin):
        raise ValueError("untrusted external witness key registry")
    rows=registry["keys"]
    if not isinstance(rows,list) or not 2<=len(rows)<=16:
        raise ValueError("invalid external signer count")
    seen_public=set()
    out={}
    for entry in rows:
        if not isinstance(entry,dict) or set(entry)!={"role","keyId","publicKeyBase64"}:
            raise ValueError("unknown external key fields")
        kid,role=entry["keyId"],entry["role"]
        if (not isinstance(kid,str) or not TOKEN.fullmatch(kid)
            or role not in ROLES or kid in out):
            raise ValueError("untrusted/repeated signing identity")
        raw=decode64(entry["publicKeyBase64"],32)
        if raw in seen_public:
            raise ValueError("duplicate public key across independent signer identities")
        seen_public.add(raw)
        out[kid]=(role,Ed25519PublicKey.from_public_bytes(raw))
    if {x[0] for x in out.values()}!=ROLES:
        raise ValueError("missing independent signer role")
    return out


def evaluate(packet,registry,*,trusted_registry_sha,expected_source_digests,
             web_sha,skill_sha,now=None):
    """Validates signed source hashes against externally supplied known digests."""
    now=now or datetime.now(timezone.utc)
    if (not isinstance(web_sha,str) or not SHA40.fullmatch(web_sha)
        or not isinstance(skill_sha,str) or not SHA40.fullmatch(skill_sha)):
        raise ValueError("exact deployed Web + Skill git SHAs required")
    if (not isinstance(expected_source_digests,dict)
        or set(expected_source_digests)!=SCOPES
        or any(not isinstance(v,str) or not SHA64.fullmatch(v)
               for v in expected_source_digests.values())):
        raise ValueError("six independently collected source digests required")
    keys=_registry(registry,trusted_registry_sha)
    if (not isinstance(packet,dict) or set(packet)!={"schemaVersion","witnesses"}
        or type(packet["schemaVersion"]) is not int or packet["schemaVersion"]!=1
        or not isinstance(packet["witnesses"],list)
        or len(packet["witnesses"])>len(SCOPES)):
        raise ValueError("invalid independent witness envelope")
    verified=set()
    used_nonces=set()
    used_signatures=set()
    for row in packet["witnesses"]:
        if not isinstance(row,dict) or set(row)!={"payload","signatures"}:
            raise ValueError("unsigned or unexpected witness fields")
        p=row["payload"]
        if (not isinstance(p,dict) or set(p)!=PAYLOAD
            or type(p["schemaVersion"]) is not int or p["schemaVersion"]!=1
            or p["scope"] not in SCOPES or p["scope"] in verified
            or p["webSha"]!=web_sha or p["skillSha"]!=skill_sha
            or p["result"]!="reviewed_source_claim_only"
            or p["sourceDigestSha256"]!=expected_source_digests[p["scope"]]):
            raise ValueError("replayed/tampered/unpinned witness claim")
        verified.add(p["scope"])
        for f in ("witnessSessionId","nonce"):
            v=p[f]
            if not isinstance(v,str) or not TOKEN.fullmatch(v):
                raise ValueError("missing immutable witness session/nonce")
        if p["nonce"] in used_nonces:
            raise ValueError("witness nonce replay across distinct sources")
        used_nonces.add(p["nonce"])
        _stamp(p["recordedAtUtc"],now)
        signatures=row["signatures"]
        if not isinstance(signatures,list) or len(signatures)!=2:
            raise ValueError("two independent witness signatures required")
        signer_roles=set()
        signer_ids=set()
        for sig in signatures:
            if not isinstance(sig,dict) or set(sig)!={"role","keyId","signatureBase64"}:
                raise ValueError("unknown signature fields")
            role,kid=sig["role"],sig["keyId"]
            if (role not in ROLES or role in signer_roles or kid in signer_ids
                or kid not in keys or keys[kid][0]!=role):
                raise ValueError("untrusted/duplicate witness signature role")
            raw=decode64(sig["signatureBase64"],64)
            if raw in used_signatures:
                raise ValueError("replayed witness signature bytes")
            used_signatures.add(raw)
            try:keys[kid][1].verify(raw,canon(p))
            except InvalidSignature:
                raise ValueError("forged independent field evidence signature") from None
            signer_roles.add(role)
            signer_ids.add(kid)
        if signer_roles!=ROLES:
            raise ValueError("independent witness signer missing")
    return {
        "phase":22,"issue":132,
        "witnessedScopes":sorted(verified),
        "missingScopes":sorted(SCOPES-verified),
        "signedSourceClaimsValidated":len(verified),
        "signedClaimPacketComplete":verified==SCOPES,
        "sourceAuthenticityIndependentlyProvenByThisTool":False,
        "externalHumanReviewStillRequired":True,
        "physicalDGradeCertification":False,
        "officialPublicationAuthorized":False,
        "automaticReleaseAuthorized":False,
        "decision":"NO-GO",
    }


def evaluate_linked(*,official_inputs,field_records,packet,registry,
                    trusted_registry_sha,web_sha,skill_sha,
                    provider=None,handraw=None,now=None):
    """Strict chain: Phase21 genuine signatures -> exact field matrices -> witnesses.

    The actual source authenticity and hosting still require on-site review.
    """
    if not isinstance(official_inputs,dict):
        raise ValueError("Phase21 authoritative editorial input bundle missing")
    official=evaluate_chain(**official_inputs)
    if (official.get("signedCandidateClaims")!=3
        or official.get("strictParityDryRunPassed") is not True
        or official.get("decision")!="NO-GO"
        or official_inputs.get("deployed_sha")!=web_sha):
        raise ValueError("all three official website/Skill approvals not staged")
    if not isinstance(field_records,dict) or set(field_records)!={
            "postgres","storage","redis","provider"}:
        raise ValueError("four private field protocol records required")
    fields={}
    for kind,record in field_records.items():
        fields[kind]=evaluate_record(record,web_sha=web_sha,skill_sha=skill_sha,
           provider=provider if kind=="provider" else None,
           handraw=handraw if kind=="provider" else None,now=now)
    if not fields["provider"]["paidProviderSourceReconciliationChecked"]:
        raise ValueError("actual normalized provider + wallet exports required")
    digests={
        "official_web_export":sha(official_inputs["source_receipt"]),
        "skill_checkout":sha({"styles":official_inputs["skill_styles"],
                              "layouts":official_inputs["skill_layouts"],
                              "expectedGitSha":skill_sha}),
        **{kind:fields[kind]["recordSha256"] for kind in fields},
    }
    signed=evaluate(packet,registry,trusted_registry_sha=trusted_registry_sha,
             expected_source_digests=digests,
             web_sha=web_sha,skill_sha=skill_sha,now=now)
    signed["websiteEditorialSignatureClaimsValidated"]=True
    signed["strictWebSkillParityDryRunPassed"]=True
    signed["providerToWalletSourceReconciliationChecked"]=True
    signed["sourceDigestsBoundToSigningRoles"]=True
    signed["independentRealWorldSiteAuditVerified"]=False
    signed["decision"]="NO-GO"
    return signed


def _private(p):
    p=Path(p)
    if (p.is_symlink() or not p.is_file() or p.stat().st_size>MAX_BYTES
        or (os.name=="posix" and stat.S_IMODE(p.stat().st_mode)&0o077)):
        raise ValueError("private witness path rejected")
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--packet",type=Path)
    ap.add_argument("--registry",type=Path)
    ap.add_argument("--expected-source-digests",type=Path)
    ap.add_argument("--web-sha",required=True)
    ap.add_argument("--skill-sha",required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        if args.report.exists() or args.report.is_symlink():
            raise ValueError("cannot overwrite private result")
        given=(args.packet,args.registry,args.expected_source_digests)
        if any(given) and not all(given):
            raise ValueError("partial signatures/evidence refused")
        if not any(given):
            result={"phase":22,"issue":132,"signedSourceClaimsValidated":0,
                    "missingScopes":sorted(SCOPES),
                    "sourceAuthenticityIndependentlyProvenByThisTool":False,
                    "automaticReleaseAuthorized":False,
                    "decision":"NO-GO"}
        else:
            result=evaluate(_private(args.packet),_private(args.registry),
                trusted_registry_sha=os.getenv("HANDRAW_PHASE22_TRUST_SHA256",""),
                expected_source_digests=_private(args.expected_source_digests),
                web_sha=args.web_sha,skill_sha=args.skill_sha)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(result,out,indent=2,sort_keys=True,ensure_ascii=False)
            out.write("\n")
        print("PHASE22 SIGNED CUSTODY "+json.dumps({
           "signed":result["signedSourceClaimsValidated"],
           "decision":"NO-GO","credentialsPrinted":False}))
        return 0
    except Exception:
        print("Phase22 independent witness signatures BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
