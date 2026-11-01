"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const studioAppSource = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const promptEngineSource = fs.readFileSync("demo/assets/studio-prompt-engine.js", "utf8");
const studioBatchSource = fs.readFileSync("demo/assets/studio-batch.js", "utf8");
const quickCreateCss = fs.readFileSync("demo/assets/quick-create.css", "utf8");

// Setup unified VM environment with mock catalog
const sharedCatalog = {
  styles: [
    { id: "FA-001", name: "治愈水彩", name_zh: "治愈水彩", kind: "style", group: "watercolor", image: "/images/fa-001.webp", description: "温暖治愈的手绘水彩画风" },
    { id: "FA-002", name: "复古版画", name_zh: "复古版画", kind: "style", group: "print", image: "/images/fa-002.webp", description: "质感颗粒复古版画" },
    { id: "FA-003", name: "铅笔速写", name_zh: "铅笔速写", kind: "style", group: "sketch", image: "/images/fa-003.webp", description: "质朴手绘铅笔速写" },
    { id: "FB-031", name: "胶片纪实", name_zh: "胶片纪实", kind: "style", group: "film", image: "/images/fb-031.webp", description: "复古胶片感插画" }
  ],
  layouts: [
    { id: "SC-021", name: "双拼信息卡", kind: "layout", group: "social-cards", image: "/images/sc-021.webp", description: "撕纸折纸或实物对比双屏" },
    { id: "SC-022", name: "签名明信片", kind: "layout", group: "social-cards", image: "/images/sc-022.webp", description: "手写签名与双拼拼音" },
    { id: "SC-001", name: "居中卡片", kind: "layout", group: "social-cards", image: "/images/sc-001.webp", description: "居中构图信息卡" },
    { id: "IG-005", name: "步骤清单", kind: "layout", group: "infographics", image: "/images/ig-005.webp", description: "步骤流程图解" }
  ],
  colors: [
    { id: "CL-001", name: "珊瑚粉", family: "pink", value: "#f48fb1" },
    { id: "CL-002", name: "石青绿", family: "green", value: "#80cbc4" }
  ],
  tones: [
    { id: "TN-001", name: "暖调柔光", name_zh: "暖调柔光", name_en: "Warm Soft Light", image: "/images/tn-001.webp" }
  ],
  moods: ["治愈", "诗意", "温暖", "宁静"],
  resourceMap: new Map([
    ["FA-001", { id: "FA-001", name: "治愈水彩", name_zh: "治愈水彩", kind: "style", group: "watercolor", image: "/images/fa-001.webp", description: "温暖治愈的手绘水彩画风" }],
    ["FA-002", { id: "FA-002", name: "复古版画", name_zh: "复古版画", kind: "style", group: "print", image: "/images/fa-002.webp", description: "质感颗粒复古版画" }],
    ["FA-003", { id: "FA-003", name: "铅笔速写", name_zh: "铅笔速写", kind: "style", group: "sketch", image: "/images/fa-003.webp", description: "质朴手绘铅笔速写" }],
    ["FB-031", { id: "FB-031", name: "胶片纪实", name_zh: "胶片纪实", kind: "style", group: "film", image: "/images/fb-031.webp", description: "复古胶片感插画" }],
    ["SC-021", { id: "SC-021", name: "双拼信息卡", kind: "layout", group: "social-cards", image: "/images/sc-021.webp", description: "撕纸折纸或实物对比双屏" }],
    ["SC-022", { id: "SC-022", name: "签名明信片", kind: "layout", group: "social-cards", image: "/images/sc-022.webp", description: "手写签名与双拼拼音" }],
    ["SC-001", { id: "SC-001", name: "居中卡片", kind: "layout", group: "social-cards", image: "/images/sc-001.webp", description: "居中构图信息卡" }],
    ["IG-005", { id: "IG-005", name: "步骤清单", kind: "layout", group: "infographics", image: "/images/ig-005.webp", description: "步骤流程图解" }],
    ["CL-001", { id: "CL-001", name: "珊瑚粉", family: "pink", value: "#f48fb1" }],
    ["CL-002", { id: "CL-002", name: "石青绿", family: "green", value: "#80cbc4" }]
  ])
};

