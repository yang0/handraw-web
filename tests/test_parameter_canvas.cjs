"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),vm=require("node:vm"),fs=require("node:fs");
const context={window:{__HANDRAW_TESTING__:true},setTimeout,clearTimeout,console};
vm.createContext(context);vm.runInContext(fs.readFileSync("demo/assets/parameter-canvas.js","utf8"),context);
const {CanvasStore,selectedQuote,arrangeNodes,pickResourceCandidate,simpleFlow,combinationSummary,addGuidedParameter,connectionError,addCanvasNode,outputItems,groupExistingParameters,matchingPreview,matchingSources,recentCanvases,removeCandidate,removeParameterField,repairEmptyCandidates,choiceOptions,customSelection}=context.window.HandrawParameterCanvas.testing;
const storage=new Map();
function store(t,api,scope="user:canvas") {
  const instance=new CanvasStore({api,scope,loggedIn:()=>true,storage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)}});
  t.after(()=>instance.close());return instance;
}
function preview() {return {planHash:"hash",quote:{freeRemaining:1,unitPrice:2,balance:10},items:[{ordinal:0,spec:{prompt:"A"}},{ordinal:1,spec:{prompt:"B"}}]};}
function run(id="run") {return {id,status:"success",items:[],count:0,retryQuote:{total:0,unitPrice:2},spentCredits:0,maxCredits:0};}
function legacyGraph() {
  return {nodes:[
    {id:"theme",type:"parameter",parameter:"prompt",values:[""],x:32,y:32},
    {id:"style",type:"parameter",parameter:"style1",values:["FA-001"],x:32,y:340},
    {id:"combine",type:"combine",mode:"cartesian",x:370,y:135},
    {id:"output",type:"output",mode:"cartesian",repeat:1,x:700,y:135}
  ],edges:[{from:"theme",to:"combine"},{from:"style",to:"combine"},{from:"combine",to:"output"}]};
}

test("guided combinations explain cross products, sequential pairs and shared singleton values",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  s.doc.graph=legacyGraph();
  const flow=simpleFlow(s.doc.graph);flow.parameters[0].values=["Forest","Ocean"];flow.parameters[1].values=["FA-001","FA-002","FA-003"];
  const ratio=addGuidedParameter(s,"ratio");assert.equal(ratio.values[0],"3:4");
  assert.ok(ratio.y>flow.parameters[0].y,"New parameters get a separate position in the free view");
  assert.equal(s.doc.graph.edges.filter(e=>e.from===ratio.id&&e.to===flow.group.id).length,1);
  const count=s.doc.graph.nodes.length;assert.equal(addGuidedParameter(s,"ratio"),ratio);assert.equal(s.doc.graph.nodes.length,count);
  assert.equal(combinationSummary(s.doc.graph).count,6);
  flow.output.repeat=2;assert.equal(combinationSummary(s.doc.graph).count,12);
  flow.group.mode="zip";assert.match(combinationSummary(s.doc.graph).problem,/数量需相同/);
  flow.parameters[1].values.pop();assert.equal(combinationSummary(s.doc.graph).count,4);
  flow.parameters[1].values.pop();assert.equal(combinationSummary(s.doc.graph).count,4,"A single style is reused for both themes");
  flow.parameters[0].values[1]="";assert.match(combinationSummary(s.doc.graph).problem,/填写每个主题/);
  flow.parameters[0].values=["Filled"];flow.output.repeat=0;assert.match(combinationSummary(s.doc.graph).problem,/1–200/);
  flow.output.repeat=201;assert.match(combinationSummary(s.doc.graph).problem,/1–200/);
  flow.output.repeat=100;flow.group.mode="cartesian";flow.parameters[0].values=["A","B","C"];
  assert.match(combinationSummary(s.doc.graph).problem,/300 张/);assert.equal(combinationSummary(s.doc.graph).count,null);
});

test("complex or partially disconnected graphs cannot silently become a guided combination",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  s.doc.graph.nodes.push({id:"nested",type:"combine",mode:"zip"});
  const before=JSON.stringify(s.doc.graph);assert.equal(simpleFlow(s.doc.graph),null);
  assert.equal(addGuidedParameter(s,"layout"),null);assert.equal(JSON.stringify(s.doc.graph),before);
  s.doc.graph.nodes.pop();s.doc.graph.edges.pop();assert.equal(simpleFlow(s.doc.graph),null);
});

test("editing invalidates the fee confirmation and preview while preserving accepted runs",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  s.preview=preview();s.confirmation="submit";s.run=run("accepted");s.selected=new Set([0]);
  s.edit();assert.equal(s.confirmation,null);assert.equal(s.preview,null);assert.equal(s.selected.size,0);assert.equal(s.run.id,"accepted");
});

test("the optional guided view keeps the three steps and automatic parameter inclusion",t=>{
  const canvas=context.window.HandrawParameterCanvas,doc=canvas.testing.blank();
  context.window.localStorage={getItem:()=>JSON.stringify({doc,view:"guided"}),setItem(){}};
  const root={innerHTML:"",querySelector:()=>null,querySelectorAll:()=>[]};
  canvas.mount(root,{scope:"guided-render",loggedIn:()=>false,resources:()=>[]});
  t.after(()=>{canvas.reset();delete context.window.localStorage;});
  for(const text of ["准备参数","这批怎么画","预览与出图"]) assert.ok(root.innerHTML.includes(text));
  assert.ok(root.innerHTML.includes('data-action="guided-add"'));
  assert.ok(!root.innerHTML.includes('class="pc-world"'));
  assert.ok(!root.innerHTML.includes('data-drag='));
});

