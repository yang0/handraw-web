/* Studio 2.0 Project transport and CAS outbox.
 * Do not equate a local draft, a workflow template, a Run and a public Work.
 * Persist the entire in-flight request so ambiguous network responses replay
 * the SAME idempotency key and payload rather than creating a false conflict.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.HandrawStudioProjectSync = api;
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  function newId(prefix = "p") {
    const u = typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
    return prefix + "-" + u.replace(/[^A-Za-z0-9_-]/g, "-");
  }

  function requestError(response, payload) {
    const err = new Error(payload?.error || "项目云端同步失败");
    err.status = Number(response?.status || 0);
    err.code = payload?.code || "project_sync_failed";
    err.currentRevision = Number(payload?.currentRevision || 0);
    return err;
  }

  const clone = value => value == null ? value : JSON.parse(JSON.stringify(value));
  const ViewModel = typeof window !== "undefined" ? window.HandrawStudioViews
    : typeof require === "function" ? require("./studio-views.js") : null;

  function authorityPatch(tab, snapshot) {
    if (tab.projectAuthority !== "spec") return draftPatch(tab, snapshot);
    if (snapshot.authority === "spec") {
      const patch = [
        {op:"set",path:"/creationSpec",value:snapshot.draft.creationSpec},
        {op:"set",path:"/activeView",value:"simple"}
      ];
      if (snapshot.draft.plan) patch.push({op:"set",path:"/plan",value:snapshot.draft.plan});
      if (snapshot.draft.editorLayout) {
        patch.push({op:"set",path:"/editorLayout",value:snapshot.draft.editorLayout});
      }
      patch.push({op:"set",path:"/title",value:snapshot.title || "未命名创作"});
      return patch;
    }
    if (snapshot.authority === "graph" && snapshot.draft.graph) {
      // Switch source atomically under the same baseRevision; the server
      // refuses graph writes while Spec is still the sole authority.
      return [
        {op:"set",path:"/authority",value:"graph"},
        {op:"set",path:"/graph",value:snapshot.draft.graph},
        {op:"set",path:"/activeView",value:"canvas"},
        {op:"set",path:"/editorLayout",value:snapshot.draft.editorLayout || {}},
        {op:"set",path:"/title",value:snapshot.title || "未命名创作"}
      ];
    }
    throw new Error("invalid_authority_transition");
  }

  function draftPatch(tab, snapshot) {
    const patches = [];
    const graph = snapshot.draft.graph;
    const baseline = tab.projectSyncedGraph || null;
    const graphChanges = ViewModel && baseline && graph
      ? ViewModel.graphFieldPatches(baseline, graph) : null;
    if (graphChanges && graphChanges.length <= 27) {
      patches.push(...graphChanges);
    } else if (graphChanges && graphChanges.length > 27) {
      // Never replace a multi-branch Graph just to fit the server patch limit.
      throw new Error("too_many_graph_patches");
    } else if (graph) {
      patches.push({op:"set",path:"/graph",value:graph});
    }
    patches.push({op:"set",path:"/activeView",
      value:snapshot.draft.activeView || "canvas"});
    if (snapshot.draft.editorLayout) {
      patches.push({op:"set",path:"/editorLayout",value:snapshot.draft.editorLayout});
    }
    patches.push({op:"set",path:"/title",value:snapshot.title || "未命名创作"});
    return patches;
  }

  function createClient({ fetchImpl = (...args) => fetch(...args), idFactory = newId } = {}) {
    async function request(method, path, body) {
      const response = await fetchImpl(path, {
        method,
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        ...(body === undefined ? {} : { body: JSON.stringify(body) })
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok || !payload || payload.ok !== true) {
        throw requestError(response, payload);
      }
      return payload;
    }

    function stage(tab, snapshot) {
      if (!tab || !snapshot || !snapshot.draft || !snapshot.kind) {
        throw new Error("缺少可保存的项目快照");
      }
      if (tab.projectPending) return tab.projectPending;
      if (!tab.projectId) tab.projectId = idFactory("prj");
      const key = idFactory("edit");
      const payload = Number(tab.projectRevision || 0) < 1
        ? {
            projectId: tab.projectId,
            kind: snapshot.kind,
            authority: snapshot.authority || "graph",
            title: snapshot.title || "未命名创作",
            draft: snapshot.draft,
            idempotencyKey: key
          }
        : {
            baseRevision: Number(tab.projectRevision),
            idempotencyKey: key,
            patch: authorityPatch(tab, snapshot)
          };
      tab.projectPending = {
        method: Number(tab.projectRevision || 0) < 1 ? "POST" : "PATCH",
        path: Number(tab.projectRevision || 0) < 1
          ? "/api/studio/projects"
          : "/api/studio/projects/" + encodeURIComponent(tab.projectId) + "/draft",
        payload,
        atEditRevision: Number(tab.editRevision || 0),
        confirmedGraph: clone(snapshot.draft.graph || null),
        confirmedAuthority: snapshot.authority || "graph"
      };
      tab.projectSaveState = "local_only";
      return tab.projectPending;
    }

    async function flush(tab, snapshot, onChange = () => {}) {
      if (tab?.projectSaveState === "conflict") return { ok: false, conflict: true };
      if (tab?.projectPromise) return tab.projectPromise;
      const pending = tab?.projectPending || stage(tab, snapshot);
      if (!pending) return { ok: false };
      tab.projectSaveState = "saving";
      onChange(tab);
      const promise = (async () => {
        try {
          const result = await request(pending.method, pending.path, pending.payload);
          // Responses acknowledge exactly the frozen payload, not edits that
          // arrived while it was running.
          tab.projectRevision = Number(result.revision);
          tab.projectAuthority = pending.confirmedAuthority || tab.projectAuthority || "graph";
          if (pending.confirmedGraph) tab.projectSyncedGraph = clone(pending.confirmedGraph);
          tab.projectPending = null;
          tab.projectSaveState = Number(tab.editRevision || 0) > pending.atEditRevision
            ? "local_only" : "synced";
          tab.projectRemoteRevision = 0;
          tab.projectError = "";
          onChange(tab);
          return { ok: true, result, needsSave: tab.projectSaveState !== "synced" };
        } catch (err) {
          const conflict = err.status === 409;
          tab.projectSaveState = conflict ? "conflict" : "error";
          tab.projectRemoteRevision = err.currentRevision || 0;
          tab.projectError = err.code || "project_sync_failed";
          onChange(tab);
          return { ok: false, conflict, error: err };
        } finally {
          if (tab.projectPromise === promise) delete tab.projectPromise;
        }
      })();
      tab.projectPromise = promise;
      return promise;
    }

    async function copyConflict(tab, localDraft, onChange = () => {}) {
      if (!tab?.projectId || tab.projectSaveState !== "conflict") {
        throw new Error("项目没有待处理的云端冲突");
      }
      // A lost copy response is as ambiguous as a lost patch response:
      // preserve the new ID and key so Retry does not create duplicate copies.
      if (!tab.projectCopyPending) {
        tab.projectCopyPending = {
          path: "/api/studio/projects/" + encodeURIComponent(tab.projectId) + "/copy",
          payload: {
            newProjectId: idFactory("prj"), localDraft,
            authority: tab.projectAuthority || "graph",
            title: tab.title || "本机创作",
            idempotencyKey: idFactory("copy")
          }
        };
        onChange(tab);
      }
      const pending = tab.projectCopyPending;
      const response = await request("POST", pending.path, pending.payload);
      tab.projectId = pending.payload.newProjectId;
      tab.projectRevision = Number(response.revision);
      tab.projectPending = null;
      tab.projectCopyPending = null;
      tab.projectRemoteRevision = 0;
      tab.projectSaveState = "synced";
      tab.projectSyncedGraph = clone(localDraft?.graph || null);
      tab.projectError = "";
      onChange(tab);
      return response;
    }

    return {
      stage, flush, copyConflict,
      list: ({query = "", cursor = "", limit = 40} = {}) => {
        const params = new URLSearchParams();
        if (query) params.set("q", String(query));
        if (cursor) params.set("cursor", String(cursor));
        params.set("limit", String(limit));
        return request("GET", "/api/studio/projects?" + params.toString());
      },
      get: id => request("GET", "/api/studio/projects/" + encodeURIComponent(id)),
      newId: idFactory
    };
  }

  return { createClient, newId };
});
