"""#119 real Chromium: V3 read after reload/offline/online; no paid resubmit."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.generation_v3 import _upsert_media, ensure_run, refresh_run_status
from backend.server import SESSION_COOKIE_NAME, create_channel_server, init_database
from backend.services import register_user


def main():
    from playwright.sync_api import sync_playwright
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    env = patch.dict(os.environ, {
        "HANDRAW_DB_PATH":str(root/"studio119.sqlite"),
        "HANDRAW_PRIVATE_STORAGE":str(root/"storage"),
        "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
        "HANDRAW_GENERATED_DIR":str(root/"generated"),
        "HANDRAW_DEMO_MODE":"1",
    })
    env.start()
    server=None
    db=None
    thread=None
    try:
        db = init_database(root/"studio119.sqlite")
        alice, token = register_user(db,"canvas_browser_119","Pass12345!")
        uid = int(alice["id"])
        with db.transaction() as tx:
            run_id = ensure_run(
                tx,user_id=uid,source="web",
                external_run_id="browser-119",expected_count=6,
            )
            now="2026-11-08T00:00:00Z"
            for i in range(5):
                success=i<3
                media_id=_upsert_media(tx,owner_id=uid,
                    url=f"/generated/fixture-119-{i}.webp",sha256="") if success else None
                tx.execute(
                    """INSERT INTO generation_items
                       (id,run_id,position,status,media_id,error_code,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (f"run119-{i}",run_id,i*1000,"success" if success else "failed",
                     media_id,"" if success else "gateway_failed",now,now),
                )
            tx.execute(
                """INSERT INTO studio_generations
                   (id,user_id,username,tab_title,mode,prompt,items_json,engine,status,
                    created_at,batch_id,batch_index,batch_total,task_id,request_id)
                   VALUES (?,?,?,?,?,'','[]','live',?,?,?,?,?,?,?)""",
                ("attempt-browser-119",uid,alice["username"],"Browser 119","pure",
                 "queued","2026-01-01T00:00:00Z","browser-119",5,6,
                 "upstream-browser-119","req-browser-119"),
            )
            refresh_run_status(tx,run_id)
        server=create_channel_server(0,"main",db)
        server.allow_demo_routes=True
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base=f"http://127.0.0.1:{server.server_port}"
        with sync_playwright() as pw:
            binary=next((p for cmd in ("chromium","google-chrome-stable",
                "google-chrome","chrome") if (p:=shutil.which(cmd))),None)
            config={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
            if binary:config["executable_path"]=binary
            browser=pw.chromium.launch(**config)
            context=browser.new_context(viewport={"width":1440,"height":900})
            context.add_cookies([{"name":SESSION_COOKIE_NAME,"value":token,"url":base}])
            page=context.new_page()
            page.add_init_script("window.__HANDRAW_TESTING__ = true")
            errors=[]
            charged_posts=[]
            checked_tasks=[]
            page.on("pageerror",lambda exc:errors.append(str(exc)))
            page.on("request",lambda req:charged_posts.append(req.url)
                    if req.method=="POST" and "/api/studio/generate" in req.url else None)
            page.route("**/api/studio/tasks?*",lambda route:(
                checked_tasks.append(route.request.url),
                route.fulfill(status=200,content_type="application/json",
                              body=json.dumps({"status":"queued","images":[]}))))
            page.goto(base+"/studio/?entry=canvas",wait_until="networkidle",timeout=30000)
            page.locator('.ic-tmpl-card-btn[data-tmpl-bp="single"]').click(timeout=15000)
            page.locator("#ic-nodes-layer .ic-node").first.wait_for(timeout=15000)
            assert page.evaluate("() => !!window.HANDRAW_STUDIO_TESTING")
            # This is a real persisted Run. The testing hook only attaches its
            # identity to an existing Canvas output control: no fake images,
            # no POST /generate, no additional Project.
            ctrl_id=page.evaluate("""(runId)=>{
              const tab=window.CS.tabs.find(t=>t.id===window.CS.activeTabId);
              const ctrl=window.CS.graph.nodes.find(n=>n.type==='output_control');
              ctrl.data.runId=runId;
              tab.graph=JSON.parse(JSON.stringify(window.CS.graph));
              const tabs=window.CS.tabs.map(t=>({
                id:t.id,title:t.title,blueprint:t.blueprint,
                savedId:t.savedId||null,dirty:false,
                vx:t.vx,vy:t.vy,vk:t.vk,graph:t.graph,
                editorLayout:t.editorLayout||null,projectActiveView:'canvas'
              }));
              window.HANDRAW_STUDIO_TESTING.writeScopedCache(
                'handraw_open_tabs_v10',{activeTabId:tab.id,tabs}
              );
              window.dispatchEvent(new Event('online'));
              return ctrl.id;
            }""",run_id)
            page.wait_for_function(
              "() => document.querySelector('#canvas-129-taskbar')?.textContent?.includes('3/6')",
              timeout=12000)
            assert "远端待核实" in page.locator("#canvas-129-taskbar").inner_text()
            assert not charged_posts,charged_posts

            context.set_offline(True)
            page.evaluate("() => window.dispatchEvent(new Event('online'))")
            page.wait_for_function(
              "() => document.querySelector('#canvas-129-taskbar')?.textContent?.includes('远端状态待核实')",
              timeout=12000)
            assert not charged_posts
            context.set_offline(False)
            page.evaluate("() => window.dispatchEvent(new Event('online'))")
            page.wait_for_function(
              "() => document.querySelector('#canvas-129-taskbar')?.textContent?.includes('3/6')",
              timeout=12000)
            # Recheck polls only known taskId, never POSTs a new billable job.
            page.locator("#canvas-129-taskbar [data-c129=tasks]").click()
            page.locator(f'#canvas-129-taskbar [data-c129=recheck][data-control="{ctrl_id}"]').click()
            page.wait_for_timeout(650)
            assert checked_tasks and not charged_posts,(checked_tasks,charged_posts)

            # Browser reload recovers the same immutable Run from V3.
            page.reload(wait_until="networkidle",timeout=30000)
            page.wait_for_function(
              "() => document.querySelector('#canvas-129-taskbar')?.textContent?.includes('3/6')",
              timeout=15000)
            assert not charged_posts,charged_posts
            owner_run=context.request.get(base+"/api/studio/runs/"+run_id)
            assert owner_run.ok,owner_run.status
            data=owner_run.json()
            assert data["projection"]["succeeded"]==3,data
            assert data["projection"]["failed"]==2,data
            assert data["projection"]["unknown"]==1,data
            assert len(data["attempts"])==1,data
            # An abandoned local cancel must not mutate remote Run facts.
            page.evaluate("""(ctrlId) => window.HANDRAW_STUDIO.cancelActiveBatchGeneration(ctrlId)""",ctrl_id)
            after=context.request.get(base+"/api/studio/runs/"+run_id).json()
            assert after["projection"]==data["projection"]
            assert not errors,errors
            out=ROOT/"artifacts"/"canvas-119-screen"
            out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/"runtime-recovery.png"),animations="disabled")
            (out/"runtime-119.json").write_text(
                json.dumps({"result":"PASS","runId":run_id,
                    "succeeded":3,"failed":2,"unknown":1,
                    "polls":len(checked_tasks),"paidPosts":len(charged_posts)},
                    ensure_ascii=False,indent=2),encoding="utf-8")
            print("STUDIO #119 REAL CHROMIUM RESTORE/OFFLINE/RECHECK PASS")
            browser.close()
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if thread:thread.join(timeout=3)
        if db:db.close()
        env.stop()
        temp.cleanup()


if __name__=="__main__":
    main()
