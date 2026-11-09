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
assert.match(app,/createEdgeDragSession\(/);
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


// P2 drag session is built AFTER the selection SVG redraw, not recreated on
// each pointermove. All updates remain bound to the exact live Graph arrays.
assert.match(app,/createEdgeDragSession\(/);
assert.match(app,/dragCtx\.edgeSession\.update\(/);
assert.match(app,/focusCanvasNodeForBenchmark:/);
assert.match(app,/_drag111Samples/);
assert.match(app,/function captureDragOverlayMetrics\(startPositions\)/,
  "measure the toolbar and viewport after selection, before drag updates");
assert.match(app,/function validDragOverlayMetrics\(metrics\)/,
  "graph, viewport, DOM, zoom and selection references must be checked");
assert.match(app,/positionFloatingOverlays\(dragCtx\.overlayMetrics\)/,
  "real pointermove must use the cached toolbar measurements");
assert.match(app,/dragCtx\.overlayMetrics=null/,
  "viewport resize must invalidate the cached toolbar dimensions");
assert.match(app,/overlayMs:overlayEnd-edgesEnd/);
assert.match(app,/minimapMs:minimapEnd-overlayEnd/);

// A pure position drag may skip only the terminal full DOM regeneration;
// any stale Graph/selection/edge/DOM identity is a mandatory full fallback.
assert.match(app,/ctx\.lastGraph===CS\.graph/,
  "pointerup fast path must belong to the same graph object");
assert.match(app,/ctx\.lastNodes===CS\.graph\?\.nodes/,
  "pointerup fast path invalidates on model list replacement");
assert.match(app,/ctx\.lastEdges===CS\.graph\?\.edges/,
  "pointerup fast path invalidates on edge list replacement");
assert.match(app,/ctx\.lastSelection===ids/,
  "pointerup fast path invalidates on selection changes");
assert.match(app,/ctx\.lastEdgeTrusted===true/,
  "do not skip full render if edge drag session was invalidated");
assert.match(app,/if\(!safe\)fullRenderCanvas\(\)/,
  "stale DOM always falls back to authoritative full render");
assert.match(app,/if\(window\.__HANDRAW_TESTING__===true && DOM\.nodesLayer\)/,
  "finish mode instrumentation must be test-only");
assert.doesNotMatch(app,/canvasDragPositionMode/,
  "failed CSS translate experiment must not remain enabled in production");
// #111 Phase 7 diagnostic-only ablation: never bypass visuals for normal
// user interactions. Release in every non-normal mode must use full render.
assert.match(app,/window\.__HANDRAW_TESTING__===true\?\s*window\.HANDRAW_STUDIO_TESTING\?\.canvasDragVisualProbeMode/,
  "ablation controls must be isolated to __HANDRAW_TESTING__");
assert.match(app,/diagMode==="no-card"/,
  "measure card coordinate style writes independently");
assert.match(app,/diagMode==="no-edges"/,
  "measure incident SVG path writes independently");
assert.match(app,/diagMode==="no-overlay"/,
  "measure floating toolbar style writes independently");
assert.match(app,/diagMode==="no-minimap"/,
  "measure minimap SVG rect writes independently");
assert.match(app,/diagMode==="node-only"/,
  "measure native card left/top writes without other canvas updates");
assert.match(app,/diagMode==="no-visual"/,
  "isolate pointer-capture drag even when all canvas visuals are bypassed");
assert.match(app,/visualProbeMode:diagMode/,
  "every real pointer event must record the active test-only diagnostic mode");
assert.match(app,/dragCtx\.lastEdgeTrusted=Boolean\(usedSession\)&&diagMode==="normal"/,
  "any visual bypass must force an authoritative pointerup full render");
assert.match(app,/if\(!safe\)fullRenderCanvas\(\)/,
  "full pointerup fallback must remain in place");

// The old full-layout path remains authoritative whenever a session becomes
// stale; do not remove it just to make 300-node synthetic numbers look good.
assert.match(app,/DOM\.viewport\.getBoundingClientRect\(\)\.width/);

let edgeDomQueries=0,graphDomQueries=0;
const cachedSvg={querySelectorAll(selector){
  assert.equal(selector,"g.ic-edge-group[data-edge-id]");
  edgeDomQueries++;
  return [g1,g2];
}};
const cachedLayer={querySelectorAll(selector){
  assert.equal(selector,".ic-node[data-node-id]");
  graphDomQueries++;
  return elements;
}};
const dragGraph=[
  {id:"e1",from:"n0",to:"n1"},
  {id:"e2",from:"n2",to:"n3"}
];
const widthBeforeDragSession=widthReads,heightBeforeDragSession=heightReads;
const dragSession=R.createEdgeDragSession(cachedSvg,dragGraph,models,
  cachedLayer,["n0"],geom);
const dragSessionWidthReads=widthReads,dragSessionHeightReads=heightReads;
assert.equal(dragSessionWidthReads-widthBeforeDragSession,2,
  "measure the two linked endpoints once at drag start");
assert.equal(dragSessionHeightReads-heightBeforeDragSession,2);
assert.ok(dragSession);
assert.equal(dragSession.incidentCount,1);
assert.equal(edgeDomQueries,1);
assert.equal(graphDomQueries,1);
models[0].x+=25;
assert.equal(dragSession.update(dragGraph,models),true);
assert.equal(g1.hit.getAttribute("d"),g1.line.getAttribute("d"));
const firstSessionPath=g1.hit.getAttribute("d");
models[0].x+=40;
assert.equal(dragSession.update(dragGraph,models),true);
assert.notEqual(g1.hit.getAttribute("d"),firstSessionPath);
assert.equal(edgeDomQueries,1,"no full edge enumeration for every frame");
assert.equal(graphDomQueries,1,"no full card query for every frame");
assert.equal(widthReads,dragSessionWidthReads,
  "drag pointermove must NEVER force offsetWidth layout reads");
assert.equal(heightReads,dragSessionHeightReads,
  "drag pointermove must NEVER force offsetHeight layout reads");
assert.equal(g2.hit.getAttribute("d"),"OLD-e2",
  "unrelated edge hit path must remain untouched");
assert.equal(dragSession.update([...dragGraph],models),false,
  "a new Graph edges array must invalidate the session");
assert.equal(dragSession.update(dragGraph,[...models]),false,
  "a new Graph nodes array must invalidate the session");
dragGraph.push({id:"e3",from:"n0",to:"n3"});
assert.equal(dragSession.update(dragGraph,models),false,
  "an in-place topology growth must invalidate the session");
dragGraph.pop();
const oldEdgeTo=dragGraph[0].to;
dragGraph[0].to="n3";
assert.equal(dragSession.update(dragGraph,models),false,
  "an in-place endpoint reassignment must invalidate the session");
dragGraph[0].to=oldEdgeTo;
const oldConnected=g1.isConnected;
g1.isConnected=false;
assert.equal(dragSession.update(dragGraph,models),false,
  "a disconnected SVG group must invalidate the session");
g1.isConnected=oldConnected;
const origLine=g1.line;
g1.querySelector=(selector)=>selector==="path.ic-edge-hit"?g1.hit:null;
const invalidSession=R.createEdgeDragSession(cachedSvg,dragGraph,models,
  cachedLayer,["n0"],geom);
assert.equal(invalidSession,null,"missing hit/line means full fallback");
g1.querySelector=selector=>selector==="path.ic-edge-hit"?g1.hit:
  selector==="path.ic-edge-line"?origLine:null;
// Two moving endpoints and zero incident edges must both stay safe.
const both=R.createEdgeDragSession(cachedSvg,dragGraph,models,cachedLayer,
  ["n0","n1"],geom);
assert.ok(both&&both.update(dragGraph,models));
const none=R.createEdgeDragSession(cachedSvg,dragGraph,models,cachedLayer,
  ["n4"],geom);
assert.ok(none&&none.update(dragGraph,models));
assert.equal(none.incidentCount,0);
dragSession.dispose();
assert.equal(dragSession.update(dragGraph,models),false,
  "disposed sessions must not alter SVG");
both.dispose();
none.dispose();

// Real browsers use ResizeObserver notifications AFTER layout to refresh
// cached endpoint dimensions, avoiding forced layout in pointermove itself.
const originalRO=globalThis.ResizeObserver,observers=[];
globalThis.ResizeObserver=class {
  constructor(callback){this.callback=callback;this.targets=[];this.disconnected=false;observers.push(this);}
  observe(el){this.targets.push(el);}
  disconnect(){this.disconnected=true;}
};
try{
  const obsSession=R.createEdgeDragSession(cachedSvg,dragGraph,models,
    cachedLayer,["n0"],geom);
  assert.ok(obsSession);
  const ro=observers.at(-1);
  assert.equal(ro.targets.length,2,
    "the ResizeObserver should watch incident endpoints, not the entire graph");
  const prevWidth=Object.getOwnPropertyDescriptor(elements[0],"offsetWidth");
  const beforePath=g1.hit.getAttribute("d");
  Object.defineProperty(elements[0],"offsetWidth",
    {configurable:true,get(){widthReads++;return 490;}});
  try{
    const oldReads=widthReads;
    ro.callback([{target:elements[0]}]);
    assert.equal(widthReads,oldReads+1,
      "resize observer may read new measured dimensions after layout");
    const readsAfterNotification=widthReads;
    assert.equal(obsSession.update(dragGraph,models),true);
    assert.notEqual(g1.hit.getAttribute("d"),beforePath,
      "a real endpoint resize updates incident SVG path");
    assert.equal(widthReads,readsAfterNotification,
      "pointer update uses ResizeObserver cache without layout reads");
  }finally{
    Object.defineProperty(elements[0],"offsetWidth",prevWidth);
  }
  obsSession.dispose();
  assert.equal(ro.disconnected,true,
    "every drag must disconnect the ResizeObserver");
  assert.equal(obsSession.update(dragGraph,models),false);
}finally{
  if(originalRO===undefined)delete globalThis.ResizeObserver;
  else globalThis.ResizeObserver=originalRO;
}


console.log("CANVAS #111 indexed edges, drag-session and stable SVG DOM PASS "+
  JSON.stringify({nodes:n,edgeLookups:500,domQueries:selectCalls,
    measuredDimensions:widthReads,svgWrites:writes}));
