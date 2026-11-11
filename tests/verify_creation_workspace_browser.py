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
    loop: {id:"loop",data:{batchLayoutMode:"ai",batchCount:3,batchSeed:"都市慢生活",promptListText:"咖啡馆\n公园\n书店",batchRows:[{theme:"咖啡馆",layout:"SC-001"},{theme:"公园",layout:"SC-001"},{theme:"书店",layout:"SC-001"}]}},
    ctrl: {id:"ctrl",data:{mode:"graphic-text",ratio:"3:4",count:1}}
  };
  const catalog = {
    styles:[{id:"FF-001",name:"暖色手绘",image:pixel}],
    layouts:[{id:"SC-001",name:"生活场景",image:pixel}],
    colors:[],tones:[],moods:[]
  };
  catalog.resourceMap = new Map([...catalog.styles,...catalog.layouts].map(r=>[r.id,r]));
  window.HANDRAW_SHARED = {App:{options:{}},toast:msg=>window.notice=msg};
  window.HandrawImageLoader = {scan:root=>{
    root.querySelectorAll("img[data-hw-src]").forEach(img=>{
      const url=img.getAttribute("data-hw-src");
      if(url && img.getAttribute("src")!==url) img.setAttribute("src",url);
    });
  }};
  window.HANDRAW_SHARED.triggerImageLoaders = root=>window.HandrawImageLoader.scan(root);
  window.HandrawStudioPromptEngine = {
    assembleControlPrompt:()=>parts.text.data.text,
    resolveControlRecipe:()=>({}),
    resolveLoopIterations:()=> {
      const rows = Array.isArray(parts.loop.data.batchRows) && parts.loop.data.batchRows.length
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
  let runs=0, cancels=0, pickers=0, refs=0, saves=0, singles=[];
  const host = document.getElementById("fixture");
  const render = () => controller.render(host,context,actions);
  const actions = {
    markDirtyAndRender:render,
    persistDraft:()=>saves++,
    isBusy:()=>context.busy,
    openAssetPicker:()=>pickers++,
    openReferencePicker:()=>refs++,
    ensureAssetItems:items=>{parts.asset.data.items=items;render();},
    run:()=>{
      runs++;context.busy=true;
      const completed=new Map(Array.from(controller.seriesOutcomes?.entries() || [])
        .filter(([,item])=>Boolean(item?.imageUrl)));
      controller.resetBatchProgress?.({
        totalCount:parts.loop.data.batchRows?.length || 3,
        batchId:"ui-batch",existingCompleted:completed
      });
      render();
    },
    runSingleRow:idx=>{
      singles.push(idx);context.busy=true;
      controller.resetBatchProgress?.({
        totalCount:parts.loop.data.batchRows?.length || 3,
        batchId:"ui-single",singleSlotIndex:idx
      });
      render();
    },
    cancel:()=>{cancels++;return true;}
  };
  window.fixture = {parts,context,controller,render,counts:()=>({runs,cancels,pickers,refs,saves,singles}),pixel};
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
        assert c["x"] >= s["right"] and abs(c["y"] - s["y"]) < 2, data
        assert c["w"] > s["w"], data
    else:
        if kind == "quick":
            assert abs(s["x"] - c["x"]) < 2 and s["y"] >= c["bottom"], data
        else:
            assert abs(s["x"] - c["x"]) < 2 and c["y"] >= s["bottom"], data
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
    page.add_style_tag(content="body{margin:0;overflow:auto}#fixture{max-width:1440px;margin:0 auto;padding:24px;box-sizing:border-box;height:calc(100dvh - 16px)}")
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
                if kind=="batch":
                    page.locator("#batch-btn-start").scroll_into_view_if_needed()
                check_bar(page, "#make-image-btn-run" if kind=="quick" else "#batch-btn-start")
                if kind=="quick":
                    # #139: leave the results pane visually clean, with no duplicate page heading.
                    expect(page.locator(".make-image-head")).to_have_count(0)
                    expect(page.locator("#make-settings-title")).to_have_count(0)
                    expect(page.locator(".make-image-properties > .creation-section-head")).to_have_count(0)
                    expect(page.locator(".make-image-properties")).to_have_attribute("aria-label", "画面属性")
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
                    # #140: test real short-stage heights (the former 520px minimum
                    # could make the hidden parent clip the sidebar before it scrolled).
                    if width > 980:
                        for stage_height in [650, 430, 340]:
                            page.locator("#fixture").evaluate("(el, h) => el.style.height = h + 'px'", stage_height)
                            page.evaluate("fixture.render()")
                            dock = page.evaluate("""() => {
                                const rect = s => document.querySelector(s).getBoundingClientRect();
                                const sidebar = document.querySelector(".make-image-properties");
                                const output = document.querySelector(".make-image-output-scroll");
                                const composer = rect(".make-image-composer");
                                const stage = rect(".make-image-conversation");
                                const host = rect("#fixture");
                                const workspace = rect(".make-image-chat-container");
                                const previousOutputScroll = output.scrollTop;
                                const beforeScroll = sidebar.scrollTop = 0;
                                sidebar.scrollTop = sidebar.scrollHeight;
                                return {
                                    sidebarHeight:sidebar.clientHeight, sidebarScroll:sidebar.scrollHeight,
                                    sidebarOverflow:getComputedStyle(sidebar).overflowY,
                                    sidebarScrollbar:getComputedStyle(sidebar).scrollbarWidth,
                                    scrollbarThumb:getComputedStyle(sidebar).scrollbarColor,
                                    sidebarScrollTop:sidebar.scrollTop,
                                    outputUntouched:output.scrollTop === previousOutputScroll,
                                    outputScrollbar:getComputedStyle(output).scrollbarWidth,
                                    composerBottom:composer.bottom, stageBottom:stage.bottom,
                                    hostBottom:host.bottom, hostHeight:host.height, workspaceHeight:workspace.height
                                };
                            }""")
                            assert dock["workspaceHeight"] <= dock["hostHeight"] + 2, (stage_height, dock)
                            has_overflow = dock["sidebarScroll"] > dock["sidebarHeight"] + 2
                            if stage_height <= 430:
                                assert has_overflow, (stage_height, dock)
                                assert dock["sidebarScrollTop"] > 2, (stage_height, dock)
                            else:
                                # A taller panel should not sprout an unnecessary scrollbar.
                                assert not has_overflow or dock["sidebarScrollTop"] > 2, (stage_height, dock)
                            assert dock["sidebarOverflow"] == "auto", (stage_height, dock)
                            assert dock["sidebarScrollbar"] != "none", (stage_height, dock)
                            assert dock["outputScrollbar"] == "none" and dock["outputUntouched"], (stage_height, dock)
                            assert dock["composerBottom"] <= dock["stageBottom"] + 1 and dock["stageBottom"] <= dock["hostBottom"], (stage_height, dock)

                            # #140 follow-up: toggles must remain fully rendered in all four
                            # collapsed/expanded combinations, not just expose a sidebar scrollbar.
                            if stage_height <= 430:
                                for more_open, prompt_open in [(False, False), (True, False), (False, True), (True, True)]:
                                    for selector, target in [
                                        ("#make-image-more-toggle", more_open),
                                        ("#make-image-prompt-toggle", prompt_open)
                                    ]:
                                        control = page.locator(selector)
                                        if control.get_attribute("aria-expanded") != str(target).lower():
                                            control.click()
                                        expect(control).to_have_attribute("aria-expanded", str(target).lower())
                                    card_state = page.evaluate("""() => {
                                        const sidebar = document.querySelector(".make-image-properties");
                                        const output = document.querySelector(".make-image-output-scroll");
                                        const sidebarBox = sidebar.getBoundingClientRect();
                                        const previousOutputScroll = output.scrollTop;
                                        const cards = [...sidebar.querySelectorAll(":scope > .make-image-collapsible-card")];
                                        const panels = cards.map(card => {
                                            const toggle = card.querySelector(".make-image-collapsible-toggle");
                                            const body = card.querySelector(".make-image-collapsible-body");
                                            const cardBox = card.getBoundingClientRect();
                                            const toggleBox = toggle.getBoundingClientRect();
                                            const bodyBox = body.getBoundingClientRect();
                                            return {
                                                expanded:toggle.getAttribute("aria-expanded") === "true",
                                                hidden:body.hidden,
                                                cardHeight:cardBox.height,
                                                contentsHeight:toggleBox.height + (body.hidden ? 0 : bodyBox.height),
                                                scrollHeight:card.scrollHeight,
                                                clientHeight:card.clientHeight,
                                                toggleHeight:toggleBox.height
                                            };
                                        });
                                        sidebar.scrollTop = sidebar.scrollHeight;
                                        const lastCardBox = cards[cards.length - 1].getBoundingClientRect();
                                        return {
                                            panels,
                                            lastCardBottom:lastCardBox.bottom,
                                            sidebarBottom:sidebarBox.bottom,
                                            sidebarScroll:sidebar.scrollHeight,
                                            sidebarHeight:sidebar.clientHeight,
                                            sidebarScrollTop:sidebar.scrollTop,
                                            rightScrollUnchanged:output.scrollTop === previousOutputScroll
                                        };
                                    }""")
                                    assert len(card_state["panels"]) == 2, card_state
                                    for index, should_expand in enumerate((more_open, prompt_open)):
                                        card = card_state["panels"][index]
                                        assert card["expanded"] == should_expand and card["hidden"] != should_expand, (stage_height, card_state)
                                        assert card["toggleHeight"] >= 32, (stage_height, card_state)
                                        # A clipped flex child reports a shorter box than its own body.
                                        assert card["cardHeight"] >= card["contentsHeight"] - 2, (stage_height, card_state)
                                        assert card["scrollHeight"] <= card["clientHeight"] + 3, (stage_height, card_state)
                                    if card_state["sidebarScroll"] > card_state["sidebarHeight"] + 2:
                                        assert card_state["sidebarScrollTop"] > 2, (stage_height, card_state)
                                    else:
                                        assert card_state["sidebarScrollTop"] <= 2, (stage_height, card_state)
                                    assert card_state["lastCardBottom"] <= card_state["sidebarBottom"] + 2, (stage_height, card_state)
                                    assert card_state["rightScrollUnchanged"], (stage_height, card_state)
                                    if width == 1440 and stage_height == 430:
                                        page.screenshot(
                                            path=str(OUT / f"quick-collapsible-{int(more_open)}-{int(prompt_open)}.png"),
                                            full_page=True
                                        )
                        # Return to the wider evidence fixture for the original screenshot.
                        page.locator("#fixture").evaluate("el => el.style.height = '650px'")
                        page.evaluate("fixture.render()")
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
                    # #143: single focused picture + vertical thumbnail navigation
                    # and upper shared / lower selected-image settings.
                    expect(page.locator(".batch-series-stage")).to_be_visible()
                    expect(page.locator(".batch-series-main-card")).to_be_visible()
                    expect(page.locator(".batch-series-thumbs")).to_be_visible()
                    expect(page.locator(".batch-series-thumb")).to_have_count(3)
                    expect(page.locator(".batch-series-focused")).to_have_count(1)
                    # #145: no heading or border around the focused placeholder.
                    expect(page.locator(".batch-series-toolbar")).to_have_count(0)
                    expect(page.locator(".batch-series-focused .batch-series-card-head")).to_have_count(0)
                    expect(page.locator(".batch-series-focused .batch-series-placeholder")).to_be_visible()
                    expect(page.locator(".batch-series-generate-one")).to_be_visible()
                    expect(page.locator(".batch-series-generate-one svg")).to_have_count(1)
                    centered=page.evaluate("""() => {
                      const main=document.querySelector('.batch-series-main-card').getBoundingClientRect();
                      const center=document.querySelector('.batch-series-placeholder-center').getBoundingClientRect();
                      const button=document.querySelector('.batch-series-generate-one').getBoundingClientRect();
                      const mid=r=>({x:r.left+r.width/2,y:r.top+r.height/2});
                      return {
                        dx:Math.abs(mid(main).x-mid(center).x),
                        dy:Math.abs(mid(main).y-mid(center).y),
                        buttonDx:Math.abs(mid(main).x-mid(button).x),
                        buttonInside:button.top>=main.top && button.bottom<=main.bottom
                      };
                    }""")
                    assert centered["dx"]<5 and centered["buttonDx"]<5 and centered["dy"]<max(45,width*.07),centered
                    assert centered["buttonInside"],centered
                    expect(page.locator("#batch-btn-add-row")).to_be_visible()
                    expect(page.locator(".batch-series-bulk-input")).to_have_count(0)
                    expect(page.locator("#batch-prompts-input")).to_have_count(0)
                    expect(page.locator("[data-row-skip-global]")).to_have_count(0)
                    frame=page.evaluate("""() => {
                      const p=document.querySelector('.batch-series-main-card');
                      const picture=document.querySelector('.batch-series-thumb-picture');
                      const stage=document.querySelector('.batch-series-stage');
                      return {
                        border:getComputedStyle(p).borderTopWidth,
                        rectangle:picture.getBoundingClientRect().width>picture.getBoundingClientRect().height,
                        thumbAtRight:picture.getBoundingClientRect().left>p.getBoundingClientRect().right-2,
                        stageWidth:stage.getBoundingClientRect().width
                      };
                    }""")
                    assert frame["border"]=="0px" and frame["rectangle"] and frame["thumbAtRight"],frame
                    expect(page.locator(".batch-series-grid")).to_have_count(0)
                    expect(page.locator(".batch-series-properties .batch-series-shared")).to_be_visible()
                    expect(page.locator(".batch-series-properties .batch-series-selected-settings")).to_be_visible()
                    expect(page.locator(".batch-series-selected-settings .make-image-picker-card")).to_be_visible()
                    # No second fixed-height sidebar. All attributes flow naturally
                    # inside one scrollable rail, including the selected picture.
                    if width > 980:
                        flow=page.evaluate("""() => {
                          const parent=document.querySelector('.batch-series-properties');
                          const shared=document.querySelector('.batch-series-shared');
                          const selected=document.querySelector('.batch-series-selected-settings');
                          const hasOwnScroller=[shared,selected].some(el=>/auto|scroll/.test(getComputedStyle(el).overflowY));
                          const linked=selected.getBoundingClientRect().top >= shared.getBoundingClientRect().bottom-1;
                          const canScroll=parent.scrollHeight>parent.clientHeight;
                          parent.scrollTop=parent.scrollHeight;
                          const visibleAtEnd=selected.getBoundingClientRect().bottom<=parent.getBoundingClientRect().bottom+2;
                          const moved=parent.scrollTop;
                          parent.scrollTop=0;
                          return {parentOverflow:getComputedStyle(parent).overflowY,hasOwnScroller,linked,canScroll,visibleAtEnd,moved};
                        }""")
                        assert flow["parentOverflow"]=="auto" and not flow["hasOwnScroller"] and flow["linked"],flow
                        assert not flow["canScroll"] or (flow["visibleAtEnd"] and flow["moved"]>0),flow
                    expect(page.locator(".batch-series-properties #batch-count-input")).to_have_count(0)
                    expect(page.locator(".batch-series-dock #batch-count-input")).to_be_visible()
                    expect(page.locator(".batch-series-properties #batch-strategy-fixed")).to_be_visible()
                    expect(page.locator("#batch-strategy-ai")).to_have_attribute("aria-pressed","true")
                    expect(page.locator(".batch-series-fixed-picker")).to_have_count(0)
                    expect(page.locator(".batch-series-layout-strategy")).to_be_visible()
                    expect(page.locator(".batch-series-layout-strategy .make-image-btn-group")).to_be_visible()
                    same_row=page.evaluate("""() => {
                      const title=document.querySelector('.batch-series-layout-strategy>.make-image-field-label').getBoundingClientRect();
                      const ai=document.querySelector('#batch-strategy-ai').getBoundingClientRect();
                      const fixed=document.querySelector('#batch-strategy-fixed').getBoundingClientRect();
                      const run=document.querySelector('#batch-btn-start');
                      return {
                        titleCenter:title.top+title.height/2,
                        aiCenter:ai.top+ai.height/2,
                        fixedCenter:fixed.top+fixed.height/2,
                        neutral:getComputedStyle(document.querySelector('#batch-strategy-ai')).backgroundColor,
                        primary:getComputedStyle(run).backgroundColor
                      };
                    }""")
                    assert abs(same_row["titleCenter"]-same_row["aiCenter"])<20,same_row
                    assert abs(same_row["aiCenter"]-same_row["fixedCenter"])<12,same_row
                    assert same_row["neutral"]!=same_row["primary"],same_row
                    assert page.locator("#batch-strategy-ai").get_attribute("class").find("btn-primary is-active") >= 0
                    expect(page.locator(".batch-series-properties [data-pick-layout-idx='0']")).to_be_visible()
                    expect(page.locator("#batch-concurrency")).to_have_count(0)
                    expect(page.locator("#batch-layout-req-input")).to_have_count(0)
                    expect(page.locator(".batch-series-dock #batch-seed-input")).to_be_visible()
                    expect(page.locator(".batch-series-dock #batch-btn-plan")).to_be_visible()
                    expect(page.locator(".batch-series-dock #batch-btn-start")).to_be_visible()
                    expect(page.locator("#batch-btn-start")).to_have_text("生成系列图")
                    assert not any(ch.isdigit() for ch in page.locator("#batch-btn-start").inner_text())
                    expect(page.locator(".batch-series-composer-attachments")).to_have_count(0)
                    expect(page.locator(".batch-series-composer-bottom > .batch-series-add-reference")).to_be_visible()
                    assert page.locator(".batch-series-composer-bottom").evaluate("""node => {
                      const plus=node.querySelector(".batch-series-add-reference").getBoundingClientRect();
                      const plan=node.querySelector("#batch-btn-plan").getBoundingClientRect();
                      const count=node.querySelector("#batch-count-input").getBoundingClientRect();
                      const generate=node.querySelector("#batch-btn-start").getBoundingClientRect();
                      return plus.left < count.left && count.left < plan.left && plan.left < generate.right;
                    }""")
                    assert "写下整套主题及随机" not in page.locator(".batch-series-composer-bottom").inner_text()
                    assert page.evaluate("""() => {
                      const r=s=>document.querySelector(s).getBoundingClientRect();
                      const a=r('.batch-series-shared'),b=r('.batch-series-selected-settings'),
                            main=r('.batch-series-main-card'),thumb=r('.batch-series-thumbs');
                      const panel=document.querySelector('.batch-series-properties');
                      return b.top>=a.bottom-1 && thumb.left>=main.right-1
                        && getComputedStyle(panel).overflowY==="auto" === (innerWidth>980);
                    }""")
                    # Before generation each thumbnail is a simple 图N placeholder.
                    expect(page.locator(".batch-series-thumb img")).to_have_count(0)
                    assert page.locator('.batch-series-thumb[data-series-select-idx="0"] .batch-series-thumb-empty').inner_text()=="图1"
                    assert page.locator('.batch-series-thumb[data-series-select-idx="1"] .batch-series-thumb-empty').inner_text()=="图2"
                    expect(page.locator(".batch-series-thumb-number")).to_have_count(0)
                    expect(page.locator(".batch-series-thumb-status")).to_have_count(0)
                    # Fixed layout reveals a real picker matching the single-image cards.
                    page.locator("#batch-strategy-fixed").click()
                    expect(page.locator(".batch-series-fixed-picker [data-pick-kind='layout']")).to_be_visible()
                    assert page.locator("#batch-strategy-fixed").get_attribute("class").find("btn-primary is-active")>=0
                    assert page.locator(".batch-series-fixed-picker").evaluate("""el => {
                      const color=document.querySelector('.batch-pickers-row [data-pick-kind="color"]').getBoundingClientRect();
                      const picker=el.getBoundingClientRect();
                      return picker.top>=color.bottom-2;
                    }""")
                    consistent_width=page.evaluate("""() => {
                      const main=document.querySelector('.batch-pickers-row [data-pick-kind="style1"]').getBoundingClientRect();
                      const layout=document.querySelector('.batch-series-fixed-picker [data-pick-kind="layout"]').getBoundingClientRect();
                      return {style:main.width,layout:layout.width,diff:Math.abs(main.width-layout.width)};
                    }""")
                    assert consistent_width["diff"]<2,consistent_width
                    page.locator(".batch-series-fixed-picker [data-pick-kind='layout']").click()
                    assert page.evaluate("fixture.counts().pickers")==1
                    # Count drives actual prepared slots, not just an input annotation.
                    expect(page.locator("#batch-count-input")).to_have_attribute("min","1")
                    expect(page.locator("#batch-count-input")).to_have_attribute("max","10")
                    page.locator("#batch-count-input").fill("11")
                    page.locator("#batch-count-input").blur()
                    expect(page.locator("#batch-count-input")).to_have_value("10")
                    expect(page.locator(".batch-series-thumb")).to_have_count(10)
                    page.locator("#batch-count-input").fill("0")
                    page.locator("#batch-count-input").blur()
                    expect(page.locator("#batch-count-input")).to_have_value("1")
                    expect(page.locator(".batch-series-thumb")).to_have_count(1)
                    page.locator("#batch-count-input").fill("3")
                    page.locator("#batch-count-input").blur()
                    expect(page.locator("#batch-count-input")).to_have_value("3")
                    expect(page.locator(".batch-series-thumb")).to_have_count(3)
                    expect(page.locator(".batch-series-focused")).to_have_count(1)
                    page.locator("#batch-strategy-ai").click()
                    expect(page.locator(".batch-series-fixed-picker")).to_have_count(0)
                    page.locator("#batch-mode-fusion").click()
                    page.locator('[data-pick-kind="style1"]').press("Space")
                    assert page.evaluate("fixture.counts().pickers")==2
                    # Mother-theme input includes natural-language layout requests.
                    page.locator("#batch-seed-input").fill("城市散步，三张图片采用随机图型")
                    page.locator("#batch-btn-pick-global-refs").click()
                    assert page.evaluate("fixture.counts().refs")==1
                    page.locator("#batch-btn-plan").click()
                    expect(page.locator(".batch-series-thumb")).to_have_count(3)
                    expect(page.locator(".batch-series-focused")).to_have_count(1)
                    expect(page.locator(".batch-series-thumb[aria-selected='true']")).to_have_count(1)
                    expect(page.locator("#batch-series-theme-0")).to_have_value("晨间咖啡")
                    expect(page.locator(".batch-series-selected-settings > .batch-series-section-title > strong")).to_contain_text("图 1")
                    expect(page.locator(".batch-series-focused[data-batch-row='0']")).to_be_visible()
                    page.locator('[data-series-select-idx="1"]').click()
                    expect(page.locator(".batch-series-selected-settings > .batch-series-section-title > strong")).to_contain_text("图 2")
                    expect(page.locator(".batch-series-focused[data-batch-row='1']")).to_be_visible()
                    expect(page.locator("#batch-series-theme-1")).to_have_value("午后公园")
                    expect(page.locator(".batch-series-properties [data-pick-layout-idx='1']")).to_be_visible()
                    page.locator("#batch-series-theme-1").fill("午后公园的暖光与树影")
                    page.locator("#batch-series-theme-1").blur()
                    theme_diag=page.evaluate("""() => ({
                      mode:fixture.parts.loop.data.batchLayoutMode,
                      rows:fixture.parts.loop.data.batchRows,
                      promptListText:fixture.parts.loop.data.promptListText,
                      selected:fixture.controller.selectedSeriesIndex,
                      editor:document.querySelector('#batch-series-theme-1')?.value
                    })""")
                    assert theme_diag["rows"][1]["theme"]=="午后公园的暖光与树影",theme_diag
                    page.locator('[data-pick-layout-idx="1"]').click()
                    assert page.evaluate("fixture.counts().pickers")==3
                    # Current-picture refs belong inside composer, independent of global refs.
                    page.locator('[data-pick-row-refs-idx="1"]').click()
                    assert page.evaluate("fixture.counts().refs")==2
                    page.evaluate("""() => {
                      fixture.parts.loop.data.batchRows[1].assetItems=[
                        {id:"A-01",name:"独立参考",image:fixture.pixel}];
                      fixture.render();
                    }""")
                    expect(page.locator(".batch-series-composer-attachments .batch-series-attachment")).to_have_count(1)
                    expect(page.locator('.batch-series-attachment [data-remove-series-ref="0"]')).to_be_visible()
                    page.locator('.batch-series-attachment [data-remove-series-ref="0"]').click()
                    assert page.evaluate("fixture.parts.loop.data.batchRows[1].assetItems.length")==0
                    page.locator('[data-series-select-idx="0"]').click()
                    expect(page.locator("#batch-series-theme-0")).to_have_value("晨间咖啡")
                    expect(page.locator(".batch-series-selected-settings > .batch-series-section-title > strong")).to_contain_text("图 1")
                    page.locator('[data-series-select-idx="1"]').click()
                    expect(page.locator("#batch-series-theme-1")).to_have_value("午后公园的暖光与树影")
                    page.locator('[data-series-composer-mode="series"]').click()
                    expect(page.locator("#batch-seed-input")).to_have_value("城市散步，三张图片采用随机图型")
                    page.locator('[data-series-composer-mode="image"]').click()
                    page.locator("#batch-btn-start").scroll_into_view_if_needed()
                    check_bar(page,"#batch-btn-start")
                    page.screenshot(path=str(OUT/f"{kind}-{width}.png"),full_page=True)
                    # Direct generation of selected picture 3 must use one slot,
                    # not the batch CTA. Reuse the single-image shimmer.
                    page.locator('[data-series-select-idx="2"]').click()
                    page.locator('[data-generate-series-idx="2"]').click()
                    assert page.evaluate("fixture.counts().singles")==[2]
                    assert page.evaluate("fixture.counts().runs")==0
                    expect(page.locator(".batch-series-focused .batch-series-pending")).to_be_visible()
                    expect(page.locator(".batch-series-focused .make-image-pending-art")).to_be_visible()
                    expect(page.locator(".batch-series-focused .make-image-pending-shimmer")).to_be_visible()
                    page.evaluate("""() => {
                      fixture.context.busy=false;
                      fixture.controller.updateProgress({
                        updatedIndex:2,
                        itemResult:{imageUrl:fixture.pixel,title:"图3已单独生成"},
                        completedCount:1,failedCount:0,totalCount:3,
                        activeIndex:null,activeIndices:[],busy:false,batchId:"ui-single"
                      });
                    }""")
                    expect(page.locator('.batch-series-thumb[data-series-select-idx="2"].has-result')).to_have_count(1)
                    page.locator('[data-series-select-idx="0"]').click()
                    page.locator("#batch-btn-start").click()
                    assert page.evaluate("fixture.counts().runs")==1
                    expect(page.locator('.batch-series-thumb[data-series-select-idx="2"].has-result')).to_have_count(1)
                    expect(page.locator("#batch-btn-stop")).to_be_visible()
                    expect(page.locator(".batch-series-focused .batch-series-pending")).to_be_visible()
                    expect(page.locator(".batch-series-thumb")).to_have_count(3)
                    expect(page.locator(".batch-results-section")).to_have_count(0)
                    # Concurrent progress updates the selected main image and
                    # other thumbnail statuses, not a second result list.
                    page.evaluate("""() => fixture.controller.updateProgress({
                      updatedIndex:0,
                      itemResult:{imageUrl:fixture.pixel,title:"第1张成图"},
                      completedCount:2,failedCount:0,totalCount:3,
                      activeIndex:1,activeIndices:[1],busy:true
                    })""")
                    expect(page.locator('.batch-series-focused[data-batch-row="0"] .is-generated')).to_have_count(1)
                    expect(page.locator('.batch-series-thumb[data-series-select-idx="0"].has-result img')).to_have_count(1)
                    expect(page.locator('.batch-series-thumb[data-series-select-idx="0"] .batch-series-thumb-overlay')).to_have_count(1)
                    # Text overlays exist only as hover/focus affordances over completed pictures.
                    overlay=page.locator('.batch-series-thumb[data-series-select-idx="0"] .batch-series-thumb-overlay')
                    assert float(overlay.evaluate("el => getComputedStyle(el).opacity")) == 0
                    page.locator('.batch-series-thumb[data-series-select-idx="0"]').hover()
                    expect(overlay).to_have_css("opacity","1")
                    expect(page.locator("#batch-btn-download-all")).to_be_enabled()
                    expect(page.locator('.batch-series-thumb[data-series-select-idx="1"].is-generating')).to_have_count(1)
                    page.locator('[data-series-select-idx="1"]').click()
                    expect(page.locator(".batch-series-focused .batch-series-pending")).to_be_visible()
                    page.evaluate("""() => fixture.controller.updateProgress({
                      updatedIndex:1,
                      itemResult:{failed:true,error:"模拟生成失败"},
                      completedCount:2,failedCount:1,totalCount:3,
                      activeIndex:null,activeIndices:[],busy:true
                    })""")
                    expect(page.locator('.batch-series-focused[data-batch-row="1"] [data-retry-idx="1"]')).to_be_visible()
                    expect(page.locator('.batch-series-thumb[data-series-select-idx="2"].has-result')).to_have_count(1)
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
