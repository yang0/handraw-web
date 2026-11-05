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
const { makeItems, renderCard, reconcileMediaRatio } = sandbox.window.HandrawMixedFeed.testing;

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
// Creation target ratios can differ from actual saved images: the card must
// shrink/grow to the real bitmap ratio, rather than letterbox the picture.
const ratioHtml = renderCard({ kind: "work", data: {
  ...works[0], ratio: "2:3"
}}, state);
assert.ok(ratioHtml.includes('class="hw-mf-media has-ratio"'));
assert.ok(ratioHtml.includes('style="aspect-ratio:2 / 3"'));
const media = {
  classList: { contains: (c) => c === "has-ratio" },
  style: { aspectRatio: "2 / 3" }
};
const loadedImage = { tagName: "IMG", naturalWidth: 1024, naturalHeight: 1024, parentElement: media };
assert.equal(reconcileMediaRatio(loadedImage), true, "wrong estimated aspect should be corrected");
assert.equal(media.style.aspectRatio, "1024 / 1024", "use decoded image ratio to remove top/bottom bands");
assert.equal(reconcileMediaRatio(loadedImage), false, "matching ratios should not trigger another layout");
assert.equal(reconcileMediaRatio({ ...loadedImage, naturalWidth: 0 }), false,
  "do not change placeholder before actual dimensions are available");
const accurateMedia = {
  classList: media.classList,
  style: { aspectRatio: "4 / 3" }
};
assert.equal(reconcileMediaRatio({ ...loadedImage, naturalWidth: 800, naturalHeight: 600,
  parentElement: accurateMedia }), false, "correct metadata must not cause relayout");

const textHtml = renderCard({ kind: "topic", data: {
  id: "discussion_test", title: "让整张卡片可点击", summary: "讨论内容"
}}, state);
assert.match(textHtml, /^<a class="hw-mf-card hw-mf-card--topic hw-mf-topic-link"/);
assert.match(textHtml, /href="\/forum\/discussion_test"/);
assert.ok(!textHtml.includes("<a class=\"hw-mf-title\""), "no nested links in discussion card");
assert.ok(textHtml.includes("讨论内容"), "summary remains visible");
// Loading the next page must append cards instead of recreating prior image elements.
let fullRenders = 0;
let appendedBatches = 0;
let lastAppend = "";
let pagerRemoved = false;
const grid = {
  insertAdjacentHTML(position, markup) {
    assert.equal(position, "beforeend");
    appendedBatches++;
    lastAppend = markup;
  }
};
const pager = { remove() { pagerRemoved = true; } };
const more = {};
let ratioCaptureListener = null;
let ratioListenerCount = 0;
const fakeRoot = {
  addEventListener(event, listener, capture) {
    if (event === "load" && capture) {
      ratioCaptureListener = listener;
      ratioListenerCount++;
    }
  },
  set innerHTML(markup) { this.html = markup; fullRenders++; },
  get innerHTML() { return this.html || ""; },
  querySelectorAll() { return []; },
  querySelector(selector) {
    if (selector === "#hw-mf-more") return more;
    if (selector === ".hw-mf-grid") return grid;
    if (selector === ".hw-mf-pager") return pager;
    return null;
  }
};
shared.App.state = state;
sandbox.window.HandrawMixedFeed.render(fakeRoot);
assert.equal(typeof ratioCaptureListener, "function", "capture image loads on the feed root");
const delegatedMedia = { classList: media.classList, style: { aspectRatio: "2 / 3" } };
ratioCaptureListener({ target: { ...loadedImage, parentElement: delegatedMedia } });
assert.equal(delegatedMedia.style.aspectRatio, "1024 / 1024", "late image load fixes visual bands");
assert.equal(ratioListenerCount, 1);
assert.equal(fullRenders, 1);
assert.equal(typeof more.onclick, "function");
more.onclick();
assert.equal(fullRenders, 1, "loading more must not rerender the page shell");
assert.equal(appendedBatches, 1, "append one batch of newly discovered cards");
assert.ok(lastAppend.includes("hw-mf-card"));
more.onclick();
assert.equal(fullRenders, 1);
assert.equal(appendedBatches, 2);
assert.equal(pagerRemoved, true, "remove pagination when everything is loaded");
console.log("Mixed feed composition, full-card navigation and append-only pagination passed.");
