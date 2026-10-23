"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const frames = [], events = new Map();
let callback, disconnected = false;
const window = {
  innerHeight: 800,
  addEventListener: (key, fn) => events.set(key, fn),
  removeEventListener: (key) => events.delete(key),
};
vm.runInNewContext(fs.readFileSync("plugin/public/studio.js", "utf8"), {
  window,
  requestAnimationFrame: (fn) => frames.push(fn),
  IntersectionObserver: class {
    constructor(fn) { callback = fn; }
    observe() {}
    disconnect() { disconnected = true; }
  },
});
const oldDraft = { style: "FA-001", character_style: "FA-002", scene_style: "FA-003", fusion: true, theme: "保留用户主题", tones: ["T-01"], layout: "SC-001" };
const restored = window.HandrawStudioDraft.restore(oldDraft);
for (const key of ["style", "character_style", "scene_style"])
  assert.equal(restored[key], "", "old drafts cannot preselect a style on entry");
assert.equal(restored.fusion, false);
assert.equal(restored.theme, oldDraft.theme);
assert.equal(restored.layout, oldDraft.layout);
assert.equal(restored.tones, oldDraft.tones);
assert.equal(oldDraft.style, "FA-001", "restoring does not mutate the saved object");
assert.equal(Object.keys(window.HandrawStudioDraft.restore(null)).length, 0);
let top = 1300, more = true, calls = 0, finish, fail = false;
const root = {
  open: true,
  getBoundingClientRect: () => ({ top: 20, bottom: 760 }),
  addEventListener: (key, fn) => events.set(key, fn),
  removeEventListener: (key) => events.delete(key),
};
const errors = [];
const pager = window.HandrawStudioPager({
  root,
  sentinel: { isConnected: true, getBoundingClientRect: () => ({ top, bottom: top + 2 }) },
  hasMore: () => more,
  load: async () => {
    calls++;
    if (fail) throw Error("temporary failure");
    await new Promise((resolve) => { finish = resolve; });
  },
  onError: (error) => errors.push(error.message),
});
(async () => {
  await callback();
  assert.equal(calls, 0, "distant pages stay unloaded");
  top = 950;
  const pending = callback();
  await callback();
  events.get("resize")();
  assert.equal(calls, 1, "viewport notifications do not overlap requests");
  top = 1300;
  finish();
  await pending;
  await frames.shift()();
  assert.equal(calls, 1, "appending a page stops when its end moves out of view");
  top = 950;
  fail = true;
  await callback();
  await callback();
  assert.equal(calls, 2, "failed requests do not loop automatically");
  assert.deepEqual(errors, ["temporary failure"]);
  fail = false;
  events.get("scroll")();
  assert.equal(calls, 3, "scrolling can retry a failed page");
  more = false;
  finish();
  await new Promise(setImmediate);
  await callback();
  assert.equal(calls, 3, "exhausted results stop loading");
  pager.stop();
  more = true;
  await callback();
  assert.equal(calls, 3);
  assert.equal(disconnected, true);
  assert.equal(events.size, 0, "closing the dialog removes viewport listeners");
  console.log("Studio picker: viewport loading, serial requests, bounded append, failure retry and cleanup passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
