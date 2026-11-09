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

// #111: node-drag patches only incident SVG geometry and preserves all hit
// targets, edge group identities and unrelated pre-existing path attributes.
assert.match(app,/patchMovedEdgePaths\(/);
assert.match(app,/updateMinimapLensOnly\(\)/);
assert.match(app,/renderMinimapMovedNodes\(movedIds\)/);
assert.match(app,/const edgesRecomputed=!partial\|\|sizeChanged/);
const makePath=d=>{
  const attrs={d};let writes=0;
  return {
    getAttribute:k=>attrs[k]||null,
    setAttribute(k,v){attrs[k]=v;writes++;},
    get writes(){return writes;}
  };
};
function makeGroup(id){
  const hit=makePath("OLD-"+id),line=makePath("OLD-"+id);
  return {id,hit,line,getAttribute:key=>key==="data-edge-id"?id:null,
    querySelector:selector=>selector==="path.ic-edge-hit"?hit:
      selector==="path.ic-edge-line"?line:null};
}
const g1=makeGroup("e1"),g2=makeGroup("e2");
const graphEdges=[
  {id:"e1",from:"n0",to:"n1"},
  {id:"e2",from:"n2",to:"n3"}
];
const svgDrag={querySelectorAll:q=>{
  assert.equal(q,"g.ic-edge-group[data-edge-id]");
  return [g1,g2];
}};
const geom=(x1,y1,x2,y2)=>`M${x1},${y1} L${x2},${y2}`;
assert.equal(R.patchMovedEdgePaths(svgDrag,graphEdges,models,layer,["n0"],geom),true);
assert.notEqual(g1.hit.getAttribute("d"),"OLD-e1");
assert.equal(g1.hit.getAttribute("d"),g1.line.getAttribute("d"));
assert.equal(g1.hit.writes,1);
assert.equal(g1.line.writes,1);
assert.equal(g2.hit.getAttribute("d"),"OLD-e2");
assert.equal(g2.line.getAttribute("d"),"OLD-e2");
assert.equal(g2.hit.writes,0,"unrelated hit path must retain identity/geometry");
assert.equal(R.patchMovedEdgePaths(svgDrag,graphEdges,models,layer,["n0"],geom),true);
assert.equal(g1.hit.writes,1,"same geometry must not write path again");
const stale={querySelectorAll:()=>[g2]};
assert.equal(R.patchMovedEdgePaths(stale,graphEdges,models,layer,["n0"],geom),false,
  "missing incident SVG group must force complete re-render");
assert.equal(g2.hit.writes,0,"preflight failure must not partially modify unrelated edges");
const partial={querySelectorAll:()=>[g1,g2]};
assert.equal(R.patchMovedEdgePaths(partial,[...graphEdges,
  {id:"missing",from:"unknown",to:"n1"}],models,layer,["unknown"],geom),false);
assert.equal(g1.hit.writes,1,"invalid edge graph must leave existing DOM untouched");

console.log("CANVAS #111 indexed edges, drag patch and stable SVG DOM PASS "+
  JSON.stringify({nodes:n,edgeLookups:500,domQueries:selectCalls,
    measuredDimensions:widthReads,svgWrites:writes}));
