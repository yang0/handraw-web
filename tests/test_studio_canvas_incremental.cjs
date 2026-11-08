"use strict";
/* #127: contract and runtime tests; Chromium exercise is separate. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const Renderer=require("../demo/assets/studio-canvas-renderer.js");
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
const html=fs.readFileSync("demo/studio.html","utf8");

assert.ok(html.indexOf("studio-canvas-renderer.js")>=0);
assert.ok(html.indexOf("studio-canvas-renderer.js")<html.indexOf("studio-app.js"));
assert.match(app,/function patchStudioCanvasDom\(layer,cardsHtml,datalistsHtml\)/);
// Verify the actual module call, rather than a stale local patch copy.
assert.match(app,/r\.reconcile\(layer,cardsHtml,datalistsHtml\)/);
assert.match(app,/for\(const el of dirtyNodes\)bindNodeInteriorActions\(el\)/);
assert.match(app,/function bindNodeInteriorActions\(root = DOM\.nodesLayer\)/);
assert.match(app,/root\.querySelectorAll\("\[data-sp-fusion\]"\)/);
assert.match(app,/root\.querySelectorAll\("\[data-disp-zoom\]"\)/);
assert.doesNotMatch(app,/studio2RenderedNodeMarkup/);
assert.doesNotMatch(app,/DOM\.nodesLayer\.innerHTML = cardsHtml \+ datalistsHtml/);
assert.match(app,/function refreshCanvasSelection\(\)/);
assert.match(app,/refreshCanvasSelection\(\)/);
assert.match(app,/window\.HandrawCanvasRenderer\.preserveRuntime\(CS\.graph,CS\.undoStack\.pop\(\)\)/);
assert.match(app,/window\.HandrawCanvasRenderer\.preserveRuntime\(CS\.graph,CS\.redoStack\.pop\(\)\)/);

const afterCurrent={
  revision:7,nodes:[
    {id:"s",type:"skill_params",x:0,y:0,data:{style1:"FA-OLD",layout:"SC-021"}},
    {id:"c1",type:"output_control",x:500,y:0,data:{
      ratio:"9:16",runId:"run-latest",studio2RunSnapshot:{runId:"run-latest",items:["item-1"]},
      pendingRequestIds:{"slot-A":"req-a"},status:"generating"}},
    {id:"c2",type:"output_control",x:500,y:800,data:{
      ratio:"4:3",runId:"run-c2",status:"success"}},
    {id:"a",type:"article_plan",x:30,y:100,data:{
      markdown:"latest user article",cards:[{id:"card-1",subject:"user revision",
        imageUrl:"/generated/owned.png",runItemId:"item-4",status:"done"}]}},
    {id:"r1",type:"output_display",x:900,y:0,data:{
      status:"success",items:[{mediaId:"media-1",imageUrl:"/generated/output.png"}]}},
    {id:"r2",type:"output_display",x:900,y:850,data:{
      status:"generating",items:[{mediaId:"media-2",imageUrl:"/generated/output2.png"}]}}
  ],
  edges:[{id:"edge-1",from:"s",to:"c1"},
    {id:"edge-r1",from:"c1",to:"r1"},
    {id:"edge-r2",from:"c2",to:"r2"}],
  runRefs:[{runId:"run-latest"}],
  meta:{runRefs:[{runId:"run-c2"}]}
};
const beforeRun={
  revision:5,nodes:[
    {id:"s",type:"skill_params",x:0,y:0,data:{style1:"FA-REVERT",layout:"SC-021"}},
    {id:"c1",type:"output_control",x:500,y:0,data:{
      ratio:"3:4",runId:"run-stale",studio2RunSnapshot:{runId:"run-stale"},status:"ready"}},
    {id:"c2",type:"output_control",x:500,y:800,data:{ratio:"1:1"}},
    {id:"a",type:"article_plan",x:30,y:100,data:{
      markdown:"article edit restored",cards:[{id:"card-1",subject:"old article",
        status:"idle",imageUrl:""}]}}
  ],
  edges:[{id:"edge-1",from:"s",to:"c1"}]
};
const frozen=JSON.stringify(afterCurrent);
const restored=Renderer.preserveRuntime(afterCurrent,beforeRun);
assert.equal(JSON.stringify(afterCurrent),frozen,"protectRun must not mutate active graph");
assert.equal(restored.revision,8,"Undo must create a new monotonic revision");
assert.equal(restored.nodes.find(x=>x.id==="s").data.style1,"FA-REVERT");
assert.equal(restored.nodes.find(x=>x.id==="c1").data.ratio,"3:4","editable ratio should undo");
assert.equal(restored.nodes.find(x=>x.id==="c1").data.runId,"run-latest","Run ID remains authoritative");
assert.equal(restored.nodes.find(x=>x.id==="c1").data.studio2RunSnapshot.runId,"run-latest");
assert.equal(restored.nodes.find(x=>x.id==="c1").data.pendingRequestIds["slot-A"],"req-a");
assert.equal(restored.nodes.find(x=>x.id==="c2").data.runId,"run-c2");
assert.equal(restored.nodes.filter(x=>x.type==="output_display").length,2);
assert.equal(restored.nodes.find(x=>x.id==="r1").data.items[0].mediaId,"media-1");
assert.equal(restored.nodes.find(x=>x.id==="r2").data.status,"generating");
assert.ok(restored.edges.some(e=>e.id==="edge-r1"));
assert.ok(restored.edges.some(e=>e.id==="edge-r2"));
assert.equal(restored.nodes.find(x=>x.id==="a").data.markdown,"article edit restored");
assert.equal(restored.nodes.find(x=>x.id==="a").data.cards[0].imageUrl,"/generated/owned.png");
assert.equal(restored.nodes.find(x=>x.id==="a").data.cards[0].runItemId,"item-4");
assert.deepEqual(restored.runRefs,[{runId:"run-latest"}]);
assert.deepEqual(restored.meta.runRefs,[{runId:"run-c2"}]);
// A second Undo after an async completion must not resurrect "generating".
const completed=JSON.parse(JSON.stringify(restored));
completed.nodes.find(x=>x.id==="r2").data.status="success";
completed.nodes.find(x=>x.id==="r2").data.items[0].mediaId="media-2-final";
const restoredAgain=Renderer.preserveRuntime(completed,beforeRun);
assert.equal(restoredAgain.nodes.find(x=>x.id==="r2").data.items[0].mediaId,"media-2-final");
assert.equal(restoredAgain.revision,9);
assert.equal(Renderer.rootFlags('<div class="ic-node abc is-selected is-related">A</div>'),
  Renderer.rootFlags('<div class="ic-node abc  ">A</div>'),
  "selection-only class updates must not trigger image reloads");
console.log("Canvas #127: scoped DOM bindings, safe revisions, two-output Run snapshots, article media PASS");
