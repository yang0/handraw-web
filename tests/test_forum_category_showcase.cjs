"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

// Mock DOM elements for testing forum-app category routing & sidebar highlighting
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
    this.id = attrs.id || "";
    this._value = attrs.value !== undefined ? String(attrs.value) : "";
  }

  get value() { return this._value; }
  set value(v) { this._value = String(v); }

  get textContent() {
    return this.children
      .map((c) => (typeof c === "string" ? c : (c.textContent || "")))
      .join("");
  }
  set textContent(v) {
    this.children = [String(v)];
  }

  get innerHTML() {
    return this.children.map((c) => (typeof c === "string" ? c : c.outerHTML)).join("");
  }

  set innerHTML(html) {
    this.children = [];
    parseHtmlToChildren(html, this);
  }

  get outerHTML() {
    const attrStr = Object.entries(this.attrs).map(([k, v]) => ` ${k}="${v}"`).join("");
    return `<${this.tagName.toLowerCase()}${attrStr}>${this.innerHTML}</${this.tagName.toLowerCase()}>`;
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

  appendChild(child) {
    if (typeof child !== "string") child.parent = this;
    this.children.push(child);
    return child;
  }

  addEventListener(event, fn) {
    this[`on${event}`] = fn;
  }

  click() {
    if (typeof this.onclick === "function") {
      this.onclick({ target: this, stopPropagation() {} });
    }
  }

  closest(sel) {
    let curr = this;
    while (curr) {
      if (typeof curr !== "string" && matchesSelector(curr, sel)) return curr;
      curr = curr.parent;
    }
    return null;
  }

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
  return el.tagName.toLowerCase() === sel.toLowerCase();
}

function querySelector(root, sel) {
  const all = querySelectorAll(root, sel);
  return all.length ? all[0] : null;
}

function querySelectorAll(root, sel) {
  const parts = sel.trim().split(/\s+/);
  if (parts.length > 1) {
    let currentNodes = [root];
    for (const part of parts) {
      const nextNodes = [];
      for (const node of currentNodes) {
        nextNodes.push(...querySelectorAll(node, part));
      }
      currentNodes = nextNodes;
    }
    return currentNodes;
  }
  const results = [];
  function walk(node) {
    if (typeof node === "string") return;
    for (const child of node.children) {
      if (typeof child !== "string" && matchesSelector(child, sel)) {
        results.push(child);
      }
      walk(child);
    }
  }
  walk(root);
  return results;
}

function createForumEnv(search = "") {
  const root = new MockElement("DIV", { id: "forum-app-root" });
  let currentSearch = search;
  const locationObj = {
    search: currentSearch,
    pathname: "/forum/",
    hostname: "localhost",
    host: "localhost:3082",
    port: "3082",
    protocol: "http:",
    get href() {
      return `http://localhost:3082/forum/${this.search}`;
    },
    set href(val) {
      try {
        const u = new URL(val, "http://localhost:3082/forum/");
        this.search = u.search;
        this.pathname = u.pathname;
      } catch (_) {}
    },
    replace(val) {
      this.href = val;
    }
  };

  const windowObj = {
    location: locationObj,
    addEventListener() {},
    scrollTo() {},
    history: {
      pushState(_st, _title, url) {
        if (url) locationObj.href = url;
      },
      replaceState(_st, _title, url) {
        if (url) locationObj.href = url;
      }
    },
    localStorage: {
      getItem() { return null; },
      setItem() {},
      removeItem() {}
    }
  };

  const documentObj = {
    getElementById(id) {
      if (id === "forum-app-root") return root;
      return null;
    },
    querySelector(sel) { return root.querySelector(sel); },
    querySelectorAll(sel) { return root.querySelectorAll(sel); },
    addEventListener() {},
    title: ""
  };

  const context = {
    window: windowObj,
    document: documentObj,
    URL,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    console,
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
  };
  vm.createContext(context);

  // Load shared.js
  vm.runInContext(fs.readFileSync("demo/assets/shared.js", "utf8"), context);
  const S = context.window.HANDRAW_SHARED;
  const App = context.window.HandrawApp || S.App || { state: {} };
  App.state = {
    serverBacked: true,
    loggedIn: false,
    user: null,
    topics: [
      { id: "top_1", title: "测试作品贴", category: "showcase", author: "alice", authorName: "Alice", images: [] },
      { id: "top_2", title: "调优帖", category: "tuning", author: "bob", authorName: "Bob", images: [] }
    ],
    forumBoards: [
      { key: "all", label: "📋 全区总版主", shortLabel: "全区总版" },
      { key: "showcase", label: "🎨 晒作品", shortLabel: "晒作品版" },
      { key: "tuning", label: "🎯 作品求调优 / 悬赏", shortLabel: "调优悬赏版" },
      { key: "experience", label: "📘 实战经验与变现", shortLabel: "实战变现版" },
      { key: "assets", label: "🎨 画风与图型专区", shortLabel: "画风图型版" },
      { key: "tools", label: "🛠️ 工具流与问答", shortLabel: "工具问答版" }
    ]
  };
  context.window.HandrawApp = App;
  S.App = App;
  S.initApp = (_name, cb) => {
    if (cb) cb();
    return Promise.resolve();
  };

  return { context, window: windowObj, root, shared: S };
}

