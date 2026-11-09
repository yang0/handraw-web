"""#111 Phase 12: isolated 300-card Studio HTTP Chrome, no paid requests.

Reuse the exact Stage 10 local HTTP/SQLite/native fixture, 120 distinct
decoded WebPs and strict no-vendor assertion. No production code is modified.
"""
from __future__ import annotations

import json
from pathlib import Path

import benchmark_studio_tree_style_111 as stage10
from ops.canvas_phase12_isolation_111 import collect
from ops.canvas_phase13_pointer_111 import collect as collect_phase13
from ops.canvas_phase14_input_111 import collect as collect_phase14

ROOT=Path(__file__).resolve().parents[1]


def main():
    original_trace=stage10.trace_tree_affected
    original_cases=stage10.CASES
    captured=False

    def run_phase12(page,cdp,mode):
        nonlocal captured
        if mode=="baseline" and not captured:
            captured=True
            warmup=stage10.profile_drag(page,cdp,cpu_factor=1)
            assert warmup["graphUndoAndMediaStable"]
            page.wait_for_selector("[data-float-topbar]",timeout=5000)
            result=collect(page,cdp)
            # Reuse the already-loaded 300-node project and Chrome context.
            # Phase 13 is a separate post-Phase12 browser experiment: isolate
            # hover/pointer-induced residual UpdateLayoutTree in no-visual mode.
            phase13=collect_phase13(page,cdp)
            folder13=ROOT/"artifacts/studio-111-phase13"
            folder13.mkdir(parents=True,exist_ok=True)
            (folder13/"summary.json").write_text(
                json.dumps(phase13,indent=2,ensure_ascii=False)+"\n",
                encoding="utf-8")
            print("CANVAS #111 PHASE13 "+json.dumps({
                "windows":{name:{
                    "large":row["largeUpdateEvents"],
                    "maximum":row["maxElementCount"],
                    "mutations":row["actualDomMutationCounts"],
                    "globalClasses":row["globalClassMutations"],
                } for name,row in phase13["conditions"].items()},
                "hoverMaskVsNoVisual":phase13["hoverMaskVsNoVisual"]["gate"],
                "safeProductionCandidate":False,
                "paidRequests":0,
            },ensure_ascii=False),flush=True)
            phase14=collect_phase14(page,cdp)
            folder14=ROOT/"artifacts/studio-111-phase14"
            folder14.mkdir(parents=True,exist_ok=True)
            (folder14/"summary.json").write_text(
                json.dumps(phase14,indent=2,ensure_ascii=False)+"\n",
                encoding="utf-8")
            print("CANVAS #111 PHASE14 "+json.dumps({
                "windows":{cpu:{
                    driver:{
                        "large":row["largeUpdateEvents"],
                        "maximum":row["maxElementCount"],
                        "syntheticEvents":row["syntheticEvents"],
                        "blockedNativeEvents":row["blockedNativeEvents"],
                        "domMutationTypes":row["domMutationTypes"],
                    }
                    for driver,row in v.items()}
                    for cpu,v in phase14["traces"].items()},
                "productionCandidate":False,
                "physicalDeviceEvidence":False,
                "paidRequests":0
            },ensure_ascii=False),flush=True)
            summary=result["traceModes"]
            print("CANVAS #111 PHASE12 "+json.dumps({
                "traceModes":{name:{
                  "maxLayoutElements":row["styleUpdate"].get(
                      "updateLayoutTree",{}).get("maxElementCount"),
                  "largeUpdates":row["styleUpdate"].get(
                      "updateLayoutTree",{}).get("largeEventsGE8000"),
                  "domMutations":row["domMutations"]["byType"],
                  "globalClassMutations":row["domMutations"]["globalClassMutations"]
                } for name,row in summary.items()},
                "cases":[{"name":c["case"],
                  "gate":c["gate"],
                  "productionCandidate":c["productionCandidate"]}
                  for c in result["cases"]],
                "paidRequests":0,"productionNoGo":True,
            },ensure_ascii=False),flush=True)
            out=ROOT/"artifacts/studio-111-phase12"
            out.mkdir(parents=True,exist_ok=True)
            (out/"summary.json").write_text(json.dumps(result,indent=2,
                ensure_ascii=False)+"\n",encoding="utf-8")
        return original_trace(page,cdp,mode)

    # Stage 10's own mandatory workflow step independently runs every
    # containment/selector A/B. Avoid duplicate expensive loops here.
    stage10.CASES=()
    stage10.trace_tree_affected=run_phase12
    try:
        stage10.main()
    finally:
        stage10.CASES=original_cases
        stage10.trace_tree_affected=original_trace
    assert captured,"Phase12 native browser hook never executed"


if __name__=="__main__":
    main()
