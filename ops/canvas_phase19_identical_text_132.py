"""#132 Phase19: visual-preserving, test-only identical status-text write guard.

Two known Studio project-save button targets; native changed text is NEVER
suppressed. Long contiguous Chrome trace covers all 3 untrusted pointer moves.
No production CSS/JS, private text, original trace, or paid vendor calls.
"""
from __future__ import annotations

from ops.canvas_phase12_isolation_111 import CPU_FACTORS
from ops.canvas_phase13_pointer_111 import one_window
from ops.canvas_phase18_status_text_132 import HOOK_JS, ROLES, validate

ORDER=("observe","skip-identical","observe","skip-identical","observe")

def _trial(page, cdp, mode):
    if mode not in ("observe", "skip-identical"):
        raise ValueError("unapproved Phase19 long-trace experiment")
    installed=page.evaluate(HOOK_JS, {"op":"start","mode":mode})
    if installed!={"installed":True,"targetPresence":2}:
        raise RuntimeError("Phase19 did not find both real save buttons")
    try:
        result=one_window(
            page, cdp, "drag-no-visual", trace=True, driver="synthetic",
        )
    finally:
        # Restore native setter even if the real Chrome trace fails.
        report=page.evaluate(HOOK_JS, "stop")
    windows=validate(mode,report)
    if not result["nativeGraphAndMediaStable"] or result["syntheticEvents"]!=3:
        raise RuntimeError("Phase19 real Studio Graph/Undo/media/input invariant failed")
    update=result["chrome"]["updateLayoutTree"]
    structure=result["structureChanges"]
    first=windows["synthetic-move-1"]
    totals={role:{
        "writes":sum(windows[phase][role]["writes"]
                     for phase in ("synthetic-move-1","synthetic-move-2","synthetic-move-3")),
        "identical":sum(windows[phase][role]["identical"]
                        for phase in ("synthetic-move-1","synthetic-move-2","synthetic-move-3")),
        "skipped":sum(windows[phase][role]["suppressed"]
                      for phase in ("synthetic-move-1","synthetic-move-2","synthetic-move-3")),
        "firstMoveWrites":first[role]["writes"],
        "firstMoveIdentical":first[role]["identical"],
        "firstMoveSkipped":first[role]["suppressed"],
    } for role in ROLES}
    return {
        "mode":mode,
        "largeUpdateEvents":update["largeEventsGE8000"],
        "maxElementCount":update["maxElementCount"],
        "childListRecords":structure["childListRecords"],
        "addedNodeCount":structure["addedNodeCount"],
        "removedNodeCount":structure["removedNodeCount"],
        "targets":totals,
        "nativeGraphUndoAndMediaStable":True,
        "originalSetterRestored":report["restored"],
        "traceWindow":"continuous-3-untrusted-moves",
    }


def summarize(trials_by_cpu):
    if set(trials_by_cpu)!={"1x","4x"}:
        raise ValueError("Phase19 requires 1x/4x CPU evidence")
    result={}
    for cpu,rows in trials_by_cpu.items():
        if len(rows)!=5 or [r["mode"] for r in rows]!=list(ORDER):
            raise ValueError("Phase19 A-B-A-B-A sequence incomplete")
        control=[r for r in rows if r["mode"]=="observe"]
        variant=[r for r in rows if r["mode"]=="skip-identical"]
        for row in rows:
            if (not row["nativeGraphUndoAndMediaStable"] or
                not row["originalSetterRestored"] or
                row["traceWindow"]!="continuous-3-untrusted-moves"):
                raise ValueError("Phase19 invalid Chrome or restoration evidence")
            if set(row["targets"])!=set(ROLES):
                raise ValueError("Phase19 wrong fixed target roles")
        writes_seen=all(all(r["targets"][role]["firstMoveWrites"]>=1
                            for role in ROLES) for r in rows)
        # Native changed visual status must never be suppressed.
        skip_safe=all(all(
            r["targets"][role]["skipped"]==r["targets"][role]["identical"]
            for role in ROLES) for r in variant)
        a_repro=all(r["largeUpdateEvents"]>=1 for r in control)
        b_absent=all(r["largeUpdateEvents"]==0 for r in variant)
        result[cpu]={
            "baselineLargeEvents":[r["largeUpdateEvents"] for r in control],
            "skipIdenticalLargeEvents":[r["largeUpdateEvents"] for r in variant],
            "baselineMaxElements":[r["maxElementCount"] for r in control],
            "skipIdenticalMaxElements":[r["maxElementCount"] for r in variant],
            "baselineAddedNodes":[r["addedNodeCount"] for r in control],
            "skipIdenticalAddedNodes":[r["addedNodeCount"] for r in variant],
            "realButtonWritesSeenInAllTrials":writes_seen,
            "skippedOnlyIdenticalText":skip_safe,
            "controlLargeUpdateReproducedAllThree":a_repro,
            "variantNoLargeUpdateBoth":b_absent,
            "syntheticControlledSignal":writes_seen and skip_safe and a_repro and b_absent,
        }
    return result


def collect(page,cdp):
    observations={}
    for cpu in CPU_FACTORS:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate":cpu})
        try:
            trials=[]
            for mode in ORDER:
                trials.append(_trial(page,cdp,mode))
            observations[str(cpu)+"x"]=trials
        finally:
            cdp.send("Emulation.setCPUThrottlingRate", {"rate":1})
    comparisons=summarize(observations)
    signal=all(row["syntheticControlledSignal"] for row in comparisons.values())
    return {
        "issue":132,"stage":19,
        "comparisonByCpu":comparisons,"tracesByCpu":observations,
        "dualCpuControlledSignalObserved":signal,
        "syntheticCpuOnly":True,
        "nativeChangedButtonTextNeverSuppressedByTest":True,
        "productionVisualEquivalenceIndependentlyProven":False,
        "physicalLowEndDeviceTested":False,
        "rootCauseUniquelyProven":False,
        "productionChangeAuthorized":False,
        "realProviderRequests":0,
        "privateTextPersisted":False,
        "rawTracePersisted":False,
        "decision":"NO-GO",
    }
