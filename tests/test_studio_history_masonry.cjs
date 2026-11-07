"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");

const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const styles = fs.readFileSync("demo/assets/studio-canvas.css", "utf8");
const start = studio.indexOf("  function historyRecordCategory(h) {");
const end = studio.indexOf("  /* ======================== VIEWPORT", start);
assert.ok(start >= 0 && end > start, "Studio history helpers and stage must exist");

const records = [
  { id: "cover_mode", mode: "article-cover", kind: "single", items: [{ title: "文章封面", imageUrl: "/cover1.webp" }], status: "success" },
  { id: "cover_legacy", mode: "poster", kind: "single", items: [{ title: "单独生成封面图", imageUrl: "/cover2.webp" }], status: "success" },
  { id: "batch", mode: "graphic-text", kind: "loop", items: [
    { imageUrl: "/batch1.webp", title: "一" }, { imageUrl: "/batch2.webp", title: "二" }, { imageUrl: "/batch3.webp", title: "三" }
  ], status: "success" },
  { id: "quick", mode: "poster", recipeId: "rcp_a", kind: "single", items: [
    { imageUrl: "/quick1.webp" }, { imageUrl: "/quick2.webp" }
  ], status: "success" },
  { id: "canvas", mode: "graphic-text", kind: "single", items: [
    { imageUrl: "/canvas1.webp" }, { imageUrl: "/canvas2.webp" }
  ], status: "success" },
];
const state = {
  stageView: "history", generationHistory: records,
  historyFilter: "all", historyStatusFilter: "all", historyQuery: "",
  historySort: "newest", historyPage: 1,
  historyExpandedPromptIds: {}, historyExpandedBatchIds: {}, historySelectedPreview: {}
};
const stage = {
  style: {}, innerHTML: "", expandBindings: [],
  querySelector() { return null; },
  querySelectorAll(selector) {
    if (selector !== "[data-hist-expand-batch]") return [];
    this.expandBindings = [...this.innerHTML.matchAll(/data-hist-expand-batch="([^"]+)"/g)]
      .map((match) => ({ id: match[1], onclick: null, getAttribute() { return match[1]; } }));
    return this.expandBindings;
  }
};
const compile = new Function(
  "DOM", "CS", "S", "esc", "ensureGenerationHistoryInitialized", "document", "window", "toast",
  "renderTopAndBottomDocks", "deleteCloudHistory", "restoreHistoryEntryToCanvas", "exportZipFromPayload",
  studio.slice(start, end) + "\nreturn { historyRecordCategory, historyImageCount, renderHistoryStage };"
);
const app = compile(
  { historyStage: stage }, state, { filterDisplayPrompt: (x) => x },
  (x) => String(x ?? ""), () => {}, { activeElement: null },
  { history: { replaceState() {} }, confirm: () => true }, () => {}, () => {}, () => {}, () => {}, () => {}
);
const sums = { quick: 0, batch: 0, article: 0, canvas: 0 };
for (const record of records) sums[app.historyRecordCategory(record)] += app.historyImageCount(record);
assert.equal(Object.values(sums).reduce((a, b) => a + b, 0), 9);
assert.equal(sums.article, 2, "Independent cover images must be under article");
assert.equal(sums.batch, 3);
assert.equal(sums.quick, 2);
assert.equal(sums.canvas, 2);

app.renderHistoryStage();
assert.match(stage.innerHTML, /生图历史 · 9 张/);
assert.match(stage.innerHTML, /data-hist-filter="all">全部 \(9\)/);
assert.match(stage.innerHTML, /data-hist-filter="article">文章配图 \(2\)/);
assert.match(stage.innerHTML, /data-hist-filter="batch">批量 \(3\)/);
assert.match(stage.innerHTML, /data-hist-filter="quick">做图 \(2\)/);
assert.match(stage.innerHTML, /data-hist-filter="canvas">画布 \(2\)/);
assert.equal((stage.innerHTML.match(/class="ic-hist-cover-button"/g) || []).length, 5,
  "Only one cover image should be rendered per generation task");
assert.ok(!stage.innerHTML.includes("ic-hist-expanded-gallery"), "Batches should start folded");
assert.ok(!stage.innerHTML.includes("hist-back-creation"), "History must not have a back button");
assert.ok(!stage.innerHTML.includes("hist-empty-back-creation"));
const batchButton = stage.expandBindings.find((button) => button.id === "batch");
assert.ok(batchButton && typeof batchButton.onclick === "function", "Click handler must be installed");
batchButton.onclick();
assert.equal(state.historyExpandedBatchIds.batch, true);
assert.ok(stage.innerHTML.includes("ic-hist-expanded-gallery"), "Batch images should expand inside masonry card");
assert.equal((stage.innerHTML.match(/data-hist-img-toggle="batch"/g) || []).length, 3,
  "Opening a batch must reveal all three images");

state.historyFilter = "article";
app.renderHistoryStage();
assert.ok(stage.innerHTML.includes('data-hist-id="cover_mode"'));
assert.ok(stage.innerHTML.includes('data-hist-id="cover_legacy"'));
assert.ok(!stage.innerHTML.includes('data-hist-id="batch"'));
assert.match(stage.innerHTML, /生图历史 · 9 张/, "Total count must be unchanged by a category filter");

assert.ok(styles.includes("max-width: 1140px"), "Toolbar must be contained");
assert.ok(styles.includes(".ic-hist-masonry-grid") && styles.includes("column-count: 3"));
assert.ok(styles.includes("column-count: 2") && styles.includes("column-count: 1"));
console.log("Studio history: 9-image category totals, cover recognition, masonry and batch reveal passed");
