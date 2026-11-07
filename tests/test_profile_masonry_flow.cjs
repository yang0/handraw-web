"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const shared = fs.readFileSync("demo/assets/shared.js","utf8");
const begin = shared.indexOf("  const profileMasonryBindings = new Map();");
const end = shared.indexOf("  function renderMasonry(", begin);
assert.ok(begin > 0 && end > begin, "Reusable measured profile masonry helper must exist");
const layoutCode = shared.slice(begin,end);
const css = fs.readFileSync("demo/assets/theme.css","utf8");
assert.match(css,/\.hw-profile-feed\s*\{[^}]*display:\s*grid;[^}]*grid-auto-flow:\s*row dense;/s);
assert.match(css,/\.hw-personal-gallery-grid\s*\{[^}]*display:\s*grid;[^}]*grid-auto-flow:\s*row dense;/s);
assert.doesNotMatch(css,/\.hw-profile-feed\s*\{[^}]*column-count\s*:/s,
  "CSS columns would fill vertically and leave most horizontal tracks empty");
assert.doesNotMatch(css,/\.hw-personal-gallery-grid\s*\{[^}]*column-count\s*:/s,
  "Gallery must not use vertically balanced CSS columns");
class FakeResizeObserver {
  constructor(cb) { this.cb=cb; this.nodes=[]; FakeResizeObserver.instances.push(this); }
  observe(el) { this.nodes.push(el); }
  disconnect() { this.disconnected=true; }
  trigger() { this.cb(); }
}
FakeResizeObserver.instances=[];
const sandbox = {
  window: {
    getComputedStyle:()=>({gridAutoRows:"8px",rowGap:"8px"}),
    requestAnimationFrame:fn=>fn()
  },
  ResizeObserver:FakeResizeObserver,
  setTimeout:fn=>fn(),
  Map, Array, Number, Math
};
const layout = vm.runInNewContext(layoutCode+"\nlayoutProfileMasonry;",sandbox);
function makeGrid(heights) {
  return {
    isConnected:true,
    children:heights.map(height=>({nodeType:1,scrollHeight:height,style:{}})),
    querySelectorAll(){return [];}
  };
}
for (const heights of [[500],[500,150,300],[510,160,220,320,140]]) {
  const grid=makeGrid(heights);
  layout(grid);
  assert.equal(FakeResizeObserver.instances.at(-1).nodes.length,heights.length+1,
    "Observer must track grid and image cards");
  for (let i=0;i<heights.length;i++) {
    assert.equal(grid.children[i].style.gridRowEnd,"span "+Math.ceil((heights[i]+8)/16),
      "Variable card height must be assigned a measured row span");
  }
}
const gallery=makeGrid([300,140,250]);
layout(gallery);
const initial=gallery.children[1].style.gridRowEnd;
gallery.children[1].scrollHeight=360;
FakeResizeObserver.instances.at(-1).trigger();
assert.notEqual(gallery.children[1].style.gridRowEnd,initial,
  "Lazy-loaded image height changes must trigger reflow");
layout(gallery);
assert.equal(FakeResizeObserver.instances.at(-2).disconnected,true,
  "Replacing gallery cards must detach the previous observer");
console.log("Profile masonry: 1/3/5 cards, variable heights, image reflow and observer cleanup passed");
