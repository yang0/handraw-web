"""#132: private, OFFLINE rights provenance contract for proposed official styles.

This accepts evidence *references* and immutable fingerprints, not rights
ownership assertions. A website editor must inspect source originals and
licenses independently. Only test fixtures are committed; never source media.
"""
from __future__ import annotations

import hashlib
import json
import re

CODES = ("FF-018", "FF-019", "FG-025")
HASH = re.compile(r"^[a-f0-9]{64}$")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
REVIEW_FIELDS = {
    "candidateCode", "skillSourceSha256", "rightsReviewEvidenceId",
    "promptProvenanceEvidenceId", "descriptionProvenanceEvidenceId",
    "reviewDecision", "assets",
}
ASSET_FIELDS = {
    "assetSha256", "originType", "rightsHolderEvidenceId",
    "licenseOrPermissionEvidenceId", "attributionEvidenceId",
    "commercialReuseAllowed", "derivativeUseAllowed",
    "officialWebsitePublishAllowed",
}
ORIGINS = {"self-created", "explicit-license", "public-domain"}


def digest(obj):
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _token(value):
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None


def index_reviews(bundle, pending):
    """Return per-code *unverified* rights review rows, rejecting incomplete data.

    The digest of each entire validated row must be covered by both Ed25519
    signatures in the website approval verifier. No publication is performed.
    """
    if (not isinstance(bundle, dict) or set(bundle) != {"schemaVersion", "reviews"}
            or type(bundle["schemaVersion"]) is not int or bundle["schemaVersion"] != 1
            or not isinstance(bundle["reviews"], list) or len(bundle["reviews"]) > 3):
        raise ValueError("invalid private editorial rights bundle")
    if (not isinstance(pending, dict) or
            set(pending) != set(CODES)):
        raise ValueError("unexpected candidate snapshot")
    result = {}
    for review in bundle["reviews"]:
        if not isinstance(review, dict) or set(review) != REVIEW_FIELDS:
            raise ValueError("incomplete editorial rights metadata")
        code = review["candidateCode"]
        if code not in CODES or code in result:
            raise ValueError("unknown or repeated rights review")
        if (review["skillSourceSha256"] != pending[code]["sha256"]
                or not isinstance(review["skillSourceSha256"], str)):
            raise ValueError("rights review has stale Skill candidate hash")
        if review["reviewDecision"] != "cleared_for_editorial_signature":
            raise ValueError("rights review not cleared")
        for key in ("rightsReviewEvidenceId", "promptProvenanceEvidenceId",
                    "descriptionProvenanceEvidenceId"):
            if not _token(review[key]):
                raise ValueError("missing editorial rights provenance")
        assets = review["assets"]
        if not isinstance(assets, list) or not 1 <= len(assets) <= 64:
            raise ValueError("no source asset rights coverage")
        seen = set()
        for asset in assets:
            if not isinstance(asset, dict) or set(asset) != ASSET_FIELDS:
                raise ValueError("incomplete source asset license metadata")
            value = asset["assetSha256"]
            if not isinstance(value, str) or not HASH.fullmatch(value) or value in seen:
                raise ValueError("invalid/duplicate original asset hash")
            seen.add(value)
            if asset["originType"] not in ORIGINS:
                raise ValueError("unknown source license category")
            for key in ("rightsHolderEvidenceId", "licenseOrPermissionEvidenceId",
                        "attributionEvidenceId"):
                if not _token(asset[key]):
                    raise ValueError("missing source author/license/attribution evidence")
            for key in ("commercialReuseAllowed", "derivativeUseAllowed",
                        "officialWebsitePublishAllowed"):
                if asset[key] is not True:
                    raise ValueError("license does not permit official website publication")
        result[code] = review
    return result
