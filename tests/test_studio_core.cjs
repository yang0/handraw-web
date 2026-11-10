"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const Core = require("../demo/assets/studio-core.js");
const DIR = "docs/studio-2.0/fixtures";
const read = (n) => JSON.parse(fs.readFileSync(DIR + "/" + n + ".json", "utf8"));
const scenarios = ["image", "series", "article", "canvas"];
for (const k of scenarios) {
  const v = read(k);
  assert.equal(v.schemaVersion, 1);
  assert.equal(v.creationSpec.style.type, "style");
  assert.equal(typeof v.creationSpec.ratio, "string");
  assert.ok(v.project.id);
}
const p = { skill: { data: { style1: "FA-001", style2: "FA-002", fusion: false, layout: "SC-021",
  colors: ["CL-001"], tones: ["TN-001"], moods: ["治愈"], customMood: "松弛", whitespace: "high",
  sc021Type: "双屏撕画", sc022Name: "张三", sc022Pinyin: "zhang san" } },
  text: { data: { text: "杭州春日" } },
  ctrl: { data: { mode: "poster", ratio: "2.35:1" } },
  asset: { data: { items: [{ mediaId: "my-private-ref", role: "character" }, { dataUrl: "local-only" }] } } };
let model = Core.normalizeLegacyParts(p);
assert.equal(model.spec.ratioSource, "user");
assert.equal(model.spec.style.id, "FA-001");
assert.equal(model.spec.referenceMedia[0].mediaId, "my-private-ref");
assert.equal(model.warnings[0].code, "unresolved_local_media");
assert.deepEqual(model.spec.layoutParams, { sc021Type: "双屏撕画", sc022Name: "张三", sc022Pinyin: "zhang san" });
const serialized = JSON.parse(JSON.stringify(model.spec));
Core.applyLegacySpec(p, serialized);
assert.equal(p.ctrl.data.ratioSource, "user");
assert.equal(p.skill.data.style2, "FA-002"); // disabled fusion is draft only
assert.equal(p.asset.data.items.length, 2); // no local image lost
assert.deepEqual(Core.normalizeLegacyParts(p).spec, model.spec);
Core.setMode(p.ctrl.data, "pure");
assert.equal(p.ctrl.data.ratio, "2.35:1"); // explicit user's choice survives mode
Core.setRatio(p.ctrl.data, "1:1");
Core.setMode(p.ctrl.data, "poster");
assert.equal(p.ctrl.data.ratio, "1:1");
Core.setMode({mode:"pure",ratio:"3:4"}, "poster");
assert.equal(Core.setMode({mode:"pure",ratio:"3:4"}, "poster").ratio, "9:16");
assert.ok(!Core.validateRatio("0:1").ok);
assert.ok(!Core.validateRatio("foo").ok);
assert.ok(Core.validateRatio("2.35:1").ok);
const cat = { resourceMap: new Map([
 ["FA-001",{id:"FA-001",kind:"style"}],["SC-021",{id:"SC-021",kind:"layout"}],
 ["CL-001",{id:"CL-001",kind:"color"}],["TN-001",{id:"TN-001",kind:"tone"}]
])};
assert.ok(Core.validateSpec(serialized, {catalog:cat}).ok);
assert.ok(Core.validateSpec({...serialized,style:{id:"nonexistent",type:"style"}},{catalog:cat}).errors.some(x=>x.code==="invalid_resource"));
assert.ok(Core.validateSpec({...serialized,style:null}).errors.some(x=>x.code==="missing_style"));
const next = Core.applySpecPatch({...serialized,revision:7,lockedFields:[]},{subject:"春季新图",ratio:"4:3"},7);
assert.equal(next.revision,8);
assert.equal(serialized.subject,"杭州春日");
assert.throws(()=>Core.applySpecPatch(next,{subject:"test"},7),/revision_conflict/);
assert.throws(()=>Core.applySpecPatch({...next,lockedFields:["subject"]},{subject:"test"},8),/locked_field/);
assert.equal(Core.resolveEffectiveSpec(serialized,{overrides:{ratio:"9:16"}}).ratio,"9:16");
const legacy = { data: { id: "loop-1", batchLayoutMode: "fixed", promptListText: "第一张\n第二张\n第三张" } };
const first = Core.normalizeLegacyBatch(legacy);
assert.equal(first.slots.length,3);
Core.pinLegacySlotIds(legacy,first);
legacy.data.promptListText="第一张修订\n第二张\n第三张";
assert.equal(Core.normalizeLegacyBatch(legacy).slots[0].slotId,first.slots[0].slotId);
legacy.data.batchLayoutMode="ai";
legacy.data.batchRows=[{theme:"第一张",layout:"SC-021"},{theme:"第二张"},{theme:"第三张"}];
assert.equal(Core.normalizeLegacyBatch(legacy).slots[0].slotId,first.slots[0].slotId);
assert.equal(Core.normalizeLegacyBatch(legacy).slots[0].overrides.layout.id,"SC-021");
// AI replan: slot identity, private reference selection, manual overrides and
// explicit locks must survive. Undo also restores stable slot revisions.
const prevPlan = {data:{id:"loop-2",batchLayoutMode:"ai",planRevision:1,
  studio2SlotIds:["slot-a","slot-b"],
  batchRows:[
    {slotId:"slot-a",theme:"手工主题",layout:"SC-021",assetItems:[{mediaId:"private-a",role:"character"}],
      skipGlobalRefs:true,lockedFields:["subject","layout"]},
    {slotId:"slot-b",theme:"旧主题",layout:"SC-021",assetItems:[{mediaId:"private-b",role:"scene"}]}
  ]}};
