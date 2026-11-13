"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),vm=require("node:vm"),fs=require("node:fs");
const context={window:{__HANDRAW_TESTING__:true},setTimeout,clearTimeout,console};
vm.createContext(context);vm.runInContext(fs.readFileSync("demo/assets/parameter-canvas.js","utf8"),context);
const {CanvasStore,selectedQuote,arrangeNodes,pickResourceCandidate}=context.window.HandrawParameterCanvas.testing;
const storage=new Map();
function store(t,api,scope="user:canvas") {
  const instance=new CanvasStore({api,scope,loggedIn:()=>true,storage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)}});
  t.after(()=>instance.close());return instance;
}
function preview() {return {planHash:"hash",quote:{freeRemaining:1,unitPrice:2,balance:10},items:[{ordinal:0,spec:{prompt:"A"}},{ordinal:1,spec:{prompt:"B"}}]};}
function run(id="run") {return {id,status:"success",items:[],count:0,retryQuote:{total:0,unitPrice:2},spentCredits:0,maxCredits:0};}

test("visual resource picks change only the chosen candidate and preserve atomic fusion pairs",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
  const node=s.doc.graph.nodes.find(n=>n.id==="style");node.values=[{style1:"FA-001",style2:"FA-002"},"FA-003"];
  const other=JSON.stringify(s.doc.graph.nodes.filter(n=>n!==node));let picker;
  const choose=(field,code)=>{pickResourceCandidate(s,node,0,field,settings=>picker=settings);picker.onPick(code);};
  choose("style1","FA-004");assert.equal(node.values[0].style2,"FA-002");assert.equal(node.values[0].style1,"FA-004");
  choose("style2","");assert.equal(node.values[0],"FA-004");
  choose("style2","FA-005");choose("style1","");assert.equal(node.values[0],"");
  assert.equal(node.values[1],"FA-003");assert.equal(JSON.stringify(s.doc.graph.nodes.filter(n=>n!==node)),other);
  assert.equal(s.dirty,true);
});

test("cancelled or late visual picker results never modify another canvas, removed node or account",t=>{
  storage.clear();const s=store(t,async()=>({writeSeq:1}));
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
  s.doc.graph.nodes[0].values=["First"];s.edit();const saving=s.save();
  s.doc.graph.nodes[0].values=["Second"];s.edit();const concurrent=s.save();
  release();assert.deepEqual(await Promise.all([saving,concurrent]),[true,true]);
  assert.equal(writes.length,2);assert.equal(writes[0].baseWriteSeq,0);assert.equal(writes[1].baseWriteSeq,1);
  assert.equal(writes[1].graph.nodes[0].values[0],"Second");assert.equal(s.dirty,false);
});
test("save conflict retains the local document and can be recovered as an explicit copy",async t=>{
  storage.clear();const s=store(t,async()=>{const error=new Error("changed elsewhere");error.status=409;error.code="canvas_conflict";throw error;});
  s.doc.graph.nodes[0].values=["Local work"];s.edit();const old=s.doc.id;
  assert.equal(await s.save(),false);assert.equal(s.conflict,true);assert.equal(s.doc.graph.nodes[0].values[0],"Local work");
  await s.create(true);assert.notEqual(s.doc.id,old);assert.equal(s.doc.writeSeq,0);assert.equal(s.conflict,false);
});
test("preview uses the saved document and never submits per-image generation requests",async t=>{
  storage.clear();const calls=[];const s=store(t,async(url,options)=>{calls.push(url);if(url.endsWith("/preview")) return preview();return {writeSeq:1};});
  s.doc.graph.nodes[0].values=["Theme"];s.edit();await s.expand();
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
  s.doc.graph.nodes[0].values=["Changed"];s.edit();release();await assert.rejects(expanding,/参数已变化/);assert.equal(s.preview,null);
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