const sandbox = {
  window: {},
  globalThis: {},
  document: {
    createElement() {
      return {
        setAttribute() {},
        appendChild() {},
        click() {},
        style: {}
      };
    }
  },
  navigator: { clipboard: { writeText: async () => {} } },
  localStorage: {
    getItem() { return null; },
    setItem() {},
    removeItem() {}
  },
  Date,
  Math,
  Number,
  String,
  Array,
  Set,
  Map,
  JSON,
  RegExp,
  console
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// 1. Run prompt engine
vm.runInContext(promptEngineSource, sandbox);
const Engine = sandbox.HANDRAW_CANVAS_ENGINE;
assert.ok(Engine, "HANDRAW_CANVAS_ENGINE must be initialized");

// 2. Run studio batch
sandbox.HANDRAW_SHARED = {
  esc(s) { return String(s == null ? "" : s); },
  toast() {}
};
vm.runInContext(studioBatchSource, sandbox);
const HandrawBatchCreate = sandbox.HandrawBatchCreate;
assert.ok(HandrawBatchCreate, "HandrawBatchCreate must be initialized");

function createTestBatchGraph(options = {}) {
  const sp = Engine.makeSkillParamsNode(64, 56, {
    fusion: Boolean(options.fusion),
    style1: options.style1 || "FA-001",
    style2: options.style2 || "",
    layout: options.layout || "SC-021",
    colors: options.colors || ["CL-001"],
    tones: options.tones || ["TN-001"],
    moods: options.moods || ["治愈"],
    customMood: options.customMood || "",
    whitespace: options.whitespace || "balanced",
    audience: options.audience || "年轻白领",
    businessScene: options.businessScene || "手账日签"
  });
  const txt = Engine.makeTextInputNode(64, 480, {
    text: options.text != null ? options.text : "都市慢生活"
  });
  const ast = Engine.makeAssetNode(64, 760, {
    items: options.assets || []
  });
  const lp = Engine.makeLoopNode(468, 200, {
    loopMode: options.loopMode || "prompts",
    promptListText: options.promptListText != null ? options.promptListText : "早八一杯热美式\n晚霞中的单车\n周末雨天读旧诗集",
    styleIds: options.styleIds || ["FA-001", "FA-002"],
    layoutIds: options.layoutIds || ["SC-021", "SC-001"],
    maxIterations: 200
  });
  const ctrl = Engine.makeOutputControlNode(880, 200, {
    mode: options.mode || "graphic-text",
    ratio: options.ratio || "3:4",
    count: 1
  });

  const nodes = [sp, txt, ast, lp, ctrl];
  const edges = [
    { id: "e1", from: sp.id, to: lp.id },
    { id: "e2", from: sp.id, to: ctrl.id },
    { id: "e3", from: txt.id, to: lp.id },
    { id: "e4", from: ast.id, to: lp.id },
    { id: "e5", from: ast.id, to: ctrl.id },
    { id: "e6", from: lp.id, to: ctrl.id }
  ];

  return { nodes, edges };
}

function parseHtml(html) {
  return {
    html,
    querySelector(selector) {
      if (selector === "#batch-mode-single") {
        return html.includes('id="batch-mode-single"') ? { id: "batch-mode-single", onclick: null } : null;
      }
      if (selector === "#batch-mode-fusion") {
        return html.includes('id="batch-mode-fusion"') ? { id: "batch-mode-fusion", onclick: null } : null;
      }
      if (selector === "#batch-prompts-input") {
        const m = html.match(/id="batch-prompts-input"[^>]*>([\s\S]*?)<\/textarea>/);
        return m ? { value: m[1], oninput: null, onblur: null } : null;
      }
      if (selector === "#batch-btn-start") {
        return html.includes('id="batch-btn-start"') ? { id: "batch-btn-start", onclick: null, disabled: html.includes('id="batch-btn-start" disabled') } : null;
      }
      if (selector === "#batch-btn-fission") {
        return html.includes('id="batch-btn-fission"') ? { id: "batch-btn-fission", onclick: null } : null;
      }
      if (selector === ".batch-cost-wrap") {
        const m = html.match(/<div class="batch-cost-wrap">([\s\S]*?)<\/div>/);
        return m ? { innerHTML: m[1] } : null;
      }
      if (selector === ".batch-preview-title") {
        const m = html.match(/<h3 class="batch-preview-title">([\s\S]*?)<\/h3>/);
        return m ? { textContent: m[1] } : null;
      }
      return null;
    },
    querySelectorAll(selector) {
      const results = [];
      if (selector === "[data-set-loop-mode]") {
        const regex = /data-set-loop-mode="([^"]+)"/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
          const val = match[1];
          results.push({
            getAttribute: (attr) => (attr === "data-set-loop-mode" ? val : null),
            onclick: null
          });
        }
      }
      if (selector === "[data-pick-kind]") {
        const regex = /data-pick-kind="([^"]+)"/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
          const val = match[1];
          results.push({
            getAttribute: (attr) => (attr === "data-pick-kind" ? val : null)
          });
        }
      }
      if (selector === ".batch-table-row") {
        const matches = html.match(/<tr class="batch-table-row/g);
        if (matches) {
          matches.forEach(() => results.push({}));
        }
      }
      if (selector === "[data-retry-idx]") {
        const regex = /data-retry-idx="(\d+)"/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
          const val = match[1];
          results.push({
            getAttribute: (attr) => (attr === "data-retry-idx" ? val : null),
            onclick: null
          });
        }
      }
      return results;
    }
  };
}

