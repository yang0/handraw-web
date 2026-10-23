"use strict";
const assert = require("node:assert/strict"),
  fs = require("node:fs"),
  vm = require("node:vm");
const window = {};
vm.runInNewContext(fs.readFileSync("plugin/public/composer-core.js", "utf8"), {
  window,
});
const resources = JSON.parse(
  fs.readFileSync("plugin/content/catalog.json", "utf8"),
).resources;
const options = JSON.parse(
  fs.readFileSync("plugin/content/studio-options.json", "utf8"),
);
assert.equal(options.modes.length, 6);
assert.equal(options.tones.length, 16);
assert.ok(options.ratios.some((r) => r.value === "2.35:1"));
assert.equal(options.shoot_types.length, 10);
assert.equal(options.moods.length, 15);
const draft = {
  mode: "poster",
  theme: "写一张秋天读书活动海报",
  style: "FA-001",
  color: "C-01",
  ratio: "5:2",
  audience: "亲子家庭",
  channel: "公众号",
  mood: "松弛、治愈",
  whitespace: "high",
  tones: ["T-01", "T-04"],
  batch: true,
  mix_layouts: true,
  asset_refs: ["CH-001"],
};
const command = window.HandrawComposerCommand(draft, resources, options);
for (const token of [
  "海报提示词",
  "亲子家庭",
  "公众号",
  "大量留白",
  "5:2",
  "高调",
  "软调",
  "批量出图",
  "混合多种图型",
  "CH-001",
])
  assert.ok(command.includes(token), token);
const fusion = window.HandrawComposerCommand(
  {
    ...draft,
    fusion: true,
    character_style: "realistic",
    scene_style: "FA-001",
  },
  resources,
  options,
);
assert.ok(fusion.includes("角色风格：写实"));
assert.ok(fusion.includes("场景风格：FA-001"));
assert.ok(
  window
    .HandrawComposerCommand(draft, resources, options, "en")
    .includes("Audience: 亲子家庭"),
);
assert.ok(!command.includes("undefined"));
console.log(
  "Skill command: complete mode, tone, whitespace, ratio, audience, channel, references, fusion and batch options passed",
);
