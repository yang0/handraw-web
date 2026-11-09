"""#132: OFFLINE verification of two independent website editorial signatures.

Ed25519 trust roots are provided by a separately administered, SHA256-pinned
private review environment. Neither the reviewer private keys nor the trusted
root checksum may come from a submitted approval bundle or this repository.
This verifier NEVER publishes assets, marks a code Web-approved, or issues GO.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from datetime import datetime, timezone, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

CODES=("FF-018","FF-019","FG-025")
ROLES=("website_editor","independent_reviewer")
SHA256=re.compile(r"^[a-f0-9]{64}$")
COMMIT=re.compile(r"^[a-f0-9]{40}$")
TOKEN=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
PAYLOAD_FIELDS={"schemaVersion","candidateCode","skillSourceSha256",
 "webDbPublishedRowSha256","deployedSha","websiteActionId",
 "rightsReviewEvidenceId","reviewedAtUtc","result"}
MAX_BYTES=256_000


def canon(obj):
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),allow_nan=False).encode("utf-8")


def sha(obj):
    return hashlib.sha256(canon(obj)).hexdigest()


def decode64(value, length):
    if not isinstance(value,str):
        raise ValueError("invalid encoded signature/key")
    try:
        raw=base64.b64decode(value,validate=True)
    except (ValueError,base64.binascii.Error):
        raise ValueError("invalid encoded signature/key") from None
    if len(raw)!=length:
        raise ValueError("invalid signature/key length")
    return raw


def _utc(value,now):
    if not isinstance(value,str) or len(value)>35:
        raise ValueError("invalid review time")
    try:
        when=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise ValueError("invalid review time") from None
    if when.tzinfo is None or when.utcoffset()!=timedelta(0):
        raise ValueError("review time must be UTC")
    if when>now+timedelta(minutes=5) or now-when>timedelta(days=30):
        raise ValueError("stale/future review")
    return when


def _registry(registry, trusted_sha):
    if not isinstance(trusted_sha,str) or not SHA256.fullmatch(trusted_sha):
        raise ValueError("out-of-band pinned trust checksum required")
    if not isinstance(registry,dict) or set(registry)!={"schemaVersion","issuer","keys"}:
        raise ValueError("invalid external trust registry")
    if registry["schemaVersion"]!=1 or registry["issuer"]!="handraw-website-ops":
        raise ValueError("unrecognized trust issuer")
    if sha(registry)!=trusted_sha:
        raise ValueError("external trust anchor fingerprint mismatch")
    if not isinstance(registry["keys"],list) or not 2<=len(registry["keys"])<=16:
        raise ValueError("invalid trusted key registry")
    keys={}
    for row in registry["keys"]:
        if not isinstance(row,dict) or set(row)!={"keyId","role","publicKeyBase64"}:
            raise ValueError("unexpected trust fields")
        kid=row["keyId"]
        if not isinstance(kid,str) or not TOKEN.fullmatch(kid) or kid in keys:
            raise ValueError("duplicate/invalid key identity")
        if row["role"] not in ROLES:
            raise ValueError("unapproved signing role")
        keys[kid]=(row["role"],Ed25519PublicKey.from_public_bytes(
            decode64(row["publicKeyBase64"],32)))
    return keys


def evaluate(approvals,registry,pending_manifest,db_styles,*,
             trusted_sha,expected_deployed_sha,now=None):
    """Validate claims, not real-world editorial authority or storage origin."""
    if not isinstance(expected_deployed_sha,str) or not COMMIT.fullmatch(expected_deployed_sha):
        raise ValueError("40-character deployed SHA required")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone-aware clock required")
    pending=pending_manifest.get("pendingSkillOnly") if isinstance(pending_manifest,dict) else None
    if not isinstance(pending,list) or {r.get("code") for r in pending if isinstance(r,dict)}!=set(CODES) or len(pending)!=3:
        raise ValueError("unexpected pending manifest: refuse implicit approvals")
    pinned={r["code"]:r for r in pending}
    if any(r.get("state")!="awaiting_website_editorial_review" or
           r.get("kind")!="style" or not isinstance(r.get("sha256"),str) or
           not SHA256.fullmatch(r["sha256"]) for r in pending):
        raise ValueError("pending editorial integrity mismatch")
    # Lack of any candidate-specific approval always remains explicitly MISSING.
    results={code:"MISSING" for code in CODES}
    if approvals is None:
        return _result(results)
    if registry is None or db_styles is None:
        raise ValueError("signed claim needs external trust and published DB export")
    keys=_registry(registry,trusted_sha)
    if (not isinstance(approvals,dict) or set(approvals)!={"schemaVersion","approvals"}
        or approvals["schemaVersion"]!=1 or not isinstance(approvals["approvals"],list)
        or len(approvals["approvals"])>3):
        raise ValueError("invalid signed approval bundle")
    if not isinstance(db_styles,list) or len(db_styles)>2000:
        raise ValueError("invalid reviewed published Web DB rows")
    rows={}
    for row in db_styles:
        if not isinstance(row,dict) or not isinstance(row.get("number"),str):
            raise ValueError("invalid published Web row")
        code=row["number"]
        if code in rows:
            raise ValueError("duplicate official published Web DB row")
        rows[code]=row
    seen=set()
    for entry in approvals["approvals"]:
        if not isinstance(entry,dict) or set(entry)!={"payload","signatures"}:
            raise ValueError("invalid signed record fields")
        p=entry["payload"]
        if not isinstance(p,dict) or set(p)!=PAYLOAD_FIELDS:
            raise ValueError("unsigned/unknown approval fields")
        code=p["candidateCode"]
        if code not in CODES or code in seen or p["schemaVersion"]!=1:
            raise ValueError("unknown/duplicate approval code")
        seen.add(code)
        if (p["result"]!="website_published_and_reviewed"
            or p["skillSourceSha256"]!=pinned[code]["sha256"]
            or p["deployedSha"]!=expected_deployed_sha):
            raise ValueError("unapproved source hash, deployment or result")
        for field in ("webDbPublishedRowSha256",):
            if not isinstance(p[field],str) or not SHA256.fullmatch(p[field]):
                raise ValueError("invalid published DB row fingerprint")
        for field in ("websiteActionId","rightsReviewEvidenceId"):
            if not isinstance(p[field],str) or not TOKEN.fullmatch(p[field]):
                raise ValueError("missing referenced editorial evidence")
        _utc(p["reviewedAtUtc"],now)
        row=rows.get(code)
        if not row or row.get("generation_name")!=pinned[code]["name"] or sha(row)!=p["webDbPublishedRowSha256"]:
            raise ValueError("signed published Web DB export mismatches pending proposal")
        signatures=entry["signatures"]
        if not isinstance(signatures,list) or len(signatures)!=2:
            raise ValueError("two independent website signature claims required")
        seen_roles=set()
        seen_keys=set()
        for sig in signatures:
            if not isinstance(sig,dict) or set(sig)!={"role","keyId","signatureBase64"}:
                raise ValueError("invalid signature fields")
            role,kid=sig["role"],sig["keyId"]
            if role in seen_roles or kid in seen_keys or kid not in keys:
                raise ValueError("duplicate/untrusted signing identity")
            if role not in ROLES or keys[kid][0]!=role:
                raise ValueError("key does not belong to declared role")
            try:
                keys[kid][1].verify(decode64(sig["signatureBase64"],64),canon(p))
            except InvalidSignature:
                raise ValueError("invalid editorial signature") from None
            seen_roles.add(role);seen_keys.add(kid)
        if seen_roles!=set(ROLES):
            raise ValueError("required distinct signers missing")
        results[code]="SIGNED_CLAIM_NEEDS_EXTERNAL_DB_AUTHENTICITY_REVIEW"
    return _result(results)


def _result(results):
    return {
        "issue":132,"checkedCodes":list(CODES),"candidateStates":results,
        "signedClaimCount":sum(s.startswith("SIGNED_") for s in results.values()),
        "automaticWebsiteApprovalGranted":False,
        "publishedDbOriginIndependentlyProven":False,
        "rightsEvidenceIndependentlyVerified":False,
        "releaseGatePassed":False,"decision":"NO-GO",
        "requiresLiveWebDbAndHumanSignoff":True,
        "privateIdsOrSignaturesEmitted":False,
    }


def _private_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise ValueError("invalid or oversized private approval input")
    if os.name=="posix" and stat.S_IMODE(path.stat().st_mode)&0o077:
        raise ValueError("private approval material must have owner-only permissions")
    return json.loads(path.read_text(encoding="utf-8"))


def _public_pending_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise ValueError("invalid published pending manifest path")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle",type=Path)
    ap.add_argument("--trust-registry",type=Path)
    ap.add_argument("--published-web-styles",type=Path)
    ap.add_argument("--deployed-sha",required=True)
    ap.add_argument("--pending",type=Path,default=Path(__file__).resolve().parent/"official_catalog_pending_11.json")
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        if args.report.exists() or args.report.is_symlink():
            raise ValueError("will not overwrite signed approval report")
        all_supplied=all((args.bundle,args.trust_registry,args.published_web_styles))
        if not all_supplied and any((args.bundle,args.trust_registry,args.published_web_styles)):
            raise ValueError("partial approval evidence refused")
        out=evaluate(
            _private_json(args.bundle) if args.bundle else None,
            _private_json(args.trust_registry) if args.trust_registry else None,
            _public_pending_json(args.pending),
            _private_json(args.published_web_styles) if args.published_web_styles else None,
            trusted_sha=os.getenv("HANDRAW_OFFICIAL_TRUST_SHA256",""),
            expected_deployed_sha=args.deployed_sha,
        )
        args.report.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as file:
            json.dump(out,file,ensure_ascii=False,indent=2)
            file.write("\n")
        print("OFFICIAL REVIEW "+json.dumps({
            "signedClaimCount":out["signedClaimCount"],"decision":"NO-GO",
            "privateIdsOrSignaturesEmitted":False},ensure_ascii=False))
        return 0
    except (ValueError,OSError,TypeError,KeyError,json.JSONDecodeError):
        print("Official approval verification BLOCKED: invalid/untrusted inputs",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