(async function testForumCategoryShowcase() {
  console.log("Running Issue #17 Tests: Forum showcase category deep-link & highlighting...");

  // Test 1: ?category=showcase URL selects showcase and highlights it in sidebar
  {
    const env = createForumEnv("?category=showcase");
    vm.runInContext(fs.readFileSync("demo/assets/forum-app.js", "utf8"), env.context);

    // Verify DOM rendering: the category button with data-fcat="showcase" has class "is-active"
    const showcaseBtn = env.root.querySelector('[data-fcat="showcase"]');
    assert.ok(showcaseBtn, "Sidebar must render a button for data-fcat='showcase'");
    assert.ok(showcaseBtn.classList.contains("is-active"), "Showcase category button must have 'is-active' class");
    assert.ok(showcaseBtn.textContent.includes("晒作品"), "Showcase category button text must include '晒作品'");

    // Verify other category buttons are not active
    const allBtn = env.root.querySelector('[data-fcat="all"]');
    assert.ok(allBtn && !allBtn.classList.contains("is-active"), "'all' category button must not have 'is-active'");
    const tuningBtn = env.root.querySelector('[data-fcat="tuning"]');
    assert.ok(tuningBtn && !tuningBtn.classList.contains("is-active"), "'tuning' category button must not have 'is-active'");

    console.log("✓ Test 1 Passed: ?category=showcase marks '晒作品' as is-active and others inactive");
  }

  // Test 2: Fallback when boot is not yet loaded (App.state.forumBoards empty)
  {
    const env = createForumEnv("?category=showcase");
    env.shared.App.state.forumBoards = null; // simulate boot not ready
    vm.runInContext(fs.readFileSync("demo/assets/forum-app.js", "utf8"), env.context);

    const showcaseBtn = env.root.querySelector('[data-fcat="showcase"]');
    assert.ok(showcaseBtn, "Sidebar must render showcase button even when boot forumBoards is null");
    assert.ok(showcaseBtn.classList.contains("is-active"), "Showcase must still be selected with fallback whitelist");
    const allBtn = env.root.querySelector('[data-fcat="all"]');
    assert.ok(!allBtn.classList.contains("is-active"), "'all' must not be active when showcase is selected");

    console.log("✓ Test 2 Passed: Fallback whitelist includes 'showcase' before boot arrives");
  }

  // Test 3: Existing categories still route correctly
  {
    for (const cat of ["all", "tuning", "experience", "assets", "tools"]) {
      const env = createForumEnv(`?category=${cat}`);
      vm.runInContext(fs.readFileSync("demo/assets/forum-app.js", "utf8"), env.context);
      const catBtn = env.root.querySelector(`[data-fcat="${cat}"]`);
      assert.ok(catBtn, `Button for ${cat} must exist`);
      assert.ok(catBtn.classList.contains("is-active"), `Button for ${cat} must have 'is-active' class`);
    }
    console.log("✓ Test 3 Passed: Standard categories (all, tuning, experience, assets, tools) still route correctly");
  }

  // Test 4: Unknown category does not change default "all"
  {
    const env = createForumEnv("?category=invalid_board");
    vm.runInContext(fs.readFileSync("demo/assets/forum-app.js", "utf8"), env.context);
    const allBtn = env.root.querySelector('[data-fcat="all"]');
    assert.ok(allBtn && allBtn.classList.contains("is-active"), "Invalid category must fall back to 'all' as active");
    const showcaseBtn = env.root.querySelector('[data-fcat="showcase"]');
    assert.ok(showcaseBtn && !showcaseBtn.classList.contains("is-active"), "Showcase must not be active for invalid category");
    console.log("✓ Test 4 Passed: Invalid category safely defaults to 'all'");
  }

  // Test 5: Clicking showcase button switches category and updates DOM
  {
    const env = createForumEnv("");
    vm.runInContext(fs.readFileSync("demo/assets/forum-app.js", "utf8"), env.context);
    const allBtn = env.root.querySelector('[data-fcat="all"]');
    assert.ok(allBtn && allBtn.classList.contains("is-active"), "Default category is 'all'");

    const showcaseBtn = env.root.querySelector('[data-fcat="showcase"]');
    assert.ok(showcaseBtn, "Showcase button exists in default view");
    showcaseBtn.click();

    // After clicking showcase, it becomes active
    const activeShowcaseBtn = env.root.querySelector('[data-fcat="showcase"]');
    assert.ok(activeShowcaseBtn && activeShowcaseBtn.classList.contains("is-active"), "Clicking showcase marks it as active");
    const inactiveAllBtn = env.root.querySelector('[data-fcat="all"]');
    assert.ok(inactiveAllBtn && !inactiveAllBtn.classList.contains("is-active"), "'all' button loses active class");

    console.log("✓ Test 5 Passed: Clicking showcase category updates DOM active button");
  }

  // Test 6: Compose page board pills must NOT contain "晒作品"
  {
    const env = createForumEnv("");
    vm.runInContext(fs.readFileSync("demo/assets/forum-app.js", "utf8"), env.context);
    const newTextBtn = env.root.querySelector("#forum-btn-new-text");
    assert.ok(newTextBtn, "New topic button must exist");
    newTextBtn.click();

    const composePills = env.root.querySelectorAll(".hw-compose-board-pill");
    assert.ok(composePills.length > 0, "Compose board pills must be rendered");
    const showcasePill = env.root.querySelector('#compose-board-pills [data-compose-cat="showcase"]');
    assert.equal(showcasePill, null, "Compose board pills must NOT have showcase option");
    for (const pill of composePills) {
      assert.ok(!pill.textContent.includes("晒作品"), `Compose pill "${pill.textContent}" must not contain '晒作品'`);
    }
    console.log("✓ Test 6 Passed: Compose page board pills do NOT contain '晒作品'");
  }

  // Test 7: Moderator move dropdown must NOT contain "移至：晒作品"
  {
    const env = createForumEnv("?view=topic&id=top_1");
    env.shared.App.state.loggedIn = true;
    env.shared.App.state.user = { role: "admin", username: "admin_user" };
    env.shared.apiJson = async (path) => {
      if (path.includes("/replies")) {
        return { ok: true, items: [], nextCursor: null };
      }
      return {
        ok: true,
        topic: {
          id: "top_1",
          title: "测试帖子",
          category: "tuning",
          author: "user_a",
          authorName: "用户A"
        },
        mount: { kind: "none" },
        viewer: { liked: false, favorited: false }
      };
    };

    vm.runInContext(fs.readFileSync("demo/assets/forum-app.js", "utf8"), env.context);
    // Wait for apiJson resolution
    await new Promise((resolve) => setTimeout(resolve, 30));

    const moveSelect = env.root.querySelector("#topic-mod-move-select");
    assert.ok(moveSelect, "Admin viewing topic must see move select dropdown (#topic-mod-move-select)");
    const showcaseOpt = env.root.querySelector('#topic-mod-move-select option[value="showcase"]');
    assert.equal(showcaseOpt, null, "Move dropdown must NOT contain option with value='showcase'");
    const allOptions = env.root.querySelectorAll("#topic-mod-move-select option");
    assert.ok(allOptions.length > 0, "Move dropdown must have options for valid boards");
    for (const opt of allOptions) {
      assert.ok(!opt.textContent.includes("晒作品"), `Option "${opt.textContent}" must not contain '晒作品'`);
    }
    console.log("✓ Test 7 Passed: Moderator move dropdown does NOT contain '移至：晒作品'");
  }

  // Source-level guard: BOARD_DEFS must not contain showcase
  {
    const forumAppSrc = fs.readFileSync("demo/assets/forum-app.js", "utf8");
    const boardDefsMatch = forumAppSrc.match(/const BOARD_DEFS = \[([\s\S]*?)\];/);
    assert.ok(boardDefsMatch, "BOARD_DEFS definition must exist in forum-app.js");
    assert.ok(!boardDefsMatch[1].includes('"showcase"') && !boardDefsMatch[1].includes("'showcase'"), "BOARD_DEFS array in forum-app.js must not contain 'showcase'");
    console.log("✓ Source Guard Passed: BOARD_DEFS array in forum-app.js does not contain 'showcase'");
  }

  console.log("\n==========================================");
  console.log("All Issue #17 Forum Category Tests PASSED!");
  console.log("==========================================");
})();
