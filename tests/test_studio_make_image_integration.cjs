"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const Core=require("../demo/assets/studio-core.js");
const N=require("../demo/assets/studio-normalization.js");
const RR=require("../demo/assets/studio-resources.js");
const Q=require("../demo/assets/studio-quick-spec.js");
const Make=require("../demo/assets/studio-make-image.js");
const copy=v=>JSON.parse(JSON.stringify(v));

const style=(id,version=1)=>({id,kind:"style",source:"official",version,canUse:true,access:{canUse:true}});
const layout=id=>({id,kind:"layout",source:"official",version:1,canUse:true,access:{canUse:true}});
const color=id=>({id,kind:"color",source:"official",version:1,canUse:true});
const tone=id=>({id,kind:"tone",source:"official",version:1,canUse:true});
const entries=[style("FA-001"),style("FA-002"),style("FA-BLOCK"),layout("SC-021"),layout("SC-022"),
 color("C-01"),color("C-02"),tone("T-01")];
const catalog={resourceMap:new Map(entries.map(e=>[e.id,e])),
 styles:entries.filter(e=>e.kind==="style"),layouts:entries.filter(e=>e.kind==="layout"),
 colors:entries.filter(e=>e.kind==="color"),tones:entries.filter(e=>e.kind==="tone")};
const options={catalog,isUnlocked:()=>true};
function graph(){
  const g={blueprint:"single",meta:{persistMe:true},revision:9,nodes:[
    {id:"s",type:"skill_params",data:{
      style1:"FA-001",style2:"FA-002",fusion:false,layout:"SC-021",
      colors:["C-01"],tones:["T-01"],moods:["治愈"],customMood:"薄雾",
      sc021Type:"撕纸",sc022Name:"原名",sc022Pinyin:"YUAN MING",
      unrelated:"keep-skill",resourceRefs:{} }},
    {id:"t",type:"text_input",data:{text:"春日西湖",subjectHint:"old",unrelated:"keep-text"}},
    {id:"c",type:"output_control",data:{mode:"graphic-text",ratio:"3:4",
      ratioSource:"default",count:1,unrelated:"keep-control"}},
    {id:"a",type:"asset",data:{items:[
      {mediaId:"media-A",source:"private",role:"scene",name:"场景"},
      {localFileName:"unuploaded.webp",image:"blob:preview"}],unrelated:"keep-assets"}},
    {id:"custom",type:"output_display",data:{items:[],pinnedResult:"keep"}}
  ],edges:[{id:"e1",from:"s",to:"c"},{id:"e2",from:"t",to:"c"},
           {id:"e3",from:"a",to:"c"},{id:"e4",from:"c",to:"custom"}]};
  return g;
}
const parts=g=>({
  skill:g.nodes.find(n=>n.id==="s"),text:g.nodes.find(n=>n.id==="t"),
  ctrl:g.nodes.find(n=>n.id==="c"),asset:g.nodes.find(n=>n.id==="a")
});
const g=graph(),p=parts(g),untouched=copy(g),first=Q.read(p);
assert.equal(first.spec.subject,"春日西湖");
assert.equal(first.spec.ratioSource,"default");
assert.equal(first.spec.secondaryStyle.id,"FA-002");
assert.deepEqual(g,untouched,"canonical read does not mutate original Graph");
const pick=RR.resolveSelection(catalog,"style1","FA-002");
assert.equal(pick.ok,true);
assert.equal(pick.ref.source,"official");
Q.apply(p,{style:pick.ref},options);
assert.equal(p.skill.data.style1,"FA-002");
assert.equal(p.skill.data.resourceRefs.style.version,1);
assert.equal(p.skill.data.style2,"FA-002");
assert.equal(p.skill.data.unrelated,"keep-skill");
assert.equal(p.text.data.unrelated,"keep-text");
assert.equal(p.ctrl.data.unrelated,"keep-control");
assert.equal(p.asset.data.items.length,2);
assert.deepEqual(g.edges,untouched.edges,"no Graph edges rewritten");
assert.deepEqual(g.nodes.find(x=>x.id==="custom"),untouched.nodes.find(x=>x.id==="custom"),
  "independent output node preserved");
