"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const batchSource = fs.readFileSync("demo/assets/studio-batch.js", "utf8");
const appSource = fs.readFileSync("demo/assets/studio-app.js", "utf8");

function controller() {
  const context = { window: {}, globalThis: {}, Map, Set, console };
  context.window = context;
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(batchSource, context);
  return context.HandrawBatchCreate;
}

test("#154 active retry displays generating animation before old failed result", () => {
  const batch = controller();
  batch.activeBatchId = "batch-1";
  batch.progressState = {busy:true,batchId:"batch-1",activeIndices:[2]};
  const priorFailure = {index:2, failed:true, error:"previous failed",batchId:"batch-1"};
  assert.equal(batch.getRowStatus(2,true,0,priorFailure,2).key,"generating");
  assert.equal(batch.getRowStatus(1,true,0,priorFailure,2).key,"failed");
  batch.progressState = {busy:false,batchId:"batch-1",activeIndices:[]};
  assert.equal(batch.getRowStatus(2,false,0,priorFailure,null).key,"failed");
});

test("#154 single retry reconciles persisted generating status before quickBusy lock", () => {
  const start = appSource.indexOf("runSingleRow: async (rowIndex) => {");
  assert.ok(start >= 0);
  const segment = appSource.slice(start,start + 1200);
  const reconcile = segment.indexOf("reconcileDetachedBatchState(bp)");
  const lock = segment.indexOf("quickBusy = { id: bp.ctrl.id, scope }");
  assert.ok(reconcile >= 0, "stale flag reconciler must be called");
  assert.ok(lock > reconcile, "lock must be acquired AFTER reconciling stale status");
});

test("#154 retry handler propagates rejected generation promise", () => {
  assert.match(batchSource,/Promise\.resolve\(\)\.then\(\(\) => self\.actions\.runSingleRow\(idx\)\)/);
  assert.match(batchSource,/重试未能启动/);
});
