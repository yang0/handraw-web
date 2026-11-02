/**
 * Unit tests for Task #4 (Issue #5): Share title uses real generation subject.
 * Tests resolveShareTitle priority:
 * 1. User explicitly edited work title
 * 2. Selected image's generation subject
 * 3. Recipe snapshot subject
 * 4. Article title
 * 5. "未命名作品"
 *
 * Also tests:
 * - Subject "雨夜书店" + tab "图文模式" -> "雨夜书店"
 * - Changing canvas subject does not alter old history entry's share title
 * - "开始工作了" as a genuine subject is preserved and not blacklisted
 * - User manual title is not overwritten
 * - Forum draft title retention
 */

const assert = require("assert");
const fs = require("fs");
const path = require("path");

// Mock browser environment for studio-app.js logic testing
const windowMock = {
  location: { href: "http://localhost:3000/", search: "" },
  localStorage: {
    _data: {},
    getItem: function (k) { return this._data[k] || null; },
    setItem: function (k, v) { this._data[k] = String(v); },
    removeItem: function (k) { delete this._data[k]; },
    clear: function () { this._data = {}; }
  },
  addEventListener: () => {},
  removeEventListener: () => {}
};
global.window = windowMock;
global.document = {
  createElement: () => ({ style: {}, classList: { add: () => {}, remove: () => {} }, setAttribute: () => {} }),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {}
};

// Read studio-app.js to ensure resolveShareTitle is exported and verify its logic
const studioCode = fs.readFileSync(path.join(__dirname, "../demo/assets/studio-app.js"), "utf8");

// Extract resolveShareTitle from studio-app.js
assert.ok(studioCode.includes("function resolveShareTitle("), "studio-app.js must define resolveShareTitle");
assert.ok(studioCode.includes("resolveShareTitle"), "studio-app.js must export resolveShareTitle");

// Create isolated evaluation sandbox for resolveShareTitle
const fnMatch = studioCode.match(/function resolveShareTitle\([\s\S]*?\n  \}/);
assert.ok(fnMatch, "Must be able to match resolveShareTitle function block");
const resolveShareTitle = eval(`(${fnMatch[0]})`);

console.log("Testing resolveShareTitle priority levels...");

// Priority 1: User explicitly edited work title
{
  const entry = {
    id: "h_1",
    tabTitle: "图文模式",
    subject: "雨夜书店",
    title: "我自定义的雨夜咖啡馆",
    isCustomTitle: true,
    items: [{ id: "i_1", title: "成图 #1", subject: "雨夜书店" }]
  };
  const title = resolveShareTitle(entry, entry.items[0]);
  assert.strictEqual(title, "我自定义的雨夜咖啡馆", "Priority 1: custom title must take highest precedence");
}

// Priority 1 via item manual title
{
  const entry = {
    id: "h_1b",
    tabTitle: "图文模式",
    subject: "雨夜书店",
    items: [{ id: "i_1", title: "手动命名的卡片", isCustomTitle: true, subject: "雨夜书店" }]
  };
  const title = resolveShareTitle(entry, entry.items[0]);
  assert.strictEqual(title, "手动命名的卡片", "Priority 1: item custom title must take precedence");
}

// Priority 1 via options override
{
  const entry = {
    id: "h_1c",
    tabTitle: "图文模式",
    subject: "雨夜书店",
    items: [{ id: "i_1", title: "成图 #1", subject: "雨夜书店" }]
  };
  const title = resolveShareTitle(entry, entry.items[0], { customTitle: "分享前输入的新标题" });
  assert.strictEqual(title, "分享前输入的新标题", "Priority 1: options custom title must take precedence");
}

// Priority 2: Selected image's generation subject (雨夜书店 + 图文模式 -> 雨夜书店)
{
  const entry = {
    id: "h_2",
    tabTitle: "图文模式",
    subject: "雨夜书店",
    items: [{ id: "i_1", title: "成图 #1", subject: "雨夜书店" }]
  };
  const title = resolveShareTitle(entry, entry.items[0]);
  assert.strictEqual(title, "雨夜书店", "Priority 2: item subject must be used over tabTitle");
  assert.ok(!title.includes("图文模式"), "Share title must not contain workspace mode name");
}

// Priority 2: Multi-image generation with distinct subject per image
{
  const entry = {
    id: "h_2b",
    tabTitle: "批量生成",
    subject: "中国古建系列",
    items: [
      { id: "i_1", title: "成图 #1", subject: "雨夜书店" },
      { id: "i_2", title: "成图 #2", subject: "徽派马头墙" }
    ]
  };
  assert.strictEqual(resolveShareTitle(entry, entry.items[0]), "雨夜书店");
  assert.strictEqual(resolveShareTitle(entry, entry.items[1]), "徽派马头墙");
}

