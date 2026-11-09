"""Phase 12 #111: controlled physical drag isolation, never production behavior.

Use existing __HANDRAW_TESTING__-guarded native drag modes in studio-app.js.
All visual bypasses and global-state selector masking are diagnostic ONLY.
No raw trace, element ID, CSS text, image, URL or user data is persisted.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter

from ops.canvas_frame_trace_111 import (
    delta_performance_metrics, summarize_raf_intervals, read_trace_from_stream,
)
from ops.canvas_style_causality_111 import summarize_causality_window

CPU_FACTORS = (1, 4)
CASES = ("no-edges", "no-card", "global-state-selector-mask", "no-overlay", "no-visual")
MIN_IMPROVEMENT = 0.10
TRACE_MODES = ("normal", "no-edges", "no-card", "global-state-selector-mask", "no-visual")
MAX_TRACE_BYTES = 30_000_000

# Only explicitly known, local, dynamic ancestor rules may be disabled.
# Full CSSOM selectors, including private runtime additions, are never saved.
CSSOM_MASK = r"""mode=>{
  const p=window.__qa111phase12||(window.__qa111phase12={changes:[]});
  for(const [r,text] of p.changes){
    r.selectorText=text;
    if(r.selectorText!==text)throw Error("CSSOM restore failure");
  }
  p.changes=[];
  if(mode!=="global-state-selector-mask")
    return {patched:0,knownMatchedBefore:0};
  const allow=new Set([
    '.ic-viewport.is-panning',
    '.ic-studio-shell.is-wiring .ic-port-zone',
    '.ic-studio-shell.edges-hidden .ic-edge-group:not(.is-related):not(.is-selected) .ic-edge-line'
  ]);
  let patched=0,matched=0;
  const visit=rules=>{
    for(const rule of rules){
      if(rule.cssRules)try{visit(rule.cssRules)}catch(_){}
      if(typeof rule.selectorText!=="string")continue;
      const fragments=rule.selectorText.split(",");
      if(!fragments.some(x=>allow.has(x.trim())))continue;
      const revised=fragments.map(x=>{
        const sel=x.trim();if(!allow.has(sel))return sel;
        try{matched+=document.querySelectorAll(sel).length}catch(_){}
        return ":root:not(:root)";
      }).join(", ");
      const before=rule.selectorText;
      rule.selectorText=revised;
      if(rule.selectorText===revised){p.changes.push([rule,before]);patched++}
    }
  };
  for(const sheet of document.styleSheets)try{visit(sheet.cssRules)}catch(_){}
  return {patched,knownMatchedBefore:matched};
}"""

# By design: only enumerated ATTR NAMES and ELEMENT ROLES. Never persist values.
OBSERVE_DOM = r"""mode=>{
  if(mode==="stop"){
    const p=window.__qa111phase12observer;
    if(!p)throw Error("observer not started");
    p.obs.takeRecords().forEach(p.process);
    p.obs.disconnect();
    return {count:p.count,overflows:p.overflow,byType:p.byType,
            globalClassMutations:p.globalClassMutations,
            globalAttributeMutations:p.globalAttributeMutations};
  }
  if(mode!=="start")throw Error("unknown observer action");
  const tracked=new Set(["style","class","d","transform"]);
  const global=new Set([
    "ic-studio-shell","ic-canvas-stage","ic-viewport","ic-world",
    "ic-nodes-layer","ic-edges-svg"
  ]);
  const classRole=e=>{
    if(e.closest("#ic-edges-svg path"))return "svg-path";
    if(e.matches("[data-float-topbar]"))return "floating-toolbar";
    if(e.closest("#ic-nodes-layer .ic-node"))return "node";
    if(e.closest("#ic-minimap"))return "minimap";
    if(e.id==="ic-edges-svg")return "svg-root";
    if(e.id==="ic-nodes-layer")return "node-layer";
    if(e.id==="ic-world")return "world";
    if(e.id==="ic-viewport")return "viewport";
    if(e.classList.contains("ic-canvas-stage"))return "canvas-stage";
    if(e.classList.contains("ic-studio-shell"))return "studio-shell";
    if(e.id==="ic-overlay-layer")return "overlay-layer";
    return "other";
  };
  const p={count:0,overflow:0,byType:{},globalClassMutations:0,
           globalAttributeMutations:0,obs:null};
  p.process=m=>{
    if(!tracked.has(m.attributeName))return;
    if(p.count>=5000){p.overflow++;return}
    p.count++;
    const role=classRole(m.target);
    const key=role+"."+m.attributeName;
    p.byType[key]=(p.byType[key]||0)+1;
    if(["studio-shell","canvas-stage","viewport","world","node-layer","svg-root"].includes(role)){
      p.globalAttributeMutations++;
      if(m.attributeName==="class")p.globalClassMutations++;
    }
  };
  p.obs=new MutationObserver(rows=>rows.forEach(p.process));
  p.obs.observe(document.body,{subtree:true,attributes:true,
       attributeFilter:["class","style","d","transform"]});
  window.__qa111phase12observer=p;
  return true;
}"""

# A/B always uses real input and actual stage graph; no synthetic workload.
DRAG_TARGET = r"""mode=>{
  if(window.__HANDRAW_TESTING__!==true||!window.HANDRAW_STUDIO_TESTING)
    throw Error("Stage12 requires native test flag");
  const testing=window.HANDRAW_STUDIO_TESTING;
  testing.canvasDragVisualProbeMode=
    ["no-edges","no-card","no-overlay","no-visual"].includes(mode)?mode:"normal";
  testing.canvasDragFinishMode="full";
  testing.focusCanvasNodeForBenchmark("g00-0");
  const node=document.querySelector('#ic-nodes-layer [data-node-id="g00-0"]');
  const head=node?.querySelector(".ic-node-header-above");
  const model=window.CS.graph.nodes.find(x=>x.id==="g00-0");
  if(!head||!model)throw Error("missing graph drag target");
  const r=head.getBoundingClientRect();
  for(const f of [.15,.45,.7]){
    const x=r.left+r.width*f,y=r.top+r.height*.5;
    if(document.elementFromPoint(x,y)?.closest(".ic-node")===node)
      return {x,y,nodeX:model.x,nodeY:model.y};
  }
  throw Error("native node header not physically reachable");
}"""

FRAMES = r"""mode=>{
  if(mode==="stop"){
    const p=window.__qa111phase12frames;
    if(!p)throw Error("no rAF probe");
    p.active=false;return p.intervals.slice();
  }
  const p={active:true,last:null,intervals:[]};
  window.__qa111phase12frames=p;
  function frame(ts){
    if(!p.active)return;
    if(p.last!==null&&p.intervals.length<120)p.intervals.push(ts-p.last);
    p.last=ts;requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);return true;
}"""

VERIFY = r"""() => {
  const n=window.CS.graph.nodes.find(x=>x.id==="g00-0");
  const layer=document.getElementById("ic-nodes-layer");
  const node=layer.querySelector('[data-node-id="g00-0"]');
  const images=[...layer.querySelectorAll("img")];
  return {
    x:n.x,y:n.y,left:node.style.left,top:node.style.top,
    cards:layer.querySelectorAll(".ic-node").length,
    edges:document.querySelectorAll("#ic-edges-svg g.ic-edge-group[data-edge-id]").length,
    paths:document.querySelectorAll("#ic-edges-svg path[d]").length,
    images:images.length,decoded:images.every(e=>e.complete&&e.naturalWidth>0),
    testedModes:[...new Set((layer._drag111Samples||[]).map(x=>x.visualProbeMode))],
    finish:layer._drag111Finish
  };
}"""


def _metrics(before, after, frames):
    delta=delta_performance_metrics(before, after)
    raf=summarize_raf_intervals(frames)
    style=delta.get("RecalcStyleDuration")
    layout=delta.get("LayoutDuration")
    p95=raf.get("frameGapP95Ms")
    assert all(isinstance(v,(int,float)) and v>=0 for v in (style,layout,p95)),(delta,raf)
    return {"styleMs":round(style,3),"layoutMs":round(layout,3),
            "combinedMs":round(style+layout,3),"rafP95Ms":p95}


def physical_trial(page, cdp, mode, cpu, *, trace=False):
    """Trace ends before pointerup/full reconciliation, CDP measured drag only."""
    masking=page.evaluate(CSSOM_MASK,mode)
    try:
        target=page.evaluate(DRAG_TARGET,mode)
        page.mouse.move(target["x"],target["y"])
        page.mouse.down()
        page.wait_for_timeout(80)
        page.evaluate(OBSERVE_DOM,"start")
        page.evaluate(FRAMES,"start")
        before=cdp.send("Performance.getMetrics")
        streams=[]
        if trace:
            cdp.on("Tracing.tracingComplete",
                   lambda ev:streams.append(ev.get("stream")))
            cdp.send("Tracing.start",{
                "categories":"devtools.timeline,disabled-by-default-devtools.timeline.invalidationTracking",
                "transferMode":"ReturnAsStream"})
        moves=3 if trace else 12
        try:
            for k in range(1,moves+1):
                page.mouse.move(target["x"]+60*k/moves,
                                target["y"]+30*k/moves,steps=1)
                page.wait_for_timeout(20 if not trace else 30)
            if trace:page.wait_for_timeout(40)
            after=cdp.send("Performance.getMetrics")
            frames=page.evaluate(FRAMES,"stop")
        finally:
            if trace:cdp.send("Tracing.end")
            dom=page.evaluate(OBSERVE_DOM,"stop")
            page.mouse.up()
        summary=None
        if trace:
            for _ in range(60):
                if streams:break
                page.wait_for_timeout(100)
            try:
                if not streams or not streams[-1]:raise ValueError("no trace stream")
                raw=read_trace_from_stream(cdp,streams[-1],
                                           max_bytes=MAX_TRACE_BYTES)
                summary=summarize_causality_window(raw)
                summary["available"]=True
            except (ValueError, KeyError, TypeError):
                summary={"available":False,
                         "rootCauseProven":False,"rawTracePersisted":False}
        # Complete authoritative rendering after diagnostic suppression.
        state=page.evaluate(VERIFY)
        assert state["x"]>target["nodeX"] and state["y"]>target["nodeY"],(mode,state)
        assert (state["cards"],state["edges"],state["images"])==(300,150,120),(mode,state)
        assert state["left"]==f'{state["x"]}px' and state["top"]==f'{state["y"]}px',(mode,state)
        assert state["decoded"] and state["paths"]>=150,(mode,state)
        assert state["finish"] and state["finish"]["targeted"] is False,(mode,state)
        expected=mode if mode in ("no-edges","no-card","no-overlay","no-visual") else "normal"
        assert state["testedModes"]==[expected],(mode,state["testedModes"])
        page.keyboard.press("Control+z")
        undo=page.evaluate("""() => {
          const n=window.CS.graph.nodes.find(x=>x.id==="g00-0");
          return {x:n.x,y:n.y};
        }""")
        assert undo=={"x":target["nodeX"],"y":target["nodeY"]},(mode,undo,target)
        return {"case":mode,"cpu":cpu,"moves":moves,
                "cdp":_metrics(before,after,frames),
                "domMutationCounts":dom,
                "selectorMask":masking,"trace":summary,
                "undoAndMediaStable":True}
    finally:
        page.evaluate(CSSOM_MASK,"normal")
        page.evaluate("""() => {
          const t=window.HANDRAW_STUDIO_TESTING;
          t.canvasDragVisualProbeMode="normal";t.canvasDragFinishMode="auto";
        }""")


def gate(records,case):
    result={}
    for cpu in CPU_FACTORS:
        rows=[r["cdp"] for r in records if r["cpu"]==cpu]
        assert len(rows)==5, (case,cpu,len(rows))
        baseline=rows[::2];candidate=rows[1::2]
        a_style=statistics.median(r["styleMs"] for r in baseline)
        a_total=statistics.median(r["combinedMs"] for r in baseline)
        a_raf=statistics.median(r["rafP95Ms"] for r in baseline)
        passed=(a_style>0 and a_total>0 and a_raf>0 and
                all(r["styleMs"]<=a_style*.90 and
                    r["combinedMs"]<=a_total*.90 and
                    r["rafP95Ms"]<=a_raf*1.05 for r in candidate))
        result[f"{cpu}x"]={
            "baselineStyleMedianMs":round(a_style,3),
            "candidateStyleMs":[r["styleMs"] for r in candidate],
            "baselineCombinedMedianMs":round(a_total,3),
            "candidateCombinedMs":[r["combinedMs"] for r in candidate],
            "baselineRafP95Ms":round(a_raf,2),
            "candidateRafP95Ms":[r["rafP95Ms"] for r in candidate],
            "bothReplicatesPass":bool(passed)}
    return {"case":case, "gate":result,
            "bothCpuBenefitObserved":all(v["bothReplicatesPass"] for v in result.values()),
            "diagnosticOnly":True,"productionCandidate":False,
            "visualBehaviorChangedOrUnproven":True}


def collect(page,cdp):
    cdp.send("Performance.enable")
    page.evaluate("""() => {
      const t=window.HANDRAW_STUDIO_TESTING;
      if(window.__HANDRAW_TESTING__!==true||!t)throw Error("missing native QA");
      t.canvasDragVisualProbeMode="normal";t.canvasDragFinishMode="auto";
    }""")
    evidence={}
    for mode in TRACE_MODES:
        trial=physical_trial(page,cdp,mode,1,trace=True)
        evidence[mode]={"styleUpdate":trial["trace"],
                        "domMutations":trial["domMutationCounts"],
                        "cssMask":trial["selectorMask"]}
    cases=[]
    for case in CASES:
        rows=[]
        for cpu in CPU_FACTORS:
            cdp.send("Emulation.setCPUThrottlingRate",{"rate":cpu})
            try:
                for mode in ("normal",case,"normal",case,"normal"):
                    rows.append(physical_trial(page,cdp,mode,cpu))
            finally:
                cdp.send("Emulation.setCPUThrottlingRate",{"rate":1})
        cases.append(gate(rows,case))
    assert all(not c["productionCandidate"] for c in cases)
    return {"source":"real-Chromium-native-drag-test-bridge",
            "issue":111,"phase":12,
            "fixture":{"nodes":300,"edges":150,"distinctDecodedWebP":120},
            "traceBoundBytes":MAX_TRACE_BYTES,
            "tracePhysicalMouseMoves":3,"pairedPhysicalMouseMoves":12,
            "traceModes":evidence,"cases":cases,
            "normalDragAndUndoRestored":True,
            "browserNodeIdentityProven":False,
            "globalClassMutationIsOnlyPartOfAttribution":True,
            "rawTracePersisted":False,
            "physicalLowEndHardwareTested":False,
            "productionCssOrJsChanged":False,
            "productionReleaseEvidence":False}
