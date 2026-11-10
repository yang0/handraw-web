"""#111 local Chromium frame-pipeline diagnostics (metadata only).

Strictly summarize rAF frame cadence, CDP Performance counters and Chromium
Tracing names/durations. Raw trace events can contain URLs, images or input:
never persist/print them. These reports are NOT production frame/GPU SLAs.
"""
from __future__ import annotations

import base64
import json
import math

CDP_COUNTERS = ("LayoutCount", "RecalcStyleCount", "LayoutDuration",
                "RecalcStyleDuration", "ScriptDuration", "TaskDuration")
COUNT_METRICS = {"LayoutCount", "RecalcStyleCount"}
TRACE_GROUPS = {
    "layout": {"Layout"},
    "style": {"RecalculateStyles", "UpdateLayoutTree"},
    "paint": {"Paint", "PrePaint"},
    "composite": {"CompositeLayers", "UpdateLayerTree"},
    "raster": {"RasterTask"},
}


def percentile(values, q):
    ordered = sorted(v for v in values if isinstance(v, (int, float)) and
                     math.isfinite(v) and v >= 0)
    if not ordered:
        return None
    return round(ordered[min(len(ordered)-1, int((len(ordered)-1)*q))], 3)


def summarize_raf_intervals(intervals):
    """rAF presentation cadence, not main-thread task latency or GPU time."""
    valid = [v for v in intervals if isinstance(v, (int, float)) and
             math.isfinite(v) and v > 0]
    return {
        "source": "requestAnimationFrame-presentation-cadence",
        "samples": len(valid),
        "frameGapP50Ms": percentile(valid, .50),
        "frameGapP95Ms": percentile(valid, .95),
        "frameGapMaxMs": round(max(valid), 3) if valid else None,
        "over16_7": sum(v > 16.7 for v in valid),
        "over33_3": sum(v > 33.3 for v in valid),
        "productionFrameSLA": False,
    }


def _numbers(payload):
    out = {}
    for entry in payload.get("metrics", []):
        name, number = entry.get("name"), entry.get("value")
        if name in CDP_COUNTERS and isinstance(number, (int, float)) and math.isfinite(number):
            out[name] = float(number)
    return out


def delta_performance_metrics(before, after):
    """CDP counters cover a test window, not individual frames.

    Missing counters are explicit None, never false zeros. Durations reported
    in seconds by CDP, here converted to milliseconds.
    """
    b, a = _numbers(before), _numbers(after)
    result = {}
    for name in CDP_COUNTERS:
        delta = a[name] - b[name] if name in a and name in b else None
        if delta is not None and delta < -1e-9:
            delta = None  # CDP clock reset cannot be interpreted as progress.
        result[name] = (round(delta, 3) if name in COUNT_METRICS else
                        round(delta*1000, 3)) if delta is not None else None
    result["durationUnit"] = "milliseconds"
    result["source"] = "Chromium-CDP-Performance-counters"
    return result


def summarize_trace_events(trace):
    """Keep only whitelisted event names/counts/summed durations.

    A missing Paint/Composite event is reported as unknown, NOT zero: Chrome
    versions may emit these on other processes, another renderer thread or
    only with different tracing categories. Nested durations may overlap;
    sums are *not* exclusive frame processing budgets.
    """
    events = trace.get("traceEvents", []) if isinstance(trace, dict) else []
    if not isinstance(events, list):
        raise ValueError("invalid chromium traceEvents")
    if len(events) > 400_000:
        raise ValueError("trace event cap exceeded")
    out = {}
    for group, names in TRACE_GROUPS.items():
        records = [e for e in events if isinstance(e, dict) and
                   e.get("name") in names and e.get("ph") == "X" and
                   isinstance(e.get("dur"), (int, float)) and
                   math.isfinite(e["dur"]) and e["dur"] >= 0]
        out[group] = {"observed": bool(records),
                      "count": len(records) if records else None,
                      "sumDurationMs": round(sum(e["dur"] for e in records)/1000, 3)
                      if records else None}
    return {"source": "Chromium-Tracing-complete-events",
            "rawTracePersisted": False,
            "eventCount": len(events),
            "groups": out,
            "exclusiveFrameBudget": False,
            "gpuFenceOrPresentTime": None,
            "productionFrameSLA": False}


def read_trace_from_stream(cdp, stream, max_bytes=30_000_000):
    """Read and immediately discard CDP tracing stream; never log raw bytes."""
    if not stream:
        raise ValueError("Chromium did not return a tracing stream")
    output, size = [], 0
    try:
        while True:
            result = cdp.send("IO.read", {"handle": stream, "size": 262_144})
            data = result.get("data", "")
            chunk = base64.b64decode(data) if result.get("base64Encoded") else data.encode("utf-8")
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("Chromium trace exceeds bounded in-memory limit")
            output.append(chunk)
            if result.get("eof"):
                break
        return json.loads(b"".join(output))
    finally:
        cdp.send("IO.close", {"handle": stream})
