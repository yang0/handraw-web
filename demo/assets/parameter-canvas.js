/* Independent parameter documents and durable generation batches. */
(function (global) {
  "use strict";
  const labels={prompt:"主题",style1:"画风方案",style2:"副画风",layout:"图型",ratio:"比例",refImages:"参考图组",colors:"配色",tones:"色调",moods:"氛围",whitespace:"留白",mode:"创作模式"};
  const ratios=["1:1","3:4","4:3","9:16","16:9","2.35:1","3:2","2:3"];
  const uid=prefix=>prefix+"_"+(global.crypto?.randomUUID?.().replace(/-/g,"") || Date.now().toString(36)+Math.random().toString(36).slice(2));
  const clone=value=>JSON.parse(JSON.stringify(value));
  const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const resourceCode=(value,field)=>typeof value==="object"&&value!==null?String(value[field]||""):field==="style2"?"":String(value||"");
  const runDate=value=>Number.isNaN(new Date(value).getTime())?String(value||"已保存批次"):new Date(value).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});
  const nodeName = node => node.type === "parameter" ? labels[node.parameter] : node.type === "combine" ? "参数组合" : "批量出图";

  function connectionError(graph, from, to) {
    const source = graph.nodes.find(node => node.id === from);
    const target = graph.nodes.find(node => node.id === to);
    if (!source || !target || source === target) return "请连接两个不同节点";
    if (source.type === "output" || target.type === "parameter") return "请从右侧输出连接到左侧输入";
    if (graph.edges.some(edge => edge.from === from && edge.to === to)) return "这两个锚点已经连接";
    if (graph.edges.length >= 400) return "画布最多可添加 400 条连线";
    const pending = [to];
    const visited = new Set();
    while (pending.length) {
      const id = pending.pop();
      if (id === from) return "这条线会形成循环，请选择其他锚点";
      if (visited.has(id)) continue;
      visited.add(id);
      for (const edge of graph.edges) if (edge.from === id) pending.push(edge.to);
    }
    return "";
  }

  function addCanvasNode(graph, type, field, position) {
    if (graph.nodes.length >= 200) return null;
    const node = {
      id: uid("node"), type,
      x: Math.max(16, Math.min(50000, position.x)),
      y: Math.max(16, Math.min(50000, position.y))
    };
    if (type === "parameter") {
      node.parameter = field;
      node.values = [initialCandidate(field)];
    } else {
      node.mode = "cartesian";
      if (type === "output") node.repeat = 1;
    }
    graph.nodes.push(node);
    return node;
  }

  function initialCandidate(field) {
    if (["refImages", "colors", "tones", "moods"].includes(field)) return [];
    if (field === "ratio") return "3:4";
    if (field === "mode") return "graphic-text";
    return "";
  }
  function pickResourceCandidate(store,node,index,field,openPicker) {
    const doc=store.doc,values=node.values,previous=values[index];
    openPicker({field,current:resourceCode(previous,field),onPick:code=>{
      if(store.closed||store.doc!==doc||!doc.graph.nodes.includes(node)||node.values!==values||values[index]!==previous) return;
      code=String(code||"").trim();
      if(node.parameter==="style1") {
        const pair={style1:resourceCode(previous,"style1"),style2:resourceCode(previous,"style2")};
        pair[field]=code;
        values[index]=!pair.style1?"":pair.style2?pair:pair.style1;
      } else values[index]=code;
      store.edit(true);
    }});
  }
  function blank() {
    return {id:uid("canvas"),name:"参数组合画布",writeSeq:0,graph:{format:1,nodes:[
      {id:"theme",type:"parameter",parameter:"prompt",values:[""],x:32,y:32},
      {id:"style",type:"parameter",parameter:"style1",values:["FA-001"],x:32,y:340},
      {id:"combine",type:"combine",mode:"cartesian",x:370,y:135},
      {id:"output",type:"output",mode:"cartesian",repeat:1,x:700,y:135}
    ],edges:[{from:"theme",to:"combine"},{from:"style",to:"combine"},{from:"combine",to:"output"}]}};
  }
  function arrangeNodes(nodes,dimensions) {
    let y=32;
    for(let start=0;start<nodes.length;start+=3) {
      const row=nodes.slice(start,start+3);let x=32,height=0;
      for(const node of row) {
        const box=dimensions.get(node.id)||{},w=Number(box.width)||276,h=Number(box.height)||330;
        node.x=x;node.y=y;x+=w+60;height=Math.max(height,h);
      }
      y+=height+40;
    }
  }
  function simpleFlow(graph) {
    const parameters=graph.nodes.filter(n=>n.type==="parameter"),groups=graph.nodes.filter(n=>n.type==="combine"),outputs=graph.nodes.filter(n=>n.type==="output");
    if(groups.length!==1||outputs.length!==1||new Set(parameters.map(n=>n.parameter)).size!==parameters.length) return null;
    const group=groups[0],output=outputs[0],expected=new Set([...parameters.map(n=>n.id+"\u0000"+group.id),group.id+"\u0000"+output.id]);
    if(graph.edges.length!==expected.size||!graph.edges.every(e=>expected.has(e.from+"\u0000"+e.to))) return null;
    if(new Set(graph.edges.map(e=>e.from+"\u0000"+e.to)).size!==expected.size) return null;
    return {parameters,group,output};
  }
  function combinationSummary(graph) {
    const flow=simpleFlow(graph);
    if(!flow) return {count:null,problem:"此画布使用自由连线，请预览实际组合。",formula:"",flow:null};
    const {parameters,group,output}=flow,counts=parameters.map(n=>n.values.length),repeat=Number(output.repeat??1);
    let problem="";
    if(!parameters.some(n=>n.parameter==="prompt")) problem="先添加主题，描述你要生成的画面。";
    for(const node of parameters) {
      if(!node.values.length) {problem=`请为${labels[node.parameter]}添加至少一个候选。`;break;}
      if(node.parameter==="prompt"&&node.values.some(v=>!String(v).trim())) {problem="先填写每个主题，再预览组合。";break;}
    }
    const longest=Math.max(1,...counts);
    if(group.mode==="zip"&&counts.some(n=>n!==1&&n!==longest)) problem="按顺序搭配时，候选数量需相同；只有一个的参数会用于每一组。";
    if(!Number.isInteger(repeat)||repeat<1||repeat>200) problem="每组张数请填写 1–200 的整数。";
    const groups=group.mode==="zip"?longest:counts.reduce((a,b)=>a*b,1),count=groups*repeat;
    if(!problem&&count>200) problem=`当前搭配为 ${count} 张，单批最多 200 张，请减少候选或每组张数。`;
    const terms=parameters.map(n=>`${n.values.length} 个${labels[n.parameter]}`);
    return {flow,count:problem?null:count,problem,formula:group.mode==="zip"?`按顺序 ${groups} 组 × 每组 ${repeat} 张`:terms.join(" × ")+` × 每组 ${repeat} 张`};
  }
  function addGuidedParameter(store,field) {
    const flow=simpleFlow(store.doc.graph);if(!flow) return null;
    const existing=flow.parameters.find(n=>n.parameter===field);if(existing) return existing;
    const y = Math.max(32, ...store.doc.graph.nodes.map(n => Number(n.y) || 0)) + 600;
    const node = addCanvasNode(store.doc.graph, "parameter", field, { x: 32, y });
    if (node) {
      store.doc.graph.edges.push({ from: node.id, to: flow.group.id });
      store.edit(true);
    }
    return node;
  }
  function selectedQuote(preview,count) {
    const q=preview.quote,free=Math.min(count,q.freeRemaining),total=(count-free)*q.unitPrice;
    return {count,freeUsed:free,paidCount:count-free,total,affordable:total<=q.balance};
  }
  class CanvasStore {
    constructor(options) {
      this.options=options; this.doc=blank(); this.list=[]; this.recent=[]; this.run=null;
      this.listCursor="";this.recentCursor="";
      this.navigation=0;
      this.view="free";
      this.dirty=false; this.error=""; this.closed=false; this.loading=false; this.conflict=false;
      this.preview=null; this.selected=new Set(); this.submission=null; this.onchange=()=>{};
      this.cacheKey="handraw.parameter-canvas:"+options.scope;
      try { const cached=JSON.parse(options.storage?.getItem(this.cacheKey)||"null");
        if(cached?.doc?.graph?.nodes) {this.doc=cached.doc;this.dirty=Boolean(cached.dirty);this.submission=cached.submission||null;this.preferredRunId=cached.runId||null;this.view=cached.view==="guided"?"guided":"free";} } catch(_) {}
    }
    notify(reason="render") { if(!this.closed) this.onchange(reason); }
    persist() { try { this.options.storage?.setItem(this.cacheKey,JSON.stringify({doc:this.doc,dirty:this.dirty,submission:this.submission,runId:this.runId||null,view:this.view})); }
      catch(_) { this.error="本地保存空间不足，请保存到云端或导出画布"; } }
    edit(render=false) {
      this.dirty=true; this.preview=null; this.confirmation=null;this.removal=null;this.selected.clear(); this.error=""; this.persist();
      clearTimeout(this.saveTimer);
      if(!this.conflict) this.saveTimer=setTimeout(()=>{void this.save().catch(error=>this.fail(error));},650);
      this.notify(render?"render":"status");
    }
    fail(error) { this.error=error?.message||String(error); if(error?.code==="canvas_conflict") this.conflict=true; this.notify(); }
    async load() {
      if(!this.options.loggedIn()) { this.notify(); return; }
      const navigation=this.navigation;this.loading=true; this.notify();
      try {
        const result=await this.options.api("/api/studio/canvases");
        if(this.closed) return;
        this.list=result.items||[];
        this.listCursor=result.nextCursor||"";
        if(navigation===this.navigation && !this.dirty && !this.submission) {
          const chosen=this.doc.writeSeq?this.doc:this.list[0];
          if(chosen) await this.open(chosen.id,false);
        }
      } catch(error) {this.fail(error);}
      finally {this.loading=false;this.notify();}
    }
    async loadMoreCanvases() {
      if(!this.listCursor||this.listLoading) return;
      const cursor=this.listCursor;this.listLoading=true;this.notify();
      try {
        const result=await this.options.api("/api/studio/canvases?cursor="+encodeURIComponent(cursor));
        if(this.closed||cursor!==this.listCursor) return;
        const byId=new Map(this.list.map(item=>[item.id,item]));
        for(const item of result.items||[]) if(!byId.has(item.id)) byId.set(item.id,item);
        this.list=[...byId.values()];this.listCursor=result.nextCursor||"";
      } finally {this.listLoading=false;this.notify();}
    }
    async open(id,save=true) {
      const navigation=++this.navigation;
      if(save && !(await this.save())) return;
      if(this.closed||navigation!==this.navigation) return;
      this.runId=null;clearTimeout(this.pollTimer);
      const result=await this.options.api("/api/studio/canvases/"+encodeURIComponent(id));
      if(this.closed||navigation!==this.navigation) return;
      this.doc=result.canvas;this.confirmation=null;this.removal=null;this.dirty=false; this.conflict=false; this.preview=null; this.run=null;this.recent=[];this.recentCursor="";
      this.error=""; this.persist(); this.notify(); await this.loadRecent();
    }
    async create(copy=false) {
      if(this.submission) throw new Error("请先确认上一次提交状态");
      if(!copy && this.dirty && !(await this.save())) return;
      this.navigation++;
      this.doc=copy?{...clone(this.doc),id:uid("canvas"),writeSeq:0,name:this.doc.name+" 副本"}:blank();
      this.runId=null;clearTimeout(this.pollTimer);
      this.preferredRunId=null;this.conflict=false;this.run=null;this.recent=[];this.recentCursor="";this.edit(true);
    }
    async importDocument(document) {
      if(this.submission) throw new Error("请先确认上一次提交状态");
      if(this.dirty && !this.conflict && !(await this.save())) return false;
      this.navigation++;
      this.doc={id:uid("canvas"),name:document.name||"导入的参数画布",writeSeq:0,graph:clone(document.graph)};
      this.preferredRunId=null;this.conflict=false;this.run=null;this.runId=null;this.recent=[];this.recentCursor="";clearTimeout(this.pollTimer);this.edit(true);
      return this.save();
    }
    async save() {
      clearTimeout(this.saveTimer);
      if(this.closed) return false;
      if(!this.options.loggedIn()) {this.persist();this.notify("status");return true;}
      if(this.conflict) return false;
      if(this.savePromise) return this.savePromise;
      const operation=(async()=>{
        while(this.dirty && !this.closed) {
          const sent=clone(this.doc),content=JSON.stringify({name:sent.name,graph:sent.graph});
          const result=await this.options.api("/api/studio/canvases",{method:"POST",body:{id:sent.id,name:sent.name,graph:sent.graph,baseWriteSeq:sent.writeSeq}});
          if(this.closed) return false;
          if(this.doc.id===sent.id) {
            this.doc.writeSeq=result.writeSeq;
            this.dirty=content!==JSON.stringify({name:this.doc.name,graph:this.doc.graph});
            this.persist();
          }
          const entry={id:sent.id,name:sent.name,writeSeq:result.writeSeq};
          this.list=[entry,...this.list.filter(item=>item.id!==sent.id)];this.notify("status");
        }
        return !this.closed;
      })();
      this.savePromise=operation;this.notify("status");
      try {return await operation;}
      catch(error) {this.fail(error);return false;}
      finally {if(this.savePromise===operation) this.savePromise=null;this.notify("status");}
    }
    async expand() {
      if(this.expanding) return;
      if(!this.options.loggedIn()) throw new Error("请先登录，再预览和生成");
      if(this.submission) throw new Error("请先确认上一次提交状态");
      this.expanding=true;this.notify("status");
      try {
        if(!this.doc.writeSeq) this.dirty=true;
        if(!(await this.save())) return;
        const id=this.doc.id,key=JSON.stringify(this.doc.graph);
        const result=await this.options.api(`/api/studio/canvases/${encodeURIComponent(id)}/preview`,{method:"POST",body:{}});
        if(this.closed) return;
        if(id!==this.doc.id||key!==JSON.stringify(this.doc.graph)) throw new Error("参数已变化，请重新预览");
        const selection = this.preview?.planHash === result.planHash ? this.selected : null;
        this.preview=result;
        this.selected=new Set(result.items.map(item=>item.ordinal).filter(ordinal=>!selection || selection.has(ordinal)));
        this.confirmation=null;
        this.submitKey=uid("canvas_run");
        this.notify();
      } finally {this.expanding=false;this.notify("status");}
    }
    async submit() {
      if(!this.submission) {
        if(!this.preview || !this.selected.size) throw new Error("请先预览并选择需要生成的组合");
        const quote=selectedQuote(this.preview,this.selected.size);
        if(!quote.affordable) throw new Error("积分余额不足，请减少生成张数");
        this.submission={canvasId:this.doc.id,body:{requestId:this.submitKey,planHash:this.preview.planHash,
          ordinals:[...this.selected].sort((a,b)=>a-b),maxCredits:quote.total}};
      }
      this.persist();
      this.notify();
      const pending=this.submission;
      try {
        const result=await this.options.api(`/api/studio/canvases/${encodeURIComponent(pending.canvasId)}/runs`,{method:"POST",body:pending.body});
        if(this.closed) return;
        this.submission=null;this.persist();this.preview=null;this.error="";await this.watch(result.runId);await this.loadRecent(false);
      } catch(error) { if(error.status) this.submission=null;this.persist();this.fail(error);throw error; }
    }
    async loadRecent(open=true) {
      if(!this.doc.writeSeq||!this.options.loggedIn()) return;
      const navigation=this.navigation,id=this.doc.id,result=await this.options.api(`/api/studio/canvases/${encodeURIComponent(id)}/runs`);
      if(this.closed||navigation!==this.navigation||id!==this.doc.id) return;
      this.recent=result.items||[];this.recentCursor=result.nextCursor||"";this.notify("panel");
      const preferred=this.preferredRunId;this.preferredRunId=null;
      if(open && (preferred||this.recent[0])) await this.watch(preferred||this.recent[0].id);
    }
    async loadMoreRuns() {
      if(!this.recentCursor||this.recentLoading) return;
      const id=this.doc.id,cursor=this.recentCursor;this.recentLoading=true;this.notify("panel");
      try {
        const result=await this.options.api(`/api/studio/canvases/${encodeURIComponent(id)}/runs?cursor=${encodeURIComponent(cursor)}`);
        if(this.closed||id!==this.doc.id||cursor!==this.recentCursor) return;
        const byId=new Map(this.recent.map(item=>[item.id,item]));
        for(const item of result.items||[]) if(!byId.has(item.id)) byId.set(item.id,item);
        this.recent=[...byId.values()];this.recentCursor=result.nextCursor||"";
      } finally {this.recentLoading=false;this.notify("panel");}
    }
    async openRun(id) {
      let navigation=++this.navigation;
      if(this.dirty && !(await this.save())) return;
      if(this.closed||navigation!==this.navigation) return;
      const result=await this.options.api("/api/studio/canvas-runs/"+encodeURIComponent(id));
      if(this.closed||navigation!==this.navigation) return;
      if(result.run.canvasId!==this.doc.id) {
        navigation++;
        try {await this.open(result.run.canvasId,false);}
        catch(error) {
          if(error.status!==404) throw error;
          this.error="来源画布已删除；此处仍可查看批次结果和执行状态";
        }
      }
      if(this.closed||navigation!==this.navigation) return;
      await this.watch(id);
    }
    async watch(id) {
      if(this.runId!==id) {this.retryPayload=null;this.run=null;}
      this.runId=id;
      this.persist();
      this.notify("panel");
      await this.refreshRun();
    }
    async refreshRun() {
      clearTimeout(this.pollTimer);
      const id=this.runId;if(!id||this.closed) return;
      try {
        const result=await this.options.api("/api/studio/canvas-runs/"+encodeURIComponent(id));
        if(this.closed||id!==this.runId) return;
        this.run=result.run;
        if(this.run.canvasId===this.doc.id && !this.recent.some(item=>item.id===id))
          this.recent.push({id,count:this.run.count,createdAt:this.run.createdAt||"已保存批次"});
        this.notify("panel");
      } catch(error) {this.fail(error);}
      if(!this.closed && id===this.runId && (!this.run||["running","pending"].includes(this.run.status)))
        this.pollTimer=setTimeout(()=>{void this.refreshRun();},2000);
    }
    async stopPending() {
      const run=this.run;if(!run) return;
      const positions=run.items.filter(item=>item.status==="pending").map(item=>item.ordinal);
      if(positions.length) await this.options.api(`/api/studio/batches/${encodeURIComponent(run.batchId)}/cancel-pending`,{method:"POST",body:{positions}});
      await this.refreshRun();
    }
    async retry() {
      const run=this.run;if(!run) return;
      if(!this.retryPayload) this.retryPayload={requestId:uid("canvas_retry"),unitPrice:run.retryQuote.unitPrice,
        maxCredits:Math.max(run.maxCredits,run.spentCredits+run.retryQuote.total)};
      await this.options.api(`/api/studio/canvas-runs/${encodeURIComponent(run.id)}/retry`,{method:"POST",body:this.retryPayload});
      this.retryPayload=null;await this.refreshRun();
    }
    close() {this.closed=true;clearTimeout(this.saveTimer);clearTimeout(this.pollTimer);this.persist();}
  }
  let current=null,root=null,options=null;
  let selectedPort = null;
  let nodeMenu = null;
  let activePanel = null;
  let outputPanelId = null;
  let panelCanvasId = null;
  let spaceHeld = false;
  let cancelPointer = null;
  let suppressPortClick = false;
  const busy=action=>Promise.resolve().then(action).catch(error=>current?.fail(error));
  const guided=()=>current?.view==="guided"&&Boolean(simpleFlow(current.doc.graph));
  function updateSummary() {
    for(const card of root?.querySelectorAll('[data-card]')||[]) {
      const node=current.doc.graph.nodes.find(n=>n.id===card.dataset.card),count=card.querySelector('.pc-node-count');
      if(count&&node?.values) count.textContent=`${node.values.length} 个候选`;
    }
    const summary=root?.querySelector("[data-live-summary]");
    if(summary) {
      const info=combinationSummary(current.doc.graph);
      summary.innerHTML=info.problem?`<p class="pc-next-action">${esc(info.problem)}</p>`:`<div class="pc-total"><strong>${info.count}</strong><span>张图片</span></div><p class="pc-formula">${esc(info.formula)}</p>`;
    }
    for(const button of root?.querySelectorAll('[data-action="preview"]')||[]) {
      const info=combinationSummary(current.doc.graph);
      button.disabled=Boolean(current.expanding||current.loading||current.submitting||(!current.submission&&info.flow&&info.problem));
      button.textContent=current.submission?"确认提交":current.expanding?"核对费用中…":"预览出图";
    }
  }
  function status() {
    const el=root?.querySelector("[data-pc-status]");if(!el||!current) return;
    el.textContent=current.conflict?"保存冲突，本地草稿已保留":!options.loggedIn()?"草稿保存在当前浏览器":current.savePromise?"正在保存…":current.dirty?"有未保存改动":"已保存";
    const select=root.querySelector('[data-action="choose-canvas"]');
    if(select) select.innerHTML='<option value="">已保存的画布</option>'+current.list.map(item=>`<option value="${esc(item.id)}" ${item.id===current.doc.id?"selected":""}>${esc(item.name)}</option>`).join("");
    updateSummary();renderPanels();
  }
  function parameterValue(node,value,index) {
    const id=esc(node.id),field=node.parameter,base=`data-node="${id}" data-value="${index}"`;
    if(field==="refImages") return `<button type="button" ${base} data-action="refs">选择一组参考图（${value.length}/6）</button><div class="pc-references">${value.map(url=>`<img src="${esc(url)}" alt="已选参考图" loading="lazy">`).join("")}</div>`;
    if(field==="prompt") return `<textarea aria-label="主题候选 ${index+1}" ${base}>${esc(value)}</textarea>`;
    if(field==="ratio") return `<select aria-label="比例候选 ${index+1}" ${base}>${ratios.map(r=>`<option ${r===value?"selected":""}>${r}</option>`).join("")}</select>`;
    if(field==="mode") return `<select aria-label="创作模式候选 ${index+1}" ${base}><option value="graphic-text" ${value!=="image-only"?"selected":""}>图文</option><option value="image-only" ${value==="image-only"?"selected":""}>纯图</option></select>`;
    if(field==="style1") return resourceValue(node,value,index,"style1")+resourceValue(node,value,index,"style2");
    if(field==="layout") return resourceValue(node,value,index,"layout");
    return `<input aria-label="${labels[field]||field}候选 ${index+1}" ${base} ${field==="layout"?'list="pc-layout-codes"':''} placeholder="${["colors","tones","moods"].includes(field)?"同一方案中的值用逗号分隔":"填写参数值"}" value="${esc(Array.isArray(value)?value.join("，"):value)}">`;
  }
  function resourceValue(node,value,index,field) {
    const code=resourceCode(value,field),kind=field==="layout"?"layout":"style";
    const resource=(options.resources?.(kind)||[]).find(item=>(item.id||item.code)===code);
    const label=field==="style1"?"主画风":field==="style2"?"融合副画风":"图型";
    const name=resource?.name_zh||resource?.name||resource?.title||(code?"资源信息暂不可用":field==="style2"?"可选，搭配双画风":"点击图片选择");
    const image=resource?.image||"",base=`data-node="${esc(node.id)}" data-value="${index}" data-field="${field}"`;
    const disabled=field==="style2"&&!resourceCode(value,"style1");
    return `<div class="pc-resource-control"><button type="button" class="pc-resource-picker ${code?"is-selected":""}" data-action="resource" ${base} aria-label="选择${label}候选 ${index+1}${code?`：${esc(code)} ${esc(name)}`:""}" ${disabled?"disabled":""}>
      <span class="pc-resource-thumb">${image?`<img src="${esc(image)}" alt="${esc(code)} ${esc(name)}" loading="lazy">`:'<span aria-hidden="true">＋</span>'}</span>
      <span class="pc-resource-info"><small>${label}${code?` · ${esc(code)}`:""}</small><strong>${esc(name)}</strong><span>${disabled?"先选择主画风":code?"点击更换":"按编号、名称或图片挑选"}</span></span></button>
      ${code?`<div class="pc-resource-actions">${image?`<button type="button" data-action="zoom-resource" ${base} aria-label="放大${label}候选 ${index+1}">放大</button>`:""}<button type="button" data-action="clear-resource" ${base} aria-label="清空${label}候选 ${index+1}">清空</button></div>`:""}</div>`;
  }
  function nodeHtml(node,index,isGuided=false) {
    const graph = current.doc.graph;
    const incoming = graph.edges.filter(edge => edge.to === node.id);
    const name = nodeName(node);
    const addLabel=node.parameter==="prompt"?"主题":node.parameter==="style1"?"画风方案":labels[node.parameter]+"候选";
    const ports = isGuided ? "" : [
      node.type !== "parameter" ? portButton(node, "in", incoming.length > 0) : "",
      node.type !== "output" ? portButton(node, "out", graph.edges.some(edge => edge.from === node.id)) : ""
    ].join("");
    return `<section class="pc-node ${isGuided?"pc-parameter":""}" data-card="${esc(node.id)}" ${isGuided?"":`style="left:${Number(node.x??32)}px;top:${Number(node.y??32)}px"`}>
      ${ports}
      <header ${isGuided?"":`data-drag="${esc(node.id)}"`}><div><strong>${esc(name)}${isGuided?"":` ${index+1}`}</strong>${isGuided?`<span class="pc-node-count">${node.values.length} 个候选</span>`:""}</div><button type="button" data-action="remove-node" data-node="${esc(node.id)}" aria-label="移除${esc(name)}">×</button></header>
      <div class="pc-node-body">${node.type==="parameter"?
        `<p>${node.parameter==="prompt"?"一条主题描述一幅画面。想换内容，就添加主题。":node.parameter==="style1"?"每个方案可选一种画风，也可搭配主副两种画风。":"只选一个时，每组都使用它；添加多个可参与搭配。"}</p>${node.values.map((value,i)=>`<div class="pc-candidate"><div class="pc-candidate-heading"><span>${esc(addLabel)} ${i+1}</span><button type="button" data-action="remove-value" data-node="${esc(node.id)}" data-value="${i}" aria-label="移除${esc(addLabel)} ${i+1}">移除</button></div>${parameterValue(node,value,i)}</div>`).join("")}<button type="button" class="pc-add-candidate" data-action="add-value" data-node="${esc(node.id)}">＋ 添加${esc(addLabel)}</button>`:
        `<p>${node.type === "output" ? "接收左边的参数或组合，设置每组出几张。" : "把主题、画风等合成一组组出图方案。例如 2 个主题 × 3 种画风 = 6 组。"}</p>
        ${node.type === "combine" || incoming.length > 1 ? `<label>怎样组合<select data-node="${esc(node.id)}" data-property="mode"><option value="cartesian" ${node.mode!=="zip"?"selected":""}>全部互相搭配</option><option value="zip" ${node.mode==="zip"?"selected":""}>按顺序一一搭配</option></select></label>` : ""}
        ${node.type === "output" ? `<label>每组生成张数<input type="number" min="1" max="200" data-node="${esc(node.id)}" data-property="repeat" value="${node.repeat??1}"></label>` : ""}
        <div class="pc-links">${incoming.map(edge => {
          const source = graph.nodes.find(item => item.id === edge.from);
          const label = source ? `${nodeName(source)} ${graph.nodes.indexOf(source) + 1}` : "参数";
          return `<span>${esc(label)}<button type="button" data-action="disconnect" data-node="${esc(node.id)}" data-from="${esc(edge.from)}" aria-label="断开${esc(label)}">×</button></span>`;
        }).join("") || '<small>从其他节点的右侧圆点连到这里的左侧圆点</small>'}</div>`}</div>
      ${node.type === "output" ? '<div class="pc-output-results" data-output-results></div>' : ""}</section>`;
  }

  function portButton(node, direction, connected) {
    const name = direction === "in" ? "输入" : "输出";
    return `<button type="button" class="pc-port pc-port-${direction}${connected ? " is-linked" : ""}" data-action="port" data-port="${direction}" data-node="${esc(node.id)}" aria-label="${esc(nodeName(node))}的${name}锚点" aria-pressed="false" title="${name}锚点，拖动或点击连线"><span aria-hidden="true"></span></button>`;
  }

  function curve(from, to) {
    const bend = Math.max(40, Math.abs(to.x - from.x) * .45);
    return `M${from.x},${from.y} C${from.x + bend},${from.y} ${to.x - bend},${to.y} ${to.x},${to.y}`;
  }

  function portPoint(port, world) {
    const bounds = port.getBoundingClientRect();
    const origin = world.getBoundingClientRect();
    return { x: bounds.left + bounds.width / 2 - origin.left, y: bounds.top + bounds.height / 2 - origin.top };
  }

  function drawEdges() {
    const svg = root.querySelector(".pc-edges");
    if (!svg) return;
    const points = new Map([...root.querySelectorAll("[data-port]")].map(port => [
      `${port.dataset.port}:${port.dataset.node}`, portPoint(port, svg.parentElement)
    ]));
    svg.innerHTML = current.doc.graph.edges.map(edge => {
      const from = points.get(`out:${edge.from}`);
      const to = points.get(`in:${edge.to}`);
      return from && to ? `<path d="${curve(from, to)}"/>` : "";
    }).join("") + '<path class="pc-wire-preview" d=""/>';
  }

  function closeNodeMenu() {
    nodeMenu?.controller.abort();
    nodeMenu?.element.remove();
    nodeMenu = null;
  }

  function worldPosition(x, y) {
    const bounds = root.querySelector(".pc-world").getBoundingClientRect();
    return { x: Math.round(x - bounds.left), y: Math.round(y - bounds.top) };
  }

  function openNodeMenu(x, y, port = null, position = worldPosition(x, y)) {
    closeNodeMenu();
    clearWire();
    const choices = [];
    if (!port || port.direction === "in") {
      for (const [field, name] of Object.entries(labels)) {
        if (field !== "style2") choices.push({ type: "parameter", field, name, group: "参数" });
      }
    }
    choices.push({ type: "combine", name: "参数组合", group: "生成流程", detail: "把主题、画风等搭配成多组方案" });
    if (!port || port.direction === "out") {
      choices.push({ type: "output", name: "批量出图", group: "生成流程", detail: "接收参数，设置每组出几张" });
    }
    const element = document.createElement("div");
    element.className = "pc-node-menu";
    element.setAttribute("role", "dialog");
    element.setAttribute("aria-label", "添加节点");
    element.innerHTML = `<div class="pc-node-menu-title"><strong>添加节点</strong><button type="button" data-action="close-node-menu" aria-label="关闭添加节点">×</button></div>
      <input type="search" aria-label="搜索节点" placeholder="搜索主题、画风、参数组合…" autocomplete="off">
      <div class="pc-node-menu-list"></div>`;
    const controller = new AbortController();
    nodeMenu = { element, position, port, controller };
    root.append(element);
    const input = element.querySelector("input");
    const list = element.querySelector(".pc-node-menu-list");
    const renderChoices = () => {
      const query = input.value.trim().toLowerCase();
      const filtered = choices.filter(item => `${item.name} ${item.detail || ""} ${item.field || ""}`.toLowerCase().includes(query));
      list.innerHTML = ["参数", "生成流程"].map(group => {
        const items = filtered.filter(item => item.group === group);
        if (!items.length) return "";
        return `<p>${group}</p>${items.map(item => `<button type="button" data-action="create-node" data-type="${item.type}" data-field="${item.field || ""}"><strong>${item.name}</strong>${item.detail ? `<small>${item.detail}</small>` : ""}</button>`).join("")}`;
      }).join("") || '<p>没有匹配的节点</p>';
    };
    input.oninput = renderChoices;
    renderChoices();
    const bounds = element.getBoundingClientRect();
    element.style.left = `${Math.max(8, Math.min(x, window.innerWidth - bounds.width - 8))}px`;
    element.style.top = `${Math.max(8, Math.min(y, window.innerHeight - bounds.height - 8))}px`;
    input.focus({ preventScroll: true });
    document.addEventListener("pointerdown", event => {
      if (!element.contains(event.target) && !event.target.closest('[data-action="add-node-menu"]')) closeNodeMenu();
    }, { capture: true, signal: controller.signal });
    element.onkeydown = event => {
      if (event.key === "Escape") {
        event.stopPropagation();
        closeNodeMenu();
        root.querySelector('[data-action="add-node-menu"]')?.focus();
        return;
      }
      const buttons = [...list.querySelectorAll("button")];
      if (event.key === "Enter" && event.target === input) {
        event.preventDefault();
        buttons[0]?.click();
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const index = buttons.indexOf(event.target);
        const next = event.key === "ArrowDown" ? index + 1 : index < 0 ? buttons.length - 1 : index - 1;
        (buttons[next] || input).focus();
      }
    };
  }

  function wireHint(message = "") {
    const hint = root?.querySelector("[data-wire-hint]");
    if (hint) hint.textContent = message || "右键或双击添加节点 · 拖动圆点连线 · 空格或中键拖动画布";
  }

  function clearWire() {
    selectedPort = null;
    root?.querySelectorAll("[data-port]").forEach(port => {
      port.classList.remove("is-available", "is-wire-target");
      port.setAttribute("aria-pressed", "false");
    });
    root?.querySelector(".pc-wire-preview")?.setAttribute("d", "");
    wireHint();
  }

  function portRef(port) {
    return { node: port.dataset.node, direction: port.dataset.port };
  }

  function portConnection(start, end) {
    if (start.direction === end.direction) return null;
    return start.direction === "out" ? { from: start.node, to: end.node } : { from: end.node, to: start.node };
  }

  function selectPort(port) {
    clearWire();
    selectedPort = portRef(port);
    port.setAttribute("aria-pressed", "true");
    root.querySelectorAll("[data-port]").forEach(candidate => {
      const edge = portConnection(selectedPort, portRef(candidate));
      if (edge && !connectionError(current.doc.graph, edge.from, edge.to)) candidate.classList.add("is-available");
    });
    wireHint(selectedPort.direction === "out" ? "选择要接收参数的左侧圆点。" : "选择提供参数的右侧圆点。");
  }

  function connectPorts(start, end) {
    const edge = portConnection(start, end);
    const error = edge ? connectionError(current.doc.graph, edge.from, edge.to) : "请连接一个右侧圆点和一个左侧圆点";
    clearWire();
    if (error) {
      wireHint(error);
      return;
    }
    current.doc.graph.edges.push(edge);
    current.edit(true);
  }

  function beginWire(event, port) {
    const start = portRef(port);
    const world = root.querySelector(".pc-world");
    const initialX = event.clientX;
    const initialY = event.clientY;
    const pointerId = event.pointerId;
    let moved = false;
    port.setPointerCapture(pointerId);
    const controller = new AbortController();
    const listener = { signal: controller.signal };
    cancelPointer = () => {
      controller.abort();
      if (port.hasPointerCapture(pointerId)) port.releasePointerCapture(pointerId);
      cancelPointer = null;
      if (moved) clearWire();
    };
    port.addEventListener("pointermove", next => {
      if (next.pointerId !== pointerId) return;
      if (!moved && Math.hypot(next.clientX - initialX, next.clientY - initialY) < 5) return;
      if (!moved) {
        moved = true;
        selectPort(port);
      }
      const hit = document.elementFromPoint(next.clientX, next.clientY)?.closest("[data-port]");
      const candidate = hit?.classList.contains("is-available") ? hit : null;
      root.querySelector(".is-wire-target")?.classList.remove("is-wire-target");
      candidate?.classList.add("is-wire-target");
      const a = portPoint(port, world);
      const b = candidate ? portPoint(candidate, world) : worldPosition(next.clientX, next.clientY);
      root.querySelector(".pc-wire-preview")?.setAttribute("d", start.direction === "out" ? curve(a, b) : curve(b, a));
    }, listener);
    port.addEventListener("pointerup", next => {
      if (next.pointerId !== pointerId) return;
      const hit = document.elementFromPoint(next.clientX, next.clientY);
      const target = hit?.closest("[data-port]");
      cancelPointer?.();
      if (!moved) return;
      suppressPortClick = true;
      if (target && target !== port && root.contains(target)) connectPorts(start, portRef(target));
      else if (hit?.closest(".pc-world") === world && !hit.closest(".pc-node")) openNodeMenu(next.clientX, next.clientY, start);
      else wireHint("把连线放到另一侧的圆点上");
    }, listener);
    port.addEventListener("pointercancel", () => cancelPointer?.(), listener);
    port.addEventListener("lostpointercapture", () => cancelPointer?.(), listener);
  }
  function outputItems(run, outputIds, canvasId) {
    const byNode = new Map(outputIds.map(id => [id, []]));
    const orphaned = [];
    for (const item of run?.items || []) {
      const id = item.outputNodeId || (outputIds.length === 1 ? outputIds[0] : null);
      const group = run.canvasId === canvasId ? byNode.get(id) : null;
      (group || orphaned).push(item);
    }
    return {byNode, orphaned};
  }

  const taskLabels = {pending:"等待提交",generating:"生成中",success:"已完成",failed:"未成功",cancelled:"已停止"};
  const completedCount = items => items.filter(item => item.status === "success").length;
  const resultCount = items => items.reduce((sum, item) => sum + item.images.length, 0);

  function outputGallery(items) {
    return `<div class="pc-gallery">${items.map(item => {
      const prompt = String(item.spec?.prompt || "");
      return `<article><strong>${item.ordinal + 1}. ${esc(prompt.slice(0, 80))}</strong><span>${taskLabels[item.status] || "等待确认"}</span>
      ${item.images.map(url => `<button type="button" class="pc-result-image" data-action="open-result-image" data-url="${esc(url)}" data-title="${esc(prompt.slice(0, 80))}" aria-label="查看第 ${item.ordinal + 1} 项生成图"><img src="${esc(url)}" alt="${esc(prompt.slice(0, 80))}" loading="lazy"></button>`).join("")}</article>`;
    }).join("")}</div>`;
  }

  function batchControls(run) {
    return `<div class="pc-run-actions"><button type="button" data-action="refresh">刷新</button>
      ${run.items.some(item => item.status === "pending") ? '<button type="button" data-action="stop">停止未提交任务</button>' : ""}
      ${run.items.some(item => ["failed","cancelled"].includes(item.status)) ? `<button type="button" data-action="retry">重试未成功项（预计 ${run.retryQuote.total} 积分）</button>` : ""}</div>`;
  }

  function previewHtml() {
    if (current.submitting) return '<p role="status">正在提交批次…</p>';
    if (current.submission) return '<p role="status">上一批提交状态待确认。</p><button type="button" class="pc-primary" data-action="submit">确认提交状态</button>';
    const preview = current.preview;
    if (!preview) return "";
    const q = selectedQuote(preview, current.selected.size);
    return `<p>已选 ${q.count} / ${preview.count} 张 · 免费 ${q.freeUsed} 张 · 预计 ${q.total} 积分</p>
      ${current.confirmation === "submit"
        ? `<div class="pc-confirm" role="group" aria-label="确认本次生成"><strong>确认生成 ${q.count} 张？</strong><p>积分上限 ${q.total}。关闭页面后仍会继续生成。</p><div><button type="button" data-action="cancel-confirm">返回检查</button><button type="button" class="pc-primary" data-action="confirm-submit">确认并开始生成</button></div></div>`
        : `<button type="button" class="pc-primary" data-action="submit" ${!q.count || !q.affordable ? "disabled" : ""}>生成选中的 ${q.count} 张</button>`}
      <button type="button" data-action="recheck-preview" ${current.expanding ? "disabled" : ""}>重新核对费用</button>
      ${!q.affordable ? '<p class="pc-next-action">积分不足，请减少勾选数量。</p>' : ""}
      <div class="pc-plan-list">${preview.items.map(item => `<label><input type="checkbox" data-select="${item.ordinal}" ${current.selected.has(item.ordinal) ? "checked" : ""}><span><b>${item.ordinal + 1}.</b> ${esc(String(item.spec?.prompt || "").slice(0,100))}<small>${esc([item.spec?.style1,item.spec?.style2,item.spec?.layout,item.spec?.ratio].filter(Boolean).join(" · "))}</small></span></label>`).join("")}</div>`;
  }

  function historyHtml(run, orphaned) {
    const entries = current.recent.map(item => `<button type="button" class="pc-history-entry" data-action="choose-run" data-run="${esc(item.id)}" aria-pressed="${item.id === current.runId}"><span>${esc(runDate(item.createdAt))}</span><small>${item.count} 张</small></button>`).join("");
    return `${entries || '<p class="pc-muted">此画布暂无出图记录。</p>'}
      ${current.recentCursor ? `<button type="button" data-action="more-runs" ${current.recentLoading ? "disabled" : ""}>${current.recentLoading ? "正在载入…" : "加载更早的批次"}</button>` : ""}
      ${current.runId && !run ? '<p role="status">正在载入批次…</p>' : ""}
      ${run ? `<p>完成 ${completedCount(run.items)} / ${run.count} 张 · 已用 ${run.spentCredits} 积分</p>${batchControls(run)}
        ${orphaned.length ? '<button type="button" data-action="show-detached-output">查看未关联到节点的结果</button>' : ""}
        ${run.items.length > orphaned.length ? '<button type="button" data-action="focus-run-output">定位出图节点</button>' : ""}` : ""}`;
  }

  function updateMarkup(element, markup) {
    if (element.dataset.rendered === markup) return;
    const scrollTop = element.scrollTop;
    const active = document.activeElement;
    const ordinal = element.contains(active) ? active.dataset.select : null;
    element.innerHTML = markup;
    element.dataset.rendered = markup;
    element.scrollTop = scrollTop;
    if (ordinal != null) element.querySelector(`[data-select="${Number(ordinal)}"]`)?.focus({preventScroll:true});
  }

  function renderPanels() {
    const drawer = root?.querySelector(".pc-drawer");
    if (!drawer || !current) return;
    const run = current.run;
    const ids = current.doc.graph.nodes.filter(node => node.type === "output").map(node => node.id);
    const {byNode, orphaned} = outputItems(run, ids, current.doc.id);
    for (const slot of root.querySelectorAll("[data-output-results]")) {
      const id = slot.dataset.outputNode || slot.closest("[data-card]").dataset.card;
      const items = byNode.get(id) || [];
      const thumb = items.find(item => item.images.length)?.images[0];
      updateMarkup(slot, items.length ? `<button type="button" data-action="open-output" data-node="${esc(id)}" aria-expanded="${activePanel === "output" && outputPanelId === id}">
        ${thumb ? `<img src="${esc(thumb)}" alt="" loading="lazy">` : ""}
        <span><strong>出图结果</strong><small>完成 ${completedCount(items)} / ${items.length} 项 · ${resultCount(items)} 张图</small></span><span aria-hidden="true">›</span></button>` : "");
    }
    const history = root.querySelector('[data-action="toggle-history"]');
    history.setAttribute("aria-expanded", String(activePanel === "history"));
    const pending = run?.items.filter(item => ["pending","generating"].includes(item.status)).length;
    history.textContent = pending ? `出图历史 · ${pending}` : "出图历史";
    history.setAttribute("aria-label", pending ? `出图历史，${pending} 项进行中` : "出图历史");
    const items = outputPanelId ? byNode.get(outputPanelId) || [] : orphaned;
    const title = activePanel === "history" ? "出图历史" : activePanel === "output"
      ? (outputPanelId ? "节点出图结果" : "未关联的历史结果") : "预览与费用";
    const markup = activePanel === "history" ? historyHtml(run, orphaned)
      : activePanel === "output" && run && items.length ? `<p>完成 ${completedCount(items)} / ${items.length} 项 · ${resultCount(items)} 张图</p>${outputGallery(items)}`
      : activePanel === "preview" ? previewHtml() : "";
    drawer.hidden = !markup;
    drawer.setAttribute("aria-label", title);
    drawer.querySelector("h2").textContent = title;
    updateMarkup(drawer.querySelector(".pc-drawer-body"), markup);
  }

  function render() {
    if(!root||!current||current.closed) return;
    closeNodeMenu();
    cancelPointer?.();
    selectedPort = null;
    const doc=current.doc,isGuided=guided(),flow=simpleFlow(doc.graph);
    const oldScroll=root.querySelector('.pc-guided-body')?.scrollTop||0;
    const oldCanvas=root.querySelector(".pc-scroll");
    if (panelCanvasId !== doc.id) {
      panelCanvasId = doc.id;
      activePanel = current.submission ? "preview" : null;
      outputPanelId = null;
    }
    root.innerHTML = `<div class="pc-header">
      <div class="pc-document"><input class="pc-name" aria-label="画布名称" data-name value="${esc(doc.name)}"><span data-pc-status role="status"></span></div>
      <div class="pc-toolbar" aria-label="画布工具">
        ${isGuided ? "" : '<button type="button" data-action="add-node-menu" aria-haspopup="dialog">＋ 添加节点</button>'}
        <button type="button" data-action="toggle-history" aria-expanded="false" aria-controls="pc-drawer">出图历史</button>
        <button type="button" class="pc-primary" data-action="preview">预览出图</button>
        <details class="pc-document-menu"><summary>更多</summary><div>
          <label>打开画布<select aria-label="打开已保存画布" data-action="choose-canvas" ${current.submission?"disabled":""}></select></label>
          ${current.listCursor ? `<button type="button" data-action="more-canvases" ${current.listLoading?"disabled":""}>${current.listLoading?"正在载入…":"加载更多画布"}</button>` : ""}
          <button type="button" data-action="new" ${current.submission?"disabled":""}>新建画布</button>
          <button type="button" data-action="save">保存画布</button>
          <button type="button" data-action="copy" ${current.submission?"disabled":""}>另存副本</button>
          <button type="button" data-action="export">导出画布</button>
          ${isGuided ? '<button type="button" data-action="free-view">切换到节点画布</button>' : `<button type="button" data-action="arrange">整理节点位置</button>
            <button type="button" data-action="guided-view" ${!flow?"disabled":""}>切换到搭配视图</button>`}
        </div></details>
      </div></div>
      ${current.error?`<div class="pc-error" role="alert">${esc(current.error)}${current.conflict?'。可另存副本保留本地改动。':""}</div>`:""}
      ${isGuided?'<nav class="pc-step-nav" aria-label="跳转画布步骤"><button type="button" data-action="step" data-step="parameters">1 准备参数</button><button type="button" data-action="step" data-step="matching">2 搭配方式</button><button type="button" data-action="step" data-step="checkout">3 预览出图</button></nav>':""}
      ${current.removal?'<div class="pc-undo" role="status">已移除，尚可撤销 <button type="button" data-action="undo-remove">撤销移除</button></div>':""}
      <div class="pc-workspace">
        ${isGuided ? guidedHtml(flow) : `<div class="pc-scroll" tabindex="0" aria-label="参数节点画布" aria-describedby="pc-wire-hint"><div class="pc-world" style="width:${Math.max(1050,...doc.graph.nodes.map(n=>(Number(n.x)||0)+320))}px;height:${Math.max(760,...doc.graph.nodes.map(n=>(Number(n.y)||0)+500))}px"><svg class="pc-edges" aria-hidden="true"></svg>${doc.graph.nodes.map((node,index)=>nodeHtml(node,index)).join("")}</div></div>
          <p id="pc-wire-hint" data-wire-hint aria-live="polite"></p>`}
        <aside id="pc-drawer" class="pc-drawer" hidden><div class="pc-drawer-header"><h2></h2><button type="button" data-action="close-drawer" aria-label="收起面板">×</button></div><div class="pc-drawer-body"></div></aside>
      </div>`;

    const canvas=root.querySelector(".pc-scroll");
    if(canvas && oldCanvas) {canvas.scrollLeft=oldCanvas.scrollLeft;canvas.scrollTop=oldCanvas.scrollTop;}
    status();wireHint();drawEdges();
    const body=root.querySelector('.pc-guided-body');if(body) body.scrollTop=oldScroll;
  }
  function guidedHtml(flow) {
    return `<div class="pc-guided-body"><main class="pc-parameters-area" aria-label="准备参数"><div class="pc-step-title"><span>1</span><div><h2>准备参数</h2><p>一个候选固定使用，多个候选参与搭配。</p></div></div>
      <div class="pc-parameter-tools" aria-label="添加参数">${["prompt","style1","layout","ratio","refImages"].map(field=>`<button type="button" data-action="guided-add" data-field="${field}">${flow.parameters.some(n=>n.parameter===field)?"编辑":"＋"} ${labels[field]}</button>`).join("")}<details><summary>更多参数</summary><div>${Object.entries(labels).filter(([key])=>!["prompt","style1","style2","layout","ratio","refImages"].includes(key)).map(([key,label])=>`<button type="button" data-action="guided-add" data-field="${key}">${label}</button>`).join("")}</div></details></div>
      <div class="pc-parameter-grid">${flow.parameters.map((node,index)=>nodeHtml(node,index,true)).join("")}</div></main>
      <aside class="pc-guide-sidebar"><section class="pc-matching" aria-label="选择搭配方式"><div class="pc-step-title"><span>2</span><div><h2>选择搭配方式</h2><p>这些参数怎么一起用？</p></div></div>
        <div class="pc-match-options">${[["cartesian","全部互相搭配","2 个主题 × 3 种画风 → 6 组","每个主题都试一遍每种画风。"],["zip","按顺序一一搭配","主题 1 + 画风 1，主题 2 + 画风 2","只有一个候选的参数，每组都会使用。"]].map(([mode,title,example,description])=>`<button type="button" data-action="matching" data-mode="${mode}" aria-pressed="${(flow.group.mode||"cartesian")===mode}"><strong>${title}</strong><span>${example}</span><small>${description}</small></button>`).join("")}</div>
        <label class="pc-repeat-label">每组生成<input type="number" min="1" max="200" aria-label="每组生成张数" data-node="${esc(flow.output.id)}" data-property="repeat" value="${flow.output.repeat??1}">张</label>
      </section><section class="pc-checkout" aria-label="预览与出图"><div class="pc-step-title"><span>3</span><div><h2>预览与出图</h2><p>先核对张数与费用，再开始。</p></div></div><div data-live-summary aria-live="polite"></div><button type="button" class="pc-primary pc-preview-button" data-action="preview">预览出图</button><div class="pc-output-results" data-output-results data-output-node="${esc(flow.output.id)}"></div></section></aside></div>`;
  }
  function valueChanged(target) {
    const node=current.doc.graph.nodes.find(n=>n.id===target.dataset.node);
    if(target.hasAttribute("data-name")) {current.doc.name=target.value;current.edit();return;}
    if(!node) return;
    if(target.dataset.property) node[target.dataset.property]=target.dataset.property==="repeat"?Number(target.value):target.value;
    else if(target.dataset.value!=null) {
      const index=Number(target.dataset.value),field=node.parameter;
      if(field==="style1") { const old=node.values[index],v={style1:typeof old==="object"?old.style1:old,style2:old?.style2||""};v[target.dataset.fusion]=target.value;node.values[index]=v.style2?v:v.style1; }
      else node.values[index]=["colors","tones","moods"].includes(field)?target.value.split(/[,，\n]/).map(v=>v.trim()).filter(Boolean):target.value;
    }
    current.edit();
  }
  function focusParameter(node,last=false) {
    const card=Array.from(root.querySelectorAll('[data-card]')).find(el=>el.dataset.card===node?.id);
    if(!card) return;
    card.scrollIntoView({block:"nearest",inline:"nearest"});
    const fields=card.querySelectorAll('textarea,input,select,button[data-action="resource"]');
    (last?fields[fields.length-1]:fields[0])?.focus();
  }
  function showPanel(panel, id = null, focus = true) {
    activePanel = panel;
    outputPanelId = id;
    renderPanels();
    if (panel) root.querySelector(".pc-document-menu")?.removeAttribute("open");
    if (focus && panel) root.querySelector(".pc-drawer:not([hidden]) [data-action='close-drawer']")?.focus({preventScroll:true});
  }

  function focusRunOutput() {
    const button = root.querySelector('[data-action="open-output"]');
    if (!button) return;
    showPanel(null);
    button.scrollIntoView({block:"nearest",inline:"nearest"});
    button.focus({preventScroll:true});
  }

  function beginPan(event, viewport) {
    const pointerId = event.pointerId;
    const {clientX, clientY} = event;
    const {scrollLeft, scrollTop} = viewport;
    const controller = new AbortController();
    const listener = {signal:controller.signal};
    viewport.setPointerCapture(pointerId);
    viewport.classList.add("is-panning");
    cancelPointer = () => {
      controller.abort();
      if (viewport.hasPointerCapture(pointerId)) viewport.releasePointerCapture(pointerId);
      viewport.classList.remove("is-panning");
      cancelPointer = null;
    };
    viewport.addEventListener("pointermove", next => {
      if (next.pointerId !== pointerId) return;
      viewport.scrollLeft = scrollLeft + clientX - next.clientX;
      viewport.scrollTop = scrollTop + clientY - next.clientY;
    }, listener);
    for (const name of ["pointerup","pointercancel","lostpointercapture"]) {
      viewport.addEventListener(name, next => {
        if (next.pointerId === pointerId) cancelPointer?.();
      }, listener);
    }
    event.preventDefault();
  }
  function bind() {
    root.oninput=event=>{if(event.target.matches("input:not([type=checkbox]),textarea")) valueChanged(event.target);};
    root.onchange=event=>{
      const t=event.target;
      if(t.dataset.select!=null) {const n=Number(t.dataset.select);t.checked?current.selected.add(n):current.selected.delete(n);current.confirmation=null;renderPanels();return;}
      if(t.dataset.action==="choose-canvas"&&t.value) {busy(()=>current.open(t.value));return;}
      if(t.matches("select[data-node]")) valueChanged(t);
    };
    root.onclick=event=>{
      const button=event.target.closest("button[data-action]");if(!button) return;
      const action=button.dataset.action,node=current.doc.graph.nodes.find(n=>n.id===button.dataset.node),index=Number(button.dataset.value);
      if(action==="toggle-history") {showPanel(activePanel==="history"?null:"history",null,false);return;}
      if(action==="close-drawer") {
        const trigger = activePanel==="history" ? root.querySelector('[data-action="toggle-history"]')
          : activePanel==="output" ? [...root.querySelectorAll('[data-action="open-output"]')].find(element=>element.dataset.node===outputPanelId)
          : root.querySelector('[data-action="preview"]');
        showPanel(null);trigger?.focus({preventScroll:true});return;
      }
      if(action==="choose-run") {void busy(()=>current.watch(button.dataset.run));return;}
      if(action==="focus-run-output") {focusRunOutput();return;}
      if(action==="open-output"||action==="show-detached-output") {
        const id=button.dataset.node||null;
        showPanel(activePanel==="output"&&outputPanelId===id?null:"output",id);
        return;
      }
      if(action==="open-result-image") {options.openImage?.(button.dataset.url,button.dataset.title);return;}
      if(action==="guided-view"||action==="free-view") {current.view=action==="free-view"?"free":"guided";current.persist();render();return;}
      if(action==="port") {
        if(suppressPortClick) {suppressPortClick=false;return;}
        const next=portRef(button);
        if(selectedPort?.node===next.node && selectedPort.direction===next.direction) clearWire();
        else if(selectedPort && selectedPort.direction!==next.direction) connectPorts(selectedPort,next);
        else selectPort(button);
        return;
      }
      if(action==="add-node-menu") {
        if(nodeMenu) {closeNodeMenu();return;}
        const bounds=button.getBoundingClientRect();
        const bottom=Math.max(0,...[...root.querySelectorAll(".pc-node")].map(card=>card.offsetTop+card.offsetHeight));
        openNodeMenu(bounds.left,bounds.bottom+6,null,{x:32,y:bottom+40});
        return;
      }
      if(action==="close-node-menu") {closeNodeMenu();root.querySelector('[data-action="add-node-menu"]')?.focus();return;}
      if(action==="create-node" && nodeMenu) {
        const {position,port}=nodeMenu;
        closeNodeMenu();
        const graph=current.doc.graph;
        if(port && graph.edges.length>=400) {wireHint("画布最多可添加 400 条连线");return;}
        const added=addCanvasNode(graph,button.dataset.type,button.dataset.field,position);
        if(!added) {wireHint("画布最多可添加 200 个节点");return;}
        if(port) graph.edges.push(portConnection(port,{node:added.id,direction:port.direction==="out"?"in":"out"}));
        current.edit(true);
        focusParameter(added);
        return;
      }
      if(action==="step") {
        const section=root.querySelector(button.dataset.step==="parameters"?'.pc-parameters-area':button.dataset.step==="matching"?'.pc-matching':'.pc-checkout');
        const body=root.querySelector('.pc-guided-body');
        if(section&&body) body.scrollTop+=section.getBoundingClientRect().top-body.getBoundingClientRect().top-18;
        return;
      }
      if(action==="guided-add") {const added=addGuidedParameter(current,button.dataset.field);focusParameter(added);return;}
      if(action==="matching") {const flow=simpleFlow(current.doc.graph);if(flow) {flow.group.mode=button.dataset.mode;current.edit(true);}return;}
      if(action==="undo-remove") {const graph=current.removal;if(graph) {current.doc.graph=graph;current.edit(true);}return;}
      if(action==="save") return void busy(()=>current.save());
      if(action==="more-canvases") return void busy(()=>current.loadMoreCanvases());
      if(action==="more-runs") return void busy(()=>current.loadMoreRuns());
      if(action==="new"||action==="copy") return void busy(()=>current.create(action==="copy"));
      if(action==="preview") {
        showPanel("preview",null,false);
        if(current.submission||current.preview) {renderPanels();return;}
        return void busy(async()=>{await current.expand();if(activePanel==="preview") showPanel("preview");});
      }
      if(action==="recheck-preview") {return void busy(()=>current.expand());}
      if(action==="refresh") return void busy(()=>current.refreshRun());
      if(action==="stop") return void busy(()=>current.stopPending());
      if(action==="retry") {if(global.confirm(`重试未成功项，额外预计 ${current.run.retryQuote.total} 积分；已成功项不重复生成。是否继续？`)) busy(()=>current.retry());return;}
      if(action==="submit" && !current.submitting && current.submission) {submitFromPreview();return;}
      if(action==="submit") {current.confirmation="submit";renderPanels();root.querySelector('[data-action="confirm-submit"]')?.focus();return;}
      if(action==="cancel-confirm") {current.confirmation=null;renderPanels();root.querySelector('[data-action="submit"]')?.focus();return;}
      if(action==="confirm-submit") {
        if(current.submitting||current.confirmation!=="submit"||!current.preview) return;
        submitFromPreview();return;
      }
      if(action==="export") {const url=URL.createObjectURL(new Blob([JSON.stringify(current.doc,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="参数画布.json";a.click();URL.revokeObjectURL(url);return;}
      if(action==="refs") {options.pickReferences?.({currentRefs:node.values[index],onConfirm:items=>{node.values[index]=items.map(item=>item.image).filter(Boolean);current.edit(true);}});return;}
      if(action==="resource"||action==="clear-resource") {
        const field=button.dataset.field;
        pickResourceCandidate(current,node,index,field,settings=>action==="clear-resource"?settings.onPick(""):options.pickResource?.(settings));return;
      }
      if(action==="zoom-resource") {
        const field=button.dataset.field,code=resourceCode(node.values[index],field);
        const resource=(options.resources?.(field==="layout"?"layout":"style")||[]).find(item=>(item.id||item.code)===code);
        if(resource?.image) options.openImage?.(resource.image,`${code} ${resource.name_zh||resource.name||""}`);return;
      }
      const removal=["remove-node","remove-value","disconnect"].includes(action)?clone(current.doc.graph):null;
      if(action==="remove-node") {current.doc.graph.nodes=current.doc.graph.nodes.filter(n=>n!==node);current.doc.graph.edges=current.doc.graph.edges.filter(e=>e.from!==node.id&&e.to!==node.id);}
      else if(action==="remove-value") node.values.splice(index,1);
      else if(action==="add-value") node.values.push(initialCandidate(node.parameter));
      else if(action==="disconnect") current.doc.graph.edges=current.doc.graph.edges.filter(e=>!(e.from===button.dataset.from&&e.to===node.id));
      else if(action==="arrange") arrangeNodes(current.doc.graph.nodes,new Map(
        Array.from(root.querySelectorAll("[data-card]")).map(card=>[card.dataset.card,{width:card.offsetWidth,height:card.offsetHeight}])
      ));
      else return;
      current.edit(true);
      if(removal) {current.removal=removal;render();}
      if(action==="add-value") focusParameter(node,true);
    };
    root.oncontextmenu=root.ondblclick=event=>{
      if(!event.target.closest(".pc-world") || event.target.closest(".pc-node")) return;
      event.preventDefault();
      openNodeMenu(event.clientX,event.clientY);
    };
    root.onkeydown=event=>{
      if(event.key==="Escape") {
        if(selectedPort||cancelPointer) {cancelPointer?.();clearWire();}
        else if(activePanel) root.querySelector('[data-action="close-drawer"]')?.click();
      }
    };
    root.onpointerdown=event=>{
      if (!event.target.closest(".pc-document-menu")) root.querySelector(".pc-document-menu")?.removeAttribute("open");
      const viewport=event.target.closest(".pc-scroll");
      if(viewport && (event.button===1 || (event.button===0 && spaceHeld))) {beginPan(event,viewport);return;}
      if(event.button!==0 || !event.isPrimary) return;
      suppressPortClick=false;
      const port=event.target.closest("[data-port]");
      if(port) {beginWire(event,port);return;}
      if(event.target.closest(".pc-world")) clearWire();
      const header=event.target.closest("[data-drag]");if(!header||event.target.closest("button")) return;
      const node=current.doc.graph.nodes.find(n=>n.id===header.dataset.drag),card=header.closest(".pc-node"),start={x:event.clientX,y:event.clientY,nx:Number(node.x)||0,ny:Number(node.y)||0};
      const pointerId=event.pointerId;
      const controller=new AbortController(),listener={signal:controller.signal};
      const world=card.parentElement;
      const syncPosition=()=>{
        card.style.left=node.x+"px";card.style.top=node.y+"px";
        world.style.width=Math.max(world.offsetWidth,node.x+card.offsetWidth+32)+"px";
        world.style.height=Math.max(world.offsetHeight,node.y+card.offsetHeight+32)+"px";
        drawEdges();
      };
      header.setPointerCapture(pointerId);
      cancelPointer=()=>{
        controller.abort();
        if(header.hasPointerCapture(pointerId)) header.releasePointerCapture(pointerId);
        cancelPointer=null;
        node.x=start.nx;node.y=start.ny;syncPosition();
      };
      header.addEventListener("pointermove",e=>{
        if(e.pointerId!==pointerId) return;
        node.x=Math.max(16,Math.min(50000,start.nx+e.clientX-start.x));
        node.y=Math.max(16,Math.min(50000,start.ny+e.clientY-start.y));
        syncPosition();
      },listener);
      header.addEventListener("pointerup",e=>{
        if(e.pointerId!==pointerId) return;
        controller.abort();cancelPointer=null;
        if(node.x!==start.nx||node.y!==start.ny) current.edit();
      },listener);
      header.addEventListener("pointercancel",()=>cancelPointer?.(),listener);
      header.addEventListener("lostpointercapture",()=>cancelPointer?.(),listener);
      event.preventDefault();
    };
  }
  function submitFromPreview() {
    current.submitting=true;
    renderPanels();
    void busy(async()=>{
      const store = current;
      try {
        await store.submit();
        if (current === store && activePanel === "preview" && !store.submission) {
          showPanel(null);
          focusRunOutput();
        }
      } finally {
        store.submitting=false;
        store.confirmation=null;
        if (current === store) status();
      }
    });
  }
  function mount(element,configuration) {
    if(root!==element || (current && options.scope!==configuration.scope)) dismissInteractions();
    if(current && (current.closed||options.scope!==configuration.scope)) {current.close();current=null;}
    const changedRoot=root!==element;root=element;options=configuration;
    if(!current) {current=new CanvasStore({...configuration,storage:global.localStorage});current.onchange=reason=>reason==="status"?status():reason==="panel"?renderPanels():render();render();bind();void current.load();}
    else if(changedRoot) {render();bind();}
  }
  function dismissInteractions() {
    closeNodeMenu();
    cancelPointer?.();
    clearWire();
    releaseSpace();
    if (activePanel) showPanel(null);
  }
  function releaseSpace() {
    spaceHeld=false;
    root?.querySelector(".pc-scroll")?.classList.remove("can-pan");
  }
  global.addEventListener?.("keydown", event=>{
    if (event.code !== "Space" || event.defaultPrevented || !root?.offsetWidth ||
        event.target.closest?.("input,textarea,select,button,summary,a,[contenteditable]")) return;
    if (event.target !== document.body && !event.target.closest?.(".pc-scroll")) return;
    const viewport = root.querySelector(".pc-scroll");
    if (!viewport) return;
    spaceHeld=true;
    viewport.classList.add("can-pan");
    event.preventDefault();
  });
  global.addEventListener?.("keyup", event=>{if(event.code==="Space") releaseSpace();});
  global.addEventListener?.("blur", releaseSpace);
  global.addEventListener?.("resize", () => {
    if (root?.offsetWidth && current && !cancelPointer) drawEdges();
  });
  global.HandrawParameterCanvas={mount,dismissInteractions,saveCurrent:()=>current?.save(),openRun:async id=>{
    const store=current;
    if(!store) return;
    await store.openRun(id);
    if(current===store && store.run?.id===id) {
      if(root.querySelector('[data-action="open-output"]')) focusRunOutput();
      else showPanel("output");
    }
  },importDocument:document=>current?.importDocument(document),reset:()=>{dismissInteractions();current?.close();current=null;root=null;panelCanvasId=null;}};
  if(global.__HANDRAW_TESTING__) global.HandrawParameterCanvas.testing={CanvasStore,blank,selectedQuote,arrangeNodes,pickResourceCandidate,simpleFlow,combinationSummary,addGuidedParameter,connectionError,addCanvasNode,outputItems};
})(window);
