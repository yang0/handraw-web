/**
 * Stage 4 Verification Test: Unified Work-Topic Detail Page (Issue #60).
 */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const forumWorkPostSrc = fs.readFileSync(path.resolve(__dirname, "../demo/assets/forum-work-post.js"), "utf8");
const sharedSrc = fs.readFileSync(path.resolve(__dirname, "../demo/assets/shared.js"), "utf8");

// Mock browser environment
function createMockEnv() {
  const window = {
    location: { href: "http://localhost:3080/", search: "", hostname: "localhost", pathname: "/" },
    navigator: { clipboard: { writeText: async () => {} } },
    addEventListener: () => {},
  };
  global.window = window;
  global.document = {
    createElement: (tag) => ({
      tagName: tag.toUpperCase(),
      setAttribute: () => {},
      getAttribute: () => null,
      classList: { add: () => {}, remove: () => {}, toggle: () => {} },
      appendChild: () => {},
    }),
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  global.navigator = window.navigator;

  // Evaluate shared.js
  const sharedFn = new Function("window", sharedSrc);
  sharedFn(window);
  const S = window.HANDRAW_SHARED;

  // Evaluate forum-work-post.js
  const fwpFn = new Function("window", forumWorkPostSrc);
  fwpFn(window);
  const FWP = window.HandrawForumWork;

  return { window, S, FWP };
}

console.log("Starting test_stage4_unified_work_topic_detail.cjs...");

// Test 1: S.goToWorkPage redirects to topic page using discussion mapping or /t/ fallback
{
  const { window, S } = createMockEnv();
  S.App.channel = "main";
  S.App.state = {
    discussions: {
      w_mapped: { topicId: "topic_mapped_123", count: 0 },
    },
  };

  // 1a: Mapped work redirects directly to forum topic URL
  S.goToWorkPage("w_mapped");
  assert.equal(
    window.location.href,
    "/forum/?view=topic&id=topic_mapped_123",
    "Mapped work must redirect to /forum/?view=topic&id=topic_mapped_123"
  );

  // 1b: Unmapped work redirects to /t/ fallback
  S.goToWorkPage("w_unmapped", true);
  assert.equal(
    window.location.href,
    "/t/work-w_unmapped?focus=comment",
    "Unmapped work must redirect to /t/work-w_unmapped?focus=comment"
  );
  console.log("✓ Test 1 Passed: S.goToWorkPage redirects to topic URL or /t/ fallback.");
}

// Test 2: FWP fromTopic with batchWorks (4 images from same batch)
{
  const { window, FWP } = createMockEnv();

  const mockTopic = {
    id: "topic_batch_1",
    title: "海滨黄昏风景 (1/4)",
    author: "alice",
    authorName: "Alice",
    workId: "w_batch_1",
    likes: 12,
    favorites: 5,
    summary: "第一张图的主题测试",
  };

  const mockWork = {
    id: "w_batch_1",
    title: "海滨黄昏风景 (1/4)",
    author: "alice",
    prompt: "sunset beach oil painting 4k",
    images: ["/img/batch_1.webp"],
    likes: 12,
    favorites: 5,
    forks: 3,
    batchWorks: [
      { workId: "w_batch_1", topicId: "topic_batch_1", imageUrl: "/img/batch_1.webp", index: 1, total: 4, isCurrent: true },
      { workId: "w_batch_2", topicId: "topic_batch_2", imageUrl: "/img/batch_2.webp", index: 2, total: 4, isCurrent: false },
      { workId: "w_batch_3", topicId: "topic_batch_3", imageUrl: "/img/batch_3.webp", index: 3, total: 4, isCurrent: false },
      { workId: "w_batch_4", topicId: "topic_batch_4", imageUrl: "/img/batch_4.webp", index: 4, total: 4, isCurrent: false },
    ],
  };

  const model = FWP.fromTopic(mockTopic, [mockWork], null, true);
  assert.ok(model, "Model must be generated from topic & work");
  assert.equal(model.batchWorks.length, 4, "Must retain 4 batch sibling works");
  assert.equal(model.prompt, "sunset beach oil painting 4k", "Prompt must be present");
  assert.ok(model.canFork, "Must be reproducible with fork");

  const html = FWP.render(model);
  // Verify gallery renders download button
  assert.ok(html.includes("fwp-download-btn"), "Gallery must include download button");
  assert.ok(html.includes('download="handraw-work.webp"'), "Download button must specify download attribute");
  assert.ok(html.includes("/img/batch_1.webp"), "Must render main image URL");

  // Verify batch thumbnails render with topic IDs and badges
  assert.ok(html.includes('data-fwp-topic="topic_batch_2"'), "Sibling thumbnail must have topic ID attribute");
  assert.ok(html.includes('data-fwp-topic="topic_batch_3"'), "Sibling thumbnail must have topic ID attribute");
  assert.ok(html.includes('data-fwp-topic="topic_batch_4"'), "Sibling thumbnail must have topic ID attribute");
  assert.ok(html.includes("1/4") && html.includes("4/4"), "Thumbnails must display index badges (1/4..4/4)");

  // Verify '做同款' and prompt
  assert.ok(html.includes("做同款"), "Must render '做同款' action");
  assert.ok(html.includes("sunset beach oil painting 4k"), "Must render prompt text");
  console.log("✓ Test 2 Passed: FWP renders batchWorks gallery with 4 siblings, download button, and '做同款'.");
}

// Test 3: Sibling thumbnail click delegates to HANDRAW_FORUM_OPEN_TOPIC
{
  const { window, FWP } = createMockEnv();

  let openedTopicId = null;
  window.HANDRAW_FORUM_OPEN_TOPIC = (tid) => {
    openedTopicId = tid;
  };

  const model = {
    source: "work",
    sourceId: "topic_batch_1",
    title: "Batch Work",
    images: ["/img/batch_1.webp"],
    prompt: "prompt",
    batchWorks: [
      { workId: "w_batch_1", topicId: "topic_batch_1", imageUrl: "/img/batch_1.webp", index: 1, total: 4, isCurrent: true },
      { workId: "w_batch_2", topicId: "topic_batch_2", imageUrl: "/img/batch_2.webp", index: 2, total: 4, isCurrent: false },
    ],
  };

  // Mock DOM root
  const listeners = {};
  const mockThumb2 = {
    getAttribute: (attr) => (attr === "data-fwp-topic" ? "topic_batch_2" : null),
    classList: { toggle: () => {} },
    setAttribute: () => {},
    addEventListener: (evt, fn) => { listeners[evt] = fn; },
  };

  const mockRoot = {
    querySelector: (sel) => {
      if (sel === ".fwp") return mockRoot;
      if (sel === "[data-fwp-stage]") return { querySelector: () => null };
      if (sel === "[data-fwp-main]") return { addEventListener: () => {}, setAttribute: () => {} };
      if (sel === "[data-fwp-copy]") return null;
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel === ".fwp-thumb") return [mockThumb2];
      return [];
    },
  };

  FWP.bind(mockRoot, model);

  // Trigger click on thumb 2
  assert.ok(listeners["click"], "Click listener must be registered on thumb");
  listeners["click"]();
  assert.equal(openedTopicId, "topic_batch_2", "Clicking sibling thumbnail must navigate to topic_batch_2");
  console.log("✓ Test 3 Passed: Sibling thumbnail click seamlessly navigates to sibling topic ID.");
}

console.log("\n=======================================================");
console.log("ALL STAGE 4 UNIFIED WORK-TOPIC DETAIL TESTS PASSED! 🎉");
console.log("=======================================================");
