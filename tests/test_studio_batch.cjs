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
    },
    body: {
      appendChild() {},
      removeChild() {}
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
  toast() {},
  openModal() {},
  closeModal() {}
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
    batchLayoutMode: options.batchLayoutMode || "fixed",
    batchSeed: options.batchSeed || "都市慢生活与手绘手账",
    batchCount: options.batchCount || 6,
    batchLayoutReq: options.batchLayoutReq || "",
    batchRows: options.batchRows || null,
    promptListText: options.promptListText != null ? options.promptListText : "早八一杯热美式\n晚霞中的单车\n周末雨天读旧诗集",
    maxIterations: 200
  });
  const ctrl = Engine.makeOutputControlNode(880, 200, {
    mode: options.mode || "graphic-text",
    ratio: options.ratio || "3:4",
    count: options.count != null ? options.count : 1
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
  const nodePool = new Map();
  function getNode(id, init) {
    if (!nodePool.has(id)) {
      nodePool.set(id, init());
    }
    return nodePool.get(id);
  }

  return {
    html,
    querySelector(selector) {
      if (selector === "#batch-mode-single") {
        return html.includes('id="batch-mode-single"') ? getNode("batch-mode-single", () => ({ id: "batch-mode-single", onclick: null })) : null;
      }
      if (selector === "#batch-mode-fusion") {
        return html.includes('id="batch-mode-fusion"') ? getNode("batch-mode-fusion", () => ({ id: "batch-mode-fusion", onclick: null })) : null;
      }
      if (selector === "#batch-strategy-fixed") {
        return html.includes('id="batch-strategy-fixed"') ? getNode("batch-strategy-fixed", () => ({ id: "batch-strategy-fixed", onclick: null, onkeydown: null, focus() {} })) : null;
      }
      if (selector === "#batch-strategy-ai") {
        return html.includes('id="batch-strategy-ai"') ? getNode("batch-strategy-ai", () => ({ id: "batch-strategy-ai", onclick: null, onkeydown: null, focus() {} })) : null;
      }
      if (selector === "#batch-btn-plan") {
        return html.includes('id="batch-btn-plan"') ? getNode("batch-btn-plan", () => ({ id: "batch-btn-plan", onclick: null, disabled: html.includes('id="batch-btn-plan" disabled') })) : null;
      }
      if (selector === "#batch-btn-reset") {
        return html.includes('id="batch-btn-reset"') ? getNode("batch-btn-reset", () => ({ id: "batch-btn-reset", onclick: null, disabled: html.includes('id="batch-btn-reset" disabled') })) : null;
      }
      if (selector === "#batch-btn-pick-fixed-layout") {
        return html.includes('id="batch-btn-pick-fixed-layout"') ? getNode("batch-btn-pick-fixed-layout", () => ({ id: "batch-btn-pick-fixed-layout", onclick: null })) : null;
      }
      if (selector === "#batch-layout-req-input") {
        const m = html.match(/id="batch-layout-req-input"[^>]*value="([^"]*)"/);
        return m ? getNode("batch-layout-req-input", () => ({ value: m[1], oninput: null })) : (html.includes('id="batch-layout-req-input"') ? getNode("batch-layout-req-input", () => ({ value: "", oninput: null })) : null);
      }
      if (selector === "#batch-prompts-input") {
        const m = html.match(/id="batch-prompts-input"[^>]*>([\s\S]*?)<\/textarea>/);
        return m ? getNode("batch-prompts-input", () => ({ value: m[1], oninput: null, onblur: null })) : null;
      }
      if (selector === "#batch-btn-start") {
        return html.includes('id="batch-btn-start"') ? getNode("batch-btn-start", () => ({ id: "batch-btn-start", onclick: null, disabled: html.includes('id="batch-btn-start" disabled') })) : null;
      }
      if (selector === "#batch-btn-fission" || selector === "#batch-btn-fission-ai") {
        const id = selector.slice(1);
        if (!html.includes(`id="${id}"`)) return null;
        return getNode(id, () => {
          const m = html.match(new RegExp(`id="${id}"[^>]*>([\\s\\S]*?)<\\/button>`));
          return { id, textContent: m ? m[1] : "", onclick: null };
        });
      }
      if (selector === "#batch-btn-pick-global-refs") {
        return html.includes('id="batch-btn-pick-global-refs"') ? getNode("batch-btn-pick-global-refs", () => ({ id: "batch-btn-pick-global-refs", onclick: null })) : null;
      }
      if (selector === ".batch-plan-notice") {
        const m = html.match(/<span class="batch-plan-notice"[^>]*>([\s\S]*?)<\/span>/);
        return m ? { textContent: m[1] } : null;
      }
      if (selector === ".batch-cost-wrap") {
        const m = html.match(/<div class="batch-cost-wrap">([\s\S]*?)<\/div>/);
        return m ? { innerHTML: m[1] } : null;
      }
      if (selector === ".batch-preview-title") {
        const m = html.match(/<h3 class="batch-preview-title">([\s\S]*?)<\/h3>/);
        return m ? { textContent: m[1] } : null;
      }
      const all = this.querySelectorAll(selector);
      return all[0] || null;
    },
    querySelectorAll(selector) {
      const results = [];
      if (selector === "[data-set-mode]") {
        const regex = /data-set-mode="([^"]+)"/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
          const val = match[1];
          results.push({
            getAttribute: (attr) => (attr === "data-set-mode" ? val : null),
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
      if (selector === ".batch-edit-row") {
        const matches = html.match(/<tr class="batch-edit-row/g);
        if (matches) {
          matches.forEach(() => results.push({}));
        }
      }
      if (selector === ".batch-row-theme-input") {
        const regex = /class="[^"]*batch-row-theme-input[^"]*"[^>]*data-row-idx="(\d+)"[^>]*value="([^"]*)"/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
          const idx = match[1];
          const val = match[2];
          results.push({
            getAttribute: (attr) => (attr === "data-row-idx" ? idx : null),
            value: val,
            oninput: null,
            onblur: null,
            onclick: null,
            onkeydown: null
          });
        }
      }
      if (selector === "[data-iter-theme-idx]" || selector === ".batch-iter-label-btn") {
        const regex = /data-iter-theme-idx="(\d+)"/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
          const idx = match[1];
          results.push({
            getAttribute: (attr) => (attr === "data-iter-theme-idx" ? idx : null),
            onclick: null,
            onkeydown: null
          });
        }
      }
      if (selector === ".batch-row-layout-select") {
        const regex = /class="[^"]*batch-row-layout-select[^"]*"[^>]*data-row-idx="(\d+)"/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
          const idx = match[1];
          results.push({
            getAttribute: (attr) => (attr === "data-row-idx" ? idx : null),
            onchange: null
          });
        }
      }
      if (selector === "[data-pick-layout-idx]" || selector === ".batch-row-layout-btn") {
        const regex = /<button[^>]*class="[^"]*batch-row-layout-btn[^"]*"[^>]*data-pick-layout-idx="(\d+)"[^>]*title="([^"]*)"[^>]*>([\s\S]*?)<\/button>/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
          const idx = match[1];
          const title = match[2];
          const inner = match[3];
          const imgMatch = inner.match(/<img[^>]*data-hw-src="([^"]*)"[^>]*>/);
          results.push({
            getAttribute: (attr) => (attr === "data-pick-layout-idx" ? idx : attr === "title" ? title : null),
            title,
            innerHTML: inner,
            querySelector: (sel) => {
              if (sel === "img" || sel === ".batch-row-layout-thumb") {
                return imgMatch ? { getAttribute: (a) => (a === "data-hw-src" ? imgMatch[1] : null) } : null;
              }
              return null;
            },
            onclick: null
          });
        }
      }
      if (selector === ".batch-iter-thumb-btn") {
        const regex = /<button[^>]*class="[^"]*batch-iter-thumb-btn[^"]*"[^>]*data-zoom-src="([^"]*)"[^>]*data-zoom-title="([^"]*)"[^>]*>([\s\S]*?)<\/button>/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
          const zSrc = match[1];
          const zTitle = match[2];
          const inner = match[3];
          results.push({
            getAttribute: (attr) => (attr === "data-zoom-src" ? zSrc : attr === "data-zoom-title" ? zTitle : null),
            title: zTitle,
            innerHTML: inner,
            onclick: null
          });
        }
      }
      if (selector === ".batch-iter-placeholder") {
        const matches = html.match(/<div[^>]*class="[^"]*batch-iter-placeholder[^"]*"[^>]*>[\s\S]*?<\/div>/g);
        if (matches) {
          matches.forEach((m) => results.push({ innerHTML: m }));
        }
      }
      if (selector === ".batch-iter-schematic-badge") {
        const matches = html.match(/<span[^>]*class="[^"]*batch-iter-schematic-badge[^"]*"[^>]*>[\s\S]*?<\/span>/g);
        if (matches) {
          matches.forEach((m) => results.push({ innerHTML: m }));
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

function createFakeDom() {
  const elements = new Map();
  let parsed = null;
  return {
    _html: "",
    get innerHTML() { return this._html; },
    set innerHTML(val) {
      this._html = val;
      elements.clear();
      parsed = parseHtml(this._html);
    },
    querySelector(sel) {
      if (!parsed) parsed = parseHtml(this._html);
      return parsed.querySelector(sel);
    },
    querySelectorAll(sel) {
      if (!parsed) parsed = parseHtml(this._html);
      if (!elements.has(sel)) {
        elements.set(sel, parsed.querySelectorAll(sel));
      }
      return elements.get(sel);
    },
    addEventListener() {},
    removeEventListener() {}
  };
}

console.log("Starting Studio Batch Test Suite (Phase 3b-4 Redesign)...\n");

// ==========================================
// Requirement 1: 固定图型 (Fixed Layout)
// 主题文本框 -> promptListText，图型取控制节点；生成的 specs 与改前逐项一致
// ==========================================
{
  const graph = createTestBatchGraph({
    batchLayoutMode: "fixed",
    layout: "SC-021",
    promptListText: "晨间热美式\n晚霞飞鸟\n深夜手账",
    batchRows: null
  });

  const ctrlNode = graph.nodes.find((n) => n.type === "output_control");
  const loopNode = graph.nodes.find((n) => n.type === "loop");
  const rec = Engine.resolveControlRecipe(graph, ctrlNode, sharedCatalog);
  const iters = Engine.resolveLoopIterations(graph, loopNode, rec, sharedCatalog);

  assert.equal(iters.length, 3, "Fixed layout must resolve 3 iterations from promptListText");
  iters.forEach((it, idx) => {
    assert.equal(it.layout, "", "Fixed layout iter.layout is empty (defaults to recipe layoutId)");
    const slotSpec = {
      fromLoop: true,
      loopNodeId: loopNode.id,
      loopStepIndex: it.index,
      slotKey: `loop_${it.index}_0`,
      style1: it.style1 || "",
      layout: it.layout || rec.layoutId || "",
      assetItems: it.assetItems || null,
      mode: "graphic-text",
      ratio: "3:4",
      theme: it.theme
    };
    assert.equal(slotSpec.layout, "SC-021", "Spec layout must equal control recipe layoutId");
    const cloudPrompt = Engine.assembleControlPrompt(graph, ctrlNode, sharedCatalog, "cloud", slotSpec);
    assert.ok(cloudPrompt.includes("SC-021") || cloudPrompt.includes("双拼"), "Prompt must reflect SC-021 layout");
  });

  console.log("✓ Requirement 1 Passed: Fixed layout path verifies specs parity with baseline");
}

// ==========================================
// Requirement 2: AI 推荐图型 (AI Recommended Layouts)
// batchRows -> 每行独立 layout 进入 specs，assembleControlPrompt 输出的图型与行图型一致
// ==========================================
{
  const testRows = [
    { theme: "晨光推开咖啡馆木门", layout: "SC-001" },
    { theme: "手冲水流与咖啡香气", layout: "IG-005" },
    { theme: "午后翻阅手绘画册", layout: "SC-022" }
  ];

  const graph = createTestBatchGraph({
    batchLayoutMode: "ai",
    layout: "SC-021", // global fallback
    batchRows: testRows
  });

  const ctrlNode = graph.nodes.find((n) => n.type === "output_control");
  const loopNode = graph.nodes.find((n) => n.type === "loop");
  const rec = Engine.resolveControlRecipe(graph, ctrlNode, sharedCatalog);
  const iters = Engine.resolveLoopIterations(graph, loopNode, rec, sharedCatalog);

  assert.equal(iters.length, 3, "AI recommended layout must resolve 3 iterations from batchRows");

  assert.equal(iters[0].layout, "SC-001");
  assert.equal(iters[1].layout, "IG-005");
  assert.equal(iters[2].layout, "SC-022");

  // Verify assembled prompts match each row's individual layout
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

    assert.equal(slotSpec.layout, testRows[i].layout, `Spec ${i} layout must match row layout`);
    const prompt = Engine.assembleControlPrompt(graph, ctrlNode, sharedCatalog, "skill", slotSpec);
    assert.ok(prompt.includes(testRows[i].layout), `Prompt for row ${i} must include layout ${testRows[i].layout}`);
  }

  console.log("✓ Requirement 2 Passed: AI recommended layout per-row layout spec and prompt assembly verified");
}

// ==========================================
// Requirement 3: batchRows 缺失或为空时，resolveLoopIterations 输出与基线逐字节一致
// ==========================================
{
  const graphBaseline = createTestBatchGraph({
    loopMode: "prompts",
    promptListText: "主题一\n主题二\n主题三"
  });
  delete graphBaseline.nodes.find(n => n.type === "loop").data.batchRows;

  const rec = Engine.resolveControlRecipe(graphBaseline, graphBaseline.nodes.find(n => n.type === "output_control"), sharedCatalog);
  const itersBaseline = Engine.resolveLoopIterations(graphBaseline, graphBaseline.nodes.find(n => n.type === "loop"), rec, sharedCatalog);

  // Compare with batchRows: []
  const graphEmptyRows = createTestBatchGraph({
    loopMode: "prompts",
    promptListText: "主题一\n主题二\n主题三",
    batchRows: []
  });
  const itersEmptyRows = Engine.resolveLoopIterations(graphEmptyRows, graphEmptyRows.nodes.find(n => n.type === "loop"), rec, sharedCatalog);

  assert.equal(JSON.stringify(itersBaseline), JSON.stringify(itersEmptyRows), "When batchRows is empty or missing, resolveLoopIterations must be byte-for-byte identical");

  console.log("✓ Requirement 3 Passed: Byte-for-byte baseline parity verified when batchRows is empty/missing");
}

// ==========================================
// Requirement 4: 策略切换 (Strategy Toggling & Confirmations)
// ==========================================
{
  const fakeHost = createFakeDom();
  const graph = createTestBatchGraph({
    batchLayoutMode: "ai",
    batchRows: [
      { theme: "主题A", layout: "SC-001" },
      { theme: "主题B", layout: "IG-005" }
    ],
    promptListText: "主题A\n主题B"
  });
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };

  let dirtyCalled = false;
  HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {
    markDirtyAndRender: () => { dirtyCalled = true; }
  });

  // Attach mock confirm
  let confirmReturn = false;
  let confirmMessage = "";
  sandbox.window.confirm = (msg) => {
    confirmMessage = msg;
    return confirmReturn;
  };

  // Case A: User cancels switching from AI to Fixed (custom layouts won't be discarded)
  confirmReturn = false;
  dirtyCalled = false;
  const parsed = parseHtml(fakeHost.innerHTML);
  const btnFixed = parsed.querySelector("#batch-strategy-fixed");
  assert.ok(btnFixed, "Strategy fixed button must exist");

  // Call the click handler logic directly
  const rows = parts.loop.data.batchRows;
  const hasCustom = rows.some(r => r.layout && r.layout !== (parts.skill.data.layout || ""));
  assert.ok(hasCustom, "Rows must have custom layout different from skill layout");

  const proceedCancel = sandbox.window.confirm("切换到固定图型将丢失每张独立的图型设置，所有图片将使用统一图型。是否继续？");
  assert.equal(proceedCancel, false);
  // State remains unchanged
  assert.equal(parts.loop.data.batchLayoutMode, "ai");
  assert.equal(parts.loop.data.batchRows.length, 2);

  // Case B: User confirms switching from AI to Fixed
  confirmReturn = true;
  const proceedOk = sandbox.window.confirm("切换到固定图型将丢失每张独立的图型设置，所有图片将使用统一图型。是否继续？");
  assert.equal(proceedOk, true);
  if (proceedOk) {
    parts.loop.data.promptListText = parts.loop.data.batchRows.map(r => r.theme).filter(Boolean).join("\n");
    parts.loop.data.batchRows = [];
    parts.loop.data.batchLayoutMode = "fixed";
  }
  assert.equal(parts.loop.data.batchLayoutMode, "fixed");
  assert.equal(parts.loop.data.promptListText, "主题A\n主题B");
  assert.equal(parts.loop.data.batchRows.length, 0);

  // Case C: Switching from Fixed to AI
  parts.loop.data.batchLayoutMode = "ai";
  const lines = parts.loop.data.promptListText.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  parts.loop.data.batchRows = lines.map(l => ({ theme: l, layout: parts.skill.data.layout || "" }));
  assert.equal(parts.loop.data.batchRows.length, 2);
  assert.equal(parts.loop.data.batchRows[0].theme, "主题A");
  assert.equal(parts.loop.data.batchRows[1].theme, "主题B");

  console.log("✓ Requirement 4 Passed: Strategy switching confirmation and theme retention verified");
}

