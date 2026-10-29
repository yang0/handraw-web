"use strict";
// Executable VM tests for the unified article editor helpers.
// Loads the REAL helpers plus the REAL prompt engine; only persistence/nav/
// resolve side effects are stubbed so the key editor functions run for real.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const engineSrc = fs.readFileSync("demo/assets/studio-prompt-engine.js", "utf8");

// Two-space top-level function boundary; never brace-counts through strings.
function extract(name) {
  const start = studio.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, `function ${name} must exist in studio-app.js`);
  const end = studio.indexOf("\n  function ", start + 1);
  return studio.slice(start, end < 0 ? undefined : end);
}

function deepClone(v) {
  return JSON.parse(JSON.stringify(v));
}

function load(names, ctx) {
  for (const n of names) {
    vm.runInContext(extract(n), ctx, { filename: `studio-app.js#${n}` });
  }
}

function makeContext(seedArticles = []) {
  let counter = 0;
  const CS = {
    myArticles: deepClone(seedArticles),
    articleEditorDraft: null,
    activeArticleId: null,
    activePlanNodeId: null,
    articleSubView: "portal",
    activeTabId: null,
    graph: { blueprint: "single", nodes: [], edges: [] },
    tabs: [],
    previewTab: null,
    stageView: "canvas"
  };

  const buildCalls = [];
  let planBuilds = 0;
  const generation = { planBuilds: () => planBuilds };

  const ctx = {
    CS,
    App: { state: { loggedIn: true, credits: 100 } },
    Catalog: {
      resourceMap: new Map([
        ["FA-001", { id: "FA-001", kind: "style" }],
        ["IG-001", { id: "IG-001", kind: "layout" }]
      ])
    },
    window: {
      location: { href: "http://127.0.0.1:3080/studio/?entry=article" },
      history: {
        replaceState(_s, _t, p) {
          const u = new URL(p, ctx.window.location.href);
          ctx.window.location.href = u.href;
        }
      }
    },
    URLSearchParams,
    URL,
    encodeURIComponent,
    JSON,
    Math,
    Date,
    console,
    isArticleGenerating: () => false,
    markActiveTabDirty: () => {},
    formatArticleTimeLabel: (ms) => `t${ms % 1000}`,
    resolveArticleTarget: (articleId) => {
      const art = ctx.findArticleById(articleId);
      if (!art) return null;
      let planNode = null;
      let hostGraph = null;
      if (art.linkedPlanNodeId) {
        const activeNode = (CS.graph.nodes || []).find((n) => n.id === art.linkedPlanNodeId);
        if (activeNode) {
          hostGraph = CS.graph;
          planNode = activeNode;
        } else {
          for (const t of CS.tabs) {
            const node = (t.graph?.nodes || []).find((n) => n.id === art.linkedPlanNodeId);
            if (node) {
              hostGraph = t.graph;
              planNode = node;
              break;
            }
          }
        }
      }
      // Mirrors production resolveArticleTarget: detached articles get a
      // virtual plan node wrapping the article itself.
      if (!planNode) {
        planNode = { id: art.id, type: "article_plan", _isVirtualArticle: true, _articleRef: art, data: art };
      }
      return { art, planNode, hostGraph };
    },
    commitArticleTargetChanges: (target, { bumpTime } = {}) => {
      if (bumpTime && target.art) {
        target.art.updatedAtMs = Date.now();
      }
    }
  };

  vm.createContext(ctx);
  vm.runInContext(engineSrc, ctx, { filename: "studio-prompt-engine.js" });
  const E = ctx.window.HANDRAW_CANVAS_ENGINE;
  assert.ok(E && typeof E.createBlueprintGraph === "function", "engine must expose createBlueprintGraph");

  // Wrap the real engine's plan builder so we can count builds without faking it.
  const realBuild = E.buildArticlePlanData.bind(E);
  E.uid = (p) => `${p}${++counter}`;
  E.buildArticlePlanData = (...args) => {
    buildCalls.push(args[0]);
    planBuilds++;
    return realBuild(...args);
  };
  ctx.E = E;
  ctx.buildCalls = buildCalls;
  ctx.generation = generation;

  // Persistence and article-store plumbing.
  ctx.ensureMyArticlesInitialized = () => {
    if (!Array.isArray(CS.myArticles)) CS.myArticles = [];
  };
  ctx.getSortedMyArticles = () =>
    CS.myArticles.slice().sort((a, b) => (b.updatedAtMs || 0) - (a.updatedAtMs || 0));
  let persistCount = 0;
  ctx.persistMyArticles = () => { persistCount++; };
  ctx.persistCount = () => persistCount;
  ctx.syncAllTabsArticlesIntoStore = () => {};
  ctx.renderFullPreviewStage = () => {};

  load([
    "flushUnifiedArticleEditor",
    "makeBlankArticleDraft",
    "draftFromArticle",
    "findArticleById",
    "syncArticleEditorDraftToHistory",
    "openUnifiedArticleEditor",
    "planUnifiedArticleDraft"
  ], ctx);

  return ctx;
}