test("matching examples follow field order, sequential pairing, fixed values and repeats",()=>{
  const inputs=[
    {name:"主题",unit:"个",count:2,samples:[{prompt:"森林"},{prompt:"公园"}]},
    {name:"画风",unit:"种",count:2,samples:[{style1:"FA-001"},{style1:"FA-002"}]},
    {name:"比例",count:1,samples:[{ratio:"16:9"}]}
  ];
  const cross=matchingPreview(inputs,"cartesian"),pairs=matchingPreview(inputs,"zip");
  assert.equal(cross.count,4);
  assert.deepEqual(Array.from(cross.samples,row=>row.prompt+row.style1),["森林FA-001","森林FA-002","公园FA-001","公园FA-002"]);
  assert.deepEqual(Array.from(pairs.samples,row=>row.prompt+row.style1),["森林FA-001","公园FA-002"]);
  assert.ok(cross.samples.every(row=>row.ratio==="16:9"));
  assert.equal(matchingPreview(inputs,"zip",2).samples[1].prompt,"森林");
  inputs[1].count=3;inputs[1].samples.push({style1:"FA-003"});
  assert.match(matchingPreview(inputs,"zip").error,/2个主题、3种画风/);
  assert.match(matchingPreview(inputs,"cartesian",40).error,/200/);
});

test("downstream examples retain upstream rows beyond the four displayed samples",()=>{
  const graph={nodes:[
    {id:"themes",type:"parameter",parameter:"prompt",values:["A","B","C","D","E"]},
    {id:"styles",type:"parameter",parameter:"style1",values:["1","2","3","4","5"]},
    {id:"set",type:"combine",mode:"zip"},
    {id:"out",type:"output"}
  ],edges:[{from:"themes",to:"set"},{from:"styles",to:"set"},{from:"set",to:"out"}]};
  const info=matchingSources(graph,graph.nodes[3]);
  assert.equal(info.sources[0].samples[4].prompt,"E");
  assert.equal(info.sources[0].samples[4].style1,"5");
  graph.edges.push({from:"set",to:"set"});
  assert.match(matchingSources(graph,graph.nodes[3]).error,/循环/);
});

test("node view opens by default and exposes one anchor for each usable direction",t=>{
  const canvas=context.window.HandrawParameterCanvas,doc=canvas.testing.blank();
  context.window.localStorage={getItem:()=>JSON.stringify({doc}),setItem(){}};
  const root={innerHTML:"",querySelector:()=>null,querySelectorAll:()=>[]};
  canvas.mount(root,{scope:"node-render",loggedIn:()=>false,resources:()=>[]});
  t.after(()=>{canvas.reset();delete context.window.localStorage;});
  assert.deepEqual([...root.innerHTML.matchAll(/data-port="(in|out)" data-node="([^"]+)"/g)].map(m=>m.slice(1)),[
    ["out","params"],["in","output"]
  ]);
  for(const field of ["prompt","style1","layout","ratio"]) assert.ok(root.innerHTML.includes(`data-parameter="${field}"`));
  assert.match(root.innerHTML,/data-action="add-node-menu"/);
  assert.match(root.innerHTML,/class="pc-drawer" hidden/);
});

test("results follow frozen output IDs, with safe fallback for unlinked and deleted nodes",()=>{
  const run={canvasId:"canvas",items:[
    {ordinal:0,outputNodeId:"second"},{ordinal:1,outputNodeId:"first"},
    {ordinal:2,outputNodeId:"removed"},{ordinal:3}
  ]};
  const groups=outputItems(run,["first","second"],"canvas");
  assert.deepEqual(Array.from(groups.byNode.get("first"),item=>item.ordinal),[1]);
  assert.deepEqual(Array.from(groups.byNode.get("second"),item=>item.ordinal),[0]);
  assert.deepEqual(Array.from(groups.orphaned,item=>item.ordinal),[2,3]);
  assert.deepEqual(Array.from(outputItems(run,["first"],"canvas").byNode.get("first"),item=>item.ordinal),[1,3]);
  assert.equal(outputItems(run,["first","second"],"another").orphaned.length,4);
});

test("wiring accepts nested combinations and rejects duplicates, cycles and terminal outputs",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  s.doc.graph=legacyGraph();
  const graph=s.doc.graph;
  const nested=addCanvasNode(graph,"combine","",{x:400,y:480});
  assert.equal(connectionError(graph,"combine",nested.id),"");
  graph.edges.push({from:"combine",to:nested.id});
  assert.equal(connectionError(graph,nested.id,"output"),"");
  assert.match(connectionError(graph,nested.id,"combine"),/循环/);
  assert.match(connectionError(graph,"theme","combine"),/已经连接/);
  assert.match(connectionError(graph,"output",nested.id),/右侧输出/);
  assert.match(connectionError(graph,nested.id,"style"),/右侧输出/);
  assert.equal(graph.edges.length,4);
});

test("grouping old parameters preserves edge order, output identity, and combination settings",()=>{
  const graph=legacyGraph(),flow=simpleFlow(graph);
  [graph.edges[0],graph.edges[1]]=[graph.edges[1],graph.edges[0]];
  flow.group.mode="zip";
  flow.output.repeat=3;
  assert.equal(groupExistingParameters(graph,flow),true);
  assert.equal(graph.nodes[1],flow.output);
  assert.equal(graph.nodes[0].mode,"zip");
  assert.deepEqual(Array.from(graph.nodes[0].fieldOrder),["style1","prompt"]);
  assert.equal(graph.nodes[0].fields.style1,flow.parameters[1].values);
  assert.equal(graph.edges[0].to,"output");
});