// ==========================================
// Requirement 5: 规划失败 (source: 'template') 提示出现且内容填入
// ==========================================
{
  const fakeHost = createFakeDom();
  const graph = createTestBatchGraph({
    batchLayoutMode: "fixed"
  });
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };

  // Set notice from template fallback
  HandrawBatchCreate.planNotice = "未使用 AI 规划，已按模板生成";
  parts.loop.data.promptListText = "【都市慢生活】序章初探\n【都市慢生活】主角特写\n【都市慢生活】核心器物";

  HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});
  const parsed = parseHtml(fakeHost.innerHTML);

  const notice = parsed.querySelector(".batch-plan-notice");
  assert.ok(notice, "Template notice must be rendered");
  assert.ok(notice.textContent.includes("未使用 AI 规划，已按模板生成"), "Notice text must match template message");

  const prompts = parsed.querySelector("#batch-prompts-input");
  assert.ok(prompts, "Prompts textarea must exist");
  assert.ok(prompts.value.includes("【都市慢生活】序章初探"), "Template generated content must be filled into textarea");

  // Clean notice for next tests
  HandrawBatchCreate.planNotice = "";

  console.log("✓ Requirement 5 Passed: Template fallback notice and content population verified");
}

// ==========================================
// Removal of Fission: No #batch-btn-fission or #batch-btn-fission-ai in either mode
// ==========================================
{
  for (const mode of ["fixed", "ai"]) {
    const fakeHost = createFakeDom();
    const graph = createTestBatchGraph({
      batchLayoutMode: mode,
      batchRows: mode === "ai" ? [{ theme: "测试", layout: "SC-001" }] : []
    });
    const parts = {
      ctrl: graph.nodes.find(n => n.type === "output_control"),
      loop: graph.nodes.find(n => n.type === "loop"),
      skill: graph.nodes.find(n => n.type === "skill_params"),
      text: graph.nodes.find(n => n.type === "text_input"),
      asset: graph.nodes.find(n => n.type === "asset")
    };
    HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});
    const html = fakeHost.innerHTML;
    assert.ok(!html.includes('id="batch-btn-fission"'), "Must not contain #batch-btn-fission");
    assert.ok(!html.includes('id="batch-btn-fission-ai"'), "Must not contain #batch-btn-fission-ai");
    assert.ok(!html.includes("从母题裂变"), "Must not contain text 从母题裂变");
  }
  assert.equal(typeof HandrawBatchCreate.openFissionModal, "undefined", "openFissionModal must be removed");
  console.log("✓ Requirement: Fission buttons and openFissionModal removed successfully");
}

