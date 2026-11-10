"use strict";
/* Issue #129: server-authoritative UI selectors and Canvas integration contract. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const UI=require("../demo/assets/studio-canvas-ui.js");
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
const canvasUiSource=fs.readFileSync("demo/assets/studio-canvas-ui.js","utf8");
// #136: run is the single canvas primary action; duplicate global save/
// view/undo controls must not crowd its own topbar.
const canvasTop=canvasUiSource.slice(canvasUiSource.indexOf("const topHtml="),
  canvasUiSource.indexOf("if(top.innerHTML!==topHtml)"));
assert.match(canvasTop,/data-c129=\\"run\\"/);
assert.match(canvasTop,/ic129-more-tools/);
for(const deprecated of ['data-c129="save"','data-c129="simple"',
  'data-c129="undo"','data-c129="redo"']){
  assert.equal(canvasTop.includes(deprecated),false,deprecated+" must not duplicate global action");
}
assert.match(app,/id="studio-mode-view-toggle"/);
assert.doesNotMatch(app,/id="studio-mode-projects"/);

const canvasCss=fs.readFileSync("demo/assets/studio-canvas-129.css","utf8");
// #111: 30 output controls must not wrap task chips into a tall overlay that
// blocks the right-hand zoom dock. Real Chromium hit-test is a separate gate.
assert.match(canvasCss,/\.ic129-task-chips\{display:flex;flex-wrap:nowrap/);
assert.match(canvasCss,/overflow-x:auto;overflow-y:hidden/);
assert.match(canvasCss,/\.ic-canvas-stage \.ic-bottom-right-dock\{bottom:100px;right:14px;z-index:48\}/);

const entry=fs.readFileSync("demo/studio.html","utf8");

const six=[
  {id:"r1",position:0,slotIndex:0,status:"success",mediaId:"m1",imageUrl:"/api/media/1"},
  {id:"r2",position:1000,slotIndex:1,status:"success",mediaId:"m2",imageUrl:"/api/media/2"},
  {id:"r3",position:2000,slotIndex:2,status:"failed",error:"上游失败"},
  {id:"r4",position:3000,slotIndex:3,status:"generating"},
  {id:"r5",position:4000,slotIndex:4,status:"pending"},
  {id:"r6",position:5000,slotIndex:5,status:"success",mediaId:"m6",imageUrl:"/api/media/6"}
];
const slots=UI.slotSummary(six,6,"web");
assert.deepEqual(slots.map(s=>s.status),["success","success","failed","generating","pending","success"]);
assert.equal(slots[2].error,"上游失败");
assert.equal(UI.slotSummary([...six,{id:"retry2",position:2001,slotIndex:2,status:"success",
  mediaId:"retry-3",imageUrl:"/api/media/retry3"}],6)[2].mediaId,"retry-3",
  "confirmed success on retry must outrank a failed attempt");
assert.equal(UI.slotSummary([...six,{position:2001,slotIndex:2,status:"generating"}],6)[2].status,"generating",
  "in-flight retry may coexist with an earlier failure");
assert.equal(UI.mediaUrl("javascript:alert(1)"),"");
assert.equal(UI.mediaUrl("//evil.example/steal"),"");
assert.equal(UI.mediaUrl("/api/media/1"),"/api/media/1");
const display={id:"disp",data:{kind:"batch_gallery",totalTarget:6,status:"generating",
  items:slots.map(s=>s.imageUrl?{imageUrl:s.imageUrl}:{failed:s.status==="failed"})}};
const projection={runId:"run-123",total:6,isTerminal:true,canRetry:true,slots};
const state=UI.galleryState(display,projection);
assert.equal(state.expected,6);
assert.equal(state.counts.success,3);
assert.equal(state.counts.failed,1);
assert.equal(UI.mayRetry(slots[2],projection),true);
assert.equal(UI.mayRetry(slots[3],projection),false);
assert.equal(UI.mayRetry(slots[2],{...projection,isTerminal:false}),false);
const compact=UI.galleryHtml(display,projection);
assert.match(compact,/系列结果组 · 6 张/);
assert.match(compact,/展开全部槽位/);
assert.doesNotMatch(compact,/data-disp-retry-slot/, "failed slots stay available after explicit expansion");
UI.toggleGallery("disp");
const expanded=UI.galleryHtml(display,projection);
assert.match(expanded,/data-disp-retry-slot="disp" data-slot="2"/);
assert.match(expanded,/data-disp-reference="disp"/);
assert.match(expanded,/handraw-1.webp/);
assert.match(expanded,/收起结果/);
assert.match(expanded,/data-disp-variant="disp" data-slot="0"/,
  "variant must carry the exact source slot, never a malformed attr");
assert.deepEqual(UI.toggleCompare("disp",0),[0]);
assert.deepEqual(UI.toggleCompare("disp",1),[0,1]);
assert.deepEqual(UI.selectedForCompare("disp"),[0,1]);
assert.match(UI.galleryHtml(display,projection),/对比选中（2）/);
assert.deepEqual(UI.toggleCompare("disp",0),[1]);
UI.toggleGallery("disp");
const graph={nodes:[{id:"c",type:"output_control",data:{runId:"run-123"}}]};
const summaries=UI.summarize(graph,()=>({runId:"run-123",viewStatus:"partial",total:6,
  succeeded:3,failed:1,queued:1,generating:1,isTerminal:false}));
assert.equal(summaries[0].text,"部分完成");
assert.equal(summaries[0].done,3);
const pending=UI.summarize(graph,()=>null)[0];
assert.equal(pending.done,null);
assert.match(pending.text,/待核实/);
assert.ok(entry.includes("studio-canvas-129.css")&&entry.includes("studio-canvas-ui.js"));
assert.ok(entry.indexOf("studio-canvas-ui.js")<entry.indexOf("studio-app.js"));
assert.match(app,/CanvasUI\.renderWorkspace\(/);
assert.match(app,/CanvasUI\.galleryHtml\(n,cloudRun\)/);
assert.match(app,/CanvasUI\.slotSummary\(payload\.items, projection\.total/);
assert.match(app,/function renderCanvasProductUI\(\)/);
assert.match(app,/function copyCanvasNodes\(\)/);
assert.match(app,/function pasteCanvasNodes\(\)/);
assert.match(app,/function newCanvasVisualAnnotation\(kind\)/);
assert.match(app,/data-disp-compare-view/);
assert.match(app,/onEdit:\(nodeId,field,raw\)=>/);
assert.match(app,/safeCount > 1/);
assert.match(app,/data-shelf-tab="templates"/);
assert.match(app,/e\.target\.closest\("\[data-canvas-no-zoom\], input, textarea, select/);
assert.match(app,/window\.HandrawCanvasRenderer\.preserveRuntime\(CS\.graph,CS\.undoStack\.pop\(\)\)/);
assert.match(app,/StudioViews\?\.classify\(CS\.graph\)/);
console.log("Canvas #129: 6-slot result group, failed-slot retry, server runs, authority & UI contract PASS");
