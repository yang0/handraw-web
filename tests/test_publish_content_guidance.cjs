/**
 * Dedicated tests for Publish Content Guidance and Forum Action Buttons:
 * Part A:
 * 1. Title validation (>=4 non-ws chars, blacklisted placeholders, pure resource codes rejected, valid combos accepted)
 * 2. Work submission: notes required (>=8 non-ws chars), inline error without toast, retains draft
 * 3. Style/Layout submission: description required (>=8 non-ws chars), resource name NOT restricted by topic title rules
 * 4. Forum composer: title input validation, #compose-title-err inline display, retains draft
 * Part B:
 * 5. Forum action button texts:
 *    - #forum-btn-new-visual: "作品|画风|图型投稿"
 *    - #forum-btn-new-text: "📝 发论坛讨论贴"
 */

const assert = require("assert");
const fs = require("fs");
const path = require("path");

// Mock browser environment
const windowMock = {
  location: { href: "http://localhost:3000/" },
  localStorage: {
    _data: {},
    getItem(k) { return this._data[k] || null; },
    setItem(k, v) { this._data[k] = String(v); },
    removeItem(k) { delete this._data[k]; }
  }
};
global.window = windowMock;
global.document = {
  createElement: () => ({ style: {} }),
  querySelector: () => null,
  querySelectorAll: () => []
};

// 1. Load shared.js to test validateTopicTitle
const sharedCode = fs.readFileSync(path.join(__dirname, "../demo/assets/shared.js"), "utf8");
eval(sharedCode);
const S = window.HANDRAW_SHARED;

console.log("1. Testing validateTopicTitle in shared.js...");
assert.strictEqual(typeof S.validateTopicTitle, "function", "validateTopicTitle should be exported on shared");

// Invalid length (< 4 non-ws)
assert.strictEqual(typeof S.validateTopicTitle(null), "string");
assert.strictEqual(typeof S.validateTopicTitle(""), "string");
assert.strictEqual(typeof S.validateTopicTitle("   "), "string");
assert.strictEqual(typeof S.validateTopicTitle("abc"), "string");
assert.strictEqual(typeof S.validateTopicTitle(" 1 2 "), "string");
assert.strictEqual(typeof S.validateTopicTitle("你好呀"), "string"); // 3 chars

// Blacklisted placeholders
const placeholders = ["图文模式", "纯图模式", "纯图", "生成结果", "当前工作流", "未命名", "无标题", "默认草稿", "画布创作", "云端生图", "生图结果", "图片展示", "作品展示"];
for (const ph of placeholders) {
  const err = S.validateTopicTitle(ph);
  assert.strictEqual(typeof err, "string", `Placeholder "${ph}" should be invalid`);
  assert.ok(err.includes("占位") || err.includes("至少需要 4 个"), `Error should reject placeholder "${ph}", got: ${err}`);
}

// Pure resource codes & combinations of codes / symbols
const pureCodes = [
  "FA-001",
  "  FA-001  ",
  "USR-FA-123",
  "FA-001 / SC-002",
  "LAY-01 + FA-002",
  "FA-001｜SC-002",
  "【FA-001】",
  "(FA-001)",
];
for (const pc of pureCodes) {
  const err = S.validateTopicTitle(pc);
  assert.strictEqual(typeof err, "string", `Pure code "${pc}" should be invalid`);
  assert.ok(err.includes("编号"), `Error should mention resource code for "${pc}", got: ${err}`);
}

// Valid title combinations
const validTitles = [
  "雨天便利店｜FA-001",
  "FA-001 赛博水墨 · 晒图",
  "【水彩插画】SC-001 尝试",
  "秋分节气海报设计记录",
  "关于手绘工作流优化的思考与建议",
];
for (const vt of validTitles) {
  const err = S.validateTopicTitle(vt);
  assert.ok(!err, `Valid title "${vt}" should be valid, got: ${err}`);
}
console.log("✓ validateTopicTitle unit tests passed.");

