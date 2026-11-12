/* Independent parameter documents and durable generation batches. */
(function (global) {
  "use strict";
  const labels={prompt:"主题",style1:"画风方案",style2:"副画风",layout:"图型",ratio:"比例",refImages:"参考图组",colors:"配色",tones:"色调",moods:"氛围",whitespace:"留白",mode:"创作模式"};
  const ratios=["1:1","3:4","4:3","9:16","16:9","2.35:1","3:2","2:3"];
  const uid=prefix=>prefix+"_"+(global.crypto?.randomUUID?.().replace(/-/g,"") || Date.now().toString(36)+Math.random().toString(36).slice(2));
  const clone=value=>JSON.parse(JSON.stringify(value));
  const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function blank() {
    return {id:uid("canvas"),name:"参数组合画布",writeSeq:0,graph:{format:1,nodes:[
      {id:"theme",type:"parameter",parameter:"prompt",values:[""],x:32,y:32},
      {id:"style",type:"parameter",parameter:"style1",values:["FA-001"],x:32,y:340},
      {id:"combine",type:"combine",mode:"cartesian",x:370,y:135},
      {id:"output",type:"output",mode:"cartesian",repeat:1,x:700,y:135}
    ],edges:[{from:"theme",to:"combine"},{from:"style",to:"combine"},{from:"combine",to:"output"}]}};
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
      this.dirty=false; this.error=""; this.closed=false; this.loading=false; this.conflict=false;
      this.preview=null; this.selected=new Set(); this.submission=null; this.onchange=()=>{};
      this.cacheKey="handraw.parameter-canvas:"+options.scope;
      try { const cached=JSON.parse(options.storage?.getItem(this.cacheKey)||"null");
        if(cached?.doc?.graph?.nodes) {this.doc=cached.doc;this.dirty=Boolean(cached.dirty);this.submission=cached.submission||null;this.preferredRunId=cached.runId||null;} } catch(_) {}
    }
    notify(reason="render") { if(!this.closed) this.onchange(reason); }
    persist() { try { this.options.storage?.setItem(this.cacheKey,JSON.stringify({doc:this.doc,dirty:this.dirty,submission:this.submission,runId:this.runId||null})); }
      catch(_) { this.error="本地保存空间不足，请保存到云端或导出画布"; } }
    edit(render=false) {
      this.dirty=true; this.preview=null; this.selected.clear(); this.error=""; this.persist();
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
      this.doc=result.canvas; this.dirty=false; this.conflict=false; this.preview=null; this.run=null;this.recent=[];this.recentCursor="";
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
      if(!this.options.loggedIn()) throw new Error("请先登录，再预览和生成");
      if(this.submission) throw new Error("请先确认上一次提交状态");
      if(!this.doc.writeSeq) this.dirty=true;
      if(!(await this.save())) return;
      const id=this.doc.id,key=JSON.stringify(this.doc.graph);
      const result=await this.options.api(`/api/studio/canvases/${encodeURIComponent(id)}/preview`,{method:"POST",body:{}});
      if(this.closed) return;
      if(id!==this.doc.id||key!==JSON.stringify(this.doc.graph)) throw new Error("参数已变化，请重新预览");
      this.preview=result;this.selected=new Set(result.items.map(item=>item.ordinal));this.submitKey=uid("canvas_run");this.notify();
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
      this.recent=result.items||[];this.recentCursor=result.nextCursor||"";this.notify();
      const preferred=this.preferredRunId;this.preferredRunId=null;
      if(open && (preferred||this.recent[0])) await this.watch(preferred||this.recent[0].id);
    }
    async loadMoreRuns() {
      if(!this.recentCursor||this.recentLoading) return;
      const id=this.doc.id,cursor=this.recentCursor;this.recentLoading=true;this.notify();
      try {
        const result=await this.options.api(`/api/studio/canvases/${encodeURIComponent(id)}/runs?cursor=${encodeURIComponent(cursor)}`);
        if(this.closed||id!==this.doc.id||cursor!==this.recentCursor) return;
        const byId=new Map(this.recent.map(item=>[item.id,item]));
        for(const item of result.items||[]) if(!byId.has(item.id)) byId.set(item.id,item);
        this.recent=[...byId.values()];this.recentCursor=result.nextCursor||"";
      } finally {this.recentLoading=false;this.notify();}
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
    async watch(id) { if(this.runId!==id) this.retryPayload=null;this.runId=id;this.persist();await this.refreshRun(); }
    async refreshRun() {
      clearTimeout(this.pollTimer);
      const id=this.runId;if(!id||this.closed) return;
      try {
        const result=await this.options.api("/api/studio/canvas-runs/"+encodeURIComponent(id));
        if(this.closed||id!==this.runId) return;
        this.run=result.run;
        if(this.run.canvasId===this.doc.id && !this.recent.some(item=>item.id===id))
          this.recent.push({id,count:this.run.count,createdAt:this.run.createdAt||"已保存批次"});
        this.notify();
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
  const busy=action=>Promise.resolve().then(action).catch(error=>current?.fail(error));
  function status() {
    const el=root?.querySelector("[data-pc-status]");if(!el||!current) return;
    el.textContent=current.conflict?"保存冲突，本地草稿已保留":!options.loggedIn()?"草稿保存在当前浏览器":current.savePromise?"正在保存…":current.dirty?"有未保存改动":"已保存";
    const select=root.querySelector('[data-action="choose-canvas"]');
    if(select) select.innerHTML='<option value="">已保存的画布</option>'+current.list.map(item=>`<option value="${esc(item.id)}" ${item.id===current.doc.id?"selected":""}>${esc(item.name)}</option>`).join("");
  }
  function parameterValue(node,value,index) {
    const id=esc(node.id),field=node.parameter,base=`data-node="${id}" data-value="${index}"`;
    if(field==="refImages") return `<button type="button" ${base} data-action="refs">选择一组参考图（${value.length}/6）</button><div class="pc-references">${value.map(url=>`<img src="${esc(url)}" alt="已选参考图" loading="lazy">`).join("")}</div>`;
    if(field==="prompt") return `<textarea aria-label="主题候选 ${index+1}" ${base}>${esc(value)}</textarea>`;
    if(field==="ratio") return `<select aria-label="比例候选 ${index+1}" ${base}>${ratios.map(r=>`<option ${r===value?"selected":""}>${r}</option>`).join("")}</select>`;
    if(field==="mode") return `<select aria-label="创作模式候选 ${index+1}" ${base}><option value="graphic-text" ${value!=="image-only"?"selected":""}>图文</option><option value="image-only" ${value==="image-only"?"selected":""}>纯图</option></select>`;
    if(field==="style1") return `<input aria-label="主画风候选 ${index+1}" list="pc-style-codes" placeholder="主画风编号，如 FA-001" ${base} data-fusion="style1" value="${esc(typeof value==="object"?value.style1:value)}"><input aria-label="融合副画风 ${index+1}" list="pc-style-codes" placeholder="副画风，可留空" ${base} data-fusion="style2" value="${esc(value?.style2||"")}">`;
    return `<input aria-label="${labels[field]||field}候选 ${index+1}" ${base} ${field==="layout"?'list="pc-layout-codes"':''} placeholder="${["colors","tones","moods"].includes(field)?"同一方案中的值用逗号分隔":"填写参数值"}" value="${esc(Array.isArray(value)?value.join("，"):value)}">`;
  }
  function nodeHtml(node,index) {
    const graph=current.doc.graph,incoming=graph.edges.filter(edge=>edge.to===node.id),name=node.type==="parameter"?labels[node.parameter]:node.type==="combine"?"组合方式":"输出";
    return `<section class="pc-node" data-card="${esc(node.id)}" style="left:${Number(node.x)||32}px;top:${Number(node.y)||32}px">
      <header data-drag="${esc(node.id)}"><strong>${esc(name)} ${index+1}</strong><button type="button" data-action="remove-node" data-node="${esc(node.id)}" aria-label="删除${esc(name)}节点">×</button></header>
      <div class="pc-node-body">${node.type==="parameter"?
        `<p>每个候选是一套完整方案</p>${node.values.map((value,i)=>`<div class="pc-candidate">${parameterValue(node,value,i)}<button type="button" data-action="remove-value" data-node="${esc(node.id)}" data-value="${i}" aria-label="删除候选 ${i+1}">移除</button></div>`).join("")}<button type="button" data-action="add-value" data-node="${esc(node.id)}">＋ 添加候选</button>`:
        `<label>搭配方式<select data-node="${esc(node.id)}" data-property="mode"><option value="cartesian" ${node.mode!=="zip"?"selected":""}>全部交叉组合</option><option value="zip" ${node.mode==="zip"?"selected":""}>按行搭配，单值复用</option></select></label>
        ${node.type==="output"?`<label>每组生成张数<input type="number" min="1" max="200" data-node="${esc(node.id)}" data-property="repeat" value="${node.repeat||1}"></label>`:""}
        <div class="pc-links">${incoming.map(edge=>`<span>${esc(graph.nodes.find(n=>n.id===edge.from)?.type==="parameter"?labels[graph.nodes.find(n=>n.id===edge.from).parameter]:"组合节点")}<button type="button" data-action="disconnect" data-node="${esc(node.id)}" data-from="${esc(edge.from)}" aria-label="断开输入">×</button></span>`).join("")}</div>
        <label>连接输入<select data-connect="${esc(node.id)}"><option value="">选择节点</option>${graph.nodes.filter(n=>n.type!=="output"&&n.id!==node.id&&!incoming.some(e=>e.from===n.id)).map(n=>`<option value="${esc(n.id)}">${esc(n.type==="parameter"?labels[n.parameter]:"组合")} ${graph.nodes.indexOf(n)+1}</option>`).join("")}</select></label>`}</div></section>`;
  }
  function drawEdges() {
    const svg=root.querySelector(".pc-edges");if(!svg) return;
    const cards=new Map(Array.from(root.querySelectorAll("[data-card]")).map(card=>[card.dataset.card,card]));
    svg.innerHTML=current.doc.graph.edges.map(edge=>{
      const a=cards.get(edge.from),b=cards.get(edge.to);
      if(!a||!b) return "";
      const x=a.offsetLeft+a.offsetWidth,y=a.offsetTop+35,u=b.offsetLeft,v=b.offsetTop+35;
      return `<path d="M${x},${y} C${x+80},${y} ${u-80},${v} ${u},${v}"/>`;
    }).join("");
  }
  function renderPanel() {
    const panel=root?.querySelector(".pc-results");if(!panel||!current) return;
    const preview=current.preview,run=current.run,q=preview?selectedQuote(preview,current.selected.size):null;
    panel.innerHTML=`${current.submission?'<p role="status">正在确认上一批提交状态，重试确认不会重复创建批次。</p><button type="button" data-action="submit">确认提交状态</button>':""}
      ${preview?`<h3>组合预览 · ${preview.count} 项</h3><p>已选 ${q.count} 张 · 免费 ${q.freeUsed} 张 · 预计 ${q.total} 积分</p><p class="pc-muted">额度会在实际提交时核验；不会超过本次确认的积分上限。单批最多 200 张。</p>
      <button type="button" class="pc-primary" data-action="submit" ${!q.count||!q.affordable||current.submission?"disabled":""}>生成选中的 ${q.count} 张</button><div class="pc-plan-list">${preview.items.map(item=>`<label><input type="checkbox" data-select="${item.ordinal}" ${current.selected.has(item.ordinal)?"checked":""} ${current.submission?"disabled":""}><span><b>${item.ordinal+1}.</b> ${esc(item.spec.prompt.slice(0,100))}<small>${esc([item.spec.style1,item.spec.style2,item.spec.layout,item.spec.ratio].filter(Boolean).join(" · "))}</small></span></label>`).join("")}</div>`:"<h3>本次出图</h3><p class='pc-muted'>先连接参数，再预览实际组合。固定参数只填一个候选。</p>"}
      ${current.recent.length?`<label>查看批次<select data-action="choose-run"><option value="">选择批次</option>${current.recent.map(r=>`<option value="${esc(r.id)}" ${r.id===current.runId?"selected":""}>${esc(r.createdAt)} · ${r.count} 张</option>`).join("")}</select></label>`:""}
      ${current.recentCursor?`<button type="button" data-action="more-runs" ${current.recentLoading?"disabled":""}>${current.recentLoading?"正在载入…":"加载更早的批次"}</button>`:""}
      ${run?`<h3>批次进度</h3><p role="status">已完成 ${run.items.filter(item=>item.status==="success").length} / ${run.count} 张 · 已用 ${run.spentCredits} 积分</p><div class="pc-run-actions"><button type="button" data-action="refresh">刷新</button>${run.items.some(i=>i.status==="pending")?'<button type="button" data-action="stop">停止未提交任务</button>':""}${run.items.some(i=>["failed","cancelled"].includes(i.status))?`<button type="button" data-action="retry">重试未成功项（预计 ${run.retryQuote.total} 积分）</button>`:""}</div><p class="pc-muted">关闭页面后仍会继续出图。已提交上游的任务按实际结果结算。</p>
      <div class="pc-gallery">${run.items.map(item=>`<article><strong>${item.ordinal+1}. ${esc(item.spec.prompt.slice(0,60))}</strong><span>${({pending:"等待提交",generating:"生成中",success:"已完成",failed:"未成功",cancelled:"已停止"})[item.status]||"等待确认"}</span>${item.images.map(url=>`<a href="${esc(url)}" target="_blank" rel="noopener"><img src="${esc(url)}" alt="${esc(item.spec.prompt.slice(0,80))}" loading="lazy"></a>`).join("")}${item.errorCode?'<small>本项未完成；可检查参数和额度后重试。</small>':""}</article>`).join("")}</div>`:""}`;
  }
  function render() {
    if(!root||!current||current.closed) return;
    const doc=current.doc;
    root.innerHTML=`<div class="pc-header"><div><p class="pc-kicker">参数画布</p><input class="pc-name" aria-label="画布名称" data-name value="${esc(doc.name)}"><span data-pc-status></span></div><div class="pc-actions"><select aria-label="打开已保存画布" data-action="choose-canvas" ${current.submission?"disabled":""}><option value="">已保存的画布</option>${current.list.map(item=>`<option value="${esc(item.id)}" ${item.id===doc.id?"selected":""}>${esc(item.name)}</option>`).join("")}</select>${current.listCursor?`<button type="button" data-action="more-canvases" ${current.listLoading?"disabled":""}>${current.listLoading?"正在载入…":"更多画布"}</button>`:""}<button type="button" data-action="new" ${current.submission?"disabled":""}>新建</button><button type="button" data-action="copy">另存副本</button><button type="button" data-action="save">保存</button><button type="button" data-action="export">导出画布</button></div></div>
      ${current.error?`<div class="pc-error" role="alert">${esc(current.error)}${current.conflict?'。可另存副本保留本地改动。':""}</div>`:""}
      <div class="pc-toolbar"><label>参数类型<select id="pc-add-parameter">${Object.entries(labels).filter(([k])=>k!=="style2").map(([key,name])=>`<option value="${key}">${name}</option>`).join("")}</select></label><button type="button" data-action="parameter">＋ 参数</button><button type="button" data-action="combine">＋ 组合</button><button type="button" data-action="output">＋ 输出</button><button type="button" data-action="arrange">整理位置</button><button type="button" class="pc-primary" data-action="preview" ${current.loading||current.submission?"disabled":""}>预览组合与费用</button></div>
      <div class="pc-layout"><div class="pc-scroll" aria-label="参数节点画布"><div class="pc-world" style="width:${Math.max(1050,...doc.graph.nodes.map(n=>(Number(n.x)||0)+320))}px;height:${Math.max(760,...doc.graph.nodes.map(n=>(Number(n.y)||0)+500))}px"><svg class="pc-edges" aria-hidden="true"></svg>${doc.graph.nodes.map(nodeHtml).join("")}</div></div><aside class="pc-results" aria-label="组合预览和批次结果"></aside></div>
      ${["style","layout"].map(kind=>`<datalist id="pc-${kind}-codes">${(options.resources?.(kind)||[]).map(r=>`<option value="${esc(r.id||r.code)}">${esc(r.name||r.name_zh||r.title||"")}</option>`).join("")}</datalist>`).join("")}`;
    status();renderPanel();drawEdges();
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
  function bind() {
    root.oninput=event=>{if(event.target.matches("input:not([type=checkbox]),textarea")) valueChanged(event.target);};
    root.onchange=event=>{
      const t=event.target;
      if(t.dataset.select!=null) {const n=Number(t.dataset.select);t.checked?current.selected.add(n):current.selected.delete(n);renderPanel();return;}
      if(t.dataset.action==="choose-canvas"&&t.value) {busy(()=>current.open(t.value));return;}
      if(t.dataset.action==="choose-run"&&t.value) {busy(()=>current.watch(t.value));return;}
      if(t.dataset.connect) {if(t.value) {current.doc.graph.edges.push({from:t.value,to:t.dataset.connect});current.edit(true);}return;}
      if(t.matches("select[data-node]")) valueChanged(t);
    };
    root.onclick=event=>{
      const button=event.target.closest("button[data-action]");if(!button) return;
      const action=button.dataset.action,node=current.doc.graph.nodes.find(n=>n.id===button.dataset.node),index=Number(button.dataset.value);
      if(action==="save") return void busy(()=>current.save());
      if(action==="more-canvases") return void busy(()=>current.loadMoreCanvases());
      if(action==="more-runs") return void busy(()=>current.loadMoreRuns());
      if(action==="new"||action==="copy") return void busy(()=>current.create(action==="copy"));
      if(action==="preview") return void busy(()=>current.expand());
      if(action==="refresh") return void busy(()=>current.refreshRun());
      if(action==="stop") return void busy(()=>current.stopPending());
      if(action==="retry") {if(global.confirm(`重试未成功项，额外预计 ${current.run.retryQuote.total} 积分；已成功项不重复生成。是否继续？`)) busy(()=>current.retry());return;}
      if(action==="submit") {if(current.submission||global.confirm(`本次生成 ${current.selected.size} 张，积分上限 ${selectedQuote(current.preview,current.selected.size).total}。额度变化后，达到上限的任务将停止提交。是否开始？`)) busy(()=>current.submit());return;}
      if(action==="export") {const url=URL.createObjectURL(new Blob([JSON.stringify(current.doc,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="参数画布.json";a.click();URL.revokeObjectURL(url);return;}
      if(action==="refs") {options.pickReferences?.({currentRefs:node.values[index],onConfirm:items=>{node.values[index]=items.map(item=>item.image).filter(Boolean);current.edit(true);}});return;}
      if(action==="remove-node") {current.doc.graph.nodes=current.doc.graph.nodes.filter(n=>n!==node);current.doc.graph.edges=current.doc.graph.edges.filter(e=>e.from!==node.id&&e.to!==node.id);}
      else if(action==="remove-value") node.values.splice(index,1);
      else if(action==="add-value") node.values.push(["refImages","colors","tones","moods"].includes(node.parameter)?[]:node.parameter==="ratio"?"3:4":node.parameter==="mode"?"graphic-text":"");
      else if(action==="disconnect") current.doc.graph.edges=current.doc.graph.edges.filter(e=>!(e.from===button.dataset.from&&e.to===node.id));
      else if(["parameter","combine","output"].includes(action)) {const field=root.querySelector("#pc-add-parameter").value;current.doc.graph.nodes.push({id:uid("node"),type:action,parameter:field,values:[["refImages","colors","tones","moods"].includes(field)?[]:field==="ratio"?"3:4":field==="mode"?"graphic-text":""],mode:"cartesian",repeat:1,x:40+(current.doc.graph.nodes.length%3)*335,y:40+Math.floor(current.doc.graph.nodes.length/3)*330});}
      else if(action==="arrange") current.doc.graph.nodes.forEach((n,i)=>{n.x=32+(i%3)*335;n.y=32+Math.floor(i/3)*330;});
      else return;
      current.edit(true);
    };
    root.onpointerdown=event=>{
      const header=event.target.closest("[data-drag]");if(!header||event.target.closest("button")) return;
      const node=current.doc.graph.nodes.find(n=>n.id===header.dataset.drag),card=header.closest(".pc-node"),start={x:event.clientX,y:event.clientY,nx:Number(node.x)||0,ny:Number(node.y)||0};
      header.setPointerCapture(event.pointerId);
      header.onpointermove=e=>{node.x=Math.max(0,start.nx+e.clientX-start.x);node.y=Math.max(0,start.ny+e.clientY-start.y);card.style.left=node.x+"px";card.style.top=node.y+"px";drawEdges();};
      header.onpointerup=()=>{header.onpointermove=null;header.onpointerup=null;current.edit();};
      event.preventDefault();
    };
  }
  function mount(element,configuration) {
    if(current && (current.closed||options.scope!==configuration.scope)) {current.close();current=null;}
    const changedRoot=root!==element;root=element;options=configuration;
    if(!current) {current=new CanvasStore({...configuration,storage:global.localStorage});current.onchange=reason=>reason==="status"?status():render();render();bind();void current.load();}
    else if(changedRoot) {render();bind();}
  }
  global.HandrawParameterCanvas={mount,saveCurrent:()=>current?.save(),openRun:id=>current?.openRun(id),importDocument:document=>current?.importDocument(document),reset:()=>{current?.close();current=null;root=null;}};
  if(global.__HANDRAW_TESTING__) global.HandrawParameterCanvas.testing={CanvasStore,blank,selectedQuote};
})(window);
