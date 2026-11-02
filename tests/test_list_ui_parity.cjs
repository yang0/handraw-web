"use strict";
/**
 * Test Suite for Issue #49:
 * 1. Three list action bars parity (Works, Styles, Layouts)
 * 2. Works list like button addition & unified order [Like, Collect, Comment]
 * 3. Local fine-grained social updates (no refreshFromServer, no notifyAll)
 * 4. Optimistic UI update with in-flight lock and rollback on failure
 * 5. Multi-occurrence DOM synchronization
 * 6. Topbar badge & wallet balance synchronization
 * 7. Collections view card removal on uncollect
 */

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

console.log("Starting test_list_ui_parity.cjs...");

// Create a DOM & browser simulation context
function createSimulatedContext(overrides = {}) {
  const elements = new Map();
  const listeners = new Map();
  const toasts = [];
  let refreshFromServerCalls = 0;
  let notifyAllCalls = 0;

  class FakeClassList {
    constructor(node) {
      this.node = node;
      this._classes = new Set();
    }
    add(...cls) {
      cls.forEach((c) => this._classes.add(c));
    }
    remove(...cls) {
      cls.forEach((c) => this._classes.delete(c));
    }
    toggle(c, force) {
      if (force !== undefined) {
        if (force) this._classes.add(c);
        else this._classes.delete(c);
        return force;
      }
      if (this._classes.has(c)) {
        this._classes.delete(c);
        return false;
      }
      this._classes.add(c);
      return true;
    }
    contains(c) {
      return this._classes.has(c);
    }
    toString() {
      return Array.from(this._classes).join(" ");
    }
  }

  class FakeNode {
    constructor(tagName = "div") {
      this.tagName = tagName.toUpperCase();
      this.id = "";
      this.classList = new FakeClassList(this);
      this.attributes = new Map();
      this.childNodes = [];
      this.parentElement = null;
      this.disabled = false;
      this.textContent_ = "";
      this.innerHTML_ = "";
      this.style = {};
    }
    get innerHTML() {
      return this.innerHTML_ || this.textContent;
    }
    set innerHTML(val) {
      this.innerHTML_ = String(val);
      this.childNodes = [];
      if (val) {
        const dummy = new FakeNode("div");
        dummy.textContent = val.replace(/<[^>]+>/g, "");
        dummy.parentElement = this;
        this.childNodes.push(dummy);
      }
    }
    get className() {
      return this.classList.toString();
    }
    set className(val) {
      this.classList._classes = new Set(String(val || "").split(/\s+/).filter(Boolean));
    }
    get textContent() {
      if (this.childNodes.length > 0) {
        return this.childNodes.map((n) => n.textContent).join("");
      }
      return this.textContent_;
    }
    set textContent(val) {
      this.textContent_ = String(val);
      this.childNodes = [{ nodeType: 3, nodeValue: String(val), textContent: String(val) }];
    }
    setAttribute(k, v) {
      this.attributes.set(k, String(v));
      if (k === "id") this.id = String(v);
      if (k === "class") this.className = String(v);
    }
    getAttribute(k) {
      if (k === "class") return this.className;
      if (k === "id") return this.id;
      return this.attributes.has(k) ? this.attributes.get(k) : null;
    }
    hasAttribute(k) {
      return this.attributes.has(k) || (k === "id" && Boolean(this.id));
    }
    removeAttribute(k) {
      this.attributes.delete(k);
    }
    appendChild(child) {
      child.parentElement = this;
      this.childNodes.push(child);
      return child;
    }
    prepend(...children) {
      for (let i = children.length - 1; i >= 0; i--) {
        const child = children[i];
        if (child) {
          child.parentElement = this;
          this.childNodes.unshift(child);
        }
      }
    }
    insertAdjacentElement(position, element) {
      if (!element) return null;
      if (position === "afterend" && this.parentElement) {
        const idx = this.parentElement.childNodes.indexOf(this);
        element.parentElement = this.parentElement;
        this.parentElement.childNodes.splice(idx + 1, 0, element);
        return element;
      }
      if (position === "beforebegin" && this.parentElement) {
        const idx = this.parentElement.childNodes.indexOf(this);
        element.parentElement = this.parentElement;
        this.parentElement.childNodes.splice(idx, 0, element);
        return element;
      }
      return element;
    }
    remove() {
      if (this.parentElement) {
        const idx = this.parentElement.childNodes.indexOf(this);
        if (idx >= 0) this.parentElement.childNodes.splice(idx, 1);
        this.parentElement = null;
      }
    }
    querySelector(sel) {
      const all = this.querySelectorAll(sel);
      return all.length ? all[0] : null;
    }
    querySelectorAll(sel) {
      return querySelectorAllSim(this, sel);
    }
    closest(sel) {
      let cur = this;
      while (cur) {
        if (matchesSim(cur, sel)) return cur;
        cur = cur.parentElement;
      }
      return null;
    }
  }

  function matchesSim(node, sel) {
    if (!node || !sel) return false;
    const parts = sel.split(",").map((s) => s.trim());
    return parts.some((rawP) => {
      let p = rawP;
      let checkLastChild = false;
      if (p.endsWith(":last-child")) {
        checkLastChild = true;
        p = p.slice(0, -":last-child".length);
      }
      if (checkLastChild && node.parentElement) {
        const siblings = node.parentElement.childNodes.filter((n) => n.nodeType !== 3);
        if (siblings.length && siblings[siblings.length - 1] !== node) return false;
      }
      if (p.startsWith("#")) return node.id === p.slice(1);
      if (p.startsWith(".")) return node.classList.contains(p.slice(1));
      if (p.includes("[") && p.includes("]")) {
        const tag = p.slice(0, p.indexOf("[")).trim().toUpperCase();
        if (tag && node.tagName !== tag) return false;
        const attrMatch = p.match(/\[([a-zA-Z0-9\-_]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\]/);
        if (attrMatch) {
          const attr = attrMatch[1];
          const val = attrMatch[2] ?? attrMatch[3] ?? attrMatch[4];
          if (!node.hasAttribute(attr)) return false;
          if (val !== undefined && node.getAttribute(attr) !== val) return false;
          return true;
        }
      }
      return !p || node.tagName === p.toUpperCase();
    });
  }

  function querySelectorAllSim(root, sel) {
    const res = [];
    const parts = sel.split(",").map((s) => s.trim());
    function traverse(cur) {
      if (!cur || !cur.childNodes) return;
      for (const child of cur.childNodes) {
        if (child.nodeType !== 3) {
          for (const p of parts) {
            if (matchesSim(child, p)) {
              if (!res.includes(child)) res.push(child);
              break;
            }
          }
          traverse(child);
        }
      }
    }
    traverse(root);
    return res;
  }

  const fakeBody = new FakeNode("body");
  elements.set("body", fakeBody);

  const fakeDocument = {
    body: fakeBody,
    createElement(tag) {
      return new FakeNode(tag);
    },
    getElementById(id) {
      for (const el of elements.values()) {
        if (el.id === id) return el;
        const found = el.querySelector("#" + id);
        if (found) return found;
      }
      return null;
    },
    querySelector(sel) {
      const all = this.querySelectorAll(sel);
      return all.length ? all[0] : null;
    },
    querySelectorAll(sel) {
      const res = [];
      for (const root of elements.values()) {
        if (matchesSim(root, sel) && !res.includes(root)) res.push(root);
        for (const found of querySelectorAllSim(root, sel)) {
          if (!res.includes(found)) res.push(found);
        }
      }
      return res;
    },
    registerElement(id, el) {
      el.id = id;
      elements.set(id, el);
    }
  };

  const fakeWindow = {
    location: {
      hostname: "localhost",
      port: "3000",
      protocol: "http:",
      href: "http://localhost:3000/",
      search: "",
      pathname: "/"
    },
    addEventListener(event, fn) {
      if (!listeners.has(event)) listeners.set(event, []);
      listeners.get(event).push(fn);
    },
    removeEventListener(event, fn) {
      if (listeners.has(event)) {
        listeners.set(event, listeners.get(event).filter((f) => f !== fn));
      }
    },
    dispatchEvent(ev) {
      const list = listeners.get(ev.type) || [];
      list.forEach((fn) => fn(ev));
      return true;
    }
  };

  if (overrides.fetch) {
    fakeWindow.fetch = overrides.fetch;
  }

  class FakeCustomEvent {
    constructor(type, init = {}) {
      this.type = type;
      this.detail = init.detail || {};
    }
  }

  class FakeFormData {}

  const ctx = {
    window: fakeWindow,
    document: fakeDocument,
    CustomEvent: FakeCustomEvent,
    FormData: typeof FormData !== "undefined" ? FormData : FakeFormData,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    console,
    toast(msg) { toasts.push(msg); },
    toasts,
    getRefreshFromServerCount: () => refreshFromServerCalls,
    getNotifyAllCalls: () => notifyAllCalls,
    ...overrides
  };

  return ctx;
}

// ---------------------------------------------------------------------------
// Test 1: Works list action bar renders [Like, Collect, Comment] with unified classes
// ---------------------------------------------------------------------------
console.log("Checking Test 1: Works list action bar structure, order & classes...");
{
  const source = fs.readFileSync("demo/assets/main-app.js", "utf8");
  const fnMatch = source.match(/function renderWorksSquare\(root\)[\s\S]*?(?=\n  function )/);
  assert.ok(fnMatch, "renderWorksSquare must be defined in main-app.js");
  const fnBody = fnMatch[0];

  // Verify like button exists in works card template
  assert.match(fnBody, /data-wb-like=/, "Works card must have data-wb-like button");
  assert.match(fnBody, /data-wb-fav=/, "Works card must have data-wb-fav button");
  assert.match(fnBody, /data-wb-comment=/, "Works card must have data-wb-comment button");

  // Verify order in HTML: data-wb-like comes BEFORE data-wb-fav, which comes BEFORE data-wb-comment
  const likeIdx = fnBody.indexOf("data-wb-like=");
  const favIdx = fnBody.indexOf("data-wb-fav=");
  const commentIdx = fnBody.indexOf("data-wb-comment=");
  assert.ok(likeIdx > 0 && favIdx > likeIdx && commentIdx > favIdx, "Works card order must be Like, Collect, Comment");

  // Verify button classes: btn btn-sm hw-action-btn
  assert.match(fnBody, /btn btn-sm hw-action-btn \$\{liked \? "btn-primary is-active" : ""\}/, "Like button must use unified btn btn-sm hw-action-btn and active state");
  assert.match(fnBody, /btn btn-sm hw-action-btn \$\{collected \? "btn-primary is-active" : ""\}/, "Collect button must use unified btn btn-sm hw-action-btn and active state");

  // Verify event listener binding for data-wb-like
  assert.match(fnBody, /root\.querySelectorAll\("\[data-wb-like\]"\)/, "renderWorksSquare must bind click listener to [data-wb-like]");

  console.log("✓ Test 1 Passed: Works list action bar has Like button, unified order [Like, Collect, Comment], and consistent classes.");
}

// ---------------------------------------------------------------------------
// Test 2: Styles & Layouts list action bar parity
// ---------------------------------------------------------------------------
console.log("Checking Test 2: Styles & Layouts list action bar parity...");
{
  const source = fs.readFileSync("demo/assets/main-app.js", "utf8");
  const catalogMatch = source.match(/function renderAssetCatalog\(root, kind\)[\s\S]*?(?=\n  function )/);
  assert.ok(catalogMatch, "renderAssetCatalog must be defined in main-app.js");
  const catBody = catalogMatch[0];

  // Verify unified button classes
  assert.match(catBody, /btn btn-sm hw-action-btn \$\{liked \? "btn-primary is-active" : ""\}/, "Asset Like button must use unified btn btn-sm hw-action-btn and active state");
  assert.match(catBody, /btn btn-sm hw-action-btn \$\{collected \? "btn-primary is-active" : ""\}/, "Asset Collect button must use unified btn btn-sm hw-action-btn and active state");

  // Verify order in action bar HTML: like comes before fav, before comment
  const actionRowStart = catBody.indexOf("hw-card-actions");
  const actionRow = actionRowStart >= 0 ? catBody.slice(actionRowStart) : catBody;
  const aLikeIdx = actionRow.indexOf("data-like-asset=");
  const aFavIdx = actionRow.indexOf("data-fav-asset=");
  const aCommentIdx = actionRow.indexOf("data-comment-asset=");
  assert.ok(aLikeIdx > 0 && aFavIdx > aLikeIdx && aCommentIdx > aFavIdx, "Asset card order in action bar must be Like, Collect, Comment");

  console.log("✓ Test 2 Passed: Styles & Layouts list action bar order and classes match Works list.");
}

// ---------------------------------------------------------------------------
// Test 3: Theme CSS unified action button rules (.hw-action-btn)
// ---------------------------------------------------------------------------
console.log("Checking Test 3: Unified action button CSS styling in theme.css...");
{
  const css = fs.readFileSync("demo/assets/theme.css", "utf8");
  assert.match(css, /\.hw-action-btn/, "theme.css must declare .hw-action-btn");
  assert.match(css, /\.hw-action-btn\.is-active/);
  assert.match(css, /\.hw-action-btn\.is-pending|\.hw-action-btn:disabled/);

  console.log("✓ Test 3 Passed: theme.css contains unified styles for .hw-action-btn, active state, and pending state.");
}

// Run all tests in async flow
(async () => {
  // ---------------------------------------------------------------------------
  // Test 4: toggleLike and toggleCollect in shared.js
  //         - No notifyAll()
  //         - No refreshFromServer()
  //         - In-flight lock & debouncing
  //         - Optimistic counting + server calibration
  //         - Rollback on failure
  // ---------------------------------------------------------------------------
  console.log("Checking Test 4: shared.js optimistic social updates, in-flight lock & zero page reloads...");
  {
    const sharedSrc = fs.readFileSync("demo/assets/shared.js", "utf8");
    const collectFnMatch = sharedSrc.match(/function toggleCollect\([\s\S]*?\n  \}/);
    assert.ok(collectFnMatch, "toggleCollect must be defined");
    assert.doesNotMatch(collectFnMatch[0], /refreshFromServer\(\)/, "toggleCollect must NOT call refreshFromServer()");
    assert.doesNotMatch(collectFnMatch[0], /notifyAll\(\)/, "toggleCollect must NOT call notifyAll()");

    const likeFnMatch = sharedSrc.match(/function toggleLike\([\s\S]*?\n  \}/);
    assert.ok(likeFnMatch, "toggleLike must be defined");
    assert.doesNotMatch(likeFnMatch[0], /refreshFromServer\(\)/, "toggleLike must NOT call refreshFromServer()");
    assert.doesNotMatch(likeFnMatch[0], /notifyAll\(\)/, "toggleLike must NOT call notifyAll()");

    // Mock fetch implementation
    let apiLikeResolver = null;
    let apiLikeRejecter = null;
    let apiCollectResolver = null;

    const fakeFetch = async (url, opts) => {
      if (url === "/api/interactions/like") {
        return new Promise((resolve, reject) => {
          apiLikeResolver = (payload) => resolve({
            ok: payload.ok !== false,
            status: payload.ok === false ? 500 : 200,
            json: async () => payload
          });
          apiLikeRejecter = (err) => reject(err);
        });
      }
      if (url === "/api/collections/toggle") {
        return new Promise((resolve) => {
          apiCollectResolver = (payload) => resolve({
            ok: true,
            status: 200,
            json: async () => payload
          });
        });
      }
      return { ok: true, json: async () => ({ ok: true }) };
    };

    const ctx = createSimulatedContext({ fetch: fakeFetch });
    vm.createContext(ctx);
    vm.runInContext(sharedSrc, ctx);

    const S = ctx.window.HANDRAW_SHARED;
    assert.ok(S, "HANDRAW_SHARED must be exported on window");
    assert.equal(typeof S.toggleLike, "function");
    assert.equal(typeof S.toggleCollect, "function");
    assert.equal(typeof S.updateSocialDom, "function");
    assert.equal(typeof S.dispatchSocialUpdate, "function");

    // Setup mock user & state
    S.App.state = {
      loggedIn: true,
      serverBacked: true,
      user: { username: "viewer_1", name: "访客一号" },
      credits: 10,
      likedIds: [],
      collections: { works: [], styles: [], layouts: [], topics: [], generations: [] },
      works: [{ id: "w_101", title: "山水画", likes: 5, favorites: 2 }],
      topics: [{ id: "t_201", title: "提示词教程", likes: 8, favorites: 4 }],
      assetLiveLikes: {},
      assetLiveFavorites: {}
    };

    // Mock DOM elements
    const workLikeBtn = ctx.document.createElement("button");
    workLikeBtn.setAttribute("data-wb-like", "w_101");
    workLikeBtn.setAttribute("data-social-action", "like");
    workLikeBtn.setAttribute("data-social-id", "w_101");
    const workLikeCnt = ctx.document.createElement("span");
    workLikeCnt.className = "hw-social-count";
    workLikeCnt.textContent = "5";
    workLikeBtn.appendChild(workLikeCnt);
    ctx.document.registerElement("btn-work-like", workLikeBtn);

    const workFavBtn = ctx.document.createElement("button");
    workFavBtn.setAttribute("data-wb-fav", "w_101");
    workFavBtn.setAttribute("data-social-action", "collect");
    workFavBtn.setAttribute("data-social-id", "w_101");
    const workFavIcon = ctx.document.createElement("span");
    workFavIcon.className = "hw-fav-icon";
    workFavIcon.textContent = "♡";
    const workFavCnt = ctx.document.createElement("span");
    workFavCnt.className = "hw-social-count";
    workFavCnt.textContent = "2";
    workFavBtn.appendChild(workFavIcon);
    workFavBtn.appendChild(workFavCnt);
    ctx.document.registerElement("btn-work-fav", workFavBtn);

    // Topbar dropdown mock
    const topbarCol = ctx.document.createElement("a");
    topbarCol.id = "hw-dropdown-collections";
    const topbarColText = ctx.document.createElement("span");
    topbarColText.textContent = "我的云端收藏 (0)";
    topbarCol.appendChild(topbarColText);
    ctx.document.registerElement("hw-dropdown-collections", topbarCol);

    // Test 4a: Optimistic Like Update
    const likeRet = S.toggleLike("work", "w_101", "山水画");
    assert.equal(likeRet, true);

    // Synchronous optimistic check: in-flight lock applied, count is 6, active class present
    assert.equal(workLikeCnt.textContent, "6", "DOM counter must update to 6 immediately");
    assert.ok(workLikeBtn.classList.contains("is-active"), "Button must have is-active immediately");
    assert.ok(workLikeBtn.classList.contains("btn-primary"), "Button must have btn-primary immediately");
    assert.equal(workLikeBtn.disabled, true, "Button must be disabled in-flight");

    // In-flight locking: second click must be rejected
    const lockedRet = S.toggleLike("work", "w_101", "山水画");
    assert.equal(lockedRet, false, "Concurrent click during in-flight must be ignored");

    // Server fulfills with calibrated likes count 6 and 2 credits bonus
    apiLikeResolver({ ok: true, liked: true, likes: 6, rewarded: 2, credits: 12 });
    await new Promise((r) => setTimeout(r, 20));

    assert.equal(workLikeCnt.textContent, "6", "Calibrated likes count");
    assert.equal(workLikeBtn.disabled, false, "Button must be re-enabled after response");
    assert.equal(S.App.state.credits, 12, "Wallet credits updated");
    let allToasts = ctx.document.querySelectorAll(".hw-toast").map((el) => el.textContent);
    assert.ok(allToasts.some((t) => t.includes("首次点赞激励 +2")), "Toast must reflect bonus credits");

    // Test 4b: Optimistic Like Rollback on Error
    S.toggleLike("work", "w_101", "山水画"); // Toggle unlike
    assert.equal(workLikeCnt.textContent, "5", "Optimistic toggle unlike to 5");
    assert.equal(workLikeBtn.classList.contains("is-active"), false, "Active class removed optimistically");

    // Server rejects with network error
    apiLikeRejecter(new Error("网络超时"));
    await new Promise((r) => setTimeout(r, 20));

    assert.equal(workLikeCnt.textContent, "6", "Count must rollback to 6 on error");
    assert.equal(workLikeBtn.classList.contains("is-active"), true, "Active class must rollback on error");
    assert.equal(workLikeBtn.disabled, false, "Button re-enabled after error");
    allToasts = ctx.document.querySelectorAll(".hw-toast").map((el) => el.textContent);
    assert.ok(allToasts.some((t) => t.includes("点赞失败：网络超时")), "Error toast displayed");

    // Test 4c: Optimistic Collect Update & Topbar Sync
    S.toggleCollect("works", "w_101", "山水画");
    assert.equal(workFavCnt.textContent, "3", "Optimistic favorite count incremented to 3");
    assert.equal(workFavIcon.textContent, "♥", "Heart icon changed to solid ♥");
    assert.ok(topbarCol.textContent.includes("(1)"), "Topbar collections badge incremented to 1");

    apiCollectResolver({ ok: true, targetType: "work", targetId: "w_101", collected: true, favorites: 3, rewarded: 0, credits: 12 });
    await new Promise((r) => setTimeout(r, 20));

    assert.equal(workFavBtn.disabled, false);
    assert.equal(workFavCnt.textContent, "3");

    console.log("✓ Test 4 Passed: Optimistic updates, in-flight locks, server calibration, topbar badge sync & rollback verified without page reloads.");
  }

  // ---------------------------------------------------------------------------
  // Test 5: Collections View - Uncollect removes card locally and checks empty state
  // ---------------------------------------------------------------------------
  console.log("Checking Test 5: Collections view card removal on uncollect...");
  {
    const ctx = createSimulatedContext({
      fetch: async () => ({ ok: true, json: async () => ({ ok: true }) })
    });
    const sharedSrc = fs.readFileSync("demo/assets/shared.js", "utf8");
    vm.createContext(ctx);
    vm.runInContext(sharedSrc, ctx);
    const S = ctx.window.HANDRAW_SHARED;

    S.App.channel = "main";
    S.App.view = "collections";
    S.App.state = {
      loggedIn: true,
      serverBacked: true,
      collections: { works: ["w_1", "w_2"], styles: [], layouts: [], topics: [], generations: [] }
    };

    const gridContainer = ctx.document.createElement("div");
    gridContainer.className = "hw-card-grid";

    const card1 = ctx.document.createElement("article");
    card1.className = "hw-card";
    card1.setAttribute("data-fav-item", "w_1");
    const card2 = ctx.document.createElement("article");
    card2.className = "hw-card";
    card2.setAttribute("data-fav-item", "w_2");

    gridContainer.appendChild(card1);
    gridContainer.appendChild(card2);
    ctx.document.registerElement("collections-grid", gridContainer);

    assert.equal(gridContainer.childNodes.length, 2);

    // Uncollect w_1
    S.toggleCollect("works", "w_1", "作品一");
    assert.equal(gridContainer.childNodes.length, 1, "card1 must be removed from DOM");
    assert.equal(gridContainer.childNodes[0].getAttribute("data-fav-item"), "w_2");

    // Uncollect w_2 -> container becomes empty, shows empty state
    S.toggleCollect("works", "w_2", "作品二");
    assert.equal(gridContainer.childNodes.length, 1, "Grid should now contain empty placeholder");
    assert.ok(gridContainer.innerHTML.includes("暂未收藏") || gridContainer.textContent.includes("暂未收藏"), "Empty placeholder rendered");

    console.log("✓ Test 5 Passed: Uncollect removes only target card from DOM, empty state triggered when 0 remain.");
  }

  console.log("\n========================================================");
  console.log("ALL 5 LIST UI PARITY & LOCAL UPDATE TESTS PASSED!");
  console.log("========================================================");
})();
