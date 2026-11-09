"""#132: read-only STAGING of official catalog transition after human approval.

Signed payloads in this file are untrusted inputs. Run the separate two-role
Ed25519, rights-origin and live website DB audits BEFORE this check. Even a
matching dry-run parity cannot approve assets, mutate Web/Skill or issue GO.
"""
from __future__ import annotations

import re

from ops.check_official_catalog_parity import audit
from ops.studio_official_approval_132 import CODES, sha

COMMIT = re.compile(r"^[a-f0-9]{40}$")


def stage_transition(catalog, skill_styles, skill_layouts,
                     pending_before, pending_after,
                     approved_styles, approved_layouts,
                     signed_payloads, *, deployed_sha):
    """Assert a proposed Web-authoritative three-resource release is rollback-safe."""
    if not isinstance(deployed_sha,str) or not COMMIT.fullmatch(deployed_sha):
        raise ValueError("deployed Web SHA missing")
    if (not isinstance(pending_before,dict)
        or not isinstance(pending_after,dict)
        or pending_before.get("schemaVersion") != 1
        or pending_after.get("schemaVersion") != 1
        or not isinstance(pending_before.get("pendingSkillOnly"),list)
        or not isinstance(pending_after.get("pendingSkillOnly"),list)):
        raise ValueError("invalid promotion manifests")
    original = pending_before["pendingSkillOnly"]
    future = pending_after["pendingSkillOnly"]
    if (len(original) != 3 or {r.get("code") for r in original} != set(CODES)
        or len(future) != 0):
        raise ValueError("promotion must retire exactly the three reviewed pending codes")
    if not isinstance(signed_payloads,list) or len(signed_payloads) != 3:
        raise ValueError("three candidate-specific signed payloads required")
    by_code={}
    for row in signed_payloads:
        if not isinstance(row,dict):
            raise ValueError("invalid signed payload")
        code=row.get("candidateCode")
        if code not in CODES or code in by_code:
            raise ValueError("missing/duplicated approved candidate code")
        if row.get("deployedSha")!=deployed_sha or row.get("result")!="website_published_and_reviewed":
            raise ValueError("approved deployment SHA/status drift")
        by_code[code]=row
    skill={r.get("number"):r for r in skill_styles if isinstance(r,dict)}
    db={r.get("number"):r for r in approved_styles if isinstance(r,dict)}
    if len(skill)!=len(skill_styles) or len(db)!=len(approved_styles):
        raise ValueError("ambiguous Skill or DB official identifiers")
    for old in original:
        code=old["code"]
        payload=by_code[code]
        if (code not in skill or code not in db
            or sha(skill[code])!=old["sha256"]
            or sha(skill[code])!=payload.get("skillSourceSha256")
            or sha(db[code])!=payload.get("webDbPublishedRowSha256")
            or db[code].get("generation_name")!=old["name"]
            or skill[code].get("generation_name")!=old["name"]):
            raise ValueError("approved official resource roll-forward/rollback fingerprint mismatch")
    report=audit(catalog,skill_styles,skill_layouts,pending_after,
                 strict=True,approved_styles=approved_styles,
                 approved_layouts=approved_layouts)
    if not report["readyForRelease"] or report["webDynamicApprovedCount"]<3:
        raise ValueError("strict Web/Skill official parity incomplete")
    return {
        "issue":132,"stagedCodes":list(CODES),
        "allStagedFingerprintChecksPassed":True,
        "strictCatalogParityDryRunPassed":True,
        "signedPayloadSignaturesVerifiedHere":False,
        "rightsOwnershipIndependentlyVerifiedHere":False,
        "liveWebsiteDbOriginVerifiedHere":False,
        "publishingAttempted":False,
        "productionApprovalAuthorized":False,"decision":"NO-GO",
    }
