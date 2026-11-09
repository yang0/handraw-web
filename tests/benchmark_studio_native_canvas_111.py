"""#111: actual Studio HTTP Project/Chromium performance matrix.

Unlike the #127 synthetic DOM test this creates four real Projects with
10/50/100/300 native Studio nodes and locally served WebP assets. Run IDs,
media credentials and vendor requests are never created. Latency numbers
are observational and have no arbitrary pass/fail performance budget.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.server import SESSION_COOKIE_NAME, create_channel_server, init_database
from backend.services import register_user
from smoke_studio_native_100_graph_112 import graph_fixture, http_json
from ops.canvas_frame_trace_111 import (
    delta_performance_metrics, read_trace_from_stream,
    summarize_raf_intervals, summarize_trace_events,
)


def percentile(values, q):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * q))], 2)


JS_MEASURE = r"""() => {
  const graph=window.CS?.graph;
  const probe=window.HANDRAW_STUDIO_TESTING?.renderCanvasNodesForBenchmark;
  const root=document.getElementById('ic-nodes-layer');
  if(!graph||typeof probe!=='function'||!root)throw Error('native canvas test bridge unavailable');
  const beforeCards=new Map([...root.querySelectorAll('.ic-node[data-node-id]')]
    .map(el=>[el.dataset.nodeId,el]));
  const beforeImages=[...root.querySelectorAll('img')];
  const input=root.querySelector('[data-node-id="g00-3"] input[data-sp-aud]');
  if(!input)throw Error('first real native text_input editor not found');
  input.focus();
  input.value='光标仍保持在正在编辑的字段';
  if(typeof input.setSelectionRange==='function')input.setSelectionRange(2,5);
  const editNode=graph.nodes.find(n=>n.id==='g00-0');
  // Progress on the actual output_control keeps all already-successful media visible;
  // output_display deliberately swaps its image for a spinner during new generation.
  const resultNode=graph.nodes.find(n=>n.id==='g00-7');
  if(!editNode||!resultNode)throw Error('required text/result nodes are missing');
  const warm=probe();
  // Within-page baseline keeps Chromium/Graph/DOM/CI host constant. The
  // unoptimised path still builds/parses every native card for each change.
  const fullUpdates=[];
  for(let i=0;i<7;i++){
    editNode.data.text='同页全量渲染对照-'+i;
    const measured=probe();
    fullUpdates.push({ms:+measured.durationMs.toFixed(2),
      partial:measured.patch?.partial,nodes:measured.patch?.nodes});
  }
  const stableEdgesAfterWarm=[...document.querySelectorAll('#ic-edges-svg [data-edge-id]')];
  const updates=[];
  for(let i=0;i<7;i++){
    editNode.data.text='页面实际编辑-'+String(i);
    const measured=probe(['g00-0']);
    updates.push({
      ms:+measured.durationMs.toFixed(2),
      partial:measured.patch?.partial,nodes:measured.patch?.nodes,
      edgesRecomputed:measured.patch?.edgesRecomputed,
      dirty:(measured.patch?.changedIds||[]).filter(id=>id.startsWith('node:')),
      replaced:measured.patch?.replaced,
    });
  }
  // Reconcile may replace the owning card while explicitly restoring focus,
  // cursor and in-progress user value to the new real textarea node.
  const activeInput=root.querySelector('[data-node-id="g00-3"] input[data-sp-aud]');
  const focusHeld=document.activeElement===activeInput &&
    activeInput?.value==='光标仍保持在正在编辑的字段' &&
    activeInput.selectionStart===2 && activeInput.selectionEnd===5;
  const edgesStableOnTextOnly=stableEdgesAfterWarm.every(el=>el.isConnected &&
    document.querySelector('#ic-edges-svg [data-edge-id="'+el.getAttribute('data-edge-id')+'"]')===el);
  const oldStatus=resultNode.data.status;
  resultNode.data.status=oldStatus==='generating'?'done':'generating';
  const status=probe(['g00-7']);
  resultNode.data.status=oldStatus;
  const restored=probe(['g00-7']);
  // Unknown dirty ID must safely fall back to a whole-Graph reconcile.
  const fallback=probe(['not-a-real-node']);
  const stableNodes=[...beforeCards].filter(([id,el])=>
    id!=='g00-0'&&id!=='g00-7'&&el.isConnected &&
    root.querySelector('[data-node-id="'+id+'"]')===el).length;
  const afterImages=[...root.querySelectorAll('img')];
  const stableImages=beforeImages.filter(el=>el.isConnected&&afterImages.includes(el)).length;
  return {
    updates,fullUpdates,focusHeld,edgesStableOnTextOnly,
    statusMs:+status.durationMs.toFixed(2),
    statusPartial:status.patch?.partial,statusNodeCount:status.patch?.nodes,
    fallbackFull:!fallback.patch?.partial &&
      fallback.patch?.nodes===graph.nodes.length,
    statusDirty:(status.patch?.changedIds||[]).filter(id=>id.startsWith('node:')),
    restoredDirty:(restored.patch?.changedIds||[]).filter(id=>id.startsWith('node:')),
    stableUnrelatedNodes:stableNodes,
    totalUnrelatedNodes:beforeCards.size-2,
    stableImages,imagesBefore:beforeImages.length,
    totalCards:root.querySelectorAll('.ic-node[data-node-id]').length,
    edges:document.querySelectorAll('#ic-edges-svg [data-edge-id]').length,
    domElements:root.querySelectorAll('*').length,
    usedJSHeapBytes:performance.memory?.usedJSHeapSize??null
  };
}"""



def measure_physical_drag(page, size: int, cpu_factor: int = 1) -> dict:
    """Actual Playwright mouse events, no synthetic handler invocation."""
    page.evaluate("""() => window.HANDRAW_STUDIO_TESTING
      .focusCanvasNodeForBenchmark('g00-0')""")
    # Use the real header drag handle, not the card's upper-left corner:
    # that corner may overlap the file picker/other interactive controls.
    target = page.evaluate("""() => {
      const node=document.querySelector('#ic-nodes-layer [data-node-id="g00-0"]');
      const head=node?.querySelector('.ic-node-header-above');
      if(!node||!head)throw Error('native drag title bar unavailable');
      const r=head.getBoundingClientRect(),points=[
        [r.left+Math.min(26,r.width*.15),r.top+r.height*.5],
        [r.left+r.width*.45,r.top+r.height*.5],
        [r.left+r.width*.7,r.top+r.height*.5]
      ];
      const checked=[];
      for(const [x,y] of points){
        const hit=document.elementFromPoint(x,y);
        checked.push({x:+x.toFixed(1),y:+y.toFixed(1),
          tag:hit?.tagName||'',className:String(hit?.className||'').slice(0,90),
          nodeId:hit?.closest('.ic-node')?.dataset.nodeId||null});
        if(hit?.closest('.ic-node')===node &&
           !hit.closest('button,input,textarea,select,label'))
          return {x,y,checked};
      }
      return {x:null,y:null,checked};
    }""")
    assert target["x"] is not None, ("no interactive-free visible node header",
                                    size, target)
    x, y = target["x"], target["y"]
    page.mouse.move(x, y)
    page.mouse.down()
    before = page.evaluate("""() => {
      const root=document.querySelector('#ic-nodes-layer');
      const svg=document.getElementById('ic-edges-svg');
      const group=svg?.querySelector('[data-edge-id="g00-edge-0-7"]');
      const other=svg?.querySelector('[data-edge-id="g00-edge-3-7"]');
      const mini=document.getElementById('ic-minimap')
        ?.querySelector('[data-mini-node-id="g00-0"]');
      const card=root?.querySelector('[data-node-id="g00-0"]');
      const model=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      const toolbar=document.querySelector('[data-float-topbar]');
      if(!group||!other||!mini||!card||!model||!toolbar)
        throw Error('native drag fixture has missing DOM binding');
      window.__drag111Refs={group,other,mini,card,toolbar,
        toolbarLeft:toolbar.style.left,toolbarTop:toolbar.style.top,
        otherPath:other.querySelector('path.ic-edge-line')?.getAttribute('d'),
        hitPath:group.querySelector('path.ic-edge-hit')?.getAttribute('d'),
        images:[...root.querySelectorAll('img')]};
      return {x:model.x,y:model.y,
        selected:(window.CS.graph.selectedIds||[]).includes('g00-0')};
    }""")
    assert before["selected"], ("real node pointer selection did not register", size)
    page.mouse.move(x + 92, y + 53, steps=9)
    middle = page.evaluate("""() => {
      const r=window.__drag111Refs;
      const svg=document.getElementById('ic-edges-svg');
      const model=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      const samples=document.getElementById('ic-nodes-layer')._drag111Samples||[];
      const line=r.group.querySelector('path.ic-edge-line');
      const hit=r.group.querySelector('path.ic-edge-hit');
      return {
        x:model.x,y:model.y,
        incidentChanged:hit?.getAttribute('d')!==r.hitPath,
        hitMatchesLine:hit?.getAttribute('d')===line?.getAttribute('d'),
        unrelatedStable:r.other.isConnected &&
          svg.querySelector('[data-edge-id="g00-edge-3-7"]')===r.other &&
          r.other.querySelector('path.ic-edge-line')?.getAttribute('d')===r.otherPath,
        cardStable:r.card.isConnected &&
          document.querySelector('#ic-nodes-layer [data-node-id="g00-0"]')===r.card,
        miniStable:r.mini.isConnected &&
          document.querySelector('#ic-minimap [data-mini-node-id="g00-0"]')===r.mini,
        imageStable:r.images.every(img=>img.isConnected),
        toolbarStable:r.toolbar.isConnected &&
          document.querySelector('[data-float-topbar]')===r.toolbar,
        toolbarMoved:r.toolbar.style.left!==r.toolbarLeft ||
          r.toolbar.style.top!==r.toolbarTop,
        samples:samples.map(p=>({totalMs:p.totalMs,
          edgeAndPositionMs:p.edgeAndPositionMs,
          overlayMs:p.overlayMs,minimapMs:p.minimapMs,
          overlayCached:p.overlayCached,
          usedSession:p.usedSession,movedCount:p.movedCount}))
      };
    }""")
    page.mouse.up()
    assert middle["x"] > before["x"] and middle["y"] > before["y"], (
        "real pointer drag did not move Graph", size, middle)
    for guard in ("incidentChanged", "hitMatchesLine", "unrelatedStable",
                  "cardStable", "miniStable", "imageStable",
                  "toolbarStable", "toolbarMoved"):
        assert middle[guard], ("drag DOM/geometry regression", size, guard, middle)
    samples = middle.pop("samples")
    assert len(samples) >= 7, ("insufficient real pointermove samples", size, samples)
    assert all(p["usedSession"] and p["movedCount"] == 1 for p in samples), (
        "drag-session invalidated without known topology change", size, samples)
    assert all(p["overlayCached"] is True for p in samples), (
        "drag toolbar fell back to a layout read during a stable drag", size, samples)
    assert all(p["overlayMs"] >= 0 and p["minimapMs"] >= 0 for p in samples), (
        "non-finite drag split timing", size, samples)
    after = page.evaluate("""() => {
      const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      return {x:n.x,y:n.y};
    }""")
    assert after["x"] == middle["x"] and after["y"] == middle["y"], (
        "pointerup lost drag coordinates", size, after, middle)
    # Real keyboard Undo and Redo must restore the edited Graph geometry.
    page.keyboard.press("Control+z")
    undo = page.evaluate("""() => {
      const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      return {x:n.x,y:n.y};
    }""")
    assert undo == {"x": before["x"], "y": before["y"]}, (
        "drag Undo failed to restore coordinates", size, before, undo)
    page.keyboard.press("Control+y")
    redo = page.evaluate("""() => {
      const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      return {x:n.x,y:n.y};
    }""")
    assert redo == after, ("drag Redo failed", size, after, redo)
    return {"nodes": size, "cpuThrottle": cpu_factor, "pointerEvents": len(samples),
            "pointerP50Ms": percentile([v["totalMs"] for v in samples], .5),
            "pointerP95Ms": percentile([v["totalMs"] for v in samples], .95),
            "edgeAndPositionP95Ms": percentile(
                [v["edgeAndPositionMs"] for v in samples], .95),
            "overlayP95Ms": percentile([v["overlayMs"] for v in samples], .95),
            "minimapP95Ms": percentile([v["minimapMs"] for v in samples], .95),
            "allOverlayCacheHits": True,
            "allSessionUpdates": True, "incidentPathsCorrect": True,
            "unrelatedEdgeAndMiniDOMStable": True, "imageStable": True,
            "undoRedoGeometry": True}



def profile_real_frame_pipeline(page, size: int, cpu_factor: int = 1,
                                finish_mode: str = "targeted") -> dict:
    """Physical pointer + rAF cadence + bounded CDP render diagnostics.

    Includes real presentation cadence while dragging AND settling after
    pointerup. No fake Graph updates. Trace raw bytes never leave memory.
    """
    assert finish_mode in ("targeted", "full")
    page.evaluate("""mode => {
      if(window.__HANDRAW_TESTING__!==true||!window.HANDRAW_STUDIO_TESTING)
        throw Error('finish mode is available only in isolated browser tests');
      window.HANDRAW_STUDIO_TESTING.canvasDragFinishMode=mode;
      return window.HANDRAW_STUDIO_TESTING.focusCanvasNodeForBenchmark('g00-0');
    }""", finish_mode)
    coords = page.evaluate("""() => {
      const node=document.querySelector('#ic-nodes-layer [data-node-id="g00-0"]');
      const header=node?.querySelector('.ic-node-header-above');
      if(!header)throw Error('real frame profile header missing');
      const r=header.getBoundingClientRect();
      const candidates=[.15,.45,.7];
      for(const ratio of candidates){
        const x=r.left+r.width*ratio, y=r.top+r.height*.5;
        const hit=document.elementFromPoint(x,y);
        if(hit?.closest('.ic-node')===node &&
            !hit.closest('button,input,textarea,select,label')){
          const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
          window.__studio111PacedCard=node;
          return {x,y,nodeX:n.x,nodeY:n.y};
        }
      }
      throw Error('no pointer-reachable native header for frame profile');
    }""")
    cdp = page.context.new_cdp_session(page)
    complete = {}
    recording = False
    try:
        cdp.send("Performance.enable")
        # The trace is Chrome renderer metadata only and is never uploaded or
        # printed. Do not label these events as GPU fence/present timing.
        cdp.on("Tracing.tracingComplete", lambda event: complete.update(event))
        cdp.send("Tracing.start", {
            "categories": "devtools.timeline,blink,cc",
            "options": "record-as-much-as-possible",
            "transferMode": "ReturnAsStream",
        })
        recording = True
        before = cdp.send("Performance.getMetrics")
        page.evaluate("""() => {
          const monitor={active:true,last:null,intervals:[]};
          window.__studio111Frames=monitor;
          function frame(t){
            if(!monitor.active)return;
            if(monitor.last!==null && monitor.intervals.length<240)
              monitor.intervals.push(t-monitor.last);
            monitor.last=t;
            requestAnimationFrame(frame);
          }
          requestAnimationFrame(frame);
        }""")
        page.mouse.move(coords["x"], coords["y"])
        page.mouse.down()
        # 12 real pointer movements with deliberate pacing, so the renderer
        # has multiple opportunities to present frames. Unlike 9 rapid
        # pointer events, this reports actual rAF cadence under pressure.
        for step in range(1, 13):
            page.mouse.move(coords["x"] + 92*step/12,
                            coords["y"] + 53*step/12, steps=1)
            page.wait_for_timeout(20)
        # Separate the compositor/style work triggered during paced dragging
        # from the authoritative render and visual settling after pointerup.
        # Both snapshots are Chromium cumulative counters for the same page,
        # not Python wall-time or per-event microbenchmarks.
        before_pointerup = cdp.send("Performance.getMetrics")
        page.mouse.up()
        # Include pointer-up authoritative full reconcile and the ensuing
        # paint opportunity; this is not solely a JavaScript handler metric.
        page.wait_for_timeout(145)
        intervals = page.evaluate("""() => {
          const monitor=window.__studio111Frames;
          monitor.active=false;
          return monitor.intervals.slice();
        }""")
        after = cdp.send("Performance.getMetrics")
        cdp.send("Tracing.end")
        recording = False
        for _ in range(45):
            if complete.get("stream"):
                break
            page.wait_for_timeout(50)
        if not complete.get("stream"):
            raise AssertionError("CDP trace stream missing after real drag")
        trace = read_trace_from_stream(cdp, complete["stream"])
        frames = summarize_raf_intervals(intervals)
        counters = delta_performance_metrics(before, after)
        drag_counters = delta_performance_metrics(before, before_pointerup)
        settle_counters = delta_performance_metrics(before_pointerup, after)
        groups = summarize_trace_events(trace)
        # Assertions prove the *measurement exists*, not 60fps performance.
        assert frames["samples"] >= 5, ("too few real frame samples", size, frames)
        assert counters["LayoutCount"] is not None, (
            "Chromium LayoutCount metric missing", size, counters)
        assert drag_counters["RecalcStyleDuration"] is not None and (
            settle_counters["RecalcStyleDuration"] is not None), (
                "CDP style recalc phase metrics unavailable", size,
                drag_counters, settle_counters)
        assert abs((drag_counters["RecalcStyleDuration"] +
                    settle_counters["RecalcStyleDuration"]) -
                   counters["RecalcStyleDuration"]) < .011, (
            "CDP style phase deltas do not reconcile", size,
            drag_counters, settle_counters, counters)
        assert groups["eventCount"] > 0, ("empty Chromium trace", size)
        state = page.evaluate("""() => {
          const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
          const layer=document.getElementById('ic-nodes-layer');
          const card=layer.querySelector('[data-node-id="g00-0"]');
          return {x:n.x,y:n.y,
            cssX:card?.style.left,cssY:card?.style.top,
            cssTranslate:card?.style.translate,
            cardStable:card===window.__studio111PacedCard &&
              card?.isConnected===true,
            finish:layer._drag111Finish||null,
            cards:document.querySelectorAll('#ic-nodes-layer .ic-node').length,
            imageNodes:document.querySelectorAll('#ic-nodes-layer img').length,
            edgeGroups:document.querySelectorAll(
              '#ic-edges-svg g.ic-edge-group[data-edge-id]').length};
        }""")
        assert state["x"] > coords["nodeX"] and state["y"] > coords["nodeY"], (
            "real paced frame drag failed to move Graph", size, coords, state)
        assert state["cards"] == size and state["edgeGroups"] == size//2, (
            "real paced drag lost Graph DOM", size, state)
        assert state["imageNodes"] >= size*4//10, (
            "real paced drag lost preview images", size, state)
        assert state["cssX"] == f'{state["x"]}px' and (
            state["cssY"] == f'{state["y"]}px'), (
                "real paced drag did not commit layout position", size, state)
        assert state["cssTranslate"] in ("", None, "none"), (
            "real drag retained a transient CSS translate", size, state)
        # The legacy full-render control is EXPECTED to replace cards.
        # The targeted path, in contrast, must preserve the exact DOM node.
        assert finish_mode == "full" or state["cardStable"], (
            "targeted drag replaced an unchanged media card DOM", size, state)
        assert state["finish"] and (
            state["finish"]["targeted"] == (finish_mode == "targeted")), (
                "node pointerup did not honor safe finish policy",
                size, finish_mode, state)
        return {"nodes": size, "cpuThrottle": cpu_factor,
                "finishMode": finish_mode,
                "finishTargeted": state["finish"]["targeted"],
                "pointerMoves": 12, "raf": frames,
                "cdpPerformance": counters,
                "cdpDragOnly": drag_counters,
                "cdpPointerupAndSettle": settle_counters,
                "cdpTrace": groups,
                "paidGatewayRequests": 0, "productionFrameSLA": False}
    finally:
        if recording:
            # Preserve cleanup when a browser assertion fails mid-trace.
            try:
                cdp.send("Tracing.end")
            except Exception:
                pass
        cdp.detach()
        # A test-only override must not leak to subsequent product flows.
        try:
            page.evaluate("""() => {
              if(window.__HANDRAW_TESTING__===true)
                window.HANDRAW_STUDIO_TESTING.canvasDragFinishMode="auto";
            }""")
        except Exception:
            pass


def main() -> None:
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary)
        env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(path / "native-111.db"),
            "HANDRAW_PRIVATE_STORAGE": str(path / "private"),
            "HANDRAW_UPLOADS_DIR": str(path / "uploads"),
            "HANDRAW_GENERATED_DIR": str(path / "generated"),
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_ENABLE_RECHARGE": "0",
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_AI_CONFIG": str(path / "missing-paid-ai.json"),
            "HANDRAW_IMAGE_CONFIG": str(path / "missing-paid-image.json"),
        })
        env.start()
        db = server = worker = None
        try:
            db = init_database(path / "native-111.db")
            _, token = register_user(db, "native111_benchmark", "Pass12345!")
            cookie = f"{SESSION_COOKIE_NAME}={token}"
            server = create_channel_server(0, "main", db)
            server.allow_demo_routes = True
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            cases = [10, 50, 100, 300]
            for size in cases:
                graph = graph_fixture(size // 10)
                assert len(graph["nodes"]) == size
                assert len(graph["edges"]) == size // 2
                status, created = http_json(base, "/api/studio/projects", cookie,
                    "POST", {"projectId": f"qa111-native-{size}",
                             "idempotencyKey": f"qa111-create-{size}",
                             "kind": "image", "authority": "graph",
                             "title": f"QA111 native {size} nodes",
                             "draft": {"graph": graph, "activeView": "canvas"}})
                assert status == 200 and created.get("ok") is not False, (
                    "Project API rejected safe fixture", size, status, created)

            measurements = []
            with sync_playwright() as pw:
                binary = next((x for cmd in ("chromium", "google-chrome-stable",
                    "google-chrome", "chrome") if (x := shutil.which(cmd))), None)
                launch = {"headless": True,
                          "args": ["--no-sandbox", "--disable-dev-shm-usage",
                                   "--enable-precise-memory-info"]}
                if binary:
                    launch["executable_path"] = binary
                browser = pw.chromium.launch(**launch)
                try:
                    context = browser.new_context(viewport={"width": 1440, "height": 900},
                                                  device_scale_factor=1)
                    context.add_cookies([{"name": SESSION_COOKIE_NAME, "value": token,
                                         "url": base}])
                    for size in cases:
                        page = context.new_page()
                        page.add_init_script("window.__HANDRAW_TESTING__ = true")
                        errors, paid_posts = [], []
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        page.on("request", lambda r: paid_posts.append(r.method)
                            if r.method == "POST" and (
                                "/api/studio/generate" in r.url or
                                "/api/studio/run" in r.url) else None)
                        begin = time.perf_counter()
                        try:
                            page.goto(base + f"/studio/?project=qa111-native-{size}",
                                      wait_until="domcontentloaded", timeout=60000)
                            page.wait_for_function("""count => window.CS?.stageView==='canvas'
                              && window.CS?.graph?.nodes?.length===count
                              && document.querySelectorAll('#ic-nodes-layer .ic-node').length===count
                            """, arg=size, timeout=120000)
                            mount_ms = round((time.perf_counter() - begin) * 1000, 2)
                            native = page.evaluate(JS_MEASURE)
                            assert native["totalCards"] == size, native
                            assert native["edges"] == size // 2, native
                            assert native["focusHeld"], ("input focus lost on real canvas", size)
                            assert native["edgesStableOnTextOnly"], (
                                "text edit re-created unchanged SVG edge DOM", size)
                            assert native["stableUnrelatedNodes"] == size - 2, (
                                "single node edit replaced unrelated cards", size, native)
                            assert native["stableImages"] == native["imagesBefore"], (
                                "local images reloaded during one-node update", size, native)
                            assert native["imagesBefore"] >= size * 4 // 10, native
                            assert all(x["dirty"] == ["node:g00-0"] for x in native["updates"]), (
                                "one text edit touched extra nodes", size, native["updates"])
                            assert all(x["edgesRecomputed"] is False
                                       for x in native["updates"]), ("text-only dirty patch still recomputed all edges", size, native["updates"])
                            assert all(x["partial"] and x["nodes"] == 1
                                       for x in native["updates"]), (
                                "dirty rendering built extra node HTML", size, native["updates"])
                            assert all(not x["partial"] and x["nodes"] == size
                                       for x in native["fullUpdates"]), (
                                "full baseline did not build all cards", size)
                            assert native["fallbackFull"], (
                                "stale dirty ID failed to fall back safely", size)
                            assert len(native["statusDirty"]) <= 1, (
                                "one control status tick touched extra nodes", size, native["statusDirty"])
                            assert native["statusPartial"] and native["statusNodeCount"] == 1
                            assert native["restoredDirty"] in ([], ["node:g00-7"]), native["restoredDirty"]
                            # The real zoom control must be pointer-reachable
                            # even with 30 output branches. Do not force-click or
                            # dispatch a JS event around a taskbar overlay.
                            zoom_hit = page.evaluate("""() => {
                              const btn=document.querySelector('#bl-zoom-in');
                              if(!btn)return {reachable:false,blocker:'missing-zoom'};
                              const box=btn.getBoundingClientRect();
                              const top=document.elementFromPoint(
                                box.left+box.width/2,box.top+box.height/2);
                              return {reachable:!!top&&(top===btn||btn.contains(top)),
                                blocker:top?.id||top?.className?.toString()?.slice(0,70)||''};
                            }""")
                            assert zoom_hit["reachable"], ("zoom covered by Canvas task queue",size,zoom_hit)
                            native["zoomPointerReachable"] = True
                            # Keep observable baseline data in CI logs even when
                            # a subsequent physical pointer/UI assertion fails.
                            print("CANVAS #111 PRE-ZOOM " + json.dumps({
                                "nodes": size, "mountMs": mount_ms,
                                "dirtyPatchP95Ms": percentile(
                                    [x["ms"] for x in native["updates"]], .95),
                                "fullPatchP95Ms": percentile(
                                    [x["ms"] for x in native["fullUpdates"]], .95),
                                "stableImages": native["stableImages"],
                                "domElements": native["domElements"],
                                "statusMs": native["statusMs"]
                            }, ensure_ascii=False), flush=True)
                            # Actual UI zoom/camera path, measured separately from JS repaint.
                            page.evaluate("""() => {
                              const mini=document.getElementById('ic-minimap');
                              const node=mini?.querySelector('[data-mini-node-id]');
                              const lens=mini?.querySelector('[data-mini-lens]');
                              if(!node||!lens)throw Error('native minimap structure missing');
                              window.__studio111MiniRefs={node,lens};
                            }""")
                            zoom_ms = []
                            for _ in range(3):
                                tick = time.perf_counter()
                                page.locator("#bl-zoom-in").click(timeout=20000)
                                zoom_ms.append(round((time.perf_counter() - tick) * 1000, 2))
                            mini_camera_stable = page.evaluate("""() => {
                              const refs=window.__studio111MiniRefs;
                              const mini=document.getElementById('ic-minimap');
                              return !!refs && refs.node.isConnected && refs.lens.isConnected &&
                                mini.querySelector('[data-mini-node-id]')===refs.node &&
                                mini.querySelector('[data-mini-lens]')===refs.lens &&
                                mini.querySelector('[data-mini-zoom]')?.textContent?.endsWith('%');
                            }""")
                            assert mini_camera_stable, ("camera zoom rebuilt every minimap node",size)
                            native["minimapStableOnZoom"] = True
                            native["physicalDrag"] = measure_physical_drag(page, size)
                            # Full pipeline differs from handler-only p95.
                            # Keep the original 9-event regression unchanged.
                            if size in (100, 300):
                                if size == 300:
                                    native["legacyFullFramePipeline"] = profile_real_frame_pipeline(
                                        page, size, finish_mode="full")
                                native["framePipeline"] = profile_real_frame_pipeline(
                                    page, size, finish_mode="targeted")
                            if size == 300:
                                cdp = context.new_cdp_session(page)
                                try:
                                    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
                                    native["emulated4xCpuDrag"] = measure_physical_drag(
                                        page, size, cpu_factor=4)
                                    native["emulated4xLegacyFullFramePipeline"] = (
                                        profile_real_frame_pipeline(
                                            page, size, cpu_factor=4, finish_mode="full"))
                                    native["emulated4xFramePipeline"] = (
                                        profile_real_frame_pipeline(
                                            page, size, cpu_factor=4, finish_mode="targeted"))
                                finally:
                                    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
                                    cdp.detach()
                            if native.get("framePipeline"):
                                print("CANVAS #111 FULL FRAME PIPELINE " + json.dumps({
                                    "nodes": size, "normal": native["framePipeline"],
                                    "legacyFull": native.get("legacyFullFramePipeline"),
                                    "throttled": native.get("emulated4xFramePipeline"),
                                    "throttledLegacyFull": native.get("emulated4xLegacyFullFramePipeline"),
                                }, ensure_ascii=False), flush=True)
                            print("CANVAS #111 REAL POINTER DRAG " + json.dumps({
                                "nodes": size,
                                "normal": native["physicalDrag"],
                                "throttled": native.get("emulated4xCpuDrag"),
                            }, ensure_ascii=False), flush=True)
                            camera_stable = page.evaluate("""() => {
                              const root=document.querySelector('#ic-nodes-layer');
                              return root.querySelectorAll('.ic-node').length===window.CS.graph.nodes.length
                                && [...root.querySelectorAll('img')].every(img=>img.isConnected);
                            }""")
                            assert camera_stable, ("zoom removed graph cards", size)
                            # Exercise REAL product gallery callbacks rather than only
                            # the test-only render bridge. This mutates memory inside
                            # the disposable local Project page, never any media API.
                            gallery = page.evaluate("""() => {
                              const display=window.CS.graph.nodes.find(n=>n.id==='g00-8');
                              const root=document.getElementById('ic-nodes-layer');
                              const other=root.querySelector('[data-node-id="g00-9"]');
                              if(!display||!other)throw Error('gallery fixture unavailable');
                              display.data={...display.data,kind:'batch_gallery',
                                status:'success',totalTarget:8,
                                items:Array.from({length:8},(_,i)=>({
                                  status:'success',mediaId:'test-only-media-'+i,
                                  slotIndex:i,position:i,
                                  title:'本地静态回归图片',
                                  imageUrl:'/starter/bear-and-bird.webp'
                                }))};
                              const bridge=window.HANDRAW_STUDIO_TESTING;
                              const initial=bridge.renderCanvasNodesForBenchmark(['g00-8']);
                              let node=root.querySelector('[data-node-id="g00-8"]');
                              const toggle=node?.querySelector('[data-disp-toggle]');
                              if(!toggle)throw Error('real gallery toggle missing');
                              toggle.click();
                              const expanded=root.querySelector('[data-node-id="g00-8"]');
                              const expandPatch=root._lastCanvasPatchStats;
                              const compare=expanded?.querySelector('[data-disp-compare]');
                              if(!compare)throw Error('real gallery compare button missing');
                              compare.click();
                              const compared=root.querySelector('[data-node-id="g00-8"]');
                              const comparePatch=root._lastCanvasPatchStats;
                              return {
                                initPartial:initial.patch?.partial,
                                initCount:initial.patch?.nodes,
                                expanded:expanded?.querySelector('[data-disp-toggle]')?.getAttribute('aria-expanded'),
                                expandPartial:expandPatch?.partial,expandCount:expandPatch?.nodes,
                                comparePartial:comparePatch?.partial,compareCount:comparePatch?.nodes,
                                otherStable:other.isConnected&&root.querySelector('[data-node-id="g00-9"]')===other,
                                compareButton:compared?.querySelector('[data-disp-compare]')?.textContent
                              };
                            }""")
                            assert gallery["initPartial"] and gallery["initCount"] == 1, gallery
                            assert gallery["expanded"] == "true", gallery
                            assert gallery["expandPartial"] and gallery["expandCount"] == 1, gallery
                            assert gallery["comparePartial"] and gallery["compareCount"] == 1, gallery
                            assert gallery["otherStable"], gallery
                            assert gallery["compareButton"] == "取消对比", gallery
                            native["galleryTargetedCallbacks"] = gallery
                            assert not errors and not paid_posts, (size, errors, paid_posts)
                            native["nodePatchMs"] = [x["ms"] for x in native.pop("updates")]
                            native["nodePatchP95Ms"] = percentile(native["nodePatchMs"], .95)
                            native["fullNodePatchMs"] = [x["ms"] for x in native.pop("fullUpdates")]
                            native["fullNodePatchP95Ms"] = percentile(native["fullNodePatchMs"], .95)
                            native["zoomClickMs"] = zoom_ms
                            native["zoomClickP95Ms"] = percentile(zoom_ms, .95)
                            native["mountMs"] = mount_ms
                            native["nodes"] = size
                            native["expectedImageNodes"] = size * 4 // 10
                            native["paidGatewayPosts"] = 0
                            measurements.append(native)
                            print("CANVAS #111 REAL STUDIO " + json.dumps({
                                "nodes": size, "mountMs": mount_ms,
                                "dirtyPatchP95Ms": native["nodePatchP95Ms"],
                                "fullPatchP95Ms": native["fullNodePatchP95Ms"],
                                "zoomClickP95Ms": native["zoomClickP95Ms"],
                                "domElements": native["domElements"],
                                "usedJSHeapBytes": native["usedJSHeapBytes"],
                                "stableImages": native["stableImages"],
                            }, ensure_ascii=False), flush=True)
                        finally:
                            page.close()
                    output = ROOT / "artifacts" / "studio-111-native"
                    output.mkdir(parents=True, exist_ok=True)
                    report = {"issue": 111,
                              "kind": "real-Studio-local-HTTP-Chromium",
                              "productionReleaseEvidence": False,
                              "paidGatewayCalls": 0,
                              "browser": browser.version,
                              "host": {"python": platform.python_version(),
                                       "system": platform.platform(),
                                       "machine": platform.machine()},
                              "measurements": measurements}
                    (output / "native-10-50-100-300.json").write_text(
                        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
                    assert [m["nodes"] for m in measurements] == cases
                    print("CANVAS #111 REAL STUDIO 10/50/100/300 PASS", flush=True)
                finally:
                    browser.close()
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if worker:
                worker.join(timeout=5)
            if db:
                db.close()
            env.stop()


if __name__ == "__main__":
    main()
