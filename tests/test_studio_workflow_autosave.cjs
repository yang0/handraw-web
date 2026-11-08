"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const from = source.indexOf("  function scheduleWorkflowAutoSave()");
const to = source.indexOf("  function exportWorkflowJsonFile(wfObj)", from);
assert.ok(from > 0 && to > from, "Studio workflow save API must be extractable");
const saveCode = source.slice(from, to);
assert.ok(source.includes('const unsynced = prev && ["local", "saving", "error", "conflict"]'),
  "Hydration must distinguish unconfirmed local state from server versions");
assert.ok(source.includes('prev.remoteUpdatedAtMs = Number(rw.updatedAtMs) || 0;'),
  "A remote concurrent version must be recorded without adopting its revision");
assert.ok(source.includes('data-wf-copy='), "Conflicting local workflow should offer Save as Copy");
assert.ok(source.includes('if (Array.isArray(ws.workflows))') &&
  source.includes('w.cloudSaveState !== "synced"'),
  "Cloud hydration must handle an empty remote workflow list without dropping pending local drafts");

function harness() {
  const timers = new Map();
  const requests = [];
  const messages = [];
  const writes = [];
  const tab = { id: "tab-1", savedId: "wf-1", title: "草稿", dirty: false, editRevision: 0 };
  const wf = { id: "wf-1", title: "草稿", blueprint: "single",
    graph: { blueprint: "single", nodes: [{ id: "original" }], edges: [] },
    cloudSaveState: "synced", serverUpdatedAtMs: 10 };
  const CS = { tabs: [tab], activeTabId: "tab-1", savedWorkflows: [wf],
    graph: { blueprint: "single", nodes: [{ id: "changed" }], edges: [] } };
  let respond = () => ({ ok: true, status: 200, json: async () => ({ ok: true, updatedAtMs: 11 }) });
  let nextTimer = 0;
  const sandbox = {
    CS,
    App: { state: { serverBacked: true, loggedIn: true } },
    E: { uid: () => "new-workflow-1" },
    activeCacheScope: "user-1",
    cacheScopeEpoch: 1,
    _workflowAutoSaveTimer: null,
    WORKFLOW_AUTO_SAVE_DELAY_MS: 1200,
    _projectAutoSaveTimer: null,
    PROJECT_AUTO_SAVE_DELAY_MS: 1600,
    ProjectClient: null, // the workflow save harness tests the independent template path
    isArticleTab: () => false,
    updateProjectStatusIndicator: () => {},
    SAVED_WORKFLOWS_KEY: "workflows",
    syncCurrentTabSnapshot: () => {},
    ensureDefaultSavedWorkflows: () => {},
    cloneGraph: (value) => JSON.parse(JSON.stringify(value)),
    writeJsonStorage: (key, value) => writes.push({ key, value: JSON.stringify(value) }),
    persistOpenTabs: () => {},
    renderTopAndBottomDocks: () => {},
    toast: (msg) => messages.push(msg),
    fetch: (url, options) => {
      requests.push({ url, payload: JSON.parse(options.body) });
      return respond(url, options);
    },
    setTimeout: (fn) => { const id = ++nextTimer; timers.set(id, fn); return id; },
    clearTimeout: (id) => { timers.delete(id); },
  };
  vm.createContext(sandbox);
  vm.runInContext(saveCode + "\nglobalThis.testSave = { markActiveTabDirty, saveCurrentWorkflow };", sandbox);
  return {
    sandbox, tab, wf, CS, timers, messages, requests, writes,
    setResponder: fn => { respond = fn; },
    async fireTimer() {
      const fn = [...timers.values()].at(-1);
      assert.ok(fn, "debounced save should exist");
      timers.clear();
      fn();
      await new Promise(resolve => setImmediate(resolve));
    }
  };
}

(async () => {
  {
    const h = harness();
    h.sandbox.testSave.markActiveTabDirty();
    assert.equal(h.tab.dirty, true);
    assert.equal(h.tab.editRevision, 1);
    assert.equal(h.timers.size, 1);
    await h.fireTimer();
    assert.equal(h.requests.length, 1);
    assert.equal(h.requests[0].payload.baseUpdatedAtMs, 10);
    assert.equal(h.requests[0].payload.graph.nodes[0].id, "changed");
    assert.equal(h.wf.serverUpdatedAtMs, 11);
    assert.equal(h.wf.cloudSaveState, "synced");
    assert.equal(h.tab.dirty, false);
    assert.deepEqual(h.messages, [], "quiet background save must not spam toasts");
  }
  {
    const h = harness();
    h.setResponder(async () => ({ ok: false, status: 409,
      json: async () => ({ error: "conflicting edits", code: "workflow_version_conflict" }) }));
    h.sandbox.testSave.markActiveTabDirty();
    await h.fireTimer();
    assert.equal(h.wf.cloudSaveState, "conflict");
    assert.equal(h.tab.dirty, true);
    assert.equal(h.requests.length, 1);
    assert.equal(await h.sandbox.testSave.saveCurrentWorkflow(), false);
    assert.equal(h.requests.length, 1, "manual retry must never overwrite conflict");
    assert.equal(h.wf.serverUpdatedAtMs, 10, "stale base cannot be upgraded implicitly");
  }
  {
    const h = harness();
    h.CS.tabs[0].savedId = null;
    h.sandbox.testSave.markActiveTabDirty();
    assert.equal(h.timers.size, 0, "new canvas must not become a named workflow silently");
  }
  {
    const h = harness();
    h.sandbox.App.state.loggedIn = false;
    h.sandbox.testSave.markActiveTabDirty();
    await h.sandbox.testSave.saveCurrentWorkflow();
    assert.equal(h.wf.cloudSaveState, "local");
    assert.equal(h.wf.serverUpdatedAtMs, 10);
    assert.equal(h.requests.length, 0);
    assert.ok(h.messages.some(m => m.includes("本机")));
  }
  {
    const h = harness();
    let release;
    h.setResponder(() => new Promise(resolve => { release = resolve; }));
    h.sandbox.testSave.markActiveTabDirty();
    const pending = h.sandbox.testSave.saveCurrentWorkflow(false, { silent: true });
    h.CS.graph.nodes.push({ id: "edit-while-uploading" });
    h.sandbox.testSave.markActiveTabDirty();
    release({ ok: true, status: 200, json: async () => ({ ok: true, updatedAtMs: 11 }) });
    await pending;
    assert.equal(h.tab.dirty, true, "later edit must not be acknowledged by older response");
    assert.ok(h.timers.size > 0, "later edit must schedule another save");
  }
  console.log("Studio workflow autosave tests passed: debounce, server ack, conflict, offline and in-flight edits");
})().catch(err => { console.error(err); process.exitCode = 1; });