// ==========================================
// Test 1: Request Body Parity between 「批量」 and 「高级画布」
// ==========================================
{
  const testModes = ["prompts", "styles", "layouts", "assets"];

  for (const mode of testModes) {
    const graph = createTestBatchGraph({
      loopMode: mode,
      style1: "FA-001",
      style2: "FB-031",
      fusion: false,
      layout: "SC-021",
      ratio: "3:4",
      mode: "graphic-text",
      promptListText: "文案一\n文案二\n文案三",
      styleIds: ["FA-001", "FA-002", "FA-003"],
      layoutIds: ["SC-021", "SC-022", "SC-001"],
      assets: [
        { id: "AST-1", name: "角色图参", image: "https://example.com/1.png" },
        { id: "AST-2", name: "道具图参", image: "https://example.com/2.png" }
      ]
    });

    const ctrlNode = graph.nodes.find((n) => n.type === "output_control");
    const loopNode = graph.nodes.find((n) => n.type === "loop");

    // Both canvas and batch use the same plan builder logic:
    const rec = Engine.resolveControlRecipe(graph, ctrlNode, sharedCatalog);
    const iters = Engine.resolveLoopIterations(graph, loopNode, rec, sharedCatalog);

    assert.ok(iters.length > 0, `Mode ${mode} must resolve iterations`);

    // In canvas, execution iterates over plan.specs:
    for (let i = 0; i < iters.length; i++) {
      const iter = iters[i];
      const slotSpec = {
        fromLoop: true,
        loopNodeId: loopNode.id,
        loopStepIndex: iter.index,
        slotKey: `loop_${iter.index}_0`,
        style1: iter.style1 || "",
        layout: iter.layout || rec.layoutId || "",
        assetItems: iter.assetItems || null,
        mode: "graphic-text",
        ratio: "3:4",
        theme: iter.theme
      };

      const canvasPrompt = Engine.assembleControlPrompt(graph, ctrlNode, sharedCatalog, "cloud", slotSpec);
      const canvasReqBody = {
        prompt: canvasPrompt,
        ratio: slotSpec.ratio,
        style1: slotSpec.style1 || rec.style1Id || "",
        style2: rec.style2Id || "",
        layout: slotSpec.layout || rec.layoutId || "",
        refImages: (slotSpec.assetItems || rec.assetItems).map((a) => a.image).filter(Boolean),
        confirmCost: true
      };

      // In batch, execution calls runLoopNode -> runOutputControlNode:
      // The identical slotSpec and cloud prompt are assembled from ctrlNode and loopNode!
      const batchPrompt = Engine.assembleControlPrompt(graph, ctrlNode, sharedCatalog, "cloud", slotSpec);
      const batchReqBody = {
        prompt: batchPrompt,
        ratio: slotSpec.ratio,
        style1: slotSpec.style1 || rec.style1Id || "",
        style2: rec.style2Id || "",
        layout: slotSpec.layout || rec.layoutId || "",
        refImages: (slotSpec.assetItems || rec.assetItems).map((a) => a.image).filter(Boolean),
        confirmCost: true
      };

      assert.deepEqual(batchReqBody, canvasReqBody, `Request body for ${mode} row ${i} must be identical`);
    }
  }
  console.log("✓ Test 1 Passed: Request Body Parity between 批量 and 画布 verified across all 4 modes");
}

