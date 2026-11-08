"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs");
const Core=require("../demo/assets/studio-core.js");
const N=require("../demo/assets/studio-normalization.js");
const read=n=>JSON.parse(fs.readFileSync("docs/studio-2.0/golden/"+n+".json","utf8"));
const clone=x=>JSON.parse(JSON.stringify(x));
for(const name of ["image","series","article","canvas"]){
  const fixture=read(name),src=clone(fixture.wire);
  const first=N.normalizeDocument(src,{strict:true});
  assert.deepEqual(src,fixture.wire,"read-only input");
  const serialized=N.serializeDocument(first);
  const again=N.reload(serialized);
  assert.deepEqual(first.wire,again.wire,name+" normalize/serialize/reload/normalize");
  assert.deepEqual(again.wire,N.reload(N.serializeDocument(again)).wire,name+" idempotence");
  assert.equal(again.wire.project.authority,src.project.authority);
  assert.equal(again.validation.ok,true);
}
const image=read("image"),legacy=N.normalizeLegacyGraph(image.legacyGraph,{projectId:"p-image"});
const spec=legacy.projection.spec;
assert.equal(spec.subject,"日式茶室");
assert.equal(spec.style.id,"FA-001");
assert.equal(spec.secondaryStyle.id,"FA-002");
assert.equal(spec.fusionEnabled,false);
assert.equal(spec.layout.id,"SC-022");
assert.equal(spec.colors[0].id,"C-01");
assert.equal(spec.tones[0].id,"T-01");
assert.deepEqual(spec.moods,["治愈"]);
assert.equal(spec.customMood,"东方留白");
assert.equal(spec.ratio,"2.35:1");
assert.equal(spec.ratioSource,"user");
assert.equal(spec.layoutParams.sc021Type,"双屏续绘");
assert.equal(spec.layoutParams.sc022Name,"林夏");
assert.equal(spec.layoutParams.sc022Pinyin,"LIN XIA");
assert.equal(spec.referenceMedia[0].mediaId,"owned-private-im");
assert.equal(legacy.warnings[0].code,"unresolved_local_media");
assert.deepEqual(legacy.graph,image.legacyGraph,"local asset items remain untouched");
const parts={skill:{data:{}},text:{data:{}},ctrl:{data:{}},
 asset:{data:{items:clone(image.legacyGraph.nodes.find(n=>n.type==="asset").data.items)}}};
Core.applyLegacySpec(parts,spec);
assert.deepEqual(Core.normalizeLegacyParts(parts).spec,spec);
assert.equal(parts.asset.data.items.length,2);
assert.equal(parts.skill.data.style2,"FA-002");

const series=read("series");
const fixed=N.normalizeLegacyGraph(series.legacyFixed,{projectId:"p-series"});
const fixedPlan=fixed.projection.plan;
assert.equal(fixedPlan.slots.length,6);
assert.equal(new Set(fixedPlan.slots.map(s=>s.slotId)).size,6);
assert.ok(fixedPlan.slots.every(s=>!/^([0-9]+)$/.test(s.slotId)));
const loop=fixed.graph.nodes.find(n=>n.type==="loop");
assert.deepEqual(loop.data.studio2SlotIds,fixedPlan.slots.map(s=>s.slotId));
const edited=clone(fixed.graph);
edited.nodes.find(n=>n.type==="loop").data.promptListText="封面改名\n西湖\n龙井茶园\n青团与茶\n路线\n总结";
assert.deepEqual(N.normalizeLegacyGraph(edited,{projectId:"p-series"}).projection.plan.slots.map(s=>s.slotId),
  fixedPlan.slots.map(s=>s.slotId));
assert.deepEqual(N.normalizeLegacyGraph(JSON.parse(JSON.stringify(fixed.graph)),
  {projectId:"p-series"}).projection.plan,fixedPlan);
const ai=N.normalizeLegacyGraph(series.legacyAI,{projectId:"p-series"});
assert.equal(ai.projection.plan.slots.length,6);
assert.deepEqual(ai.projection.plan.slots.map(s=>s.slotId),series.expect.aiSlotIds);
assert.equal(ai.projection.plan.slots[2].overrides.layout.id,"SC-022");
assert.equal(ai.projection.plan.slots[2].referenceMedia[0].mediaId,"owned-scene-3");
assert.equal(ai.projection.plan.slots[2].anchorId,"scene-anchor-3");
const aiLoop=ai.graph.nodes.find(n=>n.type==="loop");
const changed=Core.mergeLegacyPlanRows(aiLoop,[
 {slotId:"story-3",subject:"AI revised third",layout:"SC-021"},
 {slotId:"story-1",subject:"AI revised cover"}
],"ai");
assert.equal(changed.batchRows[0].slotId,"story-3");
assert.equal(changed.batchRows[0].layout,"SC-022","user layout lock");
assert.equal(changed.batchRows[0].theme,"AI revised third");
assert.equal(changed.batchRows[0].assetItems[0].mediaId,"owned-scene-3");
assert.equal(changed.batchRows[1].slotId,"story-1");

const article=read("article");
const a=N.normalizeDocument(article.wire,{strict:true});
assert.equal(a.wire.plan.documentId,article.wire.article.documentId);
assert.equal(a.wire.plan.documentRevision,4);
assert.deepEqual(a.wire.plan.slots.map(s=>s.anchorId),article.expect.anchorIds);
const missing=clone(article.wire);missing.plan.slots[0].anchorId="missing";
assert.throws(()=>N.normalizeDocument(missing),/invalid_article_anchor/);
const stale=clone(article.wire);stale.plan.documentRevision=3;
assert.throws(()=>N.normalizeDocument(stale),/article_revision_mismatch/);

