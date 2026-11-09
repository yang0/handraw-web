"""#111 residual style-tree causal triage: pointer state vs actual DOM writes.

This is intentionally diagnostic. It never changes production CSS/JS and
never promotes suppressed drag visuals to a release-performance candidate.
Stage 12 demonstrated no-visual still had one >8k UpdateLayoutTree event.
These controls distinguish idle, hover, pressed-idle, pointermove, and exact
hover CSSOM masking while all native drag *visual writes* are disabled.
"""
from __future__ import annotations

from ops.canvas_frame_trace_111 import (
    delta_performance_metrics, read_trace_from_stream, summarize_raf_intervals,
)
from ops.canvas_style_causality_111 import summarize_causality_window
from ops.canvas_phase12_isolation_111 import (
    CPU_FACTORS, DRAG_TARGET, FRAMES, OBSERVE_DOM, VERIFY,
    MAX_TRACE_BYTES, gate,
)

TRACE_WINDOWS = (
    "idle-stationary",
    "hover-moving",
    "pressed-stationary",
    "drag-no-visual",
    "drag-no-visual-hover-mask",
)

# Only pre-reviewed static selectors. Restore exact original selectorText.
# Hover CSSOM masking changes pointer feedback and is not deployable.
HOVER_MASK = r"""mode => {
  const state = window.__qa111phase13 || (window.__qa111phase13={rules:[]});
  for(const [rule, original] of state.rules){
    rule.selectorText=original;
    if(rule.selectorText!==original)throw Error("hover CSSOM restore failure");
  }
  state.rules.length=0;
  if(mode!=="mask")return {modified:0};
  const allow=new Set([
    ".ic-node:hover",
    ".ic-node:hover .ic-node-header-above",
    ".ic-node:hover .ic-port-zone"
  ]);
  const visit=rules=>{
    for(const rule of rules){
      if(rule.cssRules)try{visit(rule.cssRules)}catch(_){}
      if(typeof rule.selectorText!=="string")continue;
      const fragments=rule.selectorText.split(",");
      if(!fragments.some(f=>allow.has(f.trim())))continue;
      const changed=fragments.map(f=>allow.has(f.trim())
        ?":root:not(:root)":f.trim()).join(", ");
      const original=rule.selectorText;
      rule.selectorText=changed;
      if(rule.selectorText===changed)state.rules.push([rule,original]);
    }
  };
  for(const sheet of document.styleSheets)try{visit(sheet.cssRules)}catch(_){}
  return {modified:state.rules.length};
}"""

# Attribute-only MutationObserver misses childList and characterData changes.
# Count DOM structural mutations without reading any node text/HTML, IDs, URLs.
STRUCTURE_OBSERVER = r"""action => {
  if(action==="stop"){
    const state=window.__qa111structure13;
    if(!state)throw Error("no structure observer");
    state.obs.takeRecords().forEach(state.record);
    state.obs.disconnect();
    return {
      childListRecords:state.childList,
      addedNodeCount:state.added,
      removedNodeCount:state.removed,
      characterDataRecords:state.characterData,
      byParentRole:state.roles,
      eventsDroppedAtCap:state.overflow,
      privateContentsPersisted:false
    };
  }
  if(action!=="start")throw Error("invalid structure observer action");
  window.__qa111structure13?.obs.disconnect();
  const role=el=>{
    if(!el)return "other";
    if(el.nodeType!==1)el=el.parentElement;
    if(!el)return "other";
    if(el.closest("#ic-nodes-layer .ic-node"))return "node";
    if(el.closest("#ic-edges-svg"))return "edge-svg";
    if(el.closest("[data-float-topbar]"))return "floating-toolbar";
    if(el.closest("#ic-minimap"))return "minimap";
    if(el.closest("#ic-overlay-layer"))return "overlay";
    if(el.closest("#ic-viewport"))return "viewport";
    if(el.closest("#ic-canvas-stage"))return "canvas-stage";
    return "other";
  };
  const s={childList:0,added:0,removed:0,characterData:0,
           roles:{},overflow:0,total:0};
  s.record=m=>{
    if(s.total++>=5000){s.overflow++;return}
    const r=role(m.target);
    s.roles[r]=(s.roles[r]||0)+1;
    if(m.type==="childList"){
      s.childList++;
      s.added+=m.addedNodes.length;
      s.removed+=m.removedNodes.length;
    }else if(m.type==="characterData"){
      s.characterData++;
    }
  };
  s.obs=new MutationObserver(rows=>rows.forEach(s.record));
  s.obs.observe(document.body,{
    subtree:true,childList:true,characterData:true
  });
  window.__qa111structure13=s;
  return true;
}"""


