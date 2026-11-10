"use strict";

// Issue #135: studio-ai-plan.js captured its dependencies (HandrawQuickSpec /
// HandrawStudioSeries / HandrawStudioResources / HandrawStudioCore) while the
// page parsed it. studio.html loaded it BEFORE those files, so `Series` was
// permanently null and AI.apply() died with
// "Cannot read properties of null (reading 'read')".
//
// This guards both halves of the fix:
//   1. studio.html must load the dependency scripts before studio-ai-plan.js.
//   2. studio-ai-plan.js must resolve dependencies lazily.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "demo", "studio.html"), "utf8");
const aiPlanSrc = fs.readFileSync(
  path.join(root, "demo", "assets", "studio-ai-plan.js"), "utf8"
);

// --- 1. script order -------------------------------------------------------
const tags = [...html.matchAll(/<script src="\/assets\/([^"?]+)[^"]*"/g)]
  .map((m) => m[1]);
const idx = (name) => tags.indexOf(name);
assert.ok(idx("studio-ai-plan.js") > -1, "studio-ai-plan.js must be loaded");

for (const dep of [
  "studio-quick-spec.js",
  "studio-series-plan.js",
  "studio-resources.js",
  "studio-core.js",
]) {
  assert.ok(idx(dep) > -1, `${dep} must be loaded`);
  assert.ok(
    idx(dep) < idx("studio-ai-plan.js"),
    `${dep} must load BEFORE studio-ai-plan.js (got ${idx(dep)} vs ${idx("studio-ai-plan.js")})`
  );
}

// studio-batch.js drives the AI handlers, so it must come after ai-plan too.
assert.ok(
  idx("studio-batch.js") > idx("studio-ai-plan.js"),
  "studio-batch.js must load after studio-ai-plan.js"
);

// --- 2. lazy dependency resolution ----------------------------------------
assert.match(
  aiPlanSrc,
  /const\s+lazy\s*=/,
  "studio-ai-plan.js must resolve dependencies lazily"
);
assert.doesNotMatch(
  aiPlanSrc,
  /factory\(\s*root\.HandrawQuickSpec\s*\|\|/,
  "dependencies must not be captured eagerly in the factory call"
);

// --- 3. runtime behaviour: load the module before its dependencies ---------
const sandbox = { console };
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

vm.runInContext(aiPlanSrc, sandbox, { filename: "studio-ai-plan.js" });
const AI = sandbox.HandrawStudioAIPlan;
assert.ok(AI, "HandrawStudioAIPlan must register even if deps are absent");

// With no dependency globals present, calls must fail with a coded error
// instead of a bare TypeError.
const parts = {
  skill: { data: {} }, text: { data: {} }, ctrl: { data: {} },
};
let coded = null;
try {
  AI.apply(
    { baseRevision: 0, planRevision: 0, changes: [], conflicts: [],
      planned: [], source: { creationSpecPatch: {} } },
    { parts, loop: null, catalog: { styles: [], layouts: [] }, approvedKeys: [] }
  );
} catch (err) {
  coded = err.code;
}
assert.equal(
  coded, "ai_plan_dependencies_missing",
  `expected a coded dependency error, got ${coded}`
);

// Once the dependency appears later, the same module must use it.
let called = false;
sandbox.HandrawQuickSpec = { read: () => { called = true; return { spec: { revision: 0 } }; } };
sandbox.HandrawStudioResources = { resolveSelection: () => ({ ok: true, ref: {} }) };
sandbox.HandrawStudioCore = { validateRatio: () => ({ ok: true }) };
try {
  AI.apply(
    { baseRevision: 0, planRevision: 0, changes: [], conflicts: [],
      planned: [], source: { creationSpecPatch: {} } },
    { parts, loop: null, catalog: { styles: [], layouts: [] }, approvedKeys: [] }
  );
} catch (_) {
  // Later validation may still reject the empty report; only the dependency
  // resolution matters here.
}
assert.equal(called, true, "late-registered dependencies must be picked up");

console.log("test_studio_ai_plan_script_order_135: ok");
