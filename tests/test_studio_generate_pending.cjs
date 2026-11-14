"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const studioSrc = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const sharedSrc = fs.readFileSync("demo/assets/shared.js", "utf8");

const makeNode = () => ({
  id: "",
  className: "",
  innerHTML: "",
  value: "",
  textContent: "",
  children: [],
  style: {},
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  dataset: {},
  append() {},
  prepend() {},
  appendChild() {},
  insertAdjacentElement() {},
  addEventListener() {},
  removeEventListener() {},
  setAttribute() {},
  getAttribute() { return null; },
  remove() {},
  querySelectorAll() { return []; },
  querySelector() { return null; },
  getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 }; }
});

const doc = {
  getElementById() { return makeNode(); },
  body: { prepend() {}, append() {}, children: [] },
  createElement() { return makeNode(); },
  querySelectorAll() { return []; },
  querySelector() { return null; },
  addEventListener() {}
};

const win = {
  location: { hostname: "localhost", port: "3080", protocol: "http:", search: "" },
  addEventListener() {},
  confirm: () => true,
  __HANDRAW_TESTING__: true
};

const storage = new Map();
let fetchHandler = null;
let toasts = [];

let suppressBootLog = true;

const context = {
  window: win,
  document: doc,
  localStorage: {
    getItem(k) { return storage.get(k) || null; },
    setItem(k, v) { storage.set(k, String(v)); },
    removeItem(k) { storage.delete(k); }
  },
  sessionStorage: {
    getItem() { return null; },
    setItem() {},
    removeItem() {}
  },
  URLSearchParams,
  setTimeout: (fn, ms) => setTimeout(fn, 0),
  clearTimeout,
  setInterval: (fn, ms) => setInterval(fn, 10),
  clearInterval,
  requestAnimationFrame(fn) { return setTimeout(fn, 0); },
  cancelAnimationFrame(id) { clearTimeout(id); },
  fetch: (url, opts) => fetchHandler(url, opts),
  console: {
    log: (...args) => console.log(...args),
    warn: (...args) => console.warn(...args),
    error: (...args) => {
      if (String(args[0]).includes("Boot Error")) return;
      console.error(...args);
    }
  }
};

vm.createContext(context);
vm.runInContext(sharedSrc, context);

win.HANDRAW_SHARED.toast = (msg) => toasts.push(msg);

win.HANDRAW_SHARED.App.state = {
  loggedIn: true,
  user: { id: 1, username: "tester", role: "user" },
  credits: 100,
  freeQuotaRemaining: 3
};

win.HANDRAW_CANVAS_ENGINE = {
  OUTPUT_MODES: [{ id: "single", label: "单图直出" }],
  createDefaultState() { return { nodes: [], edges: [] }; },
  uid(p) { return p + "_" + Math.random().toString(36).slice(2, 6); },
  resolveControlRecipe() {
    return {
      audience: "",
      businessScene: "",
      assetItems: [],
      colorIds: [],
      toneIds: [],
      allMoods: [],
      combinedText: "canvas text"
    };
  },
  assembleControlPrompt() { return "mock canvas prompt"; },
  makeOutputDisplayNode(x, y, data) {
    return {
      id: "disp_" + Math.random().toString(36).slice(2, 6),
      type: "output_display",
      x,
      y,
      w: 308,
      h: 308,
      data: data || {}
    };
  }
};

fetchHandler = async (url) => {
  if (url.includes("/api/boot")) return { ok: true, status: 200, json: async () => ({ user: { loggedIn: true }, credits: 100, freeQuotaRemaining: 3 }) };
  if (url.includes("/api/studio/workspace")) return { ok: true, status: 200, json: async () => ({}) };
  if (url.includes("/api/studio/config")) return { ok: true, status: 200, json: async () => ({ liveImageEnabled: true }) };
  return { ok: true, status: 200, json: async () => ({}) };
};

win.HandrawEconomy={confirm:async(items)=>({quoteId:'fixture-quote',totalCents:0,items:items.map(item=>({spec:{id:'standard-1k'},free:true}))})};
vm.runInContext(studioSrc, context);

const {
  generateSinglePlanCard,
  runOutputControlNode,
  setPrivateState,
  resumePendingCloudTasks,
  getTabs,
  getGraph
} = win.HANDRAW_STUDIO_TESTING;