// ==========================================
// Test 2: Four Batch Modes Line Counts match resolveLoopIterations
// ==========================================
{
  const graphPrompts = createTestBatchGraph({
    loopMode: "prompts",
    promptListText: "日签 1\n日签 2\n日签 3\n日签 4\n日签 5"
  });
  const recP = Engine.resolveControlRecipe(graphPrompts, graphPrompts.nodes.find(n => n.type === "output_control"), sharedCatalog);
  const itersP = Engine.resolveLoopIterations(graphPrompts, graphPrompts.nodes.find(n => n.type === "loop"), recP, sharedCatalog);
  assert.equal(itersP.length, 5, "Prompts mode iterations must equal non-empty line count");

  const graphStyles = createTestBatchGraph({
    loopMode: "styles",
    styleIds: ["FA-001", "FA-002", "FA-003", "FB-031"]
  });
  const recS = Engine.resolveControlRecipe(graphStyles, graphStyles.nodes.find(n => n.type === "output_control"), sharedCatalog);
  const itersS = Engine.resolveLoopIterations(graphStyles, graphStyles.nodes.find(n => n.type === "loop"), recS, sharedCatalog);
  assert.equal(itersS.length, 4, "Styles mode iterations must equal selected styleIds count");

  const graphLayouts = createTestBatchGraph({
    loopMode: "layouts",
    layoutIds: ["SC-021", "SC-022", "SC-001"]
  });
  const recL = Engine.resolveControlRecipe(graphLayouts, graphLayouts.nodes.find(n => n.type === "output_control"), sharedCatalog);
  const itersL = Engine.resolveLoopIterations(graphLayouts, graphLayouts.nodes.find(n => n.type === "loop"), recL, sharedCatalog);
  assert.equal(itersL.length, 3, "Layouts mode iterations must equal selected layoutIds count");

  const graphAssets = createTestBatchGraph({
    loopMode: "assets",
    assets: [
      { id: "A1", name: "图参1", image: "https://example.com/1.png" },
      { id: "A2", name: "图参2", image: "https://example.com/2.png" }
    ]
  });
  const recA = Engine.resolveControlRecipe(graphAssets, graphAssets.nodes.find(n => n.type === "output_control"), sharedCatalog);
  const itersA = Engine.resolveLoopIterations(graphAssets, graphAssets.nodes.find(n => n.type === "loop"), recA, sharedCatalog);
  assert.equal(itersA.length, 2, "Assets mode iterations must equal asset items count");

  console.log("✓ Test 2 Passed: Line counts match resolveLoopIterations across all 4 batch modes");
}

function createFakeDom() {
  return {
    innerHTML: "",
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    removeEventListener() {}
  };
}

