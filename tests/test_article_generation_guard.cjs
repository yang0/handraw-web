"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const guardSrc = fs.readFileSync("demo/assets/article-generation-guard.js", "utf8");
const studioSrc = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const context = {window:{}};
vm.runInNewContext(guardSrc,context);
const guard = context.window.HandrawArticleGenerationGuard;
assert.ok(guard);
const cards = [
  {id:"ready-1",status:"done",imageUrl:"/img/1.png"},
  {id:"ready-2",status:"done",imageUrl:"/img/2.png"},
  {id:"ready-3",status:"done",imageUrl:"/img/3.png"},
  {id:"waiting",status:"idle",imageUrl:""},
  {id:"failed",status:"error",imageUrl:""}
];
assert.deepEqual(Array.from(guard.pendingCards(cards),x=>x.id),["waiting","failed"],
  "only unfinished cards may enter the batch queue");
assert.equal(guard.pendingCards(cards.slice(0,3)).length,0,
  "completed articles must never schedule a paid batch");
assert.equal(guard.pendingCards([{status:"generating"}]).length,0);
const q = guard.quote(2,{demo:false,free:1,unitPrice:2,balance:6});
assert.equal(q.ok,true);
assert.equal(q.freeUsed,1);
assert.equal(q.paidCount,1);
assert.equal(q.total,2);
assert.equal(q.affordable,true);
assert.equal(guard.quote(3,{free:0,unitPrice:2,balance:4}).affordable,false);
assert.equal(guard.quote(2,{free:undefined,unitPrice:2,balance:6}).ok,false,
  "unknown free quota must not be guessed");
assert.equal(guard.quote(2,{free:1,unitPrice:undefined,balance:6}).ok,false,
  "unknown unit price must not be guessed");
assert.equal(guard.quote(1,{demo:true}).total,0);
assert.equal(guard.quote(0,{demo:true}).ok,false);
assert.equal(typeof guard.confirmGeneration(1,{free:undefined,unitPrice:2,balance:6}).then,"function",
  "cross-VM promises should be verified by their thenable contract");
assert.match(studioSrc,/const effectiveTargets = guard\.pendingCards\(allCards\)/);
assert.match(studioSrc,/skipCostConfirmation: true/);
assert.match(studioSrc,/await confirmArticleGenerationCost\(effectiveTargets\.length/);
assert.match(studioSrc,/await confirmArticleGenerationCost\(1,/);
assert.match(studioSrc,/promptFromSkill: Boolean\(sourcePrompt\)/);
assert.match(studioSrc,/generateBatchPlanCards\(draft\.id, \{ onlyPending: true \}\)/);
assert.match(studioSrc,/生成剩余配图/);
console.log("article generation safeguards: selected scope, no duplicate batch, price and prompt contract OK");