(async () => {
  setPrivateState({ engineMode: "api", serverCfg: { liveImageEnabled: true } });

  // -------------------------------------------------------------
  // Test 1: Article card generation with 202 response and polling
  // -------------------------------------------------------------
  toasts.length = 0;
  const planNode1 = {
    id: "plan_node_1",
    type: "article_plan",
    x: 100, y: 100, w: 300, h: 300,
    data: {
      cards: [
        { id: "card_1", title: "文章封面", prompt: "A dragon", status: "ready", imageUrl: "", taskId: "" }
      ]
    }
  };
  planNode1.data.id = "article_1";
  const target1 = { planNode: planNode1, art: planNode1.data, isActiveCanvas: false };
  setPrivateState({myArticles: [target1.art]});

  let pollCount1 = 0;
  fetchHandler = async (url) => {
    if (url.includes("/api/studio/generate")) {
      return {
        ok: true,
        status: 202,
        json: async () => ({
          ok: true,
          status: "running",
          taskId: "",
          requestId: "req_article_1"
        })
      };
    }
    if (url.includes("/api/studio/tasks")) {
      pollCount1++;
      assert.ok(url.includes("requestId=req_article_1"), "Poll must include requestId");
      if (pollCount1 === 1) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ status: "running", taskId: "", requestId: "req_article_1" })
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          taskId: "task_art_done",
          requestId: "req_article_1",
          images: ["/images/card-dragon.webp"]
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res1 = await generateSinglePlanCard(target1, "card_1", {skipCostConfirmation:true});
  assert.equal(res1, true);
  assert.equal(pollCount1, 2, "Should poll twice before succeeding");
  const card1 = planNode1.data.cards[0];
  assert.equal(card1.status, "done");
  assert.equal(card1.imageUrl, "/images/card-dragon.webp");
  assert.ok(toasts.some((t) => t.includes("已生成「文章封面」")), `Toast should confirm generation, got: ${toasts}`);

  // -------------------------------------------------------------
  // Test 2: Article card failure when poll times out / fails
  // -------------------------------------------------------------
  toasts.length = 0;
  const planNode2 = {
    id: "plan_node_2",
    type: "article_plan",
    x: 100, y: 100, w: 300, h: 300,
    data: {
      cards: [
        { id: "card_2", title: "文章配图", prompt: "Phoenix", status: "ready", imageUrl: "", taskId: "" }
      ]
    }
  };
  planNode2.data.id = "article_2";
  const target2 = { planNode: planNode2, art: planNode2.data, isActiveCanvas: false };
  setPrivateState({myArticles: [target2.art]});

  fetchHandler = async (url) => {
    if (url.includes("/api/studio/generate")) {
      return {
        ok: true,
        status: 202,
        json: async () => ({ ok: true, status: "running", taskId: "", requestId: "req_article_2" })
      };
    }
    if (url.includes("/api/studio/tasks")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ status: "failed", error: "云端配图生图失败" })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res2 = await generateSinglePlanCard(target2, "card_2", {skipCostConfirmation:true});
  assert.equal(res2, false);
  const card2 = planNode2.data.cards[0];
  assert.equal(card2.status, "error");
  assert.equal(card2.imageUrl, "");
  assert.ok(!toasts.some((t) => t.includes("已生成")), "Must NOT toast success on failure");
  assert.ok(toasts.some((t) => t.includes("配图生成失败")), "Must toast error");

  // -------------------------------------------------------------
  // Test 3: Article card response with neither image nor taskId/requestId
  // -------------------------------------------------------------
  toasts.length = 0;
  const planNode3 = {
    id: "plan_node_3",
    type: "article_plan",
    x: 100, y: 100, w: 300, h: 300,
    data: {
      cards: [
        { id: "card_3", title: "无编号卡片", prompt: "Void", status: "ready", imageUrl: "", taskId: "" }
      ]
    }
  };
  planNode3.data.id = "article_3";
  const target3 = { planNode: planNode3, art: planNode3.data, isActiveCanvas: false };
  setPrivateState({myArticles: [target3.art]});

  fetchHandler = async (url) => {
    if (url.includes("/api/studio/generate")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, status: "queued", taskId: "", requestId: "" })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res3 = await generateSinglePlanCard(target3, "card_3", {skipCostConfirmation:true});
  assert.equal(res3, false);
  const card3 = planNode3.data.cards[0];
  assert.equal(card3.status, "error");
  assert.equal(card3.imageUrl, "");
  assert.ok(!toasts.some((t) => t.includes("已生成")), "Must NOT toast success on invalid response");

  // -------------------------------------------------------------
  // Test 4: Canvas / Form path (runOutputControlNode) 202 pending -> poll success
  // -------------------------------------------------------------
  toasts.length = 0;
  const ctrlNode1 = {
    id: "ctrl_1",
    type: "output_control",
    x: 100, y: 100, w: 344, h: 300,
    data: {
      status: "idle",
      mode: "single",
      ratio: "3:4",
      prompt: "canvas prompt"
    }
  };
  const dispNode1 = {
    id: "disp_1",
    type: "output_display",
    x: 540, y: 100, w: 308, h: 308,
    data: {
      status: "idle",
      sourceNodeId: "ctrl_1",
      items: []
    }
  };

  setPrivateState({
    activeTabId: "tab_1",
    tabs: [
      {
        id: "tab_1",
        title: "Tab 1",
        graph: {
          nodes: [ctrlNode1, dispNode1],
          edges: [{ from: "ctrl_1", to: "disp_1" }]
        }
      }
    ],
    graph: {
      nodes: [ctrlNode1, dispNode1],
      edges: [{ from: "ctrl_1", to: "disp_1" }]
    }
  });

  let pollCount4 = 0;
  fetchHandler = async (url) => {
    if (url.includes("/api/studio/generate")) {
      return {
        ok: true,
        status: 202,
        json: async () => ({
          ok: true,
          status: "running",
          taskId: "",
          requestId: "req_canvas_1"
        })
      };
    }
    if (url.includes("/api/studio/tasks")) {
      pollCount4++;
      assert.ok(url.includes("requestId=req_canvas_1"), "Poll must include requestId for canvas");
      if (pollCount4 === 1) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ status: "running", taskId: "", requestId: "req_canvas_1" })
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          taskId: "task_canvas_done",
          requestId: "req_canvas_1",
          images: ["/images/canvas-result.webp"]
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res4 = await runOutputControlNode("ctrl_1");
  assert.equal(res4, true);
  assert.equal(pollCount4, 2);
  assert.equal(ctrlNode1.data.status, "done");
  assert.equal(dispNode1.data.status, "done");
  assert.equal(dispNode1.data.items[0].imageUrl, "/images/canvas-result.webp");

  // -------------------------------------------------------------
  // Test 5: Canvas / Form path failure when poll fails
  // -------------------------------------------------------------
  toasts.length = 0;
  const ctrlNode2 = {
    id: "ctrl_2",
    type: "output_control",
    x: 100, y: 100, w: 344, h: 300,
    data: {
      status: "idle",
      mode: "single",
      ratio: "3:4",
      prompt: "canvas prompt 2"
    }
  };
  const dispNode2 = {
    id: "disp_2",
    type: "output_display",
    x: 540, y: 100, w: 308, h: 308,
    data: {
      status: "idle",
      sourceNodeId: "ctrl_2",
      items: []
    }
  };

  setPrivateState({
    activeTabId: "tab_2",
    tabs: [
      {
        id: "tab_2",
        title: "Tab 2",
        graph: {
          nodes: [ctrlNode2, dispNode2],
          edges: [{ from: "ctrl_2", to: "disp_2" }]
        }
      }
    ],
    graph: {
      nodes: [ctrlNode2, dispNode2],
      edges: [{ from: "ctrl_2", to: "disp_2" }]
    }
  });

  fetchHandler = async (url) => {
    if (url.includes("/api/studio/generate")) {
      return {
        ok: true,
        status: 202,
        json: async () => ({
          ok: true,
          status: "running",
          taskId: "",
          requestId: "req_canvas_fail"
        })
      };
    }
    if (url.includes("/api/studio/tasks")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ status: "failed", error: "Canvas task failed" })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res5 = await runOutputControlNode("ctrl_2");
  assert.equal(res5, false);
  assert.equal(ctrlNode2.data.status, "error");
  assert.equal(dispNode2.data.status, "error");
  assert.ok(!toasts.some((t) => t.includes("已自动连接") || t.includes("已更新")), "Must NOT toast success on poll failure");

  // -------------------------------------------------------------
  // Test 6: Canvas / Form path missing image & taskId/requestId -> error
  // -------------------------------------------------------------
  toasts.length = 0;
  const ctrlNode3 = {
    id: "ctrl_3",
    type: "output_control",
    x: 100, y: 100, w: 344, h: 300,
    data: {
      status: "idle",
      mode: "single",
      ratio: "3:4",
      prompt: "canvas prompt 3"
    }
  };
  const dispNode3 = {
    id: "disp_3",
    type: "output_display",
    x: 540, y: 100, w: 308, h: 308,
    data: {
      status: "idle",
      sourceNodeId: "ctrl_3",
      items: []
    }
  };

  setPrivateState({
    activeTabId: "tab_3",
    tabs: [
      {
        id: "tab_3",
        title: "Tab 3",
        graph: {
          nodes: [ctrlNode3, dispNode3],
          edges: [{ from: "ctrl_3", to: "disp_3" }]
        }
      }
    ],
    graph: {
      nodes: [ctrlNode3, dispNode3],
      edges: [{ from: "ctrl_3", to: "disp_3" }]
    }
  });

  fetchHandler = async (url) => {
    if (url.includes("/api/studio/generate")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, status: "queued", taskId: "", requestId: "" })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res6 = await runOutputControlNode("ctrl_3");
  assert.equal(res6, false);
  assert.equal(ctrlNode3.data.status, "error");
  assert.equal(dispNode3.data.status, "error");
  assert.ok(!toasts.some((t) => t.includes("已自动连接") || t.includes("已更新")), "Must NOT toast success on invalid response");

  // -------------------------------------------------------------
  // Test 7: Article card recovery after refresh with only requestId (status generating)
  // -------------------------------------------------------------
  toasts.length = 0;
  const cardResume1 = {
    id: "card_res_1",
    title: "恢复文章卡片",
    status: "generating",
    requestId: "req_resume_art_1",
    taskId: "",
    imageUrl: ""
  };
  const artResume1 = {
    id: "art_res_1",
    title: "测试文章",
    cards: [cardResume1]
  };
  setPrivateState({ myArticles: [artResume1], tabs: [] });

  let pollCount7 = 0;
  fetchHandler = async (url) => {
    if (url.includes("/api/studio/tasks")) {
      pollCount7++;
      assert.ok(url.includes("requestId=req_resume_art_1"), "Resume must poll using requestId");
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          taskId: "task_res_1",
          requestId: "req_resume_art_1",
          images: ["/images/resumed-article.webp"]
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  await resumePendingCloudTasks();
  assert.equal(pollCount7, 1);
  assert.equal(cardResume1.status, "done");
  assert.equal(cardResume1.imageUrl, "/images/resumed-article.webp");
  assert.equal(cardResume1.taskId, "");

  // -------------------------------------------------------------
  // Test 8: Active tab recovery with independent graph clone
  // -------------------------------------------------------------
  toasts.length = 0;
  const activeDisp = {
    id: "disp_res_1",
    type: "output_display",
    x: 540,
    y: 100,
    w: 308,
    h: 308,
    data: {
      status: "generating",
      pendingRequestId: "req_resume_canvas_1",
      pendingTaskId: "",
      pendingSpec: {
        req_resume_canvas_1: {
          slotKey: "out_0",
          title: "恢复画布图片",
          ratio: "3:4"
        }
      },
      items: []
    }
  };
  const activeCtrl = {
    id: "ctrl_res_1",
    type: "output_control",
    x: 100,
    y: 100,
    w: 344,
    h: 300,
    data: { status: "generating" }
  };
  activeDisp.data.sourceNodeId = "ctrl_res_1";

  const activeGraph = {
    nodes: [activeCtrl, activeDisp],
    edges: [{ from: "ctrl_res_1", to: "disp_res_1" }]
  };
  // Snapshot in tabs is an independent clone of activeGraph
  const snapshotGraph = JSON.parse(JSON.stringify(activeGraph));

  setPrivateState({
    myArticles: [],
    activeTabId: "tab_res",
    tabs: [
      {
        id: "tab_res",
        title: "Tab Res",
        graph: snapshotGraph
      }
    ],
    graph: activeGraph
  });

  let pollCount8 = 0;
  fetchHandler = async (url) => {
    if (url.includes("/api/studio/tasks")) {
      pollCount8++;
      assert.ok(url.includes("requestId=req_resume_canvas_1"), "Resume must poll using requestId for canvas node");
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          taskId: "task_res_canvas_1",
          requestId: "req_resume_canvas_1",
          images: ["/images/resumed-canvas.webp"]
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  await resumePendingCloudTasks();
  assert.equal(pollCount8, 1);
  // Verify CS.graph has been updated
  assert.equal(activeDisp.data.status, "done");
  assert.equal(activeDisp.data.items.length, 1);
  assert.equal(activeDisp.data.items[0].imageUrl, "/images/resumed-canvas.webp");
  assert.ok(!activeDisp.data.pendingTaskId, "pendingTaskId must be cleared");
  assert.ok(!activeDisp.data.pendingRequestId, "pendingRequestId must be cleared");
  assert.equal(activeDisp.data.pendingSpec?.req_resume_canvas_1, undefined, "pendingSpec must be cleared");
  assert.equal(activeCtrl.data.status, "done", "active ctrl node status should be updated to done");

  // Verify tab.graph snapshot was synced by persistOpenTabs() and is consistent with CS.graph
  const currentTabs = getTabs();
  const tabRes = currentTabs.find((t) => t.id === "tab_res");
  assert.ok(tabRes, "tab_res must exist");
  const tabDisp = tabRes.graph.nodes.find((n) => n.id === "disp_res_1");
  assert.equal(tabDisp.data.status, "done", "snapshot node status must also be done");
  assert.equal(tabDisp.data.items.length, 1);
  assert.equal(tabDisp.data.items[0].imageUrl, "/images/resumed-canvas.webp");
  assert.ok(!tabDisp.data.pendingRequestId);

  // -------------------------------------------------------------
  // Test 9: Recovery failure when task fails -> card marked error
  // -------------------------------------------------------------
  toasts.length = 0;
  const cardResumeFail = {
    id: "card_res_fail",
    title: "恢复失败卡片",
    status: "generating",
    requestId: "req_resume_art_fail",
    taskId: "",
    imageUrl: ""
  };
  const artResumeFail = {
    id: "art_res_fail",
    title: "测试失败文章",
    cards: [cardResumeFail]
  };
  setPrivateState({ myArticles: [artResumeFail], tabs: [] });

  let pollCount9 = 0;
  fetchHandler = async (url) => {
    if (url.includes("/api/studio/tasks")) {
      pollCount9++;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: "failed",
          error: "云端配图生成失败"
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  await resumePendingCloudTasks();
  assert.equal(pollCount9, 1);
  assert.equal(cardResumeFail.status, "error");
  assert.equal(cardResumeFail.imageUrl, "", "Image URL must remain empty on error");
  assert.equal(cardResumeFail.taskId, "");

  // -------------------------------------------------------------
  // Test 10: Inactive tab recovery when user is currently on another tab
  // -------------------------------------------------------------
  toasts.length = 0;
  const inactiveDisp = {
    id: "disp_inact_1",
    type: "output_display",
    x: 540,
    y: 100,
    w: 308,
    h: 308,
    data: {
      status: "generating",
      pendingRequestId: "req_resume_inactive",
      pendingTaskId: "",
      pendingSpec: {
        req_resume_inactive: {
          slotKey: "out_inact",
          title: "非活动标签页图片",
          ratio: "1:1"
        }
      },
      items: []
    }
  };
  const inactiveCtrl = {
    id: "ctrl_inact_1",
    type: "output_control",
    x: 100,
    y: 100,
    w: 344,
    h: 300,
    data: { status: "generating" }
  };
  inactiveDisp.data.sourceNodeId = "ctrl_inact_1";

  const activeTabGraph = {
    nodes: [{ id: "ctrl_active_other", type: "output_control", data: { status: "idle" } }],
    edges: []
  };

  const inactiveTabGraph = {
    nodes: [inactiveCtrl, inactiveDisp],
    edges: [{ from: "ctrl_inact_1", to: "disp_inact_1" }]
  };

  setPrivateState({
    myArticles: [],
    activeTabId: "tab_active_now",
    tabs: [
      {
        id: "tab_active_now",
        title: "Active Tab",
        graph: JSON.parse(JSON.stringify(activeTabGraph))
      },
      {
        id: "tab_inactive_target",
        title: "Inactive Tab",
        graph: inactiveTabGraph
      }
    ],
    graph: activeTabGraph
  });

  let pollCount10 = 0;
  fetchHandler = async (url) => {
    if (url.includes("/api/studio/tasks")) {
      pollCount10++;
      assert.ok(url.includes("requestId=req_resume_inactive"), "Resume must poll using requestId for inactive tab");
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          taskId: "task_inactive_done",
          requestId: "req_resume_inactive",
          images: ["/images/inactive-canvas.webp"]
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  await resumePendingCloudTasks();
  assert.equal(pollCount10, 1);
  // Verify inactiveTabGraph was updated directly
  assert.equal(inactiveDisp.data.status, "done");
  assert.equal(inactiveDisp.data.items.length, 1);
  assert.equal(inactiveDisp.data.items[0].imageUrl, "/images/inactive-canvas.webp");
  assert.ok(!inactiveDisp.data.pendingTaskId);
  assert.ok(!inactiveDisp.data.pendingRequestId);
  assert.equal(inactiveCtrl.data.status, "done");
  // Active tab graph should not be corrupted
  assert.equal(activeTabGraph.nodes[0].id, "ctrl_active_other");
  assert.equal(activeTabGraph.nodes.length, 1);

  // -------------------------------------------------------------
  // Test 11: Article card terminal failure (refunded) -> retry gets NEW requestId
  // -------------------------------------------------------------
  toasts.length = 0;
  const planNode11 = {
    id: "plan_node_11",
    type: "article_plan",
    x: 100, y: 100, w: 300, h: 300,
    data: {
      cards: [
        { id: "card_11", title: "测试终端退款卡片", prompt: "Refunded test", status: "ready", imageUrl: "", taskId: "" }
      ]
    }
  };
  planNode11.data.id = "article_11";
  const target11 = { planNode: planNode11, art: planNode11.data, isActiveCanvas: false };
  setPrivateState({myArticles: [target11.art]});

  const postRequestIds11 = [];
  fetchHandler = async (url, opts) => {
    if (url.includes("/api/studio/generate")) {
      const body = JSON.parse(opts.body || "{}");
      postRequestIds11.push(body.requestId);
      return {
        ok: true,
        status: 202,
        json: async () => ({ ok: true, status: "running", taskId: "", requestId: body.requestId })
      };
    }
    if (url.includes("/api/studio/tasks")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ status: "refunded", message: "Task was refunded" })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res11_1 = await generateSinglePlanCard(target11, "card_11", {skipCostConfirmation:true});
  assert.equal(res11_1, false);
  assert.equal(planNode11.data.cards[0].status, "error");
  assert.equal(postRequestIds11.length, 1);

  const res11_2 = await generateSinglePlanCard(target11, "card_11", {skipCostConfirmation:true});
  assert.equal(res11_2, false);
  assert.equal(postRequestIds11.length, 2);
  assert.notEqual(postRequestIds11[0], postRequestIds11[1], "Terminal failure retry must generate a different requestId");

  // -------------------------------------------------------------
  // Test 12: Article card timeout (non-terminal) -> retry REUSES same requestId
  // -------------------------------------------------------------
  toasts.length = 0;
  const planNode12 = {
    id: "plan_node_12",
    type: "article_plan",
    x: 100, y: 100, w: 300, h: 300,
    data: {
      cards: [
        { id: "card_12", title: "测试超时卡片", prompt: "Timeout test", status: "ready", imageUrl: "", taskId: "" }
      ]
    }
  };
  planNode12.data.id = "article_12";
  const target12 = { planNode: planNode12, art: planNode12.data, isActiveCanvas: false };
  setPrivateState({myArticles: [target12.art]});

  const postRequestIds12 = [];
  fetchHandler = async (url, opts) => {
    if (url.includes("/api/studio/generate")) {
      const body = JSON.parse(opts.body || "{}");
      postRequestIds12.push(body.requestId);
      return {
        ok: true,
        status: 202,
        json: async () => ({ ok: true, status: "running", taskId: "", requestId: body.requestId })
      };
    }
    if (url.includes("/api/studio/tasks")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ status: "running" })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res12_1 = await generateSinglePlanCard(target12, "card_12", {skipCostConfirmation:true});
  assert.equal(res12_1, false);
  assert.equal(planNode12.data.cards[0].status, "error");
  assert.equal(postRequestIds12.length, 1);

  const res12_2 = await generateSinglePlanCard(target12, "card_12", {skipCostConfirmation:true});
  assert.equal(res12_2, false);
  assert.equal(postRequestIds12.length, 2);
  assert.equal(postRequestIds12[0], postRequestIds12[1], "Timeout retry must reuse the same requestId");

  // -------------------------------------------------------------
  // Test 13: Canvas output terminal failure (refunded) -> retry gets NEW requestId
  // -------------------------------------------------------------
  toasts.length = 0;
  const ctrlNode13 = {
    id: "ctrl_13",
    type: "output_control",
    x: 100, y: 100, w: 344, h: 300,
    data: { status: "idle", mode: "single", ratio: "3:4", prompt: "canvas terminal prompt" }
  };
  const dispNode13 = {
    id: "disp_13",
    type: "output_display",
    x: 540, y: 100, w: 308, h: 308,
    data: { status: "idle", sourceNodeId: "ctrl_13", items: [] }
  };

  setPrivateState({
    myArticles: [],
    activeTabId: "tab_13",
    tabs: [
      {
        id: "tab_13",
        title: "Tab 13",
        graph: {
          nodes: [ctrlNode13, dispNode13],
          edges: [{ from: "ctrl_13", to: "disp_13" }]
        }
      }
    ],
    graph: {
      nodes: [ctrlNode13, dispNode13],
      edges: [{ from: "ctrl_13", to: "disp_13" }]
    }
  });

  const postRequestIds13 = [];
  fetchHandler = async (url, opts) => {
    if (url.includes("/api/studio/generate")) {
      const body = JSON.parse(opts.body || "{}");
      postRequestIds13.push(body.requestId);
      return {
        ok: true,
        status: 202,
        json: async () => ({ ok: true, status: "running", taskId: "", requestId: body.requestId })
      };
    }
    if (url.includes("/api/studio/tasks")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ status: "refunded", message: "Canvas refunded" })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res13_1 = await runOutputControlNode("ctrl_13");
  assert.equal(res13_1, false);
  assert.equal(ctrlNode13.data.status, "error");
  assert.equal(dispNode13.data.status, "error");
  assert.equal(postRequestIds13.length, 1);

  ctrlNode13.data.status = "idle";
  const res13_2 = await runOutputControlNode("ctrl_13");
  assert.equal(res13_2, false);
  assert.equal(postRequestIds13.length, 2);
  assert.notEqual(postRequestIds13[0], postRequestIds13[1], "Canvas terminal retry must get different requestId");

  // -------------------------------------------------------------
  // Test 14: Canvas output timeout (non-terminal) -> retry REUSES same requestId
  // -------------------------------------------------------------
  toasts.length = 0;
  const ctrlNode14 = {
    id: "ctrl_14",
    type: "output_control",
    x: 100, y: 100, w: 344, h: 300,
    data: { status: "idle", mode: "single", ratio: "3:4", prompt: "canvas timeout prompt" }
  };
  const dispNode14 = {
    id: "disp_14",
    type: "output_display",
    x: 540, y: 100, w: 308, h: 308,
    data: { status: "idle", sourceNodeId: "ctrl_14", items: [] }
  };

  setPrivateState({
    myArticles: [],
    activeTabId: "tab_14",
    tabs: [
      {
        id: "tab_14",
        title: "Tab 14",
        graph: {
          nodes: [ctrlNode14, dispNode14],
          edges: [{ from: "ctrl_14", to: "disp_14" }]
        }
      }
    ],
    graph: {
      nodes: [ctrlNode14, dispNode14],
      edges: [{ from: "ctrl_14", to: "disp_14" }]
    }
  });

  const postRequestIds14 = [];
  fetchHandler = async (url, opts) => {
    if (url.includes("/api/studio/generate")) {
      const body = JSON.parse(opts.body || "{}");
      postRequestIds14.push(body.requestId);
      return {
        ok: true,
        status: 202,
        json: async () => ({ ok: true, status: "running", taskId: "", requestId: body.requestId })
      };
    }
    if (url.includes("/api/studio/tasks")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ status: "running" })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const res14_1 = await runOutputControlNode("ctrl_14");
  assert.equal(res14_1, false);
  assert.equal(ctrlNode14.data.status, "error");
  assert.equal(dispNode14.data.status, "error");
  assert.equal(postRequestIds14.length, 1);

  ctrlNode14.data.status = "idle";
  const res14_2 = await runOutputControlNode("ctrl_14");
  assert.equal(res14_2, false);
  assert.equal(postRequestIds14.length, 2);
  assert.equal(postRequestIds14[0], postRequestIds14[1], "Canvas timeout retry must reuse same requestId");

  // 15: Current article documents do not read or mutate any canvas/form graph.
  const api = win.HANDRAW_STUDIO_TESTING;
  const unrelatedGraph = {nodes:[{id:"unrelated",type:"output_control",data:{prompt:"keep form"}}],edges:[]};
  const unrelatedTab = {id:"unrelated-tab",graph:unrelatedGraph};
  setPrivateState({myArticles:[],graph:unrelatedGraph,tabs:[unrelatedTab]});
  const graphBefore = JSON.stringify(unrelatedGraph);
  const firstDoc = {id:"doc-one",title:"Same",markdown:"Same body",cards:[]};
  const secondDoc = {...firstDoc,id:"doc-two"};
  api.syncArticleEditorDraftToHistory(firstDoc);
  api.syncArticleEditorDraftToHistory(secondDoc);
  api.syncArticleEditorDraftToHistory({...firstDoc,title:"Edited",markdown:"Edited body"});
  assert.equal(win.CS.myArticles.length,2,"Edits update one current document; identical new IDs stay distinct");
  assert.equal(api.resolveArticleTarget("doc-one").art.markdown,"Edited body");
  assert.equal(api.resolveArticleTarget("doc-two").art.markdown,"Same body");
  assert.equal(api.resolveArticleTarget("doc-one").isActiveCanvas,false);
  assert.equal(JSON.stringify(unrelatedGraph),graphBefore);
  assert.equal(win.CS.tabs.length,1);

  // 16: Standalone planning takes article settings without a temporary graph.
  const originalDocumentEngine = win.HANDRAW_CANVAS_ENGINE;
  vm.runInContext(fs.readFileSync("demo/assets/studio-prompt-engine.js","utf8"),context);
  const documentEngine = win.HANDRAW_CANVAS_ENGINE;
  originalDocumentEngine.parseArticleReadonlyBlocks=documentEngine.parseArticleReadonlyBlocks;
  const planned = documentEngine.buildArticleDocument("# Article\n\nIntro\n\n## Section\n\nParagraph",{
    styleId:"FA-001",layoutId:"IG-001",coverRatio:"16:9",inlineRatio:"4:3"
  });
  assert.equal(planned.cards.length,2);
  assert.equal(planned.cards[0].ratio,"16:9");
  assert.ok(planned.cards.every(card=>card.prompt.includes("#FA-001")));
  assert.equal(JSON.stringify(unrelatedGraph),graphBefore);
  const aiPlan = documentEngine.buildArticleDocumentFromAi({cover:{subject:"Cover idea"},illustrations:[{
    subject:"Inline idea",afterBlockIdx:2,anchorText:"Section"
  }]},{styleId:"FB-001",coverRatio:"3:2",inlineRatio:"4:3"});
  assert.equal(aiPlan.length,2);
  assert.ok(aiPlan[0].prompt.includes("#FB-001"));

  // 17: More than 50 documents save in bounded chunks; simultaneous callers
  // share one serial operation and runtime updates produce no document writes.
  win.HANDRAW_SHARED.App.state.serverBacked = true;
  const cloudDocs = Array.from({length:121},(_,i)=>({id:`cloud-${i}`,articleTitle:`Doc ${i}`,
    markdown:"body",createdAtMs:1,cards:[{id:"cover",prompt:"drawing",imageUrl:"/images/current.webp",status:"done"}]}));
  setPrivateState({myArticles:cloudDocs});
  let activeSaves=0,maxActiveSaves=0;
  const saveBatches=[];
  fetchHandler=async(url,opts)=>{
    assert.equal(url,"/api/studio/articles");
    const batch=JSON.parse(opts.body).articles;
    saveBatches.push(batch);
    activeSaves++;
    maxActiveSaves=Math.max(maxActiveSaves,activeSaves);
    await new Promise(resolve=>setImmediate(resolve));
    activeSaves--;
    return {ok:true,status:200,json:async()=>({ok:true,versions:Object.fromEntries(batch.map(article=>[article.id,100]))})};
  };
  assert.deepEqual(await Promise.all([api.flushCloudArticlesSync(),api.flushCloudArticlesSync()]),[true,true]);
  assert.deepEqual(saveBatches.map(batch=>batch.length),[50,50,21]);
  assert.equal(maxActiveSaves,1);
  assert.ok(!("imageUrl" in saveBatches[0][0].cards[0]));
  cloudDocs[0].cards[0].status="generating";
  cloudDocs[0].cards[0].taskId="runtime-task";
  assert.equal(await api.flushCloudArticlesSync(),true);
  assert.equal(saveBatches.length,3,"Task progress must not autosave the entire article collection");

  // 18: An edit during an outstanding save is sent afterward with the returned
  // concurrency token, never acknowledged as already saved or sent in parallel.
  const edited = {id:"edit-in-flight",articleTitle:"Draft",markdown:"A",cards:[],createdAtMs:1};
  setPrivateState({myArticles:[edited]});
  const writes=[];
  let releaseFirst;
  fetchHandler=async(url,opts)=>{
    const article=JSON.parse(opts.body).articles[0];
    writes.push(article);
    if(writes.length===1) await new Promise(resolve=>{releaseFirst=resolve;});
    return {ok:true,status:200,json:async()=>({ok:true,versions:{[article.id]:200+writes.length}})};
  };
  const saving = api.flushCloudArticlesSync();
  assert.equal(typeof releaseFirst,"function");
  edited.markdown="B";
  releaseFirst();
  assert.equal(await saving,true);
  assert.deepEqual(writes.map(article=>article.markdown),["A","B"]);
  assert.equal(writes[1].baseUpdatedAtMs,201);

  // 19: A late local result cannot overwrite an edited illustration or leave
  // its old browser-only generating flag stuck on the new configuration.
  win.HANDRAW_SHARED.App.state.serverBacked = false;
  const editedCard={id:"late-card",title:"Card",prompt:"Original",status:"pending",imageUrl:""};
  const lateArticle={id:"late-article",articleTitle:"Late",markdown:"body",cards:[editedCard]};
  setPrivateState({myArticles:[lateArticle],engineMode:"api",serverCfg:{liveImageEnabled:true}});
  fetchHandler=async(url)=>{
    if(url.includes("/api/studio/generate")) return {ok:true,status:202,json:async()=>({ok:true,requestId:"late-request"})};
    if(url.includes("/api/studio/tasks")) {
      editedCard.prompt="User changed it";
      return {ok:true,status:200,json:async()=>({status:"success",images:["/images/obsolete.webp"]})};
    }
    return {ok:true,status:200,json:async()=>({})};
  };
  assert.equal(await generateSinglePlanCard("late-article","late-card",{skipCostConfirmation:true}),false);
  assert.equal(editedCard.prompt,"User changed it");
  assert.equal(editedCard.imageUrl,"");
  assert.equal(editedCard.status,"pending");
  assert.equal(JSON.stringify(unrelatedGraph),graphBefore);

  // 20: Summary-only records are never submitted as empty article documents.
  win.HANDRAW_SHARED.App.state.serverBacked = true;
  const summary={id:"summary-only",articleTitle:"Summary",updatedAtMs:1,_summary:true,cards:[]};
  setPrivateState({myArticles:[summary]});
  fetchHandler=async()=>{throw new Error("A summary must not trigger an autosave");};
  assert.equal(await api.flushCloudArticlesSync(),true);
  let detailReads=0;
  fetchHandler=async(url)=>{
    assert.equal(url,"/api/studio/articles/summary-only");detailReads++;
    return {ok:true,status:200,json:async()=>({ok:true,article:{id:"summary-only",articleTitle:"Full",markdown:"Full private body",cards:[],updatedAtMs:2}})};
  };
  assert.equal(await api.loadArticleDocument("summary-only"),true);
  assert.equal(detailReads,1);
  assert.equal(win.CS.myArticles[0].markdown,"Full private body");
  assert.equal(win.CS.myArticles[0]._summary,false);
  fetchHandler=async()=>{throw new Error("Just reading an article must not autosave it");};
  assert.equal(await api.flushCloudArticlesSync(),true);
  win.HANDRAW_SHARED.App.state.serverBacked = false;

  // 21: A real HTTP conflict stops autosave and preserves an independent local
  // recovery copy, including edits made while the failed save was outstanding.
  win.HANDRAW_SHARED.App.state.serverBacked = true;
  setPrivateState({myArticles:[{id:"conflict-local",articleTitle:"Local",markdown:"Keep this draft",cards:[]}]});
  fetchHandler=async()=>({ok:false,status:409,json:async()=>({code:"article_version_conflict"})});
  assert.equal(await api.flushCloudArticlesSync(),false);
  const recovery=api.readScopedCache("handraw_article_conflict_backup_v1");
  assert.equal(recovery.articles[0].markdown,"Keep this draft");
  fetchHandler=async()=>{throw new Error("Conflicting drafts must not automatically retry and overwrite");};
  assert.equal(await api.flushCloudArticlesSync(),false);
  win.HANDRAW_SHARED.App.state.serverBacked = false;

  // History continuation must preserve more than forty distinct runs, retry
  // the same boundary after transport failure, and ignore another account.
  win.HANDRAW_SHARED.App.state.serverBacked = true;
  setPrivateState({generationHistory:[]});
  const historyPage=(start,stop)=>Array.from({length:stop-start},(_,n)=>({id:`paged_${start+n}`,runId:`run_${start+n}`,kind:"single",createdAtISO:new Date(1800000000000-(start+n)*1000).toISOString(),engine:"live",items:[]}));
  fetchHandler=async()=>({ok:true,status:200,json:async()=>({loggedIn:true,history:historyPage(0,40),nextCursor:"older-page"})});
  await api.hydrateCloudStudioWorkspace({collection:"history"});
  assert.equal(win.CS.generationHistory.length,40);assert.equal(win.CS.historyCursor,"older-page");
  fetchHandler=async url=>{assert.ok(url.endsWith("cursor=older-page"));throw new Error("lost response");};
  await api.loadMoreStudioHistory();assert.equal(win.CS.historyCursor,"older-page");assert.ok(win.CS.historyError);
  fetchHandler=async url=>({ok:true,status:200,json:async()=>({loggedIn:true,history:historyPage(40,80),nextCursor:""})});
  await api.loadMoreStudioHistory();assert.equal(win.CS.generationHistory.length,80);assert.equal(win.CS.historyCursor,"");
  assert.equal(win.CS.generationHistory[0].id,"paged_0");assert.equal(win.CS.generationHistory[79].id,"paged_79");
  assert.equal(new Set(win.CS.generationHistory.map(h=>h.id)).size,80);
  assert.equal(api.readScopedCache("handraw_gen_history_v4").length,40,"The local warm cache stays bounded while all fetched pages remain visible");
  let releaseHistory;win.CS.historyCursor="late";
  fetchHandler=async()=>new Promise(resolve=>releaseHistory=()=>resolve({ok:true,status:200,json:async()=>({loggedIn:true,history:historyPage(80,90),nextCursor:"wrong-account"})}));
  const latePage=api.loadMoreStudioHistory();api.switchScope("user:another-account");releaseHistory();await latePage;
  assert.equal(win.CS.historyCursor,"");assert.equal(win.CS.historyLoading,false);
  assert.ok(!(win.CS.generationHistory||[]).some(h=>h.id==="paged_80"));
  win.HANDRAW_SHARED.App.state.serverBacked = false;

  // Article defaults are independent of any canvas/form, including when a
  // card inherits its ratio instead of repeating it in the slot.
  const inherited={id:"default-article",coverRatio:"16:9",settings:{style2:"FA-002"},cards:[{id:"cover-default",role:"cover",prompt:"Saved cat",status:"ready"}]};
  setPrivateState({myArticles:[inherited]});
  let sentDefaults;
  fetchHandler=async(url,options)=>{
    if(url==="/api/studio/generate") {sentDefaults=JSON.parse(options.body);return {ok:true,status:200,json:async()=>({ok:true,imageUrl:"/images/default-cat.webp",requestId:"default-request"})};}
    return {ok:true,status:200,json:async()=>({})};
  };
  assert.equal(await api.generateSinglePlanCard(inherited.id,"cover-default",{skipCostConfirmation:true}),true);
  assert.equal(sentDefaults.ratio,"16:9");assert.equal(sentDefaults.style2,"FA-002");

  // Demo samples belong to the visitor view, never to an authenticated user's
  // empty private library where hydration could mistake them for lost drafts.
  win.HANDRAW_SHARED.App.state.demoMode=true;win.HANDRAW_SHARED.App.state.loggedIn=true;
  win.HANDRAW_SHARED.App.state.serverBacked=true;api.switchScope("user_demo_empty");
  api.ensureMyArticlesInitialized();assert.equal(win.CS.myArticles.length,0);
  fetchHandler=async()=>({ok:true,status:200,json:async()=>({loggedIn:true,articles:[],pendingTasks:[]})});
  await api.hydrateCloudStudioWorkspace();assert.equal(win.CS.myArticles.length,0);
  assert.equal(api.readScopedCache("handraw_article_conflict_backup_v1",null),null);
  const offline={id:"private-offline",markdown:"Keep this private draft",cards:[]};
  setPrivateState({myArticles:[offline]});api.ensureMyArticlesInitialized();assert.equal(win.CS.myArticles[0],offline);
  win.HANDRAW_SHARED.App.state.loggedIn=false;api.switchScope("guest_demo_samples");
  api.ensureMyArticlesInitialized();assert.ok(win.CS.myArticles.length>0);
  win.HANDRAW_SHARED.App.state.demoMode=false;win.HANDRAW_SHARED.App.state.serverBacked=false;

  // Summary thumbnails are not a complete slot list. Do not parse a missing
  // summary body as the engine's starter article or report its cover as 1/1.
  const progressSummary={id:"progress-summary",_summary:true,illustrationCount:3,selectedImageCount:1,cards:[{imageUrl:"/cover.webp"}]};
  assert.equal(api.articleImageProgress(progressSummary).total,3);
  assert.equal(api.articleImageProgress(progressSummary).ready,1);
  assert.equal(api.articleImageProgress({...progressSummary,_summary:false,cards:[]}).total,0);
  assert.ok(!api.extractArticlePlainExcerpt("").includes("留白工作法"));
  assert.ok(!api.extractArticlePlainExcerpt("").includes("日历"));
  api.switchScope("user_summary_counts");win.HANDRAW_SHARED.App.state.serverBacked=true;
  fetchHandler=async()=>({ok:true,status:200,json:async()=>({loggedIn:true,articles:[progressSummary]})});
  await api.hydrateCloudStudioWorkspace();
  assert.equal(api.articleImageProgress(win.CS.myArticles[0]).total,3);
  assert.equal(api.articleImageProgress(win.CS.myArticles[0]).ready,1);
  win.HANDRAW_SHARED.App.state.serverBacked=false;

  // 30: Legacy warm caches must be compared with the complete cloud document,
  // never a summary's missing body; old recovery archives remain available.
  {
  win.HANDRAW_SHARED.App.state.loggedIn=true;win.HANDRAW_SHARED.App.state.serverBacked=true;
  api.switchScope("user_summary_receipt");
  const complete={id:"summary-receipt",articleTitle:"Saved title",markdown:"Full saved text",cards:[{id:"cover",role:"cover",prompt:"cat"}],createdAtMs:1,updatedAtMs:100};
  const summaryOf=article=>({id:article.id,articleTitle:article.articleTitle,updatedAtMs:article.updatedAtMs,_summary:true,cards:[]});
  const response=value=>({ok:true,status:200,json:async()=>value});
  const archived={id:"old-recovery",markdown:"An older private backup",cards:[]};
  api.writeScopedCache("handraw_article_conflict_backup_v1",{articles:[archived]});
  setPrivateState({myArticles:[{...complete,updatedAtMs:900}]});
  let detailCount=0,postCount=0;
  fetchHandler=async(url,opts)=>{
    if(opts?.method==="POST") {postCount++;const article=JSON.parse(opts.body).articles[0];assert.equal(article.baseUpdatedAtMs,100);return response({ok:true,versions:{[article.id]:101},writeSequences:{[article.id]:2}});}
    if(url.includes("workspace")) return response({loggedIn:true,articles:[summaryOf(complete)]});
    detailCount++;return response({article:{...complete,cards:[{prompt:"cat",role:"cover",id:"cover",status:"done",imageUrl:"/image.webp"}]}});
  };
  await api.hydrateCloudStudioWorkspace();assert.equal(detailCount,1);
  assert.equal(win.CS.myArticles[0].markdown,"Full saved text");
  assert.equal(await api.flushCloudArticlesSync(complete.id),true);assert.equal(postCount,0);
  win.CS.myArticles[0].articleTitle="Edited title";
  assert.equal(await api.flushCloudArticlesSync(complete.id),true);assert.equal(postCount,1);
  assert.equal(win.CS.myArticles[0].updatedAtMs,101);
  assert.equal(api.readScopedCache("handraw_my_articles_v1")[0]._cloudUpdatedAtMs,101);
  assert.equal(api.readScopedCache("handraw_article_conflict_backup_v1").articles[0].markdown,archived.markdown);

  // 31: Reloading the account uses its persisted save receipt. No full-body
  // request or spurious write is needed for a known, unchanged cloud version.
  api.switchScope("receipt_reload_other");api.switchScope("user_summary_receipt");
  fetchHandler=async(url)=>{assert.ok(url.includes("workspace"));return response({loggedIn:true,articles:[{...summaryOf(complete),updatedAtMs:101}]});};
  await api.hydrateCloudStudioWorkspace();assert.equal(win.CS.myArticles[0].articleTitle,"Edited title");
  assert.equal(await api.flushCloudArticlesSync(complete.id),true);

  // 32: Offline edits may resume against their acknowledged base, while a
  // truly newer cloud document is protected and other articles can still save.
  api.switchScope("user_offline_conflicts");
  const offline={...complete,id:"offline",markdown:"Offline edit",_cloudUpdatedAtMs:100,_cloudDirty:true};
  const conflicting={...complete,id:"changed-elsewhere",markdown:"Private unsaved edit",_cloudUpdatedAtMs:100,_cloudDirty:true};
  setPrivateState({myArticles:[offline,conflicting]});
  const remoteConflict={...complete,id:conflicting.id,markdown:"New cloud edit",updatedAtMs:200};
  const savedOffline=[];
  fetchHandler=async(url,opts)=>{
    if(opts?.method==="POST") {const articles=JSON.parse(opts.body).articles;savedOffline.push(...articles);return response({ok:true,versions:Object.fromEntries(articles.map(a=>[a.id,201]))});}
    if(url.includes("workspace")) return response({loggedIn:true,articles:[summaryOf(offline),summaryOf(remoteConflict)]});
    assert.ok(url.endsWith(conflicting.id));return response({article:remoteConflict});
  };
  await api.hydrateCloudStudioWorkspace();
  assert.equal(await api.flushCloudArticlesSync(offline.id),true);
  assert.equal(savedOffline.length,1);assert.equal(savedOffline[0].baseUpdatedAtMs,100);
  assert.equal(savedOffline[0].markdown,"Offline edit");
  assert.equal(await api.flushCloudArticlesSync(conflicting.id),false);
  assert.equal(api.readScopedCache("handraw_article_conflict_backup_v1").articles[0].markdown,"Private unsaved edit");
  assert.equal(win.CS.myArticles.find(a=>a.id===conflicting.id).markdown,"Private unsaved edit");

  // 33: An atomic batch conflict names its article; unrelated writes retry
  // with their original concurrency tokens after that transaction rolls back.
  api.switchScope("user_batch_conflict_isolation");
  setPrivateState({myArticles:[{...complete,id:"batch-bad"},{...complete,id:"batch-good"}]});
  const attempts=[];
  fetchHandler=async(url,opts)=>{
    const articles=JSON.parse(opts.body).articles;attempts.push(articles);
    if(attempts.length===1) return {ok:false,status:409,json:async()=>({code:"article_version_conflict",articleId:"batch-bad"})};
    return response({ok:true,versions:{"batch-good":300}});
  };
  assert.equal(await api.flushCloudArticlesSync("batch-good"),true);
  assert.deepEqual(attempts.map(a=>a.map(b=>b.id)),[["batch-bad","batch-good"],["batch-good"]]);
  assert.equal(attempts[1][0].baseUpdatedAtMs,0);
  assert.equal(await api.flushCloudArticlesSync("batch-bad"),false);

  // 34: An older hydration completing after a newer one must not regress its
  // baseline or overwrite the article loaded by the newer request.
  api.switchScope("user_hydration_race");setPrivateState({myArticles:[{...complete}]});
  let releaseOldRead,workspaceReads=0;
  fetchHandler=async(url)=>{
    if(url.includes("workspace")) {workspaceReads++;return response({loggedIn:true,articles:[{...summaryOf(complete),updatedAtMs:workspaceReads===1?100:200}]});}
    if(workspaceReads===1) {await new Promise(resolve=>releaseOldRead=resolve);return response({article:complete});}
    return response({article:{...complete,updatedAtMs:200}});
  };
  const oldHydration=api.hydrateCloudStudioWorkspace();
  while(!releaseOldRead) await new Promise(resolve=>setImmediate(resolve));
  await api.hydrateCloudStudioWorkspace();releaseOldRead();await oldHydration;
  assert.equal(win.CS.myArticles[0]._cloudUpdatedAtMs,200);
  win.CS.myArticles[0].markdown="After the latest hydration";
  fetchHandler=async(url,opts)=>{const article=JSON.parse(opts.body).articles[0];assert.equal(article.baseUpdatedAtMs,200);return response({ok:true,versions:{[article.id]:201}});};
  assert.equal(await api.flushCloudArticlesSync(complete.id),true);

  // 35: Typing while a legacy cache's detail read is outstanding remains a
  // local edit and saves against the verified cloud base, not an empty summary.
  api.switchScope("user_edit_during_hydration");const typing={...complete};setPrivateState({myArticles:[typing]});
  let releaseDetail;
  fetchHandler=async(url)=>{
    if(url.includes("workspace")) return response({loggedIn:true,articles:[summaryOf(complete)]});
    await new Promise(resolve=>releaseDetail=resolve);return response({article:complete});
  };
  const reading=api.hydrateCloudStudioWorkspace();while(!releaseDetail) await new Promise(resolve=>setImmediate(resolve));
  typing.markdown="Typed while loading";
  let hydratedPosts=0;
  fetchHandler=async(url,opts)=>{hydratedPosts++;const article=JSON.parse(opts.body).articles[0];assert.equal(article.baseUpdatedAtMs,100);assert.equal(article.markdown,"Typed while loading");return response({ok:true,versions:{[article.id]:101}});};
  const waitingSave=api.flushCloudArticlesSync(complete.id);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(hydratedPosts,0,"Saving waits for its cloud baseline instead of sending zero");
  releaseDetail();await reading;
  assert.equal(win.CS.myArticles[0].markdown,"Typed while loading");
  assert.equal(await waitingSave,true);assert.equal(hydratedPosts,1);
  win.HANDRAW_SHARED.App.state.serverBacked=false;
  }

  // Lazy reference data is shared per account, but a late old-account response
  // must never populate another account's picker.
  api.switchScope("reference_old");
  const referenceResponse=value=>({ok:true,status:200,json:async()=>value});
  let releaseReference,referenceCalls=0;
  fetchHandler=()=>{referenceCalls++;return new Promise(resolve=>releaseReference=resolve);};
  const oldReference=api.ensureBenchmarkAssets();
  assert.equal(api.ensureBenchmarkAssets(),oldReference);assert.equal(referenceCalls,1);
  api.switchScope("reference_new");
  fetchHandler=async()=>referenceResponse({assets:[{id:"new-reference",cat:"characters",name_zh:"New"}]});
  await api.ensureBenchmarkAssets();
  releaseReference(referenceResponse({assets:[{id:"old-private-reference",cat:"characters",name_zh:"Old"}]}));
  await oldReference;
  assert(api.getReferenceAssets().some(item=>item.id==="new-reference"));
  assert(!api.getReferenceAssets().some(item=>item.id==="old-private-reference"));
  api.switchScope("reference_retry");
  fetchHandler=async()=>({ok:false});
  await assert.rejects(api.ensureBenchmarkAssets(),/参考图库加载失败/);
  fetchHandler=async()=>referenceResponse({assets:[{id:"retry-reference",cat:"props",name_zh:"Retry"}]});
  await api.ensureBenchmarkAssets();
  assert(api.getReferenceAssets().some(item=>item.id==="retry-reference"));
  assert(!api.getReferenceAssets().some(item=>item.id==="OT-001"||item.id==="OT-002"));

  console.log("All studio generation, document isolation, save and history tests passed (37/37).");
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
