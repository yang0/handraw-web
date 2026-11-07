"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const make = fs.readFileSync("demo/assets/studio-make-image.js", "utf8");
const start = studio.indexOf("  function reconcileDetachedQuickState(parts) {");
const end = studio.indexOf("  function cancelActiveBatchGeneration(", start);
assert.ok(start > 0 && end > start, "Single-image stale state reconciliation must exist");
const reconcileCode = studio.slice(start, end);
assert.match(make, /id="make-image-btn-stop"/, "Busy quick mode must offer stop waiting button");
assert.match(make, /this\.actions\?\.cancel\?\.\(\)/, "Stop button must call the cancellation action");
assert.match(studio, /cancel:\s*\(\)\s*=>\s*\{[\s\S]*?cancelActiveBatchGeneration\(p\.ctrl\.id\)/,
  "Quick UI must use the live controller cancellation path");
assert.match(studio, /reconcileDetachedQuickState\(p\)/,
  "Stale status must be reconciled before quick UI busy computation");

function scenario({pending=false, hasResult=false, live=false}={}) {
  const ctrl = {id:"quick-ctrl", data:{status:"generating"}};
  const display = {id:"display-1", data:{
    status:"generating", items:hasResult ? [{imageUrl:"/image.webp"}] : [],
    ...(pending ? {pendingTaskId:"cloud-pending",pendingRequestId:"req-pending"} : {})
  }};
  const saved = [];
  const context = {
    CS:{pendingTasks:[],activeTabId:"quick-tab"},
    _activeBatchRun:live?{ctrlId:ctrl.id,cancelled:false}:null,
    quickBusy:null,activeCacheScope:"user-test",
    getDownstreamDisplayNodes:()=>[display],
    persistOpenTabs:()=>saved.push("persist"),
    window:{}
  };
  const fn = vm.runInNewContext(
    Object.keys(context).map(key=>"const "+key+" = deps."+key+";").join("\n")+
    "\n"+reconcileCode+"\nreconcileDetachedQuickState;", {deps:context});
  return {changed:fn({ctrl}), ctrl, display, saved};
}
{
  const run = scenario();
  assert.equal(run.changed,true);
  assert.equal(run.ctrl.data.status,"idle");
  assert.equal(run.display.data.status,"idle");
  assert.equal(run.saved.length,1);
}
{
  const run = scenario({pending:true});
  assert.equal(run.changed,true);
  assert.equal(run.ctrl.data.status,"stopped");
  assert.equal(run.display.data.pendingTaskId,"cloud-pending", "Cloud task IDs must stay recoverable");
  assert.equal(run.display.data.pendingRequestId,"req-pending");
}
{
  const run = scenario({hasResult:true});
  assert.equal(run.ctrl.data.status,"done");
  assert.equal(run.display.data.status,"done");
  assert.equal(run.display.data.items[0].imageUrl,"/image.webp");
}
{
  const run = scenario({live:true});
  assert.equal(run.changed,false,"Do not clear a live run");
  assert.equal(run.ctrl.data.status,"generating");
  assert.equal(run.saved.length,0);
}
// Simulate clicking the visible stop control in the quick UI.
{
  const sandbox = {HANDRAW_SHARED:{toast(){}},console,Map,Set,Array,Math,Number};
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.runInNewContext(make, sandbox);
  const controller = new sandbox.HandrawMakeImage.MakeImageController();
  const stopButton = {disabled:false,textContent:"停止等待"};
  const root = {
    querySelector(selector) { return selector === "#make-image-btn-stop" ? stopButton : null; },
    querySelectorAll() { return []; },
    addEventListener() {}
  };
  controller.context = {
    parts: {
      skill:{data:{colors:[],moods:[]}},
      text:{data:{}},ctrl:{data:{}},asset:{data:{}}
    },busy:true
  };
  let stops=0;
  controller.actions = {cancel() { stops++; return true; }};
  controller.bindEvents(root);
  assert.equal(typeof stopButton.onclick, "function", "Stop button must be bound");
  stopButton.onclick();
  assert.equal(stops,1,"Stop click must call the current run cancel action");
  assert.equal(stopButton.disabled,true,"Stop must suppress duplicate clicks");
  assert.match(stopButton.textContent,/正在停止/);
}
console.log("Quick restart recovery and stop-click interaction passed");
