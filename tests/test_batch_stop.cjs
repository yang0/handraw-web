"use strict";
/* Issue #85: Stop aborts local transport, but not necessarily upstream jobs. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const batchSource = fs.readFileSync("demo/assets/studio-batch.js", "utf8");
const start = studio.indexOf("  function cancelActiveBatchGeneration(");
const end = studio.indexOf("  function savePrefs() {", start);
assert.ok(start > 0 && end > start, "Stop handler must exist");
const handler = studio.slice(start, end);
const messages = [];
let stopping = 0;
let aborts = 0;
const run = {
  ctrlId:"ctrl_batch", cancelled:false,
  submittedSlots:new Set(["0", "1"]),
  controller:{
    signal:{aborted:false},
    abort() {aborts += 1; this.signal.aborted = true;}
  }
};
const state = {activeBatchRun:null};
const context = {
  run, state,
  toast:message=>messages.push(message),
  window:{HandrawBatchCreate:{setStopping:()=>{stopping++;}}}
};
const stop = vm.runInNewContext(
  "let _activeBatchRun = run;\nconst CS = state;\n" + handler + "\ncancelActiveBatchGeneration",
  context
);
assert.equal(stop("not_this_ctrl"), false, "Must not stop an unrelated job");
assert.equal(run.cancelled,false);
assert.equal(aborts,0);
assert.equal(stop("ctrl_batch"),true);
assert.equal(run.cancelled,true);
assert.equal(run.controller.signal.aborted,true, "Browser POST/poll must abort");
assert.equal(aborts,1);
assert.equal(stopping,1);
assert.equal(state.activeBatchRun,run);
assert.match(messages.at(-1),/2 张已发出的图片仍可能在云端完成或计费/);
assert.equal(stop("ctrl_batch"),false,"Repeated stops must be idempotent");
assert.equal(aborts,1);
assert.equal(stopping,1);
const empty = {
  ctrlId:"ctrl_batch",cancelled:false,submittedSlots:new Set(),
  controller:{signal:{aborted:false},abort(){this.signal.aborted=true;}}
};
const emptyStop=vm.runInNewContext(
  "let _activeBatchRun = run;\nconst CS = state;\n" + handler + "\ncancelActiveBatchGeneration",
  {...context,run:empty}
);
assert.equal(emptyStop("ctrl_batch"),true);
assert.match(messages.at(-1),/尚未提交的图片不会计费/);
assert.match(studio, /const batchRun = \{ id: batchId, ctrlId: ctrl\.id, cancelled: false, controller, submittedSlots \}/);
assert.match(studio, /signal: controller \? controller\.signal : undefined/);
assert.match(studio, /if \(batchRun\.cancelled\) return;/);
assert.match(studio,/ctrl\.data\.status = "stopped"/);
assert.match(studio,/if \(bp\.ctrl\.data\.status === "stopped"\) return false;/);
assert.match(studio,/pendingTasksBySlot/, "Stop must retain per-slot recovery IDs");
assert.match(batchSource,/const cancelled = self\.actions\.cancel\(\)/);
assert.match(batchSource,/if \(cancelled !== false\) self\.setStopping\(\)/);
const sandbox = {window:{}};
sandbox.window=sandbox;
vm.runInNewContext(batchSource,sandbox);
const ui=sandbox.HandrawBatchCreate;
ui.hostElement={querySelector(){return null;}};
ui.activeBatchId="batch_123";
ui.progressState={
  batchId:"batch_123",completedCount:0,failedCount:0,
  totalCount:2,activeIndex:0,activeIndices:[0,1],
  busy:true,isStopping:false
};
ui.setStopping();
assert.equal(ui.progressState.isStopping,true);
ui.updateProgress({
  batchId:"batch_123",completedCount:1,totalCount:2,failedCount:0,
  activeIndex:null,activeIndices:[1],busy:true,isStopping:false
});
assert.equal(ui.progressState.isStopping,true,
  "Late progress must not undo Stop state");
ui.updateProgress({
  batchId:"batch_123",completedCount:1,totalCount:2,failedCount:0,
  activeIndex:null,activeIndices:[],busy:false,isStopping:false
});
assert.equal(ui.progressState.isStopping,false,"Final local result clears Stop state");
// Waiting for the next cloud polling tick is part of the active operation:
// aborting must settle it immediately rather than waiting another 2200 ms.
const sleepStart = studio.indexOf("  function cancelledTaskWaitError() {");
const sleepEnd = studio.indexOf("  async function pollCloudTask(", sleepStart);
assert.ok(sleepStart > 0 && sleepEnd > sleepStart, "Abortable poll delay must exist");
const sleep = vm.runInNewContext(
  studio.slice(sleepStart, sleepEnd) + "\nwaitForCloudPollInterval",
  {setTimeout,clearTimeout,Promise,Error}
);
(async () => {
  const controller = new AbortController();
  const waiting = sleep(10000, controller.signal);
  controller.abort();
  await assert.rejects(waiting, (err) => err && err.name === "AbortError");
  console.log("batch Stop: abort, idempotence, isolation, billing, polling and sticky UI OK");
})().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
