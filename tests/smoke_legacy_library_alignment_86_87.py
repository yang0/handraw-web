"""#86/#87 actual Chromium page alignment and workflow/history visual regression.

Live local HTTP + Studio app + shipped styles at 1440/1200/390. Does not
equate controlled local fixtures with a deployed, real-customer screenshot.
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
sys.path.insert(0,str(ROOT))
from backend.server import create_channel_server,init_database,SESSION_COOKIE_NAME
from backend.services import register_user


def main():
    from playwright.sync_api import sync_playwright
    out=ROOT/"artifacts"/"legacy-86-87"
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        env=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(root/"library.sqlite"),
            "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
            "HANDRAW_GENERATED_DIR":str(root/"generated"),
            "HANDRAW_PRIVATE_STORAGE":str(root/"private"),
            "HANDRAW_DEMO_MODE":"1",
            "HANDRAW_ENABLE_RECHARGE":"0",
        })
        env.start()
        db=server=thread=None
        try:
            db=init_database(root/"library.sqlite")
            _,token=register_user(db,"legacy_86_87","Pass12345!")
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            records=[]
            with sync_playwright() as pw:
                binary=next((b for cmd in ("chromium","google-chrome-stable",
                    "google-chrome","chrome") if (b:=shutil.which(cmd))),None)
                opts={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
                if binary:opts["executable_path"]=binary
                browser=pw.chromium.launch(**opts)
                try:
                    context=browser.new_context(viewport={"width":1440,"height":900})
                    context.add_cookies([{"name":SESSION_COOKIE_NAME,"value":token,"url":base}])
                    page=context.new_page()
                    page.add_init_script("window.__HANDRAW_TESTING__ = true")
                    failures=[]
                    page.on("pageerror",lambda e:failures.append(str(e)))
                    for width in (1440,1200,390):
                        page.set_viewport_size({"width":width,"height":900})
                        for view,stage,bar,inner,grid,expected in (
                            ("history","#ic-history-stage",".ic-history-topbar",
                             ".ic-hist-page-inner",".ic-hist-masonry-grid",
                             5 if width==1440 else 4 if width==1200 else 2),
                            ("workflows","#ic-workflows-stage",".ic-wf-minimal-tools",
                             ".ic-wf-page-inner",".ic-wf-card-grid",
                             3 if width>620 else 1),
                        ):
                            page.goto(base+"/studio/?view="+view,
                                      wait_until="domcontentloaded",timeout=60000)
                            page.wait_for_function(
                                "(v)=>window.CS?.stageView===v",arg=view,timeout=25000)
                            page.locator(stage+" "+bar).wait_for(timeout=20000)
                            page.locator(stage+" "+inner).wait_for(timeout=20000)
                            # Seed non-persisted cards only to verify real CSS
                            # layout tracks, retaining app-rendered navigation.
                            page.evaluate("""({stage,grid})=>{
                                const host=document.querySelector(stage+" "+grid);
                                if (!host) return;
                                if(!host.children.length){
                                    for(let i=0;i<3;i++){
                                        const card=document.createElement('article');
                                        card.className=grid.includes('wf-')?'ic-wf-entry-card':'ic-hist-entry-card';
                                        card.innerHTML='<div style="height:'+(130+i*55)+'px">QA 卡片 '+i+'</div>';
                                        host.appendChild(card);
                                    }
                                }
                            }""",{"stage":stage,"grid":grid})
                            measurement=page.evaluate("""({stage,bar,inner,grid})=>{
                                const element=(selector)=>document.querySelector(stage+" "+selector);
                                const rect=(node)=>{
                                    if(!node)return null;
                                    const r=node.getBoundingClientRect();
                                    return {x:r.x,right:r.right,width:r.width,y:r.y};
                                };
                                const nav=document.querySelector('#ic-entry-bar');
                                const navStyle=getComputedStyle(nav);
                                const stageNode=document.querySelector(stage);
                                const barNode=element(bar);
                                const innerNode=element(inner);
                                const gridNode=element(grid);
                                const gridCss=gridNode?getComputedStyle(gridNode):null;
                                return {
                                    width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
                                    nav:rect(nav),navPaddingLeft:parseFloat(navStyle.paddingLeft)||0,
                                    navPaddingRight:parseFloat(navStyle.paddingRight)||0,
                                    stage:rect(stageNode),bar:rect(barNode),inner:rect(innerNode),
                                    grid:rect(gridNode),
                                    columns:gridCss?gridCss.gridTemplateColumns.split(' ').filter(Boolean).length:0,
                                    cards:gridNode?[...gridNode.children].slice(0,3).map(rect):[],
                                    maxWidth:getComputedStyle(innerNode).maxWidth,
                                    pageGutter:getComputedStyle(stageNode).getPropertyValue('--ic-library-side-gap')
                                };
                            }""",{"stage":stage,"bar":bar,"inner":inner,"grid":grid})
                            assert measurement["nav"] and measurement["bar"] and measurement["inner"],measurement
                            nav=measurement["nav"]
                            left=nav["x"]+measurement["navPaddingLeft"]
                            right=nav["right"]-measurement["navPaddingRight"]
                            for name in ("bar","inner"):
                                section=measurement[name]
                                assert abs(section["x"]-left)<=2.1,(width,view,name,"left",measurement)
                                assert abs(section["right"]-right)<=2.1,(width,view,name,"right",measurement)
                            assert measurement["scrollWidth"]<=width+2,(width,view,measurement)
                            if measurement["grid"]:
                                assert measurement["columns"]==expected,(width,view,measurement)
                                if len(measurement["cards"])>=3:
                                    first,second,third=measurement["cards"]
                                    assert first["x"]<second["x"],(width,view,measurement)
                                    if expected>=3:
                                        assert second["x"]<third["x"],(width,view,measurement)
                            page.screenshot(path=str(out/f"{view}-{width}.png"),
                                            animations="disabled",full_page=True)
                            records.append({"view":view,"viewport":width,"geometry":measurement})
                    # #87 genuine in-page confirmation, not browser-native
                    # alert()/confirm()/prompt(): cancellation must preserve
                    # state and approval must be an explicit button gesture.
                    def open_confirm():
                        page.evaluate("""() => {
                          window.qaLegacyConfirmOutcome='pending';
                          window.HANDRAW_SHARED.confirmAction(
                            '不可撤销的敏感操作', {title:'确认操作',danger:true,
                            confirmText:'执行操作'}
                          ).then(v=>window.qaLegacyConfirmOutcome=v);
                        }""")
                        page.locator("dialog.hw-confirm-action-dialog").wait_for(
                            state="visible",timeout=12000)

                    native_dialogs=[]
                    page.on("dialog",lambda dlg:(native_dialogs.append(dlg.type),
                                                 dlg.dismiss()))
                    open_confirm()
                    page.locator("dialog.hw-confirm-action-dialog button").first.click()
                    page.wait_for_function(
                        "()=>window.qaLegacyConfirmOutcome===false",timeout=8000)
                    open_confirm()
                    page.locator("dialog.hw-confirm-action-dialog").press("Escape")
                    page.wait_for_function(
                        "()=>window.qaLegacyConfirmOutcome===false",timeout=8000)
                    open_confirm()
                    page.locator("dialog.hw-confirm-action-dialog button").last.click()
                    page.wait_for_function(
                        "()=>window.qaLegacyConfirmOutcome===true",timeout=8000)
                    assert not native_dialogs,native_dialogs
                    assert page.locator("dialog.hw-confirm-action-dialog").count()==0
                    assert not failures,failures
                    (out/"geometry.json").write_text(json.dumps({
                        "issue":[86,87],"result":"PASS",
                        "scope":"real-Chromium-local-Studio-navigation-and-shipped-CSS",
                        "deploymentVerified":False,
                        "browser":browser.version,"cases":records
                    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                    print("Issue #86/#87 Chromium 1440/1200/390 history/workflows "
                          "navigation gutters, responsive cards, scroll-width PASS")
                finally:
                    browser.close()
        finally:
            if server:server.shutdown();server.server_close()
            if thread:thread.join(timeout=5)
            if db:db.close()
            env.stop()


if __name__=="__main__":
    main()