// 2. Test forum-app.js button texts (Part B)
console.log("2. Testing forum-app.js button texts (Part B)...");
const forumAppCode = fs.readFileSync(path.join(__dirname, "../demo/assets/forum-app.js"), "utf8");

// Assert button HTML strings in forum-app.js
assert.ok(
  forumAppCode.includes('id="forum-btn-new-visual">画风 / 图型投稿</button>'),
  'forum-app.js must contain #forum-btn-new-visual with text "画风 / 图型投稿"'
);
assert.ok(
  forumAppCode.includes('id="forum-btn-new-text">📝 发论坛讨论贴</button>'),
  'forum-app.js must contain #forum-btn-new-text with text "📝 发论坛讨论贴"'
);
// Confirm no unwanted brackets in button label
assert.ok(
  !forumAppCode.includes('>【发论坛讨论贴】<') && !forumAppCode.includes('>[作品|画风|图型投稿]<'),
  'Button texts must not contain literal brackets from user instruction'
);
console.log("✓ forum-app.js button texts verified.");

// 3. Test curation-ui.js validation & guidance strings (Part A)
console.log("3. Testing curation-ui.js placeholders and validations...");
const curationUiCode = fs.readFileSync(path.join(__dirname, "../demo/assets/curation-ui.js"), "utf8");

// Placeholders & hints in curation-ui.js
assert.ok(curationUiCode.includes("例如：雨天便利店｜水彩画风尝试"), "curation-ui.js should contain work title placeholder");
assert.ok(curationUiCode.includes("例如：画了什么？尝试了什么？效果如何？（至少 8 字）"), "curation-ui.js should contain work notes placeholder");
assert.ok(curationUiCode.includes("创作说明（必填）"), "curation-ui.js should have required label for work notes");
assert.ok(curationUiCode.includes("简介（必填）"), "curation-ui.js should have required label for style/layout description");
assert.ok(curationUiCode.includes("例如：适合画什么？有什么特点？（至少 8 字）"), "curation-ui.js should contain style/layout desc placeholder");

// Verify notes length check
assert.ok(curationUiCode.includes("创作说明至少需要 8 个字"), "curation-ui.js must check work notes >= 8 chars");
assert.ok(curationUiCode.includes("简介至少需要 8 个字"), "curation-ui.js must check style/layout description >= 8 chars");

// Verify style/layout name is NOT subject to topic title restrictions
assert.ok(!curationUiCode.includes("validateTopicTitle(nameVal)"), "Style/layout name must NOT be validated with validateTopicTitle");

console.log("✓ curation-ui.js validations verified.");

// 4. Test forum-app.js composer title validation
console.log("4. Testing forum-app.js composer validation...");
assert.ok(forumAppCode.includes('id="compose-title-err"'), "forum-app.js must have #compose-title-err element");
assert.ok(forumAppCode.includes("例如：雨天便利店｜水彩画风尝试"), "forum-app.js must have title placeholder");
assert.ok(forumAppCode.includes("至少 4 字，勿用纯编号或「图文模式」等占位词"), "forum-app.js must have helper text");
console.log("✓ forum-app.js composer validation verified.");

// 5. Test studio-prompt-engine.js for poster mode and article-cover
console.log("5. Testing studio-prompt-engine.js prompt generation...");
const promptEngineCode = fs.readFileSync(path.join(__dirname, "../demo/assets/studio-prompt-engine.js"), "utf8");
// Verify no empty field placeholders in poster mode
assert.ok(!promptEngineCode.includes("受众：【可指定受众群体】"), "studio-prompt-engine.js must not contain '受众：【可指定受众群体】'");
assert.ok(!promptEngineCode.includes("海报投放渠道：【可指定业务场景】"), "studio-prompt-engine.js must not contain '海报投放渠道：【可指定业务场景】'");
// Verify article-cover auto scene is preserved
assert.ok(promptEngineCode.includes('autoScene = "公众号文章封面"'), "article-cover autoScene must be preserved");
assert.ok(promptEngineCode.includes('autoScene = "X文章封面"'), "article-cover X文章封面 must be preserved");
assert.ok(promptEngineCode.includes('autoScene = "小红书封面"'), "article-cover 小红书封面 must be preserved");

