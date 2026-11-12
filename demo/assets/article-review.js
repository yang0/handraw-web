/* Handraw article-plan review: user confirms AI suggestions before mutations. */
(function(global) {
  "use strict";
  const esc = (v)=>String(v==null?"":v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const purpose = (c)=>String(c.purpose||"").trim() || (c.role==="cover" ? "为整篇文章建立视觉主题" : "辅助理解这一段的核心内容");
  function reviewPlan(cards, meta={}) {
    const reconciled=global.HANDRAW_CANVAS_ENGINE.reconcileArticlePlan(cards,meta.existingCards);
    const list=reconciled.cards,retained=new Set(reconciled.retainedIds);
    if (!list.length) return Promise.resolve({approved:false,cards:[]});
    return new Promise((resolve)=>{
      const overlay=document.createElement("div");
      overlay.className="hw-article-plan-review-overlay";
      const kind=meta.articleType==="narrative"?"叙事类":"知识类";
      const source=meta.source==="model"?"AI 规划":"章节模板（AI 不可用）";
      const old=Array.isArray(meta.existingCards)?meta.existingCards:[];
      overlay.innerHTML=`<section class="hw-article-plan-review" role="dialog" aria-modal="true" aria-labelledby="hw-art-plan-review-title">
        <header><div class="hw-art-review-kicker">HANDRAW · 视觉编辑审查</div>
        <h2 id="hw-art-plan-review-title">确认配图建议</h2>
        <p>系统建议了 ${list.length} 个图位。可以取消不需要的图片，确定后才会写入文章。旧方案在确认前保持不变。</p>
        <div class="hw-art-review-tags"><span>${esc(kind)}</span><span>${esc(source)}</span><span>旧方案 ${old.length} 张</span></div></header>
        <div class="hw-art-review-list" role="group" aria-label="选择需要应用的配图建议">
          ${list.map((c,i)=>`<label class="hw-art-review-choice">
            <input type="checkbox" data-art-review-check="${i}" checked />
            <span class="hw-art-review-main"><strong>${esc(c.role==="cover"?"封面":c.title||"正文插图 "+i)}${retained.has(c.id)?" · 保留原图位":""}</strong>
            ${c.imageUrl?`<small>已保留采用图片${retained.has(c.id)?"；未匹配到新建议，取消勾选才会移除":""}</small>`:retained.has(c.id)?"<small>未匹配到新建议，默认保留；取消勾选才会移除</small>":""}
            <small>${esc(c.role==="cover"?"文章开头":c.anchorText?"位于「"+c.anchorText+"」之后":"正文第 "+((Number(c.afterBlockIdx)||0)+1)+" 段之后")}</small>
            <span class="hw-art-review-purpose"><b>推荐理由</b> ${esc(purpose(c))}</span>
            <span class="hw-art-review-subject"><b>画面建议</b> ${esc(c.subject||"待调整")}</span>
            <small>${esc(c.layoutId||"自由构图")} · ${esc(c.ratio||"4:3")}</small></span></label>`).join("")}
        </div>
        <p class="hw-art-review-summary" role="status" aria-live="polite"></p>
        <footer><button type="button" data-review-cancel>保持原方案</button>
        <button type="button" class="hw-art-review-apply" data-review-apply>应用选择的配图位</button></footer>
      </section>`;
      let settled=false;
      const previousFocus=document.activeElement;
      const checks=()=>[...overlay.querySelectorAll("[data-art-review-check]")];
      const apply=overlay.querySelector("[data-review-apply]");
      const summary=overlay.querySelector(".hw-art-review-summary");
      function update(){
        const count=checks().filter(x=>x.checked).length;
        summary.textContent=`已选 ${count} / ${list.length} 张 · 最多 200 个图位 · 不会在此步骤扣除生图费用`;
        apply.disabled=count===0||count>200;
      }
      function finish(approved) {
        if(settled)return;
        settled=true;
        overlay.removeEventListener("keydown",onKeydown);
        overlay.remove();
        if(previousFocus?.isConnected&&typeof previousFocus.focus==="function")previousFocus.focus();
        resolve({approved,cards:approved?list.filter((_,i)=>checksSnapshot[i]):[]});
      }
      let checksSnapshot=[];
      function onKeydown(e){
        if(e.key==="Escape"){e.preventDefault();finish(false);}
        if(e.key==="Tab"){
          const focusables=[...overlay.querySelectorAll('input,button:not(:disabled)')];
          if(e.shiftKey&&document.activeElement===focusables[0]){e.preventDefault();focusables[focusables.length-1].focus();}
          else if(!e.shiftKey&&document.activeElement===focusables[focusables.length-1]){e.preventDefault();focusables[0].focus();}
        }
      }
      overlay.querySelector("[data-review-cancel]").onclick=()=>finish(false);
      apply.onclick=()=>{
        checksSnapshot=checks().map(x=>x.checked);
        finish(true);
      };
      checks().forEach(x=>x.onchange=update);
      overlay.addEventListener("keydown",onKeydown);
      document.body.appendChild(overlay);
      update();
      overlay.querySelector("[data-review-cancel]").focus();
    });
  }
  function fidelitySummary(result){
    const segments=Array.isArray(result?.segments)?result.segments:[];
    const failures=segments.filter(s=>!s.aiUsed).length;
    const issues=segments.reduce((n,s)=>n+(Array.isArray(s.issues)?s.issues.length:0),0);
    const ratio=typeof result?.charDiffRatio==="number"?Math.round(result.charDiffRatio*1000)/10:null;
    return {segments,failures,issues,ratio};
  }
  global.HandrawArticleReview={reviewPlan,fidelitySummary};
})(window);