test("visual resource picks change only the chosen candidate and preserve atomic fusion pairs",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  const node=s.doc.graph.nodes[0],values=node.fields.style1=[{style1:"FA-001",style2:"FA-002"},"FA-003"];
  const other=JSON.stringify(s.doc.graph.nodes.filter(n=>n!==node));let picker;
  const choose=(field,code)=>{pickResourceCandidate(s,node,0,field,settings=>picker=settings,"style1");picker.onPick(code);};
  choose("style1","FA-004");assert.equal(values[0].style2,"FA-002");assert.equal(values[0].style1,"FA-004");
  choose("style2","");assert.equal(values[0],"FA-004");
  choose("style2","FA-005");choose("style1","");assert.equal(values[0],"");
  assert.equal(values[1],"FA-003");assert.equal(JSON.stringify(s.doc.graph.nodes.filter(n=>n!==node)),other);
  assert.equal(s.dirty,true);
});

test("cancelled or late visual picker results never modify another canvas, removed node or account",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  s.doc.graph=legacyGraph();
  let node=s.doc.graph.nodes.find(n=>n.id==="style"),picker;
  pickResourceCandidate(s,node,0,"style1",settings=>picker=settings);
  assert.equal(s.dirty,false,"Opening and cancelling a picker does not edit the document");
  s.doc={...s.doc,id:"another",graph:{nodes:[],edges:[]}};picker.onPick("FA-002");assert.equal(node.values[0],"FA-001");
  s.doc.graph.nodes=[node];pickResourceCandidate(s,node,0,"style1",settings=>picker=settings);
  s.doc.graph.nodes=[];picker.onPick("FA-003");assert.equal(node.values[0],"FA-001");
  s.doc.graph.nodes=[node];pickResourceCandidate(s,node,0,"style1",settings=>picker=settings);
  s.close();picker.onPick("FA-004");assert.equal(node.values[0],"FA-001");
});

test("canvas renders actual thumbnails and names for both fusion styles and layouts with empty states",t=>{
  const canvas=context.window.HandrawParameterCanvas,doc=canvas.testing.blank();
  doc.graph=legacyGraph();
  doc.graph.nodes.find(n=>n.id==="style").values=[{style1:"FA-001",style2:"FA-002"},"missing"];
  doc.graph.nodes.push({id:"layout",type:"parameter",parameter:"layout",values:["SC-001",""]});
  context.window.localStorage={getItem:()=>JSON.stringify({doc}),setItem(){}};
  const root={innerHTML:"",querySelector:()=>null,querySelectorAll:()=>[]};
  canvas.mount(root,{scope:"visual-render",loggedIn:()=>false,resources:kind=>kind==="style"
    ? [{id:"FA-001",name:"Primary drawing",image:"/primary.webp"},{id:"FA-002",name:"Second drawing",image:"/second.webp"}]
    : [{id:"SC-001",name:"Selected layout",image:"/layout.webp"}]});
  t.after(()=>{canvas.reset();delete context.window.localStorage;});
  for(const path of ["/primary.webp","/second.webp","/layout.webp"]) assert.ok(root.innerHTML.includes(`src="${path}"`));
  for(const name of ["Primary drawing","Second drawing","Selected layout"]) assert.ok(root.innerHTML.includes(name));
  assert.ok(root.innerHTML.includes("资源信息暂不可用"));assert.ok(root.innerHTML.includes("点击图片选择"));
  assert.ok(root.innerHTML.includes('aria-label="放大融合副画风候选 1"'));
  assert.ok(root.innerHTML.includes('aria-label="清空图型候选 1"'));
});

test("arranging tall candidate nodes preserves specs and keeps every pair separate",()=>{
  const nodes=Array.from({length:7},(_,n)=>({id:"n"+n,type:n%2?"output":"parameter",values:["keep"],x:0,y:0}));
  const sizes=new Map(nodes.map((node,n)=>[node.id,{width:n%2?252:276,height:[428,418,233,303,750,199,510][n]}]));
  const before=JSON.stringify(nodes.map(({x,y,...spec})=>spec));arrangeNodes(nodes,sizes);
  assert.equal(JSON.stringify(nodes.map(({x,y,...spec})=>spec)),before);
  for(let i=0;i<nodes.length;i++) for(let j=i+1;j<nodes.length;j++) {
    const a=nodes[i],b=nodes[j],as=sizes.get(a.id),bs=sizes.get(b.id);
    assert.ok(a.x+as.width<=b.x||b.x+bs.width<=a.x||a.y+as.height<=b.y||b.y+bs.height<=a.y,`${a.id} overlaps ${b.id}`);
  }
});

