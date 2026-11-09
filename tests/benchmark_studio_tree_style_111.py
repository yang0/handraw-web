"""#111 Stage 10: real Chromium tree-style ablations, not a performance claim.

Keep every experimental rule/CSSOM mutation in the test page only.
Neither production Canvas styles nor rendering implementation are changed.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from backend.server import SESSION_COOKIE_NAME, create_channel_server, init_database
from backend.services import register_user
from ops.canvas_frame_trace_111 import read_trace_from_stream
from ops.canvas_style_invalidation_111 import summarize_style_invalidation
from ops.canvas_unique_media_111 import make_distinct_webp, apply_distinct_media
from smoke_studio_native_100_graph_112 import graph_fixture, http_json
from benchmark_studio_distinct_media_111 import profile_drag

CASES = ("world-style-containment", "world-layout-style-containment",
         "selected-compositor-layer", "relational-selector-off")
CPU_FACTORS = (1, 4)
# The candidate must pass independently for BOTH CPUs, on both repetitions.
MIN_IMPROVEMENT = 0.10

SET_ABLATION = r"""(mode) => {
  const state=window.__qa111stage10||(window.__qa111stage10={
    patches:[], style:null
  });
  for(const [rule,original] of state.patches){
    rule.selectorText=original;
    if(rule.selectorText!==original)
      throw Error('CSSOM selector restoration failed');
  }
  state.patches=[];
  if(state.style){state.style.remove();state.style=null;}
  const styles={
    "world-style-containment":"#ic-nodes-layer { contain: style !important; }",
    "world-layout-style-containment":"#ic-nodes-layer { contain: layout style !important; }",
    "selected-compositor-layer":
      "#ic-nodes-layer .ic-node.is-selected { will-change: transform !important; }"
  };
  let changedRules=0;
  if(mode==="relational-selector-off"){
    for(const sheet of document.styleSheets){
      let rules;
      try{rules=sheet.cssRules;}catch(_){continue;}
      for(const rule of rules){
        if(typeof rule.selectorText!=="string" ||
           !rule.selectorText.includes(".ic-canvas-stage:has(.ic-canvas-template-library)"))
          continue;
        const old=rule.selectorText;
        rule.selectorText=":root:not(:root)";
        if(rule.selectorText===":root:not(:root)"){
          state.patches.push([rule,old]);changedRules++;
        }
      }
    }
  }else if(styles[mode]){
    const el=document.createElement('style');
    el.dataset.qa111Stage10=mode;
    el.textContent=styles[mode];
    document.head.appendChild(el);state.style=el;
  }else if(mode!=="baseline"){throw Error("unknown ablation");}
  // Preserve graph/card geometry, header, connection ports and mini-map.
  const layer=document.getElementById('ic-nodes-layer');
  const card=layer?.querySelector('[data-node-id="g00-0"]');
  const head=card?.querySelector('.ic-node-header-above');
  const port=card?.querySelector('.ic-port-zone');
  const mini=document.querySelector('#ic-minimap [data-mini-node-id="g00-0"]');
  if(!card||!head||!port||!mini)throw Error('geometry probe absent');
  const rect=el=>{
    const r=el.getBoundingClientRect();
    return [r.left,r.top,r.width,r.height].map(x=>Math.round(x*10)/10);
  };
  const s=getComputedStyle(card);
  return {
    mode,changedRules,
    card:rect(card),header:rect(head),port:rect(port),mini:rect(mini),
    portOpacity:getComputedStyle(port).opacity,
    headerOpacity:getComputedStyle(head).opacity,
    cardContain:s.contain,cardWillChange:s.willChange,
    layerContain:getComputedStyle(layer).contain,
    nodeCount:layer.querySelectorAll('.ic-node').length,
    mediaCount:layer.querySelectorAll('img').length,
    edgeCount:document.querySelectorAll('#ic-edges-svg g.ic-edge-group[data-edge-id]').length
  };
}"""


def install_case(page, mode, baseline):
    probe = page.evaluate(SET_ABLATION, mode)
    assert probe["nodeCount"] == 300 and probe["edgeCount"] == 150
    assert probe["mediaCount"] == 120, probe
    if mode == "relational-selector-off" and probe["changedRules"] == 0:
        return probe, False, "targeted relational selector not found in CSSOM"
    if baseline is not None:
        # Absolute on-screen geometry and node hit regions must not shift.
        for key in ("card", "header", "port", "mini"):
            if any(abs(a-b)>1.0 for a,b in zip(probe[key], baseline[key])):
                return probe, False, "node/header/port/minimap geometry shifted"
        for key in ("portOpacity", "headerOpacity"):
            if probe[key] != baseline[key]:
                return probe, False, "header or port visibility changed"
    return probe, True, None


def metrics_for(record):
    counters = record["cdpDragOnly"]
    style = counters.get("RecalcStyleDuration")
    layout = counters.get("LayoutDuration")
    raf = record["raf"].get("frameGapP95Ms")
    assert isinstance(style, (int, float)) and style >= 0, record
    assert isinstance(layout, (int, float)) and layout >= 0, record
    return {"styleMs": round(style, 3),
            "layoutMs": round(layout, 3),
            "stylePlusLayoutMs": round(style+layout, 3),
            "rafGapP95Ms": raf}


def paired_ablation(page, cdp, case):
    records = []
    # A-B-A-B-A on the SAME decoded 300-card project and Chrome page.
    for factor in CPU_FACTORS:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate":factor})
        try:
            for mode in ("baseline", case, "baseline", case, "baseline"):
                probe, valid, reason = install_case(page, mode, None)
                page.wait_for_timeout(75)
                if not valid:
                    return {"case":case,"valid":False,"reason":reason,
                            "records":records,"promotionAllowed":False}
                result = profile_drag(page, cdp, cpu_factor=factor)
                records.append({"cpu":factor,"mode":mode,
                                "values":metrics_for(result),
                                "graphUndoAndMediaStable":result["graphUndoAndMediaStable"]})
        finally:
            cdp.send("Emulation.setCPUThrottlingRate", {"rate":1})
    gate={}
    for factor in CPU_FACTORS:
        subset=[r["values"] for r in records if r["cpu"]==factor]
        baseline=subset[0::2]
        candidate=subset[1::2]
        base_style=statistics.median(x["styleMs"] for x in baseline)
        base_total=statistics.median(x["stylePlusLayoutMs"] for x in baseline)
        base_raf=statistics.median(x["rafGapP95Ms"] for x in baseline)
        # Never promote a noisy/no-op candidate. Per-replicate improvement
        # AND no rAF/layout regression are necessary, not sufficient for D QA.
        passes=(base_style>0 and base_total>0 and base_raf>0 and
                all(x["styleMs"]<=base_style*(1-MIN_IMPROVEMENT)
                    and x["stylePlusLayoutMs"]<=base_total*(1-MIN_IMPROVEMENT)
                    and x["rafGapP95Ms"]<=base_raf*1.05
                    for x in candidate))
        gate[str(factor)+"x"]={
            "baselineMedianStyleMs":round(base_style,3),
            "baselineMedianStylePlusLayoutMs":round(base_total,3),
            "baselineMedianRafP95Ms":round(base_raf,2),
            "candidateStyleMs":[x["styleMs"] for x in candidate],
            "candidateStylePlusLayoutMs":[x["stylePlusLayoutMs"] for x in candidate],
            "candidateRafGapP95Ms":[x["rafGapP95Ms"] for x in candidate],
            "bothReplicatesAtLeast10PercentFasterWithoutRafRegression":bool(passes)}
    return {"case":case,"valid":True,"records":records,
            "gate":gate,"promotionAllowed":all(
                p["bothReplicatesAtLeast10PercentFasterWithoutRafRegression"]
                for p in gate.values())}


def trace_tree_affected(page, cdp, mode):
    # Trace includes pointerup / Undo; it is not the drag-only counter window.
    install_case(page, mode, None)
    handles=[]
    cdp.on("Tracing.tracingComplete", lambda params: handles.append(params.get("stream")))
    cdp.send("Tracing.start", {
        "categories":"devtools.timeline,disabled-by-default-devtools.timeline.invalidationTracking",
        "transferMode":"ReturnAsStream"})
    try:
        profile_drag(page,cdp)
    finally:
        cdp.send("Tracing.end")
    for _ in range(50):
        if handles:break
        page.wait_for_timeout(100)
    assert handles and handles[-1], "Chromium trace stream missing"
    reduced=summarize_style_invalidation(
        read_trace_from_stream(cdp,handles[-1],max_bytes=30_000_000))
    return reduced


def browser_test(base, token, fixture):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        binary=next((x for cmd in
          ("chromium","google-chrome-stable","google-chrome","chrome")
          if (x:=shutil.which(cmd))),None)
        launch={"headless":True,"args":["--no-sandbox",
                 "--disable-dev-shm-usage","--enable-precise-memory-info"]}
        if binary:launch["executable_path"]=binary
        browser=pw.chromium.launch(**launch)
        try:
            context=browser.new_context(viewport={"width":1440,"height":900},
                                        device_scale_factor=1)
            context.add_cookies([{"name":SESSION_COOKIE_NAME,
                                 "value":token,"url":base}])
            page=context.new_page()
            page.add_init_script("window.__HANDRAW_TESTING__=true")
            errors,paid=[],[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.on("request",lambda r:paid.append(r.method) if
                r.method=="POST" and
                ("/api/studio/generate" in r.url or "/api/studio/run" in r.url)
                else None)
            page.goto(base+"/studio/?project=qa111-style-tree",
                      wait_until="domcontentloaded",timeout=60000)
            page.wait_for_function("""() => window.CS?.stageView==='canvas'
              && window.CS.graph.nodes.length===300
              && document.querySelectorAll('#ic-nodes-layer .ic-node').length===300
              && document.querySelectorAll('#ic-nodes-layer img').length===120
            """,timeout=120000)
            decoded=page.evaluate("""async () => {
              const a=[...document.querySelectorAll('#ic-nodes-layer img')];
              await Promise.all(a.map(x=>x.decode()));
              return {count:a.length,urls:new Set(a.map(x=>x.currentSrc)).size,
                pixels:a.reduce((n,x)=>n+x.naturalWidth*x.naturalHeight,0)};
            }""")
            assert decoded=={"count":120,"urls":120,
                             "pixels":fixture["decodedPixelsExpected"]},decoded
            page.evaluate("""() =>
              window.HANDRAW_STUDIO_TESTING.focusCanvasNodeForBenchmark('g00-0')
            """)
            cdp=context.new_cdp_session(page)
            try:
                cdp.send("Performance.enable")
                baseline, valid, reason=install_case(page,"baseline",None)
                assert valid,reason
                # Probes are contextual, not full visual pixel equivalence.
                cases=[]
                for name in CASES:
                    probe, valid,reason=install_case(page,name,baseline)
                    install_case(page,"baseline",None)
                    if not valid:
                        cases.append({"case":name,"valid":False,"reason":reason,
                                      "promotionAllowed":False})
                        continue
                    if name=="relational-selector-off" and probe["changedRules"]==0:
                        cases.append({"case":name,"valid":False,
                                     "reason":"no matched CSS selector",
                                     "promotionAllowed":False})
                        continue
                    cases.append(paired_ablation(page,cdp,name))
                install_case(page,"baseline",None)
                tree=trace_tree_affected(page,cdp,"baseline")
                # A single targeted CSSOM trace for change in tree scope only.
                relational=next((x for x in cases if
                    x["case"]=="relational-selector-off" and x["valid"]),None)
                tree_relational=(trace_tree_affected(page,cdp,
                    "relational-selector-off") if relational else None)
                install_case(page,"baseline",None)
                assert not errors and not paid, (errors,paid)
                return {
                    "issue":111,"phase":10,
                    "source":"real-Studio-local-HTTP-Chromium",
                    "browser":browser.version,
                    "environment":{"python":platform.python_version(),
                                   "platform":platform.platform()},
                    "fixture":{"cards":300,"edges":150,"decodedMedia":decoded,
                               "uniqueEncodedSha256":fixture["uniqueSha256"]},
                    "testing":{"order":"A-B-A-B-A per candidate per CPU",
                               "cpuFactors":[1,4],"physicalMovesPerDrag":12,
                               "minStyleAndCombinedImprovement":MIN_IMPROVEMENT,
                               "maxRafP95Regression":0.05},
                    "baselineStyleChain":{"nodeContain":baseline["cardContain"],
                        "worldContain":baseline["layerContain"],
                        "selectedWillChange":baseline["cardWillChange"]},
                    "styleTreeTraceBaseline":tree,
                    "styleTreeTraceRelationalAblation":tree_relational,
                    "styleTraceCoversPointerUpAndUndo":True,
                    "cases":cases,
                    "safeForProductionPromotion":[x["case"] for x in cases
                       if x["promotionAllowed"]],
                    "allMediaAndUndoStable":True,
                    "paidGatewayRequests":0,"pageErrors":0,
                    "realGPUOrPhysicalLowEndEvidence":False,
                    "productionReleaseEvidence":False,
                    "productionCssChangesInThisStage":False,
                    "rawTracePersisted":False
                }
            finally:
                cdp.detach()
                page.close()
        finally:
            browser.close()


def main():
    with tempfile.TemporaryDirectory(
            prefix="qa111-tree-",dir=ROOT/"demo/starter") as static:
        fixture=make_distinct_webp(Path(static))
        assert fixture["count"]==120 and fixture["uniqueSha256"]==120
        with tempfile.TemporaryDirectory() as scratch:
            root=Path(scratch)
            with patch.dict(os.environ,{
                "HANDRAW_DB_PATH":str(root/"stage10.sqlite"),
                "HANDRAW_PRIVATE_STORAGE":str(root/"private"),
                "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
                "HANDRAW_GENERATED_DIR":str(root/"generated"),
                "HANDRAW_ALLOWED_ORIGINS":"http://trusted.test",
                "HANDRAW_ENABLE_RECHARGE":"0",
                "HANDRAW_DEMO_MODE":"1",
                "HANDRAW_AI_CONFIG":str(root/"no-paid-ai.json"),
                "HANDRAW_IMAGE_CONFIG":str(root/"no-paid-images.json"),
            }):
                db=server=worker=None
                try:
                    db=init_database(root/"stage10.sqlite")
                    _,token=register_user(db,"qa111_tree_style","Pass12345!")
                    cookie=f"{SESSION_COOKIE_NAME}={token}"
                    server=create_channel_server(0,"main",db)
                    server.allow_demo_routes=True
                    worker=threading.Thread(target=server.serve_forever,daemon=True)
                    worker.start()
                    base=f"http://127.0.0.1:{server.server_port}"
                    graph=graph_fixture(30)
                    assert apply_distinct_media(graph,fixture["urls"])==120
                    status,obj=http_json(base,"/api/studio/projects",cookie,
                        "POST",{"projectId":"qa111-style-tree",
                                "idempotencyKey":"qa111-tree-create",
                                "kind":"image","authority":"graph",
                                "title":"QA111 tree style ablation",
                                "draft":{"graph":graph,"activeView":"canvas"}})
                    assert status==200 and obj.get("ok") is not False,(status,obj)
                    report=browser_test(base,token,fixture)
                    dest=ROOT/"artifacts/studio-111-tree-style"
                    dest.mkdir(parents=True,exist_ok=True)
                    (dest/"summary.json").write_text(
                        json.dumps(report,indent=2,ensure_ascii=False)+"\n",
                        encoding="utf-8")
                    print("CANVAS #111 STAGE10 "+json.dumps({
                        "baselineTreeAffected":report["styleTreeTraceBaseline"][
                            "reportedAffectedElements"],
                        "cases":[{"name":x["case"],"safe":x["promotionAllowed"],
                                  "valid":x["valid"],
                                  "gate":x.get("gate")} for x in report["cases"]],
                        "paid":0},ensure_ascii=False),flush=True)
                finally:
                    if server:
                        server.shutdown()
                        server.server_close()
                    if worker:
                        worker.join(timeout=5)
                    if db:
                        db.close()


if __name__=="__main__":
    main()
