"""Issue #137: real Chromium layout and interaction checks for both form controllers.

Uses production templates, styles and event handlers with isolated adapter fixtures.
No image provider, account, production database or paid request is used.
"""
import json
import base64
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("HANDRAW_BROWSER_ARTIFACTS", "/tmp/handraw-creation-workspace"))
OUT.mkdir(parents=True, exist_ok=True)

BOOT = r"""
(config) => {
  const {kind, image:pixel} = config;
  const parts = {
    skill: {id:"skill",data:{style1:"FF-001",style2:"",layout:"SC-001",colors:[],tones:[],moods:[]}},
    text: {id:"text",data:{text:"暖阳下的单车少女"}},
    asset: {id:"asset",data:{items:[]}},
    loop: {id:"loop",data:{batchLayoutMode:"fixed",batchCount:3,batchSeed:"都市慢生活",promptListText:"咖啡馆\n公园\n书店",batchRows:[]}},
    ctrl: {id:"ctrl",data:{mode:"graphic-text",ratio:"3:4",count:1}}
  };
  const catalog = {
    styles:[{id:"FF-001",name:"暖色手绘",image:pixel}],
    layouts:[{id:"SC-001",name:"生活场景",image:pixel}],
    colors:[],tones:[],moods:[]
  };
  catalog.resourceMap = new Map([...catalog.styles,...catalog.layouts].map(r=>[r.id,r]));
  window.HANDRAW_SHARED = {App:{options:{}},toast:msg=>window.notice=msg};
  window.HandrawStudioPromptEngine = {
    assembleControlPrompt:()=>parts.text.data.text,
    resolveControlRecipe:()=>({}),
    resolveLoopIterations:()=> {
      const rows = parts.loop.data.batchLayoutMode === "ai"
        ? parts.loop.data.batchRows
        : parts.loop.data.promptListText.split("\n").filter(s=>s.trim()).map(theme=>({theme}));
      return rows.map((r,i)=>({theme:r.theme,title:r.theme,shortLabel:r.theme,layout:r.layout||"SC-001",index:i}));
    }
  };
  window.fetch = async () => ({ok:true,json:async()=>({ok:true,source:"ai",items:[
    {subject:"晨间咖啡",layout:"SC-001"},{subject:"午后公园",layout:"SC-001"},{subject:"黄昏书店",layout:"SC-001"}
  ]})});
  const controller = kind === "quick" ? new HandrawMakeImage.MakeImageController() : HandrawBatchCreate;
  const context = {parts,graph:{nodes:[],edges:[]},catalog,busy:false,results:[],displays:[],loggedIn:true,freeQuotaRemaining:2,siteSettings:{}};
  let runs=0, cancels=0, pickers=0, refs=0, saves=0;
  const host = document.getElementById("fixture");
  const render = () => controller.render(host,context,actions);
  const actions = {
    markDirtyAndRender:render,
    persistDraft:()=>saves++,
    isBusy:()=>context.busy,
    openAssetPicker:()=>pickers++,
    openReferencePicker:()=>refs++,
    ensureAssetItems:items=>{parts.asset.data.items=items;render();},
    run:()=>{runs++;context.busy=true;render();},
    cancel:()=>{cancels++;return true;}
  };
  window.fixture = {parts,context,controller,render,counts:()=>({runs,cancels,pickers,refs,saves}),pixel};
  render();
}
"""

def geometry(page, width, kind):
    data = page.evaluate("""() => {
      const box=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom};};
      return {content:box('.creation-content'),settings:box('.creation-settings'),
        overflow:document.documentElement.scrollWidth>innerWidth+1,
        cols:getComputedStyle(document.querySelector('.creation-workspace')).gridTemplateColumns};
    }""")
    if data["overflow"]:
        page.screenshot(path=str(OUT/f"overflow-{width}.png"),full_page=True)
        data["overflowingNodes"]=page.evaluate("""() => [...document.querySelectorAll("body *")].filter(el=>el.getBoundingClientRect().right>innerWidth+1).slice(-15).map(el=>({tag:el.tagName,cls:el.className,w:el.getBoundingClientRect().width,text:el.textContent.slice(0,80)}))""")
    assert not data["overflow"], (width, data)
    c, s = data["content"], data["settings"]
    if width > 980:
        if kind == "quick":
            assert c["x"] >= s["right"] and abs(c["y"] - s["y"]) < 2, data
        else:
            assert s["x"] >= c["right"] and abs(c["y"] - s["y"]) < 2, data
        assert c["w"] > s["w"], data
    else:
        assert abs(s["x"] - c["x"]) < 2 and s["y"] >= c["bottom"], data
    return data