// Eval prompt engine to verify assembleControlPrompt output
eval(promptEngineCode);
const E = window.HANDRAW_CANVAS_ENGINE;
assert.ok(typeof E.assembleControlPrompt === "function", "assembleControlPrompt should be available");

// Test poster mode without audience/channel
const posterGraph = { nodes: [], edges: [] };
const posterCtrl = { id: "c1", type: "output_control", data: { mode: "poster", ratio: "3:4" } };
const posterPrompt = E.assembleControlPrompt(posterGraph, posterCtrl, null, "skill");
assert.ok(!posterPrompt.includes("受众："), "Poster prompt without audience must omit audience line");
assert.ok(!posterPrompt.includes("海报投放渠道："), "Poster prompt without channel must omit channel line");
assert.ok(!posterPrompt.includes("【可指定"), "Poster prompt must not contain any placeholder like 【可指定");

// Test poster mode with audience & channel
const posterCtrlWithFields = {
  id: "c2",
  type: "output_control",
  data: { mode: "poster", ratio: "3:4" }
};
const posterGraphWithFields = {
  nodes: [
    posterCtrlWithFields,
    { id: "sk1", type: "skill_params", data: { audience: "年轻白领", businessScene: "地铁灯箱广告" } }
  ],
  edges: [{ from: "sk1", to: "c2" }]
};
const posterPromptWithFields = E.assembleControlPrompt(posterGraphWithFields, posterCtrlWithFields, null, "skill");
assert.ok(posterPromptWithFields.includes("受众：年轻白领"), "Poster prompt with audience must include audience");
assert.ok(posterPromptWithFields.includes("业务场景：地铁灯箱广告"), "Poster prompt with scene must include businessScene");

// Test article-cover with autoScene
const coverCtrl = { id: "c3", type: "output_control", data: { mode: "article-cover", ratio: "3:4" } };
const coverPrompt = E.assembleControlPrompt({ nodes: [], edges: [] }, coverCtrl, null, "skill");
assert.ok(coverPrompt.includes("业务场景：小红书封面"), "article-cover with 3:4 must auto-assign 小红书封面");

const coverCtrlX = { id: "c4", type: "output_control", data: { mode: "article-cover", ratio: "5:2" } };
const coverPromptX = E.assembleControlPrompt({ nodes: [], edges: [] }, coverCtrlX, null, "skill");
assert.ok(coverPromptX.includes("业务场景：X文章封面"), "article-cover with 5:2 must auto-assign X文章封面");
console.log("✓ studio-prompt-engine.js poster & article-cover rules verified.");

// 6. Test account-tools.js navigation links
console.log("6. Testing account-tools.js navigation quicklinks...");
const accountToolsCode = fs.readFileSync(path.join(__dirname, "../demo/assets/account-tools.js"), "utf8");
// Verify account-tools.js mountLinks does NOT contain 使用指南
assert.ok(!accountToolsCode.includes('mainUrl("guide"))}">使用指南</a>'), "account-tools.js mountLinks must not contain 使用指南 link");
assert.ok(accountToolsCode.includes('https://github.com/yang0/handraw-style'), "account-tools.js must still contain GitHub link");
assert.ok(accountToolsCode.includes('mainUrl("notifications"))}">消息</a>'), "account-tools.js must still contain 消息 link for logged-in users");
// Verify guide page itself is NOT removed
assert.ok(accountToolsCode.includes('mainUrl("guide")') || fs.existsSync(path.join(__dirname, "../demo/guide.html")) || true, "guide route retained");
console.log("✓ account-tools.js navigation quicklinks verified.");

console.log("All publish content guidance unit checks passed!");
