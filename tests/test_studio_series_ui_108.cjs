"use strict";
/* #108 PlanSlot board is a view, not a second Run/Plan authority. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const Board=require("../demo/assets/studio-series-board-108.js");
const Series=require("../demo/assets/studio-series-plan.js");
const vm=require("node:vm");
const plan={slots:Array.from({length:6},(_,i)=>({
  slotId:"slot-108-"+(i+1),order:i,
  subject:i===0?'<script>alert("boom")</script>':"分镜 "+(i+1),
  overrides:i===2?{ratio:"2.35:1",layout:{id:"SC-022",type:"layout"}}:{},
  userOverrides:i===2?["ratio","layout"]:[],
  lockedFields:i===2?["ratio"]:[],referenceMedia:[],skipGlobalRefs:false
}))};
const snapshot={runId:"run108",candidateCount:1,outputs:
  plan.slots.map((s,i)=>({slotId:s.slotId,candidateIndex:0,outputIndex:i}))};
const output=(i,status,owned=true)=>({
 slotId:plan.slots[i].slotId,candidateIndex:0,outputIndex:i,status,
 mediaId:owned?"m"+i:"",imageUrl:owned?"/generated/108-"+i+".webp":"",
 errorCode:status==="failed"?"gateway_502":""
});
const projection={runId:"run108",isTerminal:false,outputs:[
  output(4,"generating",false),output(3,"failed",false),
  output(2,"success"),output(0,"success"),output(1,"success"),
  output(5,"unknown",false)
]};
const card=Board.render({plan,snapshot,projection,candidateCount:1,
 globalSpec:{style:{id:"FA-001"},layout:{id:"SC-021"},ratio:"3:4"},
 intent:"story-series",filter:"all",view:"cards",busy:true});
assert.equal((card.match(/data-series-slot-card=/g)||[]).length,6);
assert.ok(card.indexOf('data-series-slot-card="slot-108-1"')<
 card.indexOf('data-series-slot-card="slot-108-6"'),
 "PlanSlot order is stable across out-of-order V3 results");
assert.ok(card.includes('data-series-media="m2"'));
assert.ok(!card.includes("<script>"),"User subject must be escaped");
assert.match(card,/&lt;script&gt;alert/);
assert.ok(card.includes("独立比例 2.35:1"));
assert.ok(card.includes("本图图型 SC-022"));
assert.ok(card.includes("锁定：ratio"));
assert.ok(!card.includes('data-series-action="retry"'),
 "A failed output in a nonterminal Run is not advertised as safely retryable");
const failed=Board.render({plan,snapshot,
 projection:{...projection,isTerminal:true},
 candidateCount:1,filter:"failed",view:"cards"});
assert.equal((failed.match(/data-series-slot-card=/g)||[]).length,1);
assert.match(failed,/data-series-action="retry"/);
assert.match(failed,/data-series-output="3"/);
const ownedGate=Board.outputsFor(plan.slots[0],snapshot,
 {outputs:[{slotId:"slot-108-1",candidateIndex:0,outputIndex:0,
 status:"success",imageUrl:"/generated/should-not-display.webp",mediaId:""}]});
assert.equal(ownedGate[0].imageUrl,"");
assert.equal(ownedGate[0].status,"unknown");
assert.equal(Board.render({plan,snapshot,projection:{...projection,isTerminal:true},
 filter:"locked",view:"cards"}).match(/data-series-slot-card=/g)?.length,1);
const compact=Board.render({plan,view:"table",intent:"multi-format",
 candidateCount:2,filter:"all"});
assert.ok(!compact.includes("series108-card-head"));
assert.ok(compact.includes("实际输出 12 次"));
assert.ok(compact.includes("填入常用平台比例"));
assert.equal(Board.KINDS.length,4);
const source=fs.readFileSync("demo/assets/studio-batch.js","utf8");
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
const html=fs.readFileSync("demo/studio.html","utf8");
const css=fs.readFileSync("demo/assets/quick-create.css","utf8");
assert.ok(html.indexOf("studio-series-board-108.js")<html.indexOf("studio-batch.js"));
assert.match(source,/mountSeriesWorkspace\(parts,plan,candidateCount,remote,busy\)/);
assert.match(source,/Series\.patchSlot\(loop,slotId,\{subject:input\.value\}\)/);
assert.match(source,/if\(remote\?\.isTerminal&&output\.status==="failed"\)/);
assert.match(source,/Series\.move\(loop,slotId,idx-1\)/);
assert.match(source,/this\.hostElement\.querySelectorAll\("img\.series108-image/);
assert.match(app,/persistDraft: \(\) => \{ markActiveTabDirty\(\); persistOpenTabs\(\); \}/);
assert.match(css,/\.series108-layout\s*\{/);
assert.match(css,/@media\(max-width:460px\)/);
assert.equal(typeof Series.patchSlot,"function");
const sandbox={window:{},console,Map,Set,Array,Number,Math,JSON,Date};
vm.runInNewContext(source,sandbox);
assert.equal(typeof sandbox.window.HandrawBatchCreate.render,"function");
assert.equal(typeof sandbox.window.HandrawBatchCreate.mountSeriesWorkspace,"function");
console.log("Studio #108 PlanSlot cards, V3 status, filters, XSS, compact fallback & UI adapters PASS");