def check_bar(page, selector):
    data=page.locator(selector).evaluate("""el=>{
      const r=el.getBoundingClientRect();
      const x=r.x+r.width/2,y=r.y+r.height/2;
      return {top:r.top,bottom:r.bottom,height:innerHeight,
        hit:el.contains(document.elementFromPoint(x,y))};
    }""")
    assert data["top"] >= 0 and data["bottom"] <= data["height"] and data["hit"], data

def load(page, kind):
    page.set_content('<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width,initial-scale=1"><body><div id="fixture"></div></body></html>')
    html=(ROOT/"demo/studio.html").read_text()
    for rel in re.findall(r'href="/([^"?]+\.css)', html):
        page.add_style_tag(path=str(ROOT/"demo"/rel))
    page.add_style_tag(content="body{margin:0;overflow:auto}#fixture{max-width:1440px;margin:0 auto;padding:24px;box-sizing:border-box}")
    for name in ["studio-make-image.js","studio-batch.js"]:
        page.add_script_tag(path=str(ROOT/"demo/assets"/name))
    image="data:image/webp;base64,"+base64.b64encode((ROOT/"demo/starter/bear-and-bird.webp").read_bytes()).decode()
    page.evaluate(BOOT,{"kind":kind,"image":image})

def main():
    with sync_playwright() as p:
        executable=os.environ.get("HANDRAW_CHROMIUM")
        browser=p.chromium.launch(**({"executable_path":executable} if executable else {}))
        page=browser.new_page(viewport={"width":1440,"height":1000})
        errors=[]
        page.on("pageerror",lambda err:errors.append(str(err)))
        evidence=[]
        for width in [1440,1200,1024,980,768,540,390]:
            page.set_viewport_size({"width":width,"height":900})
            for kind in ["quick","batch"]:
                load(page,kind)
                evidence.append({"kind":kind,"width":width,**geometry(page,width,kind)})
                expect(page.locator(".creation-content")).to_be_visible()
                expect(page.locator(".creation-settings")).to_be_visible()
                check_bar(page, "#make-image-btn-run" if kind=="quick" else "#batch-btn-start")
                if kind=="quick":
                    # #139: leave the results pane visually clean, with no duplicate page heading.
                    expect(page.locator(".make-image-head")).to_have_count(0)
                    expect(page.locator(".make-image-results-intro")).to_have_count(0)
                    expect(page.locator("#make-content-title")).to_have_count(0)
                    expect(page.locator(".make-image-conversation")).to_have_attribute("aria-label","生成结果与创作输入")
                    # Input persists through changes in the other column.
                    page.locator("#make-image-subject").fill("纸上风景与城市散步")
                    page.locator("#make-image-mode-fusion").click()
                    expect(page.locator("#make-image-subject")).to_have_value("纸上风景与城市散步")
                    expect(page.locator('[data-pick-kind="style2"]')).to_be_visible()
                    page.locator('[data-pick-kind="style1"]').press("Enter")
                    assert page.evaluate("fixture.counts().pickers")==1
                    page.locator("#make-image-open-ref-picker").click()
                    assert page.evaluate("fixture.counts().refs")==1
                    # #139: attachments are image-only and sit above the topic textarea.
                    expect(page.locator("#make-image-btn-again")).to_have_count(0)
                    expect(page.locator("#make-image-btn-new-theme")).to_have_count(0)
                    expect(page.locator("#make-image-clear-subject")).to_have_count(0)
                    expect(page.locator(".make-image-composer label")).to_have_count(0)
                    page.evaluate("""() => {
                        fixture.parts.asset.data.items = [
                          {image:fixture.pixel,name:"人物参考"},
                          {image:fixture.pixel,name:"构图参考"}
                        ];
                        fixture.render();
                    }""")
                    expect(page.locator(".make-image-composer-attachments .make-image-ref-thumb")).to_have_count(2)
                    expect(page.locator(".make-image-ref-thumb img")).to_have_count(2)
                    expect(page.locator(".make-image-slot-meta")).to_have_count(0)
                    assert page.evaluate("""() => {
                        const box=s=>document.querySelector(s).getBoundingClientRect();
                        return box(".make-image-composer-attachments").bottom <= box("#make-image-subject").top;
                    }""")
                    page.locator('[data-del-ref="0"]').click()
                    expect(page.locator(".make-image-ref-thumb")).to_have_count(1)
                    assert len(page.evaluate("fixture.parts.asset.data.items")) == 1

                    page.locator('[data-set-ratio="1:1"]').click()
                    assert page.evaluate("fixture.parts.ctrl.data.ratio")=="1:1"
                    page.locator("#make-image-more-toggle").click()
                    expect(page.locator("#make-image-audience")).to_be_visible()
                    geometry(page,width,kind)
                    page.locator("#make-image-prompt-toggle").click()
                    geometry(page,width,kind)
                    # #138: constrain the desktop workspace height to verify independent scrolling and fixed composer.
                    if width > 980:
                        page.locator("#fixture").evaluate("el => el.style.height = '650px'")
                        page.evaluate("fixture.render()")
                        dock = page.evaluate("""() => {
                            const rect = s => document.querySelector(s).getBoundingClientRect();
                            const sidebar = document.querySelector(".make-image-properties");
                            const output = document.querySelector(".make-image-output-scroll");
                            const composer = rect(".make-image-composer");
                            const stage = rect(".make-image-conversation");
                            const host = rect("#fixture");
                            return {sidebarHeight:sidebar.clientHeight, sidebarScroll:sidebar.scrollHeight,
                                sidebarOverflow:getComputedStyle(sidebar).overflowY,
                                outputScrollbar:getComputedStyle(output).scrollbarWidth,
                                composerBottom:composer.bottom, stageBottom:stage.bottom, hostBottom:host.bottom};
                        }""")
                        assert dock["sidebarScroll"] > dock["sidebarHeight"] + 2, dock
                        assert dock["sidebarOverflow"] == "auto", dock
                        assert dock["outputScrollbar"] == "none", dock
                        assert dock["composerBottom"] <= dock["stageBottom"] and dock["stageBottom"] <= dock["hostBottom"], dock
                    # The action stays reachable with both panels expanded.
                    page.locator("#make-image-btn-run").scroll_into_view_if_needed()
                    check_bar(page,"#make-image-btn-run")
                    page.screenshot(path=str(OUT/f"{kind}-{width}.png"),full_page=True)
                    page.locator("#make-image-btn-run").click()
                    expect(page.locator("#make-image-btn-run")).to_be_disabled()
                    expect(page.locator(".make-image-pending")).to_be_visible()
                    page.locator("#make-image-btn-stop").click()
                    assert page.evaluate("fixture.counts().cancels")==1
                    geometry(page,width,kind)
                else:
                    page.locator("#batch-prompts-input").fill("山间晨雾\n湖边暮色")
                    expect(page.locator(".batch-cost-text")).to_contain_text("2 张")
                    expect(page.locator("#batch-btn-start")).to_be_enabled()
                    page.locator("#batch-strategy-ai").click()
                    assert page.locator(".batch-edit-row").count()==2
                    page.locator("#batch-mode-fusion").click()
                    page.locator('[data-pick-kind="style1"]').press("Space")
                    assert page.evaluate("fixture.counts().pickers")==1
                    page.locator("#batch-btn-pick-global-refs").click()
                    assert page.evaluate("fixture.counts().refs")==1
                    page.locator("#batch-toggle-more-settings").click()
                    geometry(page,width,kind)
                    page.locator("#batch-seed-input").fill("城市散步")
                    page.locator("#batch-btn-plan").click()
                    expect(page.locator(".batch-edit-row")).to_have_count(3)
                    geometry(page,width,kind)
                    if width<=600:
                        assert page.locator(".batch-edit-table").evaluate("el=>el.scrollWidth<=el.clientWidth+1")
                    page.locator("#batch-concurrency").select_option("2")
                    assert page.evaluate("fixture.parts.loop.data.batchConcurrency")==2
                    page.locator("#batch-btn-start").scroll_into_view_if_needed()
                    check_bar(page,"#batch-btn-start")
                    page.screenshot(path=str(OUT/f"{kind}-{width}.png"),full_page=True)
                    page.locator("#batch-btn-start").click()
                    expect(page.locator("#batch-btn-stop")).to_be_visible()
                    page.locator("#batch-btn-stop").click()
                    expect(page.locator("#batch-btn-stop")).to_be_disabled()
                    assert page.evaluate("fixture.counts().cancels")==1
                    geometry(page,width,kind)
        assert not errors, errors
        (OUT/"geometry.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
        print(f"PASS: {len(evidence)} responsive form states; input retention, keyboard pickers, references, planning, costs, run and stop.")
        browser.close()

if __name__=="__main__":
    main()
