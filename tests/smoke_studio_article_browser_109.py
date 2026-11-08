"""#109 true Chromium article journey: import/edit, PlanSlot, CAS/offline,
preview and ZIP. The only images are local fixtures; no paid generation calls.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.server import SESSION_COOKIE_NAME, create_channel_server, init_database
from backend.services import register_user
from backend.generation_v3 import _upsert_media

ARTICLE = "# 茶山与四季\n\n西湖茶园春天的清晨。\n\n## 第一节 茶园\n\n微风吹过层层梯田。\n\n## 第二节 采茶\n\n采茶人走在山间。"

def main():
    from playwright.sync_api import sync_playwright
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        cfg=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(root/"article109.sqlite"),
            "HANDRAW_PRIVATE_STORAGE":str(root/"storage"),
            "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
            "HANDRAW_GENERATED_DIR":str(root/"generated"),
            "HANDRAW_DEMO_MODE":"1","HANDRAW_ENABLE_RECHARGE":"0",
            "HANDRAW_AI_CONFIG":str(root/"absent-ai-service.json"),
            "HANDRAW_IMAGE_CONFIG":str(root/"absent-image-service.json")
        })
        cfg.start()
        db=server=thread=None
        try:
            (root/"generated").mkdir(parents=True,exist_ok=True)
            db=init_database(root/"article109.sqlite")
            alice,token=register_user(db,"article_browser_109","Pass12345!")
            bob,other=register_user(db,"article_browser_bob_109","Pass12345!")
            fixture="article109-fixture.webp"
            Image.new("RGB",(240,160),(222,205,176)).save(root/"generated"/fixture,"WEBP")
            with db.transaction() as tx:
                uid=int(alice["id"])
                media_id=_upsert_media(tx,owner_id=uid,
                    url="/generated/"+fixture,sha256="")
                # Both V3 MediaAsset identity and the legacy URL ownership
                # mapping are needed: export-zip resolves private file bytes
                # through the existing secured /generated route.
                now="2026-11-08T00:00:00Z"
                tx.execute("INSERT INTO studio_generations (id,user_id,created_at) VALUES (?,?,?)",
                    ("article109-gen-fixture",uid,now))
                tx.execute("""INSERT INTO studio_generation_media
                    (id,generation_id,user_id,media_url,created_at)
                    VALUES (?,?,?,?,?)""",
                    ("article109-media-fixture","article109-gen-fixture",uid,
                     "/generated/"+fixture,now))
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as pw:
                binary=next((v for cmd in ("chromium","google-chrome-stable",
                    "google-chrome","chrome") if (v:=shutil.which(cmd))),None)
                launch={"headless":True,
                    "args":["--no-sandbox","--disable-dev-shm-usage"]}
                if binary:launch["executable_path"]=binary
                browser=pw.chromium.launch(**launch)
                paid=[];errors=[]
                def make_page(token):
                    ctx=browser.new_context(accept_downloads=True,
                        viewport={"width":1400,"height":900})
                    ctx.add_cookies([{"name":SESSION_COOKIE_NAME,"value":token,"url":base}])
                    page=ctx.new_page()
                    page.add_init_script("window.__HANDRAW_TESTING__ = true")
                    page.on("pageerror",lambda err:errors.append(str(err)))
                    page.on("request",lambda req:paid.append(req.url)
                        if req.method=="POST" and "/api/studio/generate" in req.url else None)
                    return ctx,page

                def article_state(page):
                    return page.evaluate("""() => {
                      const d=window.CS?.articleEditorDraft;
                      const a=window.CS?.myArticles?.find(x=>x.id===d?.id);
                      return {id:d?.id,title:d?.title,markdown:d?.markdown,
                        docRev:a?.documentRevision,planRev:a?.planRevision,
                        projectId:a?.projectId,revision:a?.projectRevision,
                        state:a?.projectSaveState,pending:!!a?.projectPending,
                        cards:(a?.cards||[]).map(c=>({id:c.id,anchorId:c.anchorId,
                          pos:c.afterBlockIdx,status:c.status,imageUrl:c.imageUrl}))};
                    }""")

                def get_project(page,project_id):
                    return page.evaluate("""async id => {
                      const r=await fetch('/api/studio/projects/'+encodeURIComponent(id),
                        {credentials:'include'});
                      return {status:r.status,body:await r.json()};
                    }""",project_id)

                def wait_synced(page,timeout=45000):
                    page.wait_for_function("""() => {
                      const d=window.CS?.articleEditorDraft;
                      const a=window.CS?.myArticles?.find(x=>x.id===d?.id);
                      return !!a?.projectId && a.projectSaveState==='synced' &&
                        Number(a.projectRevision)>=1 && !a.projectPending;
                    }""",timeout=timeout)
                ctx,page=make_page(token)
                page.goto(base+"/studio/?entry=article&subview=editor&demo_mode=1",
                    wait_until="networkidle",timeout=45000)
                page.locator("#editor-file-replace-inp").wait_for(state="attached",timeout=25000)
                # Real asynchronous import; success directly replaces editor, no
                # ordinary review modal.
                page.locator("#editor-file-replace-inp").set_input_files({
                    "name":"article109.md","mimeType":"text/markdown",
                    "buffer":ARTICLE.encode("utf-8")})
                page.wait_for_function("""()=>
                  window.CS?.articleEditorDraft?.markdown?.includes('采茶人走在山间')""",
                    timeout=60000)
                assert page.locator(".hw-document-review-overlay").count()==0
                imported=article_state(page)
                assert imported["markdown"].count("第二节")==1,imported
                print("109 import replaces editor: PASS",flush=True)

                textarea=page.locator(".ic-art-seg-ta").first
                textarea.wait_for(timeout=20000)
                textarea.fill(ARTICLE+"\n\n追加一句：保留我的正文。")
                textarea.evaluate("(element)=>element.blur()")
                wait_synced(page)
                online=article_state(page)
                project_id=online["projectId"]
                assert online["docRev"]>=1,online
                response=get_project(page,project_id)
                assert response["status"]==200,response
                assert "追加一句" in response["body"]["project"]["draft"]["article"]["markdown"]
                print("109 ArticleDocument Project CAS cloud ack: PASS",flush=True)

                # Model-only plan endpoint is replaced with an offline
                # deterministic response while keeping real Chromium review,
                # permission/selection, PlanSlot and editor integration.
                ai_ref=lambda ident,kind:{"id":ident,"type":kind,
                    "source":"official","version":"current"}
                def mock_ai_plan(route):
                    req=route.request.post_data_json
                    n=max(2,min(3,int(req.get("count") or 2)))
                    slots=[]
                    for i in range(n):
                        slots.append({
                            "slotId":f"article109-slot-{i}",
                            "order":i,"subject":("茶山春光封面" if i==0 else f"茶园章节插图 {i}"),
                            "role":"cover" if i==0 else "illustration",
                            "anchorId":"cover" if i==0 else f"article109-anchor-{i}",
                            "afterBlockIdx":-1 if i==0 else i,
                            "anchorText":"茶园章节",
                            "purpose":"用原创插图帮助读者理解文章",
                            "imageType":"scene",
                            "overrides":{"layout":ai_ref("SC-021","layout"),
                                "ratio":"2.35:1" if i==0 else "4:3"},
                            "reasons":{"subject":"衔接章节","layout":"视觉结构清晰","ratio":"与文章版面匹配"}
                        })
                    proposal={
                        "ok":True,"schemaVersion":1,"kind":"article",
                        "source":"model","phase":"review",
                        "baseRevision":req["baseRevision"],
                        "creationSpecPatch":{
                            "baseRevision":req["baseRevision"],
                            "changes":{"style":ai_ref("FA-001","style"),
                                "layout":ai_ref("SC-021","layout"),"ratio":"2.35:1"},
                            "reasons":{"style":"符合手绘主题",
                                "layout":"清晰的知识布局","ratio":"适配封面"},
                            "candidates":{"style":[{"id":"FA-001"}],"layout":[{"id":"SC-021"}]}
                        },
                        "planPatch":{"baseRevision":req["planRevision"],
                            "kind":"article","slots":slots},
                        "cost":{"generationStarted":False,"runCreated":False}
                    }
                    route.fulfill(status=200,content_type="application/json",
                        body=json.dumps(proposal,ensure_ascii=False))
                page.route("**/api/studio/ai-plan",mock_ai_plan)
                page.locator("#editor-btn-plan").click(timeout=15000)
                page.locator("[data-ai-confirm]").wait_for(timeout=20000)
                page.locator("[data-ai-confirm]").click()
                page.locator("[data-review-apply]").wait_for(timeout=20000)
                page.locator("[data-review-apply]").click()
                page.wait_for_function("""()=>window.CS?.articleEditorDraft?.cards?.length>0""",
                    timeout=20000)
                plan=article_state(page)
                assert len(plan["cards"])>=1,plan
                anchors=[c["anchorId"] for c in plan["cards"]]
                assert all(anchors) and len(set(anchors))==len(anchors),plan
                assert plan["markdown"].endswith("保留我的正文。"),plan
                wait_synced(page)
                plan_cloud=get_project(page,project_id)["body"]["project"]["draft"]
                assert [s["anchorId"] for s in plan_cloud["plan"]["slots"]]==anchors
                assert plan_cloud["article"]["markdown"]==plan["markdown"]
                print("109 PlanSlot anchors and article fidelity: PASS",flush=True)

                # Offline editing writes frozen private CAS outbox and reload
                # replays the same project, not a duplicate public Work.
                ctx.set_offline(True)
                page.locator(".ic-art-seg-ta").first.fill(ARTICLE+"\n\n离线追加：山泉声。")
                page.locator(".ic-art-seg-ta").first.evaluate("(el)=>el.blur()")
                page.wait_for_function("""()=>{
                  const d=window.CS.articleEditorDraft;
                  const a=window.CS.myArticles.find(x=>x.id===d.id);
                  return !!a?.projectPending && (a.projectSaveState==='error' ||
                    a.projectSaveState==='local_only');
                }""",timeout=20000)
                offline=article_state(page)
                assert offline["pending"] and offline["projectId"]==project_id
                ctx.set_offline(False)
                page.reload(wait_until="networkidle",timeout=45000)
                wait_synced(page)
                recovered=article_state(page)
                assert recovered["projectId"]==project_id,recovered
                assert "山泉声" in recovered["markdown"],recovered
                assert [c["anchorId"] for c in recovered["cards"]]==anchors,recovered
                print("109 offline reload CAS + anchor preservation: PASS",flush=True)

                # The same Article Project in a second browser uses the same
                # server revision, and cannot overwrite a stale first tab.
                second_ctx,second=make_page(token)
                second.goto(base+"/studio/?view=projects&demo_mode=1",
                    wait_until="networkidle",timeout=45000)
                second.locator(f"[data-pc-open='{project_id}']").click()
                second.locator(".ic-art-seg-ta").first.wait_for(timeout=20000)
                assert article_state(second)["projectId"]==project_id
                second.locator(".ic-art-seg-ta").first.fill(ARTICLE+"\n\n第二窗口确认稿。")
                second.locator(".ic-art-seg-ta").first.evaluate("(el)=>el.blur()")
                wait_synced(second)
                page.locator(".ic-art-seg-ta").first.fill(ARTICLE+"\n\n旧窗口的冲突稿。")
                page.locator(".ic-art-seg-ta").first.evaluate("(el)=>el.blur()")
                page.wait_for_function("""()=>{
                  const d=window.CS.articleEditorDraft;
                  return window.CS.myArticles.find(x=>x.id===d.id)?.projectSaveState==='conflict';
                }""",timeout=30000)
                page.locator("#editor-sync-retry").click()
                page.locator("#article109-copy").wait_for(timeout=15000)
                assert page.locator(".article109-conflict-diff").count()==1
                page.locator("#article109-copy").click()
                wait_synced(page)
                copied=article_state(page)
                assert copied["projectId"]!=project_id,copied
                assert "旧窗口的冲突稿" in copied["markdown"]
                assert "第二窗口确认稿" in json.dumps(
                    get_project(page,project_id),ensure_ascii=False)
                print("109 two-context Article CAS/diff/copy: PASS",flush=True)

                # Simulate one successful RunItem and one failed slot with an
                # actual owner MediaAsset fixture, then check preview + ZIP.
                # No provider request is sent and completed slots are retained.
                page.evaluate("""media => {
                  const d=window.CS.articleEditorDraft;
                  const art=window.CS.myArticles.find(a=>a.id===d.id);
                  const cards=art.cards;
                  cards[0].imageUrl='/generated/article109-fixture.webp';
                  cards[0].mediaId=media;cards[0].status='done';
                  if(cards.length>1){cards[1].status='error';cards[1].imageUrl='';}
                  d.cards=cards;
                  window.renderFullPreviewStage();
                }""",media_id)
                page.locator("#editor-switch-preview").click()
                page.locator(".ic-article-preview-sheet").wait_for(timeout=15000)
                assert page.locator(".ic-article-preview-sheet img").count()>=1
                page.locator("#preview-switch-editor").click()
                page.locator("#editor-btn-export").wait_for(timeout=15000)
                with page.expect_download(timeout=30000) as download:
                    page.locator("#editor-btn-export").click()
                path=root/"article109.zip"
                download.value.save_as(str(path))
                with zipfile.ZipFile(path) as z:
                    names=z.namelist()
                    assert any(n.endswith("article.md") for n in names),names
                    assert any(n.endswith("preview.html") for n in names),names
                    md=next(z.read(n).decode("utf-8") for n in names
                        if n.endswith("article.md"))
                    assert "旧窗口的冲突稿" in md
                    assert any(n.startswith("images/") for n in names),names
                print("109 preview, partial result + ZIP export: PASS",flush=True)

                ctx.clear_cookies()
                ctx.add_cookies([{"name":SESSION_COOKIE_NAME,"value":other,"url":base}])
                page.goto(base+"/studio/?view=projects",wait_until="networkidle",timeout=45000)
                assert get_project(page,project_id)["status"]==404
                assert get_project(page,copied["projectId"])["status"]==404
                private_read=page.evaluate("""async()=>await fetch(
                  '/generated/article109-fixture.webp',{credentials:'include'}).then(r=>r.status)""")
                assert private_read==404,private_read
                print("109 private article/media ACL and account switch: PASS",flush=True)
                assert not paid,paid
                assert not errors,errors
                out=ROOT/"artifacts"/"article-109-screen"
                out.mkdir(parents=True,exist_ok=True)
                second.screenshot(path=str(out/"article-preview.png"),
                    animations="disabled")
                (out/"results.json").write_text(json.dumps({
                    "result":"PASS","project":project_id,
                    "cloudRevision":recovered["revision"],
                    "slots":len(anchors),"copy":copied["projectId"],
                    "paidRequests":0,"zipContents":names
                },ensure_ascii=False,indent=2),encoding="utf-8")
                browser.close()
                print("STUDIO #109 REAL CHROMIUM ARTICLE JOURNEY PASS",flush=True)
        finally:
            if server:
                server.shutdown();server.server_close()
            if thread:thread.join(timeout=4)
            if db:db.close()
            cfg.stop()
if __name__=="__main__":
    main()
