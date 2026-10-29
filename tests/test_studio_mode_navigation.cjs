// FILE: tests/test_studio_mode_navigation.cjs
"use strict";
// Executable VM tests for real navigation state transitions (not string mirrors):
// pressed states incl. history, workbench markup, history keeps canvas, canvas<->article
// payload preservation, createNewArticlePlan isolation, scope-guarded return tab, no auto generation.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");

function extract(source, name) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, `function ${name} must exist in studio-app.js`);
  const end = source.indexOf("\n  function ", start + 1);
  return source.slice(start, end < 0 ? undefined : end);
}

function deepClone(v) {
  return JSON.parse(JSON.stringify(v));
}

function makeHarness() {
  let counter = 0;
  const CS = {
    engineMode: "demo",
    serverCfg: {},
    tabs: [],
    activeTabId: null,
    graph: { blueprint: "single", nodes: [], edges: [], selectedIds: [] },
    stageView: "canvas",
    vx: 0,
    vy: 0,
    vk: 1,
    undoStack: [],
    redoStack: [],
    generationHistory: [],
    canvasTheme: "paper",
    gridMode: "dots",
    articleSubView: "portal",
    articleReturnTab: undefined
  };
  const App = { state: { loggedIn: true, credits: 100 } };
  const E = {
    uid: (p) => `${p}${++counter}`,
    createBlueprintGraph: (bp) => {
      const nodes = [];
      if (bp === "article") {
        nodes.push({ id: `n${++counter}`, type: "output_control", data: { mode: "article-illust" }, x: 0, y: 0 });
      } else {
        nodes.push({ id: `n${++counter}`, type: "skill_params", data: { style1: "FA-001" }, x: 0, y: 0 });
      }
      return { blueprint: bp, nodes, edges: [], selectedIds: [] };
    },
    makeSkillParamsNode: (x, y, d) => ({ id: `s${++counter}`, type: "skill_params", data: { ...d }, x, y }),
    makeTextInputNode: (x, y, d) => ({ id: `t${++counter}`, type: "text_input", data: { ...d }, x, y }),
    makeOutputControlNode: (x, y, d) => ({ id: `c${++counter}`, type: "output_control", data: { ...d }, x, y }),
    makeArticlePlanNode: (x, y, d) => ({ id: `p${++counter}`, type: "article_plan", data: { ...d }, x, y }),
    buildArticlePlanData: (md) => ({
      articleTitle: String(md || "").split("\n")[0].replace(/^#\s*/, ""),
      markdown: md,
      cards: [{ id: "card1" }]
    }),
    DEFAULT_STARTER_ARTICLE_MD: "# Starter\n\nbody"
  };
  const window = {
    location: { search: "", href: "http://127.0.0.1:3080/studio/" },
    history: {
      replaceState: (_s, _t, p) => {
        window.location.href = "http://127.0.0.1:3080/studio/" + String(p || "");
        window.location.search = String(p || "").includes("?") ? String(p).slice(String(p).indexOf("?")) : "";
      },
      pushState() {}
    },
    HANDRAW_MOCK: {}
  };
  const generationCalls = { n: 0 };
  const ctx = {
    CS,
    App,
    E,
    window,
    activeCacheScope: "scope-a",
    Catalog: { resourceMap: new Map() },
    DOM: {},
    URLSearchParams,
    URL,
    encodeURIComponent,
    JSON,
    console,
    Math,
    requestAnimationFrame: () => {},
    setTimeout: () => {},
    renderTopAndBottomDocks: () => {},
    renderWorkbenchBar: () => {},
    renderFullPreviewStage: () => {},
    renderHistoryStage: () => {},
    renderWorkflowsStage: () => {},
    renderQuickStart: () => {},
    renderCanvasToolstrip: () => {},
    fullRenderCanvas: () => {},
    fitView: () => {},
    updateGridBackground: () => {},
    scrollActiveTabIntoView: () => {},
    savePrefs: () => {},
    persistOpenTabs: () => {},
    ensureDefaultSavedWorkflows: () => {},
    ensureGenerationHistoryInitialized: () => {},
    syncAllTabsArticlesIntoStore: () => {},
    openMyArticlesPage: () => {},
    openContextMenu: () => {},
    openAllTabsPopover: () => {},
    updateTabScrollButtons: () => {},
    closeWorkflowTab: () => {},
    esc: (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;"),
    toast: () => {},
    setQuickField: () => {},
    runOutputControlNode: () => { generationCalls.n++; },
    markActiveTabDirty: () => {},
    normalizeGraphSchema: (g) => g,
    cloneGraph: (g) => deepClone(g),
    ensureEdge: () => {},
    getDownstreamArticlePlanNode: () => null,
    syncArticlePlanDisplayNodes: () => {},
    syncPlanNodeToMyArticles: () => ({ id: "art1" }),
    snapVal: (v) => v,
    generationCalls
  };
  vm.createContext(ctx);
  // Load the REAL flush helper into every context so openHistoryPage and
  // other blocks can call it without per-block loadNavHelpers.
  ctx.ensureMyArticlesInitialized = () => {
    if (!Array.isArray(ctx.CS.myArticles)) ctx.CS.myArticles = [];
  };
  ctx.getSortedMyArticles = () => (ctx.CS.myArticles || []).slice();
  ctx.persistMyArticles = () => {};
  ctx.renderFullPreviewStage = () => {};
  vm.runInContext(extract(studio, "flushUnifiedArticleEditor"), ctx);
  return ctx;
}

function loadNavHelpers(ctx) {
  const names = [
    "isArticleBlueprint",
    "isArticleGraph",
    "isArticleTab",
    "currentCacheScopeKey",
    "findArticleWorkspaceTab",
    "ensureArticleWorkspace",
    "pickReturnCanvasTab",
    "readScopedReturnTab",
    "writeScopedReturnTab",
    "switchIntoArticleMode",
    "switchToCanvasFromArticle"
  ];
  for (const n of names) vm.runInContext(extract(studio, n), ctx);
  vm.runInContext(extract(studio, "syncCurrentTabSnapshot"), ctx);
  vm.runInContext(extract(studio, "activateWorkflowTab"), ctx);
  // Unified editor helpers pulled in by switchIntoArticleMode/openUnifiedArticleEditor.
  ctx.ensureMyArticlesInitialized = () => {
    if (!Array.isArray(ctx.CS.myArticles)) ctx.CS.myArticles = [];
  };
  ctx.getSortedMyArticles = () => (ctx.CS.myArticles || []).slice();
  ctx.persistMyArticles = () => {};
  ctx.renderFullPreviewStage = () => {};
  for (const n of ["flushUnifiedArticleEditor", "makeBlankArticleDraft", "draftFromArticle", "findArticleById", "openUnifiedArticleEditor"]) {
    vm.runInContext(extract(studio, n), ctx);
  }
}

function installTabFactories(ctx) {
  ctx.createWorkflowTab = (opts) => {
    const tab = {
      id: `wf-${opts.blueprint || "single"}-${Math.random().toString(36).slice(2, 8)}`,
      title: opts.title || "未命名工作流",
      blueprint: opts.blueprint || "single",
      graph: opts.graph || { blueprint: opts.blueprint || "single", nodes: [], edges: [], selectedIds: [] },
      vx: 0,
      vy: 0,
      vk: 1,
      undoStack: [],
      redoStack: []
    };
    ctx.CS.tabs.push(tab);
    if (opts.makeActive !== false) ctx.activateWorkflowTab(tab.id);
    return tab;
  };
}

function fakeButton(id) {
  const b = {
    tagName: "BUTTON",
    _onclick: null,
    _attrs: { id },
    addEventListener: () => {},
    closest: () => null,
    getAttribute: (k) => b._attrs[k] || null,
    setAttribute: (k, v) => { b._attrs[k] = v; },
    getBoundingClientRect: () => ({ left: 0, bottom: 0 }),
    scrollBy: () => {},
    scrollLeft: 0,
    classList: { toggle: () => {}, add: () => {}, remove: () => {} }
  };
  Object.defineProperty(b, "onclick", { get: () => b._onclick, set: (fn) => { b._onclick = fn; } });
  return b;
}

// ============================ 1. Mode pressed states incl. history
{
  const ctx = makeHarness();
  ctx.CS.generationHistory = [{ id: "g1" }, { id: "g2" }, { id: "g3" }];
  ctx.DOM.entryBar = { hidden: true, innerHTML: "", querySelector: () => null };
  vm.runInContext(extract(studio, "renderCreationModeBar"), ctx);

  const cases = [
    ["quick", "quick"],
    ["canvas", "canvas"],
    ["preview", "article"],
    ["history", "history"]
  ];
  for (const [stage, pressed] of cases) {
    ctx.CS.stageView = stage;
    vm.runInContext("renderCreationModeBar()", ctx);
    const html = ctx.DOM.entryBar.innerHTML;
    assert.equal(ctx.DOM.entryBar.hidden, false, `entry bar visible at ${stage}`);
    for (const id of ["studio-mode-quick", "studio-mode-canvas", "studio-mode-article", "studio-mode-history"]) {
      assert.ok(html.includes(`id="${id}"`), `${id} present at ${stage}`);
    }
    assert.match(html, new RegExp(`id="studio-mode-quick"[^>]*aria-pressed="${pressed === "quick"}"`), `quick pressed=${pressed === "quick"} at ${stage}`);
    assert.match(html, new RegExp(`id="studio-mode-canvas"[^>]*aria-pressed="${pressed === "canvas"}"`), `canvas pressed at ${stage}`);
    assert.match(html, new RegExp(`id="studio-mode-article"[^>]*aria-pressed="${pressed === "article"}"`), `article pressed at ${stage}`);
    assert.match(html, new RegExp(`id="studio-mode-history"[^>]*aria-pressed="${pressed === "history"}"`), `history pressed at ${stage}`);
    assert.match(html, /生图历史\(3\)/, `history count=3 at ${stage}`);
    const histIdx = html.indexOf('id="studio-mode-history"');
    const artIdx = html.indexOf('id="studio-mode-article"');
    assert.ok(histIdx > artIdx, "history button rightmost in mode bar markup");
  }

  const buttons = {};
  for (const id of ["#studio-mode-quick", "#studio-mode-canvas", "#studio-mode-article", "#studio-mode-history"]) {
    buttons[id] = fakeButton(id.slice(1));
  }
  ctx.DOM.entryBar = { hidden: true, innerHTML: "", querySelector: (k) => buttons[k] || null };
  let historyCalls = 0;
  ctx.openHistoryPage = () => { historyCalls++; };
  vm.runInContext("renderCreationModeBar()", ctx);
  buttons["#studio-mode-history"].onclick();
  assert.equal(historyCalls, 1, "history button click calls openHistoryPage");
  assert.equal(ctx.generationCalls.n, 0, "history click triggers no generation");
}

// ============================ 2. Workbench markup: moved workflow, no nested history
{
  const ctx = makeHarness();
  ctx.CS.tabs = [
    { id: "t1", title: "Canvas", blueprint: "single", graph: { blueprint: "single", nodes: [], edges: [] } },
    { id: "t2", title: "Loop", blueprint: "loop_100", graph: { blueprint: "loop_100", nodes: [], edges: [] } }
  ];
  ctx.CS.activeTabId = "t1";
  ctx.CS.graph = ctx.CS.tabs[0].graph;
  ctx.CS.stageView = "canvas";

  const nodes = {};
  const mk = (id) => { nodes[id] = fakeButton(id); return nodes[id]; };
  mk("#tb-new-wf");
  mk("#tb-all-tabs");
  mk("#tb-open-wflib");
  mk("#tb-theme-toggle");
  mk("#tb-grid-toggle");
  const bar = { innerHTML: "", querySelector: (k) => nodes[k] || null, querySelectorAll: () => [] };
  ctx.DOM.workbenchBar = bar;

  let workflowCalls = 0;
  ctx.openWorkflowsPage = () => { workflowCalls++; };
  ctx.openHistoryPage = () => { throw new Error("history handler must not be bound in workbench"); };
  vm.runInContext(extract(studio, "renderWorkbenchBar"), ctx);
  vm.runInContext("renderWorkbenchBar()", ctx);

  const html = bar.innerHTML;
  const pinned = html.match(/<div class="ic-tabs-pinned">([\s\S]*?)<\/div>/);
  assert.ok(pinned, "ic-tabs-pinned group present");
  const ids = [...pinned[1].matchAll(/id="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(ids, ["tb-new-wf", "tb-all-tabs", "tb-open-wflib"], "workflow button immediately after all-tabs inside pinned group");

  const tools = html.match(/<div class="ic-workbench-tools">([\s\S]*?)<\/div>/);
  assert.ok(tools, "tools group present");
  assert.doesNotMatch(tools[1], /id="tb-open-wflib"/, "workflow not in tools");
  assert.doesNotMatch(tools[1], /id="tb-open-hist"/, "no history button in workbench tools");
  assert.doesNotMatch(tools[1], /id="tb-view-preview"/, "no article-mode button in workbench tools");
  assert.equal((html.match(/id="tb-open-wflib"/g) || []).length, 1, "exactly one workflow button");
  assert.equal((html.match(/id="tb-open-hist"/g) || []).length, 0, "no workflow-toolbar history button");

  nodes["#tb-open-wflib"].onclick({ stopPropagation() {} });
  assert.equal(workflowCalls, 1, "workflow button click opens workflows page");
}

// ============================ 3. History preserves canvas; no generation
{
  const ctx = makeHarness();
  const canvasGraph = {
    blueprint: "single",
    nodes: [
      { id: "n1", type: "skill_params", data: { style1: "FA-007" } },
      { id: "n2", type: "text_input", data: { text: "payload" } }
    ],
    edges: [{ id: "e1", from: "n1", to: "n2" }]
  };
  ctx.CS.tabs = [{ id: "cv1", title: "Canvas", blueprint: "single", graph: canvasGraph, vx: 10, vy: 20, vk: 0.5 }];
  ctx.CS.activeTabId = "cv1";
  ctx.CS.graph = canvasGraph;
  ctx.CS.stageView = "canvas";
  const before = JSON.stringify(canvasGraph);

  vm.runInContext(extract(studio, "openHistoryPage"), ctx);
  vm.runInContext("openHistoryPage()", ctx);

  assert.equal(ctx.CS.stageView, "history");
  assert.equal(ctx.CS.activeTabId, "cv1", "active canvas tab unchanged by history");
  assert.equal(JSON.stringify(ctx.CS.graph), before, "canvas graph identical after opening history");
  assert.equal(ctx.generationCalls.n, 0, "opening history triggers no generation");
}

// ============================ 4. Canvas -> article -> canvas preserves payload exactly
{
  const ctx = makeHarness();
  installTabFactories(ctx);
  ctx.isArticleGraph = undefined;
  loadNavHelpers(ctx);

  const canvasGraph = {
    blueprint: "single",
    nodes: [
      { id: "n1", type: "skill_params", data: { style1: "FA-007" } },
      { id: "n2", type: "text_input", data: { text: "hello" } },
      { id: "n3", type: "output_control", data: { mode: "pure-image", count: 4 } }
    ],
    edges: [{ id: "e1", from: "n1", to: "n3" }, { id: "e2", from: "n2", to: "n3" }]
  };
  const canvasTab = { id: "cv-real", title: "Canvas", blueprint: "single", graph: deepClone(canvasGraph), vx: 10, vy: 20, vk: 0.5 };
  ctx.CS.tabs.push(canvasTab);
  ctx.CS.activeTabId = canvasTab.id;
  ctx.CS.graph = deepClone(canvasGraph);
  const before = JSON.stringify(canvasGraph);

  vm.runInContext("switchIntoArticleMode()", ctx);
  assert.equal(ctx.CS.stageView, "preview");
  assert.ok(ctx.CS.articleReturnTab && typeof ctx.CS.articleReturnTab === "object", "return key is object {scope,id}");
  assert.equal(ctx.CS.articleReturnTab.id, "cv-real", "return key records exact canvas tab");
  assert.equal(ctx.CS.articleReturnTab.scope, "scope-a", "return key scope matches activeCacheScope");
  assert.ok(ctx.CS.tabs.some((t) => t.blueprint === "article"), "article workspace tab created");
  assert.equal(JSON.stringify(canvasTab.graph), before, "canvas graph not mutated by entering article mode");
  assert.equal(ctx.generationCalls.n, 0, "entering article mode triggers no generation");

  vm.runInContext("switchToCanvasFromArticle()", ctx);
  assert.equal(ctx.CS.stageView, "canvas");
  assert.equal(ctx.CS.activeTabId, "cv-real", "restored exact original canvas tab");
  assert.equal(JSON.stringify(ctx.CS.graph), before, "canvas node payload preserved exactly");
  assert.equal(ctx.CS.articleReturnTab, undefined, "return key cleared after restore");
}

// ============================ 5. createNewArticlePlan does not modify original canvas
{
  const ctx = makeHarness();
  installTabFactories(ctx);
  loadNavHelpers(ctx);

  const canvasGraph = {
    blueprint: "single",
    nodes: [{ id: "n1", type: "skill_params", data: { style1: "FA-001" } }],
    edges: []
  };
  const canvasTab = { id: "cv-src", title: "Canvas", blueprint: "single", graph: deepClone(canvasGraph), vx: 0, vy: 0, vk: 1 };
  ctx.CS.tabs.push(canvasTab);
  ctx.CS.activeTabId = canvasTab.id;
  ctx.CS.graph = deepClone(canvasGraph);
  const before = JSON.stringify(canvasGraph);

  vm.runInContext(extract(studio, "createNewArticlePlan"), ctx);
  vm.runInContext('createNewArticlePlan({ title: "Test article", markdown: "# Test\\n\\nbody" })', ctx);

  assert.equal(JSON.stringify(canvasTab.graph), before, "original canvas graph untouched by createNewArticlePlan");
  const artTab = ctx.CS.tabs.find((t) => t.blueprint === "article");
  assert.ok(artTab, "article workspace tab exists");
  assert.ok(Array.isArray(artTab.graph.nodes) && artTab.graph.nodes.some((n) => n.type === "article_plan"), "article_plan lives in article tab, not canvas");
  assert.equal(ctx.generationCalls.n, 0, "createNewArticlePlan does not auto-generate charged work");
}

// ============================ 6. Scope-guarded return tab
{
  const ctx = makeHarness();
  installTabFactories(ctx);
  loadNavHelpers(ctx);
  const isArticle = (t) => t.blueprint === "article";

  const cv = { id: "cv1", title: "Canvas", blueprint: "single", graph: { blueprint: "single", nodes: [], edges: [] } };
  const art = { id: "art1", title: "Article", blueprint: "article", graph: { blueprint: "article", nodes: [], edges: [] } };
  ctx.CS.tabs = [cv, art];
  ctx.CS.activeTabId = "art1";
  ctx.CS.graph = art.graph;

  ctx.CS.articleReturnTab = { scope: "scope-b", id: "cv1" };
  vm.runInContext("switchToCanvasFromArticle()", ctx);
  assert.notEqual(ctx.CS.stageView, "preview", "left article mode even with stale key");
  const chosen = ctx.CS.tabs.find((t) => t.id === ctx.CS.activeTabId);
  assert.ok(chosen && !isArticle(chosen), "chosen tab is non-article");

  ctx.CS.activeTabId = "art1";
  ctx.CS.graph = art.graph;
  ctx.CS.articleReturnTab = { scope: "scope-a", id: "cv1" };
  vm.runInContext("switchToCanvasFromArticle()", ctx);
  assert.equal(ctx.CS.activeTabId, "cv1", "matching-scope return key restored exactly");
  assert.equal(ctx.CS.articleReturnTab, undefined, "key cleared");
}

// ============================ 7. Legacy article activation remembers prior canvas
{
  const ctx = makeHarness();
  loadNavHelpers(ctx);

  const canvasTab = { id: "cv-legacy", title: "Canvas", blueprint: "single", graph: { blueprint: "single", nodes: [], edges: [] }, vx: 0, vy: 0, vk: 1 };
  // legacy article tab: blueprint single, but article-illust output node
  const legacyArticleGraph = {
    blueprint: "single",
    nodes: [{ id: "a1", type: "output_control", data: { mode: "article-illust" } }],
    edges: []
  };
  const legacyArticleTab = { id: "art-legacy", title: "Legacy", blueprint: "single", graph: legacyArticleGraph, vx: 0, vy: 0, vk: 1 };
  ctx.CS.tabs = [canvasTab, legacyArticleTab];
  ctx.CS.activeTabId = "cv-legacy";
  ctx.CS.graph = canvasTab.graph;
  ctx.CS.stageView = "canvas";
  ctx.CS.articleReturnTab = undefined;

  vm.runInContext('activateWorkflowTab("art-legacy", { switchToCanvas: true })', ctx);
  assert.equal(ctx.CS.stageView, "preview", "legacy article activation enters preview");
  assert.ok(ctx.CS.articleReturnTab && typeof ctx.CS.articleReturnTab === "object", "return key is object {scope,id}");
  assert.equal(ctx.CS.articleReturnTab.id, "cv-legacy", "prior canvas id remembered on legacy article activation");
  assert.equal(ctx.CS.articleReturnTab.scope, "scope-a", "return key scope matches activeCacheScope");

  vm.runInContext("switchToCanvasFromArticle()", ctx);
  assert.equal(ctx.CS.stageView, "canvas", "returned to canvas");
  assert.equal(ctx.CS.activeTabId, "cv-legacy", "restored prior canvas tab after history");
  assert.equal(ctx.CS.articleReturnTab, undefined, "return key cleared after restore");
}

console.log("Studio mode navigation: pressed states, workbench markup, history preservation, canvas<->article payload, article-plan isolation, scope guard, legacy article return passed");