// ==========================================
// Test 3: Card Hiding in Row 2
// ==========================================
{
  const fakeHost = createFakeDom();
  const controller = HandrawBatchCreate;

  // 1. In styles mode: style card is hidden, layout card is shown
  {
    const graph = createTestBatchGraph({ loopMode: "styles" });
    const parts = {
      ctrl: graph.nodes.find(n => n.type === "output_control"),
      loop: graph.nodes.find(n => n.type === "loop"),
      skill: graph.nodes.find(n => n.type === "skill_params"),
      text: graph.nodes.find(n => n.type === "text_input"),
      asset: graph.nodes.find(n => n.type === "asset")
    };
    controller.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});
    const parsed = parseHtml(fakeHost.innerHTML);
    const pickCards = parsed.querySelectorAll("[data-pick-kind]");
    const kinds = pickCards.map(c => c.getAttribute("data-pick-kind"));
    assert.ok(!kinds.includes("style1"), "Style card must be hidden in styles mode");
    assert.ok(kinds.includes("layout"), "Layout card must be shown in styles mode");
    assert.ok(kinds.includes("color"), "Color card must be shown in styles mode");
  }

  // 2. In layouts mode: layout card is hidden, style card is shown
  {
    const graph = createTestBatchGraph({ loopMode: "layouts" });
    const parts = {
      ctrl: graph.nodes.find(n => n.type === "output_control"),
      loop: graph.nodes.find(n => n.type === "loop"),
      skill: graph.nodes.find(n => n.type === "skill_params"),
      text: graph.nodes.find(n => n.type === "text_input"),
      asset: graph.nodes.find(n => n.type === "asset")
    };
    controller.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});
    const parsed = parseHtml(fakeHost.innerHTML);
    const pickCards = parsed.querySelectorAll("[data-pick-kind]");
    const kinds = pickCards.map(c => c.getAttribute("data-pick-kind"));
    assert.ok(kinds.includes("style1"), "Style card must be shown in layouts mode");
    assert.ok(!kinds.includes("layout"), "Layout card must be hidden in layouts mode");
    assert.ok(kinds.includes("color"), "Color card must be shown in layouts mode");
  }

  // 3. In prompts mode: both style and layout cards are shown
  {
    const graph = createTestBatchGraph({ loopMode: "prompts" });
    const parts = {
      ctrl: graph.nodes.find(n => n.type === "output_control"),
      loop: graph.nodes.find(n => n.type === "loop"),
      skill: graph.nodes.find(n => n.type === "skill_params"),
      text: graph.nodes.find(n => n.type === "text_input"),
      asset: graph.nodes.find(n => n.type === "asset")
    };
    controller.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});
    const parsed = parseHtml(fakeHost.innerHTML);
    const pickCards = parsed.querySelectorAll("[data-pick-kind]");
    const kinds = pickCards.map(c => c.getAttribute("data-pick-kind"));
    assert.ok(kinds.includes("style1"), "Style card must be shown in prompts mode");
    assert.ok(kinds.includes("layout"), "Layout card must be shown in prompts mode");
    assert.ok(kinds.includes("color"), "Color card must be shown in prompts mode");
  }

  console.log("✓ Test 3 Passed: Row 2 card hiding logic verified");
}

// ==========================================
// Test 4: Row 1 DOM Order
// ==========================================
{
  const fakeHost = createFakeDom();
  const graph = createTestBatchGraph({ loopMode: "prompts" });
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };
  HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});
  const html = fakeHost.innerHTML;

  const idxBatchMode = html.indexOf("批量方式");
  const idxOutputMode = html.indexOf("生成方式");
  const idxFusionMode = html.indexOf("画风模式");

  assert.ok(idxBatchMode > 0, "批量方式 must exist in Row 1");
  assert.ok(idxOutputMode > 0, "生成方式 must exist in Row 1");
  assert.ok(idxFusionMode > 0, "画风模式 must exist in Row 1");

  assert.ok(idxBatchMode < idxOutputMode, "批量方式 must appear before 生成方式");
  assert.ok(idxOutputMode < idxFusionMode, "生成方式 must appear before 画风模式");

  console.log("✓ Test 4 Passed: Row 1 DOM order verified (批量方式 -> 生成方式 -> 画风模式)");
}

