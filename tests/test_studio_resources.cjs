"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const RR=require("../demo/assets/studio-resources.js");
const Core=require("../demo/assets/studio-core.js");

const catalog={
  resourceMap:new Map([
    ["FA-001",{id:"FA-001",kind:"style",source:"official",version:1,name:"插画"}],
    ["FA-002",{id:"FA-002",kind:"style",source:"community",revision:3}],
    ["FA-PRO",{id:"FA-PRO",kind:"style",source:"exclusive",tier:"pro_credit"}],
    ["SC-021",{id:"SC-021",kind:"layout",source:"official",version:1}],
    ["C-01",{id:"C-01",kind:"color",source:"official",version:1}],
    ["T-01",{id:"T-01",kind:"tone",source:"official",version:1}]
  ]),
  styles:[{id:"FA-001",kind:"style",source:"official",version:1},
          {id:"FA-002",kind:"style",source:"community",revision:3},
          {id:"FA-PRO",kind:"style",source:"exclusive",tier:"pro_credit"}],
  layouts:[{id:"SC-021",kind:"layout",source:"official",version:1}],
  colors:[{id:"C-01",kind:"color",source:"official",version:1}],
  tones:[{id:"T-01",kind:"tone",source:"official",version:1}]
};
let pick=RR.resolveSelection(catalog,"style1","FA-001");
assert.equal(pick.ok,true);
assert.deepEqual(pick.ref,{id:"FA-001",type:"style",source:"official",version:1});
assert.equal(RR.resolveSelection(catalog,"layout","FA-001").code,"resource_not_found");
assert.equal(RR.resolveSelection(catalog,"style1","MISSING-ID").code,"resource_not_found");
assert.equal(RR.resolveSelection(catalog,"style1","FA-PRO",{isUnlocked:()=>false}).code,
  "resource_forbidden");
assert.equal(RR.resolveSelection(catalog,"style1","FA-PRO",{isUnlocked:()=>true}).ok,true);
assert.equal(RR.resolveSelection(catalog,"style1","").ok,true);
assert.equal(RR.makeRef({id:"FA-002",kind:"style",source:"community",revision:3},"style").version,3);
assert.throws(()=>RR.makeRef({id:"FA-001",kind:"layout"},"style"),/类型/);

const sd={style1:"",style2:"",fusion:false,layout:"",colors:[],tones:[]};
RR.setLegacySelection(sd,"style1",pick);
RR.setLegacySelection(sd,"style2",RR.resolveSelection(catalog,"style2","FA-002"));
RR.setLegacySelection(sd,"layout",RR.resolveSelection(catalog,"layout","SC-021"));
RR.setLegacySelection(sd,"colors",RR.resolveSelection(catalog,"colors","C-01"));
RR.setLegacySelection(sd,"tones",RR.resolveSelection(catalog,"tones","T-01"));
const graph={
  skill:{type:"skill_params",data:sd},
  text:{data:{text:"杭州春天"}},
  ctrl:{data:{mode:"graphic-text",ratio:"3:4",ratioSource:"user"}},
  asset:{data:{items:[{id:"local-photo",image:"data:image/png;base64,aGVsbG8="}]}}
};
const normalized=Core.normalizeLegacyParts(graph);
const spec=normalized.spec;
assert.deepEqual(spec.style,pick.ref);
assert.deepEqual(spec.secondaryStyle,{id:"FA-002",type:"style",source:"community",version:3});
assert.equal(spec.fusionEnabled,false,"Disabled fusion preserves draft secondary style");
assert.equal(spec.layout.source,"official");
assert.deepEqual(spec.colors[0],{id:"C-01",type:"color",source:"official",version:1});
assert.equal(spec.referenceMedia.length,0,"Local image never becomes a fake server mediaId");
assert.equal(normalized.warnings[0].code,"unresolved_local_media");
assert.equal(Core.validateSpec(spec,{catalog}).ok,true);
const restarted=JSON.parse(JSON.stringify(spec));
const p2={skill:{data:{}},text:{data:{}},ctrl:{data:{}},asset:{data:{items:graph.asset.data.items}}};
Core.applyLegacySpec(p2,restarted);
const again=Core.normalizeLegacyParts(p2).spec;
assert.deepEqual(again.style,spec.style);
assert.deepEqual(again.secondaryStyle,spec.secondaryStyle);
assert.deepEqual(again.layout,spec.layout);
assert.deepEqual(again.colors,spec.colors);
assert.equal(p2.asset.data.items[0].id,"local-photo","Graph asset items are not replaced by MediaRef");

