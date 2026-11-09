"""#111 Phase15: scoped CDP windows for individual *untrusted* Studio moves.

Tests-only: never modify shipped Studio CSS/JS, never persist raw traces,
private DOM text or pointer coordinates. Window adjacency ≠ root cause.
"""
from __future__ import annotations

from ops.canvas_frame_trace_111 import read_trace_from_stream
from ops.canvas_phase12_isolation_111 import (
    CPU_FACTORS, DRAG_TARGET, MAX_TRACE_BYTES, OBSERVE_DOM, VERIFY,
)
from ops.canvas_phase13_pointer_111 import STRUCTURE_OBSERVER
from ops.canvas_phase14_input_111 import POINTER_INPUT_HOOK
from ops.canvas_style_causality_111 import summarize_causality_window

WINDOWS = ("pre-input-idle", "synthetic-move-1",
           "synthetic-move-2", "synthetic-move-3")

# This is a diagnostic *barrier*, not an assertion that Chrome has already
# processed every descendant or every compositor/UA pseudo-class.
PRE_TRACE_READ = r"""() => {
  const layer=document.getElementById("ic-nodes-layer");
  const card=layer?.querySelector('[data-node-id="g00-0"]');
  if(!layer||!card)throw Error("missing real 300-node canvas");
  const box=card.getBoundingClientRect();
  const computed=getComputedStyle(card);
  return {
    connected:card.isConnected,
    finiteRect:[box.left,box.top,box.width,box.height]
      .every(Number.isFinite),
    hasComputedPosition:typeof computed.position==="string"
  };
}"""


def _bounded_summary(name, raw, attrs, structure):
    if name not in WINDOWS:
        raise ValueError("unknown phase15 trace window")
    summary=summarize_causality_window(raw)
    if summary["traceEventCount"] <= 0:
        raise RuntimeError("empty Chrome trace")
    update=summary["updateLayoutTree"]
    return {
        "window":name,
        "traceEventCount":summary["traceEventCount"],
        "largeUpdateEvents":update["largeEventsGE8000"],
        "maxElementCount":update["maxElementCount"],
        "invalidationEvents":summary["invalidationEvents"],
        "invalidationByName":summary["invalidationByName"],
        "reasonCategories":summary["reasonCategories"],
        "joinNearLargeUpdateByReason":
            summary["joinNearLargeUpdateByReason"],
        "attributeMutationTypes":attrs["byType"],
        "globalClassMutations":attrs["globalClassMutations"],
        "structure":structure,
        "causalAttributionConfirmed":False,
        "rawTracePersisted":False,
    }