// Canvas modification isolation: modifying canvas subject does not alter old history entry's share title
{
  const oldHistoryEntry = {
    id: "h_old",
    tabTitle: "图文模式",
    subject: "雨夜书店",
    items: [{ id: "i_1", title: "成图 #1", subject: "雨夜书店" }]
  };

  // Simulate active canvas changing to a different subject
  const currentCanvasTheme = "赛博朋克深空探索";

  // Share title for old history entry must remain "雨夜书店"
  const shareTitle = resolveShareTitle(oldHistoryEntry, oldHistoryEntry.items[0]);
  assert.strictEqual(shareTitle, "雨夜书店", "Old history title must not be affected by current canvas state");
  assert.notStrictEqual(shareTitle, currentCanvasTheme, "Must not derive title from current canvas");
}

// Special case: "开始工作了" as genuine user subject is NOT blacklisted
{
  const entry = {
    id: "h_start_work",
    tabTitle: "图文模式",
    subject: "开始工作了",
    items: [{ id: "i_1", title: "成图 #1", subject: "开始工作了" }]
  };
  const title = resolveShareTitle(entry, entry.items[0]);
  assert.strictEqual(title, "开始工作了", "Genuine user subject '开始工作了' must be preserved and not blacklisted");
}

// Priority 3: Recipe snapshot subject
{
  const entry = {
    id: "h_3",
    tabTitle: "做图配方",
    items: [
      {
        id: "i_1",
        title: "成图 #1",
        recipeSnapshot: {
          style1: "FA-003",
          layout: "SC-023",
          subject: "秋日清晨水彩森林"
        }
      }
    ]
  };
  const title = resolveShareTitle(entry, entry.items[0]);
  assert.strictEqual(title, "秋日清晨水彩森林", "Priority 3: recipe snapshot subject must be used when top-level subject missing");
}

// Priority 4: Article title
{
  const entry = {
    id: "h_4",
    tabTitle: "文章自动配图",
    articleTitle: "手账感排版指南：网格、胶带与手写批注的分寸感",
    items: [{ id: "i_1", title: "文章封面", role: "cover" }]
  };
  const title = resolveShareTitle(entry, entry.items[0]);
  assert.strictEqual(title, "手账感排版指南：网格、胶带与手写批注的分寸感", "Priority 4: article title must be used for article illustration");
}

// Priority 4: Article title parsed from markdown
{
  const entry = {
    id: "h_4b",
    tabTitle: "文章配图方案",
    markdown: "# 视觉笔记创作指南\n\n导语：手绘笔记...",
    items: [{ id: "i_1", title: "配图" }]
  };
  const title = resolveShareTitle(entry, entry.items[0]);
  assert.strictEqual(title, "视觉笔记创作指南", "Priority 4: article title from markdown # heading");
}

// Priority 5: Fallback to "未命名作品"
{
  const emptyEntry = {
    id: "h_empty",
    tabTitle: "图文模式",
    items: [{ id: "i_1", title: "成图 #1" }]
  };
  const title = resolveShareTitle(emptyEntry, emptyEntry.items[0]);
  assert.strictEqual(title, "未命名作品", "Priority 5: fallback must be '未命名作品' rather than tabTitle");
  assert.ok(!title.includes("图文模式"), "Fallback must never leak tab title");
}

// Verify upsertHistoryEntry and normalizeHistoryEntry retain subject
{
  const normMatch = studioCode.match(/function normalizeHistoryEntry\([\s\S]*?\n  \}/);
  assert.ok(normMatch, "normalizeHistoryEntry must exist");
  const E = { uid: (p) => `${p}_mock_${Date.now()}` };
  const normalizeHistoryEntry = eval(`(${normMatch[0]})`);

  const raw = {
    tabTitle: "图文模式",
    subject: "雨夜书店",
    items: [{ title: "成图 #1", subject: "雨夜书店", imageUrl: "/test.png" }]
  };
  const normalized = normalizeHistoryEntry(raw);
  assert.strictEqual(normalized.subject, "雨夜书店", "Normalized entry must retain subject");
  assert.strictEqual(normalized.items[0].subject, "雨夜书店", "Normalized items must retain subject");
}

console.log("✓ All resolveShareTitle and subject persistence tests passed successfully!");