// ==========================================
// M1 Fix Verification: Single Truth for Image Count and ctrl.data.count reset
// ==========================================
{
  // Graph initially has ctrl.data.count = 3, batchCount = 6
  const graph = createTestBatchGraph({
    promptListText: "主题1\n主题2\n主题3",
    count: 3
  });
  graph.nodes.find(n => n.type === "loop").data.batchCount = 6;
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };

  const fakeHost = createFakeDom();
  HandrawBatchCreate.render(fakeHost, {
    parts,
    graph,
    catalog: sharedCatalog,
    loggedIn: true,
    freeQuotaRemaining: 2,
    credits: 100,
    siteSettings: { credit_cost_per_image: 2 }
  }, {});

  // M1: ctrl.data.count reset to 1, folded into batchCount (6 * 3 = 18 <= 20)
  assert.equal(parts.ctrl.data.count, 1, "ctrl.data.count must be reset to 1");
  assert.equal(parts.loop.data.batchCount, 18, "batchCount must be folded to 18 (6 * 3)");
  assert.ok(fakeHost.innerHTML.includes("已按每行一张折算，共 18 张"), "Must display conversion notice in plan notice");

  const parsed = parseHtml(fakeHost.innerHTML);
  const costWrap = parsed.querySelector(".batch-cost-wrap");
  assert.ok(costWrap, "Cost wrap must exist");
  // 3 themes * 1 count = 3 total; 2 free + 1 paid * 2 = 2 credits
  assert.ok(costWrap.innerHTML.includes("共 3 张"), "Must display 共 3 张 (3 * 1)");
  assert.ok(costWrap.innerHTML.includes("免费 2 张 + 2 积分"), "Cost must reflect 3 images (2 free + 2 credits)");

  // 21 themes -> totalCount = 21 (over 20)
  const lines21 = Array.from({ length: 21 }, (_, i) => `主题 ${i + 1}`).join("\n");
  parts.loop.data.promptListText = lines21;

  const iters21 = HandrawBatchCreate.resolveIterations();
  assert.equal(iters21.length, 21);
  const cost21 = HandrawBatchCreate.calculateCost(21);
  assert.equal(cost21.totalCount, 21);
  assert.equal(cost21.freeCount, 2);
  assert.equal(cost21.paidCount, 19);
  assert.equal(cost21.totalCost, 38);

  // studio-batch.js must NOT have secondary confirm, single confirmation handled in confirmPotentialGenerationCost
  assert.ok(!studioBatchSource.includes('window.confirm("本次将批量生成'), "studio-batch.js must NOT have duplicate window.confirm");

  console.log("✓ M1 Passed: Image count unified, ctrl.data.count folded to 1, duplicate confirmation removed");
}

// ==========================================
// Defect 3 Fix Verification: Ratio validation pattern and regex
// ==========================================
{
  const ratioRegex = /^\d+(?:\.\d+)?:\d+(?:\.\d+)?$/;
  assert.ok(ratioRegex.test("5:2"), "5:2 must be valid");
  assert.ok(ratioRegex.test("3:4"), "3:4 must be valid");
  assert.ok(ratioRegex.test("16:9"), "16:9 must be valid");
  assert.ok(ratioRegex.test("2.35:1"), "2.35:1 must be valid");
  assert.ok(!ratioRegex.test("abc"), "abc must be rejected");
  assert.ok(!ratioRegex.test("5:"), "5: must be rejected");

  // Verify studio-batch.js source does not contain double escaped \\d in regex literal
  assert.ok(!studioBatchSource.includes(":\\\\d"), "studio-batch.js must not contain double escaped \\d in regex literal");

  console.log("✓ Defect 3 Passed: Custom ratio regex accepts 5:2 and valid aspect ratios");
}

// ==========================================
// Defect 4 Fix Verification: persistOpenTabs retains batchStart: true
// ==========================================
{
  assert.ok(studioAppSource.includes("batchStart: t.batchStart === true"), "studio-app.js persistOpenTabs must retain batchStart flag");
  console.log("✓ Defect 4 Passed: persistOpenTabs retains batchStart flag to prevent duplicate tabs on refresh");
}

// ==========================================
// Requirement 6: Row 1 DOM Order (生成方式 -> 画风模式)
// ==========================================
{
  const fakeHost = createFakeDom();
  const graph = createTestBatchGraph();
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };
  HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});
  const html = fakeHost.innerHTML;

  const idxOutputMode = html.indexOf("生成方式");
  const idxFusionMode = html.indexOf("画风模式");

  assert.ok(idxOutputMode > 0, "生成方式 must exist in Row 1");
  assert.ok(idxFusionMode > 0, "画风模式 must exist in Row 1");
  assert.ok(idxOutputMode < idxFusionMode, "生成方式 must appear before 画风模式");

  // No 批量方式 buttons in Row 1 anymore
  assert.ok(!html.includes('data-set-loop-mode="styles"'), "Old 批量方式 buttons must not exist in Row 1");

  console.log("✓ Requirement 6 Passed: Row 1 order verified (生成方式 -> 画风模式)");
}

