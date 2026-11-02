"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const wbCode = fs.readFileSync(path.join(__dirname, "../demo/assets/works-browser.js"), "utf8");
const ctx = {};
const fn = new Function("window", "module", "exports", wbCode);
const mod = { exports: {} };
fn(ctx, mod, mod.exports);
const B = mod.exports;

test("Author Diversity: 存在不同作者时，视口内不能被单一作者占满", () => {
  // 12 works with 4 authors: A, B, C, D (3 works each)
  const authors = ["authorA", "authorB", "authorC", "authorD"];
  const works = [];
  for (let i = 0; i < 12; i++) {
    works.push({
      id: `w_${i}`,
      author: authors[i % 4],
      images: [`/img_${i}.png`],
      styles: [`FA-00${i + 1}`],
      ratio: "1:1"
    });
  }

  const candidates = B.unpackWorkCandidates(works);
  const V_H = 800;
  const res = B.layoutWorksMasonry(candidates, {
    colCount: 4,
    colWidth: 250,
    viewportHeight: V_H,
    bodyHeight: 100,
    gap: 16
  });

  assert.equal(res.placed.length, 12, "All 12 works placed");

  // Check top viewport (0 to V_H)
  const topCards = res.placed.filter(p => p.top < V_H);
  assert.ok(topCards.length >= 4, "Top viewport should contain at least 4 cards");
  const topAuthors = new Set(topCards.map(p => p.author));
  assert.ok(topAuthors.size > 1, "Top viewport must not be monopolized by a single author");
});

test("Single Author Fallback: 全部候选同作者时页面仍紧凑可用，无整屏空洞", () => {
  // 8 works, ALL by author 'yang0', with different styles
  const works = Array.from({ length: 8 }, (_, i) => ({
    id: `w_yang_${i}`,
    author: "yang0",
    images: [`/yang_${i}.png`],
    styles: [`FA-01${i}`],
    ratio: "1:1"
  }));

  const candidates = B.unpackWorkCandidates(works);
  const V_H = 900;
  const res = B.layoutWorksMasonry(candidates, {
    colCount: 4,
    colWidth: 250,
    viewportHeight: V_H,
    bodyHeight: 100,
    gap: 16
  });

  assert.equal(res.placed.length, 8, "All 8 works must be placed");

  // Since all 8 works have different styles (FA-010 to FA-017) and only one author,
  // there should be NO giant whitespace margin (extraMargin == 0).
  for (const item of res.placed) {
    assert.equal(item.extraMargin, 0, `Work ${item.workId} should not have whitespace separation when only author is repeated`);
  }

  // The first 4 cards should cleanly occupy the 4 columns at top: 0
  const topZeroCards = res.placed.filter(p => p.top === 0);
  assert.equal(topZeroCards.length, 4, "First 4 cards must sit side-by-side at top 0 across the 4 columns");
});

test("Three Dimensions Diversity: 作者、画风、图型均不被单一值占满", () => {
  // Candidates with mixed authors, mixed styles, mixed layouts
  const works = [
    { id: "w1", author: "alice", styles: ["FA-001"], layout: "SC-001", images: ["/1.png"], ratio: "1:1" },
    { id: "w2", author: "alice", styles: ["FA-001"], layout: "SC-001", images: ["/2.png"], ratio: "1:1" },
    { id: "w3", author: "bob", styles: ["FA-002"], layout: "SC-002", images: ["/3.png"], ratio: "1:1" },
    { id: "w4", author: "charlie", styles: ["FA-003"], layout: "SC-003", images: ["/4.png"], ratio: "1:1" },
    { id: "w5", author: "dana", styles: ["FA-004"], layout: "SC-004", images: ["/5.png"], ratio: "1:1" },
  ];

  const candidates = B.unpackWorkCandidates(works);
  const res = B.layoutWorksMasonry(candidates, {
    colCount: 4,
    colWidth: 200,
    viewportHeight: 800,
    bodyHeight: 100,
    gap: 10
  });

  assert.equal(res.placed.length, 5);

  // w1 (alice, FA-001, SC-001) should NOT be immediately co-located with w2 (same author/style/layout)
  // Instead, w3 (bob), w4 (charlie), w5 (dana) should fill the other columns at top 0!
  const firstFour = res.placed.slice(0, 4);
  const authorsInFirstFour = new Set(firstFour.map(p => p.author));
  assert.ok(authorsInFirstFour.size >= 3, "First four cards should have diverse authors");

  const pW2 = res.placed.find(p => p.workId === "w2");
  assert.ok(pW2.top > 0, "w2 must not be at top 0 next to w1");
});
