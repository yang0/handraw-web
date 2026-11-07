/* Article illustration workspace interactions: selective queue, history, variants. */
(function (global) {
  "use strict";
  const escape = (v)=>String(v??"").replace(/[&<>"']/g,x=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[x]));
  const validUrl = (v)=>typeof v==="string" && (/^https?:\/\//i.test(v) || /^\/[^/]/.test(v) || /^data:image\/(?:png|jpeg|webp|gif);base64,/i.test(v));
  const normalizeHistory = (history)=> {
    const unique=new Map();
    (history||[]).forEach(entry=>(entry?.items||[]).forEach(img=>{
      if(!validUrl(img.imageUrl))return;
      if(!unique.has(img.imageUrl))unique.set(img.imageUrl,{
        url:img.imageUrl,title:img.title||entry.articleTitle||entry.tabTitle||"历史图片",
        ratio:img.ratio||"",from:entry.createdAt||"",engine:entry.engine||""
      });
    }));
    return [...unique.values()].slice(0,120);
  };
  const choices = (cards, selectedIds)=> (cards||[]).filter(c=>c && !c.imageUrl && c.status!=="generating" && selectedIds.includes(String(c.id)));
  function selectGeneration(cards, {defaultParallel=2}={}){
    const pending=(cards||[]).filter(c=>c && !c.imageUrl && c.status!=="generating");
    if(!pending.length)return Promise.resolve({approved:false, ids:[],parallel:1});
    return new Promise(resolve=>{
      const cover=document.createElement("div");cover.className="hw-article-p2-overlay";
      cover.innerHTML=`<section class="hw-article-p2-dialog" role="dialog" aria-modal="true" aria-labelledby="hw-select-title">
        <header><span class="hw-article-p2-kicker">HANDRAW · 批量任务清单</span>
        <h2 id="hw-select-title">选择这次要生成的图片</h2>
        <p>取消勾选的图位保留在文章中，不会提交、也不会扣费；已经完成的图自动跳过。</p></header>
        <div class="hw-article-p2-toolbar"><label><input type="checkbox" data-select-all checked> 全选待生成</label>
        <label>并发数 <select data-parallel><option value="1">1 · 顺序</option><option value="2">2 · 推荐</option><option value="3">3 · 高速</option></select></label></div>
        <div class="hw-article-p2-list">${pending.map(c=>`<label class="hw-article-p2-choice">
          <input type="checkbox" data-card-id="${escape(c.id)}" checked>
          <span><strong>${escape(c.title||"配图")}</strong><small>${escape(c.purpose||c.subject||"等待生成")}</small></span></label>`).join("")}</div>
        <p class="hw-article-p2-count" role="status" aria-live="polite"></p>
        <footer><button type="button" data-cancel>返回编辑</button><button type="button" data-start class="hw-article-p2-primary">继续确认费用</button></footer>
      </section>`;
      const select=cover.querySelector("[data-parallel]");select.value=String(Math.max(1,Math.min(3,defaultParallel)));
      const all=cover.querySelector("[data-select-all]"),boxes=()=>[...cover.querySelectorAll("[data-card-id]")];
      const apply=cover.querySelector("[data-start]"),count=cover.querySelector(".hw-article-p2-count");
      const update=()=>{const n=boxes().filter(x=>x.checked).length;count.textContent=`本次选择 ${n} / ${pending.length} 张`;apply.disabled=n===0;all.checked=n===pending.length;all.indeterminate=n>0&&n<pending.length;};
      let done=false;const oldFocus=document.activeElement;
      const finish=(approved)=>{if(done)return;done=true;cover.removeEventListener("keydown",key);
        const ids=approved?boxes().filter(x=>x.checked).map(x=>x.getAttribute("data-card-id")):[];
        const parallel=Number(select.value);cover.remove();if(oldFocus?.isConnected)oldFocus.focus();resolve({approved,ids,parallel});};
      function key(e){if(e.key==="Escape"){e.preventDefault();finish(false);} }
      all.onchange=()=>{boxes().forEach(x=>x.checked=all.checked);update();};
      boxes().forEach(x=>x.onchange=update);
      cover.querySelector("[data-cancel]").onclick=()=>finish(false);
      apply.onclick=()=>finish(true);
      cover.addEventListener("keydown",key);
      document.body.appendChild(cover);update();cover.querySelector("[data-cancel]").focus();
    });
  }
  async function runPool(items, concurrency, worker, shouldStop=()=>false, onSettled=()=>{}){
    const results=new Array(items.length).fill(false);let cursor=0;
    const threads=Array.from({length:Math.min(items.length,Math.max(1,Math.min(3,Number(concurrency)||1)))},async()=>{
      while(!shouldStop()){
        const i=cursor++;if(i>=items.length)return;
        try{results[i]=Boolean(await worker(items[i],i));}catch(_){results[i]=false;}
        onSettled(items[i],results[i],i);
      }
    });
    await Promise.all(threads);return results;
  }
  function chooseHistory(history, title="将历史图片放到当前图位"){
    const images=normalizeHistory(history);
    return new Promise(resolve=>{
      const cover=document.createElement("div");cover.className="hw-article-p2-overlay";
      cover.innerHTML=`<section class="hw-article-p2-dialog" role="dialog" aria-modal="true" aria-labelledby="hw-history-title">
        <header><span class="hw-article-p2-kicker">HANDRAW · 我的素材</span><h2 id="hw-history-title">${escape(title)}</h2>
        <p>从你自己已生成的历史图片选择。插入现有图片不发起生图请求，也不会扣费。</p></header>
        <input type="search" class="hw-article-p2-search" placeholder="搜索标题或主题" aria-label="搜索历史图片">
        <div class="hw-article-p2-gallery"></div><footer><button type="button" data-cancel>取消</button></footer>
      </section>`;
      const gallery=cover.querySelector(".hw-article-p2-gallery"),search=cover.querySelector("input");
      let done=false;const prev=document.activeElement;
      const finish=(v)=>{if(done)return;done=true;cover.remove();if(prev?.isConnected)prev.focus();resolve(v)};
      const render=()=>{
        const query=search.value.trim().toLowerCase();
        const visible=images.map((img,i)=>({...img,index:i})).filter(x=>!query||x.title.toLowerCase().includes(query));
        gallery.innerHTML=visible.length?visible.map(x=>`<button type="button" data-image-index="${x.index}" class="hw-article-p2-gallery-card">
          <img src="${escape(x.url)}" alt="${escape(x.title)}" loading="lazy"><span>${escape(x.title)}</span><small>${escape(x.ratio)}</small></button>`).join(""):'<p class="hw-article-p2-empty">没有找到可插入的历史图片。请先完成一次生图。</p>';
        gallery.querySelectorAll("[data-image-index]").forEach(b=>b.onclick=()=>finish(images[Number(b.dataset.imageIndex)]));
      };
      cover.querySelector("[data-cancel]").onclick=()=>finish(null);
      cover.addEventListener("keydown",e=>{if(e.key==="Escape")finish(null)});
      search.oninput=render;document.body.appendChild(cover);render();search.focus();
    });
  }
  function chooseVariant(card){
    const variants=Array.isArray(card.variants)?card.variants.filter(x=>validUrl(x.imageUrl)):[];
    if(card.imageUrl&&!variants.some(x=>x.imageUrl===card.imageUrl))variants.unshift({imageUrl:card.imageUrl,source:"当前版本"});
    if(variants.length<2)return Promise.resolve(null);
    return new Promise(resolve=>{
      const cover=document.createElement("div");cover.className="hw-article-p2-overlay";
      cover.innerHTML=`<section class="hw-article-p2-dialog" role="dialog" aria-modal="true" aria-labelledby="hw-variant-title">
        <header><span class="hw-article-p2-kicker">HANDRAW · 图片版本</span><h2 id="hw-variant-title">对比并选择图片</h2><p>旧图不会因重新生成而丢失。选择其中一张作为当前文章配图。</p></header>
        <div class="hw-article-p2-gallery">${variants.map((v,i)=>`<button type="button" data-variant="${i}" class="hw-article-p2-gallery-card">
        <img src="${escape(v.imageUrl)}" alt="候选图 ${i+1}" loading="lazy"><strong>${escape(v.source||"版本 "+(i+1))}</strong><small>${v.imageUrl===card.imageUrl?"当前使用":"点击采用"}</small></button>`).join("")}</div>
        <footer><button type="button" data-cancel>暂不替换</button></footer></section>`;
      const prev=document.activeElement;let done=false;
      const finish=(v)=>{if(done)return;done=true;cover.remove();if(prev?.isConnected)prev.focus();resolve(v)};
      cover.querySelectorAll("[data-variant]").forEach(b=>b.onclick=()=>finish(variants[Number(b.dataset.variant)]));
      cover.querySelector("[data-cancel]").onclick=()=>finish(null);
      cover.addEventListener("keydown",e=>{if(e.key==="Escape")finish(null)});
      document.body.appendChild(cover);cover.querySelector("[data-cancel]").focus();
    });
  }
  function pushVariant(card,oldUrl,source="此前版本"){
    if(!validUrl(oldUrl))return;
    const v=Array.isArray(card.variants)?card.variants:[];
    if(!v.some(x=>x.imageUrl===oldUrl))v.unshift({imageUrl:oldUrl,source,createdAt:Date.now()});
    card.variants=v.slice(0,8);
  }
  global.HandrawArticleWorkbench={normalizeHistory,choices,selectGeneration,runPool,chooseHistory,chooseVariant,pushVariant};
})(window);