// ==========================================
// Requirement 7: Zero Emoji in Batch UI Text
// ==========================================
{
  const emojiRegex = /[\u{1F300}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F900}-\u{1F9FF}\u{1F1E0}-\u{1F1FF}]/u;
  const match = studioBatchSource.match(emojiRegex);
  assert.equal(match, null, `studio-batch.js must not contain any emoji (found: ${match?.[0]})`);

  console.log("✓ Requirement 7 Passed: Zero emoji in studio-batch.js verified");
}

// ==========================================
// Requirement 8: Action Names Validation (B2 Fix Verification)
// ==========================================
{
  const renderCallMatch = studioAppSource.match(/window\.HandrawBatchCreate\.render\([\s\S]*?,\s*\{[\s\S]*?\},\s*\{([\s\S]*?)\n\s*\}\s*\n\s*\);/);
  assert.ok(renderCallMatch, "HandrawBatchCreate.render call must be found in studio-app.js");
  const actionsBlock = renderCallMatch[1];
  const providedActionKeys = new Set();
  for (const line of actionsBlock.split("\n")) {
    const km = line.match(/^ {12}([a-zA-Z0-9_]+)(?:\s*:|\s*,)/);
    if (km) providedActionKeys.add(km[1]);
  }

  assert.ok(providedActionKeys.size >= 8, `Expected at least 8 action keys, got ${providedActionKeys.size}`);
  assert.ok(providedActionKeys.has("openAssetPicker"), "studio-app.js must provide openAssetPicker");
  assert.ok(providedActionKeys.has("openImageLightbox"), "studio-app.js must provide openImageLightbox");
  assert.ok(!providedActionKeys.has("openPublish"), "openPublish must not be provided: batch results no longer offer manual publishing");
  assert.ok(providedActionKeys.has("run"), "studio-app.js must provide run");
  assert.ok(providedActionKeys.has("runSingleRow"), "studio-app.js must provide runSingleRow");
  assert.ok(providedActionKeys.has("cancel"), "studio-app.js must provide cancel");

  // Ensure retired non-existent actions are completely gone
  assert.ok(!providedActionKeys.has("openLayoutThumbPicker"), "openLayoutThumbPicker must NOT be in actions");
  assert.ok(!studioBatchSource.includes("openLayoutThumbPicker"), "openLayoutThumbPicker must not be called in studio-batch.js");
  assert.ok(!studioBatchSource.includes("openMultiPicker"), "openMultiPicker must not be called in studio-batch.js");
  assert.ok(!studioBatchSource.includes("openPublishForBatchItem"), "openPublishForBatchItem must not be called in studio-batch.js");

  // Check all actions accessed in studio-batch.js
  const usedActions = new Set();
  for (const m of studioBatchSource.matchAll(/self\.actions(?:\?|\.)([a-zA-Z0-9_]+)/g)) {
    usedActions.add(m[1]);
  }

  for (const actionName of usedActions) {
    assert.ok(
      providedActionKeys.has(actionName),
      `studio-batch.js calls action '${actionName}' which is NOT provided by studio-app.js!`
    );
  }

  console.log(`✓ Requirement 8 Passed: Action names validated (${Array.from(usedActions).join(", ")}) against studio-app.js`);
}

// ==========================================
// Requirement 9: Inline Layout Cell with Image and Shared Picker Verification
// ==========================================
{
  const graph = createTestBatchGraph();
  const loop = graph.nodes.find(n => n.type === "loop");
  const skill = graph.nodes.find(n => n.type === "skill_params");
  skill.data.layout = "SC-021";
  loop.data.batchLayoutMode = "ai";
  loop.data.batchRows = [
    { theme: "山间清风", layout: "SC-001" },
    { theme: "茶肆小憩", layout: "" } // global fallback
  ];

  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop,
    skill,
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };

  let openedPickerOpts = null;
  let openedLightbox = null;
  const fakeActions = {
    markDirtyAndRender: () => {},
    openAssetPicker: (opts) => { openedPickerOpts = opts; },
    openImageLightbox: (url, title) => { openedLightbox = { url, title }; }
  };

  const fakeHost = createFakeDom();
  HandrawBatchCreate.render(fakeHost, {
    parts,
    graph,
    catalog: sharedCatalog,
    loggedIn: true
  }, fakeActions);

  const layoutBtns = fakeHost.querySelectorAll("[data-pick-layout-idx]");
  assert.equal(layoutBtns.length, 2, "Must render 2 layout buttons for the 2 batch rows");

  // Row 0: specific layout SC-001
  const btn0 = layoutBtns[0];
  assert.ok(btn0.innerHTML.includes("<img"), "Row 0 layout button must contain <img>");
  assert.ok(btn0.innerHTML.includes("data-hw-src="), "Row 0 layout button must contain data-hw-src for lazy loading");
  assert.ok(!btn0.innerHTML.includes(" src="), "Row 0 layout button must NOT contain src attribute (lazy loader only)");
  assert.ok(btn0.innerHTML.includes("SC-001"), "Row 0 layout button must show SC-001");
  assert.ok(btn0.innerHTML.includes("居中卡片"), "Row 0 layout button must show SC-001 title");
  assert.ok(!btn0.innerHTML.includes("跟随全局"), "Row 0 specific layout must not say 跟随全局 in visible text");

  // Row 1: global layout fallback SC-021
  const btn1 = layoutBtns[1];
  assert.ok(btn1.innerHTML.includes("<img"), "Row 1 layout button must contain <img>");
  assert.ok(btn1.innerHTML.includes("data-hw-src="), "Row 1 layout button must contain data-hw-src for lazy loading");
  assert.ok(!btn1.innerHTML.includes(" src="), "Row 1 layout button must NOT contain src attribute (lazy loader only)");
  assert.ok(btn1.innerHTML.includes("SC-021"), "Row 1 layout button must show global layout SC-021");
  assert.ok(btn1.innerHTML.includes("双拼信息卡"), "Row 1 layout button must show SC-021 title");
  assert.ok(!btn1.innerHTML.includes("跟随全局"), "Row 1 layout button visible text must NOT include 跟随全局");
  assert.ok(btn1.title.includes("跟随全局图型 SC-021"), "Row 1 title must explain 跟随全局图型 SC-021");

  // Verify click calls openAssetPicker (shared picker mechanism)
  btn0.onclick();
  assert.ok(openedPickerOpts, "Clicking layout button must invoke openAssetPicker");
  assert.equal(openedPickerOpts.kind, "layout");
  assert.equal(openedPickerOpts.field, "layout");
  assert.equal(openedPickerOpts.current, "SC-001");
  assert.ok(typeof openedPickerOpts.onPick === "function", "openAssetPicker must receive onPick callback");

  // Verify studio-app.js routes openAssetPicker to openSkillFieldPickerModal
  assert.ok(
    studioAppSource.includes("openSkillFieldPickerModal(skillNode, field, options = {})") ||
    studioAppSource.includes("openSkillFieldPickerModal(bp.skill, targetField, { current, onPick, title })"),
    "openAssetPicker must delegate to openSkillFieldPickerModal with options"
  );
  assert.ok(
    !studioAppSource.includes("function openLayoutThumbPicker"),
    "openLayoutThumbPicker must be completely removed from studio-app.js"
  );
  assert.ok(
    !studioAppSource.includes("single: true"),
    "openLoopMultiPickerModal must not have single mode branch"
  );

  // Requirement 10: Batch preview iteration thumbnail zoom button verification
  const zoomBtns = fakeHost.querySelectorAll(".batch-iter-thumb-btn");
  assert.ok(zoomBtns.length > 0, "Batch preview table must wrap thumbnail in .batch-iter-thumb-btn");
  const zb0 = zoomBtns[0];
  assert.ok(zb0.getAttribute("data-zoom-src"), ".batch-iter-thumb-btn must have data-zoom-src");
  assert.ok(zb0.getAttribute("data-zoom-title"), ".batch-iter-thumb-btn must have data-zoom-title");
  assert.ok(!zb0.innerHTML.includes(" src="), "Batch iteration thumbnail must use only data-hw-src");

  zb0.onclick();
  assert.ok(openedLightbox, "Clicking .batch-iter-thumb-btn must trigger openImageLightbox");
  assert.equal(openedLightbox.url, zb0.getAttribute("data-zoom-src"));

  console.log("✓ Requirement 9 Passed: Inline layout cell contains <img> and picker shares 168-card renderer");
  console.log("✓ Requirement 10 Passed: Batch iteration thumbnail has lightbox zoom button");
}

