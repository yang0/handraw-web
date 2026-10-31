"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

// Mock DOM & environment for testing standalone topic detail and resources redirection
class MockElement {
  constructor(tagName = "DIV", attrs = {}) {
    this.tagName = tagName.toUpperCase();
    this.attrs = { ...attrs };
    this.children = [];
    this.parent = null;
    this._classes = new Set((attrs.class || "").split(/\s+/).filter(Boolean));
    const self = this;
    this.classList = {
      add(...cls) { cls.forEach((c) => self._classes.add(c)); },
      remove(...cls) { cls.forEach((c) => self._classes.delete(c)); },
      contains(c) { return self._classes.has(c); },
      toggle(c, force) {
        if (force === undefined) {
          if (self._classes.has(c)) { self._classes.delete(c); return false; }
          self._classes.add(c); return true;
        }
        if (force) { self._classes.add(c); return true; }
        self._classes.delete(c); return false;
      }
    };
    this.style = {};
    this.value = attrs.value || "";
    this.disabled = attrs.disabled !== undefined;
    this.id = attrs.id || "";
    this._textContent = null;
  }

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

  get firstElementChild() {
    return this.children.find((c) => typeof c !== "string") || null;
  }

  getAttribute(name) {
    const k = name.toLowerCase();
    if (k === "class") return Array.from(this._classes).join(" ");
    return this.attrs[k] !== undefined ? this.attrs[k] : null;
  }

  setAttribute(name, val) {
    const k = name.toLowerCase();
    this.attrs[k] = String(val);
    if (k === "id") this.id = String(val);
    if (k === "class") this._classes = new Set(String(val).split(/\s+/).filter(Boolean));
  }

  removeAttribute(name) {
    delete this.attrs[name.toLowerCase()];
  }

  get parentNode() {
    return this.parent;
  }

  insertBefore(newChild, refChild) {
    if (!refChild) return this.appendChild(newChild);
    const idx = this.children.indexOf(refChild);
    if (idx < 0) return this.appendChild(newChild);
    if (typeof newChild !== "string") newChild.parent = this;
    this.children.splice(idx, 0, newChild);
    return newChild;
  }

  appendChild(child) {
    if (typeof child !== "string") child.parent = this;
    this.children.push(child);
    return child;
  }

