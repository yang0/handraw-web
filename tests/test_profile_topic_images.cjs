"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

console.log("Starting Profile Topic Images & Layout Parity Tests (Issue #61)...");

const ROOT = path.resolve(__dirname, "..");
const sharedCode = fs.readFileSync(path.join(ROOT, "demo", "assets", "shared.js"), "utf8");
const forumAppCode = fs.readFileSync(path.join(ROOT, "demo", "assets", "forum-app.js"), "utf8");
const mainAppCode = fs.readFileSync(path.join(ROOT, "demo", "assets", "main-app.js"), "utf8");

// ============================================================================
// Test 1: shared.js defines and exports normalizeTopicImages
// ============================================================================
console.log("\n--- Test 1: shared.js normalizeTopicImages ---");
assert.ok(sharedCode.includes("function normalizeTopicImages(t)"), "shared.js must define normalizeTopicImages");
assert.ok(sharedCode.includes("normalizeTopicImages,"), "shared.js must export normalizeTopicImages");

// Execute shared.js in vm context
function createSharedContext(extraState = {}) {
  const windowMock = {
    location: { href: "http://localhost:3080/", search: "", pathname: "/" },
    addEventListener: () => {},
    removeEventListener: () => {},
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id)
  };
  const documentMock = {
    getElementById: () => null,
    createElement: () => ({ style: {}, appendChild: () => {}, remove: () => {} }),
    body: { appendChild: () => {} }
  };
  const context = {
    window: windowMock,
    document: documentMock,
    console,
    URL,
    URLSearchParams,
    Set,
    Map,
    setTimeout,
    clearTimeout,
    DOMParser: undefined,
    App: {
      channel: "main",
      view: "profile",
      state: {
        serverBacked: false,
        loggedIn: false,
        user: null,
        works: [],
        topics: [],
        ...extraState
      }
    }
  };
  vm.createContext(context);
  vm.runInContext(sharedCode, context);
  if (context.window.HANDRAW_SHARED && context.window.HANDRAW_SHARED.App) {
    context.window.HANDRAW_SHARED.App.state = context.App.state;
  }
  return context;
}

const ctx = createSharedContext({
  works: [
    { id: "work_999", title: "关联作品", images: ["/images/from-work.webp"] }
  ]
});
const S = ctx.window.HANDRAW_SHARED;
assert.ok(S && typeof S.normalizeTopicImages === "function", "HANDRAW_SHARED.normalizeTopicImages must be a function");

// Helper for cross-vm array/object comparison
const cleanJson = (val) => JSON.parse(JSON.stringify(val));

// Verify normalizeTopicImages behavior
assert.deepEqual(cleanJson(S.normalizeTopicImages(null)), []);
assert.deepEqual(cleanJson(S.normalizeTopicImages({})), []);
assert.deepEqual(
  cleanJson(S.normalizeTopicImages({ images: ["/img1.webp", "/img2.webp"] })),
  [{ url: "/img1.webp", tag: "" }, { url: "/img2.webp", tag: "" }]
);
assert.deepEqual(
  cleanJson(S.normalizeTopicImages({ images: [{ url: "/img1.webp", tag: "FA-001" }] })),
  [{ url: "/img1.webp", tag: "FA-001" }]
);
assert.deepEqual(
  cleanJson(S.normalizeTopicImages({ images_json: '["/json-img.webp"]' })),
  [{ url: "/json-img.webp", tag: "" }]
);
assert.deepEqual(
  cleanJson(S.normalizeTopicImages({ images: [], workId: "work_999" })),
  [{ url: "/images/from-work.webp", tag: "" }]
);
console.log("✓ Test 1 Passed: S.normalizeTopicImages handles all formats, JSON, and work fallbacks.");

// ============================================================================
// Test 2: forum-app.js delegates to S.normalizeTopicImages
// ============================================================================
console.log("\n--- Test 2: forum-app.js delegates to S.normalizeTopicImages ---");
assert.ok(
  forumAppCode.includes("if (S.normalizeTopicImages) return S.normalizeTopicImages(t);"),
  "forum-app.js normalizeTopicImages must delegate to S.normalizeTopicImages"
);
console.log("✓ Test 2 Passed: forum-app.js delegation verified.");

// ============================================================================
// Test 3: main-app.js static code check (removal of unnecessary elements)
// ============================================================================
console.log("\n--- Test 3: main-app.js static code verification ---");
// The profile topics block must NOT have the old button
const topicsBlockMatch = mainAppCode.match(/UI\.profileTab === "topics"\) \{([\s\S]*?)\} else if \(UI\.profileTab === "articles"/);
assert.ok(topicsBlockMatch, "Must find UI.profileTab === 'topics' block in main-app.js");
const topicsBlock = topicsBlockMatch[1];

