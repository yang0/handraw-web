// Works sharing a style must never share a viewport.
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

const works = Array.from({ length: 8 }, (_, i) => ({
  id: "w" + i,
  title: "作品" + i,
  images: ["/starter/bear-and-bird.webp"],
  styles: ["FA-001"],
  layout: "SC-001",
  aspectRatio: 1,
}));

const candidates = WB.unpackWorkCandidates(works);
const out = WB.layoutWorksMasonry(candidates, { colCount: 4, colWidth: 280, viewportHeight: 900 });
const placed = out.placed || [];

assert.strictEqual(placed.length, 8, "every work is eventually placed, none is dropped");

// Two works sharing a code must be at least one viewport apart.
for (let i = 0; i < placed.length; i++) {
  for (let j = i + 1; j < placed.length; j++) {
    const gap = Math.abs(placed[i].top - placed[j].top);
    assert.ok(gap >= 900, `works ${i} and ${j} are ${gap}px apart, less than one viewport`);
  }
}

// A work with no styles takes part in no avoidance and may fill a gap.
const free = WB.unpackWorkCandidates([{ id: "free", title: "自由", images: ["/x.webp"], styles: [], layout: "" }]);
assert.strictEqual(free[0].resourceCodes.size, 0, "a work with no codes carries no codes");

console.log("masonry conflict tests passed");
