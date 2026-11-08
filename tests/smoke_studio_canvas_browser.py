"""Studio #127 browser smoke: real Canvas entrypoint + synthetic mock backend.

Exercised without paid AI/generation: template launch, select node by pointer,
drag, zoom, autolayout, undo, redo, selection preservation, screenshot.
The heavier 10–300-node performance matrix is benchmark_studio_canvas.py.
"""
from __future__ import annotations

import argparse
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

from backend.server import create_channel_server, init_database


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--screenshots",default="artifacts/canvas-127-screen")
    args=parser.parse_args()
    from playwright.sync_api import sync_playwright
    tmp=tempfile.TemporaryDirectory()
    root=Path(tmp.name)
    env=patch.dict(os.environ,{
        "HANDRAW_DB_PATH":str(root/"canvas.db"),
        "HANDRAW_PRIVATE_STORAGE":str(root/"storage"),
        "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
        "HANDRAW_GENERATED_DIR":str(root/"generated"),
        "HANDRAW_DEMO_MODE":"1"
    })
    env.start()
    server=None
    browser=None
    pw=None
    thread=None
    db=None
    try:
        db=init_database(root/"canvas.db")
        server=create_channel_server(0,"main",db)
        server.allow_demo_routes=True
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        with sync_playwright() as pw:
            executable=next((p for n in ("chromium","google-chrome-stable",
                "google-chrome","chrome") if (p:=shutil.which(n))),None)
            args_chrome={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
            if executable: args_chrome["executable_path"]=executable
            browser=pw.chromium.launch(**args_chrome)
            page=browser.new_page(viewport={"width":1440,"height":900})
            errors=[]
            page.on("pageerror",lambda exc:errors.append(str(exc)))
            base=f"http://127.0.0.1:{server.server_port}"
            page.goto(base+"/studio/?entry=canvas",wait_until="networkidle",timeout=30000)
            page.evaluate("localStorage.clear();sessionStorage.clear()")
            page.goto(base+"/studio/?entry=canvas",wait_until="networkidle",timeout=30000)
            # #129: first use offers theme, assets, template without manual edges.
            assert page.locator("#canvas-129-first-form input[name=subject]").count()==1
            assert page.locator("#canvas-129-first-asset").count()==1
            assert page.locator("#canvas-129-first-template").count()==1
            page.locator('.ic-tmpl-card-btn[data-tmpl-bp="single"]').click(timeout=15000)
            page.locator("#canvas-129-topbar").wait_for(timeout=15000)
            assert page.locator("#canvas-129-topbar").is_visible()
            assert page.locator("#canvas-129-inspector").is_visible()
            assert page.locator("#canvas-129-taskbar").is_visible()
            assert page.locator('[data-shelf-tab="assets"]').count()==1
            assert page.locator('[data-shelf-tab="templates"]').count()==1
            assert page.locator("#canvas-129-topbar [data-c129=run]").is_enabled()
            # Six-image gallery markup in a real browser must collapse, expand,
            # expose only the failed third slot for retry, and keep real images.
            gallery=page.evaluate("""() => {
              const ui=window.HandrawCanvasUI;
              const items=Array.from({length:6},(_,i)=>({
                id:'i'+i,position:i*1000,slotIndex:i,
                status:i===2?'failed':'success',
                mediaId:i===2?'':'media'+i,
                imageUrl:i===2?'':'/images/poster-demo-autumn-equinox.webp'
              }));
              const slots=ui.slotSummary(items,6,'web');
              const node={id:'smoke-gallery',data:{totalTarget:6,kind:'batch_gallery',
                status:'done',items:items.map(i=>i.imageUrl?{imageUrl:i.imageUrl}:null)}};
              const projection={runId:'run-smoke',total:6,isTerminal:true,
                canRetry:true,slots};
              const before=ui.galleryHtml(node,projection);
              ui.toggleGallery('smoke-gallery');
              const after=ui.galleryHtml(node,projection);
              ui.toggleGallery('smoke-gallery');
              ui.toggleCompare('smoke-gallery',0);
              ui.toggleCompare('smoke-gallery',1);
              const compareCount=ui.selectedForCompare('smoke-gallery').length;
              return {compareCount,collapsed:before.includes('展开全部槽位'),
                expanded:after.includes('收起结果'),
                failedRetry:after.includes('data-slot="2"'),
                imageCount:(after.match(/data-disp-zoom=/g)||[]).length};
            }""")
            assert gallery["collapsed"] and gallery["expanded"] and gallery["failedRetry"],gallery
            assert gallery["imageCount"]==5,gallery
            assert gallery["compareCount"]==2,gallery
            page.locator("#ic-nodes-layer .ic-node").first.wait_for(timeout=15000)
            ids=page.locator("#ic-nodes-layer .ic-node").evaluate_all(
                "(nodes)=>nodes.map(n=>n.dataset.nodeId)")
            assert len(ids)>=3,ids
            assert len(set(ids))==len(ids),ids
            page.evaluate("""() => {
              window.__canvasStableNodes=[...document.querySelectorAll('#ic-nodes-layer .ic-node')];
              window.__canvasStableImgs=[...document.querySelectorAll('#ic-nodes-layer img')];
            }""")
            # Select an actual Canvas node through the viewport's pointer handler.
            node=page.locator("#ic-nodes-layer .ic-node").first
            box=node.bounding_box()
            assert box, "canvas node not measurable"
            page.mouse.click(box["x"]+30,box["y"]+15)
            selected=page.locator("#ic-nodes-layer .ic-node.is-selected").count()
            assert selected>=1,"canvas pointer selection not registered"
            assert page.evaluate("""() => window.__canvasStableNodes.every(el=>el.isConnected)
              && window.__canvasStableImgs.every(el=>el.isConnected)"""),"selection re-created nodes"
            # Drag selected card; expected geometry changes only, no removed images.
            before=page.locator("#ic-nodes-layer .ic-node").first.get_attribute("style")
            page.mouse.move(box["x"]+45,box["y"]+15)
            page.mouse.down()
            page.mouse.move(box["x"]+92,box["y"]+52,steps=7)
            page.mouse.up()
            after=page.locator("#ic-nodes-layer .ic-node").first.get_attribute("style")
            assert before!=after,"node drag did not update geometry"
            # Zoom/pan transforms are view-only and should not recreate children.
            page.locator("#bl-zoom-in").click()
            zoom=page.locator("#bl-zoom-pct").inner_text()
            assert "%" in zoom,zoom
            # Scrolling an editor input must not zoom the graph behind it.
            editor=page.locator("#ic-nodes-layer .ic-node input, #ic-nodes-layer .ic-node textarea").first
            if editor.count():
                editor.hover()
                previous_zoom=page.locator("#bl-zoom-pct").inner_text()
                page.mouse.wheel(0,325)
                page.wait_for_timeout(80)
                assert page.locator("#bl-zoom-pct").inner_text()==previous_zoom, "input wheel zoomed canvas"
            page.locator("#bl-arrange").click()
            page.locator("#bc-undo").click()
            page.locator("#bc-redo").click()
            new_ids=page.locator("#ic-nodes-layer .ic-node").evaluate_all(
                "(nodes)=>nodes.map(n=>n.dataset.nodeId)")
            assert set(new_ids)==set(ids),(ids,new_ids)
            # Visual notes are project editor metadata, never executable Graph nodes.
            page.locator('#canvas-129-topbar [data-c129="note"]').click()
            note=page.locator('#canvas-129-visual-layer [data-visual-note]').first
            note.wait_for(timeout=5000)
            note.locator('textarea').fill("这个框是视觉便签，不是执行节点")
            assert page.locator("#ic-nodes-layer .ic-node").count()==len(ids)
            assert page.locator("#canvas-129-visual-layer .ic129-visual-sticky").count()==1
            # In-app Ctrl+C/V duplicates editable Graph only; Undo and Redo
            # preserve the original node IDs and never copy Run result nodes.
            page.locator("#ic-nodes-layer .ic-node").first.click(position={"x":25,"y":14})
            page.keyboard.press("Control+c")
            page.keyboard.press("Control+v")
            assert page.locator("#ic-nodes-layer .ic-node").count()==len(ids)+1
            page.keyboard.press("Control+z")
            assert page.locator("#ic-nodes-layer .ic-node").count()==len(ids)
            page.keyboard.press("Control+y")
            assert page.locator("#ic-nodes-layer .ic-node").count()==len(ids)+1

            assert not errors,errors
            out=ROOT/args.screenshots
            out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/"studio-real-canvas-1440.png"),
                full_page=False,animations="disabled")
            report={"result":"PASS","browser":browser.version,
                "canvasNodeIds":ids,"selected":selected,"zoom":zoom,
                "dragUpdated":before!=after,"errors":errors}
            (out/"studio-real-canvas-127.json").write_text(
                json.dumps(report,ensure_ascii=False,indent=2)+"\n")
            print("CANVAS #127 real Studio browser smoke PASS "+json.dumps(
                report,ensure_ascii=False))
            page.close()
            browser.close()
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if thread:thread.join(timeout=3)
        if db:db.close()
        env.stop()
        tmp.cleanup()


if __name__=="__main__":
    main()
