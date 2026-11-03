"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const studioAppSource = fs.readFileSync(path.join(ROOT, "demo", "assets", "studio-app.js"), "utf8");

test("Issue #63: Article Preview Browser History Navigation & Draft Preservation", async (t) => {
  await t.test("1. studio-app.js defines routeArticleEntryFromUrl and popstate listener", () => {
    assert.ok(
      studioAppSource.includes("function routeArticleEntryFromUrl("),
      "studio-app.js must define routeArticleEntryFromUrl"
    );

    assert.ok(
      studioAppSource.includes('window.addEventListener("popstate"'),
      "studio-app.js must register a popstate event listener on window"
    );

    // Verify popstate listener specifically checks for entry === "article"
    const popstateSnippet = studioAppSource.match(
      /window\.addEventListener\("popstate"[\s\S]*?\}\);/
    );
    assert.ok(popstateSnippet, "popstate listener definition found");
    assert.ok(
      popstateSnippet[0].includes('params.get("entry") === "article"') ||
      popstateSnippet[0].includes("entryParam === 'article'"),
      "popstate handler must only process entry === 'article'"
    );
    assert.ok(
      !popstateSnippet[0].includes("pushState"),
      "popstate handler must NOT call pushState"
    );
  });

  await t.test("2. routeArticleEntryFromUrl flushes unsaved draft and routes subviews", () => {
    const routeFnMatch = studioAppSource.match(
      /function routeArticleEntryFromUrl[\s\S]*?^  \}/m
    );
    assert.ok(routeFnMatch, "routeArticleEntryFromUrl function body found");
    const fnBody = routeFnMatch[0];

    // Must call flushUnifiedArticleEditor at top to save dirty draft
    assert.ok(
      fnBody.includes("flushUnifiedArticleEditor()"),
      "routeArticleEntryFromUrl must call flushUnifiedArticleEditor() to save unsaved drafts"
    );

    // Must route preview vs editor
    assert.ok(
      fnBody.includes("renderArticlePreviewPage"),
      "routeArticleEntryFromUrl must route subview === 'preview' to renderArticlePreviewPage"
    );
    assert.ok(
      fnBody.includes("openUnifiedArticleEditor"),
      "routeArticleEntryFromUrl must route to openUnifiedArticleEditor"
    );
    assert.ok(
      !fnBody.includes("pushState"),
      "routeArticleEntryFromUrl must NOT invoke pushState"
    );
  });

  await t.test("3. Initial hydration uses shared routeArticleEntryFromUrl", () => {
    assert.match(
      studioAppSource,
      /entryParam === "article"\) \{\s*routeArticleEntryFromUrl\(params,\s*\{\s*renderNow:\s*false\s*\}\);/,
      "Initial hydrateTabsAndUrlParams must delegate article routing to routeArticleEntryFromUrl with renderNow: false"
    );
  });

  await t.test("4. renderWeChatArticlePreviewHtml & syncArticleEditorDraftToHistory handle title and articleTitle consistently", () => {
    assert.ok(
      studioAppSource.includes("draft.articleTitle || draft.title") ||
      studioAppSource.includes("draft.title || draft.articleTitle"),
      "Preview renderer must check both title and articleTitle"
    );
  });
});
