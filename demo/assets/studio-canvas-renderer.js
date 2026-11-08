/* Issue #127 · Canvas 2.0 DOM and runtime boundaries.
 * Preserve native image elements, active input and unrelated cards across
 * selection/result updates. Graph history is strictly edit-only; V3 Run
 * identities and immutable generated results are never rewound by Undo.
 */
(function(root,factory){
  "use strict";
  const api=factory();
  root.HandrawCanvasRenderer=api;
  if(typeof module==="object"&&module.exports)module.exports=api;
})(typeof window!=="undefined"?window:globalThis,function(){
  "use strict";
  const renderedMarkup=new WeakMap();
  const own=(x,k)=>Object.prototype.hasOwnProperty.call(x||{},k);
  const clone=x=>x==null?x:JSON.parse(JSON.stringify(x));
  const classFlag=(el,name,on)=>el.classList.toggle(name,Boolean(on));
  const key=el=>el?.classList?.contains("ic-node")
    ?"node:"+el.getAttribute("data-node-id")
    :el?.tagName==="DATALIST"?"list:"+el.id:"";
  const rootFlags=html=>String(html).replace(
    /(<div\s+class="ic-node\b[^"]*)\bis-selected\b/g,"$1")
    .replace(/(<div\s+class="ic-node\b[^"]*)\bis-related\b/g,"$1")
    .replace(/\s{2,}/g," ");
  const flags=el=>({
    selected:el.classList.contains("is-selected"),
    related:el.classList.contains("is-related")
  });
  const selector=el=>{
    for(const attr of el.getAttributeNames?.()||[]){
      if(attr.startsWith("data-")&&attr!=="data-canvas-no-zoom")
        return "["+attr+"="+JSON.stringify(el.getAttribute(attr))+"]";
    }
    return el.name?"[name="+JSON.stringify(el.name)+"]":null;
  };
  function saveFocus(old){
    const active=old?.ownerDocument?.activeElement;
    if(!active||!old.contains(active))return null;
    const controls=[...old.querySelectorAll("input,textarea,select,[contenteditable]")];
    const index=controls.indexOf(active);
    if(index<0)return null;
    const snapshot={index,selector:selector(active),
      value:"value"in active?active.value:null,
      start:null,end:null,scrollTop:active.scrollTop};
    try{snapshot.start=active.selectionStart;snapshot.end=active.selectionEnd;}catch(_){}
    return snapshot;
  }
  function restoreFocus(fresh,focus){
    if(!focus)return;
    const inputs=[...fresh.querySelectorAll("input,textarea,select,[contenteditable]")];
    const replacement=focus.selector?fresh.querySelector(focus.selector):null;
    const target=replacement||inputs[focus.index];
    if(!target)return;
    if(focus.value!=null&&"value"in target)target.value=focus.value;
    target.focus({preventScroll:true});
    target.scrollTop=focus.scrollTop;
    if(typeof target.setSelectionRange==="function"&&
      Number.isInteger(focus.start)&&Number.isInteger(focus.end)){
      try{target.setSelectionRange(focus.start,focus.end);}catch(_){}
    }
  }
  function preserveImages(old,fresh){
    const pool=new Map();
    for(const img of old.querySelectorAll("img")){
      const url=img.getAttribute("data-hw-src")||img.getAttribute("src")||"";
      if(!url)continue;
      const items=pool.get(url)||[];items.push(img);pool.set(url,items);
    }
    let reused=0;
    for(const img of [...fresh.querySelectorAll("img")]){
      const url=img.getAttribute("data-hw-src")||img.getAttribute("src")||"";
      const candidates=pool.get(url);
      if(!url||!candidates?.length)continue;
      const prior=candidates.shift();
      // In-flight image requests survive because we reuse the same element
      // rather than cloning/assigning src, including progressive placeholders.
      for(const attr of [...prior.attributes]){
        if(!img.hasAttribute(attr.name))prior.removeAttribute(attr.name);
      }
      for(const attr of [...img.attributes]){
        if(prior.getAttribute(attr.name)!==attr.value)prior.setAttribute(attr.name,attr.value);
      }
      img.replaceWith(prior);reused++;
    }
    return reused;
  }
  function reconcile(layer,cardsHtml,datalistsHtml){
    const template=layer.ownerDocument.createElement("template");
    template.innerHTML=cardsHtml+datalistsHtml;
    const desired=[...template.content.children],existing=new Map();
    for(const el of [...layer.children]){const id=key(el);if(id)existing.set(id,el);}
    const seen=new Set(),dirtyNodes=[],stat={
      nodes:0,inserted:0,replaced:0,removed:0,reused:0,
      selectionOnly:0,imagesPreserved:0,changedIds:[]
    };
    for(const fresh of desired){
      const id=key(fresh);if(!id)continue;
      seen.add(id);
      const old=existing.get(id),html=fresh.outerHTML;
      if(id.startsWith("node:"))stat.nodes++;
      if(!old){
        layer.appendChild(fresh);renderedMarkup.set(fresh,html);
        if(id.startsWith("node:"))dirtyNodes.push(fresh);
        stat.inserted++;stat.changedIds.push(id);
        continue;
      }
      const previous=renderedMarkup.get(old)||old.outerHTML;
      if(previous===html){stat.reused++;continue;}
      if(id.startsWith("node:")&&rootFlags(previous)===rootFlags(html)){
        const f=flags(fresh);
        classFlag(old,"is-selected",f.selected);
        classFlag(old,"is-related",f.related);
        renderedMarkup.set(old,html);
        stat.selectionOnly++;continue;
      }
      const focus=saveFocus(old);
      stat.imagesPreserved+=preserveImages(old,fresh);
      old.replaceWith(fresh);
      renderedMarkup.set(fresh,html);
      restoreFocus(fresh,focus);
      if(id.startsWith("node:"))dirtyNodes.push(fresh);
      stat.replaced++;stat.changedIds.push(id);
    }
    for(const [id,old] of existing){
      if(!seen.has(id)){old.remove();stat.removed++;stat.changedIds.push(id);}
    }
    return {dirtyNodes,stats:stat};
  }
  function updateSelection(layer,ids,related){
    const selected=new Set(ids||[]),rel=new Set(related||[]);
    let updated=0;
    for(const el of layer.querySelectorAll(".ic-node[data-node-id]")){
      const nid=el.getAttribute("data-node-id");
      const a=selected.has(nid),b=rel.has(nid)&&!a;
      if(el.classList.contains("is-selected")!==a||
         el.classList.contains("is-related")!==b){
        classFlag(el,"is-selected",a);classFlag(el,"is-related",b);
        // Correct the cache after fast selection path on next full render.
        const markup=renderedMarkup.get(el);
        if(markup)renderedMarkup.delete(el);
        updated++;
      }
    }
    return updated;
  }
  const RUN_FIELDS=new Set([
    "runId","runIds","runRef","runRefs","runProjection","studio2RunSnapshot",
    "activeBatchId","pendingTaskId","pendingTaskIds","pendingRequestId",
    "pendingRequestIds","lastRunId","lastRunItemId","lastResultRunId",
    "status","generationStatus","generationRunId","generationItemId",
    "errorText","elapsedSec","lastGeneratedAt"
  ]);
  const ARTICLE_CARD_FIELDS=new Set([
    "imageUrl","mediaId","runId","runItemId","requestId",
    "status","imageSource","historyImageTitle","errorText",
    "variants","generationVariants","generatedVariants"
  ]);
  function preserveRuntime(current,restore){
    const next=clone(restore),existing=new Map((current?.nodes||[]).map(n=>[n.id,n]));
    const target=new Map((next.nodes||[]).map(n=>[n.id,n]));
    for(const [id,cur] of existing){
      let dest=target.get(id);
      if(cur.type==="output_display"){
        if(!dest){
          dest=clone(cur);next.nodes.push(dest);target.set(id,dest);
        }else{
          dest.data=clone(cur.data);
          // Display nodes and Run media are not edit history.
          dest.w=cur.w;dest.h=cur.h;
        }
        continue;
      }
      if(!dest||dest.type!==cur.type)continue;
      if(cur.type==="output_control"||cur.type==="loop"){
        dest.data=dest.data||{};
        for(const name of RUN_FIELDS){
          if(own(cur.data,name))dest.data[name]=clone(cur.data[name]);
          else delete dest.data[name];
        }
      }
      if(cur.type==="article_plan"){
        const cards=new Map((cur.data?.cards||[]).map(c=>[c.id,c]));
        for(const card of dest.data?.cards||[]){
          const live=cards.get(card.id);
          if(!live)continue;
          for(const name of ARTICLE_CARD_FIELDS){
            if(own(live,name))card[name]=clone(live[name]);
            else delete card[name];
          }
        }
      }
    }
    // Results may have arrived after this undo snapshot was captured.
    // Do not restore stale or duplicate result edges.
    const edges=new Map((next.edges||[]).map(e=>[e.id,e]));
    for(const edge of current?.edges||[]){
      if(!edges.has(edge.id) && (existing.get(edge.from)?.type==="output_display"||
        existing.get(edge.to)?.type==="output_display")){
        if(target.has(edge.from)&&target.has(edge.to)){
          next.edges.push(clone(edge));edges.set(edge.id,edge);
        }
      }
    }
    if(Array.isArray(current?.runRefs))next.runRefs=clone(current.runRefs);
    if(current?.meta?.runRefs){
      next.meta=next.meta||{};
      next.meta.runRefs=clone(current.meta.runRefs);
    }
    next.revision=Math.max(Number(current?.revision)||0,Number(next.revision)||0)+1;
    return next;
  }
  return Object.freeze({reconcile,updateSelection,preserveRuntime,
    // Exposed for controlled performance/DOM regression fixtures.
    rootFlags});
});
