"""#132 Phase18: test-only save-status button text assignment isolation.

This deliberately permits a temporary stale button label in the *test page*.
It does not modify shipped CSS/JS or certify UI behavior or performance gains.
The native Node.textContent setter is restored unconditionally after each trial.
Only fixed role counters and bounded CDP layout aggregate statistics leave Chrome.
"""
from __future__ import annotations

from ops.canvas_phase12_isolation_111 import CPU_FACTORS
from ops.canvas_phase15_move_boundary_111 import one_trial

MODES=("observe","suppress")
ORDER=("observe","suppress","observe","suppress","observe")
MOVE_WINDOWS=("pre-input-idle","synthetic-move-1","synthetic-move-2","synthetic-move-3")
ROLES=("bottom-save-button","entry-save-button")

HOOK_JS=r"""arg=>{
  const op=typeof arg==="string"?arg:arg.op;
  if(op==="stop"){
    const s=window.__qa132saveText;
    if(!s)throw Error("Phase18 save-text hook missing");
    try{
      Object.defineProperty(Node.prototype,"textContent",s.originalDescriptor);
      window.removeEventListener("pointermove",s.onPointerMove,true);
      delete window.__qa132saveText;
    }catch(e){
      // Restore from a complete descriptor, never leave a partial test patch.
      Object.defineProperty(Node.prototype,"textContent",s.originalDescriptor);
      window.removeEventListener("pointermove",s.onPointerMove,true);
      delete window.__qa132saveText;
      throw e;
    }
    return {mode:s.mode,seenMoveCount:s.moveIndex,
      targetPresence:s.targetPresence,writesByWindow:s.writesByWindow,
      restored:true,noTextOrIdsPersisted:true};
  }
  if(op!=="start"||window.__HANDRAW_TESTING__!==true||
     !["observe","suppress"].includes(arg.mode)||window.__qa132saveText)
    throw Error("Phase18 only runs on a real Studio test canvas");
  const bottom=document.getElementById("bl-save-project");
  const entry=document.getElementById("studio-project-status");
  if(!bottom||!entry||bottom===entry||
     bottom.localName!=="button"||entry.localName!=="button")
    throw Error("Phase18 cannot identify two distinct save-status buttons");
  const desc=Object.getOwnPropertyDescriptor(Node.prototype,"textContent");
  if(!desc||!desc.configurable||typeof desc.set!=="function"||
     typeof desc.get!=="function")
    throw Error("Phase18 native textContent descriptor not patchable");
  const targets=new Map([[bottom,"bottom-save-button"],[entry,"entry-save-button"]]);
  const bucket=()=>({
    "bottom-save-button":{writes:0,suppressed:0,identical:0},
    "entry-save-button":{writes:0,suppressed:0,identical:0}
  });
  const counts={
    "pre-input-idle":bucket(),"synthetic-move-1":bucket(),
    "synthetic-move-2":bucket(),"synthetic-move-3":bucket()
  };
  const s={mode:arg.mode,originalDescriptor:desc,targetPresence:2,
    moveIndex:0,writesByWindow:counts,onPointerMove:null};
  s.onPointerMove=ev=>{
    if(!ev.isTrusted&&ev.type==="pointermove")
      s.moveIndex=Math.min(s.moveIndex+1,3);
  };
  const set=function(value){
    const role=targets.get(this);
    if(!role)return desc.set.call(this,value);
    const phase=s.moveIndex===0?"pre-input-idle":"synthetic-move-"+s.moveIndex;
    const slot=counts[phase][role];
    slot.writes++;
    if(slot.writes>100)throw Error("Phase18 target write cap exceeded");
    // Equality is computed in page memory only; neither text is emitted.
    if(desc.get.call(this)===String(value))slot.identical++;
    if(s.mode==="suppress"&&s.moveIndex>=1){
      slot.suppressed++;
      return;
    }
    return desc.set.call(this,value);
  };
  try{
    Object.defineProperty(Node.prototype,"textContent",{
      configurable:desc.configurable,enumerable:desc.enumerable,
      get:desc.get,set
    });
    window.addEventListener("pointermove",s.onPointerMove,true);
    window.__qa132saveText=s;
  }catch(e){
    Object.defineProperty(Node.prototype,"textContent",desc);
    window.removeEventListener("pointermove",s.onPointerMove,true);
    throw e;
  }
  return {installed:true,targetPresence:2};
}"""


