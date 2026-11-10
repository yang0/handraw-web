"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const src = fs.readFileSync("demo/assets/studio-app.js", "utf8");
assert.ok(src.includes('id="studio-mode-view-toggle"'),
  "One contextual control must navigate between form and canvas");
assert.ok(src.includes('切换到画布 →') && src.includes('← 返回表单'),
  "View toggle must show each destination");
assert.ok(!src.includes('id="studio-mode-simple"') &&
  !src.includes('id="studio-mode-canvas"'),
  "Old duplicated view buttons must not remain");
assert.ok(src.includes('if (next === "simple")'),"View switch should check representability");
assert.ok(src.includes("getQuickParts(CS.graph)"),"Simple form requires a safely editable graph");
assert.ok(src.includes("getBatchParts(CS.graph)"),"Series form requires a safely editable graph");
assert.ok(src.includes("复杂项目：仅摘要/局部可编辑"),"Complex graph has safe partial summary");
assert.ok(src.includes("renderGraphSummaryInSimpleView"),"Complex graph must not create a blank workflow");
assert.ok(src.includes("current.projectActiveView = view"),"View changes only edit Project metadata");
assert.ok(!/function switchCreationStage\(next\)[\s\S]*?function renderCreationModeBar\(\)/.exec(src)[0].includes("generateSingleImage("),"View transition never sends a new generation");
assert.ok(src.includes("lastStudioTaskView"),"Canvas retains its originating creation task");
assert.ok(src.includes('p.ctrl.data.ratioSource = "user"'),"Explicit ratio must survive mode changes");
console.log("studio2 navigation and view switching safety contract passes");