test("canvas saves serialize and include edits made while the first save is outstanding",async t=>{
  storage.clear();const writes=[];let release;
  const s=store(t,async(url,options)=>{writes.push(JSON.parse(JSON.stringify(options.body)));if(writes.length===1) await new Promise(resolve=>release=resolve);return {writeSeq:writes.length};});
  s.doc.graph.nodes[0].fields.prompt=["First"];s.edit();const saving=s.save();
  s.doc.graph.nodes[0].fields.prompt=["Second"];s.edit();const concurrent=s.save();
  release();assert.deepEqual(await Promise.all([saving,concurrent]),[true,true]);
  assert.equal(writes.length,2);assert.equal(writes[0].baseWriteSeq,0);assert.equal(writes[1].baseWriteSeq,1);
  assert.equal(writes[1].graph.nodes[0].fields.prompt[0],"Second");assert.equal(s.dirty,false);
});
test("explicit save persists a new untouched canvas once and repeated saves stay idempotent",async t=>{
  storage.clear();let writes=0;
  const s=store(t,async()=>{writes++;return {writeSeq:1};});
  assert.equal(s.dirty,false);assert.equal(await s.save(),true);assert.equal(writes,1);
  assert.equal(s.doc.writeSeq,1);assert.equal(s.list[0].id,s.doc.id);assert.ok(s.list[0].updatedAt);
  assert.equal(await s.save(),true);assert.equal(writes,1);
});
test("save conflict retains the local document and can be recovered as an explicit copy",async t=>{
  storage.clear();const s=store(t,async()=>{const error=new Error("changed elsewhere");error.status=409;error.code="canvas_conflict";throw error;});
  s.doc.graph.nodes[0].fields.prompt=["Local work"];s.edit();const old=s.doc.id;
  assert.equal(await s.save(),false);assert.equal(s.conflict,true);assert.equal(s.doc.graph.nodes[0].fields.prompt[0],"Local work");
  await s.create(true);assert.notEqual(s.doc.id,old);assert.equal(s.doc.writeSeq,0);assert.equal(s.conflict,false);
});
test("preview uses the saved document and never submits per-image generation requests",async t=>{
  storage.clear();const calls=[];const s=store(t,async(url,options)=>{calls.push(url);if(url.endsWith("/preview")) return preview();return {writeSeq:1};});
  s.doc.graph.nodes[0].fields.prompt=["Theme"];s.edit();await s.expand();
  assert.equal(calls.length,2);assert.equal(calls[0],"/api/studio/canvases");assert.ok(calls[1].endsWith("/preview"));
  assert.equal(s.selected.size,2);assert.equal(selectedQuote(s.preview,2).total,2);assert.ok(!calls.includes("/api/studio/generate"));
});
test("an unknown submission persists its exact idempotency key and survives page recreation",async t=>{
  storage.clear();let original;const first=store(t,async(url,options)=>{original=JSON.parse(JSON.stringify(options.body));throw new Error("connection lost");});
  first.doc.writeSeq=1;first.preview=preview();first.selected=new Set([1]);first.submitKey="same-command";
  await assert.rejects(first.submit(),/connection lost/);first.close();
  const calls=[];const recovered=store(t,async(url,options)=>{
    calls.push(url);
    if(url.endsWith("/runs") && options?.method==="POST") {assert.deepEqual(JSON.parse(JSON.stringify(options.body)),original);return {runId:"run"};}
    if(url.endsWith("/runs")) return {items:[]};
    return {run:run()};
  });
  assert.equal(recovered.submission.body.requestId,"same-command");await recovered.submit();
  assert.equal(recovered.submission,null);assert.equal(recovered.run.status,"success");assert.equal(calls.filter(url=>url.endsWith("/runs")).length,2);
});
test("a stale preview is discarded if the user edits during expansion",async t=>{
  storage.clear();let release;const s=store(t,async(url)=>url.endsWith("/preview")?new Promise(resolve=>release=()=>resolve(preview())):{writeSeq:1});
  s.doc.writeSeq=1;const expanding=s.expand();await new Promise(resolve=>setImmediate(resolve));
  s.doc.graph.nodes[0].fields.prompt=["Changed"];s.edit();release();await assert.rejects(expanding,/参数已变化/);assert.equal(s.preview,null);
});
test("account scope changes prevent late save responses from modifying the new account",async t=>{
  storage.clear();let release;const old=store(t,async()=>new Promise(resolve=>release=()=>resolve({writeSeq:8})),"user:first");
  old.edit();const saving=old.save();old.close();const fresh=store(t,async()=>({writeSeq:1}),"user:second");
  const id=fresh.doc.id;release();assert.equal(await saving,false);assert.equal(fresh.doc.id,id);assert.equal(fresh.doc.writeSeq,0);
});
test("stopping only targets pending items and retry replays an unknown command",async t=>{
  storage.clear();const calls=[];let retries=0;const s=store(t,async(url,options)=>{
    calls.push([url,options?.body]);if(url.endsWith("/retry")){retries++;if(retries===1) throw new Error("unknown response");return {ok:true};}
    return url.includes("/canvas-runs/")?{run:run()}:{ok:true};
  });
  s.run={...run(),id:"run",batchId:"batch",items:[{ordinal:0,status:"pending"},{ordinal:1,status:"generating"},{ordinal:2,status:"success"}]};
  s.runId="run";await s.stopPending();assert.deepEqual(Array.from(calls[0][1].positions),[0]);
  s.run={...run(),id:"run",retryQuote:{total:4,unitPrice:2},spentCredits:2,maxCredits:2};
  await assert.rejects(s.retry(),/unknown response/);await s.retry();const commands=calls.filter(([url])=>url.endsWith("/retry"));
  assert.equal(commands[0][1].requestId,commands[1][1].requestId);assert.equal(commands[1][1].maxCredits,6);
});

