"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const main = fs.readFileSync("demo/assets/main-app.js", "utf8");
const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const css = fs.readFileSync("demo/assets/studio-canvas.css", "utf8");

function extractHelper(source, start, end, name) {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing ${name} helper`);
  return vm.runInNewContext(source.slice(a, b) + "\n" + name, {});
}

// Profile V3: each logical run has ONE work containing all successful images.
// A duplicate record for that same work must not render a second card; work IDs
// are authoritative, so never collapse unrelated works by their batch labels.
const group = extractHelper(main, "  function groupProfilePublishedWorks(rows) {", "  async function loadProfilePublishedWorks(", "groupProfilePublishedWorks");
const result = group([
  { id: "w0", batchId: "gen_1", images: ["/first.png", "/second.png", "/third.gif"], coverUrl: "/second.png" },
  { id: "w0", batchId: "gen_1", images: ["/first.png", "/second.png", "/third.gif"], coverUrl: "/second.png" },
  { id: "w2", batchId: "work_w2", images: ["/solo.png"] },
]);
assert.equal(result.length, 2, "same work must show one profile card");
assert.equal(result[0].cover.id, "w0", "the canonical work ID drives the profile card");
assert.equal(result[0].total, 3, "all successful media belongs to one work");
assert.deepEqual(Array.from(result[0].cover.images), ["/first.png", "/second.png", "/third.gif"]);
assert.equal(result[0].cover.coverUrl, "/second.png", "author-selected cover is preserved");
assert.equal(result[1].cover.id, "w2", "standalone work must remain distinct");
assert.ok(main.includes('data-prof-work="${esc(cover.id)}"'), "click should still use canonical published work ID");
assert.ok(main.includes('UI.profileWorkRows = [...merged.values()]'), "profile must use authoritative author feed");
assert.ok(main.includes("profileWorksHasMore"), "pagination must be supported");

// Studio: query across creation mode, date, style code, ratio and status without
// indexing masked prompt data.
const category = extractHelper(studio, "  function historyRecordCategory(h) {", "  function historyStatusCategory(h) {", "historyRecordCategory");
const status = extractHelper(studio, "  function historyStatusCategory(h) {", "  function historySearchText(h) {", "historyStatusCategory");
const search = extractHelper(studio, "  function historySearchText(h) {", "  function renderHistoryStage() {", "historySearchText");
const record = {
  id: "gen_9", createdAt: "2026-11-07 09:30", mode: "article-illust",
  recipeSummary: "画风 #FA-003", status: "success", promptMasked: true,
  prompt: "SECRET_INTERNAL_PROMPT",
  recipeSnapshot: { styles: ["FA-003"], layoutId: "IG-001" },
  items: [{ title: "封面", ratio: "2.35:1", imageUrl: "/cover.png" }],
};
const hay = search(record);
for (const q of ["2026-11-07", "fa-003", "ig-001", "2.35:1", "封面"]) {
  assert.ok(hay.includes(q), `history search must index ${q}`);
}
assert.ok(!hay.includes("secret_internal_prompt"), "masked prompt must not enter search index");
assert.equal(category(record), "article");
assert.equal(category({ kind: "series" }), "batch");
assert.equal(category({ recipeId: "rcp_1" }), "quick");
assert.equal(category({ kind: "single" }), "other", "Missing source must not default to canvas");
assert.equal(category({ kind: "single", creationSource: "quick" }), "quick");
assert.equal(category({ kind: "single", creationSource: "canvas" }), "canvas");
assert.equal(status({ status: "queued" }), "active");
assert.equal(status({ status: "failed" }), "failed");
assert.equal(status(record), "success");
assert.ok(studio.includes('prompt: normalized.promptMasked ? ""'), "server prompt masking must override local cache");
assert.ok(studio.includes("normalized.promptMasked ? null"), "do not keep masked recipe snapshots");
assert.ok(studio.includes('id="hist-status-filter"') && studio.includes('id="hist-sort"'));
assert.ok(studio.includes("data-hist-image-download"), "individual image download must be available");
assert.ok(studio.includes("prevScrollTop"), "history rerender must preserve scroll");
assert.ok(!studio.includes('id="hist-clear-all"'), "bulk destructive delete control must be removed");
assert.ok(studio.includes("恢复到当前画布"), "restore must warn before changing the workspace");
assert.ok(css.includes(".ic-history-controls") && css.includes("@media (max-width: 768px)"));

console.log("Profile and studio P2/P3: batch grouping, search, permissions and UI safety checks passed");
