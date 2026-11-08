"""#86/#87 live Chromium navigation alignment and no-native-dialog regression.

Uses the real Studio CSS/JS served over local HTTP. Fixture cards are only
used to prove responsive grid CSS; dialogs exercise the production module and
the real image-form Reset event. No paid generation is submitted.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.server import SESSION_COOKIE_NAME,create_channel_server,init_database
from backend.services import register_user


def measure(page,stage,width):
    page.set_viewport_size({"width":width,"height":850})
    page.goto(page.context._qa_base + "/studio/?view=" + stage,
              wait_until="domcontentloaded",timeout=45000)
    page.locator("#ic-entry-bar").wait_for(timeout=20000)
    page.wait_for_function("(name) => window.CS?.stageView === name",arg=stage,timeout=20000)
    bar=page.locator(".ic-history-topbar" if stage=="history" else ".ic-wf-minimal-tools")
    bar.wait_for(state="visible",timeout=10000)
    page.evaluate("""(name) => {
      const inner=document.querySelector(name==='history'
        ?'.ic-history-stage .ic-hist-page-inner'
        :'.ic-workflows-stage .ic-wf-page-inner');
      const grid=document.createElement('div');
      grid.dataset.qaLayout=name;
      grid.className=name==='history'?'ic-hist-masonry-grid':'ic-wf-card-grid';
      inner.appendChild(grid);
      [230,130,270,170,210].forEach((height,i)=>{
        const card=document.createElement('article');
        card.className=name==='history'?'ic-hist-entry-card':'ic-wf-entry-card';
        card.textContent='受控卡片 '+(i+1);
        card.style.height=height+'px';
        grid.appendChild(card);
      });
    }""",stage)
    result=page.evaluate("""(stage) => {
      const nav=document.querySelector('#ic-entry-bar');
      const navRect=nav.getBoundingClientRect(),style=getComputedStyle(nav);
      const x=navRect.left+parseFloat(style.paddingLeft);
      const right=navRect.right-parseFloat(style.paddingRight);
      const bar=document.querySelector(stage==='history'
        ?'.ic-history-topbar':'.ic-wf-minimal-tools').getBoundingClientRect();
      const inner=document.querySelector(stage==='history'
        ?'.ic-hist-page-inner':'.ic-wf-page-inner').getBoundingClientRect();
      const grid=document.querySelector('[data-qa-layout="'+stage+'"]');
      const columns=getComputedStyle(grid).gridTemplateColumns.split(' ').length;
      const cards=[...grid.children].map(e=>{const r=e.getBoundingClientRect();
        return {x:r.x,y:r.y,w:r.width,h:r.height}});
      return {viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        nav:{left:x,right},bar:{left:bar.left,right:bar.right},
        inner:{left:inner.left,right:inner.right},
        columns,cards};
    }""",stage)
    expected=(5 if width>1400 else 4 if width>1100 else 3 if width>760
              else 2 if width>350 else 1) if stage=="history" else (
              3 if width>1000 else 2 if width>620 else 1)
    assert result["columns"]==expected,(stage,width,result)
    assert result["scrollWidth"]<=width+2,(stage,width,result)
    for key in ("bar","inner"):
        assert abs(result[key]["left"]-result["nav"]["left"])<=3,(stage,width,key,result)
        assert abs(result[key]["right"]-result["nav"]["right"])<=3,(stage,width,key,result)
    firstrow=min(3,expected)
    assert all(abs(card["y"]-result["cards"][0]["y"])<=3 for card in result["cards"][:firstrow]),(stage,width,result)
    assert all(result["cards"][i]["x"]<result["cards"][i+1]["x"] for i in range(firstrow-1)),(stage,width,result)
    return result


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as dirname:
        root=Path(dirname)
        env=patch.dict(os.environ,{
          "HANDRAW_DB_PATH":str(root/"qa86-87.sqlite"),
          "HANDRAW_PRIVATE_STORAGE":str(root/"private"),
          "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
          "HANDRAW_GENERATED_DIR":str(root/"generated"),
          "HANDRAW_DEMO_MODE":"1",
          "HANDRAW_AI_CONFIG":str(root/"absent-ai.json"),
          "HANDRAW_IMAGE_CONFIG":str(root/"absent-image.json"),
        })
        env.start()
        db=server=thread=None
        try:
            db=init_database(root/"qa86-87.sqlite")
            _,token=register_user(db,"library_dialogs_86","Pass12345!")
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as pw:
                binary=next((b for cmd in ("chromium","google-chrome-stable",
                  "google-chrome","chrome") if (b:=shutil.which(cmd))),None)
                opts={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
                if binary:opts["executable_path"]=binary
                browser=pw.chromium.launch(**opts)
                try:
                    context=browser.new_context(viewport={"width":1440,"height":850})
                    context._qa_base=base
                    context.add_cookies([{"name":SESSION_COOKIE_NAME,"value":token,"url":base}])
                    page=context.new_page()
                    page.add_init_script("window.__HANDRAW_TESTING__=true")
                    errors=[];native=[]
                    page.on("pageerror",lambda e:errors.append(str(e)))
                    page.on("dialog",lambda d:(native.append(d.type),d.dismiss()))
                    output=ROOT/"artifacts"/"legacy-86-87"
                    output.mkdir(parents=True,exist_ok=True)
                    positions={}
                    for name in ("history","workflows"):
                        positions[name]={}
                        for width in (1440,1360,1200,900,390):
                            metrics=measure(page,name,width)
                            positions[name][str(width)]=metrics
                            if width in (1440,390):
                                page.screenshot(path=str(output/f"{name}-{width}.png"),
                                                animations="disabled")
                    page.set_viewport_size({"width":1200,"height":850})
                    page.goto(base+"/studio/?entry=quick",wait_until="domcontentloaded")
                    page.locator("#make-image-subject").wait_for(timeout=20000)
                    assert page.evaluate("!!window.HandrawDialogs?.confirm")
                    field=page.locator("#make-image-subject")
                    field.fill("P0-87 取消不能清空")
                    page.locator("#make-image-btn-reset").click()
                    backdrop=page.locator(".hw-app-dialog-backdrop")
                    backdrop.wait_for(state="visible",timeout=10000)
                    assert field.input_value()=="P0-87 取消不能清空"
                    page.keyboard.press("Escape")
                    backdrop.wait_for(state="detached",timeout=10000)
                    assert field.input_value()=="P0-87 取消不能清空"
                    page.locator("#make-image-btn-reset").click()
                    backdrop.wait_for(state="visible")
                    backdrop.locator("button[data-primary]").click()
                    backdrop.wait_for(state="detached")
                    assert field.input_value()!="P0-87 取消不能清空"
                    # Real prompt with cancel and Enter never invokes browser native prompt.
                    page.evaluate("""() => {
                      window._qaDialog=null;
                      window.HandrawDialogs.prompt('输入名字','预设').then(
                        value=>window._qaDialog=value===null?'CANCEL':value);
                    }""")
                    page.locator(".hw-app-dialog input").fill("不要保存")
                    page.keyboard.press("Escape")
                    page.wait_for_function("() => window._qaDialog==='CANCEL'")
                    page.evaluate("""() => {
                      window._qaDialog=null;
                      window.HandrawDialogs.prompt('输入名字','预设').then(
                        value=>window._qaDialog=value);
                    }""")
                    page.locator(".hw-app-dialog input").fill("修改后的名字")
                    page.keyboard.press("Enter")
                    page.wait_for_function("() => window._qaDialog==='修改后的名字'")
                    # Check all main entrypoints load the in-app dialog module.
                    for page_path in ("/","/forum/","/admin/"):
                        page.goto(base+page_path,wait_until="domcontentloaded",timeout=45000)
                        assert page.evaluate("!!window.HandrawDialogs?.confirm"),page_path
                    assert not native,native
                    assert not errors,errors
                    (output/"browser-measurements.json").write_text(json.dumps({
                       "status":"PASS","issues":[86,87],
                       "scope":"real HTTP/Chromium/CSS and native-dialog-module",
                       "productionVerified":False,"browser":browser.version,
                       "measurements":positions,"nativeDialogEvents":native,
                       "unsafeAutoConfirm":False},ensure_ascii=False,indent=2)+"\n",
                       encoding="utf-8")
                    print("P0 #86/#87 Studio history/workflow layout, 1440/1360/1200/900/390, "
                          "async reset cancel/confirm, prompt Escape/Enter, all portals: PASS",flush=True)
                finally:browser.close()
        finally:
            if server:server.shutdown();server.server_close()
            if thread:thread.join(timeout=5)
            if db:db.close()
            env.stop()


if __name__=="__main__":main()
