"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");

const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const styles = fs.readFileSync("demo/assets/studio-canvas.css", "utf8");
const quickStyles = fs.readFileSync("demo/assets/quick-create.css", "utf8");
assert.match(quickStyles, /\.qc-entry-bar\s*\{\s*padding-inline:\s*var\(--hw-page-gutter\);/, "Creation navigation must use the shared responsive gutter");
const start = studio.indexOf("  function historyRecordCategory(h) {");
const end = studio.indexOf("  /* ======================== VIEWPORT", start);
assert.ok(start >= 0 && end > start, "Studio history helpers and stage must exist");

const records = [
  { id: "cover_mode", mode: "article-cover", kind: "single", items: [{ title: "文章封面", imageUrl: "/cover1.webp" }], status: "success" },
  { id: "cover_legacy", mode: "poster", kind: "single", items: [{ title: "单独生成封面图", imageUrl: "/cover2.webp" }], status: "success" },
  { id: "batch", mode: "graphic-text", kind: "loop", items: [
    { imageUrl: "/batch1.webp", title: "一" }, { imageUrl: "/batch2.webp", title: "二" }, { imageUrl: "/batch3.webp", title: "三" }
  ], status: "success" },
  { id: "quick", mode: "poster", recipeId: "rcp_a", kind: "single", items: [
    { imageUrl: "/quick1.webp" }, { imageUrl: "/quick2.webp" }
  ], status: "success" },
  { id: "canvas", mode: "graphic-text", creationSource: "canvas", ctrlId: "ctrl_existing_01", kind: "single", items: [
    { imageUrl: "/canvas1.webp" }, { imageUrl: "/canvas2.webp" }
  ], status: "success" },
];
const state = {
  stageView: "history", generationHistory: records,
  historyFilter: "all", historyStatusFilter: "all", historyQuery: "",
  historySort: "newest", historyPage: 1,
  historyExpandedPromptIds: {}, historyExpandedBatchIds: {}, historySelectedPreview: {}
};
const stage = {
  style: {}, innerHTML: "", expandBindings: [],
  querySelector() { return null; },
  querySelectorAll(selector) {
    if (selector !== "[data-hist-expand-batch]") return [];
    this.expandBindings = [...this.innerHTML.matchAll(/data-hist-expand-batch="([^"]+)"/g)]
      .map((match) => ({ id: match[1], onclick: null, getAttribute() { return match[1]; } }));
    return this.expandBindings;
  }
};
const compile = new Function(
  "DOM", "CS", "S", "esc", "ensureGenerationHistoryInitialized", "document", "window", "toast",
  "renderTopAndBottomDocks", "deleteCloudHistory", "restoreHistoryEntryToCanvas", "exportZipFromPayload", "switchCreationStage",
  studio.slice(start, end) + "\nreturn { historyRecordCategory, historyImageCount, renderHistoryStage };"
);
const switchedModes = [];
const app = compile(
  { historyStage: stage }, state, { filterDisplayPrompt: (x) => x },
  (x) => String(x ?? ""), () => {}, { activeElement: null },
  { history: { replaceState() {} }, confirm: () => true }, () => {}, () => {}, () => {}, () => {}, () => {},
  (mode) => switchedModes.push(mode)
);
const sums = { quick: 0, batch: 0, article: 0, canvas: 0 };
for (const record of records) sums[app.historyRecordCategory(record)] += app.historyImageCount(record);
assert.equal(Object.values(sums).reduce((a, b) => a + b, 0), 9);
assert.equal(sums.article, 2, "Independent cover images must be under article");
assert.equal(sums.batch, 3);
assert.equal(sums.quick, 2);
assert.equal(sums.canvas, 2);

app.renderHistoryStage();
assert.match(stage.innerHTML, /生图历史 · 9 张/);
assert.match(stage.innerHTML, /data-hist-filter="all">全部 \(9\)/);
assert.match(stage.innerHTML, /data-hist-filter="article">文章配图 \(2\)/);
assert.match(stage.innerHTML, /data-hist-filter="batch">批量 \(3\)/);
assert.match(stage.innerHTML, /data-hist-filter="quick">做图 \(2\)/);
assert.match(stage.innerHTML, /data-hist-filter="canvas">画布 \(2\)/);
assert.equal((stage.innerHTML.match(/class="ic-hist-cover-button"/g) || []).length, 5,
  "Only one cover image should be rendered per generation task");
assert.ok(!stage.innerHTML.includes("ic-hist-expanded-gallery"), "Batches should start folded");
assert.ok(!stage.innerHTML.includes("hist-back-creation"), "History must not have a back button");
assert.ok(!stage.innerHTML.includes("hist-empty-back-creation"));
const batchButton = stage.expandBindings.find((button) => button.id === "batch");
assert.ok(batchButton && typeof batchButton.onclick === "function", "Click handler must be installed");
batchButton.onclick();
assert.equal(state.historyExpandedBatchIds.batch, true);
assert.ok(stage.innerHTML.includes("ic-hist-expanded-gallery"), "Batch images should expand inside masonry card");
assert.equal((stage.innerHTML.match(/data-hist-img-toggle="batch"/g) || []).length, 3,
  "Opening a batch must reveal all three images");

state.historyFilter = "article";
app.renderHistoryStage();
assert.ok(stage.innerHTML.includes('data-hist-id="cover_mode"'));
assert.ok(stage.innerHTML.includes('data-hist-id="cover_legacy"'));
assert.ok(!stage.innerHTML.includes('data-hist-id="batch"'));
assert.match(stage.innerHTML, /生图历史 · 9 张/, "Total count must be unchanged by a category filter");

const sampleForm = {
  id: "quick_form", creationSource: "quick", mode: "3:4", kind: "single",
  items: [{ imageUrl: "/form.webp", title: "一张表单图" }]
};
assert.equal(app.historyRecordCategory(sampleForm), "quick");
assert.equal(app.historyRecordCategory({ ...sampleForm, creationSource: "batch" }), "batch");
assert.equal(app.historyRecordCategory({ ...sampleForm, creationSource: "article" }), "article");
assert.equal(app.historyRecordCategory({ ...sampleForm, creationSource: "canvas" }), "canvas");
assert.equal(app.historyRecordCategory({ ...sampleForm, creationSource: "", ctrlId: "graph_ctrl" }), "other",
  "Unknown legacy form images must not be mislabelled as canvas just because they used an internal node");
state.generationHistory.push(sampleForm);
state.historyFilter = "quick";
app.renderHistoryStage();
assert.ok(stage.innerHTML.includes('data-hist-id="quick_form"'));
assert.ok(stage.innerHTML.includes('data-hist-open-mode="quick"'));
assert.ok(!stage.innerHTML.includes('data-hist-restore="quick_form"'),
  "Form-created images must not offer recovery into an unrelated canvas");
state.historyFilter = "canvas";
app.renderHistoryStage();
assert.ok(stage.innerHTML.includes('data-hist-restore="canvas"'));
state.historyFilter = "all";
assert.ok(styles.includes("--ic-library-max-width: none"), "History/workflow must not have a competing fixed width cap");
assert.ok(styles.includes("--ic-library-side-gap: var(--hw-page-gutter, 24px)"), "Library must inherit navigation page gutter");
const feedStyles = fs.readFileSync("demo/assets/mixed-feed.css", "utf8");
assert.match(styles, /\\.ic-hist-masonry-grid\\s*\\{[^}]*display:\\s*grid;[^}]*grid-template-columns:\\s*repeat\\(5, minmax\\(0, 1fr\\)\\)/s,
  "History must use five explicit grid tracks on wide screens, matching the homepage");
