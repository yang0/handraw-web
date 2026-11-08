"use strict";
/* Issue #123: PlanSlot authority and 6x2 RunProjection end-to-end contracts. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const Core=require("../demo/assets/studio-core.js");
const N=require("../demo/assets/studio-normalization.js");
const Resources=require("../demo/assets/studio-resources.js");
const Series=require("../demo/assets/studio-series-plan.js");
const clone=x=>JSON.parse(JSON.stringify(x));
const entries=[
  {id:"FA-001",kind:"style",source:"official",version:1,name:"水彩"},
  {id:"FA-002",kind:"style",source:"official",version:1,name:"漫画"},
  {id:"SC-021",kind:"layout",source:"official",version:1,name:"双拼"},
  {id:"SC-022",kind:"layout",source:"official",version:1,name:"签名"}
];
const catalog={resourceMap:new Map(entries.map(x=>[x.id,x])),
  styles:entries.filter(x=>x.kind==="style"),
  layouts:entries.filter(x=>x.kind==="layout"),colors:[],tones:[]};
const options={catalog,isUnlocked:()=>true};
const loop={id:"loop-series-123",type:"loop",data:{
  loopMode:"prompts",batchLayoutMode:"fixed",batchCount:6,batchConcurrency:4,
  promptListText:"封面\n城市清晨\n咖啡\n街头花店\n落日\n尾声",
  batchRows:[]}};
const first=Series.read(loop);
assert.equal(first.slots.length,6);
assert.equal(new Set(first.slots.map(s=>s.slotId)).size,6);
assert.ok(first.slots.every(s=>!/^([0-9]+)$/.test(s.slotId)));
assert.deepEqual(loop.data.studio2SlotIds,first.slots.map(s=>s.slotId));
assert.deepEqual(N.normalizePlan(first).slots.map(s=>s.slotId),first.slots.map(s=>s.slotId));
const stable=first.slots.map(s=>s.slotId);
const third=stable[2],refs=[{id:"owned-scene",mediaId:"owned-scene",role:"scene",
 image:"/assets/scene.webp",source:"private"}];
Series.patchSlot(loop,third,{overrides:{
  style:"FA-002",layout:"SC-022",ratio:"2.35:1"
},referenceMedia:refs,skipGlobalRefs:true},options);
assert.equal(Series.read(loop).slots[2].overrides.layout.id,"SC-022");
assert.equal(Series.read(loop).slots[2].overrides.style.id,"FA-002");
assert.equal(Series.read(loop).slots[2].overrides.ratio,"2.35:1");
assert.equal(Series.read(loop).slots[2].referenceMedia[0].mediaId,"owned-scene");
assert.equal(Series.read(loop).slots[2].skipGlobalRefs,true);
assert.equal(Series.read(loop).slots[1].overrides.layout,undefined);
assert.equal(Series.read(loop).slots[3].referenceMedia.length,0);
const before=clone(loop.data);
assert.throws(()=>Series.patchSlot(loop,third,{overrides:{layout:"FA-002"}},options),
 /resource_not_found|invalid_resource/);
assert.deepEqual(loop.data,before,"failed override is atomic");
assert.throws(()=>Series.patchSlot(loop,third,{overrides:{ratio:"0:1"}},options),/invalid_ratio/);
const stale={...options,baseRevision:Series.read(loop).revision-1};
assert.throws(()=>Series.patchSlot(loop,third,{subject:"cannot"},stale),
 /plan_revision_conflict/);
Series.patchSlot(loop,third,{lockedFields:["subject","layout","style"]},options);
assert.throws(()=>Series.patchSlot(loop,third,{overrides:{layout:"SC-021"}},options),
 /locked_field/);
assert.throws(()=>Series.patchSlot(loop,third,{subject:"AI override"},options),
 /locked_field/);
// Return fixed -> AI -> fixed -> AI without deleting any manual override.
for(const mode of ["ai","fixed","ai","fixed"]){
  const p=Series.switchMode(loop,mode);
  assert.deepEqual(p.slots.map(s=>s.slotId),stable);
  assert.equal(p.slots[2].overrides.layout.id,"SC-022");
  assert.equal(p.slots[2].overrides.style.id,"FA-002");
  assert.equal(p.slots[2].referenceMedia[0].mediaId,"owned-scene");
  assert.ok(p.slots[2].lockedFields.includes("layout"));
}
const prior=Series.read(loop);
Series.mergeAI(loop,prior.slots.map((s,i)=>({
  slotId:s.slotId,subject:i===2?"replan must not overwrite locked":"AI "+i,
  layout:i===2?"SC-021":"SC-021"
})),"ai",options);
assert.equal(Series.read(loop).slots[2].subject,"咖啡","locked/manual subject stays");
assert.equal(Series.read(loop).slots[2].overrides.layout.id,"SC-022");
assert.equal(Series.read(loop).slots[2].referenceMedia[0].mediaId,"owned-scene");
assert.equal(Series.read(loop).slots[0].subject,"AI 0");
const idsBefore=Series.read(loop).slots.map(s=>s.slotId);
Series.updateText(loop,"新序章\n"+Series.read(loop).slots.map(s=>s.subject).join("\n"));
assert.deepEqual(Series.read(loop).slots.slice(1).map(s=>s.slotId),idsBefore,
 "inserting at top preserves original IDs via LCS");
const thirdNewIndex=Series.read(loop).slots.findIndex(s=>s.slotId===third);
assert.equal(thirdNewIndex,3);
Series.move(loop,third,2);
assert.equal(Series.read(loop).slots[2].slotId,third);
const copied=Series.duplicate(loop,third);
assert.equal(copied.slots.length,8);
assert.notEqual(copied.slots[3].slotId,third);
assert.equal(copied.slots[3].overrides.layout.id,"SC-022");
assert.deepEqual(copied.slots[3].lockedFields,[]);
Series.remove(loop,copied.slots[3].slotId);
Series.remove(loop,Series.read(loop).slots[0].slotId);
assert.equal(Series.read(loop).slots.length,6);
assert.deepEqual(Series.read(loop).slots.map(s=>s.slotId),idsBefore.slice().map(id=>id).sort((a,b)=>
  Series.read(loop).slots.findIndex(x=>x.slotId===a)-Series.read(loop).slots.findIndex(x=>x.slotId===b)));
const serialized=clone(loop);
assert.deepEqual(Series.read(serialized),Series.read(loop),"reload keeps IDs/overrides");
assert.ok(Core.normalizeLegacyBatch(loop).slots.some(s=>s.slotId===third),
 "Core reads authoritative PlanSlot IDs after independent reordering and removal");
// Validate actual execution against unified catalog, not a placeholder layout.
const parts={
 skill:{type:"skill_params",data:{style1:"FA-001",style2:"",
  fusion:false,layout:"SC-021",colors:[],tones:[]}},
 text:{type:"text_input",data:{text:"全局系列"}},
 ctrl:{type:"output_control",data:{mode:"graphic-text",ratio:"3:4",ratioSource:"user"}},
 asset:{type:"asset",data:{items:[]}},loop
};
assert.equal(Series.validateForExecution(parts,options).ok,true,
 JSON.stringify(Series.validateForExecution(parts,options).errors));
const noStyle=clone(parts);noStyle.skill.data.style1="";
assert.equal(Series.validateForExecution(noStyle,options).ok,false);
const denied={...options,catalog:{...catalog,resourceMap:new Map(catalog.resourceMap)}};
denied.catalog.resourceMap.set("FA-001",{...catalog.resourceMap.get("FA-001"),canUse:false});
assert.equal(Series.validateForExecution(parts,denied).ok,false);
const original=Series.read(loop);
Series.setCandidates(loop,2);
const snap=Series.freeze(loop,"","batch-123");
assert.equal(snap.slotCount,6);assert.equal(snap.candidateCount,2);
assert.equal(snap.outputCount,12);
assert.equal(snap.outputs.length,12);
assert.equal(new Set(snap.outputs.map(s=>s.outputId)).size,12);
const thirdOutputIndex=Series.read(loop).slots.findIndex(s=>s.slotId===third)*2;
assert.ok(thirdOutputIndex>=0);
assert.deepEqual(snap.outputs.slice(thirdOutputIndex,thirdOutputIndex+2).map(x=>x.slotId),[third,third]);
assert.deepEqual(snap.outputs.slice(thirdOutputIndex,thirdOutputIndex+2).map(x=>x.candidateIndex),[0,1]);
const frozen=JSON.stringify(snap);
Series.patchSlot(loop,third,{overrides:{ratio:"9:16"}}, {...options,unlock:true});
Series.switchMode(loop,"ai");
assert.equal(JSON.stringify(snap),frozen,"draft edits do not touch RunSnapshot");
const mk=(pos,status,media)=>{
  return {id:"item-"+pos,position:pos*1000,slotIndex:pos,status,
    mediaId:media?("owned-"+pos):"",imageUrl:media?"/generated/"+pos+".webp":""};
};
const data=[mk(5,"generating"),mk(3,"failed"),mk(2,"success",true),
 mk(0,"success",true),mk(4,"failed"),mk(1,"success",true)];
const run={id:"run-123",source:"web",status:"running",expectedCount:12};
const projection=Series.project(snap,run,data);
assert.equal(projection.total,12);
assert.equal(projection.succeeded,3);
assert.equal(projection.failed,2);
assert.equal(projection.generating,1);
assert.equal(projection.queued,6);
assert.equal(projection.isTerminal,false);
assert.deepEqual(projection.results.map(x=>x.outputIndex),[0,1,2]);
assert.equal(projection.outputs[3].status,"failed");
assert.equal(projection.outputs[4].status,"failed");
assert.equal(projection.outputs[2].imageUrl,"/generated/2.webp");
assert.equal(projection.outputs[3].slotId,snap.outputs[3].slotId);
const repeat=Series.project(snap,run,[...data,mk(2,"success",true)]);
assert.equal(repeat.succeeded,3,"duplicate success callback not double-counted");
assert.equal(repeat.results.length,3);
const retried=Series.project(snap,{...run,status:"partial"},[
  ...data.filter(x=>x.slotIndex!==3),mk(3,"success",true)
]);
assert.equal(retried.succeeded,4);
assert.equal(retried.failed,1);
assert.equal(retried.outputs[2].imageUrl,"/generated/2.webp",
 "other successful items unchanged on one failed-slot retry");
// Run projection must not infer a successful output from image URL alone.
const unowned=Series.project(snap,run,[mk(0,"success",false)]);
assert.equal(unowned.succeeded,0);
assert.equal(unowned.results.length,0);

// Exercise the existing prompt engine's Loop projection with real overrides.
const sandbox={console,Map,Set,Array,Number,Math,JSON,Date};
sandbox.window=sandbox;sandbox.globalThis=sandbox;
sandbox.HANDRAW_SHARED={};
vm.runInNewContext(fs.readFileSync("demo/assets/studio-prompt-engine.js","utf8"),sandbox);
const E=sandbox.HANDRAW_CANVAS_ENGINE;
assert.ok(E?.resolveLoopIterations);
const skill=E.makeSkillParamsNode(0,0,parts.skill.data);
const text=E.makeTextInputNode(0,0,{text:""});
const ctrl=E.makeOutputControlNode(0,0,parts.ctrl.data);
const ast=E.makeAssetNode(0,0,{items:[]});
const graph={nodes:[skill,text,ast,loop,ctrl],edges:[
  {id:"sl",from:skill.id,to:loop.id},{id:"sc",from:skill.id,to:ctrl.id},
  {id:"lc",from:loop.id,to:ctrl.id},{id:"al",from:ast.id,to:loop.id},
  {id:"ac",from:ast.id,to:ctrl.id}
]};
const rec=E.resolveControlRecipe(graph,ctrl,catalog);
const iter=E.resolveLoopIterations(graph,loop,rec,catalog);
assert.equal(iter.length,6);
const thirdIter=iter.find(item=>item.slotId===third);
assert.ok(thirdIter,"the same PlanSlot ID remains addressable after reorder/remove");
assert.equal(thirdIter.style1,"FA-002");
assert.equal(thirdIter.layout,"SC-022");
assert.equal(thirdIter.ratio,"9:16");
assert.equal(thirdIter.assetItems[0].mediaId,"owned-scene");
const prompt=E.assembleControlPrompt(graph,ctrl,catalog,"cloud",{
  fromLoop:true,style1:thirdIter.style1,layout:thirdIter.layout,
  ratio:thirdIter.ratio,assetItems:thirdIter.assetItems,theme:thirdIter.theme
});
assert.ok(prompt.includes("FA-002")&&prompt.includes("SC-022")&&prompt.includes("9:16"));
const html=fs.readFileSync("demo/studio.html","utf8");
assert.ok(html.indexOf("studio-normalization.js")<html.indexOf("studio-series-plan.js"));
assert.ok(html.indexOf("studio-series-plan.js")<html.indexOf("studio-batch.js"));
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
assert.match(app,/const isStudio2Series=Boolean\(rec\.loopNode\.data\?\.studio2Plan\?\.slots\)/);
assert.match(app,/slotId:sp\.slotId\|\|""/);
assert.match(app,/studio2RunSnapshot=\{/);
assert.match(app,/previousRunSnapshot\.executionGraph/);
assert.match(app,/getBatchRunProjection\(bp\)/);
assert.match(app,/\/api\/studio\/runs\//);
assert.match(app,/retryCancelled: resolvedOnlyIdx !== null/);
assert.match(app,/batchTotal: plan\.specs\.length/);
const UI=fs.readFileSync("demo/assets/studio-batch.js","utf8");
assert.match(UI,/data-row-options-idx/);
assert.match(UI,/data-row-copy-idx/);
assert.match(UI,/data-row-up-idx/);
assert.match(UI,/id="batch-candidates"/);
assert.match(UI,/getSeries\(\)\.mergeAI/);
console.log("Issue #123: 6 PlanSlots, 12 outputs, IDs/overrides/locks, fixed-AI roundtrips, LCS insert/reorder/clone, V3 3+2+1 and retry PASS");
