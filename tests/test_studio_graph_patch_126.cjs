"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const G=require("../demo/assets/studio-graph-patch-126.js");
const ui=fs.readFileSync("demo/assets/studio-canvas-ui.js","utf8");
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
const entry=fs.readFileSync("demo/studio.html","utf8");
assert.equal(G.contextValid(
  {projectId:"own",baseRevision:3,graphRevision:7,saveState:"synced"},
  {projectId:"own",baseRevision:3,graphRevision:7,saveState:"synced"}),true);
assert.equal(G.contextValid(
  {projectId:"own",baseRevision:3,graphRevision:7,saveState:"synced"},
  {projectId:"own",baseRevision:4,graphRevision:7,saveState:"synced"}),false);
assert.equal(G.contextValid(
  {projectId:"own",baseRevision:3,graphRevision:7,saveState:"synced"},
  {projectId:"other",baseRevision:3,graphRevision:7,saveState:"synced"}),false);
assert.equal(G.contextValid(
  {projectId:"own",baseRevision:3,graphRevision:7,saveState:"synced"},
  {projectId:"own",baseRevision:3,graphRevision:7,saveState:"dirty"}),false);
const html=G.summarize({summary:{nodesAdded:1,nodesRemoved:2,fieldsChanged:1,
  edgesAdded:3,edgesRemoved:4},
  costImpact:{additionalPotentialImages:2,estimatedAdditionalCredits:4},
  diffs:[{op:"setNodeData",path:"nodes/a/data/text",
    before:'private <img src=x onerror=alert(1)>',
    after:"new"}],
  conflicts:[{nodeId:"node_a",field:"subject",code:"locked_field"}]});
assert.match(html,/锁定冲突/);
assert.match(html,/4 积分/);
assert.doesNotMatch(html,/<img src=x onerror=/);
assert.match(html,/&lt;img src=x/);
assert.match(ui,/data-c129="graphpatch"/);
assert.match(app,/GraphPatchUI.open\(/);
assert.match(app,/onApplied:\(response,expected\)=>/);
assert.match(app,/ctx.baseRevision!==Number\(expected\?\.baseRevision\)/);
assert.match(entry,/studio-graph-patch-126.js/);
assert.match(entry,/studio-graph-patch-126.css/);
assert.ok(entry.indexOf("studio-graph-patch-126.js")<entry.indexOf("studio-app.js"));
const source=fs.readFileSync("demo/assets/studio-graph-patch-126.js","utf8");
assert.match(source,/confirmed:true/);
assert.match(source,/\/preview/);
assert.match(source,/\/apply/);
assert.match(source,/\/undo/);
assert.doesNotMatch(source,/\/api\/studio\/generate/);
console.log("GRAPH #126 browser module, review conflict, safe HTML and app wiring PASS");
