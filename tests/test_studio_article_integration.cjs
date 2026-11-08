"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const I=require("../demo/assets/studio-article-integration.js");
const Core=require("../demo/assets/studio-core.js");
const Views=require("../demo/assets/studio-views.js");
const clone=x=>JSON.parse(JSON.stringify(x));
const fixture=n=>JSON.parse(fs.readFileSync("docs/studio-2.0/golden/"+n+".json","utf8"));

async function main() {
  const articleFixture=fixture("article").wire;
  const draft={id:"article-one",title:"杭州",markdown:"# 杭州\n\n龙井茶园",revision:3};
  const token=I.documentToken(draft);
  assert.equal(I.sameDocument(token,clone(draft)),true);
  assert.equal(I.sameDocument(token,{...draft,markdown:"# 杭州\n\n新的正文"}),false);
  assert.equal(I.sameDocument(token,{...draft,revision:4}),false);
  assert.equal(I.sameDocument(token,{...draft,id:"other"}),false);
  assert.throws(()=>I.assertCurrent(token,{...draft,title:"已修改"}),/article_document_conflict/);
  const cards=[
    {id:"cover-1",role:"cover",subject:"春天的封面",ratio:"2.35:1"},
    {id:"inline-1",role:"inline",subject:"龙井茶园",afterBlockIdx:1,
      layoutId:"SC-021",styleId:"FA-001",referenceMedia:[{mediaId:"private-owned",role:"scene"}],
      lockedFields:["ratio"],mediaId:"result-owned"}
  ];
  const article=I.articleFromDraft(draft,cards);
  const plan=I.articlePlan(article,cards,{planId:"plan-article",revision:8});
  assert.deepEqual(plan.slots.map(s=>s.slotId),["cover-1","inline-1"]);
  assert.deepEqual(plan.slots.map(s=>s.anchorId),article.anchors.map(a=>a.anchorId));
  assert.equal(plan.slots[1].overrides.layout.type,"layout");
  assert.equal(plan.slots[1].overrides.style.id,"FA-001");
  assert.equal(plan.slots[1].referenceMedia[0].mediaId,"private-owned");
  assert.equal(plan.slots[1].resultMediaId,"result-owned");
  assert.equal(plan.documentRevision,3);
  const node={id:"article-plan-node",type:"article_plan",data:{documentId:"article-one",note:"keep-me"}};
  const graph={
    revision:5,blueprint:"article",nodes:[
      {id:"s",type:"skill_params",data:{style1:"FA-001"}},
      {id:"t",type:"text_input",data:{text:"这是画布内容"}},
      {id:"a",type:"asset",data:{items:[{mediaId:"private-owned",role:"scene"}]}},
      {id:"f",type:"fission",data:{count:3}},
      {id:"bridge",type:"bridge",data:{foo:"bar"}},
      {id:"loop",type:"loop",data:{loopMode:"prompts"}},
      {id:"note",type:"sticky_note",data:{text:"勿改"}},
      {id:"out-a",type:"output_control",data:{mode:"article-illust",ratio:"3:4",
        runId:"run-a",studio2RunSnapshot:{outputs:[{slotId:"a",outputId:"s-a",outputIndex:0}]} }},
      {id:"out-b",type:"output_control",data:{mode:"pure",ratio:"9:16",
        runId:"run-b",studio2RunSnapshot:{outputs:[{slotId:"b",outputId:"s-b",outputIndex:0}]} }},
      node
    ],
    edges:[
      {id:"edge-1",from:"s",to:"bridge",fromPort:"out-style",toPort:"input-style"},
      {id:"edge-2",from:"bridge",to:"out-a",fromPort:"output:1",toPort:"input"},
      {id:"edge-3",from:"loop",to:"out-b",fromPort:"out",toPort:"input"},
      {id:"edge-4",from:"f",to:"loop",fromPort:"output",toPort:"prompt"}
    ],
    groups:[{id:"group-a",nodeIds:["out-a","out-b"]}],
    runRefs:[{runId:"run-a",nodeId:"out-a",mediaId:"result-owned"}],
    selectedIds:["note"]
  };
  const original=clone(graph);
  const linked=I.linkArticleGraph(graph,article,plan,{nodeId:"article-plan-node"});
  assert.deepEqual(graph,original,"adapter does not modify source Graph");
  assert.deepEqual(linked.edges,original.edges,"typed ports are intact");
  assert.deepEqual(linked.groups,original.groups);
  assert.deepEqual(linked.runRefs,original.runRefs);
  assert.deepEqual(linked.nodes.filter(n=>n.id!=="article-plan-node"),
    original.nodes.filter(n=>n.id!=="article-plan-node"),"all execution nodes untouched");
  const link=linked.nodes.find(n=>n.id==="article-plan-node");
  assert.equal(link.data.note,"keep-me");
  assert.deepEqual(link.data.slotRefs,plan.slots.map(s=>({slotId:s.slotId,anchorId:s.anchorId})));
  assert.equal(I.safeGraphView(linked).mode,"read-only-summary");
  assert.throws(()=>I.linkArticleGraph(graph,{...article,revision:4},plan,
    {nodeId:"article-plan-node"}),/article_revision_mismatch/);
  for(let i=0, view={graph:clone(linked),activeView:"canvas"};i<10;i++){
    const next=Views.switchView(view,i%2?"canvas":"simple");
    view=next.state;
    assert.deepEqual(view.graph,linked,"ten switches preserve every Graph field");
    assert.equal(next.projection.mode,"read-only-summary");
  }
  const refs=I.graphRunRefs(linked);
  assert.deepEqual(refs.map(ref=>ref.runId),["run-a","run-b"]);
  const started=[], callbacks={};
  const promise=I.recoverGraphRuns(linked,id=>{
    started.push(id);
    return new Promise(resolve=>{callbacks[id]=resolve;});
  });
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(started,["run-a","run-b"],"both outputs recover in parallel");
  callbacks["run-b"]({ok:true,run:{id:"run-b",status:"success",source:"web"},
    items:[{id:"item-b",slotIndex:0,position:0,status:"success",mediaId:"media-b"}]});
  callbacks["run-a"]({ok:true,run:{id:"run-a",status:"success",source:"web"},
    items:[{id:"failed-a",slotIndex:0,position:0,status:"failed"},
      {id:"retry-a",slotIndex:0,position:1,status:"generating"},
      {id:"item-a",slotIndex:0,position:2,status:"success",mediaId:"media-a"}]});
  const recovered=await promise;
  assert.equal(recovered["out-a"].projection.succeeded,1);
  assert.equal(recovered["out-a"].projection.viewStatus,"partial");
  assert.equal(recovered["out-b"].projection.succeeded,1);
  assert.equal(recovered["out-a"].outputs[0].items[2].id,"item-a");
  assert.equal(recovered["out-b"].outputs[0].slotId,"b");
  const both=clone(linked);
  both.nodes.find(n=>n.id==="out-b").data.runId="run-a";
  both.nodes.find(n=>n.id==="out-b").data.studio2RunSnapshot.runId="run-a";
  let requested=0;
  await I.recoverGraphRuns(both,async id=>{
    requested++;
    return {ok:true,run:{id,status:"success",source:"web"},
      items:[{id:"item-a",slotIndex:0,position:0,status:"success",mediaId:"media-a"}]};
  });
  assert.equal(requested,1,"same owner Run is fetched once");
  await assert.rejects(I.recoverGraphRuns(linked,async()=>({ok:true,
    run:{id:"a-different-run"},items:[]})),/unverified_run_response/);
  assert.equal(Core.selectRunProjection({id:"r",status:"partial",source:"web"},
    [{position:0,status:"success",mediaId:"m1"},{position:1,status:"generating"}],
    {expectedCount:1}).succeeded,1);
  const source=fixture("image").wire.creationSpec;
  const compiled=Views.compile(source,null,{projectId:"issue124"});
  assert.equal(Views.classify(compiled).mode,"simple-editable");
  const series=fixture("series").wire;
  const seriesGraph=Views.compile(series.creationSpec,series.plan,{projectId:"issue124-series"});
  assert.deepEqual(seriesGraph.nodes.find(n=>n.type==="loop").data.studio2SlotIds,
    series.plan.slots.map(s=>s.slotId),"all series slots stable");
  assert.deepEqual(articleFixture.plan.slots.map(s=>s.anchorId),
    articleFixture.article.anchors.map(a=>a.anchorId));
  console.log("Studio #124 article/canvas integrity and parallel run recovery: OK");
}
main().catch(err=>{console.error(err);process.exitCode=1;});
