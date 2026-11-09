"""#111 Stage 11: bounded, privacy-safe *window* correlation for Chrome Style.

Trace nodeId is not a verified DOM backendNodeId. Never guess identity from it.
Chrome UpdateLayoutTree elementCount is not a count of CSS selector matches.
The result is a hypothesis-prioritization report, not a proven causal chain.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
import math

from ops.canvas_style_invalidation_111 import (
    INVALIDATION_NAMES, MAX_EVENTS, _category,
)

STYLE_UPDATE = "UpdateLayoutTree"
ROLE_ALLOWLIST = frozenset({
    "studio-shell", "canvas-stage", "viewport", "world", "nodes-layer",
    "node", "node-header", "port", "edge-svg", "edge-path", "minimap",
    "floating-toolbar", "canvas-overlay",
    "shelf", "other", "outside-canvas",
})
ATTR_ALLOWLIST = frozenset({"style", "class"})
MAX_MUTATIONS = 4000
MAX_WINDOW_MS = 50
MAX_ELEMENTS = 100_000


def _valid_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _role(val):
    return val if type(val) is str and val in ROLE_ALLOWLIST else "other"


def reduce_mutation_window(observation):
    """Whitelist mutations/ancestor *roles*, never raw DOM/class values."""
    if not isinstance(observation, dict):
        return {"available": False, "reason": "no-browser-observation"}
    rows = observation.get("records", [])
    if not isinstance(rows, list) or len(rows) > MAX_MUTATIONS:
        raise ValueError("invalid or oversized DOM mutation list")
    by_role, by_attr, chains = Counter(), Counter(), Counter()
    for row in rows:
        if not isinstance(row, dict):
            continue
        attr = row.get("attribute")
        if attr not in ATTR_ALLOWLIST:
            continue
        role = _role(row.get("role"))
        by_role[role] += 1
        by_attr[attr] += 1
        chain = row.get("ancestors")
        if isinstance(chain, list) and len(chain) <= 12:
            # Distinguish actual ancestor chains from inferred CSS matching.
            checked = tuple(_role(x) for x in chain)
            if checked:
                chains[" > ".join(checked)] += 1
    overflow = observation.get("overflow", 0)
    return {
        "available": True,
        "observedAttributes": sum(by_attr.values()),
        "byAttribute": dict(sorted(by_attr.items())),
        "byTargetRole": dict(sorted(by_role.items())),
        "topActualDomAncestorRoleChains": [
            {"chain": key, "count": count}
            for key, count in chains.most_common(12)],
        "eventsDroppedAtCap": min(max(int(overflow), 0), 1_000_000)
        if type(overflow) is int else None,
        "reconstructedFromMutationObserver": True,
        "chromeTraceNodeIdentityVerified": False,
        "rawNodeIdsPersisted": False,
        "rawDomPersisted": False,
    }


def summarize_causality_window(trace, observation=None):
    """Relate invalidations to UpdateLayoutTree on a bounded same-thread clock.

    A trace invalidation which precedes an UpdateLayoutTree on the same pid/tid
    by <=50 ms is a *temporal neighbor*, not a proof of propagation. Chrome's
    trace nodeId fields are opaque: this code never emits or attempts to map
    them to live DOM without a verified CDP bridge.
    """
    events = trace.get("traceEvents", []) if isinstance(trace, dict) else []
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("invalid/oversized Chrome trace")
    updates = []
    invalidations = []
    reason_categories = Counter()
    invalidation_names = Counter()
    node_identity_fields_observed = Counter()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        name = ev.get("name")
        ts = ev.get("ts")
        if name not in INVALIDATION_NAMES and name != STYLE_UPDATE:
            continue
        if not _valid_number(ts) or ts < 0:
            continue
        pid, tid = ev.get("pid"), ev.get("tid")
        if type(pid) is not int or type(tid) is not int:
            continue
        args = ev.get("args")
        if not isinstance(args, dict):
            args = {}
        data = args.get("data")
        if not isinstance(data, dict):
            data = {}
        if name == STYLE_UPDATE:
            if ev.get("ph") != "X":
                continue
            count = data.get("elementCount", args.get("elementCount"))
            if type(count) is not int or not 0 <= count <= MAX_ELEMENTS:
                count = None
            updates.append((float(ts), pid, tid, count))
        else:
            reason = _category(data.get("reason") or args.get("reason"))
            invalidations.append((float(ts), pid, tid, reason, name))
            invalidation_names[name] += 1
            reason_categories[reason] += 1
            if "nodeId" in data or "nodeId" in args:
                node_identity_fields_observed["opaque-nodeId"] += 1
            if "nodeName" in data or "nodeName" in args:
                node_identity_fields_observed["unverified-nodeName"] += 1

    by_thread = {}
    for ts, pid, tid, count in updates:
        by_thread.setdefault((pid, tid), []).append((ts, count))
    for values in by_thread.values():
        values.sort(key=lambda x: x[0])
    ticks = {key: [x[0] for x in values] for key, values in by_thread.items()}
    join_by_category = Counter()
    high_by_category = Counter()
    joined = high = 0
    for ts, pid, tid, reason, _ in invalidations:
        key = (pid, tid)
        times = ticks.get(key, [])
        index = bisect_left(times, ts)
        if index >= len(times):
            continue
        next_ts, count = by_thread[key][index]
        if next_ts - ts > MAX_WINDOW_MS * 1000:
            continue
        joined += 1
        join_by_category[reason] += 1
        if count is not None and count >= 8000:
            high += 1
            high_by_category[reason] += 1

    counts = [count for _, _, _, count in updates if count is not None]
    large = [count for count in counts if count >= 8000]
    return {
        "source": "Chrome-CDP-invalidationTracking-same-thread-window",
        "traceEventCount": len(events),
        "invalidationEvents": len(invalidations),
        "invalidationByName": dict(sorted(invalidation_names.items())),
        "reasonCategories": dict(sorted(reason_categories.items())),
        "unverifiedNodeIdFieldsObserved": dict(node_identity_fields_observed),
        "updateLayoutTree": {
            "samplesWithElementCount": len(counts),
            "maxElementCount": max(counts) if counts else None,
            "largeEventsGE8000": len(large),
            "largeElementCounts": sorted(set(large))[:20],
        },
        "joinedToNextSameThreadUpdateWithin50Ms": joined,
        "joinedReasonCategories": dict(sorted(join_by_category.items())),
        "joinNearLargeUpdateByReason": dict(sorted(high_by_category.items())),
        "joinsNearLargeUpdate": high,
        "actualDomMutations": reduce_mutation_window(observation),
        "cssomSelectorMapping": "separate-static-census-only",
        "timingCorrelationProvesCausation": False,
        "chromeTraceNodeIdentityVerified": False,
        "chromeElementCountMeansSelectorMatches": False,
        "rootCauseProven": False,
        "productionFrameSLA": False,
        "rawTracePersisted": False,
    }


def validate_selector_census(rows):
    """Client collected only fixed local selectors; never echo arbitrary text."""
    allowed = {
        ".ic-node:hover .ic-port-zone": "node-hover-port",
        ".ic-node.is-selected .ic-port-zone": "selected-port",
        ".ic-studio-shell.is-wiring .ic-port-zone": "shell-wiring-port",
        ".ic-node:hover .ic-node-header-above": "node-hover-header",
        ".ic-node.is-selected .ic-node-header-above": "selected-header",
        ".ic-canvas-stage:has(.ic-canvas-template-library) .ic-shelf-drawer":
            "canvas-has-shelf",
    }
    out = []
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("invalid CSSOM census")
    for row in rows:
        if not isinstance(row, dict):
            continue
        selector = row.get("selector")
        match = row.get("matches")
        if type(selector) is str and selector in allowed and type(match) is int and 0 <= match <= 20_000:
            out.append({"candidate": allowed[selector],
                        "matchesAtSnapshot": match,
                        "ancestorChildChain": selector.split(" "),
                        "cssomSnapshotOnly": True})
    return {"candidates": out,
            "sameWindowCausationProven": False,
            "doesNotCountStyleRecalculation": True}
