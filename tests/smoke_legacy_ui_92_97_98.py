"""#92/#97 genuine Chromium browser interaction regression, 1440px and 390px.

Uses the shipped Studio history renderer, shipped work-detail component,
real Handraw HTTP page/CSS, and distinct per-media metadata. History fixtures
are inserted through the shipped testing entrypoint, not a reimplemented DOM.
No production user, paid model or external storage is accessed.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.server import create_channel_server, init_database, SESSION_COOKIE_NAME
from backend.services import register_user


def check_history(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(page.qa_base + "/studio/?view=history", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_function("() => window.CS?.stageView === 'history' && !!window.HANDRAW_STUDIO?.setHistory",
                           timeout=30000)
    page.evaluate("""() => {
      window.CS.historyFilter = 'all';
      window.CS.historyStatusFilter = 'all';
      window.CS.historyQuery = '';
      window.CS.historySort = 'newest';
      window.CS.historyExpandedBatchIds = {};
      window.CS.historySelectedPreview = {};
      window.HANDRAW_STUDIO.setHistory([
        {id:'qa92-batch',mode:'graphic-text',kind:'loop',creationSource:'batch',
         subject:'三图受控历史',prompt:'三幅小镇',status:'success',createdAt:'2026-11-09',
         items:[
           {imageUrl:'/images/individual/FA/FA-013.webp',title:'一'},
           {imageUrl:'/images/individual/FA/FA-014.webp',title:'二'},
           {imageUrl:'/images/individual/FA/FA-015.webp',title:'三'}
         ]},
        {id:'qa92-single',mode:'poster',kind:'single',creationSource:'quick',
         subject:'单图历史',status:'success',items:[
           {imageUrl:'/images/individual/FA/FA-016.webp',title:'单图'}]},
        {id:'qa92-other',mode:'article',kind:'single',creationSource:'article',
         subject:'文章插图',status:'success',items:[
           {imageUrl:'/images/individual/FA/FA-017.webp',title:'文章'}]}
      ]);
    }""")
    page.wait_for_function("() => document.querySelectorAll('#hist-records-list > article.ic-hist-entry-card').length===3")
    grid = page.locator("#hist-records-list")
    before = page.evaluate("""() => {
      const grid=document.querySelector('#hist-records-list');
      const cards=[...grid.children].map(c=>c.getBoundingClientRect());
      const g=grid.getBoundingClientRect();
      const css=getComputedStyle(grid);
      const img=grid.querySelector('.ic-hist-cover img');
      return {viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        columnCount:css.gridTemplateColumns.split(' ').filter(Boolean).length,
        display:css.display,gap:parseFloat(css.columnGap),
        gridX:g.x,gridRight:g.right,
        cards:cards.map(r=>({x:r.x,y:r.y,right:r.right,width:r.width})),
        imgFit:getComputedStyle(img).objectFit};
    }""")
    expected = 5 if width == 1440 else 2
    assert before["columnCount"] == expected, before
    assert before["display"] == "grid", before
    assert before["scrollWidth"] <= width + 2, before
    assert before["cards"][0]["x"] < before["cards"][1]["x"], before
    assert before["cards"][0]["width"] <= (before["gridRight"] - before["gridX"]) / expected + 2, before
    assert before["imgFit"] != "fill", before
    assert 8 <= before["gap"] <= 18, before
    expand = grid.locator('[data-hist-expand-batch="qa92-batch"]').first
    expand.click()
    page.wait_for_function("""() => document.querySelector(
      '[data-hist-id="qa92-batch"] .ic-hist-expanded-gallery'
    )?.querySelectorAll('img').length === 3""")
    expanded = page.evaluate("""() => {
      const card=document.querySelector('[data-hist-id="qa92-batch"]');
      const r=card.getBoundingClientRect();
      const images=[...card.querySelectorAll('.ic-hist-expanded-gallery img')];
      return {outerRight:r.right,images:images.map(x=>{
        const b=x.getBoundingClientRect();return {
          left:b.left,right:b.right,naturalWidth:x.naturalWidth,
          fit:getComputedStyle(x).objectFit};})};
    }""")
    assert len(expanded["images"]) == 3, expanded
    assert all(it["fit"] == "contain" for it in expanded["images"]), expanded
    assert all(it["right"] <= width + 1 for it in expanded["images"]), expanded
    assert page.locator("#hist-records-list > article.ic-hist-entry-card").count() == 3
    assert page.locator('[data-hist-id="qa92-batch"] .ic-hist-cover-count').count() == 1
    return {"initial": before, "expanded": expanded, "oneCardPerRun": True}


def check_work_detail(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(page.qa_base + "/", wait_until="domcontentloaded", timeout=60000)
    page.add_script_tag(url=page.qa_base + "/assets/forum-work-post.js")
    page.wait_for_function("() => !!window.HandrawForumWork?.fromTopic")
    page.evaluate("""() => {
      const urls=['/images/individual/FA/FA-013.webp','/images/individual/FB/FB-001.webp'];
      const topic={id:'qa97-topic',workId:'qa97-work',title:'逐图参数验收'};
      const work={
        id:'qa97-work',title:'逐图参数验收',subject:'画两张不同风格',
        prompt:'画两张不同风格',styles:['FA-011'],layout:'SC-001',
        images:urls,
        imageAssets:[
          {url:urls[0],styles:['FA-011'],layout:'SC-001',scope:'image'},
          {url:urls[1],styles:['FB-022'],layout:'IG-006',scope:'image'}
        ]
      };
      const registry={
        'FA-011':{id:'FA-011',name:'第一张画风',kind:'style'},
        'FB-022':{id:'FB-022',name:'第二张画风',kind:'style'},
        'SC-001':{id:'SC-001',name:'第一张图型',kind:'layout'},
        'IG-006':{id:'IG-006',name:'第二张图型',kind:'layout'}
      };
      const model=window.HandrawForumWork.fromTopic(topic,[work],registry,true);
      const host=document.createElement('section');
      host.id='qa97-detail';
      host.style.cssText='max-width:960px;width:calc(100% - 32px);margin:20px auto;box-sizing:border-box;';
      host.innerHTML=window.HandrawForumWork.render(model);
      document.body.appendChild(host);
      window.HandrawForumWork.bind(host,model);
    }""")
    host=page.locator("#qa97-detail")
    assert host.locator("[data-fwp-assets]").count() == 1
    assert "FA-011" in host.locator("[data-fwp-assets]").inner_text()
    assert "SC-001" in host.locator("[data-fwp-assets]").inner_text()
    assert "FB-022" not in host.locator("[data-fwp-assets]").inner_text()
    assert host.get_by_text("全部图型", exact=True).count() == 0
    assert host.get_by_text("全部画风", exact=True).count() == 0
    links=host.locator(".fwp-asset")
    assert links.count() == 2
    assert all(links.nth(i).get_attribute("target") == "_blank" for i in range(2))
    assert "noopener" in (links.first.get_attribute("rel") or "")
    second=host.locator(".fwp-thumb").nth(1)
    second.click()
    assert second.get_attribute("aria-selected") == "true"
    meta=host.locator("[data-fwp-assets]").inner_text()
    assert "FB-022" in meta and "IG-006" in meta, meta
    assert "FA-011" not in meta and "SC-001" not in meta, meta
    main=host.locator("[data-fwp-main]").get_attribute("data-hw-src")
    download=host.locator(".fwp-download-btn").get_attribute("href")
    fork=host.locator("[data-fwp-fork]").get_attribute("href")
    assert main.endswith("FB/FB-001.webp"), main
    assert download == main and "image=1" in fork, (download,fork)
    # Actual browser back to first image must restore first image's metadata.
    host.locator(".fwp-thumb").first.click()
    first_meta=host.locator("[data-fwp-assets]").inner_text()
    assert "FA-011" in first_meta and "SC-001" in first_meta, first_meta
    assert "FB-022" not in first_meta, first_meta
    geometry=page.evaluate("""() => {
      const host=document.querySelector('#qa97-detail');
      const r=host.getBoundingClientRect();
      return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
              left:r.left,right:r.right,thumbnailCount:host.querySelectorAll('.fwp-thumb').length};
    }""")
    assert geometry["scrollWidth"] <= width + 2, geometry
    assert geometry["right"] <= width + 1 and geometry["left"] >= -1, geometry
    return {"geometry":geometry,"thumbnailSwitch":"both-directions",
            "perMediaMetadata":True,"newTabResources":True,
            "forkAndDownloadFollowImage":True}


def main():
    from playwright.sync_api import sync_playwright
    artifact = ROOT / "artifacts" / "ui-92-97-98"
    artifact.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        env=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(root/"ui.sqlite"),
            "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
            "HANDRAW_GENERATED_DIR":str(root/"generated"),
            "HANDRAW_PRIVATE_STORAGE":str(root/"private"),
            "HANDRAW_DEMO_MODE":"1",
            "HANDRAW_ENABLE_RECHARGE":"0",
        })
        env.start()
        db=server=thread=None
        try:
            db=init_database(root/"ui.sqlite")
            _,cookie=register_user(db,"ui92_97_browser","StrongPass123!")
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as pw:
                binary=next((s for n in ("chromium","google-chrome-stable","google-chrome","chrome")
                             if (s:=shutil.which(n))),None)
                launch={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
                if binary:launch["executable_path"]=binary
                browser=pw.chromium.launch(**launch)
                try:
                    context=browser.new_context(viewport={"width":1440,"height":900})
                    context.add_cookies([{"name":SESSION_COOKIE_NAME,"value":cookie,"url":base}])
                    page=context.new_page()
                    page.qa_base=base
                    page.add_init_script("window.__HANDRAW_TESTING__ = true")
                    errors=[]
                    page.on("pageerror",lambda e:errors.append(str(e)))
                    record=[]
                    for width in (1440,390):
                        history=check_history(page,width)
                        page.screenshot(path=str(artifact/f"history-{width}.png"),
                                        animations="disabled",full_page=True)
                        detail=check_work_detail(page,width)
                        page.screenshot(path=str(artifact/f"work-detail-{width}.png"),
                                        animations="disabled",full_page=True)
                        record.append({"viewport":width,"history":history,"workDetail":detail})
                    assert not errors,errors
                    (artifact/"browser-summary.json").write_text(
                        json.dumps({"issues":[92,97],"result":"PASS",
                                    "browser":browser.version,
                                    "environment":"live-local-HTTP-true-Chromium-shipped-UI-controlled-records",
                                    "productionVerified":False,"viewports":record},
                                   ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                    print("Legacy #92/#97 real Chromium history single cover card,"
                          " 3-image expansion, 5/2 columns, per-media styles and"
                          " layouts, download/fork/new-tab at 1440/390 PASS",flush=True)
                finally:
                    browser.close()
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if thread:thread.join(timeout=5)
            if db:db.close()
            env.stop()


if __name__=="__main__":
    main()
