"use strict";
/**
 * Test Suite for Issue #53:
 * 1. Unified action bar across Style, Layout, and Work detail pages
 * 2. Order and styling parity: [Like, Collect, Comment, Tip, Copy Share]
 * 3. Removal of duplicate "点赞" and "收藏" text from #topic-counts (now only in action buttons)
 * 4. "获赞赏 N✦" retained and reads actual bound target (work tips for works, topic tips for resources)
 * 5. "做同款 M" retained for works
 * 6. "去创作" for styles/layouts vs "做同款" for works (semantic distinction preserved)
 * 7. Duplicate tip button removed from resource stamps section
 * 8. Exactly ONE occurrence of "点赞" and "收藏" in page DOM
 * 9. Fine-grained partial update on like/collect without corrupting counts or reloading images
 * 10. Self-tip prevention in top action bar
 */

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

console.log("Starting test_unified_detail_actions.cjs (Issue #53)...");

class MockElement {
  constructor(tagName, attrs = {}) {
    this.tagName = tagName.toUpperCase();
    this.attrs = { ...attrs };
    this.children = [];
    this.parent = null;
    const self = this;
    this._classes = new Set(
      attrs.class ? attrs.class.trim().split(/\s+/).filter(Boolean) : []
    );
    this.classList = {
      contains: (c) => self._classes.has(c),
      add: (...cls) => {
        cls.forEach((c) => self._classes.add(c));
        self.attrs.class = Array.from(self._classes).join(" ");
      },
      remove: (...cls) => {
        cls.forEach((c) => self._classes.delete(c));
        self.attrs.class = Array.from(self._classes).join(" ");
      },
      toggle: (c, force) => {
        if (force === undefined) {
          if (self._classes.has(c)) { self._classes.delete(c); return false; }
          self._classes.add(c); return true;
        }
        if (force) { self._classes.add(c); return true; }
        self._classes.delete(c); return false;
      }
    };
    this.style = {};
    if (attrs.style) {
      attrs.style.split(";").forEach((pair) => {
        const idx = pair.indexOf(":");
        if (idx !== -1) {
          const prop = pair.slice(0, idx).trim();
          const val = pair.slice(idx + 1).trim();
          if (prop) {
            const camel = prop.replace(/-([a-z])/g, (_, g) => g.toUpperCase());
            this.style[camel] = val;
            this.style[prop] = val;
          }
        }
      });
    }
    this._value = attrs.value !== undefined ? String(attrs.value) : undefined;
    this.disabled = attrs.disabled !== undefined;
    this.id = attrs.id || "";
    this._textContent = null;
  }

  get value() {
    if (this._value !== undefined) return this._value;
    return this.attrs.value || "";
  }
  set value(v) { this._value = String(v); }

  get textContent() {
    if (this._textContent !== null) return this._textContent;
    return this.children.map((c) => (typeof c === "string" ? c : c.textContent)).join("");
  }
  set textContent(v) {
    this._textContent = String(v);
    this.children = [String(v)];
  }

  get innerHTML() {
    return this.children.map((c) => (typeof c === "string" ? c : c.outerHTML)).join("");
  }
  set innerHTML(html) {
    this.children = [];
    this._textContent = null;
    parseHtmlToChildren(html, this);
  }

  get outerHTML() {
    const attrStr = Object.entries(this.attrs).map(([k, v]) => ` ${k}="${v}"`).join("");
    return `<${this.tagName.toLowerCase()}${attrStr}>${this.innerHTML}</${this.tagName.toLowerCase()}>`;
  }

