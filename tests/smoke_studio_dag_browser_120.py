"""#120 real Chromium smoke: two independent Canvas controls share one slot budget.
Local demo samples only; any POST to billable generation endpoint fails the test.
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

def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        env=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(root/"dag120.sqlite"),
            "HANDRAW_PRIVATE_STORAGE":str(root/"storage"),
            "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
            "HANDRAW_GENERATED_DIR":str(root/"generated"),
            "HANDRAW_DEMO_MODE":"1",
            "HANDRAW_ENABLE_RECHARGE":"0",
            "HANDRAW_AI_CONFIG":str(root/"no-ai-config.json"),
            "HANDRAW_IMAGE_CONFIG":str(root/"no-image-config.json")
        })
        env.start()
        db=server=thread=None
        try:
            db=init_database(root/"dag120.sqlite")
            _,token=register_user(db,"studio_dag_browser_120","Pass12345!")
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as pw:
                binary=next((p for command in ("chromium","google-chrome-stable",
                    "google-chrome","chrome") if (p:=shutil.which(command))),None)
                cfg={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
                if binary:cfg["executable_path"]=binary
                browser=pw.chromium.launch(**cfg)
                ctx=browser.new_context(viewport={"width":1366,"height":900})
                ctx.add_cookies([{"name":SESSION_COOKIE_NAME,"value":token,"url":base}])
                page=ctx.new_page()
                page.add_init_script("window.__HANDRAW_TESTING__ = true")
                errors=[];paid=[]
                page.on("pageerror",lambda e:errors.append(str(e)))
                page.on("request",lambda req:paid.append(req.url)
                    if req.method=="POST" and "/api/studio/generate" in req.url else None)
                page.goto(base+"/studio/?entry=canvas&demo_mode=1",
                          wait_until="networkidle",timeout=45000)
                page.locator('.ic-tmpl-card-btn[data-tmpl-bp="single"]').click(timeout=15000)
                page.locator("#ic-nodes-layer .ic-node").first.wait_for(timeout=15000)
                assert page.evaluate("() => !!window.HandrawStudioDAG120"),"DAG module missing"
                assert page.locator("#ic-dag-fail-policy").count()==1
                page.locator("#ic-dag-fail-policy").select_option("continue")
                original=page.evaluate("""() => {
                  const g=window.CS.graph;
                  const ctrl=g.nodes.find(n=>n.type==='output_control');
                  const style=g.nodes.find(n=>n.type==='skill_params');
                  const text=g.nodes.find(n=>n.type==='text_input');
                  if (!ctrl||!style||!text) throw new Error('preset nodes missing');
                  ctrl.data.count=5;
                  const second=JSON.parse(JSON.stringify(ctrl));
                  second.id='dag120-second-control';
                  second.title='第二独立分支';
                  second.data={...second.data,count:5,status:'idle'};
                  second.x=(ctrl.x||400)+100;second.y=(ctrl.y||200)+550;
                  g.nodes.push(second);
                  g.edges.push(
                    {id:'dag120-edge1',from:style.id,to:second.id},
                    {id:'dag120-edge2',from:text.id,to:second.id}
                  );
                  const tab=window.CS.tabs.find(t=>t.id===window.CS.activeTabId);
                  tab.graph=JSON.parse(JSON.stringify(g));
                  return {count:g.nodes.length,ctrlIds:[ctrl.id,second.id]};
                }""")
                assert len(original["ctrlIds"])==2,original
                page.evaluate("""() => {
                  window.__dag120Peak=0;
                  window.__dag120Timer=setInterval(()=>{
                    const p=window.HandrawStudioDAG120.defaultPool.snapshot();
                    window.__dag120Peak=Math.max(window.__dag120Peak,p.running);
                  },2);
                  window.__dag120Promise=window.HANDRAW_STUDIO.runDAGOutputControls()
                    .then(result=>{
                      clearInterval(window.__dag120Timer);
                      window.__dag120Result=result;
                      return result;
                    });
                }""")
                page.wait_for_function("() => !!window.__dag120Result",timeout=35000)
                data=page.evaluate("""() => ({
                  result:window.__dag120Result,
                  maxPool:window.__dag120Peak,
                  controls:window.CS.graph.nodes.filter(n=>n.type==='output_control')
                    .map(n=>({id:n.id,status:n.data.status})),
                  historyCount:window.CS.generationHistory?.length || 0,
                  panel:document.getElementById('ic-dag-panel')?.textContent||''
                })""")
                assert data["result"]["total"]==2,data
                assert data["result"]["succeeded"]==2,data
                assert data["result"]["slots"]["succeeded"]==10,data
                assert 1 <= data["maxPool"] <= 3,data
                assert "Graph Revision" in data["panel"],data
                assert not paid,paid
                assert not errors,errors
                out=ROOT/"artifacts"/"dag-120-screen"
                out.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(out/"desktop-1366.png"),animations="disabled")
                page.set_viewport_size({"width":360,"height":780})
                page.screenshot(path=str(out/"mobile-360.png"),animations="disabled")
                (out/"results.json").write_text(json.dumps({
                    "result":"PASS","graphRevision":data["result"]["revision"],
                    "controlCount":2,"completedSlots":10,
                    "peakSharedConcurrency":data["maxPool"],
                    "paidRequests":paid,"pageErrors":errors,
                    "viewports":[1366,360]
                },ensure_ascii=False,indent=2),encoding="utf8")
                print("STUDIO #120 CHROMIUM DAG: TWO CONTROLS, 10 SLOTS, SHARED CAP <=3, NO PAID API PASS")
                browser.close()
        finally:
            if server:server.shutdown();server.server_close()
            if thread:thread.join(timeout=3)
            if db:db.close()
            env.stop()

if __name__=="__main__":
    main()
