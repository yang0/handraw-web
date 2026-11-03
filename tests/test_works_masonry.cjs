"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const wbCode = fs.readFileSync(path.join(__dirname, "../demo/assets/works-browser.js"), "utf8");
// Evaluate in node context
const ctx = {};
const fn = new Function("window", "module", "exports", wbCode);
const mod = { exports: {} };
fn(ctx, mod, mod.exports);
const B = mod.exports;

test("Requirement 1: 按最短列插入 (Greedy Shortest Column Insertion)", () => {
  // Create 4 works with distinct styles so no diversity conflicts interfere
  const works = [
    { id: "w1", images: ["/1.png"], styles: ["FA-001"], ratio: "1:1" }, // ar = 1.0, short card
    { id: "w2", images: ["/2.png"], styles: ["FA-002"], ratio: "9:16" }, // ar = 0.5625, very tall card
    { id: "w3", images: ["/3.png"], styles: ["FA-003"], ratio: "1:1" }, // ar = 1.0, short card
    { id: "w4", images: ["/4.png"], styles: ["FA-004"], ratio: "1:1" }, // ar = 1.0, short card
    { id: "w5", images: ["/5.png"], styles: ["FA-005"], ratio: "1:1" }, // 5th card should go into shortest column!
  ];

  const candidates = B.unpackWorkCandidates(works);
  // 2 columns
  const res = B.layoutWorksMasonry(candidates, {
    colCount: 2,
    colWidth: 200,
    viewportHeight: 1000,
    bodyHeight: 100,
    gap: 10
  });

  assert.equal(res.placed.length, 5);
  // In colCount=2:
  // Card 1 (ar=1.0, height=200/1.0+100=300) -> placed in col 0. colHeights[0] = 310
  // Card 2 (ar=0.5625, height=200/0.5625+100=456) -> placed in col 1. colHeights[1] = 466
  // Card 3 (ar=1.0, height=300) -> col 0 is shortest (310 < 466), placed in col 0! colHeights[0] = 310+300+10 = 620
  // Card 4 (ar=1.0, height=300) -> col 1 is shortest (466 < 620), placed in col 1! colHeights[1] = 466+300+10 = 776
  // Card 5 (ar=1.0, height=300) -> col 0 is shortest (620 < 776), placed in col 0!
  assert.equal(res.placed[0].col, 0);
  assert.equal(res.placed[1].col, 1);
  assert.equal(res.placed[2].col, 0);
  assert.equal(res.placed[3].col, 1);
  assert.equal(res.placed[4].col, 0, "Card 5 must be placed in col 0 because colHeights[0] (620) < colHeights[1] (776)");
});

test("Requirement 2: 视口内画风/图型无交集 (Diversity in Viewport)", () => {
  // Works with styles and layouts:
  // w1 has FA-001 and SC-001
  // w2 has FA-001 (same style as w1!)
  // w3 has SC-001 (same layout as w1!)
  // w4 has FA-002 (different)
  // w5 has FA-003 (different)
  const works = [
    { id: "w1", images: ["/1.png"], styles: ["FA-001"], layout: "SC-001", ratio: "1:1" },
    { id: "w4", images: ["/4.png"], styles: ["FA-002"], ratio: "1:1" },
    { id: "w5", images: ["/5.png"], styles: ["FA-003"], ratio: "1:1" },
    { id: "w6", images: ["/6.png"], styles: ["FA-004"], ratio: "1:1" },
    { id: "w7", images: ["/7.png"], styles: ["FA-005"], ratio: "1:1" },
    { id: "w8", images: ["/8.png"], styles: ["FA-006"], ratio: "1:1" },
    { id: "w2", images: ["/2.png"], styles: ["FA-001"], ratio: "1:1" }, // conflicts with w1 on FA-001
    { id: "w3", images: ["/3.png"], layout: "SC-001", ratio: "1:1" },   // conflicts with w1 on SC-001
  ];

  const candidates = B.unpackWorkCandidates(works);
  const V_H = 600;
  const res = B.layoutWorksMasonry(candidates, {
    colCount: 2,
    colWidth: 200,
    viewportHeight: V_H,
    bodyHeight: 100,
    gap: 10
  });

  assert.equal(res.placed.length, 8);

  // Check that for ANY two placed items A and B that share style or layout,
  // they NEVER overlap in any viewport of height V_H!
  for (let i = 0; i < res.placed.length; i++) {
    for (let j = i + 1; j < res.placed.length; j++) {
      const A = res.placed[i];
      const Bitem = res.placed[j];
      if (B.hasResourceConflict(A.resourceCodes, Bitem.resourceCodes)) {
        const topA = A.top, bottomA = A.top + A.height;
        const topB = Bitem.top, bottomB = Bitem.top + Bitem.height;
        // Two intervals [topA, bottomA] and [topB, bottomB] are co-visible in a viewport of V_H
        // if and only if topB < bottomA + V_H AND topA < bottomB + V_H.
        const coVisible = (topB < bottomA + V_H) && (topA < bottomB + V_H);
        assert.equal(
          coVisible,
          false,
          `Items ${A.workId} and ${Bitem.workId} share resources (${Array.from(A.resourceCodes)}) but are co-visible in viewport of height ${V_H}: A=[${topA}, ${bottomA}], B=[${topB}, ${bottomB}]`
        );
      }
    }
  }
});

