"use strict";
/* Exercise the production worker-queue source with deferred provider responses.
 * No account, provider, sleep, or browser needed.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const batch = fs.readFileSync("demo/assets/studio-batch.js", "utf8");
const start = studio.indexOf("      async function worker() {",
  studio.indexOf("async function runOutputControlNode("));
const end = studio.indexOf("      if (isStaleScope(runEpoch, runScope)) return false;", start);
assert.ok(start >= 0 && end > start, "Production bounded worker queue must exist");
const scheduler = studio.slice(start, end);
assert.match(scheduler, /await Promise\.all\(Array\.from/);
assert.match(scheduler, /nextSlotToLaunch\+\+/);
assert.match(scheduler, /batchRun\.cancelled/);
assert.match(studio, /Math\.min\(4,\s*Number\.isFinite\(requestedConcurrency\)/);
assert.match(studio, /pendingTasksBySlot/);
assert.match(studio, /slotPositions\.get\(x\.slotKey\)/);
assert.match(studio, /dn\.data\.items\[i\] = builtItem/, "Out-of-order image belongs at its slot index");
assert.match(studio, /dn\.data\.items\[i\] = failedItem/);
assert.match(studio, /activeLoopNode\.data\.completedCount = completedCount/);
assert.match(batch, /slotResults\.filter\(\(item\) => item\?\.imageUrl\)\.length/,
  "Visible images must be authoritative, not stale node completedCount");

const queueFactory = vm.runInNewContext(
  "(async function(slotIndexes, concurrency, batchRun, onSlot) {\n" +
  "let nextSlotToLaunch = 0;\nlet stopLaunching = false;\n" +
  "async function runSlot(i) { await onSlot(i); }\n" +
  scheduler + "\n})",
  {console}
);
function deferred() {
  let resolve;
  return {promise:new Promise(r => {resolve=r;}), resolve:()=>resolve()};
}
async function flush() { await new Promise(resolve => setImmediate(resolve)); }

(async()=>{
  // 5 tasks, capacity 2: exactly two HTTP requests can be in flight.
  const gates = Array.from({length:5}, deferred);
  const started=[], finished=[];
  let inflight=0,peak=0;
  const run = queueFactory([0,1,2,3,4],2,{cancelled:false}, async i => {
    started.push(i);
    inflight++;
    peak=Math.max(peak,inflight);
    try { await gates[i].promise; finished.push(i); }
    finally { inflight--; }
  });
  assert.deepEqual(started,[0,1], "2 concurrent requests start before either completes");
  gates[1].resolve();await flush();
  assert.deepEqual(started,[0,1,2], "Next queued slot starts as soon as one finishes");
  gates[2].resolve();await flush();
  assert.deepEqual(started,[0,1,2,3]);
  gates[0].resolve();await flush();
  assert.deepEqual(started,[0,1,2,3,4]);
  gates[4].resolve();gates[3].resolve();
  await run;
  assert.equal(peak,2,"Never exceed bounded concurrency");
  assert.deepEqual(finished,[1,2,0,4,3],"Provider completion is out of order");

  // Aborting after the initial requests prevents launching yet-unsent slots.
  const cancel={cancelled:false};
  const pending=[deferred(),deferred(),deferred(),deferred()];
  const cancelStarts=[];
  const cancelled=queueFactory([0,1,2,3],2,cancel,async i=>{
    cancelStarts.push(i); await pending[i].promise;
  });
  assert.deepEqual(cancelStarts,[0,1]);
  cancel.cancelled=true;
  pending[0].resolve();pending[1].resolve();
  await cancelled;
  assert.deepEqual(cancelStarts,[0,1],"Stop must not submit pending slots");

  assert.match(batch,/batch-concurrency/, "A 1-4 in-flight selector should be visible");
  console.log("batch concurrency: bounded execution, out-of-order, cancellation and truthful 2/2 source contracts OK");
})().catch(e=>{console.error(e);process.exitCode=1;});
