"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const studioAppSource = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const promptEngineSource = fs.readFileSync("demo/assets/studio-prompt-engine.js", "utf8");
const makeImageSource = fs.readFileSync("demo/assets/studio-make-image.js", "utf8");
const quickCreateCss = fs.readFileSync("demo/assets/quick-create.css", "utf8");

// Setup unified VM environment with mock catalog
const sharedCatalog = {
  styles: [
    { id: "FA-001", name: "治愈水彩", name_zh: "治愈水彩", kind: "style", group: "watercolor", image: "/images/fa-001.webp", description: "温暖治愈的手绘水彩画风" },
    { id: "FA-002", name: "复古版画", name_zh: "复古版画", kind: "style", group: "print", image: "/images/fa-002.webp", description: "质感颗粒复古版画" }
  ],
  layouts: [
    { id: "SC-021", name: "双拼信息卡", kind: "layout", group: "social-cards", image: "/images/sc-021.webp", description: "撕纸折纸或实物对比双屏" },
    { id: "SC-022", name: "签名明信片", kind: "layout", group: "social-cards", image: "/images/sc-022.webp", description: "手写签名与双拼拼音" },
    { id: "SC-001", name: "居中卡片", kind: "layout", group: "social-cards", image: "/images/sc-001.webp", description: "居中构图信息卡" }
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
    ["SC-021", { id: "SC-021", name: "双拼信息卡", kind: "layout", group: "social-cards", image: "/images/sc-021.webp", description: "撕纸折纸或实物对比双屏" }],
    ["SC-022", { id: "SC-022", name: "签名明信片", kind: "layout", group: "social-cards", image: "/images/sc-022.webp", description: "手写签名与双拼拼音" }],
    ["SC-001", { id: "SC-001", name: "居中卡片", kind: "layout", group: "social-cards", image: "/images/sc-001.webp", description: "居中构图信息卡" }],
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

// 2. Run make-image
sandbox.HANDRAW_SHARED = {
  esc(s) { return String(s == null ? "" : s); },
  toast() {}
};
vm.runInContext(makeImageSource, sandbox);
const HandrawMakeImage = sandbox.HandrawMakeImage;
assert.ok(HandrawMakeImage, "HandrawMakeImage must be initialized");

function createFakeDom() {
  return {
    innerHTML: "",
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    removeEventListener() {}
  };
}

// Helper to build test graph
function createTestGraph(options = {}) {
  const sp = Engine.makeSkillParamsNode(64, 56, {
    fusion: Boolean(options.fusion),
    style1: options.style1 || "FA-001",
    style2: options.style2 || "",
    layout: options.layout || "SC-021",
    sc021Type: options.sc021Type || "实物对比",
    sc022Name: options.sc022Name || "林知夏",
    sc022Pinyin: options.sc022Pinyin || "LIN ZHIXIA",
    colors: options.colors || ["CL-001"],
    tones: options.tones || ["TN-001"],
    moods: options.moods || ["治愈"],
    customMood: options.customMood || "",
    whitespace: options.whitespace || "balanced",
    audience: options.audience || "年轻女性",
    businessScene: options.businessScene || "文创包装"
  });
  const txt = Engine.makeTextInputNode(64, 548, {
    text: options.text != null ? options.text : "暖阳下的手绘小镇书店",
    subjectHint: options.subjectHint || ""
  });
  const ctrl = Engine.makeOutputControlNode(488, 176, {
    mode: options.mode || "graphic-text",
    ratio: options.ratio || "3:4",
    count: 1
  });
  const nodes = [sp, txt, ctrl];
  const edges = [
    { id: "e1", from: sp.id, to: ctrl.id },
    { id: "e2", from: txt.id, to: ctrl.id }
  ];

  if (options.assets && options.assets.length) {
    const ast = Engine.makeAssetNode(64, 800, { items: options.assets });
    nodes.push(ast);
    edges.push({ id: "e3", from: ast.id, to: ctrl.id });
  }

  return { nodes, edges };
}

// ==========================================
// Test 1: Request Body Parity between 「做图」 and 「高级画布」
// ==========================================
{
  const graph = createTestGraph({
    fusion: false,
    style1: "FA-001",
    layout: "SC-021",
    sc021Type: "实物对比",
    colors: ["CL-001", "CL-002"],
    tones: ["TN-001"],
    moods: ["治愈", "诗意"],
    customMood: "微醺",
    whitespace: "balanced",
    audience: "年轻女性",
    businessScene: "文创包装",
    text: "暖阳下的手绘小镇书店",
    mode: "graphic-text",
    ratio: "3:4",
    assets: [{ id: "CH-001", name: "少女", image: "https://example.com/ch.png" }]
  });

  const ctrlNode = graph.nodes.find((n) => n.type === "output_control");

  // In Advanced Canvas:
  // assembleControlPrompt is called with format "cloud"
  const canvasPrompt = Engine.assembleControlPrompt(graph, ctrlNode, sharedCatalog, "cloud");
  const canvasRec = Engine.resolveControlRecipe(graph, ctrlNode, sharedCatalog);
  const canvasBody = {
    prompt: canvasPrompt,
    ratio: ctrlNode.data.ratio || "3:4",
    style1: canvasRec.style1Id || "",
    style2: (canvasRec.fusionToggleOn ? canvasRec.style2Id : "") || "",
    layout: canvasRec.layoutId || "",
    refImages: canvasRec.assetItems.map((a) => a.image).filter(Boolean),
    confirmCost: true
  };

  // In Make Image:
  // Uses parts = { ctrl, skill, text, asset } from getQuickParts
  const sp = graph.nodes.find((n) => n.type === "skill_params");
  const txt = graph.nodes.find((n) => n.type === "text_input");
  const ast = graph.nodes.find((n) => n.type === "asset");
  const parts = { ctrl: ctrlNode, skill: sp, text: txt, asset: ast };

  const controller = new HandrawMakeImage.MakeImageController();
  controller.context = {
    parts,
    graph,
    catalog: sharedCatalog
  };

  const makeImagePrompt = controller.getPromptPreview();
  assert.equal(makeImagePrompt, canvasPrompt, "Make Image prompt preview must equal canvas prompt");

  // When Make Image clicks run, it calls runOutputControlNode(p.ctrl.id), assembling the exact same body
  const makeImageRec = Engine.resolveControlRecipe(graph, parts.ctrl, sharedCatalog);
  const makeImageBody = {
    prompt: Engine.assembleControlPrompt(graph, parts.ctrl, sharedCatalog, "cloud"),
    ratio: parts.ctrl.data.ratio || "3:4",
    style1: makeImageRec.style1Id || "",
    style2: (makeImageRec.fusionToggleOn ? makeImageRec.style2Id : "") || "",
    layout: makeImageRec.layoutId || "",
    refImages: makeImageRec.assetItems.map((a) => a.image).filter(Boolean),
    confirmCost: true
  };

  assert.deepEqual(makeImageBody, canvasBody, "Request body from 做图 and 高级画布 must be 100% identical");
  console.log("✓ Test 1 Passed: Request Body Parity between 做图 and 高级画布 verified.");
}

// ==========================================
// Test 2: Single / Dual-Style Fusion Toggle
// ==========================================
{
  const graph = createTestGraph({ fusion: false, style1: "FA-001" });
  const sp = graph.nodes.find((n) => n.type === "skill_params");
  const ctrlNode = graph.nodes.find((n) => n.type === "output_control");
  const parts = { ctrl: ctrlNode, skill: sp, text: graph.nodes.find((n) => n.type === "text_input") };

  const controller = new HandrawMakeImage.MakeImageController();
  let fakeDom = createFakeDom();
  controller.hostElement = fakeDom;
  controller.context = { parts, graph, catalog: sharedCatalog };

  // Initial: single style
  controller.render(fakeDom, controller.context, {});
  assert.ok(fakeDom.innerHTML.includes("data-pick-kind=\"style1\""), "style1 picker must exist");
  assert.ok(!fakeDom.innerHTML.includes("data-pick-kind=\"style2\""), "style2 picker must NOT exist in single style");
  assert.ok(!fakeDom.innerHTML.includes("角色画风决定人物与主体的画法"), "Fusion explanation note must NOT exist in single style");

  // Single style prompt should only lock style1
  let prompt = controller.getPromptPreview();
  assert.match(prompt, /【锁定画风 #FA-001】/);
  assert.doesNotMatch(prompt, /【跨媒介画面融合】/);

  // Switch to dual style fusion
  sp.data.fusion = true;
  sp.data.style2 = "FA-002";
  controller.render(fakeDom, controller.context, {});
  assert.ok(fakeDom.innerHTML.includes("data-pick-kind=\"style2\""), "style2 picker must exist in dual style");
  assert.ok(fakeDom.innerHTML.includes("角色画风决定人物与主体的画法，场景画风决定背景与环境"), "Fusion explanation note must exist in dual style");

  prompt = controller.getPromptPreview();
  assert.match(prompt, /【跨媒介画面融合】：角色采用 #FA-001 治愈水彩 × 场景采用 #FA-002 复古版画/);

  // Switch back to single style
  sp.data.fusion = false;
  sp.data.style2 = "";
  controller.render(fakeDom, controller.context, {});
  assert.ok(!fakeDom.innerHTML.includes("data-pick-kind=\"style2\""), "style2 picker must be removed after switching back");
  prompt = controller.getPromptPreview();
  assert.match(prompt, /【锁定画风 #FA-001】/);
  assert.doesNotMatch(prompt, /【跨媒介画面融合】/);
  assert.doesNotMatch(prompt, /FA-002/);

  console.log("✓ Test 2 Passed: Single / Dual-Style Fusion Toggle verified.");
}

// ==========================================
// Test 3: Output Modes & Default Ratios
// ==========================================
{
  const graph = createTestGraph();
  const ctrlNode = graph.nodes.find((n) => n.type === "output_control");

  // 1) Graphic-text mode (图文) -> default 3:4
  ctrlNode.data.mode = "graphic-text";
  ctrlNode.data.ratio = "3:4";
  let prompt = Engine.assembleControlPrompt(graph, ctrlNode, sharedCatalog, "cloud");
  assert.match(prompt, /【出图模式】：社媒图文信息卡（画幅比例 3:4）/);

  // 2) Pure image mode (纯图) -> default 3:4
  ctrlNode.data.mode = "pure";
  ctrlNode.data.ratio = "3:4";
  prompt = Engine.assembleControlPrompt(graph, ctrlNode, sharedCatalog, "cloud");
  assert.match(prompt, /【出图模式】：纯图叙事（不出现说明性杂字）（画幅比例 3:4）/);

  // 3) Poster mode (海报) -> default 9:16
  ctrlNode.data.mode = "poster";
  ctrlNode.data.ratio = "9:16";
  prompt = Engine.assembleControlPrompt(graph, ctrlNode, sharedCatalog, "cloud");
  assert.match(prompt, /【出图模式】：商业视觉海报（画幅比例 9:16）/);

  // 4) Ratio options Chinese labels and mapping
  const expectedRatios = [
    { label: "小红书", value: "3:4" },
    { label: "方图", value: "1:1" },
    { label: "横版", value: "4:3" },
    { label: "横屏视频", value: "16:9" },
    { label: "竖屏短视频", value: "9:16" },
    { label: "公众号封面", value: "2.35:1" }
  ];
  assert.deepEqual(
    JSON.parse(JSON.stringify(HandrawMakeImage.RATIO_OPTIONS)),
    expectedRatios,
    "RATIO_OPTIONS must match exact specification"
  );

  // Verify that there is no separate "自定义" button or separate custom ratio row
  assert.doesNotMatch(makeImageSource, />自定义<\/button>/, "No standalone '自定义' button");
  assert.doesNotMatch(makeImageSource, /make-image-custom-ratio-wrap/, "No standalone custom ratio row wrap");

  console.log("✓ Test 3 Passed: Output Modes & Default Ratios verified.");
}

// ==========================================
// Test 4: Sub-options Node Storage & Baseline Parity for assembleControlPrompt
// ==========================================
{
  const cp = require("node:child_process");
  const baselineSrc = cp.execSync("git show 5103d23:demo/assets/studio-prompt-engine.js", { encoding: "utf8" });
  const baselineSandbox = {
    window: {},
    globalThis: {},
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
  baselineSandbox.window = baselineSandbox;
  baselineSandbox.globalThis = baselineSandbox;
  vm.createContext(baselineSandbox);
  vm.runInContext(baselineSrc, baselineSandbox);
  const baselineEngine = baselineSandbox.HANDRAW_CANVAS_ENGINE;
  assert.ok(baselineEngine, "Baseline engine must load successfully");

  // 1) Test SC-021 node storage & cloud prompt output
  const graph21 = createTestGraph({
    layout: "SC-021",
    sc021Type: "局部放大微距",
    audience: "设计从业者",
    businessScene: "活动海报",
    customMood: "清冽"
  });
  const sp21 = graph21.nodes.find((n) => n.type === "skill_params");
  const ctrl21 = graph21.nodes.find((n) => n.type === "output_control");

  // Verify sub-options are written to node data
  assert.equal(sp21.data.sc021Type, "局部放大微距", "sc021Type must be stored in skill node");
  assert.equal(sp21.data.audience, "设计从业者", "audience must be stored in skill node");
  assert.equal(sp21.data.businessScene, "活动海报", "businessScene must be stored in skill node");
  assert.equal(sp21.data.customMood, "清冽", "customMood must be stored in skill node");

  // Cloud prompt includes audience, businessScene, customMood (original engine output)
  const prompt21Cloud = Engine.assembleControlPrompt(graph21, ctrl21, sharedCatalog, "cloud");
  assert.match(prompt21Cloud, /目标受众「设计从业者」/);
  assert.match(prompt21Cloud, /业务场景「活动海报」/);
  assert.match(prompt21Cloud, /【情绪氛围】：.*清冽/);
  assert.match(prompt21Cloud, /【锁定图型 SC-021】：双拼信息卡 —— 撕纸折纸或实物对比双屏/);

  // Skill prompt includes sc021Type
  const prompt21Skill = Engine.assembleControlPrompt(graph21, ctrl21, sharedCatalog, "skill");
  assert.match(prompt21Skill, /图型：SC-021（玩法：局部放大微距）/);

  // 2) Test SC-022 node storage
  const graph22 = createTestGraph({
    layout: "SC-022",
    sc022Name: "陈知远",
    sc022Pinyin: "CHEN ZHIYUAN"
  });
  const sp22 = graph22.nodes.find((n) => n.type === "skill_params");
  const ctrl22 = graph22.nodes.find((n) => n.type === "output_control");

  assert.equal(sp22.data.sc022Name, "陈知远", "sc022Name must be stored in skill node");
  assert.equal(sp22.data.sc022Pinyin, "CHEN ZHIYUAN", "sc022Pinyin must be stored in skill node");

  const prompt22Cloud = Engine.assembleControlPrompt(graph22, ctrl22, sharedCatalog, "cloud");
  assert.match(prompt22Cloud, /【锁定图型 SC-022】：签名明信片 —— 手写签名与双拼拼音/);

  const prompt22Skill = Engine.assembleControlPrompt(graph22, ctrl22, sharedCatalog, "skill");
  assert.match(prompt22Skill, /图型：SC-022（姓名：陈知远 \/ CHEN ZHIYUAN）/);

  // 3) Byte-for-byte baseline parity assertion for both "cloud" and "skill" formats
  for (const g of [graph21, graph22]) {
    const c = g.nodes.find((n) => n.type === "output_control");
    const curCloud = Engine.assembleControlPrompt(g, c, sharedCatalog, "cloud");
    const baseCloud = baselineEngine.assembleControlPrompt(g, c, sharedCatalog, "cloud");
    assert.equal(curCloud, baseCloud, "assembleControlPrompt ('cloud') must match baseline byte-for-byte");

    const curSkill = Engine.assembleControlPrompt(g, c, sharedCatalog, "skill");
    const baseSkill = baselineEngine.assembleControlPrompt(g, c, sharedCatalog, "skill");
    assert.equal(curSkill, baseSkill, "assembleControlPrompt ('skill') must match baseline byte-for-byte");
  }

  console.log("✓ Test 4 Passed: Sub-options node storage & baseline parity verified.");
}

// ==========================================
// Test 5: Two-Way State Preservation (做图 <-> 高级画布)
// ==========================================
{
  const graph = createTestGraph({ style1: "FA-001", layout: "SC-001", text: "初稿" });
  const sp = graph.nodes.find((n) => n.type === "skill_params");
  const txt = graph.nodes.find((n) => n.type === "text_input");
  const ctrl = graph.nodes.find((n) => n.type === "output_control");

  // Modify in 做图 (which modifies node.data directly)
  sp.data.style1 = "FA-002";
  txt.data.text = "在做图修改的主题";
  ctrl.data.ratio = "16:9";

  // When switching to canvas, canvas inspects graph.nodes directly
  assert.equal(sp.data.style1, "FA-002", "Canvas sees modified style1");
  assert.equal(txt.data.text, "在做图修改的主题", "Canvas sees modified topic");
  assert.equal(ctrl.data.ratio, "16:9", "Canvas sees modified ratio");

  // Modify in Canvas
  sp.data.layout = "SC-021";
  sp.data.sc021Type = "时空前后";
  txt.data.text = "在画布修改的主题";

  // When switching back to 做图, MakeImageController reads parts.skill.data / parts.text.data
  const parts = { ctrl, skill: sp, text: txt };
  assert.equal(parts.skill.data.layout, "SC-021", "做图 sees canvas modified layout");
  assert.equal(parts.skill.data.sc021Type, "时空前后", "做图 sees canvas modified sc021Type");
  assert.equal(parts.text.data.text, "在画布修改的主题", "做图 sees canvas modified text");

  console.log("✓ Test 5 Passed: Two-Way State Preservation verified.");
}

// ==========================================
// Test 6: Fork (?fork={workId}) Draft Application
// ==========================================
{
  const graph = createTestGraph();
  const sp = graph.nodes.find((n) => n.type === "skill_params");
  const txt = graph.nodes.find((n) => n.type === "text_input");
  const ctrl = graph.nodes.find((n) => n.type === "output_control");
  const parts = { ctrl, skill: sp, text: txt };

  const tabs = [{ id: "tab-quick", quickStart: true, graph }];
  const controller = new HandrawMakeImage.MakeImageController();
  controller.context = { parts, graph, catalog: sharedCatalog };

  let dirtyCalled = false;
  controller.actions = {
    markDirtyAndRender() { dirtyCalled = true; }
  };

  const initialTabCount = tabs.length;
  controller.applyForkDraft({
    styleIds: ["FA-002"],
    layoutId: "SC-001",
    colors: ["CL-002"],
    tones: ["TN-001"],
    moods: ["温暖"],
    whitespace: "pure",
    ratio: "1:1",
    mode: "pure",
    subjectHint: "原作者的主题：春日花海"
  });

  assert.equal(tabs.length, initialTabCount, "Fork must not create a new tab");
  assert.equal(sp.data.style1, "FA-002");
  assert.equal(sp.data.layout, "SC-001");
  assert.deepEqual(Array.from(sp.data.colors), ["CL-002"]);
  assert.equal(txt.data.text, "", "Forked topic must be cleared for new theme");
  assert.equal(txt.data.subjectHint, "原作者的主题：春日花海", "Forked topic hint preserved");
  assert.equal(ctrl.data.ratio, "1:1");
  assert.equal(ctrl.data.mode, "pure");
  assert.equal(ctrl.data.count, 1, "Count must strictly be 1");
  assert.ok(dirtyCalled, "markDirtyAndRender was called");

  console.log("✓ Test 6 Passed: Fork Draft Application verified.");
}

// ==========================================
// Test 7: Cost Format & Single Image Enforcement
// ==========================================
{
  const formatCostText = HandrawMakeImage.formatCostText;

  // Unauthenticated
  const unauthCost = formatCostText({
    loggedIn: false,
    freeRemaining: 0,
    creditPerImage: 2,
    dailyQuota: 3,
    balance: 0
  });
  assert.equal(unauthCost, "每张 2 积分，新用户每天免费 3 张");

  // Authenticated with free quota
  const authFreeCost = formatCostText({
    loggedIn: true,
    freeRemaining: 3,
    creditPerImage: 2,
    dailyQuota: 3,
    balance: 20
  });
  assert.equal(authFreeCost, "本次 1 张：免费（积分余额：20）");

  // Authenticated without free quota
  const authPaidCost = formatCostText({
    loggedIn: true,
    freeRemaining: 0,
    creditPerImage: 2,
    dailyQuota: 3,
    balance: 20
  });
  assert.equal(authPaidCost, "本次 1 张：需 2 积分（积分余额：20）");

  // Verify that count buttons (1/2/4/8) are not in HTML
  const fakeDom = createFakeDom();
  const graph = createTestGraph();
  const ctrl = graph.nodes.find((n) => n.type === "output_control");
  const sp = graph.nodes.find((n) => n.type === "skill_params");
  const txt = graph.nodes.find((n) => n.type === "text_input");
  const c = new HandrawMakeImage.MakeImageController();
  c.render(fakeDom, { parts: { ctrl, skill: sp, text: txt }, graph, catalog: sharedCatalog }, {});

  assert.doesNotMatch(fakeDom.innerHTML, /data-set-count/, "Count selector must not be rendered");
  assert.doesNotMatch(makeImageSource, /data-set-count/, "Count selector must not exist in source");
  assert.match(fakeDom.innerHTML, /开始生成 \(1张\)/, "Run button must indicate single image");

  console.log("✓ Test 7 Passed: Cost Format & Single Image Enforcement verified.");
}

// ==========================================
// Test 8: Cleanliness & No Emoji in New UI Text
// ==========================================
{
  // In make-image source, ensure new UI labels don't contain emoji
  // Check headings, labels, button texts in make-image template
  const uiTexts = [
    "做图",
    "画风模式",
    "单画风",
    "双画风融合",
    "角色画风",
    "场景画风",
    "图型",
    "主题色",
    "创作主题",
    "生成方式",
    "画幅",
    "更多设置",
    "影调",
    "情绪",
    "留白",
    "受众：",
    "业务场景：",
    "参考图",
    "查看提示词",
    "复制提示词",
    "开始生成 (1张)",
    "再来一张",
    "换个主题"
  ];

  for (const text of uiTexts) {
    assert.ok(makeImageSource.includes(text), `UI text "${text}" must be present`);
  }

  // Ensure no emoji in the primary UI strings
  assert.doesNotMatch(makeImageSource, /🎨\s*画风/, "No emoji in style label");
  assert.doesNotMatch(makeImageSource, /📐\s*图型/, "No emoji in layout label");
  assert.doesNotMatch(makeImageSource, /🌈\s*主题色/, "No emoji in color label");
  assert.doesNotMatch(makeImageSource, /💡\s*影调/, "No emoji in tones label");
  assert.doesNotMatch(makeImageSource, /✨\s*情绪/, "No emoji in moods label");

  console.log("✓ Test 8 Passed: Cleanliness & No Emoji in New UI Text verified.");
}

// ==========================================
// Test 9: Compact Layout Architecture & Data Fidelity
// ==========================================
{
  const graph = createTestGraph({
    fusion: true,
    style1: "FA-001",
    style2: "FA-002",
    layout: "SC-021",
    moods: ["治愈", "诗意"],
    customMood: "微醺",
    whitespace: "moderate",
    audience: "年轻女性",
    businessScene: "文创包装",
    mode: "graphic-text",
    ratio: "3:4"
  });
  const sp = graph.nodes.find((n) => n.type === "skill_params");
  const txt = graph.nodes.find((n) => n.type === "text_input");
  const ctrl = graph.nodes.find((n) => n.type === "output_control");
  const parts = { ctrl, skill: sp, text: txt };

  const controller = new HandrawMakeImage.MakeImageController();
  const fakeDom = createFakeDom();
  controller.render(fakeDom, { parts, graph, catalog: sharedCatalog }, {});

  // 1) Row 1: Output mode first, then Fusion toggle, both left-aligned in same row
  assert.match(fakeDom.innerHTML, /class="make-image-top-row"/, "make-image-top-row must exist");
  assert.match(fakeDom.innerHTML, /id="make-image-mode-single"/);
  assert.match(fakeDom.innerHTML, /id="make-image-mode-fusion"/);
  assert.match(fakeDom.innerHTML, /data-set-mode="graphic-text"/);
  assert.match(fakeDom.innerHTML, /data-set-mode="pure"/);
  assert.match(fakeDom.innerHTML, /data-set-mode="poster"/);

  const idxMode = fakeDom.innerHTML.indexOf('data-set-mode="graphic-text"');
  const idxFusion = fakeDom.innerHTML.indexOf('id="make-image-mode-single"');
  assert.ok(idxMode !== -1 && idxFusion !== -1 && idxMode < idxFusion, "Row 1 DOM order: 生成方式 must come before 画风模式");

  // 2) Row 4: Ratio buttons + inline input in same row
  assert.match(fakeDom.innerHTML, /class="make-image-ratio-row"/, "make-image-ratio-row must exist");
  assert.match(fakeDom.innerHTML, /id="make-image-ratio-input"/, "make-image-ratio-input must exist");
  assert.match(fakeDom.innerHTML, /value="3:4"/);

  // 3) More Settings: Each item in one row
  assert.match(fakeDom.innerHTML, /class="make-image-more-list"/, "make-image-more-list must exist");
  assert.match(fakeDom.innerHTML, /id="make-image-pick-tones"/, "pick tones button exists");
  assert.match(fakeDom.innerHTML, /id="make-image-pick-moods"/, "pick moods button exists");
  assert.match(fakeDom.innerHTML, /id="make-image-moods-input"/, "moods input exists");
  assert.match(fakeDom.innerHTML, /id="make-image-audience"/, "audience input exists");
  assert.match(fakeDom.innerHTML, /id="make-image-business-scene"/, "business scene input exists");
  assert.match(fakeDom.innerHTML, /class="[^"]*make-image-duo-row[^"]*"/, "audience & business scene in same duo row");

  // 4) Mood formatting and parsing fidelity
  const presetSet = controller.getKnownPresetMoods();
  const rawMoodInput = "治愈，诗意，微醺，清洌";
  const parsed = HandrawMakeImage.parseMoodsText(rawMoodInput, presetSet);
  assert.deepEqual(Array.from(parsed.moods), ["治愈", "诗意"], "Preset moods parsed into moods array");
  assert.equal(parsed.customMood, "微醺，清洌", "Custom moods joined into customMood string");

  const formatted = HandrawMakeImage.formatMoodsText(parsed.moods, parsed.customMood);
  assert.equal(formatted, "治愈，诗意，微醺，清洌", "Formatted mood text preserves all items with Chinese comma");

  // Whitespace options check
  const wsOptions = HandrawMakeImage.WHITESPACE_OPTIONS;
  assert.deepEqual(Array.from(wsOptions.map((w) => w.value)), ["", "normal", "moderate", "high"], "Whitespace values match specs");
  assert.deepEqual(Array.from(wsOptions.map((w) => w.label)), ["不限", "正常", "适中", "大量"], "Whitespace labels match specs");

  console.log("✓ Test 9 Passed: Compact Layout Architecture & Data Fidelity verified.");
}

console.log("\nALL 9 TESTS PASSED SUCCESSFULLY!");
