"""#111: native 300-node Chromium with 120 *distinct* decoded local WebPs.

The existing 300-node benchmark repeats only two WebP URLs. This script
separately covers 120 uniquely encoded local media sources while preserving
real Studio Project HTTP loading, 150 SVG edges, undo and zero vendor calls.
Not production GPU/VRAM or R2/CDN/physical-device evidence.
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
from ops.canvas_frame_trace_111 import (
    delta_performance_metrics, summarize_raf_intervals,
)
from ops.canvas_unique_media_111 import make_distinct_webp, apply_distinct_media
from smoke_studio_native_100_graph_112 import graph_fixture, http_json


def profile_drag(page, cdp, cpu_factor=1):
    """Physical mouse movement, before-pointerup Style counters and rAF."""
    target = page.evaluate("""() => {
      if(window.__HANDRAW_TESTING__!==true)
        throw Error('native test-only drag access missing');
      window.HANDRAW_STUDIO_TESTING.focusCanvasNodeForBenchmark('g00-0');
      const node=document.querySelector('#ic-nodes-layer [data-node-id="g00-0"]');
      const head=node?.querySelector('.ic-node-header-above');
      const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      if(!node||!head||!n)throw Error('native drag target missing');
      // Undo may reconcile cards. Capture identities immediately before each
      // physical drag, not before a previous gesture or the next undo.
      window.__qa111MediaImageRefs=[
        ...document.querySelectorAll('#ic-nodes-layer img')];
      const r=head.getBoundingClientRect();
      for(const frac of [.15,.45,.7]){
        const x=r.left+r.width*frac, y=r.top+r.height*.5;
        const hit=document.elementFromPoint(x,y);
        if(hit?.closest('.ic-node')===node &&
            !hit.closest('button,input,textarea,select,label'))
          return {x,y,nodeX:n.x,nodeY:n.y};
      }
      throw Error('no real mouse-reachable header on 300-node canvas');
    }""")
    page.mouse.move(target["x"],target["y"])
    page.mouse.down()
    page.wait_for_timeout(80)
    page.evaluate("""() => {
      const probe={active:true,last:null,intervals:[]};
      window.__qa111MediaFrames=probe;
      function tick(t){
        if(!probe.active)return;
        if(probe.last!==null&&probe.intervals.length<150)
          probe.intervals.push(t-probe.last);
        probe.last=t;requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }""")
    before=cdp.send("Performance.getMetrics")
    started=time.perf_counter()
    try:
        for step in range(1,13):
            page.mouse.move(target["x"]+60*step/12,
                            target["y"]+30*step/12, steps=1)
            page.wait_for_timeout(20)
        drag_end=cdp.send("Performance.getMetrics")
        elapsed=round((time.perf_counter()-started)*1000,2)
    finally:
        page.mouse.up()
    page.wait_for_timeout(100)
    frames=page.evaluate("""() => {
      const p=window.__qa111MediaFrames;
      p.active=false;
      return p.intervals.slice();
    }""")
    state=page.evaluate("""() => {
      const layer=document.getElementById('ic-nodes-layer');
      const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      const card=layer.querySelector('[data-node-id="g00-0"]');
      const imgs=[...layer.querySelectorAll('img')];
      const pre=window.__qa111MediaImageRefs||[];
      return {
        x:n.x,y:n.y,left:card.style.left,top:card.style.top,
        cards:layer.querySelectorAll('.ic-node').length,
        edges:document.querySelectorAll('#ic-edges-svg g.ic-edge-group[data-edge-id]').length,
        images:imgs.length,
        imagesStable:pre.length===imgs.length&&pre.every((el,i)=>el===imgs[i]&&el.isConnected),
        allDecoded:imgs.every(i=>i.complete&&i.naturalWidth>0),
      };
    }""")
    assert state["x"]>target["nodeX"] and state["y"]>target["nodeY"],state
    assert state["cards"]==300 and state["edges"]==150 and state["images"]==120,state
    assert state["imagesStable"] and state["allDecoded"],state
    assert state["left"]==f'{state["x"]}px' and state["top"]==f'{state["y"]}px',state
    page.keyboard.press("Control+z")
    undo=page.evaluate("""() => {
      const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      return {x:n.x,y:n.y};
    }""")
    assert undo=={"x":target["nodeX"],"y":target["nodeY"]},(undo,target)
    return {
        "cpuThrottle":cpu_factor,"physicalMoves":12,"elapsedMs":elapsed,
        "cdpDragOnly":delta_performance_metrics(before,drag_end),
        "raf":summarize_raf_intervals(frames),
        "graphUndoAndMediaStable":True,
        "frameSLA":False,
    }


def open_project_and_measure(context, base, name, expected_unique, expected_pixels, throttle=False):
    page=context.new_page()
    page.add_init_script("window.__HANDRAW_TESTING__=true")
    errors, paid_posts=[],[]
    page.on("pageerror",lambda e: errors.append(str(e)))
    page.on("request",lambda req:paid_posts.append(req.method)
        if req.method=="POST" and (
            "/api/studio/generate" in req.url or "/api/studio/run" in req.url)
        else None)
    started=time.perf_counter()
    cdp=None
    try:
        page.goto(base+f"/studio/?project={name}",wait_until="domcontentloaded",timeout=60000)
        page.wait_for_function("""() => window.CS?.stageView==='canvas'
          && window.CS.graph.nodes.length===300
          && document.querySelectorAll('#ic-nodes-layer .ic-node').length===300
          && document.querySelectorAll('#ic-nodes-layer img').length===120
        """,timeout=120000)
        # Explicitly decode all image elements, even if outside viewport.
        page.evaluate("""async () => {
          const imgs=[...document.querySelectorAll('#ic-nodes-layer img')];
          await Promise.all(imgs.map(img=>img.decode()));
          window.__qa111MediaImageRefs=imgs;
        }""")
        decoded_ms=round((time.perf_counter()-started)*1000,2)
        images=page.evaluate("""() => {
          const imgs=window.__qa111MediaImageRefs;
          const perf=performance.memory;
          const src=new Set(imgs.map(i=>i.currentSrc));
          return {
            elements:imgs.length,uniqueUrls:src.size,
            decoded:imgs.filter(i=>i.complete&&i.naturalWidth>0).length,
            naturalPixels:imgs.reduce((sum,img)=>sum+img.naturalWidth*img.naturalHeight,0),
            jsHeapUsedBytes:perf?perf.usedJSHeapSize:null,
          };
        }""")
        assert images["elements"]==120 and images["decoded"]==120,images
        assert images["uniqueUrls"]==expected_unique,(images,expected_unique)
        assert images["naturalPixels"]==expected_pixels,(images,expected_pixels)
        cdp=context.new_cdp_session(page)
        cdp.send("Performance.enable")
        normal=profile_drag(page,cdp,cpu_factor=1)
        slowed=None
        if throttle:
            cdp.send("Emulation.setCPUThrottlingRate",{"rate":4})
            try:
                slowed=profile_drag(page,cdp,cpu_factor=4)
            finally:
                cdp.send("Emulation.setCPUThrottlingRate",{"rate":1})
        assert not errors and not paid_posts,(errors,paid_posts)
        return {
            "scenario":name.rsplit("-",1)[-1],
            "images":images,
            "loadAndDecodeMs":decoded_ms,
            "physicalDrag":normal,"simulated4xCpuDrag":slowed,
            "browserErrors":0,"paidGatewayRequests":0,
            "isolatedProjectWritesOnly":True,
        }
    finally:
        if cdp: cdp.detach()
        page.close()


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory(prefix="qa111-distinct-",
                                     dir=ROOT/"demo/starter") as static:
        static_path=Path(static)
        fixture=make_distinct_webp(static_path)
        assert fixture["count"]==120 and fixture["uniqueSha256"]==120,fixture
        with tempfile.TemporaryDirectory() as rootdir:
            root=Path(rootdir)
            with patch.dict(os.environ,{
                "HANDRAW_DB_PATH":str(root/"media111.sqlite"),
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
                    db=init_database(root/"media111.sqlite")
                    _,token=register_user(db,"qa111_distinct_images","Pass12345!")
                    cookie=f"{SESSION_COOKIE_NAME}={token}"
                    server=create_channel_server(0,"main",db)
                    server.allow_demo_routes=True
                    worker=threading.Thread(target=server.serve_forever,daemon=True)
                    worker.start()
                    base=f"http://127.0.0.1:{server.server_port}"
                    for key in ("reused","distinct"):
                        graph=graph_fixture(30)
                        # Both variants use identical 960x720 natural pixels,
                        # equal number of <img> nodes and the same geometry.
                        # Only the number of independent URL/decode entries varies.
                        urls=(fixture["urls"] if key=="distinct" else
                              [fixture["urls"][i%2] for i in range(120)])
                        count=apply_distinct_media(graph,urls)
                        assert count==120
                        project=f"qa111-media-{key}"
                        status,obj=http_json(base,"/api/studio/projects",cookie,
                            "POST",{"projectId":project,
                                    "idempotencyKey":f"{project}-create",
                                    "kind":"image","authority":"graph",
                                    "title":f"QA111 distinct media {key}",
                                    "draft":{"graph":graph,"activeView":"canvas"}})
                        assert status==200 and obj.get("ok") is not False,(key,status,obj)
                    with sync_playwright() as pw:
                        binary=next((x for cmd in (
                            "chromium","google-chrome-stable","google-chrome","chrome")
                            if (x:=shutil.which(cmd))),None)
                        launch={"headless":True,"args":[
                            "--no-sandbox","--disable-dev-shm-usage",
                            "--enable-precise-memory-info"]}
                        if binary:launch["executable_path"]=binary
                        browser=pw.chromium.launch(**launch)
                        try:
                            context=browser.new_context(
                                viewport={"width":1440,"height":900},device_scale_factor=1)
                            context.add_cookies([{"name":SESSION_COOKIE_NAME,
                                                 "value":token,"url":base}])
                            records=[
                                open_project_and_measure(context,base,"qa111-media-reused",2,
                                                         fixture["decodedPixelsExpected"]),
                                open_project_and_measure(context,base,"qa111-media-distinct",120,
                                                         fixture["decodedPixelsExpected"],throttle=True),
                                open_project_and_measure(context,base,"qa111-media-reused",2,
                                                         fixture["decodedPixelsExpected"]),
                            ]
                            assert all(r["paidGatewayRequests"]==0 for r in records)
                            report={
                                "issue":111,"phase":9,
                                "source":"real-Studio-local-HTTP-Chromium",
                                "browser":browser.version,
                                "environment":{"python":platform.python_version(),
                                    "platform":platform.platform()},
                                "fixture":{"count":120,
                                   "sourceFixtureCount":fixture["sourceFixtureCount"],
                                   "distinctEncodedSha256":fixture["uniqueSha256"],
                                   "encodedBytes":fixture["encodedBytes"],
                                   "naturalPixelsExpected":fixture["decodedPixelsExpected"]},
                                "comparisonOrder":"reused/distinct/reused",
                                "methods":"12 physical pointer moves; CDP counters; rAF callback gaps; all 120 decoded",
                                "pairedProductionPerformanceSLA":False,
                                "realCDN":False,"realGPUTextureMemory":False,
                                "physicalLowEndDevice":False,
                                "paidGatewayRequests":0,
                                "productionReleaseEvidence":False,
                                "records":records,
                            }
                            output=ROOT/"artifacts/studio-111-distinct-media"
                            output.mkdir(parents=True,exist_ok=True)
                            (output/"summary.json").write_text(
                                json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                                encoding="utf-8")
                            print("CANVAS #111 120 DISTINCT WEBP " + json.dumps({
                                "unique":fixture["uniqueSha256"],
                                "pixels":fixture["decodedPixelsExpected"],
                                "cases":[{"scenario":r["scenario"],
                                    "urls":r["images"]["uniqueUrls"],
                                    "styleMs":r["physicalDrag"]["cdpDragOnly"]["RecalcStyleDuration"],
                                    "rafP95":r["physicalDrag"]["raf"]["frameGapP95Ms"],
                                    "slowStyleMs":r["simulated4xCpuDrag"]["cdpDragOnly"]["RecalcStyleDuration"]
                                        if r["simulated4xCpuDrag"] else None,
                                    } for r in records],
                            },ensure_ascii=False),flush=True)
                        finally:
                            browser.close()
                finally:
                    if server:
                        server.shutdown()
                        server.server_close()
                    if worker:worker.join(timeout=5)
                    if db:db.close()


if __name__=="__main__":
    main()
