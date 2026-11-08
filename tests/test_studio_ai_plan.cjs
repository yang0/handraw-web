"use strict";
const assert=require("node:assert/strict");
const AI=require("../demo/assets/studio-ai-plan.js");
const Quick=require("../demo/assets/studio-quick-spec.js");
const Series=require("../demo/assets/studio-series-plan.js");
const clone=x=>JSON.parse(JSON.stringify(x));
const resource=(id,kind)=>({id,kind,source:"official",version:1,
  canUse:true,access:{canUse:true}});
const resources=[resource("FA-001","style"),resource("FA-002","style"),
  resource("SC-021","layout"),resource("SC-022","layout")];
const catalog={resourceMap:new Map(resources.map(r=>[r.id,r])),
  styles:resources.filter(r=>r.kind==="style"),
  layouts:resources.filter(r=>r.kind==="layout"),colors:[],tones:[]};
const opts={catalog,isUnlocked:()=>true};
const ref=(id,type)=>({id,type,source:"official",version:1});
const makeParts=(style="",layout="",ratio="3:4")=>({
  skill:{id:"s",type:"skill_params",data:{style1:style,layout,resourceRefs:{},
    unrelated:"keep"}},
  text:{id:"t",type:"text_input",data:{text:"江南春天",userHint:"keep"}},
  ctrl:{id:"c",type:"output_control",data:{ratio,ratioSource:"default",mode:"graphic-text",
    runId:"old-run",unrelated:"keep"}},
  asset:{id:"a",type:"asset",data:{items:[{mediaId:"private-owned",source:"private"}]}}
});
const proposal=(kind="image",spec={},slots=[],revision=0,planRevision=0)=>({
  ok:true,schemaVersion:1,kind,source:"model",phase:"review",baseRevision:revision,
  creationSpecPatch:{baseRevision:revision,
    changes:{style:ref("FA-002","style"),layout:ref("SC-022","layout"),ratio:"1:1",...spec},
    reasons:{style:"适合光线",layout:"适合分镜",ratio:"适合小红书"},
    candidates:{style:[{id:"FA-002"}],layout:[{id:"SC-022"}]}},
  planPatch:kind==="image"?null:{baseRevision:planRevision,
    kind:kind==="article"?"article":"story-series",slots},
  cost:{generationStarted:false,runCreated:false}
});
const slot=(id,i,kind="series")=>({
  slotId:id,order:i,subject:"建议主题"+i,
  overrides:{layout:ref("SC-022","layout"),ratio:"1:1"},
  reasons:{subject:"内容关联",layout:"图型适合",ratio:"画幅适合"},
  ...(kind==="article"?{role:i===0?"cover":"illustration",
    anchorId:i===0?"cover":"p-"+i,afterBlockIdx:i===0?-1:i,
    anchorText:"段落"+i,purpose:"提升阅读理解",imageType:"scene"}:{})
});
(function blankImageAndUndo(){
  const p=makeParts(),before=clone(p),rev=Quick.read(p).spec.revision;
  const report=AI.review(proposal("image",{},[],rev),{
    kind:"image",baseRevision:rev,currentSpec:Quick.read(p).spec,...opts});
  assert.equal(report.conflicts.length,0);
  assert.ok(report.accepted.some(x=>x.field==="style"));
  const saved=AI.apply(report,{parts:p,...opts});
  assert.equal(Quick.read(p).spec.style.id,"FA-002");
  assert.equal(Quick.read(p).spec.layout.id,"SC-022");
  assert.equal(Quick.read(p).spec.ratio,"1:1");
  assert.deepEqual(p.asset,before.asset,"private media references unchanged");
  assert.equal(p.ctrl.data.runId,"old-run");
  assert.ok(saved.undo);
  assert.equal(AI.undo(saved.undo,{parts:p}),true);
  assert.equal(p.skill.data.style1,"");
  assert.equal(p.skill.data.layout,"");
  assert.equal(p.ctrl.data.ratio,"3:4");
  assert.equal(p.ctrl.data.runId,"old-run");
  assert.ok(Quick.read(p).spec.revision>rev+1,"undo advances rather than rewinds CAS");
  assert.throws(()=>AI.apply(report,{parts:p,...opts}),/ai_revision_conflict/);
})();
(function manualAndLocks(){
  const p=makeParts("FA-001","SC-021","9:16");
  p.ctrl.data.ratioSource="user";
  p.skill.data.lockedFields=["style"];
  const spec=Quick.read(p).spec,rev=spec.revision;
  const report=AI.review(proposal("image",{},[],rev),{
    kind:"image",baseRevision:rev,currentSpec:spec,...opts});
  assert.deepEqual(report.conflicts.map(c=>c.key).sort(),["layout","ratio","style"]);
  assert.ok(report.conflicts.find(x=>x.key==="style").locked);
  const saved=clone(p);
  const empty=AI.apply(report,{parts:p,approvedKeys:["style"],...opts});
  assert.equal(empty.undo,null);
  assert.deepEqual(p,saved);
  const explicit=AI.apply(report,{parts:p,approvedKeys:["layout","ratio"],...opts});
  assert.equal(p.skill.data.style1,"FA-001","locked style not overridden");
  assert.equal(p.skill.data.layout,"SC-022","explicit review allows manual layout replacement");
  assert.equal(p.ctrl.data.ratio,"1:1");
  p.text.data.text="changed after proposal";
  assert.throws(()=>AI.undo(explicit.undo,{parts:p}),/ai_undo_conflict/);
})();
(function seriesSixSlotsPreserveManualOverrides(){
  const p=makeParts();
  const loop={id:"loop",type:"loop",data:{loopMode:"prompts",
    batchLayoutMode:"ai",promptListText:"封面\n街头\n人物\n日落\n咖啡\n结尾",batchRows:[]}};
  p.loop=loop;
  let plan=Series.read(loop);
  const ids=plan.slots.map(s=>s.slotId);
  Series.patchSlot(loop,ids[1],{overrides:{layout:"SC-021"},
    referenceMedia:[{mediaId:"private-2",role:"scene",source:"private"}],
    lockedFields:["subject","layout"]},{...opts,unlock:true});
  plan=Series.read(loop);
  const rev=Quick.read(p).spec.revision,planRevision=plan.revision;
  const response=proposal("series",{},ids.map((id,i)=>slot(id,i)),rev,planRevision);
  const report=AI.review(response,{kind:"series",baseRevision:rev,planRevision,
    currentSpec:Quick.read(p).spec,currentPlan:plan,...opts});
  assert.ok(report.conflicts.some(c=>c.key==="slot:"+ids[1]+":subject"&&c.locked));
  assert.ok(report.conflicts.some(c=>c.key==="slot:"+ids[1]+":layout"&&c.locked));
  const history=clone(p),applied=AI.apply(report,{parts:p,loop,...opts});
  assert.equal(Series.read(loop).slots.length,6);
  assert.deepEqual(Series.read(loop).slots.map(s=>s.slotId),ids);
  assert.equal(Series.read(loop).slots[1].subject,plan.slots[1].subject);
  assert.equal(Series.read(loop).slots[1].overrides.layout.id,"SC-021");
  assert.equal(Series.read(loop).slots[1].referenceMedia[0].mediaId,"private-2");
  assert.equal(Series.read(loop).slots[0].overrides.layout.id,"SC-022");
  assert.deepEqual(p.asset,history.asset);
  assert.equal(AI.undo(applied.undo,{parts:p,loop}),true);
  assert.equal(Series.read(loop).slots[0].subject,plan.slots[0].subject);
  assert.equal(Series.read(loop).slots[1].referenceMedia[0].mediaId,"private-2");
  assert.ok(Series.read(loop).revision>planRevision+1);
  assert.throws(()=>AI.apply(report,{parts:p,loop,...opts}),/ai_revision_conflict/);
})();
(function articleCardAnchorAndResults(){
  const slots=[slot("old-cover",0,"article"),slot("old-inline",1,"article")];
  const response=proposal("article",{},slots,4,2);
  const previous=[{id:"old-cover",role:"cover",subject:"人工封面",layoutId:"SC-021",
      ratio:"2.35:1",imageUrl:"/generated/owned.webp",runId:"run-private",
      lockedFields:["subject"],userOverrides:["ratio"]},
    {id:"old-inline",role:"inline",afterBlockIdx:1,subject:"人工插图",
      layoutId:"SC-021",ratio:"4:3",imageUrl:"/generated/private.webp",
      referenceMedia:[{mediaId:"private-scene",source:"private"}],
      lockedFields:["layout"],userOverrides:["subject"]}];
  const currentPlan={slots:previous.map((card,i)=>({slotId:card.id,order:i,
      subject:card.subject,overrides:{layout:ref("SC-021","layout"),ratio:card.ratio},
      lockedFields:card.lockedFields,userOverrides:card.userOverrides,
      referenceMedia:card.referenceMedia||[]}))};
  const report=AI.review(response,{kind:"article",baseRevision:4,planRevision:2,
    currentSpec:{style:null,layout:null,ratio:"3:4"},currentPlan,...opts});
  const legacy=AI.articleLegacy(report);
  assert.equal(legacy.illustrations[0].afterBlockIdx,1);
  assert.equal(legacy.illustrations[0].layout,"SC-022");
  const suggested=[{id:"fresh",role:"cover",subject:"AI 封面"},
    {id:"fresh2",role:"inline",subject:"AI 插图",afterBlockIdx:1}];
  const merged=AI.mergeArticleCards(report,previous,suggested,[]);
  assert.equal(merged[0].subject,"人工封面");
  assert.equal(merged[0].imageUrl,"/generated/owned.webp");
  assert.equal(merged[0].runId,"run-private");
  assert.equal(merged[1].subject,"人工插图");
  assert.equal(merged[1].layoutId,"SC-021");
  assert.equal(merged[1].referenceMedia[0].mediaId,"private-scene");
  assert.equal(merged[1].anchorId,"p-1");
})();
(function failClosed(){
  const p=makeParts(),rev=Quick.read(p).spec.revision;
  const previous=clone(p);
  const bad=proposal("image",{},[],rev);
  bad.creationSpecPatch.changes.style={...bad.creationSpecPatch.changes.style,id:"FA-999"};
  assert.throws(()=>AI.review(bad,{kind:"image",baseRevision:rev,
    currentSpec:Quick.read(p).spec,...opts}),/resource_not_found/);
  assert.deepEqual(p,previous);
  const deniedCatalog={...catalog,resourceMap:new Map(catalog.resourceMap)};
  deniedCatalog.resourceMap.set("FA-002",{...catalog.resourceMap.get("FA-002"),canUse:false});
  assert.throws(()=>AI.review(proposal("image",{},[],rev),{
    kind:"image",baseRevision:rev,currentSpec:Quick.read(p).spec,
    catalog:deniedCatalog}),/resource_forbidden/);
  const stale=proposal("image",{},[],rev-1);
  assert.throws(()=>AI.review(stale,{kind:"image",baseRevision:rev,
    currentSpec:Quick.read(p).spec,...opts}),/ai_invalid_proposal/);
  const invalid=proposal("image",{},[],rev);invalid.cost.runCreated=true;
  assert.throws(()=>AI.review(invalid,{kind:"image",baseRevision:rev,
    currentSpec:Quick.read(p).spec,...opts}),/ai_invalid_proposal/);
})();
console.log("Issue #125: AI proposals, field reasons/locks, 6 slots, CAS, undo, private media and article anchors PASS");
