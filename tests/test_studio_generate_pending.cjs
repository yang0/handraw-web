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
  const target1 = { planNode: planNode1, art: {}, isActiveCanvas: false };

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

  const res1 = await generateSinglePlanCard(target1, "card_1");
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
  const target2 = { planNode: planNode2, art: {}, isActiveCanvas: false };

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

  const res2 = await generateSinglePlanCard(target2, "card_2");
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
  const target3 = { planNode: planNode3, art: {}, isActiveCanvas: false };

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

  const res3 = await generateSinglePlanCard(target3, "card_3");
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
  assert.equal(activeDisp.data.pendingTaskId, undefined, "pendingTaskId must be cleared");
  assert.equal(activeDisp.data.pendingRequestId, undefined, "pendingRequestId must be cleared");
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
  assert.equal(tabDisp.data.pendingRequestId, undefined);

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
  assert.equal(inactiveDisp.data.pendingTaskId, undefined);
  assert.equal(inactiveDisp.data.pendingRequestId, undefined);
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
  const target11 = { planNode: planNode11, art: {}, isActiveCanvas: false };

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

  const res11_1 = await generateSinglePlanCard(target11, "card_11");
  assert.equal(res11_1, false);
  assert.equal(planNode11.data.cards[0].status, "error");
  assert.equal(postRequestIds11.length, 1);

  const res11_2 = await generateSinglePlanCard(target11, "card_11");
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
  const target12 = { planNode: planNode12, art: {}, isActiveCanvas: false };

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

  const res12_1 = await generateSinglePlanCard(target12, "card_12");
  assert.equal(res12_1, false);
  assert.equal(planNode12.data.cards[0].status, "error");
  assert.equal(postRequestIds12.length, 1);

  const res12_2 = await generateSinglePlanCard(target12, "card_12");
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

  console.log("All studio generate pending and recovery tests passed (14/14).");
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