const replanned = Core.mergeLegacyPlanRows(prevPlan,[
  {subject:"AI 想覆盖",layout:"SC-022"},{subject:"新的第二张",layout:"SC-022"}
],"ai");
assert.equal(replanned.batchRows[0].slotId,"slot-a");
assert.equal(replanned.batchRows[0].theme,"手工主题");
assert.equal(replanned.batchRows[0].layout,"SC-021");
assert.equal(replanned.batchRows[0].assetItems[0].mediaId,"private-a");
assert.equal(replanned.batchRows[0].skipGlobalRefs,true);
assert.equal(replanned.batchRows[1].theme,"新的第二张");
assert.equal(replanned.batchRows[1].layout,"SC-022");
assert.equal(replanned.batchRows[1].slotId,"slot-b");
assert.equal(replanned.planRevision,2);
const fixedReplan=Core.mergeLegacyPlanRows(prevPlan,[{subject:"新一"},{subject:"新二"}],"fixed");
assert.equal(fixedReplan.batchRows[1].layout,"SC-021");
prevPlan.data.batchRows=replanned.batchRows;
Core.pinLegacySlotIds(prevPlan,Core.normalizeLegacyBatch(prevPlan));
assert.equal(Core.normalizeLegacyBatch(prevPlan).slots[0].referenceMedia[0].mediaId,"private-a");
const run={id:"r1",expected_count:6,status:"partial"};
const items=[
 {position:4,status:"failed"},{position:1,status:"generating"},
 {position:0,status:"success",media_id:"m1"},{position:2,status:"success",mediaId:"m2"},
 {position:3,status:"failed"},{position:0,status:"success",media_id:"m1"}
];
const projection=Core.selectRunProjection(run,items);
assert.equal(projection.total,6);
assert.equal(projection.succeeded,2);
assert.equal(projection.failed,2);
assert.equal(projection.generating,1);
assert.equal(projection.queued,1);
assert.equal(projection.processed,4);
assert.equal(projection.isTerminal,false);
assert.equal(projection.viewStatus,"running");
const stop=Core.selectRunProjection(run,items,{cancelRequested:true});
assert.equal(stop.viewStatus,"cancel_requested");
const actualV3 = Core.selectRunProjection({source:"web",expectedCount:3,status:"partial"}, [
  {position:0,slotIndex:0,status:"success",mediaId:"media-1"},
  {position:1000,slotIndex:1,status:"failed"},
  {position:2000,slotIndex:2,status:"generating"}
]);
assert.equal(actualV3.total,3);
assert.equal(actualV3.succeeded,1);
assert.equal(actualV3.failed,1);
assert.equal(actualV3.generating,1);
assert.equal(actualV3.viewStatus,"running");
const multiOutput=Core.selectRunProjection({source:"web",expectedCount:2,status:"partial"},[
  {position:0,status:"success",mediaId:"a"},
  {position:1,status:"failed"},
  {position:1000,status:"success",mediaId:"b"}
]);
assert.equal(multiOutput.total,2);
assert.equal(multiOutput.partialOutputs,1);
assert.equal(multiOutput.viewStatus,"partial");
const noMedia=Core.selectRunProjection({expected_count:1,status:"success"},[{position:0,status:"success"}]);
assert.equal(noMedia.succeeded,0);
assert.equal(noMedia.unknown,1);
const done=Core.selectRunProjection({expected_count:2,status:"partial"},[
 {position:0,status:"success",media_id:"good"},{position:1,status:"failed"}]);
assert.equal(done.viewStatus,"partial");
assert.equal(done.isTerminal,true);
console.log("studio2 core: fixtures, legacy adapter, ratio, patches, resource validation, stable slots and Run projection pass");

// Fixed strategy must not accidentally execute hidden AI layout overrides.
// The canvas engine exposes a browser global, not CommonJS exports.
const previousWindow = global.window;
global.window = global.window || {};
require("../demo/assets/studio-prompt-engine.js");
const E = global.window.HANDRAW_CANVAS_ENGINE;

assert.ok(typeof E.resolveLoopIterations === "function");
const g={nodes:[
 {id:"l",type:"loop",data:{loopMode:"prompts",batchLayoutMode:"fixed",batchRows:[{slotId:"stable-1",theme:"第一张",layout:"SC-021"}],promptListText:"第一张"}},
 {id:"s",type:"skill_params",data:{style1:"FA-001",layout:"SC-022"}},
 {id:"t",type:"text_input",data:{text:""}}
],edges:[{id:"e",from:"s",to:"l"}]};
const rec={layoutId:"SC-022",combinedText:"",assetItems:[]};
const it=E.resolveLoopIterations(g,g.nodes[0],rec,{resourceMap:new Map(),layouts:[]});
assert.equal(it.length,1);
assert.equal(it[0].layout,"SC-022");
assert.equal(it[0].itemKey,"stable-1");
g.nodes[0].data.batchLayoutMode="ai";
assert.equal(E.resolveLoopIterations(g,g.nodes[0],rec,{resourceMap:new Map(),layouts:[]})[0].layout,"SC-021");
