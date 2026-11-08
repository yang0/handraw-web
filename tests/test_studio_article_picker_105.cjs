"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs");
const Adapter=require("../demo/assets/studio-article-picker-105.js");
const Projects=require("../demo/assets/studio-article-project-109.js");
const Res=require("../demo/assets/studio-resources.js");
const cat={styles:[{id:"FA-001",source:"official",version:1},
  {id:"FA-002",source:"official",version:1}],
  layouts:[{id:"IG-001",source:"official",version:2},
    {id:"IG-002",source:"official",version:3}]};
const ref=(field,id)=>Res.resolveSelection(cat,field,id).ref;
const draft={id:"article-105",styleId:"FA-001",layoutId:"IG-001"};
assert.equal(Adapter.applyResource(draft,"style1","FA-002",ref("style1","FA-002")).ok,true);
assert.equal(Adapter.applyResource(draft,"layout","IG-002",ref("layout","IG-002")).ok,true);
assert.deepEqual(draft.styleRef,ref("style1","FA-002"));
assert.deepEqual(draft.layoutRef,ref("layout","IG-002"));
assert.equal(Adapter.validateForExecution(draft,cat).ok,true);
const original=JSON.stringify(draft);
assert.equal(Adapter.applyResource(draft,"style1","FA-001",
  {id:"FA-001",type:"layout",source:"official",version:1}).ok,false);
assert.equal(JSON.stringify(draft),original,"wrong-type Picker result must not mutate");
assert.equal(Adapter.validateForExecution({...draft,styleId:"FA-MISSING"},cat).ok,false);
assert.equal(Adapter.validateForExecution({...draft,styleRef:{...draft.styleRef,source:"private"}},cat).ok,false);
const denied={...cat,styles:[{id:"FA-002",canUse:false}]};
assert.equal(Adapter.validateForExecution(draft,denied).ok,false);
assert.equal(Adapter.normalizeAssetSelection([{id:"ref-x",source:"private",image:"/image.webp"}]).ok,false);
assert.equal(Adapter.normalizeAssetSelection([{id:"ref-x",source:"local",image:"blob:x"}]).ok,false);
const accepted=Adapter.normalizeAssetSelection([{id:"my-1",source:"private",mediaId:"media-105",
  image:"/api/library/assets/media-105",cat:"scenes",name:"我的场景"},
  {id:"official-1",source:"official",image:"/images/demo.webp",name:"官方示例"}]);
assert.equal(accepted.ok,true);
assert.deepEqual(accepted.referenceMedia,[{mediaId:"media-105",role:"scene"}]);
assert.equal(accepted.referenceItems.length,2);
assert.equal(Adapter.validateForExecution({...draft,referenceMedia:accepted.referenceMedia},cat).ok,true);
const article={id:"article-105",articleTitle:"场景",markdown:"# 场景",style1:draft.styleId,
  layout:draft.layoutId,styleRef:draft.styleRef,layoutRef:draft.layoutRef,
  referenceMedia:accepted.referenceMedia,cards:[],documentRevision:3,planRevision:4};
const wire=Projects.snapshot(article);
assert.deepEqual(wire.draft.creationSpec.style,draft.styleRef);
assert.deepEqual(wire.draft.creationSpec.layout,draft.layoutRef);
assert.deepEqual(wire.draft.creationSpec.referenceMedia,accepted.referenceMedia);
const back=Projects.hydrate({id:"project-105",revision:7,...wire});
assert.deepEqual(back.styleRef,draft.styleRef);
assert.deepEqual(back.layoutRef,draft.layoutRef);
assert.deepEqual(back.referenceMedia,accepted.referenceMedia);
assert.equal(back.projectRevision,7);
assert.equal(Projects.planChanged(article,{...article,referenceMedia:[]}),true);
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
const start=app.indexOf("    const selectArticleResource = (field) => {");
assert.ok(start>=0);
const bridge=app.slice(start,start+3200);
assert.match(bridge,/openSkillFieldPickerModal\(null,field/);
assert.match(bridge,/adapter\.applyResource\(draft,field,id,ref\)/);
assert.match(bridge,/openAssetPickerModal\(\{/);
assert.doesNotMatch(bridge,/S\.openAssetPickerModal\(/);
assert.match(app,/id="editor-layout-picker"/);
assert.match(app,/id="editor-reference-picker"/);
assert.match(app,/articlePicker\.validateForExecution/);
assert.match(app,/const articleRefImages =/);
const html=fs.readFileSync("demo/studio.html","utf8");
assert.ok(html.indexOf("studio-resources.js")<html.indexOf("studio-article-picker-105.js"));
assert.ok(html.indexOf("studio-article-picker-105.js")<html.indexOf("studio-app.js"));
console.log("Issue #105 article Picker, typed refs, owner MediaRef, CAS and shared UI PASS");