const canvas=read("canvas"),cm=N.normalizeDocument(canvas.wire,{strict:true});
assert.deepEqual(cm.wire.graph,canvas.wire.graph);
assert.equal(cm.projection.expressibility.mode,"read-only-summary");
assert.equal(cm.wire.graph.nodes.find(n=>n.id==="custom-branch").data.contrast,.7);
assert.equal(cm.wire.graph.groups[0].id,"g-left");
assert.equal(cm.wire.graph.runRefs[0].runId,"run-1");
assert.throws(()=>N.patchDocument(cm,{op:"set",
  path:"/creationSpec/subject",value:"bad"},canvas.wire.project.revision),
  /editor_authority_conflict/);
assert.throws(()=>N.patchDocument(cm,{op:"set",
  path:"/graph/nodesById/n-text/data/text",value:"bad"},canvas.wire.project.revision),
  /graph_field_read_only/);

const simple=N.normalizeDocument(series.wire,{strict:true}),rev=simple.wire.project.revision;
assert.throws(()=>N.patchDocument(simple,{op:"set",path:"/creationSpec/style",
  value:{id:"FA-999",type:"style"}},rev),/locked_field/);
assert.throws(()=>N.patchDocument(simple,{op:"set",
  path:"/plan/slotsById/slot-3/overrides/layout",
  value:{id:"SC-021",type:"layout"}},rev),/locked_field/);
assert.throws(()=>N.patchDocument(simple,{op:"set",path:"/plan/slots/2/subject",
  value:"no index"},rev),/invalid_patch_field/);
assert.throws(()=>N.patchDocument(simple,{op:"set",path:"/creationSpec/subject",
  value:"stale"},rev-1),/project_revision_conflict/);
const updated=N.patchDocument(simple,[
 {op:"set",path:"/creationSpec/ratio",value:"1:1"},
 {op:"set",path:"/plan/slotsById/slot-2/overrides/ratio",value:"9:16"}],rev);
assert.equal(updated.wire.creationSpec.ratio,"1:1");
assert.equal(updated.wire.creationSpec.ratioSource,"default");
assert.equal(updated.wire.plan.slots[1].overrides.ratio,"9:16");
assert.deepEqual(simple.wire,N.normalizeDocument(series.wire,{strict:true}).wire);
assert.equal(N.reload(N.serializeDocument(updated)).wire.plan.slots[1].slotId,"slot-2");

const catalog={resourceMap:new Map([
 ["FA-001",{id:"FA-001",kind:"style",source:"official",version:1,canUse:true}],
 ["FA-002",{id:"FA-002",kind:"style",source:"official",version:1,canUse:true}],
 ["SC-021",{id:"SC-021",kind:"layout",source:"official",version:1,canUse:true}],
 ["SC-022",{id:"SC-022",kind:"layout",source:"official",version:1,canUse:true}],
 ["C-01",{id:"C-01",kind:"color",source:"official",version:1,canUse:true}],
 ["T-01",{id:"T-01",kind:"tone",source:"official",version:1,canUse:true}]
])};
const authorized=id=>id==="owned-private-im";
const valid=N.validateForExecution(spec,{catalog,verifyMediaOwner:authorized});
assert.equal(valid.ok,true,JSON.stringify(valid.errors));
assert.equal(N.executionSpec(spec,null,{catalog,verifyMediaOwner:authorized}).secondaryStyle,null);
assert.equal(spec.secondaryStyle.id,"FA-002");
assert.equal(N.validateForExecution(spec,{}).ok,false);
const bad=clone(spec);bad.style={id:"MISSING-STYLE",type:"style"};
assert.ok(N.validateForExecution(bad,{catalog,verifyMediaOwner:authorized})
 .errors.some(e=>e.code==="invalid_resource"));
const forbidden={resourceMap:new Map(catalog.resourceMap)};
forbidden.resourceMap.set("FA-001",{...catalog.resourceMap.get("FA-001"),canUse:false});
assert.ok(N.validateForExecution(spec,{catalog:forbidden,verifyMediaOwner:authorized})
 .errors.some(e=>e.code==="resource_forbidden"));
assert.ok(N.validateForExecution(spec,{catalog,verifyMediaOwner:()=>false})
 .errors.some(e=>e.code==="project_media_forbidden"));
assert.ok(N.validateForExecution(spec,{catalog}).errors.some(e=>e.code==="media_authorization_required"));
const wrong=clone(spec);wrong.style.source="private";
assert.ok(N.validateForExecution(wrong,{catalog,verifyMediaOwner:authorized})
 .errors.some(e=>e.code==="resource_source_mismatch"));
const version=clone(spec);version.style.version=999;
assert.ok(N.validateForExecution(version,{catalog,verifyMediaOwner:authorized})
 .errors.some(e=>e.code==="resource_version_conflict"));
assert.throws(()=>N.serializeDocument({...simple.wire,creationSpec:{
 ...simple.wire.creationSpec,finalPrompt:"secret"}}),/protected_prompt_in_client_draft/);
const schema=JSON.parse(fs.readFileSync("docs/studio-2.0/schema.json","utf8"));
assert.ok(schema.$defs.slot.required.includes("slotId"));
assert.ok(schema.$defs.resource.required.includes("type"));
assert.ok(schema.$defs.media.required.includes("mediaId"));
const promptEngine=fs.readFileSync("demo/assets/studio-prompt-engine.js","utf8");
assert.match(promptEngine,/function assembleControlPrompt\(/);
assert.doesNotMatch(fs.readFileSync("demo/assets/studio-normalization.js","utf8"),
 /function (assembleControlPrompt|buildPromptText|compilePrompt)\(/);
console.log("Studio #121 goldens, legacy fields, stable slots, authority/locks, permission and schema passed");