Q.apply(p,{colors:["C-02"],tones:["T-01"],layout:"SC-022"},options);
assert.equal(p.skill.data.resourceRefs.colors[0].id,"C-02");
assert.equal(p.skill.data.resourceRefs.layout.version,1);
Q.apply(p,{layoutParams:{sc021Type:"实物对比"}},options);
Q.apply(p,{layoutParams:{sc022Name:"林夏",sc022Pinyin:"LIN XIA"}},options);
assert.equal(p.skill.data.sc021Type,"实物对比");
assert.equal(p.skill.data.sc022Name,"林夏");
assert.equal(p.skill.data.sc022Pinyin,"LIN XIA");
assert.equal(p.skill.data.unrelated,"keep-skill");

// A user-selected ratio survives all supported image modes and refresh.
Q.apply(p,{ratio:"2.35:1"},options);
assert.equal(p.ctrl.data.ratioSource,"user");
for(const mode of ["poster","graphic-text","pure","poster"]){
  Q.apply(p,{outputMode:mode},options);
  assert.equal(p.ctrl.data.ratio,"2.35:1");
  assert.equal(p.ctrl.data.ratioSource,"user");
}
const restart=copy(g),restartP=parts(restart);
assert.equal(Q.read(restartP).spec.ratio,"2.35:1");
assert.equal(Q.read(restartP).spec.ratioSource,"user");
assert.equal(Q.read(restartP).spec.secondaryStyle.id,"FA-002");
assert.equal(Q.read(restartP).spec.layoutParams.sc022Pinyin,"LIN XIA");
assert.equal(restartP.asset.data.items[0].mediaId,"media-A");
assert.equal(restartP.asset.data.items[1].localFileName,"unuploaded.webp");

// Disable fusion retains style2 only in draft; execution copy excludes it.
const beforeRun=Q.capture(p,{graph:g,projectId:"p-image",projectRevision:6,catalog,
 isUnlocked:()=>true});
assert.equal(beforeRun.spec.secondaryStyle,null);
assert.equal(Q.read(p).spec.secondaryStyle.id,"FA-002");
const lockedSnapshot=JSON.stringify(beforeRun);
Q.apply(p,{subject:"运行中修改的下一版主题",ratio:"1:1",
 layoutParams:{sc022Name:"下一个名字"}},options);
Q.setAssets(p,[{mediaId:"media-B",source:"private",role:"scene"},
 {localFileName:"local2.webp",image:"blob:new"}]);
assert.equal(JSON.stringify(beforeRun),lockedSnapshot,"RunSnapshot immutable by separation");
assert.equal(beforeRun.graph.nodes.find(n=>n.id==="t").data.text,"春日西湖");
assert.equal(beforeRun.spec.subject,"春日西湖");
assert.equal(beforeRun.spec.ratio,"2.35:1");
assert.equal(p.asset.data.items[0].mediaId,"media-B");

// Invalid data cannot partially overwrite any selected field and cannot reserve.
const failChange=(delta,re)=>{const saved=copy(g);assert.throws(()=>Q.apply(p,delta,options),re);
  assert.deepEqual(g,saved,"failed multi-field patch remains atomic");};
failChange({subject:"should-not-save",style:"MISSING-STYLE"},/resource_not_found/);
failChange({layout:"FA-001"},/resource_not_found/);
failChange({ratio:"0:4"},/invalid_ratio/);
failChange({layoutParams:{badKey:"fake"}},/invalid_layout_param/);
const badCatalog={...catalog,resourceMap:new Map(catalog.resourceMap)};
badCatalog.resourceMap.set("FA-001",{...catalog.resourceMap.get("FA-001"),
 canUse:false,access:{canUse:false}});