def _plan(window: str):
    if window not in TRACE_WINDOWS:
        raise ValueError("unknown pointer diagnostic window")
    return {
        "pressed": window.startswith("pressed-") or window.startswith("drag-"),
        "moves": 3 if window in ("hover-moving","drag-no-visual",
                                 "drag-no-visual-hover-mask") else 0,
        "hoverMask": window=="drag-no-visual-hover-mask",
    }


def one_window(page, cdp, name, *, trace=True, moves_override=None):
    plan=_plan(name)
    moves=plan["moves"] if moves_override is None else moves_override
    if type(moves) is not int or moves < 0 or moves > 12:
        raise ValueError("unbounded pointer moves")
    target=page.evaluate(DRAG_TARGET,"no-visual")
    page.mouse.move(target["x"],target["y"])
    mouse_down=False
    mask={"modified":0}
    stream=[]
    tracing=False
    started=False
    structure_started=False
    frames_started=False
    try:
        if plan["pressed"]:
            page.mouse.down()
            mouse_down=True
        # CSS changes occur before tracing and measurement, not during drag.
        if plan["hoverMask"]:
            mask=page.evaluate(HOVER_MASK,"mask")
            if mask["modified"]<2:
                raise RuntimeError("known hover rules missing; mask would be inert")
        page.wait_for_timeout(85)
        page.evaluate(OBSERVE_DOM,"start")
        started=True
        page.evaluate(STRUCTURE_OBSERVER,"start")
        structure_started=True
        if not trace:
            page.evaluate(FRAMES,"start")
            frames_started=True
            before=cdp.send("Performance.getMetrics")
        else:
            cdp.on("Tracing.tracingComplete",
                   lambda ev:stream.append(ev.get("stream")))
            cdp.send("Tracing.start",{
                "categories":"devtools.timeline,disabled-by-default-devtools.timeline.invalidationTracking",
                "transferMode":"ReturnAsStream"})
            tracing=True
        try:
            if moves:
                for i in range(1,moves+1):
                    page.mouse.move(target["x"]+60*i/moves,
                                    target["y"]+30*i/moves,steps=1)
                    page.wait_for_timeout(30 if trace else 20)
            else:
                page.wait_for_timeout(90 if trace else 260)
            if trace:
                page.wait_for_timeout(40)
            else:
                after=cdp.send("Performance.getMetrics")
                gaps=page.evaluate(FRAMES,"stop")
                frames_started=False
        finally:
            if tracing:
                cdp.send("Tracing.end")
                tracing=False
            dom=page.evaluate(OBSERVE_DOM,"stop")
            started=False
            structure=page.evaluate(STRUCTURE_OBSERVER,"stop")
            structure_started=False
            if mouse_down:
                page.mouse.up()
                mouse_down=False

        chrome=None
        if trace:
            for _ in range(60):
                if stream:break
                page.wait_for_timeout(100)
            if not stream or not stream[-1]:
                raise RuntimeError("Chrome diagnostic trace stream unavailable")
            raw=read_trace_from_stream(cdp,stream[-1],max_bytes=MAX_TRACE_BYTES)
            chrome=summarize_causality_window(raw)
            del raw
            if chrome["traceEventCount"]==0:
                raise RuntimeError("Chrome supplied empty trace")
        else:
            delta=delta_performance_metrics(before,after)
            raf=summarize_raf_intervals(gaps)
            style=delta.get("RecalcStyleDuration")
            layout=delta.get("LayoutDuration")
            p95=raf.get("frameGapP95Ms")
            if (not all(isinstance(v,(int,float)) and v>=0 for v
                        in (style,layout,p95)) or raf.get("samples",0)<5):
                raise RuntimeError("incomplete 1x/4x Chrome counters")
            metric={"styleMs":round(style,3),
                    "combinedMs":round(style+layout,3),
                    "rafP95Ms":round(p95,2)}

        state=page.evaluate(VERIFY)
        assert (state["cards"],state["edges"],state["images"])==(
            300,150,120),(name,state)
        assert state["decoded"] and state["paths"]>=150,(name,state)
        moved=plan["pressed"] and moves>0
        if moved:
            assert state["x"]>target["nodeX"] and state["y"]>target["nodeY"],(
                name,state)
            assert state["left"]==f'{state["x"]}px' and (
                state["top"]==f'{state["y"]}px'),(name,state)
            assert state["finish"] and state["finish"]["targeted"] is False
            page.keyboard.press("Control+z")
            restored=page.evaluate("""() => {
              const node=window.CS.graph.nodes.find(n=>n.id==="g00-0");
              return {x:node.x,y:node.y};
            }""")
            assert restored=={"x":target["nodeX"],"y":target["nodeY"]},(
                name,restored)
        else:
            assert state["x"]==target["nodeX"] and (
                state["y"]==target["nodeY"]),(name,state)
        return {
            "window":name,"physicalMouseMoves":moves,
            "pressed":plan["pressed"],"hoverRulesMasked":mask["modified"],
            "domMutations":dom,"structureChanges":structure,"chrome":chrome,
            "metric":None if trace else metric,
            "nativeGraphAndMediaStable":True,
        }
    finally:
        if tracing:
            try:cdp.send("Tracing.end")
            except Exception:pass
        if started:
            try:page.evaluate(OBSERVE_DOM,"stop")
            except Exception:pass
        if structure_started:
            try:page.evaluate(STRUCTURE_OBSERVER,"stop")
            except Exception:pass
        if frames_started:
            try:page.evaluate(FRAMES,"stop")
            except Exception:pass
        if mouse_down:
            try:page.mouse.up()
            except Exception:pass
        page.evaluate(HOVER_MASK,"restore")
        page.evaluate("""() => {
          const t=window.HANDRAW_STUDIO_TESTING;
          t.canvasDragVisualProbeMode="normal";
          t.canvasDragFinishMode="auto";
        }""")