for (const [breakpoint, columns] of [[1400, 4], [1100, 3], [760, 2], [350, 1]]) {
  const track = columns === 1 ? "minmax(0, 1fr)" : "repeat(" + columns + ", minmax(0, 1fr))";
  assert.ok(styles.includes("@media (max-width: " + breakpoint + "px)"), "Missing history breakpoint " + breakpoint);
  assert.ok(styles.includes(".ic-hist-masonry-grid { grid-template-columns: " + track + ";"),
    "Missing history " + columns + " column layout");
  assert.ok(feedStyles.includes("@media (max-width: " + breakpoint + "px)"),
    "Homepage and history breakpoints must remain in sync: " + breakpoint);
}
assert.ok(feedStyles.includes("column-count: 5"), "Homepage desktop feed uses five columns");
assert.ok(!styles.includes("column-count: 3"),
  "Regression: multicol auto-balancing can stack two history cards in the first column");
// Workflow library: one shared top-level nav, no duplicate canvas/workflow bars.
assert.ok(studio.includes('id="studio-mode-workflows"'), "Workflow shortcut should be beside generation history");
assert.ok(studio.includes('id="studio-mode-history"'));
assert.ok(!studio.includes('id="tb-open-wflib"'), "Remove workflow button from canvas tab bar");
assert.ok(studio.includes('DOM.workbenchBar.style.display = CS.stageView === "canvas" ? "" : "none"'),
  "Hide canvas tabs on standalone workflow library");