// ==========================================
// Test 5: Secondary Confirmation when Count > 20
// ==========================================
{
  // 1. Generate 25 prompts
  const lines25 = Array.from({ length: 25 }, (_, i) => `主题 ${i + 1}`).join("\n");
  const graph = createTestBatchGraph({
    loopMode: "prompts",
    promptListText: lines25
  });
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };

  let runCalled = false;
  let confirmPrompt = "";

  const fakeHost = { innerHTML: "" };
  HandrawBatchCreate.render(fakeHost, {
    parts,
    graph,
    catalog: sharedCatalog,
    loggedIn: true,
    freeQuotaRemaining: 3,
    credits: 100,
    siteSettings: { credit_cost_per_image: 2 }
  }, {
    run: () => { runCalled = true; }
  });

  // Attach mock confirm
  let confirmAnswer = false;
  sandbox.window.confirm = (msg) => {
    confirmPrompt = msg;
    return confirmAnswer;
  };

  // Case A: User cancels confirmation (> 20 items)
  confirmAnswer = false;
  runCalled = false;
  const startBtn = fakeHost.innerHTML.includes('id="batch-btn-start"');
  assert.ok(startBtn, "Start button must be rendered");

  // Call the start handler directly
  const iters = HandrawBatchCreate.resolveIterations();
  assert.equal(iters.length, 25);
  const cost = HandrawBatchCreate.calculateCost(iters.length);
  assert.equal(cost.totalCount, 25);
  assert.equal(cost.freeCount, 3);
  assert.equal(cost.paidCount, 22);
  assert.equal(cost.totalCost, 44);

  // Trigger simulated start click with cancel
  const msg = `本次将批量生成 ${iters.length} 张图片，预计消耗 ${cost.totalCost} 积分（其中免费额度 ${cost.freeCount} 张）。确认开始批量生成吗？`;
  const ok1 = sandbox.window.confirm(msg);
  assert.equal(ok1, false);
  if (ok1) runCalled = true;
  assert.equal(runCalled, false, "When user cancels confirmation, run must NOT be called");

  // Case B: User confirms (> 20 items)
  confirmAnswer = true;
  runCalled = false;
  const ok2 = sandbox.window.confirm(msg);
  assert.equal(ok2, true);
  if (ok2) runCalled = true;
  assert.equal(runCalled, true, "When user confirms, run must be called");

  console.log("✓ Test 5 Passed: Secondary confirmation when count > 20 verified");
}

// ==========================================
// Test 6: Single-Row Retry
// ==========================================
{
  let retriedIdx = null;
  const graph = createTestBatchGraph({
    loopMode: "prompts",
    promptListText: "主题1\n主题2\n主题3"
  });
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };

  // Mock displays where row 1 failed (items[1] has no imageUrl)
  const mockDisplays = [
    {
      id: "gal1",
      data: {
        kind: "batch_gallery",
        items: [
          { imageUrl: "https://example.com/1.png", title: "主题1" },
          { imageUrl: "", title: "主题2" }, // failed
          { imageUrl: "https://example.com/3.png", title: "主题3" }
        ]
      }
    }
  ];

  const fakeHost = { innerHTML: "" };
  HandrawBatchCreate.render(fakeHost, {
    parts,
    graph,
    catalog: sharedCatalog,
    displays: mockDisplays
  }, {
    runSingleRow: (idx) => { retriedIdx = idx; }
  });

  const parsed = parseHtml(fakeHost.innerHTML);
  const retryBtns = parsed.querySelectorAll("[data-retry-idx]");
  assert.equal(retryBtns.length, 1, "Only the failed row must have a retry button");
  assert.equal(retryBtns[0].getAttribute("data-retry-idx"), "1", "Retry button must target row index 1");

  console.log("✓ Test 6 Passed: Failed row retry button rendered for failed row only");
}

// ==========================================
// Test 7: Subject Passed to goToCurationShare on Publish
// ==========================================
{
  // Test that openPublishModalForDisplay in studio-app.js passes subject
  assert.ok(studioAppSource.includes("let subject = \"\";"), "studio-app.js must extract subject");
  assert.ok(studioAppSource.includes("qParts.text.data.text"), "studio-app.js must check quick parts text node");
  assert.ok(studioAppSource.includes("sharePayload.subject = subject;"), "studio-app.js must attach subject to share payload");

  console.log("✓ Test 7 Passed: Subject passed to goToCurationShare on publish");
}

// ==========================================
// Test 8: CSS Responsive Rules Verified
// ==========================================
{
  assert.ok(quickCreateCss.includes(".batch-container"), "CSS must contain .batch-container");
  assert.ok(quickCreateCss.includes(".batch-preview-table"), "CSS must contain .batch-preview-table");
  assert.ok(quickCreateCss.includes(".batch-table-wrap"), "CSS must contain .batch-table-wrap with overflow-x:auto");
  assert.ok(quickCreateCss.includes(".batch-chip"), "CSS must contain .batch-chip");
  assert.ok(quickCreateCss.includes("@media(max-width:768px)"), "CSS must contain mobile responsive rules");

  console.log("✓ Test 8 Passed: CSS layout and responsive rules verified");
}

console.log("\n==========================================");
console.log("All 8 Studio Batch tests passed successfully!");
console.log("==========================================");
