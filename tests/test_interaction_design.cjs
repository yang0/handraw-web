"use strict";
// Site-wide interaction layer: docs/architecture/interaction-design-20261030.md
// Reads tracked files only.
const assert = require("node:assert/strict");
const fs = require("node:fs");

const read = (p) => fs.readFileSync(p, "utf8");
const css = read("demo/assets/interaction.css");
const ruleBody = (selector) => {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = css.match(new RegExp(`(^|\\n)${esc}\\s*\\{([^}]*)\\}`));
  assert.ok(m, `interaction.css should have a rule for ${selector}`);
  return m[2];
};

// 1. Every entry page loads the layer, versioned, after every other stylesheet.
for (const page of ["index", "forum", "studio", "admin"]) {
  const html = read(`demo/${page}.html`);
  const sheets = [...html.matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map((m) => m[1]);
  assert.match(sheets[sheets.length - 1], /^\/assets\/interaction\.css\?v=\d+$/, `${page}.html must load interaction.css last`);
}

// 2. Card frame: fixed 1:1, contained, so a 768x1024 work cannot make its card
//    taller than the 1024x1024 ones next to it, and nothing is cropped.
assert.match(ruleBody(".hw-discovery__media"), /aspect-ratio:\s*1\s*\/\s*1/);
assert.match(ruleBody(".hw-discovery__media img"), /object-fit:\s*contain/);
assert.match(ruleBody(".hw-discovery__media img"), /height:\s*100%/);
// Zooming a contained picture inside an overflow:hidden frame crops it again.
assert.match(ruleBody(".hw-discovery__card:hover .hw-discovery__media img"), /transform:\s*none/);
// Text block below the frame is fixed too, or rows still drift.
assert.match(ruleBody(".hw-discovery__card .hw-discovery__title"), /white-space:\s*nowrap/);

// 3. Work pictures are never `cover` in this layer; only identity chips may be.
const coverRules = [...css.matchAll(/([^{}]+)\{[^}]*object-fit:\s*cover/g)].map((m) => m[1].trim());
assert.deepEqual(coverRules, [], "interaction.css must not crop work pictures");
for (const sel of [".forum-split-thumb img,\n.forum-media-item img", ".hrp-hero-img", ".hrp-card-img", ".ic-plan-slot-img-box img"]) {
  assert.match(ruleBody(sel), /object-fit:\s*contain/, `${sel} should be contained`);
}

// 4. Preview deep link: the reader page keeps its own sub-view so boot's
//    renderFullPreviewStage() does not draw the editor over it.
const studio = read("demo/assets/studio-app.js");
const previewFn = studio.slice(studio.indexOf("function renderArticlePreviewPage("), studio.indexOf("function renderArticleEditorPage("));
assert.match(previewFn, /CS\.articleSubView = "reader"/);
const stageFn = studio.slice(studio.indexOf("function renderFullPreviewStage("), studio.indexOf("function renderFullPreviewStage(") + 1500);
assert.match(stageFn, /CS\.articleSubView === "reader"[\s\S]*renderArticlePreviewPage\(CS\.activeArticleId\)/);
assert.ok(
  stageFn.indexOf('articleSubView === "reader"') < stageFn.indexOf('CS.articleSubView = "editor"'),
  "the reader check must run before the fall-through to the editor",
);
// The preview's "← 文章列表" used to call a function that does not exist.
assert.doesNotMatch(studio, /renderArticleDirectoryPage\(/);

console.log("test_interaction_design: ok");
