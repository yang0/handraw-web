"""#11 audit: website-authored official IDs vs the reviewed Skill snapshot.

A known Skill-only proposal is NOT an approved/public Web asset. CI may record
an explicitly pinned pending proposal, but --strict is a release gate and must
fail while any proposal awaits website authorization. The script NEVER writes
to the catalog, the Skill tree, or a database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CODE = re.compile(r"^[A-Z]{2}-[0-9]{3}$")
HASH = re.compile(r"^[a-f0-9]{64}$")


def _read(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _sha(item: dict[str, Any]) -> str:
    data = json.dumps(item, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _index(rows: Any, *, label: str, id_field: str | None = None) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{label}: expected JSON array")
    result: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError(f"{label}: item must be an object")
        ident = item.get(id_field) if id_field else item.get("id")
        if not isinstance(ident, str) or not CODE.fullmatch(ident):
            raise ValueError(f"{label}: invalid official ID {ident!r}")
        if ident in result:
            raise ValueError(f"{label}: duplicated official ID {ident}")
        result[ident] = item
    return result


def audit(catalog: dict[str, Any], styles: Any, layouts: Any,
          exceptions: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    """Return public, machine-readable drift report or raise ValueError.

    Pure function: inputs are local JSON payloads, there is no network access
    and no accidental acceptance of Skill additions into the public website.
    """
    resources = catalog.get("resources")
    if not isinstance(resources, list):
        raise ValueError("catalog.resources must be an array")
    official: list[dict[str, Any]] = []
    for item in resources:
        if not isinstance(item, dict):
            raise ValueError("catalog item must be an object")
        if item.get("kind") in ("style", "layout"):
            official.append(item)
    web = _index(official, label="Web catalog")
    skill_style = _index(styles, label="Skill styles", id_field="number")
    skill_layout = _index(layouts, label="Skill layouts", id_field="id")
    duplicate = set(skill_style) & set(skill_layout)
    if duplicate:
        raise ValueError(f"duplicate Skill code across categories: {sorted(duplicate)}")
    skill = {**{c: ("style", row) for c, row in skill_style.items()},
             **{c: ("layout", row) for c, row in skill_layout.items()}}

    web_only = sorted(set(web) - set(skill))
    skill_only = sorted(set(skill) - set(web))
    mismatched_kind = sorted(
        c for c in set(web) & set(skill) if web[c]["kind"] != skill[c][0])

    if exceptions.get("schemaVersion") != 1 or not isinstance(
            exceptions.get("pendingSkillOnly"), list):
        raise ValueError("pending manifest schemaVersion=1 and pendingSkillOnly list required")
    pending: dict[str, dict[str, Any]] = {}
    for row in exceptions["pendingSkillOnly"]:
        if not isinstance(row, dict):
            raise ValueError("invalid pending manifest record")
        code = row.get("code")
        if not isinstance(code, str) or not CODE.fullmatch(code) or code in pending:
            raise ValueError(f"invalid or duplicate pending code {code!r}")
        if row.get("kind") not in ("style", "layout") or not isinstance(row.get("name"), str):
            raise ValueError(f"invalid pending identity for {code}")
        if not isinstance(row.get("sha256"), str) or not HASH.fullmatch(row["sha256"]):
            raise ValueError(f"invalid pending content hash for {code}")
        if not isinstance(row.get("issue"), int) or row["issue"] < 1 or not row.get("reason"):
            raise ValueError(f"pending {code} must link an issue and reason")
        pending[code] = row

    known = sorted(set(skill_only) & set(pending))
    unexpected = sorted(set(skill_only) - set(pending))
    stale_exceptions = sorted(set(pending) - set(skill_only))
    altered: list[str] = []
    for code in known:
        item_kind, item = skill[code]
        approved = pending[code]
        name = str(item.get("generation_name") or item.get("name") or "")
        if (item_kind != approved["kind"] or name != approved["name"]
                or _sha(item) != approved["sha256"]):
            altered.append(code)

    report = {
        "status": "in_sync" if not skill_only and not web_only and not mismatched_kind
                  else "pending_review",
        "webCount": len(web),
        "skillCount": len(skill),
        "webOnly": web_only,
        "skillOnly": skill_only,
        "knownPending": known,
        "unexpectedSkillOnly": unexpected,
        "staleExceptions": stale_exceptions,
        "mismatchedKind": mismatched_kind,
        "alteredPending": altered,
        "readyForRelease": not (web_only or skill_only or mismatched_kind or stale_exceptions),
    }
    bad = bool(web_only or unexpected or stale_exceptions or mismatched_kind or altered)
    if strict and skill_only:
        bad = True
    if bad:
        raise ValueError(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path,
                        default=ROOT / "plugin/content/catalog.json")
    parser.add_argument("--skill-root", type=Path, required=True,
                        help="read-only path to Skill handdraw-style-prompter")
    parser.add_argument("--pending", type=Path,
                        default=ROOT / "ops/official_catalog_pending_11.json")
    parser.add_argument("--strict", action="store_true",
                        help="release gate: reject even individually acknowledged pending codes")
    parser.add_argument("--report", type=Path,
                        help="optional output JSON report; contains IDs only")
    args = parser.parse_args(argv)
    try:
        result = audit(
            _read(args.catalog),
            _read(args.skill_root / "references/styles.json"),
            _read(args.skill_root / "references/layouts.json"),
            _read(args.pending), strict=args.strict,
        )
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"Official catalog parity BLOCKED: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized + "\n", encoding="utf-8")
    if result["knownPending"]:
        print("ATTENTION: pending Skill-only official code(s): " +
              ", ".join(result["knownPending"]) +
              "; NOT website-approved; Issue #11 remains open and "
              "production parity is NO-GO.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
