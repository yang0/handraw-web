const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const themeCss = fs.readFileSync(path.join(ROOT, "demo", "assets", "theme.css"), "utf8");
const studioApp = fs.readFileSync(path.join(ROOT, "demo", "assets", "studio-app.js"), "utf8");
const forumApp = fs.readFileSync(path.join(ROOT, "demo", "assets", "forum-app.js"), "utf8");

test("Issue #44: Semantic Image Sizing and Contain Utilities", async (t) => {
  await t.test("1. Card selection preview uses 1:1 container with object-fit: contain", () => {
    assert.match(
      themeCss,
      /\.hw-picker-card-media\s*\{[^}]*aspect-ratio:\s*1\s*\/\s*1/,
      ".hw-picker-card-media must have aspect-ratio: 1 / 1"
    );
    assert.match(
      themeCss,
      /\.hw-picker-card-media\s+img\s*\{[^}]*object-fit:\s*contain/,
      ".hw-picker-card-media img must have object-fit: contain"
    );
    // Batch gallery in studio-app.js
    const bgalMatch = studioApp.match(/data-bgal-idx[\s\S]*?<\/div>\s*<\/div>/);
    assert.ok(bgalMatch, "data-bgal-idx card template must exist");
    assert.ok(bgalMatch[0].includes("hw-picker-card-media"), "data-bgal-idx must use hw-picker-card-media");
    assert.ok(!bgalMatch[0].includes("object-fit:cover") && !bgalMatch[0].includes("object-fit: cover"), "data-bgal-idx must not use object-fit: cover");
  });

  await t.test("2. Rich editor body images adapt to native ratio without cropping", () => {
    assert.match(
      themeCss,
      /\.hw-editor-body-img[^{]*\{[^}]*width:\s*auto/,
      ".hw-editor-body-img must have width: auto"
    );
    assert.match(
      themeCss,
      /\.hw-editor-body-img[^{]*\{[^}]*max-width:\s*100%/,
      ".hw-editor-body-img must have max-width: 100%"
    );
    assert.match(
      themeCss,
      /\.hw-editor-body-img[^{]*\{[^}]*height:\s*auto/,
      ".hw-editor-body-img must have height: auto"
    );
    assert.match(
      themeCss,
      /\.hw-intext-media-wrap\s+img\s*\{[^}]*height:\s*auto/,
      ".hw-intext-media-wrap img must have height: auto"
    );
    assert.ok(!themeCss.includes("max-height: 520px"), ".hw-intext-media-wrap img must not constrain max-height to 520px");
    assert.ok(forumApp.includes("hw-editor-body-img"), "forum-app.js must use hw-editor-body-img in buildIntextMediaHtml");
    assert.ok(studioApp.includes("hw-editor-body-img"), "studio-app.js must use hw-editor-body-img in renderPreviewFigureHtml");
  });

  await t.test("3. Modal large image preview restricts max-height, uses contain, and scrolls", () => {
    assert.match(
      themeCss,
      /\.hw-modal-lightbox-container\s*\{[^}]*overflow-y:\s*auto/,
      ".hw-modal-lightbox-container must have overflow-y: auto"
    );
    assert.match(
      themeCss,
      /\.hw-modal-lightbox-img\s*\{[^}]*object-fit:\s*contain/,
      ".hw-modal-lightbox-img must have object-fit: contain"
    );
    assert.ok(studioApp.includes("hw-modal-lightbox-img"), "studio-app.js openImageLightbox must use hw-modal-lightbox-img");
    assert.ok(forumApp.includes("hw-modal-lightbox-img"), "forum-app.js openImageLightboxModal must use hw-modal-lightbox-img");
    assert.ok(studioApp.includes("查看原图"), "studio-app.js lightbox must retain view original link");
    assert.ok(forumApp.includes("查看原图"), "forum-app.js lightbox must retain view original link");
  });
});