  getAttribute(k) {
    if (k === "class") return Array.from(this._classes).join(" ");
    return this.attrs[k] !== undefined ? this.attrs[k] : null;
  }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === "class") {
      this._classes = new Set(String(v).trim().split(/\s+/).filter(Boolean));
    }
  }
  removeAttribute(k) {
    delete this.attrs[k];
    if (k === "class") this._classes.clear();
  }
  hasAttribute(k) { return this.attrs[k] !== undefined; }

  appendChild(child) {
    if (typeof child === "string") {
      this.children.push(child);
    } else if (child) {
      child.parent = this;
      this.children.push(child);
    }
    return child;
  }

  removeChild(child) {
    const idx = this.children.indexOf(child);
    if (idx !== -1) {
      this.children.splice(idx, 1);
      if (typeof child !== "string") child.parent = null;
    }
    return child;
  }

  remove() {
    if (this.parent) this.parent.removeChild(this);
  }

  addEventListener() {}
  removeEventListener() {}
  querySelector(sel) { return querySelector(this, sel); }
  querySelectorAll(sel) { return querySelectorAll(this, sel); }
}

function parseAttributes(attrStr) {
  const attrs = {};
  const re = /([a-zA-Z0-9_-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
  let m;
  while ((m = re.exec(attrStr)) !== null) {
    const key = m[1].toLowerCase();
    const val = m[2] !== undefined ? m[2] : (m[3] !== undefined ? m[3] : (m[4] !== undefined ? m[4] : ""));
    attrs[key] = val;
  }
  return attrs;
}

const VOID_TAGS = new Set(["AREA", "BASE", "BR", "COL", "EMBED", "HR", "IMG", "INPUT", "LINK", "META", "PARAM", "SOURCE", "TRACK", "WBR"]);

function parseHtmlToChildren(html, parentElement) {
  const tagRe = /<!--[\s\S]*?-->|<(\/)?([a-zA-Z0-9-]+)([^>]*)>|([^<]+)/g;
  let match;
  let current = parentElement;

  while ((match = tagRe.exec(html)) !== null) {
    const [full, isClosing, tagName, attrStr, text] = match;
    if (full.startsWith("<!--")) continue;
    if (text) {
      current.appendChild(text);
      continue;
    }
    const tag = tagName.toUpperCase();
    if (isClosing) {
      if (current.parent && current.tagName === tag) {
        current = current.parent;
      }
    } else {
      const attrs = parseAttributes(attrStr);
      const isSelfClosing = attrStr.trim().endsWith("/") || VOID_TAGS.has(tag);
      const el = new MockElement(tag, attrs);
      current.appendChild(el);
      if (!isSelfClosing) {
        current = el;
      }
    }
  }
}

function matchesSelector(el, sel) {
  if (typeof el === "string") return false;
  sel = sel.trim();
  if (sel.startsWith("#")) return el.id === sel.slice(1);
  if (sel.startsWith(".")) return el.classList.contains(sel.slice(1));
  if (sel.startsWith("[")) {
    const inner = sel.slice(1, -1);
    if (inner.includes("=")) {
      const [k, v] = inner.split("=");
      const cleanV = v.replace(/^["']|["']$/g, "");
      return el.getAttribute(k) === cleanV;
    }
    return el.hasAttribute(inner);
  }
  return el.tagName === sel.toUpperCase();
}

function querySelector(root, sel) {
  for (const child of root.children) {
    if (typeof child === "string") continue;
    if (matchesSelector(child, sel)) return child;
    const found = querySelector(child, sel);
    if (found) return found;
  }
  return null;
}

function querySelectorAll(root, sel) {
  const results = [];
  function search(node) {
    for (const child of node.children) {
      if (typeof child === "string") continue;
      if (matchesSelector(child, sel)) results.push(child);
      search(child);
    }
  }
  search(root);
  return results;
}

function countTextOccurrences(node, textToFind) {
  let count = 0;
  function walk(n) {
    for (const child of n.children) {
      if (typeof child === "string") {
        let idx = 0;
        while ((idx = child.indexOf(textToFind, idx)) !== -1) {
          count++;
          idx += textToFind.length;
        }
      } else {
        walk(child);
      }
    }
  }
  walk(node);
  return count;
}

function createHarness({ locationSearch = "?view=topic&id=t1", apiHandlers = new Map(), currentUser = null }) {
  const toasts = [];
  let forumRoot = null;
  const docElements = {};

  const defaultFetch = async (url, opts = {}) => {
    const u = String(url);
    const pathOnly = u.split("?")[0];
    if (apiHandlers.has(pathOnly)) {
      return apiHandlers.get(pathOnly)(url, opts);
    }
    for (const [pattern, handler] of apiHandlers.entries()) {
      if (pattern instanceof RegExp ? pattern.test(u) : u.includes(pattern)) {
        return handler(url, opts);
      }
    }
    if (u.includes("/data/catalog.json")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          resources: [
            { id: "FA-001", kind: "style", name: "松散黑线", image: "/fa.webp", definition: "line art" },
            { id: "SC-001", kind: "layout", name: "留白卡片", image: "/sc.webp", definition: "card layout" }
          ]
        })
      };
    }
    if (u.includes("/data/options.json")) {
      return { ok: true, status: 200, json: async () => ({}) };
    }
    if (u.includes("/api/boot")) {
      const uObj = currentUser ? { loggedIn: true, ...currentUser } : null;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          serverBacked: true,
          topics: [],
          works: [],
          loggedIn: Boolean(uObj),
          user: uObj
        })
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  const windowObj = {
    localStorage: {
      _map: new Map(),
      getItem(k) { return this._map.has(k) ? this._map.get(k) : null; },
      setItem(k, v) { this._map.set(k, String(v)); },
      removeItem(k) { this._map.delete(k); },
      clear() { this._map.clear(); }
    },
    location: {
      protocol: "http:",
      hostname: "127.0.0.1",
      port: "3080",
      search: locationSearch,
      pathname: "/forum/",
      get href() { return `http://127.0.0.1:3080/forum/${this.search}`; },
      set href(val) {
        try {
          const u = new URL(val, "http://127.0.0.1:3080/forum/");
          this.search = u.search;
          this.pathname = u.pathname;
        } catch (_) {}
      }
    },
    addEventListener() {},
    history: { replaceState() {}, pushState() {} },
    navigator: {
      clipboard: {
        writeText: async (t) => { windowObj._lastCopied = t; }
      }
    },
    scrollTo() {},
    getSelection: () => null,
    _lastCopied: null,
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
  };

  const documentObj = {
    getElementById(id) {
      if (documentObj.body && documentObj.body.id === id) return documentObj.body;
      const inBody = documentObj.body ? documentObj.body.querySelector("#" + id) : null;
      if (inBody) return inBody;
      const inForum = forumRoot ? forumRoot.querySelector("#" + id) : null;
      if (inForum) return inForum;
      if (!docElements[id]) docElements[id] = new MockElement("DIV", { id });
      return docElements[id];
    },
    querySelector(sel) {
      if (sel === "#forum-app-root") return forumRoot;
      if (forumRoot) {
        const found = forumRoot.querySelector(sel);
        if (found) return found;
      }
      return documentObj.body ? documentObj.body.querySelector(sel) : null;
    },
    querySelectorAll(sel) {
      return forumRoot ? forumRoot.querySelectorAll(sel) : [];
    },
    createElement(tag) { return new MockElement(tag); },
    addEventListener() {},
    removeEventListener() {},
    body: new MockElement("BODY"),
    head: new MockElement("HEAD"),
    title: ""
  };

  forumRoot = new MockElement("DIV", { id: "forum-app-root" });
  documentObj.body.appendChild(forumRoot);

  const context = vm.createContext({
    window: windowObj,
    document: documentObj,
    navigator: windowObj.navigator,
    localStorage: windowObj.localStorage,
    location: windowObj.location,
    fetch: defaultFetch,
    console: { log() {}, warn() {}, error() {} },
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    URL,
    URLSearchParams,
    FormData: globalThis.FormData || class FormData {},
    App: {
      state: currentUser ? { loggedIn: true, user: currentUser } : { loggedIn: false },
      resourceMap: new Map([
        ["FA-001", { id: "FA-001", kind: "style", name: "松散黑线", image: "/fa.webp" }],
        ["SC-001", { id: "SC-001", kind: "layout", name: "留白卡片", image: "/sc.webp" }]
      ])
    }
  });

  // Load shared.js, forum-work-post.js, and forum-app.js
  const sharedJs = fs.readFileSync(path.join(__dirname, "../demo/assets/shared.js"), "utf8");
  vm.runInContext(sharedJs, context);

  const userObj = currentUser ? { loggedIn: true, ...currentUser } : null;
  const App = context.window.HandrawApp || {};
  App.state = {
    serverBacked: true,
    loggedIn: Boolean(userObj),
    user: userObj,
    topics: [],
    works: [],
    unlockedIds: []
  };
  App.resourceMap = new Map([
    ["FA-001", { id: "FA-001", kind: "style", name: "松散黑线", image: "/fa.webp" }],
    ["SC-001", { id: "SC-001", kind: "layout", name: "留白卡片", image: "/sc.webp" }]
  ]);
  context.window.HandrawApp = App;
  context.App = App;
  if (context.window.HANDRAW_SHARED) {
    context.window.HANDRAW_SHARED.App = App;
    context.window.HANDRAW_SHARED.toast = (msg) => { toasts.push(msg); };
  }

  const workPostJs = fs.readFileSync(path.join(__dirname, "../demo/assets/forum-work-post.js"), "utf8");
  vm.runInContext(workPostJs, context);

  function loadForumApp() {
    const forumJs = fs.readFileSync(path.join(__dirname, "../demo/assets/forum-app.js"), "utf8");
    vm.runInContext(forumJs, context);
  }

  return {
    context,
    window: windowObj,
    document: documentObj,
    forumRoot,
    toasts,
    loadForumApp
  };
}

async function runTests() {
  // =========================================================================
  // Test 1: Style Detail Action Bar Parity, Duplicate Removal, DOM Occurrences
  // =========================================================================
  {
    console.log("\n--- Test 1: Style Detail Action Bar Parity ---");
    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/t_style/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, replies: [], total: 0, hasMore: false, nextCursor: null })
    }));
    apiHandlers.set("/api/posts/t_style", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: {
          id: "t_style",
          title: "松散黑线手绘实战心得",
          author: "lin_style_creator",
          authorName: "黑线大师",
          createdAt: "2026-10-20",
          category: "assets",
          tips: 0,
          likes: 42,
          favorites: 18,
          price: 0
        },
        mount: {
          kind: "style",
          resource: {
            code: "FA-001",
            name: "松散黑线",
            image: "/fa.webp",
            definition: "ink pen hand drawn",
            unlocked: true,
            unlockCost: 0,
            sourceType: "community",
            author: "lin_style_creator",
            authorName: "黑线大师",
            useUrl: "/studio/?style=FA-001",
            likes: 42,
            favorites: 18,
            tips: 0,
            stampCounts: { 超实用配方: 15, 审美在线: 8 }
          }
        },
        replies: [],
        pendingReplies: [],
        viewer: { liked: false, favorited: false, stamps: [] }
      })
    }));

    const h = createHarness({
      locationSearch: "?view=topic&id=t_style",
      apiHandlers,
      currentUser: { id: 99, username: "visitor_bob", name: "访客鲍勃" }
    });
    h.loadForumApp();
    await new Promise((r) => setTimeout(r, 80));

    const root = h.forumRoot;
    assert.ok(root.querySelector("#standalone-topic-detail-page"), "Topic detail page must render");

    // 1. Action bar buttons exist and match unified order
    const actionBar = root.querySelector(".topic-action-bar");
    assert.ok(actionBar, "Action bar must exist");
    const buttons = actionBar.querySelectorAll("button");
    const btnIds = buttons.map((b) => b.id);
    assert.deepEqual(btnIds.slice(0, 5), [
      "topic-page-like",
      "topic-page-collect",
      "topic-page-scroll-reply",
      "topic-page-tip",
      "topic-page-share"
    ], "Action bar buttons must follow unified order: [like, collect, reply, tip, share]");

    // 2. Button text and classes
    const likeBtn = root.querySelector("#topic-page-like");
    const collectBtn = root.querySelector("#topic-page-collect");
    const replyBtn = root.querySelector("#topic-page-scroll-reply");
    const tipBtn = root.querySelector("#topic-page-tip");
    const shareBtn = root.querySelector("#topic-page-share");

    assert.equal(likeBtn.textContent.trim(), "👍 点赞 (42)");
    assert.equal(collectBtn.textContent.trim(), "♡ 收藏 (18)");
    assert.equal(replyBtn.textContent.trim(), "💬 评论 (0)");
    assert.equal(tipBtn.textContent.trim(), "🎁 赞赏");
    assert.equal(shareBtn.textContent.trim(), "📋 复制分享口令");

    // 3. No duplicate tip button in stamps
    assert.equal(root.querySelectorAll("#topic-stamp-tip-btn").length, 0, "Resource stamps must NOT contain duplicate tip button");
    assert.ok(root.querySelector("#topic-stamp-recipe"), "Stamps section must retain 超实用配方");
    assert.ok(root.querySelector("#topic-stamp-aesthetic"), "Stamps section must retain 审美在线");

    // 4. Style action button is "去创作" / "使用此画风"
    const useBtn = root.querySelector("#topic-resource-use-btn");
    assert.ok(useBtn, "Resource must have use button");
    assert.match(useBtn.textContent, /使用此画风|去创作/);

    // 5. #topic-counts must NOT contain duplicate "点赞" or "收藏"
    const countsEl = root.querySelector("#topic-counts");
    assert.equal(countsEl.textContent, "", "When tips and forks are 0, #topic-counts must be empty string");

    // 6. DOM text occurrence check: "点赞" and "收藏" must appear EXACTLY ONCE
    const likeCount = countTextOccurrences(root, "点赞");
    const favCount = countTextOccurrences(root, "收藏");
    assert.equal(likeCount, 1, `Expected "点赞" to appear exactly 1 time in DOM, found ${likeCount}`);
    assert.equal(favCount, 1, `Expected "收藏" to appear exactly 1 time in DOM, found ${favCount}`);

    console.log("✓ Test 1 Passed: Style detail action bar parity, duplicate counts removal, and DOM singleton verified.");
  }

  // =========================================================================
  // Test 2: Layout Detail with Tips: Bound Target Reads topic.tips
  // =========================================================================
  {
    console.log("\n--- Test 2: Layout Detail with Tips ---");
    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/t_layout/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, replies: [], total: 0, hasMore: false, nextCursor: null })
    }));
    apiHandlers.set("/api/posts/t_layout", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: {
          id: "t_layout",
          title: "留白卡片版式拆解",
          author: "master_layout",
          authorName: "版式大师",
          createdAt: "2026-10-22",
          category: "assets",
          tips: 25, // Topic tips
          likes: 80,
          favorites: 33,
          price: 0
        },
        mount: {
          kind: "layout",
          resource: {
            code: "SC-001",
            name: "留白卡片",
            image: "/sc.webp",
            definition: "minimal card layout",
            unlocked: true,
            unlockCost: 0,
            sourceType: "community",
            author: "master_layout",
            authorName: "版式大师",
            useUrl: "/studio/?layout=SC-001",
            likes: 80,
            favorites: 33,
            tips: 999, // Should NOT be used for the topic tips display
            stampCounts: { 超实用配方: 20, 审美在线: 12 }
          }
        },
        replies: [],
        pendingReplies: [],
        viewer: { liked: true, favorited: false, stamps: [] }
      })
    }));

    const h = createHarness({
      locationSearch: "?view=topic&id=t_layout",
      apiHandlers,
      currentUser: { id: 99, username: "visitor_bob", name: "访客鲍勃" }
    });
    h.loadForumApp();
    await new Promise((r) => setTimeout(r, 80));

    const root = h.forumRoot;

    // Check action bar
    const likeBtn = root.querySelector("#topic-page-like");
    assert.equal(likeBtn.textContent.trim(), "👍 已赞 (80)");
    assert.ok(likeBtn.classList.contains("btn-primary"), "Liked state must have btn-primary");

    const collectBtn = root.querySelector("#topic-page-collect");
    assert.equal(collectBtn.textContent.trim(), "♡ 收藏 (33)");

    // Layout use button
    const useBtn = root.querySelector("#topic-resource-use-btn");
    assert.ok(useBtn);
    assert.match(useBtn.textContent, /使用此图型|去创作/);

    // Tip count must read topic.tips (25), NOT resource.tips (999)
    const countsEl = root.querySelector("#topic-counts");
    assert.equal(countsEl.textContent, " · 获赞赏 25✦", "Layout detail must read topic.tips (25✦) and retain '获赞赏'");

    // Check single occurrence of like and collect button texts
    assert.equal(countTextOccurrences(root, "已赞"), 1);
    assert.equal(countTextOccurrences(root, "点赞"), 0);
    assert.equal(countTextOccurrences(root, "收藏"), 1);
    assert.equal(countsEl.textContent.includes("点赞"), false);
    assert.equal(countsEl.textContent.includes("收藏"), false);

    console.log("✓ Test 2 Passed: Layout detail reads topic.tips, renders '获赞赏 25✦', and preserves singleton counts.");
  }

  // =========================================================================
  // Test 3: Work Detail Action Bar, Reads mount.work.tips & forks
  // =========================================================================
  {
    console.log("\n--- Test 3: Work Detail Action Bar & Metrics ---");
    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/t_work_1/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        items: [{ id: "r1", author: "bob", authorName: "鲍勃", time: "1小时前", text: "好看！", likes: 2 }],
        total: 1,
        hasMore: false,
        nextCursor: null
      })
    }));
    apiHandlers.set("/api/posts/t_work_1", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: {
          id: "t_work_1",
          title: "秋分暖意手绘作品分享",
          author: "artist_amy",
          authorName: "艾米画画",
          createdAt: "2026-10-25",
          category: "showcase",
          tips: 0,
          likes: 120,
          favorites: 45,
          price: 0,
          workId: "work_101"
        },
        mount: {
          kind: "work",
          work: {
            id: "work_101",
            title: "秋分暖意",
            author: "artist_amy",
            authorName: "艾米画画",
            images: ["/autumn.webp"],
            prompt: "autumn foliage, watercolor",
            tips: 30, // Work tips
            forks: 14, // Work forks
            likes: 120,
            favorites: 45
          }
        },
        replies: [
          { id: "r1", author: "bob", authorName: "鲍勃", time: "1小时前", text: "好看！", likes: 2 }
        ],
        pendingReplies: [],
        viewer: { liked: false, favorited: true, stamps: [] }
      })
    }));

    const h = createHarness({
      locationSearch: "?view=topic&id=t_work_1",
      apiHandlers,
      currentUser: { id: 99, username: "visitor_bob", name: "访客鲍勃" }
    });
    h.loadForumApp();
    await new Promise((r) => setTimeout(r, 80));

    const root = h.forumRoot;

    // 1. Action bar buttons
    const likeBtn = root.querySelector("#topic-page-like");
    const collectBtn = root.querySelector("#topic-page-collect");
    const replyBtn = root.querySelector("#topic-page-scroll-reply");
    const tipBtn = root.querySelector("#topic-page-tip");

    assert.equal(likeBtn.textContent.trim(), "👍 点赞 (120)");
    assert.equal(collectBtn.textContent.trim(), "♥ 已收藏 (45)");
    assert.ok(collectBtn.classList.contains("btn-primary"));
    assert.equal(replyBtn.textContent.trim(), "💬 评论 (1)");
    assert.equal(tipBtn.textContent.trim(), "🎁 赞赏");

    // 2. Semantic distinction: work has "做同款"
    const forkBtn = root.querySelector(".fwp-fork");
    assert.ok(forkBtn, "Work must have 做同款 link");
    assert.equal(forkBtn.textContent.trim(), "做同款");

    // 3. Counts reads work tips (30✦) and forks (14)
    const countsEl = root.querySelector("#topic-counts");
    assert.equal(countsEl.textContent, " · 获赞赏 30✦ · 做同款 14");

    // 4. In entire DOM, 点赞 and 收藏 appear exactly ONCE
    assert.equal(countTextOccurrences(root, "点赞"), 1);
    assert.equal(countTextOccurrences(root, "收藏"), 1);

    console.log("✓ Test 3 Passed: Work detail reads work.tips (30✦) and forks (14), renders '做同款', singleton counts verified.");
  }

  // =========================================================================
  // Test 4: Self-Tip Protection (Author Cannot Tip Own Topic/Work)
  // =========================================================================
  {
    console.log("\n--- Test 4: Self-Tip Protection ---");
    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/t_self/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, replies: [], total: 0, hasMore: false, nextCursor: null })
    }));
    apiHandlers.set("/api/posts/t_self", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: {
          id: "t_self",
          title: "我的原创画风",
          author: "artist_amy",
          authorName: "艾米画画",
          createdAt: "2026-10-25",
          category: "assets",
          tips: 10,
          likes: 5,
          favorites: 2,
          price: 0
        },
        mount: {
          kind: "style",
          resource: {
            code: "FA-001",
            name: "我的原创画风",
            image: "/fa.webp",
            author: "artist_amy",
            authorName: "艾米画画",
            likes: 5,
            favorites: 2,
            tips: 10,
            stampCounts: {}
          }
        },
        replies: [],
        pendingReplies: [],
        viewer: { liked: false, favorited: false, stamps: [] }
      })
    }));

    // Author logged in as artist_amy
    const h = createHarness({
      locationSearch: "?view=topic&id=t_self",
      apiHandlers,
      currentUser: { id: 10, username: "artist_amy", name: "艾米画画" }
    });
    h.loadForumApp();
    await new Promise((r) => setTimeout(r, 80));

    const root = h.forumRoot;
    const tipBtn = root.querySelector("#topic-page-tip");
    assert.equal(tipBtn, null, "Author must NOT see tip button on own detail page");

    console.log("✓ Test 4 Passed: Author viewing own content does not render #topic-page-tip.");
  }

  // =========================================================================
  // Test 5: Fine-Grained Partial Updates (No DOM Reset, Counts Intact)
  // =========================================================================
  {
    console.log("\n--- Test 5: Fine-Grained Partial Social Updates ---");
    let likePayload = null;
    let collectPayload = null;

    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/t_social_test/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, replies: [], total: 0, hasMore: false, nextCursor: null })
    }));
    apiHandlers.set("/api/posts/t_social_test", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: {
          id: "t_social_test",
          title: "交互局部更新测试",
          author: "tester",
          authorName: "测试员",
          createdAt: "2026-10-28",
          category: "assets",
          tips: 5,
          likes: 10,
          favorites: 5,
          price: 0
        },
        mount: {
          kind: "style",
          resource: {
            code: "FA-001",
            name: "松散黑线",
            image: "/fa.webp",
            likes: 10,
            favorites: 5,
            tips: 5,
            stampCounts: {}
          }
        },
        replies: [],
        pendingReplies: [],
        viewer: { liked: false, favorited: false, stamps: [] }
      })
    }));
    apiHandlers.set("/api/interactions/like", async (url, opts) => {
      likePayload = JSON.parse(opts.body);
      return { ok: true, status: 200, json: async () => ({ ok: true, liked: true, likes: 11 }) };
    });
    apiHandlers.set("/api/collections/toggle", async (url, opts) => {
      collectPayload = JSON.parse(opts.body);
      return { ok: true, status: 200, json: async () => ({ ok: true, favorited: true, favorites: 6 }) };
    });

    const h = createHarness({
      locationSearch: "?view=topic&id=t_social_test",
      apiHandlers,
      currentUser: { id: 99, username: "visitor_bob", name: "访客鲍勃" }
    });
    h.loadForumApp();
    await new Promise((r) => setTimeout(r, 80));

    const root = h.forumRoot;
    const likeBtn = root.querySelector("#topic-page-like");
    const collectBtn = root.querySelector("#topic-page-collect");
    const countsEl = root.querySelector("#topic-counts");

    assert.equal(countsEl.textContent, " · 获赞赏 5✦");
    assert.equal(likeBtn.textContent.trim(), "👍 点赞 (10)");
    assert.equal(collectBtn.textContent.trim(), "♡ 收藏 (5)");

    // 1. Click like
    likeBtn.onclick();
    await new Promise((r) => setTimeout(r, 40));

    assert.equal(likeBtn.textContent.trim(), "👍 已赞 (11)", "Like button updates to 11");
    assert.ok(likeBtn.classList.contains("btn-primary"), "Like button has btn-primary");
    assert.equal(countsEl.textContent, " · 获赞赏 5✦", "Counts element retains ' · 获赞赏 5✦' without adding 点赞");
    assert.equal(countTextOccurrences(root, "点赞"), 0, "点赞 not present when state is 已赞");
    assert.equal(countTextOccurrences(root, "已赞"), 1, "已赞 appears exactly 1 time");

    // 2. Click collect
    collectBtn.onclick();
    await new Promise((r) => setTimeout(r, 40));

    assert.equal(collectBtn.textContent.trim(), "♥ 已收藏 (6)", "Collect button updates to 6");
    assert.ok(collectBtn.classList.contains("btn-primary"), "Collect button has btn-primary");
    assert.equal(countsEl.textContent, " · 获赞赏 5✦", "Counts element retains ' · 获赞赏 5✦' without adding 收藏");
    assert.equal(countTextOccurrences(root, "收藏"), 1, "收藏 appears exactly 1 time in collect button");
    assert.equal(countsEl.textContent.includes("收藏"), false);

    console.log("✓ Test 5 Passed: Fine-grained partial update toggles state, retains counts, and prevents DOM text pollution.");
  }

  // =========================================================================
  // Test 6: Share Button Toggles Drawer and Copies Share Command
  // =========================================================================
  {
    console.log("\n--- Test 6: Share Button & Clipboard ---");
    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/t_share_test/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, replies: [], total: 0, hasMore: false, nextCursor: null })
    }));
    apiHandlers.set("/api/posts/t_share_test/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, replies: [], total: 0, hasMore: false, nextCursor: null })
    }));
    apiHandlers.set("/api/posts/t_share_test", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: {
          id: "t_share_test",
          title: "分享测试实战帖",
          author: "sharer",
          authorName: "分享者",
          createdAt: "2026-10-30",
          category: "experience",
          tips: 0,
          likes: 2,
          favorites: 1,
          price: 0
        },
        mount: { kind: "discussion" },
        replies: [],
        pendingReplies: [],
        viewer: { liked: false, favorited: false, stamps: [] }
      })
    }));

    const h = createHarness({
      locationSearch: "?view=topic&id=t_share_test",
      apiHandlers,
      currentUser: { id: 99, username: "visitor_bob", name: "访客鲍勃", inviteCode: "inv_123" }
    });
    h.loadForumApp();
    await new Promise((r) => setTimeout(r, 80));

    const root = h.forumRoot;
    const shareBtn = root.querySelector("#topic-page-share");
    assert.ok(shareBtn);
    assert.equal(shareBtn.textContent.trim(), "📋 复制分享口令");

    // Click share button
    shareBtn.onclick();
    await new Promise((r) => setTimeout(r, 50));

    // Verify drawer opened
    assert.ok(root.querySelector("[data-inline-share-panel]"), "Inline share panel must open on share click");

    // Verify copied text contains /t/ permalink
    assert.ok(h.window._lastCopied, "Clipboard writeText must be called");
    assert.match(h.window._lastCopied, /https:\/\/handraw-style\.com\/t\/t_share_test/, "Copied text must include /t/ permalink");

    console.log("✓ Test 6 Passed: Share button copies share command and toggles inline drawer cleanly.");
  }

  console.log("\n=======================================================");
  console.log("ALL ISSUE #53 UNIFIED DETAIL ACTIONS TESTS PASSED! 🎉");
  console.log("=======================================================");
}

runTests().catch((err) => {
  console.error("Test failed with error:", err);
  process.exit(1);
});
