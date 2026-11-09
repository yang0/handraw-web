"""#84/#112 read-only V3 cross-client multi-media ownership reconciliation.

Inputs are normalized identifiers from a disposable PG17+S3 test fixture.
No credentials, image payloads, network activity, or production writes. C-level
engineering evidence cannot issue a D-level production release sign-off.
"""
from __future__ import annotations

from collections import defaultdict


def audit_v3_uploads(rows: list[dict], expected: list[dict]) -> dict:
    """Fail closed if per-run slots, Work links, media owners or grants drift.

    rows keys: owner, client, run, work, position, media, mediaOwner,
    workMedia, publicGrant. expected keys: owner, client, run, work,
    successful, status (public|hidden). Each row represents a successful item.
    """
    if not expected:
        raise ValueError("expected runs required")
    specs = {}
    for spec in expected:
        key = (spec["owner"], spec["run"])
        if key in specs or spec["status"] not in ("public", "hidden"):
            raise ValueError("duplicate or unsupported expected run")
        if not spec["work"] or spec["successful"] < 1:
            raise ValueError("invalid expected work/media count")
        specs[key] = spec
    by_run: dict[tuple, list[dict]] = defaultdict(list)
    owner_of_run = {}
    owner_of_work = {}
    owner_of_media = {}
    slots = set()
    for row in rows:
        owner, run, work, media = (row.get(k) for k in
                                   ("owner", "run", "work", "media"))
        if not all((owner, run, work, media)):
            raise ValueError("missing identifier")
        key = (owner, run)
        spec = specs.get(key)
        if spec is None:
            raise ValueError("untracked or foreign run")
        if row.get("client") != spec["client"] or work != spec["work"]:
            raise ValueError("client or Work mismatch")
        for registry, ident in ((owner_of_run, run), (owner_of_work, work),
                                (owner_of_media, media)):
            previous = registry.setdefault(ident, owner)
            if previous != owner:
                raise ValueError("cross-owner identity collision")
        position = row.get("position")
        if type(position) is not int or position < 0:
            raise ValueError("invalid item position")
        slot = (run, position)
        if slot in slots:
            raise ValueError("duplicate RunItem position")
        slots.add(slot)
        if row.get("mediaOwner") != owner or row.get("workMedia") != media:
            raise ValueError("foreign media or mismatched WorkMedia")
        if type(row.get("publicGrant")) is not bool:
            raise ValueError("grant observation missing")
        if row["publicGrant"] != (spec["status"] == "public"):
            raise ValueError("stale or missing public media grant")
        by_run[key].append(row)
    for key, spec in specs.items():
        if len(by_run.get(key, ())) != spec["successful"]:
            raise ValueError("successful item count mismatch")
        positions = {row["position"] for row in by_run[key]}
        # Partially failed runs can have gaps, but successful positions are
        # unique and bounded by the expected total set of slots.
        if max(positions) >= spec.get("totalSlots", spec["successful"]):
            raise ValueError("successful slot out of bounds")
    return {
        "evidenceLevel": "C-disposable-PG17-S3-emulation",
        "auditedRuns": len(specs),
        "auditedSuccessfulMedia": len(rows),
        "owners": len({spec["owner"] for spec in specs.values()}),
        "crossOwnerIsolation": True,
        "singleWorkPerRun": True,
        "mediaLinkage": True,
        "moderationGrantsConsistent": True,
        "readyForRelease": False,
        "productionNoGo": True,
    }
