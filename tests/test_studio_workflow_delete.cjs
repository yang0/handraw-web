"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const src = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const begin = src.indexOf('    DOM.workflowsStage.querySelectorAll("[data-wf-rm]")');
const end = src.indexOf("\n  }\n\n  /* ======================== UNDO/REDO", begin);
assert.ok(begin > 0 && end > begin, "Find the workflow delete event handler");
const fragment = src.slice(begin, end);

function setup(fetcher) {
  const btn = { disabled: false, getAttribute: () => "wf-a" };
  const wf = { id: "wf-a", title: "Need cloud confirmation", isOfficialPreset: false };
  const tab = { id: "tab-a", savedId: "wf-a", dirty: false };
  const CS = { savedWorkflows: [wf], tabs: [tab] };
  const notices = [];
  const sandbox = {
    DOM: { workflowsStage: { querySelectorAll: () => [btn] } },
    CS, App: { state: { serverBacked: true, loggedIn: true } },
    activeCacheScope: "user-a", cacheScopeEpoch: 1,
    fetch: fetcher, toast: s => notices.push(s),
    SAVED_WORKFLOWS_KEY: "wf",
    writeJsonStorage: () => {},
    persistOpenTabs: () => {},
    renderTopAndBottomDocks: () => {}
  };
  vm.createContext(sandbox);
  vm.runInContext(fragment, sandbox);
  assert.equal(typeof btn.onclick, "function");
  return { btn, tab, CS, sandbox, notices };
}

(async () => {
  {
    const h = setup(async () => ({ ok: false, status: 503,
      json: async () => ({ ok: false, error: "unavailable" }) }));
    await h.btn.onclick();
    assert.equal(h.CS.savedWorkflows.length, 1, "Failed delete cannot hide local workflow");
    assert.equal(h.tab.savedId, "wf-a");
    assert.equal(h.btn.disabled, false, "Failed request must enable retry");
    assert.ok(h.notices.some(s => s.includes("失败")));
  }
  {
    const h = setup(async () => ({ ok: true, status: 200,
      json: async () => ({ ok: true }) }));
    await h.btn.onclick();
    assert.equal(h.CS.savedWorkflows.length, 0, "Only acknowledged cloud deletion removes the card");
    assert.equal(h.tab.savedId, null, "Open tab cannot resurrect deleted workflow");
    assert.equal(h.tab.dirty, true, "Open graph becomes an unsynced local draft");
    assert.ok(h.notices.some(s => s.includes("云端删除")));
  }
  {
    let release;
    const h = setup(() => new Promise(resolve => { release = resolve; }));
    const pending = h.btn.onclick();
    h.sandbox.activeCacheScope = "user-b";
    h.sandbox.cacheScopeEpoch = 2;
    release({ ok: true, status: 200, json: async () => ({ ok: true }) });
    await pending;
    assert.equal(h.CS.savedWorkflows.length, 1, "Old account response cannot mutate new account state");
  }
  console.log("Studio workflow deletion tests passed: failed request, acknowledged deletion, scope isolation");
})().catch(err => { console.error(err); process.exitCode = 1; });