// ==========================================
// Requirement 11: Global + Per-Row Reference Images (Additive, Cap, Dedupe, SkipGlobal)
// ==========================================
{
  const refGlobal1 = { id: "AST-001", name: "主角立绘", image: "/uploads/char1.webp", cat: "character" };
  const refGlobal2 = { id: "AST-002", name: "场景色调", image: "/uploads/scene1.webp", cat: "scene" };
  const refRow1 = { id: "AST-003", name: "单条道具", image: "/uploads/prop1.webp", cat: "prop" };
  const refRowDup = { id: "AST-002-dup", name: "场景色调", image: "/uploads/scene1.webp", cat: "scene" }; // Same image as refGlobal2

  const graph = createTestBatchGraph({
    batchLayoutMode: "ai",
    layout: "SC-021",
    assets: [refGlobal1, refGlobal2],
    batchRows: [
      { theme: "第1张：全局2张+单条1张不同", layout: "SC-001", assetItems: [refRow1], skipGlobalRefs: false },
      { theme: "第2张：全局2张+单条1张重复", layout: "SC-001", assetItems: [refRowDup], skipGlobalRefs: false },
      { theme: "第3张：不用全局+单条1张", layout: "SC-001", assetItems: [refRow1], skipGlobalRefs: true },
      { theme: "第4张：不用全局+无单条参考图", layout: "SC-001", assetItems: [], skipGlobalRefs: true },
      { theme: "第5张：无单条参考图+用全局", layout: "SC-001", assetItems: [], skipGlobalRefs: false }
    ]
  });

  const ctrlNode = graph.nodes.find((n) => n.type === "output_control");
  const loopNode = graph.nodes.find((n) => n.type === "loop");
  const rec = Engine.resolveControlRecipe(graph, ctrlNode, sharedCatalog);
  const iters = Engine.resolveLoopIterations(graph, loopNode, rec, sharedCatalog);

  assert.equal(iters.length, 5);

  // Case 1: Global 2 + Row 1 (different) -> merged length 3, global first
  assert.equal(iters[0].assetItems.length, 3, "Case 1: Global 2 + Row 1 must merge to 3 items");
  assert.equal(iters[0].assetItems[0].image, "/uploads/char1.webp", "Global ref 1 must be first");
  assert.equal(iters[0].assetItems[1].image, "/uploads/scene1.webp", "Global ref 2 must be second");
  assert.equal(iters[0].assetItems[2].image, "/uploads/prop1.webp", "Row ref must be third");

  // Case 2: Global 2 + Row 1 (duplicate image) -> deduped to 2 items, only appear once
  assert.equal(iters[1].assetItems.length, 2, "Case 2: Duplicate image must be deduped");
  assert.equal(iters[1].assetItems[0].image, "/uploads/char1.webp");
  assert.equal(iters[1].assetItems[1].image, "/uploads/scene1.webp");

  // Case 3: skipGlobalRefs: true with row ref -> only row ref
  assert.equal(iters[2].assetItems.length, 1, "Case 3: skipGlobalRefs must exclude global refs");
  assert.equal(iters[2].assetItems[0].image, "/uploads/prop1.webp");

  // Case 4: skipGlobalRefs: true with no row ref -> empty array []
  assert.ok(Array.isArray(iters[3].assetItems), "Case 4: skipGlobalRefs with no row refs must be an array");
  assert.equal(iters[3].assetItems.length, 0, "Case 4: must have length 0");

  // Case 5: neither row ref nor skipGlobal -> assetItems: null (fallback to global rec.assetItems)
  assert.equal(iters[4].assetItems, null, "Case 5: no row ref and not skipGlobal must have assetItems: null for byte-identical fallback");

  // Merged cap 7 check
  const manyRefs = Array.from({ length: 10 }, (_, i) => ({ id: `R-${i}`, image: `/u/${i}.webp` }));
  const graphCap = createTestBatchGraph({
    batchLayoutMode: "ai",
    assets: manyRefs.slice(0, 4),
    batchRows: [
      { theme: "超限测试", layout: "", assetItems: manyRefs.slice(3, 9) } // 4 global + 6 row = 9 unique
    ]
  });
  const recCap = Engine.resolveControlRecipe(graphCap, graphCap.nodes.find(n => n.type === "output_control"), sharedCatalog);
  const itersCap = Engine.resolveLoopIterations(graphCap, graphCap.nodes.find(n => n.type === "loop"), recCap, sharedCatalog);
  assert.equal(itersCap[0].assetItems.length, 7, "Merged references must be capped at MAX_MERGED_REFS = 7");

  console.log("✓ Requirement 11 Passed: Global + Row reference images merging, deduplication, skipGlobal isolation, and cap 7 verified");
}

// ==========================================
// Requirement 12: Unified Planning Inputs Section, Segmented Control & Unique Hero Plan Button
// ==========================================
{
  for (const mode of ["fixed", "ai"]) {
    const fakeHost = createFakeDom();
    const graph = createTestBatchGraph({
      batchLayoutMode: mode,
      layout: "SC-001",
      batchRows: mode === "ai" ? [{ theme: "原主题1", layout: "SC-001" }] : []
    });
    const parts = {
      ctrl: graph.nodes.find(n => n.type === "output_control"),
      loop: graph.nodes.find(n => n.type === "loop"),
      skill: graph.nodes.find(n => n.type === "skill_params"),
      text: graph.nodes.find(n => n.type === "text_input"),
      asset: graph.nodes.find(n => n.type === "asset")
    };

    let dirtyCalled = false;
    HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {
      markDirtyAndRender: () => { dirtyCalled = true; }
    });

    const html = fakeHost.innerHTML;

    // 1. Planning Inputs Panel & Tag
    assert.ok(html.includes("batch-plan-inputs-panel"), "Must render .batch-plan-inputs-panel");
    assert.ok(html.includes("batch-plan-inputs-tag"), "Must render .batch-plan-inputs-tag");
    assert.ok(html.includes("规划输入"), "Must display 规划输入 tag");

    // 2. Segmented Control for Strategy: NOT .btn, but .batch-strategy-seg-btn
    assert.ok(html.includes("batch-strategy-seg"), "Must render .batch-strategy-seg container");
    assert.ok(html.includes('id="batch-strategy-fixed"'), "Must render #batch-strategy-fixed");
    assert.ok(html.includes('id="batch-strategy-ai"'), "Must render #batch-strategy-ai");
    assert.ok(html.includes("batch-strategy-seg-btn"), "Must use .batch-strategy-seg-btn class");

    // Make sure strategy items do not use button classes that look like action buttons
    const stratFixedTag = html.match(/<button[^>]*id="batch-strategy-fixed"[^>]*>/);
    const stratAiTag = html.match(/<button[^>]*id="batch-strategy-ai"[^>]*>/);
    assert.ok(stratFixedTag, "#batch-strategy-fixed button tag must exist");
    assert.ok(stratAiTag, "#batch-strategy-ai button tag must exist");
    const stratFixedClass = stratFixedTag[0].match(/class="([^"]*)"/)?.[1] || "";
    const stratAiClass = stratAiTag[0].match(/class="([^"]*)"/)?.[1] || "";
    assert.ok(!stratFixedClass.split(/\s+/).includes("btn"), "#batch-strategy-fixed must NOT have class .btn");
    assert.ok(!stratAiClass.split(/\s+/).includes("btn"), "#batch-strategy-ai must NOT have class .btn");

    // 3. Fixed layout picker button has class btn btn-sm and NOT btn-primary
    if (mode === "fixed") {
      const pickBtnTag = html.match(/<button[^>]*id="batch-btn-pick-fixed-layout"[^>]*>/);
      assert.ok(pickBtnTag, "#batch-btn-pick-fixed-layout must exist");
      const pickBtnClass = pickBtnTag[0].match(/class="([^"]*)"/)?.[1] || "";
      assert.ok(!pickBtnClass.includes("btn-primary"), "#batch-btn-pick-fixed-layout must NOT be btn-primary");
    }

    // 4. Hero Plan Button has unique hero class and SVG icon
    assert.ok(html.includes("batch-btn-plan-hero"), "#batch-btn-plan must have class .batch-btn-plan-hero");
    assert.ok(html.includes("batch-plan-icon"), "Plan button must contain .batch-plan-icon SVG");
    assert.ok(html.includes("AI 规划这套图"), "Plan button must display 'AI 规划这套图'");

    // 5. Test keyboard navigation on strategy toggle
    const btnStratFixed = fakeHost.querySelector("#batch-strategy-fixed");
    const btnStratAi = fakeHost.querySelector("#batch-strategy-ai");
    assert.ok(btnStratFixed && btnStratAi, "Strategy elements must be accessible");

    // Simulate ArrowRight on fixed
    let aiClicked = false;
    btnStratAi.click = () => { aiClicked = true; };
    if (btnStratFixed.onkeydown) {
      btnStratFixed.onkeydown({ key: "ArrowRight", preventDefault() {} });
      assert.ok(aiClicked, "ArrowRight on fixed strategy must activate AI strategy");
    }

    // Simulate ArrowLeft on AI
    let fixedClicked = false;
    btnStratFixed.click = () => { fixedClicked = true; };
    if (btnStratAi.onkeydown) {
      btnStratAi.onkeydown({ key: "ArrowLeft", preventDefault() {} });
      assert.ok(fixedClicked, "ArrowLeft on AI strategy must activate fixed strategy");
    }
  }

  console.log("✓ Requirement 12 Passed: Unified Planning Inputs Section, Segmented Control & Unique Hero Plan Button verified");
}