def validate(mode, payload):
    if mode not in MODES or not isinstance(payload,dict):
        raise ValueError("unsupported Phase18 test-only mode")
    if (payload.get("mode")!=mode or payload.get("targetPresence")!=2
        or payload.get("seenMoveCount")!=3 or payload.get("restored") is not True
        or payload.get("noTextOrIdsPersisted") is not True):
        raise ValueError("Phase18 save-text hook restoration/input not proven")
    windows=payload.get("writesByWindow")
    if not isinstance(windows,dict) or set(windows)!=set(MOVE_WINDOWS):
        raise ValueError("Phase18 missing input windows")
    for name,targets in windows.items():
        if not isinstance(targets,dict) or set(targets)!=set(ROLES):
            raise ValueError("Phase18 leaked unexpected element role")
        for row in targets.values():
            if not isinstance(row,dict) or set(row)!={"writes","suppressed","identical"}:
                raise ValueError("Phase18 unexpected counter fields")
            if any(type(v) is not int or not 0<=v<=100 for v in row.values()):
                raise ValueError("Phase18 invalid/unbounded write count")
            if row["suppressed"]>row["writes"] or row["identical"]>row["writes"]:
                raise ValueError("Phase18 impossible counts")
            if mode=="observe" and row["suppressed"]:
                raise ValueError("Phase18 control unexpectedly suppressed writes")
            if mode=="suppress" and name.startswith("synthetic-move-") and (
                    row["suppressed"]!=row["writes"]):
                raise ValueError("Phase18 intervention failed to suppress target writes")
    return windows


def _trial(page,cdp,mode):
    installed=page.evaluate(HOOK_JS,{"op":"start","mode":mode})
    if installed!={"installed":True,"targetPresence":2}:
        raise RuntimeError("Phase18 save-text hook did not install")
    try:
        result=one_trial(page,cdp)
    finally:
        # Unconditional restore: never leak test-only suppression to later tests.
        report=page.evaluate(HOOK_JS,"stop")
    windows=validate(mode,report)
    if not result["nativeGraphAndMediaUndoStable"]:
        raise RuntimeError("Phase18 Graph/Undo/decoded media invariant failure")
    samples={}
    for key in MOVE_WINDOWS:
        trace=result["windows"][key]
        structure=trace["structure"]
        samples[key]={
            "largeUpdateEvents":trace["largeUpdateEvents"],
            "maxElementCount":trace["maxElementCount"],
            "structure":{
                "childListRecords":structure["childListRecords"],
                "addedNodeCount":structure["addedNodeCount"],
                "removedNodeCount":structure["removedNodeCount"],
            },
            "saveButtonTextWrites":windows[key],
        }
    return {"mode":mode,"windows":samples,"restored":True,
            "graphUndoMediaVerified":True}


def collect(page,cdp):
    observed={}
    for cpu in CPU_FACTORS:
        cdp.send("Emulation.setCPUThrottlingRate",{"rate":cpu})
        try:
            trials=[]
            for mode in ORDER:
                trials.append(_trial(page,cdp,mode))
            observed[str(cpu)+"x"]=trials
        finally:
            cdp.send("Emulation.setCPUThrottlingRate",{"rate":1})
    # This is a structured, inconclusive comparison until an independent
    # physical-device, unmodified-visual validation and release review.
    summaries={}
    for cpu,trials in observed.items():
        first=[t["windows"]["synthetic-move-1"] for t in trials]
        summaries[cpu]={
            "baselineLargeEvents":[x["largeUpdateEvents"] for t,x in zip(trials,first)
                                  if t["mode"]=="observe"],
            "suppressedLargeEvents":[x["largeUpdateEvents"] for t,x in zip(trials,first)
                                    if t["mode"]=="suppress"],
            "baselineAddedNodes":[x["structure"]["addedNodeCount"] for t,x
                                  in zip(trials,first) if t["mode"]=="observe"],
            "suppressedAddedNodes":[x["structure"]["addedNodeCount"] for t,x
                                    in zip(trials,first) if t["mode"]=="suppress"],
            "baselineMaxElements":[x["maxElementCount"] for t,x in zip(trials,first)
                                  if t["mode"]=="observe"],
            "suppressedMaxElements":[x["maxElementCount"] for t,x in zip(trials,first)
                                    if t["mode"]=="suppress"],
        }
    return {
        "issue":132,"stage":18,"order":list(ORDER),
        "tracesByCpu":observed,"comparisonByCpu":summaries,
        "testOnlyVisualLabelsTemporarilySuppressed":True,
        "syntheticCpuOnly":True,"rootCauseUniquelyProven":False,
        "productionChangeAuthorized":False,"realProviderRequests":0,
        "realDeviceEvidence":False,"rawTracesPersisted":False,
        "privateDomTextPersisted":False,"decision":"NO-GO",
    }
