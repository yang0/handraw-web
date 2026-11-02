"use strict";
/**
 * Unit tests for Issue #58: Remove "文章配图" tab from studio mode bar and relocate to "更多 ▾" menu.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const studioAppJs = fs.readFileSync(path.join(__dirname, "../demo/assets/studio-app.js"), "utf8");
const quickCreateCss = fs.readFileSync(path.join(__dirname, "../demo/assets/quick-create.css"), "utf8");

test("Issue #58 - Studio Mode Bar: No direct '文章配图' button outside '更多 ▾'", () => {
  const modeBarFn = studioAppJs.slice(
    studioAppJs.indexOf("function renderCreationModeBar("),
    studioAppJs.indexOf("function renderQuickStart(")
  );

  assert.ok(modeBarFn.length > 0, "Found renderCreationModeBar function");

  // Extract the HTML template assigned to DOM.entryBar.innerHTML
  const innerHtmlMatch = modeBarFn.match(/DOM\.entryBar\.innerHTML\s*=\s*`([^`]+)`/);
  assert.ok(innerHtmlMatch, "Found DOM.entryBar.innerHTML template");
  const tpl = innerHtmlMatch[1];

  // 1. Direct children of qc-mode-switch before qc-mode-more
  const beforeMore = tpl.slice(0, tpl.indexOf('id="studio-mode-more-wrap"'));
  assert.ok(
    !beforeMore.includes('id="studio-mode-article"'),
    "Direct mode bar must NOT contain #studio-mode-article button"
  );
  assert.ok(
    beforeMore.includes('id="studio-mode-quick"') && beforeMore.includes('id="studio-mode-batch"'),
    "Direct mode bar must still contain 做图 and 批量 buttons"
  );

  // 2. #studio-mode-article must be located inside #studio-mode-more-menu
  const menuPart = tpl.slice(tpl.indexOf('id="studio-mode-more-menu"'));
  assert.ok(
    menuPart.includes('id="studio-mode-article"') && menuPart.includes("文章配图"),
    "More menu must contain '文章配图' item"
  );
  assert.ok(
    menuPart.includes('id="studio-mode-canvas"') && menuPart.includes("高级画布"),
    "More menu must contain '高级画布' item"
  );

  // 3. More button highlights when in canvas OR article mode
  assert.match(
    modeBarFn,
    /moreActive\s*=\s*canvas\s*\|\|\s*article/,
    "More button active state must include both canvas and article modes"
  );

  // 4. Click handler for #studio-mode-article must invoke switchCreationStage('article')
  assert.match(
    modeBarFn,
    /btnArticle\.onclick\s*=\s*\(\)\s*=>\s*\{[^}]*switchCreationStage\("article"\)/,
    "Clicking article button must invoke switchCreationStage('article')"
  );
});

test("Issue #58 - URL Entry Parameter ?entry=article preserved", () => {
  assert.match(
    studioAppJs,
    /entryParam === "article"/,
    "Initial URL parsing must continue handling ?entry=article"
  );
  assert.match(
    studioAppJs,
    /url\.searchParams\.set\("entry",\s*next === "quick" \? "quick" : next === "batch" \? "batch" : next === "article" \? "article" : "canvas"\)/,
    "switchCreationStage must synchronize ?entry=article in URL"
  );
});

test("Issue #58 - Stylesheet supports .qc-more-menu-item.is-active", () => {
  assert.match(
    quickCreateCss,
    /\.qc-more-menu-item\.is-active/,
    "quick-create.css must have active style for more-menu items"
  );
});
