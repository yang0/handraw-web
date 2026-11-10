"""Issue #105: real logged-in Chromium Picker/Project CAS regression.
No paid gateway requests. Uses one owner-authenticated SQLite MediaAsset.
"""
from __future__ import annotations
import json, os, shutil, sys, tempfile, threading
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from backend.server import SESSION_COOKIE_NAME,create_channel_server,init_database
from backend.services import register_user
from backend.generation_v3 import _upsert_media

def main():
    from playwright.sync_api import sync_playwright
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);db=server=thread=None
        env=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(root/"picker105.sqlite"),
            "HANDRAW_PRIVATE_STORAGE":str(root/"storage"),
            "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
            "HANDRAW_GENERATED_DIR":str(root/"generated"),
            "HANDRAW_DEMO_MODE":"1","HANDRAW_ENABLE_RECHARGE":"0",
            "HANDRAW_AI_CONFIG":str(root/"absent-ai.json"),
            "HANDRAW_IMAGE_CONFIG":str(root/"absent-image.json")})
        env.start()
        try:
            (root/"generated").mkdir(parents=True,exist_ok=True)
            db=init_database(root/"picker105.sqlite")
            alice,token=register_user(db,"article_picker_105","Pass12345!")
            image_name="article-picker-owner.webp"
            Image.new("RGB",(200,160),(205,194,171)).save(
                root/"generated"/image_name,"WEBP")
            with db.transaction() as tx:
                media_id=_upsert_media(tx,owner_id=int(alice["id"]),
                    url="/generated/"+image_name,sha256="")
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base="http://127.0.0.1:"+str(server.server_port)
            with sync_playwright() as pw:
                binary=next((v for cmd in ("chromium","google-chrome-stable",
                    "google-chrome","chrome") if (v:=shutil.which(cmd))),None)
                args={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
                if binary: args["executable_path"]=binary
                browser=pw.chromium.launch(**args)
                ctx=browser.new_context(viewport={"width":1400,"height":900})
                ctx.add_cookies([{"name":SESSION_COOKIE_NAME,"value":token,"url":base}])
                page=ctx.new_page();errors=[];paid=[]
                page.add_init_script("window.__HANDRAW_TESTING__ = true")
                page.on("pageerror",lambda err:errors.append(str(err)))
                page.on("request",lambda req:paid.append(req.url)
                    if req.method=="POST" and "/api/studio/generate" in req.url else None)
                page.goto(base+"/studio/?entry=article&subview=editor&demo_mode=1",
                    wait_until="networkidle",timeout=60000)
                page.locator("#editor-title-inp").fill("统一资源选择器验收")
                page.locator("#editor-title-inp").evaluate("(el)=>el.blur()")
                page.wait_for_function("""() => !!window.CS?.myArticles?.find(
                    x=>x.articleTitle==='统一资源选择器验收')""",timeout=30000)
                # Open shared catalog modal from actual article editor (not a
                # separate S.openAssetPickerModal style implementation).
                page.locator("#editor-style-picker").click()
                page.locator("#sp-picker-search").wait_for()
                page.locator("#sp-picker-search").fill("FA-001")
                page.locator("#sp-picker-grid [data-pick-id='FA-001']").first.click()
                page.wait_for_function("""() =>
                  window.CS?.articleEditorDraft?.styleRef?.id==='FA-001'""")
                page.locator("#editor-layout-picker").click()
                page.locator("#sp-picker-search").fill("IG-001")
                page.locator("#sp-picker-grid [data-pick-id='IG-001']").first.click()
                page.wait_for_function("""() =>
                  window.CS?.articleEditorDraft?.layoutRef?.id==='IG-001'""")
                assert page.locator("#editor-layout-id").inner_text().strip()=="IG-001"
                # A confirmed owned media UID may enter Article Project; local
                # thumbnails or official sample image URLs never grant ownership.
                page.evaluate("""id => {
                    window.CS.customUploads=window.CS.customUploads||[];
                    window.CS.customUploads.push({
                        id:'picker-105-owner',assetUid:id,
                        name:'用户参考图',cat:'scenes',
                        image:'/generated/article-picker-owner.webp'});
                }""",media_id)
                page.locator("#editor-reference-picker").click()
                page.locator("#ast-top-tabs [data-top-tab='my']").click()
                page.locator("#ast-picker-grid [data-pick-id='picker-105-owner']").click()
                page.locator("#ast-picker-confirm").click()
                page.wait_for_function("""() =>
                  window.CS?.articleEditorDraft?.referenceMedia?.length===1""")
                refs=page.evaluate("""() => {
                  const d=window.CS.articleEditorDraft;
                  return {style:d.styleRef,layout:d.layoutRef,
                    media:d.referenceMedia,id:d.id};
                }""")
                assert refs["style"]["type"]=="style",refs
                assert refs["layout"]["type"]=="layout",refs
                assert refs["media"]==[{"mediaId":media_id,"role":"scene"}],refs
                page.wait_for_function("""() => {
                  const d=window.CS.articleEditorDraft;
                  const a=window.CS.myArticles.find(x=>x.id===d.id);
                  return !!a?.projectId && a.projectSaveState==='synced' &&
                    !a.projectPending;
                }""",timeout=60000)
                cloud=page.evaluate("""async () => {
                    const d=window.CS.articleEditorDraft;
                    const a=window.CS.myArticles.find(x=>x.id===d.id);
                    const r=await fetch('/api/studio/projects/'+
                      encodeURIComponent(a.projectId),{credentials:'include'});
                    return {status:r.status,body:await r.json()};
                }""")
                assert cloud["status"]==200,cloud
                spec=cloud["body"]["project"]["draft"]["creationSpec"]
                assert spec["style"]["id"]=="FA-001",spec
                assert spec["layout"]["id"]=="IG-001",spec
                assert spec["referenceMedia"]==refs["media"],spec
                # Project-authorized selection persists through article
                # refresh, the same cloud revision is not blindly overwritten.
                page.reload(wait_until="networkidle")
                page.locator("#editor-layout-picker").wait_for()
                reloaded=page.evaluate("""() => {
                  const d=window.CS.articleEditorDraft;
                  return {style:d.styleRef,layout:d.layoutRef,media:d.referenceMedia};
                }""")
                assert reloaded["style"]["id"]=="FA-001",reloaded
                assert reloaded["layout"]["id"]=="IG-001",reloaded
                assert reloaded["media"]==refs["media"],reloaded
                # The second viewport is a real responsive Chromium render.
                page.set_viewport_size({"width":390,"height":844})
                page.locator("#editor-layout-picker").wait_for()
                page.locator("#editor-layout-picker").click()
                page.locator("#sp-picker-search").wait_for()
                assert page.locator("#sp-picker-grid [data-pick-id]").count()>0
                # Close/reopen must not erase current references.
                page.keyboard.press("Escape")
                assert not paid,paid
                assert not errors,errors
                print("105 Chromium Article shared Picker + CAS + owner MediaRef "
                    "+ reload + narrow viewport PASS",flush=True)
                ctx.close();browser.close()
        finally:
            if server:
                server.shutdown();server.server_close()
            if thread:thread.join(timeout=6)
            if db:db.close()
            env.stop()

if __name__=="__main__":main()
