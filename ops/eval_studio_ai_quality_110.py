"""Issue #110 reproducible AI recommendation evaluation (not model generation).

Evaluates *recorded* Studio /api/studio/ai-plan responses from a specified
authorized-catalog snapshot against hand-labelled editorial scenarios.
No network calls, model invocation, private prompt content, or image billing.
The CI golden mock checks the metric implementation, NOT real model quality.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = ROOT / "tests" / "fixtures" / "studio_ai_quality_110.json"


def _id(ref: Any) -> str:
    if isinstance(ref, dict):
        value = ref.get("id")
    else:
        value = ref
    return value if isinstance(value, str) else ""


def _parse_response(value: Any) -> dict[str, Any]:
    """Read actual normalized response; raw model JSON is NOT a success proof."""
    if not isinstance(value, dict) or value.get("ok") is not True or \
            value.get("schemaVersion") != 1 or value.get("source") != "model" or \
            value.get("phase") != "review":
        raise ValueError("response must be successful, normalized Studio AI proposal")
    cp = value.get("creationSpecPatch")
    if not isinstance(cp, dict) or not isinstance(cp.get("changes"), dict):
        raise ValueError("missing authorized CreationSpecPatch")
    changes = cp["changes"]
    reasons = cp.get("reasons")
    if not isinstance(reasons, dict) or any(
            not isinstance(reasons.get(key), str) or
            len(reasons[key].strip()) < 2 or len(reasons[key]) > 240
            for key in ("style", "layout", "ratio")):
        raise ValueError("missing/excessively long field reasons")
    candidates = cp.get("candidates")
    if not isinstance(candidates, dict):
        raise ValueError("model proposal missing alternatives")
    for group in ("style", "layout"):
        values = candidates.get(group)
        if not isinstance(values, list) or len(values) < 2:
            raise ValueError("need at least one alternative for " + group)
        ids = [_id(x) for x in values]
        if not all(ids) or len(set(ids)) != len(ids):
            raise ValueError("alternatives duplicated or malformed: " + group)
    if value.get("cost") != {"generationStarted": False, "runCreated": False}:
        raise ValueError("AI planning must not claim generation/billing")
    return {"kind": value.get("kind"),
            "style": _id(changes.get("style")),
            "layout": _id(changes.get("layout")),
            "ratio": changes.get("ratio"),
            "candidates": candidates,
            "slots": value.get("planPatch", {}).get("slots") if
                     isinstance(value.get("planPatch"), dict) else None,
            "reasons": reasons}


def evaluate(corpus: dict[str, Any], samples: list[dict[str, Any]],
             allowlist: dict[str, Any], *, min_fit: float = 0.85,
             min_diversity: float = 0.65,
             min_consistency: float = 0.80) -> dict[str, Any]:
    """Audit quality independently of any provider.

    Whitelist MUST come from an authorization-aware snapshot, e.g.
    backend.studio_ai_plan._user_catalog for the actual user. Passing a bare
    public static catalog cannot prove user entitlements.
    """
    cases = corpus.get("cases")
    if corpus.get("schemaVersion") != 1 or not isinstance(cases, list) or \
            not 5 <= len(cases) <= 50 or not all(
            isinstance(c, dict) and isinstance(c.get("id"), str)
            for c in cases):
        raise ValueError("evaluation corpus requires 5–50 named cases")
    by_id = {c["id"]: c for c in cases}
    if len(by_id) != len(cases):
        raise ValueError("duplicate case ID")
    if not isinstance(samples, list) or len(samples) > 300:
        raise ValueError("evaluation response list exceeds safe limit")
    if not isinstance(allowlist, dict):
        raise ValueError("authorized catalog snapshot required")
    allowed: dict[str, set[str]] = {}
    for kind in ("style", "layout"):
        rows = allowlist.get(kind)
        if not isinstance(rows, list) or not rows:
            raise ValueError("authorized " + kind + " catalog is empty")
        allowed[kind] = {_id(x) for x in rows}
        allowed[kind].discard("")
    for case in cases:
        if case.get("kind") not in ("image", "series", "article") or \
                not case.get("subject") or type(case.get("count")) is not int or \
                not 1 <= case["count"] <= 20:
            raise ValueError("invalid scenario " + case["id"])
        if not isinstance(case.get("expectedStyleIds"), list) or \
                not isinstance(case.get("expectedLayoutIds"), list):
            raise ValueError("missing editorial labels for " + case["id"])
        if not set(case["expectedStyleIds"]).issubset(allowed["style"]) or \
                not set(case["expectedLayoutIds"]).issubset(allowed["layout"]):
            raise ValueError("scenario references style/layout outside user's entitlement")

    seen = set()
    entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    problems: list[str] = []
    valid = 0
    fit_points = 0
    distinct_styles: set[str] = set()
    distinct_layouts: set[str] = set()
    for raw in samples:
        if not isinstance(raw, dict) or raw.get("caseId") not in by_id or \
                raw.get("trial") not in (1, 2):
            problems.append("unknown scenario or trial number")
            continue
        cid, trial = raw["caseId"], raw["trial"]
        if (cid, trial) in seen:
            problems.append(cid + ": duplicate trial " + str(trial))
            continue
        seen.add((cid, trial))
        case = by_id[cid]
        try:
            normalized = _parse_response(raw.get("response"))
            if normalized["kind"] != case["kind"] or \
                    normalized["style"] not in allowed["style"] or \
                    normalized["layout"] not in allowed["layout"]:
                raise ValueError("kind mismatch or unauthorized style/layout")
            for kind in ("style", "layout"):
                if not all(_id(x) in allowed[kind]
                           for x in normalized["candidates"][kind]):
                    raise ValueError("unauthorized alternative " + kind)
            if normalized["ratio"] not in ("1:1", "3:4", "4:3", "9:16",
                                           "16:9", "2.35:1"):
                raise ValueError("unknown ratio")
            if case["kind"] == "image" and normalized["slots"] is not None:
                raise ValueError("image proposal must not generate PlanSlots")
            if case["kind"] != "image" and (
                    not isinstance(normalized["slots"], list) or
                    len(normalized["slots"]) != case["count"] or
                    any(not isinstance(s, dict) or not s.get("slotId") or
                        not s.get("reasons", {}).get("subject")
                        for s in normalized["slots"])):
                raise ValueError("missing or invalid PlanSlot output")
            fits = [normalized["style"] in case["expectedStyleIds"],
                    normalized["layout"] in case["expectedLayoutIds"],
                    normalized["ratio"] == case["ratio"]]
            fit_points += sum(fits)
            distinct_styles.add(normalized["style"])
            distinct_layouts.add(normalized["layout"])
            entries[cid].append(normalized)
            valid += 1
        except (ValueError, TypeError, AttributeError) as exc:
            problems.append(cid + "#" + str(trial) + ": " + str(exc))

    expected_trials = 2 * len(cases)
    for case in cases:
        for trial in (1, 2):
            if (case["id"], trial) not in seen:
                problems.append(case["id"] + ": missing trial " + str(trial))
    consistent = sum(
        len(entries[c["id"]]) == 2 and
        all((a["style"], a["layout"], a["ratio"]) ==
            (entries[c["id"]][0]["style"], entries[c["id"]][0]["layout"],
             entries[c["id"]][0]["ratio"]) for a in entries[c["id"]])
        for c in cases
    )
    fit = round(fit_points / (expected_trials * 3), 4)
    diversity = round(min(len(distinct_styles), len(distinct_layouts)) /
                      len(cases), 4)
    consistency = round(consistent / len(cases), 4)
    metrics = {
        "cases": len(cases), "expectedTrials": expected_trials,
        "validResponses": valid,
        "editorialFit": fit,
        "distinctStyleCount": len(distinct_styles),
        "distinctLayoutCount": len(distinct_layouts),
        "diversity": diversity,
        "consistency": consistency,
        "minimums": {"fit": min_fit, "diversity": min_diversity,
                     "consistency": min_consistency},
    }
    ok = (valid == expected_trials and not problems and
          fit >= min_fit and diversity >= min_diversity and
          consistency >= min_consistency)
    return {
        "ok": ok,
        "evaluationType": "recorded_response_quality",
        "notLiveModelEvidence": True,
        "metrics": metrics,
        # No raw prompts, protected catalog descriptions or model messages.
        "problems": problems[:50],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--responses", type=Path, required=True,
                        help="JSON list of recorded NORMALIZED AI responses")
    parser.add_argument("--allowlist", type=Path, required=True,
                        help="sanitized user-authorized {style:[],layout:[]} snapshot")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    responses = json.loads(args.responses.read_text(encoding="utf-8"))
    allowed = json.loads(args.allowlist.read_text(encoding="utf-8"))
    report = evaluate(corpus, responses, allowed)
    out = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(out, encoding="utf-8")
    print(out)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