let local=RR.syncLegacyRefs({style1:"FA-001",layout:"OLD-404",colors:[],tones:[]},catalog);
assert.equal(local.errors.length,1);
assert.equal(local.errors[0].id,"OLD-404");
assert.equal(local.data.layout,"OLD-404","Invalid legacy ID stays visible");
assert.ok(!Object.hasOwn(local.data.resourceRefs,"layout"),
  "Do not fabricate a trusted catalog ref for a missing legacy resource");

const code=fs.readFileSync("demo/assets/studio-app.js","utf8");
const make=fs.readFileSync("demo/assets/studio-make-image.js","utf8");
const batch=fs.readFileSync("demo/assets/studio-batch.js","utf8");
const html=fs.readFileSync("demo/studio.html","utf8");
assert.match(html,/studio-resources.js/);
assert.match(code,/ResourceRefs\.resolveSelection\(Catalog, field, id/);
assert.match(code,/checkExclusiveGateForControl/);
assert.match(code,/syncLegacyRefs\(node\.data, Catalog\)/);
assert.match(make,/onSelect: \(id, ref\)/);
assert.match(batch,/patchSlotByIndex\(idx,\{overrides:\{layout:ref\|\|pickedId\|\|null\}\}\)/,
  "Batch picker writes only the selected PlanSlot override with catalog ResourceRef");
assert.match(code,/gridEl\.innerHTML = list\s*\.map\(\(it\)/,
  "Unified catalog Picker must not silently hide resources after item 180");

const owned=RR.mediaRefFromAsset({assetUid:"asset-user-owned",source:"private",cat:"scenes"});
assert.deepEqual(owned,{ok:true,ref:{mediaId:"asset-user-owned",role:"scene"}});
assert.equal(RR.mediaRefFromAsset({id:"upload-row-id",image:"blob:local"}).code,
  "media_upload_required","Local preview URL cannot mint server media authority");
assert.equal(RR.mediaRefFromAsset({mediaId:"id-from-public-preview",source:"official"}).code,
  "media_source_unverified","Public image may not impersonate private asset");
assert.equal(RR.mediaRefFromAsset({mediaId:"generated-media",source:"generated",role:"result"}).ok,true);

const wrongSource=JSON.parse(JSON.stringify(spec));
wrongSource.style.source="private";
assert.ok(Core.validateSpec(wrongSource,{catalog}).errors.some(x=>x.code==="resource_source_mismatch"));

const wrongVersion=JSON.parse(JSON.stringify(spec));
wrongVersion.style.version=999;
assert.ok(Core.validateSpec(wrongVersion,{catalog}).errors.some(x=>x.code==="resource_version_conflict"));

const missingSecond=JSON.parse(JSON.stringify(spec));
missingSecond.fusionEnabled=true;
missingSecond.secondaryStyle=null;
assert.ok(Core.validateSpec(missingSecond,{catalog}).errors.some(x=>x.code==="missing_secondary_style"));

const deniedCatalog={...catalog,resourceMap:new Map(catalog.resourceMap)};
deniedCatalog.resourceMap.set("FA-001",{...catalog.resourceMap.get("FA-001"),
  canUse:false,access:{canUse:false}});
assert.ok(Core.validateSpec(spec,{catalog:deniedCatalog}).errors.some(x=>x.code==="resource_forbidden"));

const servicesSource=fs.readFileSync("backend/services.py","utf8");
assert.match(servicesSource,/"assetUid": r\["asset_uid"\] or None/,
  "Private workspace must expose actual media UID, never reuse upload row ID");
assert.match(code,/assetUid: ru\.assetUid \|\| null/,
  "Gallery sync persists owner-only media UID");
assert.match(code,/mediaId: confirmed\?\.ok \? confirmed\.ref\.mediaId : undefined/,
  "Only verified private media is serialized as MediaRef");
assert.match(code,/markActiveTabDirty\(\);\s*fullRenderCanvas\(\);\s*persistOpenTabs\(\);/,
  "Asset picker edits should enter Project autosave");

console.log("Studio2 ResourceRef + CreationSpec/media roundtrip, entitlement, Picker bridge tests passed");