function seedArticle(id, over = {}) {
  return Object.assign(
    {
      id,
      articleTitle: `Title ${id}`,
      author: "",
      markdown: `# ${id}\n\noriginal body`,
      cards: [
        { id: "cover1", role: "cover", title: "Cover", imageUrl: "/img/a.webp", status: "ready", prompt: "cover prompt", promptCustomized: true, afterBlockIdx: 0 },
        { id: "body1", role: "body", title: "Section", section: "original body", afterBlockIdx: 1, imageUrl: "/img/b.webp", status: "ready" }
      ],
      status: "ready",
      createdAtMs: 1000,
      updatedAtMs: 1000,
      timeLabel: "t0",
      linkedTabId: null,
      linkedPlanNodeId: null,
      style1: "FA-001",
      layout: "IG-001",
      coverRatio: "2.35:1",
      inlineRatio: "4:3",
      runCount: 0
    },
    over
  );
}

// ============================ A. Text change syncs, no rebuild, cards kept
{
  const ctx = makeContext([seedArticle("A")]);
  const art = ctx.CS.myArticles[0];
  const cardsBefore = deepClone(art.cards);
  const draft = vm.runInContext("draftFromArticle(findArticleById('A'))", ctx);
  assert.deepEqual(draft.cards ?? null, null, "draftFromArticle does not carry cards");
  draft.markdown = "# A\n\nnew body text";
  const before = ctx.generation.planBuilds();
  vm.runInContext("syncArticleEditorDraftToHistory(__draft, { bumpTime: true })", Object.assign(ctx, { __draft: draft }));
  assert.equal(ctx.generation.planBuilds(), before, "text sync must not build a plan");
  assert.equal(ctx.buildCalls.length, 0, "buildArticlePlanData never called on text sync");
  assert.equal(art.markdown, "# A\n\nnew body text", "markdown overwritten in history");
  assert.deepEqual(art.cards, cardsBefore, "cards array preserved exactly (ids, images, custom prompt)");
  assert.ok(ctx.persistCount() >= 1, "sync persists to history");
}

// ============================ B. Opening A then B flushes A once, no bleed into B
{
  const ctx = makeContext([seedArticle("A"), seedArticle("B")]);
  const artA = vm.runInContext("findArticleById('A')", ctx);
  const artB = vm.runInContext("findArticleById('B')", ctx);

  const draftA = vm.runInContext("openUnifiedArticleEditor('A')", ctx);
  assert.equal(draftA.id, "A");
  assert.equal(artB.markdown, "# B\n\noriginal body", "B untouched by opening A");

  // Simulate an in-progress edit on A that has not been persisted yet.
  draftA.markdown = "# A\n\nedited while open";
  let flushCount = 0;
  ctx.CS.articleEditorFlush = () => {
    flushCount++;
    vm.runInContext("syncArticleEditorDraftToHistory(CS.articleEditorDraft, { bumpTime: true })", ctx);
  };

  const draftB = vm.runInContext("openUnifiedArticleEditor('B')", ctx);
  assert.equal(flushCount, 1, "exactly one flush before switching to B");
  assert.equal(ctx.CS.articleEditorFlush, null, "flush hook cleared after running");
  assert.equal(artA.markdown, "# A\n\nedited while open", "A saved before B opens");
  assert.equal(draftB.id, "B", "B draft opened");
  assert.equal(draftB.markdown, "# B\n\noriginal body", "B draft is its own content");
  assert.equal(artB.markdown, "# B\n\noriginal body", "B history not overwritten by A edits");
}

// ============================ C. New blank draft gets independent id, does not clobber A
{
  const ctx = makeContext([seedArticle("A")]);
  const artA = vm.runInContext("findArticleById('A')", ctx);
  const before = deepClone(artA);

  const blank = vm.runInContext("openUnifiedArticleEditor(null, { createNew: true })", ctx);
  assert.ok(blank.id && blank.id !== "A", "new draft has its own id");
  assert.equal(blank.isNewDraft, true);

  blank.title = "Fresh";
  blank.markdown = "# Fresh\n\nbody";
  vm.runInContext("syncArticleEditorDraftToHistory(CS.articleEditorDraft, { bumpTime: true })", ctx);

  assert.equal(ctx.CS.myArticles.length, 2, "new article appended, A kept");
  assert.deepEqual(artA, before, "existing article A unchanged by new draft");
  const created = vm.runInContext(`findArticleById(${JSON.stringify(blank.id)})`, ctx);
  assert.ok(created, "new article persisted under its own id");
  assert.equal(created.markdown, "# Fresh\n\nbody");
}