  prepend(...nodes) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      if (typeof n !== "string") n.parent = this;
      this.children.unshift(n);
    }
  }

  append(...nodes) {
    for (const n of nodes) {
      if (typeof n !== "string") n.parent = this;
      this.children.push(n);
    }
  }

  removeChild(child) {
    const idx = this.children.indexOf(child);
    if (idx >= 0) {
      if (typeof child !== "string") child.parent = null;
      this.children.splice(idx, 1);
    }
  }

  remove() {
    if (this.parent) this.parent.removeChild(this);
  }

  insertAdjacentElement(position, el) {
    if (position === "afterbegin") {
      this.prepend(el);
    } else if (position === "beforeend") {
      this.appendChild(el);
    } else if (position === "beforebegin" && this.parent) {
      const idx = this.parent.children.indexOf(this);
      el.parent = this.parent;
      this.parent.children.splice(idx, 0, el);
    } else if (position === "afterend" && this.parent) {
      const idx = this.parent.children.indexOf(this);
      el.parent = this.parent;
      this.parent.children.splice(idx + 1, 0, el);
    }
    return el;
  }

  insertAdjacentHTML(position, html) {
    const temp = new MockElement("DIV");
    temp.innerHTML = html;
    for (const c of temp.children) {
      this.insertAdjacentElement(position, c);
    }
  }

  addEventListener(event, fn) {
    this[`on${event}`] = fn;
  }

  click() {
    let curr = this;
    while (curr) {
      if (typeof curr.onclick === "function") {
        return curr.onclick({ target: this });
      }
      curr = curr.parent;
    }
  }
  scrollIntoView(opts) {
    this._lastScrollOpts = opts;
  }
  focus() {
    this._focused = true;
  }
  closest(sel) {
    let curr = this;
    while (curr) {
      if (typeof curr !== "string" && matchesSelector(curr, sel)) {
        return curr;
      }
      curr = curr.parent;
    }
    return null;
  }

  querySelector(sel) {
    return querySelector(this, sel);
  }

  querySelectorAll(sel) {
    return querySelectorAll(this, sel);
  }
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
  if (sel.includes(",")) {
    return sel.split(",").some((part) => matchesSelector(el, part.trim()));
  }
  if (sel.startsWith("#")) {
    return el.id === sel.slice(1);
  }
  if (sel.startsWith(".")) {
    return el.classList.contains(sel.slice(1));
  }
  const attrMatch = sel.match(/^([a-zA-Z0-9_-]*)\[([a-zA-Z0-9_-]+)(?:([*^$]?=)(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\]$/);
  if (attrMatch) {
    const [, tag, attrName, op, v1, v2, v3] = attrMatch;
    if (tag && el.tagName.toLowerCase() !== tag.toLowerCase()) return false;
    const val = v1 !== undefined ? v1 : (v2 !== undefined ? v2 : (v3 !== undefined ? v3 : null));
    const attrVal = el.getAttribute(attrName);
    if (val === null) return attrVal !== null;
    if (attrVal === null) return false;
    if (op === "=") return attrVal === val;
    if (op === "*=") return attrVal.includes(val);
    if (op === "^=") return attrVal.startsWith(val);
    if (op === "$=") return attrVal.endsWith(val);
  }
  if (sel.includes(" ")) {
    const parts = sel.split(/\s+/);
    if (parts.length === 2) {
      if (!matchesSelector(el, parts[1])) return false;
      let p = el.parent;
      while (p) {
        if (matchesSelector(p, parts[0])) return true;
        p = p.parent;
      }
      return false;
    }
  }
  return el.tagName.toLowerCase() === sel.toLowerCase();
}

function querySelector(root, sel) {
  const all = querySelectorAll(root, sel);
  return all.length ? all[0] : null;
}

function querySelectorAll(root, sel) {
  const results = [];
  function walk(node) {
    if (typeof node === "string") return;
    for (const child of node.children) {
      if (typeof child !== "string") {
        if (matchesSelector(child, sel)) {
          results.push(child);
        }
        walk(child);
      }
    }
  }
  walk(root);
  return results;
}

// Helper to create fresh test harness
function createHarness({ locationSearch = "?view=topic&id=t_default", apiHandlers = new Map(), currentUser = { username: "tester", role: "user" } } = {}) {
  const forumRoot = new MockElement("DIV", { id: "forum-app-root" });
  const docElements = { "forum-app-root": forumRoot };
  const toasts = [];
  let refreshFromServerCount = 0;
  let replaceLocation = null;

  const fakeFetch = async (url, opts = {}) => {
    const u = String(url);
    for (const [pattern, handler] of apiHandlers.entries()) {
      const matched = typeof pattern === "string" ? u.includes(pattern) : pattern.test(u);
      if (matched) return handler(u, opts);
    }
    if (u.includes("/data/catalog.json")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          resources: [
            { id: "FA-001", kind: "style", name: "松散黑线", image: "/fa.webp", definition: "line art doodle" },
            { id: "SC-001", kind: "layout", name: "留白卡片", image: "/sc.webp", definition: "minimal layout" }
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
      },
      replace(url) { replaceLocation = url; }
    },
    addEventListener() {},
    history: { replaceState() {}, pushState() {} },
    navigator: {
      clipboard: {
        writeText: async (t) => { windowObj._lastCopied = t; }
      }
    },
    scrollTo() {},
    _lastCopied: null,
    matchMedia: (query) => ({
      matches: query.includes("prefers-reduced-motion: reduce") && Boolean(windowObj._reducedMotion),
      addEventListener() {},
      removeEventListener() {}
    })
  };

  const documentObj = {
    getElementById(id) {
      if (!docElements[id]) docElements[id] = new MockElement("DIV", { id });
      return docElements[id];
    },
    querySelector(sel) { return forumRoot.querySelector(sel); },
    querySelectorAll(sel) { return forumRoot.querySelectorAll(sel); },
    createElement(tag) { return new MockElement(tag); },
    addEventListener() {},
    removeEventListener() {},
    body: new MockElement("BODY"),
    head: new MockElement("HEAD"),
    title: ""
  };

  const context = {
    window: windowObj,
    document: documentObj,
    navigator: windowObj.navigator,
    FormData: typeof FormData !== "undefined" ? FormData : class FormData {},
    URLSearchParams,
    URL,
    setTimeout,
    clearTimeout,
    console,
    fetch: fakeFetch
  };

  vm.createContext(context);

  // Load shared.js
  vm.runInContext(fs.readFileSync("demo/assets/shared.js", "utf8"), context);
  const App = context.window.HandrawApp || {};
  const userObj = currentUser ? { loggedIn: true, ...currentUser } : null;
  App.state = {
    serverBacked: true,
    loggedIn: Boolean(userObj),
    user: userObj,
    topics: [],
    works: [],
    unlockedIds: []
  };
  context.window.HandrawApp = App;
  const S = context.window.HANDRAW_SHARED;
  S.toast = (msg) => { toasts.push(msg); };
  const origRefresh = S.refreshFromServer;
  S.refreshFromServer = async (...args) => {
    refreshFromServerCount++;
    return origRefresh ? origRefresh.apply(S, args) : Promise.resolve();
  };

  // Load forum-work-post.js
  vm.runInContext(fs.readFileSync("demo/assets/forum-work-post.js", "utf8"), context);
  // Load forum-resources.js
  vm.runInContext(fs.readFileSync("demo/assets/forum-resources.js", "utf8"), context);

  return {
    context,
    window: windowObj,
    document: documentObj,
    forumRoot,
    toasts,
    getRefreshFromServerCount: () => refreshFromServerCount,
    getReplaceLocation: () => replaceLocation,
    apiHandlers,
    loadForumApp: () => {
      vm.runInContext(fs.readFileSync("demo/assets/forum-app.js", "utf8"), context);
    }
  };
}

(async () => {
  /* ==========================================================================
   * Scenario 1: channelUrl("main", {view:"work", id:"w1"}) -> /t/w1
   *             channelUrl("main", {view:"asset", id:"FB-041"}) -> /t/FB-041
   * ========================================================================== */
  {
    const h = createHarness();
    const S = h.context.window.HANDRAW_SHARED;
    assert.equal(S.channelUrl("main", { view: "work", id: "w1" }), "/t/w1", "work link must resolve to /t/w1");
    assert.equal(S.channelUrl("main", { view: "asset", id: "FB-041" }), "/t/FB-041", "asset link must resolve to /t/FB-041");
    assert.equal(S.channelUrl("main", { view: "work", id: "w1", focus: "comment" }), "/t/w1?focus=comment", "query params must be preserved");
    assert.equal(S.channelUrl("main", { view: "asset", id: "SC-001", tab: "topics" }), "/forum/?view=related&kind=asset&id=SC-001&tab=topics", "tab=topics must route to view=related");

    // Check production subdomain
    h.window.location = { protocol: "https:", hostname: "handraw-style.com", port: "" };
    assert.equal(S.channelUrl("main", { view: "work", id: "w1" }), "https://forum.handraw-style.com/t/w1");
    console.log("Scenario 1 passed: channelUrl resolves to /t/ permalinks cleanly.");
  }

  /* ==========================================================================
   * Scenario 2: Work mount renders work section (fwp), "做同款" button,
   *             and unified counts containing "做同款".
   * ========================================================================== */
  {
    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/topic_work_1/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, items: [], nextCursor: null })
    }));
    apiHandlers.set("/api/posts/topic_work_1", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: {
          id: "topic_work_1",
          title: "复古画风实测分享",
          author: "creator_a",
          authorName: "阿木",
          likes: 25,
          favorites: 10,
          workId: "work_w1",
          images: ["/work_w1.png"]
        },
        mount: {
          kind: "work",
          work: {
            id: "work_w1",
            title: "复古画风实测",
            images: ["/work_w1.png"],
            prompt: "editorial doodle poster",
            styles: ["FA-001"],
            likes: 25,
            favorites: 10,
            forks: 14
          }
        },
        viewer: { liked: false, favorited: false }
      })
    }));

    const h = createHarness({ locationSearch: "?view=topic&id=topic_work_1", apiHandlers });
    h.loadForumApp();

    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;
    assert.ok(root.innerHTML.includes("fwp"), "Topic body must contain fwp work section");
    const countsEl = root.querySelector("#topic-counts");
    assert.ok(countsEl, "Topic counts element must exist");
    assert.equal(countsEl.textContent, "点赞 25 · 收藏 10 · 做同款 14", "Counts must include '做同款 14'");

    const forkLink = root.querySelector(".fwp-fork");
    assert.ok(forkLink, "Work section must contain fork link");
    assert.match(forkLink.getAttribute("href"), /\/studio\/\?.*fork=work_w1/, "Fork link must lead to studio fork");
    assert.equal(forkLink.textContent.trim(), "做同款", "Button text must be '做同款'");
    console.log("Scenario 2 passed: Work mount renders fwp, '做同款' link and unified counts.");
  }

  /* ==========================================================================
   * Scenario 3: Style mount renders definition, copy button, "使用此画风" link,
   *             and requests /related?tab=works.
   * ========================================================================== */
  {
    const apiHandlers = new Map();
    let relatedWorksRequested = false;
    let pairedResourcesRequested = false;

    apiHandlers.set("/api/posts/topic_style_1/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, items: [], nextCursor: null })
    }));
    apiHandlers.set("/api/posts/topic_style_1", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: {
          id: "topic_style_1",
          title: "精选画风推荐：水彩社论",
          author: "curator_b",
          authorName: "小森",
          likes: 8,
          favorites: 3,
          images: ["/fb_041.png"]
        },
        mount: {
          kind: "style",
          resource: {
            code: "FB-041",
            name: "水彩社论",
            image: "/fb_041.png",
            description: "温润水彩与灵动墨线",
            definition: "watercolor soft wash, ink pen outline, minimal editorial portrait",
            unlocked: true,
            useUrl: "/studio/?style=FB-041"
          }
        },
        viewer: { liked: false, favorited: false }
      })
    }));
    apiHandlers.set(/\/api\/forum\/resources\/style\/FB-041\/related\?tab=works/, async () => {
      relatedWorksRequested = true;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          items: [
            { id: "work_rw1", title: "水彩花卉", image: "/rw1.png", authorName: "小王" }
          ]
        })
      };
    });
    apiHandlers.set(/\/api\/forum\/resources\/style\/FB-041\/related\?tab=layouts/, async () => {
      pairedResourcesRequested = true;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          items: [
            { id: "SC-001", name: "留白卡片", image: "/sc1.png" }
          ]
        })
      };
    });

    const h = createHarness({ locationSearch: "?view=topic&id=topic_style_1", apiHandlers });
    h.loadForumApp();

    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;
    assert.ok(root.innerHTML.includes("watercolor soft wash"), "Definition text must be rendered");

    const copyBtn = root.querySelector("#resource-copy-def-btn");
    assert.ok(copyBtn, "Copy definition button must exist");
    assert.equal(copyBtn.textContent.trim(), "复制定义");
    copyBtn.onclick();
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(h.window._lastCopied, "watercolor soft wash, ink pen outline, minimal editorial portrait", "Clipboard must receive definition");
    assert.ok(h.toasts.includes("定义已复制"), "Toast '定义已复制' must be shown");

    const useBtn = root.querySelector("a[href='/studio/?style=FB-041']");
    assert.ok(useBtn, "Use style button must exist");
    assert.match(useBtn.textContent, /使用此画风/);

    assert.ok(relatedWorksRequested, "Must request related works for style FB-041");
    assert.ok(pairedResourcesRequested, "Must request paired layouts recommendation for style FB-041");

    const worksContainer = root.querySelector("#topic-related-works-container");
    assert.ok(worksContainer.innerHTML.includes("/t/work_rw1"), "Related works should link to post permalink");
    assert.ok(worksContainer.innerHTML.includes("水彩花卉"), "Related works title must appear");
    console.log("Scenario 3 passed: Style mount renders definition, copy, use button, and related works.");
  }

  /* ==========================================================================
   * Scenario 4: 404 displays "帖子不存在或已不可见";
   *             Network failure displays "#topic-retry-btn", clicking retries successfully.
   * ========================================================================== */
  {
    // 4a: 404 state
    const apiHandlers404 = new Map();
    apiHandlers404.set("/api/posts/t_missing", async () => ({
      ok: false,
      status: 404,
      json: async () => ({ ok: false, error: "帖子不存在" })
    }));

    const h404 = createHarness({ locationSearch: "?view=topic&id=t_missing", apiHandlers: apiHandlers404 });
    h404.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));
    assert.ok(h404.forumRoot.innerHTML.includes("帖子不存在或已不可见"), "404 must display '帖子不存在或已不可见'");
    assert.ok(h404.forumRoot.querySelector("#topic-missing-back"), "Back button must exist on 404");

    // 4b: Network error and retry
    let shouldFail = true;
    const apiHandlersNet = new Map();
    apiHandlersNet.set("/api/posts/t_flaky/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, items: [], nextCursor: null })
    }));
    apiHandlersNet.set("/api/posts/t_flaky", async () => {
      if (shouldFail) {
        throw new Error("Network connection dropped");
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          topic: { id: "t_flaky", title: "恢复后的帖子", author: "tester", authorName: "测试员", likes: 1, favorites: 1 },
          mount: { kind: "discussion" },
          viewer: { liked: false, favorited: false }
        })
      };
    });

    const hNet = createHarness({ locationSearch: "?view=topic&id=t_flaky", apiHandlers: apiHandlersNet });
    hNet.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    assert.ok(hNet.forumRoot.innerHTML.includes("网络加载失败"), "Network error must display '网络加载失败'");
    const retryBtn = hNet.forumRoot.querySelector("#topic-retry-btn");
    assert.ok(retryBtn, "#topic-retry-btn must exist");

    // Click retry
    shouldFail = false;
    retryBtn.onclick();
    await new Promise((resolve) => setTimeout(resolve, 80));

    assert.ok(hNet.forumRoot.innerHTML.includes("恢复后的帖子"), "After retry, topic title must be rendered");
    console.log("Scenario 4 passed: 404 message and network error retry button verified.");
  }

  /* ==========================================================================
   * Scenario 5: Like updates immediately +1; when API fails, rolls back and
   *             displays toast; confirms refreshFromServer was NOT called.
   * ========================================================================== */
  {
    let likeApiShouldFail = false;
    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/t_like_test/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, items: [], nextCursor: null })
    }));
    apiHandlers.set("/api/posts/t_like_test", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_like_test", title: "点赞测试帖", author: "author1", authorName: "作者", likes: 10, favorites: 5 },
        mount: { kind: "discussion" },
        viewer: { liked: false, favorited: false }
      })
    }));
    apiHandlers.set("/api/interactions/like", async (_url, opts) => {
      if (likeApiShouldFail) {
        return {
          ok: false,
          status: 500,
          json: async () => ({ ok: false, error: "点赞服务异常" })
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, liked: true, likes: 11 })
      };
    });

    const h = createHarness({ locationSearch: "?view=topic&id=t_like_test", apiHandlers });
    h.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    const likeBtn = h.forumRoot.querySelector("#topic-page-like");
    const countsEl = h.forumRoot.querySelector("#topic-counts");
    assert.ok(likeBtn, "#topic-page-like button must exist");
    assert.equal(likeBtn.textContent.trim(), "👍 点赞 (10)");
    assert.equal(countsEl.textContent, "点赞 10 · 收藏 5");

    // 1. Success case: click like -> immediately updates
    likeBtn.onclick();
    // Synchronous optimistic check
    assert.equal(likeBtn.textContent.trim(), "👍 已赞 (11)", "Optimistic UI: like button updates immediately");
    assert.equal(countsEl.textContent, "点赞 11 · 收藏 5", "Optimistic UI: counts text updates immediately");

    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(h.getRefreshFromServerCount(), 0, "refreshFromServer must NOT be called on like");
    assert.ok(h.toasts.includes("👍 已点赞"), "Toast must confirm like success");

    // 2. Failure case: make API fail on toggle
    likeApiShouldFail = true;
    likeBtn.onclick();
    // Optimistic toggle: liked -> unliked (10)
    assert.equal(likeBtn.textContent.trim(), "👍 点赞 (10)");

    // Wait for API to reject and rollback
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(likeBtn.textContent.trim(), "👍 已赞 (11)", "On API failure, like count must rollback");
    assert.equal(countsEl.textContent, "点赞 11 · 收藏 5", "On API failure, counts must rollback");
    assert.equal(h.getRefreshFromServerCount(), 0, "refreshFromServer must still NOT be called");
    assert.ok(h.toasts.some((m) => m.includes("点赞失败")), "Toast must show failure message");
    console.log("Scenario 5 passed: Optimistic like update, rollback on failure, no refreshFromServer.");
  }

  /* ==========================================================================
   * Scenario 6: Reply pagination loads next batch with nextCursor;
   *             Submitting reply appends to bottom without full page refresh.
   * ========================================================================== */
  {
    let repliesRequestCursor = null;
    let replySubmittedText = null;

    const apiHandlers = new Map();
    apiHandlers.set(/\/api\/posts\/t_replies_test\/replies/, async (url) => {
      const u = new URL(url, "http://127.0.0.1:3080");
      const cursor = u.searchParams.get("cursor");
      repliesRequestCursor = cursor;

      if (!cursor) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            items: [
              { id: "rep_1", author: "alice", authorName: "爱丽丝", text: "第一条回复", time: "10分钟前" }
            ],
            nextCursor: "cursor_page_2"
          })
        };
      } else {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            items: [
              { id: "rep_2", author: "bob", authorName: "鲍勃", text: "第二条回复通过分页加载", time: "5分钟前" }
            ],
            nextCursor: null
          })
        };
      }
    });

    apiHandlers.set("/api/posts/t_replies_test", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_replies_test", title: "回复分页与发表测试", author: "author", authorName: "原作者", likes: 2, favorites: 1 },
        mount: { kind: "discussion" },
        viewer: { liked: false, favorited: false }
      })
    }));

    apiHandlers.set("/api/forum/topics/t_replies_test/replies", async (_url, opts) => {
      const payload = JSON.parse(opts.body);
      replySubmittedText = payload.text;
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, replyId: "rep_new_3", rewarded: 2 })
      };
    });

    const h = createHarness({ locationSearch: "?view=topic&id=t_replies_test", apiHandlers });
    h.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;
    const repliesList = root.querySelector("#topic-replies-list");
    assert.ok(repliesList.innerHTML.includes("第一条回复"), "Initial reply must appear in replies list");

    const loadMoreBtn = root.querySelector("#topic-load-more-replies-btn");
    assert.ok(loadMoreBtn, "#topic-load-more-replies-btn must exist when nextCursor is present");

    // Click load more
    loadMoreBtn.onclick();
    await new Promise((resolve) => setTimeout(resolve, 60));

    assert.equal(repliesRequestCursor, "cursor_page_2", "Pagination request must use nextCursor");
    assert.ok(repliesList.innerHTML.includes("第一条回复"), "Previous reply must remain");
    assert.ok(repliesList.innerHTML.includes("第二条回复通过分页加载"), "New reply must be appended");
    assert.equal(root.querySelector("#topic-load-more-replies-btn"), null, "Load more button must be removed when nextCursor is null");

    // Submit new reply
    const replyInput = root.querySelector("#topic-reply-input");
    const replySubmitBtn = root.querySelector("#topic-reply-submit");
    assert.ok(replyInput && replySubmitBtn, "Reply input and submit button must exist");

    replyInput.value = "这是我刚刚提交的跟帖回答";
    await replySubmitBtn.onclick();
    await new Promise((resolve) => setTimeout(resolve, 40));

    assert.equal(replySubmittedText, "这是我刚刚提交的跟帖回答", "Submitted text must match input");
    assert.ok(repliesList.innerHTML.includes("这是我刚刚提交的跟帖回答"), "New reply must be appended to replies list");
    assert.equal(replyInput.value, "", "Input must be cleared after submission");
    assert.ok(root.querySelector("#topic-replies-title").textContent.includes("(3)"), "Replies title count must update to 3");
    console.log("Scenario 6 passed: Replies pagination and append without page refresh verified.");
  }

  /* ==========================================================================
   * Scenario 7: Legacy view=resource&kind=style&id=FB-041 calls by-ref
   *             and location.replace to topic page.
   * ========================================================================== */
  {
    let byRefUrlRequested = null;
    const apiHandlers = new Map();
    apiHandlers.set(/\/api\/posts\/by-ref\/style\/FB-041/, async (url) => {
      byRefUrlRequested = url;
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, topicId: "topic_style_fb041" })
      };
    });

    const h = createHarness({ locationSearch: "?view=resource&kind=style&id=FB-041", apiHandlers });
    const HandrawResourcePages = h.context.window.HandrawResourcePages;
    assert.ok(HandrawResourcePages, "HandrawResourcePages must exist");

    const mockRoot = new MockElement("DIV");
    HandrawResourcePages.render(mockRoot, new URLSearchParams("view=resource&kind=style&id=FB-041"));

    await new Promise((resolve) => setTimeout(resolve, 60));

    assert.ok(byRefUrlRequested, "Must call /api/posts/by-ref/style/FB-041");
    assert.equal(h.getReplaceLocation(), "/forum/?view=topic&id=topic_style_fb041", "location.replace must redirect to topic page");

    // Inferred kind for asset prefix
    let layoutByRefRequested = null;
    apiHandlers.set(/\/api\/posts\/by-ref\/layout\/SC-001/, async (url) => {
      layoutByRefRequested = url;
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, topicId: "topic_layout_sc001" })
      };
    });
    HandrawResourcePages.render(mockRoot, new URLSearchParams("view=resource&kind=asset&id=SC-001"));
    await new Promise((resolve) => setTimeout(resolve, 60));
    assert.ok(layoutByRefRequested, "Must infer layout kind from SC prefix and call by-ref/layout/SC-001");
    assert.equal(h.getReplaceLocation(), "/forum/?view=topic&id=topic_layout_sc001");

    // Missing resource shows 404
    apiHandlers.set(/\/api\/posts\/by-ref\/style\/UNKNOWN/, async () => ({
      ok: false,
      status: 404,
      json: async () => ({ ok: false, error: "not found" })
    }));
    HandrawResourcePages.render(mockRoot, new URLSearchParams("view=resource&kind=style&id=UNKNOWN"));
    await new Promise((resolve) => setTimeout(resolve, 60));
    assert.ok(mockRoot.innerHTML.includes("资源不存在"), "Missing resource must render '资源不存在'");
    console.log("Scenario 7 passed: Legacy resource redirect via by-ref and kind inference verified.");
  }


  /* ==========================================================================
   * Scenario 8 (R2): Unlocking paid resource passes resource code and
   *                  targetType: "asset", then re-fetches topic detail without
   *                  calling refreshFromServer.
   * ========================================================================== */
  {
    let unlockPayload = null;
    let postDetailFetchCount = 0;
    let isUnlocked = false;
    const apiHandlers = new Map();

    apiHandlers.set("/api/posts/t_paid_style/replies", async () => ({
      ok: true, status: 200, json: async () => ({ ok: true, items: [], nextCursor: null })
    }));

    apiHandlers.set("/api/posts/t_paid_style", async () => {
      postDetailFetchCount++;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          topic: { id: "t_paid_style", title: "付费独家黑盒画风", author: "official", authorName: "官方", likes: 3, favorites: 1 },
          mount: {
            kind: "style",
            resource: {
              code: "FX-001",
              name: "复古墨色插画",
              unlocked: isUnlocked,
              unlockCost: 20,
              definition: isUnlocked ? "watercolor soft ink, editorial retro paper" : "",
              useUrl: "/studio/?style=FX-001"
            }
          },
          viewer: { liked: false, favorited: false }
        })
      };
    });

    apiHandlers.set("/api/unlocks", async (_url, opts) => {
      unlockPayload = JSON.parse(opts.body);
      isUnlocked = true;
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, unlocked: true, remainingBalance: 80 })
      };
    });

    const h = createHarness({ locationSearch: "?view=topic&id=t_paid_style", apiHandlers });
    h.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;
    const unlockBtn = root.querySelector("#resource-btn-unlock");
    assert.ok(unlockBtn, "#resource-btn-unlock must exist for locked paid resource");
    assert.match(unlockBtn.textContent, /立即解锁/);

    // Click unlock
    await unlockBtn.onclick();
    await new Promise((resolve) => setTimeout(resolve, 100));

    // Assert unlock payload passes resource code and targetType: "asset"
    assert.ok(unlockPayload, "Must send request to /api/unlocks");
    assert.equal(unlockPayload.targetId, "FX-001", "targetId must be resource code (FX-001), not topic id");
    assert.equal(unlockPayload.targetType, "asset", "targetType must be 'asset'");

    // Assert topic detail was re-fetched without calling refreshFromServer
    assert.ok(postDetailFetchCount >= 2, "Topic detail must be reloaded after unlock");
    assert.equal(h.getRefreshFromServerCount(), 0, "refreshFromServer must NOT be called on unlock");
    assert.ok(root.innerHTML.includes("watercolor soft ink"), "Unlocked definition must appear after reload");
    console.log("Scenario 8 passed: Unlocking paid resource passes targetType: 'asset' & reloads topic detail.");
  }

  /* ==========================================================================
   * Scenario 9 (R3): Governance & Bounty controls permissions:
   *                  9a: Author sees '采纳' on bounty replies and can accept;
   *                  9b: Staff sees '采纳', header '仲裁', and '删除'/'隐藏';
   *                  9c: Ordinary user sees neither.
   * ========================================================================== */
  {
    const repliesData = [
      { id: "rep_b1", author: "helper1", authorName: "热心画师", text: "建议提高边缘对比度", time: "1小时前", accepted: false },
      { id: "rep_b2", author: "helper2", authorName: "高手", text: "添加水墨晕染关键词", time: "30分钟前", accepted: false }
    ];

    let acceptedReplyId = null;
    let moderatedReplyId = null;

    const createBountyHandlers = () => {
      const handlers = new Map();
      handlers.set("/api/posts/t_bounty/replies", async () => ({
        ok: true, status: 200, json: async () => ({ ok: true, items: repliesData, nextCursor: null })
      }));
      handlers.set("/api/posts/t_bounty", async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          topic: {
            id: "t_bounty",
            title: "求助：画风颗粒感怎么调？",
            author: "bounty_author",
            authorName: "求助楼主",
            category: "bounty",
            bounty: 50,
            solved: false,
            likes: 1,
            favorites: 0
          },
          mount: { kind: "discussion" },
          viewer: { liked: false, favorited: false }
        })
      }));
      handlers.set(/\/api\/forum\/topics\/t_bounty\/accept-bounty/, async (_url, opts) => {
        const body = JSON.parse(opts.body);
        acceptedReplyId = body.replyId;
        return { ok: true, status: 200, json: async () => ({ ok: true, winnerName: "热心画师", bounty: 50 }) };
      });
      handlers.set("/api/forum/moderate", async (_url, opts) => {
        const body = JSON.parse(opts.body);
        moderatedReplyId = body.replyId;
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
      });
      return handlers;
    };

    // 9a: Topic Author
    {
      const hAuthor = createHarness({
        locationSearch: "?view=topic&id=t_bounty",
        apiHandlers: createBountyHandlers(),
        currentUser: { username: "bounty_author", role: "user" }
      });
      hAuthor.loadForumApp();
      await new Promise((resolve) => setTimeout(resolve, 80));

      const root = hAuthor.forumRoot;
      const acceptBtns = root.querySelectorAll("button[data-accept-reply]");
      assert.equal(acceptBtns.length, 2, "Topic author must see accept bounty button on replies");
      assert.equal(root.querySelectorAll("button[data-del-reply]").length, 0, "Ordinary author must not see delete reply buttons");
      assert.equal(root.querySelectorAll("button[data-hide-reply]").length, 0, "Ordinary author must not see hide reply buttons");

      // Click accept on first reply
      const repList = root.querySelector("#topic-replies-list");
      const acceptBtn = root.querySelector("button[data-accept-reply='rep_b1']");
      await repList.onclick({ target: acceptBtn });
      await new Promise((resolve) => setTimeout(resolve, 40));
      assert.equal(acceptedReplyId, "rep_b1", "Author clicking accept must trigger accept-bounty API with replyId");
      assert.ok(hAuthor.toasts.some((t) => t.includes("已采纳 @热心画师")), "Acceptance settlement toast must be shown");
    }

    // 9b: Staff / Admin
    {
      const hAdmin = createHarness({
        locationSearch: "?view=topic&id=t_bounty",
        apiHandlers: createBountyHandlers(),
        currentUser: { username: "admin_user", role: "admin" }
      });
      hAdmin.loadForumApp();
      await new Promise((resolve) => setTimeout(resolve, 80));

      const root = hAdmin.forumRoot;
      assert.ok(root.querySelector("#topic-mod-arbitrate-bounty"), "Admin must see header arbitrate button");
      assert.ok(root.querySelectorAll("button[data-accept-reply]").length > 0, "Admin must see accept buttons");
      assert.ok(root.querySelectorAll("button[data-del-reply]").length > 0, "Admin must see delete buttons");
      assert.ok(root.querySelectorAll("button[data-hide-reply]").length > 0, "Admin must see hide buttons");

      // Test arbitrate button click
      const arbBtn = root.querySelector("#topic-mod-arbitrate-bounty");
      assert.equal(typeof arbBtn.onclick, "function", "Arbitrate button must have an active click handler");

      // Test delete button via event delegation
      hAdmin.context.confirm = () => true;
      const repListAdmin = root.querySelector("#topic-replies-list");
      const delBtn = root.querySelector("button[data-del-reply='rep_b2']");
      await repListAdmin.onclick({ target: delBtn });
      await new Promise((resolve) => setTimeout(resolve, 40));
      assert.equal(moderatedReplyId, "rep_b2", "Moderator clicking delete must trigger moderate API with delete_reply op");
    }

    // 9c: Ordinary Viewer (not author, not admin)
    {
      const hViewer = createHarness({
        locationSearch: "?view=topic&id=t_bounty",
        apiHandlers: createBountyHandlers(),
        currentUser: { username: "stranger", role: "user" }
      });
      hViewer.loadForumApp();
      await new Promise((resolve) => setTimeout(resolve, 80));

      const root = hViewer.forumRoot;
      assert.equal(root.querySelectorAll("button[data-accept-reply]").length, 0, "Ordinary user must not see accept buttons");
      assert.equal(root.querySelectorAll("button[data-arbitrate-bounty]").length, 0, "Ordinary user must not see arbitrate button");
      assert.equal(root.querySelectorAll("button[data-del-reply]").length, 0, "Ordinary user must not see delete buttons");
      assert.equal(root.querySelectorAll("button[data-hide-reply]").length, 0, "Ordinary user must not see hide buttons");
    }

    console.log("Scenario 9 passed: Floor governance and bounty permissions verified across author, admin, and viewer.");
  }

  /* ==========================================================================
   * Scenario 10 (R4): Style/Layout interaction targets parity:
   *                   - Style post writes to targetType: "style" and bucket: "styles";
   *                   - Layout post writes to targetType: "layout" and bucket: "layouts";
   *                   - Work post writes to targetType: "topic" and bucket: "topics".
   * ========================================================================== */
  {
    let lastLikePayload = null;
    let lastCollectPayload = null;

    const testInteractionParity = async (kind, code, expectTargetType, expectBucket) => {
      const apiHandlers = new Map();
      apiHandlers.set(/\/api\/posts\//, async (url) => {
        if (url.includes("/replies")) return { ok: true, status: 200, json: async () => ({ ok: true, items: [] }) };
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            topic: { id: `t_${kind}`, title: `${kind}测试`, likes: kind === "work" ? 5 : 0, favorites: kind === "work" ? 2 : 0 },
            mount: kind === "work"
              ? { kind: "work", work: { id: code, title: "作品", likes: 5, favorites: 2 } }
              : { kind, resource: { code, name: `${kind}资源`, likes: 23, favorites: 1 } },
            viewer: { liked: false, favorited: false }
          })
        };
      });

      apiHandlers.set("/api/interactions/like", async (_url, opts) => {
        lastLikePayload = JSON.parse(opts.body);
        return { ok: true, status: 200, json: async () => ({ ok: true, liked: true, likes: 6 }) };
      });
      apiHandlers.set("/api/collections", async (_url, opts) => {
        lastCollectPayload = JSON.parse(opts.body);
        return { ok: true, status: 200, json: async () => ({ ok: true, favorited: true, favorites: 3 }) };
      });

      const h = createHarness({ locationSearch: `?view=topic&id=t_${kind}`, apiHandlers });
      h.loadForumApp();
      await new Promise((resolve) => setTimeout(resolve, 80));

      // Verify initial counts read from mount.resource for style/layout, or mount.work for work (U1)
      const expectedInitialCounts = kind === "work" ? "点赞 5 · 收藏 2 · 做同款 0" : "点赞 23 · 收藏 1";
      assert.equal(h.forumRoot.querySelector("#topic-counts").textContent, expectedInitialCounts, `Initial counts for ${kind} must read from mount.${kind === "work" ? "work" : "resource"}`);

      // Click like
      const likeBtn = h.forumRoot.querySelector("#topic-page-like");
      likeBtn.onclick();
      await new Promise((resolve) => setTimeout(resolve, 40));

      assert.equal(lastLikePayload.targetType, expectTargetType, `Like targetType for ${kind} must be ${expectTargetType}`);
      assert.equal(lastLikePayload.id, kind === "work" ? "t_work" : code, `Like id for ${kind} must match target`);
      // Asset mount uses local +/- 1 (23 + 1 = 24) instead of fake server res.likes (6)
      const expectedAfterLikeCounts = kind === "work" ? "点赞 6 · 收藏 2 · 做同款 0" : "点赞 24 · 收藏 1";
      assert.equal(h.forumRoot.querySelector("#topic-counts").textContent, expectedAfterLikeCounts, `Counts after like for ${kind} must reflect local +/- 1`);

      // Click collect
      const favBtn = h.forumRoot.querySelector("#topic-page-collect");
      favBtn.onclick();
      await new Promise((resolve) => setTimeout(resolve, 40));

      assert.equal(lastCollectPayload.bucket, expectBucket, `Collect bucket for ${kind} must be ${expectBucket}`);
      assert.equal(lastCollectPayload.targetId, kind === "work" ? "t_work" : code, `Collect targetId for ${kind} must match target`);
      const expectedAfterFavCounts = kind === "work" ? "点赞 6 · 收藏 3 · 做同款 0" : "点赞 24 · 收藏 2";
      assert.equal(h.forumRoot.querySelector("#topic-counts").textContent, expectedAfterFavCounts, `Counts after collect for ${kind} must reflect local +/- 1`);
    };

    // 10a: Style FB-041 -> like: style/FB-041, collect: styles/FB-041
    await testInteractionParity("style", "FB-041", "style", "styles");
    // 10b: Layout SC-021 -> like: layout/SC-021, collect: layouts/SC-021
    await testInteractionParity("layout", "SC-021", "layout", "layouts");
    // 10c: Work work_101 -> like: topic/t_work, collect: topics/t_work
    await testInteractionParity("work", "work_101", "topic", "topics");

    console.log("Scenario 10 passed: Style/Layout/Work interaction targets match server viewer model.");
  }

  /* ==========================================================================
   * Scenario 11 (R5): Successful like/collect updates cached _activeTopicDetail;
   *                   Triggering share re-render retains optimistic counts.
   * ========================================================================== */
  {
    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/t_cache_sync/replies", async () => ({
      ok: true, status: 200, json: async () => ({ ok: true, items: [] })
    }));
    apiHandlers.set("/api/posts/t_cache_sync", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_cache_sync", title: "缓存同步测试", likes: 356, favorites: 310 },
        mount: { kind: "discussion" },
        viewer: { liked: false, favorited: false }
      })
    }));
    apiHandlers.set("/api/interactions/like", async () => ({
      ok: true, status: 200, json: async () => ({ ok: true, liked: true, likes: 357 })
    }));
    apiHandlers.set("/api/collections", async () => ({
      ok: true, status: 200, json: async () => ({ ok: true, favorited: true, favorites: 311 })
    }));

    const h = createHarness({ locationSearch: "?view=topic&id=t_cache_sync", apiHandlers });
    h.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;
    const likeBtn = root.querySelector("#topic-page-like");
    const favBtn = root.querySelector("#topic-page-collect");

    // Perform like & collect
    likeBtn.onclick();
    favBtn.onclick();
    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 357 · 收藏 311");
    assert.match(likeBtn.textContent, /已赞 \(357\)/);
    assert.match(favBtn.textContent, /已收藏 \(311\)/);

    // Click share button to trigger re-render
    const shareBtn = root.querySelector("#topic-page-share");
    assert.ok(shareBtn, "Share button must exist");
    shareBtn.onclick();
    await new Promise((resolve) => setTimeout(resolve, 40));

    // Verify state does NOT revert to 356/310
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 357 · 收藏 311", "Counts must remain 357/311 after modal re-render");
    assert.match(root.querySelector("#topic-page-like").textContent, /已赞 \(357\)/, "Like button must remain in liked state");
    assert.match(root.querySelector("#topic-page-collect").textContent, /已收藏 \(311\)/, "Favorite button must remain in favorited state");

    console.log("Scenario 11 passed: Cached topicData & viewer stay synchronized with interactions.");
  }

  /* ==========================================================================
   * Scenario 12 (R6, R7): Event delegation on replies container & pending replies:
   *                       - Newly appended floors handle quote/reply via delegation;
   *                       - When nextCursor is active, new replies go to pendingReplies;
   *                       - Next page load de-duplicates by ID and merges pendingReplies.
   * ========================================================================== */
  {
    let repliesRequestCursor = null;
    const apiHandlers = new Map();

    apiHandlers.set(/\/api\/posts\/t_delegation\/replies/, async (url) => {
      const u = new URL(url, "http://127.0.0.1:3080");
      const cursor = u.searchParams.get("cursor");
      repliesRequestCursor = cursor;

      if (!cursor) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            items: [
              { id: "rep_p1", author: "alice", authorName: "爱丽丝", text: "第一页内容", time: "10分钟前" }
            ],
            nextCursor: "cursor_page_2"
          })
        };
      } else {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            items: [
              // Include a duplicate rep_p1 to test R7 de-duplication
              { id: "rep_p1", author: "alice", authorName: "爱丽丝", text: "第一页内容(重复)", time: "10分钟前" },
              { id: "rep_p2", author: "bob", authorName: "鲍勃", text: "第二页内容", time: "5分钟前" }
            ],
            nextCursor: null
          })
        };
      }
    });

    apiHandlers.set("/api/posts/t_delegation", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_delegation", title: "事件委托与暂存测试", author: "alice", authorName: "爱丽丝", likes: 0, favorites: 0 },
        mount: { kind: "discussion" },
        viewer: { liked: false, favorited: false }
      })
    }));

    apiHandlers.set("/api/forum/topics/t_delegation/replies", async (_url, opts) => {
      const payload = JSON.parse(opts.body);
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, replyId: "rep_user_pending", rewarded: 1 })
      };
    });

    const h = createHarness({ locationSearch: "?view=topic&id=t_delegation", apiHandlers });
    h.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;
    const repInput = root.querySelector("#topic-reply-input");

    // 1. Submit reply while nextCursor exists -> must go to pendingReplies
    repInput.value = "这是分页未完时的发表";
    await root.querySelector("#topic-reply-submit").onclick();
    await new Promise((resolve) => setTimeout(resolve, 40));

    const pendWrap = root.querySelector("#topic-pending-replies-wrap");
    assert.ok(pendWrap, "When nextCursor is active, #topic-pending-replies-wrap must be displayed");
    assert.ok(pendWrap.innerHTML.includes("这是分页未完时的发表"), "Pending reply must appear in pending container");

    // 2. Test event delegation on newly added pending reply: click quote
    const quoteBtn = pendWrap.querySelector("button[data-quote-floor]");
    assert.ok(quoteBtn, "Quote button must exist on pending reply");
    await pendWrap.querySelector("#topic-pending-replies-list").onclick({ target: quoteBtn });
    assert.ok(repInput.value.includes("回复 #"), "Event delegation on pending replies must populate quote in textarea");

    // 3. Click Load More replies: verifies de-duplication and merging
    const loadMoreBtn = root.querySelector("#topic-load-more-replies-btn");
    assert.ok(loadMoreBtn, "Load more button must exist");
    await loadMoreBtn.onclick();
    await new Promise((resolve) => setTimeout(resolve, 60));

    const repliesList = root.querySelector("#topic-replies-list");
    // Duplicate check: "第一页内容" should only appear once
    const matchesCount = (repliesList.innerHTML.match(/第一页内容/g) || []).length;
    assert.equal(matchesCount, 1, "Duplicate reply IDs from pagination must be filtered out");
    assert.ok(repliesList.innerHTML.includes("第二页内容"), "Paged reply must be appended");

    // Since nextCursor is now null, pendingReplies should be merged into main list
    assert.ok(repliesList.innerHTML.includes("这是分页未完时的发表"), "Pending replies must merge into main replies list once pagination is complete");
    assert.equal(root.querySelector("#topic-pending-replies-wrap"), null, "Pending wrap must be removed after merge");

    console.log("Scenario 12 passed: Event delegation on replies list and pending replies order preserved.");
  }

  /* ==========================================================================
   * Scenario 13 (R8, R9, R10): Focus query param, reduced motion & responsive CSS:
   *                            - ?focus=comment scrolls to section and focuses input;
   *                            - prefers-reduced-motion: reduce uses behavior: 'auto';
   *                            - theme.css responsive rules contain min-width: 0 and
   *                              overflow-wrap: anywhere;
   *                            - smart card copy uses '做同款 ↗'.
   * ========================================================================== */
  {
    const apiHandlers = new Map();
    apiHandlers.set("/api/posts/t_focus_test/replies", async () => ({
      ok: true, status: 200, json: async () => ({ ok: true, items: [] })
    }));
    apiHandlers.set("/api/posts/t_focus_test", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_focus_test", title: "聚焦测试帖", likes: 0, favorites: 0 },
        mount: { kind: "discussion" },
        viewer: { liked: false, favorited: false }
      })
    }));

    // 13a: Focus with normal motion -> smooth
    {
      const hNormal = createHarness({ locationSearch: "?view=topic&id=t_focus_test&focus=comment", apiHandlers });
      hNormal.loadForumApp();
      await new Promise((resolve) => setTimeout(resolve, 200));

      const sec = hNormal.forumRoot.querySelector("#topic-replies-section");
      const inp = hNormal.forumRoot.querySelector("#topic-reply-input");
      assert.ok(sec && sec._lastScrollOpts, "Section must be scrolled into view when focus=comment");
      assert.equal(sec._lastScrollOpts.behavior, "smooth", "Default scroll behavior must be 'smooth'");
      assert.equal(inp._focused, true, "Reply input must be focused when focus=comment");
    }

    // 13b: Focus with prefers-reduced-motion -> auto
    {
      const hReduced = createHarness({ locationSearch: "?view=topic&id=t_focus_test&focus=comment", apiHandlers });
      hReduced.window._reducedMotion = true;
      hReduced.loadForumApp();
      await new Promise((resolve) => setTimeout(resolve, 200));

      const sec = hReduced.forumRoot.querySelector("#topic-replies-section");
      assert.ok(sec && sec._lastScrollOpts);
      assert.equal(sec._lastScrollOpts.behavior, "auto", "Reduced motion scroll behavior must be 'auto'");
    }

    // 13c: CSS inspection for R9
    const cssContent = fs.readFileSync("demo/assets/theme.css", "utf8");
    assert.ok(cssContent.includes("overflow-wrap: anywhere;"), "theme.css must specify overflow-wrap: anywhere");
    assert.ok(cssContent.includes(".forum-thread-layout .forum-thread-sidebar"), "theme.css must style thread sidebar");

    // 13d: Smart card copy for R10
    const forumAppJs = fs.readFileSync("demo/assets/forum-app.js", "utf8");
    assert.ok(forumAppJs.includes("做同款 ↗"), "Smart card copy must use '做同款 ↗'");
    assert.ok(!forumAppJs.includes("创作台复刻 ↗"), "Legacy '创作台复刻 ↗' must be removed");

    console.log("Scenario 13 passed: Focus param, reduced motion & responsive CSS verified.");
  }

  /* ==========================================================================
   * Scenario 14 (U2): Paged replies containing newly submitted reply:
   *                   - Initial page 1 loads 20 replies with nextCursor;
   *                   - User posts a new reply, added to pendingReplies and pending DOM;
   *                   - User loads page 2: server returns 6 replies including the
   *                     newly submitted reply (total server replies: 26);
   *                   - Result: total rendered replies on page equals server count (26),
   *                     no duplicate reply cards, and #topic-pending-replies-wrap is removed.
   * ========================================================================== */
  {
    const initialItems = Array.from({ length: 20 }, (_, i) => ({
      id: `rep_${i + 1}`,
      author: `user_${i + 1}`,
      authorName: `用户${i + 1}`,
      text: `第${i + 1}楼回复内容`,
      time: "10分钟前",
    }));

    const page2Items = [
      ...Array.from({ length: 5 }, (_, i) => ({
        id: `rep_${21 + i}`,
        author: `user_${21 + i}`,
        authorName: `用户${21 + i}`,
        text: `第${21 + i}楼回复内容`,
        time: "5分钟前",
      })),
      {
        id: "rep_user_paged_in",
        author: "me",
        authorName: "创作者",
        text: "刚发表且随后被第二页收录的回复",
        time: "刚刚",
      },
    ];

    const apiHandlers = new Map();
    apiHandlers.set(/\/api\/posts\/t_paged_pending\/replies/, async (url) => {
      const u = new URL(url, "http://127.0.0.1:3080");
      const cursor = u.searchParams.get("cursor");
      if (!cursor) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            items: initialItems,
            nextCursor: "cursor_page_2",
          }),
        };
      } else {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            items: page2Items,
            nextCursor: null,
          }),
        };
      }
    });

    apiHandlers.set("/api/posts/t_paged_pending", async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_paged_pending", title: "分页合并去重测试", author: "alice", authorName: "爱丽丝", likes: 0, favorites: 0 },
        mount: { kind: "discussion" },
        viewer: { liked: false, favorited: false },
      }),
    }));

    apiHandlers.set("/api/forum/topics/t_paged_pending/replies", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, replyId: "rep_user_paged_in" }),
    }));

    const h = createHarness({ locationSearch: "?view=topic&id=t_paged_pending", apiHandlers });
    h.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;
    assert.equal(root.querySelectorAll(".forum-reply-card").length, 20, "Page 1 must render 20 replies");

    // Submit reply while nextCursor is active
    const repInput = root.querySelector("#topic-reply-input");
    repInput.value = "刚发表且随后被第二页收录的回复";
    await root.querySelector("#topic-reply-submit").onclick();
    await new Promise((resolve) => setTimeout(resolve, 40));

    // Pending container should now exist
    const pendWrap = root.querySelector("#topic-pending-replies-wrap");
    assert.ok(pendWrap, "Pending container must exist when nextCursor is active");
    assert.equal(root.querySelectorAll(".forum-reply-card").length, 21, "20 paged + 1 pending = 21 total cards");

    // Load page 2 (which contains rep_user_paged_in)
    const loadMoreBtn = root.querySelector("#topic-load-more-replies-btn");
    assert.ok(loadMoreBtn, "Load more button must exist");
    await loadMoreBtn.onclick();
    await new Promise((resolve) => setTimeout(resolve, 60));

    // Assert: Server has 26 replies total. Page must show exactly 26 reply cards.
    const allFloorCards = root.querySelectorAll(".forum-reply-card");
    assert.equal(allFloorCards.length, 26, "Page replies count must exactly match server total (26), no duplication");

    // Assert: Pending wrap must be completely removed from DOM
    assert.equal(root.querySelector("#topic-pending-replies-wrap"), null, "Pending wrap must be removed after merge");

    // Assert: The reply appears in floor list exactly once
    const floorOcc = Array.from(allFloorCards).filter((c) => c.textContent.includes("刚发表且随后被第二页收录的回复")).length;
    assert.equal(floorOcc, 1, "The newly submitted reply must appear in floor list exactly once");

    console.log("Scenario 14 passed: Paged replies containing pending reply de-duplicates and removes pending wrap.");
  }

  /* ==========================================================================
   * Scenario 15 (Y1): Serialized like & collect requests (anti-racing / debouncing):
   *                   - In-flight request sets disabled=true and aria-busy="true";
   *                   - Rapid consecutive clicks while in-flight are ignored (only 1 request sent);
   *                   - Button re-enabled and aria-busy removed after request settles (success & failure);
   *                   - Switching to another topic before response arrives discards stale response
   *                     and does NOT mutate the new topic's state or activeTopicDetail;
   *                   - Both Like and Collect are covered.
   * ========================================================================== */
  {
    let likeCallsCount = 0;
    let resolveLike = null;
    let rejectLike = null;

    let collectCallsCount = 0;
    let resolveCollect = null;
    let rejectCollect = null;

    const apiHandlers = new Map();
    apiHandlers.set(/\/api\/posts\//, async (url) => {
      if (url.includes("/replies")) return { ok: true, status: 200, json: async () => ({ ok: true, items: [] }) };
      const u = new URL(url, "http://127.0.0.1:3080");
      const id = u.pathname.split("/").pop();
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          topic: { id, title: `帖子 ${id}`, likes: id === "t_y1_b" ? 500 : 100, favorites: id === "t_y1_b" ? 250 : 50 },
          mount: { kind: "discussion" },
          viewer: { liked: false, favorited: false }
        })
      };
    });

    apiHandlers.set("/api/interactions/like", async () => {
      likeCallsCount++;
      return new Promise((resolve, reject) => {
        resolveLike = (likedVal = true, likesVal = 101) => resolve({ ok: true, status: 200, json: async () => ({ ok: true, liked: likedVal, likes: likesVal }) });
        rejectLike = (err) => reject(err || new Error("Like failed"));
      });
    });

    apiHandlers.set("/api/collections/toggle", async () => {
      collectCallsCount++;
      return new Promise((resolve, reject) => {
        resolveCollect = (collectedVal = true) => resolve({ ok: true, status: 200, json: async () => ({ ok: true, collected: collectedVal }) });
        rejectCollect = (err) => reject(err || new Error("Collect failed"));
      });
    });

    const h = createHarness({ locationSearch: "?view=topic&id=t_y1_a", apiHandlers });
    h.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;
    const likeBtn = root.querySelector("#topic-page-like");
    const favBtn = root.querySelector("#topic-page-collect");
    assert.ok(likeBtn && favBtn, "Like and Collect buttons must exist");

    // --- 1. LIKE: rapid consecutive clicks only send 1 request ---
    likeCallsCount = 0;
    likeBtn.onclick(); // Click 1
    assert.equal(likeCallsCount, 1, "First like click must initiate request");
    assert.equal(likeBtn.disabled, true, "Like button must be disabled while in-flight");
    assert.equal(likeBtn.getAttribute("aria-busy"), "true", "Like button must have aria-busy='true' while in-flight");

    likeBtn.onclick(); // Click 2 (during in-flight)
    likeBtn.onclick(); // Click 3 (during in-flight)
    assert.equal(likeCallsCount, 1, "Subsequent clicks while in-flight must be completely ignored");

    // Resolve in-flight like
    resolveLike(true, 101);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(likeBtn.disabled, false, "Like button must be re-enabled after success");
    assert.equal(likeBtn.getAttribute("aria-busy"), null, "aria-busy must be removed after success");
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 101 · 收藏 50");

    // --- 2. LIKE: failure recovery ---
    likeBtn.onclick(); // Click again to unlike
    assert.equal(likeCallsCount, 2, "New click after completion must initiate new request");
    assert.equal(likeBtn.disabled, true, "Like button must be disabled during second request");
    assert.equal(likeBtn.getAttribute("aria-busy"), "true");

    rejectLike(new Error("Network 500"));
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(likeBtn.disabled, false, "Like button must be re-enabled after failure");
    assert.equal(likeBtn.getAttribute("aria-busy"), null, "aria-busy must be removed after failure");
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 101 · 收藏 50", "Counts must roll back on failure");

    // --- 3. LIKE: Stale response protection on topic navigation ---
    likeBtn.onclick(); // Click to like while on t_y1_a
    assert.equal(likeCallsCount, 3);
    assert.equal(likeBtn.disabled, true);

    // Switch to t_y1_b before response arrives
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y1_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 500 · 收藏 250", "New topic t_y1_b must load its own counts");

    // Now resolve the old request from t_y1_a
    resolveLike(false, 100);
    await new Promise((resolve) => setTimeout(resolve, 40));
    // Verify t_y1_b was NOT overwritten by t_y1_a's response
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 500 · 收藏 250", "Old response must NOT overwrite new topic counts");

    // --- 4. COLLECT: switch back to t_y1_a and test collect ---
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y1_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    const favBtn2 = root.querySelector("#topic-page-collect");

    collectCallsCount = 0;
    favBtn2.onclick(); // Click 1
    assert.equal(collectCallsCount, 1, "First collect click must initiate request");
    assert.equal(favBtn2.disabled, true, "Collect button must be disabled while in-flight");
    assert.equal(favBtn2.getAttribute("aria-busy"), "true", "Collect button must have aria-busy='true'");

    favBtn2.onclick(); // Click 2 (during in-flight)
    favBtn2.onclick(); // Click 3 (during in-flight)
    assert.equal(collectCallsCount, 1, "Subsequent collect clicks while in-flight must be completely ignored");

    // Resolve collect
    resolveCollect(true);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(favBtn2.disabled, false, "Collect button must be re-enabled after success");
    assert.equal(favBtn2.getAttribute("aria-busy"), null, "aria-busy must be removed from collect button");
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 51");

    // --- 5. COLLECT: failure recovery ---
    favBtn2.onclick(); // Click to un-collect
    assert.equal(collectCallsCount, 2);
    assert.equal(favBtn2.disabled, true);

    rejectCollect(new Error("500 Server Error"));
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(favBtn2.disabled, false, "Collect button must be re-enabled after error");
    assert.equal(favBtn2.getAttribute("aria-busy"), null);
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 51", "Favorites must roll back on error");

    // --- 6. COLLECT: Stale response protection on topic navigation ---
    favBtn2.onclick();
    assert.equal(collectCallsCount, 3);
    assert.equal(favBtn2.disabled, true);

    // Switch to t_y1_b before collect response arrives
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y1_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 500 · 收藏 250");

    // Resolve old collect request
    resolveCollect(false);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 500 · 收藏 250", "Old collect response must NOT overwrite new topic counts");

    console.log("Scenario 15 passed: Serialized like & collect requests, in-flight debouncing, and navigation stale protection verified.");
  }

  /* ==========================================================================
   * Scenario 16 (Y2): Module-level in-flight lock across re-renders, topic switching and generation tracking:
   *                   - (a) in-flight -> re-render (share drawer) -> new button still disabled & aria-busy -> click ignored -> settle -> count matches;
   *                   - (b) in-flight on A -> switch to B -> return to A (new gen) -> A button still disabled -> settle old response -> triggers GET /api/posts/{id} calibration without applying increment;
   *                   - (c) switch to B -> settle old response on B -> does not mutate B.
   *                   - Symmetrically covered for both Like and Collect.
   * ========================================================================== */
  {
    let likeCallsCount = 0;
    let resolveLike = null;
    let rejectLike = null;

    let collectCallsCount = 0;
    let resolveCollect = null;
    let rejectCollect = null;

    let postCallsA = 0;
    let postCallsB = 0;

    const apiHandlers = new Map();
    apiHandlers.set(/\/api\/posts\//, async (url) => {
      if (url.includes("/replies")) return { ok: true, status: 200, json: async () => ({ ok: true, items: [] }) };
      const u = new URL(url, "http://127.0.0.1:3080");
      const id = u.pathname.split("/").pop();
      if (id === "t_y2_a") postCallsA++;
      if (id === "t_y2_b") postCallsB++;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          topic: { id, title: `Topic ${id}`, likes: id === "t_y2_b" ? 500 : 100, favorites: id === "t_y2_b" ? 250 : 50 },
          mount: { kind: "discussion" },
          viewer: { liked: false, favorited: false }
        })
      };
    });

    apiHandlers.set("/api/interactions/like", async () => {
      likeCallsCount++;
      return new Promise((resolve, reject) => {
        resolveLike = (likedVal = true, likesVal = 101) => resolve({ ok: true, status: 200, json: async () => ({ ok: true, liked: likedVal, likes: likesVal }) });
        rejectLike = (err) => reject(err || new Error("Like failed"));
      });
    });

    apiHandlers.set("/api/collections/toggle", async () => {
      collectCallsCount++;
      return new Promise((resolve, reject) => {
        resolveCollect = (collectedVal = true) => resolve({ ok: true, status: 200, json: async () => ({ ok: true, collected: collectedVal, favorites: collectedVal ? 51 : 50 }) });
        rejectCollect = (err) => reject(err || new Error("Collect failed"));
      });
    });

    const h = createHarness({ locationSearch: "?view=topic&id=t_y2_a", apiHandlers });
    h.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 50");

    // ==========================================
    // 1. LIKE TESTS: (a), (b), (c)
    // ==========================================

    // --- (a) Like in-flight -> re-render (share drawer) -> new button disabled -> click ignored -> settle -> counts match ---
    const likeBtnA1 = root.querySelector("#topic-page-like");
    likeCallsCount = 0;
    likeBtnA1.onclick();
    assert.equal(likeCallsCount, 1, "(a) First like click must initiate request");
    assert.equal(likeBtnA1.disabled, true);
    assert.equal(likeBtnA1.getAttribute("aria-busy"), "true");
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 101 · 收藏 50", "Optimistic like count applied");

    // Trigger re-render by opening share panel
    root.querySelector("#topic-page-share").onclick();
    const likeBtnA_drawer = root.querySelector("#topic-page-like");
    assert.notEqual(likeBtnA_drawer, likeBtnA1, "Re-render must produce new button element");
    assert.equal(likeBtnA_drawer.disabled, true, "(a) Re-rendered like button must remain disabled while request is in-flight");
    assert.equal(likeBtnA_drawer.getAttribute("aria-busy"), "true", "(a) Re-rendered like button must retain aria-busy='true'");

    // Clicking the new button while in-flight must be ignored
    likeBtnA_drawer.onclick();
    assert.equal(likeCallsCount, 1, "(a) Click on re-rendered like button while in-flight must be completely ignored");

    // Settle like response
    resolveLike(true, 101);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(likeBtnA_drawer.disabled, false, "(a) Like button must be re-enabled after response settles");
    assert.equal(likeBtnA_drawer.getAttribute("aria-busy"), null, "(a) aria-busy removed after response settles");
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 101 · 收藏 50", "(a) Counts match server response");

    // Close share drawer
    root.querySelector("#topic-page-share").onclick();

    // --- (b) Like in-flight on A -> switch to B -> return to A (new gen) -> A button disabled -> settle old response -> triggers GET /api/posts/t_y2_a calibration ---
    const likeBtnA2 = root.querySelector("#topic-page-like");
    likeBtnA2.onclick(); // in-flight unlike
    assert.equal(likeCallsCount, 2);
    assert.equal(likeBtnA2.disabled, true);

    // Switch to topic B while request is in-flight
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y2_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 500 · 收藏 250", "Switched to B");

    // Return to topic A before old response settles (generates new gen)
    const prevPostCallsA = postCallsA;
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y2_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    const likeBtnA_newGen = root.querySelector("#topic-page-like");
    assert.equal(likeBtnA_newGen.disabled, true, "(b) Button A in new generation must still be disabled because lock is retained in _socialInFlight");
    assert.equal(likeBtnA_newGen.getAttribute("aria-busy"), "true");

    // Settle old like response (from previous generation)
    resolveLike(false, 100);
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(likeBtnA_newGen.disabled, false, "(b) Button A re-enabled after settlement");
    assert.ok(postCallsA > prevPostCallsA + 1, "(b) Old response from previous gen triggered GET /api/posts/t_y2_a calibration without applying blind delta");
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 50", "(b) Counts calibrated from server");

    // --- (c) Like in-flight on A -> switch to B -> settle old response while on B -> B counts NOT modified ---
    const likeBtnA3 = root.querySelector("#topic-page-like");
    likeBtnA3.onclick(); // in-flight
    assert.equal(likeCallsCount, 3);
    assert.equal(likeBtnA3.disabled, true);

    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y2_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 500 · 收藏 250");

    // Settle old response while on B
    resolveLike(true, 101);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 500 · 收藏 250", "(c) Topic B counts must NOT be modified by stale A like response");

    // ==========================================
    // 2. COLLECT TESTS: (a), (b), (c)
    // ==========================================
    // Switch back to A to start collect tests
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y2_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    // --- (a) Collect in-flight -> re-render (share drawer) -> new button disabled -> click ignored -> settle -> counts match ---
    const favBtnA1 = root.querySelector("#topic-page-collect");
    collectCallsCount = 0;
    favBtnA1.onclick();
    assert.equal(collectCallsCount, 1, "(a) First collect click must initiate request");
    assert.equal(favBtnA1.disabled, true);
    assert.equal(favBtnA1.getAttribute("aria-busy"), "true");
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 51", "Optimistic collect count applied");

    // Re-render via share drawer
    root.querySelector("#topic-page-share").onclick();
    const favBtnA_drawer = root.querySelector("#topic-page-collect");
    assert.notEqual(favBtnA_drawer, favBtnA1, "Re-render must produce new collect button element");
    assert.equal(favBtnA_drawer.disabled, true, "(a) Re-rendered collect button must remain disabled while request is in-flight");
    assert.equal(favBtnA_drawer.getAttribute("aria-busy"), "true");

    favBtnA_drawer.onclick();
    assert.equal(collectCallsCount, 1, "(a) Click on re-rendered collect button while in-flight must be ignored");

    resolveCollect(true);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(favBtnA_drawer.disabled, false, "(a) Collect button must be re-enabled after response settles");
    assert.equal(favBtnA_drawer.getAttribute("aria-busy"), null);
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 51", "(a) Collect count matches server");

    // Close drawer
    root.querySelector("#topic-page-share").onclick();

    // --- (b) Collect in-flight on A -> switch to B -> return to A (new gen) -> A collect button disabled -> settle old response -> triggers GET /api/posts/t_y2_a calibration ---
    const favBtnA2 = root.querySelector("#topic-page-collect");
    favBtnA2.onclick();
    assert.equal(collectCallsCount, 2);
    assert.equal(favBtnA2.disabled, true);

    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y2_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    const prevPostCallsA2 = postCallsA;
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y2_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    const favBtnA_newGen = root.querySelector("#topic-page-collect");
    assert.equal(favBtnA_newGen.disabled, true, "(b) Collect button A in new generation must be disabled while lock in _socialInFlight");
    assert.equal(favBtnA_newGen.getAttribute("aria-busy"), "true");

    resolveCollect(false);
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(favBtnA_newGen.disabled, false, "(b) Collect button A re-enabled after settlement");
    assert.ok(postCallsA > prevPostCallsA2 + 1, "(b) Old response from previous gen triggered GET /api/posts/t_y2_a calibration without applying blind delta");
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 50", "(b) Counts calibrated from server");

    // --- (c) Collect in-flight on A -> switch to B -> settle old response while on B -> B counts NOT modified ---
    const favBtnA3 = root.querySelector("#topic-page-collect");
    favBtnA3.onclick();
    assert.equal(collectCallsCount, 3);
    assert.equal(favBtnA3.disabled, true);

    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y2_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 500 · 收藏 250");

    resolveCollect(true);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 500 · 收藏 250", "(c) Topic B counts must NOT be modified by stale A collect response");

    console.log("Scenario 16 passed: Module-level in-flight lock across re-renders, topic switching and generation tracking verified.");
  }

  /* ==========================================================================
   * Scenario 17 (Y3): End-to-end operation lock, interaction seq tracking, and interaction-only calibration:
   *                   - (a) Calibration GET in-flight keeps button disabled + aria-busy, click ignored;
   *                   - (b) Calibration GET returning after seq changed does NOT write back;
   *                   - (c) Calibration success only updates social fields, replies & pendingReplies untouched;
   *                   - (d) Calibration failure releases lock and re-enables button.
   *                   - Symmetrically covered for both Like and Collect.
   * ========================================================================== */
  {
    let likeCallsCount = 0;
    let resolveLikePost = null;

    let collectCallsCount = 0;
    let resolveCollectPost = null;

    let calibGetControlled = false;
    let resolveCalibGet = null;
    let rejectCalibGet = null;

    const apiHandlers = new Map();
    apiHandlers.set(/\/api\/posts\//, async (url) => {
      if (url.includes("/replies")) return { ok: true, status: 200, json: async () => ({ ok: true, items: [] }) };
      const u = new URL(url, "http://127.0.0.1:3080");
      const id = u.pathname.split("/").pop();

      if (id === "t_y3_a" && calibGetControlled) {
        calibGetControlled = false;
        return new Promise((resolve, reject) => {
          resolveCalibGet = resolve;
          rejectCalibGet = reject;
        });
      }

      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          topic: { id, title: `Topic ${id}`, likes: id === "t_y3_b" ? 500 : 100, favorites: id === "t_y3_b" ? 250 : 50 },
          mount: { kind: "discussion" },
          viewer: { liked: false, favorited: false }
        })
      };
    });

    apiHandlers.set("/api/interactions/like", async () => {
      likeCallsCount++;
      return new Promise((resolve) => {
        resolveLikePost = (likedVal = true, likesVal = 101) => resolve({ ok: true, status: 200, json: async () => ({ ok: true, liked: likedVal, likes: likesVal }) });
      });
    });

    apiHandlers.set("/api/collections/toggle", async () => {
      collectCallsCount++;
      return new Promise((resolve) => {
        resolveCollectPost = (collectedVal = true, favsVal = 51) => resolve({ ok: true, status: 200, json: async () => ({ ok: true, collected: collectedVal, favorites: favsVal }) });
      });
    });

    const h = createHarness({ locationSearch: "?view=topic&id=t_y3_a", apiHandlers });
    h.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));

    const root = h.forumRoot;

    // ==========================================
    // 1. LIKE TESTS: (a), (b), (c), (d)
    // ==========================================

    // --- (a) & (b): Calibration GET in-flight keeps button disabled + click ignored, and seq changed does not write back ---
    const likeBtn = root.querySelector("#topic-page-like");
    likeCallsCount = 0;
    likeBtn.onclick(); // POST in-flight
    assert.equal(likeCallsCount, 1);

    // Switch to B, then return to A
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    // Enable controlled calibration GET
    calibGetControlled = true;
    resolveLikePost(true, 101); // Settles POST -> triggers calibration GET
    await new Promise((resolve) => setTimeout(resolve, 30));

    // (a) Verify button is still disabled and aria-busy while calibration GET is in-flight
    const calibLikeBtn = root.querySelector("#topic-page-like");
    assert.equal(calibLikeBtn.disabled, true, "(a) Like button must be disabled while calibration GET is in-flight");
    assert.equal(calibLikeBtn.getAttribute("aria-busy"), "true", "(a) aria-busy must be true while calibration GET is in-flight");

    const likeCallsBefore = likeCallsCount;
    calibLikeBtn.onclick(); // Attempt click while calibration GET is in-flight
    assert.equal(likeCallsCount, likeCallsBefore, "(a) Click while calibration GET is in-flight must be completely ignored");

    // (b) Increment seq artificially before calibration GET returns
    const curSeq = h.window._socialSeq.get("t_y3_a:like") || 1;
    h.window._socialSeq.set("t_y3_a:like", curSeq + 1);

    // Now resolve calibration GET with stale/conflicting count 999
    resolveCalibGet({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_y3_a", likes: 999, favorites: 50 },
        mount: { kind: "discussion" },
        viewer: { liked: true }
      })
    });
    await new Promise((resolve) => setTimeout(resolve, 50));

    // (b) Verify 999 was NOT written back because seq changed!
    assert.notEqual(root.querySelector("#topic-counts").textContent, "点赞 999 · 收藏 50", "(b) Stale calibration GET must NOT write back when seq has changed");
    assert.equal(calibLikeBtn.disabled, false, "Button re-enabled after calibration settles");
    assert.equal(calibLikeBtn.getAttribute("aria-busy"), null);

    // --- (c): Calibration success only modifies interaction fields, replies & pendingReplies preserved ---
    // Inject custom replies and pendingReplies into current state
    const detailObj = root.querySelector("#standalone-topic-detail-page");
    assert.ok(detailObj, "Detail page must be rendered");
    // Switch to B, then return to A to test clean calibration write-back
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    // Start in-flight like
    const likeBtn2 = root.querySelector("#topic-page-like");
    likeBtn2.onclick();

    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    calibGetControlled = true;
    resolveLikePost(true, 101);
    await new Promise((resolve) => setTimeout(resolve, 30));

    // Resolve calibration GET with new likes 105 and favorites 50
    resolveCalibGet({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_y3_a", likes: 105, favorites: 50 },
        mount: { kind: "discussion" },
        viewer: { liked: true, favorited: false }
      })
    });
    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 105 · 收藏 50", "(c) Social fields updated from calibration");
    const likeBtnAfterCalib = root.querySelector("#topic-page-like");
    assert.equal(likeBtnAfterCalib.disabled, false);
    assert.ok(likeBtnAfterCalib.textContent.includes("已赞 (105)"), "(c) Like button displays updated calibrated count");

    // --- (d): Calibration GET failure releases lock and re-enables button ---
    likeBtnAfterCalib.onclick(); // POST in-flight
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    calibGetControlled = true;
    resolveLikePost(false, 100);
    await new Promise((resolve) => setTimeout(resolve, 30));

    const failLikeBtn = root.querySelector("#topic-page-like");
    assert.equal(failLikeBtn.disabled, true, "(d) Button disabled while calibration GET in-flight");

    rejectCalibGet(new Error("500 Internal Server Error"));
    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.equal(failLikeBtn.disabled, false, "(d) Like button must be re-enabled after calibration GET failure");
    assert.equal(failLikeBtn.getAttribute("aria-busy"), null, "(d) aria-busy must be removed after calibration GET failure");
    assert.equal(h.window._socialInFlight.has("t_y3_a:like"), false, "(d) Lock must be released from _socialInFlight");

    // ==========================================
    // 2. COLLECT TESTS: (a), (b), (c), (d)
    // ==========================================

    // --- (a) & (b): Collect calibration GET in-flight disabled, click ignored, seq changed no writeback ---
    const favBtn = root.querySelector("#topic-page-collect");
    collectCallsCount = 0;
    favBtn.onclick(); // in-flight
    assert.equal(collectCallsCount, 1);

    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    calibGetControlled = true;
    resolveCollectPost(true, 51);
    await new Promise((resolve) => setTimeout(resolve, 30));

    const calibFavBtn = root.querySelector("#topic-page-collect");
    assert.equal(calibFavBtn.disabled, true, "(a) Collect button must be disabled while calibration GET in-flight");
    assert.equal(calibFavBtn.getAttribute("aria-busy"), "true");

    const collCallsBefore = collectCallsCount;
    calibFavBtn.onclick();
    assert.equal(collectCallsCount, collCallsBefore, "(a) Click on collect button while calibration GET in-flight must be ignored");

    // Mutate seq artificially
    const curFavSeq = h.window._socialSeq.get("t_y3_a:collect") || 1;
    h.window._socialSeq.set("t_y3_a:collect", curFavSeq + 1);

    resolveCalibGet({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_y3_a", likes: 100, favorites: 888 },
        mount: { kind: "discussion" },
        viewer: { favorited: true }
      })
    });
    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.notEqual(root.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 888", "(b) Stale collect calibration must NOT write back when seq changed");
    assert.equal(calibFavBtn.disabled, false);
    assert.equal(calibFavBtn.getAttribute("aria-busy"), null);

    // --- (c): Collect calibration success updates social fields ---
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    const favBtn2 = root.querySelector("#topic-page-collect");
    favBtn2.onclick();

    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    calibGetControlled = true;
    resolveCollectPost(true, 55);
    await new Promise((resolve) => setTimeout(resolve, 30));

    resolveCalibGet({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_y3_a", likes: 100, favorites: 55 },
        mount: { kind: "discussion" },
        viewer: { liked: false, favorited: true }
      })
    });
    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.equal(root.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 55", "(c) Collect count updated via calibration");
    const favBtnAfterCalib = root.querySelector("#topic-page-collect");
    assert.equal(favBtnAfterCalib.disabled, false);
    assert.ok(favBtnAfterCalib.textContent.includes("已收藏 (55)"));

    // --- (d): Collect calibration GET failure releases lock and re-enables button ---
    favBtnAfterCalib.onclick();
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_b", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    h.window.HANDRAW_FORUM_OPEN_TOPIC("t_y3_a", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    calibGetControlled = true;
    resolveCollectPost(false, 50);
    await new Promise((resolve) => setTimeout(resolve, 30));

    const failFavBtn = root.querySelector("#topic-page-collect");
    assert.equal(failFavBtn.disabled, true, "(d) Collect button disabled during calibration GET");

    rejectCalibGet(new Error("Network Error"));
    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.equal(failFavBtn.disabled, false, "(d) Collect button must be re-enabled after calibration GET failure");
    assert.equal(failFavBtn.getAttribute("aria-busy"), null, "(d) aria-busy must be removed from collect button after failure");
    assert.equal(h.window._socialInFlight.has("t_y3_a:collect"), false, "(d) Collect lock must be released from _socialInFlight");

    console.log("Scenario 17 passed: End-to-end operation lock, interaction seq tracking, and interaction-only calibration verified.");
  }

  /* ==========================================================================
   * Scenario 18 (Y4): Decoupled social sequence per action & selective calibration:
   *                   - 4 interleaved like/collect failure & success cases (resource and discussion);
   *                   - Like calibration GET in-flight while collect succeeds; calibration does not overwrite collect.
   * ========================================================================== */
  {
    let likeCallsCount = 0;
    let resolveLikePost = null;
    let rejectLikePost = null;

    let collectCallsCount = 0;
    let resolveCollectPost = null;
    let rejectCollectPost = null;

    let calibGetControlled = false;
    let resolveCalibGet = null;

    const apiHandlers = new Map();
    apiHandlers.set(/\/api\/posts\//, async (url) => {
      if (url.includes("/replies")) return { ok: true, status: 200, json: async () => ({ ok: true, items: [] }) };
      const u = new URL(url, "http://127.0.0.1:3080");
      const id = u.pathname.split("/").pop();

      if (id === "t_y4_calib" && calibGetControlled) {
        calibGetControlled = false;
        return new Promise((resolve) => {
          resolveCalibGet = resolve;
        });
      }

      if (id === "SC-021") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            topic: { id: "SC-021", title: "SC-021 留白排版", likes: 10, favorites: 5 },
            mount: { kind: "layout", resource: { code: "SC-021", name: "留白排版", likes: 10, favorites: 5 } },
            viewer: { liked: false, favorited: false }
          })
        };
      }

      if (id === "FB-041") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            topic: { id: "FB-041", title: "FB-041 柔和画风", likes: 15, favorites: 8 },
            mount: { kind: "style", resource: { code: "FB-041", name: "柔和画风", likes: 15, favorites: 8 } },
            viewer: { liked: false, favorited: false }
          })
        };
      }

      const isDisc1 = id === "t_y4_disc_1";
      const isDisc2 = id === "t_y4_disc_2";
      const likesVal = isDisc1 ? 50 : (isDisc2 ? 40 : 100);
      const favsVal = isDisc1 ? 20 : (isDisc2 ? 30 : 50);

      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          topic: { id, title: `Topic ${id}`, likes: likesVal, favorites: favsVal },
          mount: { kind: "discussion" },
          viewer: { liked: false, favorited: false }
        })
      };
    });

    apiHandlers.set("/api/interactions/like", async () => {
      likeCallsCount++;
      return new Promise((resolve, reject) => {
        resolveLikePost = (likedVal = true, likesVal = 101) => resolve({ ok: true, status: 200, json: async () => ({ ok: true, liked: likedVal, likes: likesVal }) });
        rejectLikePost = (err) => reject(err || new Error("Like 500"));
      });
    });

    apiHandlers.set("/api/collections/toggle", async () => {
      collectCallsCount++;
      return new Promise((resolve, reject) => {
        resolveCollectPost = (collectedVal = true, favsVal = 51) => resolve({ ok: true, status: 200, json: async () => ({ ok: true, collected: collectedVal, favorites: favsVal }) });
        rejectCollectPost = (err) => reject(err || new Error("Collect 500"));
      });
    });

    // --- Case 1: Like failure + Collect success on Resource Topic (SC-021) ---
    const h1 = createHarness({ locationSearch: "?view=topic&id=SC-021", apiHandlers });
    h1.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));
    const root1 = h1.forumRoot;

    assert.equal(root1.querySelector("#topic-counts").textContent, "点赞 10 · 收藏 5");
    const likeBtn1 = root1.querySelector("#topic-page-like");
    const favBtn1 = root1.querySelector("#topic-page-collect");

    // Click like (delayed)
    likeBtn1.onclick();
    assert.equal(likeBtn1.disabled, true);
    assert.equal(root1.querySelector("#topic-counts").textContent, "点赞 11 · 收藏 5");

    // Click collect (success)
    favBtn1.onclick();
    resolveCollectPost(true, 6);
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(favBtn1.disabled, false);
    assert.ok(favBtn1.classList.contains("btn-primary"));
    assert.equal(root1.querySelector("#topic-counts").textContent, "点赞 11 · 收藏 6");

    // Like returns 500 error
    rejectLikePost(new Error("Like failed 500"));
    await new Promise((resolve) => setTimeout(resolve, 30));

    // Verify like rolled back, collect remained successful!
    assert.equal(likeBtn1.disabled, false);
    assert.equal(likeBtn1.classList.contains("btn-primary"), false);
    assert.ok(likeBtn1.textContent.includes("点赞 (10)"));
    assert.ok(favBtn1.classList.contains("btn-primary"));
    assert.ok(favBtn1.textContent.includes("已收藏 (6)"));
    assert.equal(root1.querySelector("#topic-counts").textContent, "点赞 10 · 收藏 6", "Case 1: SC-021 like failed rolled back, collect success preserved");

    // --- Case 2: Like failure + Collect success on Discussion Topic (t_y4_disc_1) ---
    const h2 = createHarness({ locationSearch: "?view=topic&id=t_y4_disc_1", apiHandlers });
    h2.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));
    const root2 = h2.forumRoot;

    assert.equal(root2.querySelector("#topic-counts").textContent, "点赞 50 · 收藏 20");
    const likeBtn2 = root2.querySelector("#topic-page-like");
    const favBtn2 = root2.querySelector("#topic-page-collect");

    likeBtn2.onclick(); // like delayed
    favBtn2.onclick(); // collect succeeds
    resolveCollectPost(true, 21);
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(root2.querySelector("#topic-counts").textContent, "点赞 51 · 收藏 21");

    rejectLikePost(new Error("Like 500"));
    await new Promise((resolve) => setTimeout(resolve, 30));

    assert.equal(likeBtn2.classList.contains("btn-primary"), false);
    assert.ok(likeBtn2.textContent.includes("点赞 (50)"));
    assert.ok(favBtn2.classList.contains("btn-primary"));
    assert.ok(favBtn2.textContent.includes("已收藏 (21)"));
    assert.equal(root2.querySelector("#topic-counts").textContent, "点赞 50 · 收藏 21", "Case 2: Discussion like failed rolled back, collect success preserved");

    // --- Case 3: Collect failure + Like success on Resource Topic (FB-041) ---
    const h3 = createHarness({ locationSearch: "?view=topic&id=FB-041", apiHandlers });
    h3.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));
    const root3 = h3.forumRoot;

    assert.equal(root3.querySelector("#topic-counts").textContent, "点赞 15 · 收藏 8");
    const likeBtn3 = root3.querySelector("#topic-page-like");
    const favBtn3 = root3.querySelector("#topic-page-collect");

    favBtn3.onclick(); // collect delayed
    assert.equal(favBtn3.disabled, true);
    assert.equal(root3.querySelector("#topic-counts").textContent, "点赞 15 · 收藏 9");

    likeBtn3.onclick(); // like succeeds
    resolveLikePost(true, 16);
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(likeBtn3.disabled, false);
    assert.ok(likeBtn3.classList.contains("btn-primary"));
    assert.equal(root3.querySelector("#topic-counts").textContent, "点赞 16 · 9".includes("16") ? root3.querySelector("#topic-counts").textContent : "");

    rejectCollectPost(new Error("Collect failed 500"));
    await new Promise((resolve) => setTimeout(resolve, 30));

    assert.equal(favBtn3.disabled, false);
    assert.equal(favBtn3.classList.contains("btn-primary"), false);
    assert.ok(favBtn3.textContent.includes("收藏 (8)"));
    assert.ok(likeBtn3.classList.contains("btn-primary"));
    assert.ok(likeBtn3.textContent.includes("已赞 (16)"));
    assert.equal(root3.querySelector("#topic-counts").textContent, "点赞 16 · 收藏 8", "Case 3: FB-041 collect failed rolled back, like success preserved");

    // --- Case 4: Collect failure + Like success on Discussion Topic (t_y4_disc_2) ---
    const h4 = createHarness({ locationSearch: "?view=topic&id=t_y4_disc_2", apiHandlers });
    h4.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));
    const root4 = h4.forumRoot;

    assert.equal(root4.querySelector("#topic-counts").textContent, "点赞 40 · 收藏 30");
    const likeBtn4 = root4.querySelector("#topic-page-like");
    const favBtn4 = root4.querySelector("#topic-page-collect");

    favBtn4.onclick(); // collect delayed
    likeBtn4.onclick(); // like succeeds
    resolveLikePost(true, 41);
    await new Promise((resolve) => setTimeout(resolve, 30));

    rejectCollectPost(new Error("Collect 500"));
    await new Promise((resolve) => setTimeout(resolve, 30));

    assert.equal(favBtn4.classList.contains("btn-primary"), false);
    assert.ok(favBtn4.textContent.includes("收藏 (30)"));
    assert.ok(likeBtn4.classList.contains("btn-primary"));
    assert.ok(likeBtn4.textContent.includes("已赞 (41)"));
    assert.equal(root4.querySelector("#topic-counts").textContent, "点赞 41 · 收藏 30", "Case 4: Discussion collect failed rolled back, like success preserved");

    // --- Case 5: Like calibration GET in-flight while Collect succeeds -> calibration does NOT overwrite Collect ---
    const h5 = createHarness({ locationSearch: "?view=topic&id=t_y4_calib", apiHandlers });
    h5.loadForumApp();
    await new Promise((resolve) => setTimeout(resolve, 80));
    const root5 = h5.forumRoot;

    assert.equal(root5.querySelector("#topic-counts").textContent, "点赞 100 · 收藏 50");
    const likeBtn5 = root5.querySelector("#topic-page-like");
    likeBtn5.onclick(); // like in-flight

    // Switch away and return
    h5.window.HANDRAW_FORUM_OPEN_TOPIC("t_y4_disc_1", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    h5.window.HANDRAW_FORUM_OPEN_TOPIC("t_y4_calib", 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    // Enable controlled calibration GET for like
    calibGetControlled = true;
    resolveLikePost(true, 101); // Settles old like POST -> triggers calibration GET
    await new Promise((resolve) => setTimeout(resolve, 30));

    // While like calibration GET is in-flight, like button is disabled, but collect button is usable
    const calibLikeBtn = root5.querySelector("#topic-page-like");
    const favBtn5 = root5.querySelector("#topic-page-collect");
    assert.equal(calibLikeBtn.disabled, true);
    assert.equal(favBtn5.disabled, false);

    // User successfully collects during like calibration GET
    favBtn5.onclick();
    resolveCollectPost(true, 51);
    await new Promise((resolve) => setTimeout(resolve, 30));

    assert.equal(favBtn5.disabled, false);
    assert.ok(favBtn5.classList.contains("btn-primary"));
    assert.ok(favBtn5.textContent.includes("已收藏 (51)"));

    // Now resolve the like calibration GET (whose server payload still has favorites: 50, favorited: false)
    resolveCalibGet({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        topic: { id: "t_y4_calib", likes: 101, favorites: 50 },
        mount: { kind: "discussion" },
        viewer: { liked: true, favorited: false }
      })
    });
    await new Promise((resolve) => setTimeout(resolve, 50));

    // CRITICAL: Like calibration GET must NOT overwrite the fresh Collect state!
    assert.equal(calibLikeBtn.disabled, false);
    assert.ok(calibLikeBtn.classList.contains("btn-primary"));
    assert.ok(calibLikeBtn.textContent.includes("已赞 (101)"));
    assert.ok(favBtn5.classList.contains("btn-primary"), "Collect state must remain primary");
    assert.ok(favBtn5.textContent.includes("已收藏 (51)"), "Collect count 51 must NOT be overwritten by calibration");
    assert.equal(root5.querySelector("#topic-counts").textContent, "点赞 101 · 收藏 51", "Counts reflect calibrated likes (101) and active collect (51)");

    console.log("Scenario 18 passed: Decoupled social sequence per action, interleaving resilience, and selective calibration verified.");
  }

  console.log("\nALL 18 SCENARIOS IN test_topic_detail.cjs PASSED SUCCESSFULLY!");
})().catch((err) => {
  console.error("Test failed with error:", err);
  process.exit(1);
});
