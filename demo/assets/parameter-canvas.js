/* Independent parameter documents and durable generation batches. */
(function (global) {
  "use strict";
  const labels={prompt:"主题",style1:"画风方案",style2:"副画风",layout:"图型",ratio:"比例",refImages:"参考图组",colors:"配色",tones:"影调",moods:"氛围",whitespace:"留白",mode:"创作模式"};
  const ratios=["1:1","3:4","4:3","9:16","16:9","2.35:1","3:2","2:3"];
  const uid=prefix=>prefix+"_"+(global.crypto?.randomUUID?.().replace(/-/g,"") || Date.now().toString(36)+Math.random().toString(36).slice(2));
  const clone=value=>JSON.parse(JSON.stringify(value));
  const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const resourceCode=(value,field)=>typeof value==="object"&&value!==null?String(value[field]||""):field==="style2"?"":String(value||"");
  const runDate=value=>Number.isNaN(new Date(value).getTime())?String(value||"已保存批次"):new Date(value).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});
  const isParameter = node => ["parameter","parameters"].includes(node.type);
  const nodeName = node => node.type === "parameters" ? "出图参数" : node.type === "parameter" ? labels[node.parameter] : node.type === "combine" ? "参数组合" : "批量出图";
  const defaultFields = () => ({prompt:[""],style1:["FA-001"],layout:[""],ratio:["3:4"]});
  const coordinate = value => Math.max(-50000, Math.min(50000, value));
  const panMargin = 320;
  const creationModes=[{value:"image-only",label:"纯图"},{value:"graphic-text",label:"图文"},{value:"poster",label:"海报"}];
  function choiceOptions(field,items=[]) {
    return [...new Map(items.map(item=>typeof item==="string"?{value:item,label:item}:({value:String(item.value??item.id??""),label:item.label||item.name_zh||item.name||item.value||item.id||"不限",image:item.image||""})).map(item=>[item.value,item])).values()];
  }
  function customSelection(previous,text,choices) {
    const known=new Set(choices.map(item=>item.value));
    return [...new Set([...(Array.isArray(previous)?previous:[]).filter(value=>known.has(value)),...String(text||"").split(/[,，、;；\n]/).map(value=>value.trim()).filter(Boolean)])];
  }
  function sketchIcon(kind) {
    const marks={
      new:'<path d="M5.2 3.6 15.2 3.2 19.5 7.4 19.7 21 5 20.6Z"/><path d="m15.2 3.4-.2 4.3 4.6-.3"/><path d="M12.1 10.4v7.3M8.6 14.1l7.3-.2"/>',
      save:'<path d="M4 3.5 18 3.1 20.6 5.7 20.2 20.7 4.2 21Z"/><path d="M7.4 3.6v6.4l9.1-.2V3.5"/><path d="M8 20.5v-7.4l8.5.1V21"/><path d="M13.8 5v3.1"/>',
      export:'<path d="M4.1 15.9v4.7l15.9.2v-4.6"/><path d="M11.8 3.2v12.4"/><path d="m7.6 11.7 4.2 4.1 4.5-4.3"/>',
      open:'<path d="M2.9 6.7 3.1 19.7l17.6.3 1-10.5-10.3-.3-2.5-3.1-6-.1Z"/><path d="M3 9.8 21.3 9.6"/>',
      undo:'<path d="M9.3 6.5 4 11.2l5.4 4.5"/><path d="M4.6 11.2h9.1c4.2 0 6 2.1 6 5.2 0 2.1-1.6 3.5-3.3 4"/>'
    };
    return `<svg class="pc-sketch-icon" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${marks[kind]||""}</svg>`;
  }
  function recentCanvases(items) {
    return [...new Map(items.filter(item=>item?.id && !item.isOfficialPreset && !String(item.id).startsWith("preset_")).map(item=>[item.id,item])).values()]
      .sort((a,b)=>(Date.parse(b.updatedAt)||Number(b.updatedAtMs)||0)-(Date.parse(a.updatedAt)||Number(a.updatedAtMs)||0) || String(a.id).localeCompare(String(b.id)))
      .slice(0,10);
  }
  const nodeMenuEntries = [
    {type:"parameters",name:"出图参数",group:"生成流程",detail:"在一张卡里编辑主题、画风、图型和比例",out:true},
    {type:"output",name:"批量出图",group:"生成流程",detail:"接收参数，设置每组出几张",in:true},
    {type:"combine",name:"参数组合",group:"高级节点",detail:"把来自多条连线的参数合成一组组出图方案",in:true,out:true},
    ...Object.entries(labels).filter(([field])=>field!=="style2")
      .map(([field,name])=>({type:"parameter",field,name,group:"单项参数",out:true}))
  ];
  const fieldList = node => Object.keys(labels).filter(field => Object.hasOwn(node.fields, field))
    .map(field => ({id:node.id,parameter:field,values:node.fields[field]}));

  function connectionError(graph, from, to) {
    const source = graph.nodes.find(node => node.id === from);
    const target = graph.nodes.find(node => node.id === to);
    if (!source || !target || source === target) return "请连接两个不同节点";
    if (source.type === "output" || isParameter(target)) return "请从右侧输出连接到左侧输入";
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
      x: coordinate(position.x),
      y: coordinate(position.y)
    };
    if (type === "parameter") {
      node.parameter = field;
      node.values = [initialCandidate(field)];
    } else {
      node.mode = "cartesian";
      if (type === "parameters") {
        node.fields = defaultFields();
        node.fieldOrder = Object.keys(node.fields);
      }
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
  function parameterField(node, field) {
    if (node?.type !== "parameters") return node;
    return {id:node.id, parameter:field, values:node.fields[field]};
  }
  function pickResourceCandidate(store,node,index,field,openPicker,parameter=node.parameter) {
    const doc=store.doc,values=parameterField(node,parameter).values,previous=values[index];
    openPicker({field,current:resourceCode(previous,field),onPick:code=>{
      if(store.closed||store.doc!==doc||!doc.graph.nodes.includes(node)||parameterField(node,parameter).values!==values||values[index]!==previous) return;
      code=String(code||"").trim();
      if(parameter==="style1") {
        const pair={style1:resourceCode(previous,"style1"),style2:resourceCode(previous,"style2")};
        pair[field]=code;
        values[index]=!pair.style1?"":pair.style2?pair:pair.style1;
      } else values[index]=code;
      store.edit(true);
    }});
  }
  function blank() {
    return {id:uid("canvas"),name:"参数组合画布",writeSeq:0,graph:{format:1,nodes:[
      {id:"params",type:"parameters",fields:defaultFields(),fieldOrder:["prompt","style1","layout","ratio"],mode:"cartesian",x:32,y:32},
      {id:"output",type:"output",mode:"cartesian",repeat:1,x:485,y:185}
    ],edges:[{from:"params",to:"output"}]}};
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
    if(graph.nodes.length===2 && graph.edges.length===1) {
      const group=graph.nodes.find(node=>node.type==="parameters"),output=graph.nodes.find(node=>node.type==="output");
      if(group && output && graph.edges[0].from===group.id && graph.edges[0].to===output.id)
        return {parameters:fieldList(group),group,output};
    }
    const parameters=graph.nodes.filter(n=>n.type==="parameter"),groups=graph.nodes.filter(n=>n.type==="combine"),outputs=graph.nodes.filter(n=>n.type==="output");
    if(groups.length!==1||outputs.length!==1||graph.nodes.length!==parameters.length+2||new Set(parameters.map(n=>n.parameter)).size!==parameters.length) return null;
    const group=groups[0],output=outputs[0],expected=new Set([...parameters.map(n=>n.id+"\u0000"+group.id),group.id+"\u0000"+output.id]);
    if(graph.edges.length!==expected.size||!graph.edges.every(e=>expected.has(e.from+"\u0000"+e.to))) return null;
    if(new Set(graph.edges.map(e=>e.from+"\u0000"+e.to)).size!==expected.size) return null;
    return {parameters,group,output};
  }
  function groupExistingParameters(graph, flow) {
    if (!flow || flow.group.type !== "combine" || !flow.parameters.length) return false;
    if (flow.parameters.some(node=>!Object.hasOwn(labels,node.parameter))) return false;
    const {parameters,group,output}=flow;
    const byId=new Map(parameters.map(node=>[node.id,node]));
    const ordered=graph.edges.filter(edge=>edge.to===group.id).map(edge=>byId.get(edge.from));
    const fields=Object.fromEntries(ordered.map(node=>[node.parameter,node.values]));
    const node={...group,type:"parameters",fields,fieldOrder:ordered.map(node=>node.parameter),
      x:Math.min(...parameters.map(node=>node.x??32)),y:Math.min(...parameters.map(node=>node.y??32))};
    graph.nodes=[node,output];
    graph.edges=[{from:node.id,to:output.id}];
    return true;
  }

  function addParameterField(node,field) {
    node.fields[field]=[initialCandidate(field)];
    node.fieldOrder?.push(field);
  }
  function removeParameterField(node,field) {
    if(node?.type!=="parameters" || !Object.hasOwn(node.fields,field)) return false;
    delete node.fields[field];
    if(node.fieldOrder) node.fieldOrder=node.fieldOrder.filter(item=>item!==field);
    return true;
  }
  function removeCandidate(node,field,index) {
    const target=parameterField(node,field),values=target?.values;
    if(!Array.isArray(values) || !Number.isInteger(index) || index<0 || index>=values.length) return false;
    if(values.length===1) {
      if(node.type==="parameters" && field!=="prompt" && Object.keys(node.fields).length>1) removeParameterField(node,field);
      else values[0]=initialCandidate(target.parameter);
    } else values.splice(index,1);
    return true;
  }
  function repairEmptyCandidates(graph) {
    let changed=false;
    for(const node of graph.nodes || []) {
      if(node.type==="parameters" && node.fields) {
        for(const [field,values] of Object.entries(node.fields)) {
          if(!Array.isArray(values) || values.length) continue;
          if(field!=="prompt" && Object.keys(node.fields).length>1) removeParameterField(node,field);
          else node.fields[field]=[initialCandidate(field)];
          changed=true;
        }
      } else if(node.type==="parameter" && Array.isArray(node.values) && !node.values.length) {
        node.values=[initialCandidate(node.parameter)];changed=true;
      }
    }
    return changed;
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
    if(flow.group.type==="parameters") {
      addParameterField(flow.group,field);
      store.edit(true);
      return {id:flow.group.id,parameter:field};
    }
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

  // Bounded examples use the same field and edge order as the saved plan.
  function matchingPreview(sources, mode, repeat=1, limit=4) {
    if (!sources.length || sources.some(source=>!source.count)) return {count:0,samples:[],error:"先填写出图内容"};
    const lengths=sources.map(source=>source.count),longest=Math.max(...lengths);
    if (mode==="zip" && lengths.some(count=>count!==1 && count!==longest)) {
      const sizes=sources.filter(source=>source.count>1).map(source=>`${source.count}${source.unit||"项"}${source.name}`).join("、");
      return {count:0,samples:[],error:`${sizes}，数量不同，无法按序号配对。补齐数量，或选择全部尝试。`};
    }
    const count=(mode==="zip"?longest:lengths.reduce((a,b)=>a*b,1))*repeat;
    if (!Number.isInteger(repeat)||repeat<1||repeat>200) return {count:0,samples:[],error:"每种结果的张数需为 1–200"};
    const samples=[];
    for(let index=0;index<Math.min(count,limit);index++) {
      let position=Math.floor(index/repeat);
      const picks=[];
      for(let i=sources.length-1;i>=0;i--) {
        const offset=mode==="zip"?(lengths[i]===1?0:position):position%lengths[i];
        picks.unshift(sources[i].samples[offset]);
        if(mode!=="zip") position=Math.floor(position/lengths[i]);
      }
      const row={};
      for(const pick of picks) {
        if (!pick) continue;
        for(const [key,value] of Object.entries(pick)) {
          if(Object.hasOwn(row,key)) return {count:0,samples:[],error:`${labels[key]}被设置了两次，请保留其中一处。`};
          row[key]=value;
        }
      }
      samples.push(row);
    }
    return {count,samples,error:count>200?"超过单批 200 张，请减少内容或张数。":""};
  }

  function matchingSources(graph,node,active=new Set()) {
    if (active.has(node.id)) return {sources:[],error:"连线形成了循环，请先调整连线"};
    const next=new Set(active).add(node.id);
    if(isParameter(node)) {
      const fields=node.type==="parameter"?[node.parameter]
        : node.fieldOrder || Object.keys(node.fields).sort((a,b)=>Number(b==="prompt")-Number(a==="prompt")||a.localeCompare(b));
      return {sources:fields.map(field=>{
        const values=node.type==="parameter"?node.values:node.fields[field];
        const samples=values.map(value=>field==="style1" && value && typeof value==="object"?value:{[field]:value});
        return {name:field==="style1"?"画风":labels[field],field,unit:field==="prompt"?"个":"种",count:values.length,samples};
      })};
    }
    const sources=[];
    for(const edge of graph.edges.filter(edge=>edge.to===node.id)) {
      const input=graph.nodes.find(item=>item.id===edge.from);
      if(!input) return {sources:[],error:"请重新连接已删除的节点"};
      const nested=matchingSources(graph,input,next);
      if(nested.error) return nested;
      const result=matchingPreview(nested.sources,input.mode||"cartesian",input.type==="output"?Number(input.repeat??1):1,200);
      if(result.error) return {sources:[],error:result.error};
      sources.push({
        name:input.type==="parameter"?nested.sources[0].name:nodeName(input),
        field:input.type==="parameter"?input.parameter:null,
        unit:input.type==="parameter"?nested.sources[0].unit:"组",
        count:result.count,samples:result.samples
      });
    }
    return {sources};
  }

  function exampleValue(field,value) {
    if(field==="style1"||field==="style2"||field==="layout") {
      const resource=(options.resources?.(field==="layout"?"layout":"style")||[]).find(item=>(item.id||item.code)===value);
      return {label:resource?.name_zh||resource?.name||value,image:resource?.image};
    }
    if(field==="refImages") return {label:value.length?`${value.length} 张参考图`:""};
    if(field==="mode") return {label:creationModes.find(item=>item.value===value)?.label||value};
    if(["colors","tones","moods","whitespace"].includes(field)) {
      const choices=presetChoices(field),name=value=>choices.find(item=>item.value===value)?.label||value;
      return {label:Array.isArray(value)?value.map(name).join("、"):name(value)};
    }
    return {label:Array.isArray(value)?value.join("、"):String(value??"")};
  }

  function matchingHtml(node) {
    const {sources,error}=matchingSources(current.doc.graph,node);
    if(error) return `<p class="pc-match-warning">${esc(error)}</p>`;
    if(sources.some(source=>source.field==="prompt" && source.samples.some(row=>!String(row.prompt).trim()))) {
      return '<p class="pc-muted">填写主题后，这里会显示将要画出的内容。</p>';
    }
    const mode=node.mode||"cartesian",repeat=node.type==="output"?Number(node.repeat??1):1;
    const result=matchingPreview(sources,mode,repeat);
    const varying=sources.filter(source=>source.count>1);
    const crossTitle=varying.length===2
      ?`每个${varying[0].name}都试所有${varying[1].name}`:"所有选择都试一遍";
    const choices=varying.length>1?`<div class="pc-match-choices" role="group" aria-label="选择这批怎么画">${[
      ["cartesian",crossTitle],["zip","第 1 个配第 1 个"]
    ].map(([value,title])=>{
      const info=matchingPreview(sources,value,repeat);
      return `<button type="button" data-action="match-mode" data-node="${esc(node.id)}" data-match-mode="${value}" aria-pressed="${mode===value}">
        <strong>${esc(title)}</strong><span>${info.error && value==="zip"?"数量不同，需补齐后配对":`共 ${Number.isFinite(info.count)?info.count:"超过 200"} ${node.type==="output"?"张":"组"}`}</span></button>`;
    }).join("")}</div>`:"";
    const examples=result.samples.map((row,index)=>`<li><span class="pc-example-number">${index+1}</span><div>${Object.keys(labels).filter(field=>Object.hasOwn(row,field)).map(field=>{
      const {label,image}=exampleValue(field,row[field]);
      if(!label) return "";
      return `<span class="pc-example-value" title="${esc(label)}">${image?`<img src="${esc(image)}" alt="" loading="lazy">`:""}${esc(label.slice(0,48))}</span>`;
    }).join("")}</div></li>`).join("");
    const fixed=sources.filter(source=>source.count===1 && source.samples.some(row=>Object.values(row).some(value=>Array.isArray(value)?value.length:value)));
    return `${choices}${result.error?`<p class="pc-match-warning" role="status">${esc(result.error)}</p>`:""}
      ${examples?`<p class="pc-example-title">将画出这些内容${result.count>4?"（先看前 4 项）":""}</p><ol class="pc-match-examples">${examples}</ol>`:""}
      ${varying.length && fixed.length?'<p class="pc-match-note">只填一项的设置，每张都会用。</p>':""}`;
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
      if(repairEmptyCandidates(this.doc.graph)) {this.dirty=true;this.persist();}
      this.localDocuments=[];
      if(!options.loggedIn()) {
        try {this.localDocuments=JSON.parse(options.storage?.getItem(this.cacheKey+":saved")||"[]").filter(item=>item?.graph?.nodes);} catch(_) {}
        this.list=this.localDocuments.map(({graph,...item})=>item);
      }
      this.resetHistory();
    }
    documentState() {return JSON.stringify({name:this.doc.name,graph:this.doc.graph});}
    resetHistory() {this.undoStack=[];this.redoStack=[];this.lastState=this.documentState();this.editGroup="";}
    notify(reason="render") { if(!this.closed) this.onchange(reason); }
    persist() { try { this.options.storage?.setItem(this.cacheKey,JSON.stringify({doc:this.doc,dirty:this.dirty,submission:this.submission,runId:this.runId||null,view:this.view})); }
      catch(_) { this.error="本地保存空间不足，请保存到云端或导出画布"; } }
    edit(render=false,{record=true,group=""}={}) {
      const state=this.documentState(),stamp=Date.now();
      if(record && state!==this.lastState) {
        if(!group || group!==this.editGroup || stamp-this.editStamp>750) {
          this.undoStack.push(this.lastState);
          if(this.undoStack.length>40) this.undoStack.shift();
        } else if(this.undoStack[this.undoStack.length-1]===state) {
          this.undoStack.pop();group="";
        }
        this.redoStack=[];
      }
      this.lastState=state;this.editGroup=group;this.editStamp=stamp;
      this.dirty=true; this.preview=null; this.confirmation=null;this.selected.clear(); this.error=""; this.persist();
      clearTimeout(this.saveTimer);
      if(!this.conflict) this.saveTimer=setTimeout(()=>{void this.save().catch(error=>this.fail(error));},650);
      this.notify(render?"render":"status");
    }
    undo(redo=false) {
      const source=redo?this.redoStack:this.undoStack,target=redo?this.undoStack:this.redoStack;
      if(!source.length) return false;
      target.push(this.documentState());
      const previous=JSON.parse(source.pop());
      this.doc.name=previous.name;this.doc.graph=previous.graph;
      this.edit(true,{record:false});
      return true;
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
      if(this.submission) throw new Error("请先确认上一次提交状态");
      const navigation=++this.navigation;
      if(save && this.dirty && !(await this.save())) return;
      if(this.closed||navigation!==this.navigation) return;
      this.runId=null;clearTimeout(this.pollTimer);
      const result=this.options.loggedIn() ? await this.options.api("/api/studio/canvases/"+encodeURIComponent(id))
        : {canvas:clone(this.localDocuments.find(item=>item.id===id)||{})};
      if(!result.canvas?.graph) throw new Error("画布不存在");
      if(this.closed||navigation!==this.navigation) return;
      this.doc=result.canvas;this.confirmation=null;this.dirty=false; this.conflict=false; this.preview=null; this.run=null;this.recent=[];this.recentCursor="";
      const repaired=repairEmptyCandidates(this.doc.graph);
      this.error="";this.resetHistory(); this.persist();
      if(repaired) this.edit(true,{record:false});else this.notify();
      await this.loadRecent();
    }
    async create(copy=false) {
      if(this.submission) throw new Error("请先确认上一次提交状态");
      if(!copy && this.dirty && !(await this.save())) return;
      this.navigation++;
      this.doc=copy?{...clone(this.doc),id:uid("canvas"),writeSeq:0,name:this.doc.name+" 副本"}:blank();
      this.runId=null;clearTimeout(this.pollTimer);
      this.preferredRunId=null;this.conflict=false;this.run=null;this.recent=[];this.recentCursor="";this.resetHistory();this.edit(true);
    }
    async importDocument(document) {
      if(this.submission) throw new Error("请先确认上一次提交状态");
      if(this.dirty && !this.conflict && !(await this.save())) return false;
      this.navigation++;
      this.doc={id:uid("canvas"),name:document.name||"导入的参数画布",writeSeq:0,graph:clone(document.graph)};
      repairEmptyCandidates(this.doc.graph);
      this.preferredRunId=null;this.conflict=false;this.run=null;this.runId=null;this.recent=[];this.recentCursor="";clearTimeout(this.pollTimer);this.resetHistory();this.edit(true);
      return this.save();
    }
    async save() {
      clearTimeout(this.saveTimer);
      if(this.closed) return false;
      if(!this.options.loggedIn()) {
        const saved={...clone(this.doc),updatedAt:new Date().toISOString()};
        const documents=[saved,...this.localDocuments.filter(item=>item.id!==saved.id)].slice(0,10);
        try {this.options.storage?.setItem(this.cacheKey+":saved",JSON.stringify(documents));}
        catch(_) {this.fail(new Error("本地保存空间不足，请导出画布后再试"));return false;}
        this.localDocuments=documents;this.list=documents.map(({graph,...item})=>item);this.dirty=false;
        this.persist();this.notify("status");return true;
      }
      if(this.conflict) return false;
      if(!this.doc.writeSeq) this.dirty=true;
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
          const entry={id:sent.id,name:sent.name,writeSeq:result.writeSeq,updatedAt:new Date().toISOString()};
          this.list=[entry,...this.list.filter(item=>item.id!==sent.id)];this.notify("status");
        }
        return !this.closed;
      })();
      this.savePromise=operation;this.notify("status");
      try {return await operation;}
      catch(error) {this.fail(error);return false;}
      finally {if(this.savePromise===operation) this.savePromise=null;this.notify("status");}
    }
    async saveNamed(name) {
      const value=String(name||"").trim();
      if(!value || value.length>100) throw new Error("请输入 1–100 个字符的工作流名称");
      if(this.closed) return false;
      if(this.doc.name!==value) {this.doc.name=value;this.edit(false,{group:"name"});}
      const saved=await this.save();
      if(saved && !this.closed && this.error) {this.error="";this.notify();}
      return saved;
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
  let selectedEdge = null;
  let nodeMenu = null;
  let activePanel = null;
  let outputPanelId = null;
  let panelCanvasId = null;
  let nodeResizeObserver = null;
  let saveDialog = null;
  let parameterDialog = null;
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
    for (const element of root.querySelectorAll("[data-matching-node]")) {
      const node=current.doc.graph.nodes.find(item=>item.id===element.dataset.matchingNode);
      updateMarkup(element,matchingHtml(node));
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
    const recent=root.querySelector(".pc-recent-list");
    if(recent) updateMarkup(recent,recentCanvasHtml());
    const undo=root.querySelector('[data-action="undo"]');
    if(undo) undo.disabled=!current.undoStack.length;
    updateChoiceWidgets();updateSummary();renderPanels();
  }
  function recentCanvasHtml() {
    const items=recentCanvases(current.list);
    return `<p class="pc-recent-title">最近保存${options.loggedIn()?"":"在本机"} · 最多 10 个</p>${items.length
      ? items.map(item=>`<button type="button" role="menuitem" data-action="open-canvas" data-canvas-id="${esc(item.id)}" ${current.submission?"disabled":""} title="${esc(item.name||"未命名画布")}"><strong>${esc(item.name||"未命名画布")}</strong><small>${item.updatedAt?esc(runDate(item.updatedAt)):"已保存"}</small></button>`).join("")
      : '<p class="pc-recent-empty">暂无已保存的画布</p>'}`;
  }
  function closeRecentCanvases() {
    root?.querySelector(".pc-open-canvases")?.classList.remove("is-open");
    root?.querySelector('[data-action="open-canvases"]')?.setAttribute("aria-expanded","false");
  }
  function setRecentOpen(open) {
    root.querySelector(".pc-open-canvases")?.classList.toggle("is-open",open);
    root.querySelector('[data-action="open-canvases"]')?.setAttribute("aria-expanded",String(open));
  }
  function closeSaveDialog(restoreFocus=true) {
    if(!saveDialog) return;
    const {element}=saveDialog;
    saveDialog=null;
    element.close();element.remove();
    if(restoreFocus) root?.querySelector('[data-action="save"]')?.focus({preventScroll:true});
  }
  function openSaveDialog() {
    if(!current || current.closed || !root?.offsetWidth) return;
    if(parameterDialog) return;
    if(saveDialog) {saveDialog.element.querySelector('input')?.focus();return;}
    closeRecentCanvases();closeNodeMenu();
    const store=current,documentId=store.doc.id,element=document.createElement("dialog");
    const state={element,store,documentId,saving:false};
    saveDialog=state;
    element.className="pc-save-dialog";
    element.setAttribute("aria-labelledby","pc-save-title");
    element.innerHTML=`<form novalidate><h2 id="pc-save-title">保存工作流</h2>
      <label for="pc-workflow-name">工作流名称</label><input id="pc-workflow-name" name="workflowName" type="text" maxlength="100" autocomplete="off" placeholder="例如：封面画风对比" required>
      <p class="pc-save-error" role="alert" hidden></p><div class="pc-save-actions"><button type="button" data-save-cancel>取消</button><button type="submit" class="pc-save-confirm">保存</button></div></form>`;
    const input=element.querySelector("input"),error=element.querySelector("[role=alert]"),confirm=element.querySelector('[type=submit]'),cancel=element.querySelector('[data-save-cancel]');
    input.value=store.doc.name==="参数组合画布"?"":store.doc.name||"";
    const isCurrent=()=>saveDialog===state && current===store && !store.closed && store.doc.id===documentId;
    input.oninput=()=>{error.hidden=true;};
    cancel.onclick=()=>{if(!state.saving) closeSaveDialog();};
    element.oncancel=event=>{event.preventDefault();if(!state.saving) closeSaveDialog();};
    element.querySelector("form").onsubmit=async event=>{
      event.preventDefault();
      if(!isCurrent() || state.saving) return;
      const name=input.value.trim();
      if(!name || name.length>100) {error.textContent="请输入 1–100 个字符的工作流名称";error.hidden=false;input.focus();return;}
      state.saving=true;confirm.disabled=true;cancel.disabled=true;input.disabled=true;confirm.textContent="保存中…";error.hidden=true;
      try {
        const saved=await store.saveNamed(name);
        if(!isCurrent()) return;
        if(saved) {closeSaveDialog();return;}
        error.textContent=store.error||"保存失败，请重试。当前草稿已保留。";error.hidden=false;
      } catch(failure) {
        if(isCurrent()) {error.textContent=failure.message||"保存失败，请重试";error.hidden=false;}
      } finally {
        if(isCurrent()) {state.saving=false;confirm.disabled=false;cancel.disabled=false;input.disabled=false;confirm.textContent="重试保存";input.focus();}
      }
    };
    document.body.appendChild(element);element.showModal();input.focus();input.select();
  }
  function parameterValue(node,value,index) {
    const id=esc(node.id),field=node.parameter,base=`data-node="${id}" data-parameter="${esc(field)}" data-value="${index}"`;
    if(field==="refImages") return `<button type="button" ${base} data-action="refs">选择一组参考图（${value.length}/6）</button><div class="pc-references">${value.map(url=>`<img src="${esc(url)}" alt="已选参考图" loading="lazy">`).join("")}</div>`;
    if(field==="prompt") return `<textarea aria-label="主题候选 ${index+1}" placeholder="描述想画的内容，例如雨后森林中的小屋" ${base}>${esc(value)}</textarea>`;
    if(field==="ratio") return `<select aria-label="比例候选 ${index+1}" ${base}>${ratios.map(r=>`<option ${r===value?"selected":""}>${r}</option>`).join("")}</select>`;
    if(field==="mode") return `<div class="pc-option-pills" role="group" aria-label="创作模式候选 ${index+1}">${creationModes.map(item=>`<button type="button" data-action="choose-single" ${base} data-option="${item.value}" aria-pressed="${value===item.value}">${item.label}</button>`).join("")}</div>`;
    if(field==="style1") return resourceValue(node,value,index,"style1")+resourceValue(node,value,index,"style2");
    if(field==="layout") return resourceValue(node,value,index,"layout");
    if(["colors","tones","moods","whitespace"].includes(field)) return choiceValue(node,value,index);
    return `<input aria-label="${labels[field]||field}候选 ${index+1}" ${base} ${field==="layout"?'list="pc-layout-codes"':''} placeholder="${["colors","tones","moods"].includes(field)?"同一方案中的值用逗号分隔":"填写参数值"}" value="${esc(Array.isArray(value)?value.join("，"):value)}">`;
  }
  function presetChoices(field) {return choiceOptions(field,options.parameterChoices?.(field)||[]);}
  function selectedPresetHtml(field,value) {
    const values=Array.isArray(value)?value:[value];
    return presetChoices(field).filter(item=>values.includes(item.value)&&item.value).map(item=>`<span class="pc-selected-preset">${item.image?`<img src="${esc(item.image)}" alt="">`:""}<span>${esc(item.label)}</span></span>`).join("");
  }
  function choiceValue(node,value,index) {
    const field=node.parameter,base=`data-node="${esc(node.id)}" data-parameter="${field}" data-value="${index}"`,choices=presetChoices(field),known=new Set(choices.map(item=>item.value));
    const custom=field==="whitespace"?(known.has(value)?"":value):(Array.isArray(value)?value:[]).filter(item=>!known.has(item)).join("，");
    return `<div class="pc-choice-widget" data-choice-widget ${base}>
      ${field==="whitespace"?`<div class="pc-option-pills" role="group" aria-label="留白预设">${choices.map(item=>`<button type="button" data-action="choose-single" ${base} data-option="${esc(item.value)}" aria-pressed="${value===item.value}">${esc(item.label)}</button>`).join("")}</div>`
        :`<button type="button" data-action="choose-parameters" ${base} aria-haspopup="dialog">选择${labels[field]}</button><div class="pc-selected-presets">${selectedPresetHtml(field,value)}</div>`}
      <label>自定义${labels[field]}<input ${base} data-custom-choice aria-label="自定义${labels[field]}候选 ${index+1}" placeholder="${field==="whitespace"?"也可填写具体留白要求":"也可填写其他内容，多项用逗号分隔"}" value="${esc(custom)}"></label>
    </div>`;
  }
  function updateChoiceWidgets() {
    for(const element of root?.querySelectorAll('[data-choice-widget]')||[]) {
      const node=current.doc.graph.nodes.find(item=>item.id===element.dataset.node),field=element.dataset.parameter;
      const value=parameterField(node,field)?.values?.[Number(element.dataset.value)];
      const selected=element.querySelector('.pc-selected-presets');if(selected) selected.innerHTML=selectedPresetHtml(field,value);
      element.querySelectorAll('[data-action="choose-single"]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.option===value)));
    }
  }
  function closeParameterDialog(restoreFocus=true) {
    if(!parameterDialog) return;
    const {element,nodeId,field,index}=parameterDialog;parameterDialog=null;element.close();element.remove();
    if(restoreFocus) [...root?.querySelectorAll('[data-action="choose-parameters"]')||[]].find(button=>button.dataset.node===nodeId&&button.dataset.parameter===field&&Number(button.dataset.value)===index)?.focus({preventScroll:true});
  }
  function openParameterDialog(node,field,index) {
    closeParameterDialog(false);closeRecentCanvases();
    const store=current,doc=store.doc,values=parameterField(node,field).values,previous=values[index],choices=presetChoices(field),known=new Set(choices.map(item=>item.value));
    const custom=(previous||[]).filter(value=>!known.has(value)),selected=new Set((previous||[]).filter(value=>known.has(value)));
    const element=document.createElement('dialog');element.className='pc-parameter-dialog';element.setAttribute('aria-labelledby','pc-parameter-title');
    parameterDialog={element,nodeId:node.id,field,index,documentId:doc.id};
    const isCurrent=()=>current===store&&!store.closed&&store.doc===doc&&doc.graph.nodes.includes(node)&&parameterField(node,field).values===values&&values[index]===previous;
    element.innerHTML=`<form><h2 id="pc-parameter-title">选择${labels[field]}</h2><p>同一方案可以多选。要分别比较不同方案，请添加候选。</p><input type="search" aria-label="搜索${labels[field]}" placeholder="搜索名称或编号"><div class="pc-parameter-grid-picker"></div><p class="pc-choice-error" role="alert" hidden></p><div class="pc-picker-actions"><button type="button" data-clear-presets>清空预设</button><span></span><button type="button" data-cancel-presets>取消</button><button type="submit" class="pc-picker-confirm">应用所选</button></div></form>`;
    const grid=element.querySelector('.pc-parameter-grid-picker'),search=element.querySelector('[type=search]'),error=element.querySelector('[role=alert]');
    const render=()=>{
      const query=search.value.trim().toLowerCase();
      grid.innerHTML=choices.filter(item=>(item.value+' '+item.label).toLowerCase().includes(query)).map(item=>`<button type="button" data-preset-value="${esc(item.value)}" aria-pressed="${selected.has(item.value)}">${item.image?`<img src="${esc(item.image)}" alt="" loading="lazy">`:""}<strong>${esc(item.label)}</strong>${item.value!==item.label?`<small>${esc(item.value)}</small>`:""}</button>`).join('')||'<p>暂无匹配预设，仍可在节点中填写自定义内容。</p>';
      element.querySelector('.pc-picker-confirm').textContent=selected.size?`应用所选（${selected.size}）`:'应用所选';
    };
    search.oninput=render;
    grid.onclick=event=>{const button=event.target.closest('[data-preset-value]');if(!button) return;const value=button.dataset.presetValue;selected.has(value)?selected.delete(value):selected.add(value);error.hidden=true;render();[...grid.querySelectorAll('[data-preset-value]')].find(item=>item.dataset.presetValue===value)?.focus({preventScroll:true});};
    element.querySelector('[data-clear-presets]').onclick=()=>{selected.clear();render();};
    element.querySelector('[data-cancel-presets]').onclick=()=>closeParameterDialog();
    element.oncancel=event=>{event.preventDefault();closeParameterDialog();};
    element.querySelector('form').onsubmit=event=>{
      event.preventDefault();if(!isCurrent()) {closeParameterDialog();return;}
      const result=[...selected,...custom];
      if(result.length>10) {error.textContent='同一方案最多包含 10 项，请减少选择。';error.hidden=false;return;}
      values[index]=result;closeParameterDialog(false);store.edit(true);
      [...root.querySelectorAll('[data-action="choose-parameters"]')].find(button=>button.dataset.node===node.id&&button.dataset.parameter===field&&Number(button.dataset.value)===index)?.focus({preventScroll:true});
    };
    document.body.appendChild(element);render();element.showModal();search.focus();
  }
  function resourceValue(node,value,index,field) {
    const code=resourceCode(value,field),kind=field==="layout"?"layout":"style";
    const resource=(options.resources?.(kind)||[]).find(item=>(item.id||item.code)===code);
    const label=field==="style1"?"主画风":field==="style2"?"融合副画风":"图型";
    const name=resource?.name_zh||resource?.name||resource?.title||(code?"资源信息暂不可用":field==="style2"?"可选，搭配双画风":"点击图片选择");
    const image=resource?.image||"",base=`data-node="${esc(node.id)}" data-parameter="${esc(node.parameter)}" data-value="${index}" data-field="${field}"`;
    const disabled=field==="style2"&&!resourceCode(value,"style1");
    return `<div class="pc-resource-control"><button type="button" class="pc-resource-picker ${code?"is-selected":""}" data-action="resource" ${base} aria-label="选择${label}候选 ${index+1}${code?`：${esc(code)} ${esc(name)}`:""}" ${disabled?"disabled":""}>
      <span class="pc-resource-thumb">${image?`<img src="${esc(image)}" alt="${esc(code)} ${esc(name)}"${node.grouped?"":" loading=\"lazy\""}>`:'<span aria-hidden="true">＋</span>'}</span>
      <span class="pc-resource-info"><small>${label}${code?` · ${esc(code)}`:""}</small><strong>${esc(name)}</strong><span>${disabled?"先选择主画风":code?"点击更换":"按编号、名称或图片挑选"}</span></span></button>
      ${code?`<div class="pc-resource-actions">${image?`<button type="button" data-action="zoom-resource" ${base} aria-label="放大${label}候选 ${index+1}">放大</button>`:""}<button type="button" data-action="clear-resource" ${base} aria-label="清空${label}候选 ${index+1}">清空</button></div>`:""}</div>`;
  }
  function candidatesHtml(node) {
    const field=node.parameter;
    const label=labels[field];
    const base=`data-node="${esc(node.id)}" data-parameter="${esc(field)}"`;
    return node.values.map((value,i)=>`<div class="pc-candidate">
      <div class="pc-candidate-heading"><span>${esc(label)} ${i+1}</span><button type="button" data-action="remove-value" ${base} data-value="${i}" aria-label="移除${esc(label)} ${i+1}">移除</button></div>
      ${parameterValue(node,value,i)}</div>`).join("") +
      `<button type="button" class="pc-add-candidate" data-action="add-value" ${base}>＋ 添加${esc(label)}</button>`;
  }

  let activeFields = new Map();
  const touchNodes = new Set();
  function parameterGroupHtml(node,isGuided=false) {
    const fields = fieldList(node);
    const selected = fields.find(item=>item.parameter===activeFields.get(node.id)) || fields[0];
    const nav = fields.map(item=>{
      const field = item.parameter;
      return `<button type="button" data-action="edit-field" data-node="${esc(node.id)}" data-parameter="${field}" aria-pressed="${field===selected?.parameter}">${labels[field]}${item.values.length > 1 ? ` <small>${item.values.length}</small>` : ""}</button>`;
    }).join("");
    const available = Object.keys(labels).filter(field=>field!=="style2" && !Object.hasOwn(node.fields,field));
    const more = available.length ? `<details class="pc-field-menu"><summary>＋ 参数</summary><div>${available.map(field=>`<button type="button" data-action="add-field" data-node="${esc(node.id)}" data-parameter="${field}">${labels[field]}</button>`).join("")}</div></details>` : "";
    return `<div class="pc-field-tabs" aria-label="要编辑的出图参数">${nav}${more}</div>
      ${selected ? `<div class="pc-field-editor" data-field-editor="${selected.parameter}">${candidatesHtml({...selected,grouped:true})}
        ${fields.length > 1 ? `<button type="button" class="pc-remove-field" data-action="remove-field" data-node="${esc(node.id)}" data-parameter="${selected.parameter}">移除此参数</button>` : ""}</div>` : ""}
      ${isGuided?"":`<div class="pc-matching-preview" data-matching-node="${esc(node.id)}"></div>`}`;
  }

  function nodeHtml(node,index,isGuided=false) {
    const graph = current.doc.graph;
    const incoming = graph.edges.filter(edge => edge.to === node.id);
    const name = nodeName(node);
    const ports = isGuided ? "" : [
      !isParameter(node) ? portButton(node, "in", incoming.length > 0) : "",
      node.type !== "output" ? portButton(node, "out", graph.edges.some(edge => edge.from === node.id)) : ""
    ].join("");
    return `<section class="pc-node ${isGuided?"pc-parameter":""} ${node.type==="parameters"?"pc-parameter-group":""}${touchNodes.has(node.id)?" is-touch-selected":""}" data-card="${esc(node.id)}" ${isGuided?"":`style="left:${Number(node.x??32)}px;top:${Number(node.y??32)}px"`}>
      ${ports}
      <header ${isGuided?"":`data-drag="${esc(node.id)}"`}><div><strong>${esc(name)}</strong>${isGuided&&node.values?`<span class="pc-node-count">${node.values.length} 个候选</span>`:""}</div><button type="button" data-action="remove-node" data-node="${esc(node.id)}" aria-label="移除${esc(name)}">×</button></header>
      <div class="pc-node-body">${node.type==="parameters"?parameterGroupHtml(node,isGuided):node.type==="parameter"?candidatesHtml(node):
        `<p>${node.type === "output" ? "在这里设置每种结果画几张。" : "将连进来的内容搭配后出图。"}</p>
        ${node.type === "combine" || incoming.length > 1 ? `<div class="pc-matching-preview" data-matching-node="${esc(node.id)}"></div>` : ""}
        ${node.type === "output" ? `<label>每组生成张数<input type="number" min="1" max="200" data-node="${esc(node.id)}" data-property="repeat" value="${node.repeat??1}"></label>` : ""}
        ${!incoming.length ? '<p>从其他节点的右侧圆点连到这里的左侧圆点</p>' : ""}`}</div>
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
    const focused = svg.contains(document.activeElement) ? document.activeElement.closest("[data-edge-from]") : null;
    const focusedEdge = focused && {from:focused.dataset.edgeFrom,to:focused.dataset.edgeTo};
    const points = new Map([...root.querySelectorAll("[data-port]")].map(port => [
      `${port.dataset.port}:${port.dataset.node}`, portPoint(port, svg.parentElement)
    ]));
    const preview = svg.querySelector(".pc-wire-preview")?.getAttribute("d") || "";
    if (selectedEdge && !current.doc.graph.edges.some(edge => edge.from === selectedEdge.from && edge.to === selectedEdge.to)) selectedEdge = null;
    svg.innerHTML = current.doc.graph.edges.map(edge => {
      const from = points.get(`out:${edge.from}`);
      const to = points.get(`in:${edge.to}`);
      const selected = selectedEdge?.from === edge.from && selectedEdge.to === edge.to;
      const source = current.doc.graph.nodes.find(node => node.id === edge.from);
      const target = current.doc.graph.nodes.find(node => node.id === edge.to);
      return from && to ? `<g class="pc-wire${selected ? " is-selected" : ""}" data-edge-from="${esc(edge.from)}" data-edge-to="${esc(edge.to)}" tabindex="0" role="button" aria-pressed="${selected}" aria-label="${esc(nodeName(source))}到${esc(nodeName(target))}的连线，点击选中"><path class="pc-wire-line" d="${curve(from, to)}"/><path class="pc-wire-hit" d="${curve(from, to)}"/></g>` : "";
    }).join("") + `<path class="pc-wire-preview" d="${preview}"/>`;
    if (focusedEdge) [...svg.querySelectorAll("[data-edge-from]")]
      .find(edge => edge.dataset.edgeFrom === focusedEdge.from && edge.dataset.edgeTo === focusedEdge.to)?.focus({preventScroll:true});
    const actions = root.querySelector(".pc-edge-actions");
    if (actions) actions.hidden = !selectedEdge;
  }

  function clearEdgeSelection() {
    if (!selectedEdge) return;
    selectedEdge = null;
    drawEdges();
    wireHint();
  }

  function selectEdge(element) {
    clearWire();
    closeNodeMenu();
    selectedEdge = {from:element.dataset.edgeFrom,to:element.dataset.edgeTo};
    drawEdges();
    root.querySelector(".pc-scroll")?.focus({preventScroll:true});
    wireHint("连线已选中 · 点击删除连线，或按 Delete / Backspace · Esc 取消");
  }

  function deleteSelectedEdge() {
    if (!selectedEdge) return;
    const {from,to} = selectedEdge, graph = current.doc.graph;
    const edges = graph.edges.filter(edge => edge.from !== from || edge.to !== to);
    if (edges.length === graph.edges.length) {clearEdgeSelection();return;}
    selectedEdge = null;
    graph.edges = edges;
    current.edit(true);
    root.querySelector(".pc-scroll")?.focus({preventScroll:true});
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
    const choices = port ? nodeMenuEntries.filter(item=>item[port.direction==="in"?"out":"in"]) : nodeMenuEntries;
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
    let showAdvanced = false;
    const renderChoices = () => {
      const query = input.value.trim().toLowerCase();
      const filtered = choices.filter(item => `${item.name} ${item.detail || ""} ${item.field || ""}`.toLowerCase().includes(query));
      const groups = ["生成流程", "高级节点", "单项参数"];
      const buttons = groups.map(group => {
        if (!query && !showAdvanced && group !== "生成流程") return "";
        const items = filtered.filter(item => item.group === group);
        if (!items.length) return "";
        return `<p>${group}</p>${items.map(item => `<button type="button" data-action="create-node" data-type="${item.type}" data-field="${item.field || ""}"><strong>${item.name}</strong>${item.detail ? `<small>${item.detail}</small>` : ""}</button>`).join("")}`;
      }).join("");
      const advanced = choices.some(item=>item.group!=="生成流程");
      list.innerHTML = (buttons || '<p>没有匹配的节点</p>') + (!query && advanced
        ? `<button type="button" data-action="advanced-nodes" aria-expanded="${showAdvanced}">${showAdvanced?"收起高级节点":"展开高级节点"}</button>` : "");
      const toggle = list.querySelector('[data-action="advanced-nodes"]');
      if (toggle) toggle.onclick = () => {
        showAdvanced = !showAdvanced;
        renderChoices();
        list.querySelector('[data-action="advanced-nodes"]')?.focus({preventScroll:true});
      };
      const bounds = element.getBoundingClientRect();
      element.style.left = `${Math.max(8, Math.min(x, window.innerWidth - bounds.width - 8))}px`;
      element.style.top = `${Math.max(8, Math.min(y, window.innerHeight - bounds.height - 8))}px`;
    };
    input.oninput = renderChoices;
    renderChoices();
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
    if (hint) hint.textContent = message || (selectedEdge ? "连线已选中 · 点击删除连线，或按 Delete / Backspace · Esc 取消" : "拖动空白处移动画布 · 点击连线可删除 · 右键或双击添加");
  }

  function clearWire() {
    selectedPort = null;
    root?.classList?.remove("is-wiring");
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
    clearEdgeSelection();
    clearWire();
    selectedPort = portRef(port);
    root.classList.add("is-wiring");
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
      else if (hit?.closest(".pc-board") === world.parentElement && !hit.closest(".pc-node")) openNodeMenu(next.clientX, next.clientY, start);
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
    if (!preview) return `<p role="status">${current.expanding?"正在重新核对出图内容与费用…":"参数已更新，请重新预览出图内容与费用。"}</p><button type="button" data-action="recheck-preview" ${current.expanding?"disabled":""}>重新预览</button>`;
    const q = selectedQuote(preview, current.selected.size);
    return `<p>已选 ${q.count} / ${preview.count} 张 · 免费 ${q.freeUsed} 张 · 预计 ${q.total} 积分</p>
      ${current.confirmation === "submit"
        ? `<div class="pc-confirm" role="group" aria-label="确认本次生成"><strong>确认生成 ${q.count} 张？</strong><p>积分上限 ${q.total}。关闭页面后仍会继续生成。</p><div><button type="button" data-action="cancel-confirm">返回检查</button><button type="button" class="pc-primary" data-action="confirm-submit">确认并开始生成</button></div></div>`
        : `<button type="button" class="pc-primary" data-action="submit" ${!q.count || !q.affordable ? "disabled" : ""}>生成选中的 ${q.count} 张</button>`}
      <button type="button" data-action="recheck-preview" ${current.expanding ? "disabled" : ""}>重新核对费用</button>
      ${!q.affordable ? '<p class="pc-next-action">积分不足，请减少勾选数量。</p>' : ""}
      <div class="pc-plan-list">${preview.items.map(item => `<label><input type="checkbox" data-select="${item.ordinal}" ${current.selected.has(item.ordinal) ? "checked" : ""}><span><b>${item.ordinal + 1}.</b> ${esc(String(item.spec?.prompt || "").slice(0,100))}<small>${esc([creationModes.find(mode=>mode.value===item.spec?.mode)?.label,item.spec?.style1,item.spec?.style2,item.spec?.layout,item.spec?.ratio].filter(Boolean).join(" · "))}</small></span></label>`).join("")}</div>`;
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
    const mode = element.contains(active) ? active.dataset.matchMode : null;
    const canvasId = element.contains(active) ? active.dataset.canvasId : null;
    element.innerHTML = markup;
    element.dataset.rendered = markup;
    element.scrollTop = scrollTop;
    if (ordinal != null) element.querySelector(`[data-select="${Number(ordinal)}"]`)?.focus({preventScroll:true});
    if (mode != null) element.querySelector(`[data-match-mode="${mode}"]`)?.focus({preventScroll:true});
    if (canvasId != null) [...element.querySelectorAll('[data-canvas-id]')].find(item=>item.dataset.canvasId===canvasId)?.focus({preventScroll:true});
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
    clearWire();
    nodeResizeObserver?.disconnect();
    const doc=current.doc,isGuided=guided(),flow=simpleFlow(doc.graph);
    const oldScroll=root.querySelector('.pc-guided-body')?.scrollTop||0;
    const oldCanvas=root.querySelector(".pc-scroll");
    const oldWorld=oldCanvas?.querySelector(".pc-world");
    const previousPan=oldWorld && oldCanvas.offsetWidth && oldCanvas.dataset.ready
      ? [oldCanvas.scrollLeft-oldWorld.offsetLeft,oldCanvas.scrollTop-oldWorld.offsetTop] : null;
    const changedDocument = panelCanvasId !== doc.id;
    if (changedDocument) {
      if(saveDialog && saveDialog.documentId!==doc.id) closeSaveDialog(false);
      if(parameterDialog && parameterDialog.documentId!==doc.id) closeParameterDialog(false);
      selectedEdge = null;
      panelCanvasId = doc.id;
      activePanel = current.submission ? "preview" : null;
      outputPanelId = null;
      activeFields = new Map();
      touchNodes.clear();
    }
    const nodes=doc.graph.nodes;
    const left=panMargin-Math.min(0,...nodes.map(node=>node.x||0),previousPan?.[0]||0);
    const top=panMargin-Math.min(0,...nodes.map(node=>node.y||0),previousPan?.[1]||0);
    const width=Math.max(1050,...nodes.map(node=>(node.x||0)+420),(previousPan?.[0]||0)+(oldCanvas?.clientWidth||0));
    const height=Math.max(760,...nodes.map(node=>(node.y||0)+500),(previousPan?.[1]||0)+(oldCanvas?.clientHeight||0));
    root.innerHTML = `<div class="pc-header">
      <div class="pc-document-actions" role="toolbar" aria-label="画布操作">
          <button type="button" data-action="new" ${current.submission?"disabled":""}>${sketchIcon("new")}<span>新建画布</span></button>
          <button type="button" data-action="save" aria-haspopup="dialog">${sketchIcon("save")}<span>保存画布</span></button>
          <button type="button" data-action="export">${sketchIcon("export")}<span>导出画布</span></button>
          <div class="pc-open-canvases"><button type="button" data-action="open-canvases" aria-haspopup="menu" aria-expanded="false" aria-controls="pc-recent-canvases">${sketchIcon("open")}<span>打开画布</span><span aria-hidden="true">⌄</span></button>
            <div id="pc-recent-canvases" class="pc-recent-list" role="menu" aria-label="最近保存的画布"></div></div>
      </div>
      <div class="pc-toolbar" aria-label="画布工具">
        <span data-pc-status role="status"></span>
        ${isGuided ? "" : '<button type="button" data-action="add-node-menu" aria-haspopup="dialog">＋ 添加节点</button>'}
        <button type="button" data-action="toggle-history" aria-expanded="false" aria-controls="pc-drawer">出图历史</button>
        <button type="button" class="pc-primary" data-action="preview">预览出图</button>
      </div></div>
      ${current.error?`<div class="pc-error" role="alert">${esc(current.error)}${current.conflict?'<button type="button" data-action="recover-copy">恢复为新画布</button>':""}</div>`:""}
      ${isGuided?'<nav class="pc-step-nav" aria-label="跳转画布步骤"><button type="button" data-action="step" data-step="parameters">1 准备参数</button><button type="button" data-action="step" data-step="matching">2 搭配方式</button><button type="button" data-action="step" data-step="checkout">3 预览出图</button></nav>':""}
      <div class="pc-workspace">
        <button type="button" class="pc-floating-undo" data-action="undo" aria-label="撤销" title="撤销 (Ctrl+Z)" ${current.undoStack.length?"":"disabled"}>${sketchIcon("undo")}</button>
        ${isGuided ? guidedHtml(flow) : `<div class="pc-scroll" tabindex="0" aria-label="参数节点画布" aria-describedby="pc-wire-hint"><div class="pc-board" style="--pc-left:${left}px;--pc-top:${top}px"><div class="pc-world" style="--pc-width:${width}px;--pc-height:${height}px"><svg class="pc-edges" aria-label="节点连线"></svg>${nodes.map((node,index)=>nodeHtml(node,index)).join("")}</div></div></div>
          <div class="pc-edge-actions" role="group" aria-label="已选中连线" hidden><span>已选中连线</span><button type="button" data-action="delete-edge">删除连线</button><button type="button" data-action="cancel-edge">取消</button></div>
          <p id="pc-wire-hint" data-wire-hint aria-live="polite"></p>`}
        <aside id="pc-drawer" class="pc-drawer" hidden><div class="pc-drawer-header"><h2></h2><button type="button" data-action="close-drawer" aria-label="收起面板">×</button></div><div class="pc-drawer-body"></div></aside>
      </div>`;

    const canvas=root.querySelector(".pc-scroll");
    if(canvas) {
      const world=canvas.querySelector(".pc-world");
      const start=doc.graph.nodes.length && changedDocument
        ? [Math.min(0,...doc.graph.nodes.map(node=>(node.x??32)-32)),Math.min(0,...doc.graph.nodes.map(node=>(node.y??32)-32))]
        : [0,0];
      const [left,top]=previousPan && !changedDocument ? previousPan : start;
      canvas.scrollLeft=world.offsetLeft+left;
      canvas.scrollTop=world.offsetTop+top;
      if (canvas.offsetWidth) canvas.dataset.ready="true";
    }
    status();wireHint();drawEdges();
    if (canvas && typeof ResizeObserver === "function") {
      nodeResizeObserver ||= new ResizeObserver(() => { if(root?.offsetWidth) drawEdges(); });
      for (const card of canvas.querySelectorAll("[data-card]")) nodeResizeObserver.observe(card);
    }
    const body=root.querySelector('.pc-guided-body');if(body) body.scrollTop=oldScroll;
    bindRecentCanvases();
  }
  function guidedHtml(flow) {
    return `<div class="pc-guided-body"><main class="pc-parameters-area" aria-label="准备参数"><div class="pc-step-title"><span>1</span><div><h2>准备参数</h2><p>填写想画的内容，画风和比例都可添加多项。</p></div></div>
      <div class="pc-parameter-tools" aria-label="添加参数">${["prompt","style1","layout","ratio","refImages"].map(field=>`<button type="button" data-action="guided-add" data-field="${field}">${flow.parameters.some(n=>n.parameter===field)?"编辑":"＋"} ${labels[field]}</button>`).join("")}<details><summary>更多参数</summary><div>${Object.entries(labels).filter(([key])=>!["prompt","style1","style2","layout","ratio","refImages"].includes(key)).map(([key,label])=>`<button type="button" data-action="guided-add" data-field="${key}">${label}</button>`).join("")}</div></details></div>
      <div class="pc-parameter-grid">${flow.group.type==="parameters" ? nodeHtml(flow.group,0,true) : flow.parameters.map((node,index)=>nodeHtml(node,index,true)).join("")}</div></main>
      <aside class="pc-guide-sidebar"><section class="pc-matching" aria-label="这批怎么画"><div class="pc-step-title"><span>2</span><div><h2>这批怎么画</h2></div></div>
        <div class="pc-matching-preview" data-matching-node="${esc(flow.group.id)}"></div>
        <label class="pc-repeat-label">每组生成<input type="number" min="1" max="200" aria-label="每组生成张数" data-node="${esc(flow.output.id)}" data-property="repeat" value="${flow.output.repeat??1}">张</label>
      </section><section class="pc-checkout" aria-label="预览与出图"><div class="pc-step-title"><span>3</span><div><h2>预览与出图</h2><p>先核对张数与费用，再开始。</p></div></div><div data-live-summary aria-live="polite"></div><button type="button" class="pc-primary pc-preview-button" data-action="preview">预览出图</button><div class="pc-output-results" data-output-results data-output-node="${esc(flow.output.id)}"></div></section></aside></div>`;
  }
  function valueChanged(target) {
    const node=current.doc.graph.nodes.find(n=>n.id===target.dataset.node);
    if(!node) return;
    if(target.dataset.property) node[target.dataset.property]=target.dataset.property==="repeat"?Number(target.value):target.value;
    else if(target.dataset.value!=null) {
      const {parameter:field,values}=parameterField(node,target.dataset.parameter);
      const index=Number(target.dataset.value);
      values[index]=target.hasAttribute('data-custom-choice')&&field!=="whitespace"?customSelection(values[index],target.value,presetChoices(field))
        :["colors","tones","moods"].includes(field)?target.value.split(/[,，\n]/).map(v=>v.trim()).filter(Boolean):target.value;
    }
    current.edit(false,{group:`${target.dataset.node}:${target.dataset.parameter||target.dataset.property}:${target.dataset.value??""}`});
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
    if (panel) closeRecentCanvases();
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
    viewport.focus({preventScroll:true});
    const pointerId = event.pointerId;
    const {clientX, clientY} = event;
    let {scrollLeft, scrollTop} = viewport;
    const board=viewport.querySelector(".pc-board"),world=board.querySelector(".pc-world");
    const controller = new AbortController();
    const listener = {signal:controller.signal};
    let moving = false;
    cancelPointer = () => {
      controller.abort();
      if (viewport.hasPointerCapture(pointerId)) viewport.releasePointerCapture(pointerId);
      viewport.classList.remove("is-panning");
      cancelPointer = null;
    };
    global.addEventListener("pointermove", next => {
      if (next.pointerId !== pointerId) return;
      if (!moving && Math.hypot(clientX-next.clientX,clientY-next.clientY)<5) return;
      if (!moving) {
        moving=true;
        viewport.setPointerCapture(pointerId);
        viewport.classList.add("is-panning");
        clearWire();
        closeNodeMenu();
      }
      let left=scrollLeft+clientX-next.clientX,top=scrollTop+clientY-next.clientY;
      if (left < 32 && world.offsetLeft < 50640) {
        board.style.setProperty("--pc-left",`${world.offsetLeft+640}px`);
        scrollLeft+=640;left+=640;
      }
      if (top < 32 && world.offsetTop < 50640) {
        board.style.setProperty("--pc-top",`${world.offsetTop+640}px`);
        scrollTop+=640;top+=640;
      }
      if (left+viewport.clientWidth > viewport.scrollWidth-32 && world.offsetWidth < 50640)
        world.style.setProperty("--pc-width",`${world.offsetWidth+640}px`);
      if (top+viewport.clientHeight > viewport.scrollHeight-32 && world.offsetHeight < 50640)
        world.style.setProperty("--pc-height",`${world.offsetHeight+640}px`);
      viewport.scrollTo(left,top);
    }, listener);
    for (const name of ["pointerup","pointercancel","lostpointercapture"]) {
      global.addEventListener(name, next => {
        if (next.pointerId === pointerId) cancelPointer?.();
      }, listener);
    }
    if (event.button===1) event.preventDefault();
  }
  function bindRecentCanvases() {
    const recentWrap=root.querySelector(".pc-open-canvases");
    if(recentWrap) {
      recentWrap.onpointerenter=event=>{if(event.pointerType!=="touch") setRecentOpen(true);};
      recentWrap.onpointerleave=event=>{if(event.pointerType!=="touch" && !recentWrap.contains(document.activeElement)) setRecentOpen(false);};
      recentWrap.onfocusout=event=>{if(!recentWrap.contains(event.relatedTarget)) setRecentOpen(false);};
    }
  }
  function bind() {
    root.oninput=event=>{if(event.target.matches("input:not([type=checkbox]),textarea")) valueChanged(event.target);};
    root.onchange=event=>{
      const t=event.target;
      if(t.dataset.select!=null) {const n=Number(t.dataset.select);t.checked?current.selected.add(n):current.selected.delete(n);current.confirmation=null;renderPanels();return;}
      if(t.matches("select[data-node]")) valueChanged(t);
    };
    root.onclick=event=>{
      const edge=event.target.closest("[data-edge-from]");
      if(edge) {selectEdge(edge);return;}
      const button=event.target.closest("button[data-action]");if(!button) return;
      const action=button.dataset.action,node=current.doc.graph.nodes.find(n=>n.id===button.dataset.node),index=Number(button.dataset.value);
      if(action==="open-canvases") {setRecentOpen(event.pointerType==="touch"?!root.querySelector(".pc-open-canvases").classList.contains("is-open"):true);return;}
      if(action==="open-canvas") {closeRecentCanvases();return void busy(()=>current.open(button.dataset.canvasId));}
      if(action==="undo") {current.undo();root.querySelector('.pc-scroll')?.focus({preventScroll:true});return;}
      if(action==="delete-edge") {deleteSelectedEdge();return;}
      if(action==="cancel-edge") {clearEdgeSelection();root.querySelector(".pc-scroll")?.focus({preventScroll:true});return;}
      if(action==="toggle-history") {showPanel(activePanel==="history"?null:"history",null,false);return;}
      if(action==="close-drawer") {
        const trigger = activePanel==="history" ? root.querySelector('[data-action="toggle-history"]')
          : activePanel==="output" ? [...root.querySelectorAll('[data-action="open-output"]')].find(element=>element.dataset.node===outputPanelId)
          : root.querySelector('[data-action="preview"]');
        showPanel(null);trigger?.focus({preventScroll:true});return;
      }
      if(action==="choose-run") {void busy(()=>current.watch(button.dataset.run));return;}
      if(action==="locate-nodes") {
        closeRecentCanvases();
        root.querySelector("[data-card]")?.scrollIntoView({block:"center",inline:"center"});
        return;
      }
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
        const cards=[...root.querySelectorAll(".pc-node")];
        const board=root.querySelector(".pc-scroll").getBoundingClientRect();
        const origin=worldPosition(board.left+32,board.top+32);
        const bottom=Math.max(origin.y,...cards.filter(card=>card.offsetLeft<origin.x+420 &&
          card.offsetLeft+card.offsetWidth>origin.x && card.offsetTop<origin.y+440 &&
          card.offsetTop+card.offsetHeight>origin.y).map(card=>card.offsetTop+card.offsetHeight+40));
        openNodeMenu(bounds.left,bounds.bottom+6,null,{x:origin.x,y:bottom});
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
      if(action==="guided-add") {
        const group=simpleFlow(current.doc.graph)?.group;
        if(group?.type==="parameters") activeFields.set(group.id,button.dataset.field);
        const added=addGuidedParameter(current,button.dataset.field);
        if(group?.type==="parameters") render();
        focusParameter(added);return;
      }
      if(action==="match-mode") {node.mode=button.dataset.matchMode;current.edit();return;}
      if(action==="save") {openSaveDialog();return;}
      if(action==="more-canvases") return void busy(()=>current.loadMoreCanvases());
      if(action==="more-runs") return void busy(()=>current.loadMoreRuns());
      if(action==="new"||action==="recover-copy") {closeRecentCanvases();return void busy(()=>current.create(action==="recover-copy"));}
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
      if(action==="export") {
        closeRecentCanvases();
        const url=URL.createObjectURL(new Blob([JSON.stringify(current.doc,null,2)],{type:"application/json"}));
        const a=document.createElement("a");a.href=url;a.download="参数画布.json";
        document.body.appendChild(a);a.click();a.remove();
        setTimeout(()=>URL.revokeObjectURL(url),1000);return;
      }
      if(action==="edit-field" || action==="add-field") {
        const field=button.dataset.parameter;
        activeFields.set(node.id,field);
        if(action==="add-field") {addParameterField(node,field);current.edit(true);}
        else render();
        const card=[...root.querySelectorAll("[data-card]")].find(element=>element.dataset.card===node.id);
        card?.querySelector(`[data-action="edit-field"][data-parameter="${field}"]`)?.focus({preventScroll:true});
        return;
      }
      const fieldNode=parameterField(node,button.dataset.parameter);
      if(action==="choose-parameters") {openParameterDialog(node,fieldNode.parameter,index);return;}
      if(action==="choose-single") {fieldNode.values[index]=button.dataset.option;current.edit(true);return;}
      if(action==="refs") {
        const store=current,doc=store.doc,values=fieldNode.values,previous=values[index],parameter=fieldNode.parameter;
        options.pickReferences?.({currentRefs:previous,onConfirm:items=>{
          if(store.closed||store.doc!==doc||!doc.graph.nodes.includes(node)||parameterField(node,parameter).values!==values||values[index]!==previous) return;
          values[index]=items.map(item=>item.image).filter(Boolean);store.edit(true);
        }});
        return;
      }
      if(action==="resource"||action==="clear-resource") {
        const field=button.dataset.field;
        pickResourceCandidate(current,node,index,field,settings=>action==="clear-resource"?settings.onPick(""):options.pickResource?.(settings),fieldNode.parameter);return;
      }
      if(action==="zoom-resource") {
        const field=button.dataset.field,code=resourceCode(fieldNode.values[index],field);
        const resource=(options.resources?.(field==="layout"?"layout":"style")||[]).find(item=>(item.id||item.code)===code);
        if(resource?.image) options.openImage?.(resource.image,`${code} ${resource.name_zh||resource.name||""}`);return;
      }
      if(action==="remove-node") {current.doc.graph.nodes=current.doc.graph.nodes.filter(n=>n!==node);current.doc.graph.edges=current.doc.graph.edges.filter(e=>e.from!==node.id&&e.to!==node.id);}
      else if(action==="remove-field") removeParameterField(node,fieldNode.parameter);
      else if(action==="remove-value") {if(!removeCandidate(node,fieldNode.parameter,index)) return;}
      else if(action==="add-value") {
        if(fieldNode.values.length>=200) {wireHint("每个参数最多添加 200 个候选");return;}
        fieldNode.values.push(initialCandidate(fieldNode.parameter));
      }
      else if(action==="group-parameters") {
        const graph=current.doc.graph;
        if(!groupExistingParameters(graph,simpleFlow(graph))) return;
      }
      else if(action==="arrange") arrangeNodes(current.doc.graph.nodes,new Map(
        Array.from(root.querySelectorAll("[data-card]")).map(card=>[card.dataset.card,{width:card.offsetWidth,height:card.offsetHeight}])
      ));
      else return;
      current.edit(true);
      if(action==="add-value") focusParameter(node,true);
    };
    root.oncontextmenu=root.ondblclick=event=>{
      if(!event.target.closest(".pc-board") || event.target.closest(".pc-node,[data-edge-from]")) return;
      event.preventDefault();
      openNodeMenu(event.clientX,event.clientY);
    };
    root.onkeydown=event=>{
      const editing=event.target.closest("input,textarea,select,[contenteditable]");
      if(!editing && (event.ctrlKey||event.metaKey) && !event.altKey && ["z","y"].includes(event.key.toLowerCase())) {
        event.preventDefault();event.stopPropagation();current.undo(event.key.toLowerCase()==="y"||event.shiftKey);root.querySelector('.pc-scroll')?.focus({preventScroll:true});return;
      }
      const menu=event.target.closest(".pc-open-canvases");
      if(menu && ["ArrowDown","ArrowUp","ArrowLeft","ArrowRight","Escape"].includes(event.key)) {
        event.preventDefault();event.stopPropagation();
        const open=root.querySelector('[data-action="open-canvases"]');
        if(event.key==="Escape") {closeRecentCanvases();open.focus();return;}
        const inRecent=Boolean(event.target.closest(".pc-recent-list"));
        if((event.key==="ArrowLeft"||event.key==="ArrowRight") && (event.target===open||inRecent)) {
          if(inRecent) {setRecentOpen(false);open.focus();}
          else {setRecentOpen(true);root.querySelector('.pc-recent-list button')?.focus();}
          return;
        }
        if(!["ArrowUp","ArrowDown"].includes(event.key)) return;
        setRecentOpen(true);
        const buttons=[...root.querySelectorAll('.pc-recent-list button:not(:disabled)')];
        const index=buttons.indexOf(event.target),next=index<0?(event.key==="ArrowDown"?0:buttons.length-1):index+(event.key==="ArrowDown"?1:-1);
        (buttons[(next+buttons.length)%buttons.length]||open).focus();
        return;
      }
      if(!editing && (event.key==="Enter" || event.key===" ") && event.target.closest("[data-edge-from]")) {
        event.preventDefault();selectEdge(event.target.closest("[data-edge-from]"));return;
      }
      if(!editing && selectedEdge && (event.key==="Delete" || event.key==="Backspace")) {
        event.preventDefault();deleteSelectedEdge();return;
      }
      if(event.key==="Escape") {
        if(selectedPort||cancelPointer) {cancelPointer?.();clearWire();}
        else if(selectedEdge) clearEdgeSelection();
        else if(activePanel) root.querySelector('[data-action="close-drawer"]')?.click();
      }
    };
    root.onpointerdown=event=>{
      if (!event.target.closest(".pc-open-canvases")) closeRecentCanvases();
      const viewport=event.target.closest(".pc-scroll");
      if(viewport && event.button===1) {beginPan(event,viewport);return;}
      if(event.button!==0 || !event.isPrimary) return;
      suppressPortClick=false;
      const port=event.target.closest("[data-port]");
      if(port) {beginWire(event,port);return;}
      if(event.target.closest("[data-edge-from],.pc-edge-actions")) return;
      clearEdgeSelection();
      const cardTarget=event.target.closest("[data-card]");
      if (event.pointerType==="touch" && viewport) {
        if (cardTarget) {
          touchNodes.add(cardTarget.dataset.card);
          cardTarget.classList.add("is-touch-selected");
        } else if (!selectedPort) {
          touchNodes.clear();
          root.querySelectorAll(".is-touch-selected").forEach(card=>card.classList.remove("is-touch-selected"));
        }
      }
      if(viewport && (spaceHeld || (!cardTarget && event.target.closest(".pc-board") && event.pointerType!=="touch"))) {
        clearWire();beginPan(event,viewport);return;
      }
      if(event.target.closest(".pc-board") && event.pointerType!=="touch") clearWire();
      const header=event.target.closest("[data-drag]");if(!header||event.target.closest("button")) return;
      viewport.focus({preventScroll:true});
      const node=current.doc.graph.nodes.find(n=>n.id===header.dataset.drag),card=header.closest(".pc-node"),start={x:event.clientX,y:event.clientY,nx:Number(node.x)||0,ny:Number(node.y)||0};
      const pointerId=event.pointerId;
      const controller=new AbortController(),listener={signal:controller.signal};
      const world=card.parentElement;
      const syncPosition=()=>{
        card.style.left=node.x+"px";card.style.top=node.y+"px";
        world.style.setProperty("--pc-width",Math.max(world.offsetWidth,node.x+card.offsetWidth+32)+"px");
        world.style.setProperty("--pc-height",Math.max(world.offsetHeight,node.y+card.offsetHeight+32)+"px");
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
        node.x=coordinate(start.nx+e.clientX-start.x);
        node.y=coordinate(start.ny+e.clientY-start.y);
        syncPosition();
      },listener);
      header.addEventListener("pointerup",e=>{
        if(e.pointerId!==pointerId) return;
        controller.abort();cancelPointer=null;
        if(node.x!==start.nx||node.y!==start.ny) {
          const board=world.parentElement;
          const dx=Math.max(0,panMargin-node.x-world.offsetLeft);
          const dy=Math.max(0,panMargin-node.y-world.offsetTop);
          board.style.setProperty("--pc-left",`${world.offsetLeft+dx}px`);
          board.style.setProperty("--pc-top",`${world.offsetTop+dy}px`);
          viewport.scrollLeft+=dx;
          viewport.scrollTop+=dy;
          current.edit();
        }
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
    closeParameterDialog(false);
    closeSaveDialog(false);
    closeRecentCanvases();
    clearEdgeSelection();
    closeNodeMenu();
    cancelPointer?.();
    clearWire();
    touchNodes.clear();
    root?.querySelectorAll(".is-touch-selected").forEach(card=>card.classList.remove("is-touch-selected"));
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
  global.HandrawParameterCanvas={mount,dismissInteractions,saveCurrent:openSaveDialog,openRun:async id=>{
    const store=current;
    if(!store) return;
    await store.openRun(id);
    if(current===store && store.run?.id===id) {
      if(root.querySelector('[data-action="open-output"]')) focusRunOutput();
      else showPanel("output");
    }
  },importDocument:document=>current?.importDocument(document),reset:()=>{dismissInteractions();nodeResizeObserver?.disconnect();current?.close();current=null;root=null;panelCanvasId=null;}};
  if(global.__HANDRAW_TESTING__) global.HandrawParameterCanvas.testing={CanvasStore,blank,selectedQuote,arrangeNodes,pickResourceCandidate,simpleFlow,combinationSummary,addGuidedParameter,connectionError,addCanvasNode,outputItems,groupExistingParameters,matchingPreview,matchingSources,recentCanvases,removeCandidate,removeParameterField,repairEmptyCandidates,choiceOptions,customSelection};
})(window);
