"use strict";
const assert = require("node:assert/strict");
const { createClient } = require("../demo/assets/studio-project-sync.js");

const snapshot = (subject = "春景") => ({
  kind: "image", authority: "graph", title: "我的画布",
  draft: { activeView: "canvas", graph: {
    blueprint: "single", nodes: [{ id: "n1", data: { text: subject } }], edges: []
  }}
});
function apiWith(fn) {
  let seq = 0;
  return createClient({ fetchImpl: fn,
    idFactory: prefix => prefix + "-fixed-" + ++seq });
}
async function test() {
  const requests = [];
  const respond = async (path, init) => {
    requests.push({ path, init, payload: JSON.parse(init.body) });
    return { ok: true, status: 200, json: async () => ({
      ok: true, projectId: "prj-fixed-1", revision: requests.length, saveState: "synced"
    }) };
  };
  const api = apiWith(respond);
  const tab = { id: "tab-1", title: "我的画布", editRevision: 1 };
  const stateUpdates = [];
  let result = await api.flush(tab, snapshot(), t => stateUpdates.push(t.projectSaveState));
  assert.equal(result.ok, true);
  assert.equal(tab.projectRevision, 1);
  assert.equal(tab.projectSaveState, "synced");
  assert.equal(tab.projectId, "prj-fixed-1");
  assert.equal(requests.length, 1);
  assert.equal(requests[0].init.method, "POST");
  assert.equal(requests[0].init.credentials, "include");
  assert.deepEqual(stateUpdates, ["saving", "synced"]);
  tab.editRevision = 2;
  result = await api.flush(tab, snapshot("夏景"));
  assert.equal(result.ok, true);
  assert.equal(tab.projectRevision, 2);
  assert.equal(requests[1].init.method, "PATCH");
  assert.equal(requests[1].payload.baseRevision, 1);
  assert.equal(requests[1].payload.patch[0].path, "/graph");
  assert.equal(requests[1].payload.patch[0].value.nodes[0].data.text, "夏景");

  // A transport exception can mean the server committed but the response was
  // lost. The same frozen payload + idempotency key MUST replay.
  let calls = [];
  let fail = true;
  const api2 = apiWith(async (path, init) => {
    calls.push(JSON.parse(init.body));
    if (fail) throw new Error("network ended after commit");
    return { ok: true, status: 200,
      json: async () => ({ ok: true, projectId: calls[0].projectId, revision: 1 }) };
  });
  const offlineTab = { editRevision: 4, title: "离线草稿" };
  const first = await api2.flush(offlineTab, snapshot());
  assert.equal(first.ok, false);
  assert.equal(offlineTab.projectSaveState, "error");
  assert.ok(offlineTab.projectPending);
  offlineTab.editRevision = 5;
  fail = false;
  const replay = await api2.flush(offlineTab, snapshot("新内容尚未提交"));
  assert.equal(replay.ok, true);
  assert.deepEqual(calls[0], calls[1], "Replay uses exactly the same request body");
  assert.equal(offlineTab.projectSaveState, "local_only",
    "Later edits must remain pending, not be falsely acknowledged");
  assert.equal(offlineTab.projectPending, null);
  await api2.flush(offlineTab, snapshot("新内容尚未提交"));
  assert.equal(calls[2].baseRevision, 1);
  assert.equal(calls[2].patch[0].value.nodes[0].data.text, "新内容尚未提交");

  // A two-tab conflict cannot be silently retried against a fresher version.
  let blocked = 0;
  const api3 = apiWith(async () => {
    blocked++;
    return { ok: false, status: 409,
      json: async () => ({ ok: false, code: "project_revision_conflict",
        currentRevision: 8, error: "云端已更新" }) };
  });
  const conflicted = { projectId: "prj-existing", projectRevision: 7,
    editRevision: 9, title: "冲突画布" };
  const conflict = await api3.flush(conflicted, snapshot("本机修改"));
  assert.equal(conflict.conflict, true);
  assert.equal(conflicted.projectSaveState, "conflict");
  assert.equal(conflicted.projectRemoteRevision, 8);
  await api3.flush(conflicted, snapshot("本机修改"));
  assert.equal(blocked, 1, "Conflict must not retry until explicitly resolved");

  let copied;
  const api4 = apiWith(async (path, init) => {
    copied = { path, payload: JSON.parse(init.body) };
    return { ok: true, status: 200,
      json: async () => ({ ok: true, revision: 1, projectId: copied.payload.newProjectId }) };
  });
  conflicted.projectPending = { path: "/old", payload: { old: true } };
  await api4.copyConflict(conflicted, snapshot("保留冲突草稿").draft);
  assert.ok(copied.path.endsWith("/prj-existing/copy"));
  assert.equal(copied.payload.localDraft.graph.nodes[0].data.text, "保留冲突草稿");
  assert.equal(conflicted.projectRevision, 1);
  assert.equal(conflicted.projectSaveState, "synced");
  assert.equal(conflicted.projectPending, null);
  assert.notEqual(conflicted.projectId, "prj-existing");
  console.log("Studio2 Project client passes CAS/outbox/replay/conflict/copy tests");
}
test().catch(err => { console.error(err); process.exitCode = 1; });