test("canvas and run lists load beyond their first windows without losing entries or retry positions",async t=>{
  storage.clear();const calls=[];let fail=true;
  const s=store(t,async url=>{
    calls.push(url);
    if(fail) {fail=false;throw new Error("temporary loss");}
    return {items:[{id:url.includes("/runs")?"older-run":"older-canvas"}],nextCursor:""};
  });
  s.list=[{id:"recent-canvas"}];s.listCursor="canvas-next";
  await assert.rejects(s.loadMoreCanvases(),/temporary loss/);assert.equal(s.listCursor,"canvas-next");
  await s.loadMoreCanvases();assert.deepEqual(Array.from(s.list,item=>item.id),["recent-canvas","older-canvas"]);
  assert.equal(s.listCursor,"");s.recent=[{id:"recent-run"}];s.recentCursor="run-next";
  await s.loadMoreRuns();assert.deepEqual(Array.from(s.recent,item=>item.id),["recent-run","older-run"]);
  assert.equal(s.recentCursor,"");assert.ok(calls[2].endsWith("/runs?cursor=run-next"));
});

test("refresh restores a cached canvas and chosen run even outside the latest list windows",async t=>{
  storage.clear();const first=store(t,async()=>({run:run("older-run")}));
  first.doc.id="older-canvas";first.doc.writeSeq=2;first.runId="older-run";first.persist();first.close();
  const calls=[];const s=store(t,async url=>{
    calls.push(url);
    if(url==="/api/studio/canvases") return {items:[{id:"newer-canvas"}],nextCursor:"more"};
    if(url.endsWith("/runs")) return {items:[{id:"newer-run"}],nextCursor:"runs-more"};
    if(url.includes("/canvas-runs/")) return {run:run("older-run")};
    return {canvas:{...s.doc,id:"older-canvas",writeSeq:2}};
  });
  await s.load();assert.equal(s.doc.id,"older-canvas");assert.equal(s.run.id,"older-run");
  assert.ok(calls.includes("/api/studio/canvas-runs/older-run"));
});

test("late run list responses cannot populate another canvas",async t=>{
  storage.clear();let release;const s=store(t,async()=>new Promise(resolve=>release=()=>resolve({items:[{id:"private-old"}],nextCursor:"done"})));
  s.recentCursor="next";const loading=s.loadMoreRuns();s.doc.id="another";s.recent=[];s.recentCursor="";
  release();await loading;assert.equal(s.recent.length,0);assert.equal(s.recentCursor,"");
});

test("history opens the saved source canvas and batch; a deleted source preserves results",async t=>{
  storage.clear();let sourceDeleted=false;
  const s=store(t,async url=>{
    if(url.includes("/canvas-runs/")) return {run:{...run("history-run"),canvasId:"source-canvas"}};
    if(url.endsWith("/runs")) return {items:[]};
    if(sourceDeleted) {const error=new Error("source deleted");error.status=404;throw error;}
    return {canvas:{id:"source-canvas",name:"Source",writeSeq:2,graph:{nodes:[],edges:[]}}};
  });
  await s.openRun("history-run");assert.equal(s.doc.id,"source-canvas");assert.equal(s.run.id,"history-run");
  s.doc={...s.doc,id:"another-canvas"};sourceDeleted=true;
  await s.openRun("history-run");assert.equal(s.run.id,"history-run");assert.match(s.error,/已删除/);
  assert.equal(s.doc.id,"another-canvas","A deleted source must not be recreated or rewrite another canvas");
});

test("background canvas bootstrap cannot override an explicit history navigation",async t=>{
  storage.clear();let releaseList;
  const s=store(t,async url=>{
    if(url==="/api/studio/canvases") return new Promise(resolve=>releaseList=()=>resolve({items:[{id:"recent-other"}]}));
    if(url.includes("/canvas-runs/")) return {run:{...run("wanted-run"),canvasId:"wanted-canvas"}};
    if(url.endsWith("/runs")) return {items:[]};
    return {canvas:{id:"wanted-canvas",writeSeq:1,graph:{nodes:[],edges:[]}}};
  });
  const loading=s.load();await s.openRun("wanted-run");releaseList();await loading;
  assert.equal(s.doc.id,"wanted-canvas");assert.equal(s.run.id,"wanted-run");
});

test("recent canvases use the latest ten real documents, never official presets",()=>{
  const items=Array.from({length:15},(_,i)=>({id:"doc-"+i,name:i===14?'<img src=x onerror="bad">':"Canvas "+i,updatedAt:new Date(1800000000000+i*1000).toISOString()}));
  items.push({id:"preset_private",updatedAt:"2099-01-01"},{id:"official",isOfficialPreset:true,updatedAt:"2099-01-01"});
  const before=JSON.stringify(items),recent=recentCanvases(items.reverse());
  assert.deepEqual(Array.from(recent,item=>item.id),Array.from({length:10},(_,i)=>"doc-"+(14-i)));
  assert.equal(items.length,17);assert.equal(JSON.stringify(items.reverse()),before);
});

test("undo restores graph edits, movement and connections without reverting save receipts or accepted runs",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  const initial=JSON.stringify(s.doc.graph),id=s.doc.id;
  s.doc.graph.nodes[0].fields.prompt=["Forest"];s.edit();
  s.doc.graph.nodes[0].x=180;s.edit();
  s.doc.graph.edges=[];s.edit();s.doc.writeSeq=42;s.run=run("accepted");
  assert.equal(s.undo(),true);assert.equal(s.doc.graph.edges.length,1);assert.equal(s.doc.graph.nodes[0].x,180);
  assert.equal(s.undo(),true);assert.equal(s.doc.graph.nodes[0].x,32);
  assert.equal(s.undo(),true);assert.equal(JSON.stringify(s.doc.graph),initial);
  assert.equal(s.doc.id,id);assert.equal(s.doc.writeSeq,42);assert.equal(s.run.id,"accepted");
  assert.equal(s.undo(),false);assert.equal(s.undo(true),true);assert.equal(s.doc.graph.nodes[0].fields.prompt[0],"Forest");
  s.doc.graph.nodes[0].fields.prompt=["Another"];s.edit();assert.equal(s.redoStack.length,0);
  assert.equal(s.dirty,true);assert.equal(s.preview,null);
});

