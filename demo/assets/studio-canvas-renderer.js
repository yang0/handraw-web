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
  // partial=true receives only already-mounted dirty card markup. Full mode
  // alone owns unmount/removal and the authoritative node/datalist ordering.
  function reconcile(layer,cardsHtml,datalistsHtml,partial=false){
    const template=layer.ownerDocument.createElement("template");
    template.innerHTML=cardsHtml+datalistsHtml;
    const desired=[...template.content.children],existing=new Map();
    for(const el of [...layer.children]){const id=key(el);if(id)existing.set(id,el);}
    if(partial && desired.some(el=>!key(el)?.startsWith("node:") ||
      !existing.has(key(el))))throw new Error("canvas_dirty_render_invariant");
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
    if(!partial){
      for(const [id,old] of existing){
        if(!seen.has(id)){old.remove();stat.removed++;stat.changedIds.push(id);}
      }
    }
    stat.partial=Boolean(partial);
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
  // #111: Undo/Redo snapshots live only in per-tab browser memory. Clone
  // editable graph state, but SHARE immutable/authority-owned Run and media
  // payloads instead of JSON-copying them for every one of 35 history steps.
  // A deleted output node must still be restorable, hence no ID-only stubs.
  // Never serialize these history snapshots as durable project Graphs.
  // #111 P2: each edge render receives one immutable index of the current
  // Graph and one query of the rendered node elements. Old behavior used
  // Array.find + querySelector + offsetWidth/Height for EVERY edge endpoint.
  // Dimensions are cached once per distinct endpoint for this render only;
  // a subsequent render always remeasures after any card/content resize.
  function createEdgeGeometryIndex(nodes,layer){
    const model=new Map(),elements=new Map(),dimensions=new Map();
    for(const node of nodes||[]){
      if(node && !model.has(node.id))model.set(node.id,node);
    }
    for(const el of layer?.querySelectorAll?.(".ic-node[data-node-id]")||[]){
      const id=el.getAttribute("data-node-id");
      if(id!=null && !elements.has(id))elements.set(id,el);
    }
    const port=(node,dir)=>{
      if(!node)return {x:0,y:0};
      const id=String(node.id);
      let size=dimensions.get(id);
      if(!size){
        const el=elements.get(id);
        // Exactly match the old DOM-based geometry when a card is mounted.
        size={w:el?el.offsetWidth:(node.w||320),
              h:el?el.offsetHeight:(node.h||240)};
        dimensions.set(id,size);
      }
      return {x:dir==="in"?node.x:node.x+size.w,
              y:node.y+size.h*0.5};
    };
    return Object.freeze({getNode:id=>model.get(id)||null,port});
  }

  // An unrelated text edit or asynchronous result tick must not destroy all
  // SVG path elements; selection/edge movement still updates changed markup.
  // Only renderEdgesSvg and its explicit blank-Canvas reset modify this SVG.
  const edgeMarkupCache=new WeakMap();
  function reconcileEdgeMarkup(svg,markup){
    if(!svg)return false;
    if(edgeMarkupCache.get(svg)===markup)return false;
    svg.innerHTML=markup;
    edgeMarkupCache.set(svg,markup);
    return true;
  }
  // #111 P2: only during an active node drag. CSS classes, wiring and
  // selection do not change on this path; update the incident SVG path
  // geometry in place, preserving hit targets and unrelated edge elements.
  // Any missing graph/DOM invariant returns false for a full SVG fallback.
  function patchMovedEdgePaths(svg,graphEdges,nodes,layer,movedIds,pathFor){
    if(!svg?.querySelectorAll||typeof pathFor!=="function")return false;
    const moved=new Set((movedIds||[]).map(String));
    if(!moved.size)return false;
    const incident=(graphEdges||[]).filter(e=>
      moved.has(String(e.from))||moved.has(String(e.to)));
    if(!incident.length)return true;
    const groups=new Map();
    for(const el of svg.querySelectorAll("g.ic-edge-group[data-edge-id]")){
      const id=el.getAttribute("data-edge-id");
      if(groups.has(id))return false;
      groups.set(id,el);
    }
    const geometry=createEdgeGeometryIndex(nodes,layer),patches=[];
    for(const edge of incident){
      const from=geometry.getNode(edge.from),to=geometry.getNode(edge.to);
      const group=groups.get(String(edge.id));
      const hit=group?.querySelector("path.ic-edge-hit");
      const line=group?.querySelector("path.ic-edge-line");
      if(!from||!to||!hit||!line)return false;
      const a=geometry.port(from,"out"),b=geometry.port(to,"in");
      const d=pathFor(a.x,a.y,b.x,b.y);
      if(typeof d!=="string"||!d)return false;
      patches.push({hit,line,d});
    }
    // Preflight every edge before mutating any DOM: no half-patched SVG.
    for(const {hit,line,d} of patches){
      if(hit.getAttribute("d")!==d)hit.setAttribute("d",d);
      if(line.getAttribute("d")!==d)line.setAttribute("d",d);
    }
    // A later full render must compare against fresh markup, not the
    // pre-drag string that was cached before these in-place attribute writes.
    edgeMarkupCache.delete(svg);
    return true;
  }
  // #111 P2: a drag lasts for many pointermove events. Resolve the immutable
  // graph/edge-to-DOM topology once after selection has finished rendering,
  // then measure only the incident endpoints on each subsequent move.
  // Runtime/Graph/full-DOM replacement invalidates the session; the app can
  // perform an authoritative full-edge render and create another session.
  function createEdgeDragSession(svg,graphEdges,nodes,layer,movedIds,pathFor){
    if(!svg?.querySelectorAll||!layer?.querySelectorAll||
       !Array.isArray(graphEdges)||!Array.isArray(nodes)||
       typeof pathFor!=="function")return null;
    const moved=new Set((movedIds||[]).map(String));
    if(!moved.size)return null;
    const incident=graphEdges.filter(e=>e&&
      (moved.has(String(e.from))||moved.has(String(e.to))));
    const model=new Map(),modelPosition=new Map();
    for(let i=0;i<nodes.length;i++){
      const node=nodes[i],id=String(node?.id);
      if(!node||model.has(id))return null;
      model.set(id,node);modelPosition.set(id,i);
    }
    const elements=new Map();
    for(const el of layer.querySelectorAll(".ic-node[data-node-id]")){
      const id=el.getAttribute("data-node-id");
      if(id==null||elements.has(id))return null;
      elements.set(id,el);
    }
    const groups=new Map();
    for(const el of svg.querySelectorAll("g.ic-edge-group[data-edge-id]")){
      const id=el.getAttribute("data-edge-id");
      if(id==null||groups.has(id))return null;
      groups.set(id,el);
    }
    const bindings=[],watched=new Map(),sizes=new Map();
    for(let i=0;i<graphEdges.length;i++){
      const edge=graphEdges[i];
      if(!incident.includes(edge))continue;
      const fromId=String(edge.from),toId=String(edge.to);
      const from=model.get(fromId),to=model.get(toId);
      const fromEl=elements.get(fromId),toEl=elements.get(toId);
      const group=groups.get(String(edge.id));
      const hit=group?.querySelector("path.ic-edge-hit");
      const line=group?.querySelector("path.ic-edge-line");
      if(!from||!to||!fromEl||!toEl||!hit||!line)return null;
      bindings.push({edge,edgeIndex:i,id:String(edge.id),fromId,toId,
        from,fromIndex:modelPosition.get(fromId),
        to,toIndex:modelPosition.get(toId),fromEl,toEl,group,hit,line});
      watched.set(fromId,fromEl);watched.set(toId,toEl);
    }
    // Measure each distinct linked endpoint BEFORE any pointer movement.
    // Reading offsetWidth/Height after moving a card can force the entire
    // 300-node layout to synchronously flush on every mouse frame.
    for(const [id,el] of watched){
      const size={w:el.offsetWidth,h:el.offsetHeight};
      if(!Number.isFinite(size.w)||!Number.isFinite(size.h))return null;
      sizes.set(id,size);
    }
    let active=true,observer=null;
    // Real content changes can resize an endpoint during a drag. Resize
    // notifications arrive after layout, without forcing layout on the
    // pointermove hot path. Re-render on pointerup still remeasures all ports.
    if(typeof ResizeObserver==="function"&&watched.size){
      observer=new ResizeObserver(entries=>{
        if(!active)return;
        for(const entry of entries){
          const el=entry.target,id=el.getAttribute("data-node-id");
          if(watched.get(id)!==el)continue;
          const size={w:el.offsetWidth,h:el.offsetHeight};
          if(Number.isFinite(size.w)&&Number.isFinite(size.h))
            sizes.set(id,size);
        }
      });
      try{
        for(const el of watched.values())observer.observe(el);
      }catch(_){
        observer.disconnect();observer=null;
      }
    }
    const edgeCount=graphEdges.length,nodeCount=nodes.length;
    return Object.freeze({
      incidentCount:bindings.length,
      dispose(){active=false;observer?.disconnect();},
      update(liveEdges,liveNodes){
        if(!active||liveEdges!==graphEdges||liveNodes!==nodes||
           graphEdges.length!==edgeCount||nodes.length!==nodeCount)return false;
        const patches=[];
        const port=(node,el,dir)=>{
          if(el.isConnected===false||
             (typeof layer.contains==="function"&&!layer.contains(el)))return null;
          const size=sizes.get(String(node.id));
          if(!size)return null;
          return {x:dir==="in"?node.x:node.x+size.w,
            y:node.y+size.h*0.5};
        };
        for(const b of bindings){
          if(graphEdges[b.edgeIndex]!==b.edge||
             nodes[b.fromIndex]!==b.from||nodes[b.toIndex]!==b.to||
             String(b.edge.id)!==b.id||
             String(b.edge.from)!==b.fromId||
             String(b.edge.to)!==b.toId||
             b.group.isConnected===false||b.hit.isConnected===false||
             b.line.isConnected===false||
             (typeof svg.contains==="function"&&!svg.contains(b.group)))return false;
          const a=port(b.from,b.fromEl,"out");
          const z=port(b.to,b.toEl,"in");
          if(!a||!z)return false;
          const d=pathFor(a.x,a.y,z.x,z.y);
          if(typeof d!=="string"||!d)return false;
          patches.push({hit:b.hit,line:b.line,d});
        }
        // Every binding is validated before any of the SVG attributes change.
        for(const {hit,line,d} of patches){
          if(hit.getAttribute("d")!==d)hit.setAttribute("d",d);
          if(line.getAttribute("d")!==d)line.setAttribute("d",d);
        }
        if(patches.length)edgeMarkupCache.delete(svg);
        return true;
      }
    });
  }
  function clearEdgeMarkup(svg){
    if(!svg)return;
    svg.innerHTML="";
    edgeMarkupCache.delete(svg);
  }

  function captureEditableGraph(graph){
    const source=graph||{},snapshot={};
    for(const [name,value] of Object.entries(source)){
      if(name==="nodes")continue;
      if(name==="runRefs"){snapshot[name]=value;continue;}
      if(name==="meta"&&value&&typeof value==="object"&&!Array.isArray(value)){
        const meta={};
        for(const [k,v] of Object.entries(value))
          meta[k]=k==="runRefs"?v:clone(v);
        snapshot.meta=meta;
      }else snapshot[name]=clone(value);
    }
    snapshot.nodes=(source.nodes||[]).map(node=>{
      const result={};
      for(const [name,value] of Object.entries(node)){
        if(name==="data")continue;
        result[name]=clone(value);
      }
      const data=node.data;
      if(!data||typeof data!=="object") {
        if(own(node,"data"))result.data=data;
        return result;
      }
      if(node.type==="output_display"){
        // The data holds the generated image list, its immutable media IDs,
        // progress and upstream status. It isn't an editable history action.
        result.data=data;
      }else if(node.type==="output_control"||node.type==="loop"){
        result.data={};
        for(const [name,value] of Object.entries(data))
          result.data[name]=RUN_FIELDS.has(name)?value:clone(value);
      }else if(node.type==="article_plan"){
        result.data={};
        for(const [name,value] of Object.entries(data)){
          if(name!=="cards"||!Array.isArray(value)){
            result.data[name]=clone(value);continue;
          }
          result.data.cards=value.map(card=>{
            if(!card||typeof card!=="object")return clone(card);
            const copy={};
            for(const [k,v] of Object.entries(card))
              copy[k]=ARTICLE_CARD_FIELDS.has(k)?v:clone(v);
            return copy;
          });
        }
      }else result.data=clone(data);
      return result;
    });
    return snapshot;
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
  return Object.freeze({reconcile,updateSelection,preserveRuntime,captureEditableGraph,
    createEdgeGeometryIndex,reconcileEdgeMarkup,clearEdgeMarkup,patchMovedEdgePaths,
    createEdgeDragSession,
    // Exposed for controlled performance/DOM regression fixtures.
    rootFlags});
});
