"""#111: bounded, private-data-free Chrome style invalidation diagnostics.

Chrome emits invalidation events only with supported tracing categories/versions.
No raw event or raw CSS text is saved. Missing events mean *unobserved*, not zero.
This is an offline diagnostic and never a browser performance SLA.
"""
from __future__ import annotations

from collections import Counter
import math

INVALIDATION_NAMES = (
    "StyleRecalcInvalidationTracking",
    "StyleInvalidatorInvalidationTracking",
    "StyleInvalidationTracking",
    "ScheduleStyleRecalculation",
)
STYLE_EVENTS = ("RecalculateStyles", "UpdateLayoutTree")
MAX_EVENTS = 400_000


def _category(reason):
    """Whitelist categories, never retain raw trace reasons or user content."""
    if not isinstance(reason, str):
        return "unknown"
    value = reason.lower()
    if "pseudo" in value or "hover" in value or "focus" in value:
        return "pseudo-state"
    if "attribute" in value or "class" in value:
        return "attribute-or-class"
    if "stylesheet" in value or "rule" in value or "selector" in value:
        return "stylesheet-or-selector"
    if "inline" in value or "style" in value or "property" in value:
        return "style-property"
    if "tree" in value or "sibling" in value or "descendant" in value:
        return "tree-dependency"
    if "dom" in value or "node" in value:
        return "dom-change"
    return "unknown"


def summarize_style_invalidation(trace):
    events = trace.get("traceEvents", []) if isinstance(trace, dict) else []
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("invalid or excessive Chrome style trace events")
    invalidations = Counter()
    reasons = Counter()
    affected = []
    style_events = Counter()
    for event in events:
        if not isinstance(event, dict):
            continue
        name = event.get("name")
        if name not in INVALIDATION_NAMES and name not in STYLE_EVENTS:
            continue
        args = event.get("args", {})
        args = args if isinstance(args, dict) else {}
        data = args.get("data", {})
        data = data if isinstance(data, dict) else {}
        if name in INVALIDATION_NAMES:
            invalidations[name] += 1
            reason = data.get("reason") or args.get("reason")
            reasons[_category(reason)] += 1
        elif event.get("ph") == "X":
            style_events[name] += 1
            count = data.get("elementCount", args.get("elementCount"))
            if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 100_000:
                affected.append(count)
    return {
        "source": "Chromium-CDP-invalidationTracking",
        "traceEventCount": len(events),
        "invalidationEventsObserved": bool(invalidations),
        "invalidationsByType": {name: invalidations[name] for name in INVALIDATION_NAMES},
        "reasonCategories": dict(sorted(reasons.items())),
        "styleUpdateEvents": dict(sorted(style_events.items())),
        "reportedAffectedElements": {
            "samples": len(affected),
            "max": max(affected) if affected else None,
            "median": sorted(affected)[len(affected)//2] if affected else None,
        },
        "rawTracePersisted": False,
        "rootCauseProven": False,
        "productionFrameSLA": False,
    }


def summarize_selector_footprint(report):
    """Reduce DOM CSSOM selector match census to bounded, static safe metadata."""
    rows = report.get("selectors", []) if isinstance(report, dict) else []
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("invalid CSS selector census")
    allowed = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sel = row.get("selector")
        matches = row.get("matches")
        if not isinstance(sel, str) or len(sel) > 150 or not (
            sel.startswith(".ic-") or sel.startswith("#ic-")
        ):
            continue
        if not all(ch.isalnum() or ch in " .#>+~:()-_[]*=" for ch in sel):
            continue
        if not isinstance(matches, int) or isinstance(matches, bool) or not 0 <= matches <= 100000:
            continue
        allowed.append({
            "selector": sel,
            "matches": matches,
            "relational": ":has(" in sel or "~" in sel or "+" in sel,
            "dynamicPseudo": any(x in sel for x in (":hover", ":focus", ":active", ":focus-within")),
            "descendant": " " in sel or ">" in sel,
        })
    allowed.sort(key=lambda row: (-row["matches"], row["selector"]))
    return {
        "source": "same-origin-static-CSSOM-querySelectorAll",
        "stylesheetsSkipped": min(max(int(report.get("skippedSheets", 0)), 0), 1000),
        "rulesInspected": min(max(int(report.get("rulesInspected", 0)), 0), 100000),
        "eligibleSelectors": len(allowed),
        "highFanoutSelectors": allowed[:20],
        "matching300Cards": any(r["matches"] >= 300 for r in allowed),
        "matchingIsNotRecalcCost": True,
        "rootCauseProven": False,
    }


def summarize_selector_timings(trace):
    """Chrome SelectorStats: real instrumented match attempts and elapsed us.

    The blink.debug capture changes workload cost and is NOT directly
    comparable to no-debug Performance counters. Never persist style_sheet_id
    or selectors outside a tiny local static .ic-/#ic- allowlist.
    """
    events = trace.get("traceEvents", []) if isinstance(trace, dict) else []
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("invalid or excessive selector trace events")
    records = {}
    stats_events = 0
    for event in events:
        if not isinstance(event, dict) or event.get("name") != "SelectorStats":
            continue
        stats_events += 1
        args = event.get("args") or {}
        if not isinstance(args, dict):
            continue
        block = args.get("selector_stats") or {}
        if not isinstance(block, dict):
            continue
        timings = block.get("selector_timings") or []
        if not isinstance(timings, list):
            continue
        for t in timings[:20000]:
            if not isinstance(t, dict):
                continue
            sel = t.get("selector")
            if not isinstance(sel, str) or not (sel.startswith(".ic-") or sel.startswith("#ic-")):
                continue
            if len(sel) > 150 or not all(
                ch.isalnum() or ch in " .#>+~:()-_[]*=" for ch in sel
            ):
                continue
            elapsed = t.get("elapsed (us)")
            attempts = t.get("match_attempts")
            hits = t.get("match_count")
            rejected = t.get("fast_reject_count", 0)
            if not all(isinstance(n, (int, float)) and not isinstance(n, bool) and
                       math.isfinite(n) and n >= 0 for n in (elapsed, attempts, hits, rejected)):
                continue
            if attempts > 10_000_000 or hits > attempts or rejected > attempts:
                continue
            row = records.setdefault(sel, {"selector": sel, "elapsedUs": 0.0,
                                           "matchAttempts": 0, "matchCount": 0,
                                           "fastRejectCount": 0})
            row["elapsedUs"] += elapsed
            row["matchAttempts"] += int(attempts)
            row["matchCount"] += int(hits)
            row["fastRejectCount"] += int(rejected)
    ranked = sorted(records.values(), key=lambda row: -row["elapsedUs"])
    result = []
    for item in ranked[:20]:
        result.append({
            "selector": item["selector"],
            "elapsedMs": round(item["elapsedUs"] / 1000, 4),
            "matchAttempts": item["matchAttempts"],
            "matchCount": item["matchCount"],
            "fastRejectCount": item["fastRejectCount"],
        })
    return {
        "source": "Chrome-SelectorStats-disabled-by-default-blink.debug",
        "selectorStatsEventsObserved": stats_events > 0,
        "events": stats_events,
        "eligibleUniqueSelectors": len(records),
        "topByMeasuredMatchTime": result,
        "addsInstrumentationOverhead": True,
        "rawTracePersisted": False,
        "productionFrameSLA": False,
    }