test("typing groups into one undo step, unrelated fields separate and history stays bounded",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  for(const value of ["F","Fo","Forest"]) {s.doc.graph.nodes[0].fields.prompt=[value];s.edit(false,{group:"prompt"});}
  assert.equal(s.undoStack.length,1);
  s.doc.name="New name";s.edit(false,{group:"name"});assert.equal(s.undoStack.length,2);
  s.undo();assert.equal(s.doc.name,"参数组合画布");s.undo();assert.equal(s.doc.graph.nodes[0].fields.prompt[0],"");
  for(let i=0;i<55;i++) {s.doc.name="Name "+i;s.edit();}
  assert.equal(s.undoStack.length,40);
});

test("native input undo returning to a checkpoint does not leave an empty graph undo step",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  s.doc.graph.nodes[0].x=180;s.edit();const original=s.doc.name;
  s.doc.name="Typed title";s.edit(false,{group:"name"});
  s.doc.name=original;s.edit(false,{group:"name"});
  assert.equal(s.undoStack.length,1);s.undo();assert.equal(s.doc.graph.nodes[0].x,32);
  s.doc.name="More typing";s.edit(false,{group:"name"});s.undo();assert.equal(s.doc.name,original);
});

test("saved local canvases reopen separately and remain isolated by account scope",async t=>{
  storage.clear();const config=scope=>({scope,loggedIn:()=>false,storage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)}});
  const s=new CanvasStore(config("guest-saved"));t.after(()=>s.close());
  s.doc.name="First";s.doc.graph.nodes[0].fields.prompt=["Keep first"];s.edit();await s.save();const first=s.doc.id;
  await s.create();s.doc.name="Second";s.edit();await s.save();const second=s.doc.id;
  await s.open(first);assert.equal(s.doc.name,"First");assert.equal(s.doc.graph.nodes[0].fields.prompt[0],"Keep first");
  assert.equal(s.undoStack.length,0);assert.equal(s.doc.writeSeq,0);
  const restored=new CanvasStore(config("guest-saved"));t.after(()=>restored.close());
  assert.equal(restored.list.length,2);await restored.open(second);assert.equal(restored.doc.name,"Second");
  const other=new CanvasStore(config("guest-other"));t.after(()=>other.close());
  assert.equal(other.list.length,0);await assert.rejects(other.open(first),/不存在/);
});

test("switching canvases saves pending edits and a rejected save keeps the current draft",async t=>{
  storage.clear();let rejectSave=true,reads=0;
  const s=store(t,async(url,options)=>{
    if(options?.method==="POST") {if(rejectSave) throw new Error("Unavailable");return {writeSeq:2};}
    reads++;if(url.endsWith("/runs")) return {items:[]};
    return {canvas:{id:"another",name:"Another",writeSeq:1,graph:context.window.HandrawParameterCanvas.testing.blank().graph}};
  });
  s.doc.graph.nodes[0].fields.prompt=["Keep edits"];s.edit();const initial=s.doc.id;
  await s.open("another");assert.equal(s.doc.id,initial);assert.equal(reads,0);assert.equal(s.undoStack.length,1);
  rejectSave=false;await s.open("another");assert.equal(s.doc.id,"another");assert.equal(s.undoStack.length,0);
});

test("local archive quota failure preserves the current document and previous saved list",async t=>{
  let fail=false;const memory=new Map();
  const s=new CanvasStore({scope:"quota",loggedIn:()=>false,storage:{getItem:key=>memory.get(key),setItem:(key,value)=>{if(fail && key.endsWith(":saved")) throw Error("Quota");memory.set(key,value);}}});t.after(()=>s.close());
  s.doc.name="Saved";s.edit();assert.equal(await s.save(),true);
  s.doc.name="Unsaved";s.edit();fail=true;assert.equal(await s.save(),false);
  assert.equal(s.doc.name,"Unsaved");assert.equal(s.dirty,true);assert.equal(s.list[0].name,"Saved");assert.match(s.error,/导出/);
});

