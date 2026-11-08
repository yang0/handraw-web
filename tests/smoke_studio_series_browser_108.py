"""#108 real Chromium: series PlanSlot card/table UX, responsive, run identity.
Offline V3 fixture only; deliberately no paid image generation.
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
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from backend.server import SESSION_COOKIE_NAME,create_channel_server,init_database
from backend.services import register_user
from backend.generation_v3 import ensure_run,_upsert_media,refresh_run_status


def main():
    from playwright.sync_api import sync_playwright
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        env=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(root/"studio108.sqlite"),
            "HANDRAW_PRIVATE_STORAGE":str(root/"storage"),
            "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
            "HANDRAW_GENERATED_DIR":str(root/"generated"),
            "HANDRAW_DEMO_MODE":"1",
        })
        env.start()
        server=None;db=None;thread=None
        try:
            (root/"generated").mkdir(parents=True,exist_ok=True)
            db=init_database(root/"studio108.sqlite")
            alice,token=register_user(db,"series_browser_108","Pass12345!")
            uid=int(alice["id"])
            with db.transaction() as tx:
                run_id=ensure_run(tx,user_id=uid,source="web",
                    external_run_id="browser-series-108",expected_count=6)
                now="2026-11-08T00:00:00Z"
                for i in range(5):
                    success=i<3
                    media_id=None
                    if success:
                        name=f"series108-{i}.webp"
                        Image.new("RGB",(220,300+i*20),
                            (200-i*22,203-i*13,190+i*18)).save(
                            root/"generated"/name,"WEBP")
                        media_id=_upsert_media(tx,owner_id=uid,
                            url=f"/generated/{name}",sha256="")
                    tx.execute("""INSERT INTO generation_items
                       (id,run_id,position,status,media_id,error_code,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                       (f"series108-item-{i}",run_id,i*1000,
                        "success" if success else "failed",media_id,
                        "" if success else "gateway_failed",now,now))
                refresh_run_status(tx,run_id)
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as pw:
                binary=next((p for cmd in (
                    "chromium","google-chrome-stable","google-chrome","chrome")
                    if (p:=shutil.which(cmd))),None)
                config={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
                if binary:config["executable_path"]=binary
                browser=pw.chromium.launch(**config)
                context=browser.new_context(viewport={"width":1440,"height":900})
                context.add_cookies([{"name":SESSION_COOKIE_NAME,"value":token,"url":base}])
                page=context.new_page()
                page.add_init_script("window.__HANDRAW_TESTING__ = true")
                errors=[];paid=[]
                page.on("pageerror",lambda exc:errors.append(str(exc)))
                page.on("request",lambda req:paid.append(req.url)
                    if req.method=="POST" and "/api/studio/generate" in req.url else None)
                page.goto(base+"/studio/?entry=batch",wait_until="networkidle",timeout=45000)
                try:
                    page.locator(".series108-board").wait_for(timeout=12000)
                except Exception:
                    debug=page.evaluate("""()=>{
                      const stage=document.querySelector('.ic-quick-stage');
                      const batch=document.querySelector('.batch-container');
                      return {url:location.href,stageView:window.CS?.stageView,
                        stageDisplay:stage&&getComputedStyle(stage).display,
                        batchCount:document.querySelectorAll('.batch-container').length,
                        quickCount:document.querySelectorAll('.make-image-container').length,
                        boardCount:document.querySelectorAll('.series108-board').length,
                        boardScript:typeof window.HandrawSeriesBoard108,
                        batchScript:typeof window.HandrawBatchCreate,
                        body:document.body.innerText.slice(0,1400),
                        root:document.querySelector('#studio-app-root')?.innerHTML.slice(0,500)};
                    }""")
                    print("SERIES108 BOOT DEBUG:",json.dumps(debug,ensure_ascii=False),
                        "PAGE_ERRORS:",errors,flush=True)
                    raise
                assert page.locator(".series108-layout").count()==1
                assert page.locator(".series108-card").count()>=3
                assert page.locator(".batch-action-bar").count()==1
                assert page.locator("#batch-btn-plan").count()==1
                assert page.locator("#batch-candidates").count()==1
                # Verify in-place editing does not create a new plan store.
                first=page.locator(".series108-card").first
                first_id=first.get_attribute("data-series-slot-card")
                subj=first.locator("[data-series-subject]")
                subj.fill("第 1 张：杭州春日旅行")
                subj.evaluate("(el)=>el.blur()")
                saved=page.evaluate("""slotId=>{
                  const loop=window.CS.graph.nodes.find(n=>n.type==='loop');
                  return {id:loop.data.studio2Plan.slots[0].slotId,
                    text:loop.data.studio2Plan.slots[0].subject,
                    projection:loop.data.batchRows[0].theme};
                }""",first_id)
                assert saved["id"]==first_id,saved
                assert saved["text"]==saved["projection"]=="第 1 张：杭州春日旅行",saved
                # Manual add/duplicate/order must not rewrite the stable original id.
                counts=[]
                for _ in range(6):
                    count=page.locator(".series108-card").count()
                    counts.append(count)
                    if count>=6:
                        break
                    page.locator('[data-series-action="add"]').click(timeout=5000)
                assert page.locator(".series108-card").count()==6, {
                    "cardCounts":counts,
                    "plan":page.evaluate("""()=>{
                      const loop=window.CS.graph.nodes.find(n=>n.type==='loop');
                      return {slots:loop.data.studio2Plan?.slots?.length,
                        rows:loop.data.batchRows?.length,stage:window.CS.stageView};
                    }"""),
                    "errors":errors
                }
                page.locator('[data-series-action="copy"][data-series-slot="'+first_id+'"]').click()
                assert page.locator(".series108-card").count()==7
                page.locator('[data-series-action="up"]').nth(1).click()
                ids=page.locator(".series108-card").evaluate_all(
                    "(items)=>items.map(el=>el.getAttribute('data-series-slot-card'))")
                assert len(ids)==len(set(ids))==7,ids
                assert first_id in ids
                # No destructive mode resets. View only hides the existing table.
                page.locator('[data-series-kind="compare"]').click()
                assert page.locator('[data-series-kind="compare"]').get_attribute("aria-pressed")=="true"
                page.locator('[data-series-kind="multi-format"]').click()
                page.locator('[data-series-action="ratios"]').click()
                ratios=page.evaluate("""()=>{
                  const slots=window.CS.graph.nodes.find(n=>n.type==='loop').data.studio2Plan.slots;
                  return slots.map(s=>s.overrides.ratio||"");
                }""")
                assert ratios[:4]==["3:4","1:1","9:16","16:9"],ratios
                page.locator('[data-series-view="table"]').click()
                assert page.locator(".batch-preview-section").is_visible()
                assert page.locator(".batch-edit-area").is_visible()
                page.locator('[data-series-view="cards"]').click()
                assert page.locator(".series108-card").count()==7
                # Freeze the seven-slot draft into a SIX-output test Run without
                # inventing media; keep only the first six in the snapshot.
                # The seven-slot view must not mis-assign any completed image
                # when the draft was reordered after the Run.
                injected=page.evaluate("""runId=>{
                  const graph=window.CS.graph;
                  const tab=window.CS.tabs.find(t=>t.id===window.CS.activeTabId);
                  const loop=graph.nodes.find(n=>n.type==='loop');
                  const ctrl=graph.nodes.find(n=>n.type==='output_control');
                  const slots=loop.data.studio2Plan.slots;
                  ctrl.data.studio2RunSnapshot={schemaVersion:1,
                    runId,batchId:"series108-browser",candidateCount:1,
                    outputCount:6,slotCount:6,
                    outputs:slots.slice(0,6).map((slot,i)=>({
                      slotId:slot.slotId,slotOrder:i,
                      candidateIndex:0,outputIndex:i,outputId:"fixture-"+i
                    }))};
                  ctrl.data.runId=runId;
                  tab.graph=JSON.parse(JSON.stringify(graph));
                  const tabs=window.CS.tabs.map(t=>({
                    id:t.id,title:t.title,blueprint:t.blueprint,
                    savedId:t.savedId||null,dirty:false,vx:t.vx,vy:t.vy,vk:t.vk,
                    graph:t.graph,editorLayout:t.editorLayout||null,
                    batchStart:t.batchStart||false,projectActiveView:"simple"
                  }));
                  window.HANDRAW_STUDIO_TESTING.writeScopedCache(
                    'handraw_open_tabs_v10',{activeTabId:tab.id,tabs});
                  return ctrl.data.studio2RunSnapshot.outputs.map(x=>x.slotId);
                }""",run_id)
                page.reload(wait_until="networkidle",timeout=45000)
                page.wait_for_function(
                    "() => document.querySelectorAll('.series108-image[data-series-media]').length === 3",
                    timeout=20000)
                visible=page.locator(".series108-card").evaluate_all(
                    "(nodes)=>nodes.filter(n=>n.querySelector('.series108-image'))"+
                    ".map(n=>n.getAttribute('data-series-slot-card'))")
                assert visible==injected[:3],(visible,injected)
                assert page.locator(".series108-state.failed").count()==2
                assert page.locator(".series108-candidate.failed [data-series-action=retry]").count()==0
                # All V3 identities are immutable; a runtime redraw must
                # retain the decoded node and the focused next draft.
                state=page.evaluate("""()=>{
                  const img=document.querySelector('.series108-image');
                  window.__series108OldImg=img;
                  const field=document.querySelector('[data-series-subject]');
                  field.focus();field.setSelectionRange(2,5);
                  const value=field.value;
                  window.HandrawBatchCreate.render();
                  const current=document.querySelector('[data-series-subject]');
                  return {same:img===document.querySelector('.series108-image'),
                    focus:document.activeElement===current,
                    caret:current.selectionStart,value:current.value,
                    expected:value};
                }""")
                assert state["same"] and state["focus"],state
                assert state["caret"]==2 and state["value"]==state["expected"],state
                out=ROOT/"artifacts"/"series-108-screen"
                out.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(out/"desktop.png"),animations="disabled")
                page.set_viewport_size({"width":390,"height":844})
                page.screenshot(path=str(out/"mobile.png"),animations="disabled")
                assert page.locator(".series108-card").first.is_visible()
                assert page.locator("#batch-btn-start").count()==1
                assert not paid,paid
                assert not errors,errors
                (out/"results.json").write_text(json.dumps({
                    "result":"PASS","runId":run_id,"ownedSuccess":3,
                    "failed":2,"unresolved":1,"paidRequests":0,
                    "focusedDraft":state["focus"],"mediaNodeStable":state["same"],
                    "widths":[1440,390]
                },ensure_ascii=False,indent=2),encoding="utf-8")
                print("STUDIO #108 REAL CHROMIUM CARD/TABLE, DESKTOP/MOBILE, V3 3+2+1 PASS")
                browser.close()
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if thread:thread.join(timeout=3)
            if db:db.close()
            env.stop()

if __name__=="__main__":
    main()