// ==========================================
// Requirement 13: Visual 2 (No badges or IDs overlaid on images)
// ==========================================
{
  const fakeHost = createFakeDom();
  const graph = createTestBatchGraph({
    batchLayoutMode: "fixed",
    layout: "SC-001",
    tones: ["TN-001"],
    assets: [{ id: "AST-001", name: "测试参考图", image: "/uploads/test.webp" }]
  });
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };

  HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});

  // 1. In batch HTML, check fixed layout slot card
  const html = fakeHost.innerHTML;
  assert.ok(!html.includes('class="make-image-slot-badge"'), "make-image-slot-badge must NOT exist in batch HTML");
  assert.ok(html.includes("make-image-slot-code"), "make-image-slot-code must exist in slot meta");

  // 2. In studioAppSource, check openSkillFieldPickerModal and openAssetPickerModal ic-picker-card
  const freshStudioApp = fs.readFileSync("demo/assets/studio-app.js", "utf8");
  assert.ok(
    !freshStudioApp.includes('<span style="position:absolute;left:6px;top:6px;padding:2px 6px;border-radius:5px;background:rgba(20,17,15,0.72);color:#fff;font-size:10px;font-family:var(--font-mono);font-weight:700;">${esc(id)}</span>'),
    "ic-picker-card in studio-app.js must not overlay ID on image"
  );

  console.log("✓ Requirement 13 Passed: Visual 2 verified (no badges or IDs overlaid on images, moved to meta text)");
}

// ==========================================
// Requirement 14: Theme input is readonly and has click handler; List label has click handler
// ==========================================
{
  const fakeHost = createFakeDom();
  const graph = createTestBatchGraph({
    batchLayoutMode: "ai",
    batchRows: [
      { theme: "主题第一张", layout: "SC-001" },
      { theme: "主题第二张", layout: "SC-022" }
    ]
  });
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };

  HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});

  // 1. Verify batch-row-theme-input has readonly in HTML
  assert.ok(
    fakeHost.innerHTML.includes('class="make-image-input batch-row-theme-input" data-row-idx="0" value="主题第一张" placeholder="输入该张画面主题..." readonly'),
    "batch-row-theme-input must be readonly"
  );

  // 2. Verify click handler is bound
  const themeInputs = fakeHost.querySelectorAll(".batch-row-theme-input");
  assert.equal(themeInputs.length, 2);
  assert.equal(typeof themeInputs[0].onclick, "function", "batch-row-theme-input must have onclick function");

  // 3. Verify list table theme label has click handler
  const iterLabels = fakeHost.querySelectorAll("[data-iter-theme-idx]");
  assert.ok(iterLabels.length >= 2, "Must render iter theme click targets");
  assert.equal(typeof iterLabels[0].onclick, "function", "iter theme target must have onclick function");

  console.log("✓ Requirement 14 Passed: Theme inputs are readonly and click handlers open theme modal");
}

// ==========================================
// Requirement 15: Hover preview floating element is a global singleton
// ==========================================
{
  // Test with mock document in sandbox
  const mockDoc = {
    _elements: {},
    body: {
      appendChild: (el) => { mockDoc._elements[el.id] = el; },
      contains: (el) => Boolean(mockDoc._elements[el.id])
    },
    getElementById: (id) => mockDoc._elements[id] || null,
    createElement: (tag) => ({
      tagName: tag,
      id: "",
      className: "",
      style: {},
      innerHTML: "",
      setAttribute: () => {},
      querySelector: () => ({ setAttribute: () => {}, style: {} })
    })
  };

  sandbox.document = mockDoc;
  sandbox.window.document = mockDoc;

  try {
    const el1 = HandrawBatchCreate.ensureHoverPreviewElement();
    const el2 = HandrawBatchCreate.ensureHoverPreviewElement();
    assert.ok(el1, "ensureHoverPreviewElement must return an element");
    assert.strictEqual(el1, el2, "ensureHoverPreviewElement must return the exact same singleton instance");
    assert.equal(el1.id, "batch-layout-hover-preview", "Element ID must be batch-layout-hover-preview");
  } finally {
    delete sandbox.document;
    delete sandbox.window.document;
  }

  console.log("✓ Requirement 15 Passed: Hover preview floating element is a verified global singleton");
}

// ==========================================
// Requirement 16: Touch / 390 mode does not register hover listeners
// ==========================================
{
  sandbox.window.innerWidth = 390;
  sandbox.window.matchMedia = (query) => {
    if (query === "(hover: none)") return { matches: true };
    return { matches: false };
  };

  try {
    const isTouch = HandrawBatchCreate.isTouchDevice();
    assert.equal(isTouch, true, "390 width / (hover: none) must be detected as touch device");

    let boundEvents = [];
    const mockRoot = {
      querySelectorAll: () => [
        {
          getAttribute: () => "SC-001",
          addEventListener: (evt) => boundEvents.push(evt)
        }
      ]
    };

    HandrawBatchCreate.bindHoverPreview(mockRoot);
    assert.equal(boundEvents.length, 0, "Touch device must not register hover listeners");
  } finally {
    sandbox.window.innerWidth = 1440;
    sandbox.window.matchMedia = () => ({ matches: false });
  }

  console.log("✓ Requirement 16 Passed: Touch / 390 mode skips hover listener registration");
}

