"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

console.log("Starting Profile Tabs Split, Rename & Collections Migration Tests (Issue #45)...");

const mainAppCode = fs.readFileSync("demo/assets/main-app.js", "utf8");
const sharedCode = fs.readFileSync("demo/assets/shared.js", "utf8");
const themeCssCode = fs.readFileSync("demo/assets/theme.css", "utf8");

// ============================================================================
// Test 1: renderCollectionsCenter must NOT exist anywhere in main-app.js
// ============================================================================
console.log("\n--- Test 1: renderCollectionsCenter已不存在 ---");
assert.ok(
  !mainAppCode.includes("renderCollectionsCenter"),
  "renderCollectionsCenter function and calls must be completely removed from main-app.js"
);
assert.ok(
  !mainAppCode.includes('App.view === "collections" renderCollectionsCenter'),
  "Old view===collections routing to renderCollectionsCenter must be removed"
);
console.log("✓ Test 1 Passed: renderCollectionsCenter completely removed.");

// ============================================================================
// Setup mock DOM environment for execution tests
// ============================================================================
function createTestEnv(initialUrl = "http://localhost:3080/?view=profile&user=creator_leo", loggedInUser = "creator_leo") {
  let currentUrl = initialUrl;
  const historyEntries = [];

  const locationMock = {
    get pathname() { return new URL(currentUrl).pathname; },
    get search() { return new URL(currentUrl).search; },
    set search(v) {
      const u = new URL(currentUrl);
      u.search = v;
      currentUrl = u.toString();
    },
    get href() { return currentUrl; },
    set href(v) { currentUrl = v; }
  };

  const historyMock = {
    replaceState(state, title, url) {
      currentUrl = new URL(url, "http://localhost:3080").toString();
      historyEntries.push({ type: "replace", state, title, url: currentUrl });
    },
    pushState(state, title, url) {
      currentUrl = new URL(url, "http://localhost:3080").toString();
      historyEntries.push({ type: "push", state, title, url: currentUrl });
    },
    get length() { return historyEntries.length + 1; },
    back() {}
  };

  const sampleStyles = [
    { id: "FA-001", code: "FA-001", name: "松散黑线", kind: "style", image: "/s1.webp", author: "creator_leo", status: "published" },
    { id: "FA-002", code: "FA-002", name: "炭笔阴影", kind: "style", image: "/s2.webp", author: "creator_leo", status: "published" }
  ];

  const sampleLayouts = [
    { id: "SC-001", code: "SC-001", name: "留白卡片", kind: "layout", image: "/l1.webp", author: "creator_leo", status: "published" }
  ];

  const sampleWorks = [
    { id: "w_01", title: "春日速写", images: ["/w1.webp"], author: "creator_leo", authorName: "雷奥", favorites: 5, cheers: 10 }
  ];

  const sampleTopics = [
    { id: "t_01", title: "手绘黑线线条实战", categoryLabel: "技巧教程", author: "creator_leo", authorName: "雷奥", replies: [] }
  ];

  const resourceMap = new Map();
  sampleStyles.forEach(s => resourceMap.set(s.id, s));
  sampleLayouts.forEach(l => resourceMap.set(l.id, l));

  const stateMock = {
    serverBacked: true,
    loggedIn: Boolean(loggedInUser),
    user: loggedInUser ? { username: loggedInUser, name: "雷奥", role: "creator" } : null,
    credits: 100,
    collections: {
      styles: ["FA-001"],
      layouts: ["SC-001"],
      works: ["w_01"],
      topics: ["t_01"]
    },
    works: [...sampleWorks],
    topics: [...sampleTopics]
  };

  const toggledCollections = [];
  const sharedMock = {
    App: {
      channel: "main",
      view: "styles",
      state: stateMock,
      styles: [...sampleStyles],
      layouts: [...sampleLayouts],
      resourceMap,
      listeners: []
    },
    esc: (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    toast: () => {},
    channelUrl: (channel, params) => `/${channel}?${new URLSearchParams(params).toString()}`,
    saveState: () => {
      sharedMock.App.listeners.forEach(fn => fn());
    },
    closeModal: () => {},
    openLoginModal: () => {},
    isCollected: (bucket, id) => (stateMock.collections[bucket] || []).includes(id),
    initApp: async (channel, onChange) => {
      if (onChange) sharedMock.App.listeners.push(onChange);
    },
    toggleCollect: (bucket, id, title) => {
      toggledCollections.push({ bucket, id, title });
      const arr = stateMock.collections[bucket] || [];
      const idx = arr.indexOf(id);
      if (idx >= 0) arr.splice(idx, 1);
      else arr.unshift(id);
      return true;
    },
    getCreatorProfile: (username) => {
      return {
        username,
        authorName: username === "creator_leo" ? "雷奥" : username,
        avatarChar: "雷",
        honor: { sealClass: "seal-master", badge: "工坊导师", boostText: "全站权重 1.5x", desc: "资深创作者" },
        bio: "专注复古黑线与版式研究",
        styles: username === "creator_leo" ? [...sampleStyles] : [],
        layouts: username === "creator_leo" ? [...sampleLayouts] : [],
        works: username === "creator_leo" ? [...sampleWorks] : [],
        topics: username === "creator_leo" ? [...sampleTopics] : [],
        totalPublished: 3,
        totalCheers: 12,
        totalForks: 4,
        achievements: ["原创画风破万"]
      };
    },
    getUserModeratorBadges: () => [],
    getAssetWorkCount: () => 3,
    getAssetComments: () => [],
    getLikeCount: () => 5,
    renderMasonry: (cards) => `<div class="hw-masonry-grid">${cards.join("")}</div>`,
    renderAccountSettingsFormHtml: () => `<div id="account-settings-form">账号设置表单</div>`,
    bindAccountSettingsForm: () => {},
    mountAuthPassStage: () => {},
    CREATOR_HONOR_TIERS: [
      { key: "tier1", badge: "新晋画手", minCount: 1, boostText: "基础权重" },
      { key: "tier2", badge: "工坊导师", minCount: 5, boostText: "全站权重 1.5x" }
    ]
  };

  const docElements = new Map();
  function makeElement(tag, attrs = {}) {
    return {
      tagName: tag.toUpperCase(),
      attributes: { ...attrs },
      classList: {
        _classes: new Set((attrs.class || "").split(/\s+/).filter(Boolean)),
        add(c) { this._classes.add(c); },
        remove(c) { this._classes.delete(c); },
        contains(c) { return this._classes.has(c); }
      },
      getAttribute(k) { return this.attributes[k] || null; },
      setAttribute(k, v) { this.attributes[k] = String(v); },
      removeAttribute(k) { delete this.attributes[k]; },
      style: {},
      onclick: null,
      addEventListener(type, fn) {
        if (type === "click") this.onclick = fn;
      },
      scrollIntoViewCalls: [],
      scrollIntoView(options) {
        this.scrollIntoViewCalls.push(options);
      }
    };
  }

  const root = {
    _innerHTML: "",
    classList: {
      toggle() {},
      add() {},
      remove() {}
    },
    get innerHTML() { return this._innerHTML; },
    set innerHTML(html) {
      this._innerHTML = String(html);
      this._elementCache.clear();
    },
    querySelector(sel) {
      if (sel === ".hw-profile-tabs .hw-pill.is-active") {
        if (this._innerHTML.includes('class="hw-pill is-active"') || this._innerHTML.includes("class=\"hw-pill is-active\"")) {
          const el = makeElement("button", { class: "hw-pill is-active" });
          return el;
        }
        return null;
      }
      if (sel === "#prof-col-batch-unfav-btn") {
        if (this._innerHTML.includes('id="prof-col-batch-unfav-btn"')) {
          return makeElement("button", { id: "prof-col-batch-unfav-btn" });
        }
        return null;
      }
      if (sel === "#prof-back-btn") return makeElement("button", { id: "prof-back-btn" });
      if (sel === "#prof-rankings-btn") return makeElement("button", { id: "prof-rankings-btn" });
      if (sel === "#prof-go-account-btn") return makeElement("button", { id: "prof-go-account-btn" });
      if (sel === "#auth-page-back-btn") return makeElement("button", { id: "auth-page-back-btn" });
      if (sel === "#standalone-auth-mount") return makeElement("div", { id: "standalone-auth-mount" });
      return null;
    },
    _elementCache: new Map(),
    querySelectorAll(sel) {
      if (!this._elementCache.has(sel)) {
        if (sel === "[data-ptab]") {
          const matches = [...this._innerHTML.matchAll(/data-ptab="([^"]+)"/g)];
          this._elementCache.set(sel, matches.map(m => makeElement("button", { "data-ptab": m[1] })));
        } else if (sel === "[data-prof-ftab]") {
          const matches = [...this._innerHTML.matchAll(/data-prof-ftab="([^"]+)"/g)];
          this._elementCache.set(sel, matches.map(m => makeElement("button", { "data-prof-ftab": m[1] })));
        } else if (sel === "[data-unfav]") {
          const matches = [...this._innerHTML.matchAll(/data-unfav="([^"]+)"/g)];
          this._elementCache.set(sel, matches.map(m => makeElement("button", { "data-unfav": m[1] })));
        } else if (sel === "[data-prof-asset]") {
          const matches = [...this._innerHTML.matchAll(/data-prof-asset="([^"]+)"/g)];
          this._elementCache.set(sel, matches.map(m => makeElement("article", { "data-prof-asset": m[1] })));
        } else {
          this._elementCache.set(sel, []);
        }
      }
      return this._elementCache.get(sel);
    }
  };

  const windowMock = {
    location: locationMock,
    history: historyMock,
    matchMedia: () => ({ matches: false }),
    scrollTo: () => {},
    confirm: () => true,
    addEventListener: () => {},
    HANDRAW_SHARED: sharedMock
  };

  const docMock = {
    getElementById: (id) => {
      if (id === "main-app-root") return root;
      return null;
    },
    addEventListener: () => {},
    title: ""
  };

  const context = {
    window: windowMock,
    document: docMock,
    location: locationMock,
    history: historyMock,
    URL,
    URLSearchParams,
    console
  };

  vm.createContext(context);
  vm.runInContext(mainAppCode, context);

  return { context, root, sharedMock, locationMock, historyMock, toggledCollections };
}

// ============================================================================
// Test 2: 公开主页保留三大 Tab，旧资源分类通过筛选兼容
// ============================================================================
console.log("\n--- Test 2: 个人主页公开栏目收敛与旧链接兼容 ---");
{
  const env = createTestEnv("http://localhost:3080/?view=profile&user=creator_leo&ptab=styles", "creator_leo");
  const { context, root } = env;
  context.window.HANDRAW_MAIN_OPEN_PROFILE("creator_leo", "styles");
  assert.ok(root.innerHTML.includes('data-ptab="works"'));
  assert.ok(root.innerHTML.includes('data-ptab="resources"'));
  assert.ok(root.innerHTML.includes('data-ptab="topics"'));
  for (const oldTab of ["generations", "styles", "layouts", "articles", "collections"]) {
    assert.ok(!root.innerHTML.includes(`data-ptab="${oldTab}"`), `Obsolete public tab ${oldTab} remains`);
  }
  assert.match(root.innerHTML, /data-ptab="resources"[^>]*>🎨 创作资源 \(3\)/);
  assert.match(root.innerHTML, /data-ptab="topics"[^>]*>💬 社区动态 \(1\)/);
  assert.ok(!root.innerHTML.includes('id="prof-go-studio-btn"'), "Redundant studio shortcut removed");
  assert.ok(!root.innerHTML.includes('id="prof-go-compose-btn"'), "Forum compose shortcut removed");
  assert.ok(!root.innerHTML.includes('id="prof-back-btn"'), "Redundant profile breadcrumb removed");
  assert.ok(root.innerHTML.includes('id="prof-go-collections-btn"'), "Collection shortcut must be separate from public tabs");
  assert.ok(root.innerHTML.includes('data-prof-resource-filter="all"'));
  assert.ok(root.innerHTML.includes('data-prof-resource-filter="styles"'));
  assert.ok(root.innerHTML.includes('data-prof-resource-filter="layouts"'));
  assert.ok(root.innerHTML.includes("FA-001") && root.innerHTML.includes("FA-002"));
  assert.ok(!root.innerHTML.includes("SC-001"), "Legacy styles route must filter resources to styles");
  context.window.HANDRAW_MAIN_OPEN_PROFILE("creator_leo", "layouts");
  assert.ok(root.innerHTML.includes("SC-001"));
  assert.ok(!root.innerHTML.includes("FA-001"));
  context.window.HANDRAW_MAIN_OPEN_PROFILE("creator_leo", "resources");
  assert.ok(root.innerHTML.includes("FA-001") && root.innerHTML.includes("SC-001"), "All resources should be shown together");
  context.window.HANDRAW_MAIN_OPEN_PROFILE("creator_leo", "assets");
  assert.equal(context.window.location.search, "?view=profile&user=creator_leo&ptab=resources");
  assert.ok(root.innerHTML.includes("FA-001") && !root.innerHTML.includes("SC-001"));
}
console.log("✓ Test 2 Passed: Public tabs consolidated and legacy resource links preserved.");

// ============================================================================
// Test 2b: 历史公开主页链接回退到作品栏目
// ============================================================================
{
  const env = createTestEnv("http://localhost:3080/?view=profile&user=creator_leo&ptab=generations", "creator_leo");
  assert.ok(!env.context.window.location.search.includes("ptab=generations"));
  assert.ok(env.root.innerHTML.includes('data-ptab="works"'));
  assert.ok(!env.root.innerHTML.includes('data-ptab="generations"'));
}
// ============================================================================
// Test 3: ?view=collections 替换跳转
// ============================================================================
console.log("\n--- Test 3: ?view=collections 替换跳转 ---");
{
  // 3a. Logged-in user visiting ?view=collections
  const envLoggedIn = createTestEnv("http://localhost:3080/?view=collections", "creator_leo");
  assert.equal(envLoggedIn.context.window.location.search, "?view=profile&user=creator_leo&ptab=collections", "Logged in user must be replaced to profile collections tab");

  // 3b. Anonymous user visiting ?view=collections
  const envAnon = createTestEnv("http://localhost:3080/?view=collections", null);
  assert.equal(envAnon.context.window.location.search, "?view=auth", "Anonymous user must be replaced to auth page");
}
console.log("✓ Test 3 Passed: ?view=collections redirects properly for both logged-in and anonymous users.");

// ============================================================================
// Test 4: 越权访问他人收藏和账号设置被拒
// ============================================================================
console.log("\n--- Test 4: 越权访问他人收藏夹被拒 ---");
{
  // Current user is creator_leo; visits author_art's profile with ptab=collections
  const env = createTestEnv("http://localhost:3080/?view=profile&user=author_art&ptab=collections", "creator_leo");
  const { root, context } = env;

  // ptab must be rewritten, falling back to works
  assert.ok(!context.window.location.search.includes("ptab=collections"), "URL must NOT retain ptab=collections for another user");
  assert.ok(!root.innerHTML.includes('data-ptab="collections"'), "Other user's profile must NOT have collections tab button");
  assert.ok(!root.innerHTML.includes('data-ptab="account"'), "Other user's profile must NOT have account tab button");

  // Also test ptab=account
  context.window.HANDRAW_MAIN_OPEN_PROFILE("author_art", "account");
  assert.ok(!context.window.location.search.includes("ptab=account"), "URL must NOT retain ptab=account for another user");
  assert.ok(!root.innerHTML.includes('data-ptab="account"'), "Other user's profile must NOT have account tab button");
}
console.log("✓ Test 4 Passed: Unauthorized access to other user's collections/account safely rejected.");

// ============================================================================
// Test 5: 收藏夹功能完整性 (操作反馈、批量清空、各分类切换)
// ============================================================================
console.log("\n--- Test 5: 收藏夹功能迁入主页 (切换、移除、批量清空) ---");
{
  const env = createTestEnv("http://localhost:3080/?view=profile&user=creator_leo&ptab=collections", "creator_leo");
  const { context, root, toggledCollections } = env;

  context.window.HANDRAW_MAIN_OPEN_PROFILE("creator_leo", "collections");
  assert.ok(root.innerHTML.includes("🎨 收藏画风"), "Must render 收藏画风 pill");
  assert.ok(!root.innerHTML.includes('class="hw-pills-row hw-profile-tabs"'), "Collections should show only its own navigation");
  assert.ok(root.innerHTML.includes("📐 收藏图型"), "Must render 收藏图型 pill");
  assert.ok(root.innerHTML.includes("🖼️ 收藏作品"), "Must render 收藏作品 pill");
  assert.ok(root.innerHTML.includes("💬 收藏帖子"), "Must render 收藏帖子 pill");
  assert.ok(root.innerHTML.includes('data-unfav="FA-001"'), "Must render data-unfav for collected style");
  assert.ok(root.innerHTML.includes('id="prof-col-batch-unfav-btn"'), "Must render batch unfav button when items exist");

  // Simulate unfav click
  const unfavBtns = root.querySelectorAll("[data-unfav]");
  assert.ok(unfavBtns.length > 0, "Unfav button must be present on cards");
  unfavBtns[0].onclick({ stopPropagation() {} });
  assert.equal(toggledCollections.length, 1, "Clicking unfav must trigger S.toggleCollect");
  assert.equal(toggledCollections[0].id, "FA-001");
}
console.log("✓ Test 5 Passed: Collections functions (unfav, pills, batch uncollect) intact.");

// ============================================================================
// Test 6: 用户下拉菜单入口改为「收藏夹」并直达本人收藏标签
// ============================================================================
console.log("\n--- Test 6: 用户下拉菜单入口与 shared.js ---");
{
  assert.ok(
    sharedCode.includes('id="hw-dropdown-collections"'),
    "User dropdown must have #hw-dropdown-collections"
  );
  assert.ok(
    sharedCode.includes("收藏夹 ("),
    "Dropdown label must say '收藏夹 (N)' instead of '我的云端收藏'"
  );
  assert.ok(
    !sharedCode.includes("data-main-view=\"collections\""),
    "Dropdown must NOT use legacy data-main-view=collections"
  );
  assert.ok(
    sharedCode.includes('ptab: "collections"'),
    "Dropdown link must navigate directly to profile collections tab"
  );
}
console.log("✓ Test 6 Passed: User dropdown menu updated cleanly.");

// ============================================================================
// Test 7: 移动端单行横向滚动与焦点样式 (theme.css)
// ============================================================================
console.log("\n--- Test 7: 移动端单行横向滚动与焦点样式 ---");
{
  assert.ok(themeCssCode.includes(".hw-profile-tabs"), "theme.css must define .hw-profile-tabs");
  assert.ok(themeCssCode.includes("overflow-x: auto"), "Must have overflow-x: auto");
  assert.ok(themeCssCode.includes("flex-wrap: nowrap"), "Must have flex-wrap: nowrap");
  assert.ok(themeCssCode.includes("white-space: nowrap"), "Must have white-space: nowrap");
  assert.ok(themeCssCode.includes(".hw-pill:focus-visible"), "Must have focus-visible styling for keyboard users");
  assert.ok(mainAppCode.includes("hw-profile-tabs"), "Profile tabs element in main-app.js must have class hw-profile-tabs");
  assert.ok(mainAppCode.includes("scrollIntoView"), "Active tab must auto scroll into view");
}
console.log("✓ Test 7 Passed: Mobile horizontal scroll and focus accessibility verified.");

console.log("\n========================================================");
console.log("ALL PROFILE TABS SPLIT & COLLECTIONS MIGRATION TESTS PASSED!");
console.log("========================================================\n");
