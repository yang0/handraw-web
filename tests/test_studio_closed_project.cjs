"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const src = fs.readFileSync("demo/assets/studio-app.js","utf8");
const start=src.indexOf("  function archiveClosedProjectDraft(");
const end=src.indexOf("  function closeWorkflowTab(",start);
assert.ok(start>0 && end>start,"Close-tab backup code is extractable");
assert.ok(src.includes("CLOSED_PROJECT_DRAFTS_KEY"),"Closed drafts have dedicated account-scoped storage");
assert.ok(src.includes("if (!archiveClosedProjectDraft(closing)) return;"),
  "A failed local backup must prevent destructive tab closing");
const fragment=src.slice(start,end);

function createHarness(fail=false) {
  const CS={closedProjectDrafts:[]};
  const writes=[],messages=[];
  const storage={setItem:(key,data)=>{
    if(fail)throw new Error("QuotaExceededError");
    writes.push({key,data:JSON.parse(data)});
  }};
  const context={CS,localStorage:storage,CLOSED_PROJECT_DRAFTS_KEY:"closed",
    scopedStorageKey:key=>"account-A::"+key,
    cloneGraph:graph=>JSON.parse(JSON.stringify(graph)),
    toast:message=>messages.push(message)};
  vm.createContext(context);
  vm.runInContext(fragment+"\nglobalThis.testArchive=archiveClosedProjectDraft",context);
  return {CS,context,writes,messages};
}
const tab={id:"tab-closed",title:"离线画布",blueprint:"single",
  graph:{nodes:[{id:"local"}],edges:[]},projectId:"prj-existing",
  projectRevision:3,projectSaveState:"error",
  editRevision:6,projectPending:{method:"PATCH",payload:{
    idempotencyKey:"keep-original-key",baseRevision:3
  }},vx:230,vy:50,vk:0.9};
{
  const h=createHarness();
  assert.equal(h.context.testArchive(tab),true);
  assert.equal(h.CS.closedProjectDrafts.length,1);
  assert.equal(h.writes[0].key,"account-A::closed");
  assert.equal(h.writes[0].data[0].projectPending.payload.idempotencyKey,"keep-original-key");
  assert.equal(h.writes[0].data[0].graph.nodes[0].id,"local");
  assert.equal(h.CS.closedProjectDrafts[0].projectSaveState,"error");
  assert.equal(h.context.testArchive(tab),true,"Saving same closed tab is idempotent");
  assert.equal(h.CS.closedProjectDrafts.length,1);
}
{
  const h=createHarness(true);
  assert.equal(h.context.testArchive(tab),false,
    "Quota error cannot cause silent loss of unsynced closed tab");
  assert.equal(h.CS.closedProjectDrafts.length,0);
  assert.ok(h.messages.some(x=>x.includes("空间不足")));
}
{
  const h=createHarness();
  assert.equal(h.context.testArchive({...tab,projectPending:null,projectSaveState:"synced"}),true);
  assert.equal(h.writes.length,0,"Fully synced project doesn't require duplicate local backup");
}
console.log("Closed Project recovery backup passed: persisted outbox, quota protection, idempotency");