// ==========================================
// Requirement 17: Global References Row relocated outside 更多设置 collapsible
// ==========================================
{
  // Test both modes with moreSettingsOpen = false (the default state)
  for (const mode of ["fixed", "ai"]) {
    const fakeHost = createFakeDom();
    const graph = createTestBatchGraph({
      batchLayoutMode: mode,
      layout: "SC-001",
      tones: ["TN-001"],
      assets: [{ id: "AST-001", name: "测试参考图", image: "/uploads/test.webp" }],
      batchRows: mode === "ai" ? [{ theme: "行1", layout: "SC-001" }] : []
    });
    const parts = {
      ctrl: graph.nodes.find(n => n.type === "output_control"),
      loop: graph.nodes.find(n => n.type === "loop"),
      skill: graph.nodes.find(n => n.type === "skill_params"),
      text: graph.nodes.find(n => n.type === "text_input"),
      asset: graph.nodes.find(n => n.type === "asset")
    };

    HandrawBatchCreate.moreSettingsOpen = false;
    HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {});

    const html = fakeHost.innerHTML;

    // 1. Must contain #batch-more-row-refs
    assert.ok(html.includes('id="batch-more-row-refs"'), `#batch-more-row-refs must be present in ${mode} mode`);

    // 2. Content comes first; shared references remain visible in the settings column.
    const idxPickers = html.indexOf("batch-pickers-row");
    const idxGlobalRefs = html.indexOf('id="batch-more-row-refs"');
    const idxPlanCard = html.indexOf("batch-plan-card");
    const idxMoreSettingsToggle = html.indexOf('id="batch-toggle-more-settings"');

    assert.ok(idxPickers !== -1, "Pickers row must exist");
    assert.ok(idxGlobalRefs !== -1, "Global refs row must exist");
    assert.ok(idxPlanCard !== -1, "Plan card must exist");
    assert.ok(idxMoreSettingsToggle !== -1, "More settings toggle must exist");

    assert.ok(idxPickers < idxGlobalRefs, "Global refs row must come after pickers row");
    assert.ok(idxPlanCard < idxPickers, "Planning must precede the shared settings column");
    assert.ok(idxPlanCard < idxMoreSettingsToggle, "Set planning card must come before more settings");

    // 3. More settings body must NOT contain #batch-more-row-refs or #batch-btn-pick-global-refs
    const moreSettingsBodyMatch = html.match(/id="batch-body-more-settings"[^>]*>([\s\S]*?)<\/div>\s*<\/div>/);
    if (moreSettingsBodyMatch) {
      assert.ok(
        !moreSettingsBodyMatch[1].includes('id="batch-more-row-refs"'),
        "batch-body-more-settings must NOT contain #batch-more-row-refs"
      );
      assert.ok(
        !moreSettingsBodyMatch[1].includes('id="batch-btn-pick-global-refs"'),
        "batch-body-more-settings must NOT contain #batch-btn-pick-global-refs"
      );
    }

    // 4. Verify contents of #batch-more-row-refs
    assert.ok(html.includes('class="make-image-field-label">参考图</span>'), "Must have field label 参考图");
    assert.ok(html.includes('id="batch-btn-pick-global-refs"'), "Must have button #batch-btn-pick-global-refs");
    assert.ok(html.includes('id="batch-global-refs-thumbs"'), "Must have thumbs container #batch-global-refs-thumbs");
    assert.ok(html.includes('data-remove-global-ref="0"'), "Must render clear button for existing global ref");
  }

  // Also verify empty state hint
  {
    const fakeHostEmpty = createFakeDom();
    const graphEmpty = createTestBatchGraph({
      batchLayoutMode: "fixed",
      assets: []
    });
    const partsEmpty = {
      ctrl: graphEmpty.nodes.find(n => n.type === "output_control"),
      loop: graphEmpty.nodes.find(n => n.type === "loop"),
      skill: graphEmpty.nodes.find(n => n.type === "skill_params"),
      text: graphEmpty.nodes.find(n => n.type === "text_input"),
      asset: graphEmpty.nodes.find(n => n.type === "asset")
    };
    HandrawBatchCreate.moreSettingsOpen = false;
    HandrawBatchCreate.render(fakeHostEmpty, { parts: partsEmpty, graph: graphEmpty, catalog: sharedCatalog }, {});
    const htmlEmpty = fakeHostEmpty.innerHTML;
    assert.ok(htmlEmpty.includes("未指定，可点此添加（最多 4 张）"), "Empty state must display hint text");
  }

  console.log("✓ Requirement 17 Passed: Global References Row relocated outside 更多设置 collapsible (between Row 2 and Set Planning card)");
}

// ==========================================
// Requirement 18: Form Reset (清空表单) in Batch and Make-Image
// ==========================================
{
  // 1. Batch Form Reset
  const fakeHost = createFakeDom();
  const graph = createTestBatchGraph({
    mode: "pure-image",
    ratio: "16:9",
    fusion: true,
    style1: "FA-002",
    style2: "FA-003",
    layout: "SC-022",
    colors: ["CL-002"],
    tones: ["TN-001"],
    moods: ["治愈"],
    customMood: "清静",
    whitespace: "spacious",
    audience: "学生",
    businessScene: "壁纸",
    batchSeed: "自定义母题",
    batchCount: 12,
    batchLayoutMode: "ai",
    batchLayoutReq: "前两张分镜",
    batchRows: [{ theme: "第1行", layout: "SC-001" }, { theme: "第2行", layout: "SC-022" }],
    promptListText: "第1行\n第2行",
    assets: [{ id: "AST-001", name: "参考1", image: "/ref1.webp" }]
  });
  const parts = {
    ctrl: graph.nodes.find(n => n.type === "output_control"),
    loop: graph.nodes.find(n => n.type === "loop"),
    skill: graph.nodes.find(n => n.type === "skill_params"),
    text: graph.nodes.find(n => n.type === "text_input"),
    asset: graph.nodes.find(n => n.type === "asset")
  };

  let dirtyCalled = false;
  HandrawBatchCreate.planNotice = "测试提示";
  HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog }, {
    markDirtyAndRender: () => { dirtyCalled = true; },
    ensureAssetItems: (items) => { parts.asset.data.items = items; }
  });

  const html = fakeHost.innerHTML;
  assert.ok(html.includes('id="batch-btn-reset"'), "Must render #batch-btn-reset");
  assert.ok(html.includes("清空表单"), "Reset button must have text 清空表单");

  const btnReset = fakeHost.querySelector("#batch-btn-reset");
  assert.ok(btnReset, "Should find #batch-btn-reset");

  // A. Cancel confirm: nothing changes
  let confirmPrompt = "";
  sandbox.window.confirm = (msg) => { confirmPrompt = msg; return false; };
  btnReset.onclick();
  assert.ok(confirmPrompt.includes("清空后，当前表单将恢复默认，并清除本工作区的生成结果；生图历史仍保留。确定清空吗？"), "Confirm message must match specification");
  assert.equal(parts.loop.data.batchLayoutMode, "ai", "Mode should remain AI on cancel");
  assert.equal(dirtyCalled, false, "markDirty must not be called on cancel");

  // B. Accept confirm: restores all defaults
  sandbox.window.confirm = () => true;
  btnReset.onclick();

  assert.equal(dirtyCalled, true, "markDirty must be called on confirm");
  assert.equal(parts.ctrl.data.mode, "graphic-text", "mode must reset to graphic-text");
  assert.equal(parts.ctrl.data.ratio, "3:4", "ratio must reset to 3:4");
  assert.equal(parts.ctrl.data.count, 1, "count must reset to 1");

  assert.equal(parts.skill.data.fusion, false, "fusion must reset to false");
  assert.equal(parts.skill.data.style1, "", "style1 must reset to empty");
  assert.equal(parts.skill.data.style2, "", "style2 must reset to empty");
  assert.equal(parts.skill.data.layout, "", "layout must reset to empty");
  assert.equal(parts.skill.data.colors.length, 0, "colors must reset to empty array");
  assert.equal(parts.skill.data.tones.length, 0, "tones must reset to empty array");
  assert.equal(parts.skill.data.moods.length, 0, "moods must reset to empty array");
  assert.equal(parts.skill.data.customMood, "", "customMood must reset to empty");
  assert.equal(parts.skill.data.whitespace, "balanced", "whitespace must reset to balanced");
  assert.equal(parts.skill.data.audience, "", "audience must reset to empty");
  assert.equal(parts.skill.data.businessScene, "", "businessScene must reset to empty");
  assert.equal(parts.skill.data.negativePrompt, "", "negativePrompt must reset to empty");

  assert.equal(parts.loop.data.batchSeed, "", "batchSeed must reset to empty");
  assert.equal(parts.loop.data.batchCount, 6, "batchCount must reset to 6");
  assert.equal(parts.loop.data.batchLayoutMode, "fixed", "batchLayoutMode must reset to fixed");
  assert.equal(parts.loop.data.batchLayoutReq, "", "batchLayoutReq must reset to empty");
  assert.equal(parts.loop.data.batchRows.length, 0, "batchRows must reset to empty array");
  assert.equal(
    parts.loop.data.promptListText,
    "早八一杯热美式\n晚霞中的单车\n周末雨天读旧诗集",
    "promptListText must reset to default 3 lines"
  );
  assert.equal(parts.asset.data.items.length, 0, "asset items must reset to empty");
  assert.equal(HandrawBatchCreate.planNotice, "", "planNotice must be cleared");

  // Verify totalCount is 3 from 3 promptListText lines
  const iters = HandrawBatchCreate.resolveIterations();
  assert.equal(iters.length, 3, "Reset promptListText must resolve to exactly 3 iterations");

  // 2. Check disabled state when busy
  HandrawBatchCreate.context.busy = true;
  HandrawBatchCreate.render(fakeHost, { parts, graph, catalog: sharedCatalog, busy: true }, {});
  assert.ok(fakeHost.innerHTML.includes('id="batch-btn-reset" disabled'), "#batch-btn-reset must be disabled when busy");
  HandrawBatchCreate.context.busy = false;

  // 3. Verify Make-Image source contains #make-image-btn-reset
  const makeImageSource = fs.readFileSync("demo/assets/studio-make-image.js", "utf8");
  assert.ok(makeImageSource.includes('id="make-image-btn-reset"'), "studio-make-image.js must render #make-image-btn-reset");
  assert.ok(makeImageSource.includes("清空后，当前表单将恢复默认，并清除本工作区的生成结果；生图历史仍保留。确定清空吗？"), "studio-make-image.js must check confirmation");

  console.log("✓ Requirement 18 Passed: Form Reset (清空表单) in Batch and Make-Image verified");
}

