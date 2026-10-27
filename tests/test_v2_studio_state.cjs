"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const shared = fs.readFileSync("demo/assets/shared.js", "utf8");
const loader = fs.readFileSync("demo/assets/image-loader.js", "utf8");

// Private Studio caches are scoped after the server identifies the user, and
// the account-switch path invalidates pending hydration/sync work.
for (const key of [
  "handraw_canvas_uploads_v3",
  "handraw_saved_workflows_v10",
  "handraw_open_tabs_v10",
  "handraw_gen_history_v4",
  "handraw_my_articles_v1"
]) assert.match(studio, new RegExp(key.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")));
assert.match(studio, /SCOPED_STORAGE_KEYS/);
assert.match(studio, /`\$\{key\}::\$\{scope\}`/);
assert.match(studio, /cacheScopeEpoch\s*\+=\s*1/);
assert.match(studio, /_workspaceHydrationController\.abort/);
assert.match(studio, /requestScope !== activeCacheScope/);

// Normal users cannot silently fall back to sample output or seeded private
// articles/history. Demo output is an explicit, visibly-labelled mode.
assert.match(studio, /CS\.engineMode\s*=\s*configured \? "api" : CS\.demoMode \? "demo" : "disabled"/);
assert.match(studio, /isDemoGenerationEnabled\(\)/);
assert.match(studio, /generationMode = useLiveApi \? "live" : "demo"/);
assert.match(studio, /demoMode: isDemoGenerationEnabled\(\)/);
assert.match(studio, /isExplicitDemoMode\(\) \? createSeededMyArticles\(\) : \[\]/);
assert.match(studio, /isExplicitDemoMode\(\) \? createSeededGenerationHistory\(\) : \[\]/);
assert.match(studio, /requestId/);
assert.match(studio, /confirmCost: true/);
assert.match(studio, /cancelActiveBatchGeneration/);
assert.match(studio, /api\/studio\/history\/delete/);
assert.match(studio, /all \? \{ all: true \} : \{ id \}/);
assert.match(studio, /pendingTasks/);

// Fresh-release ranking uses only a numeric publication timestamp and a
// rolling 72-hour window; labels such as “刚刚” are not accepted.
const freshSource = shared.match(/function isFreshRelease\(item, nowMs = Date\.now\(\)\) \{[\s\S]*?\n  \}/);
assert.ok(freshSource, "isFreshRelease should remain directly testable");
const isFreshRelease = vm.runInNewContext(`(${freshSource[0]})`);
const now = 1_800_000_000_000;
assert.equal(isFreshRelease({ createdAt: "刚刚" }, now), false);
assert.equal(isFreshRelease({ publishedAtMs: now - 72 * 60 * 60 * 1000 }, now), true);
assert.equal(isFreshRelease({ publishedAtMs: now - 72 * 60 * 60 * 1000 - 1 }, now), false);
assert.equal(isFreshRelease({ publishedAtMs: now + 1 }, now), false);

// Execute the shared chrome renderer in both modes. Normal boot state must
// remove the demo-only sandbox controls (including the simulated-domain label
// and persona switcher), while explicit demo state may render them.
{
  class FakeElement {
    constructor(document) {
      this.document = document;
      this.children = [];
      this.listeners = new Map();
      this.classList = { add() {}, remove() {}, contains() { return false; } };
      this.style = {};
      this._id = "";
      this._innerHTML = "";
    }
    set id(value) {
      this._id = String(value || "");
      if (this._id) this.document.elements.set(this._id, this);
    }
    get id() { return this._id; }
    set innerHTML(value) {
      this._innerHTML = String(value || "");
      for (const [, id] of this._innerHTML.matchAll(/\bid=["']([^"']+)["']/g)) {
        const child = new FakeElement(this.document);
        child.id = id;
        this.children.push(child);
      }
    }
    get innerHTML() { return this._innerHTML; }
    append(...nodes) { this.children.push(...nodes); }
    appendChild(node) { this.children.push(node); }
    prepend(...nodes) { this.children.unshift(...nodes); }
    insertAdjacentElement(_position, node) { this.children.push(node); }
    querySelectorAll() { return []; }
    addEventListener(name, fn) { this.listeners.set(name, fn); }
    setAttribute() {}
    getAttribute() { return null; }
    remove() { if (this.id) this.document.elements.delete(this.id); }
  }
  class FakeDocument {
    constructor() {
      this.elements = new Map();
      this.body = new FakeElement(this);
    }
    createElement() { return new FakeElement(this); }
    getElementById(id) { return this.elements.get(id) || null; }
    addEventListener() {}
  }
  const document = new FakeDocument();
  const window = {
    location: { hostname: "localhost", port: "3190", protocol: "http:", search: "" },
    addEventListener() {}
  };
  const context = {
    window,
    document,
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    URLSearchParams,
    setTimeout() { return 1; },
    clearTimeout() {},
    console: { warn() {}, error() {}, log() {} }
  };
  vm.runInNewContext(shared, context);
  const sharedApi = window.HANDRAW_SHARED;
  const app = sharedApi.App;
  app.channel = "main";
  app.view = "styles";
  app.styles = [];
  app.layouts = [];
  app.resourceMap = new Map();
  app.state = {
    demoMode: false,
    loggedIn: false,
    user: { username: "guest", role: "guest" },
    collections: { styles: [], layouts: [], works: [], topics: [] },
    works: [],
    totalWorksCount: 0,
    siteSettings: {}
  };
  sharedApi.renderChrome();
  const sandbox = document.getElementById("hw-sandbox-mount");
  assert.ok(sandbox, "chrome should keep a mount point for normal rerenders");
  assert.equal(sandbox.innerHTML, "", "normal mode must not render demo controls");
  assert.doesNotMatch(sandbox.innerHTML, /当前模拟域名|多角色秒切|超管|重置/);

  app.state.demoMode = true;
  sharedApi.renderChrome();
  assert.match(sandbox.innerHTML, /当前模拟域名/);
  assert.match(sandbox.innerHTML, /多角色秒切/);

  app.state.demoMode = false;
  sharedApi.renderChrome();
  assert.equal(sandbox.innerHTML, "", "switching back to normal removes stale demo controls");
}

// An empty server-provided exclusive list must not be replaced with the
// legacy mock FX resources. This executes applyBootState/rebuildResourceIndexes
// in a normal-mode VM and checks the resulting catalog, not just the source.
{
  const document = { getElementById() { return null; }, body: { prepend() {}, append() {} }, createElement() { return { id: "", innerHTML: "", append() {}, prepend() {}, insertAdjacentElement() {}, querySelectorAll() { return []; } }; }, addEventListener() {} };
  const window = { location: { hostname: "localhost", port: "3190", protocol: "http:", search: "" } };
  const context = {
    window,
    document,
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    URLSearchParams,
    setTimeout() { return 1; },
    clearTimeout() {},
    console: { warn() {}, error() {}, log() {} }
  };
  vm.runInNewContext(shared, context);
  const sharedApi = window.HANDRAW_SHARED;
  sharedApi.App.catalogRaw = { resources: [] };
  sharedApi.App.state = {
    demoMode: false,
    exclusiveResources: [],
    communityResources: [],
    officialOverrides: [],
    forumBoards: [],
    forumModerators: [],
    assetComments: {},
    assetSeedMetrics: {},
    assetLiveLikes: {},
    assetLiveFavorites: []
  };
  sharedApi.applyBootState(sharedApi.App.state);
  assert.equal(sharedApi.App.styles.length, 0, "normal empty exclusive list remains empty");
  assert.equal(sharedApi.App.layouts.length, 0, "normal empty exclusive list has no mock layouts");
  assert.equal(sharedApi.App.resourceMap.size, 0, "no mock exclusive resources leak into normal boot");
}

assert.match(loader, /MAX_ACTIVE\s*=\s*2/);
assert.match(loader, /START_INTERVAL\s*=\s*600/);
assert.match(loader, /RETRY_DELAY\s*=\s*10_000/);
assert.match(loader, /data-hw-src/);

// Execute the demo loader with a tiny deterministic DOM instead of merely
// checking constants: hidden images wait for an intersection, starts are
// paced, two requests are the maximum, and failures require the cooldown plus
// an explicit retry.
{
  let now = 0;
  let timerId = 0;
  const timers = new Map();
  const starts = [];
  const notices = [];
  let io;

  class FakeElement {
    constructor() {
      this.dataset = {};
      this.listeners = new Map();
      this.children = [];
      this.style = {};
      this.isConnected = true;
      this.visible = true;
    }
    setAttribute() {}
    addEventListener(name, fn) {
      if (!this.listeners.has(name)) this.listeners.set(name, new Set());
      this.listeners.get(name).add(fn);
    }
    removeEventListener(name, fn) {
      this.listeners.get(name)?.delete(fn);
    }
    emit(name) {
      for (const fn of [...(this.listeners.get(name) || [])]) fn();
    }
    getClientRects() { return this.visible ? [{}] : []; }
    getBoundingClientRect() { return { top: 10, bottom: 100, left: 10, right: 100 }; }
    append(...nodes) { this.children.push(...nodes); }
    remove() { this.isConnected = false; }
    set src(value) {
      this._src = value;
      starts.push({ image: this, value, at: now });
    }
    get src() { return this._src || ""; }
  }

  function advance(ms) {
    const end = now + ms;
    for (let i = 0; i < 10000; i += 1) {
      const next = [...timers.entries()].filter(([, item]) => item.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) { now = end; return; }
      timers.delete(next[0]);
      now = next[1].at;
      next[1].fn();
    }
    throw new Error("image loader timer loop exceeded");
  }

  const images = Array.from({ length: 4 }, () => new FakeElement());
  images.forEach((img, idx) => { img.dataset.hwSrc = `/queue-${idx}.webp`; });
  images[3].visible = false;
  const document = {
    readyState: "complete",
    documentElement: {},
    body: { append(node) { notices.push(node); } },
    createElement() { return new FakeElement(); },
    querySelectorAll() { return images; },
    addEventListener() {}
  };
  class IntersectionObserver {
    constructor(callback) { this.callback = callback; io = this; }
    observe() {}
    show(targets) { this.callback(targets.map((target) => ({ target, isIntersecting: true }))); }
  }
  class MutationObserver {
    constructor() {}
    observe() {}
  }
  const window = {
    innerWidth: 1440,
    innerHeight: 900,
    addEventListener() {}
  };
  vm.runInNewContext(loader, {
    window,
    document,
    IntersectionObserver,
    MutationObserver,
    Date: { now: () => now },
    setTimeout(fn, delay) {
      const id = ++timerId;
      timers.set(id, { fn, at: now + delay });
      return id;
    },
    clearTimeout(id) { timers.delete(id); }
  });

  assert.equal(starts.length, 0, "data-hw-src must not request before intersection");
  io.show(images.slice(0, 3));
  assert.equal(starts.length, 1);
  advance(599);
  assert.equal(starts.length, 1, "starts are spaced by 600ms");
  advance(1);
  assert.equal(starts.length, 2, "queue allows two active requests");
  images[0].emit("load");
  images[1].emit("error");
  const failedAt = now;
  advance(9999);
  assert.equal(starts.length, 2, "failure pauses new starts for ten seconds");
  advance(1);
  assert.equal(starts.length, 3);
  assert.equal(starts[2].at, failedAt + 10000);
  images[2].emit("error");
  assert.equal(window.HandrawImageLoader.retry(images[2]), true);
  advance(9999);
  assert.equal(starts.length, 3, "explicit retry still respects cooldown");
  advance(1);
  assert.equal(starts.length, 4);
  images[2].emit("load");
  images[3].visible = true;
  io.show([images[3]]);
  advance(600);
  assert.equal(starts.length, 5, "revealed image resumes the queue");
  assert.ok(notices.length >= 1, "failed images expose an explicit retry notice");
}

// The templates feeding public grids/pickers opt into the queue, while
// explicit lightboxes and private single-result views retain direct src.
for (const source of [shared, studio]) {
  assert.match(source, /data-hw-src=/);
}
assert.match(shared, /<img data-hw-src="\$\{esc\(item\.image\)\}"/);
assert.match(studio, /<img data-hw-src="\$\{esc\(it\.image\)\}"/);
assert.match(studio, /<img src="\$\{esc\(url\)\}"/);

// Execute the actual Studio scope helpers in isolation. This simulates a
// logged-in user's draft, switches to another account, rejects a late token,
// and verifies that the first account's scoped cache is restored without
// leaking into the second account. It also exercises requestId reuse for a
// retry rather than generating a second identifier.
{
  const local = new Map();
  const app = { state: { loggedIn: true, user: { id: 101, username: "alice" } }, listeners: [] };
  const window = {
    __HANDRAW_TESTING__: true,
    location: { search: "" },
    HANDRAW_SHARED: {
      App: app,
      esc(value) { return String(value == null ? "" : value); },
      toast() {},
      initApp() { return Promise.reject(new Error("test boot skipped")); }
    },
    HANDRAW_CANVAS_ENGINE: {}
  };
  const document = {
    getElementById() { return null; },
    addEventListener() {},
    querySelectorAll() { return []; },
    createElement() { return { style: {}, classList: { add() {} }, append() {} }; },
    body: { append() {} }
  };
  const context = {
    window,
    document,
    localStorage: {
      getItem(key) { return local.has(key) ? local.get(key) : null; },
      setItem(key, value) { local.set(key, String(value)); },
      removeItem(key) { local.delete(key); }
    },
    console: { error() {}, log() {} },
    fetch() { return Promise.reject(new Error("test boot skipped")); },
    requestAnimationFrame() {},
    setTimeout() { return 1; },
    clearTimeout() {},
    URLSearchParams,
    AbortController,
    crypto: { randomUUID: () => "fixed-test-uuid" }
  };
  vm.runInNewContext(studio, context);
  const hooks = window.HANDRAW_STUDIO_TESTING;
  assert.ok(hooks, "studio test hooks should be available only in the test flag");

  hooks.switchScope("user_101");
  hooks.writeScopedCache("handraw_my_articles_v1", [{ id: "alice-draft" }]);
  hooks.writeScopedCache("handraw_gen_history_v4", [{ id: "alice-history" }]);
  hooks.setPrivateState({
    tabs: [{ id: "alice-tab" }],
    graph: { nodes: [{ id: "alice-node" }], edges: [], selectedIds: [] },
    myArticles: [{ id: "alice-draft" }],
    generationHistory: [{ id: "alice-history" }],
    customUploads: [{ id: "alice-upload" }]
  });
  const aliceToken = hooks.getSnapshot();
  hooks.switchScope("user_202");
  const bob = hooks.getSnapshot();
  assert.equal(bob.scope, "user_202");
  assert.equal(bob.tabs, 0);
  assert.equal(bob.graphNodes, 0);
  assert.equal(bob.articles, null);
  assert.equal(bob.history, null);
  assert.equal(bob.uploads, 0);
  assert.equal(hooks.isStaleScope(aliceToken.epoch, aliceToken.scope), true, "late Alice responses are rejected");
  hooks.writeScopedCache("handraw_my_articles_v1", [{ id: "bob-draft" }]);
  hooks.switchScope("user_101");
  assert.equal(JSON.stringify(hooks.readScopedCache("handraw_my_articles_v1", [])), JSON.stringify([{ id: "alice-draft" }]));
  const requestId = hooks.ensureStableRequestId("", "test");
  assert.equal(hooks.ensureStableRequestId(requestId, "test"), requestId, "retry keeps the same requestId");
  hooks.setPrivateState({ generationHistory: [] });
  hooks.applyDurableTaskResult(
    { genId: "gen-pending", requestId: "pending-rid", mode: "poster", prompt: "pending prompt" },
    ["/private/generated.webp"]
  );
  const resumed = hooks.getHistory();
  assert.equal(resumed[0].id, "gen-pending");
  assert.equal(resumed[0].status, "success");
  assert.equal(resumed[0].requestId, "pending-rid");
  assert.equal(resumed[0].items[0].imageUrl, "/private/generated.webp");
}

console.log("Studio v2 state: scoped caches, explicit engine, task identity, cost gate, timestamp freshness and image queue checks passed");
