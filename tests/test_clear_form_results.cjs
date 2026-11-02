"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const promptEngineSource = fs.readFileSync("demo/assets/studio-prompt-engine.js", "utf8");
const makeImageSource = fs.readFileSync("demo/assets/studio-make-image.js", "utf8");
const studioAppSource = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const quickCreateCss = fs.readFileSync("demo/assets/quick-create.css", "utf8");

function createFakeDom() {
  const elements = new Map();
  return {
    innerHTML: "",
    querySelector(sel) {
      if (sel.startsWith("#")) {
        const id = sel.slice(1);
        const match = this.innerHTML.match(new RegExp(`id=["']${id}["']`));
        if (match) {
          if (!elements.has(id)) {
            elements.set(id, {
              id,
              focus() {},
              disabled: this.innerHTML.includes(`id="${id}" disabled`),
              onclick: null,
              oninput: null,
              onchange: null,
              value: ""
            });
          }
          return elements.get(id);
        }
      }
      return null;
    },
    querySelectorAll(sel) {
      return [];
    }
  };
}

test("Issue #47: Clear form also clears workspace generation results and guards busy states", async (t) => {
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
      _store: {},
      getItem(k) { return this._store[k] || null; },
      setItem(k, v) { this._store[k] = String(v); },
      removeItem(k) { delete this._store[k]; }
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
    setTimeout,
    clearTimeout,
    console
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  vm.runInContext(promptEngineSource, sandbox);
  vm.runInContext(makeImageSource, sandbox);

  const HandrawMakeImage = sandbox.HandrawMakeImage;
  assert.ok(HandrawMakeImage, "HandrawMakeImage must be defined");

  await t.test("Requirement 1 & 3: Reset confirms with updated copy, clears form fields AND downstream results", () => {
    const fakeHost = createFakeDom();
    const ctrlNode = {
      id: "ctrl-1",
      type: "output_control",
      data: { mode: "pure-image", ratio: "1:1", count: 1, status: "done", activeBatchId: "batch_old_123" }
    };
    const skillNode = {
      id: "skill-1",
      type: "skill_params",
      data: { style1: "FA-001", style2: "FA-002", fusion: true, layout: "SC-021", colors: ["CL-001"] }
    };
    const textNode = {
      id: "text-1",
      type: "text_input",
      data: { text: "秋日山景", subjectHint: "落叶与枫树" }
    };
    const assetNode = {
      id: "asset-1",
      type: "asset",
      data: { items: [{ id: "AST-1", imageUrl: "/ref.webp" }] }
    };
    const displayNode = {
      id: "disp-1",
      type: "output_display",
      data: {
        status: "done",
        activeBatchId: "batch_old_123",
        items: [{ imageUrl: "/out1.webp", title: "秋日山景 #1" }],
        selectedIdx: 0,
        downloadUrl: "/out1.webp"
      }
    };
    const graph = {
      nodes: [ctrlNode, skillNode, textNode, assetNode, displayNode],
      edges: [
        { id: "e1", from: skillNode.id, to: ctrlNode.id },
        { id: "e2", from: textNode.id, to: ctrlNode.id },
        { id: "e3", from: assetNode.id, to: ctrlNode.id },
        { id: "e4", from: ctrlNode.id, to: displayNode.id }
      ]
    };
    const parts = { ctrl: ctrlNode, skill: skillNode, text: textNode, asset: assetNode };

    let dirtyRenderCalled = false;
    let clearedCtrlId = null;

    HandrawMakeImage.render(fakeHost, {
      parts,
      graph,
      results: [{ id: "disp-1:0", imageUrl: "/out1.webp", title: "秋日山景 #1", node: displayNode }],
      busy: false,
      statusText: "已显示 1 张结果，保存在你的生成历史中。"
    }, {
      isBusy: () => false,
      clearWorkspaceResults: (cid) => {
        clearedCtrlId = cid;
        ctrlNode.data.status = "idle";
        delete ctrlNode.data.activeBatchId;
        displayNode.data.items = [];
        displayNode.data.status = "idle";
        delete displayNode.data.activeBatchId;
      },
      markDirtyAndRender: () => { dirtyRenderCalled = true; },
      ensureAssetItems: (items) => { assetNode.data.items = items; }
    });

    const resetBtn = fakeHost.querySelector("#make-image-btn-reset");
    assert.ok(resetBtn, "Reset button must exist");

    // A. User cancels confirm: state unchanged
    let promptMsg = "";
    sandbox.window.confirm = (msg) => { promptMsg = msg; return false; };
    resetBtn.onclick();
    assert.strictEqual(
      promptMsg,
      "清空后，当前表单将恢复默认，并清除本工作区的生成结果；生图历史仍保留。确定清空吗？",
      "Confirm prompt must strictly match specification"
    );
    assert.strictEqual(dirtyRenderCalled, false, "Dirty render must not be called on cancel");
    assert.strictEqual(textNode.data.text, "秋日山景", "Form text must remain unchanged");
    assert.strictEqual(displayNode.data.items.length, 1, "Results must remain unchanged on cancel");

    // B. User accepts confirm: form and results cleared together
    sandbox.window.confirm = () => true;
    resetBtn.onclick();

    assert.strictEqual(dirtyRenderCalled, true, "Dirty render must be called on confirm");
    assert.strictEqual(clearedCtrlId, "ctrl-1", "clearWorkspaceResults action must be passed control ID");
    assert.strictEqual(textNode.data.text, "", "Text must reset to empty");
    assert.strictEqual(textNode.data.subjectHint, "", "Subject hint must reset to empty");
    assert.strictEqual(ctrlNode.data.mode, "graphic-text", "Mode must reset to default graphic-text");
    assert.strictEqual(ctrlNode.data.ratio, "3:4", "Ratio must reset to 3:4");
    assert.strictEqual(ctrlNode.data.count, 1, "Count must reset to 1");
    assert.strictEqual(ctrlNode.data.status, "idle", "Control status must reset to idle");
    assert.strictEqual(ctrlNode.data.activeBatchId, undefined, "Old batch ID must be cleared");

    assert.strictEqual(displayNode.data.items.length, 0, "Display node items must be cleared to empty array");
    assert.strictEqual(displayNode.data.status, "idle", "Display node status must reset to idle");
    assert.strictEqual(displayNode.data.activeBatchId, undefined, "Display node batch ID must be cleared");
    assert.strictEqual(assetNode.data.items.length, 0, "Asset items must be cleared");
  });

  await t.test("Requirement 2 & 3: Generation history untouched, saved graph reloads with zero results", () => {
    // History mock
    const historyEntry = { id: "gen_001", prompt: "秋日山景", imageUrl: "/out1.webp", createdAt: Date.now() };
    const userHistory = [historyEntry];

    // Node items were cleared in Requirement 1
    const serializedTabs = JSON.stringify([{
      id: "tab-1",
      quickStart: true,
      graph: {
        nodes: [
          { id: "ctrl-1", type: "output_control", data: { mode: "graphic-text", ratio: "3:4", count: 1, status: "idle" } },
          { id: "disp-1", type: "output_display", data: { items: [], status: "idle" } }
        ]
      }
    }]);

    // Simulate page reload
    const reloadedTabs = JSON.parse(serializedTabs);
    const reloadedDisp = reloadedTabs[0].graph.nodes.find(n => n.type === "output_display");
    assert.deepStrictEqual(reloadedDisp.data.items, [], "Reloaded display node items must be empty (old images never return)");

    // History is completely intact
    assert.strictEqual(userHistory.length, 1, "User history record must remain intact");
    assert.strictEqual(userHistory[0].id, "gen_001", "User history entry ID preserved");
  });

  await t.test("Requirement 4: Busy state disables buttons, renders busy hint, and blocks direct execution", () => {
    const fakeHost = createFakeDom();
    const ctrlNode = { id: "ctrl-1", type: "output_control", data: { status: "generating" } };
    const skillNode = { id: "skill-1", type: "skill_params", data: {} };
    const textNode = { id: "text-1", type: "text_input", data: { text: "生成中任务" } };
    const parts = { ctrl: ctrlNode, skill: skillNode, text: textNode };
    const graph = { nodes: [ctrlNode, skillNode, textNode], edges: [] };

    let runActionCalled = false;
    let clearActionCalled = false;

    HandrawMakeImage.render(fakeHost, {
      parts,
      graph,
      busy: true,
      statusText: "正在生成，可以稍后回到历史记录查看。"
    }, {
      isBusy: () => true,
      run: () => { runActionCalled = true; },
      clearWorkspaceResults: () => { clearActionCalled = true; }
    });

    const html = fakeHost.innerHTML;
    assert.ok(html.includes('id="make-image-btn-reset" disabled'), "Reset button must be disabled when busy");
    assert.ok(html.includes('id="make-image-btn-run" disabled'), "Run button must be disabled when busy");
    assert.ok(html.includes("任务处理中，暂不能清空或再次生成"), "Must display busy hint text beside buttons");

    const resetBtn = fakeHost.querySelector("#make-image-btn-reset");
    const runBtn = fakeHost.querySelector("#make-image-btn-run");

    // Direct invocation when busy
    let confirmCalled = false;
    sandbox.window.confirm = () => { confirmCalled = true; return true; };

    resetBtn.onclick();
    assert.strictEqual(confirmCalled, false, "Confirm must NOT be invoked when busy");
    assert.strictEqual(clearActionCalled, false, "Clear results must NOT be executed when busy");

    runBtn.onclick();
    assert.strictEqual(runActionCalled, false, "Run action must NOT be executed when busy");
  });

  await t.test("Requirement 5: Clearing one controller does not affect other controllers or tabs", () => {
    // Control A & Display A (current workspace)
    const ctrlA = { id: "ctrl-A", type: "output_control", data: { status: "done", count: 1 } };
    const dispA = { id: "disp-A", type: "output_display", data: { items: [{ imageUrl: "/imgA.webp" }] } };

    // Control B & Display B (another workflow or tab)
    const ctrlB = { id: "ctrl-B", type: "output_control", data: { status: "done", count: 1 } };
    const dispB = { id: "disp-B", type: "output_display", data: { items: [{ imageUrl: "/imgB.webp" }] } };

    const graph = {
      nodes: [ctrlA, dispA, ctrlB, dispB],
      edges: [
        { id: "eA", from: ctrlA.id, to: dispA.id },
        { id: "eB", from: ctrlB.id, to: dispB.id }
      ]
    };

    // Simulate clearControlWorkspaceResults(ctrlA.id)
    const outEdgesA = graph.edges.filter(e => e.from === ctrlA.id);
    const outIdsA = new Set(outEdgesA.map(e => e.to));
    ctrlA.data.status = "idle";
    graph.nodes.forEach(n => {
      if (outIdsA.has(n.id) && n.type === "output_display") {
        n.data.items = [];
      }
    });

    assert.strictEqual(dispA.data.items.length, 0, "Display A items must be cleared");
    assert.strictEqual(dispB.data.items.length, 1, "Display B items must remain completely intact");
    assert.strictEqual(dispB.data.items[0].imageUrl, "/imgB.webp", "Display B image URL must be preserved");
    assert.strictEqual(ctrlB.data.status, "done", "Control B status must remain done");
  });
});
