/**
 * V3 gallery contract (#84): a generation run has a single work card,
 * even when its work.images contains several media items.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const B = require("../demo/assets/works-browser.js");

const shared = {
  compareByRecency: (a, b) => (b.publishedAtMs || 0) - (a.publishedAtMs || 0),
  popularScore: () => 0,
};
const generated = {
  id: "run_work_1", title: "Puppy illustrations", author: "alice",
  batchId: "run_1", images: ["/img/p1.webp", "/img/p2.webp", "/img/p3.webp",
                            "/img/p4.webp", "/img/p5.webp"],
  publishedAtMs: 1700000004000,
};
const single = {
  id: "run_work_2", title: "Mountain", author: "bob",
  images: ["/img/m1.webp"], publishedAtMs: 1700000005000,
};

for (const filters of [{}, {query:"puppy"}, {format:"multi"}]) {
  const selected = B.select([generated, single], filters, null, shared);
  assert.equal(selected.filter(w => w.id === generated.id).length, 1,
    "One generation run must be one selected work even during searching");
  const candidates = B.unpackWorkCandidates(selected);
  assert.equal(candidates.filter(c => c.workId === generated.id).length, 1,
    "Masonry must not explode work.images into separate cards");
  const cover = candidates.find(c => c.workId === generated.id);
  assert.equal(cover.imageUrl, "/img/p1.webp", "First image is default cover");
  assert.equal(cover.totalImages, 5, "Card retains its real image count");
  assert.equal(cover.imgIndex, 0);
}

assert.equal(B.unpackWorkCandidates([single]).length, 1);
const source = fs.readFileSync("demo/assets/main-app.js", "utf8");
assert.match(source, /共 \$\{totalImgs\} 张图片/);
assert.match(source, /const href = channelUrl\("main", \{ view: "work", id \}\)/,
  "Gallery must open the entire work detail, not a forum topic");
assert.doesNotMatch(source, /hw-profile-batch-strip" aria-hidden="true"/,
  "Profile must show only the cover, not a multi-image strip");
console.log("V3 cover-only gallery, multi-image counts and detail navigation passed");
