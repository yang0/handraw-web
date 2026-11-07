"use strict";
/* Issue #100: work do-same must fill the real quick-creation graph, not a
 * MakeImage singleton whose render context may be uninitialized. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");

const begin = studio.indexOf("  function applyForkDraftToQuickNodes(draft) {");
const end = studio.indexOf("  if (window.HandrawMakeImage) {", begin);
assert.ok(begin > 0 && end > begin, "Canonical graph draft applier must exist");

const parts = {
  skill: { data: { style1: "", style2: "", layout: "" } },
  text: { data: { text: "" } },
  ctrl: { data: { mode: "graphic-text", ratio: "3:4" } },
};
let ensured = 0, persisted = 0, rendered = 0;
const context = {
  parts,
  CS: { stageView: "quick", forkGenerationSource: null },
  ensureQuickTab() { ensured++; },
  getQuickParts() { return parts; },
  normalizeMoodLabel: (x) => x,
  markActiveTabDirty() {},
  persistOpenTabs() { persisted++; },
  renderQuickStart() { rendered++; },
};
const apply = vm.runInNewContext(
  studio.slice(begin, end) + "\napplyForkDraftToQuickNodes", context
);
apply({
  styleIds: ["FA-011", "FB-022"], layoutId: "IG-006",
  colors: ["C-01"], tones: ["T-04"], moods: ["治愈"],
  customMood: "春日", whitespace: "留白", audience: "初中生",
  businessScene: "科普", subjectHint: "春日书店", ratio: "9:16",
  mode: "pure-image", source: { workId: "w_1", imageIndex: 1 }
});
assert.equal(ensured, 1);
assert.equal(persisted, 1);
assert.equal(rendered, 1);
assert.equal(parts.skill.data.style1, "FA-011");
assert.equal(parts.skill.data.style2, "FB-022");
assert.equal(parts.skill.data.fusion, true);
assert.equal(parts.skill.data.layout, "IG-006");
assert.equal(parts.skill.data.colors[0], "C-01");
assert.equal(parts.skill.data.tones[0], "T-04");
assert.equal(parts.skill.data.audience, "初中生");
assert.equal(parts.skill.data.businessScene, "科普");
assert.equal(parts.skill.data.customMood, "春日");
assert.equal(parts.text.data.text, "春日书店");
assert.equal(parts.ctrl.data.ratio, "9:16");
assert.equal(parts.ctrl.data.mode, "pure");
assert.equal(context.CS.forkGenerationSource.imageIndex, 1);

apply({ styleIds: ["FA-003"], layoutId: "SC-021", subjectHint: "另一张图", mode: "canvas" });
assert.equal(parts.skill.data.style1, "FA-003");
assert.equal(parts.skill.data.style2, "");
assert.equal(parts.skill.data.fusion, false);
assert.equal(parts.skill.data.layout, "SC-021");
assert.equal(parts.ctrl.data.mode, "graphic-text", "Unknown canvas mode must not destroy quick graph");
assert.equal(parts.text.data.text, "另一张图");

assert.match(studio, /const forkImage = params\.get\("image"\)/);
assert.match(studio, /applyForkDraftToQuickNodes\(data\.draft\)/);
assert.match(studio, /if \(!resp\.ok\)/);
assert.match(studio, /cleanUrl\.searchParams\.delete\("image"\)/);
console.log("Issue #100 quick fork hydration and mode fallback passed");