const workflowStart = studio.indexOf("  function renderWorkflowsStage() {");
const workflowEnd = studio.indexOf("  /*", workflowStart + 20);
const workflow = studio.slice(workflowStart, workflowEnd > workflowStart ? workflowEnd : undefined);
for (const id of ['id="wf-search-inp"', 'id="wf-import-file-inp"', 'id="wf-saved-list-box"']) {
  assert.ok(workflow.includes(id), "Workflow page is missing " + id);
}
for (const id of ['id="wf-back-canvas"', 'id="wf-restore-presets"', 'id="wf-empty-go-canvas"']) {
  assert.ok(!workflow.includes(id), "Redundant workflow control still exists: " + id);
}
assert.ok(workflow.includes('class="ic-wf-minimal-tools"'));

const sharedShellStyle = [
  ".ic-history-stage .ic-history-topbar,",
  ".ic-workflows-stage .ic-wf-minimal-tools",
  ".ic-history-stage .ic-hist-page-inner,",
  ".ic-workflows-stage .ic-wf-page-inner",
  "--ic-library-max-width: none",
  "--ic-library-side-gap: var(--hw-page-gutter, 24px)"
];
for (const fragment of sharedShellStyle) {
  assert.ok(styles.includes(fragment), "Shared history/workflow alignment missing: " + fragment);
}
assert.ok(styles.includes(".ic-wf-card-grid") && styles.includes("grid-template-columns: repeat(3, minmax(0, 1fr))"),
  "Desktop workflow list needs three cards across");
assert.ok(styles.includes("grid-template-columns: repeat(2, minmax(0, 1fr))"),
  "Tablet workflow list needs two cards across");
assert.ok(styles.includes("grid-template-columns: minmax(0, 1fr)"),
  "Mobile workflow list needs a single card column");
assert.ok(studio.includes('id="studio-mode-canvas"') && studio.includes('>画布</button>'),
  "Global canvas button should be named 画布");
assert.ok(!studio.includes("高级画布"), "Studio UI must not keep the old canvas label");

const workflowStage = {
  style: {}, innerHTML: "",
  querySelector() { return null; },
  querySelectorAll() { return []; }
};
const workflowData = {
  stageView: "workflows", workflowQuery: "",
  savedWorkflows: [
    {
      id: "wf_1", title: "示范工作流", updatedAt: "今天", scenarioBadge: "海报",
      scenarioDesc: "可复用的创作节点", graph: {
        nodes: [{ type: "text_input" }, { type: "output_control" }], edges: [{ from: "a", to: "b" }]
      }
    },
    {
      id: "wf_2", title: "自定义工作流", updatedAt: "昨天",
      graph: { nodes: [{ type: "output_display" }], edges: [] }
    }
  ]
};
const wfSourceStart = studio.indexOf("  function renderWorkflowsStage() {");
const wfSourceEnd = studio.indexOf("  /* ======================== UNDO/REDO", wfSourceStart);
assert.ok(wfSourceStart >= 0 && wfSourceEnd > wfSourceStart);
const renderWorkflow = new Function("DOM", "CS", "esc", "ensureDefaultSavedWorkflows", "document",
  studio.slice(wfSourceStart, wfSourceEnd) + "\nreturn renderWorkflowsStage;")(
    { workflowsStage: workflowStage }, workflowData, (v) => String(v), () => {}, { activeElement: null }
  );
renderWorkflow();
assert.ok(workflowStage.innerHTML.includes('class="ic-wf-card-grid"'), "Workflow list must be a card grid");
assert.equal((workflowStage.innerHTML.match(/class="ic-wf-entry-card"/g) || []).length, 2);
for (const name of ["示范工作流", "自定义工作流"]) {
  assert.ok(workflowStage.innerHTML.includes(name), "Missing workflow card: " + name);
}
for (const action of ["data-wf-open", "data-wf-dl", "data-wf-rm"]) {
  assert.ok(workflowStage.innerHTML.includes(action), "Workflow cards must preserve action: " + action);
}
assert.ok(workflowStage.innerHTML.includes("2 个节点"), "Card should show node count");
assert.ok(workflowStage.innerHTML.includes("1 条连线"), "Card should show edge count");

console.log("Studio history and workflows: shared responsive navigation gutters, responsive cards and actions passed");