test("current canvas renders four direct toolbar actions without More or a permanent name input",t=>{
  const canvas=context.window.HandrawParameterCanvas,doc=canvas.testing.blank();
  context.window.localStorage={getItem:()=>JSON.stringify({doc}),setItem(){}};
  const root={innerHTML:"",querySelector:()=>null,querySelectorAll:()=>[]};
  canvas.mount(root,{scope:"four-action-render",loggedIn:()=>false,resources:()=>[]});
  t.after(()=>{canvas.reset();delete context.window.localStorage;});
  const menu=root.innerHTML.split('class="pc-document-actions"')[1].split('class="pc-toolbar"')[0];
  assert.deepEqual([...menu.matchAll(/data-action="([^"]+)"/g)].map(m=>m[1]),["new","save","export","open-canvases"]);
  assert.equal([...root.innerHTML.matchAll(/data-action="undo"/g)].length,1);
  assert.ok(!root.innerHTML.includes('class="pc-undo"'));assert.ok(!root.innerHTML.includes('data-action="choose-canvas"'));
  assert.ok(root.innerHTML.includes('aria-label="最近保存的画布"'));
  assert.ok(!root.innerHTML.includes('pc-document-menu'));assert.ok(!root.innerHTML.includes('data-name'));
  assert.ok(menu.includes('role="toolbar"'));
});

test("named saves trim and validate the workflow name before writing, and preserve its ID",async t=>{
  storage.clear();const writes=[];const s=store(t,async(url,options)=>{writes.push(options.body);return {writeSeq:writes.length};});
  const id=s.doc.id,initial=s.doc.name;
  await assert.rejects(s.saveNamed(" \n "),/名称/);await assert.rejects(s.saveNamed("x".repeat(101)),/名称/);
  assert.equal(s.doc.name,initial);assert.equal(writes.length,0);
  assert.equal(await s.saveNamed("  工作流A  "),true);assert.equal(s.doc.name,"工作流A");assert.equal(s.doc.id,id);
  assert.equal(writes[0].name,"工作流A");assert.equal(await s.saveNamed("工作流A"),true);assert.equal(writes.length,1);
});

test("a failed named save retains its name and graph for a successful retry",async t=>{
  storage.clear();let fail=true;const s=store(t,async()=>{if(fail) throw Error("Unavailable");return {writeSeq:1};});
  s.doc.graph.nodes[0].fields.prompt=["Keep this subject"];s.edit();
  assert.equal(await s.saveNamed("保留草稿"),false);assert.equal(s.doc.name,"保留草稿");assert.equal(s.dirty,true);
  fail=false;assert.equal(await s.saveNamed("保留草稿"),true);assert.equal(s.doc.graph.nodes[0].fields.prompt[0],"Keep this subject");assert.equal(s.error,"");
});

test("removing the last color candidate restores the original combinations and other parameters",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1})),node=s.doc.graph.nodes[0];
  node.fields.prompt=["Forest","Ocean"];node.fields.style1=["FA-001","FA-002"];s.edit();
  const before=JSON.stringify(node.fields),edges=JSON.stringify(s.doc.graph.edges),order=JSON.stringify(node.fieldOrder);
  const plans=()=>{const source=matchingSources(s.doc.graph,node);return JSON.stringify(matchingPreview(source.sources,node.mode,1,200));};
  const initial=plans();
  for(let i=0;i<3;i++) {
    addGuidedParameter(s,"colors");node.fields.colors=[["red"],["blue"]];s.edit();
    assert.equal(combinationSummary(s.doc.graph).count,8);
    assert.equal(removeCandidate(node,"colors",1),true);s.edit();assert.equal(combinationSummary(s.doc.graph).count,4);
    assert.equal(removeCandidate(node,"colors",0),true);s.edit();
    assert.equal(JSON.stringify(node.fields),before);assert.equal(JSON.stringify(node.fieldOrder),order);
    assert.equal(plans(),initial);assert.equal(JSON.stringify(s.doc.graph.edges),edges);
  }
  s.undo();assert.deepEqual(Array.from(s.doc.graph.nodes[0].fields.colors[0]),["red"]);
  s.undo(true);assert.equal(Object.hasOwn(s.doc.graph.nodes[0].fields,"colors"),false);
});

test("all optional parameter deletions preserve the required content and field order",t=>{
  for(const field of ["colors","tones","moods","refImages","whitespace","mode","layout","ratio","style1"]) {
    storage.clear();const s=store(t,async()=>({writeSeq:1})),node=s.doc.graph.nodes[0];node.fields.prompt=["Keep my subject"];s.edit();
    addGuidedParameter(s,field);assert.equal(removeCandidate(node,field,0),true);
    assert.equal(Object.hasOwn(node.fields,field),false,field);assert.ok(!node.fieldOrder.includes(field));
    assert.equal(node.fields.prompt[0],"Keep my subject");assert.equal(combinationSummary(s.doc.graph).count,1);
    assert.equal(removeCandidate(node,field,0),false,"A stale removal must not affect another field");
  }
});

test("removing a whole optional field and clearing required or standalone candidates keep an editable graph",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1})),node=s.doc.graph.nodes[0];node.fields.prompt=["One","Two"];s.edit();
  addGuidedParameter(s,"colors");assert.equal(removeParameterField(node,"colors"),true);
  assert.equal(combinationSummary(s.doc.graph).count,2);assert.equal(removeCandidate(node,"prompt",0),true);
  assert.equal(node.fields.prompt[0],"Two");removeCandidate(node,"prompt",0);
  assert.equal(node.fields.prompt.length,1);assert.equal(node.fields.prompt[0],"");assert.match(combinationSummary(s.doc.graph).problem,/填写每个主题/);
  const only={id:"only",type:"parameters",fields:{colors:[["red"]]},fieldOrder:["colors"]};
  removeCandidate(only,"colors",0);assert.equal(only.fields.colors.length,1);assert.equal(only.fields.colors[0].length,0);
  const single={type:"parameter",parameter:"colors",values:[["red"]]};removeCandidate(single,"colors",0);
  assert.equal(single.values.length,1);assert.equal(single.values[0].length,0);
});

test("already saved empty optional candidates recover without modifying other values or identities",()=>{
  const graph=context.window.HandrawParameterCanvas.testing.blank().graph,node=graph.nodes[0];
  node.fields.prompt=["Existing private content"];node.fields.colors=[];node.fieldOrder.push("colors");
  assert.equal(repairEmptyCandidates(graph),true);assert.ok(!Object.hasOwn(node.fields,"colors"));
  assert.equal(node.fields.prompt[0],"Existing private content");assert.equal(node.id,"params");assert.equal(graph.edges[0].to,"output");
  assert.equal(repairEmptyCandidates(graph),false);assert.ok(!node.fieldOrder.includes("colors"));
  node.fields.prompt=[];assert.equal(repairEmptyCandidates(graph),true);assert.equal(node.fields.prompt.length,1);
  assert.equal(node.fields.prompt[0],"");
});

