"use strict";
/* Server-owned RunSlots override transient Graph busy and older failed Item. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const Core=require("../demo/assets/studio-core.js");
const Canvas=require("../demo/assets/studio-canvas-ui.js");
const Quick=require("../demo/assets/studio-quick-spec.js");
const Series=require("../demo/assets/studio-series-plan.js");
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");

assert.deepEqual([...Core.RUN_PERSISTED].sort(),
  ["cancelled","failed","partial","pending","running","success","uploading"].sort());
assert.deepEqual([...Core.ITEM_PERSISTED].sort(),
  ["cancelled","failed","generating","pending","success"].sort());
assert.ok(!Core.RUN_PERSISTED.has("unknown"));
assert.ok(!Core.ITEM_PERSISTED.has("cancel_requested"));

const run={id:"run119",source:"web",status:"running",expectedCount:6};
const items=[
  ...[0,1,2].map(i=>({id:"item"+i,position:i*1000,slotIndex:i,
    status:"success",mediaId:"m"+i,imageUrl:"/generated/"+i+".webp"})),
  ...[3,4].map(i=>({id:"item"+i,position:i*1000,slotIndex:i,status:"failed"}))
];
const slots=Array.from({length:6},(_,i)=>({
  slotIndex:i,viewStatus:i<3?"success":i<5?"failed":"running",
  mediaId:i<3?"m"+i:"",imageUrl:i<3?"/generated/"+i+".webp":"",
  retryAllowed:i===3||i===4
}));
let p=Core.selectRunProjection(run,items,{authoritativeSlots:slots});
assert.deepEqual([p.total,p.succeeded,p.failed,p.generating,p.queued,p.unknown],
  [6,3,2,1,0,0]);
assert.equal(p.isTerminal,false);
assert.equal(p.viewStatus,"running");
const pendingRetry=[...slots];pendingRetry[3]={...slots[3],viewStatus:"running",retryAllowed:false};
p=Core.selectRunProjection(run,items,{authoritativeSlots:pendingRetry});
assert.deepEqual([p.succeeded,p.failed,p.generating],[3,1,2]);
assert.equal(p.processed,4);
assert.equal(p.viewStatus,"running");
const cancel=Core.selectRunProjection(run,items,{
  authoritativeSlots:pendingRetry,cancelRequested:true});
assert.equal(cancel.viewStatus,"cancel_requested");
assert.equal(cancel.persistedStatus,"running");
assert.ok(!Core.RUN_PERSISTED.has(cancel.viewStatus));
const unknownSlots=[{slotIndex:0,viewStatus:"unknown"}];
const unconfirmed=Core.selectRunProjection({id:"r1",status:"running",
  expectedCount:1,source:"web"},[],{authoritativeSlots:unknownSlots});
assert.equal(unconfirmed.succeeded,0);
assert.equal(unconfirmed.unknown,1);
assert.equal(unconfirmed.isTerminal,false);
const confirmed=Core.selectRunProjection({id:"r1",status:"running",
  expectedCount:1,source:"web"},[
    {slotIndex:0,position:0,status:"success",mediaId:"m",
      imageUrl:"/generated/one.webp"}],{
    authoritativeSlots:[{slotIndex:0,viewStatus:"success",
      mediaId:"m",imageUrl:"/generated/one.webp"}]
  });
assert.equal(confirmed.succeeded,1);
assert.equal(confirmed.isTerminal,true);
// Successful media must never be counted based solely on a local guessed URL.
const group={id:"out",data:{totalTarget:6,kind:"batch_gallery",status:"generating",
  items:[{imageUrl:"/generated/local-unconfirmed.webp"}]}};
let visible=Canvas.galleryState(group,{
  runId:"run119",slots:[{index:0,status:"unknown",imageUrl:""}]
});
assert.equal(visible.slots[0].imageUrl,"");
assert.equal(visible.counts.success,0);
assert.equal(visible.counts.unknown,1);
assert.equal(visible.counts.pending,5); // no synthetic completed items
assert.equal(typeof Quick.projectRun,"function");
assert.equal(typeof Series.project,"function");
const quick=Quick.projectRun({ok:true,run,items,slots});
assert.equal(quick.succeeded,3);
assert.equal(quick.failed,2);
assert.equal(quick.generating,1);
assert.match(app,/async function recheckStudioControl\(controlId\)/);
assert.match(app,/fetch\("\/api\/studio\/runs\/"\+encodeURIComponent\(runId\)/);
assert.match(app,/fetch\("\/api\/studio\/tasks\?"\+params\.toString\(\)/);
assert.match(app,/canvasRunModels\.clear\(\)/);
assert.match(app,/idempotencyKey: requestId/);
assert.match(app,/retryFailed: resolvedOnlyIdx !== null/);
assert.match(app,/不保证退款/);
console.log("Studio Runtime #119 Node projection, no false-success, retry/recovery contract PASS");
