"use strict";
/* Issue #113: imported "do same" themes belong in the editable textarea only. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("demo/assets/studio-make-image.js", "utf8");
const sandbox = { console, Map, Set, Array, String, Number, Boolean, Math, JSON, Date };
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.HANDRAW_SHARED = {
  esc: value => String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;"),
  toast() {}
};
vm.runInNewContext(source, sandbox);
assert.ok(sandbox.HandrawMakeImage?.MakeImageController);

const original = "天上·瑶台仙境：青绿远山浮于云海，仙鹤掠过月轮。";
function renderTheme(text, hint) {
  const p = {
    skill: { data: { style1: "FE-051", style2: "", layout: "EC-024", colors: ["C-15"] } },
    text: { data: { text, subjectHint: hint } },
    ctrl: { data: { mode: "graphic-text", ratio: "3:4", count: 1 } },
  };
  const root = {
    innerHTML: "",
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    removeEventListener() {},
  };
  const controller = new sandbox.HandrawMakeImage.MakeImageController();
  controller.render(root, {
    parts: p,
    graph: { nodes: [], edges: [] },
    catalog: { resourceMap: new Map(), styles: [], layouts: [], colors: [], tones: [] },
  }, {});
  return root.innerHTML;
}

const forkHtml = renderTheme(original, original);
assert.equal((forkHtml.match(/id="make-image-subject"/g) || []).length, 1);
assert.match(forkHtml, /id="make-image-subject"[\s\S]*?天上·瑶台仙境：[\s\S]*?<\/textarea>/);
assert.doesNotMatch(forkHtml, /id="make-image-clear-subject"/);
assert.match(forkHtml, /FE-051/);
assert.match(forkHtml, /EC-024/);
assert.doesNotMatch(forkHtml, /make-image-subject-banner|换成你的主题|原作主题：/);

const plainHtml = renderTheme("普通创作主题", "");
assert.equal((plainHtml.match(/id="make-image-subject"/g) || []).length, 1);
assert.match(plainHtml, /普通创作主题<\/textarea>/);
assert.doesNotMatch(plainHtml, /make-image-subject-banner|换成你的主题|原作主题：/);

console.log("Issue #113: fork theme appears once in editable subject textarea; banner removed.");
