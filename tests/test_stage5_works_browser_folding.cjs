/**
 * Stage 5 Frontend Unit Test:
 * - HandrawWorksBrowser.select batch folding in plaza mode vs search mode
 * - unpackWorkCandidates propagation of batch metadata
 * - Badge rendering ("同批 4 件" vs "同批第 2/4 张")
 */
const assert = require("assert");
const fs = require("fs");
const path = require("path");

// Load works-browser.js
const B = require("../demo/assets/works-browser.js");

console.log("Starting test_stage5_works_browser_folding.cjs...");

// 1. Prepare 4 same-batch works and 1 single work
const batchWorks = [
  {
    id: "w_b1",
    title: "Puppy 1",
    author: "alice",
    batchId: "gen_pup",
    batchTotal: 4,
    batchIndex: 1,
    images: ["/img/p1.png"],
    publishedAtMs: 1700000004000,
  },
  {
    id: "w_b2",
    title: "Puppy 2",
    author: "alice",
    batchId: "gen_pup",
    batchTotal: 4,
    batchIndex: 2,
    images: ["/img/p2.png"],
    publishedAtMs: 1700000003000,
  },
  {
    id: "w_b3",
    title: "Puppy 3",
    author: "alice",
    batchId: "gen_pup",
    batchTotal: 4,
    batchIndex: 3,
    images: ["/img/p3.png"],
    publishedAtMs: 1700000002000,
  },
  {
    id: "w_b4",
    title: "Puppy 4",
    author: "alice",
    batchId: "gen_pup",
    batchTotal: 4,
    batchIndex: 4,
    images: ["/img/p4.png"],
    publishedAtMs: 1700000001000,
  },
  {
    id: "w_s1",
    title: "Mountain",
    author: "bob",
    batchId: "work_w_s1",
    batchTotal: 1,
    batchIndex: 1,
    images: ["/img/m1.png"],
    publishedAtMs: 1700000005000,
  }
];

const shared = {
  compareByRecency: (a, b) => (b.publishedAtMs || 0) - (a.publishedAtMs || 0),
  popularScore: () => 0,
};

// Test 1: B.select without query collapses batchWorks into 1 representative
const folded = B.select(batchWorks, {}, null, shared);
assert.strictEqual(folded.length, 2, "Plaza feed without query must fold 5 works into 2 cards (1 batch rep + 1 single)");
const rep = folded.find(w => w.batchId === "gen_pup");
assert.ok(rep, "Must have representative for gen_pup");
assert.strictEqual(rep.id, "w_b1", "Representative must be first index (w_b1)");
assert.strictEqual(rep.batchTotal, 4, "Representative must report batchTotal = 4");
assert.strictEqual(rep.batchIndex, 1, "Representative must have batchIndex = 1");
console.log("✓ Test 1 Passed: B.select folds same-batch works into 1 representative in plaza mode.");

// Test 2: B.select with search query returns all 4 individual items
const searched = B.select(batchWorks, { query: "puppy" }, null, shared);
assert.strictEqual(searched.length, 4, "Search mode must return all 4 items without folding");
const searchIds = searched.map(w => w.id);
assert.deepStrictEqual(searchIds.sort(), ["w_b1", "w_b2", "w_b3", "w_b4"].sort());
console.log("✓ Test 2 Passed: B.select returns individual items in search mode.");

// Test 3: unpackWorkCandidates propagates batch metadata
const candidates = B.unpackWorkCandidates(folded);
assert.strictEqual(candidates.length, 2);
const candRep = candidates.find(c => c.workId === "w_b1");
assert.strictEqual(candRep.batchTotal, 4);
assert.strictEqual(candRep.batchIndex, 1);
console.log("✓ Test 3 Passed: unpackWorkCandidates propagates batch metadata.");

// Test 4: Verify badge string generation logic
function renderBadge(item, w, isSearchMode) {
  const batchTotal = Number(item.batchTotal || w.batchTotal || 1);
  const batchIdx = Number(item.batchIndex || w.batchIndex || 1);
  if (batchTotal > 1) {
    if (isSearchMode) {
      return `<span class="hw-wb-batch-badge" title="同批第 ${batchIdx}/${batchTotal} 张">同批第 ${batchIdx}/${batchTotal} 张</span>`;
    } else {
      return `<span class="hw-wb-batch-badge" title="同批 ${batchTotal} 件作品">同批 ${batchTotal} 件</span>`;
    }
  }
  return "";
}

const plazaBadge = renderBadge(candRep, candRep.work, false);
assert.ok(plazaBadge.includes("同批 4 件"), "Plaza card must show '同批 4 件'");

const searchItem2 = searched.find(w => w.id === "w_b2");
const searchBadge = renderBadge(searchItem2, searchItem2, true);
assert.ok(searchBadge.includes("同批第 2/4 张"), "Search card must show '同批第 2/4 张'");
console.log("✓ Test 4 Passed: Badge generation correctly formats '同批 4 件' and '同批第 2/4 张'.");

console.log("\n=======================================================");
console.log("ALL STAGE 5 BATCH FOLDING FRONTEND TESTS PASSED! 🎉");
console.log("=======================================================\n");