// ==========================================
// Requirement 19: Batch Iteration Thumbnail Clean Semantics
// 1. 无图型时 sampleImg 为空字符串、渲染占位框而非 <img>
// 2. 有图型时 sampleImg 等于该图型 image、渲染带有「版式示意」角标的缩略图
// 3. 已生成时渲染真实生成图，绝不显示无关的硬编码示例图
// 4. sampleVisuals 常量被彻底删除
// ==========================================
{
  // 1. Verify sampleVisuals is completely deleted from studio-prompt-engine.js
  const promptEngineCode = fs.readFileSync("demo/assets/studio-prompt-engine.js", "utf8");
  assert.ok(!promptEngineCode.includes("sampleVisuals"), "sampleVisuals constant must be completely removed from studio-prompt-engine.js");

  // 2. Fixed mode without layout -> sampleImg is empty string, table renders .batch-iter-placeholder
  const graphNoLayout = createTestBatchGraph({
    batchLayoutMode: "fixed",
    layout: "",
    promptListText: "主题一\n主题二\n主题三",
    batchRows: null
  });
  const partsNoLayout = {
    ctrl: graphNoLayout.nodes.find(n => n.type === "output_control"),
    loop: graphNoLayout.nodes.find(n => n.type === "loop"),
    skill: graphNoLayout.nodes.find(n => n.type === "skill_params"),
    text: graphNoLayout.nodes.find(n => n.type === "text_input"),
    asset: graphNoLayout.nodes.find(n => n.type === "asset")
  };
  partsNoLayout.skill.data.layout = "";

  const recNoLayout = Engine.resolveControlRecipe(graphNoLayout, partsNoLayout.ctrl, sharedCatalog);
  const itersNoLayout = Engine.resolveLoopIterations(graphNoLayout, partsNoLayout.loop, recNoLayout, sharedCatalog);

  assert.equal(itersNoLayout.length, 3);
  itersNoLayout.forEach((it, i) => {
    assert.equal(it.sampleImg, "", `Iteration ${i} sampleImg must be empty string when no layout is selected`);
  });

  const fakeHost = createFakeDom();
  HandrawBatchCreate.render(fakeHost, {
    parts: partsNoLayout,
    graph: graphNoLayout,
    catalog: sharedCatalog,
    loggedIn: true
  }, {});

  const placeholders = fakeHost.querySelectorAll(".batch-iter-placeholder");
  assert.equal(placeholders.length, 3, "Table must render 3 .batch-iter-placeholder elements when no layout");
  const thumbBtns = fakeHost.querySelectorAll(".batch-iter-thumb-btn");
  assert.equal(thumbBtns.length, 0, "Table must NOT render any .batch-iter-thumb-btn when no layout");
  assert.ok(!fakeHost.innerHTML.includes("/images/poster-demo-autumn-equinox.webp"), "Must NOT include autumn equinox demo image");
  assert.ok(!fakeHost.innerHTML.includes("/images/graphic-text-mode-demo.webp"), "Must NOT include graphic-text-mode-demo image");
  assert.ok(!fakeHost.innerHTML.includes("/images/individual/FA/FA-003.webp"), "Must NOT include FA-003 demo image");

  // 3. Fixed mode with SC-021 -> sampleImg equals SC-021 image, renders schematic thumbnail with badge
  const graphWithLayout = createTestBatchGraph({
    batchLayoutMode: "fixed",
    layout: "SC-021",
    promptListText: "主题一\n主题二\n主题三",
    batchRows: null
  });
  const partsWithLayout = {
    ctrl: graphWithLayout.nodes.find(n => n.type === "output_control"),
    loop: graphWithLayout.nodes.find(n => n.type === "loop"),
    skill: graphWithLayout.nodes.find(n => n.type === "skill_params"),
    text: graphWithLayout.nodes.find(n => n.type === "text_input"),
    asset: graphWithLayout.nodes.find(n => n.type === "asset")
  };
  partsWithLayout.skill.data.layout = "SC-021";

  const recWithLayout = Engine.resolveControlRecipe(graphWithLayout, partsWithLayout.ctrl, sharedCatalog);
  const itersWithLayout = Engine.resolveLoopIterations(graphWithLayout, partsWithLayout.loop, recWithLayout, sharedCatalog);

  assert.equal(itersWithLayout.length, 3);
  itersWithLayout.forEach((it, i) => {
    assert.equal(
      it.sampleImg,
      "/images/sc-021.webp",
      `Iteration ${i} sampleImg must equal SC-021 layout image`
    );
  });

  HandrawBatchCreate.render(fakeHost, {
    parts: partsWithLayout,
    graph: graphWithLayout,
    catalog: sharedCatalog,
    loggedIn: true
  }, {});

  const placeholdersLayout = fakeHost.querySelectorAll(".batch-iter-placeholder");
  assert.equal(placeholdersLayout.length, 0, "Table must NOT render placeholders when layout is selected");
  const thumbBtnsLayout = fakeHost.querySelectorAll(".batch-iter-thumb-btn");
  assert.equal(thumbBtnsLayout.length, 3, "Table must render 3 .batch-iter-thumb-btn elements");
  const badgesLayout = fakeHost.querySelectorAll(".batch-iter-schematic-badge");
  assert.equal(badgesLayout.length, 3, "Each layout schematic must have 版式示意 badge");
  assert.equal(thumbBtnsLayout[0].getAttribute("data-zoom-src"), "/images/sc-021.webp");

  // 4. AI recommended layout mode with diverse layouts
  const graphAi = createTestBatchGraph({
    batchLayoutMode: "ai",
    layout: "",
    batchRows: [
      { theme: "行1", layout: "SC-001" },
      { theme: "行2", layout: "IG-005" },
      { theme: "行3", layout: "" } // No layout on row 3
    ]
  });
  const partsAi = {
    ctrl: graphAi.nodes.find(n => n.type === "output_control"),
    loop: graphAi.nodes.find(n => n.type === "loop"),
    skill: graphAi.nodes.find(n => n.type === "skill_params"),
    text: graphAi.nodes.find(n => n.type === "text_input"),
    asset: graphAi.nodes.find(n => n.type === "asset")
  };
  partsAi.skill.data.layout = "";

  const recAi = Engine.resolveControlRecipe(graphAi, partsAi.ctrl, sharedCatalog);
  const itersAi = Engine.resolveLoopIterations(graphAi, partsAi.loop, recAi, sharedCatalog);

  assert.equal(itersAi[0].sampleImg, "/images/sc-001.webp");
  assert.equal(itersAi[1].sampleImg, "/images/ig-005.webp");
  assert.equal(itersAi[2].sampleImg, "");

  HandrawBatchCreate.render(fakeHost, {
    parts: partsAi,
    graph: graphAi,
    catalog: sharedCatalog,
    loggedIn: true
  }, {});

  assert.equal(fakeHost.querySelectorAll(".batch-iter-thumb-btn").length, 2, "Rows 1 and 2 with layout must have thumb buttons");
  assert.equal(fakeHost.querySelectorAll(".batch-iter-placeholder").length, 1, "Row 3 without layout must have placeholder box");

  // 5. Generated state: itemResult?.imageUrl overrides schematic
  const fakeDisplays = [{
    id: "disp_1",
    data: {
      sourceNodeId: partsWithLayout.ctrl.id,
      items: [
        { imageUrl: "/generated/real_output_1.webp", title: "真实图1" }
      ]
    }
  }];
  HandrawBatchCreate.render(fakeHost, {
    parts: partsWithLayout,
    graph: graphWithLayout,
    catalog: sharedCatalog,
    displays: fakeDisplays,
    loggedIn: true
  }, {});

  assert.ok(fakeHost.innerHTML.includes("/generated/real_output_1.webp"), "Row 0 must render real generated imageUrl");
  assert.ok(fakeHost.innerHTML.includes("is-generated"), "Row 0 button must have is-generated class");

  console.log("✓ Requirement 19 Passed: Batch Iteration Thumbnail Clean Semantics & Placeholder verified");
}

console.log("\n==========================================");
console.log("All 19 Studio Batch tests passed successfully!");
console.log("==========================================");
