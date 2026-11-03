"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

// Mock browser globals for prompt engine
global.window = global;
global.document = {
  createElement: () => ({ style: {} }),
  head: { appendChild: () => {} }
};

const promptEngineCode = fs.readFileSync(path.join(__dirname, "../demo/assets/studio-prompt-engine.js"), "utf8");
eval(promptEngineCode);
const Engine = window.HANDRAW_CANVAS_ENGINE;

test("Prompt engine: usable style without definition only includes ID, never placeholder text", () => {
  const resourceMap = new Map();
  resourceMap.set("USR-S99", {
    id: "USR-S99",
    name: "付费社区画风",
    kind: "style",
    definition: null,
    canUse: true,
    unlockCost: 10,
    sourceType: "community"
  });

  const catalog = { resourceMap, tones: [] };
  const graph = {
    nodes: [
      {
        id: "sp1",
        type: "skill_params",
        data: { style1: "USR-S99" }
      },
      {
        id: "ctrl1",
        type: "output_control",
        data: { mode: "pure", ratio: "3:4" }
      }
    ],
    edges: [
      { id: "e1", from: "sp1", to: "ctrl1" }
    ]
  };

  const ctrlNode = graph.nodes[1];

  // 1. Skill format
  const skillPrompt = Engine.assembleControlPrompt(graph, ctrlNode, catalog, "skill");
  assert.ok(skillPrompt.includes("画风：#USR-S99"), "Skill prompt must contain style code");
  assert.ok(!skillPrompt.includes("null"), "Skill prompt must not contain 'null'");
  assert.ok(!skillPrompt.includes("undefined"), "Skill prompt must not contain 'undefined'");
  assert.ok(!skillPrompt.includes("CLOUD_BLACKBOX"), "Skill prompt must not contain blackbox placeholder");
  assert.ok(!skillPrompt.includes("LOCKED_ASSET"), "Skill prompt must not contain locked placeholder");

  // 2. Cloud format
  const cloudPrompt = Engine.assembleControlPrompt(graph, ctrlNode, catalog, "cloud");
  assert.ok(cloudPrompt.includes("【画风】：#USR-S99"), "Cloud prompt must contain style code");
  assert.ok(!cloudPrompt.includes("null"), "Cloud prompt must not contain 'null'");
  assert.ok(!cloudPrompt.includes("undefined"), "Cloud prompt must not contain 'undefined'");
  assert.ok(!cloudPrompt.includes("CLOUD_BLACKBOX"), "Cloud prompt must not contain blackbox placeholder");
  assert.ok(!cloudPrompt.includes("LOCKED_ASSET"), "Cloud prompt must not contain locked placeholder");

  // 3. English format
  const enPrompt = Engine.assembleControlPrompt(graph, ctrlNode, catalog, "en");
  assert.ok(enPrompt.includes("[Style]: #USR-S99"), "English prompt must contain style code");
});

test("Prompt engine: style with blackbox/locked placeholder definition never leaks placeholder into assembled prompt", () => {
  const resourceMap = new Map();
  resourceMap.set("USR-S88", {
    id: "USR-S88",
    name: "已解锁付费画风",
    kind: "style",
    definition: "[CLOUD_BLACKBOX::USR-S88] 付费共创资产（已解锁，仅限在线创作工坊云端生图自动注入底层视觉参数）",
    canUse: true,
    unlockCost: 20,
    sourceType: "community"
  });
  resourceMap.set("USR-L88", {
    id: "USR-L88",
    name: "已解锁付费图型",
    kind: "layout",
    definition: "[CLOUD_BLACKBOX::USR-L88] 仅限在线创作工坊云端生图自动注入底层视觉参数。",
    canUse: true,
    unlockCost: 15,
    sourceType: "community"
  });

  const catalog = { resourceMap, tones: [] };
  const graph = {
    nodes: [
      {
        id: "sp1",
        type: "skill_params",
        data: { style1: "USR-S88", layout: "USR-L88" }
      },
      {
        id: "ctrl1",
        type: "output_control",
        data: { mode: "graphic-text", ratio: "3:4" }
      }
    ],
    edges: [
      { id: "e1", from: "sp1", to: "ctrl1" }
    ]
  };

  const ctrlNode = graph.nodes[1];

  for (const fmt of ["skill", "cloud", "en"]) {
    const prompt = Engine.assembleControlPrompt(graph, ctrlNode, catalog, fmt);
    assert.ok(!prompt.includes("CLOUD_BLACKBOX"), `Prompt in format ${fmt} must not leak CLOUD_BLACKBOX placeholder`);
    assert.ok(!prompt.includes("仅限在线创作工坊"), `Prompt in format ${fmt} must not leak placeholder text`);
    assert.ok(!prompt.includes("LOCKED_ASSET"), `Prompt in format ${fmt} must not leak LOCKED_ASSET`);
  }
});
