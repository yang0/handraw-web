// Works sharing a style must never share a viewport when sufficient works exist.
// When quantity is insufficient, all works are placed without pushdown.
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const src = fs.readFileSync(path.join(__dirname, "..", "demo", "assets", "works-browser.js"), "utf8");
const sandbox = { window: {}, document: { createElement: () => ({ style: {}, appendChild() {} }) }, console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const WB = sandbox.window.HandrawWorksBrowser;

assert.ok(WB && typeof WB.layoutWorksMasonry === "function", "layout engine must be exported");

// 1. When sufficient works exist, works sharing a style are kept at least one viewport apart.
const diverseWorks = [
  { id: "w0", title: "作品0", images: ["/starter/bear-and-bird.webp"], styles: ["FA-001"], layout: "SC-001", aspectRatio: 1 },
  ...Array.from({ length: 16 }, (_, i) => ({
    id: "other" + i,
    title: "其他" + i,
    images: ["/starter/bear-and-bird.webp"],
    styles: ["DIFF-" + i],
    layout: "DIFF-" + i,
    aspectRatio: 1,
  })),
  { id: "w1", title: "作品1", images: ["/starter/bear-and-bird.webp"], styles: ["FA-001"], layout: "SC-001", aspectRatio: 1 },
];

const outDiverse = WB.layoutWorksMasonry(WB.unpackWorkCandidates(diverseWorks), { colCount: 4, colWidth: 280, viewportHeight: 900 });
const p0 = outDiverse.placed.find(p => (p.work && p.work.id === "w0") || p.id === "w0");
const p1 = outDiverse.placed.find(p => (p.work && p.work.id === "w1") || p.id === "w1");
assert.ok(p0 && p1, "both works must be placed");
assert.ok(Math.abs(p0.top - p1.top) >= 900, "two works sharing FA-001 must be at least one viewport apart when sufficient works exist");

// 2. When quantity is insufficient, all works are placed without pushdown.
const sameWorks = Array.from({ length: 8 }, (_, i) => ({
  id: "same" + i,
  title: "同款" + i,
  images: ["/starter/bear-and-bird.webp"],
  styles: ["FA-001"],
  layout: "SC-001",
  aspectRatio: 1,
}));

const outSame = WB.layoutWorksMasonry(WB.unpackWorkCandidates(sameWorks), { colCount: 4, colWidth: 280, viewportHeight: 900 });
assert.strictEqual(outSame.placed.length, 8, "every work is eventually placed, none is dropped");
assert.strictEqual(outSame.remainingQueue.length, 0, "queue is empty");
for (const p of outSame.placed) {
  assert.strictEqual(p.extraMargin, 0, "no pushdown extraMargin when quantity is insufficient");
}

// 3. A work with no styles takes part in no avoidance and may fill a gap.
const free = WB.unpackWorkCandidates([{ id: "free", title: "自由", images: ["/x.webp"], styles: [], layout: "" }]);
assert.strictEqual(free[0].resourceCodes.size, 0, "a work with no codes carries no codes");

console.log("masonry conflict tests passed");
