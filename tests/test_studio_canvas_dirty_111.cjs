"use strict";
/* #111 P2: strict partial-reconcile DOM boundary with no other nodes touched. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const Renderer=require("../demo/assets/studio-canvas-renderer.js");
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
assert.match(app,/function renderWorldNodes\(changedNodeIds = null\)/);
assert.match(app,/renderNodes=partial\?nodes\.filter/);
assert.match(app,/patchStudioCanvasDirtyDom\(DOM\.nodesLayer,cardsHtml\)/);
assert.match(app,/renderWorldNodes\(\[groupId\]\)/);
assert.match(app,/renderWorldNodes\(\[disp\.id\]\)/);
assert.match(app,/renderWorldNodes\(\[id\]\)/);
assert.match(app,/const partial=Boolean\(mounted&&mounted\.size===nodes\.length/);

let layer;
const doc={activeElement:null,createElement(name){
  assert.equal(name,"template");
  let text="";
  return {
    content:{children:[]},
    set innerHTML(html){
      text=html;
      this.content.children=[...text.matchAll(/<div class="([^"]+)" data-node-id="([^"]+)" data-content="([^"]+)"><\/div>/g)]
        .map(x=>makeNode(x[2],x[3],x[1]));
    },
    get innerHTML(){return text;}
  };
}};
function makeNode(id,content,cls="ic-node"){
  const classes=new Set(cls.split(" ").filter(Boolean));
  const n={
    tagName:"DIV",
    ownerDocument:doc,
    id:null,
    outerHTML:`<div class="${cls}" data-node-id="${id}" data-content="${content}"></div>`,
    getAttribute(name){return name==="data-node-id"?id:null;},
    classList:{contains:name=>classes.has(name),toggle:(name,on)=>on?classes.add(name):classes.delete(name)},
    querySelectorAll:()=>[],
    contains:()=>false,
    remove(){
      const i=layer.children.indexOf(n);
      if(i>=0)layer.children.splice(i,1);
    },
    replaceWith(other){
      const i=layer.children.indexOf(n);
      assert.ok(i>=0);
      layer.children[i]=other;
    }
  };
  return n;
}
const a=makeNode("a","old"),b=makeNode("b","untouched");
const datalist={
  tagName:"DATALIST",id:"ic-datalist-audience",ownerDocument:doc,remove(){
    const i=layer.children.indexOf(datalist);
    if(i>=0)layer.children.splice(i,1);
  }
};
layer={ownerDocument:doc,children:[a,b,datalist],appendChild(el){this.children.push(el);}};
const markup=(id,content)=>`<div class="ic-node" data-node-id="${id}" data-content="${content}"></div>`;
const partial=Renderer.reconcile(layer,markup("a","fresh"),"",true);
assert.equal(partial.stats.partial,true);
assert.equal(partial.stats.nodes,1);
assert.equal(partial.stats.replaced,1);
assert.equal(partial.stats.removed,0);
assert.deepEqual(partial.stats.changedIds,["node:a"]);
assert.notStrictEqual(layer.children[0],a);
assert.strictEqual(layer.children[1],b,"unaffected card DOM must remain identical");
assert.strictEqual(layer.children[2],datalist,"untouched shared datalist must survive");
assert.equal(layer.children.length,3);

const noop=Renderer.reconcile(layer,markup("a","fresh"),"",true);
assert.equal(noop.stats.partial,true);
assert.equal(noop.stats.reused,1);
assert.equal(noop.stats.replaced,0);
assert.strictEqual(layer.children[1],b);
assert.throws(()=>Renderer.reconcile(layer,markup("missing","x"),"",true),
  /canvas_dirty_render_invariant/,"new nodes cannot use dirty-update path");
assert.strictEqual(layer.children[1],b);

const full=Renderer.reconcile(layer,markup("a","final"),"",false);
assert.equal(full.stats.partial,false);
assert.equal(full.stats.removed,2,"full reconcile still owns deleted cards and datalists");
assert.equal(layer.children.length,1);
console.log("CANVAS #111 dirty-node renderer contract PASS: targeted parse, no unrelated removal, strict guard and full fallback");