test("Requirement 3: 融合作品占全部编号 (Dual-Style Fusion Occupies All Codes)", () => {
  // Fusion work w_fusion has both FA-001 and FA-002
  // w_single1 has FA-001
  // w_single2 has FA-002
  // w_single3 has FA-003
  const works = [
    { id: "w_fusion", images: ["/f.png"], styles: ["FA-001", "FA-002"], ratio: "1:1" },
    { id: "w_single1", images: ["/s1.png"], styles: ["FA-001"], ratio: "1:1" },
    { id: "w_single2", images: ["/s2.png"], styles: ["FA-002"], ratio: "1:1" },
    { id: "w_single3", images: ["/s3.png"], styles: ["FA-003"], ratio: "1:1" },
    { id: "w_other1", images: ["/o1.png"], styles: ["FA-004"], ratio: "1:1" },
    { id: "w_other2", images: ["/o2.png"], styles: ["FA-005"], ratio: "1:1" },
    { id: "w_other3", images: ["/o3.png"], styles: ["FA-006"], ratio: "1:1" },
    { id: "w_other4", images: ["/o4.png"], styles: ["FA-007"], ratio: "1:1" },
    { id: "w_other5", images: ["/o5.png"], styles: ["FA-008"], ratio: "1:1" },
    { id: "w_other6", images: ["/o6.png"], styles: ["FA-009"], ratio: "1:1" },
  ];

  const fusionRes = B.normalizeResourceCodes(works[0]);
  assert.ok(fusionRes.has("FA-001"));
  assert.ok(fusionRes.has("FA-002"));
  assert.equal(fusionRes.size, 2);

  assert.ok(B.hasResourceConflict(fusionRes, B.normalizeResourceCodes(works[1])), "Fusion must conflict with FA-001");
  assert.ok(B.hasResourceConflict(fusionRes, B.normalizeResourceCodes(works[2])), "Fusion must conflict with FA-002");
  assert.equal(B.hasResourceConflict(fusionRes, B.normalizeResourceCodes(works[3])), false, "Fusion does not conflict with FA-003");

  const candidates = B.unpackWorkCandidates(works);
  const V_H = 700;
  const res = B.layoutWorksMasonry(candidates, {
    colCount: 2,
    colWidth: 200,
    viewportHeight: V_H,
    bodyHeight: 100,
    gap: 10
  });

  const pFusion = res.placed.find(p => p.workId === "w_fusion");
  const pSingle1 = res.placed.find(p => p.workId === "w_single1");
  const pSingle2 = res.placed.find(p => p.workId === "w_single2");

  // Single1 and Single2 must NOT be in the same viewport as Fusion!
  const coVis1 = (pSingle1.top < pFusion.top + pFusion.height + V_H) && (pFusion.top < pSingle1.top + pSingle1.height + V_H);
  const coVis2 = (pSingle2.top < pFusion.top + pFusion.height + V_H) && (pFusion.top < pSingle2.top + pSingle2.height + V_H);
  assert.equal(coVis1, false, "w_single1 must not be co-visible with w_fusion");
  assert.equal(coVis2, false, "w_single2 must not be co-visible with w_fusion");
});

test("Requirement 4: 无画风/无图型作品不参与避让，可填空 (Freeform Works Fill Gaps)", () => {
  // Suppose w1 has FA-001, w2 has FA-001 (conflict!)
  // w_freeform has no styles and no layout!
  const works = [
    { id: "w1", images: ["/1.png"], styles: ["FA-001"], ratio: "1:1" },
    { id: "w2", images: ["/2.png"], styles: ["FA-001"], ratio: "1:1" },
    { id: "w_freeform", images: ["/free.png"], styles: [], layout: "", ratio: "1:1" },
  ];

  const candidates = B.unpackWorkCandidates(works);
  const V_H = 800;
  const res = B.layoutWorksMasonry(candidates, {
    colCount: 2,
    colWidth: 200,
    viewportHeight: V_H,
    bodyHeight: 100,
    gap: 10
  });

  // w1 is placed in col 0 at top 0.
  // Next in queue was w2 (FA-001), but it conflicts with w1 at top 0!
  // w_freeform is next in queue: it has NO styles, so it CAN be placed at top 0 in col 1!
  const pFree = res.placed.find(p => p.workId === "w_freeform");
  assert.ok(pFree, "w_freeform must be placed");
  assert.equal(pFree.col, 1, "w_freeform fills the other column at top 0");
  assert.equal(pFree.top, 0, "w_freeform top is 0");
});

