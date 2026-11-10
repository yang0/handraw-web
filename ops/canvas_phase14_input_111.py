"""#111 Phase14: distinguish UA native pointer movement from Studio handler.

No production CSS/JS mutation. All hooks exist only in the test page.
Synthetic PointerEvent is explicitly untrusted; its result cannot certify
physical-device input, browser pointer capture, or release performance.
"""
from __future__ import annotations

from ops.canvas_phase12_isolation_111 import CPU_FACTORS

DRIVERS = ("native", "synthetic", "native-handler-blocked")
POINTER_INPUT_HOOK = r"""arg => {
  const op=typeof arg==="string"?arg:arg.op;
  const vp=document.getElementById("ic-viewport");
  if(!vp)throw Error("missing true Studio viewport");
  if(op==="setup"){
    if(!["synthetic","native-handler-blocked"].includes(arg.driver))
      throw Error("unexpected test input driver");
    if(window.__qa111phase14input)throw Error("stale phase14 listener");
    const s={id:null,driver:arg.driver,seenDown:0,synthetic:0,blocked:0,
      syntheticTrusted:false};
    s.onDown=e=>{s.id=e.pointerId;s.seenDown++};
    s.onMove=e=>{
      if(e.pointerId!==s.id)return;
      s.blocked++;
      e.stopImmediatePropagation();
    };
    vp.addEventListener("pointerdown",s.onDown,{capture:true});
    if(arg.driver==="native-handler-blocked")
      vp.addEventListener("pointermove",s.onMove,{capture:true});
    window.__qa111phase14input=s;
    return true;
  }
  const s=window.__qa111phase14input;
  if(op==="restore"){
    if(!s)return {restored:false};
    vp.removeEventListener("pointerdown",s.onDown,{capture:true});
    if(s.driver==="native-handler-blocked")
      vp.removeEventListener("pointermove",s.onMove,{capture:true});
    delete window.__qa111phase14input;
    return {restored:true};
  }
  if(!s||!Number.isInteger(s.id)||s.seenDown!==1)
    throw Error("missing actual native pointerdown before phase14 input");
  if(op==="dispatch"){
    if(s.driver!=="synthetic")throw Error("not synthetic driver");
    if(!Number.isFinite(arg.x)||!Number.isFinite(arg.y))
      throw Error("invalid synthetic coordinates");
    const event=new PointerEvent("pointermove",{
      bubbles:true,cancelable:true,pointerId:s.id,
      pointerType:"mouse",isPrimary:true,buttons:1,
      clientX:arg.x,clientY:arg.y
    });
    if(event.isTrusted)throw Error("synthetic event incorrectly trusted");
    vp.dispatchEvent(event);
    s.synthetic++;
  }else if(op!=="stats")throw Error("unknown phase14 input op");
  return {seenDown:s.seenDown,synthetic:s.synthetic,blocked:s.blocked,
          syntheticTrusted:false,driver:s.driver};
}"""


def _reduce_trace(row):
    chrome=row["chrome"]
    update=chrome["updateLayoutTree"]
    return {
        "driver":row["eventDriver"],
        "physicalMouseMoves":row["physicalMouseMoves"],
        "syntheticEvents":row["syntheticEvents"],
        "blockedNativeEvents":row["blockedNativeEvents"],
        "largeUpdateEvents":update["largeEventsGE8000"],
        "maxElementCount":update["maxElementCount"],
        "invalidationEvents":chrome["invalidationEvents"],
        "joinNearLargeByReason":chrome["joinNearLargeUpdateByReason"],
        "domMutationTypes":row["domMutations"]["byType"],
        "structureChanges":row["structureChanges"],
        "nativeGraphAndMediaStable":row["nativeGraphAndMediaStable"],
    }


def collect(page, cdp):
    # Exactly 6 bounded native-Chrome traces. CPU rates are simulated, not
    # independent physical devices; no production benefit can be inferred.
    cdp.send("Performance.enable")
    observations={}
    for cpu in CPU_FACTORS:
        cdp.send("Emulation.setCPUThrottlingRate",{"rate":cpu})
        try:
            per_driver={}
            for driver in DRIVERS:
                # import locally: Phase13 imports our test-only hook.
                from ops.canvas_phase13_pointer_111 import one_window
                result=one_window(
                    page,cdp,"drag-no-visual",driver=driver,trace=True)
                per_driver[driver]=_reduce_trace(result)
                if not per_driver[driver]["nativeGraphAndMediaStable"]:
                    raise RuntimeError("Phase14 native Graph/media assertion failed")
            observations[str(cpu)+"x"]=per_driver
        finally:
            cdp.send("Emulation.setCPUThrottlingRate",{"rate":1})
    return {
        "issue":111,"stage":14,"diagnosticOnly":True,
        "purpose":"native UA pointer movement vs Studio pointer handler",
        "sampleScope":"same Chromium HTTP/SQLite Studio 300/150/120",
        "traces":observations,
        "scriptedEventsAreTrusted":False,
        "nativeInputCertification":False,
        "physicalLowEndDeviceTested":False,
        "productionCandidate":False,
        "rawTracePersisted":False,
        "paidRequests":0,
        "issue132ProductionReleaseApproved":False,
    }
