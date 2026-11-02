"use strict";
/**
 * Unit tests for Issue #55: Fix thumbnail cropping on "用这个画风做的作品" and related works page.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const forumAppJs = fs.readFileSync(path.join(__dirname, "../demo/assets/forum-app.js"), "utf8");
const forumResourcesJs = fs.readFileSync(path.join(__dirname, "../demo/assets/forum-resources.js"), "utf8");
const forumResourcesCss = fs.readFileSync(path.join(__dirname, "../demo/assets/forum-resources.css"), "utf8");
const interactionCss = fs.readFileSync(path.join(__dirname, "../demo/assets/interaction.css"), "utf8");
const forumResourcesPy = fs.readFileSync(path.join(__dirname, "../backend/forum_resources.py"), "utf8");

test("Issue #55 - Style Detail Related Works: No Fixed Aspect Ratio & No Object-Fit Cover", () => {
  // Locate the related works container rendering in forum-app.js
  const lastIdx = forumAppJs.lastIndexOf("topic-related-works-container");
  const relatedWorksBlock = forumAppJs.slice(
    lastIdx,
    lastIdx + 3000
  );

  assert.ok(relatedWorksBlock.length > 0, "Found related works block in forum-app.js");

  // 1. Container must not enforce fixed 1:1 aspect ratio
  assert.ok(
    !relatedWorksBlock.includes('style="aspect-ratio:1;') && !relatedWorksBlock.includes('style="aspect-ratio: 1;'),
    "Related works container must not force fixed aspect-ratio:1"
  );

  // 2. Container must reserve height using dynamic aspect-ratio
  assert.ok(
    relatedWorksBlock.includes("aspect-ratio:${ar}") || relatedWorksBlock.includes("aspect-ratio: ${ar}"),
    "Related works container must reserve height with dynamic aspect-ratio from feed/ratio"
  );

  // 3. Img must NOT use object-fit: cover
  assert.ok(
    !relatedWorksBlock.includes("object-fit:cover") && !relatedWorksBlock.includes("object-fit: cover"),
    "Related works img must NOT use object-fit: cover"
  );

  // 4. Img must use object-fit: contain
  assert.ok(
    relatedWorksBlock.includes("object-fit:contain") || relatedWorksBlock.includes("object-fit: contain"),
    "Related works img must use object-fit: contain to prevent cropping"
  );

  // 5. Multi-image works must take the first image
  assert.ok(
    relatedWorksBlock.includes("w.images[0]") || relatedWorksBlock.includes("firstImg"),
    "Multi-image works must pick the first image (首图)"
  );
});

test("Issue #55 - View All (forum-resources): No Fixed Ratio on Work Cards & Contain Fit", () => {
  // 1. forum-resources.css must NOT have object-fit: cover on .hrp-card-img
  assert.ok(
    !forumResourcesCss.includes(".hrp-card-img { width: 100%; height: 100%; object-fit: cover;"),
    "forum-resources.css must not use object-fit: cover for .hrp-card-img"
  );
  assert.match(
    forumResourcesCss,
    /\.hrp-card-img\s*\{[^}]*object-fit:\s*contain/,
    "forum-resources.css must specify object-fit: contain for .hrp-card-img"
  );

  // 2. Work cards in forum-resources.css must allow aspect-ratio: auto
  assert.match(
    forumResourcesCss,
    /\.hrp-card\[data-res-kind="work"\]\s+\.hrp-card-media\s*\{[^}]*aspect-ratio:\s*auto/,
    "forum-resources.css must set aspect-ratio: auto for work cards"
  );

  // 3. interaction.css must also allow work card media to not be forced to 1:1
  assert.match(
    interactionCss,
    /hrp-card\[data-res-kind="work"\]/,
    "interaction.css must allow work card media to override fixed aspect-ratio"
  );

  // 4. forum-resources.js renderCard must set dynamic aspect-ratio for work cards
  assert.ok(
    forumResourcesJs.includes("formatCardRatio") || forumResourcesJs.includes("aspectRatio"),
    "forum-resources.js must compute dynamic card ratio"
  );
  assert.ok(
    forumResourcesJs.includes("isWork") && forumResourcesJs.includes("mediaStyle"),
    "forum-resources.js must apply mediaStyle aspect-ratio on work cards"
  );
});

test("Issue #55 - Backend forum_resources.py Enriches Work Dimensions and Aspect Ratio", () => {
  assert.ok(
    forumResourcesPy.includes("enrich_dimensions"),
    "backend/forum_resources.py must import/call enrich_dimensions for work items"
  );
  assert.ok(
    forumResourcesPy.includes("ratio"),
    "backend/forum_resources.py must query work ratio"
  );
});