test("warm-cache and cloud documents with an empty color list can save and preview again",async t=>{
  storage.clear();const document=context.window.HandrawParameterCanvas.testing.blank();document.id="broken";document.writeSeq=9;
  document.graph.nodes[0].fields.prompt=["Recover body"];document.graph.nodes[0].fields.colors=[];document.graph.nodes[0].fieldOrder.push("colors");
  storage.set("handraw.parameter-canvas:cache-repair",JSON.stringify({doc:document}));
  const cached=store(t,async()=>({writeSeq:10}),"cache-repair");assert.equal(cached.dirty,true);assert.equal(combinationSummary(cached.doc.graph).count,1);
  let sent;
  const cloud=store(t,async(url,options)=>{
    if(options?.method==="POST") {sent=options.body;return {writeSeq:10};}
    if(url.endsWith("/runs")) return {items:[]};return {canvas:JSON.parse(JSON.stringify(document))};
  },"cloud-repair");
  await cloud.open("broken");assert.equal(cloud.dirty,true);assert.equal(combinationSummary(cloud.doc.graph).count,1);
  assert.equal(await cloud.save(),true);assert.equal(sent.id,"broken");assert.equal(sent.baseWriteSeq,9);assert.equal(sent.graph.nodes[0].fields.prompt[0],"Recover body");
  assert.equal(Object.hasOwn(sent.graph.nodes[0].fields,"colors"),false);
});

test("preset choices normalize catalog items and custom input keeps selected presets",()=>{
  const choices=choiceOptions("colors",[{id:"C-01",name_zh:"克莱因蓝",image:"/blue.webp"},{id:"C-15",name:"朱砂红"}]);
  assert.equal(choices[0].label,"克莱因蓝");assert.equal(choices[0].image,"/blue.webp");
  assert.deepEqual(Array.from(customSelection(["C-01","old custom"],"暖灰，米白、暖灰",choices)),["C-01","暖灰","米白"]);
  assert.deepEqual(Array.from(customSelection(["C-01","old custom"],"",choices)),["C-01"]);
  assert.deepEqual(Array.from(customSelection(["unknown legacy"],"unknown legacy",[])),["unknown legacy"]);
  assert.equal(choiceOptions("moods",["治愈","治愈","松弛"]).length,2);
});

test("several chosen presets form one candidate while different candidates and modes multiply",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1})),node=s.doc.graph.nodes[0];
  node.fields.prompt=["One subject"];node.fields.colors=[["C-01","C-15","custom color"]];node.fieldOrder.push("colors");
  assert.equal(combinationSummary(s.doc.graph).count,1);
  node.fields.colors.push(["C-02"]);assert.equal(combinationSummary(s.doc.graph).count,2);
  node.fields.mode=["image-only","graphic-text","poster"];node.fieldOrder.push("mode");assert.equal(combinationSummary(s.doc.graph).count,6);
  const source=matchingSources(s.doc.graph,node),rows=matchingPreview(source.sources,"cartesian",1,200);
  assert.equal(rows.count,6);assert.deepEqual(Array.from(rows.samples[0].colors),["C-01","C-15","custom color"]);
});

test("advanced parameters render selection plus custom input, with shadow tone labels and all three modes",t=>{
  const canvas=context.window.HandrawParameterCanvas,doc=canvas.testing.blank(),node=doc.graph.nodes[0];
  Object.assign(node.fields,{colors:[["C-01","自定义暖灰"]],tones:[["T-01","柔和逆光"]],moods:[["治愈","远行感"]],whitespace:["high"],mode:["poster"]});
  node.fieldOrder=Object.keys(node.fields);
  context.window.localStorage={getItem:()=>JSON.stringify({doc}),setItem(){}};
  const root={innerHTML:"",querySelector:()=>null,querySelectorAll:()=>[]};
  canvas.mount(root,{scope:"preset-custom-render",loggedIn:()=>false,resources:()=>[],parameterChoices:field=>field==="colors"?[{id:"C-01",name_zh:"克莱因蓝",image:"/blue.webp"}]:field==="tones"?[{id:"T-01",name_zh:"高调",image:"/tone.webp"}]:field==="moods"?["治愈"]:[{value:"high",label:"大量留白"}]});
  t.after(()=>{canvas.reset();delete context.window.localStorage;});
  // Select a tab through the actual delegated handler without a fake rendering implementation.
  for(const field of ["colors","tones","moods","whitespace","mode"]) {
    const button={dataset:{action:"edit-field",node:node.id,parameter:field}};
    root.onclick({target:{closest:selector=>selector==="button[data-action]"?button:null}});
    if(field==="mode") {for(const mode of ["纯图","图文","海报"]) assert.ok(root.innerHTML.includes(`>${mode}</button>`));}
    else {
      assert.ok(root.innerHTML.includes('data-custom-choice'));
      if(field!=="whitespace") assert.ok(root.innerHTML.includes('data-action="choose-parameters"'));
      if(field==="colors") {assert.ok(root.innerHTML.includes('src="/blue.webp"'));assert.ok(root.innerHTML.includes('value="自定义暖灰"'));}
      if(field==="tones") {assert.ok(root.innerHTML.includes('选择影调'));assert.ok(!root.innerHTML.includes('选择色调'));assert.ok(root.innerHTML.includes('value="柔和逆光"'));}
    }
  }
});
