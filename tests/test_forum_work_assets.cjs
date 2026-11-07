"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const src = fs.readFileSync("demo/assets/forum-work-post.js", "utf8");
const S = {
  esc: (v) => String(v == null ? "" : v).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
  resourceLabel: (item) => item.name || item.id,
  channelUrl: (_target, p) => "/t/" + encodeURIComponent(p.id),
  filterDisplayPrompt: (v) => v,
};
const w = { HANDRAW_SHARED: S };
vm.runInNewContext(src, { window: w });
const workModule = w.HandrawForumWork;
assert.ok(workModule && workModule.fromTopic && workModule.render);
const topic = { title: "原创作品", workId: "work_001" };
const work = {
  id: "work_001", title: "原创作品", images: ["/media/original.webp"],
  styles: ["FA-003", "FB-006"], layout: "SC-021", promptMasked: true
};
const model = workModule.fromTopic(topic, [work], new Map(), false);
assert.equal(model.assets.length, 3, "Codes must survive before the catalog hydrates");
const html = workModule.render(model);
for (const code of ["FA-003", "FB-006", "SC-021"]) {
  assert.ok(html.includes(code), "Work detail should preserve source code " + code);
}
assert.match(html, /使用的画风与图型/);
assert.match(html, /href="\/t\/FA-003" target="_blank" rel="noopener noreferrer"/);
assert.match(html, /href="\/t\/SC-021" target="_blank" rel="noopener noreferrer"/);
assert.doesNotMatch(html, /SECRET_INTERNAL_PROMPT/);
const blank = workModule.fromTopic(topic, [{
  id: "work_001", title: "空元数据", images: ["/media/a.webp"],
  styles: [], layout: ""
}], new Map(), true);
const blankHtml = workModule.render(blank);
assert.match(blankHtml, /画风：原始生成记录未提供相关信息/);
assert.match(blankHtml, /图型：原始生成记录未提供相关信息/);
const hydrated = workModule.fromTopic(topic, [work], new Map([
  ["FA-003", {id:"FA-003",kind:"style",name:"画风三",image:"/fa3.webp"}],
  ["SC-021", {id:"SC-021",kind:"layout",name:"图型二十一",image:"/sc21.webp"}]
]), true);
assert.match(workModule.render(hydrated), /画风三/);
assert.match(workModule.render(hydrated), /图型二十一/);
console.log("work detail: style/layout codes, catalog and fallback, new-tab links OK");