def one_trial(page, cdp):
    """Trace four windows within one native pointerdown/synthetic-move drag."""
    cdp.send("Performance.enable")
    target=page.evaluate(DRAG_TARGET,"no-visual")
    page.mouse.move(target["x"],target["y"])
    mouse_down=False
    hook_installed=False
    observer_started=False
    structure_started=False
    tracing=False
    streams=[]
    cdp.on("Tracing.tracingComplete",
           lambda ev: streams.append(ev.get("stream")))
    windows={}
    try:
        page.evaluate(POINTER_INPUT_HOOK,{
            "op":"setup","driver":"synthetic"})
        hook_installed=True
        page.mouse.down()
        mouse_down=True
        page.wait_for_timeout(85)
        pre=page.evaluate(PRE_TRACE_READ)
        if not all(pre.values()):
            raise RuntimeError("pre-trace layout reading failed")
        page.wait_for_timeout(40)

        def capture(name, action):
            nonlocal observer_started, structure_started, tracing
            if name not in WINDOWS or name in windows:
                raise ValueError("unapproved/duplicate phase15 window")
            page.evaluate(OBSERVE_DOM,"start")
            observer_started=True
            page.evaluate(STRUCTURE_OBSERVER,"start")
            structure_started=True
            start_count=len(streams)
            cdp.send("Tracing.start",{
                "categories":
                    "devtools.timeline,disabled-by-default-devtools.timeline.invalidationTracking",
                "transferMode":"ReturnAsStream",
            })
            tracing=True
            attrs=None
            structure=None
            try:
                action()
                page.wait_for_timeout(75 if name!="pre-input-idle" else 90)
            finally:
                if tracing:
                    cdp.send("Tracing.end")
                    tracing=False
                if observer_started:
                    attrs=page.evaluate(OBSERVE_DOM,"stop")
                    observer_started=False
                if structure_started:
                    structure=page.evaluate(STRUCTURE_OBSERVER,"stop")
                    structure_started=False
            for _ in range(60):
                if len(streams)>start_count:
                    break
                page.wait_for_timeout(100)
            if len(streams)!=start_count+1 or not streams[-1]:
                raise RuntimeError("missing/ambiguous Chrome trace stream")
            raw=read_trace_from_stream(
                cdp,streams[-1],max_bytes=MAX_TRACE_BYTES)
            summary=_bounded_summary(name,raw,attrs,structure)
            del raw
            windows[name]=summary

        capture("pre-input-idle",lambda: None)

        def move(i):
            page.evaluate(POINTER_INPUT_HOOK,{
                "op":"dispatch",
                "x":target["x"]+i*20,
                "y":target["y"]+i*10,
            })

        for i in (1,2,3):
            capture(f"synthetic-move-{i}",lambda i=i:move(i))

        stats=page.evaluate(POINTER_INPUT_HOOK,"stats")
        if (stats["seenDown"],stats["synthetic"],stats["blocked"])!=(
            1,3,0):
            raise AssertionError("pointer IDs/events did not reach Studio")
        page.mouse.up()
        mouse_down=False
        state=page.evaluate(VERIFY)
        assert (state["cards"],state["edges"],state["images"])==(
            300,150,120),state
        assert state["decoded"] and state["paths"]>=150,state
        assert state["x"]>target["nodeX"] and (
            state["y"]>target["nodeY"]),state
        assert state["left"]==f'{state["x"]}px' and (
            state["top"]==f'{state["y"]}px'),state
        assert state["finish"] and (
            state["finish"]["targeted"] is False),state
        page.keyboard.press("Control+z")
        restored=page.evaluate("""() => {
          const n=window.CS.graph.nodes.find(x=>x.id==="g00-0");
          return {x:n.x,y:n.y};
        }""")
        assert restored=={
            "x":target["nodeX"],"y":target["nodeY"]},restored
        return {
            "windows":windows,
            "syntheticEventCount":stats["synthetic"],
            "syntheticEventsTrusted":False,
            "physicalMouseMovesDuringWindows":0,
            "nativeGraphAndMediaUndoStable":True,
            "preTraceReadPassed":True,
            "singlePointerDown":True,
            "rawTracePersisted":False,
        }
    finally:
        if tracing:
            try:cdp.send("Tracing.end")
            except Exception:pass
        if observer_started:
            try:page.evaluate(OBSERVE_DOM,"stop")
            except Exception:pass
        if structure_started:
            try:page.evaluate(STRUCTURE_OBSERVER,"stop")
            except Exception:pass
        if mouse_down:
            try:page.mouse.up()
            except Exception:pass
        if hook_installed:
            page.evaluate(POINTER_INPUT_HOOK,"restore")
        page.evaluate("""() => {
          const t=window.HANDRAW_STUDIO_TESTING;
          if(!t)throw Error("missing test controls after Phase15");
          t.canvasDragVisualProbeMode="normal";
          t.canvasDragFinishMode="auto";
        }""")


def collect(page, cdp):
    observed={}
    for cpu in CPU_FACTORS:
        cdp.send("Emulation.setCPUThrottlingRate",{"rate":cpu})
        try:
            observed[str(cpu)+"x"]=one_trial(page,cdp)
        finally:
            cdp.send("Emulation.setCPUThrottlingRate",{"rate":1})
    return {
        "issue":111,"stage":15,
        "windows":list(WINDOWS),
        "tracesByCpu":observed,
        "purpose":"temporal neighborhoods around first/later synthetic moves",
        "diagnosticOnly":True,
        "chromeAsyncLayoutMayCrossWindowBoundary":True,
        "rootCauseProven":False,
        "physicalLowEndDeviceTested":False,
        "productionCandidate":False,
        "realWorldInputCertified":False,
        "rawTracePersisted":False,
        "paidRequests":0,
        "issue132ProductionReleaseApproved":False,
    }
