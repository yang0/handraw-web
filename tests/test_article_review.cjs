"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("demo/assets/article-review.js", "utf8");
const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const importer = fs.readFileSync("demo/assets/task-journey.js", "utf8");
const ctx = {window:{}};
vm.runInNewContext(source,ctx);
const review = ctx.window.HandrawArticleReview;
assert.ok(review);
const stats = review.fidelitySummary({
  charDiffRatio:0.061,
  segments:[
    {aiUsed:true,issues:[]},
    {aiUsed:false,issues:["table_cells_changed","image_missing"]},
    {aiUsed:true,issues:["text_length_diff"]}
  ]
});
assert.equal(stats.segments.length,3);
assert.equal(stats.failures,1);
assert.equal(stats.issues,3);
assert.equal(stats.ratio,6.1);
assert.equal(review.fidelitySummary({}).issues,0);
assert.match(source,/data-art-review-check/);
assert.match(source,/review\.cards|cards:approved/);
assert.match(studio,/await window\.HandrawArticleReview\.reviewPlan\(aiCards/);
assert.match(studio,/const approvedCards = review\.cards/);
assert.match(studio,/planUnifiedArticleDraft\(draft, \{ aiCards: approvedCards \}\)/);
assert.match(studio,/推荐理由/);
assert.match(importer,/hw-document-review-single-editor/);
assert.match(importer,/id="hw-doc-review-editor"/);
assert.match(importer,/editor\.value = body/);
assert.match(importer,/result\.markdown = editor\.value/);
assert.doesNotMatch(importer,/hw-document-fidelity-columns/);
assert.doesNotMatch(importer,/最多展示前 7,500 字符/);
assert.match(studio,/baseUpdatedAtMs: _articleCloudBases\.get/);
assert.match(studio,/response\.status === 409/);
assert.match(studio,/ARTICLE_CONFLICT_BACKUP_KEY/);
console.log("article P1: plan review, single editable import and save conflict recovery contracts OK");