// ============================ D. Planning only touches the current target article
{
  const ctx = makeContext([seedArticle("A"), seedArticle("B")]);
  const artA = vm.runInContext("findArticleById('A')", ctx);
  const artB = vm.runInContext("findArticleById('B')", ctx);
  const artBBefore = deepClone(artB);
  const graphBefore = deepClone(ctx.CS.graph);

  const draftA = vm.runInContext("draftFromArticle(findArticleById('A'))", ctx);
  draftA.markdown = "# A\n\nplanned body";
  const planNode = vm.runInContext("planUnifiedArticleDraft(__draft)", Object.assign(ctx, { __draft: draftA }));
  assert.ok(planNode, "plan produced for target A");
  assert.equal(ctx.buildCalls.length, 1, "exactly one plan build for the target");
  assert.equal(artA.markdown, "# A\n\nplanned body", "target A updated");
  assert.deepEqual(artB, artBBefore, "other article B untouched");
  assert.deepEqual(ctx.CS.graph, graphBefore, "CS.graph unchanged for detached target");
  assert.equal(planNode.data.articleTitle, "Title A", "plan reflects target only");
}

// ============================ E. Replan same sections keeps images + custom prompts
{
  const ctx = makeContext([seedArticle("A")]);
  const artA = vm.runInContext("findArticleById('A')", ctx);
  // Real engine roles: cover + inline. Inline section title must match the
  // actual ## heading the engine anchors on.
  const md = "# A\n\nintro\n\n## Section One\n\nbody of section one\n\n## Section Two\n\nbody of section two";
  const E = ctx.E;
  const catalog = ctx.Catalog;
  const graph = E.createBlueprintGraph("article", catalog, {});
  const ctrlNode = graph.nodes.find((n) => n && n.type === "output_control");
  const planData = E.buildArticlePlanData(md, ctrlNode, graph, catalog);
  const coverInit = planData.cards.find((c) => c.role === "cover");
  const inlineInit = planData.cards.find((c) => c.role === "inline");
  assert.ok(coverInit && inlineInit, "engine produces cover and inline cards");
  coverInit.id = "cover-custom";
  coverInit.imageUrl = "/img/a.webp";
  coverInit.prompt = "cover prompt";
  coverInit.promptCustomized = true;
  coverInit.status = "done";
  inlineInit.id = "inline-custom";
  inlineInit.imageUrl = "/img/b.webp";
  inlineInit.prompt = "inline prompt";
  inlineInit.promptCustomized = true;
  inlineInit.status = "done";
  const initialCards = deepClone(planData.cards);
  artA.markdown = md;
  artA.cards = deepClone(initialCards);
  delete artA.linkedPlanNodeId;

  const buildsAfterInit = ctx.buildCalls.length;

  const draft = vm.runInContext("draftFromArticle(findArticleById('A'))", ctx);
  vm.runInContext("planUnifiedArticleDraft(__draft)", Object.assign(ctx, { __draft: draft }));

  const replanned = artA.cards;
  assert.ok(Array.isArray(replanned) && replanned.length > 0, "replan produced cards");
  assert.equal(ctx.buildCalls.length - buildsAfterInit, 1, "replan added exactly one plan build");
  const coverAfter = replanned.find((c) => c.role === "cover");
  assert.ok(coverAfter, "cover card survives replan");
  assert.equal(coverAfter.id, "cover-custom", "cover id preserved");
  assert.equal(coverAfter.imageUrl, "/img/a.webp", "cover image preserved");
  assert.equal(coverAfter.promptCustomized, true, "custom-prompt flag preserved");
  assert.equal(coverAfter.prompt, "cover prompt", "custom prompt preserved");
  assert.equal(coverAfter.status, "done", "card status preserved");

  const inlineAfter = replanned.find((c) => c.role === "inline");
  assert.ok(inlineAfter, "inline card survives replan");
  assert.equal(inlineAfter.id, "inline-custom", "inline id preserved");
  assert.equal(inlineAfter.imageUrl, "/img/b.webp", "inline image preserved");
  assert.equal(inlineAfter.promptCustomized, true, "inline custom-prompt flag preserved");
  assert.equal(inlineAfter.prompt, "inline prompt", "inline custom prompt preserved");

  const coverCount = replanned.filter((c) => c.role === "cover").length;
  const ids = replanned.map((c) => c.id);
  assert.equal(coverCount, 1, "exactly one cover card");
  assert.equal(new Set(ids).size, ids.length, "no duplicate card ids (one-to-one)");
}

// ============================ F. Helper calls never auto-generate images
{
  const ctx = makeContext([seedArticle("A")]);
  const draft = vm.runInContext("openUnifiedArticleEditor('A')", ctx);
  draft.markdown = "# A\n\nchanged";
  vm.runInContext("syncArticleEditorDraftToHistory(CS.articleEditorDraft)", ctx);
  vm.runInContext("openUnifiedArticleEditor(null, { createNew: true })", ctx);
  vm.runInContext("openUnifiedArticleEditor('A')", ctx);
  // No image generation path is wired in; builds only happen on explicit plan.
  assert.equal(ctx.generation.planBuilds(), 0, "open/sync never build a plan");
  assert.equal(ctx.buildCalls.length, 0, "engine plan builder never invoked implicitly");
}

console.log("Article unified editor: text sync preserves cards, flush-on-switch, independent new draft, targeted planning, replan preservation, no auto generation passed");
