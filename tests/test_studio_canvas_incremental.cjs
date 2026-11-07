"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const source = fs.readFileSync("demo/assets/studio-app.js", "utf8");
assert.ok(source.includes("function patchStudioCanvasDom(layer, cardsHtml, datalistsHtml)"),
  "Canvas should patch node DOM by stable ID");
assert.ok(source.includes("studio2RenderedNodeMarkup.get(old) === html"),
  "Unchanged images and input cards should not be replaced");
assert.ok(source.includes("replacement.focus({ preventScroll: true })"),
  "A modified input node must restore keyboard focus");
assert.ok(!source.includes("DOM.nodesLayer.innerHTML = cardsHtml + datalistsHtml"),
  "Do not wholesale recreate all canvas nodes per progress/selection update");
assert.ok(source.includes("renderEdgesSvg();\n    bindNodeInteriorActions();"),
  "Existing graph wiring and node interactions remain in place");
console.log("Canvas incremental renderer contract passes; live browser/perf baseline still required");