assert.ok(
  !topicsBlock.includes("阅读全文与楼层 ↗"),
  "Redundant '阅读全文与楼层 ↗' button must be removed from profile topics list"
);
assert.ok(
  !topicsBlock.includes("S.getLikeCount(\"topic\", t)"),
  "Redundant '👍 N · 💬 N 回复' row must be removed from profile topics list"
);
assert.ok(
  topicsBlock.includes("forum-card-split"),
  "Profile topics must use .forum-card-split for 1-image topics"
);
assert.ok(
  topicsBlock.includes("forum-split-thumb"),
  "Profile topics must use .forum-split-thumb for 1-image thumbnail"
);
assert.ok(
  topicsBlock.includes("forum-media-strip"),
  "Profile topics must use .forum-media-strip for multi-image topics"
);
assert.ok(
  topicsBlock.includes("forum-media-item"),
  "Profile topics must use .forum-media-item for multi-image thumbnails"
);
assert.ok(
  topicsBlock.includes("forum-format-badge"),
  "Profile topics must use .forum-format-badge"
);
console.log("✓ Test 3 Passed: Redundant elements removed, shared forum CSS classes wired.");

// ============================================================================
// Test 4: Dynamic rendering of profile topic cards (0 / 1 / multi images)
// ============================================================================
console.log("\n--- Test 4: Dynamic DOM rendering for 0 / 1 / multi images ---");

// Simple DOM Mock to execute main-app.js profile view
function renderProfileWithTopics(topics) {
  const elements = new Map();
  function makeEl(tag) {
    const el = {
      tagName: tag.toUpperCase(),
      style: {},
      attributes: {},
      children: [],
      classList: new Set(),
      setAttribute(k, v) { this.attributes[k] = v; },
      getAttribute(k) { return this.attributes[k] || null; },
      hasAttribute(k) { return k in this.attributes; },
      appendChild(c) { this.children.push(c); return c; },
      remove() {},
      querySelectorAll(selector) {
        const results = [];
        function walk(node) {
          if (!node || typeof node !== "object") return;
          if (selector === "[data-prof-topic]" && node.attributes && node.attributes["data-prof-topic"]) {
            results.push(node);
          }
          if (selector === ".forum-topic-card" && node.className && node.className.includes("forum-topic-card")) {
            results.push(node);
          }
          if (selector === ".forum-card-split" && node.className && node.className.includes("forum-card-split")) {
            results.push(node);
          }
          if (selector === ".forum-split-thumb" && node.className && node.className.includes("forum-split-thumb")) {
            results.push(node);
          }
          if (selector === ".forum-media-strip" && node.className && node.className.includes("forum-media-strip")) {
            results.push(node);
          }
          if (selector === ".forum-media-item" && node.className && node.className.includes("forum-media-item")) {
            results.push(node);
          }
          if (selector === "img" && node.tagName === "IMG") {
            results.push(node);
          }
          for (const ch of node.children || []) walk(ch);
        }
        walk(this);
        return results;
      }
    };
    return el;
  }

  // Parse HTML string to simple mock DOM nodes
  // For precise verification, we extract the HTML output of UI.profileTab === "topics"
  const esc = (s) => String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const testProf = {
    username: "artist_yang",
    authorName: "杨凌",
    bio: "测试创作者",
    honor: { name: "知名作者", desc: "在社区发布多篇作品", badgeClass: "honor-gold", sealClass: "seal-master" },
    styles: [],
    layouts: [],
    works: [],
    topics: topics,
    totalPublished: 5,
    totalCheers: 100,
    totalFavorites: 50
  };

  // Run the snippet with testProf
  const runContext = createSharedContext({ topics });
  runContext.prof = testProf;
  runContext.UI = { profileTab: "topics" };
  runContext.esc = esc;
  runContext.isMe = true;

  const codeToRun = `
    const S = window.HANDRAW_SHARED;
    const UI = { profileTab: "topics" };
    let tabBodyHtml = "";
    ${topicsBlock}
    tabBodyHtml;
  `;
  const html = vm.runInContext(codeToRun, runContext);
  return html;
}

// 4a. 0 images (pure text)
const html0 = renderProfileWithTopics([
  {
    id: "t_text_only",
    title: "纯文字帖子探讨手绘风线稿表现力",
    categoryLabel: "技巧教程",
    createdAt: "2 天前",
    images: [],
    summary: "这是纯文本帖子的摘要内容，没有任何配图，排版应该保持为纯文字形式。"
  }
]);

assert.ok(html0.includes('data-prof-topic="t_text_only"'), "0-image post must render data-prof-topic");
assert.ok(html0.includes("纯文字帖子探讨手绘风线稿表现力"), "0-image post must render title");
assert.ok(html0.includes("这是纯文本帖子的摘要内容"), "0-image post must render summary snippet");
assert.ok(!html0.includes("forum-card-split"), "0-image post must NOT render forum-card-split");
assert.ok(!html0.includes("forum-split-thumb"), "0-image post must NOT render forum-split-thumb");
assert.ok(!html0.includes("forum-media-strip"), "0-image post must NOT render forum-media-strip");
assert.ok(!html0.includes("阅读全文与楼层"), "0-image post must NOT render button");
console.log("✓ Test 4a Passed: 0-image topic renders clean text-only card.");

