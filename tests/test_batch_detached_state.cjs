"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const start = source.indexOf("  function reconcileDetachedBatchState(");
const end = source.indexOf("  function savePrefs() {", start);
const busyStart = source.indexOf("        const isBatchCurrentBusy = () => {");
const busyEnd = source.indexOf("        const busy = isBatchCurrentBusy();", busyStart);
assert.ok(start > 0 && end > start && busyEnd > busyStart);
function fixture({run = null, quick = null, pending = false, image = true} = {}) {
  const bp = {
    ctrl: {id: "batch-control", data: {status: "generating"}},
    loop: {data: {status: "running", isStopping: true}}
  };
  const data = {
    status: "generating",
    items: image ? [{imageUrl: "/generated/completed.webp"}] : [],
    ...(pending ? {
      pendingTaskId: "cloud-task", pendingRequestId: "request-id",
      pendingTasksBySlot: {1: {taskId: "cloud-task", requestId: "request-id"}},
      pendingSpec: {"request-id": {slotKey: "1", prompt: "keep"}}
    } : {})
  };
  const state = {activeTabId: "tab-batch", pendingTasks: []};
  const ui = {progressState: {busy: true, isStopping: true}, setStopping() { throw Error("Must not lock detached UI"); }};
  const counts = {saved: 0, rendered: 0, messages: []};
  const sandbox = {
    bp, state, data, run, quick, ui,
    getDownstreamDisplayNodes: () => [{data}],
    getBatchParts: () => bp,
    persistOpenTabs: () => counts.saved++,
    renderQuickStart: () => counts.rendered++,
    toast: message => counts.messages.push(message),
    window: {HandrawBatchCreate: ui}
  };
  const api = vm.runInNewContext(
    "let _activeBatchRun = run; const CS = state; const quickBusy = quick; const activeCacheScope = 'user_1';\n" +
    source.slice(start, end) + "\n" + source.slice(busyStart, busyEnd) +
    "\n({busy: isBatchCurrentBusy, stop: cancelActiveBatchGeneration})", sandbox);
  return {api, bp, data, state, counts, ui};
}
// Reopening a completed batch used to leave Stop visible with no local owner.
const completed = fixture();
assert.equal(completed.api.busy(), false);
assert.equal(completed.bp.ctrl.data.status, "done");
assert.equal(completed.bp.loop.data.status, "idle");
assert.equal(completed.data.items[0].imageUrl, "/generated/completed.webp");
assert.equal(completed.ui.progressState, null);
assert.equal(completed.counts.saved, 1);
assert.equal(completed.api.busy(), false);
assert.equal(completed.counts.saved, 1, "Reconciliation must be idempotent");

// A click on an already-rendered stale Stop recovers the controls immediately.
const recovered = fixture({pending: true, image: false});
const recovery = JSON.stringify(recovered.data.pendingTasksBySlot);
assert.equal(recovered.api.stop("batch-control"), false);
assert.equal(recovered.counts.rendered, 1);
assert.match(recovered.counts.messages[0], /已清除页面残留/);
assert.equal(recovered.api.busy(), false);
assert.equal(recovered.bp.ctrl.data.status, "stopped");
assert.equal(recovered.data.pendingTaskId, "cloud-task");
assert.equal(recovered.data.pendingRequestId, "request-id");
assert.equal(JSON.stringify(recovered.data.pendingTasksBySlot), recovery);
assert.equal(recovered.data.pendingSpec["request-id"].prompt, "keep");

// Live local queues, including their stop-in-progress cleanup, keep ownership.
for (const cancelled of [false, true]) {
  const live = fixture({run: {ctrlId: "batch-control", cancelled}});
  assert.equal(live.api.busy(), true);
  assert.equal(live.bp.ctrl.data.status, "generating");
  assert.equal(live.counts.saved, 0);
}
const launching = fixture({quick: {id: "batch-control", scope: "user_1"}});
assert.equal(launching.api.busy(), true);
assert.equal(launching.counts.saved, 0);
const other = {ctrlId: "another-control", cancelled: false};
const unrelated = fixture({run: other});
assert.equal(unrelated.api.busy(), false);
assert.equal(unrelated.api.stop("batch-control"), false);
assert.equal(other.cancelled, false);
console.log("detached batch: restored controls, stale Stop, recovery IDs and live queue isolation OK");
