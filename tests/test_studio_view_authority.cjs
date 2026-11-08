"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const Views = require("../demo/assets/studio-views.js");
const Core = require("../demo/assets/studio-core.js");
const {createClient} = require("../demo/assets/studio-project-sync.js");
const fixture = name => JSON.parse(fs.readFileSync("docs/studio-2.0/fixtures/"+name+".json","utf8"));
const clone = value => JSON.parse(JSON.stringify(value));

async function main() {
  const image=fixture("image"), series=fixture("series"), article=fixture("article");
  const compiled=Views.compile(image.creationSpec,null,{projectId:image.project.id});
  const again=Views.compile(image.creationSpec,null,{projectId:image.project.id});
  assert.deepEqual(compiled,again,"ID mapping must be stable");
  assert.equal(Views.classify(compiled).mode,"simple-editable");
  const derived=Views.specFromGraph(compiled).spec;
  assert.equal(derived.subject,image.creationSpec.subject);
  assert.equal(derived.style.id,image.creationSpec.style.id);
  assert.equal(derived.ratio,image.creationSpec.ratio);
  assert.equal(derived.referenceMedia[0].mediaId,image.creationSpec.referenceMedia[0].mediaId);
  assert.equal(compiled.nodes.find(n=>n.type==="asset").data.items[0].role,"scene");
  assert.throws(()=>Views.compile(image.creationSpec,null,
    {projectId:"image",existingGraph:compiled}),/existing_graph_requires_patch/);

  assert.equal(series.plan.slots.length,6,"six storyboard slots required");
  const batch=Views.compile(series.creationSpec,series.plan,{projectId:"series-A"});
  const loop=batch.nodes.find(n=>n.type==="loop");
  assert.deepEqual(loop.data.studio2SlotIds,series.plan.slots.map(s=>s.slotId));
  assert.equal(Core.normalizeLegacyBatch(loop).slots.length,6);
  assert.deepEqual(Core.normalizeLegacyBatch(loop).slots.map(s=>s.slotId),
    series.plan.slots.map(s=>s.slotId));
  assert.equal(Views.classify(batch).mode,"simple-editable");
  const a=Views.compile(article.creationSpec,article.plan,
    {projectId:"article-A",article:article.article});
  const anchorNode=a.nodes.find(n=>n.type==="article_plan");
  assert.deepEqual(anchorNode.data.anchors.map(x=>x.anchorId),
    article.article.anchors.map(x=>x.anchorId));
  assert.ok(!JSON.stringify(a).includes(article.article.markdown),
    "article document markdown must not be duplicated into the graph");

  const complex=fixture("canvas").graph;
  const view=Views.classify(complex);
  assert.equal(view.mode,"partial-editable","two output branches are only partially expressible");
  assert.deepEqual(view.nodeIds.outputs,["n-output-a","n-output-b"]);
  const original=clone(complex);
  const patched=Views.patchNode(complex,{nodeId:"n-text",field:"text",
    value:"分支公共主题",baseRevision:complex.revision});
  assert.equal(patched.nodes.find(n=>n.id==="n-text").data.text,"分支公共主题");
  assert.deepEqual(complex,original,"a patch must never mutate the original");
  assert.deepEqual(patched.edges,complex.edges,"edges must be byte-for-byte preserved");
  assert.equal(patched.nodes.find(n=>n.id==="n-output-b").data.ratio,"9:16");
  assert.throws(()=>Views.patchNode(complex,{nodeId:"n-output-a",
    field:"ratio",value:"1:1",baseRevision:6}),/graph_field_read_only/);
  assert.throws(()=>Views.patchNode(complex,{nodeId:"n-text",
    field:"status",value:"running",baseRevision:6}),/unsafe_graph_patch/);
  assert.throws(()=>Views.patchNode(complex,{nodeId:"n-text",
    field:"text",value:"other",baseRevision:5}),/graph_revision_conflict/);
  const diffs=Views.graphFieldPatches(complex,patched);
  assert.deepEqual(diffs,[{op:"set",
    path:"/graph/nodesById/n-text/data/text",value:"分支公共主题"}]);
  const reordered=clone(patched);
  reordered.nodes.push({id:"hand-user-node",type:"custom_filter",data:{note:"手工节点"}});
  assert.equal(Views.classify(reordered).mode,"read-only-summary");
  assert.equal(Views.graphFieldPatches(complex,reordered),null,
    "structural edits must never be disguised as simple parameter changes");

  let state={graph:clone(complex), activeView:"simple", editorLayout:{
    camera:{vx:40,vy:-15,vk:0.73},selectedIds:["n-text"],panels:{shelfOpen:false},
    workflowVersion:"unsaved-3",resultRefs:[{nodeId:"n-output-b",runId:"run-123"}]}};
  const immutable=clone(state);
  for(let i=0;i<10;i++) {
    const result=Views.switchView(state,i%2?"simple":"canvas");
    state=result.state;
    assert.equal(result.projection.mode,"partial-editable");
  }
  assert.deepEqual(state.graph,immutable.graph);
  assert.deepEqual(state.editorLayout,immutable.editorLayout);
  assert.equal(state.activeView,"simple");
  assert.equal(state.editorLayout.resultRefs[0].runId,"run-123");
  assert.equal(Views.graphFieldPatches(complex,complex).length,0);
  assert.equal(Views.classify({nodes:[{id:"x",type:"mystery"}],edges:[]}).mode,
    "read-only-summary");

  const calls=[];
  const client=createClient({fetchImpl:async (_url,init)=>{
    calls.push(JSON.parse(init.body));
    return {ok:true,status:200,json:async()=>({ok:true,projectId:"proj-existing",revision:7})};
  },idFactory:()=>"edit-testkey"});
  const tab={projectId:"proj-existing",projectRevision:6,
    projectSyncedGraph:clone(complex), editRevision:4};
  const result=await client.flush(tab,{kind:"image",authority:"graph",title:"双分支",
    draft:{graph:patched,activeView:"simple",editorLayout:state.editorLayout}});
  assert.equal(result.ok,true);
  assert.equal(calls.length,1);
  assert.equal(calls[0].baseRevision,6);
  assert.ok(calls[0].patch.some(x=>x.path==="/graph/nodesById/n-text/data/text"));
  assert.ok(!calls[0].patch.some(x=>x.path==="/graph"),
    "simple edit must not replace an entire multi-branch graph");
  assert.deepEqual(tab.projectSyncedGraph,patched);
  assert.deepEqual(calls[0].patch.find(x=>x.path==="/editorLayout").value,state.editorLayout);

  // Spec Projects save only their structured authority until Canvas adoption.
  const authorityCalls=[];
  const transport=createClient({fetchImpl:async (_url,init)=>{
    authorityCalls.push(JSON.parse(init.body));
    return {ok:true,status:200,json:async()=>({ok:true,projectId:"project-spec-A",
      revision:2+authorityCalls.length})};
  },idFactory:()=> "idempotent-spec-107"});
  const specTab={projectId:"project-spec-A",projectRevision:2,
    projectAuthority:"spec",editRevision:2};
  const compiledSpec=Views.specFromGraph(compiled).spec;
  await transport.flush(specTab,{kind:"image",authority:"spec",title:"仅 Spec 可写",
    draft:{creationSpec:compiledSpec,activeView:"simple",editorLayout:{camera:{vx:12,vy:40,vk:.82}}}});
  assert.equal(specTab.projectAuthority,"spec");
  assert.ok(authorityCalls[0].patch.some(x=>x.path==="/creationSpec"));
  assert.ok(!authorityCalls[0].patch.some(x=>x.path==="/graph"));
  specTab.editRevision++;
  await transport.flush(specTab,{kind:"image",authority:"graph",title:"进入画布",
    draft:{graph:compiled,activeView:"canvas",editorLayout:{camera:{vx:12,vy:40,vk:.82}}}});
  assert.deepEqual(authorityCalls[1].patch.slice(0,2).map(x=>x.path),
    ["/authority","/graph"],"atomic transition must precede Graph write");
  assert.equal(specTab.projectAuthority,"graph");

  console.log("Studio #107 compile/partial/read-only, 10 switches, no Run, scoped CAS patches OK");
}
main().catch(err=>{console.error(err);process.exitCode=1;});
