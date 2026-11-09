"""#111 Stage 11: browser-only attribution and targeted CSSOM drag ablation."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from ops.canvas_frame_trace_111 import read_trace_from_stream
from ops.canvas_style_causality_111 import (
    summarize_causality_window, validate_selector_census,
)

HOVER_RULES = (
    ".ic-node:hover",
    ".ic-node:hover .ic-node-header-above",
    ".ic-node:hover .ic-port-zone",
)

# CSSOM mutation is isolated to local QA and precisely restored.
JS_ABLATION = r"""mode=>{
  const stash=window.__qa111hover||(window.__qa111hover=[]);
  for(const [rule,original] of stash){
    rule.selectorText=original;
    if(rule.selectorText!==original)throw Error("CSSOM restoration failed");
  }
  stash.length=0;
  const allowed=new Set([
    '.ic-node:hover','.ic-node:hover .ic-node-header-above',
    '.ic-node:hover .ic-port-zone'
  ]);
  let changes=0;
  const walk=rules=>{
    for(const rule of rules){
      if(rule.cssRules)try{walk(rule.cssRules)}catch(_){}
      if(typeof rule.selectorText!=="string")continue;
      const old=rule.selectorText,parts=old.split(",");
      if(!parts.some(p=>allowed.has(p.trim())))continue;
      const out=parts.map(p=>{
        const text=p.trim();
        if(!allowed.has(text))return text;
        return mode==="selected-hover-guard"
          ?text.replace(".ic-node:hover",".ic-node:not(.is-selected):hover")
          :":root:not(:root)";
      }).join(", ");
      if(out===old)continue;
      rule.selectorText=out;
      if(rule.selectorText===out){stash.push([rule,old]);changes++}
    }
  };
  if(mode!=="baseline"){
    for(const sheet of document.styleSheets)try{walk(sheet.cssRules)}catch(_){}
  }
  const layer=document.getElementById("ic-nodes-layer");
  const node=layer.querySelector('[data-node-id="g00-0"]');
  const head=node.querySelector(".ic-node-header-above");
  const port=node.querySelector(".ic-port-zone");
  const mini=document.querySelector('#ic-minimap [data-mini-node-id="g00-0"]');
  const coords=el=>{const r=el.getBoundingClientRect();
    return [r.x,r.y,r.width,r.height].map(n=>Math.round(n*10)/10)};
  return {changes,geometry:[coords(node),coords(head),coords(port),coords(mini)],
    headOpacity:getComputedStyle(head).opacity,
    portOpacity:getComputedStyle(port).opacity,
    nodes:layer.querySelectorAll(".ic-node").length,
    edges:document.querySelectorAll(
      "#ic-edges-svg g.ic-edge-group[data-edge-id]").length,
    images:layer.querySelectorAll("img").length};
}"""

JS_MUTATIONS = r"""action=>{
  if(action==="stop"){
    const p=window.__qa111probe;
    if(!p)return {records:[],overflow:0};
    p.observer.disconnect();return {records:p.rows,overflow:p.overflow};
  }
  const tags=[
    ['#ic-nodes-layer .ic-node-header-above','node-header'],
    ['#ic-nodes-layer .ic-port-zone','port'],
    ['#ic-nodes-layer .ic-node','node'],
    ['#ic-nodes-layer','nodes-layer'],
    ['#ic-edges-svg path','edge-path'],
    ['#ic-edges-svg','edge-svg'],
    ['#ic-minimap','minimap'],
    ['.ic-world','world'],
    ['.ic-viewport','viewport'],
    ['.ic-shelf-drawer','shelf'],
    ['.ic-canvas-stage','canvas-stage'],
    ['.ic-studio-shell','studio-shell']
  ];
  const role=el=>{
    if(!el||el.nodeType!==1)return 'other';
    for(const [sel,label] of tags)if(el.matches(sel))return label;
    return 'outside-canvas';
  };
  const p={rows:[],overflow:0};
  p.observer=new MutationObserver(records=>{
    for(const m of records){
      if(p.rows.length>=4000){p.overflow++;continue}
      const chain=[];
      let cur=m.target;
      for(let n=0;cur&&n<12;n++,cur=cur.parentElement){
        chain.unshift(role(cur));
        if(cur.matches('.ic-studio-shell'))break;
      }
      p.rows.push({attribute:m.attributeName,role:role(m.target),
                   ancestors:chain});
    }
  });
  p.observer.observe(document.body,{
    subtree:true,attributes:true,attributeFilter:["style","class"]
  });
  window.__qa111probe=p;return true;
}"""

JS_SELECTORS = r"""() => [
  '.ic-node:hover .ic-port-zone',
  '.ic-node.is-selected .ic-port-zone',
  '.ic-studio-shell.is-wiring .ic-port-zone',
  '.ic-node:hover .ic-node-header-above',
  '.ic-node.is-selected .ic-node-header-above',
  '.ic-canvas-stage:has(.ic-canvas-template-library) .ic-shelf-drawer'
].map(selector=>{
  let matches=0;try{matches=document.querySelectorAll(selector).length}catch(_){}
  return {selector,matches};
})"""


def ablation(page, cdp, name, profile_drag, metrics_for):
    first=page.evaluate(JS_ABLATION,"baseline")
    after=page.evaluate(JS_ABLATION,name)
    page.evaluate(JS_ABLATION,"baseline")
    valid=(after["changes"]>=2 and
           (after["nodes"],after["images"],after["edges"])==(300,120,150) and
           all(all(abs(a-b)<=1 for a,b in zip(p,q))
               for p,q in zip(first["geometry"],after["geometry"])) and
           first["headOpacity"]==after["headOpacity"] and
           first["portOpacity"]==after["portOpacity"])
    if not valid:
        return {"case":name,"valid":False,"productionCandidate":False,
                "reason":"unmatched rules or geometry/opacity mismatch"}
    values=[]
    for cpu in (1,4):
        cdp.send("Emulation.setCPUThrottlingRate",{"rate":cpu})
        try:
            for mode in ("baseline",name,"baseline",name,"baseline"):
                page.evaluate(JS_ABLATION,mode)
                page.wait_for_timeout(75)
                drag=profile_drag(page,cdp,cpu_factor=cpu)
                values.append({"cpu":cpu,"mode":mode,
                               "metric":metrics_for(drag),
                               "undoAndMediaStable":drag["graphUndoAndMediaStable"]})
        finally:
            cdp.send("Emulation.setCPUThrottlingRate",{"rate":1})
    page.evaluate(JS_ABLATION,"baseline")
    gates={}
    for cpu in (1,4):
        vals=[v["metric"] for v in values if v["cpu"]==cpu]
        control=vals[0::2];test=vals[1::2]
        style=statistics.median(v["styleMs"] for v in control)
        total=statistics.median(v["stylePlusLayoutMs"] for v in control)
        raf=statistics.median(v["rafGapP95Ms"] for v in control)
        good=(style>0 and total>0 and raf>0 and all(
            v["styleMs"]<=style*.90 and
            v["stylePlusLayoutMs"]<=total*.90 and
            v["rafGapP95Ms"]<=raf*1.05 for v in test))
        gates[f"{cpu}x"]={
            "baselineStyleMedianMs":round(style,3),
            "candidateStyleMs":[v["styleMs"] for v in test],
            "baselineCombinedMedianMs":round(total,3),
            "candidateCombinedMs":[v["stylePlusLayoutMs"] for v in test],
            "baselineRafP95Ms":round(raf,2),
            "candidateRafP95Ms":[v["rafGapP95Ms"] for v in test],
            "stableAtLeast10PercentBothReplicates":bool(good)}
    diagnostic=name=="node-hover-rules-off"
    return {"case":name,"valid":True,"rulesPatched":after["changes"],
            "diagnosticOnly":diagnostic,"gate":gates,
            "productionCandidate":not diagnostic and
              all(g["stableAtLeast10PercentBothReplicates"] for g in gates.values()),
            "furtherCrossViewAndPhysicalDeviceReviewRequired":True}


def trace_window(page,cdp):
    """Capture only 3 mouse moves, no pointerdown/up/Undo in trace window."""
    page.evaluate(JS_ABLATION,"baseline")
    target=page.evaluate(r"""() => {
      window.HANDRAW_STUDIO_TESTING.focusCanvasNodeForBenchmark('g00-0');
      const el=document.querySelector(
        '#ic-nodes-layer [data-node-id="g00-0"]');
      const h=el.querySelector(".ic-node-header-above");
      const n=window.CS.graph.nodes.find(x=>x.id==="g00-0");
      const r=h.getBoundingClientRect();
      for(const f of [.15,.45,.7]){
        const x=r.left+r.width*f,y=r.top+r.height*.5;
        if(document.elementFromPoint(x,y)?.closest('.ic-node')===el)
          return {x,y,nx:n.x,ny:n.y};
      }
      throw Error('no hit-testable node header');
    }""")
    cssom=validate_selector_census(page.evaluate(JS_SELECTORS))
    page.mouse.move(target["x"],target["y"])
    page.mouse.down()
    page.wait_for_timeout(70)
    streams=[]
    cdp.on("Tracing.tracingComplete",lambda m:streams.append(m.get("stream")))
    page.evaluate(JS_MUTATIONS,"start")
    cdp.send("Tracing.start",{
        "categories":"devtools.timeline,disabled-by-default-devtools.timeline.invalidationTracking",
        "transferMode":"ReturnAsStream"})
    try:
        for k in (1,2,3):
            page.mouse.move(target["x"]+20*k,target["y"]+10*k,steps=1)
            page.wait_for_timeout(25)
        page.wait_for_timeout(40)
    finally:
        cdp.send("Tracing.end")
        mutations=page.evaluate(JS_MUTATIONS,"stop")
        page.mouse.up()
    for _ in range(60):
        if streams:break
        page.wait_for_timeout(100)
    try:
        if not streams or not streams[-1]:
            raise ValueError("missing stream")
        raw=read_trace_from_stream(cdp,streams[-1],max_bytes=30_000_000)
        summary=summarize_causality_window(raw,mutations)
        summary["available"]=True
        del raw
    except (ValueError,KeyError,TypeError):
        summary={"available":False,"errorCategory":"bounded-or-missing-trace",
                 "rawTracePersisted":False,"rootCauseProven":False}
    page.keyboard.press("Control+z")
    state=page.evaluate("""() => {
      const n=window.CS.graph.nodes.find(x=>x.id==="g00-0");
      const root=document.getElementById("ic-nodes-layer");
      return {x:n.x,y:n.y,cards:root.querySelectorAll(".ic-node").length,
        images:root.querySelectorAll("img").length,decoded:
          [...root.querySelectorAll("img")].every(
            i=>i.complete&&i.naturalWidth>0)};
    }""")
    assert state=={"x":target["nx"],"y":target["ny"],"cards":300,
                   "images":120,"decoded":True},state
    return {"sameWindowChrome":summary,"staticCSSOM":cssom,
            "realMouseMoves":3,"traceIncludesPointerDownUpUndo":False,
            "mutationObserverInstrumentation":True,
            "chromeNodeIdIsNotVerifiedDomIdentity":True}