// 4b. 1 image (left text, right thumb)
const html1 = renderProfileWithTopics([
  {
    id: "t_single_img",
    title: "单图实战：松散黑线在海报中的应用",
    categoryLabel: "画风与图型",
    createdAt: "1 天前",
    images: [{ url: "/images/sample1.webp", tag: "FA-001 松散黑线" }],
    summary: "单图帖子的摘要内容，展示右侧单张封面缩略图与标签。"
  }
]);

assert.ok(html1.includes('data-prof-topic="t_single_img"'), "1-image post must render data-prof-topic");
assert.ok(html1.includes("forum-card-split"), "1-image post must render .forum-card-split");
assert.ok(html1.includes("forum-split-thumb"), "1-image post must render .forum-split-thumb");
assert.ok(html1.includes('data-hw-src="/images/sample1.webp"'), "1-image post must render data-hw-src");
assert.ok(html1.includes("FA-001 松散黑线"), "1-image post must render tag in thumbnail");
assert.ok(html1.includes("图文分享"), "1-image post must render 图文分享 badge");
assert.ok(!html1.includes("forum-media-strip"), "1-image post must NOT render forum-media-strip");
console.log("✓ Test 4b Passed: 1-image topic renders forum-card-split with right thumbnail.");

// 4c. 2 images (cols-2 strip)
const html2 = renderProfileWithTopics([
  {
    id: "t_two_img",
    title: "双图对比：水彩与线稿结合前后效果",
    categoryLabel: "经验分享",
    createdAt: "3 小时前",
    images: [
      { url: "/images/imgA.webp", tag: "线稿" },
      { url: "/images/imgB.webp", tag: "上色后" }
    ],
    summary: "双图实测对比。"
  }
]);

assert.ok(html2.includes("forum-media-strip cols-2"), "2-image post must render .forum-media-strip.cols-2");
assert.ok(html2.includes('data-hw-src="/images/imgA.webp"'), "2-image post must render image A");
assert.ok(html2.includes('data-hw-src="/images/imgB.webp"'), "2-image post must render image B");
assert.ok(html2.includes("2 图分享"), "2-image post must render '2 图分享' badge");
console.log("✓ Test 4c Passed: 2-image topic renders forum-media-strip cols-2.");

// 4d. 4 images (cols-4 strip)
const html4 = renderProfileWithTopics([
  {
    id: "t_four_img",
    title: "四格手账插画组图分享",
    categoryLabel: "图文专区",
    createdAt: "昨天",
    images: [
      "/images/1.webp",
      "/images/2.webp",
      "/images/3.webp",
      "/images/4.webp"
    ],
    summary: "四张图片完整平铺于媒体带。"
  }
]);

assert.ok(html4.includes("forum-media-strip cols-4"), "4-image post must render .forum-media-strip.cols-4");
assert.ok(html4.includes('data-hw-src="/images/1.webp"'), "4-image post must render image 1");
assert.ok(html4.includes('data-hw-src="/images/4.webp"'), "4-image post must render image 4");
assert.ok(html4.includes("4 图分享"), "4-image post must render '4 图分享' badge");
assert.ok(!html4.includes("+"), "4-image post must NOT render extra count overlay");
console.log("✓ Test 4d Passed: 4-image topic renders forum-media-strip cols-4 with 4 items.");

// 4e. 6 images (max 4 images + '+2' overlay)
const html6 = renderProfileWithTopics([
  {
    id: "t_six_img",
    title: "多图组图：六节气插画合辑",
    categoryLabel: "合辑推荐",
    createdAt: "5 天前",
    images: [
      "/images/s1.webp",
      "/images/s2.webp",
      "/images/s3.webp",
      "/images/s4.webp",
      "/images/s5.webp",
      "/images/s6.webp"
    ],
    summary: "多图展示，前四张平铺，最后一张显示 +2 遮罩。"
  }
]);

assert.ok(html6.includes("forum-media-strip cols-4"), "6-image post must render .forum-media-strip.cols-4");
assert.ok(html6.includes("+2"), "6-image post must render +2 overlay on fourth item");
assert.ok(html6.includes("6 图分享"), "6-image post must render '6 图分享' badge");
assert.ok(!html6.includes('data-hw-src="/images/s5.webp"'), "5th image must not be directly in strip");
console.log("✓ Test 4e Passed: 6-image topic renders 4 items with +2 overlay.");

// ============================================================================
// Test 5: Click delegation to S.goToTopicPage
// ============================================================================
console.log("\n--- Test 5: Click delegation binding ---");
assert.ok(
  mainAppCode.includes('root.querySelectorAll("[data-prof-topic]").forEach((el) => {'),
  "main-app.js must bind onclick on all [data-prof-topic]"
);
assert.ok(
  mainAppCode.includes("el.onclick = () => S.goToTopicPage(el.getAttribute(\"data-prof-topic\"));"),
  "main-app.js must navigate to S.goToTopicPage on card click"
);
console.log("✓ Test 5 Passed: Click handler properly navigates to topic page.");

console.log("\n============================================================");
console.log("ALL PROFILE TOPIC IMAGES TESTS PASSED SUCCESSFULLY! 🎉");
console.log("============================================================");
