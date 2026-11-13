// Canvas menu regression guard: preserve four actions and a single floating undo.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const js = fs.readFileSync(path.resolve(__dirname, "../demo/assets/studio-app.js"), "utf8");
const css = fs.readFileSync(path.resolve(__dirname, "../demo/assets/studio-canvas.css"), "utf8");
new Function(js);
const toolbar = js.split("function renderCanvasToolstrip() {")[1].split("/* ======================== CLEAN SINGLE-COLUMN")[0];
assert.match(toolbar, /id="bc-undo"/);
assert.match(toolbar, /class="ic-canvas-undo-btn"/);
for (const removed of ['class="ic-float-pill"', 'id="bc-redo"', 'id="bl-arrange"']) {
  assert.ok(!toolbar.includes(removed), "obsolete canvas toolbar control: " + removed);
}
for (const action of ["new", "save", "export", "open"]) {
  assert.ok(js.includes('id="tb-canvas-' + action + '"'), "missing canvas action " + action);
}
assert.match(js, /\.slice\(0, 10\)/);
assert.match(js, /!wf\.isOfficialPreset/);
assert.match(js, /data-canvas-recent-open/);
assert.match(js, /title: active\.title, blueprint: CS\.graph\.blueprint, graph: cloneGraph\(CS\.graph\)/);
assert.ok(!js.includes('id="bl-save-wf"'), "duplicate bottom-right save action");
assert.match(css, /\.ic-canvas-more:hover > \.ic-canvas-more-menu/);
assert.match(css, /\.ic-canvas-open-wrap:hover > \.ic-canvas-recent-panel/);
console.log("Canvas toolbar regression guards passed");