def collect(page,cdp):
    cdp.send("Performance.enable")
    traces={}
    for name in TRACE_WINDOWS:
        row=one_window(page,cdp,name,trace=True)
        chrome=row.pop("chrome")
        traces[name]={
            "largeUpdateEvents":chrome["updateLayoutTree"]["largeEventsGE8000"],
            "maxElementCount":chrome["updateLayoutTree"]["maxElementCount"],
            "invalidationCount":chrome["invalidationEvents"],
            "joinNearLargeByReason":chrome["joinNearLargeUpdateByReason"],
            "actualDomMutationCounts":row["domMutations"]["byType"],
            "structuralDomMutations":row["structureChanges"],
            "globalClassMutations":row["domMutations"]["globalClassMutations"],
            "hoverRulesMasked":row["hoverRulesMasked"],
            "pressed":row["pressed"],
            "moves":row["physicalMouseMoves"],
        }
    samples=[]
    for cpu in CPU_FACTORS:
        cdp.send("Emulation.setCPUThrottlingRate",{"rate":cpu})
        try:
            for mode in ("drag-no-visual","drag-no-visual-hover-mask",
                         "drag-no-visual","drag-no-visual-hover-mask",
                         "drag-no-visual"):
                row=one_window(page,cdp,mode,trace=False,moves_override=12)
                samples.append({"cpu":cpu,"cdp":row["metric"]})
        finally:
            cdp.send("Emulation.setCPUThrottlingRate",{"rate":1})
    verdict=gate(samples,"no-visual-hover-mask")
    return {
        "issue":111,"stage":13,
        "purpose":"residual-update pointer/hover hypothesis, after Phase 12",
        "conditions":traces,
        "hoverMaskVsNoVisual":verdict,
        "diagnosticOnly":True,
        "productionCandidate":False,
        "realInputTestBridge":True,
        "browserNodeIdentityProven":False,
        "rawTracePersisted":False,
        "paidRequests":0,"physicalLowEndDeviceTested":False,
        "productionReleaseEvidence":False,
    }