test("Requirement 5: 候选不足时不留白，全部卡片都被放置且 extraMargin 为 0", () => {
  // Suppose all 3 works have FA-001! No other styles exist!
  const works = [
    { id: "w1", images: ["/1.png"], styles: ["FA-001"], ratio: "1:1" },
    { id: "w2", images: ["/2.png"], styles: ["FA-001"], ratio: "1:1" },
    { id: "w3", images: ["/3.png"], styles: ["FA-001"], ratio: "1:1" },
  ];

  const candidates = B.unpackWorkCandidates(works);
  const V_H = 600;
  const res = B.layoutWorksMasonry(candidates, {
    colCount: 2,
    colWidth: 200,
    viewportHeight: V_H,
    bodyHeight: 100,
    gap: 10
  });

  // All 3 works MUST be placed (never dropped!)
  assert.equal(res.placed.length, 3, "All works must be placed, none permanently dropped");
  assert.equal(res.remainingQueue.length, 0, "Queue must be empty");

  for (const item of res.placed) {
    assert.equal(item.extraMargin, 0, "extraMargin must be strictly 0");
  }

  assert.equal(res.placed[0].col, 0);
  assert.equal(res.placed[0].top, 0);
  assert.equal(res.placed[1].col, 1);
  assert.equal(res.placed[1].top, 0);
  assert.equal(res.placed[2].col, 0);
  assert.equal(res.placed[2].top, 310);
});

test("Requirement 7: 10 件全部共用同一图型时，全部放置、无下推", () => {
  const works = Array.from({ length: 10 }, (_, i) => ({
    id: `work_${i + 1}`,
    images: [`/${i + 1}.png`],
    layout: "SC-021",
    ratio: "1:1"
  }));

  const candidates = B.unpackWorkCandidates(works);
  const V_H = 800;
  const res = B.layoutWorksMasonry(candidates, {
    colCount: 4,
    colWidth: 250,
    viewportHeight: V_H,
    bodyHeight: 100,
    gap: 16
  });

  assert.equal(res.placed.length, 10, "All 10 works must be placed");
  assert.equal(res.remainingQueue.length, 0, "Remaining queue must be empty");

  for (const item of res.placed) {
    assert.equal(item.extraMargin, 0, "extraMargin must be strictly 0");
  }

  // 4 columns, card height = 250/1.0 + 100 = 350. Next row at 350 + 16 = 366.
  for (let i = 0; i < 4; i++) {
    assert.equal(res.placed[i].top, 0, `Card ${i + 1} must be at top 0`);
  }
  for (let i = 4; i < 8; i++) {
    assert.equal(res.placed[i].top, 366, `Card ${i + 1} must be at top 366`);
  }
  for (let i = 8; i < 10; i++) {
    assert.equal(res.placed[i].top, 732, `Card ${i + 1} must be at top 732`);
  }
});

test("Requirement 6: 窗口变化重排 (Window Resize Redistribution)", () => {
  // Test rearranging from 4 columns to 2 columns
  const works = Array.from({ length: 8 }, (_, i) => ({
    id: `w_${i}`,
    images: [`/${i}.png`],
    styles: [`FA-00${i + 1}`],
    ratio: "1:1"
  }));

  const candidates = B.unpackWorkCandidates(works);

  // 4 columns (desktop)
  const res4 = B.layoutWorksMasonry(candidates, {
    colCount: 4,
    colWidth: 250,
    viewportHeight: 800,
    bodyHeight: 100,
    gap: 16
  });
  assert.equal(res4.placed.length, 8);
  const cols4 = new Set(res4.placed.map(p => p.col));
  assert.equal(cols4.size, 4, "Should use all 4 columns");

  // 2 columns (mobile)
  const res2 = B.layoutWorksMasonry(candidates, {
    colCount: 2,
    colWidth: 180,
    viewportHeight: 800,
    bodyHeight: 100,
    gap: 10
  });
  assert.equal(res2.placed.length, 8);
  const cols2 = new Set(res2.placed.map(p => p.col));
  assert.equal(cols2.size, 2, "Should use all 2 columns");
  for (const item of res2.placed) {
    assert.ok(item.col < 2, "Columns must be strictly < 2");
  }
});
