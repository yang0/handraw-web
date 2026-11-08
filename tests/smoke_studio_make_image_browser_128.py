"""#128 real Chromium UI smoke: authenticated quick editor, persisted media,
responsive layout, controlled focus, no paid generation requests.
This does not substitute for live image provider / billing E2E.
"""
from __future__ import annotations
import json
import os
import shutil
import tempfile
import threading
import sys
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.server import SESSION_COOKIE_NAME,create_channel_server,init_database
from backend.services import register_user
from backend.generation_v3 import ensure_run,_upsert_media,refresh_run_status

def main():
    from playwright.sync_api import sync_playwright
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        env=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(root/"studio128.sqlite"),
            "HANDRAW_PRIVATE_STORAGE":str(root/"storage"),
            "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
            "HANDRAW_GENERATED_DIR":str(root/"generated"),
            "HANDRAW_DEMO_MODE":"1"
        })
        env.start()
        server=None;db=None;thread=None
        try:
            (root/"generated").mkdir(parents=True,exist_ok=True)
            db=init_database(root/"studio128.sqlite")
            alice,token=register_user(db,"quick_browser_128","Pass12345!")
            uid=int(alice["id"])
            entries=[]
            with db.transaction() as tx:
                for i in range(2):
                    filename=f"fixture-128-{i}.webp"
                    url=f"/generated/{filename}"
                    Image.new("RGB",(220,300 if i==0 else 180),
                        (220-i*45,206-i*18,195+i*22)).save(root/"generated"/filename,"WEBP")
                    run_id=ensure_run(tx,user_id=uid,source="web",
                        external_run_id=f"quick-browser-128-{i}",expected_count=1)
                    media_id=_upsert_media(tx,owner_id=uid,url=url,sha256="")
                    now="2026-11-08T00:00:00Z"
                    tx.execute("""INSERT INTO generation_items
                      (id,run_id,position,status,media_id,error_code,created_at,updated_at)
                      VALUES (?,?,?,?,?,?,?,?)""",
                      (f"quick128-item-{i}",run_id,0,"success",media_id,"",now,now))
                    refresh_run_status(tx,run_id)
                    entries.append({"key":media_id,"mediaId":media_id,
                        "runId":run_id,"imageUrl":url,
                        "title":f"第 {i+1} 个真实媒体",
                        "recipeSnapshot":{"subject":f"原稿 {i+1}","ratio":"3:4" if i==0 else "16:9",
                         "style":{"id":"FA-001","type":"style"},"layout":{"id":"SC-021","type":"layout"},
                         "outputMode":"graphic-text"}})
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as pw:
                binary=next((p for cmd in ("chromium","google-chrome-stable",
                    "google-chrome","chrome") if (p:=shutil.which(cmd))),None)
                options={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
                if binary:options["executable_path"]=binary
                browser=pw.chromium.launch(**options)
                ctx=browser.new_context(viewport={"width":1440,"height":900})
                ctx.add_cookies([{"name":SESSION_COOKIE_NAME,"value":token,"url":base}])
                page=ctx.new_page()
                page.add_init_script("window.__HANDRAW_TESTING__ = true")
                errors=[];paid=[]
                page.on("pageerror",lambda exc:errors.append(str(exc)))
                page.on("request",lambda req:paid.append(req.url)
                    if req.method=="POST" and "/api/studio/generate" in req.url else None)
                page.goto(base+"/studio/?entry=quick",wait_until="networkidle",timeout=45000)
                page.locator("#make-image-subject").wait_for(timeout=20000)
                assert page.locator(".make-image-workspace-layout").count()==1
                assert page.locator("#make-image-ref-dropzone").count()==1
                assert page.locator("#make-image-ratio-input").count()==1
                assert page.locator("#make-image-btn-run").count()==1
                desktop=page.locator(".make-image-workspace-layout").evaluate(
                    "(el)=>getComputedStyle(el).gridTemplateColumns")
                assert len(desktop.split(" "))>=2,desktop
                # Seed two real owned V3 media identities into the project's
                # persisted quick version index (no synthetic paid generation).
                page.evaluate("""versions=>{
                  const ctrl=window.CS.graph.nodes.find(n=>n.type==='output_control');
                  const skill=window.CS.graph.nodes.find(n=>n.type==='skill_params');
                  ctrl.data.quickVersionHistory=versions;
                  ctrl.data.ratio='2.35:1';ctrl.data.ratioSource='user';
                  skill.data.layout='SC-021';
                  const tab=window.CS.tabs.find(t=>t.id===window.CS.activeTabId);
                  tab.graph=JSON.parse(JSON.stringify(window.CS.graph));
                  const tabs=window.CS.tabs.map(t=>({
                    id:t.id,title:t.title,blueprint:t.blueprint,
                    savedId:t.savedId||null,dirty:false,
                    vx:t.vx,vy:t.vy,vk:t.vk,graph:t.graph,
                    editorLayout:t.editorLayout||null,
                    projectActiveView:'simple',
                    quickStart:t.quickStart||false
                  }));
                  window.HANDRAW_STUDIO_TESTING.writeScopedCache(
                    'handraw_open_tabs_v10',{activeTabId:tab.id,tabs});
                }""",entries)
                page.reload(wait_until="networkidle",timeout=45000)
                page.locator(".make-image-version-tile").first.wait_for(timeout=15000)
                assert page.locator(".make-image-version-tile").count()==2
                assert page.locator("#make-image-primary-media").get_attribute("src")==entries[1]["imageUrl"]
                assert page.locator("#make-image-ratio-input").input_value()=="2.35:1"
                page.locator("[data-quick-version]").first.click()
                assert page.locator("#make-image-primary-media").get_attribute("src")==entries[0]["imageUrl"]
                page.locator('[data-quick-action="recipe"]').click()
                assert "原稿 1" in page.locator(".make-image-recipe-snapshot").inner_text()
                page.locator('[data-quick-action="compare"]').click()
                assert page.locator(".make-image-compare-grid img").count()==2
                page.locator("#make-image-more-toggle").click()
                assert page.locator("#make-image-sc021-select").count()==1
                # An unrelated runtime render must not replace the successful
                # HTMLImageElement or erase an in-progress, focused textarea.
                page.locator("#make-image-subject").fill("仍在编辑的下一轮草稿")
                retained=page.evaluate("""()=>{
                  window.__oldImage128=document.querySelector('#make-image-primary-media');
                  const editor=document.querySelector('#make-image-subject');
                  editor.focus();editor.setSelectionRange(3,6);
                  window.HandrawMakeImage.render();
                  return {focus:document.activeElement?.id,
                    same:window.__oldImage128===document.querySelector('#make-image-primary-media'),
                    value:document.querySelector('#make-image-subject')?.value,
                    from:document.querySelector('#make-image-subject')?.selectionStart};
                }""")
                assert retained["focus"]=="make-image-subject",retained
                assert retained["same"],retained
                assert retained["value"]=="仍在编辑的下一轮草稿",retained
                assert retained["from"]==3,retained
                out=ROOT/"artifacts"/"quick-128-screen"
                out.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(out/"desktop.png"),animations="disabled")
                page.set_viewport_size({"width":390,"height":844})
                page.locator("#make-image-settings-collapse").click()
                assert not page.locator(".make-image-main-grid").is_visible()
                assert page.locator("#make-image-primary-media").is_visible()
                assert page.locator(".make-image-version-tile").count()==2
                page.screenshot(path=str(out/"mobile.png"),animations="disabled")
                page.locator("#make-image-settings-collapse").click()
                assert page.locator("#make-image-subject").is_visible()
                ctx.set_offline(True)
                assert page.locator("#make-image-primary-media").count()==1
                ctx.set_offline(False)
                assert not paid,paid
                assert not errors,errors
                (out/"results.json").write_text(json.dumps({
                    "result":"PASS","versions":2,"paidRequests":len(paid),
                    "focusPreserved":retained["focus"],
                    "imageNodeStable":retained["same"],"viewportWidths":[1440,390]
                },ensure_ascii=False,indent=2),encoding="utf8")
                print("STUDIO #128 CHROMIUM DESKTOP/MOBILE, FOCUS AND VERSION SMOKE PASS")
                browser.close()
        finally:
            if server:server.shutdown();server.server_close()
            if thread:thread.join(timeout=3)
            if db:db.close()
            env.stop()

if __name__=="__main__":
    main()
