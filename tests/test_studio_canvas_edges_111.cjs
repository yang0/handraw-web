"use strict";
/* #111 real 300-node edge geometry indexing / stable SVG-path DOM semantics. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const R=require("../demo/assets/studio-canvas-renderer.js");
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
const edgePart=app.split("function renderEdgesSvg() {")[1]
  ?.split("function renderVisualSlotHtml")[0]||"";
assert.ok(edgePart,"active Studio edge renderer missing");
assert.match(edgePart,/createEdgeGeometryIndex/);
assert.match(edgePart,/reconcileEdgeMarkup/);
assert.doesNotMatch(edgePart,/getNodeById\(e\.(?:from|to)\)/,
  "edge loop must not perform an O(N) linear Graph search per endpoint");
assert.doesNotMatch(edgePart,/getPortWorldPos\(n(?:From|To)/,
  "edge loop must not query DOM and measure sizes repeatedly");

const n=300,models=Array.from({length:n},(_,i)=>({
  id:"n"+i,x:i*19,y:i*3,w:320,h:230
}));
let selectCalls=0,widthReads=0,heightReads=0;
const elements=models.map((node,i)=>({
  getAttribute:name=>name==="data-node-id"?node.id:null,
  get offsetWidth(){widthReads++;return 312+(i%3)*8;},
  get offsetHeight(){heightReads++;return 145+(i%5)*6;}
}));
const layer={querySelectorAll:selector=>{
  assert.equal(selector,".ic-node[data-node-id]");selectCalls++;return elements;
}};
const idx=R.createEdgeGeometryIndex(models,layer);
const repeated=[];
for(let i=0;i<500;i++){
  const node=idx.getNode("n"+(i%150));
  assert.ok(node);
  repeated.push(idx.port(node,"out"),idx.port(node,"in"));
}
assert.equal(selectCalls,1,"one indexed DOM query per SVG render");
assert.equal(widthReads,150,"each used endpoint measured once, no repeated forced layout");
assert.equal(heightReads,150);
assert.deepEqual(idx.port(idx.getNode("n0"),"in"),{x:0,y:145/2});
assert.deepEqual(idx.port(idx.getNode("n0"),"out"),{x:312,y:145/2});
assert.equal(idx.getNode("missing"),null);
assert.deepEqual(idx.port(null,"out"),{x:0,y:0});

const fallback=R.createEdgeGeometryIndex(
  [{id:"unmounted",x:80,y:30,w:340,h:260}],{querySelectorAll:()=>[]});
assert.deepEqual(fallback.port(fallback.getNode("unmounted"),"out"),
  {x:420,y:160},"unmounted nodes keep exactly the prior Graph-geometry fallback");

let markup="",writes=0;
const svg={get innerHTML(){return markup},set innerHTML(v){markup=v;writes++;}};
assert.equal(R.reconcileEdgeMarkup(svg,'<g data-edge-id="e"></g>'),true);
assert.equal(writes,1);
const firstEdge="<g data-edge-id=\"e\"></g>";
assert.equal(R.reconcileEdgeMarkup(svg,firstEdge),false,
  "text edit/result status must preserve existing SVG paths");
assert.equal(writes,1);
assert.equal(R.reconcileEdgeMarkup(svg,'<g data-edge-id="e" class="is-selected"></g>'),true,
  "selection changes still repaint relevant SVG path markup");
assert.equal(writes,2);
R.clearEdgeMarkup(svg);
assert.equal(markup,"");
assert.equal(R.reconcileEdgeMarkup(svg,firstEdge),true,
  "blank Canvas must invalidate prior SVG markup before restoring a project");
assert.equal(writes,4);
console.log("CANVAS #111 indexed edges and stable SVG DOM PASS "+
  JSON.stringify({nodes:n,edgeLookups:500,domQueries:selectCalls,
    measuredDimensions:widthReads,svgWrites:writes}));
