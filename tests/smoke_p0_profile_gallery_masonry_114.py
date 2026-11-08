"""#114 P0 real Chromium layout check using shipped profile/gallery CSS and JS.

This mounts actual profile masonry card classes inside a live local Handraw
page (controlled DOM, no fake CSS or duplicate layout implementation).
Evidence is native browser geometry for 1440px and 390px, not a claim about
customer profile data in production.
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

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.server import create_channel_server, init_database


def exercise(page, viewport):
    page.set_viewport_size({"width": viewport, "height": 900})
    page.evaluate("""() => {
        document.querySelector('#qa-p0-profile-masonry')?.remove();
        const section = document.createElement('section');
        section.id = 'qa-p0-profile-masonry';
        section.style.cssText = 'box-sizing:border-box;width:100%;max-width:1080px;margin:32px auto;padding:0 8px;';
        // The shipped helper intentionally ignores grids outside the DOM.
        // Mount the fixture before asking ResizeObserver to measure it.
        document.body.appendChild(section);
        const classes = [
          ['works', 'hw-profile-feed hw-profile-work-feed', 'hw-card hw-profile-work-group'],
          ['resources', 'hw-profile-feed hw-profile-resource-feed', 'hw-card hw-profile-resource-card'],
          ['topics', 'hw-profile-feed hw-profile-topic-feed', 'forum-topic-card hw-profile-topic-card'],
          ['gallery', 'hw-personal-gallery-grid', 'hw-personal-gallery-card'],
        ];
        classes.forEach(([key,gridClass,cardClass]) => {
            const title=document.createElement('h3');
            title.textContent=key;section.appendChild(title);
            const grid=document.createElement('div');
            grid.dataset.qaGrid=key;
            grid.className=gridClass;
            grid.style.marginBottom='20px';
            [270,135,215].forEach((height,i) => {
                const card=document.createElement('article');
                card.className=cardClass;
                card.tabIndex=0;
                card.dataset.qaCard=String(i);
                card.innerHTML='<div class="qa-p0-card-body" style="height:'+
                  height+'px;box-sizing:border-box;padding:8px;">'+
                  '<strong>第 '+(i+1)+' 张卡片</strong>'+
                  '</div>';
                grid.appendChild(card);
            });
            section.appendChild(grid);
            window.HANDRAW_SHARED.layoutProfileMasonry(grid);
            const one=document.createElement('div');
            one.dataset.qaGrid=key+'-single';
            one.className=gridClass;
            one.style.marginTop='8px';
            const child=document.createElement('article');
            child.className=cardClass;
            child.tabIndex=0;
            child.innerHTML='<div style="height:120px">单卡内容</div>';
            one.appendChild(child);
            section.appendChild(one);
            window.HANDRAW_SHARED.layoutProfileMasonry(one);
        });
    }""")
    page.wait_for_function("""() => {
      const grids=[...document.querySelectorAll('#qa-p0-profile-masonry [data-qa-grid]')];
      return grids.length===8 && grids.every(g=>[...g.children].every(
        c=>c.style.gridRowEnd.startsWith('span ')));
    }""", timeout=15000)
    metrics = page.evaluate("""() => {
      const result={};
      for(const grid of document.querySelectorAll('#qa-p0-profile-masonry [data-qa-grid]')){
        const b=grid.getBoundingClientRect();
        const cards=[...grid.children].map(el=>{
          const r=el.getBoundingClientRect();
          return {x:Math.round(r.x*10)/10,y:Math.round(r.y*10)/10,
                  w:Math.round(r.width*10)/10,h:Math.round(r.height*10)/10,
                  span:el.style.gridRowEnd,focusable:el.tabIndex>=0};
        });
        result[grid.dataset.qaGrid]={
          columns:getComputedStyle(grid).gridTemplateColumns.split(' ').length,
          gridX:b.x,gridRight:b.right,cards
        };
      }
      return {viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,
              grids:result};
    }""")
    expected_columns = 5 if viewport == 1440 else 2
    assert metrics["scrollWidth"] <= viewport + 2, metrics
    for name in ("works", "resources", "topics", "gallery"):
        item = metrics["grids"][name]
        cards = item["cards"]
        assert item["columns"] == expected_columns, (name, item)
        assert len(cards) == 3 and all(x["focusable"] for x in cards), name
        assert cards[0]["x"] < cards[1]["x"], (name, cards)
        if viewport == 1440:
            assert cards[1]["x"] < cards[2]["x"], (name, cards)
            assert max(c["y"] for c in cards) - min(c["y"] for c in cards) < 2, (name,cards)
        for card in cards:
            assert card["x"] >= -1 and card["x"] + card["w"] <= viewport + 1, (name,card)
            assert card["span"].startswith("span "), (name,card)
        single = metrics["grids"][name + "-single"]
        assert len(single["cards"]) == 1 and single["columns"] == expected_columns
    return metrics


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "masonry114.sqlite"),
            "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_DEMO_MODE": "1",
        })
        env.start()
        db=server=thread=None
        try:
            db=init_database(root / "masonry114.sqlite")
            server=create_channel_server(0,"main",db)
            server.allow_demo_routes=True
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base="http://127.0.0.1:"+str(server.server_port)
            with sync_playwright() as p:
                binary=next((value for name in (
                    "chromium","google-chrome-stable","google-chrome","chrome")
                    if (value:=shutil.which(name))),None)
                launch={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
                if binary:
                    launch["executable_path"]=binary
                browser=p.chromium.launch(**launch)
                try:
                    page=browser.new_page(viewport={"width":1440,"height":900})
                    errors=[]
                    page.on("pageerror",lambda error:errors.append(str(error)))
                    page.goto(base+"/",wait_until="domcontentloaded",timeout=60000)
                    # The real application initializes its shared layout module.
                    # If home entry route doesn't include it, attach the same
                    # shipped script (no test-only reimplementation).
                    if not page.evaluate(
                        "() => !!window.HANDRAW_SHARED?.layoutProfileMasonry"
                    ):
                        page.add_script_tag(url=base+"/assets/shared.js")
                    page.wait_for_function(
                        "() => !!window.HANDRAW_SHARED?.layoutProfileMasonry",
                        timeout=10000)
                    output=ROOT/"artifacts"/"p0-masonry-114"
                    output.mkdir(parents=True,exist_ok=True)
                    results=[]
                    for width in (1440,390):
                        result=exercise(page,width)
                        results.append(result)
                        page.screenshot(
                            path=str(output/f"profile-gallery-{width}.png"),
                            animations="disabled",full_page=True)
                    # ResizeObserver should update row span when a media
                    # thumbnail becomes taller after loading.
                    before=page.locator(
                        '[data-qa-grid="gallery"] [data-qa-card="0"]'
                    ).evaluate("(el) => el.style.gridRowEnd")
                    page.evaluate("""() => {
                        document.querySelector(
                          '[data-qa-grid="gallery"] [data-qa-card="0"] .qa-p0-card-body'
                        ).style.height='620px';
                    }""")
                    page.wait_for_function("""(prev) => document.querySelector(
                      '[data-qa-grid="gallery"] [data-qa-card="0"]'
                    ).style.gridRowEnd!==prev""",arg=before,timeout=10000)
                    assert not errors,errors
                    (output/"browser-geometry.json").write_text(
                        json.dumps({"issue":114,"result":"PASS",
                                    "scope":"native-app-css-controlled-cards",
                                    "productionVerified":False,
                                    "browser":browser.version,
                                    "viewports":results},ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
                    print("P0 #114 native Chromium profile/gallery 1+3 cards, "
                          "1440/390 breakpoints, row-first and ResizeObserver: PASS",
                          flush=True)
                finally:
                    browser.close()
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if thread:
                thread.join(timeout=5)
            if db:
                db.close()
            env.stop()


if __name__=="__main__":
    main()
