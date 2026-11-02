const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("Issue #43 and #44: Share panel simplification & modal image contain aspect ratio", async (t) => {
  const sharedJsPath = path.join(__dirname, "..", "demo", "assets", "shared.js");
  const themeCssPath = path.join(__dirname, "..", "demo", "assets", "theme.css");

  const sharedJsCode = fs.readFileSync(sharedJsPath, "utf-8");
  const themeCssCode = fs.readFileSync(themeCssPath, "utf-8");

  await t.test("Requirement 1: No inline cover styles in modals or share thumbnail", () => {
    assert.strictEqual(
      sharedJsCode.includes("height:125px;object-fit:cover"),
      false,
      "height:125px;object-fit:cover must be removed from openAssetPickerModal"
    );
    assert.strictEqual(
      sharedJsCode.includes("height:120px;object-fit:cover"),
      false,
      "height:120px;object-fit:cover must be removed from openSharedCardPickerModal"
    );
    assert.strictEqual(
      sharedJsCode.includes("height:96px;object-fit:cover"),
      false,
      "height:96px;object-fit:cover must be removed from renderInlineSharePanelHtml"
    );
    assert.strictEqual(
      sharedJsCode.includes("data-btn-share-card-forum"),
      false,
      "data-btn-share-card-forum must be completely removed"
    );
  });

  await t.test("Requirement 2: theme.css contains scoped 1:1 contain rules and mobile full-width", () => {
    assert.match(
      themeCssCode,
      /\.hw-picker-card-media\s*\{[^}]*aspect-ratio:\s*1\s*\/\s*1/s,
      "theme.css must define .hw-picker-card-media with aspect-ratio: 1 / 1"
    );
    assert.match(
      themeCssCode,
      /\.hw-picker-card-media\s+img\s*\{[^}]*object-fit:\s*contain/s,
      "theme.css must define .hw-picker-card-media img with object-fit: contain"
    );
    assert.match(
      themeCssCode,
      /\.hw-share-thumb-wrap\s*\{[^}]*width:\s*96px[^}]*height:\s*96px/s,
      "theme.css must define .hw-share-thumb-wrap with 96px x 96px"
    );
    assert.match(
      themeCssCode,
      /\.hw-share-thumb-wrap\s+img\s*\{[^}]*object-fit:\s*contain/s,
      "theme.css must define .hw-share-thumb-wrap img with object-fit: contain"
    );
    assert.match(
      themeCssCode,
      /\.hw-btn-copy-share\s*\{[^}]*width:\s*100%/s,
      "theme.css must expand .hw-btn-copy-share to width: 100% on mobile"
    );
  });

  await t.test("Requirement 3: renderInlineSharePanelHtml for work, style, layout, topic", () => {
    // Mock browser environment to execute shared.js
    const mockWindow = {
      location: { href: "http://localhost:3000/" },
      localStorage: {
        getItem: () => null,
        setItem: () => {},
        removeItem: () => {}
      },
      navigator: { clipboard: { writeText: async () => {} } },
      document: {
        createElement: () => ({ style: {}, classList: { add() {}, remove() {} } }),
        head: { appendChild: () => {} },
        body: { appendChild: () => {}, querySelector: () => null },
        querySelector: () => null,
        querySelectorAll: () => []
      }
    };
    mockWindow.window = mockWindow;

    const context = vm.createContext(mockWindow);
    vm.runInContext(sharedJsCode, context);

    const S = mockWindow.HANDRAW_SHARED;
    assert.ok(S, "HANDRAW_SHARED must be initialized");
    assert.strictEqual(typeof S.goToForumCompose, "function", "goToForumCompose pipeline must be preserved");

    // Test style
    const styleHtml = S.renderInlineSharePanelHtml("style", { id: "FA-001", name: "水彩插画" });
    assert.ok(styleHtml.includes("data-btn-copy-share=\"1\""), "Must have copy button");
    assert.ok(styleHtml.includes("📋 复制分享口令"), "Must have unchanged copy button text");
    assert.strictEqual(styleHtml.includes("data-btn-share-card-forum"), false, "Must NOT have share to forum card button");
    assert.ok(styleHtml.includes("hw-share-thumb-wrap"), "Must use hw-share-thumb-wrap thumbnail");
    assert.ok(styleHtml.includes("https://handraw-style.com/?target=FA-001"), "Style URL target must match");

    // Test layout
    const layoutHtml = S.renderInlineSharePanelHtml("layout", { id: "SC-001", name: "居中卡片" });
    assert.ok(layoutHtml.includes("data-btn-copy-share=\"1\""));
    assert.strictEqual(layoutHtml.includes("data-btn-share-card-forum"), false);
    assert.ok(layoutHtml.includes("https://handraw-style.com/?target=SC-001"));

    // Test work
    const workHtml = S.renderInlineSharePanelHtml("work", { id: "work_101", title: "晨光茶会" });
    assert.ok(workHtml.includes("data-btn-copy-share=\"1\""));
    assert.strictEqual(workHtml.includes("data-btn-share-card-forum"), false);
    assert.ok(workHtml.includes("https://handraw-style.com/?target=work_101"));

    // Test topic (must use https://handraw-style.com/t/${code}?ref=${invCode})
    const topicHtml = S.renderInlineSharePanelHtml("topic", { id: "12345", title: "水彩心得" });
    assert.ok(topicHtml.includes("data-btn-copy-share=\"1\""));
    assert.strictEqual(topicHtml.includes("data-btn-share-card-forum"), false);
    assert.ok(topicHtml.includes("https://handraw-style.com/t/12345?ref="), "Topic URL must use /t/ format");
  });
});