const blocked=parts(graph());
assert.equal(Q.preflight(blocked,{catalog:badCatalog,isUnlocked:()=>false}).ok,false);
assert.ok(Q.preflight(blocked,{catalog:badCatalog,isUnlocked:()=>false}).errors
  .some(e=>e.code==="resource_forbidden"));
assert.ok(Q.preflight(blocked,{}).errors.some(e=>
 e.code==="resource_authorization_required"));
assert.ok(Q.preflight(blocked,options).ok);
blocked.text.data.text=" ";
assert.ok(Q.preflight(blocked,options).errors.some(e=>e.code==="missing_subject"));
blocked.text.data.text="春日";
blocked.skill.data.style1="";
assert.ok(Q.preflight(blocked,options).errors.some(e=>e.code==="missing_style"));
assert.throws(()=>Q.capture(blocked,{graph:graph(),catalog}),/missing_style/);
blocked.skill.data.style1="MISSING-STYLE";
assert.ok(!Q.preflight(blocked,options).ok);
const locked=parts(graph());
locked.skill.data.lockedFields=["style"];
assert.throws(()=>Q.apply(locked,{style:"FA-002"},options),/locked_field/);

// #100 selected media image receives the precise draft, preserved source
// authorship and does not silently overwrite unspecified optional fields.
const fork=parts(graph());
Q.fork(fork,{styleIds:["FA-002"],layoutId:"SC-022",
 ratio:"2.35:1",mode:"pure-image",subjectHint:"作品第二张",
 source:{workId:"W42",imageIndex:1,author:"orig-artist"}});
assert.equal(fork.skill.data.style1,"FA-002");
assert.equal(fork.skill.data.style2,"");
assert.equal(fork.skill.data.layout,"SC-022");
assert.equal(fork.text.data.text,"作品第二张");
assert.equal(fork.ctrl.data.ratio,"2.35:1");
assert.equal(fork.ctrl.data.ratioSource,"user");
assert.equal(fork.ctrl.data.mode,"pure");
assert.deepEqual(fork.skill.data.colors,["C-01"],"unspecified fork fields remain");
assert.equal(Q.read(fork).spec.style.id,"FA-002");

// V3-only authoritative projection: no optimistic DOM count as success.
const run=(status,items)=>Q.projectRun({run:{id:"run-stable",source:"web",
 expectedCount:1,status},items});
const accepted=run("running",[{id:"it",slotIndex:0,position:0,status:"generating",
 mediaId:"",imageUrl:"/should-not-count.webp"}]);
assert.equal(accepted.completed,0);
assert.equal(accepted.viewStatus,"running");
assert.equal(accepted.isTerminal,false);
const succeeded=run("success",[{id:"it",slotIndex:0,position:0,status:"success",
 mediaId:"owned-output",imageUrl:"/generated/result.webp"}]);
assert.equal(succeeded.completed,1);
assert.equal(succeeded.results.length,1);
assert.equal(succeeded.results[0].mediaId,"owned-output");
const failed=run("failed",[{id:"it",slotIndex:0,position:0,status:"failed",
 mediaId:"",errorCode:"gateway_failed"}]);
assert.equal(failed.succeeded,0);
assert.equal(failed.failed,1);
assert.equal(failed.canRetry,true);
assert.equal(failed.isTerminal,true);
const cancelIntent=Q.projectRun({run:{id:"run-stable",source:"web",
 expectedCount:1,status:"running"},items:[{slotIndex:0,position:0,status:"generating"}]},
 {cancelRequested:true});
assert.equal(cancelIntent.viewStatus,"cancel_requested");
assert.equal(cancelIntent.persistedStatus,"running");
assert.equal(Q.projectRun(null).viewStatus,"unknown");
const noMedia=run("success",[{id:"it",slotIndex:0,position:0,status:"success",
 mediaId:"",imageUrl:"/preview-only.webp"}]);
