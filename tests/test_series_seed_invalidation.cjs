"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function loadController() {
  const sandbox = { window: {}, globalThis: {}, console, Map, Set };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync("demo/assets/studio-batch.js", "utf8"), sandbox);
  return sandbox.HandrawBatchCreate;
}

test("#152: starting a new series clears old plan, image slots and workspace outputs", () => {
  const component = loadController();
  const loop = {data: {
    batchSeed: "新的母题", batchCount: 3, batchRows: [{theme:"旧主题",layout:"SC-021"}],
    promptListText: "旧主题", activeBatchId:"old", status:"done", currentStep:3
  }};
  const ctrl = {id:"ctrl",data:{status:"done",activeBatchId:"old",activeBatchTotal:3}};
  const display = {data:{kind:"batch_gallery",items:[{imageUrl:"/old.webp"}],status:"done",activeBatchId:"old"}};
  let cleared = 0;
  component.context = {parts:{loop,ctrl},results:[{imageUrl:"/old.webp",index:0}],displays:[display]};
  component.actions = {clearWorkspaceResults(id){assert.equal(id,"ctrl");cleared++;}};
  component.activeBatchId = "old";
  component.seriesOutcomes = new Map([[0,{imageUrl:"/old.webp"}]]);
  component.progressState = {busy:false,batchId:"old"};
  component.lastSummary = "全部完成";
  component.clearSeriesForNewPlan(3);
  assert.equal(cleared,1);
  assert.equal(loop.data.batchRows.length,3);
  assert.equal(loop.data.batchRows.every(row=>row.theme==="" && row.layout===""),true);
  assert.equal(loop.data.promptListText.trim(),"");
  assert.equal(loop.data.activeBatchId,undefined);
  assert.equal(ctrl.data.activeBatchId,undefined);
  assert.equal(component.seriesOutcomes.size,0);
  assert.equal(component.context.results.length,0);
  assert.equal(display.data.items.length,0);
  assert.equal(component.lastSummary,"");
});

test("#152: new-theme plan and direct run both have invalidation guards", () => {
  const source = fs.readFileSync("demo/assets/studio-batch.js","utf8");
  assert.match(source,/self\.clearSeriesForNewPlan\(loop\.data\.batchCount\)/);
  assert.match(source,/revision !== self\.planRevision/);
  assert.match(source,/currentSeed !== self\.plannedSeed/);
  assert.match(source,/await btnPlan\?\.onclick\?\.\(\)/);
});
