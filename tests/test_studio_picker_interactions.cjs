"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

// Issue #95: clicked pickers must never become silent no-ops while previous
// image-generation tasks remain pending. Also cover keyboard activation.
const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
function bridge(start, end) {
  const i = studio.indexOf(start);
  assert.ok(i >= 0, "Missing resource-picker bridge: " + start);
  const j = studio.indexOf(end, i);
  assert.ok(j > i, "Missing resource-picker bridge end: " + end);
  return studio.slice(i, j);
}
const batchBridge = bridge(
  "openAssetPicker: ({ kind, field, current, onPick, title } = {}) => {",
  "openReferencePicker:", 
);
const quickBridge = bridge(
  "openAssetPicker: ({ kind, field, currentId, onSelect } = {}) => {",
  "openReferencePicker:",
);
assert.doesNotMatch(batchBridge, /isBatchCurrentBusy\(\)/, "Pending batches must not silently lock resource selection");
assert.doesNotMatch(quickBridge, /isCurrentBusy\(\)/, "Pending image jobs must not silently lock resource selection");
assert.match(quickBridge, /onPick:\s*\(id,\s*ref\)\s*=>/, "Selection must propagate catalog ResourceRef");
assert.match(quickBridge, /onSelect\(id,\s*ref\)/, "Picker must forward verified source and version, not only ID");
assert.match(batchBridge, /catch\s*\(err\)/, "Picker failures must be visible");

function load(file, name) {
  const sandbox = {console, HANDRAW_SHARED: {toast() {}}, Map, Set, Array, String, Number, Math};
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.runInNewContext(fs.readFileSync(file, "utf8"), sandbox, {filename: file});
  assert.ok(sandbox[name]);
  return sandbox[name];
}
function runPickerEvents(name, controller) {
  const options = [];
  const cards = ["style1", "style2", "layout", "color"].map(kind => ({
    kind,
    getAttribute(attr) { return attr === "data-pick-kind" ? kind : null; },
    closest() { return null; },
    onclick: null,
    onkeydown: null
  }));
  const root = {
    querySelector() { return null; },
    querySelectorAll(selector) { return selector === "[data-pick-kind]" ? cards : []; },
    addEventListener() {},
    classList: {toggle() {}}
  };
  const parts = {
    skill: {data: {style1:"", style2:"", layout:"", colors:[], tones:[], moods:[]}},
    ctrl: {data: {}},
    loop: {data: {promptListText:"", batchRows:[]}},
    asset: {data: {items: []}},
    text: {data: {}}
  };
  controller.context = {parts, busy:true, catalog:{styles:[], layouts:[], colors:[]}};
  controller.actions = {openAssetPicker(opts) {options.push(opts);}, markDirtyAndRender() {}};
  controller.bindEvents(root, parts, []);
  for (const card of cards) {
    assert.equal(typeof card.onclick, "function", name + " missing click for " + card.kind);
    assert.equal(typeof card.onkeydown, "function", name + " missing keyboard support for " + card.kind);
    card.onclick({target:{closest(){return null;}}});
    card.onkeydown({key:"Enter",target:card,preventDefault(){}});
    card.onkeydown({key:" ",target:card,preventDefault(){}});
    const before = options.length;
    card.onclick({target:{closest(){return {};}}});
    assert.equal(options.length,before,name + " clear click must not open picker");
  }
  assert.equal(options.length, cards.length * 3, name + " click/keyboard must open all pickers");
  assert.deepEqual(options.map(o => o.kind).slice(0,3), ["style1","style1","style1"]);
}
const MakeImage = load("demo/assets/studio-make-image.js", "HandrawMakeImage");
runPickerEvents("做图", new MakeImage.MakeImageController());
const Batch = load("demo/assets/studio-batch.js", "HandrawBatchCreate");
runPickerEvents("批量", Batch);
console.log("Studio resource pickers: click, Enter, Space, clear click and pending-task access passed");