assert.equal(noMedia.completed,0);

// Direct form events exercise the new bridge (without a new UI framework).
let edits=0,errors=[];
global.HandrawStudioCore=Core;global.HandrawStudioResources=RR;
global.HandrawStudioNormalization=N;global.HandrawQuickSpec=Q;
global.HANDRAW_SHARED={toast:x=>errors.push(x)};
global.window={addEventListener(){},confirm:()=>true};
const ui=parts(graph()),controller=new Make.MakeImageController();
const modeButton={getAttribute:()=> "poster"};
const ratioButton={getAttribute:()=> "16:9"};
const styleButton={getAttribute:k=>k==="data-pick-kind"?"style1":null};
const subjectInput={value:"键盘录入的主题"};
const fakeRoot={
 querySelector(selector){return selector==="#make-image-subject"?subjectInput:null;},
 querySelectorAll(selector){if(selector==="[data-set-mode]")return [modeButton];
  if(selector==="[data-set-ratio]")return [ratioButton];
  if(selector==="[data-pick-kind]")return [styleButton];return [];},
 addEventListener(){}
};
controller.context={parts:ui,catalog};controller.actions={
 markDirtyAndRender(){edits++;},persistDraft(){},isUnlocked:()=>true,
 openAssetPicker({onSelect}){onSelect("FA-002",RR.makeRef(style("FA-002"),"style"))}
};
controller.bindEvents(fakeRoot);
modeButton.onclick();ratioButton.onclick();styleButton.onclick({target:{closest:()=>false}});
subjectInput.oninput();
assert.equal(ui.ctrl.data.mode,"poster");
assert.equal(ui.ctrl.data.ratio,"16:9");
assert.equal(ui.skill.data.resourceRefs.style.id,"FA-002");
assert.equal(ui.text.data.text,"键盘录入的主题");
assert.ok(edits>=3);
const html=fs.readFileSync("demo/studio.html","utf8");
for(const name of ["studio-core","studio-resources","studio-views",
 "studio-normalization","studio-quick-spec","studio-make-image"]){
 assert.ok(html.includes(name+".js"),name+" included in Studio");
}
assert.ok(html.indexOf("studio-normalization.js")<html.indexOf("studio-quick-spec.js"));
assert.ok(html.indexOf("studio-quick-spec.js")<html.indexOf("studio-make-image.js"));
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
assert.match(app,/const executionGraph = previousRunSnapshot\?\.executionGraph[\s\S]*?cloneGraph\(previousRunSnapshot\.executionGraph\) : cloneGraph\(executionGraphOverride \|\| CS\.graph\)/,
 "Run uses frozen DAG Graph or current draft for new execution; explicit retry keeps old frozen Graph");
assert.match(app,/E\.assembleControlPrompt\(executionGraph, executionCtrl, Catalog, "cloud", sp\)/);
assert.match(app,/HandrawQuickSpec\.setAssets\(p,ast\.data\.items\)/);
assert.match(app,/\/api\/studio\/runs\//);
assert.match(app,/onSelect\(id, ref\)/);
assert.match(app,/forkOf: batchRun\.forkSource\.workId/,
 "Public work fork must retain original-author Work identity captured before execution");
assert.match(app,/forkItemId: batchRun\.forkSource\.itemId/,
 "Selected image fork lineage must not change while the Run executes");
assert.match(app,/E\.assembleControlPrompt\(runGraph, ctrlNode, Catalog, "skill"\)/,
 "History must use the frozen execution graph instead of a newly edited draft");
assert.match(app,/recordGenerationHistory\(executionCtrl, allItems, plan\.kind/,
 "Execution history is recorded with the frozen control and origin");
assert.match(app,/retry:\s*async \(\)/);
console.log("Studio #122 Make Image integration: atomic patches, catalog refs, ratio, fork, Run, frozen snapshot and DOM events PASS");
