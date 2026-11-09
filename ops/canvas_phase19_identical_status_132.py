"""#132 Phase19: only skip truly redundant save-label text assignments.

The test page preserves actual changes to save-state text, returns aggregate
counters and Chromium native style/layout events, and never changes shipped JS.
A-B-A-B-A on 1x/4x synthetic CPU is *diagnostic*, not device release evidence.
"""
from __future__ import annotations

from ops.canvas_phase12_isolation_111 import CPU_FACTORS
from ops.canvas_phase18_status_text_132 import _trial

ORDER=("observe","skip_identical","observe","skip_identical","observe")


def collect(page,cdp):
    observed={}
    for cpu in CPU_FACTORS:
        cdp.send("Emulation.setCPUThrottlingRate",{"rate":cpu})
        try:
            trials=[]
            for mode in ORDER:
                trial=_trial(page,cdp,mode)
                if mode=="skip_identical" and trial["visualLabelsPreserved"] is not True:
                    raise RuntimeError("Phase19 altered semantic save-status button labels")
                trials.append(trial)
            observed[str(cpu)+"x"]=trials
        finally:
            cdp.send("Emulation.setCPUThrottlingRate",{"rate":1})
    comparisons={}
    for cpu,trials in observed.items():
        records=[]
        for trial in trials:
            first=trial["windows"]["synthetic-move-1"]
            writes=first["saveButtonTextWrites"]
            records.append({
                "mode":trial["mode"],
                "largeUpdateEvents":first["largeUpdateEvents"],
                "maxElementCount":first["maxElementCount"],
                "added":first["structure"]["addedNodeCount"],
                "removed":first["structure"]["removedNodeCount"],
                "writes":sum(row["writes"] for row in writes.values()),
                "identicalWrites":sum(row["identical"] for row in writes.values()),
                "skippedWrites":sum(row["suppressed"] for row in writes.values()),
                "necessaryWrites":sum(row["writes"]-row["identical"] for row in writes.values()),
                "semanticLabelsPreserved":trial["visualLabelsPreserved"] is True,
                "graphUndoMediaVerified":trial["graphUndoMediaVerified"],
            })
        comparisons[cpu]=records
    return {
        "issue":132,"stage":19,"tracesByCpu":observed,
        "comparisonByCpu":comparisons,"order":list(ORDER),
        "skipsOnlyExactSameText":True,
        "necessarySaveStatusTextUpdatesStillApplied":True,
        "testOnlyInstrumentation":True,"realLowEndHardwareMeasured":False,
        "rootCauseUniquelyProven":False,"productionOptimizationAuthorized":False,
        "realProviderRequests":0,"privateDomTextPersisted":False,
        "rawTracePersisted":False,"decision":"NO-GO",
    }
