"use strict";
/* #111 · real edit-only Graph snapshots, large Run/Media references stay shared. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {performance}=require("node:perf_hooks");
const Renderer=require("../demo/assets/studio-canvas-renderer.js");
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
const marker="window.HandrawCanvasRenderer.captureEditableGraph(CS.graph)";
assert.equal((app.match(/window\.HandrawCanvasRenderer\.captureEditableGraph\(CS\.graph\)/g)||[]).length,3,
  "push, undo and redo must share one memory-only history capture contract");
assert.ok(Renderer.captureEditableGraph&&Renderer.preserveRuntime);

const hugeResult="result-image:".repeat(1250);
const hugeRun="authoritative-run-snapshot:".repeat(330);
const graph={
  revision:10,blueprint:"series",selectedIds:["text"],runRefs:[{runId:"run-1"}],
  meta:{runRefs:[{runId:"run-1"}],lastEditedBy:"test"},
  nodes:[
    {id:"text",type:"text_input",x:0,y:0,data:{text:"my old editable prompt",extra:{tags:["a","b"]}}},
    {id:"ctrl",type:"output_control",x:200,y:0,data:{
      ratio:"3:4",count:5,runId:"run-1",status:"generating",
      studio2RunSnapshot:{blob:hugeRun},pendingRequestIds:{0:"req-a"}}},
    {id:"loop",type:"loop",x:400,y:0,data:{
      count:3,runId:"loop-run-1",status:"generating",pendingTaskId:"pending-1"}},
    {id:"article",type:"article_plan",x:20,y:200,data:{
      markdown:"original article",cards:[{id:"card-1",subject:"old draft",
        mediaId:"media-old",imageUrl:"/generated/original.webp",
        generationVariants:[{image:hugeResult}],status:"success"}]}},
    {id:"display",type:"output_display",x:650,y:0,w:400,data:{
      items:[{mediaId:"media-1",imageUrl:"/generated/file.webp",bytes:hugeResult}],
      status:"generating"}}
  ],
  edges:[{id:"edge-a",from:"ctrl",to:"display"}]
};
const saved=Renderer.captureEditableGraph(graph);
assert.notEqual(saved,graph);
assert.notEqual(saved.nodes.find(x=>x.id==="text").data,graph.nodes[0].data,
  "user-editable data needs its own history snapshot");
assert.notEqual(saved.nodes.find(x=>x.id==="ctrl").data,graph.nodes[1].data);
assert.notEqual(saved.nodes.find(x=>x.id==="article").data,graph.nodes[3].data);
assert.strictEqual(saved.nodes.find(x=>x.id==="display").data,graph.nodes[4].data,
  "generated result bytes should never be cloned per edit");
assert.strictEqual(saved.nodes.find(x=>x.id==="ctrl").data.studio2RunSnapshot,
  graph.nodes[1].data.studio2RunSnapshot,"RunSnapshot is not editable history");
assert.strictEqual(saved.nodes.find(x=>x.id==="article").data.cards[0].generationVariants,
  graph.nodes[3].data.cards[0].generationVariants,"media history is authoritative");
assert.strictEqual(saved.runRefs,graph.runRefs);
assert.strictEqual(saved.meta.runRefs,graph.meta.runRefs);
assert.notStrictEqual(saved.selectedIds,graph.selectedIds);
const fullGraphBefore=JSON.stringify(graph);
assert.notStrictEqual(saved.nodes.find(x=>x.id==="text").data.extra,graph.nodes[0].data.extra);

graph.nodes[0].data.text="newer prompt";
graph.nodes[0].data.extra.tags.push("c");
graph.nodes[1].data.ratio="9:16";
graph.nodes[1].data.runId="run-live";
graph.nodes[1].data.studio2RunSnapshot={blob:hugeRun,runId:"run-live"};
graph.nodes[1].data.pendingRequestIds={0:"req-live"};
graph.nodes[2].data.runId="loop-run-live";
graph.nodes[3].data.markdown="newer article";
graph.nodes[3].data.cards[0].subject="newer card";
graph.nodes[3].data.cards[0].mediaId="media-live";
graph.nodes[3].data.cards[0].imageUrl="/generated/live.webp";
graph.nodes[3].data.cards[0].generationVariants.push({image:"new variant"});
graph.nodes[4].data.status="success";
graph.nodes[4].data.items[0].mediaId="media-live";
graph.nodes.push({id:"added",type:"text_input",data:{text:"should undo"},x:800,y:200});
const activeJson=JSON.stringify(graph);
const undo=Renderer.preserveRuntime(graph,saved);
assert.equal(JSON.stringify(graph),activeJson,"restoring a snapshot must not mutate the live graph");
assert.equal(undo.revision,11);
assert.equal(undo.nodes.length,5,"new editable node is undone");
assert.equal(undo.nodes.find(x=>x.id==="text").data.text,"my old editable prompt");
assert.deepEqual(undo.nodes.find(x=>x.id==="text").data.extra.tags,["a","b"]);
assert.equal(undo.nodes.find(x=>x.id==="ctrl").data.ratio,"3:4");
assert.equal(undo.nodes.find(x=>x.id==="ctrl").data.runId,"run-live");
assert.equal(undo.nodes.find(x=>x.id==="ctrl").data.studio2RunSnapshot.runId,"run-live");
assert.equal(undo.nodes.find(x=>x.id==="ctrl").data.pendingRequestIds[0],"req-live");
assert.equal(undo.nodes.find(x=>x.id==="loop").data.runId,"loop-run-live");
assert.equal(undo.nodes.find(x=>x.id==="article").data.markdown,"original article");
assert.equal(undo.nodes.find(x=>x.id==="article").data.cards[0].subject,"old draft");
assert.equal(undo.nodes.find(x=>x.id==="article").data.cards[0].mediaId,"media-live");
assert.equal(undo.nodes.find(x=>x.id==="article").data.cards[0].imageUrl,"/generated/live.webp");
assert.equal(undo.nodes.find(x=>x.id==="article").data.cards[0].generationVariants.length,2);
assert.equal(undo.nodes.find(x=>x.id==="display").data.status,"success");
assert.equal(undo.nodes.find(x=>x.id==="display").data.items[0].mediaId,"media-live");
assert.deepEqual(undo.runRefs,[{runId:"run-1"}]);

const redo=Renderer.captureEditableGraph(graph);
const restored=Renderer.preserveRuntime(undo,redo);
assert.equal(restored.nodes.find(x=>x.id==="text").data.text,"newer prompt");
assert.equal(restored.nodes.find(x=>x.id==="ctrl").data.runId,"run-live");
assert.equal(restored.nodes.find(x=>x.id==="display").data.status,"success");
// Deleting a result node is an EDIT: it must be undoable without wiping its
// media bytes. Memory snapshots keep references for precisely this case.
const deleted=structuredClone(graph);
deleted.nodes=deleted.nodes.filter(x=>x.id!=="display");
deleted.edges=[];
const recovered=Renderer.preserveRuntime(deleted,saved);
assert.equal(recovered.nodes.find(x=>x.id==="display").data.items[0].mediaId,"media-live");
assert.equal(recovered.nodes.find(x=>x.id==="display").data.status,"success");

function largeGraph(n){
  const nodes=[];
  for(let i=0;i<n;i++){
    const id="node-"+i;
    if(i%3===0)nodes.push({id,type:"output_display",x:i*2,y:i*3,
      data:{status:"success",items:[{mediaId:"media-"+i,bytes:hugeResult}]}});
    else if(i%3===1)nodes.push({id,type:"output_control",x:i*2,y:i*3,
      data:{ratio:"3:4",count:3,runId:"run-"+i,
        studio2RunSnapshot:{id:i,bytes:hugeRun},status:"success"}});
    else nodes.push({id,type:"text_input",x:i*2,y:i*3,
      data:{text:"创作任务 "+i,editable:{ratio:"1:1"}}});
  }
  return {blueprint:"series",revision:9,nodes,edges:[],selectedIds:[]};
}
const report=[];
for(const n of [10,50,100,300]){
  const g=largeGraph(n);
  const mediaObjects=g.nodes.filter(x=>x.type==="output_display").map(x=>x.data);
  const runObjects=g.nodes.filter(x=>x.type==="output_control")
    .map(x=>x.data.studio2RunSnapshot);
  const copies=[];
  const start=performance.now();
  for(let i=0;i<35;i++)copies.push(Renderer.captureEditableGraph(g));
  const durationMs=performance.now()-start;
  for(const copy of copies){
    const display=copy.nodes.filter(x=>x.type==="output_display");
    const control=copy.nodes.filter(x=>x.type==="output_control");
    assert.ok(display.every((x,i)=>x.data===mediaObjects[i]));
    assert.ok(control.every((x,i)=>x.data.studio2RunSnapshot===runObjects[i]));
    assert.notStrictEqual(copy.nodes.find(x=>x.type==="text_input").data,
      g.nodes.find(x=>x.type==="text_input").data);
  }
  const uniqueRuntimeRefs=new Set(copies.flatMap(x=>x.nodes.flatMap(node=>
    node.type==="output_display"?[node.data]:
    node.type==="output_control"?[node.data.studio2RunSnapshot]:[])));
  assert.equal(uniqueRuntimeRefs.size,mediaObjects.length+runObjects.length,
    "35 captures must share the very same authoritative media/Run objects");
  const theoreticalFullCopyBytes=Buffer.byteLength(JSON.stringify(g))*35;
  const uniqueRetainedRuntimeBytes=[...uniqueRuntimeRefs].reduce(
    (total,o)=>total+Buffer.byteLength(JSON.stringify(o)),0);
  const allSnapshots=copies.reduce((sum,copy)=>
    sum+copy.nodes.filter(x=>x.type!=="output_display"&&x.type!=="output_control")
      .reduce((s,x)=>s+Buffer.byteLength(JSON.stringify(x)),0),0);
  const approxRetainedBytes=uniqueRetainedRuntimeBytes+allSnapshots;
  assert.ok(approxRetainedBytes<theoreticalFullCopyBytes*0.5,
    "large 35-step history must share enough actual Run/media objects");
  report.push({nodes:n,steps:35,captureTotalMs:+durationMs.toFixed(2),
    theoreticalFullSnapshotBytes:theoreticalFullCopyBytes,
    uniqueRuntimeObjects:uniqueRuntimeRefs.size,
    approxRetainedPayloadBytes:approxRetainedBytes,
    estimatedPayloadSavingsPct:+(100*(1-approxRetainedBytes/theoreticalFullCopyBytes)).toFixed(1)});
}
console.log("CANVAS #111 edit-only in-memory Run/media retention PASS "+JSON.stringify(report));
