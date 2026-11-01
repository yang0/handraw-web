/**
 * Test Suite for Phase 3b-3: Article Illustration Preview/Editor Switch & Advanced Canvas Interface Polish
 */

const assert = require("assert");
const fs = require("fs");
const path = require("path");

console.log("Starting test_article_canvas.cjs...\n");

// Read source files
const studioAppSource = fs.readFileSync(path.join(__dirname, "../demo/assets/studio-app.js"), "utf8");
const promptEngineSource = fs.readFileSync(path.join(__dirname, "../demo/assets/studio-prompt-engine.js"), "utf8");
const quickCreateCss = fs.readFileSync(path.join(__dirname, "../demo/assets/quick-create.css"), "utf8");

// Regex for emoji detection
const emojiRegex = /[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;

// ==========================================
// Test 1: Segmented switch DOM & duplicate button removal
// ==========================================
console.log("Checking Test 1: Article Editor & Preview Segmented Switch DOM...");

// 1.1 Segmented switch CSS exists
assert(quickCreateCss.includes(".ic-article-segmented-switch"), "quick-create.css must define .ic-article-segmented-switch");
assert(quickCreateCss.includes(".ic-article-seg-btn"), "quick-create.css must define .ic-article-seg-btn");

// 1.2 renderArticleEditorPage has topbar with list btn and segmented switch
assert(studioAppSource.includes('id="editor-btn-back"'), "Editor topbar must contain #editor-btn-back (← 文章列表)");
assert(studioAppSource.includes('id="editor-switch-group"'), "Editor topbar must contain #editor-switch-group");
assert(studioAppSource.includes('id="editor-switch-editor"'), "Editor switch must contain #editor-switch-editor");
assert(studioAppSource.includes('id="editor-switch-preview"'), "Editor switch must contain #editor-switch-preview");

// 1.3 renderArticlePreviewPage has topbar with list btn and segmented switch
assert(studioAppSource.includes('id="preview-btn-list"'), "Preview topbar must contain #preview-btn-list (← 文章列表)");
assert(studioAppSource.includes('id="preview-switch-group"'), "Preview topbar must contain #preview-switch-group");
assert(studioAppSource.includes('id="preview-switch-editor"'), "Preview switch must contain #preview-switch-editor");
assert(studioAppSource.includes('id="preview-switch-preview"'), "Preview switch must contain #preview-switch-preview");

// 1.4 Duplicate button preview-btn-back-editor-2 removed from preview footer
assert(!studioAppSource.includes('preview-btn-back-editor-2'), "Duplicate #preview-btn-back-editor-2 must be removed from preview footer");

console.log("✓ Test 1 Passed: Segmented switch markup and duplicate button removal verified.\n");

// ==========================================
// Test 2: Canvas First Entry Template Library
// ==========================================
console.log("Checking Test 2: Canvas Template Library...");

assert(quickCreateCss.includes(".ic-canvas-template-library"), "quick-create.css must define .ic-canvas-template-library");
assert(quickCreateCss.includes(".ic-tmpl-grid"), "quick-create.css must define .ic-tmpl-grid");
assert(quickCreateCss.includes(".ic-tmpl-card"), "quick-create.css must define .ic-tmpl-card");

assert(studioAppSource.includes("renderCanvasTemplateLibrary"), "studio-app.js must implement renderCanvasTemplateLibrary");
assert(studioAppSource.includes('bp: "single"'), "Template library must support single image template");
assert(studioAppSource.includes('bp: "loop_100"'), "Template library must support loop_100 template");
assert(studioAppSource.includes('bp: "style_ab"'), "Template library must support style_ab template");
assert(studioAppSource.includes('bp: "ip_story"'), "Template library must support ip_story template");
assert(studioAppSource.includes('bp: "omnimedia"'), "Template library must support omnimedia template");
assert(studioAppSource.includes('bp: "fusion"'), "Template library must support fusion template");
assert(studioAppSource.includes('bp: "blank"'), "Template library must support blank template");

// Check that hydrateTabsAndUrlParams does NOT force default 3 tabs when localStorage is empty
assert(studioAppSource.includes("CS.tabs = [];"), "Empty localStorage must initialize CS.tabs to empty array");

// 2.2 Template library hides floating toolstrip, minimap, and save button
assert(
  studioAppSource.includes('const isShowingTemplateLib = CS.stageView === "canvas" && (!CS.tabs || !CS.tabs.length);'),
  "studio-app.js must detect whether template library is currently showing"
);
assert(
  quickCreateCss.includes(".ic-canvas-stage:has(.ic-canvas-template-library) .ic-canvas-toolstrip"),
  "quick-create.css must hide .ic-canvas-toolstrip when template library is present"
);
assert(
  quickCreateCss.includes(".ic-canvas-stage:has(.ic-canvas-template-library) .ic-bottom-right-dock"),
  "quick-create.css must hide .ic-bottom-right-dock when template library is present"
);
assert(
  quickCreateCss.includes(".ic-canvas-stage:has(.ic-canvas-template-library) .ic-minimap"),
  "quick-create.css must hide .ic-minimap when template library is present"
);

// Check function renderCanvasToolstrip hides toolstrip on template library
const toolstripMatch = studioAppSource.match(/function renderCanvasToolstrip\(\)\s*\{([\s\S]*?)\n  \}/);
assert(toolstripMatch, "renderCanvasToolstrip function must be found");
assert(toolstripMatch[1].includes('DOM.canvasToolstrip.style.display = "none";'), "renderCanvasToolstrip must hide toolstrip when template library is showing");
assert(toolstripMatch[1].includes('DOM.canvasToolstrip.style.display = "";'), "renderCanvasToolstrip must restore toolstrip when template is active");

// Check function renderMinimap hides minimap on template library
const minimapMatch = studioAppSource.match(/function renderMinimap\(\)\s*\{([\s\S]*?)\n  \}/);
assert(minimapMatch, "renderMinimap function must be found");
assert(minimapMatch[1].includes('!isShowingTemplateLib'), "renderMinimap must hide minimap window when template library is showing");

// Check function renderTopAndBottomDocks hides bottomRight (save button & minimap button) on template library
const docksMatch = studioAppSource.match(/function renderTopAndBottomDocks\(\)\s*\{([\s\S]*?)\n  \}/);
assert(docksMatch, "renderTopAndBottomDocks function must be found");
assert(docksMatch[1].includes('DOM.bottomRight.style.display = (CS.stageView === "canvas" && !isShowingTemplateLib) ? "flex" : "none";'), "renderTopAndBottomDocks must hide bottom-right bar when template library is showing");
assert(docksMatch[1].includes('DOM.bottomRight.innerHTML = "";'), "renderTopAndBottomDocks must clear bottom-right dock when template library is showing");

console.log("✓ Test 2 Passed: Canvas Template Library on first entry & dock hiding verified.\n");

// ==========================================
// Test 3: Zero Emoji in Prompt Engine & Blueprint Defs
// ==========================================
console.log("Checking Test 3: Zero Emoji in Prompt Engine & Blueprint Defs...");

global.window = global;
require(path.join(__dirname, "../demo/assets/studio-prompt-engine.js"));
const E = global.HANDRAW_CANVAS_ENGINE;

assert(E, "HANDRAW_CANVAS_ENGINE must be exported on window");

// Check PRESET_WORKFLOW_DEFS
Object.entries(E.PRESET_WORKFLOW_DEFS || {}).forEach(([key, def]) => {
  assert(!emojiRegex.test(def.title), `Blueprint def ${key} title must have no emoji: ${def.title}`);
  assert(!emojiRegex.test(def.scenarioBadge || ""), `Blueprint def ${key} scenarioBadge must have no emoji: ${def.scenarioBadge}`);
  assert(!emojiRegex.test(def.scenarioDesc || ""), `Blueprint def ${key} scenarioDesc must have no emoji: ${def.scenarioDesc}`);
});

// Check OUTPUT_MODES
(E.OUTPUT_MODES || []).forEach((m) => {
  assert(!emojiRegex.test(m.icon || ""), `OUTPUT_MODE ${m.id} icon must have no emoji: ${m.icon}`);
  assert(!emojiRegex.test(m.label || ""), `OUTPUT_MODE ${m.id} label must have no emoji: ${m.label}`);
});

// Check LOOP_MODES
(E.LOOP_MODES || []).forEach((m) => {
  assert(!emojiRegex.test(m.icon || ""), `LOOP_MODE ${m.id} icon must have no emoji: ${m.icon}`);
  assert(!emojiRegex.test(m.label || ""), `LOOP_MODE ${m.id} label must have no emoji: ${m.label}`);
});

// Check FISSION_STRATEGIES
(E.FISSION_STRATEGIES || []).forEach((s) => {
  assert(!emojiRegex.test(s.icon || ""), `FISSION_STRATEGY ${s.id} icon must have no emoji: ${s.icon}`);
  assert(!emojiRegex.test(s.label || ""), `FISSION_STRATEGY ${s.id} label must have no emoji: ${s.label}`);
});

console.log("✓ Test 3 Passed: Zero emoji in Prompt Engine & Blueprint Defs verified.\n");

// ==========================================
// Test 4: Terminology Substitutions & Removed Internal Counts
// ==========================================
console.log("Checking Test 4: Terminology Substitutions & Internal Count Stripping...");

// 4.1 Terminology replacements
const forbiddenTerms = [
  "选题裂变",
  "循环批量",
  "裂变、循环与桥接"
];

// Check NODE_TOOLBOX_GROUPS definition in studio-app.js
const tbMatch = studioAppSource.match(/const NODE_TOOLBOX_GROUPS = \[([\s\S]*?)\];/);
assert(tbMatch, "NODE_TOOLBOX_GROUPS must be defined");
const tbCode = tbMatch[0];
assert(!emojiRegex.test(tbCode), "NODE_TOOLBOX_GROUPS must have no emoji");
assert(tbCode.includes("AI 扩写主题"), "NODE_TOOLBOX_GROUPS must contain 'AI 扩写主题'");
assert(tbCode.includes("批量"), "NODE_TOOLBOX_GROUPS must contain '批量'");
assert(tbCode.includes("多尺寸输出"), "NODE_TOOLBOX_GROUPS must contain '多尺寸输出'");
assert(tbCode.includes("生成设置"), "NODE_TOOLBOX_GROUPS must contain '生成设置'");
assert(!tbCode.includes("选题裂变"), "NODE_TOOLBOX_GROUPS must not contain '选题裂变'");
assert(!tbCode.includes("循环批量"), "NODE_TOOLBOX_GROUPS must not contain '循环批量'");
assert(!tbCode.includes("桥接"), "NODE_TOOLBOX_GROUPS must not contain '桥接'");
assert(!tbCode.includes("输出控制"), "NODE_TOOLBOX_GROUPS must not contain '输出控制'");

// 4.2 Bottom-right controls in studio-app.js
assert(studioAppSource.includes('>缩略图</button>'), "Minimap button must be labeled '缩略图'");
assert(!studioAppSource.includes('>🧭 鹰眼</button>'), "Minimap button must not contain '>🧭 鹰眼</button>'");

// 4.3 Internal count strings removed
assert(!studioAppSource.includes("风格参数(5项)"), "studio-app.js must not contain '风格参数(5项)'");
assert(!studioAppSource.includes("文本参数(45字)"), "studio-app.js must not contain '文本参数(45字)'");
assert(!studioAppSource.includes("选题裂变(10条)"), "studio-app.js must not contain '选题裂变(10条)'");

console.log("✓ Test 4 Passed: Terminology substitutions & internal counts stripped.\n");

// ==========================================
// Test 5: Secondary Cost Confirmation (> 20 items)
// ==========================================
console.log("Checking Test 5: Secondary Cost Confirmation (> 20 items)...");

assert(studioAppSource.includes("confirmSecondaryBatchCost"), "studio-app.js must implement confirmSecondaryBatchCost");
assert(studioAppSource.includes("confirmPotentialGenerationCost"), "studio-app.js must have confirmPotentialGenerationCost");

// Check threshold logic in confirmPotentialGenerationCost
const fnMatch = studioAppSource.match(/function confirmPotentialGenerationCost[\s\S]*?^  \}/m);
assert(fnMatch, "confirmPotentialGenerationCost function must be found");
assert(fnMatch[0].includes("count > 20"), "confirmPotentialGenerationCost must check if count > 20 for secondary confirmation");

console.log("✓ Test 5 Passed: Secondary cost confirmation for > 20 items verified.\n");

// ==========================================
// Test 6: Blank Canvas Bug Guard
// ==========================================
console.log("Checking Test 6: Blank Canvas Bug Guard in fitView()...");

const fitViewMatch = studioAppSource.match(/function fitView\([\s\S]*?\)\s*\{([\s\S]*?)\n  \}/);
assert(fitViewMatch, "fitView() function must be found");
const fitViewCode = fitViewMatch[1];

assert(fitViewCode.includes('if (CS.stageView !== "canvas") return;'), "fitView must guard against non-canvas stageView");
assert(fitViewCode.includes("vRect.width <= 0 || vRect.height <= 0"), "fitView must guard against 0x0 viewport dimensions");

console.log("✓ Test 6 Passed: Blank canvas bug guard verified.\n");

console.log("====================================================");
console.log("ALL 6 ARTICLE & CANVAS TESTS PASSED SUCCESSFULLY!");
console.log("====================================================");
