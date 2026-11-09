"""#111: 300 native nodes / 150 edges / 120 DISTINCT decoded WebP stress.

A/B/A compares the original few repeatedly reused repository images against
120 unique in-memory variants of those repository images, with nearly equal
aggregate natural pixel counts. The inputs are local, never paid/generated
media, and are not committed, uploaded, or written to object storage.
Chromium trace remains private, bounded and discarded by the existing helper.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

from PIL import Image, ImageEnhance, ImageOps

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from backend.server import SESSION_COOKIE_NAME, create_channel_server, init_database
from backend.services import register_user
from smoke_studio_native_100_graph_112 import graph_fixture, http_json
from benchmark_studio_native_canvas_111 import profile_real_frame_pipeline

COUNT=120
SIZE=(960,960)
MEDIA_PREFIX="/starter/qa111-unique-"


def build_unique_webps():
    """Real image-derived, deterministic, distinct WebPs; bytes live in memory."""
    originals=sorted((ROOT/"demo"/"starter").glob("*.webp"))
    if len(originals)<2:
        raise AssertionError("heavy media test source images unavailable")
    payloads={}
    for i in range(COUNT):
        with Image.open(originals[i % len(originals)]) as original:
            source=original.convert("RGB")
            # Distinct crop, flip and brightness; NO generated artwork is shipped.
            enlarged=ImageOps.fit(source,(1040,1040),method=Image.Resampling.BICUBIC)
            dx=(i*17)%75
            dy=(i*29)%75
            img=enlarged.crop((dx,dy,dx+SIZE[0],dy+SIZE[1]))
            if i%3==0:
                img=ImageOps.mirror(img)
            img=ImageEnhance.Brightness(img).enhance(0.78+(i%17)*0.025)
            buffer=io.BytesIO()
            img.save(buffer,format="WEBP",quality=73,method=0)
            payloads[f"{MEDIA_PREFIX}{i:03}.webp"]=buffer.getvalue()
    digests=[hashlib.sha256(x).digest() for x in payloads.values()]
    assert len(payloads)==COUNT and len(set(digests))==COUNT, (
        "benchmark variants must have distinct compressed image identities"
    )
    return payloads


def as_unique_media(graph):
    index=0
    for node in graph["nodes"]:
        if node["type"]=="asset":
            for item in node["data"].get("items",[]):
                item["image"]=f"{MEDIA_PREFIX}{index:03}.webp"
                index+=1
        elif node["type"]=="output_display":
            for item in node["data"].get("items",[]):
                item["imageUrl"]=f"{MEDIA_PREFIX}{index:03}.webp"
                index+=1
    assert index==COUNT, ("wrong number of 300-node native media references",index)
    return graph


def case_result(page, mode):
    """Real Chrome with actual 120 WebP decode and physical paced mouse drag."""
    page.wait_for_function("""() => window.CS?.stageView==='canvas' &&
      window.CS?.graph?.nodes?.length===300 &&
      document.querySelectorAll('#ic-nodes-layer .ic-node').length===300
    """,timeout=120000)
    # Force decode to make the different bitmaps real, including offscreen media.
    media=page.evaluate("""async () => {
      const layer=document.getElementById('ic-nodes-layer');
      const imgs=[...layer.querySelectorAll('img')];
      await Promise.all(imgs.map(img=>img.decode()));
      return {
        nodes:layer.querySelectorAll('.ic-node').length,
        images:imgs.length,
        decoded:imgs.filter(img=>img.complete&&img.naturalWidth>0).length,
        distinctDecodedUrls:new Set(imgs.map(img=>img.currentSrc)).size,
        naturalPixels:imgs.reduce((v,img)=>v+img.naturalWidth*img.naturalHeight,0),
        // A lower bound on uncompressed RGBA bytes, NOT GPU allocation.
        estimatedRGBABytes:imgs.reduce((v,img)=>v+img.naturalWidth*img.naturalHeight*4,0),
        allConnected:imgs.every(img=>img.isConnected),
      };
    }""")
    assert media["nodes"]==300 and media["images"]==COUNT and media["decoded"]==COUNT,media
    assert media["distinctDecodedUrls"]==(COUNT if mode=="unique" else 2),(
        mode,media["distinctDecodedUrls"]
    )
    # Track DOM object identity only inside Chrome, never JSON serialize nodes.
    page.evaluate("""() => {
      const root=document.getElementById('ic-nodes-layer');
      const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      window.__qa111HeavyRefs={
        x:n.x,y:n.y,
        images:[...root.querySelectorAll('img')],
        cards:[...root.querySelectorAll('.ic-node')],
      };
    }""")
    metrics=profile_real_frame_pipeline(page,300,finish_mode="targeted")
    state=page.evaluate("""() => {
      const r=window.__qa111HeavyRefs;
      const root=document.getElementById('ic-nodes-layer');
      const current=[...root.querySelectorAll('img')];
      return {
        stableCards:r.cards.filter(el=>el.isConnected).length,
        stableImages:r.images.filter(el=>el.isConnected&&current.includes(el)).length,
        imageNodes:current.length,
        edgeGroups:document.querySelectorAll(
          '#ic-edges-svg g.ic-edge-group[data-edge-id]').length,
      };
    }""")
    assert state["stableCards"]==300 and state["stableImages"]==COUNT and (
        state["imageNodes"]==COUNT and state["edgeGroups"]==150
    ),(mode,state)
    page.keyboard.press("Control+z")
    undone=page.evaluate("""() => {
      const n=window.CS.graph.nodes.find(n=>n.id==='g00-0');
      return {x:n.x,y:n.y};
    }""")
    assert undone=={"x":before["x"],"y":before["y"]},(
        "real heavy-media drag Undo failed",mode,undone
    )
    return {
        "mode":mode,
        "media":media,
        "stableDom":state,
        "drag":{
            "physicalPointerMoves":metrics["pointerMoves"],
            "finishTargeted":metrics["finishTargeted"],
            "raf":metrics["raf"],
            "cdpDragOnly":metrics["cdpDragOnly"],
            "cdpPointerupAndSettle":metrics["cdpPointerupAndSettle"],
            "cdpTrace":metrics["cdpTrace"],
        },
        "paidGatewayPosts":0,
        "gpuPresentEvidence":False,
        "physicalLowEndDeviceEvidence":False,
    }


def main():
    from playwright.sync_api import sync_playwright
    distinct=build_unique_webps()
    with tempfile.TemporaryDirectory() as temp:
        basepath=Path(temp)
        env=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(basepath/"heavy111.sqlite"),
            "HANDRAW_PRIVATE_STORAGE":str(basepath/"private"),
            "HANDRAW_UPLOADS_DIR":str(basepath/"uploads"),
            "HANDRAW_GENERATED_DIR":str(basepath/"generated"),
            "HANDRAW_ALLOWED_ORIGINS":"http://trusted.test",
            "HANDRAW_ENABLE_RECHARGE":"0",
            "HANDRAW_DEMO_MODE":"1",
            "HANDRAW_AI_CONFIG":str(basepath/"missing-paid-ai.json"),
            "HANDRAW_IMAGE_CONFIG":str(basepath/"missing-paid-image.json"),
        })
        env.start()
        db=server=worker=None
        try:
            db=init_database(basepath/"heavy111.sqlite")
            _,token=register_user(db,"qa111_unique_media","Pass12345!")
            cookie=f"{SESSION_COOKIE_NAME}={token}"
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            worker=threading.Thread(target=server.serve_forever,daemon=True)
            worker.start()
            base=f"http://127.0.0.1:{server.server_port}"
            for kind in ("reused","unique"):
                graph=graph_fixture(30)
                if kind=="unique":
                    graph=as_unique_media(graph)
                ident=f"qa111-unique-webp-{kind}"
                status,data=http_json(base,"/api/studio/projects",cookie,"POST",{
                    "projectId":ident,
                    "idempotencyKey":f"qa111-unique-create-{kind}",
                    "kind":"image","authority":"graph",
                    "title":f"QA111 controlled media {kind}",
                    "draft":{"graph":graph,"activeView":"canvas"},
                })
                assert status==200 and data.get("ok") is not False,(kind,status,data)
            with sync_playwright() as pw:
                executable=next((p for cmd in (
                    "chromium","google-chrome-stable","google-chrome","chrome"
                ) if (p:=shutil.which(cmd))),None)
                options={"headless":True,"args":[
                    "--no-sandbox","--disable-dev-shm-usage",
                    "--enable-precise-memory-info",
                ]}
                if executable:
                    options["executable_path"]=executable
                browser=pw.chromium.launch(**options)
                try:
                    context=browser.new_context(viewport={"width":1440,"height":900},
                                                device_scale_factor=1)
                    context.add_cookies([{"name":SESSION_COOKIE_NAME,
                                         "value":token,"url":base}])
                    records=[]
                    for kind in ("reused","unique","reused"):
                        page=context.new_page()
                        page.add_init_script("window.__HANDRAW_TESTING__=true")
                        paid_posts=[]
                        page_errors=[]
                        requested=set()
                        def intercept(route):
                            path=urlparse(route.request.url).path
                            body=distinct.get(path)
                            if body is None:
                                route.abort()
                                return
                            requested.add(path)
                            route.fulfill(status=200,content_type="image/webp",
                                          body=body,headers={"Cache-Control":"no-store"})
                        page.route("**/starter/qa111-unique-*.webp",intercept)
                        page.on("pageerror",lambda e:page_errors.append(str(e)))
                        page.on("request",lambda r:paid_posts.append(r.url)
                                if r.method=="POST" and (
                                    "/api/studio/generate" in r.url or
                                    "/api/studio/run" in r.url) else None)
                        try:
                            actual="unique" if kind=="unique" else "reused"
                            page.goto(base+f"/studio/?project=qa111-unique-webp-{actual}",
                                      wait_until="domcontentloaded",timeout=60000)
                            page.set_default_timeout(120000)
                            outcome=case_result(page,actual)
                            outcome["sequence"]=len(records)+1
                            outcome["requestedUniqueMediaCount"]=len(requested)
                            assert len(requested)==(COUNT if actual=="unique" else 0),(
                                actual,len(requested))
                            assert not page_errors and not paid_posts,(
                                "browser errors/paid requests",actual,page_errors,paid_posts)
                            records.append(outcome)
                            print("CANVAS #111 UNIQUE MEDIA CASE "+json.dumps({
                                "mode":actual,"sequence":len(records),
                                "distinctURLs":outcome["media"]["distinctDecodedUrls"],
                                "decoded":outcome["media"]["decoded"],
                                "naturalPixels":outcome["media"]["naturalPixels"],
                                "styleMs":outcome["drag"]["cdpDragOnly"]["RecalcStyleDuration"],
                                "rafP95":outcome["drag"]["raf"]["frameGapP95Ms"],
                            }),flush=True)
                        finally:
                            page.close()
                    report={
                        "issue":111,
                        "kind":"real-native-Studio-Chromium-unique-media-A-B-A",
                        "browser":browser.version,
                        "host":{"python":platform.python_version(),
                                "system":platform.platform(),
                                "machine":platform.machine()},
                        "input":{"nodeCount":300,"edgeCount":150,"mediaNodes":COUNT,
                                 "distinctGeneratedWebPs":COUNT,
                                 "sourceCount":len(list((ROOT/"demo"/"starter").glob("*.webp"))),
                                 "inMemoryEncodedBytes":sum(map(len,distinct.values())),
                                 "imageSizePx":list(SIZE),
                                 "sourceType":"derived local test fixtures only"},
                        "records":records,
                        "rawTracePersisted":False,
                        "productionReleaseEvidence":False,
                        "productionFrameSLA":False,
                        "paidGatewayCalls":0,
                    }
                    out=ROOT/"artifacts"/"studio-111-native"/"heavy-unique-300.json"
                    out.parent.mkdir(parents=True,exist_ok=True)
                    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                                   encoding="utf-8")
                    assert len(records)==3
                    print("CANVAS #111 UNIQUE MEDIA A/B/A PASS",flush=True)
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


if __name__=="__main__":
    main()
