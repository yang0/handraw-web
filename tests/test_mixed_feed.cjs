"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const shared = {
  App: { state: {} },
  esc: (v) => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;"),
  channelUrl: (channel, params) => "/" + channel + "/" + (params && params.id || ""),
  resourceLabel: (r) => r.name || r.id
};
const sandbox = { window: { HANDRAW_SHARED: shared } };
const file = path.join(__dirname, "..", "demo", "assets", "mixed-feed.js");
vm.runInNewContext(fs.readFileSync(file, "utf8"), sandbox, { filename: file });
const { makeItems, renderCard } = sandbox.window.HandrawMixedFeed.testing;

const works = Array.from({ length: 40 }, (_, i) => ({
  id: "work_" + i, title: "测试作品 " + i, images: ["/w" + i + ".webp"],
  status: "published", likes: 100 - i, author: "user_" + i
}));
works.push({ ...works[0] }); // repeated work must be deduplicated
works.push({ id: "hidden", title: "隐藏内容", images: ["/hidden.webp"], status: "deleted" });

const resources = Array.from({ length: 10 }, (_, i) => ({
  id: "FA-" + i, name: "画风 " + i, image: "/style" + i + ".webp"
}));
const topics = Array.from({ length: 10 }, (_, i) => ({
  id: "topic_" + i, category: "experience", title: "经验 " + i, summary: "技巧"
}));
topics.push({ id: "work_topic", category: "showcase", title: "作品原生讨论" });
topics.push({ id: "linked_topic", category: "experience", workId: "work_0", title: "绑定作品讨论" });

const state = { works, topics, discussions: {} };
const mixed = makeItems(state, resources, [], { tab: "recommended" });
const first20 = mixed.slice(0, 20);
assert.equal(first20.filter((item) => item.kind === "work").length, 15, "work-first 75% mix");
assert.equal(first20.filter((item) => item.kind === "resource").length, 3, "resource 15% mix");
assert.equal(first20.filter((item) => item.kind === "topic").length, 2, "independent discussions 10% mix");
assert.equal(mixed.filter((item) => item.kind === "work").length, 40, "same work shown once");
assert.equal(mixed.filter((item) => item.kind === "topic").length, 10, "linked discussions excluded");

const single = makeItems(state, resources, [], { tab: "work", query: "测试作品 12" });
assert.equal(single.length, 1);
assert.equal(single[0].data.id, "work_12");
const resourceOnly = makeItems(state, resources, [], { tab: "resource" });
assert.equal(resourceOnly.length, 10);
const html = renderCard({ kind: "work", data: { ...works[0], title: "<script>" } }, state);
assert.ok(!html.includes("<script>"), "work title must be escaped");
assert.ok(html.includes("用同款做一张"), "remix entry exists");
console.log("Mixed feed contract tests passed.");
